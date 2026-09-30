"""Read-only, calendar-report evidence for the three Study Mode authorities.

This adapter does not select a reporting period.  Each report section selects
its own authoritative start after the complete native entity is validated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
import json
import sqlite3

from METRIC_HUB.read_model import _cosecant_metric
from PERSISTENCE.presentation_aliases import cosecant_founding, secant_founding
from SCIENCE_LAB.secant_adapter import (SecantFact, _canonical, _digest,
                                        _validate_lifecycle, recorder_readiness)
from SECANT.dashboard_evidence import read_corpus, read_display_alias
from SECANT.dashboard_projection import project_secant, project_study
from SECANT.read_model import validate_display_metadata
from time_projection import parse_utc_timestamp


@dataclass(frozen=True)
class StudyFamilyEvidence:
    studies: tuple[tuple[int, Mapping], ...] = ()
    secant: tuple[Mapping, ...] = ()
    cosecant: tuple[Mapping, ...] = ()
    errors: Mapping[str, str] = field(default_factory=dict)
    secant_excluded: tuple[Mapping, ...] = ()


def _secant_episode(episode) -> dict:
    if episode.status != "AVAILABLE" or episode.founded is None:
        raise ValueError("SECANT episode identity or founding is unavailable")
    events = episode.events
    if any(row["recording_quality"] != "BOUNDED_OBSERVATION" for row in events):
        raise ValueError("SECANT recorder gap")
    for row in events:
        fact = [1, row["session_id"], row["study_context_id"], row["study_target_resource_id"],
                row["episode_id"], row["event_name"], row["stage"], row["occurred_monotonic_ns"],
                row["request_id"], row["attempt_id"], row["evidence_id"], row["reason"]]
        canonical = _canonical(fact)
        if (row["canonical_fact_json"] != canonical or row["fact_digest"] != _digest(canonical)
                or row["event_id"] != _digest(_canonical(["secant-event-v1", fact, row["occurrence_ordinal"]]))):
            raise ValueError("SECANT durable identity mismatch")
    if events[0]["event_name"] != "SECANT_EPISODE_FOUNDED":
        raise ValueError("SECANT founding is not first")
    displays = [row for row in events if row["event_name"] == "SECANT_DISPLAYED"]
    if not displays or displays[0]["stage"] != 1:
        raise ValueError("SECANT-1 display is missing")
    if (displays[0]["occurred_monotonic_ns"] != events[0]["occurred_monotonic_ns"]
            or displays[0]["request_id"] != events[0]["request_id"]):
        raise ValueError("SECANT founding/display evidence mismatch")
    stages = [row["stage"] for row in displays]
    if any(later < earlier or later > earlier + 1 for earlier, later in zip(stages, stages[1:])):
        raise ValueError("SECANT displayed-stage chronology is invalid")
    if episode.closed is not None:
        facts = tuple(SecantFact(row["event_id"], row["event_name"], row["occurred_monotonic_ns"],
                                 row["stage"], row["request_id"], row["attempt_id"], row["reason"])
                      for row in events)
        _validate_lifecycle(facts)
    else:
        # An incomplete episode cannot use the closed-lifecycle certificate,
        # but every reported recovery fact still needs its own attempt chain.
        attempts = {}
        for row in events:
            name, attempt, at = row["event_name"], row["attempt_id"], row["occurred_monotonic_ns"]
            if name == "SECANT_RETURN_STARTED":
                if not attempt or attempt in attempts:
                    raise ValueError("Invalid open SECANT attempt identity")
                attempts[attempt] = ("STARTED", at)
            elif name in ("SECANT_RETURN_VERIFIED", "SECANT_RECOVERY_CLOSED", "SECANT_RECOVERY_INTERRUPTED"):
                phase, began = attempts.get(attempt, ("MISSING", -1))
                if phase not in ("STARTED", "VERIFIED") or at < began:
                    raise ValueError("Open SECANT recovery event lacks its attempt")
                if name == "SECANT_RETURN_VERIFIED":
                    if phase != "STARTED" or at - began < 10_000_000_000:
                        raise ValueError("Open SECANT verification chronology is invalid")
                    attempts[attempt] = ("VERIFIED", began)
                elif name == "SECANT_RECOVERY_CLOSED":
                    if phase != "VERIFIED" or at - began < 60_000_000_000:
                        raise ValueError("Open SECANT recovery closure is invalid")
                    attempts[attempt] = ("CLOSED", began)
                else:
                    attempts[attempt] = ("INTERRUPTED", began)
    founded_at = secant_founding(episode.founded).at_utc
    caption = "Not recorded"
    if episode.source_status == "AVAILABLE" and episode.source.get("display_metadata") is not None:
        try:
            caption = validate_display_metadata(
                episode.source["display_metadata"],
                observation_id=episode.source.get("display_observation_id"),
                observed_ns=episode.source.get("display_observed_ns"),
            ).normalized_caption
        except (ValueError, TypeError, KeyError):
            caption = "Unavailable"
    names = [row["event_name"] for row in events]
    recovered = bool(episode.closed and episode.closed["reason"] == "recovered"
                     and "SECANT_RECOVERY_CLOSED" in names)
    return dict(session_id=episode.identity[0], context_id=episode.identity[1],
                alias=episode.display_episode_id, start_utc=founded_at,
                highest_stage=episode.stage_reached, closed=episode.closed is not None,
                terminal_reason=episode.closed["reason"] if episode.closed else "Open / incomplete",
                recovered=recovered, source_status=episode.source_status,
                source_caption=caption, source_kind=episode.source.get("kind", "Not recorded"),
                events=events)


def _recorder_statuses(database_file: str | Path) -> tuple[Mapping, ...]:
    """Read finality receipts before the event corpus, so closure is a fence."""
    connection = sqlite3.connect(Path(database_file).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        try:
            rows = connection.execute(
                "SELECT key, value FROM myelin_meta WHERE key LIKE 'passive_recorder:v1:run:%'").fetchall()
        except sqlite3.OperationalError as error:
            if "no such table" not in str(error).lower():
                raise
            return ()
        statuses = []
        for key, value in rows:
            status = json.loads(value)
            if key != "passive_recorder:v1:run:" + str(status.get("run_id", "")):
                raise ValueError("Recorder receipt identity mismatch")
            statuses.append(status)
        return tuple(statuses)
    finally:
        connection.rollback()
        connection.close()


def _cosecant_break(snapshot, item: Mapping) -> dict:
    if item["status"] != "AVAILABLE" or item["started"] is None:
        raise ValueError("COSECANT break chronology or start is unavailable")
    events = tuple(item["events"])
    start = next(row for row in events if row["kind"] == "BREAK_STARTED")
    started_at = cosecant_founding(start).at_utc
    target = item.get("target") or {}
    caption = "Not recorded"
    metadata = target.get("display_metadata")
    if metadata is not None:
        try:
            caption = validate_display_metadata(metadata,
                observed_ns=target.get("observed_monotonic_ns")).normalized_caption
        except (ValueError, TypeError, KeyError):
            caption = "Unavailable"
    kinds = {row["kind"] for row in events}
    return dict(session_id=snapshot.session_id,
                alias=read_display_alias(snapshot, "COSECANT", item["native_id"]),
                start_utc=started_at, study_block_id=item["started"].get("study_block_id", ""),
                allowance=item.get("allowance"), target_kind=target.get("identity_kind", "Not recorded"),
                target_caption=caption, confirmed="RETURN_CONFIRMED" in kinds,
                cancelled="BREAK_CANCELLED" in kinds, complete="BREAK_COMPLETE" in kinds,
                events=events)


def _cosecant_breaks(snapshot) -> tuple[Mapping, ...]:
    """Project break entities without mistaking session-wide sequence for per-break sequence.

    The certified metric validator runs first.  It checks the durable payload,
    clocks, and contiguous sequence *within* each break, starting at that
    break's recorded first number.  The dashboard's break projector instead
    requires every break to start at 1, which rejects later live breaks.
    """
    groups: dict[str, list[Mapping]] = {}
    for row in snapshot.rows("cosecant_events"):
        if not row["break_id"] and row["kind"] == "SAFE_SHUTDOWN":
            continue
        groups.setdefault(row["break_id"], []).append(row)
    result = []
    for native, rows in groups.items():
        ordered = sorted(rows, key=lambda row: row["sequence"])
        events = []
        started = target = allowance = None
        for row in ordered:
            payload = json.loads(row["payload_json"])
            if (row["session_id"] != snapshot.session_id or payload["break_id"] != native
                    or payload["sequence"] != row["sequence"] or payload["kind"] != row["kind"]):
                raise ValueError("COSECANT durable break identity mismatch")
            parse_utc_timestamp(payload["occurred_wall_time_utc"])
            events.append(dict(row, payload=payload))
            if row["kind"] != "BREAK_STARTED":
                continue
            if started is not None or row is not ordered[0]:
                raise ValueError("COSECANT break has an invalid opening fact")
            started = payload
            if "selected_break_extension_version" in payload:
                seconds = payload.get("selected_break_seconds")
                if (payload["selected_break_extension_version"] != 1
                        or type(seconds) is not int or seconds <= 0):
                    raise ValueError("Invalid COSECANT allowance")
                allowance = seconds
            if "return_target_extension_version" in payload:
                if payload["return_target_extension_version"] != 1 or not isinstance(payload.get("return_target"), dict):
                    raise ValueError("Invalid COSECANT return target")
                target = payload["return_target"]
                if (target.get("identity_version") != 1
                        or target.get("identity_kind") not in ("BROWSER", "DESKTOP")
                        or (target["identity_kind"] == "BROWSER"
                            and not (target.get("platform_key") and target.get("resource_token")))):
                    raise ValueError("Incomplete COSECANT return identity")
        if started is None:
            raise ValueError("COSECANT break lacks a start")
        item = dict(status="AVAILABLE", native_id=native, events=tuple(events),
                    started=started, target=target, allowance=allowance)
        result.append(_cosecant_break(snapshot, item))
    return tuple(result)


def _excluded_secant(episode, reason: str) -> Mapping:
    """Keep the gap visible without turning it into a behavioural outcome."""
    if episode.founded is None:
        raise ValueError("SECANT gap has no authoritative founding time")
    return dict(alias=episode.display_episode_id,
                start_utc=secant_founding(episode.founded).at_utc, reason=reason)


def read_study_family(database_file: str | Path) -> StudyFamilyEvidence:
    """Read one bounded historical SQLite snapshot; never bootstrap or write."""
    statuses = _recorder_statuses(database_file)
    snapshots = read_corpus(database_file)
    studies, secant, cosecant, secant_excluded = [], [], [], []
    errors: dict[str, str] = {}
    for snapshot in snapshots:
        if any(snapshot.tables[name].status == "UNAVAILABLE" for name in (
            "study_events", "study_resources", "study_resource_intervals",
            "study_resource_boundaries", "study_resource_observation_evidence")):
            errors["study"] = "Study evidence is unavailable."
        else:
            study = project_study(snapshot)
            if study["status"] == "AVAILABLE":
                studies.append((snapshot.session_id, study))
            else:
                errors["study"] = "Study resource evidence failed validation."

        table = snapshot.tables["secant_events"]
        if table.status == "UNAVAILABLE":
            errors["secant"] = "SECANT evidence is unavailable."
        elif table.status == "AVAILABLE":
            try:
                session_statuses = tuple(status for status in statuses
                    if snapshot.session_id in status.get("attached_session_ids", ()))
                if table.rows or session_statuses:
                    readiness, reason = recorder_readiness(session_statuses,
                        {row["recorder_run_id"] for row in table.rows})
                else:
                    readiness, reason = "AVAILABLE", ""
                if readiness != "AVAILABLE":
                    secant_excluded.extend(_excluded_secant(item, reason)
                                           for item in project_secant(snapshot))
                else:
                    for item in project_secant(snapshot):
                        try:
                            secant.append(_secant_episode(item))
                        except ValueError as error:
                            if str(error) != "SECANT recorder gap":
                                raise
                            secant_excluded.append(_excluded_secant(item, "Recorder gap"))
            except (ValueError, TypeError, KeyError) as error:
                errors["secant"] = f"SECANT evidence failed validation: {type(error).__name__}."

        table = snapshot.tables["cosecant_events"]
        if table.status == "UNAVAILABLE":
            errors["cosecant"] = "COSECANT evidence is unavailable."
        elif table.status == "AVAILABLE":
            try:
                _cosecant_metric(snapshot.rows("cosecant_events"), {snapshot.session_id})
                cosecant.extend(_cosecant_breaks(snapshot))
            except (ValueError, TypeError, KeyError, RuntimeError) as error:
                errors["cosecant"] = f"COSECANT evidence failed validation: {type(error).__name__}."
    if secant_excluded and not secant:
        errors["secant"] = "No SECANT episode has fully bounded recorder evidence."
    return StudyFamilyEvidence(tuple(studies), tuple(secant), tuple(cosecant), errors,
                               tuple(secant_excluded))
