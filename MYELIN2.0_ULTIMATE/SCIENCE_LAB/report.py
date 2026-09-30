"""MYELIN REPORT -- Phase 3 visual-reconstruction renderer.

Phase 3 scope only: reproduce the Chief/ChatGPT-frozen Cover + SP1-SP14
visual design as closely as practical using ReportLab vector drawing.  This
module does not decide what is true -- it formats already-approved layout
with development-safe placeholder content on the dynamic result pages
(SP6-SP10).  It performs no I/O, opens no database, and is not wired to any
UI control yet.

    GOOD (future, Phase 4+):  SCIENCE_LAB.analysis.Chapter3ResultPackage -> report.py -> PDF
    BAD, always:              report.py -> raw database / raw organ tables -> PDF

Everything below the "PHASE 3 DEV-ONLY PREVIEW FIXTURES" banner is disposable
scaffolding: literal placeholder values clearly separated from the drawing
code, used only to exercise every page's layout while Chapter 3 dynamic
wiring is still Phase 4's job.  Nothing in this module reads certified
evidence yet.
"""

from __future__ import annotations

import html
import math
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from reportlab.lib import colors
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import Paragraph

from SCIENCE_LAB.analysis import AVAILABLE, CERTIFIED, NO_EVIDENCE, NOT_APPLICABLE, UNAVAILABLE
from SCIENCE_LAB.report_model import (
    PRIMARY_TABLE_ROW_CAPACITY,
    OrganRenderModel,
    ReportRenderModel,
    SnapshotCard,
    adapt_certified_report_input,
    plan_report_pages,
)

REPORT_SCHEMA_VERSION: Final = "myelin-report-pdf-phase3-preview-v1"

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN: Final = 18 * mm
CONTENT_WIDTH: Final = PAGE_WIDTH - 2 * MARGIN

# ---------------------------------------------------------------------------
# Palette -- same design family MIRL/report.py already established for this
# codebase (navy/cyan/pale-cyan/ink/muted/line/soft); extended with the
# additional escalation/branch accent colours the MYELIN REPORT references
# use (amber for SINE-2, red for Protected Red / final lock, green/purple
# for MINE's two branches).
# ---------------------------------------------------------------------------
NAVY: Final = HexColor("#10283E")
NAVY_DEEP: Final = HexColor("#0B1B2E")
CYAN: Final = HexColor("#19B7C8")
CYAN_DARK: Final = HexColor("#0F87A8")
INK: Final = HexColor("#213343")
MUTED: Final = HexColor("#667989")
LINE: Final = HexColor("#D5E0E7")
SOFT: Final = HexColor("#F4F8FA")
PALE_CYAN: Final = HexColor("#EAF8FA")
PALE_BLUE: Final = HexColor("#EAF2FB")
WHITE: Final = colors.white
AMBER: Final = HexColor("#E8A93A")
AMBER_BG: Final = HexColor("#FBF1DD")
RED: Final = HexColor("#D9534F")
RED_BG: Final = HexColor("#FBE7E6")
GREEN: Final = HexColor("#3FAE6A")
GREEN_BG: Final = HexColor("#E7F6ED")
PURPLE: Final = HexColor("#8E5FC4")
PURPLE_BG: Final = HexColor("#F1E9F8")
BLUE_MED: Final = HexColor("#2E6FE0")


class MyelinReportError(RuntimeError):
    """Raised when a fixed Phase 3 layout region cannot hold its content."""


# ---------------------------------------------------------------------------
# Low-level text/shape primitives (same discipline as MIRL/report.py: a
# Paragraph that overflows its fixed box is a layout bug, not something to
# silently clip).
# ---------------------------------------------------------------------------

def _pdf_text(value) -> str:
    text = " ".join(str(value if value is not None else "").split())
    replacements = {
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "--",
        "−": "-", "→": "->", "↔": "<->", "·": "-", " ": " ",
        "’": "'", "‘": "'", "×": "x", "…": "...",
    }
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    return "".join(character if ord(character) < 128 else "?" for character in text)[:2000]


def _text(c, text, x, y, size, color, *, bold=False, spacing: float = 0.0, align: str = "left", serif: bool = False) -> None:
    font = ("Times-Bold" if bold else "Times-Roman") if serif else ("Helvetica-Bold" if bold else "Helvetica")
    c.setFont(font, size)
    c.setFillColor(color)
    clean = _pdf_text(text)
    if spacing:
        letter_widths = [c.stringWidth(ch, font, size) for ch in clean]
        total = sum(letter_widths) + spacing * max(0, len(clean) - 1)
        if align == "right":
            cursor = x - total
        elif align == "center":
            cursor = x - total / 2
        else:
            cursor = x
        for ch, lw in zip(clean, letter_widths):
            c.drawString(cursor, y, ch)
            cursor += lw + spacing
        return
    if align == "right":
        c.drawRightString(x, y, clean)
    elif align == "center":
        c.drawCentredString(x, y, clean)
    else:
        c.drawString(x, y, clean)


def _paragraph(c, text, x, y, width, height, *, size, leading, color=INK, bold=False, align="left") -> float:
    style = ParagraphStyle(
        f"MyelinPara{secrets.token_hex(4)}", fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size, leading=leading, textColor=color,
        alignment={"left": 0, "center": 1, "right": 2, "justify": 4}.get(align, 0),
    )
    paragraph = Paragraph(html.escape(_pdf_text(text)), style)
    _, used = paragraph.wrap(width, height + 0.01)
    if used > height + 0.5:
        raise MyelinReportError(
            f"Phase 3 layout region overflowed: needed {used:.1f}pt, had {height:.1f}pt for {text[:40]!r}"
        )
    paragraph.drawOn(c, x, y - used)
    return y - used


def _rule(c, x0, y, x1, color=CYAN, width=0.9) -> None:
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.line(x0, y, x1, y)


def _rrect(c, x, y, w, h, r, *, fill=None, stroke=None, line_width=0.7) -> None:
    if fill is not None:
        c.setFillColor(fill)
    if stroke is not None:
        c.setStrokeColor(stroke)
        c.setLineWidth(line_width)
    c.roundRect(x, y, w, h, r, fill=1 if fill is not None else 0, stroke=1 if stroke is not None else 0)


# ---------------------------------------------------------------------------
# Page frame: geometric top/bottom bands, running header, footer.  Shared by
# every SP page; the cover uses its own larger variant.
# ---------------------------------------------------------------------------

def _geometric_band(c, *, top: bool) -> None:
    """Approximation of the frozen diagonal-cut blue band.  Exact pixel
    reproduction of the reference art is not attempted; the band's role
    (a recognisable angular MYELIN motif at the top and a mirrored one at
    the bottom of every page) is preserved with vector shapes.
    """

    bar_h = 2.6 * mm
    if top:
        c.setFillColor(NAVY)
        c.rect(0, PAGE_HEIGHT - bar_h, PAGE_WIDTH, bar_h, fill=1, stroke=0)
        band_top = PAGE_HEIGHT - bar_h
        band_h = 9.5 * mm
        c.saveState()
        p = c.beginPath()
        p.moveTo(PAGE_WIDTH * 0.42, band_top)
        p.lineTo(PAGE_WIDTH, band_top)
        p.lineTo(PAGE_WIDTH, band_top - band_h)
        p.lineTo(PAGE_WIDTH * 0.55, band_top - band_h)
        p.close()
        c.setFillColor(NAVY)
        c.drawPath(p, fill=1, stroke=0)
        for offset, color, w in ((0, CYAN, 3.4), (5.2, WHITE, 2.6), (9.4, NAVY, 2.0)):
            c.setStrokeColor(color)
            c.setLineWidth(w * mm)
            c.line(PAGE_WIDTH * 0.62 + offset * mm, band_top + 1 * mm,
                   PAGE_WIDTH * 0.98 + offset * mm, band_top - band_h - 3 * mm)
        c.restoreState()
    else:
        c.setFillColor(NAVY)
        c.rect(0, 0, PAGE_WIDTH, bar_h, fill=1, stroke=0)
        band_h = 9.5 * mm
        c.saveState()
        p = c.beginPath()
        p.moveTo(0, bar_h)
        p.lineTo(PAGE_WIDTH * 0.5, bar_h)
        p.lineTo(PAGE_WIDTH * 0.4, bar_h + band_h)
        p.lineTo(0, bar_h + band_h)
        p.close()
        c.setFillColor(NAVY)
        c.drawPath(p, fill=1, stroke=0)
        for offset, color, w in ((0, CYAN, 3.4), (5.2, WHITE, 2.6), (9.4, NAVY, 2.0)):
            c.setStrokeColor(color)
            c.setLineWidth(w * mm)
            c.line(0 - offset * mm, bar_h + band_h + 2 * mm,
                   PAGE_WIDTH * 0.34 - offset * mm, bar_h - 2 * mm)
        c.restoreState()


def _logo_mark(c, x, y, size) -> None:
    """The small crossing-strokes 'X' mark beside the MYELIN wordmark.  A
    faithful vector approximation of the canonical PNG mark's silhouette,
    used only at sizes too small for the raster asset to stay crisp; the
    canonical PNG asset itself is used on the cover (see _draw_cover).
    """

    c.saveState()
    c.setLineWidth(size * 0.16)
    c.setLineCap(1)
    c.setStrokeColor(PURPLE)
    c.line(x, y + size, x + size * 0.5, y + size * 0.15)
    c.setStrokeColor(CYAN)
    c.line(x + size, y + size, x + size * 0.5, y + size * 0.15)
    c.setFillColor(CYAN_DARK)
    c.circle(x + size * 0.5, y + size * 0.08, size * 0.09, fill=1, stroke=0)
    c.restoreState()


def _wordmark(c, x, y, *, size=10, spacing=1.6, color=NAVY) -> None:
    _text(c, "MYELIN", x, y, size, color, bold=True, spacing=spacing)


def _page_frame(c, *, page_code: str, chapter_label: str) -> tuple[float, float]:
    """Draw the common body-page frame.  Returns (content_top_y, footer_y)
    -- the vertical band a page's own content must lay itself out inside.
    """

    c.setFillColor(WHITE)
    c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
    _geometric_band(c, top=True)
    _geometric_band(c, top=False)

    header_y = PAGE_HEIGHT - 17 * mm
    _logo_mark(c, MARGIN, header_y - 1 * mm, 4.6 * mm)
    _wordmark(c, MARGIN + 7 * mm, header_y, size=9.5, spacing=1.4)

    _text(c, "MYELIN REPORT", PAGE_WIDTH - MARGIN, header_y + 1.2 * mm, 9.5, NAVY, bold=True, align="right")
    _text(c, chapter_label, PAGE_WIDTH - MARGIN, header_y - 4.4 * mm, 8.2, CYAN, bold=True, align="right")
    _rule(c, PAGE_WIDTH - MARGIN - 26 * mm, header_y - 7.4 * mm, PAGE_WIDTH - MARGIN, CYAN, 0.8)

    content_top = header_y - 13 * mm
    footer_y = 22 * mm
    _rule(c, MARGIN, footer_y, PAGE_WIDTH - MARGIN, LINE, 0.6)
    return content_top, footer_y


def _footer(c, *, caption: str, page_label: str) -> None:
    footer_y = 22 * mm
    _paragraph(c, caption, MARGIN, footer_y - 3.2 * mm, CONTENT_WIDTH - 20 * mm, 6 * mm,
               size=6.6, leading=8, color=MUTED)
    _text(c, page_label, PAGE_WIDTH - MARGIN, footer_y - 3.6 * mm, 9, NAVY, bold=True, align="right")


def _page_label(fx, fallback: int) -> str:
    """Use a planned physical page number without changing frozen geometry."""

    return f"-- {getattr(fx, '_physical_page', fallback)}"


# ---------------------------------------------------------------------------
# Reusable page components
# ---------------------------------------------------------------------------

def _chapter_title(c, y, number: str, title: str) -> float:
    full = f"{number} | {title}"
    size = 20
    while size > 12 and c.stringWidth(_pdf_text(full), "Times-Bold", size) > CONTENT_WIDTH:
        size -= 1
    _text(c, full, MARGIN, y, size, NAVY, bold=True, serif=True)
    _rule(c, MARGIN, y - 4.5 * mm, PAGE_WIDTH - MARGIN, CYAN, 1.1)
    return y - 12 * mm


def _sp_title(c, y, title: str) -> float:
    """SP1's untitled essay-style heading (no leading chapter number)."""
    _text(c, title, MARGIN, y, 20, NAVY, bold=True, serif=True)
    _rule(c, MARGIN, y - 4.5 * mm, PAGE_WIDTH - MARGIN, CYAN, 1.1)
    return y - 12 * mm


def _callout(c, y, text: str, *, height=None, bold=False, size=9.3) -> float:
    """height=None (the default) auto-sizes the box to its wrapped text, so
    callers never have to guess a fixed height for a variable-length
    fixture string -- the single largest source of Phase 3 layout-overflow
    bugs before this fix.  Pass an explicit height only to force extra
    whitespace.
    """

    style = ParagraphStyle(
        f"MyelinCalloutMeasure{secrets.token_hex(4)}",
        fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size, leading=size + 2.6, textColor=NAVY,
    )
    measured = Paragraph(html.escape(_pdf_text(text)), style)
    _, text_h = measured.wrap(CONTENT_WIDTH - 12 * mm, 500 * mm)
    if height is None:
        height = text_h + 7.2 * mm
    _rrect(c, MARGIN, y - height, CONTENT_WIDTH, height, 1.8 * mm, fill=PALE_BLUE)
    c.setFillColor(NAVY)
    c.rect(MARGIN, y - height, 1.4 * mm, height, fill=1, stroke=0)
    _paragraph(c, text, MARGIN + 6 * mm, y - 3.6 * mm, CONTENT_WIDTH - 12 * mm, height - 5 * mm,
               size=size, leading=size + 2.6, color=NAVY, bold=bold)
    return y - height - 5 * mm


_ICONS = {
    "doc": lambda c, cx, cy, r: _icon_doc(c, cx, cy, r),
    "gear": lambda c, cx, cy, r: _icon_gear(c, cx, cy, r),
    "flow": lambda c, cx, cy, r: _icon_flow(c, cx, cy, r),
    "info": lambda c, cx, cy, r: _icon_info(c, cx, cy, r),
    "flag": lambda c, cx, cy, r: _icon_flag(c, cx, cy, r),
    "bell": lambda c, cx, cy, r: _icon_bell(c, cx, cy, r),
    "chat": lambda c, cx, cy, r: _icon_chat(c, cx, cy, r),
    "play": lambda c, cx, cy, r: _icon_play(c, cx, cy, r),
    "cap": lambda c, cx, cy, r: _icon_cap(c, cx, cy, r),
    "chart": lambda c, cx, cy, r: _icon_chart(c, cx, cy, r),
    "warn": lambda c, cx, cy, r: _icon_warn(c, cx, cy, r),
    "list": lambda c, cx, cy, r: _icon_list(c, cx, cy, r),
    "clock": lambda c, cx, cy, r: _icon_clock(c, cx, cy, r),
    "check": lambda c, cx, cy, r: _icon_check(c, cx, cy, r),
    "refresh": lambda c, cx, cy, r: _icon_refresh(c, cx, cy, r),
    "target": lambda c, cx, cy, r: _icon_target(c, cx, cy, r),
    "layers": lambda c, cx, cy, r: _icon_layers(c, cx, cy, r),
    "undo": lambda c, cx, cy, r: _icon_undo(c, cx, cy, r),
    "brain": lambda c, cx, cy, r: _icon_brain(c, cx, cy, r),
    "people": lambda c, cx, cy, r: _icon_people(c, cx, cy, r),
    "book": lambda c, cx, cy, r: _icon_book(c, cx, cy, r),
    "growth": lambda c, cx, cy, r: _icon_growth(c, cx, cy, r),
    "watch": lambda c, cx, cy, r: _icon_watch(c, cx, cy, r),
    "eye": lambda c, cx, cy, r: _icon_eye(c, cx, cy, r),
    "laptop": lambda c, cx, cy, r: _icon_laptop(c, cx, cy, r),
    "shield": lambda c, cx, cy, r: _icon_shield(c, cx, cy, r),
    "person": lambda c, cx, cy, r: _icon_person(c, cx, cy, r),
    "route": lambda c, cx, cy, r: _icon_route(c, cx, cy, r),
    "lock": lambda c, cx, cy, r: _icon_lock(c, cx, cy, r),
    "cup": lambda c, cx, cy, r: _icon_cup(c, cx, cy, r),
    "arrow_return": lambda c, cx, cy, r: _icon_refresh(c, cx, cy, r),
}


def _icon_doc(c, cx, cy, r):
    c.rect(cx - r * 0.42, cy - r * 0.55, r * 0.84, r * 1.1, fill=0, stroke=1)
    for i in range(3):
        c.line(cx - r * 0.26, cy + r * 0.25 - i * r * 0.28, cx + r * 0.26, cy + r * 0.25 - i * r * 0.28)


def _icon_gear(c, cx, cy, r):
    c.circle(cx, cy, r * 0.42, fill=0, stroke=1)
    import math
    for i in range(8):
        angle = math.pi * 2 * i / 8
        x0, y0 = cx + math.cos(angle) * r * 0.42, cy + math.sin(angle) * r * 0.42
        x1, y1 = cx + math.cos(angle) * r * 0.65, cy + math.sin(angle) * r * 0.65
        c.line(x0, y0, x1, y1)


def _icon_flow(c, cx, cy, r):
    c.line(cx - r * 0.5, cy - r * 0.3, cx + r * 0.5, cy - r * 0.3)
    c.line(cx + r * 0.5, cy - r * 0.3, cx + r * 0.25, cy - r * 0.05)
    c.line(cx + r * 0.5, cy - r * 0.3, cx + r * 0.25, cy - r * 0.55)
    c.line(cx - r * 0.5, cy + r * 0.3, cx + r * 0.5, cy + r * 0.3)
    c.line(cx + r * 0.5, cy + r * 0.3, cx + r * 0.25, cy + r * 0.05)


def _icon_info(c, cx, cy, r):
    c.circle(cx, cy, r * 0.55, fill=0, stroke=1)
    c.circle(cx, cy + r * 0.22, r * 0.05, fill=1, stroke=0)
    c.line(cx, cy - r * 0.05, cx, cy - r * 0.3)


def _icon_flag(c, cx, cy, r):
    c.line(cx - r * 0.3, cy - r * 0.5, cx - r * 0.3, cy + r * 0.5)
    p = c.beginPath()
    p.moveTo(cx - r * 0.3, cy + r * 0.5)
    p.lineTo(cx + r * 0.4, cy + r * 0.35)
    p.lineTo(cx - r * 0.3, cy + r * 0.05)
    c.drawPath(p, fill=0, stroke=1)


def _icon_bell(c, cx, cy, r):
    p = c.beginPath()
    p.moveTo(cx - r * 0.35, cy - r * 0.05)
    p.curveTo(cx - r * 0.35, cy + r * 0.45, cx + r * 0.35, cy + r * 0.45, cx + r * 0.35, cy - r * 0.05)
    p.lineTo(cx + r * 0.45, cy - r * 0.3)
    p.lineTo(cx - r * 0.45, cy - r * 0.3)
    p.close()
    c.drawPath(p, fill=0, stroke=1)
    c.circle(cx, cy - r * 0.45, r * 0.08, fill=1, stroke=0)


def _icon_chat(c, cx, cy, r):
    c.roundRect(cx - r * 0.5, cy - r * 0.3, r * 1.0, r * 0.7, r * 0.15, fill=0, stroke=1)
    p = c.beginPath()
    p.moveTo(cx - r * 0.15, cy - r * 0.3)
    p.lineTo(cx - r * 0.3, cy - r * 0.55)
    p.lineTo(cx + r * 0.05, cy - r * 0.3)
    c.drawPath(p, fill=0, stroke=1)


def _icon_play(c, cx, cy, r):
    c.circle(cx, cy, r * 0.5, fill=0, stroke=1)
    p = c.beginPath()
    p.moveTo(cx - r * 0.15, cy - r * 0.2)
    p.lineTo(cx - r * 0.15, cy + r * 0.2)
    p.lineTo(cx + r * 0.22, cy)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def _icon_cap(c, cx, cy, r):
    p = c.beginPath()
    p.moveTo(cx - r * 0.5, cy + r * 0.05)
    p.lineTo(cx, cy + r * 0.3)
    p.lineTo(cx + r * 0.5, cy + r * 0.05)
    p.lineTo(cx, cy - r * 0.2)
    p.close()
    c.drawPath(p, fill=0, stroke=1)
    c.line(cx + r * 0.35, cy - r * 0.02, cx + r * 0.35, cy - r * 0.35)


def _icon_chart(c, cx, cy, r):
    c.line(cx - r * 0.45, cy - r * 0.4, cx - r * 0.45, cy + r * 0.45)
    c.line(cx - r * 0.45, cy - r * 0.4, cx + r * 0.5, cy - r * 0.4)
    for dx, h in ((-0.25, 0.25), (0.05, 0.5), (0.35, 0.35)):
        c.rect(cx + dx * r - r * 0.08, cy - r * 0.4, r * 0.16, h * r, fill=1, stroke=0)


