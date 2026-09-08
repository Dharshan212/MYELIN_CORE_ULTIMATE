"""Read-only NEW COSINE facts, with no runtime, SQL, UI or timing calculations.

Episode identity is (cosine_session_id, generation); sequence alone orders its
events. Structural errors make the whole snapshot unavailable (counts are None,
not misleading zeroes). This is not an episode evidence-quality classification.

Episodes are presented newest recorded start first, with identity as a stable
tie-breaker. ``latest_events`` contains those episode blocks, each in descending
sequence; it is not a global wall-clock chronology. Nothing is silently capped.
Wall timestamps never reorder events within an episode.

All returned collections are deeply immutable. Payloads are plain-text/data
values, not HTML; a future renderer must escape them or use plain-text widgets.
No raw event/payload/monotonic clock is attached to the presentation objects.
Supply generated_at_utc for reproducible metadata as well as reproducible facts.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Final, Protocol

from COSINE.cosine import COSINE_SCHEMA_VERSION, PLATFORM_LABELS, CosineEvent, EventClass
from time_projection import (
    TimezoneProjectionError,
    parse_utc_timestamp,
    project_utc_timestamp,
    resolve_timezone,
    timezone_tag,
)


HELD_PRESENTATION_PAYLOAD_KEYS: Final = frozenset({
    "foreground_ott_seconds", "platform_seconds",
    "break_start_effective_ns", "break_deadline_effective_ns",
})
_CHOICES: Final = MappingProxyType({
    "RETURN_INTENT_RECORDED": "RETURN_INTENTION",
    "BREAK_INTENT_RECORDED": "INTENTIONAL_BREAK",
})


class CosineEventReader(Protocol):
    def read_cosine_events(self) -> tuple[CosineEvent, ...]: ...


@dataclass(frozen=True, slots=True)
class CosineStructuralIssue:
    code: str
    detail: str
    event_id: str = ""
    cosine_session_id: str = ""
    generation: int | None = None


@dataclass(frozen=True, slots=True)
class CosineEventProjection:
    event_id: str
    cosine_session_id: str
    generation: int
    sequence: int
    event_name: str
    event_class: str
    occurred_at_utc: str
    occurred_at_display: str
    timezone_label: str
    platform_key: str
    platform_label: str
    content_title: str
    request_id: str
    payload_display: Mapping[str, object]
    withheld_payload_field_count: int
    schema_version: str


@dataclass(frozen=True, slots=True)
class CosineHopperTransition:
    from_platform: str
    to_platform: str
    from_platform_label: str
    to_platform_label: str
    sequence: int
    occurred_at_utc: str
    occurred_at_display: str
    timezone_label: str


@dataclass(frozen=True, slots=True)
class CosineEpisodeProjection:
    cosine_session_id: str
    generation: int
    parent_session_id: int | None
    started_at_utc: str
    started_at_display: str
    ended_at_utc: str | None
    ended_at_display: str | None
    starting_platform_key: str
    starting_platform_label: str
    event_count: int
    user_choice: str | None
    chosen_break_minutes: int | None
    hopper_count: int
    hopper_transitions: tuple[CosineHopperTransition, ...]
    closure_reason: str | None
    closure_outcome: str | None
    is_closed: bool
    events: tuple[CosineEventProjection, ...]
    hold_context: bool
    hold_context_reason: str | None


@dataclass(frozen=True, slots=True)
class CosineOverviewProjection:
    """Counts of captured episodes and exact durable event occurrences."""
    captured_episode_count: int | None
    confirmed_return_count: int | None
    break_started_count: int | None
    population_scope: str = "DATABASE_SNAPSHOT"
    usual_return_seconds: None = None
    usual_return_status: str = "UNAVAILABLE"
    usual_return_reason: str = "Phase 2 definition not certified"


@dataclass(frozen=True, slots=True)
class CosineAnalysisProjection:
    available: bool
    generated_at_utc: str
    presentation_timezone: str
    overview: CosineOverviewProjection
    episodes: tuple[CosineEpisodeProjection, ...]
    latest_events: tuple[CosineEventProjection, ...]
    latest_or_selected_recent_episode: CosineEpisodeProjection | None
    status: str
    status_message: str
    read_error: str | None
    structural_issues: tuple[CosineStructuralIssue, ...]


def _stamp(value: str | None) -> str:
    stamp = value if value is not None else datetime.now(timezone.utc).isoformat(timespec="microseconds")
    parse_utc_timestamp(stamp)
    return stamp


def _unavailable(stamp, zone, status, message, *, issues=(), read_error=None):
    return CosineAnalysisProjection(
        False, stamp, zone, CosineOverviewProjection(None, None, None),
        (), (), None, status, message, read_error, tuple(issues),
    )


class CosineReadAuthority:
    """Calls only the injected reader; owns no selection or runtime state."""
    def __init__(self, *, event_reader: CosineEventReader):
        self._reader = event_reader

    def project(self, presentation_timezone: str = "local", *,
                generated_at_utc: str | None = None) -> CosineAnalysisProjection:
        stamp = _stamp(generated_at_utc)
        try:
            events = self._reader.read_cosine_events()
        except Exception as error:
            # Exception text may include raw payloads/SQL/paths. Never publish it.
            return _unavailable(stamp, presentation_timezone, "READ_ERROR",
                                "COSINE event source could not be read.",
                                read_error=type(error).__name__)
        return project_cosine_events(events, presentation_timezone=presentation_timezone,
                                     generated_at_utc=stamp)


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON value")


def _sanitize(value):
    """Copy/freeze all levels, withholding held keys even in nested containers.

    Count removed field occurrences; a removed object-valued field counts once,
    since its entire subtree is withheld with it. Never expose removed names.
    """
    if isinstance(value, dict):
        result, count = {}, 0
        for key, item in sorted(value.items()):
            if key in HELD_PRESENTATION_PAYLOAD_KEYS:
                count += 1
            else:
                result[key], removed = _sanitize(item)
                count += removed
        return MappingProxyType(result), count
    if isinstance(value, list):
        pairs = tuple(_sanitize(item) for item in value)
        return tuple(item for item, _ in pairs), sum(count for _, count in pairs)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON value")
    return value, 0


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _validate_event(event):
    """Validate the read boundary, not physiology or final outcome mathematics."""
    if not isinstance(event, CosineEvent):
        return "MALFORMED_EVENT", "Source contains a non-CosineEvent record.", None
    text_fields = (event.event_id, event.cosine_session_id, event.event_name,
                   event.occurred_at_utc, event.schema_version)
    optional_text = (event.platform_key, event.content_title, event.request_id,
                     event.evidence_token, event.payload_json)
    if (not all(_nonempty(value) for value in text_fields)
            or not all(isinstance(value, str) for value in optional_text)
            or not isinstance(event.event_class, EventClass)
            or any(type(value) is not int or value <= 0
                   for value in (event.sequence, event.generation, event.monotonic_ns))
            or (event.session_id is not None and
                (type(event.session_id) is not int or event.session_id <= 0))):
        return "MALFORMED_EVENT", "Event fields do not satisfy the durable record contract.", None
    if event.schema_version != COSINE_SCHEMA_VERSION:
        return "UNSUPPORTED_SCHEMA", "Event schema is not the current NEW COSINE schema.", None
    try:
        parse_utc_timestamp(event.occurred_at_utc)
    except (ValueError, OverflowError):
        return "MALFORMED_UTC", "Event timestamp does not identify a readable UTC instant.", None
    try:
        payload = json.loads(event.payload_json, object_pairs_hook=_json_object,
                             parse_constant=_reject_constant)
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        display, withheld = _sanitize(payload)
    except (ValueError, TypeError, RecursionError, OverflowError):
        return "MALFORMED_PAYLOAD", "Event payload is not an unambiguous finite JSON object.", None
    name = event.event_name
    if name in _CHOICES and (payload.get("choice") != _CHOICES[name]
                            or event.event_class is not EventClass.USER_ACTION):
        return "MALFORMED_CHOICE", "Durable choice event and recorded choice disagree.", None
    if name == "BREAK_DURATION_COMMITTED" and (
            type(payload.get("duration_minutes")) is not int or payload["duration_minutes"] <= 0):
        return "MALFORMED_BREAK_COMMIT", "Committed duration must be a positive integer number of minutes.", None
    if name == "HOPPER_TRANSITION" and not all(
            _nonempty(payload.get(key)) for key in ("from_platform", "to_platform")):
        return "MALFORMED_HOPPER", "Hopper transition must record both platform keys.", None
    if name == "COSINE_SESSION_CLOSED" and not all(
            _nonempty(payload.get(key)) for key in ("closure_reason", "closure_outcome")):
        return "MALFORMED_CLOSURE", "Closure must record its reason and outcome.", None
    return "", "", (display, withheld)


def _group_issues(key, events):
    """Explicit key check defends this seam against mixed-generation grouping."""
    issues = []

    def add(code, detail):
        issues.append(CosineStructuralIssue(code, detail, cosine_session_id=key[0], generation=key[1]))

    if any((e.cosine_session_id, e.generation) != key for e in events):
        add("MIXED_EPISODE_KEY", "Group contains more than one episode identity or generation.")
    if len({e.session_id for e in events}) != 1:
        add("MIXED_PARENT_SESSION", "Episode rows disagree about the parent session.")
    sequences = [e.sequence for e in events]
    if len(set(sequences)) != len(sequences):
        add("DUPLICATE_SEQUENCE", "Episode contains duplicate sequence numbers.")
    if sorted(set(sequences)) != list(range(1, len(set(sequences)) + 1)):
        add("NON_CONTIGUOUS_SEQUENCE", "Episode sequence must start at one with no gaps.")
    starts = [e for e in events if e.event_name == "COSINE_SESSION_STARTED"]
    if len(starts) != 1 or starts[0].sequence != 1:
        add("INVALID_START_BOUNDARY", "Episode requires exactly one start at sequence one.")
    closes = [e for e in events if e.event_name == "COSINE_SESSION_CLOSED"]
    if len(closes) > 1 or (closes and closes[0].sequence != max(sequences)):
        add("INVALID_CLOSE_BOUNDARY", "A closure must be unique and the final episode event.")
    if sum(e.event_name in _CHOICES for e in events) > 1:
        add("AMBIGUOUS_CHOICE", "Multiple durable choices cannot project to one choice.")
    if sum(e.event_name == "BREAK_DURATION_COMMITTED" for e in events) > 1:
        add("AMBIGUOUS_BREAK_COMMIT", "Multiple committed durations cannot project to one duration.")
    return issues


def _display_time(stamp, zone):
    moment = project_utc_timestamp(stamp, zone)
    label = timezone_tag(moment, zone)
    # Include offset as well as the short tag, including ambiguous DST hours.
    return f"{moment.isoformat(sep=' ', timespec='microseconds')} {label}", label


def _event_projection(event, sanitized, zone):
    display_time, label = _display_time(event.occurred_at_utc, zone)
    payload, withheld = sanitized
    return CosineEventProjection(
        event.event_id, event.cosine_session_id, event.generation, event.sequence,
        event.event_name, event.event_class.value, event.occurred_at_utc, display_time,
        label, event.platform_key, PLATFORM_LABELS.get(event.platform_key, event.platform_key),
        event.content_title, event.request_id, payload, withheld, event.schema_version,
    )


def _episode_projection(key, source, sanitized, zone):
    ordered = sorted(source, key=lambda e: e.sequence)
    events = tuple(_event_projection(e, sanitized[e.event_id], zone) for e in ordered)
    start = events[0]  # validated start event, not the earliest timestamp
    close = next((e for e in events if e.event_name == "COSINE_SESSION_CLOSED"), None)
    choice = next((e.payload_display["choice"] for e in events if e.event_name in _CHOICES), None)
    minutes = next((e.payload_display["duration_minutes"] for e in events
                    if e.event_name == "BREAK_DURATION_COMMITTED"), None)
    hopper = tuple(CosineHopperTransition(
        e.payload_display["from_platform"], e.payload_display["to_platform"],
        PLATFORM_LABELS.get(e.payload_display["from_platform"], e.payload_display["from_platform"]),
        PLATFORM_LABELS.get(e.payload_display["to_platform"], e.payload_display["to_platform"]),
        e.sequence, e.occurred_at_utc, e.occurred_at_display, e.timezone_label,
    ) for e in events if e.event_name == "HOPPER_TRANSITION")
    reason = close.payload_display["closure_reason"] if close else None
    outcome = close.payload_display["closure_outcome"] if close else None
    held = reason == "SINE_HANDOFF" or outcome == "HANDOVER"
    return CosineEpisodeProjection(
        key[0], key[1], ordered[0].session_id, start.occurred_at_utc, start.occurred_at_display,
        close.occurred_at_utc if close else None, close.occurred_at_display if close else None,
        start.platform_key, start.platform_label, len(events), choice, minutes,
        len(hopper), hopper, reason, outcome, close is not None, events, held,
        "SINE/COSINE handoff: context only; interpretation on HOLD." if held else None,
    )


def project_cosine_events(events: tuple[CosineEvent, ...], *,
                          presentation_timezone: str = "local",
                          generated_at_utc: str | None = None) -> CosineAnalysisProjection:
    """Project a complete immutable event snapshot, never reading or writing it.

    Unsupported schemas and malformed evidence fail closed, with no partial
    counts/history. Empty valid input is available with zero snapshot counts.
    Invalid caller-supplied generation metadata raises TimezoneProjectionError.
    """
    stamp = _stamp(generated_at_utc)
    try:
        if not isinstance(presentation_timezone, str):
            raise TimezoneProjectionError("timezone must be a string")
        resolve_timezone(presentation_timezone)
    except (ValueError, TypeError):
        return _unavailable(stamp, presentation_timezone, "TIMEZONE_ERROR",
                            "Selected presentation timezone is unavailable.")
    if not isinstance(events, tuple):
        return _unavailable(stamp, presentation_timezone, "STRUCTURAL_ERROR",
                            "COSINE event source must supply an immutable tuple.",
                            issues=(CosineStructuralIssue("MALFORMED_SOURCE", "Expected tuple[CosineEvent, ...]."),))
    groups, sanitized, issues = defaultdict(list), {}, []
    for event in events:
        code, detail, safe = _validate_event(event)
        if code:
            issues.append(CosineStructuralIssue(code, detail))
            continue
        if event.event_id in sanitized:
            issues.append(CosineStructuralIssue("DUPLICATE_EVENT_ID", "Event ID occurs more than once.", event.event_id))
        sanitized[event.event_id] = safe
        groups[(event.cosine_session_id, event.generation)].append(event)
    for key in sorted(groups):
        issues.extend(_group_issues(key, groups[key]))
    if issues:
        issues.sort(key=lambda issue: (issue.code, issue.cosine_session_id, issue.generation or 0, issue.event_id))
        return _unavailable(stamp, presentation_timezone, "STRUCTURAL_ERROR",
                            "COSINE structural validation failed; snapshot facts withheld.", issues=issues)
    try:
        episodes = tuple(sorted(
            (_episode_projection(key, groups[key], sanitized, presentation_timezone) for key in sorted(groups)),
            key=lambda e: (parse_utc_timestamp(e.started_at_utc), e.cosine_session_id, e.generation),
            reverse=True,
        ))
    except (TimezoneProjectionError, OverflowError, OSError, ValueError):
        return _unavailable(stamp, presentation_timezone, "TIMEZONE_ERROR",
                            "UTC evidence could not be projected into the selected timezone.")
    latest = tuple(event for episode in episodes for event in reversed(episode.events))
    overview = CosineOverviewProjection(
        len(episodes), sum(e.event_name == "RETURN_CONFIRMED" for e in latest),
        sum(e.event_name == "BREAK_STARTED" for e in latest),
    )
    return CosineAnalysisProjection(
        True, stamp, presentation_timezone, overview, episodes, latest,
        episodes[0] if episodes else None, "AVAILABLE" if episodes else "EMPTY",
        "Facts from the database snapshot." if episodes else "No COSINE events in the database snapshot.",
        None, (),
    )


__all__ = [
    "CosineAnalysisProjection", "CosineEpisodeProjection", "CosineEventProjection",
    "CosineHopperTransition", "CosineOverviewProjection", "CosineStructuralIssue",
    "CosineEventReader", "CosineReadAuthority", "HELD_PRESENTATION_PAYLOAD_KEYS",
    "project_cosine_events",
]
