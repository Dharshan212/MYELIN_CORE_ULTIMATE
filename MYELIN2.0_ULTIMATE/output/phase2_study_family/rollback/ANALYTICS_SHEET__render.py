"""A4 PDF renderer for the MYELIN Analytics Sheet (reportlab, no database access).

The visual language follows Chief's three references: charcoal pages, white
headings, orange accents, readable cards and clean tables.  Every value shown
comes from ``ANALYTICS_SHEET.model``; this module only lays it out.

Text is real, selectable PDF text (embedded TrueType).  Nothing is rasterised
except the official MYELIN logo.
"""

from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table as RlTable,
    TableStyle,
)

from .model import (
    Card,
    CardRow,
    Cell,
    EmptyState,
    Heading,
    Note,
    Record,
    ReportModel,
    Section,
    Table,
    build_report,
)

PAGE_W, PAGE_H = A4
MARGIN_X: Final = 40.0
MARGIN_TOP: Final = 66.0
MARGIN_BOTTOM: Final = 58.0
CONTENT_W: Final = PAGE_W - 2 * MARGIN_X

BG: Final = HexColor("#1e1f22")
PANEL: Final = HexColor("#26282c")
PANEL_HI: Final = HexColor("#2f3237")
LINE: Final = HexColor("#3a3d43")
ORANGE: Final = HexColor("#f57c1f")
ORANGE_DIM: Final = HexColor("#a5541a")
WHITE: Final = HexColor("#ffffff")
TEXT: Final = HexColor("#e8e9ec")
MUTED: Final = HexColor("#a4a8b1")

TONES: Final = {
    "ok": ("#1d5a33", "#bdf5d0", "#2f8a4f"),
    "warn": ("#6a4a12", "#ffdc94", "#a37a20"),
    "bad": ("#6c2222", "#ffc4c4", "#a63b3b"),
    "neutral": ("#33363c", "#e2e4e9", "#4a4e56"),
    "muted": ("#2a2c31", "#9da1ab", "#3d4047"),
    "accent": ("#763a0d", "#ffcfa5", "#b0561a"),
}
TONE_VALUE: Final = {"ok": "#7ff0a6", "warn": "#ffc55c", "bad": "#ff9a9a", "muted": "#9da1ab", "": "#ffffff"}

TAGLINE: Final = "OBSERVE  \u00b7  UNDERSTAND  \u00b7  NUDGE  \u00b7  RECOVER  \u00b7  REPEAT"
DEFAULT_LOGO: Final = Path(__file__).resolve().parent.parent / "ASSETS" / "images" / "Myelin_Report_Logo.png"
WINDOWS_FONTS: Final = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"


class ReportAssetError(RuntimeError):
    """The official logo (or another required asset) is missing."""


class ReportVerificationError(RuntimeError):
    """The generated file failed its post-build checks."""


@dataclass(slots=True)
class BuildResult:
    path: Path
    pages: int
    substituted: tuple[str, ...] = ()
    fonts: tuple[str, str] = ("", "")


# --------------------------------------------------------------------------
# Fonts (system TrueType, embedded as subsets; Helvetica/Courier fallback)
# --------------------------------------------------------------------------

_FONT_STATE: dict[str, object] = {}


def _register_fonts() -> dict[str, str]:
    if "names" in _FONT_STATE:
        return _FONT_STATE["names"]  # type: ignore[return-value]
    names = {"body": "Helvetica", "bold": "Helvetica-Bold", "semi": "Helvetica-Bold",
             "italic": "Helvetica-Oblique", "mono": "Courier", "mono_bold": "Courier-Bold", "ttf": ""}
    candidates = (
        ("MYL-Body", "segoeui.ttf", "MYL-Bold", "segoeuib.ttf", "MYL-Semi", "seguisb.ttf", "MYL-Italic", "segoeuii.ttf"),
        ("MYL-Body", "arial.ttf", "MYL-Bold", "arialbd.ttf", "MYL-Semi", "arialbd.ttf", "MYL-Italic", "ariali.ttf"),
        ("MYL-Body", "DejaVuSans.ttf", "MYL-Bold", "DejaVuSans-Bold.ttf", "MYL-Semi", "DejaVuSans-Bold.ttf", "MYL-Italic", "DejaVuSans-Oblique.ttf"),
    )
    for group in candidates:
        try:
            for i in range(0, len(group), 2):
                pdfmetrics.registerFont(TTFont(group[i], str(WINDOWS_FONTS / group[i + 1])))
        except Exception:  # noqa: BLE001 - try the next family
            continue
        pdfmetrics.registerFontFamily("MYL-Body", normal="MYL-Body", bold="MYL-Bold", italic="MYL-Italic", boldItalic="MYL-Bold")
        names.update(body="MYL-Body", bold="MYL-Bold", semi="MYL-Semi", italic="MYL-Italic", ttf=group[1])
        break
    for mono, mono_bold, file_a, file_b in (("MYL-Mono", "MYL-MonoBold", "consola.ttf", "consolab.ttf"),):
        try:
            pdfmetrics.registerFont(TTFont(mono, str(WINDOWS_FONTS / file_a)))
            pdfmetrics.registerFont(TTFont(mono_bold, str(WINDOWS_FONTS / file_b)))
            names.update(mono=mono, mono_bold=mono_bold)
        except Exception:  # noqa: BLE001
            pass
    _FONT_STATE["names"] = names
    return names


