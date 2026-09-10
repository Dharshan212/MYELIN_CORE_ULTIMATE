"""Three-page A4 publication report for one factual MINE projection.

The renderer is a presentation boundary only.  It receives an immutable
``MineProjection`` and never opens SQLite, calls ``MineRuntime``, derives
physiology, or reconstructs missing dwell/return measurements.  Normal export
always selects the newest durably closed formal episode from the supplied
projection, independently of any dashboard selection.
"""
from __future__ import annotations

import html
import math
import os
import secrets
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

from MINE.read_model import MineEpisodeProjection, MineProjection
from time_projection import project_utc_timestamp, timezone_tag


REPORT_SCHEMA_VERSION: Final = "myelin-mine-pdf-v1"
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN: Final = 16 * mm
CONTENT_WIDTH: Final = PAGE_WIDTH - (2 * MARGIN)

NAVY: Final = colors.HexColor("#10283E")
CYAN: Final = colors.HexColor("#19B7C8")
INK: Final = colors.HexColor("#213343")
MUTED: Final = colors.HexColor("#667989")
LINE: Final = colors.HexColor("#D5E0E7")
SOFT: Final = colors.HexColor("#F4F8FA")
PALE_CYAN: Final = colors.HexColor("#EAF8FA")
GREEN: Final = colors.HexColor("#2F8F69")
WHITE: Final = colors.white

_BANDS: Final = (
    "10 MIN OR LESS",
    "11-30 MIN",
    "31-60 MIN",
    "61-120 MIN",
    "MORE THAN 120 MIN",
)
_RETURN_DETECTED_NAMES: Final = frozenset({
    "RETURN_VISUAL_CONFIRMING_STARTED",
    "RETURN_VERIFICATION_STARTED",
    "RETURN_VERIFICATION_COMPLETED",
    "RETURN_CONFIRMED",
})


class MineReportError(RuntimeError):
    """Raised when a factual three-page report cannot be produced."""


@dataclass(frozen=True, slots=True)
class MinePdfReportRequest:
    output_path: Path
    overwrite: bool = True

    def __post_init__(self) -> None:
        if Path(self.output_path).suffix.lower() != ".pdf":
            raise ValueError("output_path must end with .pdf")


@dataclass(frozen=True, slots=True)
class MinePdfReportResult:
    output_path: str
    generated_at_utc: str
    byte_size: int
    page_count: int
    episode_display_id: str
    episode_event_count: int
    episode_dwell_count: int
    messenger_hop_count: int


def latest_completed_episode(projection: MineProjection) -> MineEpisodeProjection:
    """Return the newest formal episode with explicit durable closure."""

    if not isinstance(projection, MineProjection) or not projection.available:
        raise MineReportError("MINE durable evidence is unavailable; report was not created.")
    episode = next((item for item in projection.episodes if item.is_closed), None)
    if episode is None:
        raise MineReportError("No completed MINE episode is available for export.")
    if not _public_episode_id(episode.display_episode_id):
        raise MineReportError("MINE presentation identity is unavailable.")
    return episode


def suggested_report_filename(
    projection: MineProjection,
    *,
    generated_at: datetime | None = None,
) -> str:
    episode = latest_completed_episode(projection)
    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"MYELIN_MINE_REPORT_{episode.display_episode_id}_{stamp}.pdf"


