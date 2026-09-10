"""Exactly-three-page MIRL recovery-history PDF presentation.

The renderer consumes one immutable :class:`MirlReadModelSnapshot`. It does
not open persistence, poll runtime state, calculate episode physiology, or
manufacture missing evidence. The normal export obtains a fresh snapshot
through ``PERSISTENCE.storage.read_mirl_snapshot`` before calling this module.
"""
from __future__ import annotations

import html
import os
import secrets
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Paragraph

from MIRL.read_model import IntegrityStatus, LiveMirlEpisodeRow, MirlReadModelSnapshot
from time_projection import project_utc_timestamp, timezone_tag

REPORT_SCHEMA_VERSION: Final = "myelin-mirl-pdf-v2"
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN: Final = 16 * mm
CONTENT_WIDTH: Final = PAGE_WIDTH - (2 * MARGIN)
HISTORY_ROW_CAP: Final = 6
EVIDENCE_ROW_CAP: Final = 6
TIMELINE_ROW_CAP: Final = 11

NAVY: Final = colors.HexColor("#10283E")
CYAN: Final = colors.HexColor("#19B7C8")
INK: Final = colors.HexColor("#213343")
MUTED: Final = colors.HexColor("#667989")
LINE: Final = colors.HexColor("#D5E0E7")
SOFT: Final = colors.HexColor("#F4F8FA")
PALE_CYAN: Final = colors.HexColor("#EAF8FA")
WHITE: Final = colors.white

_RECOVERED_OUTCOME: Final = "RETURNED"
_MILESTONE_NAMES: Final = (
    "episode_created", "sine_displayed", "sine_response_recorded",
    "return_intent_recorded", "return_verification_started",
    "return_verification_completed", "return_verified",
    "return_verification_interrupted", "relapse_detected", "episode_resumed",
    "closure_confirmation_started", "closure_confirmation_completed",
    "episode_closed", "emergency_stopped",
)


class MirlReportError(RuntimeError):
    """Raised when a factual fixed-layout report cannot be produced."""


@dataclass(frozen=True, slots=True)
class MirlReportRequest:
    output_path: str | Path
    title: str = "MYELIN MIRL Recovery History Report"
    subtitle: str = "MYELIN Intervention Recovery Loop"
    overwrite: bool = True

    def __post_init__(self) -> None:
        if Path(self.output_path).suffix.lower() != ".pdf":
            raise ValueError("output_path must end with .pdf")


@dataclass(frozen=True, slots=True)
class MirlReportResult:
    output_path: str
    generated_at_utc: str
    byte_size: int
    page_count: int
    focus_episode_id: str
    total_episode_count: int
    shown_history_count: int
    shown_timeline_count: int
    shown_evidence_count: int
    integrity_status: IntegrityStatus


def suggested_report_filename(*, generated_at: datetime | None = None) -> str:
    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"MYELIN_MIRL_Report_{stamp}.pdf"


def build_mirl_report_pdf(snapshot: MirlReadModelSnapshot, request: MirlReportRequest) -> MirlReportResult:
    """Render exactly three A4 portrait pages from one authoritative snapshot."""
    if not isinstance(snapshot, MirlReadModelSnapshot):
        raise TypeError("snapshot must be MirlReadModelSnapshot")
    if not isinstance(request, MirlReportRequest):
        raise TypeError("request must be MirlReportRequest")

    episodes = _ordered_episodes(snapshot)
    focus = episodes[0] if episodes else None
    history = episodes[:HISTORY_ROW_CAP]
    evidence = episodes[:EVIDENCE_ROW_CAP]
    timeline, timeline_total = _select_timeline(focus)
    output = Path(request.output_path).expanduser().resolve()
    if output.exists() and not request.overwrite:
        raise FileExistsError("report destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}-{secrets.token_hex(6)}.tmp.pdf")

    try:
        report = pdfcanvas.Canvas(str(temporary), pagesize=A4, pageCompression=1)
        report.setTitle(request.title)
        report.setAuthor("MYELIN")
        report.setSubject("MIRL durable behavioral recovery evidence")
        _draw_cover(report, snapshot, focus)
        report.showPage()
        _draw_episode_page(report, snapshot, focus, history, timeline, timeline_total)
        report.showPage()
        _draw_evidence_page(report, snapshot, evidence)
        report.showPage()
        report.save()
        if not temporary.exists() or temporary.stat().st_size <= 0:
            raise MirlReportError("ReportLab produced no PDF bytes")
        if request.overwrite:
            os.replace(temporary, output)
        else:
            os.link(temporary, output)
            temporary.unlink(missing_ok=True)
    except Exception as error:
        temporary.unlink(missing_ok=True)
        if isinstance(error, (MirlReportError, FileExistsError)):
            raise
        raise MirlReportError("MIRL report generation failed") from error

    return MirlReportResult(
        output_path=str(output), generated_at_utc=snapshot.generated_at,
        byte_size=output.stat().st_size, page_count=3,
        focus_episode_id=_display_id(focus), total_episode_count=len(episodes),
        shown_history_count=len(history), shown_timeline_count=len(timeline),
        shown_evidence_count=len(evidence), integrity_status=snapshot.integrity_status,
    )


