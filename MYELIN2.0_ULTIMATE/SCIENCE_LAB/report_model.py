"""Pure Phase-4 adapter and page planner for the MYELIN report PDF.

The module consumes one immutable, certified Chapter 3 package (or its exact
transfer receipt).  It performs no I/O and never imports persistence, Qt, or an
organ runtime.  Its only calculations are presentation formatting, direct
cardinalities of already-certified rows, and deterministic pagination.

Report-facing episode/break display codes (``EPI-``/``MINE-``/``COS-``/
``CSC-DDMMYYYY-NN``).  For SINE/MIRL, MINE and COSINE, the official code is
resolved from each organ's own live, cross-session projection during
certification (SCIENCE_LAB/analysis.py) and carried through the certified
package/rows verbatim -- this module only reads it (Chief's Phase 5 final
correction pass ruling: a single-experiment adapter with no organ-runtime or
persistence access cannot see the global daily sequence those live
dashboards use, so it must never recompute a lookalike).  COSECANT has no
prior live dashboard convention, so its ``CSC-DDMMYYYY-NN`` family remains a
report-side presentation code computed by ``_report_local_episode_codes``
below.  The raw scientific identifier is never touched in any case -- these
codes are substituted only at the point a value is placed into a display
tuple/label.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone as _dt_timezone
from typing import Final
from zoneinfo import ZoneInfo

from SCIENCE_LAB.analysis import (
    AVAILABLE,
    CERTIFIED,
    CROSS_BOUNDARY_OVERLAP,
    FULLY_CONTAINED,
    NO_EVIDENCE,
    NOT_APPLICABLE,
    OUTSIDE_WINDOW,
    UNAVAILABLE,
    Chapter3ResultPackage,
    CosecantBreakRow,
    CosineEpisodeReportRow,
    EvidenceRef,
    MineEpisodeReportRow,
    OrganExperimentScope,
    SineStageRow,
    SuccessfulReturnOnsetLatencyExtrema,
)
from SCIENCE_LAB.chapters import COSECANT_TIMING_FACTS
from SCIENCE_LAB.handoff import Chapter3TransferReceipt


REPORT_MODEL_SCHEMA_VERSION: Final = "myelin-report-phase4-render-model-v1"
ORGAN_ORDER: Final = ("SINE", "MINE", "COSINE", "SECANT", "COSECANT")
PRIMARY_TABLE_ROW_CAPACITY: Final = 2
CONTINUATION_TABLE_ROW_CAPACITY: Final = 22
NANOSECONDS_PER_SECOND: Final = 1_000_000_000


def _policy_clock_to_ns(value: str) -> int:
    """Convert a frozen M:SS policy label to nanoseconds without rounding."""

    try:
        minutes_text, seconds_text = value.split(":", 1)
        minutes, seconds = int(minutes_text), int(seconds_text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError("frozen COSECANT timing fact is malformed") from exc
    if minutes < 0 or seconds < 0 or seconds >= 60:
        raise RuntimeError("frozen COSECANT timing fact is out of range")
    return (minutes * 60 + seconds) * NANOSECONDS_PER_SECOND


COSECANT_ALREADY_OVER_DELAY_NS: Final = _policy_clock_to_ns(
    COSECANT_TIMING_FACTS["already_over_delay"]
)
COSECANT_FINAL_LOCK_DELAY_NS: Final = _policy_clock_to_ns(
    COSECANT_TIMING_FACTS["final_lock_delay"]
)
COSECANT_MINIMUM_BREAK_NS: Final = (
    COSECANT_TIMING_FACTS["break_minimum_seconds"] * NANOSECONDS_PER_SECOND
)
COSECANT_MAXIMUM_BREAK_NS: Final = (
    COSECANT_TIMING_FACTS["break_maximum_hours"] * 60 * 60 * NANOSECONDS_PER_SECOND
)


class ReportModelError(ValueError):
    """The supplied certified snapshot cannot produce a safe report model."""


@dataclass(frozen=True, slots=True)
class SnapshotCard:
    label: str
    value: str
    caption: str
    status: str = AVAILABLE


@dataclass(frozen=True, slots=True)
class TableRenderModel:
    number: int
    title: str
    description: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    widths_mm: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.headers or len(self.headers) != len(self.widths_mm):
            raise ReportModelError("table headers and widths disagree")
        if any(len(row) != len(self.headers) for row in self.rows):
            raise ReportModelError("table row width disagrees with its header")


@dataclass(frozen=True, slots=True)
class ChartRenderModel:
    status: str
    kind: str
    categories: tuple[str, ...]
    values: tuple[float, ...]
    unit: str
    reason: str
    observation_label: str

    def __post_init__(self) -> None:
        if self.status not in (AVAILABLE, UNAVAILABLE, NO_EVIDENCE, NOT_APPLICABLE):
            raise ReportModelError("chart has an unknown status")
        if self.status == AVAILABLE:
            if not self.values or len(self.values) != len(self.categories):
                raise ReportModelError("available chart requires aligned factual points")
        elif self.values or self.categories:
            raise ReportModelError("non-available chart cannot carry points")


@dataclass(frozen=True, slots=True)
class OrganRenderModel:
    organ: str
    page_code: str
    status: str
    reason: str
    overlap_note: str
    snapshot_cards: tuple[SnapshotCard, ...]
    pathway_labels: tuple[str, ...]
    table1: TableRenderModel
    table2: TableRenderModel
    chart: ChartRenderModel
    discussion_note: str
    provenance: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class UnavailableOrgan:
    organ: str
    status: str
    reason: str
    provenance: tuple[EvidenceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class ReportRenderModel:
    schema_version: str
    experiment_id: str
    parent_session_id: int
    experiment_started_at_utc: str
    experiment_ended_at_utc: str
    analysis_status: str
    organ_pages: tuple[OrganRenderModel, ...]
    unavailable_organs: tuple[UnavailableOrgan, ...]
    limitations: tuple[str, ...]
    provenance: tuple[EvidenceRef, ...]

    def organ_page(self, organ: str) -> OrganRenderModel | None:
        return next((page for page in self.organ_pages if page.organ == organ), None)


@dataclass(frozen=True, slots=True)
class PlannedPage:
    kind: str
    page_code: str
    physical_page: int
    organ: str = ""
    table_number: int = 0
    rows: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class ReportPagePlan:
    pages: tuple[PlannedPage, ...]


def _dedupe_refs(refs) -> tuple[EvidenceRef, ...]:
    return tuple(dict.fromkeys(refs))


def _presentation_aliases(raw_ids, *, prefix: str) -> dict[str, str]:
    """Deterministic, first-occurrence-ordered, bounded display aliases for
    an opaque production identifier (Chief's Phase 5C presentation-ID
    ruling, following the full-source-audit revision).

    Production episode/attempt/break identifiers are long, opaque, and were
    never sized against the frozen Phase-3 table/journey-box geometry --
    only Phase-4's own short synthetic test ids were.  This alias exists
    ONLY to fit a fixed-width report cell; it is built after every
    grouping, count, and provenance reference has already been resolved
    against the real raw id, and it is used nowhere else.  The raw id is
    never modified, shortened, or dropped from the certified package,
    scope logic, or provenance -- only substituted at the point a value is
    placed into a display tuple/label."""

    unique_ids = tuple(dict.fromkeys(raw_ids))
    width = max(2, len(str(len(unique_ids))))
    return {raw_id: f"{prefix}{index:0{width}d}" for index, raw_id in enumerate(unique_ids, start=1)}


_IST: Final = ZoneInfo("Asia/Kolkata")


def _parse_certified_utc(value: str | None) -> datetime | None:
    """Parse a certified ISO-8601 UTC timestamp; ``None`` for missing/malformed
    input rather than raising -- a formatting helper must degrade to
    UNAVAILABLE, never fail report generation over a display concern."""

    if not value or type(value) is not str:
        return None
    try:
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(_dt_timezone.utc)


def _ist_date_key(moment: datetime) -> str:
    local = moment.astimezone(_IST)
    return f"{local.day:02d}{local.month:02d}{local.year:04d}"


def _ist_time_only(value: str | None) -> str:
    """``HH:MM:SS IST`` for a certified UTC timestamp (Chief's Bug I): a real
    ``zoneinfo`` conversion, never a manual +5:30 offset add.  The underlying
    certified UTC string is never altered -- this is a display-only read."""

    moment = _parse_certified_utc(value)
    if moment is None:
        return UNAVAILABLE
    local = moment.astimezone(_IST)
    return f"{local.hour:02d}:{local.minute:02d}:{local.second:02d} IST"


def _report_local_episode_codes(entries, *, prefix: str) -> dict[str, str]:
    """Report-local ``{PREFIX}-DDMMYYYY-NN`` display codes.

    As of the Phase 5 final correction pass, this is used ONLY for COSECANT,
    which has no prior live dashboard convention (confirmed by forensic
    audit) -- Chief defines this ``CSC-DDMMYYYY-NN`` family as a report-side
    presentation code, scoped to the one certified experiment being
    reported, with no live dashboard for it to disagree with.

    SINE/MIRL, MINE and COSINE no longer use this function: their official
    codes are resolved from each organ's own live, cross-session projection
    during certification (SCIENCE_LAB/analysis.py) and carried through
    verbatim -- see the module docstring above.

    ``entries`` is an already-correctly-ordered iterable of
    ``(raw_id, utc_moment_or_None)``; the date+sequence counter is applied in
    that exact order (Python's sort below is stable, so entries sharing a
    moment -- or missing one, as COSECANT's own experiment-start fallback
    does -- keep the caller's ordering)."""

    dated = [(raw_id, moment) for raw_id, moment in entries if moment is not None]
    dated.sort(key=lambda item: item[1])
    counts: dict[str, int] = {}
    codes: dict[str, str] = {}
    for raw_id, moment in dated:
        date_key = _ist_date_key(moment)
        counts[date_key] = counts.get(date_key, 0) + 1
        codes[raw_id] = f"{prefix}-{date_key}-{counts[date_key]:02d}"
    return codes


def _scope_unavailable_reason(organ: str, scope: OrganExperimentScope) -> str:
    """A never-blank reason for an unavailable organ scope (Chief's Bug M/N).

    Preserves ``scope.reason`` verbatim when it is a real, non-empty string;
    only substitutes a neutral, status-appropriate fallback when the scope
    itself carried none.  Never changes ``scope.status`` and never claims an
    organ was unused -- it only ever describes why no quantitative result
    exists for the certified evidence state that is actually present."""

    if scope.reason:
        return scope.reason
    fallback = {
        NO_EVIDENCE: f"no certified {organ} result rows for the selected experiment",
        CROSS_BOUNDARY_OVERLAP: f"{organ} episode(s) crossed the selected experiment boundary",
        OUTSIDE_WINDOW: f"no certified {organ} episode falls within the selected experiment window",
        UNAVAILABLE: f"{organ} evidence is not available for the selected experiment",
    }
    return fallback.get(scope.status, f"no certified {organ} evidence for the selected experiment")


def _coverage(package: Chapter3ResultPackage, source: str):
    return next((row for row in package.source_coverage if row.source_system == source), None)


def _unavailable_from_coverage(package: Chapter3ResultPackage, source: str) -> UnavailableOrgan:
    row = _coverage(package, source)
    if row is None:
        return UnavailableOrgan(source, UNAVAILABLE, f"{source} source coverage is missing")
    status = row.status if row.status in (NO_EVIDENCE, UNAVAILABLE) else NO_EVIDENCE
    reason = row.reason or f"no certified {source} result rows for the selected experiment"
    return UnavailableOrgan(source, status, reason)


def _format_duration_ns(value: int | None) -> str:
    if value is None:
        return UNAVAILABLE
    if type(value) is not int or value < 0:
        raise ReportModelError("duration must be a non-negative integer nanosecond value")
    seconds = value / 1_000_000_000
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)} min {remainder:.1f} s"