def font_names() -> dict[str, str]:
    return _register_fonts()


class _Glyphs:
    """Substitute characters the embedded font cannot draw, and remember them."""

    def __init__(self) -> None:
        self.missing: set[str] = set()
        names = font_names()
        try:
            self.face = pdfmetrics.getFont(names["body"]).face
            self.covered = set(getattr(self.face, "charToGlyph", {}).keys())
        except Exception:  # noqa: BLE001 - base-14 font: Latin-1 + WinAnsi punctuation
            self.face = None
            self.covered = set()
        self.marker = "\u25a1" if (not self.covered or 0x25A1 in self.covered) else "?"

    def ok(self, ch: str) -> bool:
        code = ord(ch)
        if code < 0x80 or ch in "\n\t":
            return True
        if self.face is None:
            return code < 0x100 or ch in "\u2013\u2014\u2018\u2019\u201c\u201d\u2022\u2026\u00b7"
        return code in self.covered

    def clean(self, text: str) -> str:
        if all(self.ok(c) for c in text):
            return text
        out = []
        for ch in text:
            if self.ok(ch):
                out.append(ch)
            else:
                self.missing.add(ch)
                out.append(self.marker)
        return "".join(out)


# --------------------------------------------------------------------------
# Styles and small flowables
# --------------------------------------------------------------------------


class _Styles:
    def __init__(self) -> None:
        f = font_names()
        base = dict(fontName=f["body"], textColor=TEXT, leading=11, fontSize=8.4)
        self.f = f
        self.body = ParagraphStyle("body", **base)
        self.right = ParagraphStyle("right", parent=self.body, alignment=TA_RIGHT)
        self.header = ParagraphStyle("header", parent=self.body, fontName=f["bold"], textColor=WHITE, fontSize=7.8, leading=9.5)
        self.header_right = ParagraphStyle("header_right", parent=self.header, alignment=TA_RIGHT)
        self.title = ParagraphStyle("title", parent=self.body, fontName=f["bold"], textColor=WHITE, fontSize=11.5, leading=14, spaceBefore=10, spaceAfter=4)
        self.h2 = ParagraphStyle("h2", parent=self.body, fontName=f["bold"], textColor=WHITE, fontSize=14, leading=17, spaceBefore=12, spaceAfter=1, keepWithNext=1)
        self.h2_sub = ParagraphStyle("h2s", parent=self.body, textColor=MUTED, fontSize=8.6, leading=11, spaceAfter=5, keepWithNext=1)
        self.note = ParagraphStyle("note", parent=self.body, textColor=MUTED, fontSize=7.8, leading=10, spaceBefore=3, spaceAfter=6)
        self.note_box = ParagraphStyle("notebox", parent=self.body, textColor=TEXT, fontSize=8.6, leading=11.5)


class Badge(Flowable):
    """A small rounded status pill; shrinks its text rather than overflowing."""

    def __init__(self, text: str, tone: str, glyphs: _Glyphs) -> None:
        super().__init__()
        self.text = glyphs.clean(text)
        self.tone = tone if tone in TONES else "neutral"
        self.font = font_names()["bold"]
        self.size = 7.0
        self.pad = 5.0
        self.hgt = 12.0

    def wrap(self, availWidth, availHeight):  # noqa: N802 - reportlab API
        natural = pdfmetrics.stringWidth(self.text, self.font, self.size) + 2 * self.pad
        self.width_used = min(natural, availWidth)
        self.draw_size = self.size
        if natural > availWidth:
            self.draw_size = max(5.0, self.size * (availWidth - 2 * self.pad) / max(1.0, natural - 2 * self.pad))
        return self.width_used, self.hgt

    def draw(self):
        bg, fg, edge = TONES[self.tone]
        c = self.canv
        c.setFillColor(HexColor(bg))
        c.setStrokeColor(HexColor(edge))
        c.setLineWidth(0.5)
        c.roundRect(0, 0, self.width_used, self.hgt, 5.5, fill=1, stroke=1)
        c.setFillColor(HexColor(fg))
        c.setFont(self.font, self.draw_size)
        c.drawCentredString(self.width_used / 2, 3.3, self.text)


