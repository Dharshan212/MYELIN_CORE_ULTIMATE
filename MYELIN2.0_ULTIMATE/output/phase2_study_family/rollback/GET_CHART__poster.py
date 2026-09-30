"""MYELIN Neon Poster: one canonical painter for screen, A3 PDF and JPG.

Layers
------
1. ``build_poster_model`` turns the immutable ``PosterChartData`` into a small
   presentation model.  It only counts, groups, formats and lays out values the
   read model already certified; it never queries SQLite and never re-derives a
   scientific classification.  Anything the evidence cannot support is simply
   not drawn (or is drawn as an explicit UNAVAILABLE / NO DATA state).
2. ``paint_poster`` draws that model on a fixed 16:9 logical canvas. The
   interactive window, A3 PDF and 300-DPI JPG all call this one function;
   A3 output centres the wide artwork without distortion.
3. ``NeonPosterWindow`` hosts the canvas, keeps access tokens honest and
   publishes exports through a temporary file that is discarded on any failure
   or revocation.

Every glyph is emitted as a vector path, which keeps text metrics identical on
every paint device (screen, ``QImage`` and ``QPdfWriter``) and keeps the PDF
resolution independent.
"""

from __future__ import annotations

import math
import os
import re
import statistics
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from functools import lru_cache
from pathlib import Path
from typing import Final

from PyQt6.QtCore import (
    QMarginsF,
    QPointF,
    QRectF,
    QSizeF,
    QStandardPaths,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPageLayout,
    QPageSize,
    QPainter,
    QPainterPath,
    QPdfWriter,
    QPen,
    QPixmap,
    QTransform,
)
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from GET_CHART.read_model import AVAILABLE, NO_DATA, UNAVAILABLE
from PERSISTENCE.database import resource_path


# --------------------------------------------------------------------------
# Canonical geometry
# --------------------------------------------------------------------------

CANVAS_W: Final = 1680.0
CANVAS_H: Final = 945.0  # 16:9 composition; A3 exports fit this art on the page.
A3_LANDSCAPE_MM: Final = (420.0, 297.0)
EXPORT_DPI: Final = 300
A3_LANDSCAPE_PX: Final = (4961, 3508)  # 420 mm / 297 mm at 300 DPI

PANEL_W: Final = 805.0
PANEL_H: Final = 428.0
PANEL_ORIGINS: Final = {
    "SINE": (26.0, 156.0),
    "MINE": (849.0, 156.0),
    "COSINE": (26.0, 602.0),
    "COSECANT": (849.0, 602.0),
}
PANEL_ORDER: Final = ("SINE", "MINE", "COSINE", "COSECANT")

COSINE_MAX_ROWS: Final = 5
MINE_MAX_BRANCH_NODES: Final = 4
LOGO_RESOURCE: Final = "images/Myelin_Report_Logo.png"

# Palette -----------------------------------------------------------------
INK: Final = "#f3f7ff"
MUTED: Final = "#9fb0d0"
CYAN: Final = "#22e6ff"
NAVY_DEEP: Final = "#03060f"
NAVY: Final = "#081226"
INSET: Final = "#050912"
SLATE: Final = "#5d6d90"
ORANGE: Final = "#ff8a1f"
PINK: Final = "#ff2fb8"
VIOLET: Final = "#a44dff"
GREEN: Final = "#2dff6f"
BLUE: Final = "#168cff"
PURPLE_RETURN: Final = "#b060ff"

ORGAN_COLOR: Final = {
    "SINE": ORANGE,
    "MINE": PINK,
    "COSINE": VIOLET,
    "COSECANT": GREEN,
    "SECANT": BLUE,
}
ORGAN_TINT: Final = {
    "SINE": "#1d0f04",
    "MINE": "#1a0619",
    "COSINE": "#120826",
    "COSECANT": "#04170b",
}
ORGAN_COPY: Final = {
    "SINE": (
        ("DETECTS DISTRACTION.", "NUDGES YOU BACK."),
        ("“A gentle nudge today,", "a stronger you tomorrow.”"),
    ),
    "MINE": (
        ("FOR MESSAGING DISTRACTIONS.", "A CHANCE TO CHOOSE."),
        ("“A decision today", "shapes a better tomorrow.”"),
    ),
    "COSINE": (
        ("MONITORS OTT VIEWING.", "KEEPS YOU AWARE."),
        ("“Enjoy today,", "stay in control tomorrow.”"),
    ),
    "COSECANT": (
        ("MANAGES BREAKS.", "BRINGS YOU BACK TO STUDY."),
        ("“A short break.", "A stronger session.”"),
    ),
}

UNAVAILABLE_TEXT: Final = "UNAVAILABLE"
NO_DATA_TEXT: Final = "NO DATA"

_FAMILIES: Final = ["Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", "Arial"]
_SCRIPT_FAMILIES: Final = ["Segoe Script", "Segoe UI", "Arial"]


class PosterAssetError(RuntimeError):
    """The approved poster asset (official logo) is missing or unreadable."""


class _ExportCancelled(Exception):
    """Access was revoked or the user cancelled before publication."""


# --------------------------------------------------------------------------
# Presentation model (pure Python: counting, grouping, formatting only)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MetricCard:
    label: str
    value: str
    numeric: bool = False


@dataclass(frozen=True, slots=True)
class DonutSlice:
    label: str
    count: int
    color: str


@dataclass(frozen=True, slots=True)
class FunnelStage:
    label: str
    count: int
    denominator: int
    share_text: str


@dataclass(frozen=True, slots=True)
class SinePanel:
    status: str
    total: int | None
    stages: tuple[FunnelStage, ...]
    returned: int | None
    return_share_text: str
    slices: tuple[DonutSlice, ...]
    cards: tuple[MetricCard, ...]


@dataclass(frozen=True, slots=True)
class MineOutcomeNode:
    label: str
    count: int
    denominator: int
    share_text: str
    tone: str  # "returned" | "other" | "undocumented"


@dataclass(frozen=True, slots=True)
class MineChoiceNode:
    key: str
    label: str
    count: int
    share_text: str
    outcomes: tuple[MineOutcomeNode, ...]


@dataclass(frozen=True, slots=True)
class MinePanel:
    status: str
    total: int | None
    documented: int | None
    choices: tuple[MineChoiceNode, ...]
    slices: tuple[DonutSlice, ...]
    cards: tuple[MetricCard, ...]


@dataclass(frozen=True, slots=True)
class CosineRow:
    date_label: str
    span_label: str
    offsets_seconds: tuple[float, ...]
    event_count: int


@dataclass(frozen=True, slots=True)
class CosinePanel:
    status: str
    rows: tuple[CosineRow, ...]
    total_episodes: int | None
    total_events: int | None
    axis_max_seconds: float
    tz_label: str
    slices: tuple[DonutSlice, ...]
    cards: tuple[MetricCard, ...]


@dataclass(frozen=True, slots=True)
class LadderStep:
    kind: str
    lines: tuple[str, ...]
    count: int
    share_text: str
    median_text: str


@dataclass(frozen=True, slots=True)
class CosecantPanel:
    status: str
    total: int | None
    steps: tuple[LadderStep, ...]
    confirmed: int | None
    slices: tuple[DonutSlice, ...]
    cards: tuple[MetricCard, ...]


@dataclass(frozen=True, slots=True)
class PosterModel:
    snapshot_id: str
    generated_at_utc: str
    generated_label: str
    tz_label: str
    sine: SinePanel
    mine: MinePanel
    cosine: CosinePanel
    cosecant: CosecantPanel

    @property
    def snapshot_label(self) -> str:
        """Readable snapshot identity (long digests are shortened for print)."""

        return self.snapshot_id if len(self.snapshot_id) <= 24 else self.snapshot_id[:12] + "…"


def fmt_pct(numerator: int, denominator: int) -> str:
    """Percentage of a stated denominator, or N/A when none exists."""

    if denominator <= 0:
        return "N/A"
    return f"{100.0 * numerator / denominator:.1f}%"


def fmt_elapsed(seconds: float) -> str:
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m" if secs == 0 else f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h" if minutes == 0 else f"{hours}h {minutes:02d}m"


def _humanize(name: str) -> str:
    text = name.replace("_", " ").strip().lower()
    return text[:1].upper() + text[1:] if text else name


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _tz_label(moment: datetime) -> str:
    offset = moment.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{rest:02d}"


def _card(label: str, value: object, status: str = AVAILABLE) -> MetricCard:
    if status == UNAVAILABLE:
        return MetricCard(label, UNAVAILABLE_TEXT)
    if status == NO_DATA:
        return MetricCard(label, NO_DATA_TEXT)
    if isinstance(value, int) and not isinstance(value, bool):
        return MetricCard(label, f"{value:,}", numeric=True)
    return MetricCard(label, str(value))


def _lifetime_card(metric: object, label: str) -> MetricCard:
    """A separately read lifetime figure; unavailable stays UNAVAILABLE."""

    if getattr(metric, "available", False) and isinstance(metric.value, int):
        return MetricCard(label, f"{metric.value:,}", numeric=True)
    return MetricCard(label, UNAVAILABLE_TEXT)


def _slices_from_counts(
    entries: Sequence[tuple[str, int, str]],
) -> tuple[DonutSlice, ...]:
    return tuple(DonutSlice(label, count, color) for label, count, color in entries if count > 0)


# -- SINE -------------------------------------------------------------------


def _model_sine(chart, lifetime) -> SinePanel:
    status = chart.status
    lifetime_card = _lifetime_card(lifetime.sine.triggers, "LIFETIME TRIGGERS")
    if status != AVAILABLE:
        cards = (
            _card("EPISODES", None, status),
            _card("VERIFIED RETURNS", None, status),
            lifetime_card,
        )
        return SinePanel(status, None, (), None, "", (), cards)
    total = len(chart.episodes)
    stages = tuple(
        FunnelStage(
            f"SINE-{stage.stage}",
            int(stage.count),
            int(stage.denominator),
            fmt_pct(int(stage.count), total),
        )
        for stage in chart.funnel
    )
    returned = int(chart.verified_return_count)
    remainder = total - returned
    slices = _slices_from_counts(
        (
            ("Verified return", returned, PURPLE_RETURN),
            ("No verified return recorded", remainder, SLATE),
        )
    )
    cards = (
        _card("EPISODES", total),
        _card("VERIFIED RETURNS", returned),
        lifetime_card,
    )
    return SinePanel(
        status, total, stages, returned, fmt_pct(returned, total), slices, cards
    )


# -- MINE -------------------------------------------------------------------

_MINE_CHOICE_LABELS: Final = (
    ("I_WILL_COME_BACK", "I WILL COME BACK"),
    ("ITS_IMPORTANT", "IT'S IMPORTANT"),
)
_MINE_DONUT_COLORS: Final = ("#35ff8a", "#22e6ff", "#ff9a1f", "#b060ff", "#ff4fd8")


def _mine_tone(outcome: str) -> str:
    return "returned" if outcome.startswith(("RETURNED", "EARLY_RETURN")) else "other"


def _model_mine(chart, lifetime) -> MinePanel:
    status = chart.status
    lifetime_card = _lifetime_card(lifetime.mine.triggers, "LIFETIME TRIGGERS")
    if status != AVAILABLE:
        cards = (
            _card("MINE-1 CHOICES", None, status),
            _card("DOCUMENTED OUTCOMES", None, status),
            lifetime_card,
        )
        return MinePanel(status, None, None, (), (), cards)
    total = int(chart.choice_denominator)
    documented = int(chart.documented_outcome_count)
    per_choice = Counter(row.choice for row in chart.choices)
    choices: list[MineChoiceNode] = []
    for key, label in _MINE_CHOICE_LABELS:
        denominator = per_choice.get(key, 0)
        buckets = sorted(
            (bucket for bucket in chart.outcome_buckets if bucket.choice == key),
            key=lambda bucket: (-bucket.count, bucket.outcome),
        )
        nodes = [
            MineOutcomeNode(
                _humanize(bucket.outcome),
                bucket.count,
                denominator,
                fmt_pct(bucket.count, denominator),
                _mine_tone(bucket.outcome),
            )
            for bucket in buckets
        ]
        # Choices without a documented closure are shown as an explicit
        # remainder, never silently classed as failure.
        remainder = denominator - sum(node.count for node in nodes)
        remainder_node = (
            MineOutcomeNode(
                "No documented outcome", remainder, denominator,
                fmt_pct(remainder, denominator), "undocumented",
            )
            if remainder > 0
            else None
        )
        # The flow has room for MINE_MAX_BRANCH_NODES nodes per branch.  Beyond
        # that the smallest documented outcomes are folded into one explicit
        # aggregate (the donut still lists every outcome separately).
        slots = MINE_MAX_BRANCH_NODES - (1 if remainder_node else 0)
        if len(nodes) > slots:
            kept, folded = nodes[: slots - 1], nodes[slots - 1 :]
            count = sum(node.count for node in folded)
            kept.append(
                MineOutcomeNode(
                    f"Other documented ({len(folded)} kinds)", count, denominator,
                    fmt_pct(count, denominator), "other",
                )
            )
            nodes = kept
        if remainder_node is not None:
            nodes.append(remainder_node)
        choices.append(
            MineChoiceNode(key, label, denominator, fmt_pct(denominator, total), tuple(nodes))
        )
    by_outcome: Counter[str] = Counter()
    for bucket in chart.outcome_buckets:
        by_outcome[bucket.outcome] += bucket.count
    entries: list[tuple[str, int, str]] = []
    for index, (outcome, count) in enumerate(
        sorted(by_outcome.items(), key=lambda item: (-item[1], item[0]))
    ):
        entries.append(
            (_humanize(outcome), count, _MINE_DONUT_COLORS[index % len(_MINE_DONUT_COLORS)])
        )
    entries.append(("No documented outcome", total - documented, SLATE))
    cards = (
        _card("MINE-1 CHOICES", total),
        _card("DOCUMENTED OUTCOMES", documented),
        lifetime_card,
    )
    return MinePanel(
        status, total, documented, tuple(choices), _slices_from_counts(entries), cards
    )


