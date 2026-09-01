"""MIRL and Science Lab PDF presentation for final MYELIN.

This file renders the immutable output of :mod:`MIRL.read_model`.  It does not
open the database, replay the MIRL lifecycle, calculate recovery truth, repair
evidence, or read the monitor.

Privacy and provenance rules
----------------------------
* Raw ``source_event_id`` values are never placed in the PDF, filename,
  metadata, timeline, diagnostics or provenance sections.
* The report does not invent a producer name, model version or software
  version.  It displays source/projector/schema provenance only when those
  values are already present in the authoritative read-model snapshot.
* DEGRADED, UNKNOWN and UNAVAILABLE evidence remains visibly labelled.  The
  report never changes it to a healthy state.
"""

from __future__ import annotations

import html
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from MIRL.read_model import (
    IntegrityStatus,
    LiveMirlEpisodeRow,
    MirlReadModelSnapshot,
)
from time_projection import (
    TimezoneProjectionError,
    project_utc_timestamp,
    timezone_tag,
)


PAGE_WIDTH, PAGE_HEIGHT = A4
PAGE_MARGIN: Final = 16 * mm
CONTENT_WIDTH: Final = PAGE_WIDTH - (2 * PAGE_MARGIN)
MAX_REPORT_TEXT: Final = 4_000

NAVY: Final = colors.HexColor("#071426")
PANEL: Final = colors.HexColor("#10253A")
CYAN: Final = colors.HexColor("#46D7FF")
BLUE: Final = colors.HexColor("#79AFFF")
GREEN: Final = colors.HexColor("#35D983")
AMBER: Final = colors.HexColor("#F6C85F")
RED: Final = colors.HexColor("#FF6F79")
INK: Final = colors.HexColor("#182333")
MUTED: Final = colors.HexColor("#5E6B7B")
LINE: Final = colors.HexColor("#D7E0EA")
SOFT: Final = colors.HexColor("#F3F7FB")
WHITE: Final = colors.white


class MirlReportError(RuntimeError):
    """Raised when a report cannot be produced without violating its contract."""


@dataclass(frozen=True, slots=True)
class MirlReportSections:
    metric_hub: bool = True
    live_mirl: bool = True
    science_lab: bool = True
    integrity_and_provenance: bool = True

    def any_selected(self) -> bool:
        return any(
            (
                self.metric_hub,
                self.live_mirl,
                self.science_lab,
                self.integrity_and_provenance,
            )
        )


@dataclass(frozen=True, slots=True)
class MirlReportRequest:
    output_path: str | Path
    title: str = "MYELIN MIRL / Science Lab Report"
    subtitle: str = "Behavioral intervention and recovery evidence"
    sections: MirlReportSections = MirlReportSections()
    maximum_episodes: int = 25
    maximum_timeline_events_per_episode: int = 100
    overwrite: bool = False

    def __post_init__(self) -> None:
        if not str(self.title).strip():
            raise ValueError("title must not be empty")
        if not self.sections.any_selected():
            raise ValueError("at least one report section must be selected")
        if type(self.maximum_episodes) is not int or not 1 <= self.maximum_episodes <= 200:
            raise ValueError("maximum_episodes must be between 1 and 200")
        if (
            type(self.maximum_timeline_events_per_episode) is not int
            or not 1 <= self.maximum_timeline_events_per_episode <= 1_000
        ):
            raise ValueError(
                "maximum_timeline_events_per_episode must be between 1 and 1000"
            )
        path = Path(self.output_path).expanduser()
        if path.suffix.lower() != ".pdf":
            raise ValueError("output_path must end with .pdf")


@dataclass(frozen=True, slots=True)
class MirlReportResult:
    output_path: str
    generated_at_utc: str
    byte_size: int
    integrity_status: IntegrityStatus
    displayed_episode_count: int
    truncated_episode_count: int


