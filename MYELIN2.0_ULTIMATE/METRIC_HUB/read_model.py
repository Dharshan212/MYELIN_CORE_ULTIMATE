"""One coherent, read-only lifetime projection for the Metric Hub.

The projection is intentionally separate from MIRL's historical ``metric_hub``
contract.  It opens the canonical production database in SQLite ``mode=ro``,
starts one read transaction, loads every contributing ledger from that one
snapshot, validates the existing organ evidence, and closes the connection.
No schema bootstrap, migration, write API, timer, or Qt object is used here.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import types
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from COSECANT_STUDY_MODE.cosecant import COSECANT_SCHEMA_VERSION
from CORE_ENGINE.trigger import TRIGGER_SCHEMA_VERSION
from COSINE.cosine import (
    COSINE_SCHEMA_VERSION,
    PLATFORM_KEYS,
    CosineEvent,
    EventClass,
)
from COSINE.read_model import project_cosine_events
from MINE.mine import MINE_SCHEMA_VERSION, MineEvent, MineEventClass
from MINE.read_model import project_mine_events
from MIRL.mirl import MirlEvent, MirlEventClass, MirlEventName
from PERSISTENCE.database import SQLITE_BUSY_TIMEOUT_MS, database_path
from SINE.sine import SINE_SCHEMA_VERSION
from time_projection import parse_utc_timestamp


AVAILABLE: Final = "AVAILABLE"
NO_DATA: Final = "NO_DATA"
UNAVAILABLE: Final = "UNAVAILABLE"

_TRIGGER_SCHEMA_VERSIONS: Final = frozenset(
    {"myelin-trigger-v3", TRIGGER_SCHEMA_VERSION}
)
_SINE_SOCIAL_SURFACES: Final = frozenset(
    {"social", "youtube_watch", "selected_video", "youtube_shorts", "youtube_other"}
)

_SINE_STAGES: Final = frozenset({1, 2, 3})
# SINE's module documents the v1 -> v2 -> v3 changes as return-hold policy
# changes. The numbered factual SINE_DISPLAYED identity used by this KPI is
# stable across those durable generations.
_SINE_DISPLAY_SCHEMA_VERSIONS: Final = frozenset(
    {"myelin-sine-v1", "myelin-sine-v2", SINE_SCHEMA_VERSION}
)
_MINE_STAGES: Final = frozenset(
    {"MINE1_DISPLAYED", "MINE2A_DISPLAYED", "MINE2B_DISPLAYED"}
)
_COSINE_STAGES: Final = frozenset(
    {"INTENT_GATE_DISPLAYED", "BREAK_ACK_DISPLAYED", "FINAL_CALLBACK_DISPLAYED"}
)
_COSECANT_STAGES: Final = frozenset(
    {"BREAK_COMPLETE", "BREAK_ALREADY_OVER", "FINAL_LOCKED"}
)
_MINE_RETURN_OUTCOMES: Final = frozenset(
    {
        "RETURNED_AFTER_INTENT",
        "EARLY_RETURN_DURING_IMPORTANT_ALLOWANCE",
        "RETURNED_AFTER_CALLBACK",
    }
)
_COSINE_RETURN_OUTCOMES: Final = frozenset(
    {"RETURNED_AFTER_INTENT", "EARLY_RETURN", "RETURNED_AFTER_CALLBACK"}
)


@dataclass(frozen=True, slots=True)
class MetricValue:
    status: str
    value: int | None
    reason: str
    evidence_unit: str
    source_count: int | None = None

    def __post_init__(self) -> None:
        if self.status not in {AVAILABLE, UNAVAILABLE}:
            raise ValueError("metric status must be AVAILABLE or UNAVAILABLE")
        if self.status == AVAILABLE:
            if type(self.value) is not int or self.value < 0:
                raise ValueError("available metric requires a non-negative integer")
        elif self.value is not None:
            raise ValueError("unavailable metric cannot carry a number")

    @property
    def available(self) -> bool:
        return self.status == AVAILABLE


@dataclass(frozen=True, slots=True)
class OrganMetric:
    organ: str
    triggers: MetricValue
    returned: MetricValue
    trigger_disclosure: str
    return_disclosure: str


@dataclass(frozen=True, slots=True)
class SessionOrganMetric:
    """One organ's approved contributions inside one genuine parent session."""

    triggers: MetricValue
    returned: MetricValue


@dataclass(frozen=True, slots=True)
class SessionMetricRow:
    """Immutable chart-source row; presentation may format but not recalculate it."""

    session_id: int
    ordinal: int
    order_key: tuple[str, int]
    started_at_utc: str
    closed_at_utc: str | None
    is_closed: bool
    sine: SessionOrganMetric
    cosine: SessionOrganMetric
    mine: SessionOrganMetric
    cosecant: SessionOrganMetric
    combined_triggers: MetricValue
    combined_returned: MetricValue

    @property
    def available(self) -> bool:
        return self.combined_triggers.available and self.combined_returned.available


@dataclass(frozen=True, slots=True)
class PieExclusion:
    reason_code: str
    count: int

    def __post_init__(self) -> None:
        if not self.reason_code or type(self.count) is not int or self.count <= 0:
            raise ValueError("pie exclusion requires a reason code and positive count")


@dataclass(frozen=True, slots=True)
class BehaviourDistributionProjection:
    """Chart-ready episode distribution; values are never inferred in Qt."""

    status: str
    social_count: int | None
    ott_count: int | None
    messaging_count: int | None
    eligible_total: int | None
    social_percent: float | None
    ott_percent: float | None
    messaging_percent: float | None
    excluded_identity_count: int
    exclusions: tuple[PieExclusion, ...]
    source_explanation: str
    status_message: str

    def __post_init__(self) -> None:
        if self.status not in {AVAILABLE, NO_DATA, UNAVAILABLE}:
            raise ValueError("pie status must be AVAILABLE, NO_DATA or UNAVAILABLE")
        if type(self.excluded_identity_count) is not int or self.excluded_identity_count < 0:
            raise ValueError("pie excluded identity count must be non-negative")
        if sum(item.count for item in self.exclusions) != self.excluded_identity_count:
            raise ValueError("pie exclusion summary does not reconcile")

        counts = (self.social_count, self.ott_count, self.messaging_count)
        percentages = (
            self.social_percent,
            self.ott_percent,
            self.messaging_percent,
        )
        if self.status == UNAVAILABLE:
            if self.eligible_total is not None or any(value is not None for value in counts):
                raise ValueError("unavailable pie cannot carry episode counts")
            if any(value is not None for value in percentages):
                raise ValueError("unavailable pie cannot carry percentages")
            return

        if any(type(value) is not int or value < 0 for value in counts):
            raise ValueError("available pie counts must be non-negative integers")
        if type(self.eligible_total) is not int or self.eligible_total < 0:
            raise ValueError("available pie requires a non-negative total")
        if sum(counts) != self.eligible_total:
            raise ValueError("pie category counts do not reconcile to the total")
        if self.status == NO_DATA:
            if self.eligible_total != 0 or any(value is not None for value in percentages):
                raise ValueError("NO_DATA pie has zero counts and no percentages")
            return
        if self.eligible_total <= 0:
            raise ValueError("AVAILABLE pie requires positive eligible evidence")
        if any(type(value) not in {int, float} or value < 0 for value in percentages):
            raise ValueError("AVAILABLE pie requires non-negative percentages")
        if abs(sum(float(value) for value in percentages) - 100.0) > 1e-8:
            raise ValueError("pie percentages do not conserve 100 percent")


@dataclass(frozen=True, slots=True)
class LifetimeMetricHubProjection:
    sessions: MetricValue
    total_triggers: MetricValue
    total_returned: MetricValue
    sine: OrganMetric
    cosine: OrganMetric
    mine: OrganMetric
    cosecant: OrganMetric
    behaviour_distribution: BehaviourDistributionProjection
    generated_at_utc: str
    snapshot_id: str
    source_path: str
    read_only: bool
    status: str
    status_message: str
    session_rows: tuple[SessionMetricRow, ...] = ()
    session_series_status: str = UNAVAILABLE
    session_series_message: str = "Session series is unavailable."

    @property
    def available(self) -> bool:
        return (
            self.sessions.available
            and self.total_triggers.available
            and self.total_returned.available
        )

    @property
    def organs(self) -> tuple[OrganMetric, ...]:
        return (self.sine, self.cosine, self.mine, self.cosecant)

    @property
    def session_series_available(self) -> bool:
        return self.session_series_status == AVAILABLE