# -- COSINE -----------------------------------------------------------------

_COSINE_DONUT_COLORS: Final = (VIOLET, CYAN, "#ff4fd8", "#4d7dff")


def _model_cosine(chart, lifetime, tz: tzinfo) -> CosinePanel:
    status = chart.status
    lifetime_card = _lifetime_card(lifetime.cosine.triggers, "LIFETIME TRIGGERS")
    if status != AVAILABLE:
        cards = (
            _card("EPISODES", None, status),
            _card("RECORDED EVENTS", None, status),
            lifetime_card,
        )
        return CosinePanel(status, (), None, None, 0.0, "", (), cards)

    dated: list[tuple[datetime, object]] = []
    for episode in chart.episodes:
        stamps = [_parse_utc(event.occurred_at_utc) for event in episode.events]
        first = min(stamps) if stamps else _parse_utc(episode.started_at_utc)
        dated.append((first, episode))
    dated.sort(key=lambda item: (item[0], item[1].cosine_session_id, item[1].generation))
    shown = dated[-COSINE_MAX_ROWS:]

    rows: list[CosineRow] = []
    axis_max = 0.0
    for first, episode in shown:
        stamps = sorted(_parse_utc(event.occurred_at_utc) for event in episode.events)
        origin = stamps[0] if stamps else first
        offsets = tuple((stamp - origin).total_seconds() for stamp in stamps)
        if offsets:
            axis_max = max(axis_max, offsets[-1])
        local_first = (stamps[0] if stamps else first).astimezone(tz)
        if len(stamps) > 1:
            local_last = stamps[-1].astimezone(tz)
            span = f"{local_first:%H:%M}–{local_last:%H:%M}"
        else:
            span = f"{local_first:%H:%M}"
        rows.append(
            CosineRow(
                f"{local_first.day} {local_first:%b}".upper(),
                span,
                offsets,
                len(stamps),
            )
        )

    names = Counter(
        event.event_name for episode in chart.episodes for event in episode.events
    )
    ordered = sorted(names.items(), key=lambda item: (-item[1], item[0]))
    top = ordered[:4]
    entries = [
        (_humanize(name), count, _COSINE_DONUT_COLORS[index])
        for index, (name, count) in enumerate(top)
    ]
    rest = ordered[4:]
    if rest:
        entries.append((f"Other ({len(rest)} kinds)", sum(count for _n, count in rest), SLATE))
    tz_label = _tz_label(datetime.now(timezone.utc).astimezone(tz))
    if shown:
        tz_label = _tz_label(shown[-1][0].astimezone(tz))
    total_events = int(chart.timestamp_count)
    total_episodes = int(chart.episode_denominator)
    cards = (
        _card("EPISODES", total_episodes),
        _card("RECORDED EVENTS", total_events),
        lifetime_card,
    )
    return CosinePanel(
        status,
        tuple(rows),
        total_episodes,
        total_events,
        axis_max,
        tz_label,
        _slices_from_counts(entries),
        cards,
    )


# -- COSECANT ---------------------------------------------------------------

_LADDER: Final = (
    ("BREAK_STARTED", ("BREAK", "STARTED"), "#1f7bff"),
    ("BREAK_COMPLETE", ("BREAK", "COMPLETE"), "#17d9a0"),
    ("FINAL_LOCKED", ("FINAL", "LOCKED"), "#ffd21f"),
    ("RETURN_INTENT_RECORDED", ("RETURN", "INTENT"), "#ff9a1f"),
    ("RETURN_CONFIRMATION_STARTED", ("CONFIRM", "STARTED"), "#ff5a36"),
    ("RETURN_CONFIRMED", ("RETURN", "CONFIRMED"), "#35ff7a"),
)
LADDER_COLORS: Final = {kind: color for kind, _lines, color in _LADDER}


def _first_milestone(break_row, kind: str):
    return next((m for m in break_row.milestones if m.kind == kind), None)


def _model_cosecant(chart, lifetime) -> CosecantPanel:
    status = chart.status
    lifetime_card = _lifetime_card(lifetime.cosecant.triggers, "LIFETIME TRIGGERS")
    if status != AVAILABLE:
        cards = (
            _card("BREAKS", None, status),
            _card("CONFIRMED RETURNS", None, status),
            lifetime_card,
        )
        return CosecantPanel(status, None, (), None, (), cards)
    total = len(chart.breaks)
    steps: list[LadderStep] = []
    for kind, lines, _color in _LADDER:
        with_kind = [
            (row, _first_milestone(row, kind))
            for row in chart.breaks
            if _first_milestone(row, kind) is not None
        ]
        median_text = "—"
        if kind != "BREAK_STARTED":
            deltas: list[float] = []
            for row, milestone in with_kind:
                start = _first_milestone(row, "BREAK_STARTED")
                if start is None:
                    continue
                # Same break, same (effective monotonic) clock: never a wall
                # clock minus a monotonic reading.
                delta_ns = milestone.effective_monotonic_ns - start.effective_monotonic_ns
                if delta_ns >= 0:
                    deltas.append(delta_ns / 1e9)
            if deltas:
                median_text = "+" + fmt_elapsed(statistics.median(deltas))
        steps.append(
            LadderStep(kind, lines, len(with_kind), fmt_pct(len(with_kind), total), median_text)
        )
    confirmed = int(chart.confirmed_return_count)
    slices = _slices_from_counts(
        (
            ("Return confirmed", confirmed, GREEN),
            ("No return confirmation recorded", total - confirmed, SLATE),
        )
    )
    cards = (
        _card("BREAKS", total),
        _card("CONFIRMED RETURNS", confirmed),
        lifetime_card,
    )
    return CosecantPanel(status, total, tuple(steps), confirmed, slices, cards)


def build_poster_model(data, *, tz: tzinfo | None = None) -> PosterModel:
    """Project immutable poster data to a presentation model (no I/O)."""

    zone = tz if tz is not None else datetime.now().astimezone().tzinfo
    lifetime = data.lifetime_summary
    generated = _parse_utc(data.generated_at_utc).astimezone(zone)
    return PosterModel(
        snapshot_id=str(data.snapshot_id),
        generated_at_utc=str(data.generated_at_utc),
        generated_label=f"{generated:%Y-%m-%d %H:%M} {_tz_label(generated)}",
        tz_label=_tz_label(generated),
        sine=_model_sine(data.sine, lifetime),
        mine=_model_mine(data.mine, lifetime),
        cosine=_model_cosine(data.cosine, lifetime, zone),
        cosecant=_model_cosecant(data.cosecant, lifetime),
    )


# --------------------------------------------------------------------------
# Painting toolkit
# --------------------------------------------------------------------------


@dataclass(slots=True)
class TextPlacement:
    text: str
    rect: QRectF  # logical poster units
    region: str
    region_rect: QRectF | None
    size: float


class _Ctx:
    """Painter wrapper that can record where every glyph run landed."""

    def __init__(self, painter: QPainter, log: list[TextPlacement] | None) -> None:
        self.p = painter
        self.log = log
        self.base = painter.worldTransform()
        self.base_inv, _ok = self.base.inverted()
        self._regions: list[tuple[str, QRectF]] = []

    def to_logical(self) -> QTransform:
        return self.p.worldTransform() * self.base_inv

    def push_region(self, name: str, rect: QRectF) -> None:
        self._regions.append((name, self.to_logical().mapRect(rect)))

    def pop_region(self) -> None:
        self._regions.pop()


def _color(value: str | QColor, alpha: float = 1.0) -> QColor:
    color = QColor(value)
    color.setAlphaF(max(0.0, min(1.0, alpha)))
    return color


def _lighten(value: str, amount: float) -> QColor:
    color = QColor(value)
    h, s, l, a = color.getHslF()
    color.setHslF(h, s, min(1.0, l + amount), a)
    return color


def _darken(value: str, factor: float) -> QColor:
    color = QColor(value)
    return QColor(
        int(color.red() * factor), int(color.green() * factor), int(color.blue() * factor)
    )


def _luma(value: str) -> float:
    color = QColor(value)
    return (0.2126 * color.red() + 0.7152 * color.green() + 0.0722 * color.blue()) / 255.0


@lru_cache(maxsize=64)
def _font(bold: bool, italic: bool, spacing: float, script: bool, black: bool) -> QFont:
    font = QFont()
    font.setFamilies(_SCRIPT_FAMILIES if script else _FAMILIES)
    font.setPixelSize(100)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    if black:
        font.setWeight(QFont.Weight.Black)
    else:
        font.setBold(bold)
    font.setItalic(italic)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing * 100.0)
    return font


def text_width(
    text: str,
    size: float,
    *,
    bold: bool = False,
    italic: bool = False,
    spacing: float = 0.0,
    script: bool = False,
    black: bool = False,
) -> float:
    font = _font(bold, italic, spacing, script, black)
    return QFontMetricsF(font).horizontalAdvance(text) * size / 100.0


@lru_cache(maxsize=2048)
def _text_path(text: str, bold: bool, italic: bool, spacing: float, script: bool, black: bool):
    path = QPainterPath()
    path.addText(QPointF(0.0, 0.0), _font(bold, italic, spacing, script, black), text)
    return path