def _format_offset(value: int | None, start_ns: int) -> str:
    if value is None:
        return UNAVAILABLE
    if type(value) is not int or value < start_ns:
        raise ReportModelError("event offset precedes the certified experiment start")
    seconds = (value - start_ns) // 1_000_000_000
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"T+{hours:02d}:{minutes:02d}:{seconds:02d}"


def _metric_display(package: Chapter3ResultPackage, code: str) -> tuple[str, str]:
    metric = next((item for item in package.key_metrics if item.code == code), None)
    if metric is None:
        return UNAVAILABLE, UNAVAILABLE
    if metric.status == AVAILABLE:
        return str(metric.value), AVAILABLE
    return metric.status, metric.status


def _chart(points: tuple[tuple[str, float], ...], *, kind: str, unit: str, empty_reason: str) -> ChartRenderModel:
    if not points:
        return ChartRenderModel(UNAVAILABLE, kind, (), (), unit, empty_reason, "Unavailable")
    label = "Single certified observation" if len(points) == 1 else "Certified observations"
    return ChartRenderModel(
        AVAILABLE,
        kind,
        tuple(label for label, _value in points),
        tuple(float(value) for _label, value in points),
        unit,
        "",
        label,
    )


def _validate_scope(source: str, scope: OrganExperimentScope | None, rows: tuple) -> OrganExperimentScope:
    if not isinstance(scope, OrganExperimentScope) or scope.source != source:
        raise ReportModelError(f"{source} experiment scope is missing or mislabeled")
    if scope.fully_contained_count != len(rows):
        raise ReportModelError(f"{source} contained count disagrees with report rows")
    if rows and scope.status != FULLY_CONTAINED:
        raise ReportModelError(f"{source} rows contradict experiment scope")
    if not rows and scope.status == FULLY_CONTAINED:
        raise ReportModelError(f"{source} scope claims contained evidence without rows")
    return scope