class _SourceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class _SineDisplay:
    row_id: int
    session_id: int
    episode_uid: str
    candidate_uid: str
    stage: int
    popup_request_id: str
    occurred_monotonic_ns: int
    occurred_wall_time_utc: str


@dataclass(frozen=True, slots=True)
class _TriggerEvidence:
    session_id: int
    candidate_uid: str
    occurred_monotonic_ns: int
    reason: str
    source: str
    source_rule_id: str
    source_policy_version: str
    platform_key: str
    surface_class: str
    study_context_token: str
    evidence_digest: str
    model_category: str


@dataclass(frozen=True, slots=True)
class _SessionSource:
    session_id: int
    order_key: tuple[str, int]
    started_at_utc: str
    closed_at_utc: str | None


@dataclass(frozen=True, slots=True)
class _OrganEvidence:
    metric: OrganMetric
    trigger_session_ids: tuple[int, ...] | None
    return_session_ids: tuple[int, ...] | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _scoped_sine_return_samples(events: tuple[MirlEvent, ...]):
    """Load and invoke the frozen Chapter 6 validator without requiring Qt.

    The desktop application has already imported the real ``SCIENCE_LAB``
    package. Standalone backend tests may not have PyQt6, so they use the same
    lightweight namespace technique as the existing pure Chapter 6 tests;
    the actual validator module and ``analysis.py`` are still loaded verbatim.
    """

    created_namespace = "SCIENCE_LAB" not in sys.modules
    modules_before = set(sys.modules)
    if created_namespace:
        package = types.ModuleType("SCIENCE_LAB")
        package.__path__ = [str(Path(__file__).resolve().parents[1] / "SCIENCE_LAB")]
        sys.modules["SCIENCE_LAB"] = package
    try:
        from SCIENCE_LAB.chapter6_lifetime import (
            _lifetime_successful_return_onset_latency_samples,
        )

        return _lifetime_successful_return_onset_latency_samples(events)
    finally:
        # Do not let the Qt-free standalone-test shim shadow the real package
        # if a caller imports the desktop application later in the process.
        if created_namespace:
            for module_name in tuple(sys.modules):
                if (
                    module_name == "SCIENCE_LAB"
                    or module_name.startswith("SCIENCE_LAB.")
                ) and module_name not in modules_before:
                    sys.modules.pop(module_name, None)


def _available(
    value: int,
    reason: str,
    evidence_unit: str,
    *,
    source_count: int | None = None,
) -> MetricValue:
    return MetricValue(AVAILABLE, value, reason, evidence_unit, source_count)


def _unavailable(reason: str, evidence_unit: str) -> MetricValue:
    return MetricValue(UNAVAILABLE, None, reason, evidence_unit)


def _unavailable_organ(organ: str, reason: str) -> OrganMetric:
    return OrganMetric(
        organ,
        _unavailable(reason, "approved stage identity per genuine episode/break"),
        _unavailable(reason, "validated behavioural return per genuine episode/break"),
        reason,
        reason,
    )


def _unavailable_evidence(organ: str, reason: str) -> _OrganEvidence:
    return _OrganEvidence(_unavailable_organ(organ, reason), None, None)


def _bounded(error: BaseException) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:300]