def draw_text(
    ctx: _Ctx,
    text: str,
    x: float,
    y: float,
    size: float,
    color: str | QColor = INK,
    *,
    align: str = "l",
    bold: bool = False,
    italic: bool = False,
    spacing: float = 0.0,
    max_w: float | None = None,
    glow: str | None = None,
    script: bool = False,
    black: bool = False,
    alpha: float = 1.0,
) -> QRectF:
    """Draw one baseline-anchored run as vector outlines, shrinking to ``max_w``."""

    if not text:
        return QRectF()
    natural = text_width(
        text, size, bold=bold, italic=italic, spacing=spacing, script=script, black=black
    )
    effective = size
    if max_w is not None and natural > max_w > 0:
        effective = size * max_w / natural
        natural = max_w
    if align == "c":
        left = x - natural / 2.0
    elif align == "r":
        left = x - natural
    else:
        left = x
    transform = QTransform()
    transform.translate(left, y)
    transform.scale(effective / 100.0, effective / 100.0)
    path = transform.map(_text_path(text, bold, italic, spacing, script, black))
    painter = ctx.p
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if glow:
        for layer in (4, 3, 2, 1):
            painter.setPen(
                QPen(
                    _color(glow, 0.07 * (5 - layer) * alpha),
                    effective * 0.055 * layer,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_color(color, alpha))
    painter.drawPath(path)
    rect = path.boundingRect()
    if ctx.log is not None:
        region, region_rect = ctx._regions[-1] if ctx._regions else ("canvas", None)
        ctx.log.append(
            TextPlacement(text, ctx.to_logical().mapRect(rect), region, region_rect, effective)
        )
    return rect


def wrap_words(text: str, size: float, max_w: float, *, bold: bool = False) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and text_width(trial, size, bold=bold) > max_w:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def glow_path(
    ctx: _Ctx,
    path: QPainterPath,
    color: str | QColor,
    width: float,
    *,
    layers: int = 5,
    strength: float = 0.5,
    cap: Qt.PenCapStyle = Qt.PenCapStyle.RoundCap,
) -> None:
    painter = ctx.p
    painter.setBrush(Qt.BrushStyle.NoBrush)
    base = QColor(color)
    for layer in range(layers, 0, -1):
        outer = QColor(base)
        outer.setAlphaF(strength * 0.09 * (layers - layer + 1) / layers * 2.0)
        painter.setPen(
            QPen(outer, width + layer * width * 1.7, Qt.PenStyle.SolidLine, cap, Qt.PenJoinStyle.RoundJoin)
        )
        painter.drawPath(path)
    painter.setPen(QPen(base, width, Qt.PenStyle.SolidLine, cap, Qt.PenJoinStyle.RoundJoin))
    painter.drawPath(path)


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _vgradient(rect: QRectF, top: QColor, bottom: QColor) -> QLinearGradient:
    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gradient.setColorAt(0.0, top)
    gradient.setColorAt(1.0, bottom)
    return gradient


# -- icons (simple line-art, drawn as strokes) ------------------------------


def _icon_shield(rect: QRectF) -> QPainterPath:
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath(QPointF(x + w / 2, y))
    path.cubicTo(x + w * 0.75, y + h * 0.12, x + w * 0.92, y + h * 0.12, x + w, y + h * 0.16)
    path.lineTo(x + w, y + h * 0.5)
    path.cubicTo(x + w, y + h * 0.78, x + w * 0.7, y + h * 0.92, x + w / 2, y + h)
    path.cubicTo(x + w * 0.3, y + h * 0.92, x, y + h * 0.78, x, y + h * 0.5)
    path.lineTo(x, y + h * 0.16)
    path.cubicTo(x + w * 0.08, y + h * 0.12, x + w * 0.25, y + h * 0.12, x + w / 2, y)
    inner = QPainterPath(QPointF(x + w * 0.5, y + h * 0.22))
    inner.lineTo(x + w * 0.66, y + h * 0.52)
    inner.lineTo(x + w * 0.5, y + h * 0.72)
    inner.lineTo(x + w * 0.34, y + h * 0.52)
    inner.closeSubpath()
    path.addPath(inner)
    return path


def _icon_chat(rect: QRectF) -> QPainterPath:
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath()
    body = QRectF(x, y + h * 0.05, w, h * 0.68)
    path.addRoundedRect(body, h * 0.28, h * 0.28)
    tail = QPainterPath(QPointF(x + w * 0.28, y + h * 0.72))
    tail.lineTo(x + w * 0.2, y + h * 0.95)
    tail.lineTo(x + w * 0.5, y + h * 0.73)
    path.addPath(tail)
    for fraction in (0.3, 0.5, 0.7):
        path.addEllipse(QPointF(x + w * fraction, y + h * 0.39), w * 0.035, w * 0.035)
    return path


def _icon_play(rect: QRectF) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(rect)
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    tri = QPainterPath(QPointF(x + w * 0.4, y + h * 0.3))
    tri.lineTo(x + w * 0.72, y + h * 0.5)
    tri.lineTo(x + w * 0.4, y + h * 0.7)
    tri.closeSubpath()
    path.addPath(tri)
    return path


def _icon_book(rect: QRectF) -> QPainterPath:
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath(QPointF(x + w / 2, y + h * 0.2))
    path.cubicTo(x + w * 0.35, y + h * 0.05, x + w * 0.15, y + h * 0.05, x, y + h * 0.12)
    path.lineTo(x, y + h * 0.85)
    path.cubicTo(x + w * 0.15, y + h * 0.78, x + w * 0.35, y + h * 0.78, x + w / 2, y + h * 0.92)
    path.cubicTo(x + w * 0.65, y + h * 0.78, x + w * 0.85, y + h * 0.78, x + w, y + h * 0.85)
    path.lineTo(x + w, y + h * 0.12)
    path.cubicTo(x + w * 0.85, y + h * 0.05, x + w * 0.65, y + h * 0.05, x + w / 2, y + h * 0.2)
    path.lineTo(x + w / 2, y + h * 0.92)
    return path


def _icon_brain(rect: QRectF) -> QPainterPath:
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath()
    path.addEllipse(QRectF(x, y + h * 0.1, w * 0.56, h * 0.62))
    path.addEllipse(QRectF(x + w * 0.44, y + h * 0.1, w * 0.56, h * 0.62))
    path.addEllipse(QRectF(x + w * 0.16, y + h * 0.34, w * 0.68, h * 0.5))
    path.moveTo(x + w * 0.5, y + h * 0.16)
    path.lineTo(x + w * 0.5, y + h * 0.9)
    return path


def _icon_target(rect: QRectF) -> QPainterPath:
    path = QPainterPath()
    center = rect.center()
    for fraction in (0.5, 0.32, 0.14):
        path.addEllipse(center, rect.width() * fraction, rect.height() * fraction)
    path.moveTo(center)
    path.lineTo(rect.right(), rect.top())
    return path


def _icon_bars(rect: QRectF) -> QPainterPath:
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath()
    for index, height in enumerate((0.38, 0.6, 0.85)):
        bar = QRectF(x + w * (0.05 + index * 0.32), y + h * (1 - height), w * 0.22, h * height)
        path.addRoundedRect(bar, 2, 2)
    path.moveTo(x, y + h * 0.3)
    path.lineTo(x + w * 0.4, y + h * 0.1)
    path.lineTo(x + w * 0.8, y + h * 0.16)
    return path


def _icon_heart(rect: QRectF) -> QPainterPath:
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    path = QPainterPath(QPointF(x + w / 2, y + h * 0.92))
    path.cubicTo(x - w * 0.15, y + h * 0.5, x + w * 0.1, y - h * 0.05, x + w / 2, y + h * 0.28)
    path.cubicTo(x + w * 0.9, y - h * 0.05, x + w * 1.15, y + h * 0.5, x + w / 2, y + h * 0.92)
    return path


def _icon_sun(rect: QRectF) -> QPainterPath:
    center = rect.center()
    path = QPainterPath()
    path.addEllipse(center, rect.width() * 0.2, rect.height() * 0.2)
    for index in range(8):
        angle = index * math.pi / 4
        inner, outer = rect.width() * 0.32, rect.width() * 0.5
        path.moveTo(center.x() + math.cos(angle) * inner, center.y() + math.sin(angle) * inner)
        path.lineTo(center.x() + math.cos(angle) * outer, center.y() + math.sin(angle) * outer)
    return path


def _draw_icon(ctx: _Ctx, builder, rect: QRectF, color: str, width: float = 3.0) -> None:
    glow_path(ctx, builder(rect), color, width, layers=3, strength=0.45)


# --------------------------------------------------------------------------
# Background, header, footer
# --------------------------------------------------------------------------


def radial_glow(
    ctx: _Ctx, cx: float, cy: float, radius: float, tone: str, peak: float, *, steps: int = 30
) -> None:
    """Soft glow built from constant-alpha discs.

    Alpha inside gradient stops is not honoured by every PDF renderer, so the
    glow is stacked flat translucent fills, which behave identically on screen,
    in JPG and in PDF.
    """

    p = ctx.p
    p.setPen(Qt.PenStyle.NoPen)
    step_alpha = 1.0 - (1.0 - peak) ** (1.0 / steps)
    p.setBrush(_color(tone, step_alpha))
    for index in range(steps):
        r = radius * (1.0 - index / steps) ** 1.6
        p.drawEllipse(QPointF(cx, cy), r, r)


def _paint_background(ctx: _Ctx) -> None:
    p = ctx.p
    canvas = QRectF(0, 0, CANVAS_W, CANVAS_H)
    p.fillRect(canvas, _vgradient(canvas, QColor("#050a18"), QColor("#02040a")))
    p.setPen(QPen(_color("#1b5b82", 0.15), 0.8))
    for x in range(0, int(CANVAS_W) + 1, 42):
        p.drawLine(QPointF(x, 0), QPointF(x, CANVAS_H))
    for y in range(0, int(CANVAS_H) + 1, 42):
        p.drawLine(QPointF(0, y), QPointF(CANVAS_W, y))
    for i in range(72):
        x = 18 + (i * 337) % 1644
        y = 8 + (i * 191) % 930
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_color(CYAN, 0.11 if i % 3 else 0.25))
        p.drawEllipse(QPointF(x, y), 1.0 if i % 3 else 1.5, 1.0 if i % 3 else 1.5)
    p.save()
    p.setClipRect(canvas)
    for cx, cy, radius, tone, alpha in (
        (230, 60, 520, "#3a1e9a", 0.30),
        (1450, 60, 520, "#0a6a8a", 0.24),
        (840, 1200, 760, "#7a3a12", 0.22),
        (840, 1200, 560, "#0a5a7a", 0.20),
    ):
        radial_glow(ctx, cx, cy, radius, tone, alpha)
    p.restore()


def _paint_background_logo(ctx: _Ctx, logo: QImage) -> None:
    """The complete official mark, ghosted behind the poster content."""

    p = ctx.p
    p.save()
    try:
        p.setClipRect(QRectF(0, 0, CANVAS_W, CANVAS_H))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        radial_glow(ctx, 840, 455, 500, BLUE, 0.035)
        mark = QRectF(140, -220, 1400, 1400)
        # Small offset passes soften the existing transparent logo edges while
        # keeping the combined opacity below the approved eight percent.
        for dx, dy in ((-5, 0), (5, 0), (0, -5), (0, 5),
                       (-3, -3), (3, -3), (-3, 3), (3, 3)):
            p.setOpacity(0.002)
            p.drawImage(mark.translated(dx, dy), logo)
        p.setOpacity(0.06)
        p.drawImage(mark, logo)
    finally:
        p.restore()


def _paint_mountains(ctx: _Ctx) -> None:
    p = ctx.p
    horizon = 1124.0
    back = QPainterPath(QPointF(0, CANVAS_H))
    for x, y in (
        (0, 1166), (120, 1144), (260, 1168), (420, 1128), (560, 1162), (700, 1138),
        (840, 1166), (990, 1132), (1140, 1164), (1290, 1136), (1440, 1166),
        (1560, 1144), (1680, 1168),
    ):
        back.lineTo(x, y)
    back.lineTo(CANVAS_W, CANVAS_H)
    back.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_vgradient(QRectF(0, horizon, CANVAS_W, CANVAS_H - horizon), QColor("#0a1a30"), QColor("#040810")))
    p.drawPath(back)
    front = QPainterPath(QPointF(0, CANVAS_H))
    for x, y in (
        (0, 1188), (170, 1164), (330, 1192), (520, 1166), (700, 1194), (860, 1176),
        (1020, 1194), (1200, 1164), (1380, 1192), (1540, 1168), (1680, 1190),
    ):
        front.lineTo(x, y)
    front.lineTo(CANVAS_W, CANVAS_H)
    front.closeSubpath()
    p.setBrush(_vgradient(QRectF(0, 1156, CANVAS_W, 32), QColor("#07101f"), QColor("#02040a")))
    p.drawPath(front)
    ridge = QPainterPath(QPointF(0, 1166))
    for x, y in (
        (120, 1144), (260, 1168), (420, 1128), (560, 1162), (700, 1138), (840, 1166),
        (990, 1132), (1140, 1164), (1290, 1136), (1440, 1166), (1560, 1144), (1680, 1168),
    ):
        ridge.lineTo(x, y)
    # Keep the horizon line clear of the tagline printed across the ridge.
    keep = QPainterPath()
    keep.addRect(QRectF(0, 1036, CANVAS_W, CANVAS_H - 1036))
    band = QPainterPath()
    band.addRect(QRectF(470, 1126, 740, 30))
    p.save()
    p.setClipPath(keep.subtracted(band))
    glow_path(ctx, ridge, "#188aa8", 1.2, layers=2, strength=0.22)
    p.restore()
    p.save()
    p.setClipRect(QRectF(0, 1036, CANVAS_W, CANVAS_H - 1036))
    radial_glow(ctx, CANVAS_W / 2, 1170, 460, "#ff9a3a", 0.16)
    p.restore()


def _paint_header(ctx: _Ctx, logo: QImage) -> None:
    p = ctx.p
    ctx.push_region("header", QRectF(0, 0, CANVAS_W, 150))
    # Official logo: native aspect ratio, never redrawn.
    box = 128.0
    scale = min(box / logo.width(), box / logo.height())
    lw, lh = logo.width() * scale, logo.height() * scale
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.drawImage(QRectF(22 + (box - lw) / 2, 10 + (box - lh) / 2, lw, lh), logo)

    word_w = min(330.0, text_width("MYELIN", 68, bold=True, black=True, spacing=0.02))
    draw_text(ctx, "MYELIN", 158, 78, 68, CYAN, bold=True, black=True, spacing=0.02, glow=CYAN, max_w=330)
    draw_text(ctx, "2.0", 158 + word_w + 14, 78, 38, INK, bold=True, glow=CYAN, max_w=90)
    draw_text(
        ctx, "OBSERVE · UNDERSTAND · NUDGE · RECOVER · REPEAT",
        160, 112, 14, "#7fe8ff", spacing=0.12, max_w=470,
    )

    draw_text(ctx, "BEHAVIOUR ANALYTICS FOR A", 840, 50, 26, "#bfeaff", align="c", spacing=0.16, glow=CYAN, max_w=460)
    draw_text(ctx, "FOCUSED TOMORROW", 840, 96, 48, INK, align="c", bold=True, black=True, spacing=0.08, glow=CYAN, max_w=470)
    draw_text(ctx, "FOUR ORGANS  ·  ONE GOAL  ·  A BETTER YOU", 840, 128, 15, CYAN, align="c", spacing=0.22, max_w=470)

    draw_text(ctx, "“Distraction is not a failure.", 1300, 62, 26, INK, align="c", italic=True, max_w=360)
    draw_text(ctx, "It is a signal.”", 1300, 94, 26, INK, align="c", italic=True, max_w=360)
    draw_text(ctx, "— MYELIN", 1300, 124, 16, CYAN, align="c", spacing=0.08, max_w=200)
    p.setPen(QPen(_color(CYAN, 0.7), 1.6))
    p.drawLine(QPointF(1490, 26), QPointF(1490, 132))
    for index, word in enumerate(
        ("AWARENESS", "DISCIPLINE", "SELF-CONTROL", "BETTER HABITS", "A BRIGHTER YOU")
    ):
        draw_text(ctx, word, 1508, 42 + index * 23, 15, CYAN, bold=True, spacing=0.08, max_w=152)
    ctx.pop_region()