class MirlReportPresenter:
    """One ReportLab presenter over one authoritative read-model snapshot."""

    def build(
        self,
        snapshot: MirlReadModelSnapshot,
        request: MirlReportRequest,
    ) -> MirlReportResult:
        if not isinstance(snapshot, MirlReadModelSnapshot):
            raise TypeError("snapshot must be MirlReadModelSnapshot")
        if not isinstance(request, MirlReportRequest):
            raise TypeError("request must be MirlReportRequest")

        output_path = Path(request.output_path).expanduser().resolve()
        if output_path.exists() and not request.overwrite:
            raise FileExistsError(f"report already exists: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        generated_at = _utc_now()
        active = tuple(snapshot.live_mirl.active_episodes)
        closed = tuple(snapshot.live_mirl.recently_closed_episodes)
        all_episodes = (*active, *closed)
        selected_episodes = all_episodes[: request.maximum_episodes]
        truncated_count = max(0, len(all_episodes) - len(selected_episodes))

        styles = _styles()
        story = self._build_story(
            snapshot,
            request,
            generated_at=generated_at,
            episodes=selected_episodes,
            truncated_episode_count=truncated_count,
            styles=styles,
        )
        temporary = output_path.with_name(
            f".{output_path.name}.{secrets.token_hex(8)}.tmp.pdf"
        )
        document = SimpleDocTemplate(
            str(temporary),
            pagesize=A4,
            leftMargin=PAGE_MARGIN,
            rightMargin=PAGE_MARGIN,
            topMargin=21 * mm,
            bottomMargin=18 * mm,
            title=_pdf_text(request.title),
            subject="MIRL and Science Lab behavioral evidence report",
            pageCompression=1,
        )

        def decorate(canvas, doc) -> None:
            _page_decoration(
                canvas,
                doc,
                integrity_status=snapshot.integrity_status,
            )

        try:
            document.build(story, onFirstPage=decorate, onLaterPages=decorate)
            if not temporary.exists() or temporary.stat().st_size <= 0:
                raise MirlReportError("ReportLab produced no PDF bytes")
            if request.overwrite:
                os.replace(temporary, output_path)
            else:
                # Same-directory hard-link commit is atomic and fails if the
                # destination appeared after the initial validation.
                os.link(temporary, output_path)
                temporary.unlink(missing_ok=True)
        except Exception as error:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(error, (MirlReportError, FileExistsError)):
                raise
            raise MirlReportError(f"MIRL report generation failed: {error}") from error

        return MirlReportResult(
            output_path=str(output_path),
            generated_at_utc=generated_at,
            byte_size=output_path.stat().st_size,
            integrity_status=snapshot.integrity_status,
            displayed_episode_count=len(selected_episodes),
            truncated_episode_count=truncated_count,
        )

    def _build_story(
        self,
        snapshot: MirlReadModelSnapshot,
        request: MirlReportRequest,
        *,
        generated_at: str,
        episodes: tuple[LiveMirlEpisodeRow, ...],
        truncated_episode_count: int,
        styles: dict[str, ParagraphStyle],
    ) -> list:
        story: list = []
        story.extend(
            _cover(
                snapshot,
                request,
                generated_at=generated_at,
                styles=styles,
            )
        )

        if request.sections.metric_hub:
            story.extend(_metric_hub_section(snapshot, styles))

        if request.sections.live_mirl:
            story.append(PageBreak())
            story.extend(
                _live_mirl_section(
                    snapshot,
                    episodes,
                    maximum_timeline_events=request.maximum_timeline_events_per_episode,
                    truncated_episode_count=truncated_episode_count,
                    styles=styles,
                )
            )

        if request.sections.science_lab:
            story.append(PageBreak())
            story.extend(_science_lab_section(snapshot, styles))

        if request.sections.integrity_and_provenance:
            story.append(PageBreak())
            story.extend(_integrity_and_provenance_section(snapshot, styles))
        return story


def build_mirl_report_pdf(
    snapshot: MirlReadModelSnapshot,
    request: MirlReportRequest,
) -> MirlReportResult:
    """Public entry point used by the persistence/export coordinator."""

    return MirlReportPresenter().build(snapshot, request)


def suggested_report_filename(*, generated_at: datetime | None = None) -> str:
    """Return a safe filename containing no episode or source-event identity."""

    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y%m%d_%H%M%S")
    return f"MYELIN_MIRL_SCIENCE_REPORT_{stamp}.pdf"


# ---------------------------------------------------------------------------
# Story sections
# ---------------------------------------------------------------------------


def _projected_timestamp(value: object, presentation_timezone: str) -> str:
    """Human wall time from immutable UTC evidence, with a truthful zone."""

    try:
        moment = project_utc_timestamp(value, presentation_timezone)
    except TimezoneProjectionError:
        return str(value or "Unavailable")
    return (
        f"{moment.strftime('%d %b %Y · %H:%M:%S')} "
        f"[{timezone_tag(moment, presentation_timezone)}]"
    )


def _cover(
    snapshot: MirlReadModelSnapshot,
    request: MirlReportRequest,
    *,
    generated_at: str,
    styles: dict[str, ParagraphStyle],
) -> list:
    provenance = snapshot.research_provenance
    story = [
        Spacer(1, 14 * mm),
        Paragraph(_escape(request.title), styles["title"]),
        Paragraph(_escape(request.subtitle), styles["subtitle"]),
        Spacer(1, 5 * mm),
        _integrity_banner(snapshot.integrity_status, styles),
        Spacer(1, 7 * mm),
        _key_value_table(
            (
                ("Generated at (UTC)", generated_at),
                (
                    "Presentation timezone",
                    snapshot.live_mirl.presentation_timezone,
                ),
                ("Selected range", snapshot.science_lab.metadata.selected_range_label),
                ("Evidence population", _human_code(provenance.evidence_population)),
                ("Source", provenance.source_name),
                ("Source revision", provenance.source_revision),
                ("Source generated at", provenance.source_generated_at),
                ("Integrity issues", len(snapshot.integrity_issues)),
                ("Metric exclusions", snapshot.science_lab.metadata.exclusion_count),
            ),
            styles,
        ),
        Spacer(1, 8 * mm),
        Paragraph("Evidence boundary", styles["heading"]),
        Paragraph(_escape(provenance.limitation), styles["body"]),
        Spacer(1, 3 * mm),
        Paragraph(
            "Raw operational source-event identifiers are intentionally omitted "
            "from every report section.",
            styles["note"],
        ),
    ]
    return story


def _metric_hub_section(
    snapshot: MirlReadModelSnapshot,
    styles: dict[str, ParagraphStyle],
) -> list:
    metric = snapshot.metric_hub
    story = [
        Paragraph("Metric Hub", styles["heading"]),
        Paragraph(_escape(metric.status_message), styles["body"]),
        Spacer(1, 3 * mm),
    ]
    cards = (
        ("Sessions", _display_value(metric.total_session_count)),
        ("Operational triggers", _display_value(metric.total_trigger_count)),
        ("Native MIRL episodes", _display_value(metric.native_episode_count)),
        ("Eligible episodes", _display_value(metric.eligible_native_episode_count)),
        ("Closed episodes", _display_value(metric.closed_native_episode_count)),
        ("Pending episodes", _display_value(metric.pending_native_episode_count)),
        (
            "Verified return / closure rate",
            _display_percent(metric.verified_stable_recovery_rate_percent),
        ),
        ("Episode closure rate", _display_percent(metric.episode_closure_rate_percent)),
        (
            "Mean returned closure latency",
            _display_seconds(metric.average_stable_recovery_latency_seconds),
        ),
    )
    story.append(_summary_cards(cards, styles))
    story.append(Spacer(1, 4 * mm))

    detail_rows = [
        ("Population", "Status", "Value", "Evidence"),
        *(
            (
                row.population,
                row.status,
                _display_value(row.value),
                row.evidence,
            )
            for row in metric.read_model_detail_rows
        ),
    ]
    story.append(
        _table(
            detail_rows,
            styles,
            widths=(36 * mm, 30 * mm, 25 * mm, CONTENT_WIDTH - 91 * mm),
        )
    )
    story.append(
        Paragraph(
            _escape(metric.evidence_scope_label),
            styles["note"],
        )
    )
    return story


def _live_mirl_section(
    snapshot: MirlReadModelSnapshot,
    episodes: tuple[LiveMirlEpisodeRow, ...],
    *,
    maximum_timeline_events: int,
    truncated_episode_count: int,
    styles: dict[str, ParagraphStyle],
) -> list:
    live = snapshot.live_mirl
    story = [
        Paragraph("Live MIRL", styles["heading"]),
        Paragraph(_escape(live.status_message), styles["body"]),
        Spacer(1, 3 * mm),
    ]
    if not episodes:
        story.append(
            _empty_panel(live.empty_state_reason or "No MIRL episode evidence.", styles)
        )
        return story

    overview_rows = [
        ("Episode", "Status", "Outcome", "Started", "Attempts", "Relapses", "Integrity")
    ]
    for episode in episodes:
        overview_rows.append(
            (
                episode.short_display_id,
                episode.episode_status,
                episode.final_outcome or "IN PROGRESS",
                _projected_timestamp(
                    episode.started_at, live.presentation_timezone
                ),
                episode.recovery_attempt_count,
                episode.relapse_count,
                episode.integrity_status.value,
            )
        )
    story.append(
        _table(
            overview_rows,
            styles,
            widths=(24 * mm, 34 * mm, 24 * mm, 39 * mm, 17 * mm, 17 * mm, 23 * mm),
        )
    )
    if truncated_episode_count:
        story.append(
            Paragraph(
                f"{truncated_episode_count} additional episode(s) were omitted by the "
                "report presentation limit; underlying evidence was not changed.",
                styles["warning"],
            )
        )

    for episode in episodes:
        story.append(Spacer(1, 6 * mm))
        story.extend(
            _episode_timeline(
                episode,
                maximum_events=maximum_timeline_events,
                presentation_timezone=live.presentation_timezone,
                styles=styles,
            )
        )
    return story


def _episode_timeline(
    episode: LiveMirlEpisodeRow,
    *,
    maximum_events: int,
    presentation_timezone: str,
    styles: dict[str, ParagraphStyle],
) -> list:
    selected = episode.timeline[:maximum_events]
    omitted = max(0, len(episode.timeline) - len(selected))
    story = [
        KeepTogether(
            [
                Paragraph(
                    f"Episode {_escape(episode.short_display_id)}",
                    styles["subheading"],
                ),
                _key_value_table(
                    (
                        ("Status", episode.episode_status),
                        ("Outcome", episode.final_outcome or "IN PROGRESS"),
                        (
                            "Started",
                            _projected_timestamp(
                                episode.started_at, presentation_timezone
                            ),
                        ),
                        ("Return intent latency", _display_seconds(episode.return_intent_latency_seconds)),
                        ("Verified return latency", _display_seconds(episode.verified_return_latency_seconds)),
                        ("Returned closure latency", _display_seconds(episode.stable_recovery_latency_seconds)),
                        ("Recovery attempts", episode.recovery_attempt_count),
                        ("Relapses", episode.relapse_count),
                        ("SINE stages displayed", ", ".join(map(str, episode.sine_stages_exposed)) or "Unavailable"),
                        ("Integrity", episode.integrity_status.value),
                    ),
                    styles,
                ),
            ]
        )
    ]
    rows = [("Seq", "Occurred", "Event", "Class", "Reason / response")]
    for event in selected:
        rows.append(
            (
                event.episode_seq,
                _projected_timestamp(
                    event.occurred_at, presentation_timezone
                ),
                _friendly_event(event.event_name),
                event.observed_or_derived,
                event.reason_or_outcome_code or "",
            )
        )
    story.append(
        _table(
            rows,
            styles,
            widths=(12 * mm, 42 * mm, 51 * mm, 26 * mm, CONTENT_WIDTH - 131 * mm),
        )
    )
    if omitted:
        story.append(
            Paragraph(
                f"{omitted} later timeline event(s) were omitted by the presentation limit.",
                styles["warning"],
            )
        )
    if episode.integrity_issues:
        story.append(
            Paragraph(
                "Episode integrity issues: "
                + _escape(", ".join(issue.code for issue in episode.integrity_issues)),
                styles["warning"],
            )
        )
    return story


def _science_lab_section(
    snapshot: MirlReadModelSnapshot,
    styles: dict[str, ParagraphStyle],
) -> list:
    science = snapshot.science_lab
    story = [
        Paragraph("MYELIN Science Lab", styles["heading"]),
        _integrity_banner(science.integrity_status, styles),
        Spacer(1, 4 * mm),
    ]
    if not science.available:
        story.append(
            _empty_panel(science.empty_state_reason or "No scientific evidence population.", styles)
        )

    metric_rows = [("Metric", "Value", "Formula", "Population", "Exclusion / N/A")]
    for metric in science.metrics:
        value = (
            "Unavailable"
            if metric.value is None
            else f"{_display_number(metric.value)} {metric.unit}"
        )
        note = metric.na_reason or "; ".join(metric.exclusions)
        metric_rows.append(
            (
                metric.metric_name,
                value,
                metric.formula,
                _human_code(metric.evidence_population),
                note,
            )
        )
    story.append(
        _table(
            metric_rows,
            styles,
            widths=(37 * mm, 24 * mm, 52 * mm, 31 * mm, CONTENT_WIDTH - 144 * mm),
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Recorded lifecycle evidence", styles["subheading"]))
    story.append(
        _key_value_table(
            (
                ("Recovery attempts", science.recovery_attempt_count),
                ("Relapses", science.relapse_count),
                (
                    "Relapse timings (seconds)",
                    ", ".join(_display_number(value) for value in science.relapse_timings_seconds)
                    or "Unavailable",
                ),
                (
                    "SINE stage exposure counts",
                    _mapping_text(science.sine_stage_exposure_counts),
                ),
                ("SINE response counts", _mapping_text(science.sine_response_counts)),
            ),
            styles,
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Scientific evidence limitation", styles["subheading"]))
    story.append(
        Paragraph(_escape(science.scientific_evidence_limitation), styles["body"])
    )
    return story


def _integrity_and_provenance_section(
    snapshot: MirlReadModelSnapshot,
    styles: dict[str, ParagraphStyle],
) -> list:
    provenance = snapshot.research_provenance
    metadata = snapshot.science_lab.metadata
    story = [
        Paragraph("Integrity and Research Provenance", styles["heading"]),
        _integrity_banner(snapshot.integrity_status, styles),
        Spacer(1, 4 * mm),
        _key_value_table(
            (
                ("Evidence source", provenance.source_name),
                ("Source revision", provenance.source_revision),
                ("Source generated at", provenance.source_generated_at),
                ("Projected at", provenance.projected_at),
                ("Projector version", provenance.projector_version),
                (
                    "MIRL event schema versions",
                    ", ".join(provenance.mirl_event_schema_versions) or "Unavailable",
                ),
                ("Time basis", provenance.time_basis),
                ("Episode event count", provenance.episode_event_count),
                ("Control event count", provenance.control_event_count),
                ("Excluded episode count", provenance.excluded_episode_count),
            ),
            styles,
        ),
        Spacer(1, 5 * mm),
        Paragraph("Integrity issues", styles["subheading"]),
    ]

    if snapshot.integrity_issues:
        issue_rows = [("Severity", "Code", "Episode", "Detail")]
        for issue in snapshot.integrity_issues:
            issue_rows.append(
                (
                    issue.severity.value,
                    issue.code,
                    _public_episode_reference(issue.episode_id),
                    issue.detail,
                )
            )
        story.append(
            _table(
                issue_rows,
                styles,
                widths=(22 * mm, 42 * mm, 29 * mm, CONTENT_WIDTH - 93 * mm),
            )
        )
    else:
        story.append(
            _empty_panel("No integrity issues were supplied by the read authority.", styles)
        )

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Metric exclusions", styles["subheading"]))
    if metadata.exclusions:
        exclusion_rows = [("Metric", "Reason", "Episode", "Detail")]
        for exclusion in metadata.exclusions:
            exclusion_rows.append(
                (
                    exclusion.metric,
                    exclusion.reason,
                    _public_episode_reference(exclusion.episode_id),
                    exclusion.detail,
                )
            )
        story.append(
            _table(
                exclusion_rows,
                styles,
                widths=(35 * mm, 42 * mm, 29 * mm, CONTENT_WIDTH - 106 * mm),
            )
        )
    else:
        story.append(_empty_panel("No metric exclusions were supplied.", styles))

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Research limitation", styles["subheading"]))
    story.append(Paragraph(_escape(provenance.limitation), styles["body"])),
    return story


# ---------------------------------------------------------------------------
# ReportLab presentation helpers
# ---------------------------------------------------------------------------


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "MyelinReportTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=27,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=5,
        ),
        "subtitle": ParagraphStyle(
            "MyelinReportSubtitle",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            textColor=MUTED,
            spaceAfter=5,
        ),
        "heading": ParagraphStyle(
            "MyelinReportHeading",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=NAVY,
            spaceBefore=7,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "subheading": ParagraphStyle(
            "MyelinReportSubheading",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=14,
            textColor=PANEL,
            spaceBefore=4,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "MyelinReportBody",
            parent=base["BodyText"],
            fontSize=8.7,
            leading=12.2,
            textColor=INK,
        ),
        "note": ParagraphStyle(
            "MyelinReportNote",
            parent=base["BodyText"],
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
            spaceBefore=3,
        ),
        "warning": ParagraphStyle(
            "MyelinReportWarning",
            parent=base["BodyText"],
            fontSize=7.7,
            leading=10.5,
            textColor=colors.HexColor("#8A4D00"),
            backColor=colors.HexColor("#FFF4D6"),
            borderColor=AMBER,
            borderWidth=0.5,
            borderPadding=5,
            spaceBefore=4,
            spaceAfter=4,
        ),
        "cell": ParagraphStyle(
            "MyelinReportCell",
            parent=base["BodyText"],
            fontSize=7.2,
            leading=9.2,
            textColor=INK,
        ),
        "cell_header": ParagraphStyle(
            "MyelinReportCellHeader",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.2,
            leading=9.2,
            textColor=WHITE,
        ),
        "card_label": ParagraphStyle(
            "MyelinReportCardLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=6.8,
            leading=8.5,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "card_value": ParagraphStyle(
            "MyelinReportCardValue",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=11,
            leading=13,
            textColor=NAVY,
            alignment=TA_CENTER,
        ),
        "banner": ParagraphStyle(
            "MyelinReportBanner",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            alignment=TA_CENTER,
            borderPadding=7,
        ),
    }


def _integrity_banner(
    status: IntegrityStatus,
    styles: dict[str, ParagraphStyle],
) -> Table:
    color = {
        IntegrityStatus.CONFIRMED: GREEN,
        IntegrityStatus.DEGRADED: AMBER,
        IntegrityStatus.UNKNOWN: AMBER,
        IntegrityStatus.UNAVAILABLE: RED,
    }[status]
    text = {
        IntegrityStatus.CONFIRMED: "INTEGRITY-CONFIRMED EVIDENCE",
        IntegrityStatus.DEGRADED: "DEGRADED EVIDENCE - AGGREGATE RATES MAY BE WITHHELD",
        IntegrityStatus.UNKNOWN: "EVIDENCE INTEGRITY UNKNOWN",
        IntegrityStatus.UNAVAILABLE: "MIRL EVIDENCE UNAVAILABLE",
    }[status]
    paragraph_style = ParagraphStyle(
        f"Integrity{status.value}",
        parent=styles["banner"],
        textColor=NAVY,
    )
    table = Table([[Paragraph(_escape(text), paragraph_style)]], colWidths=[CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), color),
                ("BOX", (0, 0), (-1, -1), 0.8, color),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _key_value_table(
    pairs,
    styles: dict[str, ParagraphStyle],
) -> Table:
    rows = []
    for label, value in pairs:
        rows.append(
            [
                Paragraph(f"<b>{_escape(label)}</b>", styles["cell"]),
                Paragraph(_escape(_display_value(value)), styles["cell"]),
            ]
        )
    table = Table(rows, colWidths=[47 * mm, CONTENT_WIDTH - 47 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, SOFT]),
                ("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table


def _summary_cards(cards, styles: dict[str, ParagraphStyle]) -> Table:
    cells = []
    for label, value in cards:
        cells.append(
            [
                Paragraph(_escape(label), styles["card_label"]),
                Spacer(1, 1.2 * mm),
                Paragraph(_escape(value), styles["card_value"]),
            ]
        )
    rows = []
    for index in range(0, len(cells), 3):
        row = cells[index : index + 3]
        while len(row) < 3:
            row.append([])
        rows.append(row)
    table = Table(rows, colWidths=[CONTENT_WIDTH / 3] * 3)
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                ("GRID", (0, 0), (-1, -1), 1, WHITE),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _table(rows, styles: dict[str, ParagraphStyle], *, widths) -> Table:
    rendered = []
    for row_index, row in enumerate(rows):
        style = styles["cell_header"] if row_index == 0 else styles["cell"]
        rendered.append([Paragraph(_escape(value), style) for value in row])
    table = Table(rendered, colWidths=list(widths), repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, SOFT]),
                ("GRID", (0, 0), (-1, -1), 0.35, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _empty_panel(text: str, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table([[Paragraph(_escape(text), styles["body"])]], colWidths=[CONTENT_WIDTH])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), SOFT),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def _page_decoration(canvas, doc, *, integrity_status: IntegrityStatus) -> None:
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, PAGE_HEIGHT - 12 * mm, PAGE_WIDTH, 12 * mm, fill=1, stroke=0)
    canvas.setFillColor(CYAN)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(PAGE_MARGIN, PAGE_HEIGHT - 7.5 * mm, "MYELIN - MIRL / SCIENCE LAB")
    canvas.setFillColor(WHITE)
    canvas.setFont("Helvetica", 7)
    canvas.drawRightString(
        PAGE_WIDTH - PAGE_MARGIN,
        PAGE_HEIGHT - 7.5 * mm,
        f"Evidence: {integrity_status.value}",
    )
    canvas.setStrokeColor(LINE)
    canvas.line(PAGE_MARGIN, 14 * mm, PAGE_WIDTH - PAGE_MARGIN, 14 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(PAGE_MARGIN, 9.5 * mm, "Behavioral software evidence only")
    canvas.drawRightString(
        PAGE_WIDTH - PAGE_MARGIN,
        9.5 * mm,
        f"Page {canvas.getPageNumber()}",
    )
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Safe formatting helpers
# ---------------------------------------------------------------------------


_WHITESPACE = re.compile(r"\s+")


def _pdf_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    replacements = {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u00d7": "x",
        "\u2022": "*",
        "\u00a0": " ",
    }
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    text = "".join(character if ord(character) < 128 else "?" for character in text)
    return _WHITESPACE.sub(" ", text).strip()[:MAX_REPORT_TEXT]


def _escape(value: object) -> str:
    return html.escape(_pdf_text(value), quote=False)


def _display_value(value: object) -> str:
    if value is None or value == "":
        return "Unavailable"
    if isinstance(value, float):
        return _display_number(value)
    return _pdf_text(value)


def _display_number(value: object) -> str:
    if value is None:
        return "Unavailable"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _pdf_text(value)
    if not number.is_integer():
        return f"{number:.2f}".rstrip("0").rstrip(".")
    return str(int(number))


def _display_percent(value: float | None) -> str:
    return "Unavailable" if value is None else f"{_display_number(value)}%"


def _display_seconds(value: float | None) -> str:
    return "Unavailable" if value is None else f"{_display_number(value)} seconds"


def _friendly_event(value: str) -> str:
    return _pdf_text(value).replace("_", " ").title() or "Unknown event"


def _human_code(value: object) -> str:
    return _pdf_text(value).replace("_", " ") or "Unavailable"


def _mapping_text(value) -> str:
    if not value:
        return "Unavailable"
    return ", ".join(
        f"{_pdf_text(key)}: {_display_value(item)}"
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
    )


def _public_episode_reference(episode_id: str) -> str:
    """Present a bounded display reference, never the full internal identity."""

    if not episode_id:
        return "Not episode-specific"
    tail = str(episode_id).rsplit("-", 1)[-1][:8].upper()
    return f"MIRL-{tail}" if tail else "MIRL-UNKNOWN"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


__all__ = [
    "MirlReportError",
    "MirlReportPresenter",
    "MirlReportRequest",
    "MirlReportResult",
    "MirlReportSections",
    "build_mirl_report_pdf",
    "suggested_report_filename",
]