class SectionTitle(Flowable):
    def __init__(self, key: str, title: str, subtitle: str, glyphs: _Glyphs, appendix: bool = False) -> None:
        super().__init__()
        self.key, self.title, self.subtitle = key, glyphs.clean(title), glyphs.clean(subtitle)
        self.appendix = appendix
        self.f = font_names()

    def wrap(self, availWidth, availHeight):  # noqa: N802
        self.avail = availWidth
        return availWidth, 74

    def draw(self):
        c = self.canv
        size = 30.0
        while pdfmetrics.stringWidth(self.title, self.f["bold"], size) > self.avail and size > 14:
            size -= 1
        c.setFillColor(WHITE)
        c.setFont(self.f["bold"], size)
        c.drawString(0, 40, self.title)
        c.setFillColor(MUTED)
        sub_size = 10.5
        while pdfmetrics.stringWidth(self.subtitle, self.f["body"], sub_size) > self.avail and sub_size > 7:
            sub_size -= 0.5
        c.setFont(self.f["body"], sub_size)
        c.drawString(0, 22, self.subtitle)
        c.setStrokeColor(ORANGE)
        c.setLineWidth(2.2)
        c.line(0, 8, 64, 8)


class EmptyStateFlowable(Flowable):
    """Centred panel used for \u201cNo episode recorded\u201d and \u201cEvidence unavailable\u201d."""

    def __init__(self, state: EmptyState, glyphs: _Glyphs) -> None:
        super().__init__()
        self.title = glyphs.clean(state.title)
        self.detail = glyphs.clean(state.detail)
        self.tone = state.tone
        self.f = font_names()

    def wrap(self, availWidth, availHeight):  # noqa: N802
        self.avail = availWidth
        self.lines = simpleSplit(self.detail, self.f["body"], 9.2, availWidth - 90)
        self.hgt = 92 + 12 * len(self.lines)
        return availWidth, self.hgt

    def draw(self):
        c = self.canv
        edge = HexColor("#a37a20") if self.tone == "warn" else LINE
        c.setFillColor(PANEL)
        c.setStrokeColor(edge)
        c.setLineWidth(0.8)
        c.roundRect(0, 0, self.avail, self.hgt, 9, fill=1, stroke=1)
        cx = self.avail / 2
        top = self.hgt
        c.setStrokeColor(ORANGE if self.tone != "warn" else HexColor("#ffc55c"))
        c.setLineWidth(1.3)
        c.roundRect(cx - 9, top - 34, 18, 20, 4, fill=0, stroke=1)
        c.line(cx - 4, top - 22, cx + 4, top - 22)
        c.line(cx - 4, top - 27, cx + 2, top - 27)
        c.setFillColor(WHITE)
        c.setFont(self.f["bold"], 16)
        c.drawCentredString(cx, top - 56, self.title)
        c.setFillColor(MUTED)
        c.setFont(self.f["body"], 9.2)
        y = top - 74
        for line in self.lines:
            c.drawCentredString(cx, y, line)
            y -= 12


class CardRowFlowable(Flowable):
    def __init__(self, row: CardRow, glyphs: _Glyphs) -> None:
        super().__init__()
        self.cards = [Card(glyphs.clean(c.label), glyphs.clean(c.value), glyphs.clean(c.caption), c.tone) for c in row.cards]
        self.f = font_names()

    def wrap(self, availWidth, availHeight):  # noqa: N802
        self.avail = availWidth
        return availWidth, 68

    def draw(self):
        c = self.canv
        n = 4
        gap = 8.0
        w = (self.avail - gap * (n - 1)) / n
        for i, card in enumerate(self.cards):
            x = i * (w + gap)
            c.setFillColor(PANEL)
            c.setStrokeColor(LINE)
            c.setLineWidth(0.6)
            c.roundRect(x, 4, w, 60, 6, fill=1, stroke=1)
            c.setFillColor(ORANGE)
            c.roundRect(x, 4, 3.2, 60, 1.6, fill=1, stroke=0)
            inner = w - 20
            c.setFillColor(MUTED)
            size = 7.0
            label = card.label.upper()
            while pdfmetrics.stringWidth(label, self.f["semi"], size) > inner and size > 5:
                size -= 0.3
            c.setFont(self.f["semi"], size)
            c.drawString(x + 12, 51, label)
            value_size = 20.0
            while pdfmetrics.stringWidth(card.value, self.f["bold"], value_size) > inner and value_size > 9:
                value_size -= 0.5
            c.setFillColor(HexColor(TONE_VALUE.get(card.tone, "#ffffff")))
            c.setFont(self.f["bold"], value_size)
            c.drawString(x + 12, 28, card.value)
            c.setFillColor(MUTED)
            cap_size = 6.8
            while pdfmetrics.stringWidth(card.caption, self.f["body"], cap_size) > inner and cap_size > 4.6:
                cap_size -= 0.2
            c.setFont(self.f["body"], cap_size)
            c.drawString(x + 12, 12, card.caption)


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