def _validate_cosecant_temporal_integrity(row: CosecantBreakRow) -> None:
    """Reject impossible certified COSECANT sequences without repairing them."""

    anchors = {
        "BREAK_STARTED": row.break_started_monotonic_ns,
        "BREAK_COMPLETE": row.break_complete_monotonic_ns,
        "BREAK_ALREADY_OVER": row.break_already_over_monotonic_ns,
        "FINAL_LOCKED": row.final_locked_monotonic_ns,
        "RETURN_CONFIRMED": row.return_confirmed_monotonic_ns,
    }
    for label, value in anchors.items():
        if value is not None and (type(value) is not int or value < 0):
            raise ReportModelError(f"COSECANT {row.break_id} has malformed {label} time")

    started = row.break_started_monotonic_ns
    complete = row.break_complete_monotonic_ns
    reminder = row.break_already_over_monotonic_ns
    final_lock = row.final_locked_monotonic_ns
    confirmed = row.return_confirmed_monotonic_ns

    if started is not None and any(
        value is not None and value < started
        for value in (complete, reminder, final_lock, confirmed)
    ):
        raise ReportModelError(f"COSECANT {row.break_id} contains an event before BREAK_STARTED")
    if started is not None and complete is not None:
        break_duration = complete - started
        if not COSECANT_MINIMUM_BREAK_NS <= break_duration <= COSECANT_MAXIMUM_BREAK_NS:
            raise ReportModelError(
                f"COSECANT {row.break_id} break duration violates the frozen policy bounds"
            )
    if reminder is not None:
        if complete is None or reminder < complete + COSECANT_ALREADY_OVER_DELAY_NS:
            raise ReportModelError(
                f"COSECANT {row.break_id} BREAK_ALREADY_OVER violates the frozen +5:00 policy"
            )
        if confirmed is not None and reminder >= confirmed:
            raise ReportModelError(f"COSECANT {row.break_id} reminder occurs after return")
    if final_lock is not None:
        if reminder is None:
            raise ReportModelError(f"COSECANT {row.break_id} FINAL_LOCKED lacks its reminder path")
        if final_lock < reminder + COSECANT_FINAL_LOCK_DELAY_NS:
            raise ReportModelError(
                f"COSECANT {row.break_id} FINAL_LOCKED violates the frozen subsequent +1:00 policy"
            )
        if confirmed is not None and final_lock >= confirmed:
            raise ReportModelError(f"COSECANT {row.break_id} final lock occurs after return")

    status = row.post_break_return_latency_status
    latency = row.post_break_return_latency_ns
    if status == AVAILABLE:
        if complete is None or confirmed is None or confirmed < complete:
            raise ReportModelError(f"COSECANT {row.break_id} AVAILABLE latency lacks ordered anchors")
        if latency != confirmed - complete:
            raise ReportModelError(
                f"COSECANT {row.break_id} supplied latency disagrees with BREAK_COMPLETE to RETURN_CONFIRMED"
            )
    elif status == NOT_APPLICABLE:
        if confirmed is None or (complete is not None and confirmed >= complete):
            raise ReportModelError(
                f"COSECANT {row.break_id} NOT_APPLICABLE does not describe an early return"
            )
        if reminder is not None or final_lock is not None:
            raise ReportModelError(f"COSECANT {row.break_id} escalates after an early return")
    elif status == UNAVAILABLE and confirmed is not None:
        raise ReportModelError(
            f"COSECANT {row.break_id} UNAVAILABLE latency contradicts RETURN_CONFIRMED"
        )