def _icon_warn(c, cx, cy, r):
    p = c.beginPath()
    p.moveTo(cx, cy + r * 0.5)
    p.lineTo(cx + r * 0.45, cy - r * 0.35)
    p.lineTo(cx - r * 0.45, cy - r * 0.35)
    p.close()
    c.drawPath(p, fill=0, stroke=1)
    c.line(cx, cy + r * 0.1, cx, cy - r * 0.1)
    c.circle(cx, cy - r * 0.22, r * 0.04, fill=1, stroke=0)


def _icon_list(c, cx, cy, r):
    for i in range(3):
        y0 = cy + r * 0.3 - i * r * 0.3
        c.circle(cx - r * 0.4, y0, r * 0.05, fill=1, stroke=0)
        c.line(cx - r * 0.22, y0, cx + r * 0.45, y0)


def _icon_clock(c, cx, cy, r):
    c.circle(cx, cy, r * 0.5, fill=0, stroke=1)
    c.line(cx, cy, cx, cy + r * 0.28)
    c.line(cx, cy, cx + r * 0.2, cy)


def _icon_check(c, cx, cy, r):
    c.circle(cx, cy, r * 0.5, fill=0, stroke=1)
    p = c.beginPath()
    p.moveTo(cx - r * 0.22, cy)
    p.lineTo(cx - r * 0.03, cy - r * 0.18)
    p.lineTo(cx + r * 0.28, cy + r * 0.2)
    c.drawPath(p, fill=0, stroke=1)


def _icon_refresh(c, cx, cy, r):
    c.arc(cx - r * 0.4, cy - r * 0.4, cx + r * 0.4, cy + r * 0.4, 40, 270)
    p = c.beginPath()
    p.moveTo(cx + r * 0.32, cy + r * 0.28)
    p.lineTo(cx + r * 0.44, cy + r * 0.1)
    p.lineTo(cx + r * 0.16, cy + r * 0.08)
    c.drawPath(p, fill=1, stroke=0)


def _icon_target(c, cx, cy, r):
    c.circle(cx, cy, r * 0.5, fill=0, stroke=1)
    c.circle(cx, cy, r * 0.28, fill=0, stroke=1)
    c.circle(cx, cy, r * 0.08, fill=1, stroke=0)


def _icon_layers(c, cx, cy, r):
    for dy in (-0.25, 0, 0.25):
        p = c.beginPath()
        p.moveTo(cx - r * 0.45, cy + dy * r)
        p.lineTo(cx, cy + dy * r - r * 0.15)
        p.lineTo(cx + r * 0.45, cy + dy * r)
        p.lineTo(cx, cy + dy * r + r * 0.15)
        p.close()
        c.drawPath(p, fill=0, stroke=1)


def _icon_undo(c, cx, cy, r):
    c.arc(cx - r * 0.4, cy - r * 0.4, cx + r * 0.4, cy + r * 0.4, 90, 260)
    p = c.beginPath()
    p.moveTo(cx - r * 0.4, cy + r * 0.05)
    p.lineTo(cx - r * 0.15, cy + r * 0.05)
    p.lineTo(cx - r * 0.28, cy - r * 0.22)
    c.drawPath(p, fill=1, stroke=0)


def _icon_brain(c, cx, cy, r):
    c.circle(cx - r * 0.15, cy, r * 0.4, fill=0, stroke=1)
    c.circle(cx + r * 0.2, cy, r * 0.32, fill=0, stroke=1)


def _icon_people(c, cx, cy, r):
    c.circle(cx - r * 0.2, cy + r * 0.15, r * 0.18, fill=0, stroke=1)
    c.circle(cx + r * 0.22, cy + r * 0.15, r * 0.18, fill=0, stroke=1)
    c.arc(cx - r * 0.42, cy - r * 0.4, cx + r * 0.02, cy + r * 0.05, 0, 180)
    c.arc(cx - r * 0.02, cy - r * 0.4, cx + r * 0.42, cy + r * 0.05, 0, 180)


def _icon_book(c, cx, cy, r):
    c.line(cx, cy - r * 0.4, cx, cy + r * 0.4)
    for side in (-1, 1):
        p = c.beginPath()
        p.moveTo(cx, cy - r * 0.4)
        p.lineTo(cx + side * r * 0.45, cy - r * 0.25)
        p.lineTo(cx + side * r * 0.45, cy + r * 0.35)
        p.lineTo(cx, cy + r * 0.4)
        c.drawPath(p, fill=0, stroke=1)


def _icon_growth(c, cx, cy, r):
    c.line(cx - r * 0.45, cy - r * 0.4, cx - r * 0.45, cy + r * 0.45)
    c.line(cx - r * 0.45, cy - r * 0.4, cx + r * 0.5, cy - r * 0.4)
    p = c.beginPath()
    p.moveTo(cx - r * 0.3, cy - r * 0.1)
    p.lineTo(cx, cy + r * 0.1)
    p.lineTo(cx + r * 0.35, cy + r * 0.35)
    c.drawPath(p, fill=0, stroke=1)
    p2 = c.beginPath()
    p2.moveTo(cx + r * 0.15, cy + r * 0.35)
    p2.lineTo(cx + r * 0.35, cy + r * 0.35)
    p2.lineTo(cx + r * 0.35, cy + r * 0.15)
    c.drawPath(p2, fill=0, stroke=1)


def _icon_watch(c, cx, cy, r):
    c.roundRect(cx - r * 0.32, cy - r * 0.5, r * 0.64, r, r * 0.18, fill=0, stroke=1)
    p = c.beginPath()
    p.moveTo(cx - r * 0.15, cy)
    p.lineTo(cx, cy + r * 0.1)
    p.lineTo(cx + r * 0.15, cy - r * 0.15)
    c.drawPath(p, fill=0, stroke=1)


def _icon_eye(c, cx, cy, r):
    p = c.beginPath()
    p.moveTo(cx - r * 0.48, cy)
    p.curveTo(cx - r * 0.2, cy + r * 0.35, cx + r * 0.2, cy + r * 0.35, cx + r * 0.48, cy)
    p.curveTo(cx + r * 0.2, cy - r * 0.35, cx - r * 0.2, cy - r * 0.35, cx - r * 0.48, cy)
    c.drawPath(p, fill=0, stroke=1)
    c.circle(cx, cy, r * 0.15, fill=0, stroke=1)


def _icon_laptop(c, cx, cy, r):
    c.rect(cx - r * 0.42, cy - r * 0.15, r * 0.84, r * 0.5, fill=0, stroke=1)
    c.line(cx - r * 0.55, cy - r * 0.25, cx + r * 0.55, cy - r * 0.25)


def _icon_shield(c, cx, cy, r):
    p = c.beginPath()
    p.moveTo(cx, cy + r * 0.5)
    p.lineTo(cx + r * 0.4, cy + r * 0.3)
    p.lineTo(cx + r * 0.4, cy - r * 0.15)
    p.lineTo(cx, cy - r * 0.5)
    p.lineTo(cx - r * 0.4, cy - r * 0.15)
    p.lineTo(cx - r * 0.4, cy + r * 0.3)
    p.close()
    c.drawPath(p, fill=0, stroke=1)


def _icon_person(c, cx, cy, r):
    c.circle(cx, cy + r * 0.2, r * 0.2, fill=0, stroke=1)
    c.arc(cx - r * 0.4, cy - r * 0.45, cx + r * 0.4, cy + r * 0.1, 0, 180)


def _icon_route(c, cx, cy, r):
    c.line(cx - r * 0.45, cy + r * 0.35, cx + r * 0.45, cy - r * 0.35)
    p = c.beginPath()
    p.moveTo(cx + r * 0.2, cy - r * 0.5)
    p.lineTo(cx + r * 0.45, cy - r * 0.35)
    p.lineTo(cx + r * 0.4, cy - r * 0.05)
    c.drawPath(p, fill=0, stroke=1)


def _icon_lock(c, cx, cy, r):
    c.rect(cx - r * 0.32, cy - r * 0.35, r * 0.64, r * 0.5, fill=0, stroke=1)
    c.arc(cx - r * 0.22, cy - r * 0.1, cx + r * 0.22, cy + r * 0.45, 0, 180)


def _icon_cup(c, cx, cy, r):
    c.rect(cx - r * 0.3, cy - r * 0.35, r * 0.6, r * 0.45, fill=0, stroke=1)
    c.arc(cx + r * 0.3, cy - r * 0.15, cx + r * 0.5, cy + r * 0.15, -90, 180)


def _icon_circle(c, cx, cy, r, icon: str, *, ring=CYAN, glyph=NAVY, fill=PALE_CYAN) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(ring)
    c.setLineWidth(1.0)
    c.circle(cx, cy, r, fill=1, stroke=1)
    c.setStrokeColor(glyph)
    c.setFillColor(glyph)
    c.setLineWidth(1.0)
    drawer = _ICONS.get(icon)
    if drawer:
        drawer(c, cx, cy, r * 0.62)


def _section_head(c, x, y, icon: str, title: str, body: str, width: float, *, body_size=8.6, body_height=16 * mm) -> float:
    _icon_circle(c, x + 4 * mm, y - 4 * mm, 4 * mm, icon)
    _text(c, title, x + 11 * mm, y - 2 * mm, 12.2, CYAN, bold=True, spacing=0.3)
    top = y - 8.4 * mm
    return _paragraph(c, body, x, top, width, body_height, size=body_size, leading=body_size + 2.6, color=INK)


def _card(c, x, y, w, h, *, fill=SOFT, stroke=LINE) -> None:
    _rrect(c, x, y - h, w, h, 2.2 * mm, fill=fill, stroke=stroke, line_width=0.7)