def _paint_footer(ctx: _Ctx, model: PosterModel) -> None:
    p = ctx.p
    _paint_mountains(ctx)
    ctx.push_region("footer", QRectF(0, 1036, CANVAS_W, CANVAS_H - 1036))
    items = (
        (_icon_brain, "PRODUCTIVE USE"),
        (_icon_target, "SELF-CONTROL"),
        (_icon_bars, "BETTER HABITS"),
        (_icon_heart, "A CALMER MIND"),
        (_icon_sun, "A BRIGHTER TOMORROW"),
    )
    x0, span = 250.0, 188.0
    for index, (builder, label) in enumerate(items):
        cx = x0 + index * span + span / 2
        _draw_icon(ctx, builder, QRectF(cx - 22, 1046, 44, 40), CYAN, 2.6)
        draw_text(ctx, label, cx, 1112, 14.5, "#8fefff", align="c", bold=True, spacing=0.08, max_w=span - 22)
        if index:
            p.setPen(QPen(_color(CYAN, 0.55), 1.4))
            p.drawLine(QPointF(x0 + index * span, 1048), QPointF(x0 + index * span, 1106))

    draw_text(ctx, "MYELIN", 1222, 1092, 38, CYAN, bold=True, black=True, glow=CYAN, max_w=170)
    draw_text(ctx, "MORE THAN A TOOL", 1408, 1078, 14, "#cfe9ff", spacing=0.08, max_w=130)
    draw_text(ctx, "A HEALTHIER YOU", 1408, 1100, 14, "#cfe9ff", spacing=0.08, max_w=130)

    badge = QRectF(1562, 1046, 98, 56)
    p.setPen(QPen(_color(CYAN, 0.7), 1.2))
    p.setBrush(_color("#04101e", 0.9))
    p.drawRoundedRect(badge, 6, 6)
    draw_text(ctx, "MYELIN 2.0", badge.center().x(), 1070, 13.5, INK, align="c", bold=True, max_w=84)
    draw_text(ctx, "EST. 2026", badge.center().x(), 1090, 12.5, INK, align="c", max_w=84)

    p.save()
    p.translate(38, 1082)
    p.rotate(-7)
    draw_text(ctx, "Small Steps", 0, 0, 26, "#dbe6ff", script=True, italic=True, max_w=170)
    draw_text(ctx, "Big Change", 22, 28, 26, "#dbe6ff", script=True, italic=True, max_w=170)
    p.restore()
    p.save()
    p.translate(1520, 1140)
    p.rotate(-7)
    draw_text(ctx, "Focus Creates", 0, 0, 22, "#dbe6ff", script=True, italic=True, max_w=150)
    draw_text(ctx, "Freedom", 26, 24, 22, "#dbe6ff", script=True, italic=True, max_w=110)
    p.restore()

    draw_text(
        ctx, "DATA TODAY  ·  DISCIPLINE TOMORROW  ·  A BRIGHTER YOU",
        840, 1146, 15, "#7fe8ff", align="c", spacing=0.22, max_w=700,
    )
    evidence = (
        "Summary of recorded MYELIN behavioural data (non-clinical). "
        f"Generated {model.generated_label}  ·  snapshot {model.snapshot_label}  ·  "
        "lifetime summary and episode evidence are read separately, not as one atomic snapshot."
    )
    draw_text(ctx, evidence, 840, 1176, 12, "#a9bad8", align="c", max_w=1180)
    ctx.pop_region()


# --------------------------------------------------------------------------
# Panel chrome and shared widgets
# --------------------------------------------------------------------------

LEFT_INSET: Final = QRectF(14, 88, 452, 326)
DONUT_INSET: Final = QRectF(478, 88, 313, 226)
CARD_ROW_Y: Final = 324.0
CARD_H: Final = 90.0


def _card_rects() -> list[QRectF]:
    gap = 8.0
    width = (DONUT_INSET.width() - 2 * gap) / 3.0
    return [QRectF(478 + i * (width + gap), CARD_ROW_Y, width, CARD_H) for i in range(3)]


def _paint_panel_chrome(ctx: _Ctx, organ: str) -> None:
    p = ctx.p
    color = ORGAN_COLOR[organ]
    rect = QRectF(0, 0, PANEL_W, PANEL_H)
    p.setPen(Qt.PenStyle.NoPen)
    fill = _vgradient(rect, QColor(ORGAN_TINT[organ]), QColor("#03060d"))
    p.setBrush(fill)
    p.drawPath(rounded_path(rect, 18))
    border = rounded_path(rect.adjusted(1.5, 1.5, -1.5, -1.5), 17)
    glow_path(ctx, border, color, 2.6, layers=6, strength=0.5)

    builder = {"SINE": _icon_shield, "MINE": _icon_chat, "COSINE": _icon_play, "COSECANT": _icon_book}[organ]
    _draw_icon(ctx, builder, QRectF(22, 14, 54, 52), color, 3.0)
    name_w = text_width(organ, 50, bold=True, black=True, spacing=0.02)
    draw_text(ctx, organ, 92, 62, 50, color, bold=True, black=True, spacing=0.02, glow=color, max_w=300)
    name_w = min(name_w, 300)
    tag, quote = ORGAN_COPY[organ]
    tag_x = 92 + name_w + 24
    quote_right = PANEL_W - 22
    tag_w = max(text_width(line, 15, bold=True) for line in tag)
    tag_w = min(tag_w, 232)
    draw_text(ctx, tag[0], tag_x, 32, 15, "#dfe8ff", bold=True, max_w=tag_w)
    draw_text(ctx, tag[1], tag_x, 54, 15, "#dfe8ff", bold=True, max_w=tag_w)
    quote_w = quote_right - (tag_x + tag_w + 18)
    draw_text(ctx, quote[0], quote_right, 32, 15, color, align="r", italic=True, max_w=quote_w)
    draw_text(ctx, quote[1], quote_right, 54, 15, color, align="r", italic=True, max_w=quote_w)


def _paint_inset(ctx: _Ctx, rect: QRectF, title: str, organ: str) -> None:
    p = ctx.p
    p.setBrush(_color(INSET, 0.94))
    p.setPen(QPen(_color(ORGAN_COLOR[organ], 0.55), 1.3))
    p.drawRoundedRect(rect, 9, 9)
    draw_text(
        ctx, title, rect.x() + 14, rect.y() + 26, 16, INK, bold=True, spacing=0.03,
        max_w=rect.width() - 28,
    )


def _paint_empty(ctx: _Ctx, rect: QRectF, status: str, noun: str, organ: str) -> None:
    color = ORGAN_COLOR[organ]
    cx, cy = rect.center().x(), rect.center().y()
    if status == NO_DATA:
        headline, sub = f"NO RECORDED {noun}", "Nothing has been recorded yet."
    else:
        headline, sub = "EVIDENCE UNAVAILABLE", "Recorded evidence could not be validated."
    draw_text(ctx, headline, cx, cy - 2, 20, color, align="c", bold=True, spacing=0.06, glow=color, max_w=rect.width() - 36)
    draw_text(ctx, sub, cx, cy + 24, 13, MUTED, align="c", max_w=rect.width() - 36)


def _paint_card(ctx: _Ctx, rect: QRectF, card: MetricCard, organ: str) -> None:
    p = ctx.p
    ctx.push_region("card", rect)
    p.setBrush(_color("#04101c", 0.95))
    glow_path(ctx, rounded_path(rect, 9), CYAN, 1.4, layers=3, strength=0.35)
    p.setBrush(_color("#04101c", 0.95))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)
    if card.numeric:
        draw_text(ctx, card.value, rect.center().x(), rect.y() + 44, 32, INK, align="c", bold=True, glow=ORGAN_COLOR[organ], max_w=rect.width() - 14)
    else:
        draw_text(ctx, card.value, rect.center().x(), rect.y() + 40, 16, "#ffd0a0" if card.value == UNAVAILABLE_TEXT else MUTED, align="c", bold=True, max_w=rect.width() - 14)
    lines = wrap_words(card.label, 11.5, rect.width() - 14, bold=True)[:2]
    for index, line in enumerate(lines):
        draw_text(ctx, line, rect.center().x(), rect.y() + 62 + index * 15, 11.5, "#b9c8e6", align="c", bold=True, spacing=0.02, max_w=rect.width() - 12)
    ctx.pop_region()


def _paint_cards(ctx: _Ctx, cards: Sequence[MetricCard], organ: str) -> None:
    for rect, card in zip(_card_rects(), cards):
        _paint_card(ctx, rect, card, organ)


def _donut_arc(center: QPointF, radius: float, start: float, span: float) -> QPainterPath:
    path = QPainterPath()
    box = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
    path.arcMoveTo(box, start)
    path.arcTo(box, start, span)
    return path


def _paint_donut(
    ctx: _Ctx,
    rect: QRectF,
    title: str,
    slices: Sequence[DonutSlice],
    total: int,
    center_label: str,
    organ: str,
    legend_note: str = "",
) -> None:
    """Donut of mutually exclusive categories that sum to ``total``."""

    p = ctx.p
    _paint_inset(ctx, rect, title, organ)
    center = QPointF(rect.x() + 66, rect.y() + 130)
    radius, thickness = 50.0, 18.0
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_color("#16203a", 0.9), thickness))
    p.drawEllipse(center, radius, radius)
    angle = 90.0
    if slices and total > 0:
        if len(slices) == 1:
            glow_path(ctx, _donut_arc(center, radius, 90.0, 359.99), slices[0].color, thickness, layers=2, strength=0.3, cap=Qt.PenCapStyle.FlatCap)
        else:
            for piece in slices:
                span = -360.0 * piece.count / total
                gap = 2.0 if abs(span) > 6 else 0.0
                arc = _donut_arc(center, radius, angle - (gap / 2), span + gap)
                glow_path(ctx, arc, piece.color, thickness, layers=2, strength=0.3, cap=Qt.PenCapStyle.FlatCap)
                angle += span
    draw_text(ctx, f"{total:,}", center.x(), center.y() + 8, 28, INK, align="c", bold=True, max_w=62)
    draw_text(ctx, center_label, center.x(), center.y() + 24, 11, MUTED, align="c", bold=True, spacing=0.05, max_w=64)

    legend_x = rect.x() + 128
    legend_w = rect.width() - 128 - 10
    text_w = legend_w - 17
    avail = 152.0
    # Widest layout that fits: wrapped labels, then compact two-line, then one line.
    plans = ((12.5, 15.5, True, False), (11.5, 13.0, True, False), (11.0, 0.0, False, True))
    chosen = plans[-1]
    for size, line_h, wrap, single in plans:
        if single:
            break
        need = 0.0
        for piece in slices:
            lines = wrap_words(piece.label, size, text_w, bold=True) if wrap else [piece.label]
            if len(lines) > 2 or (not wrap and text_width(piece.label, size, bold=True) > text_w):
                need = avail + 1
                break
            need += (len(lines) + 1) * line_h + (6 if size > 12 else 3)
        if need <= avail:
            chosen = (size, line_h, wrap, single)
            break
    size, line_h, wrap, single = chosen
    y = rect.y() + 52
    row_h = avail / max(1, len(slices))
    for piece in slices:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_color(piece.color))
        value = f"{piece.count:,}  ({fmt_pct(piece.count, total)})"
        if single:
            p.drawEllipse(QPointF(legend_x + 5, y + 8), 4.5, 4.5)
            value_w = text_width(value, size, bold=True)
            draw_text(ctx, value, legend_x + legend_w, y + 12, size, _lighten(piece.color, 0.08), align="r", bold=True, max_w=value_w)
            draw_text(ctx, piece.label, legend_x + 17, y + 12, size, INK, bold=True, max_w=max(20.0, text_w - value_w - 6))
            y += min(row_h, 22.0)
            continue
        lines = wrap_words(piece.label, size, text_w, bold=True) if wrap else [piece.label]
        p.drawEllipse(QPointF(legend_x + 5, y + 8), 5, 5)
        for offset, line in enumerate(lines):
            draw_text(ctx, line, legend_x + 17, y + 12 + offset * line_h, size, INK, bold=True, max_w=text_w)
        draw_text(
            ctx, value, legend_x + 17, y + 12 + len(lines) * line_h,
            size, _lighten(piece.color, 0.08), bold=True, max_w=text_w,
        )
        y += (len(lines) + 1) * line_h + (6 if size > 12 else 3)
    if legend_note:
        draw_text(ctx, legend_note, rect.x() + 14, rect.bottom() - 12, 10.5, MUTED, max_w=rect.width() - 28)


# --------------------------------------------------------------------------
# SINE
# --------------------------------------------------------------------------

_SINE_STAGE_COLORS: Final = ("#21e05c", "#ffd21f", "#ff4b2b")