def _validate_package(package: Chapter3ResultPackage) -> None:
    if not isinstance(package, Chapter3ResultPackage):
        raise TypeError("report generation requires a Chapter3ResultPackage")
    if package.analysis_status != CERTIFIED:
        raise ReportModelError("report generation requires CERTIFIED analysis")
    if type(package.experiment_id) is not str or not package.experiment_id.strip():
        raise ReportModelError("certified report package requires an experiment id")
    if type(package.parent_session_id) is not int or package.parent_session_id < 0:
        raise ReportModelError("certified report package requires a parent session id")
    if package.experiment_end_monotonic_ns <= package.experiment_start_monotonic_ns:
        raise ReportModelError("certified experiment window is invalid")
    if not isinstance(package.successful_return_onset_latency_extrema, SuccessfulReturnOnsetLatencyExtrema):
        raise ReportModelError("certified SINE return-onset extrema are missing")
    _validate_scope("MINE", package.mine_experiment_scope, package.mine_episode_rows)
    _validate_scope("COSINE", package.cosine_experiment_scope, package.cosine_episode_rows)
    if len({(row.episode_id, row.stage, row.popup_request_id) for row in package.sine_stage_rows}) != len(package.sine_stage_rows):
        raise ReportModelError("SINE factual display identity is duplicated")
    sine_display_map = dict(package.sine_episode_display_ids)
    if len(sine_display_map) != len(package.sine_episode_display_ids):
        raise ReportModelError("SINE episode display code table contains a duplicate raw episode id")
    referenced_sine_episode_ids = {row.episode_id for row in package.sine_stage_rows}
    if package.successful_return_onset_latency_extrema is not None:
        referenced_sine_episode_ids |= {
            sample.episode_id for sample in package.successful_return_onset_latency_extrema.samples
        }
    missing_sine_codes = referenced_sine_episode_ids - sine_display_map.keys()
    if missing_sine_codes:
        raise ReportModelError(
            "certified package is missing an official display code for SINE "
            f"episode(s): {sorted(missing_sine_codes)!r}"
        )
    for rows, row_type, label in (
        (package.sine_stage_rows, SineStageRow, "SINE"),
        (package.mine_episode_rows, MineEpisodeReportRow, "MINE"),
        (package.cosine_episode_rows, CosineEpisodeReportRow, "COSINE"),
        (package.cosecant_break_rows, CosecantBreakRow, "COSECANT"),
    ):
        if any(not isinstance(row, row_type) or not row.provenance for row in rows):
            raise ReportModelError(f"{label} report rows are malformed or lack provenance")
    for row in package.cosecant_break_rows:
        _validate_cosecant_temporal_integrity(row)