def _grid_cards(c, x, y, width, items, *, columns: int, card_h: float, gap=3.5 * mm,
                 render_cell) -> float:
    n = len(items)
    rows = -(-n // columns)
    cell_w = (width - (columns - 1) * gap) / columns
    for index, item in enumerate(items):
        row, col = divmod(index, columns)
        left = x + col * (cell_w + gap)
        top = y - row * (card_h + gap)
        render_cell(c, left, top, cell_w, card_h, item)
    return y - rows * (card_h + gap) + gap


def _chain_box(c, left, y, box_w, box_h, box, label_size, label_h) -> None:
    icon = box.get("icon")
    fill = box.get("fill", SOFT)
    stroke = box.get("stroke", LINE)
    _card(c, left, y, box_w, box_h, fill=fill, stroke=stroke)
    if icon:
        cy = y - min(4.2 * mm, box_h * 0.32)
        icon_r = min(3.0 * mm, box_h * 0.24)
        _icon_circle(c, left + box_w / 2, cy, icon_r, icon,
                     ring=box.get("ring", CYAN), glyph=box.get("glyph", NAVY), fill=box.get("icon_fill", WHITE))
        label_top = y - min(8.6 * mm, box_h * 0.64)
    else:
        label_top = y - min(3.0 * mm, box_h * 0.22)
    this_label_size = box.get("label_size", label_size)
    label_bottom = _paragraph(c, box["label"], left + 1.2 * mm, label_top, box_w - 2.4 * mm, label_h,
               size=this_label_size, leading=this_label_size + 1.3,
               color=box.get("label_color", NAVY), bold=True, align="center")
    if box.get("caption"):
        # Never more than the room actually left above this box's own
        # bottom edge -- an earlier version floored this at 4mm regardless,
        # which let a long wrapped label push the caption below the card
        # border on a tight (e.g. branch sub-box) box_h.
        caption_h = (label_bottom - 1.2 * mm) - (y - box_h) - 0.4 * mm
        _paragraph(c, box["caption"], left + 1.2 * mm, label_bottom - 1.2 * mm, box_w - 2.4 * mm,
                   max(0.1 * mm, caption_h),
                   size=5.6, leading=6.7, color=MUTED, align="center")


def _workflow_chain(c, x, y, width, boxes, *, box_w=None, box_h=17 * mm, gap=None) -> float:
    """A left-to-right chain of rounded boxes joined by arrows, matching
    the SINE/MINE/COSINE/COSECANT/journey-map workflow figures.

    A box may carry ``"branch": [box_a, box_b]`` instead of its own
    label/icon/caption -- that column then draws as two stacked half-height
    boxes fed by a single fan-in arrow and rejoined by a single fan-out
    arrow, for the two-option decision points MINE and COSINE actually
    branch on (this draws the existing box/arrow language differently; it
    does not introduce new colors, icons, or box styles)."""

    n = len(boxes)
    if gap is None:
        gap = 5 * mm
    if box_w is None:
        box_w = (width - (n - 1) * gap) / n
    label_size = 6.0 if (box_w < 20 * mm or n >= 6) else 7.0
    label_h = 12 * mm if (box_w < 24 * mm or n >= 5) else 5 * mm
    sub_gap = 2.2 * mm
    sub_h = (box_h - sub_gap) / 2
    sub_label_size = max(5.2, label_size - 0.6)
    sub_label_h = max(5 * mm, sub_h * 0.6)

    for index, box in enumerate(boxes):
        left = x + index * (box_w + gap)
        branch = box.get("branch")
        if branch:
            top_y = y
            bottom_y = y - sub_h - sub_gap
            # Sub-boxes skip the icon: at half box_h there is only room for
            # a (possibly two-line) label plus caption, and the two-option
            # decision point is already visually distinct via the fan-in/
            # fan-out arrows below.
            sub_a = {k: v for k, v in branch[0].items() if k != "icon"}
            sub_b = {k: v for k, v in branch[1].items() if k != "icon"}
            _chain_box(c, left, top_y, box_w, sub_h, sub_a, sub_label_size, sub_label_h)
            _chain_box(c, left, bottom_y, box_w, sub_h, sub_b, sub_label_size, sub_label_h)
            if index > 0:
                prev_right = left - gap + 0.6 * mm
                _fan_arrow(c, prev_right, y - box_h / 2, left - 0.4 * mm, top_y - sub_h / 2)
                _fan_arrow(c, prev_right, y - box_h / 2, left - 0.4 * mm, bottom_y - sub_h / 2)
            if index < n - 1:
                next_left = left + box_w + gap - 1.2 * mm
                _fan_arrow(c, left + box_w + 0.4 * mm, top_y - sub_h / 2, next_left, y - box_h / 2)
                _fan_arrow(c, left + box_w + 0.4 * mm, bottom_y - sub_h / 2, next_left, y - box_h / 2)
        else:
            _chain_box(c, left, y, box_w, box_h, box, label_size, label_h)
            if index < n - 1 and not boxes[index + 1].get("branch"):
                _arrow(c, left + box_w + 0.6 * mm, y - box_h / 2, gap - 1.2 * mm)
    return y - box_h


def _arrow(c, x, y, length) -> None:
    c.setStrokeColor(CYAN)
    c.setLineWidth(1.1)
    c.line(x, y, x + length, y)
    c.setFillColor(CYAN)
    p = c.beginPath()
    p.moveTo(x + length, y + 1.3 * mm)
    p.lineTo(x + length + 1.8 * mm, y)
    p.lineTo(x + length, y - 1.3 * mm)
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def _fan_arrow(c, x0, y0, x1, y1) -> None:
    """A single diagonal arrow segment used to fan a chain arrow out to, or
    in from, a branch's two stacked sub-boxes."""
    c.setStrokeColor(CYAN)
    c.setLineWidth(1.1)
    c.line(x0, y0, x1, y1)
    c.setFillColor(CYAN)
    angle = math.atan2(y1 - y0, x1 - x0)
    ah = 1.7 * mm
    spread = 0.5
    p = c.beginPath()
    p.moveTo(x1, y1)
    p.lineTo(x1 - ah * math.cos(angle - spread), y1 - ah * math.sin(angle - spread))
    p.lineTo(x1 - ah * math.cos(angle + spread), y1 - ah * math.sin(angle + spread))
    p.close()
    c.drawPath(p, fill=1, stroke=0)


def _table(c, x, y, col_widths_mm, rows, *, row_h=7.6 * mm, header=True) -> float:
    widths = [w * mm for w in col_widths_mm]
    header_h = row_h * 1.7 if header else row_h
    cursor = y
    for r_index, row in enumerate(rows):
        left = x
        is_header = header and r_index == 0
        this_h = header_h if is_header else row_h
        bg = NAVY if is_header else (PALE_CYAN if r_index % 2 == 0 else WHITE)
        fg = WHITE if is_header else INK
        for value, w in zip(row, widths):
            c.setFillColor(bg)
            c.setStrokeColor(LINE)
            c.setLineWidth(0.5)
            c.rect(left, cursor - this_h, w, this_h, fill=1, stroke=1)
            _paragraph(c, str(value), left + 1.6 * mm, cursor - 1.7 * mm, w - 3.2 * mm, this_h - 2.4 * mm,
                       size=6.3, leading=7.2, color=fg, bold=is_header)
            left += w
        cursor -= this_h
    return cursor


def _line_chart(c, x, y, w, h, *, categories, series, y_labels, title="") -> float:
    _card(c, x, y, w, h, fill=WHITE, stroke=LINE)
    pad_l, pad_r, pad_t, pad_b = 16 * mm, 4 * mm, 4 * mm, 9 * mm
    plot_x, plot_y = x + pad_l, y - h + pad_b
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(plot_x, plot_y, plot_x, plot_y + plot_h)
    c.line(plot_x, plot_y, plot_x + plot_w, plot_y)
    n_levels = len(y_labels)
    for i, label in enumerate(y_labels):
        ly = plot_y + plot_h * i / max(1, n_levels - 1)
        _text(c, label, plot_x - 2.5 * mm, ly - 1 * mm, 6.2, MUTED, align="right")
        c.setStrokeColor(HexColor("#EEF3F6"))
        c.line(plot_x, ly, plot_x + plot_w, ly)
    n = len(categories)
    step = plot_w / max(1, n - 1) if n > 1 else 0
    visible_ticks = set(_visible_chart_tick_indices(n, max(2, int(plot_w / (18 * mm)) + 1)))
    for i, cat in enumerate(categories):
        cx = plot_x + step * i
        if i in visible_ticks:
            _text(c, cat, cx, plot_y - 5 * mm, 6.2, MUTED, align="center")
    for s in series:
        values = s["values"]
        dashed = s.get("dashed", False)
        color = s.get("color", CYAN)
        c.setStrokeColor(color)
        c.setLineWidth(1.4)
        if dashed:
            c.setDash(2.2, 1.6)
        else:
            c.setDash()
        pts = [(plot_x + step * i, plot_y + plot_h * v) for i, v in enumerate(values) if v is not None]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            c.line(x0, y0, x1, y1)
        c.setDash()
        marker = s.get("marker", "filled")
        for (px, py), v in zip(pts, [v for v in values if v is not None]):
            if marker == "hollow":
                c.setFillColor(WHITE)
                c.setStrokeColor(color)
                c.circle(px, py, 1.5 * mm, fill=1, stroke=1)
            else:
                c.setFillColor(color)
                c.circle(px, py, 1.5 * mm, fill=1, stroke=0)
    legend_x = plot_x
    legend_y = y - 2.5 * mm
    for i, s in enumerate(series):
        lx = legend_x + i * 44 * mm
        c.setStrokeColor(s.get("color", CYAN))
        c.setLineWidth(1.4)
        if s.get("dashed"):
            c.setDash(2, 1.4)
        c.line(lx, legend_y, lx + 6 * mm, legend_y)
        c.setDash()
        _text(c, s["label"], lx + 7.5 * mm, legend_y - 1 * mm, 6.4, MUTED)
    return y - h


def _y_axis_tick_fractions(y_max: float) -> tuple[float, ...]:
    """Vertical-axis tick positions, as fractions of ``y_max``, chosen so
    every rounded label is distinct.

    The plain five-tick 0/0.25/0.5/0.75/1.0 scheme silently duplicates
    labels whenever ``y_max`` is a small integer -- e.g. ``y_max=1`` rounds
    to 0, 0, 0, 1, 1 (Python's banker's rounding on ``round(0.5)``), which
    read as a fabricated multi-point axis for what is a single certified
    observation.  When that happens, this falls back to exactly one tick
    per whole unit instead -- never a fractional label, never an invented
    data point, just an accurate integer scale (``0`` and ``1`` for
    ``y_max=1``)."""

    default = (0.0, 0.25, 0.5, 0.75, 1.0)
    if y_max <= 0:
        return default
    labels = [round(y_max * frac) for frac in default]
    if len(set(labels)) == len(labels):
        return default
    whole = int(round(y_max))
    if whole < 1:
        return default
    return tuple(i / whole for i in range(whole + 1))


def _bar_chart(c, x, y, w, h, *, categories, values, y_max, unit="", bars_color=CYAN, value_labels=True,
               extra_series=None) -> float:
    _card(c, x, y, w, h, fill=WHITE, stroke=LINE)
    pad_l, pad_r, pad_t, pad_b = 12 * mm, 4 * mm, 6 * mm, 9 * mm
    plot_x, plot_y = x + pad_l, y - h + pad_b
    plot_w, plot_h = w - pad_l - pad_r, h - pad_t - pad_b
    c.setStrokeColor(LINE)
    c.setLineWidth(0.6)
    c.line(plot_x, plot_y, plot_x, plot_y + plot_h)
    c.line(plot_x, plot_y, plot_x + plot_w, plot_y)
    for frac in _y_axis_tick_fractions(y_max):
        ly = plot_y + plot_h * frac
        _text(c, str(round(y_max * frac)), plot_x - 2.5 * mm, ly - 1 * mm, 6.2, MUTED, align="right")
        c.setStrokeColor(HexColor("#EEF3F6"))
        c.line(plot_x, ly, plot_x + plot_w, ly)
    n = len(categories)
    slot = plot_w / n
    bar_w = slot * 0.5
    visible_ticks = set(_visible_chart_tick_indices(n, max(2, int(plot_w / (18 * mm)) + 1)))
    for i, (cat, value) in enumerate(zip(categories, values)):
        bx = plot_x + slot * i + (slot - bar_w) / 2
        bh = plot_h * (value / y_max) if y_max else 0
        c.setFillColor(bars_color)
        c.rect(bx, plot_y, bar_w, bh, fill=1, stroke=0)
        if value_labels and i in visible_ticks:
            _text(c, str(value), bx + bar_w / 2, plot_y + bh + 1.6 * mm, 6.6, INK, align="center")
        if i in visible_ticks:
            _text(c, cat, plot_x + slot * i + slot / 2, plot_y - 5 * mm, 6.2, MUTED, align="center")
    if extra_series:
        for s in extra_series:
            pts = []
            for i, v in enumerate(s["values"]):
                cx = plot_x + slot * i + slot / 2
                cy = plot_y + plot_h * (v / y_max) if y_max else plot_y
                pts.append((cx, cy))
            c.setStrokeColor(s.get("color", PURPLE))
            c.setLineWidth(1.2)
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                c.line(x0, y0, x1, y1)
            for px, py in pts:
                c.setFillColor(WHITE)
                c.setStrokeColor(s.get("color", PURPLE))
                c.circle(px, py, 1.3 * mm, fill=1, stroke=1)
    legend_y = y - 2.5 * mm
    legend_x = plot_x
    c.setFillColor(bars_color)
    c.rect(legend_x, legend_y - 1.6 * mm, 3.4 * mm, 2.6 * mm, fill=1, stroke=0)
    _text(c, unit, legend_x + 5 * mm, legend_y - 1 * mm, 6.4, MUTED)
    if extra_series:
        offset = legend_x + 5 * mm + c.stringWidth(_pdf_text(unit), "Helvetica", 6.4) + 12 * mm
        for s in extra_series:
            c.setStrokeColor(s.get("color", PURPLE))
            c.setFillColor(WHITE)
            c.circle(offset, legend_y, 1.3 * mm, fill=1, stroke=1)
            _text(c, s["label"], offset + 4 * mm, legend_y - 1 * mm, 6.4, MUTED)
            offset += 4 * mm + c.stringWidth(_pdf_text(s["label"]), "Helvetica", 6.4) + 10 * mm
    return y - h


def _visible_chart_tick_indices(point_count: int, max_labels: int) -> tuple[int, ...]:
    """Thin only displayed x-axis labels while retaining every point/bar."""

    if point_count <= 0:
        return ()
    if point_count <= max_labels:
        return tuple(range(point_count))
    stride = math.ceil((point_count - 1) / (max_labels - 1))
    indices = list(range(0, point_count, stride))
    if indices[-1] != point_count - 1:
        indices.append(point_count - 1)
    return tuple(indices)


def _empty_chart(c, x, y, w, h, *, message) -> float:
    """Neutral placeholder for a chart region with no certified data points.

    NO CERTIFIED EVIDENCE = NO NUMBER: a chart must never fall back to a
    fake zero-valued series just to have something to draw -- that would
    visually claim observations exist when none are certified. This keeps
    the same card frame as _bar_chart/_line_chart so the page layout is
    unaffected, but draws no axis, no bars, and no points."""

    _card(c, x, y, w, h, fill=WHITE, stroke=LINE)
    icon_cy = y - h / 2 + 5 * mm
    _icon_circle(c, x + w / 2, icon_cy, 4 * mm, "warn", ring=MUTED, glyph=MUTED)
    _paragraph(c, message, x + 8 * mm, icon_cy - 7 * mm, w - 16 * mm, h / 2 - 2 * mm,
               size=7.4, leading=9, color=MUTED, align="center", bold=True)
    return y - h


def _two_col(x, width, gap=6 * mm) -> tuple[float, float, float]:
    col_w = (width - gap) / 2
    return x, x + col_w + gap, col_w


# ---------------------------------------------------------------------------
# Canonical logo asset (ASSET-0001..0010): exact path, native transparency
# and aspect ratio preserved; fail explicitly rather than substitute.
# ---------------------------------------------------------------------------

CANONICAL_LOGO_PATH: Final = (
    Path(__file__).resolve().parent.parent / "ASSETS" / "images" / "Myelin_Report_Logo.png"
)


def _draw_logo(c, cx, cy, target_h) -> None:
    """Draw the canonical logo centred at (cx, cy) scaled to target_h tall,
    preserving its native aspect ratio.  Fails loudly if the asset is
    missing rather than substituting another image (ASSET-0008)."""

    if not CANONICAL_LOGO_PATH.is_file():
        raise MyelinReportError(f"canonical logo missing at {CANONICAL_LOGO_PATH}")
    from PIL import Image

    with Image.open(CANONICAL_LOGO_PATH) as image:
        native_w, native_h = image.size
    aspect = native_w / native_h
    target_w = target_h * aspect
    c.drawImage(
        str(CANONICAL_LOGO_PATH), cx - target_w / 2, cy - target_h / 2, target_w, target_h,
        mask="auto", preserveAspectRatio=True,
    )


# ---------------------------------------------------------------------------
# Cover page
# ---------------------------------------------------------------------------

def _draw_cover_bands(c) -> None:
    bar_h = 9.5 * mm
    c.setFillColor(NAVY)
    c.rect(0, PAGE_HEIGHT - bar_h, PAGE_WIDTH, bar_h, fill=1, stroke=0)
    band_top = PAGE_HEIGHT - bar_h
    band_h = 30 * mm
    p = c.beginPath()
    p.moveTo(PAGE_WIDTH * 0.34, band_top)
    p.lineTo(PAGE_WIDTH, band_top)
    p.lineTo(PAGE_WIDTH, band_top - band_h)
    p.lineTo(PAGE_WIDTH * 0.5, band_top - band_h)
    p.close()
    c.setFillColor(NAVY)
    c.drawPath(p, fill=1, stroke=0)
    for offset, color, w in ((0, CYAN, 9), (13, WHITE, 7), (23, NAVY, 5)):
        c.setStrokeColor(color)
        c.setLineWidth(w * mm)
        c.line(PAGE_WIDTH * 0.4 + offset * mm, band_top + 3 * mm,
               PAGE_WIDTH + offset * mm, band_top - band_h - 12 * mm)

    c.setFillColor(NAVY)
    c.rect(0, 0, PAGE_WIDTH, bar_h, fill=1, stroke=0)
    p2 = c.beginPath()
    p2.moveTo(0, bar_h)
    p2.lineTo(PAGE_WIDTH * 0.58, bar_h)
    p2.lineTo(PAGE_WIDTH * 0.40, bar_h + band_h)
    p2.lineTo(0, bar_h + band_h)
    p2.close()
    c.setFillColor(NAVY)
    c.drawPath(p2, fill=1, stroke=0)
    for offset, color, w in ((0, CYAN, 9), (13, WHITE, 7), (23, NAVY, 5)):
        c.setStrokeColor(color)
        c.setLineWidth(w * mm)
        c.line(0 - offset * mm, bar_h + band_h + 10 * mm,
               PAGE_WIDTH * 0.5 - offset * mm, bar_h - 3 * mm)


def _draw_cover_texture(c) -> None:
    """Simplified approximation of the reference's decorative wave/hex
    background art in the lower half -- reduced to faint vector strokes and
    a sparse hex-dot lattice, deliberately subtle so it never competes with
    the title text."""

    c.saveState()
    c.setStrokeColor(HexColor("#DCEBF7"))
    c.setLineWidth(0.8)
    for i in range(5):
        yy = 250 + i * 14
        p = c.beginPath()
        p.moveTo(0, yy)
        p.curveTo(PAGE_WIDTH * 0.3, yy + 26, PAGE_WIDTH * 0.55, yy - 22, PAGE_WIDTH, yy + 10)
        c.drawPath(p, fill=0, stroke=1)
    c.setFillColor(HexColor("#CFE6F5"))
    for row in range(4):
        for col in range(6):
            hx = PAGE_WIDTH - 60 * mm + col * 7 * mm - (row % 2) * 3.5 * mm
            hy = 150 + row * 7 * mm
            c.circle(hx, hy, 0.6 * mm, fill=1, stroke=0)
    c.restoreState()


def _draw_cover(c, *, title: str, subtitle: str, tagline: str) -> None:
    c.setFillColor(WHITE)
    c.rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, fill=1, stroke=0)
    _draw_cover_bands(c)
    _draw_cover_texture(c)

    _text(c, "MYELIN", MARGIN, PAGE_HEIGHT - 16.5 * mm, 12, NAVY, bold=True, spacing=1.6)
    _text(c, "RESEARCH REPORT", MARGIN, PAGE_HEIGHT - 22.5 * mm, 7.5, MUTED, spacing=1.4)
    _text(c, "SCIENCE INSIGHTS", PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 15.5 * mm, 7.2, WHITE, bold=True, align="right", spacing=0.6)
    _text(c, "FOR A BRIGHTER", PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 20 * mm, 7.2, WHITE, bold=True, align="right", spacing=0.6)
    _text(c, "TOMORROW", PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 24.5 * mm, 7.2, WHITE, bold=True, align="right", spacing=0.6)
    _rule(c, PAGE_WIDTH - MARGIN - 20 * mm, PAGE_HEIGHT - 28.5 * mm, PAGE_WIDTH - MARGIN, WHITE, 0.5)

    _draw_logo(c, PAGE_WIDTH / 2, PAGE_HEIGHT - 92 * mm, 26 * mm)

    _text(c, title, PAGE_WIDTH / 2, PAGE_HEIGHT - 130 * mm, 34, NAVY_DEEP, bold=True, align="center", spacing=0.4, serif=True)
    _text(c, "RESEARCH REPORT", PAGE_WIDTH / 2, PAGE_HEIGHT - 141 * mm, 8.5, CYAN_DARK, bold=True, align="center", spacing=1.6)
    _rule(c, PAGE_WIDTH / 2 - 60 * mm, PAGE_HEIGHT - 143.5 * mm, PAGE_WIDTH / 2 - 22 * mm, LINE, 0.7)
    _rule(c, PAGE_WIDTH / 2 + 22 * mm, PAGE_HEIGHT - 143.5 * mm, PAGE_WIDTH / 2 + 60 * mm, LINE, 0.7)
    _paragraph(c, subtitle, PAGE_WIDTH / 2 - 75 * mm, PAGE_HEIGHT - 150 * mm, 150 * mm, 16 * mm,
               size=13.5, leading=17, color=INK, align="center")

    _text(c, "GENERATED BY MYELIN CORE", PAGE_WIDTH / 2, 42 * mm, 8, MUTED, bold=True, align="center", spacing=1.2)
    _rule(c, PAGE_WIDTH / 2 - 60 * mm, 43.6 * mm, PAGE_WIDTH / 2 - 46 * mm, LINE, 0.6)
    _rule(c, PAGE_WIDTH / 2 + 46 * mm, 43.6 * mm, PAGE_WIDTH / 2 + 60 * mm, LINE, 0.6)
    _text(c, tagline, PAGE_WIDTH / 2, 35 * mm, 9.5, CYAN_DARK, align="center", spacing=1.0)

    _text(c, "ADVANCING SCIENCE WITH INTELLIGENCE", PAGE_WIDTH - MARGIN, 4.2 * mm, 6.6, WHITE, bold=True, align="right", spacing=0.5)


# ---------------------------------------------------------------------------
# SP1 -- Introduction (Abstract, Keywords, Intro body, Figure 1)
# ---------------------------------------------------------------------------

def _page_sp1(c, fx) -> None:
    top, _ = _page_frame(c, page_code="SP1", chapter_label="Chapter 1  |  Introduction")
    y = _sp_title(c, top, "From Intent to Drift, Absorption, and Re-engagement")

    _rrect(c, MARGIN, y - 30 * mm, CONTENT_WIDTH, 30 * mm, 1.8 * mm, fill=PALE_BLUE, stroke=None)
    _text(c, "ABSTRACT", MARGIN + 5 * mm, y - 5.5 * mm, 8, CYAN, bold=True, spacing=0.8)
    y2 = _paragraph(c, fx.abstract, MARGIN + 5 * mm, y - 10.5 * mm, CONTENT_WIDTH - 10 * mm, 15 * mm,
                     size=8.4, leading=10.6, color=INK)
    _rule(c, MARGIN + 5 * mm, y - 25.5 * mm, PAGE_WIDTH - MARGIN - 5 * mm, LINE, 0.5)
    _paragraph(c, "Keywords: " + fx.keywords, MARGIN + 5 * mm, y - 28 * mm, CONTENT_WIDTH - 10 * mm, 5 * mm,
               size=7.6, leading=9, color=CYAN_DARK)
    y -= 36 * mm

    left_x, right_x, col_w = _two_col(MARGIN, CONTENT_WIDTH)
    _text(c, "1 | INTRODUCTION", left_x, y, 11.5, NAVY, bold=True, serif=True)
    _text(c, "Drift, competing tasks and return", right_x, y, 11.5, NAVY, bold=True, serif=True)
    y -= 5.5 * mm
    left_bottom = _paragraph(c, fx.intro_left, left_x, y, col_w, 62 * mm, size=8.0, leading=10.4, color=INK)
    right_bottom = _paragraph(c, fx.intro_right, right_x, y, col_w, 62 * mm, size=8.0, leading=10.4, color=INK)
    y = min(left_bottom, right_bottom) - 5 * mm

    y = _callout(c, y, fx.behavioral_geometry_statement, bold=True, size=9.6)

    boxes = [
        {"label": "INTENT", "caption": "Begin intended work", "icon": "target"},
        {"label": "DRIFT", "caption": "Switch to other activity", "icon": "laptop"},
        {"label": "ABSORPTION", "caption": "Sustained engagement elsewhere", "icon": "layers"},
        {"label": "RETURN", "caption": "Back to original task", "icon": "undo"},
        {"label": "RE-ENGAGEMENT", "caption": "Sustained recovery or relapse", "icon": "chart"},
    ]
    y = _workflow_chain(c, MARGIN, y, CONTENT_WIDTH, boxes, box_h=30 * mm, gap=8 * mm)
    y -= 5 * mm
    _text(c, "Figure 1  |  Conceptual behavioural trajectory studied by MYELIN", MARGIN, y, 7.6, CYAN_DARK, bold=True)
    y -= 6 * mm

    note_h = 20 * mm
    _rrect(c, MARGIN, y - note_h, CONTENT_WIDTH, note_h, 1.8 * mm, fill=PALE_BLUE, stroke=None)
    c.setFillColor(NAVY)
    c.rect(MARGIN, y - note_h, 1.1 * mm, note_h, fill=1, stroke=0)
    _paragraph(c, "Scope note:", MARGIN + 4.5 * mm, y - 3 * mm, CONTENT_WIDTH - 9 * mm, 4 * mm,
               size=7.4, leading=8.6, color=NAVY, bold=True)
    _paragraph(
        c,
        "The sequence describes the observable behavioural trajectory surrounding intended digital work. "
        "The terms do not imply that MYELIN directly measures attention, motivation, neural activity or "
        "cognitive state. The chapters that follow trace this trajectory through each MYELIN organ, the "
        "certified evidence each stage produces, and the results and conclusions that evidence can "
        "support.",
        MARGIN + 4.5 * mm, y - 6.6 * mm, CONTENT_WIDTH - 9 * mm, note_h - 8 * mm,
        size=7.2, leading=8.8, color=INK,
    )
    y -= note_h
    _footer(c, caption="", page_label=_page_label(fx, 2))


# ---------------------------------------------------------------------------
# Shared organ-anatomy block, used identically for SINE/MINE (SP2) and
# COSINE/COSECANT (SP3).
# ---------------------------------------------------------------------------

def _organ_block(c, y, *, icon, name, subtitle, body, core_purpose, distinctive_features,
                  workflow_boxes, figure_num, figure_caption, figure_note,
                  workflow_box_h=19 * mm, workflow_box_w=None) -> float:
    _icon_circle(c, MARGIN + 6 * mm, y - 6 * mm, 6 * mm, icon, ring=CYAN, glyph=NAVY, fill=WHITE)
    _text(c, name, MARGIN + 16 * mm, y - 4.5 * mm, 16, NAVY, bold=True)
    _text(c, subtitle, MARGIN + 16 * mm, y - 10.5 * mm, 9, CYAN_DARK, bold=True, spacing=0.6)
    y -= 16 * mm
    y = _paragraph(c, body, MARGIN, y, CONTENT_WIDTH, 15 * mm, size=8.2, leading=10.4, color=INK) - 3 * mm

    left_x, right_x, col_w = _two_col(MARGIN, CONTENT_WIDTH)
    box_h = 20 * mm
    _rrect(c, left_x, y - box_h, col_w, box_h, 1.6 * mm, fill=PALE_BLUE)
    c.setFillColor(NAVY)
    c.rect(left_x, y - box_h, 1.1 * mm, box_h, fill=1, stroke=0)
    _paragraph(c, "Core purpose:", left_x + 4.5 * mm, y - 3 * mm, col_w - 8 * mm, 4 * mm, size=7.4, leading=8.6, color=NAVY, bold=True)
    _paragraph(c, core_purpose, left_x + 4.5 * mm, y - 6.6 * mm, col_w - 8 * mm, box_h - 8 * mm, size=7.2, leading=8.6, color=INK)
    _rrect(c, right_x, y - box_h, col_w, box_h, 1.6 * mm, fill=PALE_BLUE)
    c.setFillColor(NAVY)
    c.rect(right_x, y - box_h, 1.1 * mm, box_h, fill=1, stroke=0)
    _paragraph(c, "Distinctive features:", right_x + 4.5 * mm, y - 3 * mm, col_w - 8 * mm, 4 * mm, size=7.4, leading=8.6, color=NAVY, bold=True)
    _paragraph(c, distinctive_features, right_x + 4.5 * mm, y - 6.6 * mm, col_w - 8 * mm, box_h - 8 * mm, size=7.2, leading=8.6, color=INK)
    y -= box_h + 5 * mm

    panel_h = workflow_box_h + 6 * mm
    _rrect(c, MARGIN, y - panel_h, CONTENT_WIDTH, panel_h, 2 * mm, fill=SOFT, stroke=LINE)
    y = _workflow_chain(c, MARGIN + 3 * mm, y - 3 * mm, CONTENT_WIDTH - 6 * mm, workflow_boxes,
                         box_h=workflow_box_h, box_w=workflow_box_w, gap=3.2 * mm) - 6 * mm
    _text(c, f"Figure {figure_num}  |  {figure_caption}", MARGIN, y, 7.6, CYAN_DARK, bold=True)
    y -= 4.2 * mm
    y = _paragraph(c, figure_note, MARGIN, y, CONTENT_WIDTH, 7 * mm, size=6.6, leading=8, color=MUTED)
    return y


# ---------------------------------------------------------------------------
# SP2 -- SINE and MINE
# ---------------------------------------------------------------------------