def _ordered_episodes(snapshot: MirlReadModelSnapshot) -> tuple[LiveMirlEpisodeRow, ...]:
    """Newest factual opening first, with raw identity used only as a tie-break."""
    combined = tuple(snapshot.live_mirl.active_episodes) + tuple(snapshot.live_mirl.recently_closed_episodes)
    unique: dict[str, LiveMirlEpisodeRow] = {}
    for row in combined:
        unique.setdefault(row.episode_id, row)
    return tuple(sorted(
        unique.values(),
        key=lambda row: (str(row.started_at or ""), str(row.episode_id or "")),
        reverse=True,
    ))


def _select_timeline(row: LiveMirlEpisodeRow | None) -> tuple[tuple, int]:
    """Select a deterministic milestone set while preserving episode sequence."""
    ordered = tuple(sorted(tuple(row.timeline), key=lambda event: event.episode_seq)) if row else ()
    if len(ordered) <= TIMELINE_ROW_CAP:
        return ordered, len(ordered)
    selected: dict[int, object] = {
        ordered[0].episode_seq: ordered[0], ordered[-1].episode_seq: ordered[-1]
    }
    for name in _MILESTONE_NAMES:
        matches = [event for event in ordered if event.event_name == name]
        if matches:
            event = matches[-1] if name in {"return_verified", "episode_closed"} else matches[0]
            selected[event.episode_seq] = event
    if len(selected) < TIMELINE_ROW_CAP:
        for event in ordered:
            selected.setdefault(event.episode_seq, event)
            if len(selected) >= TIMELINE_ROW_CAP:
                break
    priority = {name: index for index, name in enumerate(_MILESTONE_NAMES)}
    ranked = sorted(
        selected.values(),
        key=lambda event: (
            event.episode_seq not in {ordered[0].episode_seq, ordered[-1].episode_seq},
            priority.get(event.event_name, len(priority)), event.episode_seq,
        ),
    )[:TIMELINE_ROW_CAP]
    return tuple(sorted(ranked, key=lambda event: event.episode_seq)), len(ordered)


def _draw_cover(report, snapshot, focus) -> None:
    _white_page(report)
    report.setFillColor(NAVY)
    report.rect(0, PAGE_HEIGHT - 9 * mm, PAGE_WIDTH, 9 * mm, fill=1, stroke=0)
    report.setFillColor(CYAN)
    report.rect(MARGIN, PAGE_HEIGHT - 38 * mm, 18 * mm, 1.3 * mm, fill=1, stroke=0)
    _text(report, "MYELIN 2.0", MARGIN, PAGE_HEIGHT - 31 * mm, 10, NAVY, bold=True)
    _text(report, "MIRL", MARGIN, PAGE_HEIGHT - 70 * mm, 31, NAVY, bold=True)
    _text(report, "RECOVERY HISTORY REPORT", MARGIN, PAGE_HEIGHT - 82 * mm, 22, NAVY, bold=True)
    _text(report, "SINE -> MIRL", MARGIN, PAGE_HEIGHT - 103 * mm, 18, CYAN, bold=True)
    _paragraph(report, "MYELIN Intervention Recovery Loop", MARGIN, PAGE_HEIGHT - 121 * mm,
               125 * mm, 24 * mm, size=13, leading=17, color=INK, bold=True)
    generated, zone = _generated_display(snapshot)
    _text(report, f"Generated: {generated} [{zone}]", MARGIN, 79 * mm, 9, MUTED)
    _text(report, "Data Scope: Current MIRL + Recorded SINE / MIRL Recovery History",
          MARGIN, 70 * mm, 8, MUTED)
    if focus is not None:
        _text(report, f"Latest recorded episode: {_display_id(focus)}", MARGIN, 61 * mm, 8, MUTED)
    report.setStrokeColor(LINE)
    report.line(MARGIN, 42 * mm, PAGE_WIDTH - MARGIN, 42 * mm)
    _text(report, "MYELIN", MARGIN, 31 * mm, 10, NAVY, bold=True)
    _text(report, "GUIDE - RECOVER - FOCUS", MARGIN, 23 * mm, 8, MUTED)