def _sine_model(package: Chapter3ResultPackage) -> OrganRenderModel | UnavailableOrgan:
    extrema = package.successful_return_onset_latency_extrema
    rows = package.sine_stage_rows
    samples = extrema.samples
    if not rows and not samples:
        cov = _coverage(package, "SINE")
        mirl = _coverage(package, "MIRL")
        selected = cov if cov is not None and cov.status != AVAILABLE else mirl
        if selected is None:
            return UnavailableOrgan("SINE", UNAVAILABLE, "SINE/MIRL source coverage is missing")
        status = selected.status if selected.status in (NO_EVIDENCE, UNAVAILABLE) else NO_EVIDENCE
        return UnavailableOrgan("SINE", status, selected.reason or "no certified SINE result evidence")

    episode_ids = tuple(dict.fromkeys([row.episode_id for row in rows] + [sample.episode_id for sample in samples]))
    attempt_alias = _presentation_aliases(
        tuple(dict.fromkeys(sample.attempt_id for sample in samples)), prefix="ATT-"
    )
    observed_stages = tuple(sorted({row.stage for row in rows}))
    relapses, relapse_status = _metric_display(package, "relapses")
    first_display_by_episode = {}
    for row in sorted(rows, key=lambda item: item.display_monotonic_ns):
        first_display_by_episode.setdefault(row.episode_id, row)
    # Official EPI-DDMMYYYY-NN codes, resolved from MIRL's own live global
    # projection during certification (Chief's Phase 5 final correction pass
    # ruling) -- never recomputed here.  See
    # SCIENCE_LAB/analysis.py::_resolve_sine_mirl_display_codes.
    episode_code = dict(package.sine_episode_display_ids)
    missing_codes = [episode_id for episode_id in episode_ids if episode_id not in episode_code]
    if missing_codes:
        raise ReportModelError(
            f"certified package is missing an official display code for SINE episode(s): {missing_codes!r}"
        )
    # A genuine episode is counted once, not once per raw identity space.
    # ``episode_ids`` is the union of SINE's own ``episode_uid`` and MIRL's
    # own ``episode_id`` -- two different raw-ID namespaces that can both
    # refer to the SAME real episode (SINE and MIRL each mint their own
    # identity for it).  The already-validated join in
    # SCIENCE_LAB/analysis.py::_resolve_sine_mirl_display_codes resolves
    # both namespaces to one shared official display code per genuine
    # episode, so counting DISTINCT resolved codes -- not distinct raw
    # ids -- is the correct genuine-episode count (Chief's Phase 5 SCI03
    # correction: this fixed a real double-count, EPI-16092026-03 alone
    # was being reported as "Episodes: 2").
    genuine_episode_count = len({episode_code[episode_id] for episode_id in episode_ids})
    recovery_rows = []
    for sample in samples:
        opening = first_display_by_episode.get(sample.episode_id)
        opening_text = opening.display_wall_time_utc if opening and opening.display_wall_time_utc else _format_offset(
            sample.opening_sine_display.occurred_monotonic_ns, package.experiment_start_monotonic_ns
        )
        recovery_rows.append((
            episode_code[sample.episode_id], attempt_alias[sample.attempt_id],
            opening_text, _format_duration_ns(sample.latency_ns),
        ))
    stage_rows = tuple(
        (
            episode_code[row.episode_id],
            row.display_wall_time_utc or _format_offset(row.display_monotonic_ns, package.experiment_start_monotonic_ns),
            f"SINE-{row.stage}",
            row.response or UNAVAILABLE,
        )
        for row in rows
    )
    highest = {}
    for row in rows:
        highest[row.episode_id] = max(row.stage, highest.get(row.episode_id, 0))
    chart = _chart(
        tuple((episode_code[episode_id], float(stage)) for episode_id, stage in highest.items()),
        kind="stage",
        unit="SINE stage",
        empty_reason="no certified per-episode SINE stage points",
    )
    provenance = _dedupe_refs(
        [ref for row in rows for ref in row.provenance]
        + [ref for sample in samples for ref in sample.supporting_event_chain]
    )
    # The journey map is a behavioural pathway, not an identifier lookup: it
    # shows the factual stage sequence exactly as displayed (chronological
    # display order), with same-stage retries kept as separate nodes rather
    # than collapsed -- no database identifier belongs on this figure at all.
    pathway = tuple(
        f"SINE-{row.stage}" for row in sorted(rows, key=lambda item: item.display_monotonic_ns)[:5]
    )
    if samples:
        pathway += ("VERIFIED RETURN",)
    return OrganRenderModel(
        "SINE", "SP7", AVAILABLE, "certified factual SINE displays or MIRL return samples are present", "",
        (
            SnapshotCard("Episodes", str(genuine_episode_count), "Distinct certified SINE episode identities represented"),
            SnapshotCard("SINE stages observed", ", ".join(f"SINE-{stage}" for stage in observed_stages) or UNAVAILABLE, "Factual displayed levels", AVAILABLE if observed_stages else UNAVAILABLE),
            SnapshotCard("Verified returns", str(len(samples)), "Certified successful MIRL return-onset samples"),
            SnapshotCard("Relapses", relapses, "Certified Chapter 3 relapse metric", relapse_status),
            SnapshotCard("Data status", AVAILABLE, "Certified SINE results available"),
        ),
        pathway or ("CERTIFIED SINE EVIDENCE",),
        TableRenderModel(1, "MIRL RECOVERY SUMMARY", "Successful return-onset samples; latency is opening SINE display to final successful return verification start.", ("EPISODE", "ATTEMPT", "FIRST SINE DISPLAY", "RETURN ONSET LATENCY"), tuple(recovery_rows), (20, 20, 24, 24)),
        TableRenderModel(2, "SINE STAGE SUMMARY", "Every factual display is retained, including same-stage retries with distinct popup identities.", ("EPISODE", "DISPLAY TIME", "SINE LEVEL", "RESPONSE"), stage_rows, (20, 20, 20, 24)),
        chart,
        "The page reports software-observed SINE displays and MIRL-verified behavioural return. It does not infer cognitive recovery.",
        provenance,
    )


def _scope_note(scope: OrganExperimentScope) -> str:
    if scope.cross_boundary_overlap_count:
        return (
            f"{scope.fully_contained_count} complete episode(s) analysed; "
            f"{scope.cross_boundary_overlap_count} overlapping episode(s) excluded at the experiment boundary."
        )
    return ""


def _mine_model(package: Chapter3ResultPackage) -> OrganRenderModel | UnavailableOrgan:
    rows = package.mine_episode_rows
    scope = package.mine_experiment_scope
    if not rows:
        return UnavailableOrgan("MINE", scope.status, _scope_unavailable_reason("MINE", scope), scope.provenance)
    branch_rows = tuple(row for row in rows if row.branch)
    # Official MINE-DDMMYYYY-NN code, carried verbatim from
    # MineEpisodeProjection.display_episode_id during certification -- never
    # recomputed here (Chief's Phase 5 final correction pass ruling).
    episode_code = {row.episode_id: row.display_episode_id for row in rows}
    table1 = tuple((episode_code[row.episode_id], str(package.parent_session_id), _ist_time_only(row.started_at_utc), row.closure_outcome or row.closure_reason or UNAVAILABLE) for row in rows)
    table2 = []
    for row in rows:
        if row.important_duration_minutes is not None:
            timer = f"{row.important_duration_minutes} min"
        elif row.branch == "I_WILL_COME_BACK":
            timer = "13:15 policy"
        else:
            timer = NOT_APPLICABLE
        outcome = "VERIFIED RETURN" if row.return_verified else (row.closure_outcome or row.closure_reason or UNAVAILABLE)
        table2.append((episode_code[row.episode_id], row.branch or UNAVAILABLE, timer, outcome))
    branch_counts = {}
    for row in branch_rows:
        branch_counts[row.branch] = branch_counts.get(row.branch, 0) + 1
    chart = _chart(tuple((label, count) for label, count in branch_counts.items()), kind="bar", unit="episodes", empty_reason="MINE branch is not exposed for any contained episode")
    pathway = tuple(dict.fromkeys([f"BRANCH: {row.branch}" for row in branch_rows] + [f"CLOSURE: {row.closure_outcome}" for row in rows if row.closure_outcome]))
    provenance = _dedupe_refs([ref for row in rows for ref in row.provenance] + list(scope.provenance))
    return OrganRenderModel(
        "MINE", "SP8", AVAILABLE, scope.reason, _scope_note(scope),
        (
            SnapshotCard("Messaging episodes", str(len(rows)), "Fully-contained certified MINE episodes"),
            SnapshotCard("MINE-1 displays", UNAVAILABLE, "MINE-1 display count is unavailable in this report.", UNAVAILABLE),
            SnapshotCard("Branch choices", str(len(branch_rows)), "Episodes with a factual branch value"),
            SnapshotCard("Final callbacks", UNAVAILABLE, "Final callback count is unavailable in this report.", UNAVAILABLE),
            SnapshotCard("Data status", AVAILABLE, "Certified MINE results available"),
        ),
        pathway or ("MINE EPISODE", "MINE-OWNED CLOSURE"),
        # Column widths widened for MINE specifically (Chief's Phase 5 final
        # correction pass, visual defect #2): production MINE-DDMMYYYY-NN
        # codes and underscore-joined closure reasons (e.g.
        # RETURNED_AFTER_CALLBACK) are wider than the shared table
        # renderer's original SINE-sized columns, causing an awkward
        # episode-code wrap and a mid-word character split -- verified via
        # reportlab's own Paragraph.wrap() against the real production
        # values, still summing to the same 84mm column budget as before.
        TableRenderModel(1, "MINE EPISODE SUMMARY", "Only fully-contained episodes are included.", ("EPISODE", "SESSION", "START", "CLOSURE"), table1, (23, 7, 16, 38)),
        TableRenderModel(2, "RESPONSE OPTION SUMMARY", "Factual branch, approved timer route, and MINE-owned outcome.", ("EPISODE", "OPTION", "TIMER", "OUTCOME"), tuple(table2), (23, 26, 14, 21)),
        chart,
        "MINE results describe recorded messaging choices and episode outcomes. The final callback count is unavailable in this report.",
        provenance,
    )


