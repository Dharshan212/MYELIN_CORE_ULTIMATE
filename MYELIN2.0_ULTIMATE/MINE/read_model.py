"""Pure, read-only projection of durable MINE events.

Generation identity is ``(parent_session_id, generation)``.  That key keeps
the candidate prefix attached to the formal episode even though
``mine_episode_id`` is empty until ``MINE_EPISODE_STARTED`` is committed.
Sequence is the sole ordering authority inside a generation.

This module owns no SQL, Qt, runtime calls, timers, or selection state.  It
does not expose request/evidence/event identifiers or raw JSON.  MBI consumes
only explicit ``MESSAGING_DWELL_SEGMENT_COMPLETED`` facts; event-to-event
monotonic deltas remain presentation facts and are never treated as dwell.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Final, Protocol

from MINE.mine import MINE_SCHEMA_VERSION, MineEvent, MineEventClass
from time_projection import (
    TimezoneProjectionError,
    parse_utc_timestamp,
    project_utc_timestamp,
    resolve_timezone,
    timezone_tag,
)


MBI_UNAVAILABLE_MESSAGE: Final = (
    "Factual messaging dwell duration was not recorded for these episodes."
)
MBI_AVAILABLE_MESSAGE: Final = (
    "Factual messaging dwell segments from the latest 10 formal MINE episodes."
)

# Ordinary dashboard projections may expose only these event-specific facts.
# request_id/evidence_token/event_id remain diagnostic-only by design.
APPROVED_PAYLOAD_KEYS: Final = MappingProxyType({
    "MESSAGING_DWELL_SEGMENT_COMPLETED": frozenset({
        "segment_order", "platform_key", "dwell_seconds",
    }),
    "MESSAGING_PLATFORM_TRANSITION": frozenset({"from_platform", "to_platform"}),
    "RETURN_INTENT_RECORDED": frozenset({"choice"}),
    "IMPORTANT_INTENT_RECORDED": frozenset({"choice"}),
    "IMPORTANT_DURATION_COMMITTED": frozenset({"duration_minutes"}),
    "IMPORTANT_ALLOWANCE_STARTED": frozenset({"duration_minutes"}),
    "RETURN_VISUAL_CONFIRMING_STARTED": frozenset({"variant"}),
    "RETURN_VERIFICATION_STARTED": frozenset({"branch", "visual_stage"}),
    "RETURN_VERIFICATION_COMPLETED": frozenset({"branch"}),
    "RETURN_VERIFICATION_INTERRUPTED": frozenset({"reason", "branch", "stage"}),
    "CLOSURE_CONFIRMATION_STARTED": frozenset({"branch"}),
    "CLOSURE_CONFIRMATION_INTERRUPTED": frozenset({"reason"}),
    "CLOSURE_CONFIRMATION_COMPLETED": frozenset({"closure_outcome"}),
    "RETURN_CONFIRMED": frozenset({"closure_outcome"}),
    "MINE_SESSION_CLOSED": frozenset({"closure_reason", "closure_outcome"}),
    "MINE_RUNTIME_STOPPED": frozenset({"closure_reason", "closure_outcome"}),
    "EMERGENCY_STOPPED": frozenset({"closure_reason", "closure_outcome"}),
    "MINE_CANDIDATE_RESET": frozenset({"outcome"}),
    "MINE_CANDIDATE_ENDED_BEFORE_INTERVENTION": frozenset({"outcome"}),
    "EVIDENCE_GAP": frozenset({"reason"}),
    "STUDY_PREEMPTED_MINE": frozenset({"formal_episode"}),
    "STUDY_PREEMPTION_RELEASED": frozenset({"future_mine_eligibility_only"}),
    "MINE_HANDOVER_SUPERSEDED_BY_CONTEXT": frozenset({"old_kind", "reason"}),
})

_BRANCH_EVENTS: Final = frozenset({
    "RETURN_INTENT_RECORDED", "IMPORTANT_INTENT_RECORDED",
})
_CHOICES: Final = frozenset({"I_WILL_COME_BACK", "ITS_IMPORTANT"})
_CLOSURE_EVENTS: Final = frozenset({
    "MINE_SESSION_CLOSED", "MINE_RUNTIME_STOPPED", "EMERGENCY_STOPPED",
})
_RETURN_CLOSURE_EVENTS: Final = frozenset({
    "RETURN_VISUAL_CONFIRMING_STARTED",
    "RETURN_VERIFICATION_STARTED",
    "RETURN_VERIFICATION_COMPLETED",
    "RETURN_VERIFICATION_INTERRUPTED",
    "CLOSURE_CONFIRMATION_STARTED",
    "CLOSURE_CONFIRMATION_INTERRUPTED",
    "CLOSURE_CONFIRMATION_COMPLETED",
    "RETURN_CONFIRMED",
    "MINE_SESSION_CLOSED",
    "MINE_RUNTIME_STOPPED",
    "EMERGENCY_STOPPED",
})


class MineEventReader(Protocol):
    def read_mine_events(self) -> tuple[MineEvent, ...]: ...


@dataclass(frozen=True, slots=True)
class MineStructuralIssue:
    code: str
    detail: str
    session_id: int | None = None
    generation: int | None = None


@dataclass(frozen=True, slots=True)
class MineDisplayEvent:
    session_id: int
    generation: int
    mine_episode_id: str
    sequence: int
    event_name: str
    event_class: str
    occurred_at_utc: str
    occurred_at_display: str
    timezone_label: str
    platform_key: str
    platform_label: str
    payload_facts: Mapping[str, object]
    withheld_payload_field_count: int
    elapsed_from_previous_seconds: float | None
    schema_version: str


@dataclass(frozen=True, slots=True)
class MineMessengerHop:
    from_platform_key: str
    from_platform_label: str
    to_platform_key: str
    to_platform_label: str
    sequence: int
    occurred_at_utc: str
    occurred_at_display: str
    timezone_label: str


@dataclass(frozen=True, slots=True)
class MineDwellRecord:
    """One factual completed dwell segment, or an honest legacy placeholder."""

    session_id: int
    generation: int
    mine_episode_id: str
    display_episode_id: str
    segment_order: int | None
    platform_key: str
    platform_label: str
    dwell_seconds: float | None
    mbi_band: str | None
    completed_at_utc: str | None
    completed_at_display: str | None


@dataclass(frozen=True, slots=True)
class MineEpisodeProjection:
    session_id: int
    generation: int
    mine_episode_id: str
    display_episode_id: str
    started_at_utc: str
    started_at_display: str
    ended_at_utc: str | None
    ended_at_display: str | None
    starting_platform_key: str
    starting_platform_label: str
    branch: str | None
    important_duration_minutes: int | None
    closure_outcome: str | None
    closure_reason: str | None
    is_closed: bool
    return_verified: bool
    closure_confirmed: bool
    event_count: int
    events: tuple[MineDisplayEvent, ...]
    return_closure_events: tuple[MineDisplayEvent, ...]
    messenger_platforms: tuple[tuple[str, str], ...]
    messenger_hops: tuple[MineMessengerHop, ...]
    mbi_available: bool = False
    mbi_status_message: str = MBI_UNAVAILABLE_MESSAGE
    dwell_records: tuple[MineDwellRecord, ...] = ()


@dataclass(frozen=True, slots=True)
class MineOverviewProjection:
    captured_episode_count: int | None
    closed_episode_count: int | None
    confirmed_return_count: int | None
    recorded_generation_count: int | None
    messenger_hop_count: int | None
    population_scope: str = "DATABASE_SNAPSHOT"


@dataclass(frozen=True, slots=True)
class MineProjection:
    available: bool
    generated_at_utc: str
    presentation_timezone: str
    overview: MineOverviewProjection
    episodes: tuple[MineEpisodeProjection, ...]
    latest_episode_key: tuple[int, int] | None
    latest_events: tuple[MineDisplayEvent, ...]
    latest_or_selected_recent_episode: MineEpisodeProjection | None
    status: str
    status_message: str
    read_error: str | None
    structural_issues: tuple[MineStructuralIssue, ...]
    mbi_available: bool = False
    mbi_status_message: str = MBI_UNAVAILABLE_MESSAGE
    dwell_records: tuple[MineDwellRecord, ...] = ()


def _stamp(value: str | None) -> str:
    stamp = value if value is not None else datetime.now(timezone.utc).isoformat(
        timespec="microseconds"
    )
    parse_utc_timestamp(stamp)
    return stamp


def _unavailable(
    stamp: str,
    zone: str,
    status: str,
    message: str,
    *,
    issues: tuple[MineStructuralIssue, ...] = (),
    read_error: str | None = None,
) -> MineProjection:
    return MineProjection(
        False,
        stamp,
        zone,
        MineOverviewProjection(None, None, None, None, None),
        (),
        None,
        (),
        None,
        status,
        message,
        read_error,
        tuple(issues),
    )


class MineReadAuthority:
    """Read once through the injected persistence boundary, then project."""

    def __init__(self, *, event_reader: MineEventReader):
        self._reader = event_reader

    def project(
        self,
        presentation_timezone: str = "local",
        *,
        generated_at_utc: str | None = None,
    ) -> MineProjection:
        stamp = _stamp(generated_at_utc)
        try:
            events = self._reader.read_mine_events()
        except Exception as error:
            # Exception text can contain paths, SQL or raw evidence.
            return _unavailable(
                stamp,
                presentation_timezone,
                "READ_ERROR",
                "MINE event source could not be read.",
                read_error=type(error).__name__,
            )
        return project_mine_events(
            events,
            presentation_timezone=presentation_timezone,
            generated_at_utc=stamp,
        )


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON value")


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in sorted(value.items())})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON value")
    return value


def _parse_payload(event: MineEvent):
    payload = json.loads(
        event.payload_json,
        object_pairs_hook=_json_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    approved = APPROVED_PAYLOAD_KEYS.get(event.event_name, frozenset())
    display = {
        key: _freeze(value)
        for key, value in payload.items()
        if key in approved
    }
    return MappingProxyType(dict(sorted(display.items()))), len(payload) - len(display), payload


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_event(event: object):
    if not isinstance(event, MineEvent):
        return "MALFORMED_EVENT", "Source contains a non-MineEvent record.", None
    required_text = (
        event.event_id,
        event.event_name,
        event.occurred_at_utc,
        event.schema_version,
    )
    optional_text = (
        event.mine_episode_id,
        event.platform_key,
        event.platform_label,
        event.request_id,
        event.evidence_token,
        event.payload_json,
    )
    if (
        not all(_nonempty(value) for value in required_text)
        or not all(isinstance(value, str) for value in optional_text)
        or not isinstance(event.event_class, MineEventClass)
        or any(
            type(value) is not int or value <= 0
            for value in (
                event.parent_session_id,
                event.sequence,
                event.generation,
                event.monotonic_ns,
            )
        )
    ):
        return (
            "MALFORMED_EVENT",
            "Event fields do not satisfy the durable MINE record contract.",
            None,
        )
    if event.schema_version != MINE_SCHEMA_VERSION:
        return "UNSUPPORTED_SCHEMA", "Event schema is not the current MINE schema.", None
    try:
        parse_utc_timestamp(event.occurred_at_utc)
    except (ValueError, OverflowError):
        return "MALFORMED_UTC", "Event timestamp is not a readable UTC instant.", None
    try:
        display, withheld, payload = _parse_payload(event)
    except (ValueError, TypeError, RecursionError, OverflowError):
        return (
            "MALFORMED_PAYLOAD",
            "Event payload is not an unambiguous finite JSON object.",
            None,
        )
    if event.event_name in _BRANCH_EVENTS and (
        payload.get("choice") not in _CHOICES
        or event.event_class is not MineEventClass.USER_ACTION
    ):
        return "MALFORMED_CHOICE", "Branch event does not contain an approved choice.", None
    if event.event_name == "IMPORTANT_DURATION_COMMITTED" and (
        type(payload.get("duration_minutes")) is not int
        or not 5 <= payload["duration_minutes"] <= 30
    ):
        return (
            "MALFORMED_DURATION",
            "Committed important duration must be a whole 5-30 minutes.",
            None,
        )
    if event.event_name == "MESSAGING_PLATFORM_TRANSITION" and (
        not all(_nonempty(payload.get(key)) for key in ("from_platform", "to_platform"))
        or payload["from_platform"] == payload["to_platform"]
        or event.platform_key != payload["to_platform"]
        or event.event_class is not MineEventClass.OBSERVED
    ):
        return (
            "MALFORMED_MESSENGER_HOP",
            "Messenger transition must factually record distinct from/to platforms.",
            None,
        )
    if event.event_name == "MESSAGING_DWELL_SEGMENT_COMPLETED" and (
        type(payload.get("segment_order")) is not int
        or payload["segment_order"] <= 0
        or type(payload.get("dwell_seconds")) not in {int, float}
        or not math.isfinite(float(payload["dwell_seconds"]))
        or float(payload["dwell_seconds"]) < 0
        or not _nonempty(payload.get("platform_key"))
        or event.platform_key != payload["platform_key"]
        or event.event_class is not MineEventClass.DERIVED
    ):
        return (
            "MALFORMED_DWELL_SEGMENT",
            "Dwell segment must record ordered certified platform seconds.",
            None,
        )
    if event.event_name == "MINE_SESSION_CLOSED" and not all(
        _nonempty(payload.get(key)) for key in ("closure_reason", "closure_outcome")
    ):
        return "MALFORMED_CLOSURE", "Episode closure must record reason and outcome.", None
    return "", "", (display, withheld)


def _group_issues(key: tuple[int, int], events: list[MineEvent]):
    issues: list[MineStructuralIssue] = []

    def add(code: str, detail: str) -> None:
        issues.append(MineStructuralIssue(code, detail, key[0], key[1]))

    if any((event.parent_session_id, event.generation) != key for event in events):
        add("MIXED_GENERATION_KEY", "Group contains more than one session/generation key.")
    sequences = [event.sequence for event in events]
    if len(set(sequences)) != len(sequences):
        add("DUPLICATE_SEQUENCE", "Generation contains duplicate sequence numbers.")
    if sorted(set(sequences)) != list(range(1, len(set(sequences)) + 1)):
        add("NON_CONTIGUOUS_SEQUENCE", "Generation sequence must start at one with no gaps.")
    starts = [event for event in events if event.event_name == "MINE_CANDIDATE_STARTED"]
    if len(starts) != 1 or starts[0].sequence != 1:
        add("INVALID_CANDIDATE_BOUNDARY", "Generation requires one candidate start at sequence one.")
    episode_starts = [event for event in events if event.event_name == "MINE_EPISODE_STARTED"]
    if len(episode_starts) > 1:
        add("AMBIGUOUS_EPISODE_START", "Generation contains multiple formal episode starts.")
    episode_ids = {event.mine_episode_id for event in events if event.mine_episode_id}
    if len(episode_ids) > 1:
        add("AMBIGUOUS_EPISODE_ID", "Generation contains conflicting formal episode IDs.")
    if bool(episode_starts) != bool(episode_ids):
        add("INVALID_EPISODE_ID_BOUNDARY", "Formal episode start and minted identity disagree.")
    if episode_starts and not episode_starts[0].mine_episode_id:
        add("MISSING_EPISODE_ID", "Formal episode start has no minted episode identity.")
    closes = [event for event in events if event.event_name == "MINE_SESSION_CLOSED"]
    if len(closes) > 1 or (closes and closes[0].sequence != max(sequences)):
        add("INVALID_CLOSE_BOUNDARY", "Episode closure must be unique and final.")
    if sum(event.event_name in _BRANCH_EVENTS for event in events) > 1:
        add("AMBIGUOUS_BRANCH", "Generation contains multiple durable branch choices.")
    if sum(event.event_name == "IMPORTANT_DURATION_COMMITTED" for event in events) > 1:
        add("AMBIGUOUS_DURATION", "Generation contains multiple committed durations.")
    dwell_orders = [
        json.loads(event.payload_json).get("segment_order")
        for event in events
        if event.event_name == "MESSAGING_DWELL_SEGMENT_COMPLETED"
    ]
    if len(dwell_orders) != len(set(dwell_orders)):
        add("DUPLICATE_DWELL_SEGMENT", "Generation contains duplicate dwell segment order.")
    if dwell_orders and dwell_orders != sorted(dwell_orders):
        add("REGRESSED_DWELL_SEGMENT", "Dwell segment order regresses by event sequence.")
    ordered = sorted(events, key=lambda event: event.sequence)
    if any(current.monotonic_ns < previous.monotonic_ns for previous, current in zip(ordered, ordered[1:])):
        add("REGRESSED_MONOTONIC_ORDER", "Generation monotonic evidence regresses by sequence.")
    current_platform = ""
    for event in ordered:
        if event.event_name == "MESSAGING_PLATFORM_ENTERED":
            current_platform = event.platform_key
        elif event.event_name == "MESSAGING_PLATFORM_TRANSITION":
            try:
                payload = json.loads(event.payload_json)
            except (ValueError, TypeError):
                continue
            if current_platform and payload.get("from_platform") != current_platform:
                add("BROKEN_MESSENGER_CHAIN", "Messenger transition does not continue the recorded route.")
            current_platform = str(payload.get("to_platform", ""))
    return issues


def _display_time(stamp: str, zone: str) -> tuple[str, str]:
    moment = project_utc_timestamp(stamp, zone)
    label = timezone_tag(moment, zone)
    return f"{moment.isoformat(sep=' ', timespec='microseconds')} {label}", label


def _project_group(
    source: list[MineEvent],
    sanitized: dict[str, tuple[Mapping[str, object], int]],
    zone: str,
) -> tuple[MineDisplayEvent, ...]:
    ordered = sorted(source, key=lambda event: event.sequence)
    projected = []
    previous_ns: int | None = None
    for event in ordered:
        display_time, label = _display_time(event.occurred_at_utc, zone)
        payload, withheld = sanitized[event.event_id]
        elapsed = (
            None
            if previous_ns is None
            else (event.monotonic_ns - previous_ns) / 1_000_000_000
        )
        projected.append(MineDisplayEvent(
            event.parent_session_id,
            event.generation,
            event.mine_episode_id,
            event.sequence,
            event.event_name,
            event.event_class.value,
            event.occurred_at_utc,
            display_time,
            label,
            event.platform_key,
            event.platform_label or event.platform_key,
            payload,
            withheld,
            elapsed,
            event.schema_version,
        ))
        previous_ns = event.monotonic_ns
    return tuple(projected)


def mbi_band(dwell_seconds: object) -> str:
    """Classify one validated factual duration without affecting physiology."""

    if type(dwell_seconds) not in {int, float}:
        raise TypeError("dwell_seconds must be numeric")
    seconds = float(dwell_seconds)
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("dwell_seconds must be finite and non-negative")
    if seconds <= 600:
        return "10 MIN OR LESS"
    if seconds <= 1800:
        return "11–30 MIN"
    if seconds <= 3600:
        return "31–60 MIN"
    if seconds <= 7200:
        return "61–120 MIN"
    return "MORE THAN 120 MIN"


def _episode_projection(events: tuple[MineDisplayEvent, ...]) -> MineEpisodeProjection:
    episode_start = next(event for event in events if event.event_name == "MINE_EPISODE_STARTED")
    episode_id = episode_start.mine_episode_id
    close = next((event for event in events if event.event_name == "MINE_SESSION_CLOSED"), None)
    entered = next((event for event in events if event.event_name == "MESSAGING_PLATFORM_ENTERED"), None)
    candidate = events[0]
    starting = entered or candidate
    branch_event = next((event for event in events if event.event_name in _BRANCH_EVENTS), None)
    duration_event = next(
        (event for event in events if event.event_name == "IMPORTANT_DURATION_COMMITTED"),
        None,
    )

    labels: dict[str, str] = {}
    route: list[tuple[str, str]] = []
    hops: list[MineMessengerHop] = []
    if entered and entered.platform_key:
        labels[entered.platform_key] = entered.platform_label or entered.platform_key
        route.append((entered.platform_key, labels[entered.platform_key]))
    for event in events:
        if event.event_name != "MESSAGING_PLATFORM_TRANSITION":
            continue
        source_key = str(event.payload_facts["from_platform"])
        destination_key = str(event.payload_facts["to_platform"])
        source_label = labels.get(source_key, source_key)
        destination_label = event.platform_label or destination_key
        labels[destination_key] = destination_label
        if not route:
            route.append((source_key, source_label))
        if route[-1][0] != destination_key:
            route.append((destination_key, destination_label))
            hops.append(MineMessengerHop(
                source_key,
                source_label,
                destination_key,
                destination_label,
                event.sequence,
                event.occurred_at_utc,
                event.occurred_at_display,
                event.timezone_label,
            ))

    return_events = tuple(event for event in events if event.event_name in _RETURN_CLOSURE_EVENTS)
    dwell_records = tuple(
        MineDwellRecord(
            candidate.session_id,
            candidate.generation,
            episode_id,
            "",
            int(event.payload_facts["segment_order"]),
            event.platform_key,
            event.platform_label or event.platform_key,
            float(event.payload_facts["dwell_seconds"]),
            mbi_band(event.payload_facts["dwell_seconds"]),
            event.occurred_at_utc,
            event.occurred_at_display,
        )
        for event in events
        if event.event_name == "MESSAGING_DWELL_SEGMENT_COMPLETED"
    )
    return MineEpisodeProjection(
        candidate.session_id,
        candidate.generation,
        episode_id,
        "",
        candidate.occurred_at_utc,
        candidate.occurred_at_display,
        close.occurred_at_utc if close else None,
        close.occurred_at_display if close else None,
        starting.platform_key,
        starting.platform_label,
        str(branch_event.payload_facts["choice"]) if branch_event else None,
        int(duration_event.payload_facts["duration_minutes"]) if duration_event else None,
        str(close.payload_facts["closure_outcome"]) if close else None,
        str(close.payload_facts["closure_reason"]) if close else None,
        close is not None,
        any(event.event_name == "RETURN_VERIFICATION_COMPLETED" for event in events),
        any(event.event_name == "CLOSURE_CONFIRMATION_COMPLETED" for event in events),
        len(events),
        events,
        return_events,
        tuple(route),
        tuple(hops),
        bool(dwell_records),
        MBI_AVAILABLE_MESSAGE if dwell_records else MBI_UNAVAILABLE_MESSAGE,
        dwell_records,
    )


def _with_display_episode_ids(
    episodes: tuple[MineEpisodeProjection, ...],
) -> tuple[MineEpisodeProjection, ...]:
    """Assign local-date aliases while retaining durable internal identities."""

    chronological = sorted(
        episodes,
        key=lambda episode: (
            parse_utc_timestamp(next(
                event.occurred_at_utc
                for event in episode.events
                if event.event_name == "MINE_EPISODE_STARTED"
            )),
            episode.session_id,
            episode.generation,
        ),
    )
    daily_counts: dict[str, int] = defaultdict(int)
    aliases: dict[tuple[int, int], str] = {}
    for episode in chronological:
        formal_start = next(
            event for event in episode.events if event.event_name == "MINE_EPISODE_STARTED"
        )
        local_date = formal_start.occurred_at_display.split(" ", 1)[0]
        date_code = datetime.fromisoformat(local_date).strftime("%d%m%Y")
        daily_counts[date_code] += 1
        aliases[(episode.session_id, episode.generation)] = (
            f"MINE-{date_code}-{daily_counts[date_code]:02d}"
        )

    result = []
    for episode in episodes:
        alias = aliases[(episode.session_id, episode.generation)]
        records = tuple(
            replace(record, display_episode_id=alias)
            for record in episode.dwell_records
        )
        result.append(replace(
            episode,
            display_episode_id=alias,
            dwell_records=records,
        ))
    return tuple(result)


def project_mine_events(
    events: tuple[MineEvent, ...],
    *,
    presentation_timezone: str = "local",
    generated_at_utc: str | None = None,
) -> MineProjection:
    """Project one complete immutable MINE event snapshot without I/O."""

    stamp = _stamp(generated_at_utc)
    try:
        if not isinstance(presentation_timezone, str):
            raise TimezoneProjectionError("timezone must be a string")
        resolve_timezone(presentation_timezone)
    except (ValueError, TypeError):
        return _unavailable(
            stamp,
            presentation_timezone,
            "TIMEZONE_ERROR",
            "Selected presentation timezone is unavailable.",
        )
    if not isinstance(events, tuple):
        return _unavailable(
            stamp,
            presentation_timezone,
            "STRUCTURAL_ERROR",
            "MINE event source must supply an immutable tuple.",
            issues=(MineStructuralIssue("MALFORMED_SOURCE", "Expected tuple[MineEvent, ...]."),),
        )

    groups: dict[tuple[int, int], list[MineEvent]] = defaultdict(list)
    sanitized: dict[str, tuple[Mapping[str, object], int]] = {}
    issues: list[MineStructuralIssue] = []
    for event in events:
        code, detail, safe = _validate_event(event)
        if code:
            issues.append(MineStructuralIssue(code, detail))
            continue
        assert isinstance(event, MineEvent)
        if event.event_id in sanitized:
            issues.append(MineStructuralIssue(
                "DUPLICATE_EVENT_ID", "Durable event identity occurs more than once."
            ))
        sanitized[event.event_id] = safe
        groups[(event.parent_session_id, event.generation)].append(event)
    for key in sorted(groups):
        issues.extend(_group_issues(key, groups[key]))
    if issues:
        issues.sort(key=lambda issue: (
            issue.code,
            issue.session_id or 0,
            issue.generation or 0,
        ))
        return _unavailable(
            stamp,
            presentation_timezone,
            "STRUCTURAL_ERROR",
            "MINE structural validation failed; snapshot facts withheld.",
            issues=tuple(issues),
        )

    try:
        projected_groups = {
            key: _project_group(groups[key], sanitized, presentation_timezone)
            for key in sorted(groups)
        }
        episodes = tuple(sorted(
            (
                _episode_projection(projected)
                for projected in projected_groups.values()
                if any(event.event_name == "MINE_EPISODE_STARTED" for event in projected)
            ),
            key=lambda episode: (
                parse_utc_timestamp(episode.started_at_utc),
                episode.session_id,
                episode.generation,
            ),
            reverse=True,
        ))
        episodes = _with_display_episode_ids(episodes)
        recent_group_keys = sorted(
            projected_groups,
            key=lambda key: (
                parse_utc_timestamp(projected_groups[key][-1].occurred_at_utc),
                key[0],
                key[1],
            ),
            reverse=True,
        )
    except (TimezoneProjectionError, OverflowError, OSError, ValueError):
        return _unavailable(
            stamp,
            presentation_timezone,
            "TIMEZONE_ERROR",
            "UTC evidence could not be projected into the selected timezone.",
        )

    # Generation blocks are newest-last-event first; sequence stays sovereign
    # inside every block and is reversed only for the Latest News presentation.
    latest = tuple(
        event
        for key in recent_group_keys
        for event in reversed(projected_groups[key])
    )
    overview = MineOverviewProjection(
        len(episodes),
        sum(episode.is_closed for episode in episodes),
        sum(
            any(event.event_name == "RETURN_CONFIRMED" for event in episode.events)
            for episode in episodes
        ),
        len(projected_groups),
        sum(event.event_name == "MESSAGING_PLATFORM_TRANSITION" for event in latest),
    )
    latest_episode = episodes[0] if episodes else None
    dwell_records = tuple(
        record
        for episode in episodes[:10]
        for record in (
            episode.dwell_records
            if episode.dwell_records
            else (
                MineDwellRecord(
                    episode.session_id,
                    episode.generation,
                    episode.mine_episode_id,
                    episode.display_episode_id,
                    None,
                    episode.starting_platform_key,
                    episode.starting_platform_label,
                    None,
                    None,
                    None,
                    None,
                ),
            )
        )
    )
    mbi_available = any(record.dwell_seconds is not None for record in dwell_records)
    if episodes:
        status_message = "Facts from the durable MINE database snapshot."
    elif latest:
        status_message = "No formal MINE episodes; candidate evidence is available."
    else:
        status_message = "No MINE events in the database snapshot."
    return MineProjection(
        True,
        stamp,
        presentation_timezone,
        overview,
        episodes,
        (
            (latest_episode.session_id, latest_episode.generation)
            if latest_episode is not None
            else None
        ),
        latest,
        latest_episode,
        "AVAILABLE" if episodes else "EMPTY",
        status_message,
        None,
        (),
        mbi_available,
        MBI_AVAILABLE_MESSAGE if mbi_available else MBI_UNAVAILABLE_MESSAGE,
        dwell_records,
    )


__all__ = [
    "APPROVED_PAYLOAD_KEYS",
    "MBI_AVAILABLE_MESSAGE",
    "MBI_UNAVAILABLE_MESSAGE",
    "MineDisplayEvent",
    "MineDwellRecord",
    "MineEpisodeProjection",
    "MineEventReader",
    "MineMessengerHop",
    "MineOverviewProjection",
    "MineProjection",
    "MineReadAuthority",
    "MineStructuralIssue",
    "mbi_band",
    "project_mine_events",
]