def _draw_episode_page(report, snapshot, focus, history, timeline, timeline_total) -> None:
    _page_base(report, snapshot, 2)
    y = _section(report, "01", "CURRENT EPISODE", PAGE_HEIGHT - 27 * mm)
    if focus is None:
        _empty_box(report, "No factual MIRL episode has been recorded.", MARGIN, y, CONTENT_WIDTH, 31 * mm)
        y -= 38 * mm
    else:
        facts = (
            ("EPISODE", _display_id(focus)), ("STATUS", _status_text(focus)),
            ("APPLICATION", _recorded(focus.application)), ("TRIGGER", _trigger_label(focus)),
            ("HIGHEST SINE", _highest_sine(focus)),
            ("RETURN LATENCY", _duration(focus.verified_return_latency_seconds)),
            ("RECOVERY ATTEMPTS", str(focus.recovery_attempt_count)),
            ("RELAPSES", str(focus.relapse_count)),
        )
        _fact_grid(report, facts, MARGIN, y, columns=4, cell_height=15.5 * mm)
        y -= 35.5 * mm
        _paragraph(
            report,
            "No live-active confirmation is part of this export; the newest recorded episode is shown. Closed evidence is never labelled active.",
            MARGIN, y, CONTENT_WIDTH, 9 * mm, size=6.7, leading=8.3, color=MUTED,
        )
        y -= 10 * mm

    y = _section(report, "02", "EPISODE HISTORY", y)
    if not history:
        _empty_box(report, "No MIRL episode history recorded.", MARGIN, y, CONTENT_WIDTH, 14 * mm)
        y -= 20 * mm
    else:
        rows = [("EPISODE", "OPENED", "APPLICATION", "HIGHEST SINE", "OUTCOME", "EVENTS")]
        for row in history:
            rows.append((
                _display_id(row), _clock(row.started_at, snapshot.live_mirl.presentation_timezone),
                _recorded(row.application), _highest_sine(row), _outcome(row), str(len(row.timeline)),
            ))
        _draw_table(report, rows, MARGIN, y, (29, 28, 34, 25, 39, 23), 6.2 * mm)
        y -= len(rows) * 6.2 * mm + 3 * mm
        _text(report, f"Showing latest {len(history)} of {len(_ordered_episodes(snapshot))} projected MIRL episodes - newest first.",
              MARGIN, y, 6.3, MUTED)
        y -= 8 * mm

    y = _section(report, "03", "EVENT TIMELINE", y)
    if focus is None or not timeline:
        _empty_box(report, "No recorded event evidence for the latest episode.", MARGIN, y, CONTENT_WIDTH, 14 * mm)
        return
    rows = [("SEQ", "TIME", "EVENT", "CLASS", "REASON / OUTCOME")]
    for event in timeline:
        rows.append((
            str(event.episode_seq), _clock(event.occurred_at, snapshot.live_mirl.presentation_timezone),
            _event_label(event.event_name), _humanize(event.observed_or_derived),
            _humanize(event.reason_or_outcome_code, "Not recorded"),
        ))
    _draw_table(report, rows, MARGIN, y, (12, 31, 55, 28, 52), 5.6 * mm)
    _text(report, f"{len(timeline)} key milestones shown - {timeline_total} total recorded events - exact episode_seq order.",
          MARGIN, y - len(rows) * 5.6 * mm - 3 * mm, 6.3, MUTED)