def _paint_sine(ctx: _Ctx, model: SinePanel) -> None:
    p = ctx.p
    organ = "SINE"
    left = LEFT_INSET
    _paint_inset(ctx, left, "EPISODE FLOW (FUNNEL)", organ)
    if model.status != AVAILABLE:
        _paint_empty(ctx, left, model.status, "SINE EPISODES", organ)
        _paint_inset(ctx, DONUT_INSET, "EPISODE OUTCOMES", organ)
        _paint_empty(ctx, DONUT_INSET, model.status, "EPISODES", organ)
        _paint_cards(ctx, model.cards, organ)
        return

    total = model.total or 0
    max_w = left.width() - 60
    cx = left.center().x()
    top = left.y() + 44
    stage_h, gap = 58.0, 5.0

    def width_for(count: int) -> float:
        ratio = (count / total) if total else 0.0
        return max_w * (0.36 + 0.64 * ratio)

    previous_w = max_w
    for index, stage in enumerate(model.stages):
        y = top + index * (stage_h + gap)
        bottom_w = width_for(stage.count)
        color = _SINE_STAGE_COLORS[index]
        path = QPainterPath()
        path.moveTo(cx - previous_w / 2, y)
        path.lineTo(cx + previous_w / 2, y)
        path.lineTo(cx + bottom_w / 2, y + stage_h)
        path.lineTo(cx - bottom_w / 2, y + stage_h)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_vgradient(QRectF(cx - previous_w / 2, y, previous_w, stage_h), _lighten(color, 0.06), _darken(color, 0.62)))
        p.drawPath(path)
        glow_path(ctx, path, color, 1.6, layers=3, strength=0.5, cap=Qt.PenCapStyle.RoundCap)
        ink = "#08101e" if _luma(color) > 0.55 else "#ffffff"
        text_w = min(previous_w, bottom_w) - 26
        draw_text(ctx, stage.label, cx, y + 23, 17, ink, align="c", bold=True, spacing=0.04, max_w=text_w)
        draw_text(ctx, f"{stage.count:,}  ·  {stage.share_text}", cx, y + 44, 15.5, ink, align="c", bold=True, max_w=text_w)
        previous_w = bottom_w

    note_y = top + 3 * (stage_h + gap) + 6
    draw_text(
        ctx, f"Unique recorded episodes; % of {total:,} episodes. Escalation only.",
        left.x() + 14, note_y, 11, MUTED, max_w=left.width() - 28,
    )
    # Recovery is a separate outcome, never a fourth escalation stage.
    divider_y = note_y + 20
    p.setPen(QPen(_color(PURPLE_RETURN, 0.55), 1.2, Qt.PenStyle.DashLine))
    p.drawLine(QPointF(left.x() + 14, divider_y), QPointF(left.right() - 14, divider_y))
    draw_text(ctx, "RECOVERY OUTCOME (SEPARATE FROM ESCALATION)", left.x() + 14, divider_y + 19, 12, PURPLE_RETURN, bold=True, spacing=0.05, max_w=left.width() - 28)
    track = QRectF(left.x() + 14, divider_y + 28, left.width() - 28, 30)
    p.setPen(QPen(_color(PURPLE_RETURN, 0.5), 1.0))
    p.setBrush(_color("#160c26", 0.9))
    p.drawRoundedRect(track, 7, 7)
    returned = model.returned or 0
    if total and returned:
        fill = QRectF(track.x(), track.y(), max(6.0, track.width() * returned / total), track.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_vgradient(fill, _lighten(PURPLE_RETURN, 0.06), _darken(PURPLE_RETURN, 0.55)))
        p.drawRoundedRect(fill, 7, 7)
    draw_text(
        ctx, f"VERIFIED RETURN  {returned:,} of {total:,} episodes  ({model.return_share_text})",
        track.center().x(), track.y() + 20, 13.5, "#ffffff", align="c", bold=True, max_w=track.width() - 16,
    )

    _paint_donut(ctx, DONUT_INSET, "EPISODE OUTCOMES", model.slices, total, "EPISODES", organ, "Verified return vs. none recorded")
    _paint_cards(ctx, model.cards, organ)


# --------------------------------------------------------------------------
# MINE
# --------------------------------------------------------------------------

_TONE_COLORS: Final = {"returned": "#2dff8a", "other": "#22c8ff", "undocumented": "#8091b4"}


def _flow_curve(ctx: _Ctx, x1: float, y1: float, x2: float, y2: float, color: str, width: float) -> None:
    path = QPainterPath(QPointF(x1, y1))
    mid = (x1 + x2) / 2.0
    path.cubicTo(mid, y1, mid, y2, x2, y2)
    glow_path(ctx, path, color, width, layers=3, strength=0.4, cap=Qt.PenCapStyle.FlatCap)


def _flow_node(ctx: _Ctx, rect: QRectF, color: str, line1: str, line2: str, *, dashed: bool = False, compact: bool = False) -> None:
    p = ctx.p
    ctx.push_region("mine-node", rect)
    path = rounded_path(rect, 8)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_vgradient(rect, _darken(color, 0.55), _darken(color, 0.28)))
    p.drawPath(path)
    if dashed:
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_color(color, 0.95), 1.4, Qt.PenStyle.DashLine))
        p.drawPath(path)
    else:
        glow_path(ctx, path, color, 1.5, layers=3, strength=0.45)
    cx = rect.center().x()
    if compact:
        draw_text(ctx, f"{line1}  {line2}", cx, rect.center().y() + 4, 11.5, "#ffffff", align="c", bold=True, max_w=rect.width() - 10)
    else:
        draw_text(ctx, line1, cx, rect.y() + rect.height() * 0.42, 12.5, "#ffffff", align="c", bold=True, max_w=rect.width() - 12)
        draw_text(ctx, line2, cx, rect.y() + rect.height() * 0.78, 12.5, "#ffffff", align="c", bold=True, max_w=rect.width() - 12)
    ctx.pop_region()


def _paint_mine(ctx: _Ctx, model: MinePanel) -> None:
    organ = "MINE"
    left = LEFT_INSET
    _paint_inset(ctx, left, "DECISION PATHWAY (FLOW)", organ)
    if model.status != AVAILABLE:
        _paint_empty(ctx, left, model.status, "MINE-1 CHOICES", organ)
        _paint_inset(ctx, DONUT_INSET, "EPISODE OUTCOMES", organ)
        _paint_empty(ctx, DONUT_INSET, model.status, "EPISODES", organ)
        _paint_cards(ctx, model.cards, organ)
        return

    total = model.total or 0
    area_top, area_bottom = left.y() + 46, left.bottom() - 38
    root_x, root_w = left.x() + 14, 70.0
    choice_x, choice_w = left.x() + 114, 120.0
    out_x, out_w = left.x() + 264, left.width() - 264 - 14

    inter_group, node_gap, group_min = 14.0, 5.0, 58.0
    height_budget = area_bottom - area_top

    def content_height(node_h: float) -> float:
        heights = [
            max(group_min, len(c.outcomes) * node_h + max(0, len(c.outcomes) - 1) * node_gap)
            for c in model.choices
        ]
        return sum(heights) + inter_group

    # Largest node height that keeps the whole flow above its footnote.
    node_h = 50.0
    while node_h > 20.0 and content_height(node_h) > height_budget:
        node_h -= 1.0
    compact = node_h < 34.0

    groups = []
    for choice in model.choices:
        k = len(choice.outcomes)
        groups.append((choice, max(group_min, k * node_h + max(0, k - 1) * node_gap)))
    content_h = sum(h for _c, h in groups) + inter_group
    y = area_top + max(0.0, (height_budget - content_h) / 2.0)

    root_rect = QRectF(root_x, (area_top + area_bottom) / 2 - 46, root_w, 92)
    choice_colors = {"I_WILL_COME_BACK": "#1fd35a", "ITS_IMPORTANT": "#ff9a1f"}
    layout = []
    for choice, height in groups:
        layout.append((choice, y, height))
        y += height + inter_group

    # Connectors first, so nodes sit above them.
    for choice, top, height in layout:
        cy = top + height / 2.0
        color = choice_colors[choice.key]
        share = (choice.count / total) if total else 0.0
        _flow_curve(ctx, root_rect.right(), root_rect.center().y(), choice_x, cy, color, 2.5 + 9.0 * share)
        for index, outcome in enumerate(choice.outcomes):
            oy = top + index * (node_h + node_gap) + node_h / 2.0
            share_o = (outcome.count / choice.count) if choice.count else 0.0
            _flow_curve(ctx, choice_x + choice_w, cy, out_x, oy, _TONE_COLORS[outcome.tone], 2.0 + 8.0 * share_o)

    _flow_node(ctx, root_rect, "#2a6cff", "MINE-1", f"{total:,} choices")
    for choice, top, height in layout:
        cy = top + height / 2.0
        rect = QRectF(choice_x, cy - 30, choice_w, 60)
        _flow_node(ctx, rect, choice_colors[choice.key], choice.label, f"{choice.count:,} ({choice.share_text})")
        for index, outcome in enumerate(choice.outcomes):
            orect = QRectF(out_x, top + index * (node_h + node_gap), out_w, node_h)
            line2 = f"{outcome.count:,}/{outcome.denominator:,}" + ("" if compact else f" ({outcome.share_text})")
            _flow_node(ctx, orect, _TONE_COLORS[outcome.tone], outcome.label, line2, dashed=outcome.tone == "undocumented", compact=compact)

    draw_text(
        ctx, "Each branch is its own denominator; a choice is not a verified return.",
        left.x() + 14, left.bottom() - 10, 11, MUTED, max_w=left.width() - 28,
    )
    _paint_donut(ctx, DONUT_INSET, "EPISODE OUTCOMES", model.slices, total, "CHOICES", organ, "Documented closure vs. remainder")
    _paint_cards(ctx, model.cards, organ)


# --------------------------------------------------------------------------
# COSINE
# --------------------------------------------------------------------------


def _nice_step(maximum: float) -> float:
    for candidate in (30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 14400, 28800, 86400):
        if maximum / candidate <= 6:
            return float(candidate)
    return 86400.0


def _axis_label(seconds: float) -> str:
    if seconds == 0:
        return "0"
    return "+" + fmt_elapsed(seconds)


def _paint_cosine(ctx: _Ctx, model: CosinePanel) -> None:
    p = ctx.p
    organ = "COSINE"
    color = ORGAN_COLOR[organ]
    left = LEFT_INSET
    _paint_inset(ctx, left, "RECORDED EVENT TIMELINE", organ)
    if model.status != AVAILABLE:
        _paint_empty(ctx, left, model.status, "COSINE EPISODES", organ)
        _paint_inset(ctx, DONUT_INSET, "RECORDED EVENTS", organ)
        _paint_empty(ctx, DONUT_INSET, model.status, "EVENTS", organ)
        _paint_cards(ctx, model.cards, organ)
        return

    label_x = left.x() + 14
    x0, x1 = left.x() + 122, left.x() + 388
    count_x = left.right() - 14
    header_y = left.y() + 46
    draw_text(ctx, "EPISODE", label_x, header_y, 10.5, MUTED, bold=True, spacing=0.06)
    draw_text(ctx, "EVENTS", count_x, header_y, 10.5, MUTED, bold=True, spacing=0.06, align="r")
    axis_max = model.axis_max_seconds if model.axis_max_seconds > 0 else 60.0
    top = left.y() + 56
    row_h = min(54.0, 190.0 / max(1, len(model.rows)))
    for index, row in enumerate(model.rows):
        cy = top + index * row_h + row_h / 2
        draw_text(ctx, row.date_label, label_x, cy - 2, 13, INK, bold=True, max_w=100)
        draw_text(ctx, row.span_label, label_x, cy + 13, 11.5, MUTED, max_w=104)
        p.setPen(QPen(_color(color, 0.35), 1.2, Qt.PenStyle.DotLine))
        p.drawLine(QPointF(x0, cy), QPointF(x1, cy))
        for offset in row.offsets_seconds:
            px = x0 + (x1 - x0) * min(1.0, offset / axis_max)
            marker = QPainterPath()
            marker.addEllipse(QPointF(px, cy), 5.0, 5.0)
            glow_path(ctx, marker, "#d9a8ff", 1.6, layers=2, strength=0.5)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_color("#f0dcff", 0.9))
            p.drawEllipse(QPointF(px, cy), 2.6, 2.6)
        draw_text(ctx, f"{row.event_count:,}", count_x, cy + 5, 15, INK, align="r", bold=True, max_w=40)

    axis_y = top + len(model.rows) * row_h + 6
    p.setPen(QPen(_color(MUTED, 0.7), 1.2))
    p.drawLine(QPointF(x0, axis_y), QPointF(x1, axis_y))
    step = _nice_step(axis_max)
    tick = 0.0
    while tick <= axis_max + 1e-6:
        px = x0 + (x1 - x0) * tick / axis_max
        p.drawLine(QPointF(px, axis_y), QPointF(px, axis_y + 4))
        draw_text(ctx, _axis_label(tick), px, axis_y + 17, 10.5, MUTED, align="c", max_w=52)
        tick += step

    shown = len(model.rows)
    total = model.total_episodes or 0
    notes = (
        f"Latest {shown} of {total:,} episodes. Each dot is one recorded event.",
        "Position = elapsed time since the episode's first event.",
        f"No viewing duration is inferred. Clock times: {model.tz_label}.",
    )
    for index, note in enumerate(notes):
        draw_text(ctx, note, left.x() + 14, left.bottom() - 34 + index * 14, 10.5, MUTED, max_w=left.width() - 28)

    total_events = model.total_events or 0
    _paint_donut(ctx, DONUT_INSET, "RECORDED EVENTS", model.slices, total_events, "EVENTS", organ, "Count by recorded event type")
    _paint_cards(ctx, model.cards, organ)


# --------------------------------------------------------------------------
# COSECANT
# --------------------------------------------------------------------------