def _page_sp2(c, fx) -> None:
    top, _ = _page_frame(c, page_code="SP2", chapter_label="SP2  |  Chapter 2 Drift Intervention Organs")
    y = _chapter_title(c, top, "2", "DRIFT INTERVENTION ORGANS: SINE AND MINE")
    y = _callout(c, y, fx.sp2_intro)

    y = _organ_block(
        c, y, icon="bell", name="SINE", subtitle="SOFT INTERVENTION NUDGE ESCALATION",
        body=fx.sine_body,
        core_purpose="regulates general digital drift through progressive intervention.",
        distinctive_features="Blue to Amber to Protected Red escalation; return is not proven by a "
                              "button press alone; MIRL governs recovery verification.",
        workflow_boxes=[
            {"label": "DETECTED DIGITAL DRIFT", "caption": "Software-observed off-task behaviour", "icon": "warn", "ring": MUTED, "glyph": MUTED},
            {"label": "SINE-1", "caption": "Soft intervention: gentle nudge and refocus", "icon": "bell", "fill": PALE_CYAN, "ring": CYAN},
            {"label": "CONTINUED OFF-TASK", "caption": "Distraction persists", "icon": "layers", "ring": MUTED, "glyph": MUTED},
            {"label": "SINE-2", "caption": "Amber escalation: stronger intervention", "icon": "bell", "fill": AMBER_BG, "ring": AMBER, "glyph": AMBER, "label_color": AMBER},
            {"label": "CONTINUED OFF-TASK", "caption": "Still off-task after escalation", "icon": "layers", "ring": MUTED, "glyph": MUTED},
            {"label": "SINE-3", "caption": "Protected red, no buttons", "icon": "bell", "fill": RED_BG, "ring": RED, "glyph": RED, "label_color": RED},
            {"label": "RETURN INTENT + EVIDENCE", "caption": "Sustained on-task activity", "icon": "chart", "ring": CYAN, "glyph": NAVY},
            {"label": "MIRL RECOVERY PATHWAY", "caption": "Verification and return", "icon": "gear", "ring": CYAN, "glyph": NAVY},
        ],
        figure_num=2, figure_caption="SINE workflow",
        figure_note="SINE is an escalation organ: intervention intensity increases as off-task exposure "
                    "persists. The green Normal Break welcome-back screen is not an additional SINE stage.",
        workflow_box_h=27 * mm,
    )
    y -= 4 * mm
    _rule(c, MARGIN, y, PAGE_WIDTH - MARGIN, LINE, 0.5)
    y -= 6 * mm

    y = _organ_block(
        c, y, icon="chat", name="MINE", subtitle="MESSAGING INTERVENTION NUDGE ESCALATION",
        body=fx.mine_body,
        core_purpose="regulates persistent messaging behaviour through branch-based escalation.",
        distinctive_features="MINE-1 presents two options; both later converge to a final no-button "
                              "callback; MINE owns its own recovery sequence.",
        workflow_boxes=[
            {"label": "QUALIFYING MESSAGING", "caption": "Sustained conversation activity", "icon": "chat", "ring": MUTED, "glyph": MUTED},
            {"label": "10:00 THRESHOLD", "caption": "Qualifying behaviour persists", "icon": "clock", "ring": MUTED, "glyph": MUTED},
            {"label": "MINE-1 POPUP", "caption": "Two options presented", "icon": "chat", "fill": PALE_CYAN, "ring": CYAN},
            {"branch": [
                {"label": "I WILL COME BACK", "caption": "13:15 timer starts", "icon": "route", "ring": GREEN, "glyph": GREEN},
                {"label": "IT'S IMPORTANT", "caption": "5-30 min window", "icon": "route", "ring": GREEN, "glyph": GREEN},
            ]},
            {"label": "MINE-2A / MINE-2B", "caption": "Final callback, no buttons", "icon": "chat", "fill": RED_BG, "ring": RED, "glyph": RED},
            {"label": "RETURN / OWN RECOVERY", "caption": "MINE verification and return", "icon": "refresh", "ring": CYAN, "glyph": NAVY},
        ],
        figure_num=3, figure_caption="MINE workflow",
        figure_note="Messaging-app switches remain within the same episode; neutral detours pause the "
                    "post-MINE-1 timer rather than reset it.",
        workflow_box_h=27 * mm,
    )
    _footer(c, caption="", page_label=_page_label(fx, 3))


# ---------------------------------------------------------------------------
# SP3 -- COSINE and COSECANT
# ---------------------------------------------------------------------------

def _page_sp3(c, fx) -> None:
    top, _ = _page_frame(c, page_code="SP3", chapter_label="SP3  |  Chapter 2 Context-Specific Regulation Organs")
    y = _chapter_title(c, top, "2", "OTT REGULATION: COSINE")
    y = _callout(c, y, fx.sp3_intro)

    y = _organ_block(
        c, y, icon="play", name="COSINE", subtitle="CHOICE-ORIENTED STREAMING INSIGHT AND NAVIGATION ENGINE",
        body=fx.cosine_body,
        core_purpose="regulates OTT and video diversion through intention-aware guidance.",
        distinctive_features="Separates return intention from intentional leisure viewing; both "
                              "pathways eventually converge to a callback and return route.",
        workflow_boxes=[
            {"label": "OTT DETECTED", "caption": "Start of an OTT episode", "icon": "play", "ring": PURPLE, "glyph": PURPLE},
            {"label": "5:00 THRESHOLD", "caption": "Episode confirmed after 5 minutes of viewing", "icon": "clock", "ring": MUTED, "glyph": MUTED},
            {"label": "COSINE INTENTION CHECK", "caption": "User indicates whether they intend to come back", "icon": "chat", "ring": CYAN, "glyph": NAVY},
            {"branch": [
                {"label": "RETURN WINDOW", "caption": "5:00 return window", "icon": "route", "ring": GREEN, "glyph": GREEN},
                {"label": "CHOSEN WATCH PERIOD", "caption": "10-200 min period", "icon": "route", "ring": GREEN, "glyph": GREEN},
            ]},
            {"label": "END-OF-BREAK CALLBACK", "caption": "Buttonless final guidance", "icon": "bell", "ring": RED, "glyph": RED, "fill": RED_BG},
            {"label": "RETURN / CLOSURE PATHWAY", "caption": "Return from OTT confirmed; episode resolution", "icon": "undo", "ring": CYAN, "glyph": NAVY},
        ],
        figure_num=4, figure_caption="COSINE workflow",
        figure_note="OTT platform switches remain inside the same COSINE episode. The current production "
                    "pathway does not use the older '10 more min' / 'finish my show' model.",
        workflow_box_h=27 * mm,
    )
    y -= 4 * mm
    _rule(c, MARGIN, y, PAGE_WIDTH - MARGIN, LINE, 0.5)
    y -= 6 * mm

    _footer(c, caption="", page_label=_page_label(fx, 4))


def _page_study_organs(c, fx):
    top, _ = _page_frame(c, page_code="STUDY_ORGANS", chapter_label="Chapter 2 Study regulation")
    y = _chapter_title(c, top, "2", "STUDY REGULATION: SECANT AND COSECANT")
    y = _callout(c, y, "SECANT describes Study off-task regulation and recovery. COSECANT is the approved-break "
                 "branch in this conceptual architecture, with independent runtime authority.")
    y = _organ_block(c, y, icon="book", name="SECANT", subtitle="STUDY OFF-TASK AND RECOVERY REGULATION",
        body="Confirmed Study off-task evidence supports 5:00 dwell. The episode begins only on factual SECANT-1 display. "
             "Continued qualifying off-task behaviour can escalate the same episode to SECANT-2, then SECANT-3.",
        core_purpose="Regulates confirmed Study off-task behaviour and independently verifies Study return.",
        distinctive_features="Return may start at any applicable stage. A button press is intent, not proof. "
                             "Approved COSECANT breaks are not ordinary SECANT escalation.",
        workflow_boxes=[
            {"label": "STUDY OFF-TASK", "caption": "5:00 supported dwell", "icon": "book"},
            {"label": "SECANT-1", "caption": "Factual display founds episode", "icon": "bell"},
            {"label": "SECANT-2", "caption": "+10:00 qualifying off-task", "icon": "clock"},
            {"label": "SECANT-3", "caption": "+13:15 eligible escalation", "icon": "lock"},
        ], figure_num=5, figure_caption="SECANT escalation and return branches",
        figure_note="Return from any applicable stage: return process -> 10s supported verification -> 60s confirmation -> recovery closure. "
                    "Interrupted attempts retain evidence_gap / return_away reasons. Not every episode reaches stage 3 or recovers.",
        workflow_box_h=23 * mm)
    y -= 5 * mm
    y = _organ_block(
        c, y, icon="cap", name="COSECANT", subtitle="CONTEXT-ORIENTED STUDY ESCALATION, CONFIRMATION AND NAVIGATION TOOL",
        body=fx.cosecant_body,
        core_purpose="protects return-to-study continuity after an approved break.",
        distinctive_features="Works from a finite break allowance; uses break-complete to +5 min to "
                              "+1 min escalation; requires exact-resource confirmation rather than "
                              "intention alone.",
        workflow_boxes=[
            {"label": "STUDY CONTEXT ACTIVE", "caption": "Time + keywords / task resource", "icon": "book", "ring": MUTED, "glyph": MUTED},
            {"label": "APPROVED STUDY BREAK", "caption": "Break is started and tracked", "icon": "cup", "ring": MUTED, "glyph": MUTED},
            {"label": "BREAK COMPLETE", "caption": "Planned break duration ends", "icon": "check", "ring": CYAN, "glyph": NAVY},
            {"label": "+5 MIN REMINDER", "caption": "First reminder notification", "icon": "clock", "ring": AMBER, "glyph": AMBER, "fill": AMBER_BG, "label_color": AMBER},
            {"label": "+1 MIN FINAL LOCK", "caption": "Final escalation if still away", "icon": "lock", "ring": RED, "glyph": RED, "fill": RED_BG, "label_color": RED},
            {"label": "EXACT RESOURCE CONFIRMATION", "caption": "3 continuous seconds", "icon": "doc", "ring": CYAN, "glyph": NAVY},
            {"label": "STUDY RESUMED", "caption": "User continues studying", "icon": "chart", "ring": CYAN, "glyph": NAVY},
        ],
        figure_num=6, figure_caption="COSECANT workflow",
        figure_note="SECANT governs confirmed Study off-task recovery. COSECANT independently governs "
                    "approved breaks and the "
                    "countdown back to study continuity.",
        workflow_box_h=27 * mm,
    )
    _footer(c, caption="", page_label=_page_label(fx, 4))


def _metric_card(c, x, y, w, h, item) -> None:
    _card(c, x, y, w, h, fill=WHITE, stroke=LINE)
    _icon_circle(c, x + 5.5 * mm, y - 5.5 * mm, 3.8 * mm, item["icon"], ring=item.get("ring", CYAN))
    _paragraph(c, item["label"], x + 10.5 * mm, y - 3.6 * mm, w - 13 * mm, 7 * mm, size=7.4, leading=8.6, color=NAVY, bold=True)
    _paragraph(c, item["body"], x + 3 * mm, y - 11 * mm, w - 6 * mm, h - 12 * mm, size=6.7, leading=8.1, color=MUTED)


def _small_source_card(c, x, y, w, h, item) -> None:
    """ICON, then a clear gap, then a bounded centered TITLE (wraps to two
    lines rather than crossing the card width or touching the icon), then
    another clear gap, then BODY (Chief's Bug J/K/L small-card fix: same
    renderer, same card bounds/grid, no change to _icon_circle() itself --
    only this card's internal vertical stacking)."""

    _card(c, x, y, w, h, fill=WHITE, stroke=LINE)
    compact = h < 25 * mm
    icon_r = 3.4 * mm if compact else 3.8 * mm
    icon_cy = y - (4.8 * mm if compact else 5.6 * mm)
    _icon_circle(c, x + w / 2, icon_cy, icon_r, item["icon"], ring=item.get("ring", CYAN))

    title_size = 6.6 if compact else 7.6
    title_leading = title_size + 1.6
    title_top = icon_cy - icon_r - (1.6 * mm if compact else 2.0 * mm)
    title_max_h = 8 * mm if compact else 9.5 * mm
    title_bottom = _paragraph(
        c, item["label"], x + 2 * mm, title_top, w - 4 * mm, title_max_h,
        size=title_size, leading=title_leading, color=NAVY, bold=True, align="center",
    )
    body_top = title_bottom - (1.2 * mm if compact else 1.6 * mm)
    body_bottom_limit = y - h + (1.0 * mm if compact else 1.4 * mm)
    body_h = max(3 * mm, body_top - body_bottom_limit)
    body_size = 5.6 if compact else 6.0
    _paragraph(c, item["body"], x + 2 * mm, body_top, w - 4 * mm, body_h,
               size=body_size, leading=body_size + 1.2, color=MUTED, align="center")


# ---------------------------------------------------------------------------
# SP4 -- What Data MYELIN Actually Collects
# ---------------------------------------------------------------------------

def _page_sp4(c, fx) -> None:
    top, _ = _page_frame(c, page_code="SP4", chapter_label="SP4  |  Chapter 3 Data Analysis")
    y = _chapter_title(c, top, "3", "WHAT DATA MYELIN ACTUALLY COLLECTS")
    y = _callout(c, y, fx.sp4_intro)

    y = _section_head(c, MARGIN, y, "doc", "HOW MYELIN COLLECTS DATA", fx.how_collects, CONTENT_WIDTH, body_size=8.2, body_height=18 * mm)
    y -= 4 * mm

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "gear")
    _text(c, "KEY BEHAVIOURAL METRICS", MARGIN + 10 * mm, y - 2 * mm, 11, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.metrics_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 10 * mm, size=7.6, leading=9, color=INK) - 2.5 * mm

    metrics = [
        {"label": "Task-aligned time", "icon": "target", "ring": MUTED,
         "body": "Time spent on the intended task. Not yet available in the current report."},
        {"label": "Off-task dwell", "icon": "route", "ring": MUTED,
         "body": "Time spent away from the intended task. Not yet available in the current report."},
        {"label": "Return latency", "icon": "refresh", "ring": CYAN,
         "body": "How long it takes to come back after drift. Reported when certified MIRL evidence exists."},
        {"label": "Verified returns", "icon": "check", "ring": CYAN,
         "body": "Confirmed returns supported by evidence. Reported when certified MIRL evidence exists."},
        {"label": "Relapses", "icon": "undo", "ring": CYAN,
         "body": "Returns that were followed by drifting away again. Reported when certified MIRL evidence exists."},
        {"label": "Post-return persistence", "icon": "chart", "ring": MUTED,
         "body": "How long on-task behaviour continues after return. Not yet available in the current report."},
        {"label": "Context switches", "icon": "refresh", "ring": MUTED,
         "body": "How often the user changes between task contexts. Not yet available in the current report."},
        {"label": "Experiment duration", "icon": "clock", "ring": CYAN,
         "body": "The total measured time for the selected experiment or session. Always available once an experiment is selected."},
    ]
    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, metrics, columns=4, card_h=24 * mm, render_cell=_metric_card) - 3 * mm

    left_x, right_x, col_w = _two_col(MARGIN, CONTENT_WIDTH)
    ly = _section_head(c, left_x, y, "doc", "LIVE EVIDENCE FEED", fx.live_feed_intro, col_w, body_size=7.4)
    _rrect(c, left_x, ly - 15 * mm, col_w, 15 * mm, 1.6 * mm, fill=PALE_BLUE)
    c.setFillColor(NAVY); c.rect(left_x, ly - 15 * mm, 1.1 * mm, 15 * mm, fill=1, stroke=0)
    _paragraph(c, fx.live_feed_examples, left_x + 4.5 * mm, ly - 3 * mm, col_w - 8 * mm, 11 * mm, size=6.8, leading=8.2, color=INK)

    ry = _section_head(c, right_x, y, "list", "DERIVED FINDINGS", fx.derived_findings_intro, col_w, body_size=7.4)
    _rrect(c, right_x, ry - 15 * mm, col_w, 15 * mm, 1.6 * mm, fill=PALE_BLUE)
    c.setFillColor(NAVY); c.rect(right_x, ry - 15 * mm, 1.1 * mm, 15 * mm, fill=1, stroke=0)
    _paragraph(c, fx.derived_findings_examples, right_x + 4.5 * mm, ry - 3 * mm, col_w - 8 * mm, 11 * mm, size=6.8, leading=8.2, color=INK)
    y = min(ly, ry) - 20 * mm

    left_x, right_x, col_w = MARGIN, MARGIN + CONTENT_WIDTH * 0.62 + 4 * mm, CONTENT_WIDTH * 0.62
    _icon_circle(c, left_x + 4 * mm, y - 4 * mm, 4 * mm, "flow")
    _text(c, "SOURCE COVERAGE", left_x + 10 * mm, y - 2 * mm, 10.5, CYAN, bold=True, spacing=0.3)
    y2 = _paragraph(c, fx.source_coverage_intro, left_x, y - 7.5 * mm, CONTENT_WIDTH, 8 * mm, size=7.2, leading=8.6, color=INK) - 2 * mm
    sources = [
        {"label": "SINE", "icon": "bell", "body": "Intervention evidence"},
        {"label": "MINE", "icon": "chat", "body": "Messaging evidence"},
        {"label": "COSINE", "icon": "play", "body": "OTT evidence"},
        {"label": "MIRL", "icon": "refresh", "body": "SINE recovery evidence"},
        {"label": "SECANT", "icon": "book", "body": "Study off-task / recovery evidence"},
        {"label": "COSECANT", "icon": "cap", "body": "Study-break return evidence"},
        {"label": "RESOURCE INTENT", "icon": "doc", "body": "Task-context evidence"},
        {"label": "STUDY", "icon": "people", "body": "Study-context evidence"},
        {"label": "NORMAL BREAK", "icon": "cup", "body": "Break evidence"},
    ]
    source_bottom = _grid_cards(c, left_x, y2, CONTENT_WIDTH, sources, columns=5, card_h=21 * mm,
                                render_cell=_small_source_card)
    _paragraph(c, "IMPORTANT BOUNDARY: " + fx.important_boundary, MARGIN, source_bottom - 3 * mm,
               CONTENT_WIDTH, 13 * mm, size=7.2, leading=9, color=INK)

    _footer(c, caption=fx.sp4_footer, page_label=_page_label(fx, 5))


# ---------------------------------------------------------------------------
# SP5 -- How MYELIN Uses the Collected Data
# ---------------------------------------------------------------------------

def _page_sp5(c, fx) -> None:
    top, _ = _page_frame(c, page_code="SP5", chapter_label="SP5  |  Chapter 3 Data Analysis")
    y = _chapter_title(c, top, "3", "HOW MYELIN USES THE COLLECTED DATA")
    y = _callout(c, y, fx.sp5_intro)

    y = _section_head(c, MARGIN, y, "doc", "FROM EVIDENCE TO INTERPRETATION", fx.evidence_to_interpretation,
                       CONTENT_WIDTH, body_size=8.0, body_height=18 * mm)
    y -= 3 * mm

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "gear")
    _text(c, "WHAT THE EVIDENCE CAN SHOW", MARGIN + 10 * mm, y - 2 * mm, 11, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.what_evidence_shows, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 10 * mm, size=7.6, leading=9, color=INK) - 2.5 * mm

    shows = [
        {"label": "Return latency", "icon": "refresh", "body": "How quickly a user comes back after drift or an interruption."},
        {"label": "Platforms involved", "icon": "layers", "body": "Which apps, sites, or organ pathways were involved in drift and return."},
        {"label": "User reaction", "icon": "person", "body": "What option the user chose or how they responded to an intervention pathway."},
        {"label": "HCI impact", "icon": "laptop", "body": "How the evidence can help evaluate prompt timing, burden, escalation, and design effectiveness."},
        {"label": "Neuroscience prediction", "icon": "brain", "body": "May suggest behavioural hypotheses about re-engagement or difficulty of return, but this is a prediction from behaviour, not a direct brain measurement."},
    ]
    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, shows, columns=5, card_h=36 * mm, render_cell=_metric_card) - 2 * mm

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "flow")
    _text(c, "FROM SESSION EVIDENCE TO FINDINGS", MARGIN + 10 * mm, y - 2 * mm, 11, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.session_to_findings, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 10 * mm, size=7.6, leading=9, color=INK) - 2.5 * mm

    steps = [
        {"label": "EVIDENCE EVENTS", "caption": "Off-task activity, Verified return, Relapse", "icon": "doc"},
        {"label": "METRICS", "caption": "Durations, Counts, Frequencies", "icon": "chart"},
        {"label": "PATTERNS", "caption": "Organ and platform trends, Common sequences", "icon": "layers"},
        {"label": "INTERPRETATION", "caption": "HCI insight, Behavioural explanation, Research questions", "icon": "check"},
    ]
    y = _workflow_chain(c, MARGIN, y, CONTENT_WIDTH, steps, box_h=22 * mm, gap=6 * mm) - 4 * mm

    left_x, right_x, col_w = _two_col(MARGIN, CONTENT_WIDTH)
    ly = _section_head(c, left_x, y, "chart", "WHOLE-MYELIN ANALYSIS", "", col_w, body_size=7.4, body_height=1 * mm)
    lb = _rrect(c, left_x, ly - 24 * mm, col_w, 24 * mm, 1.6 * mm, fill=PALE_BLUE)
    c.setFillColor(NAVY); c.rect(left_x, ly - 24 * mm, 1.1 * mm, 24 * mm, fill=1, stroke=0)
    _paragraph(c, fx.whole_myelin_analysis, left_x + 4.5 * mm, ly - 3 * mm, col_w - 8 * mm, 20 * mm, size=7.0, leading=8.6, color=INK)

    ry = _section_head(c, right_x, y, "info", "LIMITATIONS AND CAUTION", fx.limitations_caution_intro, col_w, body_size=6.8, body_height=6 * mm)
    _rrect(c, right_x, ry - 18 * mm, col_w, 18 * mm, 1.6 * mm, fill=PALE_BLUE)
    c.setFillColor(NAVY); c.rect(right_x, ry - 18 * mm, 1.1 * mm, 18 * mm, fill=1, stroke=0)
    _paragraph(c, fx.limitations_caution_body, right_x + 4.5 * mm, ry - 3 * mm, col_w - 8 * mm, 14 * mm, size=6.8, leading=8.2, color=INK)
    y = min(ly - 24 * mm, ry - 18 * mm) - 6 * mm

    _footer(c, caption=fx.sp5_footer, page_label=_page_label(fx, 6))