def build_mine_report_pdf(
    projection: MineProjection,
    request: MinePdfReportRequest,
) -> MinePdfReportResult:
    """Render exactly three A4 portrait pages from one immutable projection."""

    if not isinstance(request, MinePdfReportRequest):
        raise TypeError("request must be MinePdfReportRequest")
    episode = latest_completed_episode(projection)
    output = Path(request.output_path).expanduser().resolve()
    if output.exists() and not request.overwrite:
        raise FileExistsError("report destination already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}-{secrets.token_hex(6)}.tmp.pdf")

    try:
        report = pdfcanvas.Canvas(
            str(temporary),
            pagesize=A4,
            pageCompression=1,
            invariant=0,
        )
        report.setTitle(f"MYELIN MINE Episode Report - {episode.display_episode_id}")
        report.setAuthor("MYELIN")
        report.setSubject("MINE durable behavioral software evidence")
        _draw_cover(report, projection, episode)
        report.showPage()
        _draw_analysis_page(report, projection, episode)
        report.showPage()
        _draw_return_about_page(report, projection, episode)
        report.showPage()
        report.save()
        if not temporary.exists() or temporary.stat().st_size <= 0:
            raise MineReportError("ReportLab produced no PDF bytes")
        if request.overwrite:
            os.replace(temporary, output)
        else:
            os.link(temporary, output)
            temporary.unlink(missing_ok=True)
    except Exception as error:
        temporary.unlink(missing_ok=True)
        if isinstance(error, (MineReportError, FileExistsError)):
            raise
        raise MineReportError("MINE report generation failed.") from error

    return MinePdfReportResult(
        output_path=str(output),
        generated_at_utc=projection.generated_at_utc,
        byte_size=output.stat().st_size,
        page_count=3,
        episode_display_id=episode.display_episode_id,
        episode_event_count=episode.event_count,
        episode_dwell_count=len(episode.dwell_records),
        messenger_hop_count=len(episode.messenger_hops),
    )


def _draw_cover(
    report: pdfcanvas.Canvas,
    projection: MineProjection,
    episode: MineEpisodeProjection,
) -> None:
    report.setFillColor(WHITE)
    report.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
    report.setFillColor(NAVY)
    report.rect(0, PAGE_HEIGHT - 9 * mm, PAGE_WIDTH, 9 * mm, fill=1, stroke=0)
    report.setFillColor(CYAN)
    report.rect(MARGIN, PAGE_HEIGHT - 38 * mm, 18 * mm, 1.3 * mm, fill=1, stroke=0)

    y = PAGE_HEIGHT - 31 * mm
    _text(report, "MYELIN 2.0", MARGIN, y, 10, NAVY, bold=True)
    y -= 39 * mm
    _text(report, "MINE", MARGIN, y, 31, NAVY, bold=True)
    y -= 12 * mm
    _text(report, "EPISODE REPORT", MARGIN, y, 22, NAVY, bold=True)
    y -= 21 * mm
    _text(report, episode.display_episode_id, MARGIN, y, 18, CYAN, bold=True)
    y -= 18 * mm
    _paragraph(
        report,
        "Messaging Intervention Nudge Escalation",
        MARGIN,
        y,
        115 * mm,
        30 * mm,
        size=13,
        leading=17,
        color=INK,
        bold=True,
    )

    generated, zone = _generated_display(projection)
    y = 79 * mm
    _text(report, f"Generated: {generated} [{zone}]", MARGIN, y, 9, MUTED)
    y -= 9 * mm
    _text(report, "Data Scope: Latest Completed MINE Episode", MARGIN, y, 8, MUTED)
    report.setStrokeColor(LINE)
    report.setLineWidth(0.6)
    report.line(MARGIN, 42 * mm, PAGE_WIDTH - MARGIN, 42 * mm)
    _text(report, "MYELIN", MARGIN, 31 * mm, 10, NAVY, bold=True)
    _text(report, "GUIDE - RECOVER - FOCUS", MARGIN, 23 * mm, 8, MUTED)