def _draw_evidence_page(report, snapshot, evidence) -> None:
    _page_base(report, snapshot, 3)
    y = _section(report, "04", "HISTORY EVIDENCE", PAGE_HEIGHT - 27 * mm)
    if evidence:
        rows = [("EPISODE", "DISTRACTED", "RECOVERED", "HIGHEST", "TRIGGER", "APP", "LATENCY")]
        for row in evidence:
            recovered = _recovered_at(row) if row.final_outcome == _RECOVERED_OUTCOME else None
            rows.append((
                _display_id(row), _clock(row.started_at, snapshot.live_mirl.presentation_timezone),
                _clock(recovered, snapshot.live_mirl.presentation_timezone), _highest_sine(row),
                _clock(row.trigger_fired_at, snapshot.live_mirl.presentation_timezone, seconds=True),
                _recorded(row.application), _duration(row.verified_return_latency_seconds),
            ))
        _draw_table(report, rows, MARGIN, y, (27, 26, 26, 22, 31, 24, 22), 6.5 * mm)
        y -= len(rows) * 6.5 * mm + 3 * mm
        _text(report, f"Showing latest {len(evidence)} of {len(_ordered_episodes(snapshot))}. Missing measurements remain unavailable, never zero.",
              MARGIN, y, 6.3, MUTED)
        y -= 8 * mm
    else:
        _empty_box(report, "No MIRL history evidence recorded.", MARGIN, y, CONTENT_WIDTH, 14 * mm)
        y -= 20 * mm

    y = _section(report, "05", "DATA QUALITY", y)
    live = snapshot.live_mirl
    metadata = live.metadata
    quality = (
        ("INTEGRITY", snapshot.integrity_status.value), ("ISSUE COUNT", str(len(snapshot.integrity_issues))),
        ("METRIC EXCLUSIONS", str(metadata.exclusion_count)),
        ("EVIDENCE POPULATION", _humanize(metadata.evidence_population)),
        ("POPULATION SCOPE", _humanize(metadata.population_scope)),
        ("SELECTED RANGE", _recorded(metadata.selected_range_label)),
        ("PROJECTED AT", _clock(metadata.generated_at, live.presentation_timezone, seconds=True)),
        ("PROJECTOR", _recorded(metadata.projector_version)),
    )
    _fact_grid(report, quality, MARGIN, y, columns=4, cell_height=15.5 * mm, value_size=7.2)
    y -= 35.5 * mm
    _paragraph(report, _issue_digest(snapshot), MARGIN, y, CONTENT_WIDTH, 18 * mm,
               size=6.4, leading=8.1, color=MUTED)
    y -= 19 * mm
    y = _section(report, "06", "ABOUT MIRL", y)
    _about_panel(report, MARGIN, y, CONTENT_WIDTH, 82 * mm)


def _about_panel(report, x, y, width, height) -> None:
    report.setFillColor(NAVY)
    report.roundRect(x, y - height, width, height, 2.5 * mm, fill=1, stroke=0)
    report.setFillColor(CYAN)
    report.rect(x, y - 1.5 * mm, width, 1.5 * mm, fill=1, stroke=0)
    _text(report, "MIRL", x + 7 * mm, y - 12 * mm, 16, WHITE, bold=True)
    _text(report, "MYELIN INTERVENTION RECOVERY LOOP", x + 7 * mm, y - 20 * mm, 8, CYAN, bold=True)
    _paragraph(report,
        "MIRL records the behavioral recovery pathway that follows a factual MYELIN intervention. It preserves evidence of SINE exposure, return attempts, verification, relapse and closure.",
        x + 7 * mm, y - 27 * mm, width - 14 * mm, 18 * mm, size=8.2, leading=11, color=WHITE)
    _text(report, "OBSERVES", x + 7 * mm, y - 49 * mm, 6.7, CYAN, bold=True)
    _text(report, "SINE intervention -> Response -> Recovery -> Closure", x + 7 * mm, y - 56 * mm, 8, WHITE)
    _text(report, "RECORDED EVIDENCE MAY INCLUDE", x + 7 * mm, y - 65 * mm, 6.7, CYAN, bold=True)
    _text(report, "SINE stage exposure - return attempts - verification - relapse - recovery latency - closure outcome",
          x + 7 * mm, y - 72 * mm, 7.2, WHITE)
    _text(report, "SCIENTIFIC BOUNDARY", x + 100 * mm, y - 49 * mm, 6.7, CYAN, bold=True)
    _paragraph(report,
        "Behavioral software evidence only. MIRL does not directly measure attention, dopamine, brain activity, cognition, psychological state or clinical state.",
        x + 100 * mm, y - 55 * mm, width - 107 * mm, 24 * mm, size=7.2, leading=9.2, color=WHITE)