# ---------------------------------------------------------------------------
# Results-page components shared by SP6-SP10 (Phase 3 DEV FIXTURES ONLY --
# every numeric/status value these pages show comes from the caller's
# fixture object, never a literal inside these drawing functions).
# ---------------------------------------------------------------------------

def _status_pill(c, x, y, w, text, *, bg, fg) -> None:
    _rrect(c, x, y, w, 6 * mm, 3 * mm, fill=bg)
    _text(c, text, x + w / 2, y + 1.9 * mm, 6.6, fg, bold=True, align="center")


def _snapshot_card(c, x, y, w, h, item) -> None:
    _card(c, x, y, w, h, fill=WHITE, stroke=LINE)
    if item.get("icon"):
        _icon_circle(c, x + 5 * mm, y - 5 * mm, 3.6 * mm, item["icon"])
        label_x = x + 10 * mm
    else:
        label_x = x + 3 * mm
    _paragraph(c, item["label"], label_x, y - 3.2 * mm, w - (label_x - x) - 2 * mm, 8 * mm,
               size=7.0, leading=8.2, color=NAVY, bold=True)
    value_bottom = _paragraph(c, item["value"], x + 3 * mm, y - 12.5 * mm, w - 6 * mm, 9 * mm,
               size=8.6, leading=10, color=item.get("value_color", MUTED), bold=True)
    caption_top = value_bottom - 1.2 * mm
    caption_height = max(6 * mm, caption_top - (y - h) - 2 * mm)
    _paragraph(c, item["caption"], x + 3 * mm, caption_top, w - 6 * mm, caption_height,
               size=6.0, leading=7.2, color=MUTED)


def _measure_paragraph_height(text: str, width: float, *, size: float, leading: float, bold: bool = False) -> float:
    style = ParagraphStyle(
        f"MyelinMeasure{secrets.token_hex(4)}", fontName="Helvetica-Bold" if bold else "Helvetica",
        fontSize=size, leading=leading, textColor=INK,
    )
    _, used = Paragraph(html.escape(_pdf_text(text)), style).wrap(width, 500 * mm)
    return used


def _bullet_list(c, x, y, width, items, *, size=6.6, leading=8.0, gap=1.4 * mm) -> float:
    for line in items:
        c.setFillColor(CYAN)
        c.circle(x + 1 * mm, y - size * 0.38, 0.55 * mm, fill=1, stroke=0)
        needed = _measure_paragraph_height(line, width - 3.2 * mm, size=size, leading=leading) + 1 * mm
        y = _paragraph(c, line, x + 3.2 * mm, y, width - 3.2 * mm, needed, size=size, leading=leading, color=INK) - gap
    return y


def _organ_availability_card(c, x, y, w, h, item) -> None:
    _card(c, x, y, w, h, fill=WHITE, stroke=LINE)
    _text(c, item["organ"], x + 4 * mm, y - 5.5 * mm, 9, NAVY, bold=True)
    _bullet_list(c, x + 4 * mm, y - 11 * mm, w - 8 * mm, item["items"], size=6.2, leading=7.4, gap=1 * mm)


# ---------------------------------------------------------------------------
# SP6 -- Results and Discussion Overview
# ---------------------------------------------------------------------------

def _page_sp6(c, fx) -> None:
    top, _ = _page_frame(c, page_code="SP6", chapter_label="SP6  |  Chapter 4 Results and Discussion")
    y = _chapter_title(c, top, "4", "RESULTS AND DISCUSSION OVERVIEW")
    y = _callout(c, y, fx.sp6_intro)

    y = _section_head(c, MARGIN, y, "doc", "HOW THIS CHAPTER IS ORGANISED", fx.how_organised, CONTENT_WIDTH,
                       body_size=8.0, body_height=13 * mm)
    y -= 3 * mm
    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "chart")
    _text(c, "OVERALL EXPERIMENT | ORGAN AVAILABILITY", MARGIN + 10 * mm, y - 2 * mm, 11, CYAN, bold=True)
    y = _paragraph(c, fx.session_level_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 10 * mm, size=7.6, leading=9, color=INK) - 3 * mm

    def _overview_card(c, x, y, w, h, item):
        _card(c, x, y, w, h, fill=WHITE, stroke=LINE)
        c.setFillColor(item["dot"])
        c.circle(x + w / 2, y - 6 * mm, 2.6 * mm, fill=1, stroke=0)
        _text(c, item["organ"], x + w / 2, y - 12.5 * mm, 9, NAVY, bold=True, align="center")
        _status_pill(c, x + w / 2 - 15 * mm, y - 20 * mm, 30 * mm, item["status"], bg=item["status_bg"], fg=item["status_fg"])
        _paragraph(c, item["caption"], x + 2.5 * mm, y - 24 * mm, w - 5 * mm, h - 25 * mm, size=6.0, leading=7.2, color=MUTED, align="center")

    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, [item for item in fx.organ_overview_cards if item["organ"] != "OVERALL EXPERIMENT"], columns=5, card_h=38 * mm, render_cell=_overview_card) - 2 * mm

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "list")
    _text(c, "AVAILABLE RESULT TYPES", MARGIN + 10 * mm, y - 2 * mm, 11, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.available_result_types_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 10 * mm, size=7.6, leading=9, color=INK) - 2.5 * mm
    result_types = [
        {"label": "Behavioural journey map", "icon": "route", "body": "Chronological view of user behaviour."},
        {"label": "Episode tables", "icon": "doc", "body": "List of episodes with key details."},
        {"label": "Stage / escalation tables", "icon": "chart", "body": "Progression through stages and levels."},
        {"label": "Recovery attempts", "icon": "growth", "body": "Verified return, interruptions and closure."},
        {"label": "Break timing analysis", "icon": "clock", "body": "Timing and duration of breaks."},
        {"label": "Unavailable data flag", "icon": "warn", "body": 'Shown when evidence cannot support a value; never means unused.'},
    ]
    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, result_types, columns=6, card_h=30 * mm, render_cell=_small_source_card) - 2 * mm

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "gear")
    _text(c, "WHAT APPEARS ON EACH ORGAN PAGE", MARGIN + 10 * mm, y - 2 * mm, 11, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.what_appears_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 10 * mm, size=7.6, leading=9, color=INK) - 2.5 * mm
    organ_pages = [
        {"organ": "SINE", "items": ["Behavioural journey map", "MIRL table", "SINE stage table", "Trend graph"]},
        {"organ": "MINE", "items": ["Messaging pathway", "Response options", "Episode table", "Trend graph"]},
        {"organ": "COSINE", "items": ["OTT pathway", "Break/watch decisions", "Callback summary", "Trend graph"]},
        {"organ": "SECANT", "items": ["Study recovery", "Stage chronology", "Return attempts", "Interruptions / closure"]},
        {"organ": "COSECANT", "items": ["Study-break route", "Reminder / final-lock levels", "Break timing table", "Return latency"]},
    ]
    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, organ_pages, columns=5, card_h=32 * mm, render_cell=_organ_availability_card) - 2 * mm

    y = _callout(c, y, fx.important_reading_rule)
    y = _callout(c, y, fx.mixed_membership_scope_note, size=7.6)
    _footer(c, caption=fx.sp6_footer, page_label=_page_label(fx, 7))


# ---------------------------------------------------------------------------
# Shared organ-results page shell (SP7-SP10).  All values arrive via fx --
# nothing numeric is a literal in this function.
# ---------------------------------------------------------------------------

def _results_page_header(c, *, page_code, chapter_label, chapter_num, chapter_title, intro) -> float:
    top, _ = _page_frame(c, page_code=page_code, chapter_label=chapter_label)
    y = _chapter_title(c, top, chapter_num, chapter_title)
    return _callout(c, y, intro)


def _table_block(c, y, *, number, title, desc, rows, widths_mm, row_h=7.6 * mm) -> float:
    _icon_circle(c, MARGIN + 3.6 * mm, y - 3.6 * mm, 3.6 * mm, "doc")
    _text(c, f"TABLE {number}  |  {title}", MARGIN + 9 * mm, y - 1.8 * mm, 8.6, NAVY, bold=True)
    y = _paragraph(c, desc, MARGIN, y - 6.8 * mm, CONTENT_WIDTH_HALF, 8 * mm, size=6.4, leading=7.6, color=MUTED) - 1.5 * mm
    y = _table(c, MARGIN, y, widths_mm, rows, row_h=row_h)
    return y


CONTENT_WIDTH_HALF: Final = (CONTENT_WIDTH - 6 * mm) / 2


def _page_sp7(c, fx) -> None:
    y = _results_page_header(c, page_code="SP7", chapter_label="SP7  |  Chapter 4 Results and Discussion",
                              chapter_num="4", chapter_title="SINE RESULTS AND DISCUSSION", intro=fx.intro)

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "chart")
    _text(c, "SINE SESSION SNAPSHOT", MARGIN + 10 * mm, y - 2 * mm, 10.5, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.snapshot_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 10 * mm, size=7.2, leading=8.6, color=INK) - 2 * mm
    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, fx.snapshot_cards, columns=5, card_h=28 * mm, render_cell=_snapshot_card) - 2 * mm

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "route")
    _text(c, "BEHAVIOURAL JOURNEY MAP", MARGIN + 10 * mm, y - 2 * mm, 10.5, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.journey_map_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 8 * mm, size=7.2, leading=8.6, color=INK) - 2 * mm
    y = _workflow_chain(c, MARGIN, y, CONTENT_WIDTH, fx.journey_boxes, box_h=22 * mm, gap=2.8 * mm) - 4 * mm

    left_x, right_x, col_w = _two_col(MARGIN, CONTENT_WIDTH)
    ly = _table_block(c, y, number=1, title=fx.table1_title, desc=fx.table1_desc, rows=fx.table1_rows, widths_mm=fx.table1_widths)
    saved_ly = ly
    ry_y = y
    _icon_circle(c, right_x + 3.6 * mm, ry_y - 3.6 * mm, 3.6 * mm, "doc")
    _text(c, f"TABLE 2  |  {fx.table2_title}", right_x + 9 * mm, ry_y - 1.8 * mm, 8.6, NAVY, bold=True)
    ry = _paragraph(c, fx.table2_desc, right_x, ry_y - 6.8 * mm, col_w, 8 * mm, size=6.4, leading=7.6, color=MUTED) - 1.5 * mm
    ry = _table(c, right_x, ry, fx.table2_widths, fx.table2_rows, row_h=7.6 * mm)
    y = min(ly, ry) - 5 * mm

    if fx.chart_available:
        _line_chart(c, MARGIN, y, col_w + 3 * mm, 42 * mm, categories=fx.chart_categories,
                    series=fx.chart_series, y_labels=fx.chart_y_labels)
    else:
        _empty_chart(c, MARGIN, y, col_w + 3 * mm, 42 * mm, message=fx.chart_unavailable_message)
    _text(c, getattr(fx, "chart_title", "SINE TREND GRAPH"), MARGIN, y + 1.5 * mm, 7.6, CYAN_DARK, bold=True)

    box_h = 42 * mm
    _rrect(c, right_x, y - box_h, col_w, box_h, 2 * mm, fill=PALE_BLUE)
    _icon_circle(c, right_x + 5 * mm, y - 5 * mm, 3.4 * mm, "info")
    _text(c, "DISCUSSION NOTE", right_x + 10 * mm, y - 4 * mm, 8, NAVY, bold=True)
    _paragraph(c, fx.discussion_note, right_x + 4.5 * mm, y - 10 * mm, col_w - 9 * mm, box_h - 12 * mm,
               size=6.6, leading=8, color=INK)
    y -= box_h + 4 * mm

    _footer(c, caption=fx.footer, page_label=_page_label(fx, 8))


def _page_sp8(c, fx) -> None:
    y = _results_page_header(c, page_code="SP8", chapter_label="SP8  |  Chapter 4 Results and Discussion",
                              chapter_num="4", chapter_title="MINE RESULTS AND DISCUSSION", intro=fx.intro)

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "chart")
    _text(c, "MINE SESSION SNAPSHOT", MARGIN + 10 * mm, y - 2 * mm, 10.5, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.snapshot_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 10 * mm, size=7.2, leading=8.6, color=INK) - 2 * mm
    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, fx.snapshot_cards, columns=5, card_h=28 * mm, render_cell=_snapshot_card) - 2 * mm

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "route")
    _text(c, "MESSAGING PATHWAY MAP", MARGIN + 10 * mm, y - 2 * mm, 10.5, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.pathway_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 8 * mm, size=7.2, leading=8.6, color=INK) - 2 * mm
    y = _workflow_chain(c, MARGIN, y, CONTENT_WIDTH, fx.pathway_boxes, box_h=24 * mm, gap=3.5 * mm) - 4 * mm

    left_x, right_x, col_w = _two_col(MARGIN, CONTENT_WIDTH)
    ly = _table_block(c, y, number=1, title=fx.table1_title, desc=fx.table1_desc, rows=fx.table1_rows, widths_mm=fx.table1_widths)
    _icon_circle(c, right_x + 3.6 * mm, y - 3.6 * mm, 3.6 * mm, "doc")
    _text(c, f"TABLE 2  |  {fx.table2_title}", right_x + 9 * mm, y - 1.8 * mm, 8.6, NAVY, bold=True)
    ry = _paragraph(c, fx.table2_desc, right_x, y - 6.8 * mm, col_w, 8 * mm, size=6.4, leading=7.6, color=MUTED) - 1.5 * mm
    ry = _table(c, right_x, ry, fx.table2_widths, fx.table2_rows, row_h=7.6 * mm)
    y = min(ly, ry) - 5 * mm

    _text(c, getattr(fx, "chart_title", "MINE TREND GRAPH"), MARGIN, y + 1.5 * mm, 7.6, CYAN_DARK, bold=True)
    if fx.chart_available:
        y = _bar_chart(c, MARGIN, y, CONTENT_WIDTH, 42 * mm, categories=fx.chart_categories, values=fx.chart_values,
                        y_max=fx.chart_y_max, unit=fx.chart_unit, bars_color=CYAN, extra_series=fx.chart_extra_series) - 5 * mm
    else:
        y = _empty_chart(c, MARGIN, y, CONTENT_WIDTH, 42 * mm, message=fx.chart_unavailable_message) - 5 * mm

    box_h = 16 * mm
    _rrect(c, MARGIN, y - box_h, CONTENT_WIDTH, box_h, 2 * mm, fill=PALE_BLUE)
    _icon_circle(c, MARGIN + 5 * mm, y - 5 * mm, 3.4 * mm, "info")
    _text(c, "DISCUSSION NOTE", MARGIN + 10.5 * mm, y - 4 * mm, 8, NAVY, bold=True)
    _paragraph(c, fx.discussion_note, MARGIN + 4.5 * mm, y - 9.5 * mm, CONTENT_WIDTH - 9 * mm, box_h - 10 * mm,
               size=6.8, leading=8.2, color=INK)

    _footer(c, caption=fx.footer, page_label=_page_label(fx, 9))


def _page_sp9(c, fx) -> None:
    y = _results_page_header(c, page_code="SP9", chapter_label="SP9  |  Chapter 4 Results and Discussion",
                              chapter_num="4", chapter_title="COSINE RESULTS AND DISCUSSION", intro=fx.intro)

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "doc")
    _text(c, "COSINE SESSION SNAPSHOT", MARGIN + 10 * mm, y - 2 * mm, 10.5, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.snapshot_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 10 * mm, size=7.2, leading=8.6, color=INK) - 2 * mm
    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, fx.snapshot_cards, columns=5, card_h=28 * mm, render_cell=_snapshot_card) - 2 * mm

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "route")
    _text(c, "OTT BEHAVIOURAL PATHWAY", MARGIN + 10 * mm, y - 2 * mm, 10.5, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.pathway_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 8 * mm, size=7.2, leading=8.6, color=INK) - 2 * mm
    y = _workflow_chain(c, MARGIN, y, CONTENT_WIDTH, fx.pathway_boxes, box_h=24 * mm, gap=3.5 * mm) - 4 * mm

    left_x, right_x, col_w = _two_col(MARGIN, CONTENT_WIDTH)
    ly = _table_block(c, y, number=1, title=fx.table1_title, desc=fx.table1_desc, rows=fx.table1_rows, widths_mm=fx.table1_widths)
    _icon_circle(c, right_x + 3.6 * mm, y - 3.6 * mm, 3.6 * mm, "doc")
    _text(c, f"TABLE 2  |  {fx.table2_title}", right_x + 9 * mm, y - 1.8 * mm, 8.6, NAVY, bold=True)
    ry = _paragraph(c, fx.table2_desc, right_x, y - 6.8 * mm, col_w, 8 * mm, size=6.4, leading=7.6, color=MUTED) - 1.5 * mm
    ry = _table(c, right_x, ry, fx.table2_widths, fx.table2_rows, row_h=7.6 * mm)
    y = min(ly, ry) - 5 * mm

    if fx.chart_available:
        ly2 = _bar_chart(c, MARGIN, y, col_w + 3 * mm, 42 * mm, categories=fx.chart_categories, values=fx.chart_values,
                          y_max=fx.chart_y_max, unit=fx.chart_unit, bars_color=CYAN)
    else:
        ly2 = _empty_chart(c, MARGIN, y, col_w + 3 * mm, 42 * mm,
                            message=fx.chart_unavailable_message)
    _text(c, getattr(fx, "chart_title", "COSINE TREND GRAPH"), MARGIN, y + 1.5 * mm, 7.6, CYAN_DARK, bold=True)

    box_h = 42 * mm
    _rrect(c, right_x, y - box_h, col_w, box_h, 2 * mm, fill=PALE_BLUE)
    _icon_circle(c, right_x + 5 * mm, y - 5 * mm, 3.4 * mm, "info")
    _text(c, "DISCUSSION NOTE", right_x + 10 * mm, y - 4 * mm, 8, NAVY, bold=True)
    _paragraph(c, fx.discussion_note, right_x + 4.5 * mm, y - 10 * mm, col_w - 9 * mm, box_h - 12 * mm,
               size=6.6, leading=8, color=INK)
    y -= box_h + 4 * mm

    _footer(c, caption=fx.footer, page_label=_page_label(fx, 10))


def _page_secant(c, fx):
    y = _results_page_header(c, page_code="SECANT_RESULTS", chapter_label="Chapter 4 Results and Discussion",
                            chapter_num="4", chapter_title="SECANT RESULTS AND DISCUSSION", intro=fx.intro)
    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, fx.snapshot_cards, columns=5, card_h=30 * mm,
                    render_cell=_snapshot_card) - 7 * mm
    y = _callout(c, y, fx.discussion_note, size=8)
    y = _table_block(c, y, number=1, title=fx.table1_title, desc=fx.table1_desc,
                     rows=fx.table1_rows, widths_mm=fx.table1_widths, row_h=14 * mm) - 6 * mm
    y = _table_block(c, y, number=2, title=fx.table2_title, desc=fx.table2_desc,
                     rows=fx.table2_rows, widths_mm=fx.table2_widths, row_h=14 * mm) - 5 * mm
    _paragraph(c, "Full episode evidence and chronological events continue on the following pages when needed. "
               "No generic dwell, relapse, attention or cognitive-recovery score is inferred.",
               MARGIN, y, CONTENT_WIDTH, 15 * mm, size=8, leading=10, color=MUTED)
    _footer(c, caption=fx.footer, page_label=_page_label(fx, 0))