def _cosine_model(package: Chapter3ResultPackage) -> OrganRenderModel | UnavailableOrgan:
    rows = package.cosine_episode_rows
    scope = package.cosine_experiment_scope
    if not rows:
        return UnavailableOrgan("COSINE", scope.status, _scope_unavailable_reason("COSINE", scope), scope.provenance)
    choices = tuple(row for row in rows if row.user_choice)
    # Official COS-DDMMYYYY-NN code, carried verbatim from COSINE's own
    # episode_display_ids() during certification -- never recomputed here
    # (Chief's Phase 5 final correction pass ruling).
    episode_code = {row.episode_id: row.display_episode_id for row in rows}
    durations = tuple((episode_code[row.episode_id], float(row.chosen_break_minutes)) for row in rows if row.chosen_break_minutes is not None)
    chart = _chart(durations, kind="bar", unit="minutes", empty_reason="no certified chosen COSINE duration points")
    table1 = tuple((episode_code[row.episode_id], str(package.parent_session_id), row.started_at_utc or UNAVAILABLE, row.closure_outcome or row.closure_reason or UNAVAILABLE) for row in rows)
    table2 = tuple((episode_code[row.episode_id], row.user_choice or UNAVAILABLE, f"{row.chosen_break_minutes} min" if row.chosen_break_minutes is not None else NOT_APPLICABLE, str(row.hopper_count), row.closure_outcome or row.closure_reason or UNAVAILABLE) for row in rows)
    pathway = tuple(dict.fromkeys([f"PLATFORM: {row.starting_platform_label}" for row in rows] + [f"CHOICE: {row.user_choice}" for row in choices] + [f"CLOSURE: {row.closure_outcome}" for row in rows if row.closure_outcome]))
    provenance = _dedupe_refs([ref for row in rows for ref in row.provenance] + list(scope.provenance))
    return OrganRenderModel(
        "COSINE", "SP9", AVAILABLE, scope.reason, _scope_note(scope),
        (
            SnapshotCard("OTT episodes", str(len(rows)), "Fully-contained certified COSINE episodes"),
            SnapshotCard("Intention checks", UNAVAILABLE, "Intention check count is unavailable in this report.", UNAVAILABLE),
            SnapshotCard("Chosen watch/break", str(len(choices)), "Episodes with a factual user choice"),
            SnapshotCard("Callbacks", UNAVAILABLE, "Callback count is unavailable in this report.", UNAVAILABLE),
            SnapshotCard("Data status", AVAILABLE, "Certified COSINE results available"),
        ),
        pathway or ("COSINE EPISODE", "COSINE-OWNED CLOSURE"),
        TableRenderModel(1, "COSINE EPISODE SUMMARY", "Only fully-contained OTT episodes are included.", ("EPISODE", "SESSION", "OTT START", "CLOSURE"), table1, (20, 16, 24, 24)),
        TableRenderModel(2, "BREAK / WATCH DECISION SUMMARY", "Factual choice, chosen duration, hopper count, and closure.", ("EPISODE", "OPTION", "DURATION", "HOPS", "CLOSURE"), table2, (17, 18, 18, 13, 18)),
        chart,
        "COSINE results describe factual OTT choices and COSINE-owned closure. They do not infer viewing duration or cognitive state.",
        provenance,
    )


def _latency_text(row: CosecantBreakRow) -> str:
    if row.post_break_return_latency_status == AVAILABLE:
        return _format_duration_ns(row.post_break_return_latency_ns)
    if row.post_break_return_latency_status == NOT_APPLICABLE:
        return f"NOT APPLICABLE - {row.post_break_return_latency_reason}"
    return f"UNAVAILABLE - {row.post_break_return_latency_reason}"