def _draw_analysis_page(
    report: pdfcanvas.Canvas,
    projection: MineProjection,
    episode: MineEpisodeProjection,
) -> None:
    _page_base(report, projection, episode, 2)
    y = PAGE_HEIGHT - 27 * mm
    y = _section(report, "01", "OVERVIEW", y)

    final_platform = (
        episode.messenger_platforms[-1][1]
        if episode.messenger_platforms
        else episode.starting_platform_label
    )
    overview = (
        ("EPISODE", episode.display_episode_id),
        ("START PLATFORM", episode.starting_platform_label or "Not recorded"),
        ("FINAL PLATFORM", final_platform or "Not recorded"),
        ("BRANCH", _humanize(episode.branch)),
        ("FINAL OUTCOME", _humanize(episode.closure_outcome)),
        ("CLOSURE REASON", _humanize(episode.closure_reason)),
        ("RECORDED STEPS", str(episode.event_count)),
        ("MESSENGER HOPS", str(len(episode.messenger_hops))),
    )
    _fact_grid(report, overview, MARGIN, y, columns=4, cell_height=16 * mm)
    y -= 36 * mm
    summary = _episode_summary(episode)
    _paragraph(report, summary, MARGIN, y, CONTENT_WIDTH, 12 * mm, size=7.6, leading=9.6)

    y -= 18 * mm
    y = _section(report, "02", "EPISODE PATH", y)
    _draw_event_path(report, episode, MARGIN, y, CONTENT_WIDTH, 73 * mm)
    y -= 79 * mm
    _draw_messenger_hop(report, episode, MARGIN, y, CONTENT_WIDTH)

    y -= 25 * mm
    y = _section(report, "03", "MBI", y)
    _draw_mbi(report, projection, episode, MARGIN, y, CONTENT_WIDTH)


def _draw_return_about_page(
    report: pdfcanvas.Canvas,
    projection: MineProjection,
    episode: MineEpisodeProjection,
) -> None:
    _page_base(report, projection, episode, 3)
    y = PAGE_HEIGHT - 27 * mm
    y = _section(report, "04", "RETURN & CLOSURE", y)

    detected = next(
        (event for event in episode.events if event.event_name in _RETURN_DETECTED_NAMES),
        None,
    )
    facts = (
        ("RETURN DETECTED", _event_label(detected.event_name) if detected else "Not recorded"),
        ("RETURN VERIFIED", "Recorded" if episode.return_verified else "Not recorded"),
        ("CLOSURE CONFIRMED", "Recorded" if episode.closure_confirmed else "Not recorded"),
        ("FINAL STATE", "Closed" if episode.is_closed else "Open / incomplete"),
        ("FINAL OUTCOME", _humanize(episode.closure_outcome)),
        ("CLOSURE REASON", _humanize(episode.closure_reason)),
        ("CLOSED AT", _display_stamp(episode.ended_at_display)),
        ("RETURN LATENCY", "Not recorded"),
    )
    _fact_grid(report, facts, MARGIN, y, columns=2, cell_height=17 * mm)
    y -= 82 * mm
    _label(report, "RETURN / CLOSURE TRACE", MARGIN, y)
    y -= 6 * mm
    _draw_compact_event_list(
        report,
        episode.return_closure_events,
        MARGIN,
        y,
        CONTENT_WIDTH,
        80 * mm,
        maximum_columns=2,
    )
    y -= 87 * mm
    _paragraph(
        report,
        _closure_summary(episode),
        MARGIN,
        y,
        CONTENT_WIDTH,
        20 * mm,
        size=8,
        leading=11,
    )

    y -= 27 * mm
    y = _section(report, "05", "ABOUT", y)
    about = (
        "MINE - Messaging Intervention Nudge Escalation - records messaging-use "
        "intervention episodes within MYELIN. This report uses factual durable "
        "mine_events data projected through MineProjection. Live MINE status is "
        "transported separately through MineSnapshot."
    )
    boundary = (
        "MBI reports recorded messaging dwell duration and deterministic duration "
        "bands. Messenger Hop reports recorded movement between certified messaging "
        "platforms. MYELIN observes behavioral computer-use events. It does not "
        "directly measure attention, dopamine, brain activity, or psychological state."
    )
    y = _paragraph(report, about, MARGIN, y, CONTENT_WIDTH, 29 * mm, size=8.3, leading=11.5)
    _paragraph(report, boundary, MARGIN, y - 4 * mm, CONTENT_WIDTH, 32 * mm, size=8.3, leading=11.5)


