"""The single read-only projection authority for final MYELIN MIRL.

This module converts authoritative MIRL events into immutable views for:

* Metric Hub;
* Science Lab;
* Live MIRL;
* integrity reporting; and
* research provenance.

It does not monitor Windows, advance MIRL timers, display SINE, write a
database, or calculate a second version of episode truth.  Episode outcomes
come only from factual ``MIRL_EPISODE_CLOSED`` events.  The projector merely
validates their order and prepares read-only summaries.

Important integrity rule
------------------------
Missing or contradictory evidence is never converted into a healthy-looking
empty state.  An upstream ``DEGRADED`` or ``UNKNOWN`` source can never become
``CONFIRMED`` here, even when the events that remain are internally ordered.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from statistics import fmean
from types import MappingProxyType
from typing import Final

from MIRL.mirl import (
    EVENT_CONTRACTS,
    MIRL_SCHEMA_VERSION,
    MirlEvent,
    MirlEventClass,
    MirlEventName,
)


MIRL_READ_MODEL_VERSION: Final = "myelin-mirl-read-model-v1"
NANOSECONDS_PER_SECOND: Final = 1_000_000_000
MAX_RECENTLY_CLOSED_EPISODES: Final = 50


class IntegrityStatus(str, Enum):
    """Explicit evidence condition; there is intentionally no generic PASS."""

    CONFIRMED = "CONFIRMED"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class IntegritySeverity(str, Enum):
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class IntegrityIssue:
    code: str
    severity: IntegritySeverity
    detail: str
    episode_id: str = ""
    event_id: str = ""


@dataclass(frozen=True, slots=True)
class MetricExclusion:
    metric: str
    reason: str
    detail: str
    episode_id: str = ""


@dataclass(frozen=True, slots=True)
class ResearchProvenance:
    """Where the projection came from and what its evidence can support."""

    projector_version: str
    mirl_event_schema_versions: tuple[str, ...]
    source_name: str
    source_revision: str
    source_generated_at: str
    projected_at: str
    time_basis: str
    evidence_population: str
    episode_event_count: int
    control_event_count: int
    excluded_episode_count: int
    integrity_status: IntegrityStatus
    integrity_issue_codes: tuple[str, ...]
    limitation: str


@dataclass(frozen=True, slots=True)
class ProjectionMetadata:
    generated_at: str
    start_time: str | None
    end_time: str | None
    applied_filters: Mapping[str, object]
    selected_range_label: str
    evidence_population: str
    population_scope: str
    exclusion_count: int
    exclusions: tuple[MetricExclusion, ...]
    formula_version: str
    projector_version: str
    integrity_status: IntegrityStatus
    integrity_issues: tuple[IntegrityIssue, ...]
    research_provenance: ResearchProvenance


@dataclass(frozen=True, slots=True)
class MetricHubDetailRow:
    population: str
    status: str
    value: object
    evidence: str


@dataclass(frozen=True, slots=True)
class MetricHubProjection:
    """Prepared Metric Hub values; the UI must not recompute them."""

    available: bool
    total_session_count: int | None
    total_trigger_count: int | None
    native_episode_count: int
    legacy_observation_count: int
    eligible_native_episode_count: int
    closed_native_episode_count: int
    pending_native_episode_count: int
    recovery_eligible_native_episode_count: int
    native_outcome_counts: Mapping[str, int]
    verified_stable_recovery_rate_percent: float | None
    episode_closure_rate_percent: float | None
    average_stable_recovery_latency_seconds: float | None
    stable_recovery_latency_series: tuple[float, ...]
    legacy_resolved_return_rate_percent: float | None
    exclusion_count: int
    evidence_scope_label: str
    read_model_detail_rows: tuple[MetricHubDetailRow, ...]
    status_message: str
    integrity_status: IntegrityStatus
    integrity_issues: tuple[IntegrityIssue, ...]
    research_provenance: ResearchProvenance


@dataclass(frozen=True, slots=True)
class LiveMirlTimelineRow:
    episode_id: str
    episode_seq: int
    occurred_at: str
    event_name: str
    observed_or_derived: str
    reason_or_outcome_code: str | None
    reference: str | None
    integrity_status: IntegrityStatus


@dataclass(frozen=True, slots=True)
class LiveMirlEpisodeRow:
    episode_id: str
    short_display_id: str
    source_event_id: int
    session_id: int
    candidate_uid: str
    started_at: str
    episode_status: str
    final_outcome: str | None
    return_intent_latency_seconds: float | None
    verified_return_latency_seconds: float | None
    stable_recovery_latency_seconds: float | None
    recovery_attempt_count: int
    relapse_count: int
    relapse_timings_seconds: tuple[float, ...]
    sine_stages_exposed: tuple[int, ...]
    sine_responses: tuple[str, ...]
    timeline: tuple[LiveMirlTimelineRow, ...]
    integrity_status: IntegrityStatus
    integrity_issues: tuple[IntegrityIssue, ...]


@dataclass(frozen=True, slots=True)
class LiveMirlProjection:
    available: bool
    metadata: ProjectionMetadata
    active_episodes: tuple[LiveMirlEpisodeRow, ...]
    recently_closed_episodes: tuple[LiveMirlEpisodeRow, ...]
    native_outcome_counts: Mapping[str, int]
    evidence_availability: Mapping[str, bool]
    empty_state_reason: str | None
    status_message: str
    integrity_status: IntegrityStatus
    integrity_issues: tuple[IntegrityIssue, ...]


@dataclass(frozen=True, slots=True)
class ScienceMetric:
    key: str
    metric_name: str
    formula: str
    numerator: float | None
    denominator: float | None
    value: float | None
    unit: str
    evidence_population: str
    scope: str
    exclusions: tuple[str, ...]
    na_reason: str | None
    provenance: str
    integrity_status: IntegrityStatus


@dataclass(frozen=True, slots=True)
class LatencySummaryProjection:
    metric_name: str
    evidence_population: str
    sample_size: int
    mean_seconds: float | None
    minimum_seconds: float | None
    maximum_seconds: float | None
    exclusions: tuple[str, ...]
    na_reason: str | None


@dataclass(frozen=True, slots=True)
class ScienceLabProjection:
    """Behavioral evidence only; no neurological or biometric inference."""

    available: bool
    metadata: ProjectionMetadata
    metrics: tuple[ScienceMetric, ...]
    counts: Mapping[str, int]
    native_outcome_counts: Mapping[str, int]
    latency_summaries: tuple[LatencySummaryProjection, ...]
    recovery_attempt_count: int
    relapse_count: int
    relapse_timings_seconds: tuple[float, ...]
    sine_stage_exposure_counts: Mapping[str, int]
    sine_response_counts: Mapping[str, int]
    model_provenance: tuple[str, ...]
    evidence_availability: Mapping[str, bool]
    empty_state_reason: str | None
    scientific_evidence_limitation: str
    integrity_status: IntegrityStatus
    integrity_issues: tuple[IntegrityIssue, ...]
    research_provenance: ResearchProvenance


@dataclass(frozen=True, slots=True)
class MirlReadInput:
    """Immutable evidence envelope supplied by runtime or persistence.

    Counts outside MIRL are optional because this projector must not infer a
    session or trigger population from episode rows alone.
    """

    events: tuple[MirlEvent, ...]
    source_name: str
    source_revision: str
    source_generated_at: str
    upstream_integrity_status: IntegrityStatus
    upstream_integrity_issues: tuple[str, ...] = ()
    total_session_count: int | None = None
    total_trigger_count: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    applied_filters: Mapping[str, object] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not str(self.source_name).strip():
            raise ValueError("source_name must not be empty")
        if not str(self.source_revision).strip():
            raise ValueError("source_revision must not be empty")
        for name in ("total_session_count", "total_trigger_count"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(
            self,
            "upstream_integrity_issues",
            tuple(str(item) for item in self.upstream_integrity_issues),
        )
        object.__setattr__(self, "applied_filters", _freeze_mapping(self.applied_filters))


@dataclass(frozen=True, slots=True)
class MirlReadModelSnapshot:
    generated_at: str
    metric_hub: MetricHubProjection
    science_lab: ScienceLabProjection
    live_mirl: LiveMirlProjection
    integrity_status: IntegrityStatus
    integrity_issues: tuple[IntegrityIssue, ...]
    research_provenance: ResearchProvenance
    control_events: tuple[MirlEvent, ...]
    schema_version: str = MIRL_READ_MODEL_VERSION


@dataclass(slots=True)
class _EpisodeProjectionWork:
    episode_id: str
    events: tuple[MirlEvent, ...]
    issues: list[IntegrityIssue]
    state: str = "EXPECT_CREATED"
    active_attempt_id: str = ""
    last_interruption_event_id: str = ""
    verification_completed_event_id: str = ""
    return_verified_event_id: str = ""
    closure_completed_event_id: str = ""
    emergency_event_id: str = ""
    verification_started_ns: int = 0
    closure_started_ns: int = 0
    next_attempt_index: int = 1
    seen_attempt_ids: set[str] = field(default_factory=set)


class MirlReadAuthority:
    """One pure projector over one frozen MIRL evidence envelope."""

    def project(self, source: MirlReadInput) -> MirlReadModelSnapshot:
        if not isinstance(source, MirlReadInput):
            raise TypeError("source must be MirlReadInput")

        generated_at = _utc_now()
        global_issues = self._source_issues(source)
        control_events, grouped = self._group_events(source.events, global_issues)
        self._validate_control_events(control_events, global_issues)
        rows: list[LiveMirlEpisodeRow] = []
        exclusions: list[MetricExclusion] = []

        for episode_id, events in grouped.items():
            row, episode_exclusions = self._project_episode(episode_id, events)
            rows.append(row)
            exclusions.extend(episode_exclusions)
            global_issues.extend(row.integrity_issues)

        rows.sort(
            key=lambda item: (
                item.timeline[-1].occurred_at if item.timeline else item.started_at,
                item.episode_id,
            ),
            reverse=True,
        )
        status = _projection_status(source.upstream_integrity_status, global_issues, rows)
        if (
            status is IntegrityStatus.DEGRADED
            and source.upstream_integrity_status is not IntegrityStatus.CONFIRMED
        ):
            exclusions.append(
                MetricExclusion(
                    metric="all_aggregate_mirl_metrics",
                    reason="upstream_integrity_not_confirmed",
                    detail=(
                        "Aggregate rates are withheld because the authoritative "
                        "source marked its evidence as "
                        f"{source.upstream_integrity_status.value}."
                    ),
                )
            )
        provenance = self._build_provenance(
            source,
            generated_at=generated_at,
            control_events=control_events,
            rows=rows,
            exclusions=exclusions,
            status=status,
            issues=global_issues,
        )
        metadata = ProjectionMetadata(
            generated_at=generated_at,
            start_time=source.start_time,
            end_time=source.end_time,
            applied_filters=source.applied_filters,
            selected_range_label=_range_label(source.start_time, source.end_time),
            evidence_population="NATIVE_MIRL_EVENTS",
            population_scope="Final MYELIN MIRL episodes only",
            exclusion_count=len(exclusions),
            exclusions=tuple(exclusions),
            formula_version=MIRL_READ_MODEL_VERSION,
            projector_version=MIRL_READ_MODEL_VERSION,
            integrity_status=status,
            integrity_issues=tuple(global_issues),
            research_provenance=provenance,
        )

        outcome_counts = _outcome_counts(rows)
        metric_hub = self._metric_hub(
            source, rows, exclusions, status, global_issues, provenance
        )
        live_mirl = self._live_mirl(
            rows, outcome_counts, metadata, status, global_issues
        )
        science_lab = self._science_lab(
            source,
            rows,
            outcome_counts,
            metadata,
            exclusions,
            status,
            global_issues,
            provenance,
        )
        return MirlReadModelSnapshot(
            generated_at=generated_at,
            metric_hub=metric_hub,
            science_lab=science_lab,
            live_mirl=live_mirl,
            integrity_status=status,
            integrity_issues=tuple(global_issues),
            research_provenance=provenance,
            control_events=control_events,
        )

    def project_runtime(
        self,
        runtime: object,
        *,
        source_revision: str = "live-runtime",
    ) -> MirlReadModelSnapshot:
        """Project a live runtime without treating its memory as durable storage."""

        events_reader = getattr(runtime, "events", None)
        live_reader = getattr(runtime, "live_view", None)
        if not callable(events_reader) or not callable(live_reader):
            raise TypeError("runtime must expose events() and live_view()")
        live = live_reader()
        integrity_ok = bool(_field(live, "integrity_ok", False))
        diagnostic = str(_field(live, "diagnostic", "") or "")
        source = MirlReadInput(
            events=tuple(events_reader()),
            source_name="MIRL live runtime memory",
            source_revision=source_revision,
            source_generated_at=_utc_now(),
            upstream_integrity_status=(
                IntegrityStatus.CONFIRMED if integrity_ok else IntegrityStatus.DEGRADED
            ),
            upstream_integrity_issues=((diagnostic,) if diagnostic else ()),
        )
        return self.project(source)

    # ------------------------------------------------------------------
    # Integrity replay
    # ------------------------------------------------------------------

    def _source_issues(self, source: MirlReadInput) -> list[IntegrityIssue]:
        issues = [
            IntegrityIssue(
                code="UPSTREAM_INTEGRITY_ISSUE",
                severity=IntegritySeverity.ERROR,
                detail=detail,
            )
            for detail in source.upstream_integrity_issues
        ]
        if source.upstream_integrity_status in {
            IntegrityStatus.DEGRADED,
            IntegrityStatus.UNKNOWN,
            IntegrityStatus.UNAVAILABLE,
        }:
            issues.append(
                IntegrityIssue(
                    code="UPSTREAM_NOT_CONFIRMED",
                    severity=IntegritySeverity.ERROR,
                    detail=(
                        "Upstream evidence status is "
                        f"{source.upstream_integrity_status.value}; the read model "
                        "cannot promote it to confirmed."
                    ),
                )
            )
        return issues

    def _group_events(
        self,
        events: Sequence[MirlEvent],
        issues: list[IntegrityIssue],
    ) -> tuple[tuple[MirlEvent, ...], dict[str, tuple[MirlEvent, ...]]]:
        grouped: dict[str, list[MirlEvent]] = defaultdict(list)
        controls: list[MirlEvent] = []
        seen_event_ids: set[str] = set()

        for event in events:
            if not isinstance(event, MirlEvent):
                issues.append(
                    IntegrityIssue(
                        code="INVALID_EVENT_OBJECT",
                        severity=IntegritySeverity.ERROR,
                        detail=f"Read source contained {type(event).__name__}, not MirlEvent.",
                    )
                )
                continue
            if event.event_id in seen_event_ids:
                issues.append(
                    IntegrityIssue(
                        code="DUPLICATE_EVENT_ID",
                        severity=IntegritySeverity.ERROR,
                        detail=f"Duplicate MIRL event ID {event.event_id}.",
                        episode_id=event.episode_id,
                        event_id=event.event_id,
                    )
                )
                continue
            seen_event_ids.add(event.event_id)
            if event.episode_id:
                grouped[event.episode_id].append(event)
            else:
                controls.append(event)

        frozen_groups: dict[str, tuple[MirlEvent, ...]] = {}
        for episode_id, episode_events in grouped.items():
            frozen_groups[episode_id] = tuple(
                sorted(
                    episode_events,
                    key=lambda item: (
                        item.episode_sequence,
                        item.occurred_monotonic_ns,
                        item.event_id,
                    ),
                )
            )
        controls.sort(key=lambda item: (item.occurred_monotonic_ns, item.event_id))
        return tuple(controls), frozen_groups

    def _validate_control_events(
        self,
        events: Sequence[MirlEvent],
        issues: list[IntegrityIssue],
    ) -> None:
        allowed = {
            MirlEventName.TRIGGER_PREPARED,
            MirlEventName.FIRST_DISPLAY_TIMED_OUT,
            MirlEventName.FIRST_DISPLAY_REJECTED,
        }
        for event in events:
            contract = EVENT_CONTRACTS.get(event.event_name)
            if event.event_name not in allowed:
                issues.append(
                    IntegrityIssue(
                        code="ILLEGAL_CONTROL_EVENT",
                        severity=IntegritySeverity.ERROR,
                        detail=f"{event.event_name.value} cannot exist without episode identity.",
                        event_id=event.event_id,
                    )
                )
            if contract is None or contract.requires_episode:
                issues.append(
                    IntegrityIssue(
                        code="CONTROL_EVENT_CONTRACT_MISMATCH",
                        severity=IntegritySeverity.ERROR,
                        detail="Control event disagrees with the MIRL event contract.",
                        event_id=event.event_id,
                    )
                )
            elif event.event_class is not contract.event_class:
                issues.append(
                    IntegrityIssue(
                        code="CONTROL_EVENT_CLASS_MISMATCH",
                        severity=IntegritySeverity.ERROR,
                        detail=f"{event.event_name.value} has the wrong event class.",
                        event_id=event.event_id,
                    )
                )
            if event.episode_sequence != 0 or event.episode_id:
                issues.append(
                    IntegrityIssue(
                        code="CONTROL_EVENT_IDENTITY_MISMATCH",
                        severity=IntegritySeverity.ERROR,
                        detail="Control event must have empty episode identity and sequence zero.",
                        event_id=event.event_id,
                    )
                )
            if event.schema_version != MIRL_SCHEMA_VERSION:
                issues.append(
                    IntegrityIssue(
                        code="CONTROL_EVENT_SCHEMA_MISMATCH",
                        severity=IntegritySeverity.ERROR,
                        detail=f"Unsupported control-event schema {event.schema_version}.",
                        event_id=event.event_id,
                    )
                )

    def _project_episode(
        self,
        episode_id: str,
        events: tuple[MirlEvent, ...],
    ) -> tuple[LiveMirlEpisodeRow, list[MetricExclusion]]:
        work = _EpisodeProjectionWork(episode_id=episode_id, events=events, issues=[])
        self._validate_identity_and_sequence(work)
        self._replay_lifecycle(work)

        first = events[0]
        created = _first_named(events, MirlEventName.EPISODE_CREATED)
        started_ns = created.occurred_monotonic_ns if created else first.occurred_monotonic_ns
        started_at = created.occurred_wall_time_utc if created else first.occurred_wall_time_utc
        closed = _last_named(events, MirlEventName.EPISODE_CLOSED)
        outcome = closed.reason or None if closed else None
        attempts = {event.attempt_id for event in events if event.attempt_id}
        relapse_events = _named(events, MirlEventName.RELAPSE_DETECTED)
        relapse_timings = tuple(
            _elapsed_seconds(started_ns, event.occurred_monotonic_ns)
            for event in relapse_events
        )
        return_intent = _first_named(events, MirlEventName.RETURN_INTENT_RECORDED)
        verified = _first_named(events, MirlEventName.RETURN_VERIFIED)
        sine_stages = tuple(
            sorted({event.sine_stage for event in events if event.sine_stage > 0})
        )
        sine_responses = tuple(
            event.response
            for event in events
            if event.event_name is MirlEventName.SINE_RESPONSE_RECORDED and event.response
        )

        episode_status = _episode_status(work, closed)
        integrity = (
            IntegrityStatus.DEGRADED if work.issues else IntegrityStatus.CONFIRMED
        )
        timeline = tuple(
            LiveMirlTimelineRow(
                episode_id=episode_id,
                episode_seq=event.episode_sequence,
                occurred_at=event.occurred_wall_time_utc,
                event_name=event.event_name.value,
                observed_or_derived=event.event_class.value,
                reason_or_outcome_code=event.reason or event.response or None,
                reference=(event.supporting_event_ids[0] if event.supporting_event_ids else None),
                integrity_status=integrity,
            )
            for event in events
        )
        stable_latency = (
            _elapsed_seconds(started_ns, closed.occurred_monotonic_ns)
            if closed and outcome == "RETURNED" and not work.issues
            else None
        )
        row = LiveMirlEpisodeRow(
            episode_id=episode_id,
            short_display_id=_short_episode_id(episode_id),
            source_event_id=first.operational_event_id or 0,
            session_id=first.session_id or 0,
            candidate_uid=first.candidate_uid,
            started_at=started_at,
            episode_status=episode_status,
            final_outcome=outcome,
            return_intent_latency_seconds=(
                _elapsed_seconds(started_ns, return_intent.occurred_monotonic_ns)
                if return_intent
                else None
            ),
            verified_return_latency_seconds=(
                _elapsed_seconds(started_ns, verified.occurred_monotonic_ns)
                if verified and not work.issues
                else None
            ),
            stable_recovery_latency_seconds=stable_latency,
            recovery_attempt_count=len(attempts),
            relapse_count=len(relapse_events),
            relapse_timings_seconds=relapse_timings,
            sine_stages_exposed=sine_stages,
            sine_responses=sine_responses,
            timeline=timeline,
            integrity_status=integrity,
            integrity_issues=tuple(work.issues),
        )
        exclusions = []
        if work.issues:
            exclusions.append(
                MetricExclusion(
                    metric="native_episode_metrics",
                    reason="episode_integrity_degraded",
                    detail="; ".join(issue.code for issue in work.issues),
                    episode_id=episode_id,
                )
            )
        return row, exclusions

    def _validate_identity_and_sequence(self, work: _EpisodeProjectionWork) -> None:
        events = work.events
        if not events:
            self._issue(work, "EMPTY_EPISODE", "Episode contains no events.")
            return
        expected_sequence = 1
        first = events[0]
        previous_monotonic_ns = 0
        for event in events:
            if event.episode_sequence != expected_sequence:
                self._issue(
                    work,
                    "BROKEN_EPISODE_SEQUENCE",
                    f"Expected sequence {expected_sequence}, found {event.episode_sequence}.",
                    event,
                )
                expected_sequence = event.episode_sequence
            expected_sequence += 1
            if event.occurred_monotonic_ns <= 0:
                self._issue(work, "INVALID_MONOTONIC_TIME", "Event monotonic time is not positive.", event)
            elif event.occurred_monotonic_ns < previous_monotonic_ns:
                self._issue(work, "MONOTONIC_TIME_REGRESSION", "Event time moved backwards.", event)
            previous_monotonic_ns = max(previous_monotonic_ns, event.occurred_monotonic_ns)
            if not _valid_utc_timestamp(event.occurred_wall_time_utc):
                self._issue(work, "INVALID_WALL_TIMESTAMP", "Event UTC timestamp is malformed.", event)
            if event.episode_id != work.episode_id:
                self._issue(work, "EPISODE_ID_MISMATCH", "Event episode ID changed.", event)
            if event.session_id != first.session_id:
                self._issue(work, "SESSION_ID_MISMATCH", "Session ID changed inside episode.", event)
            if event.candidate_uid != first.candidate_uid:
                self._issue(work, "CANDIDATE_ID_MISMATCH", "Candidate UID changed inside episode.", event)
            if event.operational_event_id != first.operational_event_id:
                self._issue(
                    work,
                    "OPERATIONAL_EVENT_ID_MISMATCH",
                    "Operational event ID changed inside episode.",
                    event,
                )
            contract = EVENT_CONTRACTS.get(event.event_name)
            if contract is None:
                self._issue(work, "UNKNOWN_EVENT_NAME", "Event has no MIRL contract.", event)
            elif event.event_class is not contract.event_class:
                self._issue(
                    work,
                    "EVENT_CLASS_MISMATCH",
                    f"{event.event_name.value} must be {contract.event_class.value}.",
                    event,
                )
            if event.schema_version != MIRL_SCHEMA_VERSION:
                self._issue(
                    work,
                    "SCHEMA_VERSION_MISMATCH",
                    f"Unsupported event schema {event.schema_version}.",
                    event,
                )

        known_ids: set[str] = set()
        for event in events:
            for reference in event.supporting_event_ids:
                if reference not in known_ids:
                    self._issue(
                        work,
                        "BROKEN_EVENT_REFERENCE",
                        f"Supporting event {reference} is missing or not earlier.",
                        event,
                    )
            known_ids.add(event.event_id)

    def _replay_lifecycle(self, work: _EpisodeProjectionWork) -> None:
        for event in work.events:
            name = event.event_name
            if name is MirlEventName.EPISODE_CREATED:
                self._expect(work, event, {"EXPECT_CREATED"})
                work.state = "WAITING"
            elif name in {
                MirlEventName.SINE_DISPLAYED,
                MirlEventName.SINE_RESPONSE_RECORDED,
                MirlEventName.RETURN_INTENT_RECORDED,
            }:
                self._expect(work, event, {"WAITING", "VERIFY", "CLOSURE"})
            elif name is MirlEventName.RETURN_VERIFICATION_STARTED:
                self._expect(work, event, {"WAITING"})
                if not event.attempt_id or event.attempt_index <= 0:
                    self._issue(work, "MISSING_ATTEMPT_IDENTITY", "Verification start lacks attempt identity.", event)
                if event.attempt_id in work.seen_attempt_ids:
                    self._issue(work, "REUSED_ATTEMPT_ID", "Recovery attempt ID was reused.", event)
                if event.attempt_index != work.next_attempt_index:
                    self._issue(
                        work,
                        "BROKEN_ATTEMPT_SEQUENCE",
                        f"Expected attempt {work.next_attempt_index}, found {event.attempt_index}.",
                        event,
                    )
                work.seen_attempt_ids.add(event.attempt_id)
                work.next_attempt_index = max(work.next_attempt_index, event.attempt_index + 1)
                work.active_attempt_id = event.attempt_id
                work.verification_started_ns = event.occurred_monotonic_ns
                work.closure_started_ns = 0
                work.state = "VERIFY"
            elif name is MirlEventName.RETURN_UNVERIFIED:
                self._expect_attempt(work, event, "VERIFY")
            elif name is MirlEventName.RETURN_VERIFICATION_INTERRUPTED:
                self._expect_attempt(work, event, "VERIFY")
                work.last_interruption_event_id = event.event_id
                work.state = "VERIFY_INTERRUPTED"
            elif name is MirlEventName.RETURN_VERIFICATION_COMPLETED:
                self._expect_attempt(work, event, "VERIFY")
                self._validate_completed_timer(
                    work, event, started_ns=work.verification_started_ns
                )
                work.verification_completed_event_id = event.event_id
                work.state = "VERIFY_COMPLETED"
            elif name is MirlEventName.RETURN_VERIFIED:
                self._expect_attempt(work, event, "VERIFY_COMPLETED")
                if work.verification_completed_event_id not in event.supporting_event_ids:
                    self._issue(work, "UNBOUND_RETURN_VERIFICATION", "Return verified is not bound to completion.", event)
                work.return_verified_event_id = event.event_id
                work.state = "RETURN_VERIFIED"
            elif name is MirlEventName.CLOSURE_CONFIRMATION_STARTED:
                self._expect_attempt(work, event, "RETURN_VERIFIED")
                if work.return_verified_event_id not in event.supporting_event_ids:
                    self._issue(work, "UNBOUND_CLOSURE_START", "Closure start is not bound to verified return.", event)
                work.closure_started_ns = event.occurred_monotonic_ns
                work.state = "CLOSURE"
            elif name is MirlEventName.CLOSURE_CONFIRMATION_INTERRUPTED:
                self._expect_attempt(work, event, "CLOSURE")
                work.last_interruption_event_id = event.event_id
                work.state = "CLOSURE_INTERRUPTED"
            elif name is MirlEventName.RELAPSE_DETECTED:
                self._expect_attempt(work, event, "CLOSURE_INTERRUPTED")
                if work.last_interruption_event_id not in event.supporting_event_ids:
                    self._issue(work, "UNBOUND_RELAPSE", "Relapse is not bound to closure interruption.", event)
                work.last_interruption_event_id = event.event_id
                work.state = "RELAPSE"
            elif name is MirlEventName.EPISODE_RESUMED:
                self._expect(work, event, {"VERIFY_INTERRUPTED", "CLOSURE_INTERRUPTED", "RELAPSE"})
                if work.last_interruption_event_id not in event.supporting_event_ids:
                    self._issue(work, "UNBOUND_EPISODE_RESUME", "Episode resume lacks interruption evidence.", event)
                work.active_attempt_id = ""
                work.state = "WAITING"
            elif name is MirlEventName.CLOSURE_CONFIRMATION_COMPLETED:
                self._expect_attempt(work, event, "CLOSURE")
                self._validate_completed_timer(
                    work, event, started_ns=work.closure_started_ns
                )
                work.closure_completed_event_id = event.event_id
                work.state = "CLOSURE_COMPLETED"
            elif name is MirlEventName.EMERGENCY_STOPPED:
                self._expect(work, event, {"WAITING", "VERIFY", "CLOSURE"})
                work.emergency_event_id = event.event_id
                work.state = "EMERGENCY"
            elif name is MirlEventName.EVIDENCE_GAP:
                self._expect(work, event, {"WAITING", "VERIFY", "CLOSURE"})
            elif name is MirlEventName.EPISODE_CLOSED:
                self._validate_episode_close(work, event)
                work.state = "CLOSED"
            else:
                self._issue(work, "ILLEGAL_EPISODE_EVENT", f"{name.value} is not an episode event.", event)

        if work.state == "EXPECT_CREATED":
            self._issue(work, "MISSING_EPISODE_CREATED", "Episode has no episode_created event.")
        if work.state in {"VERIFY_INTERRUPTED", "CLOSURE_INTERRUPTED", "RELAPSE", "VERIFY_COMPLETED", "RETURN_VERIFIED", "CLOSURE_COMPLETED", "EMERGENCY"}:
            self._issue(
                work,
                "INCOMPLETE_ATOMIC_EVENT_SEQUENCE",
                f"Episode ended its stored sequence in intermediate state {work.state}.",
            )

    def _validate_completed_timer(
        self,
        work: _EpisodeProjectionWork,
        event: MirlEvent,
        *,
        started_ns: int,
    ) -> None:
        if event.target_seconds <= 0:
            self._issue(work, "MISSING_TIMER_TARGET", "Timer completion has no positive target.", event)
        if event.elapsed_seconds < event.target_seconds:
            self._issue(work, "TIMER_COMPLETED_EARLY", "Elapsed time is below target.", event)
        factual_elapsed = _elapsed_seconds(started_ns, event.occurred_monotonic_ns)
        if started_ns <= 0 or factual_elapsed < event.target_seconds:
            self._issue(
                work,
                "MONOTONIC_TIMER_COMPLETED_EARLY",
                "Monotonic event timestamps do not cover the declared timer target.",
                event,
            )

    def _validate_episode_close(self, work: _EpisodeProjectionWork, event: MirlEvent) -> None:
        if event.reason == "RETURNED":
            self._expect(work, event, {"CLOSURE_COMPLETED"})
            if work.closure_completed_event_id not in event.supporting_event_ids:
                self._issue(work, "UNBOUND_RETURNED_CLOSE", "RETURNED close lacks closure completion.", event)
        elif event.reason == "EMERGENCY":
            self._expect(work, event, {"EMERGENCY"})
            if work.emergency_event_id not in event.supporting_event_ids:
                self._issue(work, "UNBOUND_EMERGENCY_CLOSE", "Emergency close lacks emergency event.", event)
        else:
            self._issue(work, "UNKNOWN_EPISODE_OUTCOME", f"Unsupported close outcome {event.reason!r}.", event)

    def _expect_attempt(self, work: _EpisodeProjectionWork, event: MirlEvent, state: str) -> None:
        self._expect(work, event, {state})
        if not work.active_attempt_id or event.attempt_id != work.active_attempt_id:
            self._issue(work, "ATTEMPT_ID_MISMATCH", "Event is not bound to the active attempt.", event)

    def _expect(self, work: _EpisodeProjectionWork, event: MirlEvent, states: set[str]) -> None:
        if work.state not in states:
            self._issue(
                work,
                "ILLEGAL_EVENT_ORDER",
                f"{event.event_name.value} is illegal after state {work.state}.",
                event,
            )

    @staticmethod
    def _issue(
        work: _EpisodeProjectionWork,
        code: str,
        detail: str,
        event: MirlEvent | None = None,
    ) -> None:
        work.issues.append(
            IntegrityIssue(
                code=code,
                severity=IntegritySeverity.ERROR,
                detail=detail,
                episode_id=work.episode_id,
                event_id=event.event_id if event else "",
            )
        )

    # ------------------------------------------------------------------
    # Consumer projections
    # ------------------------------------------------------------------

    def _metric_hub(
        self,
        source: MirlReadInput,
        rows: Sequence[LiveMirlEpisodeRow],
        exclusions: Sequence[MetricExclusion],
        status: IntegrityStatus,
        issues: Sequence[IntegrityIssue],
        provenance: ResearchProvenance,
    ) -> MetricHubProjection:
        eligible = (
            [row for row in rows if row.integrity_status is IntegrityStatus.CONFIRMED]
            if status is IntegrityStatus.CONFIRMED
            else []
        )
        closed = [row for row in eligible if row.final_outcome is not None]
        returned = [row for row in eligible if row.final_outcome == "RETURNED"]
        latencies = tuple(
            row.stable_recovery_latency_seconds
            for row in returned
            if row.stable_recovery_latency_seconds is not None
        )
        closure_rate = _percentage(len(closed), len(eligible))
        recovery_rate = _percentage(len(returned), len(eligible))
        available = bool(rows)
        detail_rows = (
            MetricHubDetailRow("Native MIRL", status.value, len(rows), "Factual MIRL episode events"),
            MetricHubDetailRow("Eligible native", "INCLUDED", len(eligible), "Integrity-confirmed episodes"),
            MetricHubDetailRow("Degraded native", "EXCLUDED", len(rows) - len(eligible), "Visible integrity exclusions"),
            MetricHubDetailRow("Legacy", "NOT USED", 0, "Final MYELIN does not merge legacy observations"),
        )
        return MetricHubProjection(
            available=available,
            total_session_count=source.total_session_count,
            total_trigger_count=source.total_trigger_count,
            native_episode_count=len(rows),
            legacy_observation_count=0,
            eligible_native_episode_count=len(eligible),
            closed_native_episode_count=len(closed),
            pending_native_episode_count=len(eligible) - len(closed),
            recovery_eligible_native_episode_count=len(eligible),
            native_outcome_counts=_freeze_mapping(_outcome_counts(rows)),
            verified_stable_recovery_rate_percent=recovery_rate,
            episode_closure_rate_percent=closure_rate,
            average_stable_recovery_latency_seconds=(fmean(latencies) if latencies else None),
            stable_recovery_latency_series=latencies,
            legacy_resolved_return_rate_percent=None,
            exclusion_count=len(exclusions),
            evidence_scope_label="NATIVE MIRL ONLY; degraded episodes excluded from rates",
            read_model_detail_rows=detail_rows,
            status_message=_status_message(status, available),
            integrity_status=status,
            integrity_issues=tuple(issues),
            research_provenance=provenance,
        )

    def _live_mirl(
        self,
        rows: Sequence[LiveMirlEpisodeRow],
        outcome_counts: Mapping[str, int],
        metadata: ProjectionMetadata,
        status: IntegrityStatus,
        issues: Sequence[IntegrityIssue],
    ) -> LiveMirlProjection:
        active = tuple(row for row in rows if row.final_outcome is None)
        closed = tuple(row for row in rows if row.final_outcome is not None)[
            :MAX_RECENTLY_CLOSED_EPISODES
        ]
        available = bool(rows)
        return LiveMirlProjection(
            available=available,
            metadata=metadata,
            active_episodes=active,
            recently_closed_episodes=closed,
            native_outcome_counts=_freeze_mapping(outcome_counts),
            evidence_availability=_freeze_mapping(
                {
                    "native_mirl_events": available,
                    "integrity_confirmed": status is IntegrityStatus.CONFIRMED,
                    "legacy_evidence": False,
                }
            ),
            empty_state_reason=(None if available else "No factual MIRL episode has been recorded."),
            status_message=_status_message(status, available),
            integrity_status=status,
            integrity_issues=tuple(issues),
        )

    def _science_lab(
        self,
        source: MirlReadInput,
        rows: Sequence[LiveMirlEpisodeRow],
        outcome_counts: Mapping[str, int],
        metadata: ProjectionMetadata,
        exclusions: Sequence[MetricExclusion],
        status: IntegrityStatus,
        issues: Sequence[IntegrityIssue],
        provenance: ResearchProvenance,
    ) -> ScienceLabProjection:
        eligible = (
            [row for row in rows if row.integrity_status is IntegrityStatus.CONFIRMED]
            if status is IntegrityStatus.CONFIRMED
            else []
        )
        returned = [row for row in eligible if row.final_outcome == "RETURNED"]
        closed = [row for row in eligible if row.final_outcome is not None]
        latencies = tuple(
            row.stable_recovery_latency_seconds
            for row in returned
            if row.stable_recovery_latency_seconds is not None
        )
        recovery_rate = _percentage(len(returned), len(eligible))
        closure_rate = _percentage(len(closed), len(eligible))
        metric_integrity = (
            IntegrityStatus.CONFIRMED if eligible else IntegrityStatus.UNAVAILABLE
        )
        exclusion_codes = tuple(exclusion.reason for exclusion in exclusions)
        metrics = (
            ScienceMetric(
                key="verified_return_closure_rate",
                metric_name="Verified return and closure rate",
                formula="100 × integrity-confirmed RETURNED episodes / integrity-confirmed episodes",
                numerator=float(len(returned)) if eligible else None,
                denominator=float(len(eligible)) if eligible else None,
                value=recovery_rate,
                unit="percent",
                evidence_population="NATIVE_MIRL_EVENTS",
                scope="Behavioral software events only",
                exclusions=exclusion_codes,
                na_reason=(None if eligible else "No integrity-confirmed episode population."),
                provenance=MIRL_READ_MODEL_VERSION,
                integrity_status=metric_integrity,
            ),
            ScienceMetric(
                key="episode_closure_rate",
                metric_name="Episode closure rate",
                formula="100 × integrity-confirmed closed episodes / integrity-confirmed episodes",
                numerator=float(len(closed)) if eligible else None,
                denominator=float(len(eligible)) if eligible else None,
                value=closure_rate,
                unit="percent",
                evidence_population="NATIVE_MIRL_EVENTS",
                scope="Behavioral software events only",
                exclusions=exclusion_codes,
                na_reason=(None if eligible else "No integrity-confirmed episode population."),
                provenance=MIRL_READ_MODEL_VERSION,
                integrity_status=metric_integrity,
            ),
            ScienceMetric(
                key="mean_returned_episode_latency",
                metric_name="Mean verified-return episode closure latency",
                formula="sum(RETURNED closure latency seconds) / eligible RETURNED episodes",
                numerator=(float(sum(latencies)) if latencies else None),
                denominator=(float(len(latencies)) if latencies else None),
                value=(fmean(latencies) if latencies else None),
                unit="seconds",
                evidence_population="NATIVE_MIRL_RETURNED_EPISODES",
                scope="Behavioral software events only",
                exclusions=exclusion_codes,
                na_reason=(None if latencies else "No integrity-confirmed RETURNED closure latency."),
                provenance=MIRL_READ_MODEL_VERSION,
                integrity_status=(IntegrityStatus.CONFIRMED if latencies else IntegrityStatus.UNAVAILABLE),
            ),
        )
        attempts = sum(row.recovery_attempt_count for row in rows)
        relapses = sum(row.relapse_count for row in rows)
        relapse_timings = tuple(
            value for row in rows for value in row.relapse_timings_seconds
        )
        stage_counts: dict[str, int] = defaultdict(int)
        response_counts: dict[str, int] = defaultdict(int)
        for row in rows:
            for stage in row.sine_stages_exposed:
                stage_counts[f"SINE_{stage}"] += 1
            for response in row.sine_responses:
                response_counts[response] += 1
        latency_summary = LatencySummaryProjection(
            metric_name="Verified-return episode closure latency",
            evidence_population="NATIVE_MIRL_RETURNED_EPISODES",
            sample_size=len(latencies),
            mean_seconds=(fmean(latencies) if latencies else None),
            minimum_seconds=(min(latencies) if latencies else None),
            maximum_seconds=(max(latencies) if latencies else None),
            exclusions=exclusion_codes,
            na_reason=(None if latencies else "No eligible returned latency evidence."),
        )
        limitation = (
            "These projections describe recorded software events, intervention displays, "
            "focus-evidence timing, returns and relapses. They do not measure neural, "
            "dopamine, cognitive or clinical state. Degraded episodes remain excluded "
            "from rates and are still visible in Live MIRL."
        )
        return ScienceLabProjection(
            available=bool(rows),
            metadata=metadata,
            metrics=metrics,
            counts=_freeze_mapping(
                {
                    "total_session_count": source.total_session_count,
                    "total_trigger_count": source.total_trigger_count,
                    "native_episode_count": len(rows),
                    "legacy_observation_count": 0,
                    "integrity_confirmed_episode_count": len(eligible),
                    "degraded_episode_count": len(rows) - len(eligible),
                }
            ),
            native_outcome_counts=_freeze_mapping(outcome_counts),
            latency_summaries=(latency_summary,),
            recovery_attempt_count=attempts,
            relapse_count=relapses,
            relapse_timings_seconds=relapse_timings,
            sine_stage_exposure_counts=_freeze_mapping(stage_counts),
            sine_response_counts=_freeze_mapping(response_counts),
            model_provenance=(
                f"MIRL event schema: {MIRL_SCHEMA_VERSION}",
                f"Read projector: {MIRL_READ_MODEL_VERSION}",
                "No predictive or biological model was applied by this read authority.",
            ),
            evidence_availability=_freeze_mapping(
                {
                    "native_mirl_events": bool(rows),
                    "integrity_confirmed_population": bool(eligible),
                    "returned_latency": bool(latencies),
                    "legacy_evidence": False,
                }
            ),
            empty_state_reason=(None if rows else "No factual MIRL episode evidence."),
            scientific_evidence_limitation=limitation,
            integrity_status=status,
            integrity_issues=tuple(issues),
            research_provenance=provenance,
        )

    def _build_provenance(
        self,
        source: MirlReadInput,
        *,
        generated_at: str,
        control_events: Sequence[MirlEvent],
        rows: Sequence[LiveMirlEpisodeRow],
        exclusions: Sequence[MetricExclusion],
        status: IntegrityStatus,
        issues: Sequence[IntegrityIssue],
    ) -> ResearchProvenance:
        schema_versions = tuple(sorted({event.schema_version for event in source.events}))
        episode_event_count = sum(len(row.timeline) for row in rows)
        return ResearchProvenance(
            projector_version=MIRL_READ_MODEL_VERSION,
            mirl_event_schema_versions=schema_versions,
            source_name=source.source_name,
            source_revision=source.source_revision,
            source_generated_at=source.source_generated_at,
            projected_at=generated_at,
            time_basis=(
                "Episode order and durations use MIRL monotonic nanoseconds; "
                "UTC wall timestamps are presentation/provenance evidence only."
            ),
            evidence_population="NATIVE_MIRL_EVENTS",
            episode_event_count=episode_event_count,
            control_event_count=len(control_events),
            excluded_episode_count=len({item.episode_id for item in exclusions if item.episode_id}),
            integrity_status=status,
            integrity_issue_codes=tuple(issue.code for issue in issues),
            limitation=(
                "Read-only behavioral software evidence. No neurological, biometric, "
                "dopamine or clinical inference is produced."
            ),
        )


def _projection_status(
    upstream: IntegrityStatus,
    issues: Sequence[IntegrityIssue],
    rows: Sequence[LiveMirlEpisodeRow],
) -> IntegrityStatus:
    if upstream is IntegrityStatus.UNAVAILABLE and not rows:
        return IntegrityStatus.UNAVAILABLE
    if upstream is not IntegrityStatus.CONFIRMED or issues:
        return IntegrityStatus.DEGRADED
    if not rows:
        return IntegrityStatus.UNAVAILABLE
    return IntegrityStatus.CONFIRMED


def _episode_status(work: _EpisodeProjectionWork, closed: MirlEvent | None) -> str:
    if work.issues:
        return "DEGRADED"
    if closed:
        return f"CLOSED_{closed.reason or 'UNKNOWN'}"
    return {
        "WAITING": "WAITING_FOR_RETURN",
        "VERIFY": "RETURN_VERIFICATION_ACTIVE",
        "CLOSURE": "CLOSURE_CONFIRMATION_ACTIVE",
        "CLOSED": "CLOSED",
    }.get(work.state, f"INCOMPLETE_{work.state}")


def _status_message(status: IntegrityStatus, available: bool) -> str:
    if status is IntegrityStatus.DEGRADED:
        return "DEGRADED EVIDENCE — review integrity issues and exclusions"
    if status is IntegrityStatus.UNAVAILABLE or not available:
        return "NO MIRL EPISODE EVIDENCE"
    if status is IntegrityStatus.UNKNOWN:
        return "EVIDENCE INTEGRITY UNKNOWN"
    return "INTEGRITY-CONFIRMED MIRL EVIDENCE"


def _outcome_counts(rows: Sequence[LiveMirlEpisodeRow]) -> dict[str, int]:
    counts = {"RETURNED": 0, "EMERGENCY": 0, "PENDING": 0, "DEGRADED": 0}
    for row in rows:
        if row.integrity_status is IntegrityStatus.DEGRADED:
            counts["DEGRADED"] += 1
        elif row.final_outcome:
            counts.setdefault(row.final_outcome, 0)
            counts[row.final_outcome] += 1
        else:
            counts["PENDING"] += 1
    return counts


def _first_named(events: Sequence[MirlEvent], name: MirlEventName) -> MirlEvent | None:
    return next((event for event in events if event.event_name is name), None)


def _last_named(events: Sequence[MirlEvent], name: MirlEventName) -> MirlEvent | None:
    return next((event for event in reversed(events) if event.event_name is name), None)


def _named(events: Sequence[MirlEvent], name: MirlEventName) -> tuple[MirlEvent, ...]:
    return tuple(event for event in events if event.event_name is name)


def _elapsed_seconds(start_ns: int, end_ns: int) -> float:
    return max(0.0, (end_ns - start_ns) / NANOSECONDS_PER_SECOND)


def _percentage(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100.0, 6)


def _short_episode_id(episode_id: str) -> str:
    tail = episode_id.rsplit("-", 1)[-1][:8].upper()
    return f"MIRL-{tail}" if tail else "MIRL-UNKNOWN"


def _range_label(start: str | None, end: str | None) -> str:
    if start is None and end is None:
        return "All supplied MIRL evidence"
    return f"{start or '-infinity'} <= event time < {end or '+infinity'}"


def _freeze_mapping(value: Mapping | Iterable[tuple[object, object]]) -> Mapping:
    items = value.items() if isinstance(value, Mapping) else value
    frozen = {}
    for key, item in items:
        if isinstance(item, Mapping):
            item = _freeze_mapping(item)
        elif isinstance(item, list):
            item = tuple(item)
        elif isinstance(item, set):
            item = frozenset(item)
        frozen[key] = item
    return MappingProxyType(frozen)


def _field(value: object, name: str, default=None):
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _valid_utc_timestamp(value: str) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


__all__ = [
    "IntegrityIssue",
    "IntegritySeverity",
    "IntegrityStatus",
    "LatencySummaryProjection",
    "LiveMirlEpisodeRow",
    "LiveMirlProjection",
    "LiveMirlTimelineRow",
    "MIRL_READ_MODEL_VERSION",
    "MetricExclusion",
    "MetricHubDetailRow",
    "MetricHubProjection",
    "MirlReadAuthority",
    "MirlReadInput",
    "MirlReadModelSnapshot",
    "ProjectionMetadata",
    "ResearchProvenance",
    "ScienceLabProjection",
    "ScienceMetric",
]