def _paint_cosecant(ctx: _Ctx, model: CosecantPanel) -> None:
    p = ctx.p
    organ = "COSECANT"
    left = LEFT_INSET
    _paint_inset(ctx, left, "RETURN WINDOW (STEP LADDER)", organ)
    if model.status != AVAILABLE:
        _paint_empty(ctx, left, model.status, "COSECANT BREAKS", organ)
        _paint_inset(ctx, DONUT_INSET, "EPISODE OUTCOMES", organ)
        _paint_empty(ctx, DONUT_INSET, model.status, "BREAKS", organ)
        _paint_cards(ctx, model.cards, organ)
        return

    total = model.total or 0
    axis_x = left.x() + 44
    right_edge = left.right() - 12
    baseline = left.y() + 214
    max_h = 112.0
    step_w = (right_edge - axis_x) / len(model.steps)
    bar_w = step_w - 14

    p.setPen(QPen(_color(MUTED, 0.35), 1.0, Qt.PenStyle.DotLine))
    p.drawLine(QPointF(axis_x, baseline - max_h), QPointF(right_edge, baseline - max_h))
    draw_text(ctx, f"{total:,}", axis_x - 6, baseline - max_h + 4, 11, MUTED, align="r", max_w=34)
    draw_text(ctx, "0", axis_x - 6, baseline + 4, 11, MUTED, align="r", max_w=34)
    p.setPen(QPen(_color(MUTED, 0.8), 1.4))
    p.drawLine(QPointF(axis_x, baseline), QPointF(right_edge, baseline))

    for index, step in enumerate(model.steps):
        color = LADDER_COLORS[step.kind]
        cx = axis_x + step_w * index + step_w / 2
        height = (max_h * step.count / total) if total else 0.0
        rect = QRectF(cx - bar_w / 2, baseline - height, bar_w, height)
        if height > 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_vgradient(rect, _lighten(color, 0.05), _darken(color, 0.5)))
            p.drawRect(rect)
            glow_path(ctx, rounded_path(rect, 1.5), color, 1.4, layers=3, strength=0.5, cap=Qt.PenCapStyle.FlatCap)
        label_y = baseline - height - 32
        draw_text(ctx, f"{step.count:,}", cx, label_y + 12, 16, INK, align="c", bold=True, max_w=bar_w + 6)
        draw_text(ctx, f"({step.share_text})", cx, label_y + 26, 11, MUTED, align="c", max_w=bar_w + 8)
        for line_index, line in enumerate(step.lines):
            draw_text(ctx, line, cx, baseline + 17 + line_index * 13, 11, INK, align="c", bold=True, max_w=step_w - 6)
        draw_text(ctx, step.median_text, cx, baseline + 52, 12, color, align="c", bold=True, max_w=step_w - 6)
    draw_text(ctx, "MEDIAN", axis_x - 6, baseline + 52, 9.5, MUTED, align="r", bold=True, max_w=38)

    notes = (
        f"Bars: breaks that recorded each milestone, of {total:,} breaks.",
        "Median = elapsed from the same break's start on its recorded",
        "monotonic clock, only for breaks with both milestones.",
    )
    for index, note in enumerate(notes):
        draw_text(ctx, note, left.x() + 14, left.bottom() - 34 + index * 14, 10.5, MUTED, max_w=left.width() - 28)

    _paint_donut(ctx, DONUT_INSET, "EPISODE OUTCOMES", model.slices, total, "BREAKS", organ, "Confirmed vs. none recorded")
    _paint_cards(ctx, model.cards, organ)


# --------------------------------------------------------------------------
# Public painter
# --------------------------------------------------------------------------


def load_official_logo() -> QImage:
    """Load the approved logo; fail explicitly rather than substitute art."""

    path = resource_path(LOGO_RESOURCE)
    if not path.is_file():
        raise PosterAssetError("Official MYELIN logo asset is missing.")
    image = QImage(str(path))
    if image.isNull():
        raise PosterAssetError("Official MYELIN logo asset could not be decoded.")
    return image


_PANEL_PAINTERS: Final = {
    "SINE": ("sine", _paint_sine),
    "MINE": ("mine", _paint_mine),
    "COSINE": ("cosine", _paint_cosine),
    "COSECANT": ("cosecant", _paint_cosecant),
}


# The five-organ poster is a presentation layer over the existing four-organ
# snapshot.  SECANT and whole-system numbers deliberately have no data binding.
POSTER_RECTS: Final = {
    "SINE": QRectF(15, 110, 570, 312),
    "MINE": QRectF(1095, 110, 570, 312),
    "COSINE": QRectF(15, 435, 570, 225),
    "COSECANT": QRectF(1095, 435, 570, 225),
    "SECANT": QRectF(15, 672, 810, 205),
    "SYSTEM": QRectF(838, 672, 827, 205),
}


def _new_frame_fill(ctx: _Ctx, rect: QRectF) -> None:
    p = ctx.p
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_vgradient(rect, QColor("#0b1730"), QColor("#030711")))
    p.drawRoundedRect(rect, 13, 13)


def _new_frame(ctx: _Ctx, rect: QRectF, tone: str, name: str, subtitle: str) -> None:
    p = ctx.p
    glow_path(ctx, rounded_path(rect.adjusted(1, 1, -1, -1), 12), tone, 2.0, layers=4, strength=0.42)
    p.setPen(QPen(_color(tone, 0.42), 1.1))
    p.drawLine(QPointF(rect.x() + 14, rect.y() + 56), QPointF(rect.right() - 14, rect.y() + 56))
    icon = {"SINE": _icon_shield, "MINE": _icon_chat, "COSINE": _icon_play,
            "SECANT": _icon_target, "COSECANT": _icon_book,
            "SYSTEM SUMMARY": _icon_bars}[name]
    _draw_icon(ctx, icon, QRectF(rect.x() + 19, rect.y() + 15, 31, 29), tone, 2.0)
    draw_text(ctx, name, rect.x() + 61, rect.y() + 39, 32, tone, bold=True, black=True, glow=tone)
    draw_text(ctx, subtitle, rect.right() - 20, rect.y() + 37, 13, INK, align="r", max_w=rect.width() - 200)


def _box(ctx: _Ctx, rect: QRectF, tone: str = CYAN) -> None:
    p = ctx.p
    p.setPen(QPen(_color(tone, 0.58), 1.1))
    p.setBrush(_color("#050d1d", 0.92))
    p.drawRoundedRect(rect, 8, 8)


def _heading(ctx: _Ctx, title: str, x: float, y: float, width: float, tone: str = INK) -> None:
    draw_text(ctx, title, x, y, 13, tone, bold=True, spacing=0.04, max_w=width)


def _stat(ctx: _Ctx, rect: QRectF, value: str, label: str, tone: str) -> None:
    _box(ctx, rect, tone)
    draw_text(ctx, value, rect.center().x(), rect.y() + 32, 25, tone, align="c", bold=True, max_w=rect.width() - 15)
    draw_text(ctx, label, rect.center().x(), rect.bottom() - 11, 11.5, INK, align="c", bold=True, max_w=rect.width() - 12)


def _ring(ctx: _Ctx, cx: float, cy: float, radius: float, pieces: Sequence[DonutSlice], total: int, tone: str, label: str) -> None:
    p = ctx.p
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(_color("#263553"), 13))
    p.drawEllipse(QPointF(cx, cy), radius, radius)
    angle = 90.0
    if total > 0:
        for piece in pieces:
            span = -360.0 * piece.count / total
            color = tone if piece is pieces[0] else piece.color
            glow_path(ctx, _donut_arc(QPointF(cx, cy), radius, angle, span), color, 13, layers=2, strength=0.3)
            angle += span
    draw_text(ctx, f"{total:,}", cx, cy + 5, 23, INK, align="c", bold=True, max_w=66)
    draw_text(ctx, label, cx, cy + 22, 10.5, MUTED, align="c", bold=True, max_w=78)


def _status(ctx: _Ctx, rect: QRectF, state: str, noun: str, tone: str) -> bool:
    if state == AVAILABLE:
        return False
    label = f"NO RECORDED {noun}" if state == NO_DATA else "EVIDENCE UNAVAILABLE"
    draw_text(ctx, label, rect.center().x(), rect.center().y() + 8, 22, tone, align="c", bold=True, max_w=rect.width() - 40)
    return True


def _new_sine(ctx: _Ctx, model: SinePanel) -> None:
    r = POSTER_RECTS["SINE"]
    _new_frame(ctx, r, ORANGE, "SINE", "GENERAL DRIFT REGULATION")
    if _status(ctx, r, model.status, "SINE EPISODES", ORANGE):
        return
    _heading(ctx, "INTERVENTION STAGES", 33, 185, 240)
    for i, stage in enumerate(model.stages[:3]):
        x = 34 + i * 181
        _box(ctx, QRectF(x, 198, 170, 54), ORANGE)
        draw_text(ctx, stage.label, x + 85, 221, 15, ORANGE, align="c", bold=True)
        draw_text(ctx, f"{stage.count:,}  ·  {stage.share_text}", x + 85, 241, 13, INK, align="c", max_w=155)
    _box(ctx, QRectF(30, 263, 300, 143), ORANGE)
    _heading(ctx, "EPISODE ESCALATION", 43, 285, 260)
    maximum = max((s.count for s in model.stages), default=1) or 1
    for i, stage in enumerate(model.stages[:3]):
        y = 301 + i * 30
        draw_text(ctx, stage.label, 44, y + 13, 12, INK)
        p = ctx.p
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_color(ORANGE, 0.25))
        p.drawRoundedRect(QRectF(124, y, 172, 16), 4, 4)
        p.setBrush(_color(ORANGE, 0.9))
        if stage.count:
            p.drawRoundedRect(QRectF(124, y, 172 * stage.count / maximum, 16), 4, 4)
        draw_text(ctx, f"{stage.count:,}", 309, y + 13, 11, INK, align="r")
    _box(ctx, QRectF(341, 263, 228, 143), ORANGE)
    _heading(ctx, "RETURN OUTCOME", 353, 285, 190)
    _ring(ctx, 397, 343, 34, model.slices, model.total or 0, ORANGE, "EPISODES")
    draw_text(ctx, f"{model.returned or 0:,} returned", 451, 335, 13, INK, max_w=108)
    draw_text(ctx, model.return_share_text, 451, 357, 17, ORANGE, bold=True)


def _new_mine(ctx: _Ctx, model: MinePanel) -> None:
    r = POSTER_RECTS["MINE"]
    _new_frame(ctx, r, PINK, "MINE", "MESSAGING PATHWAY")
    if _status(ctx, r, model.status, "MINE-1 CHOICES", PINK):
        return
    _box(ctx, QRectF(1110, 176, 312, 230), PINK)
    _heading(ctx, "DECISION PATHWAY", 1123, 198, 260)
    total = model.total or 0
    _stat(ctx, QRectF(1124, 211, 105, 56), f"{total:,}", "CHOICES", PINK)
    for i, choice in enumerate(model.choices[:2]):
        y = 280 + i * 55
        _box(ctx, QRectF(1130, y, 276, 45), PINK)
        draw_text(ctx, choice.label, 1142, y + 20, 13, INK, bold=True, max_w=184)
        draw_text(ctx, f"{choice.count:,} ({choice.share_text})", 1395, y + 35, 12, PINK, align="r", max_w=110)
    draw_text(ctx, "Each choice has its own outcome path.", 1127, 391, 11.5, MUTED, max_w=260)
    _box(ctx, QRectF(1432, 176, 217, 230), PINK)
    _heading(ctx, "RECORDED OUTCOMES", 1444, 198, 190)
    _ring(ctx, 1491, 277, 46, model.slices, total, PINK, "CHOICES")
    draw_text(ctx, f"{model.documented or 0:,} documented", 1446, 366, 13, INK, max_w=185)
    draw_text(ctx, "No inference from missing closure", 1446, 388, 11, MUTED, max_w=185)


def _new_cosine(ctx: _Ctx, model: CosinePanel) -> None:
    r = POSTER_RECTS["COSINE"]
    _new_frame(ctx, r, VIOLET, "COSINE", "OTT VIEWING AWARENESS")
    if _status(ctx, r, model.status, "COSINE EPISODES", VIOLET):
        return
    _box(ctx, QRectF(30, 502, 334, 143), VIOLET)
    _heading(ctx, "RECORDED EVENT TIMELINE", 43, 524, 300)
    rows = model.rows[:5]
    max_events = max((row.event_count for row in rows), default=1) or 1
    for i, row in enumerate(rows):
        y = 535 + i * 20
        draw_text(ctx, row.date_label, 44, y + 14, 11, INK, max_w=105)
        p = ctx.p
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_color(VIOLET, 0.27))
        p.drawRoundedRect(QRectF(145, y + 2, 166, 13), 3, 3)
        p.setBrush(_color(VIOLET, 0.85))
        if row.event_count:
            p.drawRoundedRect(QRectF(145, y + 2, 166 * row.event_count / max_events, 13), 3, 3)
        draw_text(ctx, str(row.event_count), 344, y + 14, 11, INK, align="r")
    draw_text(ctx, f"LATEST {len(rows)} OF {model.total_episodes or 0} EPISODES", 44, 643, 10.5, MUTED, max_w=300)
    _box(ctx, QRectF(374, 502, 195, 143), VIOLET)
    _heading(ctx, "EVENTS", 387, 524, 140)
    _ring(ctx, 430, 581, 34, model.slices, model.total_events or 0, VIOLET, "EVENTS")
    draw_text(ctx, f"{model.total_episodes or 0:,} episodes", 482, 574, 13, INK, max_w=75)
    draw_text(ctx, model.tz_label, 482, 599, 11, MUTED, max_w=72)