def _cosecant_model(package: Chapter3ResultPackage) -> OrganRenderModel | UnavailableOrgan:
    rows = package.cosecant_break_rows
    if not rows:
        return _unavailable_from_coverage(package, "COSECANT")
    # COSECANT never had a prior human-readable dashboard convention
    # (confirmed by forensic audit); Chief defines this CSC-DDMMYYYY-NN
    # presentation family.  No per-break wall-clock field exists on
    # CosecantBreakRow, so every break in this certified experiment shares
    # its date key, sequenced by the real BREAK_STARTED monotonic order.
    experiment_moment = _parse_certified_utc(package.experiment_started_at_utc)
    ordered_break_ids = tuple(dict.fromkeys(
        row.break_id
        for row in sorted(rows, key=lambda item: (item.break_started_monotonic_ns or 0, item.break_id))
    ))
    break_code = _report_local_episode_codes(
        ((break_id, experiment_moment) for break_id in ordered_break_ids),
        prefix="CSC",
    )
    table1 = tuple((break_code[row.break_id], _format_offset(row.break_started_monotonic_ns, package.experiment_start_monotonic_ns), _format_offset(row.break_complete_monotonic_ns, package.experiment_start_monotonic_ns), _latency_text(row)) for row in rows)
    escalations = []
    for row in rows:
        for label, value in (
            ("BREAK COMPLETE", row.break_complete_monotonic_ns),
            ("+5 MIN REMINDER", row.break_already_over_monotonic_ns),
            ("FINAL LOCK", row.final_locked_monotonic_ns),
            ("RETURN CONFIRMED", row.return_confirmed_monotonic_ns),
        ):
            if value is not None:
                escalations.append((break_code[row.break_id], label, _format_offset(value, package.experiment_start_monotonic_ns), row.post_break_return_latency_status))
    latency_points = tuple((break_code[row.break_id], row.post_break_return_latency_ns / 1_000_000_000) for row in rows if row.post_break_return_latency_status == AVAILABLE)
    chart = _chart(latency_points, kind="bar", unit="seconds", empty_reason="no certified AVAILABLE post-break return-latency samples")
    stages = []
    for label, attr in (
        ("BREAK STARTED", "break_started_monotonic_ns"),
        ("BREAK COMPLETE", "break_complete_monotonic_ns"),
        ("+5 MIN REMINDER", "break_already_over_monotonic_ns"),
        ("FINAL LOCK", "final_locked_monotonic_ns"),
        ("RETURN CONFIRMED", "return_confirmed_monotonic_ns"),
    ):
        if any(getattr(row, attr) is not None for row in rows):
            stages.append(label)
    provenance = _dedupe_refs(ref for row in rows for ref in row.provenance)
    return OrganRenderModel(
        "COSECANT", "SP10", AVAILABLE, "certified COSECANT break rows are present", "",
        (
            SnapshotCard("Approved study breaks", str(len(rows)), "Certified COSECANT break identities"),
            SnapshotCard("Reminder levels observed", str(sum(row.break_already_over_monotonic_ns is not None for row in rows)), "Factual +5 reminder events"),
            SnapshotCard("Final locks", str(sum(row.final_locked_monotonic_ns is not None for row in rows)), "Factual final-lock events"),
            SnapshotCard("Return confirmations", str(sum(row.return_confirmed_monotonic_ns is not None for row in rows)), "Factual exact-resource confirmations"),
            SnapshotCard("Data status", AVAILABLE, "Certified COSECANT results available"),
        ),
        tuple(stages),
        TableRenderModel(1, "BREAK TIMING SUMMARY", "Event times are shown as offsets from the certified experiment start; latency is the frozen BREAK_COMPLETE to RETURN_CONFIRMED value.", ("BREAK", "BREAK STARTED", "BREAK COMPLETE", "RETURN LATENCY"), table1, (20, 22, 22, 28)),
        TableRenderModel(2, "COSECANT ESCALATION SUMMARY", "Only factual stages reached by each break are shown.", ("BREAK", "FACTUAL STAGE", "EVENT TIME", "LATENCY STATUS"), tuple(escalations), (20, 25, 20, 25)),
        chart,
        "COSECANT results report exact Study-resource behavioural confirmation. An early return before break completion remains NOT_APPLICABLE, never zero.",
        provenance,
    )