def _page_base(
    report: pdfcanvas.Canvas,
    projection: MineProjection,
    episode: MineEpisodeProjection,
    page_number: int,
) -> None:
    report.setFillColor(WHITE)
    report.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
    report.setFillColor(NAVY)
    report.rect(0, PAGE_HEIGHT - 8 * mm, PAGE_WIDTH, 8 * mm, fill=1, stroke=0)
    generated, zone = _generated_display(projection)
    _text(report, "DATA SCOPE: LATEST COMPLETED MINE EPISODE", MARGIN, PAGE_HEIGHT - 15 * mm, 6.8, MUTED, bold=True)
    _text_right(report, f"GENERATED: {generated} [{zone}]", PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 15 * mm, 6.8, MUTED)
    report.setStrokeColor(LINE)
    report.line(MARGIN, 14 * mm, PAGE_WIDTH - MARGIN, 14 * mm)
    _text(report, f"MYELIN 2.0 - MINE - {episode.display_episode_id}", MARGIN, 9 * mm, 7, MUTED)
    _text_right(report, f"PAGE {page_number:02d}", PAGE_WIDTH - MARGIN, 9 * mm, 7, MUTED, bold=True)


def _section(report: pdfcanvas.Canvas, number: str, title: str, y: float) -> float:
    _text(report, number, MARGIN, y, 8.5, CYAN, bold=True)
    _text(report, title, MARGIN + 11 * mm, y, 14, NAVY, bold=True)
    report.setStrokeColor(CYAN)
    report.setLineWidth(0.8)
    report.line(MARGIN, y - 3 * mm, PAGE_WIDTH - MARGIN, y - 3 * mm)
    return y - 10 * mm


def _fact_grid(report, facts, x, y, *, columns: int, cell_height: float) -> None:
    gap = 2.5 * mm
    width = (CONTENT_WIDTH - (columns - 1) * gap) / columns
    for index, (caption, value) in enumerate(facts):
        row, column = divmod(index, columns)
        left = x + column * (width + gap)
        top = y - row * (cell_height + gap)
        report.setFillColor(SOFT)
        report.setStrokeColor(LINE)
        report.roundRect(left, top - cell_height, width, cell_height, 2.2 * mm, fill=1, stroke=1)
        _text(report, caption, left + 3 * mm, top - 5 * mm, 6.2, MUTED, bold=True)
        _fit_text(report, value, left + 3 * mm, top - 11.5 * mm, width - 6 * mm, 8.4, NAVY, bold=True)


def _draw_event_path(report, episode, x, y, width, height) -> None:
    events = tuple(episode.events)
    _draw_compact_event_list(report, events, x, y, width, height, maximum_columns=3)
    _text(
        report,
        f"{len(events)} durable events shown in exact sequence.",
        x,
        y - height - 2.5 * mm,
        6.3,
        MUTED,
    )