def _new_cosecant(ctx: _Ctx, model: CosecantPanel) -> None:
    r = POSTER_RECTS["COSECANT"]
    _new_frame(ctx, r, GREEN, "COSECANT", "APPROVED STUDY BREAKS")
    if _status(ctx, r, model.status, "COSECANT BREAKS", GREEN):
        return
    _box(ctx, QRectF(1110, 502, 335, 143), GREEN)
    _heading(ctx, "RETURN LADDER", 1123, 524, 300)
    maximum = model.total or 1
    for i, step in enumerate(model.steps[:5]):
        y = 535 + i * 20
        label = " ".join(step.lines).title()
        draw_text(ctx, label, 1124, y + 14, 11.5, INK, max_w=150)
        p = ctx.p
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_color(GREEN, 0.22))
        p.drawRoundedRect(QRectF(1278, y + 2, 115, 13), 3, 3)
        p.setBrush(_color(GREEN, 0.85))
        if step.count:
            p.drawRoundedRect(QRectF(1278, y + 2, 115 * step.count / maximum, 13), 3, 3)
        draw_text(ctx, str(step.count), 1428, y + 14, 11, INK, align="r")
    _box(ctx, QRectF(1455, 502, 194, 143), GREEN)
    _heading(ctx, "RETURN OUTCOME", 1468, 524, 165)
    _ring(ctx, 1510, 582, 34, model.slices, model.total or 0, GREEN, "BREAKS")
    draw_text(ctx, f"{model.confirmed or 0:,} confirmed", 1561, 575, 12, INK, max_w=73)


def _new_secant(ctx: _Ctx) -> None:
    r = POSTER_RECTS["SECANT"]
    _new_frame(ctx, r, BLUE, "SECANT", "STUDY OFF-TASK AND RECOVERY REGULATION")
    _box(ctx, QRectF(30, 739, 282, 123), BLUE)
    _heading(ctx, "STAGE DISTRIBUTION", 43, 761, 246)
    for i, stage in enumerate(("SECANT-1", "SECANT-2", "SECANT-3")):
        y = 770 + i * 25
        draw_text(ctx, stage, 44, y + 15, 12, INK)
        p = ctx.p
        p.setPen(QPen(_color(BLUE, 0.55), 1))
        p.setBrush(_color(BLUE, 0.12))
        p.drawRoundedRect(QRectF(149, y + 3, 147, 14), 3, 3)
        draw_text(ctx, "—", 220, y + 15, 13, MUTED, align="c")
    _box(ctx, QRectF(322, 739, 488, 123), BLUE)
    _heading(ctx, "RECOVERY JOURNEY", 335, 761, 450)
    stages = ("OFF-TASK", "RETURN PROMPT", "RETURN", "VERIFICATION")
    for i, stage in enumerate(stages):
        x = 335 + i * 118
        _box(ctx, QRectF(x, 782, 105, 45), BLUE if i < 3 else GREEN)
        draw_text(ctx, stage, x + 52.5, 809, 11, INK, align="c", bold=True, max_w=96)
        if i < 3:
            draw_text(ctx, "→", x + 111, 811, 17, CYAN, align="c")
    draw_text(ctx, "AWAITING APPROVED SECANT ANALYTICS", 564, 849, 12, MUTED, align="c", max_w=445)


def _new_system(ctx: _Ctx) -> None:
    r = POSTER_RECTS["SYSTEM"]
    _new_frame(ctx, r, CYAN, "SYSTEM SUMMARY", "WHOLE-SYSTEM VISUAL AREA")
    labels = ("SESSIONS", "INTERVENTIONS", "RETURNS", "STUDY", "BREAKS")
    for i, label in enumerate(labels):
        x = 853 + i * 159
        _stat(ctx, QRectF(x, 743, 149, 78), "—", label, CYAN)
    draw_text(ctx, "Whole-system metrics awaiting approved definitions", 1250, 849, 13, MUTED, align="c", max_w=780)


def _architecture_node(ctx: _Ctx, rect: QRectF, name: str, detail: str, tone: str) -> None:
    p = ctx.p
    path = QPainterPath()
    bevel = 17
    path.moveTo(rect.left() + bevel, rect.top())
    path.lineTo(rect.right() - bevel, rect.top())
    path.lineTo(rect.right(), rect.top() + bevel)
    path.lineTo(rect.right(), rect.bottom() - bevel)
    path.lineTo(rect.right() - bevel, rect.bottom())
    path.lineTo(rect.left() + bevel, rect.bottom())
    path.lineTo(rect.left(), rect.bottom() - bevel)
    path.lineTo(rect.left(), rect.top() + bevel)
    path.closeSubpath()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_vgradient(rect, _darken(tone, 0.24), QColor("#030914")))
    p.drawPath(path)
    glow_path(ctx, path, tone, 2.1, layers=4, strength=0.46)
    icon = {"SINE": _icon_shield, "MINE": _icon_chat, "COSINE": _icon_play,
            "SECANT": _icon_target, "COSECANT": _icon_book}[name]
    _draw_icon(ctx, icon, QRectF(rect.center().x() - 12, rect.y() + 6, 24, 24), tone, 1.7)
    draw_text(ctx, name, rect.center().x(), rect.y() + 50, 24, tone, align="c", bold=True, black=True, glow=tone, max_w=rect.width() - 15)
    draw_text(ctx, detail, rect.center().x(), rect.y() + 66, 11.5, INK, align="c", max_w=rect.width() - 15)


def _new_architecture(ctx: _Ctx) -> None:
    p = ctx.p
    lines = ((840, 212, 840, 230), (840, 230, 708, 230), (840, 230, 972, 230),
             (708, 230, 708, 251), (972, 230, 972, 251),
             (708, 341, 708, 366), (972, 341, 972, 366),
             (708, 454, 708, 501), (972, 454, 972, 501),
             (708, 501, 840, 501), (972, 501, 840, 501), (840, 501, 840, 530))
    for x1, y1, x2, y2 in lines:
        p.setPen(QPen(_color(CYAN, 0.8), 1.6))
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    _architecture_node(ctx, QRectF(740, 118, 200, 94), "SINE", "DETECT · NUDGE · RECOVER", ORANGE)
    _architecture_node(ctx, QRectF(598, 251, 220, 90), "COSINE", "OTT VIEWING AWARENESS", VIOLET)
    _architecture_node(ctx, QRectF(862, 251, 220, 90), "MINE", "MESSAGING CHOICES", PINK)
    _architecture_node(ctx, QRectF(598, 366, 220, 88), "SECANT", "STUDY RECOVERY", BLUE)
    _architecture_node(ctx, QRectF(862, 366, 220, 88), "COSECANT", "APPROVED BREAKS", GREEN)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(_color("#07162b", 0.95))
    p.drawEllipse(QPointF(840, 565), 72, 72)
    glow_path(ctx, _donut_arc(QPointF(840, 565), 72, 0, 359.9), CYAN, 2.0, layers=4, strength=0.35)
    draw_text(ctx, "MYELIN", 840, 555, 20, CYAN, align="c", bold=True)
    draw_text(ctx, "SYSTEM CORE", 840, 580, 13, INK, align="c", bold=True)
    draw_text(ctx, "DATA     →     INSIGHT     →     BETTER HABITS", 840, 657, 13, CYAN, align="c", spacing=0.09, max_w=480)


def _new_header(ctx: _Ctx, logo: QImage) -> None:
    p = ctx.p
    ctx.push_region("header", QRectF(0, 0, CANVAS_W, 105))
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    scale = min(50 / logo.width(), 50 / logo.height())
    lw, lh = logo.width() * scale, logo.height() * scale
    p.drawImage(QRectF(606, 22, lw, lh), logo)
    draw_text(ctx, "MYELIN", 847, 70, 65, CYAN, align="c", bold=True, black=True, glow=CYAN, max_w=420)
    draw_text(ctx, "2.0", 1047, 70, 53, "#8daaff", align="c", bold=True, black=True, glow=BLUE)
    draw_text(ctx, "BEHAVIOUR INTELLIGENCE FOR A FOCUSED TOMORROW", 840, 96, 13, CYAN, align="c", spacing=0.1, max_w=520)
    draw_text(ctx, "OBSERVE  ·  UNDERSTAND  ·  NUDGE  ·  RECOVER  ·  REPEAT", 55, 41, 14, CYAN, spacing=0.13, max_w=515)
    draw_text(ctx, "FIVE ORGANS  ·  ONE SYSTEM  ·  A BRIGHTER YOU", 92, 78, 13, CYAN, spacing=0.1, max_w=475)
    draw_text(ctx, "“Distraction is a signal.", 1295, 43, 19, INK, align="c", italic=True, max_w=350)
    draw_text(ctx, "A better you is the response.”", 1295, 72, 19, INK, align="c", italic=True, max_w=350)
    p.setPen(QPen(_color(CYAN, 0.68), 1.4))
    p.drawLine(QPointF(1464, 12), QPointF(1464, 96))
    for i, line in enumerate(("AWARENESS", "DISCIPLINE", "SELF-CONTROL", "BETTER HABITS")):
        draw_text(ctx, line, 1481, 28 + i * 21, 13, CYAN, spacing=0.08, max_w=181)
    ctx.pop_region()


def _new_footer(ctx: _Ctx, model: PosterModel) -> None:
    p = ctx.p
    ctx.push_region("footer", QRectF(0, 884, CANVAS_W, 61))
    p.setPen(QPen(_color(CYAN, 0.4), 1))
    p.drawLine(QPointF(15, 885), QPointF(1665, 885))
    for i, label in enumerate(("PRODUCTIVE USE", "SELF-CONTROL", "BETTER HABITS", "A CALMER MIND", "A BRIGHTER TOMORROW")):
        cx = 305 + i * 218
        draw_text(ctx, label, cx, 916, 13, CYAN, align="c", bold=True, spacing=0.05, max_w=200)
    draw_text(ctx, "Small Steps · Big Change", 23, 916, 17, INK, italic=True, max_w=247)
    draw_text(ctx, "MYELIN 2.0", 1470, 914, 23, CYAN, bold=True, black=True, max_w=188)
    evidence = (f"Recorded MYELIN data (non-clinical) · {model.generated_label} · snapshot {model.snapshot_label} "
                "· lifetime and episode evidence read separately")
    draw_text(ctx, evidence, 840, 937, 11.5, MUTED, align="c", max_w=1550)
    ctx.pop_region()


def paint_poster(
    painter: QPainter,
    model: PosterModel,
    logo: QImage,
    *,
    width: float,
    height: float,
    log: list[TextPlacement] | None = None,
) -> None:
    """Draw the wide poster without distortion, centred on any export page."""

    if width <= 0 or height <= 0:
        raise ValueError("poster target must have positive dimensions")
    painter.save()
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(QRectF(0, 0, width, height), QColor(NAVY_DEEP))
        scale = min(width / CANVAS_W, height / CANVAS_H)
        painter.translate((width - CANVAS_W * scale) / 2, (height - CANVAS_H * scale) / 2)
        painter.scale(scale, scale)
        ctx = _Ctx(painter, log)
        ctx.push_region("canvas", QRectF(0, 0, CANVAS_W, CANVAS_H))
        _paint_background(ctx)
        for rect in POSTER_RECTS.values():
            _new_frame_fill(ctx, rect)
        _paint_background_logo(ctx, logo)
        _new_header(ctx, logo)
        _new_architecture(ctx)
        for organ, function, data in (
            ("SINE", _new_sine, model.sine),
            ("MINE", _new_mine, model.mine),
            ("COSINE", _new_cosine, model.cosine),
            ("COSECANT", _new_cosecant, model.cosecant),
        ):
            ctx.push_region(f"panel:{organ}", POSTER_RECTS[organ])
            function(ctx, data)
            ctx.pop_region()
        ctx.push_region("panel:SECANT", POSTER_RECTS["SECANT"])
        _new_secant(ctx)
        ctx.pop_region()
        ctx.push_region("panel:SYSTEM", POSTER_RECTS["SYSTEM"])
        _new_system(ctx)
        ctx.pop_region()
        _new_footer(ctx, model)
    finally:
        painter.restore()


def render_poster_image(
    model: PosterModel,
    logo: QImage,
    width_px: int,
    *,
    height_px: int | None = None,
    dpi: int | None = None,
    log: list[TextPlacement] | None = None,
) -> QImage:
    height_px = height_px or int(round(width_px * CANVAS_H / CANVAS_W))
    image = QImage(width_px, height_px, QImage.Format.Format_RGB32)
    image.fill(QColor(NAVY_DEEP))
    if dpi:
        per_meter = int(round(dpi / 0.0254))
        image.setDotsPerMeterX(per_meter)
        image.setDotsPerMeterY(per_meter)
    painter = QPainter(image)
    try:
        paint_poster(painter, model, logo, width=width_px, height=height_px, log=log)
    finally:
        painter.end()
    return image


def write_poster_pdf(model: PosterModel, logo: QImage, path: str | os.PathLike[str]) -> None:
    """Write one A3-landscape page using the canonical painter."""

    writer = QPdfWriter(str(path))
    writer.setResolution(EXPORT_DPI)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A3))
    writer.setPageOrientation(QPageLayout.Orientation.Landscape)
    writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    writer.setTitle("MYELIN 2.0 Neon Poster")
    writer.setCreator("MYELIN")
    painter = QPainter(writer)
    try:
        if not painter.isActive():
            raise OSError("PDF writer could not open its output")
        device_w = float(writer.width())
        device_h = float(writer.height())
        paint_poster(painter, model, logo, width=device_w, height=device_h)
    finally:
        painter.end()