def _page_sp10(c, fx) -> None:
    y = _results_page_header(c, page_code="SP10", chapter_label="SP10  |  Chapter 4 Results and Discussion",
                              chapter_num="4", chapter_title="COSECANT RESULTS AND DISCUSSION", intro=fx.intro)

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "doc")
    _text(c, "COSECANT SESSION SNAPSHOT", MARGIN + 10 * mm, y - 2 * mm, 10.5, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.snapshot_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 10 * mm, size=7.2, leading=8.6, color=INK) - 2 * mm
    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, fx.snapshot_cards, columns=5, card_h=28 * mm, render_cell=_snapshot_card) - 2 * mm

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "route")
    _text(c, "STUDY-BREAK RETURN PATHWAY", MARGIN + 10 * mm, y - 2 * mm, 10.5, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.pathway_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 8 * mm, size=7.2, leading=8.6, color=INK) - 2 * mm
    y = _workflow_chain(c, MARGIN, y, CONTENT_WIDTH, fx.pathway_boxes, box_h=24 * mm, gap=2.8 * mm) - 4 * mm

    left_x, right_x, col_w = _two_col(MARGIN, CONTENT_WIDTH)
    ly = _table_block(c, y, number=1, title=fx.table1_title, desc=fx.table1_desc, rows=fx.table1_rows, widths_mm=fx.table1_widths)
    _icon_circle(c, right_x + 3.6 * mm, y - 3.6 * mm, 3.6 * mm, "doc")
    _text(c, f"TABLE 2  |  {fx.table2_title}", right_x + 9 * mm, y - 1.8 * mm, 8.6, NAVY, bold=True)
    ry = _paragraph(c, fx.table2_desc, right_x, y - 6.8 * mm, col_w, 8 * mm, size=6.4, leading=7.6, color=MUTED) - 1.5 * mm
    ry = _table(c, right_x, ry, fx.table2_widths, fx.table2_rows, row_h=7.6 * mm)
    y = min(ly, ry) - 5 * mm

    if fx.chart_available:
        ly2 = _bar_chart(c, MARGIN, y, col_w + 3 * mm, 42 * mm, categories=fx.chart_categories, values=fx.chart_values,
                          y_max=fx.chart_y_max, unit=fx.chart_unit, bars_color=CYAN)
    else:
        ly2 = _empty_chart(c, MARGIN, y, col_w + 3 * mm, 42 * mm,
                            message=fx.chart_unavailable_message)
    _text(c, getattr(fx, "chart_title", "COSECANT TREND GRAPH"), MARGIN, y + 1.5 * mm, 7.6, CYAN_DARK, bold=True)

    box_h = 42 * mm
    _rrect(c, right_x, y - box_h, col_w, box_h, 2 * mm, fill=PALE_BLUE)
    _icon_circle(c, right_x + 5 * mm, y - 5 * mm, 3.4 * mm, "info")
    _text(c, "DISCUSSION NOTE", right_x + 10 * mm, y - 4 * mm, 8, NAVY, bold=True)
    _paragraph(c, fx.discussion_note, right_x + 4.5 * mm, y - 10 * mm, col_w - 9 * mm, box_h - 12 * mm,
               size=6.6, leading=8, color=INK)
    y -= box_h + 4 * mm

    _footer(c, caption=fx.footer, page_label=_page_label(fx, 11))


# ---------------------------------------------------------------------------
# Shared components for SP11/SP12/SP13/SP14
# ---------------------------------------------------------------------------

def _numbered_circle(c, cx, cy, r, number: str, *, fill=CYAN, fg=WHITE) -> None:
    c.setFillColor(fill)
    c.circle(cx, cy, r, fill=1, stroke=0)
    _text(c, number, cx, cy - 2.6, 9, fg, bold=True, align="center")


def _verdict_box(c, x, y, w, h, *, title, icon, tone, items) -> None:
    bg = GREEN_BG if tone == "good" else RED_BG
    accent = GREEN if tone == "good" else RED
    _rrect(c, x, y - h, w, h, 2 * mm, fill=bg)
    _icon_circle(c, x + 5 * mm, y - 5 * mm, 3.4 * mm, icon, ring=accent, glyph=accent, fill=WHITE)
    _text(c, title, x + 10 * mm, y - 4 * mm, 8.6, NAVY, bold=True)
    yy = y - 10 * mm
    for line in items:
        c.setFillColor(accent)
        c.circle(x + 5 * mm, yy - 2.2, 0.55 * mm, fill=1, stroke=0)
        yy = _paragraph(c, line, x + 7.5 * mm, yy, w - 11 * mm, 8 * mm, size=6.6, leading=7.8, color=INK) - 1.4 * mm


def _numbered_future_card(c, x, y, w, h, item) -> None:
    _card(c, x, y, w, h, fill=WHITE, stroke=LINE)
    _numbered_circle(c, x + 6 * mm, y - 6 * mm, 3.6 * mm, item["number"], fill=item.get("badge", CYAN))
    _icon_circle(c, x + w / 2, y - 15 * mm, 6 * mm, item["icon"], ring=item.get("badge", CYAN), glyph=item.get("badge", CYAN))
    _text(c, item["title"], x + w / 2, y - 24 * mm, 8, NAVY, bold=True, align="center")
    _rule(c, x + 5 * mm, y - 26.5 * mm, x + w - 5 * mm, LINE, 0.5)
    _paragraph(c, item["body"], x + 4 * mm, y - 29.5 * mm, w - 8 * mm, h - 31 * mm, size=6.6, leading=8, color=INK, align="center")


def _roadmap_strip(c, x, y, width, steps) -> float:
    h = 10 * mm
    n = len(steps)
    seg_w = width / n
    c.setFillColor(CYAN)
    c.circle(x, y - h / 2, 2 * mm, fill=1, stroke=0)
    for i, step in enumerate(steps):
        left = x + i * seg_w
        p = c.beginPath()
        p.moveTo(left, y)
        p.lineTo(left + seg_w - 2 * mm, y)
        p.lineTo(left + seg_w, y - h / 2)
        p.lineTo(left + seg_w - 2 * mm, y - h)
        p.lineTo(left, y - h)
        p.lineTo(left + 2 * mm, y - h / 2)
        p.close()
        c.setFillColor(CYAN if i == 0 else PALE_CYAN)
        c.setStrokeColor(WHITE)
        c.drawPath(p, fill=1, stroke=1)
        fg = WHITE if i == 0 else NAVY
        _text(c, step["number"], left + seg_w / 2, y - 4 * mm, 8, fg, bold=True, align="center")
        _text(c, step["label"], left + seg_w / 2, y - 8 * mm, 6.2, fg, bold=True, align="center")
    y -= h + 3 * mm
    _rule(c, x, y, x + width, LINE, 0.5)
    _text(c, "RESEARCH AND DEVELOPMENT ROADMAP", x + width / 2, y - 3.6 * mm, 6.4, MUTED, bold=True, align="center", spacing=0.6)
    return y - 8 * mm


def _foundation_card(c, x, y, w, h, item) -> None:
    _card(c, x, y, w, h, fill=WHITE, stroke=LINE)
    c.setFillColor(item["color"])
    c.circle(x + 5 * mm, y - 5 * mm, 2 * mm, fill=1, stroke=0)
    _text(c, item["name"], x + 9 * mm, y - 6 * mm, 8.4, NAVY, bold=True)
    _bullet_list(c, x + 3.5 * mm, y - 11 * mm, w - 7 * mm, item["points"], size=6.1, leading=7.3, gap=1 * mm)


def _reference_entry(c, x, y, w, h, item) -> None:
    _numbered_circle(c, x + 5 * mm, y - 5 * mm, 4 * mm, item["number"], fill=PALE_CYAN, fg=CYAN_DARK)
    _paragraph(c, item["text"], x + 12 * mm, y - 2 * mm, w - 14 * mm, h - 2 * mm, size=7.2, leading=9.2, color=INK)


# ---------------------------------------------------------------------------
# SP11 -- Conclusion
# ---------------------------------------------------------------------------

def _page_sp11(c, fx) -> None:
    top, _ = _page_frame(c, page_code="SP11", chapter_label="SP11  |  Chapter 5 Conclusion and Future Scope")
    y = _chapter_title(c, top, "5", "CONCLUSION")
    y = _callout(c, y, fx.intro)

    y = _section_head(c, MARGIN, y, "doc", "WHAT MYELIN DEMONSTRATES", fx.what_demonstrates_intro, CONTENT_WIDTH,
                       body_size=8.0, body_height=8 * mm)
    box_h = 22 * mm
    _rrect(c, MARGIN, y - box_h, CONTENT_WIDTH, box_h, 2 * mm, fill=SOFT, stroke=LINE)
    left_x, right_x, col_w = _two_col(MARGIN + 4 * mm, CONTENT_WIDTH - 8 * mm)
    _bullet_list(c, left_x, y - 4 * mm, col_w, fx.demonstrates_left, size=6.8, leading=8.2)
    _bullet_list(c, right_x, y - 4 * mm, col_w, fx.demonstrates_right, size=6.8, leading=8.2)
    y -= box_h + 3 * mm

    y = _section_head(c, MARGIN, y, "flow", "RECOVERY AS THE CORE CONTRIBUTION", fx.recovery_core_intro, CONTENT_WIDTH,
                       body_size=8.0, body_height=8 * mm)
    y = _workflow_chain(c, MARGIN, y, CONTENT_WIDTH, fx.recovery_chain_boxes, box_h=20 * mm, gap=3.5 * mm) - 4 * mm
    y = _callout(c, y, fx.mirl_statement)

    y = _section_head(c, MARGIN, y, "chart", "HCI SIGNIFICANCE", fx.hci_significance_intro, CONTENT_WIDTH,
                       body_size=8.0, body_height=8 * mm)
    hci_cards = fx.hci_cards
    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, hci_cards, columns=4, card_h=26 * mm, render_cell=_metric_card) - 3 * mm

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "warn")
    _text(c, "SCIENTIFIC BOUNDARY", MARGIN + 10 * mm, y - 2 * mm, 11, CYAN, bold=True, spacing=0.3)
    y = _paragraph(c, fx.scientific_boundary_intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 6 * mm, size=7.6, leading=9, color=INK) - 2 * mm
    y = _callout(c, y, fx.scientific_boundary_statement, bold=True)

    left_x, right_x, col_w = _two_col(MARGIN, CONTENT_WIDTH)
    box_h2 = 26 * mm
    _verdict_box(c, left_x, y, col_w, box_h2, title="CURRENTLY DEFENSIBLE", icon="check", tone="good", items=fx.currently_defensible)
    _verdict_box(c, right_x, y, col_w, box_h2, title="NOT YET ESTABLISHED", icon="warn", tone="bad", items=fx.not_yet_established)
    y -= box_h2 + 4 * mm

    y = _paragraph(c, fx.closing_remark, MARGIN, y, CONTENT_WIDTH, 12 * mm, size=9.3, leading=11, color=NAVY, bold=True)
    _footer(c, caption="", page_label=_page_label(fx, 12))


# ---------------------------------------------------------------------------
# SP12 -- Future Scope and Research Roadmap
# ---------------------------------------------------------------------------

def _page_sp12(c, fx) -> None:
    top, _ = _page_frame(c, page_code="SP12", chapter_label="SP12  |  Chapter 5 Conclusion and Future Scope")
    y = _chapter_title(c, top, "5", "FUTURE SCOPE AND RESEARCH ROADMAP")
    y = _callout(c, y, fx.intro)

    y = _section_head(c, MARGIN, y, "flag", "FIVE KEY FUTURE DIRECTIONS", fx.five_directions_intro, CONTENT_WIDTH,
                       body_size=8.0, body_height=10 * mm)

    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, fx.first_three, columns=3, card_h=54 * mm, render_cell=_numbered_future_card) - 4 * mm
    y = _roadmap_strip(c, MARGIN, y, CONTENT_WIDTH, fx.roadmap_steps)
    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, fx.last_two, columns=2, card_h=42 * mm, render_cell=_numbered_future_card) - 4 * mm

    y = _callout(c, y, fx.next_scientific_step, bold=False)
    _footer(c, caption=fx.footer, page_label=_page_label(fx, 13))


# ---------------------------------------------------------------------------
# SP13 -- Scientific Maturity and Research Responsibility
# ---------------------------------------------------------------------------

def _page_sp13(c, fx) -> None:
    top, _ = _page_frame(c, page_code="SP13", chapter_label="SP13  |  Chapter 5 Conclusion and Future Scope")
    y = _chapter_title(c, top, "5", "SCIENTIFIC MATURITY AND RESEARCH RESPONSIBILITY")
    y = _callout(c, y, fx.intro)

    for number, title, icon, body in fx.numbered_sections:
        _numbered_circle(c, MARGIN + 3.6 * mm, y - 3.6 * mm, 3.6 * mm, number)
        _text(c, title, MARGIN + 9 * mm, y - 2 * mm, 9.6, NAVY, bold=True)
        y = _paragraph(c, body, MARGIN, y - 7 * mm, CONTENT_WIDTH, 9 * mm, size=7.2, leading=8.6, color=INK) - 2.6 * mm

    y = _grid_cards(c, MARGIN, y, CONTENT_WIDTH, fx.foundations, columns=4, card_h=27 * mm, render_cell=_foundation_card) - 2 * mm

    left_x, right_x, col_w = _two_col(MARGIN, CONTENT_WIDTH)
    box_h = 26 * mm
    _verdict_box(c, left_x, y, col_w, box_h, title="CURRENTLY DEFENSIBLE", icon="check", tone="good", items=fx.currently_defensible)
    _verdict_box(c, right_x, y, col_w, box_h, title="NOT YET ESTABLISHED", icon="warn", tone="bad", items=fx.not_yet_established)
    y -= box_h + 5 * mm

    y = _callout(c, y, fx.closing_note)
    _footer(c, caption="", page_label=_page_label(fx, 14))


# ---------------------------------------------------------------------------
# SP14 -- References
# ---------------------------------------------------------------------------

def _page_sp14(c, fx) -> None:
    top, _ = _page_frame(c, page_code="SP14", chapter_label="References")
    y = _sp_title(c, top, "REFERENCES")

    _icon_circle(c, MARGIN + 4 * mm, y - 4 * mm, 4 * mm, "doc")
    _text(c, "Key references cited in this report", MARGIN + 10 * mm, y - 2 * mm, 10, NAVY, bold=True)
    y = _paragraph(c, fx.intro, MARGIN, y - 7.5 * mm, CONTENT_WIDTH, 14 * mm, size=7.6, leading=9, color=INK) - 3 * mm

    left_x, right_x, col_w = _two_col(MARGIN, CONTENT_WIDTH, gap=8 * mm)
    ly = y
    ry = y
    for index, entry in enumerate(fx.references):
        target_x, target_y = (left_x, ly) if index % 2 == 0 else (right_x, ry)
        h = entry.get("height", 22 * mm)
        _rrect(c, target_x, target_y - h, col_w, h, 1.8 * mm, fill=SOFT, stroke=LINE)
        _reference_entry(c, target_x + 2 * mm, target_y - 3 * mm, col_w - 4 * mm, h - 4 * mm,
                          {"number": str(entry["number"]), "text": entry["text"]})
        if index % 2 == 0:
            ly = target_y - h - 3 * mm
        else:
            ry = target_y - h - 3 * mm

    _footer(c, caption=fx.footer, page_label=_page_label(fx, 15))


# =============================================================================
# PHASE 3 DEV-ONLY PREVIEW FIXTURES -- NOT PRODUCTION DATA
#
# Everything below is disposable scaffolding used only to exercise every
# page's layout while Chapter 3 dynamic wiring is Phase 4's job.  Per the
# Phase 3 Data Rule: no numeric value below is copied from the reference
# mock images; result-page values use explicit non-numeric placeholder
# labels (CERTIFIED VALUE, EPISODE ID, TIME, AVAILABLE, UNAVAILABLE) so
# nothing here can be mistaken for real experiment evidence.  This section
# has no production caller -- report.py exposes drawing functions that take
# real Chapter3ResultPackage-shaped data in a future phase; it does not
# read this module-level fixture itself.
# =============================================================================

from types import SimpleNamespace as _NS