def _page_base(report, snapshot, page_number: int) -> None:
    _white_page(report)
    report.setFillColor(NAVY)
    report.rect(0, PAGE_HEIGHT - 8 * mm, PAGE_WIDTH, 8 * mm, fill=1, stroke=0)
    generated, zone = _generated_display(snapshot)
    _text(report, "DATA SCOPE: CURRENT MIRL + RECORDED RECOVERY HISTORY", MARGIN, PAGE_HEIGHT - 15 * mm, 6.5, MUTED, bold=True)
    _text_right(report, f"GENERATED: {generated} [{zone}]", PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 15 * mm, 6.5, MUTED)
    report.setStrokeColor(LINE)
    report.line(MARGIN, 14 * mm, PAGE_WIDTH - MARGIN, 14 * mm)
    _text(report, "MYELIN 2.0 - MIRL", MARGIN, 9 * mm, 7, MUTED)
    _text_right(report, f"PAGE {page_number:02d}", PAGE_WIDTH - MARGIN, 9 * mm, 7, MUTED, bold=True)


def _white_page(report) -> None:
    report.setFillColor(WHITE)
    report.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)


def _section(report, number: str, title: str, y: float) -> float:
    _text(report, number, MARGIN, y, 8.5, CYAN, bold=True)
    _text(report, title, MARGIN + 11 * mm, y, 14, NAVY, bold=True)
    report.setStrokeColor(CYAN)
    report.setLineWidth(0.8)
    report.line(MARGIN, y - 3 * mm, PAGE_WIDTH - MARGIN, y - 3 * mm)
    return y - 10 * mm


def _fact_grid(report, facts, x, y, *, columns: int, cell_height: float, value_size: float = 8.1) -> None:
    gap = 2.5 * mm
    width = (CONTENT_WIDTH - (columns - 1) * gap) / columns
    for index, (caption, value) in enumerate(facts):
        row, column = divmod(index, columns)
        left = x + column * (width + gap)
        top = y - row * (cell_height + gap)
        report.setFillColor(SOFT)
        report.setStrokeColor(LINE)
        report.roundRect(left, top - cell_height, width, cell_height, 2.2 * mm, fill=1, stroke=1)
        _text(report, caption, left + 3 * mm, top - 5 * mm, 5.8, MUTED, bold=True)
        _paragraph(report, value, left + 3 * mm, top - 7.2 * mm, width - 6 * mm,
                   cell_height - 8 * mm, size=value_size, leading=value_size + 1.5,
                   color=NAVY, bold=True)


def _draw_table(report, rows, x, y, widths_mm, row_height) -> None:
    widths = [value * mm for value in widths_mm]
    for row_index, row in enumerate(rows):
        left = x
        for value, width in zip(row, widths):
            report.setFillColor(NAVY if row_index == 0 else (PALE_CYAN if row_index % 2 else SOFT))
            report.setStrokeColor(LINE)
            report.rect(left, y - (row_index + 1) * row_height, width, row_height, fill=1, stroke=1)
            _paragraph(report, value, left + 1.5 * mm, y - row_index * row_height - 1.5 * mm,
                       width - 3 * mm, row_height - 2 * mm, size=5.7 if row_index else 5.6,
                       leading=6.5, color=WHITE if row_index == 0 else INK, bold=row_index == 0)
            left += width


def _empty_box(report, text, x, y, width, height) -> None:
    report.setFillColor(SOFT)
    report.setStrokeColor(LINE)
    report.roundRect(x, y - height, width, height, 2 * mm, fill=1, stroke=1)
    _paragraph(report, text, x + 4 * mm, y - 5 * mm, width - 8 * mm, height - 8 * mm,
               size=8, leading=10, color=INK)