def inspect_pdf(path: str | os.PathLike[str]) -> tuple[int, tuple[float, float]]:
    """Return (page count, first page MediaBox size in points) from the bytes."""

    data = Path(path).read_bytes()
    if not data.startswith(b"%PDF"):
        raise ValueError("not a PDF file")
    pages = re.findall(rb"/Type\s*/Page(?![A-Za-z])", data)
    boxes = re.findall(rb"/MediaBox\s*\[\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*\]", data)
    if not boxes:
        raise ValueError("PDF has no MediaBox")
    x0, y0, x1, y1 = (float(value) for value in boxes[0])
    return len(pages), (x1 - x0, y1 - y0)


def _pdf_matches_a3(path: str | os.PathLike[str]) -> bool:
    count, (width, height) = inspect_pdf(path)
    expected_w, expected_h = (mm / 25.4 * 72.0 for mm in A3_LANDSCAPE_MM)
    return count == 1 and abs(width - expected_w) < 3.0 and abs(height - expected_h) < 3.0


# --------------------------------------------------------------------------
# Interactive surface
# --------------------------------------------------------------------------


class PosterCanvas(QWidget):
    """Shows the canonical painting at the correct aspect ratio (letterboxed)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("neonPosterCanvas")
        self.setMinimumSize(640, 452)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._model: PosterModel | None = None
        self._logo: QImage | None = None
        self._message = "LOADING MYELIN POSTER…"
        self._cache: QPixmap | None = None
        self._cache_key: tuple[int, int] | None = None
        self._rerender = QTimer(self)
        self._rerender.setSingleShot(True)
        self._rerender.setInterval(140)
        self._rerender.timeout.connect(self._refresh_cache)

    @property
    def has_poster(self) -> bool:
        return self._model is not None

    def show_message(self, message: str) -> None:
        self._model = None
        self._cache = None
        self._cache_key = None
        self._message = message
        self.update()

    def show_model(self, model: PosterModel, logo: QImage) -> None:
        self._model, self._logo = model, logo
        self._cache = None
        self._cache_key = None
        self.update()

    def clear(self) -> None:
        self._rerender.stop()
        self._model = None
        self._cache = None
        self._cache_key = None
        self._message = ""
        self.update()

    def _target(self) -> QRectF:
        available = QRectF(self.rect())
        scale = min(available.width() / CANVAS_W, available.height() / CANVAS_H)
        w, h = CANVAS_W * scale, CANVAS_H * scale
        return QRectF(
            available.x() + (available.width() - w) / 2,
            available.y() + (available.height() - h) / 2,
            w,
            h,
        )

    def _device_ratio(self) -> float:
        return max(1.0, float(self.devicePixelRatioF()))

    def _refresh_cache(self) -> None:
        if self._model is None or self._logo is None:
            return
        target = self._target()
        ratio = self._device_ratio()
        width = max(2, int(target.width() * ratio))
        image = render_poster_image(self._model, self._logo, width)
        pixmap = QPixmap.fromImage(image)
        pixmap.setDevicePixelRatio(ratio)
        self._cache = pixmap
        self._cache_key = (width, image.height())
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        if self._model is not None:
            self._rerender.start()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(NAVY_DEEP))
        if self._model is None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            if self._message:
                ctx = _Ctx(painter, None)
                painter.translate(self.width() / 2.0, self.height() / 2.0)
                draw_text(ctx, self._message, 0, 0, 24, CYAN, align="c", bold=True, spacing=0.08, glow=CYAN, max_w=self.width() * 0.8)
            painter.end()
            return
        if self._cache is None:
            self._refresh_cache()
        target = self._target()
        if self._cache is not None:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.drawPixmap(target, self._cache, QRectF(self._cache.rect()))
        painter.end()


_WINDOW_STYLE: Final = """
QDialog#myelinNeonPoster { background: #03060f; }
QFrame#posterControlBar { background: #060c1b; border-top: 1px solid #12405a; }
QLabel#posterStatus { color: #9fb0d0; font-size: 12px; }
QPushButton { background: #07142a; color: #dff6ff; border: 1px solid #22e6ff;
  border-radius: 6px; padding: 8px 16px; font-weight: 700; letter-spacing: 1px; }
QPushButton:hover { background: #0a2140; }
QPushButton:disabled { color: #5d6d90; border-color: #1b3550; }
"""


class NeonPosterWindow(QDialog):
    """The single registered MYELIN Neon Poster surface."""

    analytics_requested = pyqtSignal()
    a3_pdf_requested = pyqtSignal()
    jpg_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("myelinNeonPoster")
        self.setWindowTitle("MYELIN Neon Poster")
        self.setMinimumSize(760, 560)
        self.setStyleSheet(_WINDOW_STYLE)
        self._access_token = 0
        self._access_is_current: Callable[[int], bool] | None = None
        self._load_chart_data: Callable[[int], object] | None = None
        self._model: PosterModel | None = None
        self._logo: QImage | None = None
        self._revocations = 0
        #: Optional test seam: (kind, default_path, filter) -> chosen path or "".
        self.path_chooser: Callable[[str, str, str], str] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.canvas = PosterCanvas(self)
        layout.addWidget(self.canvas, 1)

        bar = QFrame(self)
        bar.setObjectName("posterControlBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(14, 10, 14, 10)
        self.analytics_button = QPushButton("OPEN ANALYTICS SHEET", bar)
        self.pdf_button = QPushButton("EXPORT A3 PDF", bar)
        self.jpg_button = QPushButton("EXPORT HIGH-RES JPG", bar)
        self.status_label = QLabel("", bar)
        self.status_label.setObjectName("posterStatus")
        self.status_label.setWordWrap(True)
        self.analytics_button.clicked.connect(self.analytics_requested.emit)
        self.pdf_button.clicked.connect(self.a3_pdf_requested.emit)
        self.jpg_button.clicked.connect(self.jpg_requested.emit)
        row.addWidget(self.analytics_button)
        row.addWidget(self.pdf_button)
        row.addWidget(self.jpg_button)
        row.addWidget(self.status_label, 1)
        layout.addWidget(bar)
        self._set_export_enabled(False)

        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._deliver_load)

    # -- properties ------------------------------------------------------

    @property
    def access_token(self) -> int:
        return self._access_token

    @property
    def model(self) -> PosterModel | None:
        return self._model

    def sizeHint(self):  # noqa: N802 - Qt override
        from PyQt6.QtCore import QSize

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return QSize(1280, 960)
        area = screen.availableGeometry()
        width = int(min(area.width() * 0.9, (area.height() * 0.88 - 60) * CANVAS_W / CANVAS_H))
        return QSize(max(760, width), max(560, int(width * CANVAS_H / CANVAS_W) + 60))

    # -- lifecycle -------------------------------------------------------

    def present(
        self,
        access_token: int,
        access_is_current: Callable[[int], bool],
        load_chart_data: Callable[[int], object],
    ) -> None:
        self._access_token = int(access_token)
        self._access_is_current = access_is_current
        self._load_chart_data = load_chart_data
        self._model = None
        self._set_export_enabled(False)
        self.status_label.setText("Loading recorded MYELIN data…")
        self.canvas.show_message("LOADING MYELIN POSTER…")
        if not self.isVisible():
            self.resize(self.sizeHint())
        self.show()
        self.raise_()
        self.activateWindow()
        # Load on the GUI thread, after the window has painted once; the token
        # is re-validated when the result is delivered.
        self._load_timer.start(0)

    def revoke_access(self) -> None:
        self._revocations += 1
        self._load_timer.stop()
        self._access_token = 0
        self._access_is_current = None
        self._load_chart_data = None
        self._model = None
        self._set_export_enabled(False)
        self.canvas.clear()
        self.status_label.setText("")
        self.hide()

    def _access_ok(self) -> bool:
        predicate = self._access_is_current
        return bool(predicate is not None and self._access_token and predicate(self._access_token))

    def _deliver_load(self) -> None:
        loader = self._load_chart_data
        if loader is None or not self._access_ok():
            self.revoke_access()
            return
        token = self._access_token
        try:
            data = loader(token)
        except Exception:  # noqa: BLE001 - access loss or read failure; never leak details
            if not self._access_ok():
                self.revoke_access()
            else:
                self.canvas.show_message("CHART DATA UNAVAILABLE")
                self.status_label.setText("Recorded chart data could not be read.")
            return
        if not self._access_ok() or token != self._access_token:
            self.revoke_access()
            return
        try:
            model = build_poster_model(data)
            logo = load_official_logo()
        except PosterAssetError as error:
            self.canvas.show_message("OFFICIAL LOGO MISSING")
            self.status_label.setText(str(error))
            return
        except Exception:  # noqa: BLE001
            self.canvas.show_message("CHART DATA UNAVAILABLE")
            self.status_label.setText("Recorded chart data could not be presented.")
            return
        self._model, self._logo = model, logo
        self.canvas.show_model(model, logo)
        self._set_export_enabled(True)
        self.status_label.setText(
            f"Snapshot {model.snapshot_id} · generated {model.generated_label}"
        )

    def _set_export_enabled(self, enabled: bool) -> None:
        self.pdf_button.setEnabled(enabled)
        self.jpg_button.setEnabled(enabled)

    # -- exports ---------------------------------------------------------

    def export_a3_pdf(
        self, access_token: int, access_is_current: Callable[[int], bool]
    ) -> bool:
        return self._export("PDF", access_token, access_is_current)

    def export_high_resolution_jpg(
        self, access_token: int, access_is_current: Callable[[int], bool]
    ) -> bool:
        return self._export("JPG", access_token, access_is_current)

    def _default_path(self, kind: str) -> str:
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = "A3.pdf" if kind == "PDF" else "A3_300dpi.jpg"
        return str(Path(folder or ".") / f"MYELIN_Poster_{stamp}_{suffix}")

    def _choose_path(self, kind: str) -> str:
        default = self._default_path(kind)
        name_filter = "PDF document (*.pdf)" if kind == "PDF" else "JPEG image (*.jpg *.jpeg)"
        if self.path_chooser is not None:
            return str(self.path_chooser(kind, default, name_filter) or "")
        title = "Export MYELIN poster as A3 PDF" if kind == "PDF" else "Export MYELIN poster as high-resolution JPG"
        chosen, _selected = QFileDialog.getSaveFileName(self, title, default, name_filter)
        return chosen

    def _export(
        self, kind: str, access_token: int, access_is_current: Callable[[int], bool]
    ) -> bool:
        revocations = self._revocations

        def alive() -> bool:
            return bool(
                revocations == self._revocations
                and int(access_token) == self._access_token
                and access_is_current(access_token)
            )

        # 1. Before initiating.
        if not alive():
            return False
        model, logo = self._model, self._logo
        # 2. Before using the displayed snapshot.
        if model is None or logo is None or not alive():
            self.status_label.setText("No poster snapshot is loaded; nothing was exported.")
            return False
        chosen = self._choose_path(kind)
        if not chosen:
            self.status_label.setText("Export cancelled; no file was written.")
            return False
        # 3. After file selection.
        if not alive():
            return False
        destination = Path(chosen)
        expected = (".pdf",) if kind == "PDF" else (".jpg", ".jpeg")
        if destination.suffix.lower() not in expected:
            destination = destination.with_suffix(expected[0])
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex[:8]}.part")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._render_to(kind, model, logo, temporary)
            # 4. Immediately before publishing.
            if not alive():
                raise _ExportCancelled
            os.replace(temporary, destination)
        except _ExportCancelled:
            self.status_label.setText("Access changed during export; no file was published.")
            return False
        except Exception as error:  # noqa: BLE001
            self.status_label.setText(f"Export failed ({type(error).__name__}); no file was published.")
            return False
        finally:
            QApplication.restoreOverrideCursor()
            try:
                temporary.unlink()
            except OSError:
                pass
        self.status_label.setText(
            f"Exported {destination.name} · snapshot {model.snapshot_id}"
        )
        # 5. The controller re-checks the predicate on completion.
        return True

    @staticmethod
    def _render_to(kind: str, model: PosterModel, logo: QImage, target: Path) -> None:
        if kind == "PDF":
            write_poster_pdf(model, logo, target)
            if not _pdf_matches_a3(target):
                raise ValueError("PDF is not one A3 landscape page")
            return
        width, height = A3_LANDSCAPE_PX
        image = render_poster_image(model, logo, width, height_px=height, dpi=EXPORT_DPI)
        if (image.width(), image.height()) != (width, height):
            raise ValueError("JPG has unexpected dimensions")
        if not image.save(str(target), "JPG", 95):
            raise OSError("JPG could not be written")
        check = QImage(str(target))
        if check.isNull() or (check.width(), check.height()) != (width, height):
            raise ValueError("JPG failed verification")


__all__ = [
    "A3_LANDSCAPE_PX",
    "CANVAS_H",
    "CANVAS_W",
    "NeonPosterWindow",
    "PosterAssetError",
    "PosterCanvas",
    "PosterModel",
    "build_poster_model",
    "inspect_pdf",
    "load_official_logo",
    "paint_poster",
    "render_poster_image",
    "write_poster_pdf",
]