def _build_report_fixtures(*, report_model: ReportRenderModel | None = None) -> dict:
    sp1 = _NS(
        abstract="Digital work is frequently interrupted by application switching, messaging, social "
                 "platforms, streaming media and other competing activities. Conventional screen-time "
                 "measures describe where time was spent, but they reveal much less about what happened "
                 "to the task that preceded the interruption or how behaviour recovered afterwards.",
        keywords="digital interruption, task switching, behavioural return, re-engagement, digital "
                 "distraction, human-computer interaction",
        intro_left="A person may begin a digital task with a genuine intention to work, maintain that "
                   "task for a period, transition to another activity, remain engaged elsewhere and "
                   "eventually return. The return, however, should not automatically be interpreted as "
                   "restoration of the state that existed before the interruption.",
        intro_right="The neuroscience of drift requires an important distinction between internal "
                    "mind-wandering and external attentional redirection. Mind-wandering research "
                    "implicates both default-mode and executive-system contributions rather than a "
                    "simple switch from a focus network to a distraction network [Christoff et al., "
                    "2009].",
        behavioral_geometry_statement="MYELIN measures the behavioural geometry around attention -- "
            "where activity goes, how long it remains elsewhere and how successfully it returns -- not "
            "the hidden biology generating that behaviour.",
    )
    sp2 = _NS(
        sp2_intro="SINE and MINE regulate general and messaging drift outside the Study SECANT pathway. Both regulate "
                  "off-task digital behaviour, but MINE introduces a branch pathway for messaging the "
                  "user considers important.",
        sine_body="SINE is MYELIN's general drift-regulation organ. It responds when software-observed "
                  "behaviour suggests that the user has moved away from the intended task context into a "
                  "distracting digital pathway. It uses staged escalation that begins softly and becomes "
                  "progressively firmer if off-task behaviour persists.",
        mine_body="MINE is MYELIN's messaging-specific organ. It activates when qualifying messaging "
                  "behaviour persists long enough to suggest that conversation activity is taking control "
                  "of the session. Unlike SINE, MINE contains a branch structure that distinguishes "
                  "ordinary messaging drift from communication the user considers important.",
    )
    sp3 = _NS(
        sp3_intro="COSINE manages OTT streaming pathways. Study off-task regulation and approved-break return "
                  "are described separately on the following SECANT / COSECANT page.",
        cosine_body="COSINE is MYELIN's OTT and streaming-regulation organ. It is designed for prolonged "
                    "entertainment-streaming contexts rather than ordinary web drift or messaging. COSINE "
                    "first asks about the user's intention, then manages either return intention or an "
                    "intentionally chosen leisure interval before guiding the user back toward task "
                    "resumption.",
        cosecant_body="COSECANT independently governs the approved Study-break branch. A permitted break has a selected "
                      "allowance, then reminder and final-lock stages if return remains unconfirmed. SECANT owns confirmed "
                      "Study off-task recovery outside that approved-break interval; COSECANT confirms exact Study-resource return.",
    )
    sp4 = _NS(
        sp4_intro="This chapter explains the behavioural data MYELIN can record from certified software "
                  "evidence. It describes what the system actually collects, not live results or "
                  "invented numbers.",
        how_collects="MYELIN records behavioural evidence from certified software when you work on a "
                     "task. It captures activity related to task work, drift, intervention, return, and "
                     "recovery across the different MYELIN organs. Report values update when new eligible "
                     "sessions are added and a new PDF is generated.",
        metrics_intro="The following metrics describe MYELIN's behavioural measurements. Each metric is "
                      "reported only when certified evidence supports it. Unsupported measurements are "
                      "marked unavailable rather than presented as measured results.",
        live_feed_intro="Chronological behavioural events are recorded here from certified software "
                        "evidence.",
        live_feed_examples="Examples include intervention display, off-task activity, return attempts, "
                           "verified return, relapse, and closure-related events.",
        derived_findings_intro="This area turns validated evidence into comparisons and summaries.",
        derived_findings_examples="Examples include best and worst return times, common drift patterns, "
                                  "and organ-specific behaviour.",
        source_coverage_intro="MYELIN can collect evidence from the following organs and sources when "
                              "available. Each can contribute different types of behavioural data.",
        important_boundary="MYELIN measures software-observed behaviour. It does not directly measure "
                           "dopamine, brain activity, motivation, boredom, stress, fatigue, or subjective "
                           "effort.",
        sp4_footer="All measurements are behavioural. Availability depends on certified MYELIN evidence "
                   "at report-generation time.",
    )
    sp5 = _NS(
        sp5_intro="This page explains what MYELIN can learn from its collected evidence. It focuses on "
                  "behavioural interpretation, HCI relevance, and careful prediction rather than direct "
                  "brain measurement.",
        evidence_to_interpretation="MYELIN first records software-observed behavioural events from "
            "certified sessions, such as task engagement, drift, interventions, returns, and context "
            "switches. These events are then organised into behavioural metrics, validated comparisons, "
            "and session summaries.",
        what_evidence_shows="The collected evidence can provide insights into several aspects of user "
                            "behaviour and system performance.",
        session_to_findings="MYELIN turns raw session events into structured findings through a series "
                            "of steps.",
        whole_myelin_analysis="Once a full MYELIN run is complete, the system can combine evidence from "
            "all organs into a single session-level summary. This supports both practical design "
            "insights and scientific analysis.",
        limitations_caution_intro="Important considerations when interpreting MYELIN results.",
        limitations_caution_body="MYELIN describes software-observed behaviour. It does not directly "
            "measure dopamine, neural firing, motivation, boredom, stress, fatigue, or subjective effort.",
        sp5_footer="As MYELIN records more certified sessions, the same evidence structure can support "
                   "future results, comparisons, and longitudinal analysis.",
    )

    def _overview_card(organ, status, dot, caption):
        good = status == "AVAILABLE"
        return {"organ": organ, "status": status, "status_bg": GREEN_BG if good else SOFT,
                "status_fg": GREEN if good else MUTED, "dot": dot, "caption": caption}

    sp6 = _NS(
        sp6_intro="This chapter presents the certified behavioural results from the MYELIN organs for "
                  "the selected experiment (development preview fixture). When an organ has no certified "
                  "result data, its evidence is shown clearly as unavailable.",
        how_organised="This chapter contains an overview of the certified behavioural results, followed "
                      "by separate organ pages for SINE, MINE, COSINE, SECANT and COSECANT when data exists.",
        session_level_intro="This section shows which MYELIN organs have certified results for the "
                            "selected experiment (development preview fixture, not real experiment data).",
        organ_overview_cards=[
            _overview_card("SINE", "AVAILABLE", BLUE_MED, "CERTIFIED VALUE"),
            _overview_card("MINE", "AVAILABLE", GREEN, "CERTIFIED VALUE"),
            _overview_card("COSINE", "UNAVAILABLE", PURPLE, "UNAVAILABLE"),
            _overview_card("SECANT", "NO_EVIDENCE", CYAN_DARK, "DEV FIXTURE: no SECANT rows"),
            _overview_card("COSECANT", "AVAILABLE", AMBER, "CERTIFIED VALUE"),
            _overview_card("MIRL / OVERALL", "AVAILABLE", CYAN, "Summary pathway"),
        ],
        available_result_types_intro="This chapter presents the following types of results, when "
                                     "certified for the selected experiment.",
        what_appears_intro="Each organ page presents organ-specific results from certified evidence. "
                           "Content varies by organ as follows.",
        important_reading_rule="DEV FIXTURE: Results in this chapter reflect only certified evidence for "
            "the selected experiment. NO_EVIDENCE, UNAVAILABLE, or CROSS_BOUNDARY_OVERLAP do not by "
            "themselves prove that an organ was unused. Each state describes the evidence available for "
            "the selected experiment and must be interpreted according to its recorded reason -- no state "
            "is ever inferred or invented.",
        mixed_membership_scope_note="[X] complete episode(s) analysed; [Y] overlapping episode(s) "
            "excluded at the experiment boundary. Reserved for Phase 4 dynamic wiring; not populated in "
            "Phase 3.",
        sp6_footer="Page structure varies with the organs used in the selected experiment (development "
                   "preview fixture).",
    )

    def _journey_box(label, icon, **kw):
        base = {"label": label, "icon": icon, "ring": kw.pop("ring", MUTED), "glyph": kw.pop("glyph", MUTED)}
        base.update(kw)
        return base

    sp7 = _NS(
        intro="This page summarises the certified SINE behavioural results from the selected experiment "
              "(development preview fixture). SINE recovery is verified through MIRL.",
        snapshot_intro="Key details from the selected experiment. Values shown are development preview "
                       "fixtures, not real experiment evidence.",
        snapshot_cards=[
            {"label": "Episodes", "icon": "doc", "value": "EPISODE ID", "caption": "Number of SINE episodes detected"},
            {"label": "SINE stages observed", "icon": "layers", "value": "AVAILABLE", "caption": "Different SINE levels in this experiment"},
            {"label": "Verified returns", "icon": "check", "value": "CERTIFIED VALUE", "caption": "Confirmed through MIRL evidence"},
            {"label": "Relapses", "icon": "refresh", "value": "CERTIFIED VALUE", "caption": "Returns followed by drifting away again"},
            {"label": "Data status", "icon": "doc", "value": "AVAILABLE", "value_color": GREEN, "caption": "SINE results available for this experiment"},
        ],
        journey_map_intro="A simplified view of how behaviour changed during the experiment, based on "
                          "certified evidence (development preview fixture).",
        journey_boxes=[
            _journey_box("DETECTED DRIFT", "warn"),
            _journey_box("SINE-1", "bell", fill=PALE_CYAN, ring=CYAN, glyph=NAVY),
            _journey_box("CONTINUED OFF-TASK", "layers"),
            _journey_box("SINE-2", "bell", fill=AMBER_BG, ring=AMBER, glyph=AMBER, label_color=AMBER),
            _journey_box("CONTINUED OFF-TASK", "layers"),
            _journey_box("SINE-3", "bell", fill=RED_BG, ring=RED, glyph=RED, label_color=RED),
            _journey_box("RETURN INTENT", "undo", ring=CYAN, glyph=NAVY),
            _journey_box("VERIFIED RETURN", "check", ring=CYAN, glyph=NAVY),
            _journey_box("CLOSURE", "flag", ring=CYAN, glyph=NAVY),
        ],
        table1_title="MIRL RECOVERY SUMMARY",
        table1_desc="Summary of verified returns for each SINE episode (development preview fixture).",
        table1_rows=[("EPISODE", "SESSION", "FIRST SINE DISPLAY", "TIME RETURNED"),
                     ("EPISODE ID", "EPISODE ID", "TIME", "TIME"),
                     ("EPISODE ID", "EPISODE ID", "TIME", "TIME")],
        table1_widths=(20, 20, 24, 24),
        table2_title="SINE STAGE SUMMARY",
        table2_desc="Details of SINE stages and user response for each episode (development preview "
                    "fixture).",
        table2_rows=[("EPISODE", "ESC. TIME", "SINE LEVEL", "RESPONSE"),
                     ("EPISODE ID", "TIME", "SINE-1", "UNAVAILABLE"),
                     ("EPISODE ID", "TIME", "SINE-2", "UNAVAILABLE")],
        table2_widths=(20, 20, 20, 24),
        chart_categories=["EP-01", "EP-02", "EP-03"],
        chart_series=[
            {"label": "Escalation (drift)", "values": [0.2, 0.6, 0.85], "color": CYAN},
            {"label": "Return (verified)", "values": [0.85, None, 0.15], "dashed": True, "marker": "hollow", "color": CYAN_DARK},
        ],
        chart_y_labels=["Low", "Medium", "High"],
        chart_available=True,
        chart_unavailable_message="UNAVAILABLE -- no certified SINE chart points.",
        discussion_note="DEV FIXTURE: The SINE results show how behaviour drifted, how it escalated "
            "across episodes, and how recovery was achieved. Verified returns are confirmed using MIRL "
            "evidence. These results describe observable behaviour, not internal thoughts or motivation.",
        footer="Values show certified results from the selected experiment (development preview "
               "fixture).",
    )

    sp8 = _NS(
        intro="This page summarises the certified MINE behavioural results for messaging episodes in "
              "the selected experiment (development preview fixture). It shows how the two-option "
              "response pathway was used and what happened next.",
        snapshot_intro="Key information about MINE messaging activity in the selected experiment "
                       "(development preview fixture).",
        snapshot_cards=[
            {"label": "Messaging episodes", "icon": "chat", "value": "CERTIFIED VALUE", "caption": "Total MINE messaging episodes"},
            {"label": "MINE-1 displays", "icon": "doc", "value": "CERTIFIED VALUE", "caption": "Number of times MINE-1 was shown"},
            {"label": "Branch choices", "icon": "route", "value": "CERTIFIED VALUE", "caption": "Total response options selected"},
            {"label": "Final callbacks", "icon": "refresh", "value": "CERTIFIED VALUE", "caption": "Number of final MINE-2 callbacks recorded"},
            {"label": "Data status", "icon": "chat", "value": "AVAILABLE", "value_color": GREEN, "caption": "Certified results available"},
        ],
        pathway_intro="This diagram shows the MINE messaging route and the two possible response "
                      "pathways after MINE-1 (development preview fixture).",
        pathway_boxes=[
            _journey_box("QUALIFYING MESSAGING", "chat"),
            _journey_box("10:00 THRESHOLD", "clock"),
            _journey_box("MINE-1 POPUP", "chat", fill=PALE_CYAN, ring=CYAN, glyph=NAVY),
            {"branch": [
                _journey_box("I WILL COME BACK", "route", ring=GREEN, glyph=GREEN, caption="13:15 timer starts"),
                _journey_box("IT'S IMPORTANT", "route", ring=GREEN, glyph=GREEN, caption="5-30 min window"),
            ]},
            _journey_box("MINE-2A / MINE-2B", "chat", fill=RED_BG, ring=RED, glyph=RED),
            _journey_box("RETURN / OWN RECOVERY", "refresh", ring=CYAN, glyph=NAVY),
        ],
        table1_title="MINE EPISODE SUMMARY",
        table1_desc="Overview of MINE messaging episodes in this experiment (development preview "
                    "fixture).",
        table1_rows=[("EPISODE", "SESSION", "START", "FINAL RETURN"),
                     ("EPISODE ID", "S1", "TIME", "TIME"),
                     ("EPISODE ID", "S1", "TIME", "TIME")],
        table1_widths=(20, 16, 20, 24),
        table2_title="RESPONSE OPTION SUMMARY",
        table2_desc="Which response options were chosen and what happened next (development preview "
                    "fixture).",
        table2_rows=[("EPISODE", "OPTION", "TIMER", "CALLBACK"),
                     ("EPISODE ID", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE"),
                     ("EPISODE ID", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE")],
        table2_widths=(20, 22, 20, 22),
        chart_categories=["EP1", "EP2", "EP3", "EP4", "EP5"],
        chart_values=[2, 3, 1, 2, 1],
        chart_y_max=4,
        chart_unit="MINE-1 displays",
        chart_extra_series=[
            {"label": "Option A (I will come back)", "values": [1, 2, 1, 1, 1], "color": PURPLE},
            {"label": "Option B (It's important)", "values": [1, 1, 0, 1, 0], "color": GREEN},
        ],
        chart_available=True,
        chart_unavailable_message="UNAVAILABLE -- no certified MINE chart points.",
        discussion_note="DEV FIXTURE: MINE results help explain how persistent messaging was managed and "
            "how users reacted to the two response options. They do not measure motivation, internal "
            "state or any direct brain activity.",
        footer="Values show certified results from the selected experiment (development preview "
               "fixture).",
    )

    sp9 = _NS(
        intro="This page summarises the certified COSINE results for OTT episodes in the selected "
              "experiment (development preview fixture). It shows how watch behaviour, return "
              "intention, and callbacks were recorded.",
        snapshot_intro="Quick overview of the COSINE data available for the selected experiment "
                       "(development preview fixture).",
        snapshot_cards=[
            {"label": "OTT episodes", "icon": "play", "value": "UNAVAILABLE", "value_color": MUTED, "caption": "Total OTT episodes recorded"},
            {"label": "Intention checks", "icon": "check", "value": "UNAVAILABLE", "value_color": MUTED, "caption": "COSINE intention checks completed"},
            {"label": "Chosen watch/break", "icon": "clock", "value": "UNAVAILABLE", "value_color": MUTED, "caption": "User selected watch or break per episode"},
            {"label": "Callbacks", "icon": "refresh", "value": "UNAVAILABLE", "value_color": MUTED, "caption": "End-of-break callbacks recorded"},
            {"label": "Data status", "icon": "play", "value": "UNAVAILABLE", "value_color": MUTED, "caption": "No certified COSINE data for this experiment"},
        ],
        pathway_intro="This diagram shows how COSINE captures OTT behaviour, return intention, and "
                      "callbacks for each episode (development preview fixture).",
        pathway_boxes=[
            _journey_box("OTT DETECTED", "play", ring=PURPLE, glyph=PURPLE),
            _journey_box("5:00 THRESHOLD", "clock"),
            _journey_box("COSINE INTENTION CHECK", "chat", ring=CYAN, glyph=NAVY),
            {"branch": [
                _journey_box("RETURN WINDOW", "route", ring=GREEN, glyph=GREEN, caption="5:00 return window"),
                _journey_box("CHOSEN WATCH PERIOD", "route", ring=GREEN, glyph=GREEN, caption="10-200 min period"),
            ]},
            _journey_box("END-OF-BREAK CALLBACK", "bell", fill=RED_BG, ring=RED, glyph=RED),
            _journey_box("RETURN / CLOSURE", "undo", ring=CYAN, glyph=NAVY),
        ],
        table1_title="COSINE EPISODE SUMMARY",
        table1_desc="Overview of OTT episodes and final return times (development preview fixture).",
        table1_rows=[("EPISODE", "SESSION", "OTT START", "FINAL RETURN"),
                     ("UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE")],
        table1_widths=(20, 18, 22, 24),
        table2_title="BREAK / WATCH DECISION SUMMARY",
        table2_desc="User choices and callback outcomes for each episode (development preview fixture).",
        table2_rows=[("EPISODE", "OPTION", "DURATION", "CALLBACK"),
                     ("UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE")],
        table2_widths=(20, 20, 22, 22),
        chart_available=False,
        chart_unavailable_message="UNAVAILABLE -- no certified COSINE trend data for this experiment.",
        discussion_note="DEV FIXTURE: COSINE results describe the user's leisure-streaming behaviour for "
            "the selected experiment. This organ has no certified data in this fixture, so its detail "
            "fields are shown as UNAVAILABLE rather than estimated.",
        footer="Page structure varies with the organs used in the selected experiment (development "
               "preview fixture).",
    )

    sp10 = _NS(
        intro="This page summarises the certified COSECANT results for approved study breaks in the "
              "selected experiment (development preview fixture). It presents how the user came back "
              "from breaks and how the escalation process supported study continuity.",
        snapshot_intro="Key information from the selected experiment, showing study breaks and return "
                       "behaviour (development preview fixture).",
        snapshot_cards=[
            {"label": "Approved study breaks", "icon": "cap", "value": "CERTIFIED VALUE", "caption": "Number of approved breaks taken"},
            {"label": "Reminder levels observed", "icon": "bell", "value": "CERTIFIED VALUE", "caption": "Reminder stages triggered after break completion"},
            {"label": "Final locks", "icon": "lock", "value": "CERTIFIED VALUE", "caption": "Number of +1 min final lock events"},
            {"label": "Return confirmations", "icon": "check", "value": "CERTIFIED VALUE", "caption": "Confirmed returns via exact study-resource access"},
            {"label": "Data status", "icon": "cap", "value": "AVAILABLE", "value_color": GREEN, "caption": "Certified COSECANT data available"},
        ],
        pathway_intro="This diagram shows the COSECANT process from study break to study resumption "
                      "(development preview fixture).",
        pathway_boxes=[
            _journey_box("STUDY CONTEXT ACTIVE", "book"),
            _journey_box("APPROVED STUDY BREAK", "cup"),
            _journey_box("BREAK COMPLETE", "check", ring=CYAN, glyph=NAVY),
            _journey_box("+5 MIN REMINDER", "clock", fill=AMBER_BG, ring=AMBER, glyph=AMBER, label_color=AMBER),
            _journey_box("+1 MIN FINAL LOCK", "lock", fill=RED_BG, ring=RED, glyph=RED, label_color=RED),
            _journey_box("EXACT RESOURCE CONFIRMATION", "doc", ring=CYAN, glyph=NAVY),
            _journey_box("STUDY RESUMED", "chart", ring=CYAN, glyph=NAVY),
        ],
        table1_title="BREAK TIMING SUMMARY",
        table1_desc="Timing details for each approved study break in the experiment (development "
                    "preview fixture).",
        table1_rows=[("SESSION", "BREAK STARTED", "BREAK DURATION", "BREAK COMPLETE", "RETURN LATENCY"),
                     ("EPISODE ID", "TIME", "TIME", "TIME", "UNAVAILABLE")],
        table1_widths=(15, 17, 17, 17, 18),
        table2_title="COSECANT ESCALATION SUMMARY",
        table2_desc="Reminder and escalation events for each break (development preview fixture).",
        table2_rows=[("SESSION", "REMINDER LEVEL", "ESC. TIME", "RETURN STATUS"),
                     ("EPISODE ID", "+5 MIN", "TIME", "AVAILABLE"),
                     ("EPISODE ID", "+1 MIN", "TIME", "AVAILABLE")],
        table2_widths=(18, 22, 20, 22),
        chart_available=False,
        chart_unavailable_message="UNAVAILABLE -- no certified post-break return-latency data in this fixture.",
        discussion_note="DEV FIXTURE: COSECANT results show how users came back from approved study "
            "breaks and how the reminder/escalation steps supported study continuity. Locked latency "
            "definition: BREAK_COMPLETE -> RETURN_CONFIRMED. An early return before BREAK_COMPLETE reads "
            "'Not applicable -- returned before break completion', never 0 or negative.",
        footer="All values are development preview fixtures. Availability depends on certified COSECANT "
               "evidence.",
    )

    sp11 = _NS(
        intro="MYELIN approaches digital distraction as a behavioural trajectory rather than only as "
              "accumulated screen time.",
        what_demonstrates_intro="MYELIN shows that certified digital evidence can provide a structured "
            "and meaningful view of distraction and recovery. In this chapter, we conclude that MYELIN:",
        demonstrates_left=[
            "Observes the full behavioural trajectory: task engagement, drift, intervention, return, "
            "relapse and closure.",
            "Distinguishes SINE, MINE, COSINE, SECANT and COSECANT, each with clear meanings and evidence.",
        ],
        demonstrates_right=[
            "Records certified behavioural evidence from real digital activity.",
            "Keeps evidence that is unavailable clearly marked as unavailable rather than inferring or "
            "inventing data.",
        ],
        recovery_core_intro="MYELIN's key contribution is to model the recovery trajectory and verify "
                            "behavioral return, not just to detect distraction.",
        recovery_chain_boxes=[
            _journey_box("FOCUSED TASK", "target", ring=CYAN, glyph=NAVY),
            _journey_box("DRIFT", "warn", fill=AMBER_BG, ring=AMBER, glyph=AMBER),
            _journey_box("INTERVENTION", "gear", fill=PURPLE_BG, ring=PURPLE, glyph=PURPLE),
            _journey_box("RETURN INTENT", "person", fill=GREEN_BG, ring=GREEN, glyph=GREEN),
            _journey_box("VERIFIED RETURN", "chart", ring=CYAN, glyph=NAVY),
            _journey_box("RELAPSE OR CLOSURE", "refresh", fill=RED_BG, ring=RED, glyph=RED),
        ],
        mirl_statement="Return intent alone is not recovery. MIRL carries SINE recovery evidence; "
            "SECANT owns Study off-task recovery; COSECANT governs approved-break return. "
            "Each pathway requires its own recorded evidence of supported return.",
        hci_significance_intro="MYELIN provides practical insights for human-computer interaction by "
                               "showing:",
        hci_cards=[
            {"label": "Timing of interventions", "icon": "clock", "body": "How intervention timing relates to observed user responses."},
            {"label": "Escalation strength", "icon": "gear", "body": "How different escalation levels relate to observed response patterns."},
            {"label": "Burden of prompts", "icon": "people", "body": "How prompt frequency and escalation relate to observed response patterns."},
            {"label": "Supporting self-regulation", "icon": "check", "body": "Designing for user control and sustainable habits, rather than forcing productivity."},
        ],
        scientific_boundary_intro="It is important to be clear about what MYELIN can and cannot claim.",
        scientific_boundary_statement="MYELIN measures software-observed behaviour. It does not "
            "directly measure attention, dopamine, neural activity, fatigue, motivation, memory strength "
            "or cognitive recovery.",
        currently_defensible=[
            "Observed digital behaviour and task sequences",
            "Timing and duration of drift and return",
            "User responses to interventions",
            "Behavioural patterns across contexts and over time",
        ],
        not_yet_established=[
            "Direct measurement of attention or concentration",
            "Changes in dopamine or neural activity",
            "Levels of fatigue or mental effort",
            "Motivation or intention beyond observed behaviour",
        ],
        closing_remark="MYELIN should be judged by whether its evidence supports reproducible questions "
                       "about distraction, intervention and recovery.",
    )

    sp12 = _NS(
        intro="This page outlines the next scientific and technical directions for MYELIN. These future "
              "directions build on the current certified evidence and aim to further improve "
              "understanding, validation and real-world application of MYELIN.",
        five_directions_intro="MYELIN can grow in several directions. The following areas represent the "
                              "main focus for future research and development.",
        first_three=[
            {"number": "1", "title": "CONTROLLED HUMAN VALIDATION", "icon": "people", "badge": BLUE_MED,
             "body": "Future studies can compare normal work, conventional focus tools, and MYELIN-assisted regulation, measuring verified returns, relapse, return latency, and task-aligned work."},
            {"number": "2", "title": "MI -- MYELIN INTELLIGENCE", "icon": "brain", "badge": GREEN,
             "body": "Mi is a future adaptive intelligence layer above the organs, learning from return and relapse history, time of day, session history and user preferences, but not inventing MYELIN policy."},
            {"number": "3", "title": "ASK MI + LOCAL MODEL", "icon": "chat", "badge": PURPLE,
             "body": "A future local language model may explain and summarise certified MYELIN evidence, but will not decide whether distraction or recovery occurred."},
        ],
        roadmap_steps=[
            {"number": "1", "label": "Validation"}, {"number": "2", "label": "Mi Intelligence"},
            {"number": "3", "label": "Local Model"}, {"number": "4", "label": "SenseHub / Edge"},
            {"number": "5", "label": "Longitudinal Research"},
        ],
        last_two=[
            {"number": "4", "title": "SENSEHUB / MYELIN EDGE", "icon": "watch", "badge": BLUE_MED,
             "body": "A future physical extension may add phone-presence sensing, study-state display, physical controls, and future experimental physiological synchronization, without claiming this is current evidence."},
            {"number": "5", "title": "LONGITUDINAL BEHAVIOURAL RESEARCH", "icon": "growth", "badge": GREEN,
             "body": "MYELIN may study changes across days and weeks, such as return latency, relapse patterns, and stable user-specific patterns."},
        ],
        next_scientific_step="The next scientific step is controlled validation: determine whether "
            "MYELIN-assisted regulation produces measurably different behavioural-recovery outcomes "
            "compared with control conditions.",
        footer="These directions are forward-looking and may evolve based on future research, technical "
               "development and real-world findings.",
    )

    sp13 = _NS(
        intro="MYELIN should grow as a careful research platform, with clear evidence boundaries, "
              "minimum necessary observation, and responsible use of participant data.",
        numbered_sections=[
            ("1", "PRIVACY BY MINIMUM OBSERVATION", "eye",
             "MYELIN aims to collect only the behavioural evidence needed for the research question, "
             "not the maximum amount of personal data. We focus on task engagement, app usage, timing "
             "and other high-level behavioural signals, rather than sensitive content such as message "
             "text, file content or full browsing history."),
            ("2", "LOCAL-FIRST DESIGN", "laptop",
             "Where possible, MYELIN uses local processing on the participant's device to reduce "
             "unnecessary external transmission of data. Local execution can lower privacy risks, but "
             "it does not by itself guarantee privacy."),
            ("3", "RESEARCH RESPONSIBILITY", "shield",
             "MYELIN follows a set of core principles to ensure responsible and ethical research "
             "practice: informed consent, minimum necessary observation, transparent data use, secure "
             "local storage, clear experiment boundaries, and participant control."),
        ],
        foundations=[
            {"name": "Ebbinghaus", "color": BLUE_MED, "points": ["Motivates an elapsed-time / temporal hypothesis about how behaviour changes with time away from task, not a memory-forgetting curve [Murre & Dros, 2015]."]},
            {"name": "JITAI", "color": GREEN, "points": ["Motivates questions on just-in-time, context-aware interventions, but does not prove that MYELIN's timing or delivery is optimal [Nahum-Shani et al., 2018]."]},
            {"name": "Weber-Fechner", "color": PURPLE, "points": ["Motivates questions about how changes in stimulus or burden may relate to perceived effect, but does not prove the exact form of the relationship in MYELIN [Stevens, 1957]."]},
            {"name": "Gloria Mark", "color": BLUE_MED, "points": ["Motivates questions about attention, interruption and resumption, but does not prove that MYELIN reduces distraction or improves focus [Mark et al., 2008]."]},
        ],
        currently_defensible=[
            "MYELIN can collect and organise behavioural data as designed.",
            "The system can generate descriptive insights about user behaviour (timing, patterns, platform usage).",
            "The platform provides a structured framework for studying software-observed behaviour in "
            "real-world digital work settings.",
        ],
        not_yet_established=[
            "MYELIN directly improves memory, focus or well-being.",
            "The observed behavioural changes are caused by MYELIN rather than other factors.",
            "The results generalise to broader populations and long-term use.",
        ],
        closing_note="These frameworks motivate testable questions; they do not prove that MYELIN is "
            "effective. As MYELIN collects more certified sessions and diverse data, we can address "
            "these questions with further analysis, comparisons and longer-term studies.",
    )

    sp14 = _NS(
        intro="This section lists the verified academic sources cited throughout the MYELIN report. "
              "Each reference corresponds to a scientific claim, framework, or research context "
              "discussed in the report.",
        references=[
            {"number": 1, "text": "Murre JMJ, Dros J. Replication and Analysis of Ebbinghaus' Forgetting Curve. PLOS ONE, 10(7), e0120644, 2015. DOI: 10.1371/journal.pone.0120644", "height": 24 * mm},
            {"number": 2, "text": "Stevens SS. On the Psychophysical Law. Psychological Review, 64(3), 153-181, 1957. DOI: 10.1037/h0046162", "height": 20 * mm},
            {"number": 3, "text": "Nahum-Shani I, Smith SN, Spring BJ, Collins LM, Witkiewitz K, Tewari A, Murphy SA. Just-in-Time Adaptive Interventions (JITAIs) in Mobile Health. Annals of Behavioral Medicine, 52(6), 446-462, 2018. DOI: 10.1007/s12160-016-9830-8", "height": 28 * mm},
            {"number": 4, "text": "Mark G, Gudith D, Klocke U. The Cost of Interrupted Work: More Speed and Stress. Proceedings of CHI 2008, 107-110, 2008. DOI: 10.1145/1357054.1357072", "height": 24 * mm},
            {"number": 5, "text": "Christoff K, Gordon AM, Smallwood J, Smith R, Schooler JW. Experience Sampling during fMRI Reveals Default Network and Executive System Contributions to Mind Wandering. Proceedings of the National Academy of Sciences, 106(21), 8719-8724, 2009. DOI: 10.1073/pnas.0900234106", "height": 30 * mm},
        ],
        footer="Only sources actually cited in the report are listed here.",
    )

    fixtures = dict(sp1=sp1, sp2=sp2, sp3=sp3, sp4=sp4, sp5=sp5, sp6=sp6, sp7=sp7, sp8=sp8, sp9=sp9,
                    sp10=sp10, sp11=sp11, sp12=sp12, sp13=sp13, sp14=sp14)
    fixtures["study_organs"] = _NS(**vars(sp3))
    fixtures["secant_results"] = _NS(
        intro="DEVELOPMENT PREVIEW: no SECANT quantitative evidence in this fixture.",
        snapshot_cards=[{"label": "Data status", "icon": "book", "value": NO_EVIDENCE, "value_color": MUTED, "caption": "DEV FIXTURE"}],
        table1_title="SECANT EPISODE EVIDENCE", table1_desc="Development fixture only.",
        table1_rows=[("EPISODE", "FIELD", "RECORDED VALUE")], table1_widths=(35, 35, 104),
        table2_title="SECANT EVENT CHRONOLOGY", table2_desc="No synthetic result is certified.",
        table2_rows=[("EPISODE", "OFFSET", "ATTEMPT", "EVENT / REASON")], table2_widths=(35, 21, 18, 100),
        discussion_note="SECANT recovery is independent of MIRL; COSECANT keeps approved-break authority.",
        footer="DEVELOPMENT PREVIEW ONLY")
    if report_model is not None:
        fixtures.update(_integration_result_fixtures(report_model))
    return fixtures


def _build_dev_fixtures() -> dict:
    """Explicit Phase-3 regression fixture entry point; never used by integration."""

    return _build_report_fixtures()


def _integration_result_fixtures(model: ReportRenderModel) -> dict:
    """Translate the pure render model into the frozen Phase-3 drawing seams."""

    def status_style(status: str):
        if status == AVAILABLE:
            return GREEN_BG, GREEN
        if status in (NO_EVIDENCE, UNAVAILABLE, NOT_APPLICABLE):
            return SOFT, MUTED
        return PALE_BLUE, NAVY

    def overview_card(organ: str, status: str, caption: str, dot):
        bg, fg = status_style(status)
        return {"organ": organ, "status": status, "status_bg": bg, "status_fg": fg, "dot": dot, "caption": caption}

    available = {page.organ: page for page in model.organ_pages}
    unavailable = {item.organ: item for item in model.unavailable_organs}
    organ_dots = {"SINE": BLUE_MED, "MINE": GREEN, "COSINE": PURPLE, "SECANT": CYAN_DARK, "COSECANT": AMBER}
    overview_cards = []
    for organ in ("SINE", "MINE", "COSINE", "SECANT", "COSECANT"):
        if organ in available:
            page = available[organ]
            caption = page.overlap_note or page.reason
            overview_cards.append(overview_card(organ, AVAILABLE, caption, organ_dots[organ]))
        else:
            item = unavailable[organ]
            overview_cards.append(overview_card(organ, item.status, item.reason, organ_dots[organ]))
    overview_cards.append(
        overview_card("OVERALL EXPERIMENT", CERTIFIED, f"Experiment {model.experiment_id}; session {model.parent_session_id}", CYAN)
    )
    overlap_notes = tuple(page.overlap_note for page in model.organ_pages if page.overlap_note)
    sp6 = _NS(
        sp6_intro=f"Certified behavioural results for experiment {model.experiment_id} in parent session {model.parent_session_id}.",
        how_organised="The overview is followed only by organ pages supported by certified, experiment-scoped quantitative evidence.",
        session_level_intro="Each card states the certified result availability for this immutable experiment snapshot.",
        organ_overview_cards=overview_cards,
        available_result_types_intro="Tables and charts appear only when their specific certified source fields support them.",
        what_appears_intro="Organ pages retain the frozen visual family while unsupported fields remain explicitly unavailable.",
        important_reading_rule="NO_EVIDENCE, UNAVAILABLE, and CROSS_BOUNDARY_OVERLAP are evidence states; they do not by themselves prove organ non-use.",
        mixed_membership_scope_note=" ".join(overlap_notes) if overlap_notes else "No mixed contained-plus-overlap disclosure is required for this snapshot.",
        sp6_footer=f"Certified snapshot: {model.experiment_id}. The PDF is static after generation.",
    )

    def snapshot_dict(card: SnapshotCard):
        color = GREEN if card.status == AVAILABLE else MUTED
        return {"label": card.label, "icon": "doc", "value": card.value, "value_color": color, "caption": card.caption}

    def path_boxes(page: OrganRenderModel):
        boxes = []
        for label in page.pathway_labels[:9]:
            upper = label.upper()
            if "FINAL LOCK" in upper:
                boxes.append({"label": label, "icon": "lock", "fill": RED_BG, "ring": RED, "glyph": RED, "label_color": RED})
            elif "RETURN" in upper or "CLOSURE" in upper:
                boxes.append({"label": label, "icon": "check", "ring": GREEN, "glyph": GREEN})
            else:
                boxes.append({"label": label, "icon": "route", "ring": CYAN, "glyph": NAVY})
        return boxes

    def base(page: OrganRenderModel):
        point_count = len(page.chart.values)
        if page.organ == "MINE":
            chart_title = "MINE BRANCH DISTRIBUTION"
            if point_count == 1:
                chart_title += " | SINGLE CERTIFIED OBSERVATION"
        elif page.chart.status != AVAILABLE:
            chart_title = f"{page.organ} CHART | UNAVAILABLE"
        elif point_count == 1:
            chart_title = f"{page.organ} | SINGLE CERTIFIED OBSERVATION"
        else:
            chart_title = f"{page.organ} TREND GRAPH"
        return dict(
            intro=f"Certified {page.organ} results for experiment {model.experiment_id}.",
            snapshot_intro="Values below are based on certified evidence from this experiment.",
            snapshot_cards=[snapshot_dict(card) for card in page.snapshot_cards],
            footer=f"Certified snapshot {model.experiment_id}. {page.overlap_note}".strip(),
            discussion_note=page.discussion_note,
            chart_available=page.chart.status == AVAILABLE,
            chart_title=chart_title,
            chart_unavailable_message=f"{page.chart.status} -- {page.chart.reason}",
            table1_title=page.table1.title,
            table1_desc=page.table1.description,
            table1_rows=[page.table1.headers, *page.table1.rows[:PRIMARY_TABLE_ROW_CAPACITY]],
            table1_widths=page.table1.widths_mm,
            table2_title=page.table2.title,
            table2_desc=page.table2.description,
            table2_rows=[page.table2.headers, *page.table2.rows[:PRIMARY_TABLE_ROW_CAPACITY]],
            table2_widths=page.table2.widths_mm,
        )

    dynamic = {"sp6": sp6}
    for page in model.organ_pages:
        values = base(page)
        if page.organ == "SINE":
            normalized = [max(0.0, min(1.0, (value - 1.0) / 2.0)) for value in page.chart.values]
            values.update(
                journey_map_intro="Factual SINE displays are shown in certified order; same-stage retries remain distinct.",
                journey_boxes=path_boxes(page),
                chart_categories=[label[:12] for label in page.chart.categories],
                chart_series=[{"label": page.chart.observation_label, "values": normalized, "color": CYAN}],
                chart_y_labels=["SINE-1", "SINE-2", "SINE-3"],
            )
            dynamic["sp7"] = _NS(**values)
        elif page.organ == "MINE":
            values.update(
                pathway_intro="Only factual branch and closure values exposed by the certified MINE rows are shown.",
                pathway_boxes=path_boxes(page),
                chart_categories=[label.replace("I_WILL_COME_BACK", "RETURN").replace("ITS_IMPORTANT", "IMPORTANT")[:12] for label in page.chart.categories],
                chart_values=list(page.chart.values),
                chart_y_max=max(page.chart.values, default=1),
                chart_unit=page.chart.unit,
                chart_extra_series=[],
            )
            dynamic["sp8"] = _NS(**values)
        elif page.organ == "COSINE":
            values.update(
                pathway_intro="The pathway shows factual starting platforms, choices, and COSINE-owned closure values.",
                pathway_boxes=path_boxes(page),
                chart_categories=[label[:12] for label in page.chart.categories],
                chart_values=list(page.chart.values),
                chart_y_max=max(page.chart.values, default=1),
                chart_unit=page.chart.unit,
            )
            dynamic["sp9"] = _NS(**values)
        elif page.organ == "SECANT":
            dynamic["secant_results"] = _NS(**values)
        elif page.organ == "COSECANT":
            values.update(
                pathway_intro="Only certified COSECANT stages actually reached in this experiment are shown.",
                pathway_boxes=path_boxes(page),
                chart_categories=[label[:12] for label in page.chart.categories],
                chart_values=list(page.chart.values),
                chart_y_max=max(page.chart.values, default=1),
                chart_unit=page.chart.unit,
            )
            dynamic["sp10"] = _NS(**values)
    return dynamic


#: Which SP6 "Results Overview" organ card each organ-results page's own
#: "Data status" snapshot card must agree with.  Both describe the same
#: development fixture, so a mismatch here is always a fixture-authoring
#: bug, never a legitimate difference (Chief's Phase 3 fix-pass ruling).
_ORGAN_OVERVIEW_TO_RESULTS_PAGE: Final = {
    "SINE": "sp7",
    "MINE": "sp8",
    "COSINE": "sp9",
    "SECANT": "secant_results",
    "COSECANT": "sp10",
}


def _data_status_value(snapshot_cards: list[dict]) -> str | None:
    for card in snapshot_cards:
        if card.get("label") == "Data status":
            return card.get("value")
    return None


def _check_dev_fixture_consistency(fixtures: dict) -> None:
    """Fail loudly if SP6's per-organ status disagrees with that organ's own
    results page, rather than shipping a self-contradictory preview (Chief's
    Phase 3 fix-pass ruling item 5)."""

    overview_status = {
        card["organ"]: card["status"] for card in fixtures["sp6"].organ_overview_cards
    }
    for organ, page_key in _ORGAN_OVERVIEW_TO_RESULTS_PAGE.items():
        overview = overview_status.get(organ)
        page_status = _data_status_value(fixtures[page_key].snapshot_cards)
        if overview is None or page_status is None:
            raise MyelinReportError(
                f"Dev fixture consistency check could not find a status to compare for {organ}."
            )
        if overview != page_status:
            raise MyelinReportError(
                f"Dev fixture inconsistency: SP6 Results Overview shows {organ} as {overview!r} "
                f"but {page_key.upper()}'s own Data status card shows {page_status!r}."
            )


def _page_unavailable_organs(c, model: ReportRenderModel, *, physical_page: int) -> None:
    top, _ = _page_frame(c, page_code="UNAVAILABLE", chapter_label="Chapter 4 Results and Discussion")
    y = _chapter_title(c, top, "4", "UNAVAILABLE ORGAN RESULTS")
    y = _callout(
        c,
        y,
        "The following organs do not receive a quantitative result page for this certified experiment. "
        "No value, graph, or table is inferred.",
    )
    items = [
        {
            "organ": item.organ,
            "items": [f"State: {item.status}", f"Reason: {item.reason}"],
        }
        for item in model.unavailable_organs
    ]
    columns = 1 if len(items) == 1 else 2
    card_h = 48 * mm if len(items) == 1 else 42 * mm
    _grid_cards(c, MARGIN, y - 3 * mm, CONTENT_WIDTH, items, columns=columns, card_h=card_h,
                render_cell=_organ_availability_card)
    _footer(c, caption="No certified evidence = no result.", page_label=f"-- {physical_page}")


def _page_continuation(c, organ: OrganRenderModel, planned) -> None:
    table = organ.table1 if planned.table_number == 1 else organ.table2
    top, _ = _page_frame(c, page_code="CONTINUED", chapter_label="Chapter 4 Results and Discussion")
    y = _chapter_title(c, top, "4", f"{organ.organ} RESULTS AND DISCUSSION -- CONTINUED")
    y = _callout(c, y, f"TABLE {table.number} | {table.title}. Certified rows continue below.")
    _table(c, MARGIN, y - 3 * mm, table.widths_mm, [table.headers, *planned.rows], row_h=(14 if organ.organ == "SECANT" else 7.6) * mm)
    _footer(c, caption=f"Continuation of {organ.page_code}; table headers are repeated.",
            page_label=f"-- {planned.physical_page}")


def generate_report_pdf(source, output_path: str | Path) -> Path:
    """Generate one integration-preview PDF from explicit certified input.

    There is deliberately no default input and no development-fixture fallback.
    The final file is replaced only after a complete temporary PDF is saved.
    """

    model = adapt_certified_report_input(source)
    plan = plan_report_pages(model)
    fixtures = _build_report_fixtures(report_model=model)
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{secrets.token_hex(8)}.tmp")
    c = None
    try:
        c = pdfcanvas.Canvas(str(temporary), pagesize=A4, pageCompression=1)
        c.setTitle("MYELIN REPORT")
        c.setAuthor("MYELIN")
        c.setSubject(f"MYELIN certified integration preview -- experiment {model.experiment_id}")
        static_functions = {
            "STUDY_ORGANS": _page_study_organs, "SP1": _page_sp1, "SP2": _page_sp2, "SP3": _page_sp3, "SP4": _page_sp4, "SP5": _page_sp5,
            "SP11": _page_sp11, "SP12": _page_sp12, "SP13": _page_sp13, "SP14": _page_sp14,
        }
        organ_functions = {"SINE": _page_sp7, "MINE": _page_sp8, "COSINE": _page_sp9, "SECANT": _page_secant, "COSECANT": _page_sp10}
        organ_keys = {"SINE": "sp7", "MINE": "sp8", "COSINE": "sp9", "SECANT": "secant_results", "COSECANT": "sp10"}
        for planned in plan.pages:
            if planned.kind == "cover":
                _draw_cover(c, title="MYELIN REPORT",
                            subtitle="A Technical Report on Behavioral Monitoring, Intervention and Recovery with MYELIN",
                            tagline="guide  .  recover  .  focus")
            elif planned.kind == "static":
                fx = fixtures[planned.page_code.lower()]
                fx._physical_page = planned.physical_page
                static_functions[planned.page_code](c, fx)
            elif planned.kind == "overview":
                fixtures["sp6"]._physical_page = planned.physical_page
                _page_sp6(c, fixtures["sp6"])
            elif planned.kind == "organ":
                key = organ_keys[planned.organ]
                fixtures[key]._physical_page = planned.physical_page
                organ_functions[planned.organ](c, fixtures[key])
            elif planned.kind == "continuation":
                organ = model.organ_page(planned.organ)
                if organ is None:
                    raise MyelinReportError("continuation page lost its organ model")
                _page_continuation(c, organ, planned)
            elif planned.kind == "unavailable":
                _page_unavailable_organs(c, model, physical_page=planned.physical_page)
            else:
                raise MyelinReportError(f"unknown planned page kind: {planned.kind}")
            c.showPage()
        c.save()
        c = None
        os.replace(temporary, output)
    except Exception:
        if c is not None:
            try:
                c.save()
            except Exception:
                pass
        if temporary.exists():
            temporary.unlink()
        raise
    return output


def generate_dev_preview_pdf(output_path: str | Path) -> Path:
    """Phase 3 preview only: renders the full Cover + SP1-SP14 layout using
    the disposable dev fixtures above.  Not wired to any UI control.  Not
    called by any production path.  Causes zero database/network I/O --
    only reads the canonical logo PNG and writes the one output PDF.
    """

    fixtures = _build_dev_fixtures()
    _check_dev_fixture_consistency(fixtures)
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    c = pdfcanvas.Canvas(str(output), pagesize=A4, pageCompression=1)
    c.setTitle("MYELIN REPORT")
    c.setAuthor("MYELIN")
    c.setSubject("MYELIN REPORT -- Phase 3 visual-reconstruction preview (development fixtures)")

    _draw_cover(c, title="MYELIN REPORT",
                subtitle="A Technical Report on Behavioral Monitoring, Intervention and Recovery with MYELIN",
                tagline="guide  .  recover  .  focus")
    c.showPage()

    pages = [
        _page_sp1, _page_sp2, _page_sp3, _page_study_organs, _page_sp4, _page_sp5, _page_sp6, _page_sp7,
        _page_sp8, _page_sp9, _page_secant, _page_sp10, _page_sp11, _page_sp12, _page_sp13, _page_sp14,
    ]
    keys = ["sp1", "sp2", "sp3", "study_organs", "sp4", "sp5", "sp6", "sp7", "sp8", "sp9", "secant_results", "sp10", "sp11", "sp12", "sp13", "sp14"]
    for physical, (page_fn, key) in enumerate(zip(pages, keys), start=2):
        fixtures[key]._physical_page = physical
        page_fn(c, fixtures[key])
        c.showPage()

    c.save()
    return output