def _generated_display(snapshot) -> tuple[str, str]:
    try:
        moment = project_utc_timestamp(snapshot.generated_at, snapshot.live_mirl.presentation_timezone)
        return moment.strftime("%d %b %Y - %H:%M:%S"), timezone_tag(moment, snapshot.live_mirl.presentation_timezone)
    except Exception:
        return "Unavailable", "Unavailable"


def _clock(value, zone: str, *, seconds: bool = False) -> str:
    if not value:
        return "Unavailable"
    try:
        moment = project_utc_timestamp(value, zone)
        return moment.strftime("%H:%M:%S" if seconds else "%d %b %H:%M")
    except Exception:
        return "Unavailable"


def _display_id(row) -> str:
    value = str(getattr(row, "short_display_id", "") or "")
    return value if value.startswith("EPI-") else "Not recorded"


def _recorded(value) -> str:
    text = _pdf_text(value)
    return text or "Not recorded"


def _humanize(value, empty: str = "Unavailable") -> str:
    text = _pdf_text(value)
    return text.replace("_", " ").title() if text else empty


def _event_label(value) -> str:
    return _humanize(value, "Event unavailable")


def _highest_sine(row) -> str:
    stages = tuple(getattr(row, "sine_stages_exposed", ()) or ())
    return f"SINE-{max(stages)}" if stages else "Not recorded"


def _status_text(row) -> str:
    return "Closed" if row.final_outcome is not None else "Open / In Progress"


def _outcome(row) -> str:
    return "In Progress" if row.final_outcome is None else _humanize(row.final_outcome)


def _trigger_label(row) -> str:
    return "Recorded" if row.trigger_fired_at else "Not recorded"


def _duration(value) -> str:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return "Unavailable"
    total = max(0, int(round(float(value))))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def _recovered_at(row):
    found = None
    for event in tuple(row.timeline):
        if event.event_name == "return_verified":
            found = event.occurred_at
    return found


def _issue_digest(snapshot) -> str:
    issues = Counter(issue.code for issue in snapshot.integrity_issues)
    ranked = sorted(issues.items(), key=lambda item: (-item[1], item[0]))[:3]
    digest = "; ".join(f"{_humanize(code)} x {count}" for code, count in ranked)
    if len(issues) > len(ranked):
        digest += f"; {len(issues) - len(ranked)} additional issue kinds"
    if not digest:
        digest = "No integrity issues supplied by the read authority."
    return (f"Evidence status: {snapshot.integrity_status.value}. {digest}. "
            "Episode order follows episode_seq; missing evidence is displayed as unavailable.")


def _pdf_text(value) -> str:
    text = " ".join(str(value or "").split())
    replacements = {
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
        "\u2212": "-", "\u2192": "->", "\u00b7": "-", "\u00a0": " ",
        "\u2019": "'", "\u2018": "'", "\u00d7": "x",
    }
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    return "".join(character if ord(character) < 128 else "?" for character in text)[:1000]


def _paragraph(report, text, x, y, width, height, *, size, leading, color=INK, bold=False):
    style = ParagraphStyle("MirlPdfParagraph", fontName="Helvetica-Bold" if bold else "Helvetica",
                           fontSize=size, leading=leading, textColor=color)
    paragraph = Paragraph(html.escape(_pdf_text(text)), style)
    _, used = paragraph.wrap(width, height)
    if used > height + 0.1:
        raise MirlReportError("MIRL report content exceeds its fixed page region")
    paragraph.drawOn(report, x, y - used)
    return y - used


def _text(report, text, x, y, size, color, *, bold=False) -> None:
    report.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    report.setFillColor(color)
    report.drawString(x, y, _pdf_text(text))


def _text_right(report, text, x, y, size, color, *, bold=False) -> None:
    report.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    report.setFillColor(color)
    report.drawRightString(x, y, _pdf_text(text))


__all__ = [
    "REPORT_SCHEMA_VERSION", "MirlReportError", "MirlReportRequest",
    "MirlReportResult", "build_mirl_report_pdf", "suggested_report_filename",
]