def _draw_compact_event_list(
    report,
    events,
    x,
    y,
    width,
    height,
    *,
    maximum_columns: int,
) -> None:
    items = tuple(events)
    if not items:
        _empty_box(report, "Not recorded", x, y, width, 16 * mm)
        return
    row_height = 4.4 * mm
    rows_per_column = max(1, int(height // row_height))
    columns = min(maximum_columns, max(1, math.ceil(len(items) / rows_per_column)))
    rows = math.ceil(len(items) / columns)
    if rows > rows_per_column:
        row_height = max(3.2 * mm, height / rows)
    column_gap = 3 * mm
    column_width = (width - (columns - 1) * column_gap) / columns
    font_size = 6.4 if columns < 3 else 5.9
    for index, event in enumerate(items):
        column = index // rows
        row = index % rows
        left = x + column * (column_width + column_gap)
        baseline = y - row * row_height - 3.1 * mm
        report.setFillColor(PALE_CYAN if index % 2 == 0 else SOFT)
        report.roundRect(left, baseline - 1.3 * mm, column_width, row_height - 0.4 * mm, 1.1 * mm, fill=1, stroke=0)
        sequence = int(getattr(event, "sequence", index + 1))
        label = f"{sequence:02d}  {_event_label(getattr(event, 'event_name', ''))}"
        _fit_text(report, label, left + 2 * mm, baseline, column_width - 4 * mm, font_size, INK)


def _draw_messenger_hop(report, episode, x, y, width) -> None:
    _label(report, "MESSENGER HOP", x, y)
    platforms = tuple(episode.messenger_platforms)
    if not platforms:
        text = "Not recorded"
    elif not episode.messenger_hops:
        text = f"{platforms[0][1]} - No messenger hops recorded"
    else:
        text = " -> ".join(label or key for key, label in platforms)
    _empty_box(report, text, x, y - 4 * mm, width, 14 * mm)


def _draw_mbi(report, projection, episode, x, y, width) -> None:
    exact = tuple(episode.dwell_records)
    if not exact:
        _empty_box(report, "Latest episode exact dwell: Not recorded", x, y, width, 13 * mm)
        table_bottom = y - 17 * mm
    else:
        visible = exact[:6]
        row_height = 5.2 * mm
        table_widths = (53 * mm, 27 * mm, width - 80 * mm)
        headers = ("PLATFORM", "EXACT DWELL", "MBI BAND")
        _table_row(report, headers, x, y, table_widths, row_height, header=True)
        for index, record in enumerate(visible, start=1):
            _table_row(
                report,
                (
                    record.platform_label or "Not recorded",
                    _dwell_text(record.dwell_seconds),
                    record.mbi_band or "Not recorded",
                ),
                x,
                y - index * row_height,
                table_widths,
                row_height,
                header=False,
            )
        table_bottom = y - (len(visible) + 1) * row_height
        if len(exact) > len(visible):
            _text(
                report,
                f"{len(exact)} recorded dwell segments - {len(visible)} shown in this compact report.",
                x,
                table_bottom - 3 * mm,
                6.2,
                MUTED,
            )
            table_bottom -= 5 * mm

    window = tuple(projection.dwell_records)
    factual = tuple(record for record in window if record.dwell_seconds is not None)
    counts = {band: 0 for band in _BANDS}
    for record in factual:
        band = _pdf_text(record.mbi_band)
        if band in counts:
            counts[band] += 1
    covered = len({
        (record.session_id, record.generation)
        for record in factual
    })
    scope = min(10, len(projection.episodes))
    context_one = "  |  ".join(f"{band}: {counts[band]}" for band in _BANDS[:3])
    context_two = "  |  ".join(f"{band}: {counts[band]}" for band in _BANDS[3:])
    _fit_text(report, context_one, x, table_bottom - 5 * mm, width, 6.4, NAVY, bold=True)
    _fit_text(report, context_two, x, table_bottom - 9 * mm, width, 6.4, NAVY, bold=True)
    _text(
        report,
        f"Dwell evidence recorded in {covered} of latest {scope} formal episodes; missing measurements are not zero.",
        x,
        table_bottom - 14 * mm,
        6.2,
        MUTED,
    )


def _table_row(report, values, x, y, widths, height, *, header: bool) -> None:
    left = x
    for value, width in zip(values, widths):
        report.setFillColor(NAVY if header else SOFT)
        report.setStrokeColor(LINE)
        report.rect(left, y - height, width, height, fill=1, stroke=1)
        _fit_text(
            report,
            value,
            left + 2 * mm,
            y - 3.5 * mm,
            width - 4 * mm,
            6.1,
            WHITE if header else INK,
            bold=header,
        )
        left += width


def _empty_box(report, text, x, y, width, height) -> None:
    report.setFillColor(SOFT)
    report.setStrokeColor(LINE)
    report.roundRect(x, y - height, width, height, 2 * mm, fill=1, stroke=1)
    _fit_text(report, text, x + 4 * mm, y - height / 2 - 1.5 * mm, width - 8 * mm, 7.5, INK)


def _generated_display(projection: MineProjection) -> tuple[str, str]:
    try:
        moment = project_utc_timestamp(
            projection.generated_at_utc,
            projection.presentation_timezone,
        )
        return (
            moment.strftime("%d %b %Y - %H:%M:%S"),
            timezone_tag(moment, projection.presentation_timezone),
        )
    except Exception:
        return "Unavailable", "Unavailable"


def _display_stamp(value: object) -> str:
    parts = _pdf_text(value).split()
    if len(parts) < 2:
        return "Not recorded"
    try:
        moment = datetime.fromisoformat(f"{parts[0]} {parts[1]}")
    except ValueError:
        return "Not recorded"
    zone = " ".join(parts[2:]) if len(parts) > 2 else ""
    return f"{moment.strftime('%d %b %Y - %H:%M:%S')} {zone}".strip()


def _public_episode_id(value: object) -> bool:
    text = str(value or "")
    parts = text.split("-")
    return bool(
        len(parts) == 3
        and parts[0] == "MINE"
        and len(parts[1]) == 8
        and parts[1].isdigit()
        and len(parts[2]) >= 2
        and parts[2].isdigit()
    )


def _humanize(value: object) -> str:
    text = _pdf_text(value)
    return text.replace("_", " ").title() if text else "Not recorded"


_EVENT_LABELS: Final = {
    "MINE_CANDIDATE_STARTED": "Messaging candidate started",
    "MESSAGING_PLATFORM_ENTERED": "Messaging platform entered",
    "MESSAGING_PLATFORM_TRANSITION": "Messenger platform changed",
    "MESSAGING_DWELL_SEGMENT_COMPLETED": "Messaging dwell recorded",
    "MINE_INITIAL_GATE_ELIGIBLE": "MINE-1 gate eligible",
    "MINE1_REQUESTED": "MINE-1 requested",
    "MINE1_DISPLAYED": "MINE-1 displayed",
    "MINE_EPISODE_STARTED": "MINE episode started",
    "RETURN_INTENT_RECORDED": "Return intent recorded",
    "IMPORTANT_INTENT_RECORDED": "Important intent recorded",
    "RETURN_INTENT_WINDOW_STARTED": "Return-intent window started",
    "IMPORTANT_DURATION_REQUESTED": "Important duration requested",
    "IMPORTANT_DURATION_COMMITTED": "Important duration committed",
    "IMPORTANT_ALLOWANCE_STARTED": "Important allowance started",
    "MINE2A_REQUESTED": "MINE-2A requested",
    "MINE2A_DISPLAYED": "MINE-2A displayed",
    "MINE2B_REQUESTED": "MINE-2B requested",
    "MINE2B_DISPLAYED": "MINE-2B displayed",
    "RETURN_VISUAL_CONFIRMING_STARTED": "Return visual confirming",
    "RETURN_VERIFICATION_STARTED": "Return verification started",
    "RETURN_VERIFICATION_COMPLETED": "Return verification completed",
    "RETURN_VERIFICATION_INTERRUPTED": "Return verification interrupted",
    "CLOSURE_CONFIRMATION_STARTED": "Closure confirmation started",
    "CLOSURE_CONFIRMATION_COMPLETED": "Closure confirmation completed",
    "CLOSURE_CONFIRMATION_INTERRUPTED": "Closure confirmation interrupted",
    "RETURN_CONFIRMED": "Return confirmed",
    "MINE_RUNTIME_STOPPED": "MINE runtime stopped",
    "EMERGENCY_STOPPED": "Emergency stop recorded",
    "MINE_SESSION_CLOSED": "MINE episode closed",
    "COSINE_HANDOVER_STARTED": "COSINE handoff started",
    "COSINE_HANDOVER_RESUMED": "COSINE handoff resumed",
    "COSINE_HANDOVER_SETTLED": "COSINE handoff settled",
}


def _event_label(value: object) -> str:
    name = str(value or "")
    return _EVENT_LABELS.get(name, _humanize(name))


def _episode_summary(episode: MineEpisodeProjection) -> str:
    clauses = []
    if episode.starting_platform_label:
        clauses.append(f"Messaging began on {episode.starting_platform_label}.")
    if episode.branch:
        clauses.append(f"{_humanize(episode.branch)} was recorded.")
    if episode.closure_outcome:
        clauses.append(f"The durable final outcome is {_humanize(episode.closure_outcome)}.")
    return " ".join(clauses) or "No optional summary facts were recorded."


def _closure_summary(episode: MineEpisodeProjection) -> str:
    outcome = _humanize(episode.closure_outcome)
    reason = _humanize(episode.closure_reason)
    if episode.return_verified:
        return (
            f"Return verification is recorded. The episode closed with outcome {outcome} "
            f"and closure reason {reason}. Return latency is not recorded."
        )
    return (
        f"No verified return is claimed. The episode closed with outcome {outcome} "
        f"and closure reason {reason}. Return latency is not recorded."
    )


def _dwell_text(value: object) -> str:
    if type(value) not in {int, float} or not math.isfinite(float(value)) or value < 0:
        return "Not recorded"
    seconds = float(value)
    whole = int(seconds)
    nanos = int(round((seconds - whole) * 1_000_000_000))
    if nanos == 1_000_000_000:
        whole += 1
        nanos = 0
    hours, remainder = divmod(whole, 3600)
    minutes, whole_seconds = divmod(remainder, 60)
    base = (
        f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"
        if hours
        else f"{minutes:02d}:{whole_seconds:02d}"
    )
    return base + (f".{nanos:09d}".rstrip("0") if nanos else "")


def _pdf_text(value: object) -> str:
    text = " ".join(str(value or "").split())
    replacements = {
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
        "\u2014": "-", "\u2212": "-", "\u2192": "->", "\u00b7": "-",
        "\u00a0": " ", "\u2019": "'", "\u2018": "'",
    }
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    return "".join(character if ord(character) < 128 else "?" for character in text)[:1000]


def _paragraph(report, text, x, y, width, height, *, size, leading, color=INK, bold=False):
    style = ParagraphStyle(
        "MinePdfParagraph",
        fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size,
        leading=leading,
        textColor=color,
    )
    paragraph = Paragraph(html.escape(_pdf_text(text)), style)
    _, used = paragraph.wrap(width, height)
    paragraph.drawOn(report, x, y - used)
    return y - used


def _label(report, text, x, y) -> None:
    _text(report, text, x, y, 6.7, MUTED, bold=True)


def _text(report, text, x, y, size, color, *, bold=False) -> None:
    report.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    report.setFillColor(color)
    report.drawString(x, y, _pdf_text(text))


def _text_right(report, text, x, y, size, color, *, bold=False) -> None:
    report.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    report.setFillColor(color)
    report.drawRightString(x, y, _pdf_text(text))


def _fit_text(report, text, x, y, width, size, color, *, bold=False) -> None:
    font = "Helvetica-Bold" if bold else "Helvetica"
    value = _pdf_text(text) or "Not recorded"
    while len(value) > 1 and report.stringWidth(value, font, size) > width:
        value = value[:-1]
    if value != _pdf_text(text):
        value = value.rstrip() + "..."
        while len(value) > 3 and report.stringWidth(value, font, size) > width:
            value = value[:-4].rstrip() + "..."
    report.setFont(font, size)
    report.setFillColor(color)
    report.drawString(x, y, value)


__all__ = [
    "REPORT_SCHEMA_VERSION",
    "MinePdfReportRequest",
    "MinePdfReportResult",
    "MineReportError",
    "build_mine_report_pdf",
    "latest_completed_episode",
    "suggested_report_filename",
]