def _secant_model(package):
    from .secant_adapter import validate_package_rows
    import textwrap
    rows, scope = package.secant_episode_rows, package.secant_experiment_scope
    validate_package_rows(rows, scope, package.parent_session_id,
                          package.experiment_start_monotonic_ns, package.experiment_end_monotonic_ns)
    if scope is None:
        return UnavailableOrgan("SECANT", UNAVAILABLE, "SECANT absent from legacy certified package")
    if not rows:
        status = NO_EVIDENCE if scope.status == OUTSIDE_WINDOW else scope.status
        return UnavailableOrgan("SECANT", status, scope.reason, scope.provenance)
    summary, chronology = [], []
    for row in rows:
        alias = row.display_alias
        values = (("Stage reached", f"SECANT-{row.stage_reached}"),
                  ("Founding source", row.founding_source),
                  ("Source state", row.source_status),
                  ("Recorded caption", row.founding_caption),
                  ("Caption state", row.caption_status),
                  ("Terminal reason", row.terminal_reason or "NOT_RECORDED"))
        for label, value in values:
            for index, part in enumerate(textwrap.wrap(str(value), 100) or ["NOT_RECORDED"]):
                summary.append((alias, label if index == 0 else "continued", part))
        attempts = {}
        for event in row.events:
            if event.attempt_id:
                attempts.setdefault(event.attempt_id, len(attempts) + 1)
            attempt = str(attempts[event.attempt_id]) if event.attempt_id else "—"
            detail = event.name.removeprefix("SECANT_")
            if event.name == "SECANT_DISPLAYED":
                detail += f" SECANT-{event.stage}"
            if event.reason:
                detail += ": " + event.reason
            offset = f"+{(event.at_ns-package.experiment_start_monotonic_ns)/1e9:.3f}s"
            for index, part in enumerate(textwrap.wrap(detail, 100) or [detail]):
                chronology.append((alias, offset if index == 0 else "", attempt, part))
    facts = [f for row in rows for f in row.events]
    recovered = sum(any(f.name == "SECANT_RECOVERY_CLOSED" for f in row.events) for row in rows)
    return OrganRenderModel("SECANT", "SECANT_RESULTS", AVAILABLE, scope.reason, _scope_note(scope), (
        SnapshotCard("Episodes", str(len(rows)), "Complete, experiment-contained lifecycles"),
        SnapshotCard("Highest stage", str(max(r.stage_reached for r in rows)), "Factual displayed stage"),
        SnapshotCard("Verified returns", str(sum(f.name == "SECANT_RETURN_VERIFIED" for f in facts)), "SECANT attempt events, not MIRL"),
        SnapshotCard("Recovered episodes", str(recovered), "Native recovery closure recorded"),
        SnapshotCard("Data status", AVAILABLE, "Experiment-scoped SECANT evidence"),
    ), ("FACTUAL DISPLAY", "STUDY RETURN", "VERIFICATION", "CONFIRMATION", "CLOSURE"),
        TableRenderModel(1, "SECANT EPISODE EVIDENCE", "Stored alias, founding metadata and outcome; absent optional fields stay explicit.",
                         ("EPISODE", "FIELD", "RECORDED VALUE"), tuple(summary), (35, 35, 104)),
        TableRenderModel(2, "SECANT EVENT CHRONOLOGY", "Every certified event in occurrence order. Attempt numbers are local presentation labels.",
                         ("EPISODE", "OFFSET", "ATTEMPT", "EVENT / REASON"), tuple(chronology), (35, 21, 18, 100)),
        ChartRenderModel(UNAVAILABLE, "bar", (), (), "", "No generic recovery score or dwell is inferred", ""),
        "SECANT verifies Study return independently of MIRL. A behavioural evidence_gap interruption is not recorder loss. "
        "Episode closure alone does not establish recovery. COSECANT retains approved-break authority.", scope.provenance)


def adapt_certified_report_input(source: Chapter3ResultPackage | Chapter3TransferReceipt) -> ReportRenderModel:
    if isinstance(source, Chapter3TransferReceipt):
        package = source.package
        if source.experiment_id != package.experiment_id or source.parent_session_id != package.parent_session_id:
            raise ReportModelError("receipt identity differs from its package")
    elif isinstance(source, Chapter3ResultPackage):
        package = source
    else:
        raise TypeError("report input must be a certified package or transfer receipt")
    _validate_package(package)
    candidates = (
        _sine_model(package),
        _mine_model(package),
        _cosine_model(package),
        _secant_model(package),
        _cosecant_model(package),
    )
    organ_pages = tuple(item for item in candidates if isinstance(item, OrganRenderModel))
    unavailable = tuple(item for item in candidates if isinstance(item, UnavailableOrgan))
    return ReportRenderModel(
        REPORT_MODEL_SCHEMA_VERSION,
        package.experiment_id,
        package.parent_session_id,
        package.experiment_started_at_utc,
        package.experiment_ended_at_utc,
        package.analysis_status,
        organ_pages,
        unavailable,
        package.limitations,
        package.provenance,
    )


def _chunks(rows: tuple[tuple[str, ...], ...], size: int):
    for offset in range(0, len(rows), size):
        yield rows[offset : offset + size]


def plan_report_pages(model: ReportRenderModel) -> ReportPagePlan:
    if not isinstance(model, ReportRenderModel) or model.analysis_status != CERTIFIED:
        raise ReportModelError("page planner requires a certified render model")
    draft: list[tuple[str, str, str, int, tuple[tuple[str, ...], ...]]] = [
        ("cover", "COVER", "", 0, ()),
        *(("static", code, "", 0, ()) for code in ("SP1", "SP2", "SP3", "STUDY_ORGANS", "SP4", "SP5")),
        ("overview", "SP6", "", 0, ()),
    ]
    by_organ = {page.organ: page for page in model.organ_pages}
    for organ in ORGAN_ORDER:
        page = by_organ.get(organ)
        if page is None:
            continue
        draft.append(("organ", page.page_code, organ, 0, ()))
        for table in (page.table1, page.table2):
            overflow = table.rows[PRIMARY_TABLE_ROW_CAPACITY:]
            for chunk in _chunks(overflow, 12 if organ == "SECANT" else CONTINUATION_TABLE_ROW_CAPACITY):
                draft.append(("continuation", f"{page.page_code}-T{table.number}-CONT", organ, table.number, chunk))
    if model.unavailable_organs:
        draft.append(("unavailable", "UNAVAILABLE", "", 0, ()))
    draft.extend(("static", f"SP{index}", "", 0, ()) for index in range(11, 15))
    pages = tuple(
        PlannedPage(kind, page_code, number, organ, table_number, rows)
        for number, (kind, page_code, organ, table_number, rows) in enumerate(draft, start=1)
    )
    return ReportPagePlan(pages)


__all__ = [
    "ChartRenderModel",
    "CONTINUATION_TABLE_ROW_CAPACITY",
    "OrganRenderModel",
    "PlannedPage",
    "PRIMARY_TABLE_ROW_CAPACITY",
    "ReportModelError",
    "ReportPagePlan",
    "ReportRenderModel",
    "SnapshotCard",
    "TableRenderModel",
    "UnavailableOrgan",
    "adapt_certified_report_input",
    "plan_report_pages",
]
