"""Pure, immutable Chapter 3 analysis of one finalized Science Lab session.

This module consumes the single final evidence snapshot captured after factual
Core Engine cleanup.  It performs no I/O, owns no clock, imports no Qt, and
never mutates source evidence or experiment state.  Unsupported measurements
remain explicitly UNAVAILABLE rather than receiving an inferred formula.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final, TYPE_CHECKING

from PERSISTENCE.storage import ScienceLabExperimentRecord
from SCIENCE_LAB.evidence import ScienceLabEvidenceSnapshot, SourceCoverage

if TYPE_CHECKING:
    from SCIENCE_LAB.engine import ScienceLabFinalizedSession


AVAILABLE: Final = "AVAILABLE"
NO_EVIDENCE: Final = "NO_EVIDENCE"
UNAVAILABLE: Final = "UNAVAILABLE"
NOT_APPLICABLE: Final = "NOT_APPLICABLE"

# Experiment-membership classification for episode-grouped organs (MINE,
# COSINE) whose report rows require full containment.  Chief-approved:
# CROSS_BOUNDARY_OVERLAP is real organ activity excluded from quantitative
# rows -- it must never be reported as if the organ were simply unused
# (that is OUTSIDE_WINDOW, a different and stronger claim).
FULLY_CONTAINED: Final = "FULLY_CONTAINED"
CROSS_BOUNDARY_OVERLAP: Final = "CROSS_BOUNDARY_OVERLAP"
OUTSIDE_WINDOW: Final = "OUTSIDE_WINDOW"

CERTIFIED: Final = "CERTIFIED"
NO_COMPLETED_EXPERIMENT: Final = "NO_COMPLETED_EXPERIMENT"
ANALYSIS_UNAVAILABLE: Final = "ANALYSIS_UNAVAILABLE"

MAIN: Final = "MAIN"
BREAK: Final = "BREAK"

_VALUE_STATUSES: Final = frozenset({AVAILABLE, NO_EVIDENCE, UNAVAILABLE})
_OUTCOME_STATUSES: Final = frozenset(
    {CERTIFIED, NO_COMPLETED_EXPERIMENT, ANALYSIS_UNAVAILABLE}
)
_TIMELINE_STAGES: Final = frozenset(
    {
        "OFF_TASK_DWELL",
        "TRIGGER",
        "RETURN",
        "VERIFIED_RETURN",
        "EPISODE_CLOSURE",
        "BREAK_LANE",
    }
)
_TIMELINE_LANES: Final = frozenset({MAIN, BREAK})
_METRIC_ROSTER: Final = (
    ("task_aligned_time", "Task-aligned time"),
    ("off_task_dwell", "Off-task dwell"),
    ("return_latency", "Return latency"),
    ("verified_returns", "Verified returns"),
    ("relapses", "Relapses"),
    ("post_return_persistence", "Post-return persistence"),
    ("context_switches", "Context switches"),
    ("experiment_duration", "Experiment duration"),
)
_WHOLE_ROSTER: Final = (
    ("SINE", "Completed episodes"),
    ("MINE", "Completed episodes"),
    ("COSINE", "Completed episodes"),
    ("MIRL", "Verified recoveries"),
    ("SECANT", "Completed episodes"),
    ("COSECANT", "Completed returns"),
    ("STUDY", "Completed study blocks"),
    ("NORMAL_BREAK", "Completed break events"),
)
_REQUIRED_COVERAGE: Final = frozenset(
    {
        "SINE",
        "NORMAL_BREAK",
        "MINE",
        "COSINE",
        "MIRL",
        "STUDY",
        "COSECANT",
        "RESOURCE_INTENT",
    }
)
_SUCCESSFUL_RETURN_ONSET_REFERENCE: Final = (
    "opening MIRL SINE display to return_verification_started for the final "
    "attempt durably linked to return_verified and successful episode_closed"
)


class AnalysisIntegrityError(RuntimeError):
    """Final evidence cannot support a coherent certified package."""


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    source: str
    durable_id: str
    occurred_monotonic_ns: int | None
    event_kind: str
    note: str = ""

    def __post_init__(self) -> None:
        if not self.source or not self.durable_id or not self.event_kind:
            raise ValueError("evidence provenance requires source, identity and kind")
        if self.occurred_monotonic_ns is not None and (
            type(self.occurred_monotonic_ns) is not int
            or self.occurred_monotonic_ns < 0
        ):
            raise ValueError("provenance monotonic time must be non-negative")


@dataclass(frozen=True, slots=True)
class AnalysisValue:
    status: str
    value: int | float | None
    unit: str
    reason: str
    provenance: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        _validate_value(self.status, self.value)


@dataclass(frozen=True, slots=True)
class SuccessfulReturnOnsetLatencySample:
    """One certified behavioural-return-onset sample from one closed episode."""

    episode_id: str
    attempt_id: str
    latency_ns: int
    opening_sine_display: EvidenceRef
    successful_return_onset: EvidenceRef
    return_verified: EvidenceRef
    episode_closed: EvidenceRef
    supporting_event_chain: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not self.episode_id or not self.attempt_id:
            raise ValueError("return-onset sample requires episode and attempt identity")
        if type(self.latency_ns) is not int or self.latency_ns <= 0:
            raise ValueError("return-onset latency must be a positive integer")
        anchors = (
            self.opening_sine_display,
            self.successful_return_onset,
            self.return_verified,
            self.episode_closed,
        )
        if any(anchor not in self.supporting_event_chain for anchor in anchors):
            raise ValueError("return-onset sample dropped a required evidence anchor")
        if len(set(self.supporting_event_chain)) != len(self.supporting_event_chain):
            raise ValueError("return-onset supporting chain contains duplicate evidence")
        start_ns = self.opening_sine_display.occurred_monotonic_ns
        return_ns = self.successful_return_onset.occurred_monotonic_ns
        verified_ns = self.return_verified.occurred_monotonic_ns
        closed_ns = self.episode_closed.occurred_monotonic_ns
        if None in {start_ns, return_ns, verified_ns, closed_ns}:
            raise ValueError("return-onset sample requires monotonic evidence anchors")
        if not start_ns < return_ns <= verified_ns <= closed_ns:
            raise ValueError("return-onset sample evidence is out of order")
        if self.latency_ns != return_ns - start_ns:
            raise ValueError("return-onset latency disagrees with evidence anchors")


@dataclass(frozen=True, slots=True)
class SuccessfulReturnOnsetLatencyExtrema:
    """Certified Best/Worst results and their complete eligible population."""

    best_successful_return_onset_latency: AnalysisValue
    worst_successful_return_onset_latency: AnalysisValue
    eligible_sample_count: int
    unit: str
    reference_definition: str
    experiment_start_monotonic_ns: int
    experiment_end_monotonic_ns: int
    samples: tuple[SuccessfulReturnOnsetLatencySample, ...]

    def __post_init__(self) -> None:
        _validate_window(
            self.experiment_start_monotonic_ns,
            self.experiment_end_monotonic_ns,
        )
        if type(self.eligible_sample_count) is not int or self.eligible_sample_count < 0:
            raise ValueError("eligible return-onset sample count must be non-negative")
        if self.eligible_sample_count != len(self.samples):
            raise ValueError("eligible return-onset sample count is inconsistent")
        if self.unit != "ns" or self.reference_definition != _SUCCESSFUL_RETURN_ONSET_REFERENCE:
            raise ValueError("return-onset extrema contract changed")
        best = self.best_successful_return_onset_latency
        worst = self.worst_successful_return_onset_latency
        if best.unit != self.unit or worst.unit != self.unit:
            raise ValueError("return-onset extrema unit is inconsistent")
        if not self.samples:
            if best.status != UNAVAILABLE or worst.status != UNAVAILABLE:
                raise ValueError("zero return-onset samples must remain UNAVAILABLE")
            if best.provenance or worst.provenance:
                raise ValueError("zero return-onset samples cannot carry provenance")
            return
        if best.status != AVAILABLE or worst.status != AVAILABLE:
            raise ValueError("eligible return-onset samples require available extrema")
        if any(
            not point_in_window(
                ref.occurred_monotonic_ns,
                self.experiment_start_monotonic_ns,
                self.experiment_end_monotonic_ns,
            )
            for sample in self.samples
            for ref in sample.supporting_event_chain
        ):
            raise ValueError("return-onset sample escaped its experiment window")
        values = tuple(sample.latency_ns for sample in self.samples)
        if best.value != min(values) or worst.value != max(values):
            raise ValueError("return-onset extrema disagree with eligible samples")
        expected_best_refs = _sample_refs(
            tuple(sample for sample in self.samples if sample.latency_ns == best.value)
        )
        expected_worst_refs = _sample_refs(
            tuple(sample for sample in self.samples if sample.latency_ns == worst.value)
        )
        if best.provenance != expected_best_refs or worst.provenance != expected_worst_refs:
            raise ValueError("return-onset extrema provenance does not preserve all ties")


@dataclass(frozen=True, slots=True)
class Chapter3Metric:
    code: str
    label: str
    status: str
    value: int | float | None
    unit: str
    reason: str
    provenance: tuple[EvidenceRef, ...] = ()
    samples: tuple[AnalysisValue, ...] = ()

    def __post_init__(self) -> None:
        _validate_value(self.status, self.value)


@dataclass(frozen=True, slots=True)
class Chapter3TimelineEvent:
    source: str
    stage: str
    occurred_monotonic_ns: int
    label: str
    durable_id: str
    lane: str
    provenance: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if self.stage not in _TIMELINE_STAGES:
            raise ValueError("unknown Chapter 3 timeline stage")
        if self.lane not in _TIMELINE_LANES:
            raise ValueError("unknown Chapter 3 timeline lane")
        if type(self.occurred_monotonic_ns) is not int:
            raise TypeError("timeline monotonic time must be an exact integer")
        if self.occurred_monotonic_ns < 0:
            raise ValueError("timeline monotonic time cannot be negative")
        if not self.source or not self.label or not self.durable_id:
            raise ValueError("timeline event requires source, label and identity")
        if not self.provenance:
            raise ValueError("timeline event requires provenance")


@dataclass(frozen=True, slots=True)
class WholeMyelinRow:
    source: str
    label: str
    status: str
    count: int | None
    reason: str
    provenance: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        _validate_value(self.status, self.count)
        if self.count is not None and (
            type(self.count) is not int or self.count < 0
        ):
            raise ValueError("Whole-MYELIN count must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class DerivedFinding:
    code: str
    scientific_label: str
    text: str
    provenance: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class CertifiedPattern:
    code: str
    label: str
    description: str
    provenance: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class SineStageRow:
    """One factual SINE escalation-stage DISPLAY (SP7 Table 2) -- not one row
    per stage number.  Identity is (episode_id, stage, popup_request_id):
    SINE's own display-failure retry path can re-request the same stage
    within one episode, minting a new popup_request_id per attempt
    (SINE/sine.py:_request_stage), so stage number alone cannot identify a
    single factual display.  ``response`` is "" when no certified
    SINE_RESPONSE_RECORDED fact exists for this exact display inside the
    selected experiment window -- never inferred, never defaulted.
    """

    episode_id: str
    stage: int
    popup_request_id: str
    display_monotonic_ns: int
    display_wall_time_utc: str
    response: str
    resource_key: str
    provenance: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise ValueError("SINE stage row requires a durable episode identity")
        if self.stage not in (1, 2, 3):
            raise ValueError("SINE stage row stage must be 1, 2 or 3")
        if not self.popup_request_id:
            raise ValueError("SINE stage row requires a durable per-display popup identity")
        if type(self.display_monotonic_ns) is not int or self.display_monotonic_ns < 0:
            raise ValueError("SINE stage row requires a valid monotonic display time")
        if not self.provenance:
            raise ValueError("SINE stage row requires provenance")


@dataclass(frozen=True, slots=True)
class MineEpisodeReportRow:
    """One factual, fully experiment-contained MINE episode (SP8 Tables 1-2).

    Every descriptive field (branch, timer, closure) is read verbatim from
    the already-validated ``MineEpisodeProjection`` MINE/read_model.py
    produces -- this row adds experiment-window inclusion only and performs
    no re-derivation of MINE's own organ semantics.
    """

    episode_id: str
    #: The official ``MINE-DDMMYYYY-NN`` display code MINE/read_model.py's
    #: own ``_with_display_episode_ids()`` already computed, globally,
    #: across every session -- carried through verbatim from
    #: ``MineEpisodeProjection.display_episode_id``.  Never recomputed here.
    display_episode_id: str
    branch: str | None
    important_duration_minutes: int | None
    closure_outcome: str | None
    closure_reason: str | None
    return_verified: bool
    started_at_utc: str
    ended_at_utc: str | None
    opening_monotonic_ns: int
    closing_monotonic_ns: int
    provenance: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise ValueError("MINE episode row requires a durable episode identity")
        if not self.display_episode_id:
            raise ValueError("MINE episode row requires an official display episode id")
        if self.closing_monotonic_ns < self.opening_monotonic_ns:
            raise ValueError("MINE episode row has an inverted monotonic span")
        if not self.provenance:
            raise ValueError("MINE episode row requires provenance")


@dataclass(frozen=True, slots=True)
class CosineEpisodeReportRow:
    """One factual, fully experiment-contained COSINE episode (SP9 Tables
    1-2).  Same non-duplication rule as MineEpisodeReportRow: every
    descriptive field is read verbatim from the already-validated
    ``CosineEpisodeProjection``.
    """

    episode_id: str
    #: The official ``COS-DDMMYYYY-NN`` display code COSINE/report.py's own
    #: ``episode_display_ids()`` already computed, globally, across every
    #: session's episodes.  Carried through verbatim; never recomputed here.
    display_episode_id: str
    starting_platform_key: str
    starting_platform_label: str
    user_choice: str | None
    chosen_break_minutes: int | None
    hopper_count: int
    closure_outcome: str | None
    closure_reason: str | None
    started_at_utc: str
    ended_at_utc: str | None
    opening_monotonic_ns: int
    closing_monotonic_ns: int
    provenance: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise ValueError("COSINE episode row requires a durable episode identity")
        if not self.display_episode_id:
            raise ValueError("COSINE episode row requires an official display episode id")
        if self.closing_monotonic_ns < self.opening_monotonic_ns:
            raise ValueError("COSINE episode row has an inverted monotonic span")
        if not self.provenance:
            raise ValueError("COSINE episode row requires provenance")


@dataclass(frozen=True, slots=True)
class CosecantBreakRow:
    """One factual COSECANT break (SP10 Tables 1-2: break timing +
    escalation), grouped only by the durable ``break_id`` identity
    COSECANT/analysis.py's own whole-MYELIN builder already trusts.

    ``post_break_return_latency_*`` implements Chief's locked definition:
    BREAK_COMPLETE -> RETURN_CONFIRMED.  A factual return recorded before
    BREAK_COMPLETE (or a break with no certified BREAK_COMPLETE fact at all)
    yields NOT_APPLICABLE, never 0 and never a negative value.
    """

    break_id: str
    break_started_monotonic_ns: int | None
    break_complete_monotonic_ns: int | None
    break_already_over_monotonic_ns: int | None
    final_locked_monotonic_ns: int | None
    return_confirmed_monotonic_ns: int | None
    post_break_return_latency_ns: int | None
    post_break_return_latency_status: str
    post_break_return_latency_reason: str
    provenance: tuple[EvidenceRef, ...]

    def __post_init__(self) -> None:
        if not self.break_id:
            raise ValueError("COSECANT break row requires a durable break identity")
        if self.post_break_return_latency_status not in (AVAILABLE, UNAVAILABLE, NOT_APPLICABLE):
            raise ValueError("COSECANT break row has an unknown latency status")
        if self.post_break_return_latency_status == AVAILABLE and (
            type(self.post_break_return_latency_ns) is not int
            or self.post_break_return_latency_ns < 0
        ):
            raise ValueError("AVAILABLE COSECANT latency requires a non-negative value")
        if self.post_break_return_latency_status != AVAILABLE and self.post_break_return_latency_ns is not None:
            raise ValueError("non-AVAILABLE COSECANT latency must not carry a numeric value")
        if not self.provenance:
            raise ValueError("COSECANT break row requires provenance")


@dataclass(frozen=True, slots=True)
class OrganExperimentScope:
    """SP6's experiment-scoped membership signal for MINE/COSINE -- the
    thing SP6 must read instead of whole-session evidence to decide organ
    inclusion.  status is FULLY_CONTAINED / CROSS_BOUNDARY_OVERLAP /
    OUTSIDE_WINDOW / NO_EVIDENCE / UNAVAILABLE.

    status reflects only whether AT LEAST ONE fully-contained episode
    exists (FULLY_CONTAINED) or not -- it is not "no overlap occurred".
    Mixed membership is real and common: one experiment can have both a
    fully-contained episode (eligible for quantitative rows) and a
    cross-boundary episode (excluded from them) at the same time.
    cross_boundary_overlap_count and its provenance are populated
    whenever ANY episode overlapped the boundary, independent of status,
    specifically so a FULLY_CONTAINED result never makes an excluded
    overlapping episode disappear.  SP6 must render both facts together,
    e.g. "N episode(s) analysed; M overlapping episode(s) excluded at the
    experiment boundary" -- never silently drop the second half because
    the first half exists.
    """

    source: str
    status: str
    fully_contained_count: int
    cross_boundary_overlap_count: int
    outside_window_count: int
    reason: str
    provenance: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in (
            FULLY_CONTAINED, CROSS_BOUNDARY_OVERLAP, OUTSIDE_WINDOW, NO_EVIDENCE, UNAVAILABLE,
        ):
            raise ValueError("organ experiment scope has an unknown status")
        for count in (
            self.fully_contained_count, self.cross_boundary_overlap_count, self.outside_window_count,
        ):
            if type(count) is not int or count < 0:
                raise ValueError("organ experiment scope counts must be non-negative integers")
        if self.status == CROSS_BOUNDARY_OVERLAP and self.fully_contained_count != 0:
            raise ValueError("CROSS_BOUNDARY_OVERLAP status contradicts a fully-contained episode")
        if self.status == FULLY_CONTAINED and self.fully_contained_count == 0:
            raise ValueError("FULLY_CONTAINED status requires at least one contained episode")
        if self.cross_boundary_overlap_count > 0 and not self.provenance:
            raise ValueError(
                "any cross-boundary overlap count requires provenance, "
                "regardless of the winning status"
            )
        if self.cross_boundary_overlap_count == 0 and self.status == CROSS_BOUNDARY_OVERLAP:
            raise ValueError("CROSS_BOUNDARY_OVERLAP status requires a non-zero overlap count")


@dataclass(frozen=True, slots=True)
class Chapter3ResultPackage:
    experiment_id: str
    parent_session_id: int
    experiment_started_at_utc: str
    experiment_ended_at_utc: str
    experiment_start_monotonic_ns: int
    experiment_end_monotonic_ns: int
    session_finalized_at_utc: str
    source_coverage: tuple[SourceCoverage, ...]
    timeline: tuple[Chapter3TimelineEvent, ...]
    key_metrics: tuple[Chapter3Metric, ...]
    whole_myelin_summary: tuple[WholeMyelinRow, ...]
    derived_findings: tuple[DerivedFinding, ...]
    certified_patterns: tuple[CertifiedPattern, ...]
    limitations: tuple[str, ...]
    provenance: tuple[EvidenceRef, ...]
    analysis_status: str
    successful_return_onset_latency_extrema: SuccessfulReturnOnsetLatencyExtrema | None = None
    sine_stage_rows: tuple[SineStageRow, ...] = ()
    mine_episode_rows: tuple[MineEpisodeReportRow, ...] = ()
    cosine_episode_rows: tuple[CosineEpisodeReportRow, ...] = ()
    cosecant_break_rows: tuple[CosecantBreakRow, ...] = ()
    mine_experiment_scope: OrganExperimentScope | None = None
    cosine_experiment_scope: OrganExperimentScope | None = None
    #: Official ``EPI-DDMMYYYY-NN`` display codes for every raw SINE episode
    #: identity referenced anywhere in this package (sine_stage_rows and
    #: successful_return_onset_latency_extrema.samples alike), as
    #: ``(episode_id, display_episode_id)`` pairs.  Resolved from MIRL's own
    #: live, globally-masked episode projection
    #: (MIRL/read_model.py::_apply_display_masks); never recomputed locally.
    #: One shared table so a SINE stage row and a MIRL recovery sample that
    #: reference the same raw episode always resolve to the same code.
    sine_episode_display_ids: tuple[tuple[str, str], ...] = ()
    secant_episode_rows: tuple[object, ...] = ()
    secant_experiment_scope: OrganExperimentScope | None = None


@dataclass(frozen=True, slots=True)
class Chapter3AnalysisOutcome:
    status: str
    package: Chapter3ResultPackage | None
    reason: str
    source_coverage: tuple[SourceCoverage, ...] = ()
    whole_myelin_summary: tuple[WholeMyelinRow, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in _OUTCOME_STATUSES:
            raise ValueError("unknown Chapter 3 analysis outcome")
        if (self.status == CERTIFIED) != (self.package is not None):
            raise ValueError("only CERTIFIED analysis may carry a package")


def point_in_window(timestamp_ns: int, start_ns: int, end_ns: int) -> bool:
    """Return whether one exact point lies in the [start,end) window."""

    _validate_window(start_ns, end_ns)
    if type(timestamp_ns) is not int:
        raise TypeError("point timestamp must be an exact integer")
    return start_ns <= timestamp_ns < end_ns


def clip_interval(
    source_start_ns: int,
    source_end_ns: int,
    experiment_start_ns: int,
    experiment_end_ns: int,
) -> tuple[int, int] | None:
    """Clip one factual half-open interval without mutating its source."""

    _validate_window(experiment_start_ns, experiment_end_ns)
    if type(source_start_ns) is not int or type(source_end_ns) is not int:
        raise TypeError("interval bounds must be exact integers")
    if source_end_ns < source_start_ns:
        raise ValueError("source interval cannot have negative duration")
    clipped_start = max(source_start_ns, experiment_start_ns)
    clipped_end = min(source_end_ns, experiment_end_ns)
    return (clipped_start, clipped_end) if clipped_start < clipped_end else None


def analyze_finalized_session(
    *,
    finalized: "ScienceLabFinalizedSession",
    experiments: tuple[ScienceLabExperimentRecord, ...],
) -> Chapter3AnalysisOutcome:
    """Build one deterministic result from already-finalized factual input."""

    try:
        return _analyze(finalized=finalized, experiments=tuple(experiments))
    except Exception as exc:
        reason = " ".join(str(exc).split())[:240] or type(exc).__name__
        snapshot = getattr(finalized, "evidence_snapshot", None)
        coverage = tuple(getattr(snapshot, "source_coverage", ()) or ())
        return Chapter3AnalysisOutcome(
            status=ANALYSIS_UNAVAILABLE,
            package=None,
            reason=f"{type(exc).__name__}: {reason}",
            source_coverage=coverage,
            limitations=(
                "Chapter 3 analysis could not certify the finalized evidence: "
                f"{type(exc).__name__}.",
            ),
        )


def unavailable_outcome(
    reason: str,
    *,
    finalized: "ScienceLabFinalizedSession | None" = None,
) -> Chapter3AnalysisOutcome:
    """Create a bounded immutable failure result for orchestration failures."""

    clean = " ".join(str(reason).split())[:240] or "analysis unavailable"
    snapshot = getattr(finalized, "evidence_snapshot", None)
    coverage = tuple(getattr(snapshot, "source_coverage", ()) or ())
    return Chapter3AnalysisOutcome(
        status=ANALYSIS_UNAVAILABLE,
        package=None,
        reason=clean,
        source_coverage=coverage,
        limitations=(clean,),
    )


def _analyze(
    *,
    finalized: "ScienceLabFinalizedSession",
    experiments: tuple[ScienceLabExperimentRecord, ...],
) -> Chapter3AnalysisOutcome:
    sid = getattr(finalized, "parent_session_id", None)
    if type(sid) is not int or sid <= 0:
        raise AnalysisIntegrityError("finalized parent session identity is invalid")
    snapshot = getattr(finalized, "evidence_snapshot", None)
    if not isinstance(snapshot, ScienceLabEvidenceSnapshot):
        raise AnalysisIntegrityError("finalized evidence snapshot type is invalid")
    if snapshot.parent_session_id != sid:
        raise AnalysisIntegrityError("finalized snapshot belongs to another session")
    if type(getattr(finalized, "finalized_at_utc", None)) is not str or not finalized.finalized_at_utc:
        raise AnalysisIntegrityError("session finalization time is missing")

    coverage = _coverage_by_source(snapshot.source_coverage)
    _validate_snapshot_evidence(snapshot, coverage)
    whole = _build_whole_myelin(snapshot, coverage)
    base_limitations = _base_limitations(snapshot, coverage)

    completed = tuple(
        experiment
        for experiment in experiments
        if getattr(experiment, "parent_session_id", None) == sid
        and getattr(experiment, "status", None) == "COMPLETED"
        and getattr(experiment, "ended_monotonic_ns", None) is not None
    )
    if not completed:
        return Chapter3AnalysisOutcome(
            status=NO_COMPLETED_EXPERIMENT,
            package=None,
            reason="no completed Science Lab experiment exists for the finalized session",
            source_coverage=snapshot.source_coverage,
            whole_myelin_summary=whole,
            limitations=_dedupe(
                (*base_limitations, "No completed Science Lab experiment is available for analysis.")
            ),
        )

    selected = sorted(
        completed,
        key=lambda row: (row.started_monotonic_ns, row.experiment_id),
    )[-1]
    start_ns = selected.started_monotonic_ns
    end_ns = selected.ended_monotonic_ns
    _validate_window(start_ns, end_ns)
    if not selected.experiment_id or not selected.started_at_utc or not selected.ended_at_utc:
        raise AnalysisIntegrityError("selected completed experiment identity is incomplete")

    timeline = _build_timeline(snapshot, start_ns, end_ns)
    metrics = _build_metrics(snapshot, coverage, selected, start_ns, end_ns)
    return_extrema = _build_successful_return_onset_latency_extrema(
        snapshot,
        coverage,
        start_ns,
        end_ns,
    )
    findings = _build_findings(metrics)
    patterns = _build_patterns(snapshot, metrics, start_ns, end_ns)
    sine_stage_rows = _build_sine_stage_rows(snapshot, coverage, start_ns, end_ns)
    mine_episode_rows = _build_mine_rows(snapshot, coverage, start_ns, end_ns)
    cosine_episode_rows = _build_cosine_rows(snapshot, coverage, start_ns, end_ns)
    cosecant_break_rows = _build_cosecant_break_rows(snapshot, coverage, start_ns, end_ns)
    mine_experiment_scope = _mine_experiment_scope(snapshot, coverage, start_ns, end_ns)
    cosine_experiment_scope = _cosine_experiment_scope(snapshot, coverage, start_ns, end_ns)
    from .secant_adapter import classify, validate_package_rows
    secant_rows, secant_scope = classify(snapshot.secant, start_ns, end_ns)
    validate_package_rows(secant_rows, secant_scope, sid, start_ns, end_ns)
    secant_timeline = []
    for episode in secant_rows:
        for event in episode.events:
            stage = {"SECANT_EPISODE_FOUNDED": "TRIGGER", "SECANT_DISPLAYED": "TRIGGER",
                     "SECANT_ACTION_INTENT": "RETURN", "SECANT_RETURN_STARTED": "RETURN",
                     "SECANT_RETURN_VERIFIED": "VERIFIED_RETURN", "SECANT_RECOVERY_CLOSED": "EPISODE_CLOSURE",
                     "SECANT_EPISODE_CLOSED": "EPISODE_CLOSURE"}.get(event.name, "RETURN")
            ref = EvidenceRef("SECANT", event.event_id, event.at_ns, event.name,
                              "Fully contained SECANT episode; " + episode.recorder_run_id)
            label = f"{episode.display_alias}: {event.name.removeprefix('SECANT_').replace('_', ' ')}"
            if event.name == "SECANT_DISPLAYED":
                label += f" SECANT-{event.stage}"
            if event.reason:
                label += " — " + event.reason
            secant_timeline.append(Chapter3TimelineEvent("SECANT", stage, event.at_ns,
                label, event.event_id, MAIN, (ref,)))
    # Stable ties preserve native SECANT founding/display/recovery event order.
    timeline = tuple(sorted((*timeline, *secant_timeline), key=lambda e: e.occurred_monotonic_ns))
    sine_episode_display_ids = _resolve_sine_mirl_display_codes(
        snapshot, coverage, sine_stage_rows, return_extrema
    )
    limitations = _dedupe(
        (
            *base_limitations,
            "SECANT experiment scope: " + secant_scope.reason,
            "The selected experiment may cover only part of its parent MYELIN session.",
            *(
                f"{metric.label}: {metric.reason}"
                for metric in metrics
                if metric.status == UNAVAILABLE
            ),
            *(
                (
                    (
                        "Best successful-return-onset latency: "
                        f"{return_extrema.best_successful_return_onset_latency.reason}"
                    ),
                    (
                        "Worst successful-return-onset latency: "
                        f"{return_extrema.worst_successful_return_onset_latency.reason}"
                    ),
                )
                if return_extrema.eligible_sample_count == 0
                else ()
            ),
        )
    )
    experiment_ref = EvidenceRef(
        source="SCIENCE_LAB_EXPERIMENT",
        durable_id=selected.experiment_id,
        occurred_monotonic_ns=start_ns,
        event_kind="COMPLETED_EXPERIMENT_WINDOW",
        note="Exact durable [start,end) experiment boundary.",
    )
    provenance = _collect_provenance(
        experiment_ref,
        timeline,
        metrics,
        whole,
        findings,
        patterns,
        return_extrema,
        sine_stage_rows,
        mine_episode_rows,
        cosine_episode_rows,
        cosecant_break_rows,
        mine_experiment_scope,
        cosine_experiment_scope,
    )
    provenance = _dedupe_refs((*provenance, *secant_scope.provenance))
    package = Chapter3ResultPackage(
        experiment_id=selected.experiment_id,
        parent_session_id=sid,
        experiment_started_at_utc=selected.started_at_utc,
        experiment_ended_at_utc=selected.ended_at_utc,
        experiment_start_monotonic_ns=start_ns,
        experiment_end_monotonic_ns=end_ns,
        session_finalized_at_utc=finalized.finalized_at_utc,
        source_coverage=tuple(coverage.values()),
        timeline=timeline,
        key_metrics=metrics,
        whole_myelin_summary=whole,
        derived_findings=findings,
        certified_patterns=patterns,
        secant_episode_rows=secant_rows,
        secant_experiment_scope=secant_scope,
        sine_stage_rows=sine_stage_rows,
        mine_episode_rows=mine_episode_rows,
        cosine_episode_rows=cosine_episode_rows,
        cosecant_break_rows=cosecant_break_rows,
        mine_experiment_scope=mine_experiment_scope,
        cosine_experiment_scope=cosine_experiment_scope,
        limitations=limitations,
        provenance=provenance,
        analysis_status=CERTIFIED,
        successful_return_onset_latency_extrema=return_extrema,
        sine_episode_display_ids=sine_episode_display_ids,
    )
    _validate_package(package, selected)
    return Chapter3AnalysisOutcome(
        status=CERTIFIED,
        package=package,
        reason="certified Chapter 3 result package is ready",
        source_coverage=package.source_coverage,
        whole_myelin_summary=package.whole_myelin_summary,
        limitations=package.limitations,
    )


def _validate_value(status: str, value: object) -> None:
    if status not in _VALUE_STATUSES:
        raise ValueError("unknown analysis availability status")
    if status == AVAILABLE and value is None:
        raise ValueError("AVAILABLE analysis requires a value")
    if status != AVAILABLE and value is not None:
        raise ValueError("non-AVAILABLE analysis cannot carry a value")


def _validate_window(start_ns: int, end_ns: int) -> None:
    if type(start_ns) is not int or type(end_ns) is not int:
        raise TypeError("experiment bounds must be exact integers")
    if start_ns < 0 or end_ns < start_ns:
        raise ValueError("experiment window is invalid")


def _coverage_by_source(
    rows: tuple[SourceCoverage, ...],
) -> dict[str, SourceCoverage]:
    result: dict[str, SourceCoverage] = {}
    for row in rows:
        if not isinstance(row, SourceCoverage) or row.source_system in result:
            raise AnalysisIntegrityError("source coverage is malformed or duplicated")
        if row.status not in _VALUE_STATUSES:
            raise AnalysisIntegrityError("source coverage has an unknown status")
        if row.status == UNAVAILABLE:
            if row.item_count is not None:
                raise AnalysisIntegrityError("UNAVAILABLE source cannot carry a count")
        elif type(row.item_count) is not int or row.item_count < 0:
            raise AnalysisIntegrityError("readable source requires a non-negative count")
        if row.status == AVAILABLE and row.item_count == 0:
            raise AnalysisIntegrityError("AVAILABLE source cannot have zero evidence rows")
        if row.status == NO_EVIDENCE and row.item_count != 0:
            raise AnalysisIntegrityError("NO_EVIDENCE source must have zero rows")
        result[row.source_system] = row
    if "SECANT" not in result:
        result["SECANT"] = SourceCoverage("SECANT", UNAVAILABLE, "SECANT absent from legacy snapshot", None)
    if set(result) != _REQUIRED_COVERAGE | {"SECANT"}:
        raise AnalysisIntegrityError("final snapshot source coverage roster is incomplete")
    resource = result["RESOURCE_INTENT"]
    if (
        resource.status != UNAVAILABLE
        or resource.reason != "no_durable_event_identity"
        or resource.item_count is not None
    ):
        raise AnalysisIntegrityError("Resource Intent coverage semantics changed")
    return result


def _validate_snapshot_evidence(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
) -> None:
    """Reject coverage/evidence disagreement instead of certifying false zero."""

    evidence_by_source = {
        "SINE": snapshot.sine,
        "NORMAL_BREAK": snapshot.normal_break,
        "MINE": snapshot.mine,
        "COSINE": snapshot.cosine,
        "MIRL": snapshot.mirl,
        "STUDY": snapshot.study,
        "COSECANT": snapshot.cosecant,
    }
    for source, evidence in evidence_by_source.items():
        row = coverage[source]
        if row.status == UNAVAILABLE:
            if evidence is not None:
                raise AnalysisIntegrityError(
                    f"{source} evidence exists despite UNAVAILABLE coverage"
                )
            continue
        if evidence is None:
            raise AnalysisIntegrityError(
                f"{source} evidence is absent despite readable coverage"
            )
        if getattr(evidence, "session_id", None) != snapshot.parent_session_id:
            raise AnalysisIntegrityError(f"{source} evidence belongs to another session")
        population = (
            getattr(evidence, "events", ())
            if source == "MIRL"
            else getattr(evidence, "episodes", ())
            if source in {"MINE", "COSINE"}
            else getattr(evidence, "records", ())
        )
        if type(population) is not tuple:
            raise AnalysisIntegrityError(f"{source} evidence population is mutable")
        if len(population) != row.item_count:
            raise AnalysisIntegrityError(f"{source} evidence count disagrees with coverage")
    secant = snapshot.secant
    cov = coverage["SECANT"]
    if secant is not None:
        if secant.session_id != snapshot.parent_session_id or secant.status != cov.status:
            raise AnalysisIntegrityError("SECANT coverage/session mismatch")
        if cov.status != UNAVAILABLE and cov.item_count != len(secant.episodes):
            raise AnalysisIntegrityError("SECANT coverage count mismatch")
    elif cov.status != UNAVAILABLE:
        raise AnalysisIntegrityError("SECANT readable coverage lacks evidence")
    if snapshot.resource_intent is not None:
        raise AnalysisIntegrityError("Resource Intent evidence must remain unavailable")


def _status_metric(
    code: str,
    label: str,
    status: str,
    reason: str,
    *,
    value: int | float | None = None,
    unit: str = "",
    provenance: tuple[EvidenceRef, ...] = (),
    samples: tuple[AnalysisValue, ...] = (),
) -> Chapter3Metric:
    return Chapter3Metric(
        code, label, status, value, unit, reason, provenance, samples
    )


def _build_metrics(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
    experiment: ScienceLabExperimentRecord,
    start_ns: int,
    end_ns: int,
) -> tuple[Chapter3Metric, ...]:
    labels = dict(_METRIC_ROSTER)
    resource_reason = (
        "a complete durable Resource Intent ledger is unavailable; unknown time "
        "cannot be classified"
    )
    metrics: dict[str, Chapter3Metric] = {
        "task_aligned_time": _status_metric(
            "task_aligned_time", labels["task_aligned_time"], UNAVAILABLE, resource_reason
        ),
        "off_task_dwell": _status_metric(
            "off_task_dwell",
            labels["off_task_dwell"],
            UNAVAILABLE,
            "certified sources do not provide one complete non-overlapping experiment-wide off-task interval population",
        ),
        "post_return_persistence": _status_metric(
            "post_return_persistence",
            labels["post_return_persistence"],
            UNAVAILABLE,
            "no certified task-aligned persistence endpoint exists after verified return",
        ),
        "context_switches": _status_metric(
            "context_switches",
            labels["context_switches"],
            UNAVAILABLE,
            "no complete durable context-switch identity ledger covers the experiment",
        ),
    }

    mirl_status = coverage["MIRL"].status
    mirl_events = _mirl_events(snapshot, coverage)
    verified = tuple(
        event
        for event in mirl_events
        if _event_name(event) == "return_verified"
        and point_in_window(_event_time(event), start_ns, end_ns)
    )
    relapses = tuple(
        event
        for event in mirl_events
        if _event_name(event) == "relapse_detected"
        and point_in_window(_event_time(event), start_ns, end_ns)
    )
    if mirl_status == UNAVAILABLE:
        metrics["verified_returns"] = _status_metric(
            "verified_returns", labels["verified_returns"], UNAVAILABLE, coverage["MIRL"].reason
        )
        metrics["relapses"] = _status_metric(
            "relapses", labels["relapses"], UNAVAILABLE, coverage["MIRL"].reason
        )
        metrics["return_latency"] = _status_metric(
            "return_latency", labels["return_latency"], UNAVAILABLE, coverage["MIRL"].reason
        )
    elif mirl_status == NO_EVIDENCE:
        metrics["verified_returns"] = _status_metric(
            "verified_returns", labels["verified_returns"], NO_EVIDENCE, "MIRL contains no session evidence"
        )
        metrics["relapses"] = _status_metric(
            "relapses", labels["relapses"], NO_EVIDENCE, "MIRL contains no session evidence"
        )
        metrics["return_latency"] = _status_metric(
            "return_latency", labels["return_latency"], NO_EVIDENCE, "no verified recovery episode exists"
        )
    else:
        verified_refs = tuple(_mirl_ref(event) for event in verified)
        relapse_refs = tuple(_mirl_ref(event) for event in relapses)
        metrics["verified_returns"] = _status_metric(
            "verified_returns",
            labels["verified_returns"],
            AVAILABLE,
            "factual MIRL return_verified events in [start,end)",
            value=len(verified),
            unit="count",
            provenance=verified_refs,
        )
        metrics["relapses"] = _status_metric(
            "relapses",
            labels["relapses"],
            AVAILABLE,
            "factual MIRL relapse_detected events in [start,end)",
            value=len(relapses),
            unit="count",
            provenance=relapse_refs,
        )
        latency_samples = _return_latency_samples(mirl_events, verified)
        metrics["return_latency"] = _status_metric(
            "return_latency",
            labels["return_latency"],
            UNAVAILABLE,
            (
                "per-episode factual latency samples are retained, but no approved "
                "single-card aggregation is defined"
                if latency_samples
                else "no complete factual display-to-verified-return pair exists"
            ),
            samples=latency_samples,
        )

    experiment_ref = EvidenceRef(
        "SCIENCE_LAB_EXPERIMENT",
        experiment.experiment_id,
        start_ns,
        "COMPLETED_EXPERIMENT_WINDOW",
        f"end_monotonic_ns={end_ns}",
    )
    metrics["experiment_duration"] = _status_metric(
        "experiment_duration",
        labels["experiment_duration"],
        AVAILABLE,
        "ended_monotonic_ns - started_monotonic_ns",
        value=end_ns - start_ns,
        unit="ns",
        provenance=(experiment_ref,),
    )
    return tuple(metrics[code] for code, _label in _METRIC_ROSTER)


def _return_latency_samples(
    events: tuple[object, ...],
    verified_events: tuple[object, ...],
) -> tuple[AnalysisValue, ...]:
    samples: list[AnalysisValue] = []
    for verified in verified_events:
        episode_id = str(getattr(verified, "episode_id", ""))
        displays = tuple(
            event
            for event in events
            if str(getattr(event, "episode_id", "")) == episode_id
            and _event_name(event) == "sine_displayed"
            and _event_time(event) <= _event_time(verified)
        )
        if not displays:
            continue
        displayed = sorted(displays, key=lambda event: (_event_time(event), _event_id(event)))[0]
        samples.append(
            AnalysisValue(
                AVAILABLE,
                _event_time(verified) - _event_time(displayed),
                "ns",
                "factual SINE display to MIRL verified-return proof",
                (_mirl_ref(displayed), _mirl_ref(verified)),
            )
        )
    return tuple(samples)


def _build_successful_return_onset_latency_extrema(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
    start_ns: int,
    end_ns: int,
) -> SuccessfulReturnOnsetLatencyExtrema:
    """Certify Best/Worst from final successful MIRL episode chains only."""

    events = _mirl_events(snapshot, coverage)
    samples = _successful_return_onset_latency_samples(events, start_ns, end_ns)
    if not samples:
        reason = (
            f"MIRL evidence is unavailable: {coverage['MIRL'].reason}"
            if coverage["MIRL"].status == UNAVAILABLE
            else (
                "no successfully closed MIRL episode has a complete durable "
                "return-onset chain wholly inside the selected experiment"
            )
        )
        best = AnalysisValue(UNAVAILABLE, None, "ns", reason)
        worst = AnalysisValue(UNAVAILABLE, None, "ns", reason)
    else:
        best_value = min(sample.latency_ns for sample in samples)
        worst_value = max(sample.latency_ns for sample in samples)
        best_samples = tuple(
            sample for sample in samples if sample.latency_ns == best_value
        )
        worst_samples = tuple(
            sample for sample in samples if sample.latency_ns == worst_value
        )
        best = AnalysisValue(
            AVAILABLE,
            best_value,
            "ns",
            (
                "minimum certified opening-SINE-display to final-successful-"
                "return-onset latency"
            ),
            _sample_refs(best_samples),
        )
        worst = AnalysisValue(
            AVAILABLE,
            worst_value,
            "ns",
            (
                "maximum certified opening-SINE-display to final-successful-"
                "return-onset latency"
            ),
            _sample_refs(worst_samples),
        )
    return SuccessfulReturnOnsetLatencyExtrema(
        best_successful_return_onset_latency=best,
        worst_successful_return_onset_latency=worst,
        eligible_sample_count=len(samples),
        unit="ns",
        reference_definition=_SUCCESSFUL_RETURN_ONSET_REFERENCE,
        experiment_start_monotonic_ns=start_ns,
        experiment_end_monotonic_ns=end_ns,
        samples=samples,
    )


def _successful_return_onset_latency_samples(
    events: tuple[object, ...],
    start_ns: int,
    end_ns: int,
) -> tuple[SuccessfulReturnOnsetLatencySample, ...]:
    _validate_window(start_ns, end_ns)
    by_id = {_event_id(event): event for event in events}
    episode_ids = sorted(
        {
            str(getattr(event, "episode_id", ""))
            for event in events
            if str(getattr(event, "episode_id", ""))
        }
    )
    samples: list[SuccessfulReturnOnsetLatencySample] = []
    for episode_id in episode_ids:
        episode_events = tuple(
            event
            for event in events
            if str(getattr(event, "episode_id", "")) == episode_id
        )
        returned_closes = tuple(
            event
            for event in episode_events
            if _event_name(event) == "episode_closed"
            and str(getattr(event, "reason", "")) == "RETURNED"
        )
        if not returned_closes:
            continue
        if len(returned_closes) != 1:
            raise AnalysisIntegrityError(
                "MIRL episode has ambiguous successful closure identity"
            )
        chain = _successful_return_event_chain(
            episode_id,
            episode_events,
            returned_closes[0],
            by_id,
        )
        if not all(
            point_in_window(_event_time(event), start_ns, end_ns)
            for event in chain
        ):
            continue
        (
            _episode_created,
            opening_display,
            return_started,
            _verification_completed,
            return_verified,
            _closure_started,
            _closure_completed,
            episode_closed,
        ) = chain
        samples.append(
            SuccessfulReturnOnsetLatencySample(
                episode_id=episode_id,
                attempt_id=_event_attempt_id(return_started),
                latency_ns=_event_time(return_started) - _event_time(opening_display),
                opening_sine_display=_mirl_chain_ref(opening_display),
                successful_return_onset=_mirl_chain_ref(return_started),
                return_verified=_mirl_chain_ref(return_verified),
                episode_closed=_mirl_chain_ref(episode_closed),
                supporting_event_chain=tuple(
                    _mirl_chain_ref(event) for event in chain
                ),
            )
        )
    return tuple(
        sorted(
            samples,
            key=lambda sample: (
                sample.opening_sine_display.occurred_monotonic_ns,
                sample.episode_id,
            ),
        )
    )


def _successful_return_event_chain(
    episode_id: str,
    episode_events: tuple[object, ...],
    episode_closed: object,
    by_id: dict[str, object],
) -> tuple[object, ...]:
    """Resolve one successful chain by IDs and attempt identity, or fail closed."""

    attempt_id = _event_attempt_id(episode_closed)
    attempt_index = getattr(episode_closed, "attempt_index", None)
    if not attempt_id or type(attempt_index) is not int or attempt_index <= 0:
        raise AnalysisIntegrityError("successful MIRL closure lacks attempt identity")

    episode_created = _unique_episode_event(episode_events, "episode_created")
    opening_displays = tuple(
        event
        for event in episode_events
        if _event_name(event) == "sine_displayed"
        and getattr(event, "sine_stage", None) == 1
        and _event_supporting_ids(event) == (_event_id(episode_created),)
    )
    if len(opening_displays) != 1:
        raise AnalysisIntegrityError(
            "successful MIRL episode lacks one durable opening SINE display"
        )
    opening_display = opening_displays[0]

    closure_completed = _supported_event(
        episode_closed,
        "closure_confirmation_completed",
        episode_id,
        by_id,
    )
    closure_started = _unique_attempt_event(
        episode_events,
        "closure_confirmation_started",
        attempt_id,
        attempt_index,
    )
    return_verified = _supported_event(
        closure_started,
        "return_verified",
        episode_id,
        by_id,
    )
    verification_completed = _supported_event(
        return_verified,
        "return_verification_completed",
        episode_id,
        by_id,
    )
    return_started = _unique_attempt_event(
        episode_events,
        "return_verification_started",
        attempt_id,
        attempt_index,
    )
    disqualifying_attempt_events = {
        "return_verification_interrupted",
        "closure_confirmation_interrupted",
        "evidence_gap",
        "emergency_stopped",
    }
    if any(
        _event_attempt_id(event) == attempt_id
        and getattr(event, "attempt_index", None) == attempt_index
        and _event_name(event) in disqualifying_attempt_events
        and _event_time(return_started)
        <= _event_time(event)
        <= _event_time(episode_closed)
        for event in episode_events
    ):
        raise AnalysisIntegrityError(
            "successful MIRL closure contains an interrupted or evidence-gap attempt"
        )
    attempt_events = (
        return_started,
        verification_completed,
        return_verified,
        closure_started,
        closure_completed,
        episode_closed,
    )
    if any(
        _event_attempt_id(event) != attempt_id
        or getattr(event, "attempt_index", None) != attempt_index
        for event in attempt_events
    ):
        raise AnalysisIntegrityError("successful MIRL chain changed attempt identity")
    chain = (episode_created, opening_display, *attempt_events)
    times = tuple(_event_time(event) for event in chain)
    if not (
        times[0] <= times[1] < times[2]
        and all(left <= right for left, right in zip(times[2:], times[3:]))
    ):
        raise AnalysisIntegrityError("successful MIRL chain is out of order")
    return chain


def _supported_event(
    event: object,
    expected_name: str,
    episode_id: str,
    by_id: dict[str, object],
) -> object:
    supporting_ids = _event_supporting_ids(event)
    if any(
        event_id not in by_id
        or str(getattr(by_id[event_id], "episode_id", "")) != episode_id
        or _event_time(by_id[event_id]) > _event_time(event)
        for event_id in supporting_ids
    ):
        raise AnalysisIntegrityError("successful MIRL chain has a broken durable support")
    matches = tuple(
        by_id[event_id]
        for event_id in supporting_ids
        if _event_name(by_id[event_id]) == expected_name
    )
    if len(matches) != 1:
        raise AnalysisIntegrityError(
            f"successful MIRL chain cannot prove {expected_name} support"
        )
    return matches[0]


def _unique_episode_event(events: tuple[object, ...], event_name: str) -> object:
    matches = tuple(event for event in events if _event_name(event) == event_name)
    if len(matches) != 1:
        raise AnalysisIntegrityError(
            f"successful MIRL episode does not contain one {event_name} event"
        )
    return matches[0]


def _unique_attempt_event(
    events: tuple[object, ...],
    event_name: str,
    attempt_id: str,
    attempt_index: int,
) -> object:
    matches = tuple(
        event
        for event in events
        if _event_name(event) == event_name
        and _event_attempt_id(event) == attempt_id
        and getattr(event, "attempt_index", None) == attempt_index
    )
    if len(matches) != 1:
        raise AnalysisIntegrityError(
            f"successful MIRL attempt does not contain one {event_name} event"
        )
    return matches[0]


def _event_attempt_id(event: object) -> str:
    return str(getattr(event, "attempt_id", ""))


def _event_supporting_ids(event: object) -> tuple[str, ...]:
    value = getattr(event, "supporting_event_ids", ())
    if type(value) is not tuple or any(type(item) is not str or not item for item in value):
        raise AnalysisIntegrityError("MIRL supporting-event identity is malformed")
    return value


def _mirl_chain_ref(event: object) -> EvidenceRef:
    supporting = ",".join(_event_supporting_ids(event)) or "none"
    return EvidenceRef(
        "MIRL",
        _event_id(event),
        _event_time(event),
        _event_name(event),
        (
            f"episode_id={getattr(event, 'episode_id', '')};"
            f"attempt_id={_event_attempt_id(event) or 'none'};"
            f"supporting_event_ids={supporting}"
        ),
    )


def _sample_refs(
    samples: tuple[SuccessfulReturnOnsetLatencySample, ...],
) -> tuple[EvidenceRef, ...]:
    return _dedupe_refs(
        tuple(ref for sample in samples for ref in sample.supporting_event_chain)
    )


def _build_timeline(
    snapshot: ScienceLabEvidenceSnapshot,
    start_ns: int,
    end_ns: int,
) -> tuple[Chapter3TimelineEvent, ...]:
    events: list[Chapter3TimelineEvent] = []

    for record in _generic_records(snapshot.sine, "SINE", snapshot.parent_session_id):
        mapping = {
            "SINE_DISPLAYED": ("TRIGGER", "SINE intervention factually displayed"),
            "SINE_EPISODE_RESOLVED": ("EPISODE_CLOSURE", "SINE episode resolved"),
        }.get(record.kind)
        if mapping and point_in_window(record.occurred_monotonic_ns, start_ns, end_ns):
            ref = _record_ref(record)
            events.append(
                Chapter3TimelineEvent(
                    "SINE", mapping[0], record.occurred_monotonic_ns, mapping[1],
                    record.source_event_id, MAIN, (ref,),
                )
            )

    for record in _generic_records(
        snapshot.normal_break, "NORMAL_BREAK", snapshot.parent_session_id
    ):
        if record.kind not in {
            "NORMAL_BREAK_STARTED",
            "NORMAL_BREAK_COMPLETED",
            "NORMAL_BREAK_STOPPED",
        }:
            continue
        if point_in_window(record.occurred_monotonic_ns, start_ns, end_ns):
            label = {
                "NORMAL_BREAK_STARTED": "Approved Normal Break started",
                "NORMAL_BREAK_COMPLETED": "Approved Normal Break completed",
                "NORMAL_BREAK_STOPPED": "Approved Normal Break stopped",
            }[record.kind]
            events.append(
                Chapter3TimelineEvent(
                    "NORMAL_BREAK", "BREAK_LANE", record.occurred_monotonic_ns,
                    label, record.source_event_id, BREAK, (_record_ref(record),),
                )
            )

    mirl_mapping = {
        "return_verification_started": ("RETURN", "Factual return evidence began"),
        "return_verified": ("VERIFIED_RETURN", "MIRL return verified"),
        "episode_closed": ("EPISODE_CLOSURE", "MIRL episode closed"),
    }
    coverage = {row.source_system: row for row in snapshot.source_coverage}
    for event in _mirl_events(snapshot, coverage):
        mapping = mirl_mapping.get(_event_name(event))
        if mapping and point_in_window(_event_time(event), start_ns, end_ns):
            ref = _mirl_ref(event)
            events.append(
                Chapter3TimelineEvent(
                    "MIRL", mapping[0], _event_time(event), mapping[1],
                    _event_id(event), MAIN, (ref,),
                )
            )

    cosecant_mapping = {
        "BREAK_STARTED": ("BREAK_LANE", BREAK, "Approved Study break started"),
        "BREAK_COMPLETE": ("BREAK_LANE", BREAK, "Approved Study break elapsed"),
        "RETURN_CONFIRMATION_STARTED": ("RETURN", MAIN, "Study return confirmation began"),
        "RETURN_CONFIRMED": ("VERIFIED_RETURN", MAIN, "Study return confirmed"),
    }
    for record in _generic_records(
        snapshot.cosecant, "COSECANT", snapshot.parent_session_id
    ):
        mapping = cosecant_mapping.get(record.kind)
        if mapping is None:
            continue
        payload = _payload(record)
        timestamp = payload.get("effective_monotonic_ns", record.occurred_monotonic_ns)
        if type(timestamp) is not int:
            raise AnalysisIntegrityError("COSECANT effective timestamp is malformed")
        if point_in_window(timestamp, start_ns, end_ns):
            ref = EvidenceRef(
                "COSECANT", record.source_event_id, timestamp, record.kind,
                "effective_monotonic_ns from durable fact payload",
            )
            events.append(
                Chapter3TimelineEvent(
                    "COSECANT", mapping[0], timestamp, mapping[2],
                    record.source_event_id, mapping[1], (ref,),
                )
            )

    unique: dict[tuple[str, str, str], Chapter3TimelineEvent] = {}
    for event in events:
        key = (event.source, event.durable_id, event.stage)
        if key in unique:
            raise AnalysisIntegrityError("duplicate normalized timeline identity")
        unique[key] = event
    return tuple(
        sorted(
            unique.values(),
            key=lambda event: (
                event.occurred_monotonic_ns,
                event.source,
                event.durable_id,
                event.stage,
            ),
        )
    )


def _build_whole_myelin(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
) -> tuple[WholeMyelinRow, ...]:
    builders = {
        "SINE": lambda: _whole_generic(
            snapshot.sine, "SINE", snapshot.parent_session_id,
            {"SINE_EPISODE_RESOLVED"}, "episode_uid",
        ),
        "NORMAL_BREAK": lambda: _whole_generic(
            snapshot.normal_break, "NORMAL_BREAK", snapshot.parent_session_id,
            {"NORMAL_BREAK_COMPLETED", "NORMAL_BREAK_STOPPED"}, "break_id",
        ),
        "STUDY": lambda: _whole_study(snapshot),
        "COSECANT": lambda: _whole_generic(
            snapshot.cosecant, "COSECANT", snapshot.parent_session_id,
            {"RETURN_CONFIRMED"}, "break_id",
        ),
        "MIRL": lambda: _whole_mirl(snapshot),
        "MINE": lambda: _whole_mine(snapshot),
        "COSINE": lambda: _whole_cosine(snapshot),
        "SECANT": lambda: (len(snapshot.secant.episodes), tuple(
            EvidenceRef("SECANT", e.events[-1].event_id, e.closing_ns, "SECANT_EPISODE_CLOSED")
            for e in snapshot.secant.episodes)),
    }
    rows: list[WholeMyelinRow] = []
    for source, label in _WHOLE_ROSTER:
        source_coverage = coverage[source]
        if source_coverage.status != AVAILABLE:
            rows.append(
                WholeMyelinRow(
                    source,
                    label,
                    source_coverage.status,
                    None,
                    source_coverage.reason or "readable source contains no session evidence",
                )
            )
            continue
        count, refs = builders[source]()
        rows.append(
            WholeMyelinRow(
                source,
                label,
                AVAILABLE,
                count,
                "counted from the full finalized parent-session population",
                refs,
            )
        )
    return tuple(rows)


def _whole_generic(
    evidence: object,
    source: str,
    session_id: int,
    terminal_kinds: set[str],
    identity_field: str,
) -> tuple[int, tuple[EvidenceRef, ...]]:
    records = _generic_records(evidence, source, session_id)
    identities: dict[str, EvidenceRef] = {}
    for record in records:
        if record.kind not in terminal_kinds:
            continue
        identity = _payload(record).get(identity_field)
        if type(identity) is not str or not identity:
            raise AnalysisIntegrityError(f"{source} terminal fact lacks identity")
        identities.setdefault(identity, _record_ref(record))
    return len(identities), tuple(identities[key] for key in sorted(identities))


def _whole_study(
    snapshot: ScienceLabEvidenceSnapshot,
) -> tuple[int, tuple[EvidenceRef, ...]]:
    identities: dict[tuple[str, int], EvidenceRef] = {}
    for record in _generic_records(snapshot.study, "STUDY", snapshot.parent_session_id):
        if record.kind not in {"COMPLETE", "TARGET_REACHED"}:
            continue
        payload = _payload(record)
        if payload.get("state") != "COMPLETED":
            continue
        block_id = payload.get("block_id")
        generation = payload.get("generation")
        if type(block_id) is not str or not block_id or type(generation) is not int:
            raise AnalysisIntegrityError("Study completion lacks block identity")
        identities.setdefault((block_id, generation), _record_ref(record))
    keys = sorted(identities)
    return len(keys), tuple(identities[key] for key in keys)


def _whole_mirl(
    snapshot: ScienceLabEvidenceSnapshot,
) -> tuple[int, tuple[EvidenceRef, ...]]:
    identities: dict[str, EvidenceRef] = {}
    coverage = {row.source_system: row for row in snapshot.source_coverage}
    for event in _mirl_events(snapshot, coverage):
        if _event_name(event) == "return_verified":
            identities.setdefault(_event_id(event), _mirl_ref(event))
    return len(identities), tuple(identities[key] for key in sorted(identities))


def _whole_mine(
    snapshot: ScienceLabEvidenceSnapshot,
) -> tuple[int, tuple[EvidenceRef, ...]]:
    if snapshot.mine is None:
        raise AnalysisIntegrityError("MINE evidence is absent despite AVAILABLE coverage")
    identities: dict[str, EvidenceRef] = {}
    for episode in snapshot.mine.episodes:
        if getattr(episode, "session_id", None) != snapshot.parent_session_id:
            raise AnalysisIntegrityError("MINE episode belongs to another session")
        if type(getattr(episode, "is_closed", None)) is not bool:
            raise AnalysisIntegrityError("MINE episode completion state is malformed")
        if not getattr(episode, "is_closed", False):
            continue
        identity = getattr(episode, "mine_episode_id", "")
        if type(identity) is not str or not identity:
            raise AnalysisIntegrityError("closed MINE episode lacks durable identity")
        identities.setdefault(
            identity,
            EvidenceRef("MINE", identity, None, "CLOSED_EPISODE", "MineEpisodeProjection.is_closed"),
        )
    return len(identities), tuple(identities[key] for key in sorted(identities))


def _whole_cosine(
    snapshot: ScienceLabEvidenceSnapshot,
) -> tuple[int, tuple[EvidenceRef, ...]]:
    if snapshot.cosine is None:
        raise AnalysisIntegrityError("COSINE evidence is absent despite AVAILABLE coverage")
    identities: dict[str, EvidenceRef] = {}
    for episode in snapshot.cosine.episodes:
        if getattr(episode, "parent_session_id", None) != snapshot.parent_session_id:
            raise AnalysisIntegrityError("COSINE episode belongs to another session")
        if type(getattr(episode, "is_closed", None)) is not bool:
            raise AnalysisIntegrityError("COSINE episode completion state is malformed")
        if not getattr(episode, "is_closed", False):
            continue
        session_id = getattr(episode, "cosine_session_id", "")
        generation = getattr(episode, "generation", None)
        if type(session_id) is not str or not session_id or type(generation) is not int:
            raise AnalysisIntegrityError("closed COSINE episode lacks durable identity")
        identity = f"{session_id}:{generation}"
        identities.setdefault(
            identity,
            EvidenceRef("COSINE", identity, None, "CLOSED_EPISODE", "CosineEpisodeProjection.is_closed"),
        )
    return len(identities), tuple(identities[key] for key in sorted(identities))


def _build_sine_stage_rows(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
    start_ns: int,
    end_ns: int,
) -> tuple[SineStageRow, ...]:
    """SP7 Table 2.

    Grouping key is (episode_uid, stage, popup_request_id), NOT
    (episode_uid, stage) alone.  SINE/sine.py:_request_stage proves stage
    display is not a one-shot fact: a display-failure/surface-lost retry
    (episode.retry_stage, sine.py:1128/1357) can re-request the SAME stage,
    minting a fresh SinePopupRequest with its own request_id and an
    incrementing per-stage occurrence counter (sine.py:2295-2303).  Every
    SineFact -- SINE_DISPLAYED and SINE_RESPONSE_RECORDED alike -- carries
    that same popup_request_id (sine.py:_emit), so it is the correct,
    already-durable identity for one factual display, and correlates each
    display to its own response without merging two distinct occurrences of
    the same stage number into one row.
    """

    if coverage["SINE"].status != AVAILABLE:
        return ()
    groups: dict[tuple[str, int, str], dict[str, object]] = {}
    order: list[tuple[str, int, str]] = []
    for record in _generic_records(snapshot.sine, "SINE", snapshot.parent_session_id):
        if record.kind not in {"SINE_DISPLAYED", "SINE_RESPONSE_RECORDED"}:
            continue
        if not point_in_window(record.occurred_monotonic_ns, start_ns, end_ns):
            continue
        payload = _payload(record)
        episode_id = payload.get("episode_uid")
        stage = payload.get("stage")
        popup_request_id = payload.get("popup_request_id")
        if (
            type(episode_id) is not str or not episode_id
            or type(stage) is not int
            or type(popup_request_id) is not str or not popup_request_id
        ):
            raise AnalysisIntegrityError(
                "SINE fact lacks durable episode/stage/display identity"
            )
        key = (episode_id, stage, popup_request_id)
        entry = groups.setdefault(key, {"refs": []})
        entry["refs"].append(_record_ref(record))
        if record.kind == "SINE_DISPLAYED":
            entry["display_record"] = record
            entry["resource_key"] = str(payload.get("resource_key", ""))
            entry["display_wall_time_utc"] = str(payload.get("occurred_wall_time_utc", ""))
        else:
            entry["response"] = str(payload.get("response", ""))
        if key not in order:
            order.append(key)

    rows: list[SineStageRow] = []
    for key in order:
        entry = groups[key]
        display = entry.get("display_record")
        if display is None:
            # A SINE_RESPONSE_RECORDED fact fell inside the window but its
            # own SINE_DISPLAYED counterpart did not -- that specific
            # display happened outside [start,end); excluded, not fabricated
            # with a borrowed or estimated timestamp.
            continue
        episode_id, stage, popup_request_id = key
        rows.append(
            SineStageRow(
                episode_id=episode_id,
                stage=stage,
                popup_request_id=popup_request_id,
                display_monotonic_ns=int(display.occurred_monotonic_ns),
                display_wall_time_utc=str(entry.get("display_wall_time_utc", "")),
                response=str(entry.get("response", "")),
                resource_key=str(entry.get("resource_key", "")),
                provenance=tuple(entry["refs"]),
            )
        )
    return tuple(
        sorted(rows, key=lambda row: (row.display_monotonic_ns, row.episode_id, row.stage, row.popup_request_id))
    )


def _sine_stage1_identity_index(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
) -> dict[str, tuple[str, str]]:
    """Map every certified SINE episode_uid in this session's raw SINE
    evidence to the ``(candidate_uid, occurred_wall_time_utc)`` of its own
    factual stage-1 SINE_DISPLAYED fact.

    This is a genuine, byte-exact join key, not an inferred one: MIRL's own
    engine consumes this exact fact to open its episode
    (MIRL/mirl.py::_handle_sine_first_display) and copies its
    ``occurred_wall_time_utc`` verbatim -- via ``_wall_time(fact)`` at
    MIRL/mirl.py:936 -- into the new episode's ``created_wall_time_utc``,
    which MIRL/read_model.py::_project_episode then copies verbatim again
    into ``LiveMirlEpisodeRow.started_at`` (the EPISODE_CREATED event's own
    ``occurred_wall_time_utc``).  No timestamp is recomputed at either hop.

    Deliberately NOT window-filtered: a stage-1 display can fall outside the
    selected experiment while a later retried stage falls inside it, and
    this index exists only to resolve a display alias, never to decide
    experiment membership or any quantitative result.
    """

    if coverage["SINE"].status != AVAILABLE or snapshot.sine is None:
        return {}
    index: dict[str, tuple[str, str]] = {}
    for record in _generic_records(snapshot.sine, "SINE", snapshot.parent_session_id):
        if record.kind != "SINE_DISPLAYED":
            continue
        payload = _payload(record)
        if payload.get("stage") != 1:
            continue
        episode_id = payload.get("episode_uid")
        candidate_uid = payload.get("candidate_uid")
        wall_time = payload.get("occurred_wall_time_utc")
        if (
            type(episode_id) is not str or not episode_id
            or type(candidate_uid) is not str or not candidate_uid
            or type(wall_time) is not str or not wall_time
        ):
            continue
        index.setdefault(episode_id, (candidate_uid, wall_time))
    return index


def _resolve_sine_mirl_display_codes(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
    sine_stage_rows: tuple[SineStageRow, ...],
    return_extrema: SuccessfulReturnOnsetLatencyExtrema,
) -> tuple[tuple[str, str], ...]:
    """Carry MIRL's own already-computed, live, cross-experiment-global
    ``EPI-DDMMYYYY-NN`` display code onto every raw episode identity this
    certified package references -- never recomputed, never guessed
    (Chief's Phase 5 final correction pass ruling).  report_model.py must
    not manufacture this number itself, because its NN is a global daily
    sequence across every session's episodes on that date, which a single-
    experiment adapter cannot see.  MIRL/read_model.py::_apply_display_masks
    already computes it correctly, globally, on every LiveMirlEpisodeRow --
    this function only looks that value up.  A resolution that cannot be
    made without guessing fails loudly (AnalysisIntegrityError) rather than
    substituting a locally-recomputed lookalike.

    Two different raw identity spaces reference "the same" real episode
    here, and each is resolved differently:

    * ``sine_stage_rows[*].episode_id`` is SINE's OWN ``episode_uid``
      (SINE/sine.py:798) -- a different string than MIRL's episode_id.
      Resolved via the exact byte-identical wall-time/candidate_uid join
      proven in ``_sine_stage1_identity_index``.
    * ``return_extrema.samples[*].episode_id`` is already MIRL's OWN
      ``episode_id`` (analysis.py::_successful_return_onset_latency_samples
      reads it straight off the MIRL event) -- resolved by a direct
      identity lookup against ``live_mirl_rows``, no join needed.

    Both paths bottom out at the same ``LiveMirlEpisodeRow``, so a SINE
    stage row and a MIRL recovery sample for the same real episode always
    resolve to the same code.
    """

    sine_ids = tuple(dict.fromkeys(row.episode_id for row in sine_stage_rows))
    sample_ids = tuple(dict.fromkeys(sample.episode_id for sample in return_extrema.samples))
    if not sine_ids and not sample_ids:
        return ()
    if coverage["MIRL"].status != AVAILABLE or snapshot.mirl is None:
        raise AnalysisIntegrityError(
            "certified SINE/MIRL evidence exists but MIRL evidence is unavailable, "
            "so the official EPI- display code cannot be resolved without guessing"
        )
    mirl_rows = tuple(getattr(snapshot.mirl, "live_mirl_rows", ()))
    codes: dict[str, str] = {}

    mirl_id_to_code: dict[str, str] = {}
    for row in mirl_rows:
        mirl_episode_id = str(getattr(row, "episode_id", ""))
        display_id = str(getattr(row, "short_display_id", ""))
        if mirl_episode_id and display_id:
            mirl_id_to_code[mirl_episode_id] = display_id
    for episode_id in sample_ids:
        display_id = mirl_id_to_code.get(episode_id)
        if not display_id:
            raise AnalysisIntegrityError(
                f"MIRL episode {episode_id!r} has no matching certified live-MIRL "
                "projection row (it may have aged out of MIRL's recent-episode "
                "window); its official display code cannot be resolved without "
                "guessing"
            )
        codes[episode_id] = display_id

    if sine_ids:
        identity_index = _sine_stage1_identity_index(snapshot, coverage)
        for episode_id in sine_ids:
            identity = identity_index.get(episode_id)
            if identity is None:
                raise AnalysisIntegrityError(
                    f"SINE episode {episode_id!r} has no certified stage-1 display "
                    "fact; its official MIRL display code cannot be resolved"
                )
            candidate_uid, wall_time = identity
            matches = tuple(
                row for row in mirl_rows
                if str(getattr(row, "candidate_uid", "")) == candidate_uid
                and str(getattr(row, "started_at", "")) == wall_time
            )
            if not matches:
                raise AnalysisIntegrityError(
                    f"SINE episode {episode_id!r} has no matching certified MIRL "
                    "episode (it may have aged out of MIRL's recent-episode "
                    "window); its official display code cannot be resolved "
                    "without guessing"
                )
            if len(matches) > 1:
                raise AnalysisIntegrityError(
                    f"SINE episode {episode_id!r} matches more than one certified "
                    "MIRL episode; the official display code mapping is ambiguous"
                )
            display_id = str(getattr(matches[0], "short_display_id", ""))
            if not display_id:
                raise AnalysisIntegrityError(
                    f"matched MIRL episode for SINE episode {episode_id!r} has no "
                    "official display code"
                )
            codes[episode_id] = display_id
    return tuple(sorted(codes.items()))


def _episode_monotonic_bounds(
    raw_events: tuple[object, ...],
    identity_fn,
) -> dict[str, tuple[object, object]]:
    """Find the earliest and latest RAW event for each already-identified
    episode.  Returns the actual event objects (not bare timestamps) so
    provenance can cite their real event_id/event_name -- performs no
    interpretation of what the episode IS, only which of its own already-
    durable events happened first and last.
    """

    bounds: dict[str, tuple[object, object]] = {}
    for event in raw_events:
        identity = identity_fn(event)
        if not identity:
            continue
        timestamp = getattr(event, "monotonic_ns", None)
        if type(timestamp) is not int:
            raise AnalysisIntegrityError("raw event lacks a durable monotonic timestamp")
        if identity in bounds:
            earliest, latest = bounds[identity]
            if timestamp < getattr(earliest, "monotonic_ns"):
                earliest = event
            if timestamp > getattr(latest, "monotonic_ns"):
                latest = event
            bounds[identity] = (earliest, latest)
        else:
            bounds[identity] = (event, event)
    return bounds


def _classify_experiment_membership(
    opening_ns: int, closing_ns: int, start_ns: int, end_ns: int
) -> str:
    """Three-state classification approved by Chief: an episode-grouped
    organ's activity is either entirely inside the selected experiment
    (eligible for quantitative rows), genuinely outside it (irrelevant), or
    overlapping one boundary without full containment -- real activity that
    must never be reported as "organ not used", even though it is excluded
    from quantitative result rows.
    """

    if start_ns <= opening_ns and closing_ns < end_ns:
        return FULLY_CONTAINED
    if closing_ns < start_ns or opening_ns >= end_ns:
        return OUTSIDE_WINDOW
    return CROSS_BOUNDARY_OVERLAP


def _raw_event_ref(source: str, event: object, *, note: str) -> EvidenceRef:
    """Cite the actual durable raw event -- its own event_id and event_name
    -- never a synthetic role label in the event_kind position.  ``note`` is
    the only place the row-building ROLE (e.g. "earliest event in this
    episode's span") may appear; it must never be mistaken for the durable
    event's own kind.
    """

    return EvidenceRef(
        source,
        str(getattr(event, "event_id", "")),
        int(getattr(event, "monotonic_ns")),
        str(getattr(event, "event_name", "")),
        note,
    )


def _mine_episode_classifications(
    snapshot: ScienceLabEvidenceSnapshot,
    start_ns: int,
    end_ns: int,
) -> list[tuple[object, str, object, object]]:
    """One (episode, status, opening_event, closing_event) tuple per closed
    MINE episode in this parent session, regardless of experiment window --
    the shared basis for both the quantitative rows and the experiment-scope
    summary, so the two can never silently disagree with each other.
    """

    if snapshot.mine is None:
        return []
    bounds = _episode_monotonic_bounds(
        snapshot.mine.raw_events, lambda event: str(getattr(event, "mine_episode_id", ""))
    )
    results: list[tuple[object, str, object, object]] = []
    for episode in snapshot.mine.episodes:
        if getattr(episode, "session_id", None) != snapshot.parent_session_id:
            raise AnalysisIntegrityError("MINE episode belongs to another session")
        if not getattr(episode, "is_closed", False):
            continue
        identity = str(getattr(episode, "mine_episode_id", ""))
        if not identity:
            raise AnalysisIntegrityError("closed MINE episode lacks durable identity")
        span = bounds.get(identity)
        if span is None:
            raise AnalysisIntegrityError(
                "closed MINE episode has no matching raw-event monotonic span"
            )
        opening_event, closing_event = span
        status = _classify_experiment_membership(
            getattr(opening_event, "monotonic_ns"), getattr(closing_event, "monotonic_ns"),
            start_ns, end_ns,
        )
        results.append((episode, status, opening_event, closing_event))
    return results


def _build_mine_rows(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
    start_ns: int,
    end_ns: int,
) -> tuple[MineEpisodeReportRow, ...]:
    """SP8 Tables 1-2.  Boundary-crossing policy (Chief-approved): a MINE
    episode is included only when its ENTIRE raw-event monotonic span --
    earliest through latest event -- lies inside this experiment's
    [start,end).  A CROSS_BOUNDARY_OVERLAP or OUTSIDE_WINDOW episode is
    excluded here, not partially included, not approximated, and not
    silently clipped -- but see mine_experiment_scope, which records that
    exclusion so it is never confused with "MINE was not used".
    """

    if coverage["MINE"].status != AVAILABLE or snapshot.mine is None:
        return ()
    rows: list[MineEpisodeReportRow] = []
    for episode, status, opening_event, closing_event in _mine_episode_classifications(
        snapshot, start_ns, end_ns
    ):
        if status != FULLY_CONTAINED:
            continue
        identity = str(getattr(episode, "mine_episode_id", ""))
        opening_ns = getattr(opening_event, "monotonic_ns")
        closing_ns = getattr(closing_event, "monotonic_ns")
        rows.append(
            MineEpisodeReportRow(
                episode_id=identity,
                display_episode_id=str(getattr(episode, "display_episode_id", "") or ""),
                branch=getattr(episode, "branch", None),
                important_duration_minutes=getattr(episode, "important_duration_minutes", None),
                closure_outcome=getattr(episode, "closure_outcome", None),
                closure_reason=getattr(episode, "closure_reason", None),
                return_verified=bool(getattr(episode, "return_verified", False)),
                started_at_utc=str(getattr(episode, "started_at_utc", "")),
                ended_at_utc=getattr(episode, "ended_at_utc", None),
                opening_monotonic_ns=opening_ns,
                closing_monotonic_ns=closing_ns,
                provenance=(
                    _raw_event_ref(
                        "MINE", opening_event,
                        note="earliest raw MineEvent in this episode's monotonic span",
                    ),
                    _raw_event_ref(
                        "MINE", closing_event,
                        note="latest raw MineEvent in this episode's monotonic span",
                    ),
                ),
            )
        )
    return tuple(sorted(rows, key=lambda row: (row.opening_monotonic_ns, row.episode_id)))


def _scope_status_reason_and_refs(
    source: str,
    counts: dict[str, int],
    overlap_refs: tuple[EvidenceRef, ...],
) -> tuple[str, str, tuple[EvidenceRef, ...]]:
    """Shared MINE/COSINE rule: status reflects only whether a fully-
    contained episode exists.  Mixed membership (contained>=1 AND
    overlap>=1) keeps BOTH facts in the reason and keeps the overlap
    provenance -- a FULLY_CONTAINED result must never make an excluded
    cross-boundary episode disappear just because a valid episode also
    exists in the same experiment.
    """

    contained = counts[FULLY_CONTAINED]
    overlap = counts[CROSS_BOUNDARY_OVERLAP]
    if contained > 0:
        if overlap > 0:
            reason = (
                f"{contained} {source} episode(s) fully contained and analysed; "
                f"{overlap} additional episode(s) crossed the experiment boundary "
                "and were excluded from quantitative rows"
            )
        else:
            reason = f"{contained} {source} episode(s) fully contained and analysed"
        return FULLY_CONTAINED, reason, overlap_refs
    if overlap > 0:
        return (
            CROSS_BOUNDARY_OVERLAP,
            f"{source} activity overlapped the experiment boundary but no episode was "
            "fully contained; excluded from quantitative rows, not absent",
            overlap_refs,
        )
    return (
        OUTSIDE_WINDOW,
        f"certified {source} episodes exist for this session but none overlap this experiment",
        (),
    )


def _mine_experiment_scope(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
    start_ns: int,
    end_ns: int,
) -> OrganExperimentScope:
    """SP6 must read this, never whole-session MINE evidence, to decide
    whether MINE was used in the selected experiment.  A CROSS_BOUNDARY_
    OVERLAP-only result must render as an explicit boundary limitation, not
    as "organ not used" -- and an excluded overlapping episode must still be
    disclosed even when a separate fully-contained episode also exists.
    """

    row = coverage["MINE"]
    if row.status != AVAILABLE:
        return OrganExperimentScope("MINE", row.status, 0, 0, 0, row.reason)
    counts = {FULLY_CONTAINED: 0, CROSS_BOUNDARY_OVERLAP: 0, OUTSIDE_WINDOW: 0}
    overlap_refs: list[EvidenceRef] = []
    for episode, status, opening_event, closing_event in _mine_episode_classifications(
        snapshot, start_ns, end_ns
    ):
        counts[status] += 1
        if status == CROSS_BOUNDARY_OVERLAP:
            overlap_refs.append(
                _raw_event_ref(
                    "MINE", opening_event,
                    note="earliest raw MineEvent of a boundary-overlapping episode",
                )
            )
            overlap_refs.append(
                _raw_event_ref(
                    "MINE", closing_event,
                    note="latest raw MineEvent of a boundary-overlapping episode",
                )
            )
    status, reason, refs = _scope_status_reason_and_refs("MINE", counts, tuple(overlap_refs))
    return OrganExperimentScope(
        "MINE", status, counts[FULLY_CONTAINED], counts[CROSS_BOUNDARY_OVERLAP],
        counts[OUTSIDE_WINDOW], reason, refs,
    )


def _cosine_episode_classifications(
    snapshot: ScienceLabEvidenceSnapshot,
    start_ns: int,
    end_ns: int,
) -> list[tuple[object, str, object, object]]:
    if snapshot.cosine is None:
        return []
    bounds = _episode_monotonic_bounds(
        snapshot.cosine.raw_events,
        lambda event: f"{getattr(event, 'cosine_session_id', '')}:{getattr(event, 'generation', '')}",
    )
    results: list[tuple[object, str, object, object]] = []
    for episode in snapshot.cosine.episodes:
        if getattr(episode, "parent_session_id", None) != snapshot.parent_session_id:
            raise AnalysisIntegrityError("COSINE episode belongs to another session")
        if not getattr(episode, "is_closed", False):
            continue
        cosine_session_id = getattr(episode, "cosine_session_id", "")
        generation = getattr(episode, "generation", None)
        if type(cosine_session_id) is not str or not cosine_session_id or type(generation) is not int:
            raise AnalysisIntegrityError("closed COSINE episode lacks durable identity")
        identity = f"{cosine_session_id}:{generation}"
        span = bounds.get(identity)
        if span is None:
            raise AnalysisIntegrityError(
                "closed COSINE episode has no matching raw-event monotonic span"
            )
        opening_event, closing_event = span
        status = _classify_experiment_membership(
            getattr(opening_event, "monotonic_ns"), getattr(closing_event, "monotonic_ns"),
            start_ns, end_ns,
        )
        results.append((episode, status, opening_event, closing_event))
    return results


def _build_cosine_rows(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
    start_ns: int,
    end_ns: int,
) -> tuple[CosineEpisodeReportRow, ...]:
    """SP9 Tables 1-2.  Same Chief-approved full-containment boundary policy
    as _build_mine_rows; see cosine_experiment_scope for the CROSS_BOUNDARY_
    OVERLAP / OUTSIDE_WINDOW distinction SP6 must use instead.
    """

    if coverage["COSINE"].status != AVAILABLE or snapshot.cosine is None:
        return ()
    display_id_index = {
        (session_id, generation): display_episode_id
        for session_id, generation, display_episode_id in getattr(snapshot.cosine, "display_ids", ())
    }
    rows: list[CosineEpisodeReportRow] = []
    for episode, status, opening_event, closing_event in _cosine_episode_classifications(
        snapshot, start_ns, end_ns
    ):
        if status != FULLY_CONTAINED:
            continue
        cosine_session_id = str(getattr(episode, "cosine_session_id", ""))
        generation = getattr(episode, "generation")
        identity = f"{cosine_session_id}:{generation}"
        opening_ns = getattr(opening_event, "monotonic_ns")
        closing_ns = getattr(closing_event, "monotonic_ns")
        rows.append(
            CosineEpisodeReportRow(
                episode_id=identity,
                display_episode_id=display_id_index.get((cosine_session_id, generation), ""),
                starting_platform_key=str(getattr(episode, "starting_platform_key", "")),
                starting_platform_label=str(getattr(episode, "starting_platform_label", "")),
                user_choice=getattr(episode, "user_choice", None),
                chosen_break_minutes=getattr(episode, "chosen_break_minutes", None),
                hopper_count=int(getattr(episode, "hopper_count", 0) or 0),
                closure_outcome=getattr(episode, "closure_outcome", None),
                closure_reason=getattr(episode, "closure_reason", None),
                started_at_utc=str(getattr(episode, "started_at_utc", "")),
                ended_at_utc=getattr(episode, "ended_at_utc", None),
                opening_monotonic_ns=opening_ns,
                closing_monotonic_ns=closing_ns,
                provenance=(
                    _raw_event_ref(
                        "COSINE", opening_event,
                        note="earliest raw CosineEvent in this episode's monotonic span",
                    ),
                    _raw_event_ref(
                        "COSINE", closing_event,
                        note="latest raw CosineEvent in this episode's monotonic span",
                    ),
                ),
            )
        )
    return tuple(sorted(rows, key=lambda row: (row.opening_monotonic_ns, row.episode_id)))


def _cosine_experiment_scope(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
    start_ns: int,
    end_ns: int,
) -> OrganExperimentScope:
    row = coverage["COSINE"]
    if row.status != AVAILABLE:
        return OrganExperimentScope("COSINE", row.status, 0, 0, 0, row.reason)
    counts = {FULLY_CONTAINED: 0, CROSS_BOUNDARY_OVERLAP: 0, OUTSIDE_WINDOW: 0}
    overlap_refs: list[EvidenceRef] = []
    for episode, status, opening_event, closing_event in _cosine_episode_classifications(
        snapshot, start_ns, end_ns
    ):
        counts[status] += 1
        if status == CROSS_BOUNDARY_OVERLAP:
            overlap_refs.append(
                _raw_event_ref(
                    "COSINE", opening_event,
                    note="earliest raw CosineEvent of a boundary-overlapping episode",
                )
            )
            overlap_refs.append(
                _raw_event_ref(
                    "COSINE", closing_event,
                    note="latest raw CosineEvent of a boundary-overlapping episode",
                )
            )
    status, reason, refs = _scope_status_reason_and_refs("COSINE", counts, tuple(overlap_refs))
    return OrganExperimentScope(
        "COSINE", status, counts[FULLY_CONTAINED], counts[CROSS_BOUNDARY_OVERLAP],
        counts[OUTSIDE_WINDOW], reason, refs,
    )


_COSECANT_BREAK_ROW_KIND_FIELD: Final = {
    "BREAK_STARTED": "break_started_monotonic_ns",
    "BREAK_COMPLETE": "break_complete_monotonic_ns",
    "BREAK_ALREADY_OVER": "break_already_over_monotonic_ns",
    "FINAL_LOCKED": "final_locked_monotonic_ns",
    "RETURN_CONFIRMED": "return_confirmed_monotonic_ns",
}


def _build_cosecant_break_rows(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
    start_ns: int,
    end_ns: int,
) -> tuple[CosecantBreakRow, ...]:
    """SP10 Tables 1-2 (break timing + escalation).  Locked latency
    definition: BREAK_COMPLETE -> RETURN_CONFIRMED.  A factual return before
    BREAK_COMPLETE (or a break with no certified BREAK_COMPLETE fact at all)
    yields NOT_APPLICABLE -- never 0, never negative.
    """

    if coverage["COSECANT"].status != AVAILABLE:
        return ()
    groups: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for record in _generic_records(snapshot.cosecant, "COSECANT", snapshot.parent_session_id):
        field = _COSECANT_BREAK_ROW_KIND_FIELD.get(record.kind)
        if field is None:
            continue
        payload = _payload(record)
        break_id = payload.get("break_id")
        if type(break_id) is not str or not break_id:
            raise AnalysisIntegrityError("COSECANT fact lacks durable break identity")
        timestamp = payload.get("effective_monotonic_ns", record.occurred_monotonic_ns)
        if type(timestamp) is not int:
            raise AnalysisIntegrityError("COSECANT effective timestamp is malformed")
        if not point_in_window(timestamp, start_ns, end_ns):
            continue
        entry = groups.setdefault(break_id, {"refs": []})
        if field in entry:
            raise AnalysisIntegrityError(f"duplicate COSECANT {record.kind} fact for one break")
        entry[field] = timestamp
        entry["refs"].append(
            EvidenceRef(
                "COSECANT", record.source_event_id, timestamp, record.kind,
                "effective_monotonic_ns from durable fact payload",
            )
        )
        if break_id not in order:
            order.append(break_id)

    rows: list[CosecantBreakRow] = []
    for break_id in order:
        entry = groups[break_id]
        started = entry.get("break_started_monotonic_ns")
        complete = entry.get("break_complete_monotonic_ns")
        already_over = entry.get("break_already_over_monotonic_ns")
        final_locked = entry.get("final_locked_monotonic_ns")
        confirmed = entry.get("return_confirmed_monotonic_ns")

        if confirmed is None:
            latency_ns, status, reason = (
                None, UNAVAILABLE,
                "no certified RETURN_CONFIRMED fact for this break in this experiment window",
            )
        elif complete is None or confirmed < complete:
            latency_ns, status, reason = (
                None, NOT_APPLICABLE, "returned before break completion",
            )
        else:
            latency_ns, status, reason = (
                confirmed - complete, AVAILABLE,
                "BREAK_COMPLETE to RETURN_CONFIRMED (locked definition)",
            )

        rows.append(
            CosecantBreakRow(
                break_id=break_id,
                break_started_monotonic_ns=started,
                break_complete_monotonic_ns=complete,
                break_already_over_monotonic_ns=already_over,
                final_locked_monotonic_ns=final_locked,
                return_confirmed_monotonic_ns=confirmed,
                post_break_return_latency_ns=latency_ns,
                post_break_return_latency_status=status,
                post_break_return_latency_reason=reason,
                provenance=tuple(entry["refs"]),
            )
        )
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                row.break_started_monotonic_ns if row.break_started_monotonic_ns is not None else -1,
                row.break_id,
            ),
        )
    )


def _build_findings(
    metrics: tuple[Chapter3Metric, ...],
) -> tuple[DerivedFinding, ...]:
    by_code = {metric.code: metric for metric in metrics}
    duration = by_code["experiment_duration"]
    findings = [
        DerivedFinding(
            "EXPERIMENT_DURATION",
            "DERIVED",
            f"The selected experiment lasted {duration.value} nanoseconds.",
            duration.provenance,
        )
    ]
    verified = by_code["verified_returns"]
    if verified.status == AVAILABLE:
        findings.append(
            DerivedFinding(
                "VERIFIED_RETURN_COUNT",
                "MEASURED",
                f"{verified.value} verified returns occurred within the selected experiment.",
                verified.provenance,
            )
        )
    for metric in metrics:
        if metric.status == UNAVAILABLE:
            findings.append(
                DerivedFinding(
                    f"{metric.code.upper()}_LIMITATION",
                    "LIMITATION",
                    f"{metric.label} is unavailable because {metric.reason}.",
                    metric.provenance,
                )
            )
    return tuple(findings)


def _build_patterns(
    snapshot: ScienceLabEvidenceSnapshot,
    metrics: tuple[Chapter3Metric, ...],
    start_ns: int,
    end_ns: int,
) -> tuple[CertifiedPattern, ...]:
    by_code = {metric.code: metric for metric in metrics}
    patterns: list[CertifiedPattern] = []
    verified = by_code["verified_returns"]
    if verified.status == AVAILABLE and int(verified.value or 0) >= 2:
        patterns.append(
            CertifiedPattern(
                "MULTIPLE_VERIFIED_RETURNS",
                "Multiple verified returns",
                "At least two factual MIRL verified-return events occurred in the experiment.",
                verified.provenance,
            )
        )

    coverage = {row.source_system: row for row in snapshot.source_coverage}
    mirl_events = _mirl_events(snapshot, coverage)
    verified_by_episode: dict[str, list[object]] = {}
    for event in mirl_events:
        if _event_name(event) == "return_verified" and point_in_window(
            _event_time(event), start_ns, end_ns
        ):
            verified_by_episode.setdefault(str(getattr(event, "episode_id", "")), []).append(event)
    relapse_pairs: list[EvidenceRef] = []
    for event in mirl_events:
        if _event_name(event) != "relapse_detected" or not point_in_window(
            _event_time(event), start_ns, end_ns
        ):
            continue
        prior = tuple(
            candidate
            for candidate in verified_by_episode.get(str(getattr(event, "episode_id", "")), ())
            if _event_time(candidate) < _event_time(event)
        )
        if prior:
            latest = sorted(prior, key=lambda item: (_event_time(item), _event_id(item)))[-1]
            relapse_pairs.extend((_mirl_ref(latest), _mirl_ref(event)))
    if relapse_pairs:
        patterns.append(
            CertifiedPattern(
                "RELAPSE_AFTER_VERIFIED_RETURN",
                "Relapse after verified return",
                "A factual MIRL relapse followed a verified return in the same episode.",
                _dedupe_refs(tuple(relapse_pairs)),
            )
        )
    return tuple(patterns)


def _base_limitations(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
) -> tuple[str, ...]:
    items = [
        "Science Lab analyzes behavioral/software evidence only; it does not directly measure brain state.",
        "Science Lab does not directly measure neurotransmitter activity.",
        *snapshot.limitations,
    ]
    for source in sorted(coverage):
        row = coverage[source]
        if row.status == UNAVAILABLE:
            items.append(f"{source}: unavailable ({row.reason}).")
    return _dedupe(tuple(items))


def _generic_records(evidence: object, source: str, session_id: int) -> tuple[object, ...]:
    if evidence is None:
        return ()
    if getattr(evidence, "session_id", None) != session_id:
        raise AnalysisIntegrityError(f"{source} evidence belongs to another session")
    records = tuple(getattr(evidence, "records", ()) or ())
    for record in records:
        if (
            getattr(record, "source_system", None) != source
            or getattr(record, "session_id", None) != session_id
            or type(getattr(record, "source_event_id", None)) is not str
            or not record.source_event_id
            or type(getattr(record, "kind", None)) is not str
            or not record.kind
            or type(getattr(record, "occurred_monotonic_ns", None)) is not int
            or record.occurred_monotonic_ns < 0
        ):
            raise AnalysisIntegrityError(f"{source} source record is malformed")
        _payload(record)
    return records


def _payload(record: object) -> dict:
    try:
        value = json.loads(getattr(record, "payload_json"))
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AnalysisIntegrityError("source payload is not valid JSON") from exc
    if not isinstance(value, dict):
        raise AnalysisIntegrityError("source payload is not a JSON object")
    return value


def _record_ref(record: object) -> EvidenceRef:
    return EvidenceRef(
        str(record.source_system),
        str(record.source_event_id),
        int(record.occurred_monotonic_ns),
        str(record.kind),
    )


def _mirl_events(
    snapshot: ScienceLabEvidenceSnapshot,
    coverage: dict[str, SourceCoverage],
) -> tuple[object, ...]:
    if coverage["MIRL"].status == UNAVAILABLE:
        return ()
    if snapshot.mirl is None:
        if coverage["MIRL"].status == NO_EVIDENCE:
            return ()
        raise AnalysisIntegrityError("MIRL evidence is absent despite AVAILABLE coverage")
    if snapshot.mirl.session_id != snapshot.parent_session_id:
        raise AnalysisIntegrityError("MIRL evidence belongs to another session")
    events = tuple(snapshot.mirl.events)
    seen_ids: set[str] = set()
    for event in events:
        if (
            getattr(event, "session_id", None) != snapshot.parent_session_id
            or type(getattr(event, "event_id", None)) is not str
            or not event.event_id
            or type(getattr(event, "occurred_monotonic_ns", None)) is not int
            or event.occurred_monotonic_ns < 0
            or not _event_name(event)
        ):
            raise AnalysisIntegrityError("MIRL event is malformed")
        if event.event_id in seen_ids:
            raise AnalysisIntegrityError("MIRL event identity is duplicated")
        seen_ids.add(event.event_id)
    return events


def _event_name(event: object) -> str:
    value = getattr(event, "event_name", "")
    return str(getattr(value, "value", value))


def _event_time(event: object) -> int:
    return int(getattr(event, "occurred_monotonic_ns"))


def _event_id(event: object) -> str:
    return str(getattr(event, "event_id"))


def _mirl_ref(event: object) -> EvidenceRef:
    return EvidenceRef(
        "MIRL", _event_id(event), _event_time(event), _event_name(event)
    )


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _dedupe_refs(values: tuple[EvidenceRef, ...]) -> tuple[EvidenceRef, ...]:
    return tuple(dict.fromkeys(values))


def _collect_provenance(
    experiment_ref: EvidenceRef,
    timeline: tuple[Chapter3TimelineEvent, ...],
    metrics: tuple[Chapter3Metric, ...],
    whole: tuple[WholeMyelinRow, ...],
    findings: tuple[DerivedFinding, ...],
    patterns: tuple[CertifiedPattern, ...],
    return_extrema: SuccessfulReturnOnsetLatencyExtrema,
    sine_stage_rows: tuple[SineStageRow, ...] = (),
    mine_episode_rows: tuple[MineEpisodeReportRow, ...] = (),
    cosine_episode_rows: tuple[CosineEpisodeReportRow, ...] = (),
    cosecant_break_rows: tuple[CosecantBreakRow, ...] = (),
    mine_experiment_scope: OrganExperimentScope | None = None,
    cosine_experiment_scope: OrganExperimentScope | None = None,
) -> tuple[EvidenceRef, ...]:
    refs = [experiment_ref]
    refs.extend(ref for item in timeline for ref in item.provenance)
    refs.extend(ref for item in metrics for ref in item.provenance)
    refs.extend(ref for item in metrics for sample in item.samples for ref in sample.provenance)
    refs.extend(ref for item in whole for ref in item.provenance)
    refs.extend(ref for item in findings for ref in item.provenance)
    refs.extend(ref for item in patterns for ref in item.provenance)
    refs.extend(
        ref
        for sample in return_extrema.samples
        for ref in sample.supporting_event_chain
    )
    refs.extend(ref for item in sine_stage_rows for ref in item.provenance)
    refs.extend(ref for item in mine_episode_rows for ref in item.provenance)
    refs.extend(ref for item in cosine_episode_rows for ref in item.provenance)
    refs.extend(ref for item in cosecant_break_rows for ref in item.provenance)
    if mine_experiment_scope is not None:
        refs.extend(mine_experiment_scope.provenance)
    if cosine_experiment_scope is not None:
        refs.extend(cosine_experiment_scope.provenance)
    return tuple(
        sorted(
            set(refs),
            key=lambda ref: (
                ref.source,
                ref.durable_id,
                -1 if ref.occurred_monotonic_ns is None else ref.occurred_monotonic_ns,
                ref.event_kind,
                ref.note,
            ),
        )
    )


def _validate_package(
    package: Chapter3ResultPackage,
    selected: ScienceLabExperimentRecord,
) -> None:
    if package.analysis_status != CERTIFIED:
        raise AnalysisIntegrityError("package is not marked CERTIFIED")
    if selected.status != "COMPLETED" or selected.ended_monotonic_ns is None:
        raise AnalysisIntegrityError("selected experiment is not factually completed")
    if (
        package.experiment_id != selected.experiment_id
        or package.parent_session_id != selected.parent_session_id
        or package.experiment_start_monotonic_ns != selected.started_monotonic_ns
        or package.experiment_end_monotonic_ns != selected.ended_monotonic_ns
        or package.experiment_started_at_utc != selected.started_at_utc
        or package.experiment_ended_at_utc != selected.ended_at_utc
    ):
        raise AnalysisIntegrityError("package experiment identity changed")
    _validate_window(
        package.experiment_start_monotonic_ns,
        package.experiment_end_monotonic_ns,
    )
    seen_timeline: set[tuple[str, str, str]] = set()
    for event in package.timeline:
        if not point_in_window(
            event.occurred_monotonic_ns,
            package.experiment_start_monotonic_ns,
            package.experiment_end_monotonic_ns,
        ):
            raise AnalysisIntegrityError("timeline event escaped experiment window")
        key = (event.source, event.durable_id, event.stage)
        if key in seen_timeline:
            raise AnalysisIntegrityError("timeline contains duplicate identity/stage")
        seen_timeline.add(key)
    if tuple(metric.code for metric in package.key_metrics) != tuple(
        code for code, _label in _METRIC_ROSTER
    ):
        raise AnalysisIntegrityError("metric roster changed")
    for metric in package.key_metrics:
        _validate_value(metric.status, metric.value)
        if metric.code == "experiment_duration" and (
            metric.value != package.experiment_end_monotonic_ns
            - package.experiment_start_monotonic_ns
            or metric.value < 0
        ):
            raise AnalysisIntegrityError("experiment duration is inconsistent")
    if tuple(row.source for row in package.whole_myelin_summary) != tuple(
        source for source, _label in _WHOLE_ROSTER
    ):
        raise AnalysisIntegrityError("Whole-MYELIN roster changed")
    coverage = _coverage_by_source(package.source_coverage)
    for source, row in coverage.items():
        if row.status == UNAVAILABLE and not any(
            source in limitation for limitation in package.limitations
        ):
            raise AnalysisIntegrityError("unavailable source limitation was dropped")
    for metric in package.key_metrics:
        if metric.status == UNAVAILABLE and not any(
            metric.reason in limitation for limitation in package.limitations
        ):
            raise AnalysisIntegrityError("unavailable metric limitation was dropped")
    extrema = package.successful_return_onset_latency_extrema
    if not isinstance(extrema, SuccessfulReturnOnsetLatencyExtrema):
        raise AnalysisIntegrityError("certified return-onset extrema are missing")
    if (
        extrema.experiment_start_monotonic_ns
        != package.experiment_start_monotonic_ns
        or extrema.experiment_end_monotonic_ns
        != package.experiment_end_monotonic_ns
    ):
        raise AnalysisIntegrityError("return-onset extrema escaped experiment scope")
    for sample in extrema.samples:
        if any(
            not point_in_window(
                ref.occurred_monotonic_ns,
                package.experiment_start_monotonic_ns,
                package.experiment_end_monotonic_ns,
            )
            for ref in sample.supporting_event_chain
        ):
            raise AnalysisIntegrityError("return-onset evidence escaped experiment window")
    seen_stage_keys: set[tuple[str, int, str]] = set()
    for row in package.sine_stage_rows:
        if not point_in_window(
            row.display_monotonic_ns,
            package.experiment_start_monotonic_ns,
            package.experiment_end_monotonic_ns,
        ):
            raise AnalysisIntegrityError("SINE stage row escaped experiment window")
        key = (row.episode_id, row.stage, row.popup_request_id)
        if key in seen_stage_keys:
            raise AnalysisIntegrityError("SINE stage row contains duplicate identity")
        seen_stage_keys.add(key)
    seen_mine_ids: set[str] = set()
    for row in package.mine_episode_rows:
        if not (
            package.experiment_start_monotonic_ns <= row.opening_monotonic_ns
            and row.closing_monotonic_ns < package.experiment_end_monotonic_ns
        ):
            raise AnalysisIntegrityError("MINE episode row escaped experiment window")
        if row.episode_id in seen_mine_ids:
            raise AnalysisIntegrityError("MINE episode row contains duplicate identity")
        seen_mine_ids.add(row.episode_id)
    seen_cosine_ids: set[str] = set()
    for row in package.cosine_episode_rows:
        if not (
            package.experiment_start_monotonic_ns <= row.opening_monotonic_ns
            and row.closing_monotonic_ns < package.experiment_end_monotonic_ns
        ):
            raise AnalysisIntegrityError("COSINE episode row escaped experiment window")
        if row.episode_id in seen_cosine_ids:
            raise AnalysisIntegrityError("COSINE episode row contains duplicate identity")
        seen_cosine_ids.add(row.episode_id)
    seen_break_ids: set[str] = set()
    for row in package.cosecant_break_rows:
        for candidate in (
            row.break_started_monotonic_ns,
            row.break_complete_monotonic_ns,
            row.break_already_over_monotonic_ns,
            row.final_locked_monotonic_ns,
            row.return_confirmed_monotonic_ns,
        ):
            if candidate is not None and not point_in_window(
                candidate,
                package.experiment_start_monotonic_ns,
                package.experiment_end_monotonic_ns,
            ):
                raise AnalysisIntegrityError("COSECANT break row escaped experiment window")
        if row.break_id in seen_break_ids:
            raise AnalysisIntegrityError("COSECANT break row contains duplicate identity")
        seen_break_ids.add(row.break_id)
    for source, scope, rows in (
        ("MINE", package.mine_experiment_scope, package.mine_episode_rows),
        ("COSINE", package.cosine_experiment_scope, package.cosine_episode_rows),
    ):
        if not isinstance(scope, OrganExperimentScope) or scope.source != source:
            raise AnalysisIntegrityError(f"{source} experiment scope is missing or mislabeled")
        if scope.status == FULLY_CONTAINED and not rows:
            raise AnalysisIntegrityError(
                f"{source} experiment scope claims FULLY_CONTAINED with no rows"
            )
        if scope.status != FULLY_CONTAINED and rows:
            raise AnalysisIntegrityError(
                f"{source} experiment scope contradicts its own quantitative rows"
            )
        if scope.fully_contained_count != len(rows):
            # Mixed-membership guard: the contained COUNT must exactly match
            # the row count even when cross-boundary episodes also exist in
            # the same experiment -- a fully-contained episode's presence
            # must never be miscounted because an excluded episode is also
            # present, and vice versa.
            raise AnalysisIntegrityError(
                f"{source} experiment scope's fully_contained_count disagrees with its rows"
            )
        if scope.status == CROSS_BOUNDARY_OVERLAP and not scope.provenance:
            raise AnalysisIntegrityError(
                f"{source} CROSS_BOUNDARY_OVERLAP scope requires provenance"
            )
        if scope.cross_boundary_overlap_count > 0 and not scope.provenance:
            # Same requirement OrganExperimentScope.__post_init__ already
            # enforces, re-checked here so a future refactor of either
            # class cannot silently drop it without breaking a test.
            raise AnalysisIntegrityError(
                f"{source} scope has overlapping episodes but lost their provenance"
            )


__all__ = [
    "ANALYSIS_UNAVAILABLE",
    "AVAILABLE",
    "AnalysisValue",
    "CERTIFIED",
    "CROSS_BOUNDARY_OVERLAP",
    "CertifiedPattern",
    "Chapter3AnalysisOutcome",
    "Chapter3Metric",
    "Chapter3ResultPackage",
    "Chapter3TimelineEvent",
    "CosecantBreakRow",
    "CosineEpisodeReportRow",
    "DerivedFinding",
    "EvidenceRef",
    "FULLY_CONTAINED",
    "MineEpisodeReportRow",
    "NO_COMPLETED_EXPERIMENT",
    "NO_EVIDENCE",
    "NOT_APPLICABLE",
    "OUTSIDE_WINDOW",
    "OrganExperimentScope",
    "SineStageRow",
    "SuccessfulReturnOnsetLatencyExtrema",
    "SuccessfulReturnOnsetLatencySample",
    "UNAVAILABLE",
    "WholeMyelinRow",
    "analyze_finalized_session",
    "clip_interval",
    "point_in_window",
    "unavailable_outcome",
]