def _required_table(
    connection: sqlite3.Connection,
    table: str,
    columns: tuple[str, ...],
    query: str,
) -> tuple[sqlite3.Row, ...]:
    found = {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if not found:
        raise _SourceError(f"required table {table} is missing")
    missing = sorted(set(columns) - found)
    if missing:
        raise _SourceError(f"{table} is missing columns: {', '.join(missing)}")
    return tuple(connection.execute(query).fetchall())


def _json_object(text: object, *, source: str) -> dict:
    try:
        value = json.loads(str(text))
    except (TypeError, ValueError, RecursionError) as exc:
        raise _SourceError(f"{source} contains malformed JSON") from exc
    if not isinstance(value, dict):
        raise _SourceError(f"{source} payload is not an object")
    return value


def _canonical_utc(value: object, *, field: str) -> tuple[str, datetime]:
    try:
        moment = parse_utc_timestamp(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise _SourceError(f"sessions contains an invalid {field}") from exc
    return (
        moment.astimezone(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
        moment,
    )


def _session_population(
    rows: tuple[sqlite3.Row, ...],
) -> tuple[MetricValue, set[int], tuple[_SessionSource, ...]]:
    identities: list[int] = []
    sources: list[tuple[datetime, _SessionSource]] = []
    for row in rows:
        value = row["id"]
        if type(value) is not int or value <= 0:
            raise _SourceError("sessions contains an invalid primary key")
        started_text, started = _canonical_utc(
            row["started_at_utc"], field="started_at_utc"
        )
        raw_closed = row["closed_at_utc"]
        closed_text: str | None = None
        if raw_closed is not None:
            if not str(raw_closed).strip():
                raise _SourceError("sessions contains an empty closed_at_utc")
            closed_text, closed = _canonical_utc(raw_closed, field="closed_at_utc")
            if closed < started:
                raise _SourceError("session closes before it starts")
        identities.append(value)
        sources.append(
            (
                started,
                _SessionSource(
                    session_id=value,
                    order_key=(started_text, value),
                    started_at_utc=started_text,
                    closed_at_utc=closed_text,
                ),
            )
        )
    if len(identities) != len(set(identities)):
        raise _SourceError("sessions contains duplicate primary keys")
    ordered = tuple(
        source for _started, source in sorted(sources, key=lambda item: (item[0], item[1].session_id))
    )
    return (
        _available(
            len(identities),
            "All committed parent session identities, including open sessions.",
            "distinct sessions.id",
            source_count=len(rows),
        ),
        set(identities),
        ordered,
    )


def _sine_displays(
    rows: tuple[sqlite3.Row, ...], session_ids: set[int]
) -> tuple[_SineDisplay, ...]:
    displays: list[_SineDisplay] = []
    seen_rows: set[int] = set()
    for row in rows:
        if str(row["kind"]) != "SINE_DISPLAYED":
            continue
        row_id = row["id"]
        session_id = row["session_id"]
        episode_uid = str(row["episode_uid"] or "")
        candidate_uid = str(row["candidate_uid"] or "")
        popup_request_id = str(row["popup_request_id"] or "")
        occurred_ns = row["occurred_monotonic_ns"]
        payload = _json_object(row["payload_json"], source="sine_facts")
        stage = payload.get("stage")
        wall_time = payload.get("occurred_wall_time_utc")
        if (
            type(row_id) is not int
            or row_id <= 0
            or row_id in seen_rows
            or type(session_id) is not int
            or session_id not in session_ids
            or not episode_uid
            or not candidate_uid
            or not popup_request_id
            or type(occurred_ns) is not int
            or occurred_ns < 0
            or type(stage) is not int
            or stage not in _SINE_STAGES
            or type(wall_time) is not str
            or not wall_time
            or payload.get("kind") != "SINE_DISPLAYED"
            or payload.get("session_id") != session_id
            or payload.get("episode_uid") != episode_uid
            or payload.get("candidate_uid") != candidate_uid
            or payload.get("popup_request_id") != popup_request_id
            or payload.get("occurred_monotonic_ns") != occurred_ns
            or payload.get("schema_version") not in _SINE_DISPLAY_SCHEMA_VERSIONS
        ):
            raise _SourceError(f"invalid SINE display evidence at row {row_id}")
        parse_utc_timestamp(wall_time)
        seen_rows.add(row_id)
        displays.append(
            _SineDisplay(
                row_id,
                session_id,
                episode_uid,
                candidate_uid,
                stage,
                popup_request_id,
                occurred_ns,
                wall_time,
            )
        )

    episode_parent: dict[str, int] = {}
    candidate_episode: dict[tuple[int, str], str] = {}
    for display in displays:
        parent = episode_parent.setdefault(display.episode_uid, display.session_id)
        if parent != display.session_id:
            raise _SourceError("one SINE episode identity spans parent sessions")
        candidate_key = (display.session_id, display.candidate_uid)
        episode = candidate_episode.setdefault(candidate_key, display.episode_uid)
        if episode != display.episode_uid:
            raise _SourceError("one SINE candidate maps to multiple genuine episodes")

    return tuple(displays)


def _sine_trigger_metric(
    displays: tuple[_SineDisplay, ...],
) -> tuple[MetricValue, tuple[int, ...]]:
    slots = {
        (display.session_id, display.episode_uid, display.stage)
        for display in displays
    }
    return (
        _available(
            len(slots),
            "Numbered SINE-1/2/3 stages, once per genuine episode and stage; "
            "stage-0 post-break gates and same-episode reappearances are excluded.",
            "numbered SINE stage first appearance per genuine episode",
            source_count=len(displays),
        ),
        tuple(sorted(session_id for session_id, _episode, _stage in slots)),
    )


def _mirl_events(rows: tuple[sqlite3.Row, ...]) -> tuple[MirlEvent, ...]:
    events: list[MirlEvent] = []
    seen: set[str] = set()
    for row in rows:
        payload = _json_object(row["payload_json"], source="mirl_events")
        event_id = str(payload.get("event_id") or "")
        if (
            not event_id
            or event_id in seen
            or event_id != str(row["event_id"])
            or str(payload.get("episode_id") or "") != str(row["episode_id"])
            or payload.get("episode_sequence") != row["episode_sequence"]
            or str(payload.get("event_name") or "") != str(row["event_name"])
            or payload.get("occurred_monotonic_ns") != row["occurred_monotonic_ns"]
            or payload.get("session_id") != row["session_id"]
        ):
            raise _SourceError(f"MIRL row identity mismatch at {row['event_id']}")
        try:
            event = MirlEvent(
                kind=str(payload["kind"]),
                event_name=MirlEventName(str(payload["event_name"])),
                event_class=MirlEventClass(str(payload["event_class"])),
                event_id=event_id,
                episode_id=str(payload["episode_id"]),
                episode_sequence=int(payload["episode_sequence"]),
                occurred_monotonic_ns=int(payload["occurred_monotonic_ns"]),
                occurred_wall_time_utc=str(payload["occurred_wall_time_utc"]),
                session_id=(
                    int(payload["session_id"])
                    if payload.get("session_id") is not None
                    else None
                ),
                candidate_uid=str(payload.get("candidate_uid", "")),
                operational_event_id=(
                    int(payload["operational_event_id"])
                    if payload.get("operational_event_id") is not None
                    else None
                ),
                attempt_id=str(payload.get("attempt_id", "")),
                attempt_index=int(payload.get("attempt_index", 0)),
                sine_stage=int(payload.get("sine_stage", 0)),
                sine_occurrence=int(payload.get("sine_occurrence", 0)),
                reason=str(payload.get("reason", "")),
                response=str(payload.get("response", "")),
                elapsed_seconds=float(payload.get("elapsed_seconds", 0.0)),
                target_seconds=float(payload.get("target_seconds", 0.0)),
                supporting_event_ids=tuple(payload.get("supporting_event_ids", ())),
                detail=str(payload.get("detail", "")),
                schema_version=str(payload.get("schema_version", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise _SourceError(f"invalid MIRL event {event_id}") from exc
        seen.add(event_id)
        events.append(event)
    return tuple(events)


def _sine_return_metric(
    displays: tuple[_SineDisplay, ...],
    mirl_events: tuple[MirlEvent, ...],
    session_ids: set[int],
) -> tuple[MetricValue, tuple[int, ...]]:
    samples, skipped = _scoped_sine_return_samples(mirl_events)
    if skipped:
        raise _SourceError(
            f"scoped Chapter 6 validation excluded {skipped} returned episode(s)"
        )

    events_by_episode: dict[str, list[MirlEvent]] = {}
    for event in mirl_events:
        events_by_episode.setdefault(event.episode_id, []).append(event)
    stage1_by_join: dict[tuple[int, str, str], set[str]] = {}
    for display in displays:
        if display.stage == 1:
            key = (
                display.session_id,
                display.candidate_uid,
                display.occurred_wall_time_utc,
            )
            stage1_by_join.setdefault(key, set()).add(display.episode_uid)

    mapped: dict[str, tuple[int, str]] = {}
    sine_owner: dict[str, str] = {}
    for sample in samples:
        episode_events = events_by_episode.get(sample.episode_id, [])
        created = [
            event
            for event in episode_events
            if event.event_name is MirlEventName.EPISODE_CREATED
        ]
        if len(created) != 1:
            raise _SourceError("validated MIRL return lacks one episode-created identity")
        origin = created[0]
        if (
            type(origin.session_id) is not int
            or origin.session_id not in session_ids
            or not origin.candidate_uid
        ):
            raise _SourceError("validated MIRL return lacks a valid parent/candidate")
        key = (
            origin.session_id,
            origin.candidate_uid,
            origin.occurred_wall_time_utc,
        )
        matches = stage1_by_join.get(key, set())
        if len(matches) != 1:
            raise _SourceError(
                "validated MIRL return cannot map uniquely to its genuine SINE episode"
            )
        sine_episode = next(iter(matches))
        previous_mirl = sine_owner.setdefault(sine_episode, sample.episode_id)
        if previous_mirl != sample.episode_id:
            raise _SourceError("multiple MIRL episodes map to one SINE episode")
        mapped[sample.episode_id] = (origin.session_id, sine_episode)

    returned_slots = set(mapped.values())
    return (
        _available(
            len(returned_slots),
            "Scoped Chapter 6 durable return-chain validation, mapped to genuine "
            "SINE episodes. This does not resolve global MIRL degradation.",
            "scoped Chapter 6 validated returned SINE episode",
            source_count=len(samples),
        ),
        tuple(sorted(session_id for session_id, _episode in returned_slots)),
    )


def _mine_events(rows: tuple[sqlite3.Row, ...]) -> tuple[MineEvent, ...]:
    events: list[MineEvent] = []
    for row in rows:
        try:
            events.append(
                MineEvent(
                    event_id=str(row["event_id"]),
                    parent_session_id=int(row["session_id"]),
                    mine_episode_id=str(row["mine_episode_id"]),
                    sequence=int(row["sequence"]),
                    event_name=str(row["event_name"]),
                    event_class=MineEventClass(str(row["event_class"])),
                    occurred_at_utc=str(row["occurred_at_utc"]),
                    monotonic_ns=int(row["monotonic_ns"]),
                    generation=int(row["generation"]),
                    platform_key=str(row["platform_key"]),
                    platform_label=str(row["platform_label"]),
                    request_id=str(row["request_id"]),
                    evidence_token=str(row["evidence_token"]),
                    payload_json=str(row["payload_json"]),
                    schema_version=str(row["schema_version"]),
                )
            )
        except (TypeError, ValueError) as exc:
            raise _SourceError("MINE row cannot be reconstructed") from exc
    return tuple(events)


def _mine_metric(
    rows: tuple[sqlite3.Row, ...], session_ids: set[int], stamp: str
) -> _OrganEvidence:
    events = _mine_events(rows)
    if any(event.parent_session_id not in session_ids for event in events):
        raise _SourceError("MINE contains an invalid parent session")
    projection = project_mine_events(
        events, presentation_timezone="local", generated_at_utc=stamp
    )
    if not projection.available:
        raise _SourceError(f"MINE validation failed: {projection.status}")

    slots: set[tuple[int, int, str, str]] = set()
    returned: set[tuple[int, int, str]] = set()
    for episode in projection.episodes:
        identity = (episode.session_id, episode.generation, episode.mine_episode_id)
        for event in episode.events:
            if (
                event.event_name in _MINE_STAGES
                and event.event_class == MineEventClass.PRESENTATION.value
            ):
                slots.add((*identity, event.event_name))
        confirmations = [
            event for event in episode.events if event.event_name == "RETURN_CONFIRMED"
        ]
        if len(confirmations) > 1:
            raise _SourceError("MINE episode has multiple return confirmations")
        if confirmations:
            closes = [
                event
                for event in episode.events
                if event.event_name == "MINE_SESSION_CLOSED"
            ]
            confirmed = confirmations[0]
            if len(closes) != 1:
                raise _SourceError("MINE confirmed return lacks one closure")
            close = closes[0]
            outcome = str(confirmed.payload_facts.get("closure_outcome", ""))
            if (
                confirmed.event_class != MineEventClass.DERIVED.value
                or close.sequence <= confirmed.sequence
                or close.payload_facts.get("closure_reason") != "VERIFIED_RETURN"
                or close.payload_facts.get("closure_outcome") != outcome
                or outcome not in _MINE_RETURN_OUTCOMES
            ):
                raise _SourceError("MINE return/closure proof is inconsistent")
            returned.add(identity)

    return _OrganEvidence(
        OrganMetric(
            "MINE",
            _available(
                len(slots),
                "MINE1/MINE2A/MINE2B presentation stages, once per episode and stage.",
                "validated MINE presentation stage per genuine episode/generation",
                source_count=sum(
                    event.event_name in _MINE_STAGES
                    and event.event_class is MineEventClass.PRESENTATION
                    for event in events
                ),
            ),
            _available(
                len(returned),
                "RETURN_CONFIRMED with matching successful same-episode closure.",
                "validated returned MINE episode",
                source_count=len(returned),
            ),
            "Validated MINE presentation stages; restorations do not add a stage slot.",
            "Confirmed same-episode return and successful closure.",
        ),
        tuple(
            sorted(
                session_id
                for session_id, _generation, _episode, _stage in slots
            )
        ),
        tuple(
            sorted(
                session_id for session_id, _generation, _episode in returned
            )
        ),
    )


def _cosine_events(rows: tuple[sqlite3.Row, ...]) -> tuple[CosineEvent, ...]:
    events: list[CosineEvent] = []
    for row in rows:
        try:
            events.append(
                CosineEvent(
                    event_id=str(row["event_id"]),
                    session_id=(
                        int(row["session_id"])
                        if row["session_id"] is not None
                        else None
                    ),
                    cosine_session_id=str(row["cosine_session_id"]),
                    sequence=int(row["sequence"]),
                    event_name=str(row["event_name"]),
                    event_class=EventClass(str(row["event_class"])),
                    occurred_at_utc=str(row["occurred_at_utc"]),
                    monotonic_ns=int(row["monotonic_ns"]),
                    generation=int(row["generation"]),
                    platform_key=str(row["platform_key"]),
                    content_title=str(row["content_title"]),
                    request_id=str(row["request_id"]),
                    evidence_token=str(row["evidence_token"]),
                    payload_json=str(row["payload_json"]),
                    schema_version=str(row["schema_version"]),
                )
            )
        except (TypeError, ValueError) as exc:
            raise _SourceError("COSINE row cannot be reconstructed") from exc
    return tuple(events)


def _cosine_metric(
    rows: tuple[sqlite3.Row, ...], session_ids: set[int], stamp: str
) -> _OrganEvidence:
    events = _cosine_events(rows)
    if any(
        type(event.session_id) is not int or event.session_id not in session_ids
        for event in events
    ):
        raise _SourceError("COSINE contains an invalid parent session")
    projection = project_cosine_events(
        events, presentation_timezone="local", generated_at_utc=stamp
    )
    if not projection.available:
        raise _SourceError(f"COSINE validation failed: {projection.status}")

    slots: set[tuple[int, str, int, str]] = set()
    returned: set[tuple[int, str, int]] = set()
    for episode in projection.episodes:
        if type(episode.parent_session_id) is not int:
            raise _SourceError("COSINE episode lacks a parent session")
        identity = (
            episode.parent_session_id,
            episode.cosine_session_id,
            episode.generation,
        )
        for event in episode.events:
            if (
                event.event_name in _COSINE_STAGES
                and event.event_class == EventClass.PRESENTATION.value
            ):
                slots.add((*identity, event.event_name))
        confirmations = [
            event for event in episode.events if event.event_name == "RETURN_CONFIRMED"
        ]
        if len(confirmations) > 1:
            raise _SourceError("COSINE episode has multiple return confirmations")
        if confirmations:
            closes = [
                event
                for event in episode.events
                if event.event_name == "COSINE_SESSION_CLOSED"
            ]
            confirmed = confirmations[0]
            if len(closes) != 1:
                raise _SourceError("COSINE confirmed return lacks one closure")
            close = closes[0]
            outcome = str(confirmed.payload_display.get("closure_outcome", ""))
            if (
                confirmed.event_class != EventClass.DERIVED.value
                or close.sequence <= confirmed.sequence
                or close.payload_display.get("closure_reason") != "RETURN_CONFIRMED"
                or close.payload_display.get("closure_outcome") != outcome
                or outcome not in _COSINE_RETURN_OUTCOMES
            ):
                raise _SourceError("COSINE return/closure proof is inconsistent")
            returned.add(identity)

    return _OrganEvidence(
        OrganMetric(
            "COSINE",
            _available(
                len(slots),
                "PARTIAL: explicit acknowledged INTENT_GATE, BREAK_ACK and FINAL_CALLBACK "
                "displays only; duration-popup visibility is not evidenced.",
                "acknowledged COSINE presentation stage per genuine episode/generation",
                source_count=sum(
                    event.event_name in _COSINE_STAGES
                    and event.event_class is EventClass.PRESENTATION
                    for event in events
                ),
            ),
            _available(
                len(returned),
                "RETURN_CONFIRMED with matching successful OTT episode closure.",
                "validated returned COSINE episode",
                source_count=len(returned),
            ),
            "PARTIAL — acknowledged displays only; duration-popup visibility unsupported.",
            "Confirmed same-episode return; handovers and intent are excluded.",
        ),
        tuple(
            sorted(
                session_id
                for session_id, _episode, _generation, _stage in slots
            )
        ),
        tuple(
            sorted(
                session_id for session_id, _episode, _generation in returned
            )
        ),
    )


_PIE_SOURCE_EXPLANATION: Final = (
    "One episode per documented first display: SINE-1 joined to its accepted "
    "trigger, MINE-1 joined to same-generation messaging evidence, and COSINE "
    "intent-gate display joined to same-episode certified OTT evidence."
)


def _pie_exclusions(counter: Counter[str]) -> tuple[PieExclusion, ...]:
    return tuple(
        PieExclusion(code, count)
        for code, count in sorted(counter.items())
        if count > 0
    )


def _unavailable_behaviour_distribution(
    reason: str,
    exclusions: Counter[str] | None = None,
) -> BehaviourDistributionProjection:
    summary = _pie_exclusions(exclusions or Counter())
    return BehaviourDistributionProjection(
        UNAVAILABLE,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        sum(item.count for item in summary),
        summary,
        _PIE_SOURCE_EXPLANATION,
        reason,
    )


def _completed_behaviour_distribution(
    *,
    social: int,
    ott: int,
    messaging: int,
    exclusions: Counter[str],
) -> BehaviourDistributionProjection:
    counts = (social, ott, messaging)
    if any(type(value) is not int or value < 0 for value in counts):
        raise _SourceError("pie category count is invalid")
    total = sum(counts)
    summary = _pie_exclusions(exclusions)
    excluded = sum(item.count for item in summary)
    if total == 0:
        return BehaviourDistributionProjection(
            NO_DATA,
            social,
            ott,
            messaging,
            0,
            None,
            None,
            None,
            excluded,
            summary,
            _PIE_SOURCE_EXPLANATION,
            "No documented distraction-intervention episodes.",
        )
    return BehaviourDistributionProjection(
        AVAILABLE,
        social,
        ott,
        messaging,
        total,
        100.0 * social / total,
        100.0 * ott / total,
        100.0 * messaging / total,
        excluded,
        summary,
        _PIE_SOURCE_EXPLANATION,
        "Documented distraction-intervention episode distribution is available.",
    )


def _trigger_evidence(
    rows: tuple[sqlite3.Row, ...], session_ids: set[int]
) -> dict[tuple[int, str], _TriggerEvidence]:
    result: dict[tuple[int, str], _TriggerEvidence] = {}
    seen_rows: set[int] = set()
    for row in rows:
        row_id = row["id"]
        session_id = row["session_id"]
        candidate_uid = str(row["candidate_uid"] or "")
        occurred_ns = row["occurred_monotonic_ns"]
        payload = _json_object(row["payload_json"], source="triggers")
        evidence = payload.get("evidence")
        recovery = payload.get("recovery_model")
        if (
            type(row_id) is not int
            or row_id <= 0
            or row_id in seen_rows
            or type(session_id) is not int
            or session_id not in session_ids
            or not candidate_uid
            or type(occurred_ns) is not int
            or occurred_ns <= 0
            or payload.get("candidate_uid") != candidate_uid
            or payload.get("session_id") != session_id
            or payload.get("trigger") is not True
            or payload.get("schema_version") not in _TRIGGER_SCHEMA_VERSIONS
            or not isinstance(evidence, Mapping)
            or evidence.get("observed_monotonic_ns") != occurred_ns
            or not isinstance(recovery, Mapping)
        ):
            raise _SourceError(f"invalid accepted trigger evidence at row {row_id}")
        key = (session_id, candidate_uid)
        if key in result:
            raise _SourceError("accepted trigger identity is duplicated")
        seen_rows.add(row_id)
        result[key] = _TriggerEvidence(
            session_id,
            candidate_uid,
            occurred_ns,
            str(payload.get("reason") or ""),
            str(evidence.get("source") or ""),
            str(evidence.get("source_rule_id") or ""),
            str(evidence.get("source_policy_version") or ""),
            str(evidence.get("platform_key") or "").strip().casefold(),
            str(evidence.get("surface_class") or "").strip().casefold(),
            str(evidence.get("study_context_token") or ""),
            str(evidence.get("evidence_digest") or ""),
            str(recovery.get("model_category") or "").strip().casefold(),
        )
    return result


def _sine_social_episode_count(
    displays: tuple[_SineDisplay, ...],
    triggers: dict[tuple[int, str], _TriggerEvidence],
    exclusions: Counter[str],
) -> int:
    grouped: dict[tuple[int, str], list[_SineDisplay]] = {}
    represented_candidates: set[tuple[int, str]] = set()
    for display in displays:
        if display.stage != 1:
            continue
        grouped.setdefault((display.session_id, display.episode_uid), []).append(display)
        represented_candidates.add((display.session_id, display.candidate_uid))

    eligible = 0
    for identity, episode_displays in grouped.items():
        candidates = {display.candidate_uid for display in episode_displays}
        if len(candidates) != 1:
            exclusions["SINE_AMBIGUOUS_IDENTITY"] += 1
            continue
        candidate_uid = next(iter(candidates))
        trigger = triggers.get((identity[0], candidate_uid))
        if trigger is None:
            exclusions["SINE_TRIGGER_MISSING"] += 1
            continue
        if not trigger.evidence_digest or not trigger.source_rule_id or not trigger.source_policy_version:
            exclusions["SINE_TRIGGER_INCOMPLETE"] += 1
            continue
        if (
            not trigger.platform_key
            or trigger.platform_key == "unknown"
            or trigger.surface_class not in _SINE_SOCIAL_SURFACES
            or trigger.surface_class in {"activity", "messaging", "cosine"}
            or trigger.model_category == "activity"
            or trigger.platform_key in PLATFORM_KEYS
        ):
            exclusions["SINE_CATEGORY_UNSUPPORTED"] += 1
            continue
        if trigger.source == "study_off_task":
            valid_context = (
                trigger.reason == "study_off_task_dwell"
                and trigger.source_rule_id == "RI-STUDY-OFF-TASK-READY-001"
                and bool(trigger.study_context_token)
            )
        elif trigger.source == "executive_blacklist":
            valid_context = (
                trigger.reason == "executive_blacklist_dwell"
                and trigger.source_rule_id.startswith("EB-")
            )
        else:
            valid_context = False
        if not valid_context:
            exclusions["SINE_CONTEXT_UNSUPPORTED"] += 1
            continue
        eligible += 1

    for key in triggers:
        if key not in represented_candidates:
            exclusions["SINE_NOT_DISPLAYED"] += 1
    return eligible


def _mine_messaging_episode_count(
    events: tuple[MineEvent, ...],
    stamp: str,
    exclusions: Counter[str],
) -> int:
    projection = project_mine_events(
        events, presentation_timezone="local", generated_at_utc=stamp
    )
    if not projection.available:
        raise _SourceError(f"MINE pie validation failed: {projection.status}")
    groups: dict[tuple[int, int], list[MineEvent]] = {}
    for event in events:
        groups.setdefault((event.parent_session_id, event.generation), []).append(event)

    eligible = 0
    seen: set[tuple[int, int, str]] = set()
    for episode in projection.episodes:
        identity = (episode.session_id, episode.generation, episode.mine_episode_id)
        if identity in seen:
            exclusions["MINE_DUPLICATE_IDENTITY"] += 1
            continue
        seen.add(identity)
        ordered = sorted(groups[(episode.session_id, episode.generation)], key=lambda event: event.sequence)
        candidates = [event for event in ordered if event.event_name == "MINE_CANDIDATE_STARTED"]
        entered = [event for event in ordered if event.event_name == "MESSAGING_PLATFORM_ENTERED"]
        displays = [event for event in ordered if event.event_name == "MINE1_DISPLAYED"]
        starts = [event for event in ordered if event.event_name == "MINE_EPISODE_STARTED"]
        if not (len(candidates) == len(entered) == len(displays) == len(starts) == 1):
            exclusions["MINE_LINEAGE_AMBIGUOUS"] += 1
            continue
        candidate, platform_entered, display, episode_start = (
            candidates[0], entered[0], displays[0], starts[0]
        )
        if (
            candidate.event_class is not MineEventClass.OBSERVED
            or platform_entered.event_class is not MineEventClass.OBSERVED
            or display.event_class is not MineEventClass.PRESENTATION
            or episode_start.event_class is not MineEventClass.DERIVED
            or not (
                candidate.sequence < platform_entered.sequence < display.sequence < episode_start.sequence
            )
            or display.mine_episode_id != episode.mine_episode_id
            or episode_start.mine_episode_id != episode.mine_episode_id
            or not display.request_id
            or display.request_id != episode_start.request_id
        ):
            exclusions["MINE_LINEAGE_INVALID"] += 1
            continue
        if (
            not candidate.platform_key
            or candidate.platform_key != platform_entered.platform_key
            or not candidate.evidence_token
            or candidate.evidence_token != platform_entered.evidence_token
        ):
            exclusions["MINE_PLATFORM_AMBIGUOUS"] += 1
            continue
        current_platform = platform_entered.platform_key
        for event in ordered:
            if event.sequence >= display.sequence:
                break
            if event.event_name != "MESSAGING_PLATFORM_TRANSITION":
                continue
            payload = _json_object(event.payload_json, source="mine_events")
            if (
                payload.get("from_platform") != current_platform
                or payload.get("to_platform") != event.platform_key
                or not event.platform_key
                or not event.evidence_token
            ):
                current_platform = ""
                break
            current_platform = event.platform_key
        if not current_platform:
            exclusions["MINE_PLATFORM_AMBIGUOUS"] += 1
            continue
        eligible += 1
    return eligible


def _cosine_ott_episode_count(
    events: tuple[CosineEvent, ...],
    stamp: str,
    exclusions: Counter[str],
) -> int:
    projection = project_cosine_events(
        events, presentation_timezone="local", generated_at_utc=stamp
    )
    if not projection.available:
        raise _SourceError(f"COSINE pie validation failed: {projection.status}")
    groups: dict[tuple[str, int], list[CosineEvent]] = {}
    for event in events:
        groups.setdefault((event.cosine_session_id, event.generation), []).append(event)

    eligible = 0
    seen: set[tuple[int, str, int]] = set()
    for episode in projection.episodes:
        if type(episode.parent_session_id) is not int:
            exclusions["COSINE_PARENT_MISSING"] += 1
            continue
        identity = (
            episode.parent_session_id,
            episode.cosine_session_id,
            episode.generation,
        )
        if identity in seen:
            exclusions["COSINE_DUPLICATE_IDENTITY"] += 1
            continue
        seen.add(identity)
        ordered = sorted(
            groups[(episode.cosine_session_id, episode.generation)],
            key=lambda event: event.sequence,
        )
        starts = [event for event in ordered if event.event_name == "COSINE_SESSION_STARTED"]
        entered = [event for event in ordered if event.event_name == "OTT_PLATFORM_ENTERED"]
        eligible_rows = [event for event in ordered if event.event_name == "INTENT_GATE_ELIGIBLE"]
        requests = [event for event in ordered if event.event_name == "INTENT_GATE_REQUESTED"]
        displays = [event for event in ordered if event.event_name == "INTENT_GATE_DISPLAYED"]
        if not (
            len(starts) == len(entered) == len(eligible_rows) == len(requests) == len(displays) == 1
        ):
            if displays:
                exclusions["COSINE_LINEAGE_AMBIGUOUS"] += 1
            continue
        start, platform_entered, gate_eligible, request, display = (
            starts[0], entered[0], eligible_rows[0], requests[0], displays[0]
        )
        if (
            start.session_id != episode.parent_session_id
            or start.event_class is not EventClass.OBSERVED
            or platform_entered.event_class is not EventClass.OBSERVED
            or gate_eligible.event_class is not EventClass.DERIVED
            or request.event_class is not EventClass.DERIVED
            or display.event_class is not EventClass.PRESENTATION
            or not (
                start.sequence
                < platform_entered.sequence
                < gate_eligible.sequence
                < request.sequence
                < display.sequence
            )
            or not request.request_id
            or gate_eligible.request_id != request.request_id
            or display.request_id != request.request_id
        ):
            exclusions["COSINE_LINEAGE_INVALID"] += 1
            continue
        start_payload = _json_object(start.payload_json, source="cosine_events")
        if (
            start.platform_key not in PLATFORM_KEYS
            or platform_entered.platform_key != start.platform_key
            or not start.evidence_token
            or platform_entered.evidence_token != start.evidence_token
            or start_payload.get("evidence_source")
            not in {"CERTIFIED_HOST", "NATIVE_PROCESS", "WINDOWS_APP"}
        ):
            exclusions["COSINE_PLATFORM_AMBIGUOUS"] += 1
            continue
        current_platform = start.platform_key
        for event in ordered:
            if event.sequence >= display.sequence:
                break
            if event.event_name != "HOPPER_TRANSITION":
                continue
            payload = _json_object(event.payload_json, source="cosine_events")
            if (
                payload.get("from_platform") != current_platform
                or payload.get("to_platform") != event.platform_key
                or event.platform_key not in PLATFORM_KEYS
                or not event.evidence_token
            ):
                current_platform = ""
                break
            current_platform = event.platform_key
        if not current_platform:
            exclusions["COSINE_PLATFORM_AMBIGUOUS"] += 1
            continue
        eligible += 1
    return eligible


def _project_behaviour_distribution(
    *,
    trigger_rows: tuple[sqlite3.Row, ...],
    sine_rows: tuple[sqlite3.Row, ...],
    mine_rows: tuple[sqlite3.Row, ...],
    cosine_rows: tuple[sqlite3.Row, ...],
    session_ids: set[int],
    stamp: str,
) -> BehaviourDistributionProjection:
    exclusions: Counter[str] = Counter()
    triggers = _trigger_evidence(trigger_rows, session_ids)
    displays = _sine_displays(sine_rows, session_ids)
    mine_events = _mine_events(mine_rows)
    cosine_events = _cosine_events(cosine_rows)
    if any(event.parent_session_id not in session_ids for event in mine_events):
        raise _SourceError("MINE pie source contains an invalid parent session")
    if any(
        type(event.session_id) is not int or event.session_id not in session_ids
        for event in cosine_events
    ):
        raise _SourceError("COSINE pie source contains an invalid parent session")
    return _completed_behaviour_distribution(
        social=_sine_social_episode_count(displays, triggers, exclusions),
        ott=_cosine_ott_episode_count(cosine_events, stamp, exclusions),
        messaging=_mine_messaging_episode_count(mine_events, stamp, exclusions),
        exclusions=exclusions,
    )


def _cosecant_metric(
    rows: tuple[sqlite3.Row, ...], session_ids: set[int]
) -> _OrganEvidence:
    groups: dict[tuple[int, str], list[dict]] = {}
    source_stage_rows = 0
    for row in rows:
        kind = str(row["kind"])
        payload = _json_object(row["payload_json"], source="cosecant_events")
        break_id = str(row["break_id"] or "")
        if not break_id and kind == "SAFE_SHUTDOWN":
            continue
        session_id = row["session_id"]
        if (
            type(row["id"]) is not int
            or row["id"] <= 0
            or type(session_id) is not int
            or session_id not in session_ids
            or not break_id
            or type(row["sequence"]) is not int
            or row["sequence"] <= 0
            or type(row["occurred_monotonic_ns"]) is not int
            or row["occurred_monotonic_ns"] < 0
            or payload.get("sequence") != row["sequence"]
            or payload.get("break_id") != break_id
            or payload.get("kind") != kind
            or payload.get("observed_monotonic_ns") != row["occurred_monotonic_ns"]
            or payload.get("schema_version") != COSECANT_SCHEMA_VERSION
        ):
            raise _SourceError(f"invalid COSECANT evidence at row {row['id']}")
        wall_time = payload.get("occurred_wall_time_utc")
        if type(wall_time) is not str or not wall_time:
            raise _SourceError("COSECANT fact lacks a UTC timestamp")
        parse_utc_timestamp(wall_time)
        groups.setdefault((session_id, break_id), []).append(payload)
        if kind in _COSECANT_STAGES:
            source_stage_rows += 1

    slots: set[tuple[int, str, str]] = set()
    returned: set[tuple[int, str]] = set()
    for identity, facts in groups.items():
        ordered = sorted(facts, key=lambda fact: int(fact["sequence"]))
        sequences = [int(fact["sequence"]) for fact in ordered]
        if sequences != list(range(sequences[0], sequences[0] + len(sequences))):
            raise _SourceError("COSECANT break sequence is not contiguous")
        starts = [fact for fact in ordered if fact["kind"] == "BREAK_STARTED"]
        relevant = any(
            fact["kind"] in _COSECANT_STAGES or fact["kind"] == "RETURN_CONFIRMED"
            for fact in ordered
        )
        if relevant and (
            len(starts) != 1 or starts[0]["sequence"] != sequences[0]
        ):
            raise _SourceError("COSECANT break lacks one opening BREAK_STARTED fact")
        kinds = [str(fact["kind"]) for fact in ordered]
        for fact in ordered:
            kind = str(fact["kind"])
            if kind in _COSECANT_STAGES:
                expected_state = {
                    "BREAK_COMPLETE": "BREAK_COMPLETE",
                    "BREAK_ALREADY_OVER": "BREAK_ALREADY_OVER",
                    "FINAL_LOCKED": "FINAL_LOCK",
                }[kind]
                if fact.get("to_state") != expected_state:
                    raise _SourceError("COSECANT reminder transition has the wrong state")
                slots.add((*identity, kind))
        if "BREAK_ALREADY_OVER" in kinds and "BREAK_COMPLETE" not in kinds:
            raise _SourceError("COSECANT overdue stage lacks break completion")
        if "FINAL_LOCKED" in kinds and (
            "BREAK_COMPLETE" not in kinds or "BREAK_ALREADY_OVER" not in kinds
        ):
            raise _SourceError("COSECANT final stage lacks its reminder path")
        confirmations = [fact for fact in ordered if fact["kind"] == "RETURN_CONFIRMED"]
        if len(confirmations) > 1:
            raise _SourceError("COSECANT break has multiple return confirmations")
        if confirmations:
            confirmed = confirmations[0]
            complete_positions = [
                index for index, fact in enumerate(ordered) if fact["kind"] == "BREAK_COMPLETE"
            ]
            confirmed_position = ordered.index(confirmed)
            if (
                not complete_positions
                or complete_positions[0] >= confirmed_position
                or confirmed.get("to_state") != "CONFIRMED"
                or not str(confirmed.get("evidence_token") or "")
            ):
                raise _SourceError("COSECANT return lacks same-break resource proof")
            returned.add(identity)

    return _OrganEvidence(
        OrganMetric(
            "COSECANT",
            _available(
                len(slots),
                "Reminder stages REACHED (BREAK_COMPLETE, BREAK_ALREADY_OVER, FINAL_LOCKED), "
                "once per genuine break; these are not witnessed popup paints.",
                "durable COSECANT reminder stage reached per genuine break",
                source_count=source_stage_rows,
            ),
            _available(
                len(returned),
                "Same-break completion plus exact-resource RETURN_CONFIRMED proof.",
                "validated returned COSECANT break",
                source_count=len(returned),
            ),
            "Reminder stages REACHED — not independently witnessed popup paints.",
            "Completed same-break exact-resource return confirmation.",
        ),
        tuple(
            sorted(
                session_id for session_id, _break_id, _stage in slots
            )
        ),
        tuple(sorted(session_id for session_id, _break_id in returned)),
    )


def _sum_metric(label: str, metrics: tuple[tuple[str, MetricValue], ...]) -> MetricValue:
    blocked = [name for name, metric in metrics if not metric.available]
    if blocked:
        return _unavailable(
            f"{label} unavailable because {', '.join(blocked)} contribution(s) are unavailable.",
            "sum of the four displayed organ contributions",
        )
    return _available(
        sum(int(metric.value) for _, metric in metrics),
        "Exact sum of the four displayed same-snapshot organ contributions.",
        "sum of the four displayed organ contributions",
        source_count=4,
    )


def _session_metric(
    lifetime: MetricValue,
    counts: Counter[int] | None,
    session_id: int,
) -> MetricValue:
    if counts is None or not lifetime.available:
        return _unavailable(lifetime.reason, lifetime.evidence_unit)
    value = int(counts.get(session_id, 0))
    return _available(
        value,
        lifetime.reason,
        lifetime.evidence_unit,
        source_count=value,
    )


def _build_session_rows(
    sources: tuple[_SessionSource, ...],
    evidence: tuple[_OrganEvidence, ...],
    sessions_metric: MetricValue,
    total_triggers: MetricValue,
    total_returned: MetricValue,
) -> tuple[SessionMetricRow, ...]:
    if not sessions_metric.available:
        raise _SourceError("session population is unavailable")
    if len(sources) != sessions_metric.value:
        raise _SourceError("session row population does not reconcile")

    counters: dict[str, tuple[Counter[int] | None, Counter[int] | None]] = {}
    for organ in evidence:
        counters[organ.metric.organ] = (
            Counter(organ.trigger_session_ids)
            if organ.trigger_session_ids is not None
            else None,
            Counter(organ.return_session_ids)
            if organ.return_session_ids is not None
            else None,
        )

    rows: list[SessionMetricRow] = []
    by_name = {organ.metric.organ: organ for organ in evidence}
    for ordinal, source in enumerate(sources, start=1):
        per_organ: dict[str, SessionOrganMetric] = {}
        for name in ("SINE", "COSINE", "MINE", "COSECANT"):
            organ = by_name[name]
            trigger_counts, return_counts = counters[name]
            per_organ[name] = SessionOrganMetric(
                _session_metric(
                    organ.metric.triggers, trigger_counts, source.session_id
                ),
                _session_metric(
                    organ.metric.returned, return_counts, source.session_id
                ),
            )
        trigger_parts = tuple(
            (name, per_organ[name].triggers)
            for name in ("SINE", "COSINE", "MINE", "COSECANT")
        )
        return_parts = tuple(
            (name, per_organ[name].returned)
            for name in ("SINE", "COSINE", "MINE", "COSECANT")
        )
        rows.append(
            SessionMetricRow(
                session_id=source.session_id,
                ordinal=ordinal,
                order_key=source.order_key,
                started_at_utc=source.started_at_utc,
                closed_at_utc=source.closed_at_utc,
                is_closed=source.closed_at_utc is not None,
                sine=per_organ["SINE"],
                cosine=per_organ["COSINE"],
                mine=per_organ["MINE"],
                cosecant=per_organ["COSECANT"],
                combined_triggers=_sum_metric(
                    "Session combined triggers", trigger_parts
                ),
                combined_returned=_sum_metric(
                    "Session combined returned", return_parts
                ),
            )
        )

    result = tuple(rows)
    for name, attribute in (
        ("SINE", "sine"),
        ("COSINE", "cosine"),
        ("MINE", "mine"),
        ("COSECANT", "cosecant"),
    ):
        organ = by_name[name]
        for metric_name in ("triggers", "returned"):
            lifetime = getattr(organ.metric, metric_name)
            if not lifetime.available:
                continue
            values = [
                getattr(getattr(row, attribute), metric_name) for row in result
            ]
            if any(not value.available for value in values) or sum(
                int(value.value) for value in values
            ) != int(lifetime.value):
                raise _SourceError(
                    f"{name} per-session {metric_name} does not reconcile"
                )

    for label, lifetime, attribute in (
        ("trigger", total_triggers, "combined_triggers"),
        ("return", total_returned, "combined_returned"),
    ):
        if not lifetime.available:
            continue
        values = [getattr(row, attribute) for row in result]
        if any(not value.available for value in values) or sum(
            int(value.value) for value in values
        ) != int(lifetime.value):
            raise _SourceError(f"combined per-session {label} total does not reconcile")
    return result


def _snapshot_digest(
    path: Path,
    schema_version: int,
    sources: tuple[tuple[str, tuple[sqlite3.Row, ...]], ...],
) -> str:
    """Identify the exact row values observed inside this read transaction."""

    digest = hashlib.sha256()
    digest.update(str(path.resolve()).encode("utf-8"))
    digest.update(f"|schema:{schema_version}|".encode("ascii"))
    for source, rows in sources:
        digest.update(source.encode("ascii"))
        digest.update(b"\0")
        for row in rows:
            encoded = json.dumps(
                tuple(row), ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def _all_unavailable(path: Path, reason: str, stamp: str) -> LifetimeMetricHubProjection:
    sessions = _unavailable(reason, "distinct sessions.id")
    sine = _unavailable_organ("SINE", reason)
    cosine = _unavailable_organ("COSINE", reason)
    mine = _unavailable_organ("MINE", reason)
    cosecant = _unavailable_organ("COSECANT", reason)
    behaviour = _unavailable_behaviour_distribution(reason)
    return LifetimeMetricHubProjection(
        sessions,
        _unavailable(reason, "sum of four organ trigger contributions"),
        _unavailable(reason, "sum of four organ return contributions"),
        sine,
        cosine,
        mine,
        cosecant,
        behaviour,
        stamp,
        "unavailable",
        str(path),
        True,
        UNAVAILABLE,
        reason,
    )


def read_lifetime_metric_hub(
    database_file: str | Path | None = None,
) -> LifetimeMetricHubProjection:
    """Project lifetime KPIs, session charts and the episode pie read-only."""

    stamp = _now()
    path = (
        Path(database_file)
        if database_file is not None
        else database_path(create_parent=False)
    )
    if not path.is_file():
        return _all_unavailable(path, "Metric Hub database is missing.", stamp)

    try:
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
            check_same_thread=False,
        )
    except (OSError, sqlite3.Error) as exc:
        return _all_unavailable(path, f"Metric Hub read failed: {_bounded(exc)}", stamp)

    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        connection.execute("BEGIN")
        schema_version = int(connection.execute("PRAGMA schema_version").fetchone()[0])
        connection.execute("PRAGMA data_version").fetchone()

        source_errors: dict[str, str] = {}

        def load(name: str, columns: tuple[str, ...], query: str):
            try:
                return _required_table(connection, name, columns, query)
            except (sqlite3.Error, _SourceError) as exc:
                source_errors[name] = _bounded(exc)
                return ()

        session_rows = load(
            "sessions",
            ("id", "started_at_utc", "closed_at_utc"),
            "SELECT id, started_at_utc, closed_at_utc FROM sessions ORDER BY id",
        )
        trigger_rows = load(
            "triggers",
            (
                "id", "session_id", "candidate_uid", "occurred_monotonic_ns",
                "payload_json",
            ),
            "SELECT id, session_id, candidate_uid, occurred_monotonic_ns, "
            "payload_json FROM triggers ORDER BY id",
        )
        sine_rows = load(
            "sine_facts",
            (
                "id", "session_id", "episode_uid", "candidate_uid", "kind",
                "popup_request_id", "occurred_monotonic_ns", "payload_json",
            ),
            "SELECT id, session_id, episode_uid, candidate_uid, kind, "
            "popup_request_id, occurred_monotonic_ns, payload_json "
            "FROM sine_facts ORDER BY occurred_monotonic_ns, id",
        )
        mirl_rows = load(
            "mirl_events",
            (
                "event_id", "session_id", "episode_id", "episode_sequence",
                "event_name", "occurred_monotonic_ns", "payload_json",
            ),
            "SELECT event_id, session_id, episode_id, episode_sequence, event_name, "
            "occurred_monotonic_ns, payload_json FROM mirl_events "
            "ORDER BY occurred_monotonic_ns, event_id",
        )
        mine_rows = load(
            "mine_events",
            (
                "event_id", "session_id", "mine_episode_id", "generation", "sequence",
                "event_name", "event_class", "occurred_at_utc", "monotonic_ns",
                "platform_key", "platform_label", "request_id", "evidence_token",
                "payload_json", "schema_version",
            ),
            "SELECT * FROM mine_events ORDER BY session_id, generation, sequence, event_id",
        )
        cosine_rows = load(
            "cosine_events",
            (
                "event_id", "session_id", "cosine_session_id", "generation", "sequence",
                "event_name", "event_class", "occurred_at_utc", "monotonic_ns",
                "platform_key", "content_title", "request_id", "evidence_token",
                "payload_json", "schema_version",
            ),
            "SELECT * FROM cosine_events "
            "ORDER BY cosine_session_id, generation, sequence, event_id",
        )
        cosecant_rows = load(
            "cosecant_events",
            (
                "id", "session_id", "break_id", "sequence", "kind",
                "occurred_monotonic_ns", "payload_json",
            ),
            "SELECT id, session_id, break_id, sequence, kind, occurred_monotonic_ns, "
            "payload_json FROM cosecant_events ORDER BY break_id, sequence, id",
        )

        if "sessions" in source_errors:
            sessions = _unavailable(source_errors["sessions"], "distinct sessions.id")
            session_ids: set[int] = set()
            session_sources: tuple[_SessionSource, ...] = ()
        else:
            try:
                sessions, session_ids, session_sources = _session_population(session_rows)
            except _SourceError as exc:
                sessions = _unavailable(_bounded(exc), "distinct sessions.id")
                session_ids = set()
                session_sources = ()

        if not sessions.available:
            shared_reason = "Parent session population is unavailable."
            sine_evidence = _unavailable_evidence("SINE", shared_reason)
            mine_evidence = _unavailable_evidence("MINE", shared_reason)
            cosine_evidence = _unavailable_evidence("COSINE", shared_reason)
            cosecant_evidence = _unavailable_evidence("COSECANT", shared_reason)
        else:
            try:
                if "sine_facts" in source_errors:
                    raise _SourceError(source_errors["sine_facts"])
                displays = _sine_displays(sine_rows, session_ids)
                sine_triggers, sine_trigger_sessions = _sine_trigger_metric(displays)
            except (OverflowError, ValueError, _SourceError) as exc:
                displays = ()
                sine_triggers = _unavailable(
                    _bounded(exc), "numbered SINE stage first appearance per episode"
                )
                sine_trigger_sessions = None
            try:
                if "mirl_events" in source_errors:
                    raise _SourceError(source_errors["mirl_events"])
                if not sine_triggers.available:
                    raise _SourceError("SINE lineage evidence is unavailable")
                parsed_mirl = _mirl_events(mirl_rows)
                sine_returned, sine_return_sessions = _sine_return_metric(
                    displays, parsed_mirl, session_ids
                )
            except (OverflowError, ValueError, _SourceError) as exc:
                sine_returned = _unavailable(
                    _bounded(exc), "scoped Chapter 6 validated returned SINE episode"
                )
                sine_return_sessions = None
            sine_evidence = _OrganEvidence(
                OrganMetric(
                    "SINE",
                    sine_triggers,
                    sine_returned,
                    "Numbered SINE-1/2/3 once per episode/stage; stage-0 and relapse repeats excluded.",
                    "SCOPED Chapter 6 validation; global MIRL degradation is not resolved.",
                ),
                sine_trigger_sessions,
                sine_return_sessions,
            )

            try:
                if "mine_events" in source_errors:
                    raise _SourceError(source_errors["mine_events"])
                mine_evidence = _mine_metric(mine_rows, session_ids, stamp)
            except (OverflowError, ValueError, _SourceError) as exc:
                mine_evidence = _unavailable_evidence("MINE", _bounded(exc))

            try:
                if "cosine_events" in source_errors:
                    raise _SourceError(source_errors["cosine_events"])
                cosine_evidence = _cosine_metric(cosine_rows, session_ids, stamp)
            except (OverflowError, ValueError, _SourceError) as exc:
                cosine_evidence = _unavailable_evidence("COSINE", _bounded(exc))

            try:
                if "cosecant_events" in source_errors:
                    raise _SourceError(source_errors["cosecant_events"])
                cosecant_evidence = _cosecant_metric(cosecant_rows, session_ids)
            except (OverflowError, ValueError, _SourceError) as exc:
                cosecant_evidence = _unavailable_evidence(
                    "COSECANT", _bounded(exc)
                )

        evidence = (
            sine_evidence,
            cosine_evidence,
            mine_evidence,
            cosecant_evidence,
        )
        sine, cosine, mine, cosecant = tuple(item.metric for item in evidence)

        if not sessions.available:
            behaviour_distribution = _unavailable_behaviour_distribution(
                "Parent session population is unavailable."
            )
        else:
            try:
                pie_sources = ("triggers", "sine_facts", "mine_events", "cosine_events")
                failed = [name for name in pie_sources if name in source_errors]
                if failed:
                    raise _SourceError(
                        "Required pie source unavailable: "
                        + ", ".join(f"{name} ({source_errors[name]})" for name in failed)
                    )
                behaviour_distribution = _project_behaviour_distribution(
                    trigger_rows=trigger_rows,
                    sine_rows=sine_rows,
                    mine_rows=mine_rows,
                    cosine_rows=cosine_rows,
                    session_ids=session_ids,
                    stamp=stamp,
                )
            except (OverflowError, ValueError, _SourceError) as exc:
                behaviour_distribution = _unavailable_behaviour_distribution(
                    _bounded(exc)
                )

        total_triggers = _sum_metric(
            "Total Triggers",
            tuple((organ.organ, organ.triggers) for organ in (sine, cosine, mine, cosecant)),
        )
        total_returned = _sum_metric(
            "Total Returned",
            tuple((organ.organ, organ.returned) for organ in (sine, cosine, mine, cosecant)),
        )
        try:
            metric_session_rows = _build_session_rows(
                session_sources,
                evidence,
                sessions,
                total_triggers,
                total_returned,
            )
            session_series_status = (
                AVAILABLE
                if all(row.available for row in metric_session_rows)
                else UNAVAILABLE
            )
            session_series_message = (
                "Per-session values reconcile exactly to the lifetime KPIs."
                if session_series_status == AVAILABLE
                else "Per-session rows contain explicitly unavailable organ values."
            )
        except (OverflowError, ValueError, _SourceError) as exc:
            metric_session_rows = ()
            session_series_status = UNAVAILABLE
            session_series_message = f"Session series unavailable: {_bounded(exc)}"
        snapshot_id = _snapshot_digest(
            path,
            schema_version,
            (
                ("sessions", session_rows),
                ("triggers", trigger_rows),
                ("sine_facts", sine_rows),
                ("mirl_events", mirl_rows),
                ("mine_events", mine_rows),
                ("cosine_events", cosine_rows),
                ("cosecant_events", cosecant_rows),
            ),
        )
        connection.rollback()
    except (sqlite3.Error, OSError, OverflowError, ValueError, _SourceError) as exc:
        try:
            connection.rollback()
        except sqlite3.Error:
            pass
        return _all_unavailable(path, f"Metric Hub snapshot failed: {_bounded(exc)}", stamp)
    finally:
        connection.close()

    available = sessions.available and total_triggers.available and total_returned.available
    return LifetimeMetricHubProjection(
        sessions,
        total_triggers,
        total_returned,
        sine,
        cosine,
        mine,
        cosecant,
        behaviour_distribution,
        stamp,
        snapshot_id,
        str(path.resolve()),
        True,
        AVAILABLE if available else UNAVAILABLE,
        (
            "Live lifetime snapshot loaded read-only."
            if available
            else "Some lifetime metrics are unavailable; see the affected cards."
        ),
        metric_session_rows,
        session_series_status,
        session_series_message,
    )


__all__ = [
    "AVAILABLE",
    "NO_DATA",
    "UNAVAILABLE",
    "BehaviourDistributionProjection",
    "LifetimeMetricHubProjection",
    "MetricValue",
    "OrganMetric",
    "PieExclusion",
    "SessionMetricRow",
    "SessionOrganMetric",
    "read_lifetime_metric_hub",
]