class _Builder:
    def __init__(self) -> None:
        self.st = _Styles()
        self.glyphs = _Glyphs()
        self.f = self.st.f

    # -- cells -----------------------------------------------------------------

    def _markup(self, cell: Cell, base_size: float) -> str:
        text = escape(self.glyphs.clean(cell.text))
        size = 6.5 if cell.tiny else (base_size - 0.9 if cell.small else base_size)
        font = self.f["mono_bold" if cell.bold else "mono"] if cell.mono else (self.f["bold"] if cell.bold else self.f["body"])
        out = f'<font name="{font}" size="{size}">{text}</font>'
        if cell.sub:
            sub_font = self.f["mono"] if cell.sub_mono else self.f["body"]
            out += f'<br/><font name="{sub_font}" size="6.2" color="#9da1ab">{escape(self.glyphs.clean(cell.sub))}</font>'
        return out

    def cell(self, cell: Cell | str, align: str, header: bool = False):
        if isinstance(cell, str):
            cell = Cell(cell)
        if cell.tone and not header:
            return Badge(cell.text, cell.tone, self.glyphs)
        style = self.st.right if align == "r" else self.st.body
        return Paragraph(self._markup(cell, 8.4), style)

    # -- tables ----------------------------------------------------------------

    def table(self, t: Table, *, first_title: bool = True) -> list:
        st = self.st
        total = sum(t.widths) or 1.0
        widths = [CONTENT_W * w / total for w in t.widths]
        ncols = len(t.columns)
        aligns = list(t.align) + ["l"] * (ncols - len(t.align))
        out: list = []
        if t.title:
            out.append(Paragraph(escape(self.glyphs.clean(t.title)), st.title))
        if not t.rows:
            out.append(self._note_box(t.empty, "info"))
            return out
        data = []
        if t.header:
            data.append([Paragraph(escape(self.glyphs.clean(c)), st.header_right if aligns[i] == "r" else st.header) for i, c in enumerate(t.columns)])
        for row in t.rows:
            data.append([self.cell(c, aligns[i]) for i, c in enumerate(row)])
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4.5),
            ("TOPPADDING", (0, 0), (-1, -1), 2.1 if t.dense else 3.2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.3 if t.dense else 3.4),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
            ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ]
        body_start = 1 if t.header else 0
        if t.header:
            style += [("BACKGROUND", (0, 0), (-1, 0), PANEL_HI), ("LINEBELOW", (0, 0), (-1, 0), 1.0, ORANGE_DIM)]
        style.append(("ROWBACKGROUNDS", (0, body_start), (-1, -1), [HexColor("#232529"), HexColor("#1d1e21")]))
        if not t.header:
            style.append(("BACKGROUND", (0, 0), (0, -1), PANEL_HI))
        table = RlTable(data, colWidths=widths, repeatRows=1 if t.header else 0, splitByRow=1)
        table.setStyle(TableStyle(style))
        out.append(table)
        if t.note:
            out.append(Paragraph(escape(self.glyphs.clean(t.note)), st.note))
        else:
            out.append(Spacer(1, 6))
        return out

    def keep(self, flowables: list, rows: int, limit: int = 12) -> list:
        if rows <= limit:
            return [KeepTogether(flowables)]
        return [CondPageBreak(90), *flowables]

    # -- notes and headings -----------------------------------------------------

    def _note_box(self, text: str, tone: str):
        para = Paragraph(escape(self.glyphs.clean(text)), self.st.note_box)
        box = RlTable([[para]], colWidths=[CONTENT_W])
        edge = HexColor("#c98a1e") if tone == "warn" else ORANGE
        box.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, edge),
                    ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        return KeepTogether([box, Spacer(1, 6)])

    def heading_flowables(self, h: Heading) -> list:
        out = [Paragraph(escape(self.glyphs.clean(h.text)), self.st.h2)]
        if h.sub:
            out.append(Paragraph(escape(self.glyphs.clean(h.sub)), self.st.h2_sub))
        return out

    def heading(self, h: Heading) -> list:
        """A heading with no record after it (a record heading is bound to its record by ``record``)."""

        return [CondPageBreak(230), *self.heading_flowables(h)]

    @staticmethod
    def _measure(flowables: list) -> float:
        """Height the flowables need at the content width, including paragraph spacing."""

        total = 0.0
        for f in flowables:
            _w, h = f.wrap(CONTENT_W, 1_000_000)
            total += h + f.getSpaceBefore() + f.getSpaceAfter()
        return total

    @staticmethod
    def _leading_rows_height(flowables: list, rows: int = 3) -> float:
        """Measured height of the first table rows (header row included) so a table never starts alone."""

        for f in flowables:
            if isinstance(f, RlTable):
                f.wrap(CONTENT_W, 1_000_000)
                return float(sum(getattr(f, "_rowHeights", ())[:rows]))
        return 0.0

    # -- records ----------------------------------------------------------------

    def record(self, r: Record, lead: list | None = None) -> list:
        st = self.st
        lead = list(lead or ())
        badges = [Badge(b.text, b.tone or "neutral", self.glyphs) for b in r.badges]
        badge_cells = [[b for b in badges]] if badges else [[""]]
        inner = RlTable(badge_cells, colWidths=[None] * len(badges) if badges else None)
        inner.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
        title = Paragraph(f'<font name="{self.f["bold"]}" size="10.5" color="#ffffff">{escape(self.glyphs.clean(r.title))}</font>', st.body)
        head = RlTable([[title, inner]], colWidths=[CONTENT_W * 0.52, CONTENT_W * 0.48])
        head.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), PANEL_HI),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, ORANGE),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        flow: list = [head]
        per_row = 6
        facts = list(r.facts)
        grid = []
        for i in range(0, len(facts), per_row):
            row = []
            for label, value in facts[i : i + per_row]:
                row.append(
                    Paragraph(
                        f'<font name="{self.f["semi"]}" size="6.2" color="#a4a8b1">{escape(self.glyphs.clean(label.upper()))}</font><br/>'
                        f'<font name="{self.f["body"]}" size="8.2">{escape(self.glyphs.clean(value))}</font>',
                        st.body,
                    )
                )
            row += [""] * (per_row - len(row))
            grid.append(row)
        if grid:
            facts_table = RlTable(grid, colWidths=[CONTENT_W / per_row] * per_row)
            facts_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), PANEL),
                        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 9),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            flow.append(facts_table)
        if r.ids:
            line = "   ".join(
                f'<font name="{self.f["semi"]}" size="6.2" color="#a4a8b1">{escape(self.glyphs.clean(k.upper()))}</font> '
                f'<font name="{self.f["mono"]}" size="6.6" color="#d6d8dd">{escape(self.glyphs.clean(v))}</font>'
                for k, v in r.ids
            )
            id_box = RlTable([[Paragraph(line, st.body)]], colWidths=[CONTENT_W])
            id_box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PANEL), ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            flow.append(id_box)
        table_flow = self.table(r.table)
        if r.caption:
            table_flow.append(Paragraph(escape(self.glyphs.clean(r.caption)), st.note))
        for extra in r.extra:
            table_flow.extend(self.table(extra))
        # Keep a record on one page when its estimated height is modest;
        # longer records flow across pages with their table header repeated.
        # ``lead`` is the chapter's "Episode records" heading: it travels with the
        # record so it can never be left at the foot of a page by itself.
        estimate = 120.0
        for row in r.table.rows:
            estimate += 17.0 + (9.0 if any(c.sub for c in row) else 0.0) + (10.0 * (max(len(c.text) for c in row) // 45))
        if estimate <= 300.0:
            return [KeepTogether([*lead, *flow, *table_flow, Spacer(1, 8)])]
        if lead:
            # A long record may break across pages, but never before its heading,
            # its title block and the first table rows fit together.
            needed = self._measure([*lead, *flow]) + self._leading_rows_height(table_flow)
            return [CondPageBreak(max(160.0, needed)), *lead, *flow, *table_flow, Spacer(1, 8)]
        return [CondPageBreak(160), *flow, *table_flow, Spacer(1, 8)]

    # -- story --------------------------------------------------------------------

    def block(self, b) -> list:
        if isinstance(b, CardRow):
            return [CardRowFlowable(b, self.glyphs), Spacer(1, 6)]
        if isinstance(b, Note):
            return [self._note_box(b.text, b.tone)]
        if isinstance(b, EmptyState):
            return [EmptyStateFlowable(b, self.glyphs), Spacer(1, 8)]
        if isinstance(b, Heading):
            return self.heading(b)
        if isinstance(b, Table):
            return self.keep(self.table(b), len(b.rows))
        if isinstance(b, Record):
            return self.record(b)
        raise TypeError(f"unsupported block {type(b).__name__}")

    def story(self, model: ReportModel) -> list:
        story: list = [NextPageTemplate("content"), PageBreak()]
        for index, section in enumerate(model.sections):
            if index:
                story.append(PageBreak())
            story.append(SectionTitle(section.key, section.title, section.subtitle, self.glyphs, section.appendix))
            blocks = list(section.blocks)
            position = 0
            while position < len(blocks):
                block = blocks[position]
                following = blocks[position + 1] if position + 1 < len(blocks) else None
                if isinstance(block, Heading) and isinstance(following, Record):
                    story.extend(self.record(following, lead=self.heading_flowables(block)))
                    position += 2
                    continue
                story.extend(self.block(block))
                position += 1
        if self.glyphs.missing:
            chars = ", ".join(f"U+{ord(c):04X}" for c in sorted(self.glyphs.missing))
            story.append(
                self._note_box(
                    f"Rendering note: {len(self.glyphs.missing)} character(s) recorded in the evidence are outside the report font and are shown as "
                    f"\u201c{self.glyphs.marker}\u201d ({chars}). The recorded evidence itself is unchanged.",
                    "warn",
                )
            )
        return story


# --------------------------------------------------------------------------
# Page chrome, cover and wave
# --------------------------------------------------------------------------


def _draw_wave(c: rl_canvas.Canvas, x0: float, x1: float, y_mid: float, amplitude: float, seed: float, lines: int = 64) -> None:
    """A twisting ribbon of fine orange lines (vector)."""

    steps = 90
    for i in range(lines):
        t = i / (lines - 1)
        points = []
        for s in range(steps + 1):
            u = s / steps
            x = x0 + (x1 - x0) * u
            a = math.sin(u * math.pi * 2.1 + seed) * amplitude
            b = math.sin(u * math.pi * 2.1 + seed + 1.15 + 0.5 * math.sin(u * 3.0)) * amplitude * 0.75
            twist = (0.5 + 0.5 * math.sin(u * math.pi * 3.0 + seed * 0.7)) * amplitude * 0.5
            y = y_mid + a * (1 - t) + b * t + twist * (t - 0.5) * 1.2
            points.append((x, y))
        alpha = 0.28 + 0.5 * (1 - abs(t - 0.5) * 2)
        c.setStrokeColor(Color(0.96, 0.49 + 0.18 * t, 0.12, alpha=alpha))
        c.setLineWidth(0.35 + 0.25 * (1 - abs(t - 0.5) * 2))
        p = c.beginPath()
        p.moveTo(*points[0])
        for pt in points[1:]:
            p.lineTo(*pt)
        c.drawPath(p, stroke=1, fill=0)


def _icon(c, kind: str, cx: float, cy: float) -> None:
    c.setStrokeColor(ORANGE)
    c.setFillColor(ORANGE)
    c.setLineWidth(1.1)
    c.circle(cx, cy, 13, stroke=1, fill=0)
    c.setLineWidth(1.3)
    if kind == "MINE":
        body = c.beginPath()
        body.roundRect(cx - 8, cy - 4, 16, 11, 4)
        c.drawPath(body, stroke=1, fill=0)
        tail = c.beginPath()
        tail.moveTo(cx - 4, cy - 4); tail.lineTo(cx - 6, cy - 9); tail.lineTo(cx + 1, cy - 4)
        c.drawPath(tail, stroke=1, fill=0)
        for dx in (-3.5, 0, 3.5):
            c.circle(cx + dx, cy + 1.5, 0.9, stroke=0, fill=1)
    elif kind == "STUDY MODE":
        p = c.beginPath()
        p.moveTo(cx, cy + 5); p.curveTo(cx - 3, cy + 8, cx - 6, cy + 8, cx - 9, cy + 6)
        p.lineTo(cx - 9, cy - 6); p.curveTo(cx - 6, cy - 4, cx - 3, cy - 4, cx, cy - 7)
        p.curveTo(cx + 3, cy - 4, cx + 6, cy - 4, cx + 9, cy - 6)
        p.lineTo(cx + 9, cy + 6); p.curveTo(cx + 6, cy + 8, cx + 3, cy + 8, cx, cy + 5)
        c.drawPath(p, stroke=1, fill=0)
        c.line(cx, cy + 5, cx, cy - 7)
    elif kind == "MIRL":
        p = c.beginPath()
        p.moveTo(cx - 9, cy); p.lineTo(cx - 4, cy); p.lineTo(cx - 2, cy + 7)
        p.lineTo(cx + 2, cy - 7); p.lineTo(cx + 4, cy); p.lineTo(cx + 9, cy)
        c.drawPath(p, stroke=1, fill=0)
    elif kind == "COSINE":
        pts = [(cx, cy + 7), (cx - 7, cy - 5), (cx + 7, cy - 5)]
        c.line(*pts[0], *pts[1]); c.line(*pts[0], *pts[2])
        for x, y in pts:
            c.circle(x, y, 2.4, stroke=0, fill=1)
    else:  # Evidence Integrity
        p = c.beginPath()
        p.moveTo(cx, cy + 9); p.lineTo(cx + 7, cy + 6); p.lineTo(cx + 7, cy - 1)
        p.curveTo(cx + 7, cy - 6, cx + 3, cy - 8, cx, cy - 10)
        p.curveTo(cx - 3, cy - 8, cx - 7, cy - 6, cx - 7, cy - 1)
        p.lineTo(cx - 7, cy + 6); p.close()
        c.drawPath(p, stroke=1, fill=0)
        c.line(cx - 3, cy - 1, cx - 0.5, cy - 4); c.line(cx - 0.5, cy - 4, cx + 4, cy + 3)


class _Chrome:
    def __init__(self, model: ReportModel, logo: ImageReader, glyphs: _Glyphs) -> None:
        self.model, self.logo, self.glyphs = model, logo, glyphs
        self.f = font_names()
        self.total = 0

    def page_tag(self, c, page: int) -> None:
        f = self.f
        size, space = 7.0, 1.5
        label, number, tail = "PAGE  ", f"{page}", f"  OF  {self.total or page}"

        def width(s):
            return pdfmetrics.stringWidth(s, f["body"], size) + space * len(s)

        x = PAGE_W - MARGIN_X - (width(label) + width(number) + width(tail))
        t = c.beginText()
        t.setCharSpace(space)
        t.setTextOrigin(x, PAGE_H - 38)
        t.setFont(f["body"], size); t.setFillColor(MUTED); t.textOut(label)
        t.setFont(f["bold"], size); t.setFillColor(ORANGE); t.textOut(number)
        t.setFont(f["body"], size); t.setFillColor(MUTED); t.textOut(tail)
        t.setCharSpace(0)
        c.drawText(t)

    def _logo_at(self, c, x, y, size) -> None:
        c.drawImage(self.logo, x, y, width=size, height=size, mask="auto", preserveAspectRatio=True)

    def _spaced(self, c, text, x, y, font, size, color, space=1.4, align="l") -> None:
        text = self.glyphs.clean(text)
        c.setFillColor(color)
        t = c.beginText()
        t.setFont(font, size)
        t.setCharSpace(space)
        width = pdfmetrics.stringWidth(text, font, size) + space * len(text)
        if align == "r":
            x -= width
        t.setTextOrigin(x, y)
        t.textOut(text)
        t.setCharSpace(0)
        c.drawText(t)

    def footer(self, c) -> None:
        c.setStrokeColor(ORANGE)
        c.setLineWidth(1.0)
        c.line(0, 46, PAGE_W, 46)
        self._logo_at(c, MARGIN_X - 4, 8, 32)
        self._spaced(c, "MYELIN", MARGIN_X + 32, 20, self.f["body"], 13, WHITE, 3.2)
        self._spaced(c, TAGLINE, PAGE_W - MARGIN_X, 21, self.f["body"], 6.4, MUTED, 1.2, "r")

    def content_page(self, c, doc) -> None:
        c.saveState()
        c.setFillColor(BG)
        c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        self._spaced(c, "MYELIN ANALYTICS SHEET", MARGIN_X, PAGE_H - 38, self.f["body"], 8.6, WHITE, 2.4)
        c.setStrokeColor(ORANGE)
        c.setLineWidth(1.2)
        c.line(0, PAGE_H - 46, 150, PAGE_H - 46)
        self._spaced(c, self.model.period_text.upper(), PAGE_W - MARGIN_X - 118, PAGE_H - 38, self.f["body"], 6.6, MUTED, 1.4, "r")
        self.footer(c)
        self._banner(c)
        self.page_tag(c, doc.page)
        c.restoreState()

    def _banner(self, c) -> None:
        if not self.model.sample_banner:
            return
        text = self.glyphs.clean(self.model.sample_banner)
        width = pdfmetrics.stringWidth(text, self.f["bold"], 8) + 22
        c.setFillColor(ORANGE)
        c.roundRect((PAGE_W - width) / 2, PAGE_H - 24, width, 15, 3, stroke=0, fill=1)
        c.setFillColor(HexColor("#1e1f22"))
        c.setFont(self.f["bold"], 8)
        c.drawCentredString(PAGE_W / 2, PAGE_H - 19.2, text)

    def cover_page(self, c, doc) -> None:
        m = self.model
        c.saveState()
        c.setFillColor(BG)
        c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        self._spaced(c, "MYELIN ANALYTICS SHEET", MARGIN_X + 2, PAGE_H - 46, self.f["body"], 10, WHITE, 2.8)
        c.setStrokeColor(ORANGE)
        c.setLineWidth(1.4)
        c.line(0, PAGE_H - 58, 190, PAGE_H - 58)
        # official logo, native proportions (square asset)
        self._logo_at(c, PAGE_W - MARGIN_X - 86, PAGE_H - 178, 92)
        # title
        c.setFillColor(WHITE)
        c.setFont(self.f["bold"], 92)
        c.drawString(MARGIN_X - 2, PAGE_H - 190, "MYELIN")
        c.setFillColor(ORANGE)
        c.setFont(self.f["bold"], 30)
        c.drawString(MARGIN_X + 2, PAGE_H - 238, "2.0")
        c.setFillColor(WHITE)
        size = 50
        while pdfmetrics.stringWidth("Analytics Sheet", self.f["bold"], size) > CONTENT_W:
            size -= 1
        c.setFont(self.f["bold"], size)
        c.drawString(MARGIN_X - 2, PAGE_H - 292, "Analytics Sheet")
        c.setFillColor(ORANGE)
        c.setFont(self.f["body"], 30)
        c.drawString(MARGIN_X, PAGE_H - 336, "Behavioural Data Report")
        c.setFillColor(TEXT)
        c.setFont(self.f["body"], 11.2)
        y = PAGE_H - 370
        for line in (
            "A structured presentation of recorded behavioural evidence:",
            "summaries, episode timelines and evidence integrity.",
            "Read-only, non-clinical software evidence.",
        ):
            c.drawString(MARGIN_X, y, self.glyphs.clean(line))
            y -= 16
        _draw_wave(c, -10, PAGE_W + 10, 350, 62, 0.4, 64)
        _draw_wave(c, -10, PAGE_W + 10, 336, 38, 2.2, 40)
        # sections and metadata
        yy = 246
        for name in m.cover_items:
            _icon(c, name, MARGIN_X + 14, yy)
            c.setFillColor(WHITE)
            c.setFont(self.f["body"], 12)
            c.drawString(MARGIN_X + 40, yy - 4, self.glyphs.clean(name))
            yy -= 40
        x = PAGE_W - MARGIN_X - 240
        rows = (("REPORTING PERIOD", m.period_text), ("GENERATED", m.generated_label), ("ORGANS", f"{len(m.cover_items)} selected"))
        yy = 246
        for label, value in rows:
            self._spaced(c, label, x, yy, self.f["semi"], 7.2, MUTED, 1.6)
            c.setFillColor(WHITE)
            v = self.glyphs.clean(value)
            fs = 13
            while pdfmetrics.stringWidth(v, self.f["bold"], fs) > 240 and fs > 8:
                fs -= 0.5
            c.setFont(self.f["bold"], fs)
            c.drawString(x, yy - 17, v)
            yy -= 44
        c.setFillColor(MUTED)
        c.setFont(self.f["body"], 7.4)
        c.drawString(x, 110, "Only records inside the selected period are included.")
        self.footer(c)
        self._banner(c)
        self.page_tag(c, doc.page)
        c.restoreState()


class _Doc(BaseDocTemplate):
    def afterFlowable(self, flowable) -> None:  # noqa: N802
        if isinstance(flowable, SectionTitle):
            key = f"sec-{flowable.key}-{self.page}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(flowable.title, key, 1 if flowable.appendix else 0, 0)


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


def _load_logo(path: Path) -> ImageReader:
    if not path.is_file():
        raise ReportAssetError("Official MYELIN logo asset is missing.")
    try:
        from PIL import Image

        image = Image.open(path).convert("RGBA")
        if max(image.size) > 512:
            image = image.resize((512, int(512 * image.height / image.width)) if image.width >= image.height else (int(512 * image.width / image.height), 512), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        buffer.seek(0)
        return ImageReader(buffer)
    except ImportError:
        return ImageReader(str(path))


def verify_pdf(path: Path, expected_pages: int) -> int:
    data = Path(path).read_bytes()
    if not data.startswith(b"%PDF") or b"%%EOF" not in data[-2048:]:
        raise ReportVerificationError("PDF header or trailer is missing")
    import re

    pages = len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", data))
    if pages < 1 or pages != expected_pages:
        raise ReportVerificationError(f"PDF page count {pages} does not match the built report ({expected_pages})")
    return pages


def build_analytics_sheet_pdf(
    *,
    snapshot: object,
    request: object,
    output_path: str | os.PathLike[str],
    generated_at: datetime | None = None,
    tz: tzinfo | None = None,
    logo_path: str | os.PathLike[str] | None = None,
    sample_banner: str = "",
    study_records=None,
    study_error: str | None = None,
) -> BuildResult:
    """Render one A4 report to ``output_path`` (the caller owns safe finalisation)."""

    model = build_report(
        snapshot,
        request,
        generated_at=generated_at,
        tz=tz,
        sample_banner=sample_banner,
        study_records=study_records,
        study_error=study_error,
    )
    return render_model(model, output_path, logo_path=logo_path)


def render_model(model: ReportModel, output_path, *, logo_path=None) -> BuildResult:
    output = Path(output_path)
    logo = _load_logo(Path(logo_path) if logo_path else DEFAULT_LOGO)
    builder = _Builder()
    chrome = _Chrome(model, logo, builder.glyphs)
    doc = _Doc(
        str(output),
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title="MYELIN 2.0 Analytics Sheet",
        author="MYELIN",
        subject=f"Behavioural data report, {model.period_text}",
        creator="MYELIN 2.0",
    )
    cover_frame = Frame(0, 0, 10, 10, id="cover", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    body_frame = Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W, PAGE_H - MARGIN_TOP - MARGIN_BOTTOM, id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[cover_frame], onPage=chrome.cover_page),
            PageTemplate(id="content", frames=[body_frame], onPage=chrome.content_page),
        ]
    )
    # Pass 1 measures the page count (layout does not depend on the number
    # text); pass 2 renders with "PAGE n OF total" and correct bookmarks.
    scratch = _Doc(io.BytesIO(), pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM)
    scratch.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[Frame(0, 0, 10, 10, id="cover", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)]),
            PageTemplate(id="content", frames=[Frame(MARGIN_X, MARGIN_BOTTOM, CONTENT_W, PAGE_H - MARGIN_TOP - MARGIN_BOTTOM, id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)]),
        ]
    )
    scratch.build(builder.story(model))
    chrome.total = scratch.page
    doc.build(builder.story(model))
    pages = verify_pdf(output, doc.page)
    names = font_names()
    return BuildResult(output, pages, tuple(sorted(builder.glyphs.missing)), (names["body"], names["mono"]))


__all__ = [
    "BuildResult",
    "ReportAssetError",
    "ReportVerificationError",
    "build_analytics_sheet_pdf",
    "font_names",
    "render_model",
    "verify_pdf",
]
