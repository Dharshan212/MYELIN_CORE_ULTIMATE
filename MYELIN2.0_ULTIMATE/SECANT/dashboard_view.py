"""Static SECANT landing page and SECANT / COSECANT Deep Analysis.

DUMMY_UI_ONLY / NOT_REAL_EVIDENCE / ASTRA_WIRING_PENDING.
The dashboard owns local Qt navigation state and renders literal fixture values.
It imports no read model, database, report engine, or physiology organ.
"""

from __future__ import annotations
import weakref

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QGraphicsBlurEffect, QGraphicsDropShadowEffect,
    QGraphicsPixmapItem, QGraphicsScene, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from SECANT import dashboard_demo as demo


CONTEXT_CAPTION_KEYS = frozenset(('about_architecture', 'about_dashboard_time', 'about_foundation_title', 'about_input_category', 'about_input_time', 'about_source', 'about_stage', 'about_stage_label', 'cosecant_events', 'cosecant_returns', 'distraction_attributes', 'episodes_flow', 'episodes_summary', 'evidence_attributes', 'evidence_summary', 'landing_events', 'landing_flow', 'overview_events', 'overview_flow', 'overview_insights', 'secant_archive_events', 'secant_archive_list', 'secant_archive_summary', 'source_banner', 'study_archive_events', 'study_archive_list', 'study_archive_summary'))


CYAN = "#04d9ec"
MUTED = "#a6c0d8"
TEXT = "#e6f2ff"
TONE = {
    "cyan": "#04d9ec", "teal": "#12d6c4", "green": "#03d8a4",
    "blue": "#5ba9ff", "amber": "#ffd747", "red": "#ff4d72",
    "purple": "#ae80ff", "yellow": "#f4e36d", "neutral": "#d8e5f0",
}

PANEL_STYLE = (
    "QFrame#analysisPanel{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
    "stop:0 rgba(21,48,73,230),stop:1 rgba(10,29,48,238));"
    "border:1px solid rgba(77,139,176,115);border-radius:14px;}"
)
TABLE_STYLE = (
    "QTableWidget{background:rgba(6,25,43,210);alternate-background-color:rgba(16,44,68,225);"
    "color:#e6f2ff;border:1px solid rgba(73,130,165,135);border-radius:7px;"
    "selection-background-color:#0b5269;selection-color:white;gridline-color:transparent;}"
    "QTableWidget::item{padding:4px 6px;border-bottom:1px solid rgba(112,161,190,35);}"
    "QHeaderView::section{background:#12374f;color:#adcae3;border:none;"
    "border-right:1px solid #31536a;border-bottom:1px solid #31536a;padding:5px 7px;}"
    "QScrollBar:vertical{background:#102d43;width:9px;}"
    "QScrollBar::handle:vertical{background:#2c6883;border-radius:4px;min-height:28px;}"
)


def _glass(frame: QFrame, object_name: str = "analysisPanel") -> None:
    """COSINE-style per-instance QSS survives the Control Station theme pass."""
    frame.setObjectName(object_name)
    frame.setFrameShape(QFrame.Shape.NoFrame)
    frame.setStyleSheet(PANEL_STYLE)


class SecantGlyph(QWidget):
    """A small waveform mark adapted from COSINE's presentation glyph."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(30, 30)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.moveTo(3, 21)
        path.cubicTo(9, 8, 13, 13, 16, 19)
        path.cubicTo(21, 28, 24, 7, 28, 9)
        gradient = QLinearGradient(0, 0, 30, 30)
        gradient.setColorAt(0, QColor("#14e0ee"))
        gradient.setColorAt(1, QColor("#5a9fff"))
        pen = QPen(gradient, 2.7)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(path)


class FlowConnector(QWidget):
    """Paint a real connector and elapsed label, following COSINE's map."""

    def __init__(self, caption: str, *, study_jump: bool = False) -> None:
        super().__init__()
        self.caption = caption
        self.setFixedSize(172 if study_jump else (62 if len(caption) < 12 else 80), 104)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mid = self.height() / 2 + 7
        right = self.width() - 7
        painter.setPen(QPen(QColor("#5da7eb"), 1.3))
        painter.drawLine(QPointF(5, mid), QPointF(right, mid))
        painter.drawLine(QPointF(right - 6, mid - 4), QPointF(right, mid))
        painter.drawLine(QPointF(right - 6, mid + 4), QPointF(right, mid))
        painter.setPen(QColor(MUTED))
        painter.setFont(_font(8, 400, mono=True))
        painter.drawText(QRectF(0, 15, self.width(), 30),
                         int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), self.caption)


def _font(size: int = 10, weight: int = 400, mono: bool = False) -> QFont:
    font = QFont("Consolas" if mono else "Segoe UI", size)
    font.setWeight(QFont.Weight(weight))
    return font


def _label(text: str, *, size: int = 10, weight: int = 400,
           color: str = TEXT, wrap: bool = False, mono: bool = False) -> QLabel:
    result = QLabel(text)
    result.setFont(_font(size, weight, mono))
    result.setStyleSheet(f"color:{color};background:transparent;border:none;")
    result.setWordWrap(wrap)
    return result


def _panel(title: str, subtitle: str = "") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    _glass(frame)
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(15, 10, 15, 10)
    layout.setSpacing(3)
    frame.title_label = _label(title, size=11, weight=700, color=CYAN)
    layout.addWidget(frame.title_label)
    if subtitle:
        frame.subtitle_label = _label(subtitle, size=9, color=MUTED, wrap=True)
        layout.addWidget(frame.subtitle_label)
    return frame, layout


def _row_container(*widgets: QWidget, weights: tuple[int, ...] | None = None) -> QWidget:
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, weights[index] if weights else 1)
    return host


def _kv_panel(title: str, rows: tuple[tuple[str, str], ...], subtitle: str = "") -> QFrame:
    frame, layout = _panel(title, subtitle)
    grid = QGridLayout()
    grid.setHorizontalSpacing(4)
    grid.setVerticalSpacing(0)
    cells = []
    for row, (key, value) in enumerate(rows):
        left = _label(key.upper(), size=9, color=MUTED)
        right = _label(value, size=9, color=TEXT, wrap=True)
        left.setObjectName("keyCell")
        right.setObjectName("valueCell")
        for cell in (left, right):
            cell.setMinimumHeight(19)
            cell.setContentsMargins(7, 2, 7, 2)
            cell.setStyleSheet(
                f"QLabel{{color:{MUTED if cell is left else TEXT};"
                "background:rgba(5,22,39,0.28);border:none;"
                "border-bottom:1px solid rgba(94,142,170,0.18);}"
            )
        grid.addWidget(left, row, 0)
        grid.addWidget(right, row, 1)
        cells.append((left, right))
    grid.setColumnStretch(0, 2)
    grid.setColumnStretch(1, 3)
    layout.addLayout(grid)
    layout.addStretch(1)
    frame.presentation_cells = tuple(cells)
    return frame


def _set_kv_items(frame: QFrame, rows: tuple[tuple[str, str], ...]) -> None:
    if len(rows) != len(frame.presentation_cells):
        raise ValueError("Key/value field count differs from the displayed panel")
    for (key_label, value_label), (key, value) in zip(frame.presentation_cells, rows):
        key_label.setText(key.upper())
        value_label.setText(value)


def _horizontal_strip(rows: tuple[tuple[str, str], ...], *, active: bool = False) -> QFrame:
    strip = QFrame()
    strip.setObjectName("activeBreakStrip" if active else "recentBreakStrip")
    strip.setFrameShape(QFrame.Shape.NoFrame)
    strip.setStyleSheet(
        "QFrame#activeBreakStrip{background:rgba(5,48,51,0.82);"
        "border:1px solid #02af86;border-radius:13px;}"
        if active else
        "QFrame#recentBreakStrip{background:rgba(28,45,78,0.78);"
        "border:1px solid #4267a6;border-radius:13px;}"
    )
    line = QHBoxLayout(strip)
    line.setContentsMargins(15, 10, 15, 10)
    line.setSpacing(10)
    cells = []
    for key, value in rows:
        field = QWidget()
        field_layout = QVBoxLayout(field)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(3)
        key_label = _label(key, size=8, weight=600, color=MUTED)
        value_label = _label(value, size=10, weight=700,
                             color=TONE["green"] if active and key in ("BREAK ACTIVE", "STATE") else TEXT,
                             wrap=True)
        field_layout.addWidget(key_label)
        field_layout.addWidget(value_label)
        cells.append((key_label, value_label))
        line.addWidget(field, 1)
    strip.presentation_cells = tuple(cells)
    strip.presentation_active = active
    return strip


def _set_strip_items(strip: QFrame, rows: tuple[tuple[str, str], ...]) -> None:
    if len(rows) != len(strip.presentation_cells):
        raise ValueError("Strip field count differs from the displayed strip")
    for (key_label, value_label), (key, value) in zip(strip.presentation_cells, rows):
        key_label.setText(key)
        value_label.setText(value)
        color = TONE["green"] if strip.presentation_active and key in ("BREAK ACTIVE", "STATE") else TEXT
        value_label.setStyleSheet(f"color:{color};background:transparent;border:none;")


class MetricCard(QFrame):
    def __init__(self, label: str, value: str, caption: str, tone: str = "cyan") -> None:
        super().__init__()
        self.setObjectName("metricCard")
        self.setProperty("tone", tone)
        accent = TONE[tone]
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            "QFrame#metricCard{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 rgba(18,45,68,235),stop:1 rgba(9,32,53,235));"
            f"border:1px solid {accent};border-radius:12px;}}"
        )
        self.setMinimumWidth(155)
        self.setMinimumHeight(78)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 7, 13, 7)
        layout.setSpacing(1)
        self.caption_label = _label(label, size=8, weight=600, color=MUTED, wrap=True)
        self.value_label = _label(value, size=19, weight=700, color=TONE[tone])
        self.supporting_label = _label(caption, size=8, color=MUTED, wrap=True)
        layout.addWidget(self.caption_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.supporting_label)

    def set_content(self, label: str, value: str, caption: str) -> None:
        self.caption_label.setText(label)
        self.value_label.setText(value)
        self.supporting_label.setText(caption)


def _metrics(values: tuple[tuple[str, str, str], ...]) -> QWidget:
    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(9)
    palette = ("cyan", "green", "purple", "teal", "blue", "blue")
    cards = []
    for index, item in enumerate(values):
        card = MetricCard(*item, tone=palette[index])
        layout.addWidget(card, 1)
        cards.append(card)
    host.metric_cards = tuple(cards)
    return host


def _set_metrics(host: QWidget, values: tuple[tuple[str, str, str], ...]) -> None:
    if len(values) != len(host.metric_cards):
        raise ValueError("Metric count differs from the displayed collection")
    for card, item in zip(host.metric_cards, values):
        card.set_content(*item)


class TablePanel(QFrame):
    """A fixed-height scrollable table; later wiring replaces rows via set_rows."""

    def __init__(self, title: str, subtitle: str, columns: tuple[str, ...],
                 rows: tuple[tuple[str, ...], ...], object_name: str,
                 *, max_visible_rows: int = 6) -> None:
        super().__init__()
        self.max_visible_rows = max_visible_rows
        _glass(self)
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        layout.addWidget(_label(title, size=11, weight=700, color=CYAN))
        self.subtitle_label = _label(subtitle, size=9, color=MUTED, wrap=True)
        layout.addWidget(self.subtitle_label)
        table = QTableWidget(0, len(columns), self)
        table.setObjectName(object_name)
        table.setStyleSheet(TABLE_STYLE)
        table.setFont(_font(9))
        table.setHorizontalHeaderLabels(columns)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        table.setWordWrap(True)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        if columns[0] == "#":
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
            table.setColumnWidth(0, 42)
        table.horizontalHeader().setMinimumSectionSize(42)
        table.setFixedHeight(200)
        layout.addWidget(table)
        self.table = table
        self.set_rows(rows)

    def set_rows(self, rows: tuple[tuple[str, ...], ...]) -> None:
        # ASTRA_WIRING_POINT: consume prepared display rows only.
        self.table.setRowCount(len(rows))
        self.table.setFixedHeight(max(200, min(len(rows), self.max_visible_rows) * 32 + 34))
        for row_index, row in enumerate(rows):
            self.table.setRowHeight(row_index, 32)
            for column_index, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if str(value) in ("Verified", "Matched", "Yes", "Return verified", "Confirmed"):
                    item.setForeground(QColor(TONE["green"]))
                elif str(value) in ("Uncertain", "Late", "Interrupted"):
                    item.setForeground(QColor(TONE["amber"]))
                elif str(value) in ("No", "Missed", "Not matched", "Not returned"):
                    item.setForeground(QColor(TONE["red"]))
                self.table.setItem(row_index, column_index, item)


class FlowPanel(QFrame):
    """Horizontally scrollable factual demonstration journey."""

    def __init__(self, title: str, subtitle: str,
                 nodes: tuple[tuple[str, str, str, str, str, str], ...],
                 *, large: bool = False, study_jump: bool = False,
                 semantic_color: bool = False) -> None:
        super().__init__()
        self.large = large
        self.study_jump = study_jump
        self.semantic_color = semantic_color
        _glass(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(5)
        layout.addWidget(_label(title, size=11, weight=700, color=CYAN))
        self.subtitle_label = _label(subtitle, size=9, color=MUTED, wrap=True)
        layout.addWidget(self.subtitle_label)
        scroll = QScrollArea()
        scroll.setObjectName("flowScroll")
        scroll.setStyleSheet(
            "QScrollArea#flowScroll{background:transparent;border:none;}"
            "QScrollBar:horizontal{background:#0d293e;height:8px;border-radius:4px;}"
            "QScrollBar::handle:horizontal{background:#31677f;border-radius:4px;min-width:35px;}"
        )
        scroll.setWidgetResizable(False)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedHeight(170 if large else 122)
        layout.addWidget(scroll)
        self.scroll = scroll
        self.set_nodes(nodes)

    def set_nodes(self, nodes: tuple[tuple[str, str, str, str, str, str], ...]) -> None:
        # ASTRA_WIRING_POINT: display-only sequence, no timing calculation.
        scroll_value = self.scroll.horizontalScrollBar().value()
        host = QWidget()
        host.setStyleSheet("QWidget{background:transparent;}")
        row = QHBoxLayout(host)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(3)
        self.node_labels = []
        for index, (category, title, detail, stamp, tone, gap) in enumerate(nodes):
            card = QFrame()
            card.setObjectName("flowNode")
            card.setProperty("tone", tone)
            accent = TONE[tone]
            fill = QColor(accent)
            card.setFrameShape(QFrame.Shape.NoFrame)
            card.setStyleSheet(
                "QFrame#flowNode{"
                f"background:rgba({fill.red()},{fill.green()},{fill.blue()},0.10);"
                f"border:1px solid {accent};border-radius:11px;}}"
            )
            if self.semantic_color:
                glow = QGraphicsDropShadowEffect(card)
                glow_color = QColor(accent)
                glow_color.setAlpha(60)
                glow.setColor(glow_color)
                glow.setBlurRadius(14)
                glow.setOffset(0, 0)
                card.setGraphicsEffect(glow)
            if self.large:
                card.setFixedSize(174, 148)
            else:
                card.setFixedSize(152, 102)
            vertical = QVBoxLayout(card)
            vertical.setContentsMargins(8, 7, 8, 7)
            vertical.setSpacing(1)
            cat = _label(category, size=8, weight=700, color=TONE[tone], wrap=True)
            cat.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name = _label(title, size=9, weight=600, wrap=True)
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            info = _label(detail, size=8, color=MUTED, wrap=True)
            info.setAlignment(Qt.AlignmentFlag.AlignCenter)
            time = _label(stamp, size=8, color=MUTED, mono=True)
            time.setAlignment(Qt.AlignmentFlag.AlignCenter)
            vertical.addWidget(cat)
            vertical.addWidget(name, 1)
            vertical.addWidget(info)
            vertical.addWidget(time)
            self.node_labels.append((cat, name, info, time))
            row.addWidget(card)
            if index < len(nodes) - 1:
                row.addWidget(FlowConnector(gap, study_jump=self.study_jump))
        host.adjustSize()
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        self.scroll.setWidget(host)
        self.scroll.horizontalScrollBar().setValue(scroll_value)


def _page() -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(13, 12, 13, 13)
    layout.setSpacing(9)
    return page, layout


class _PresentationContext:
    """Only explicitly bound source captions accept caller-prepared text."""

    def _init_context(self) -> None:
        self._context_text = {}
        self._context_labels = {}

    def _bind_context(self, key: str, label: QLabel) -> None:
        refs = self._context_labels.setdefault(key, [])
        refs[:] = [ref for ref in refs if ref() is not None]
        refs.append(weakref.ref(label))
        if key in self._context_text:
            label.setText(self._context_text[key])

    def _context_label(self, key: str, default: str, **style) -> QLabel:
        label = _label(default, **style)
        self._bind_context(key, label)
        return label

    def _apply_context(self, captions: dict[str, str]) -> None:
        self._context_text.update(captions)
        for key, refs in self._context_labels.items():
            if key not in captions:
                continue
            for ref in refs:
                label = ref()
                if label is not None:
                    try:
                        label.setText(captions[key])
                    except RuntimeError:
                        pass  # The previous archive detail was deleted by Qt.


class SecantDeepAnalysis(QWidget, _PresentationContext):
    """Existing glass analysis surface: two faces, seven static routes."""

    ROUTES = ("overview", "episodes", "distraction_history", "study_history",
              "evidence", "about", "cosecant")
    HISTORY_ROUTES = ("past_secant_episodes", "past_study_sessions")
    close_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    export_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_context()
        self._refresh_feedback = "Dummy layout — no live refresh"
        self.setObjectName("secantCosecantDashboard")
        self.face = "secant"
        self.route = "overview"
        self._pages: dict[str, QWidget] = {}
        self._nav: dict[str, QPushButton] = {}
        self._subnav: dict[str, QPushButton] = {}
        self._history_buttons: dict[str, QPushButton] = {}
        self._return_route = "overview"
        self._secant_archive = demo.DEMO_SECANT_EPISODE_ARCHIVE
        self._study_archive = demo.DEMO_STUDY_SESSION_ARCHIVE
        self._secant_filtered: tuple[dict, ...] = ()
        self._study_filtered: tuple[dict, ...] = ()
        self.selected_secant_episode_id: str | None = None
        self.selected_study_demo_key: str | None = None
        self._backdrop: QPixmap | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet(self._style())
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 26, 26, 26)
        root.setSpacing(0)

        surface = QFrame()
        surface.setObjectName("dashboardSurface")
        surface.setFrameShape(QFrame.Shape.NoFrame)
        surface.setMaximumHeight(900)
        surface.setStyleSheet(
            "QFrame#dashboardSurface{background:rgba(26,43,61,0.55);"
            "border:1px solid rgba(255,255,255,0.14);border-radius:20px;}"
        )
        shadow = QGraphicsDropShadowEffect(surface)
        shadow.setBlurRadius(80)
        shadow.setOffset(0, 30)
        shadow.setColor(QColor(0, 0, 0, 180))
        surface.setGraphicsEffect(shadow)
        self._surface = surface
        shell = QVBoxLayout(surface)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        root.addWidget(surface)
        shell.addWidget(self._header())
        self.nav_host = self._navigation()
        shell.addWidget(self.nav_host)
        self.subnav_host = self._subnavigation()
        shell.addWidget(self.subnav_host)

        self.body = QScrollArea()
        self.body.setObjectName("dashboardBody")
        self.body.setStyleSheet(
            "QScrollArea#dashboardBody{background:transparent;border:none;}"
            "QScrollArea#dashboardBody > QWidget > QWidget{background:transparent;}"
            "QScrollBar:vertical{background:rgba(255,255,255,0.03);width:9px;}"
            "QScrollBar::handle:vertical{background:#34647e;border-radius:4px;min-height:35px;}"
        )
        self.body.setWidgetResizable(True)
        self.body.setFrameShape(QFrame.Shape.NoFrame)
        shell.addWidget(self.body, 1)
        self.stack = QStackedWidget()
        self.stack.setObjectName("dashboardStack")
        self.body.setWidget(self.stack)
        self._build_pages()
        self.set_overview_data(metrics=demo.OVERVIEW_METRICS, recent_episode=demo.RECENT_EPISODE,
                               study_snapshot=demo.STUDY_SNAPSHOT, latest_events=demo.LATEST_SECANT_EVENTS,
                               insights=demo.OVERVIEW_INSIGHTS, journey=demo.SECANT_FLOW)
        self.set_episodes_data(metrics=demo.DISTRACTION_METRICS, rows=demo.EPISODES,
                               recent_episode=demo.RECENT_EPISODE, flow=demo.SECANT_FLOW)
        self.set_distraction_history_data(metrics=demo.DISTRACTION_METRICS, rows=demo.DISTRACTION_HISTORY,
                                          attributes=demo.DISTRACTION_ATTRIBUTES, flow=demo.SECANT_FLOW)
        self.set_study_history_data(metrics=demo.STUDY_METRICS, rows=demo.STUDY_HISTORY,
                                    jump_nodes=demo.STUDY_FLOW)
        self.set_study_evidence_data(metrics=demo.STUDY_METRICS, rows=demo.STUDY_EVIDENCE,
                                     attributes=demo.EVIDENCE_ATTRIBUTES, confirmation_nodes=demo.CONFIRMATION_FLOW)
        self.set_cosecant_data(main_summary=demo.COSECANT_BREAK, recent_break=demo.RECENT_BREAK,
                               metrics=demo.COSECANT_METRICS, break_history=demo.BREAK_HISTORY,
                               events=demo.COSECANT_EVENTS, return_history=demo.RETURN_HISTORY,
                               flow=demo.COSECANT_FLOW)
        footer = QFrame()
        footer.setObjectName("dashboardFooter")
        footer.setFrameShape(QFrame.Shape.NoFrame)
        footer.setStyleSheet(
            "QFrame#dashboardFooter{background:rgba(255,255,255,0.025);"
            "border:none;border-top:1px solid rgba(145,195,220,0.15);"
            "border-bottom-left-radius:18px;border-bottom-right-radius:18px;}"
        )
        foot = QHBoxLayout(footer)
        foot.setContentsMargins(16, 7, 16, 7)
        self.footer_left = _label("SECANT · Overview Analysis", size=8, color=MUTED, mono=True)
        foot.addWidget(self.footer_left)
        foot.addStretch(1)
        foot.addWidget(self._context_label("source_banner", "DEMO VALUES · NOT REAL EVIDENCE", size=8, color=CYAN, mono=True))
        shell.addWidget(footer)
        self.select_route("overview")

    def _retheme(self, _theme) -> None:
        """Reassert page-local glass QSS after Control Station's theme pass.

        The host replaces every page's stylesheet with global QSS. COSINE's
        presentation descendants survive by owning per-instance QSS; this
        dashboard follows that pattern and also restores its root background.
        """
        self.setStyleSheet(self._style())

    def open_overlay(self) -> None:
        """Show the landing face through a blurred, dimmed glass backdrop."""
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(parent.rect())
        self._backdrop = self._grab_blurred(parent.grab())
        self.show()
        self.raise_()
        self.setFocus()

    def close_overlay(self) -> None:
        self.hide()
        self._backdrop = None

    @staticmethod
    def _grab_blurred(source: QPixmap) -> QPixmap | None:
        if source.isNull():
            return None
        scene = QGraphicsScene()
        item = QGraphicsPixmapItem(source)
        blur = QGraphicsBlurEffect()
        blur.setBlurRadius(14)
        item.setGraphicsEffect(blur)
        scene.addItem(item)
        output = QPixmap(source.size())
        output.fill(Qt.GlobalColor.transparent)
        painter = QPainter(output)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        scene.render(painter)
        painter.end()
        return output

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        if self._backdrop is not None:
            painter.drawPixmap(self.rect(), self._backdrop)
        painter.fillRect(self.rect(), QColor(4, 8, 16, 140))
        painter.end()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close_requested.emit()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self._surface.geometry().contains(event.pos()):
            self.close_requested.emit()
            return
        super().mousePressEvent(event)

    def _header(self) -> QWidget:
        host = QFrame()
        host.setObjectName("dashboardHeader")
        host.setFrameShape(QFrame.Shape.NoFrame)
        host.setStyleSheet(
            "QFrame#dashboardHeader{background:rgba(255,255,255,0.035);"
            "border:none;border-bottom:1px solid rgba(145,195,220,0.18);"
            "border-top-left-radius:18px;border-top-right-radius:18px;}"
        )
        row = QHBoxLayout(host)
        row.setContentsMargins(20, 9, 20, 9)
        row.setSpacing(12)
        row.addWidget(SecantGlyph())
        title_box = QWidget()
        title_lay = QVBoxLayout(title_box)
        title_lay.setContentsMargins(0, 0, 0, 0)
        title_lay.setSpacing(1)
        title_lay.addWidget(_label("SECANT — DEEP ANALYSIS", size=11, weight=700))
        title_lay.addWidget(_label("Study Escape and Cognitive Attention Navigation Tracker", size=9, color=MUTED))
        row.addWidget(title_box, 1)
        face_host = QFrame()
        face_host.setObjectName("dashboardFaceSwitch")
        face_host.setStyleSheet(
            "QFrame#dashboardFaceSwitch{background:rgba(4,17,31,0.48);"
            "border:1px solid rgba(98,151,184,0.40);border-radius:8px;}"
        )
        face_row = QHBoxLayout(face_host)
        face_row.setContentsMargins(2, 2, 2, 2)
        face_row.setSpacing(0)
        for face in ("secant", "cosecant"):
            button = self._button(face.upper(), face)
            button.setObjectName(f"face_{face}")
            button.setMinimumWidth(105)
            button.clicked.connect(lambda _checked=False, name=face: self.select_face(name))
            face_row.addWidget(button)
            self._nav[face] = button
        row.addWidget(face_host)
        row.addStretch(1)
        refresh = self._button("REFRESH", "action")
        refresh.setObjectName("dashboardRefresh")
        refresh.clicked.connect(self._on_refresh_clicked)
        row.addWidget(refresh)
        export_box = QWidget()
        export_lay = QVBoxLayout(export_box)
        export_lay.setContentsMargins(0, 0, 0, 0)
        export_lay.setSpacing(0)
        export = self._button("EXPORT PDF", "export")
        export.setObjectName("dashboardExportPdf")
        export.clicked.connect(self._request_pdf_export)
        self._export_button = export
        export_lay.addWidget(export)
        export_lay.addWidget(_label("Study + SECANT + COSECANT · one session", size=7, color=MUTED))
        row.addWidget(export_box)
        # Close the glass analysis overlay back to the SECANT landing face.
        close = self._button("×", "action")
        close.setObjectName("dashboardClose")
        close.setFixedWidth(32)
        close.setStyleSheet(
            "QPushButton#dashboardClose{background:rgba(255,255,255,0.03);"
            "border:1px solid rgba(145,195,220,0.35);border-radius:16px;color:#c7d9e9;}"
            "QPushButton#dashboardClose:hover{border-color:#04d9ec;color:white;}"
        )
        close.setToolTip("Return to SECANT Dashboard")
        close.clicked.connect(self.close_requested.emit)
        row.addWidget(close)
        self.feedback = _label("", size=8, color=CYAN)
        self.feedback.setObjectName("dashboardFeedback")
        return host

    @staticmethod
    def _button(text: str, role: str) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("role", role)
        button.setCheckable(role not in ("action", "export", "history_action"))
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFont(_font(9, 700))
        button.setMinimumHeight(31)
        if role in ("secant", "cosecant"):
            button.setStyleSheet(
                "QPushButton{color:#a7c6dc;background:transparent;border:1px solid transparent;"
                "border-radius:6px;padding:5px 15px;}"
                "QPushButton:checked{color:#02e5eb;background:rgba(3,193,212,0.15);"
                "border-color:#05c9da;}"
                "QPushButton:hover{color:white;background:rgba(63,149,185,0.12);}"
            )
        elif role in ("nav", "subnav"):
            button.setStyleSheet(
                "QPushButton{color:#b6cbe0;background:transparent;border:1px solid transparent;"
                "border-radius:7px;padding:7px 15px;}"
                "QPushButton:checked{color:#04d9ec;background:rgba(3,193,212,0.12);"
                "border-color:rgba(4,217,236,0.60);}"
                "QPushButton:hover{color:white;background:rgba(255,255,255,0.05);}"
            )
        elif role in ("history", "history_action"):
            button.setStyleSheet(
                "QPushButton{color:#25dce8;background:rgba(4,217,236,0.025);"
                "border:1px solid rgba(4,217,236,0.56);border-radius:8px;padding:6px 13px;}"
                "QPushButton:checked{color:white;background:rgba(4,217,236,0.17);"
                "border-color:#04d9ec;}"
                "QPushButton:hover{color:white;background:rgba(4,217,236,0.12);}"
                "QPushButton:disabled{color:#668a99;border-color:#355265;background:rgba(4,217,236,0.01);}"
            )
        elif role == "export":
            button.setStyleSheet(
                "QPushButton{color:#ffd747;background:rgba(255,215,71,0.06);"
                "border:1px solid #b9962e;border-radius:7px;padding:6px 13px;}"
                "QPushButton:hover{background:rgba(255,215,71,0.14);border-color:#ffd747;}"
            )
        else:
            button.setStyleSheet(
                "QPushButton{color:#bad1e5;background:rgba(255,255,255,0.025);"
                "border:1px solid rgba(120,163,193,0.32);border-radius:7px;padding:6px 13px;}"
                "QPushButton:hover{color:white;border-color:#04d9ec;}"
            )
        return button

    def _navigation(self) -> QWidget:
        host = QFrame()
        host.setObjectName("dashboardNav")
        host.setFrameShape(QFrame.Shape.NoFrame)
        host.setStyleSheet(
            "QFrame#dashboardNav{background:rgba(255,255,255,0.02);"
            "border:none;border-bottom:1px solid rgba(145,195,220,0.14);}"
        )
        row = QHBoxLayout(host)
        row.setContentsMargins(16, 5, 16, 5)
        row.setSpacing(6)
        for group, text in (("overview", "OVERVIEW"), ("distraction", "DISTRACTION"),
                            ("study", "STUDY"), ("about", "ABOUT")):
            button = self._button(text, "nav")
            button.setMinimumWidth(115)
            button.setObjectName(f"nav_{group}")
            button.clicked.connect(lambda _checked=False, key=group: self.select_group(key))
            row.addWidget(button)
            self._nav[group] = button
        row.addStretch(1)
        return host

    def _subnavigation(self) -> QWidget:
        host = QFrame()
        host.setObjectName("dashboardSubnav")
        host.setFrameShape(QFrame.Shape.NoFrame)
        host.setStyleSheet(
            "QFrame#dashboardSubnav{background:rgba(3,29,47,0.68);"
            "border:none;border-bottom:1px solid rgba(145,195,220,0.12);}"
        )
        row = QHBoxLayout(host)
        row.setContentsMargins(16, 4, 16, 4)
        row.setSpacing(7)
        self.section_hint = _label("", size=8, color=MUTED)
        row.addWidget(self.section_hint)
        for key, title in (("episodes", "EPISODES"), ("distraction_history", "DISTRACTION HISTORY"),
                           ("study_history", "STUDY HISTORY"), ("evidence", "EVIDENCE")):
            button = self._button(title, "subnav")
            button.setObjectName(f"subnav_{key}")
            button.clicked.connect(lambda _checked=False, route=key: self.select_route(route))
            row.addWidget(button)
            self._subnav[key] = button
        row.addStretch(1)
        for route, title in (("past_secant_episodes", "PAST SECANT EPISODES"),
                             ("past_study_sessions", "PAST STUDY SESSIONS")):
            button = self._button(title, "history")
            icon = QPixmap(16, 16)
            icon.fill(Qt.GlobalColor.transparent)
            painter = QPainter(icon)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(QColor(CYAN), 1.5))
            painter.drawEllipse(2, 2, 12, 12)
            painter.drawLine(8, 8, 8, 4)
            painter.drawLine(8, 8, 11, 9)
            painter.end()
            button.setIcon(QIcon(icon))
            button.setObjectName(f"history_{route}")
            button.clicked.connect(lambda _checked=False, key=route: self.open_history(key))
            row.addWidget(button)
            self._history_buttons[route] = button
        return host

    def _build_pages(self) -> None:
        builders = {
            "overview": self._overview, "episodes": self._episodes,
            "distraction_history": self._distraction_history,
            "study_history": self._study_history, "evidence": self._evidence,
            "about": self._about, "cosecant": self._cosecant,
            "past_secant_episodes": self._past_secant_episodes,
            "past_study_sessions": self._past_study_sessions,
        }
        for key, builder in builders.items():
            page = builder()
            page.setObjectName(f"dashboardPage_{key}")
            page.setStyleSheet(f"QWidget#dashboardPage_{key}{{background:transparent;}}")
            self.stack.addWidget(page)
            self._pages[key] = page

    def select_group(self, group: str) -> None:
        self.select_route({"overview": "overview", "distraction": "episodes",
                           "study": "study_history", "about": "about"}[group])

    def select_face(self, face: str) -> None:
        if face == "cosecant":
            self.select_route("cosecant")
        elif face == "secant":
            self.select_route("overview")

    def select_route(self, route: str) -> None:
        if route not in self._pages:
            raise ValueError(f"Unknown dashboard route: {route}")
        self.route = route
        self.face = "cosecant" if route == "cosecant" else "secant"
        self.stack.setCurrentWidget(self._pages[route])
        self.body.verticalScrollBar().setValue(0)
        self.nav_host.setVisible(self.face == "secant")
        group = ("distraction" if route in ("episodes", "distraction_history", "past_secant_episodes") else
                 "study" if route in ("study_history", "evidence", "past_study_sessions") else route)
        self.subnav_host.setVisible(group in ("distraction", "study"))
        for name, button in self._nav.items():
            button.setChecked(name == (self.face if name in ("secant", "cosecant") else group))
        for name, button in self._subnav.items():
            button.setVisible((group == "distraction" and name in ("episodes", "distraction_history"))
                              or (group == "study" and name in ("study_history", "evidence")))
            button.setChecked(name == route)
        for name, button in self._history_buttons.items():
            button.setVisible((group == "distraction" and name == "past_secant_episodes")
                              or (group == "study" and name == "past_study_sessions"))
            button.setChecked(name == route)
        self.section_hint.setText("DISTRACTION contains:" if group == "distraction" else "STUDY contains:")
        self.footer_left.setText(f"{self.face.upper()} · {route.replace('_', ' ').title()} Analysis")

    def open_history(self, route: str) -> None:
        if route not in self.HISTORY_ROUTES:
            raise ValueError(f"Unknown history route: {route}")
        if self.route not in self.HISTORY_ROUTES:
            self._return_route = self.route
        self.select_route(route)
        picker = (self._secant_date_picker if route == "past_secant_episodes"
                  else self._study_date_picker)
        picker.setCurrentIndex(0)

    def back_from_history(self) -> None:
        self.select_route(self._return_route)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.select_route("overview")

    def _feedback(self, message: str) -> None:
        self.feedback.setText(message)
        self.footer_left.setText(message)

    def _request_pdf_export(self) -> None:
        selection = {}
        if self.route == 'past_secant_episodes':
            row = next((r for r in self._secant_filtered if r['episode_id'] == self.selected_secant_episode_id), None)
            if not row or not row.get('scope_identity'):
                self._feedback('Select a recorded SECANT episode before exporting its parent session.')
                return
            selection['secant_identity'] = tuple(row['scope_identity'])
        elif self.route == 'past_study_sessions':
            row = next((r for r in self._study_filtered if r['demo_key'] == self.selected_study_demo_key), None)
            if not row or not row.get('scope_identity'):
                self._feedback('Select a recorded Study block before exporting its parent session.')
                return
            selection['study_identity'] = tuple(row['scope_identity'])
        self.export_requested.emit(selection)

    def _on_refresh_clicked(self) -> None:
        if self._refresh_feedback:
            self._feedback(self._refresh_feedback)
        self.refresh_requested.emit()

    def _overview(self) -> QWidget:
        page, layout = _page()
        self.overview_metrics = _metrics(tuple(("", "", "") for _ in demo.OVERVIEW_METRICS))
        layout.addWidget(self.overview_metrics)
        self.overview_recent = _kv_panel("RECENT SECANT EPISODE", tuple(("", "") for _ in demo.RECENT_EPISODE),
                                         "Most recent distraction episode and outcome.")
        self.overview_study = _kv_panel("RECENT STUDY SNAPSHOT", tuple(("", "") for _ in demo.STUDY_SNAPSHOT),
                                        "Current study context and resource evidence.")
        layout.addWidget(_row_container(
            self.overview_recent, self.overview_study))
        self.overview_insights = _kv_panel("OVERVIEW INSIGHTS", tuple(("", "") for _ in demo.OVERVIEW_INSIGHTS),
                             "Factual notes from the static demonstration history.")
        events = TablePanel("LATEST EVENTS", "Most recent system events in the demo timeline.",
                            ("#", "TIME", "EVENT", "SOURCE", "TYPE"), (),
                            "overviewEventsTable")
        self.overview_events = events
        self._bind_context("overview_events", events.subtitle_label)
        self._bind_context("overview_insights", self.overview_insights.subtitle_label)
        layout.addWidget(_row_container(events, self.overview_insights, weights=(3, 2)))
        self.overview_flow = FlowPanel("RECENT SECANT JOURNEY", "Episode flow from distraction to recorded closure; times are demo values.", (), semantic_color=True)
        layout.addWidget(self.overview_flow)
        self._bind_context("overview_flow", self.overview_flow.subtitle_label)
        layout.addStretch(1)
        return page

    def _episodes(self) -> QWidget:
        page, layout = _page()
        self.episodes_metrics = _metrics(tuple(("", "", "") for _ in demo.DISTRACTION_METRICS))
        layout.addWidget(self.episodes_metrics)
        table = TablePanel("EPISODE LIST", "Recent distraction episodes captured by SECANT.",
                           ("#", "EPISODE ID", "SOURCE", "STAGE REACHED", "OUTCOME", "RECORDED AT"),
                           (), "episodeListTable")
        self.episode_table = table
        self.episodes_recent = _kv_panel("RECENT EPISODE", tuple(("", "") for _ in demo.RECENT_EPISODE),
                                         "Static demonstration summary.")
        layout.addWidget(_row_container(table, self.episodes_recent, weights=(3, 2)))
        self.episodes_flow = FlowPanel("RECENT DISTRACTION EPISODE FLOW", "Recorded actions and display stages; demo elapsed times.", (), semantic_color=True)
        layout.addWidget(self.episodes_flow)
        self._bind_context("episodes_summary", self.episodes_recent.subtitle_label)
        self._bind_context("episodes_flow", self.episodes_flow.subtitle_label)
        layout.addStretch(1)
        return page

    def _distraction_history(self) -> QWidget:
        page, layout = _page()
        self.distraction_metrics = _metrics(tuple(("", "", "") for _ in demo.DISTRACTION_METRICS))
        layout.addWidget(self.distraction_metrics)
        history = TablePanel("DISTRACTION HISTORY", "Factual history of distraction episodes and return outcomes.",
                             ("#", "SOURCE", "STARTED", "STAGE", "RETURN INTENT", "VERIFIED", "CLOSURE"),
                             (), "distractionHistoryTable")
        self.distraction_rows = history
        self.distraction_attributes = _kv_panel("DISTRACTION ATTRIBUTES", tuple(("", "") for _ in demo.DISTRACTION_ATTRIBUTES),
                                                 "Recent episode facts from the static demonstration.")
        layout.addWidget(_row_container(
            history, self.distraction_attributes, weights=(3, 2)))
        layout.addWidget(_label("No brain-state claims. Behaviour and software evidence only.", size=9, color=CYAN))
        self.distraction_flow = FlowPanel("DISTRACTION RETURN FLOW", "Intent, interruption, verification, and closure in recorded order.", (), semantic_color=True)
        layout.addWidget(self.distraction_flow)
        self._bind_context("distraction_attributes", self.distraction_attributes.subtitle_label)
        layout.addStretch(1)
        return page

    def _study_history(self) -> QWidget:
        page, layout = _page()
        self.study_history_metrics = _metrics(tuple(("", "", "") for _ in demo.STUDY_METRICS))
        layout.addWidget(self.study_history_metrics)
        history = TablePanel("STUDY HISTORY", "Only study-aligned resources are shown. Distraction videos are excluded.",
                             ("#", "RESOURCE", "SUPPORTED FOREGROUND\nDURATION", "FIRST OBSERVED", "LAST OBSERVED", "QUALIFICATION"),
                             (), "studyHistoryTable")
        history.table.horizontalHeader().setFixedHeight(41)
        self.study_history_rows = history
        layout.addWidget(history)
        self.study_history_flow = FlowPanel("STUDY JUMP EFFECT", "Study-resource movement with interruptions and evidence gaps preserved.", (), study_jump=True)
        layout.addWidget(self.study_history_flow)
        layout.addStretch(1)
        return page

    def _evidence(self) -> QWidget:
        page, layout = _page()
        self.study_evidence_metrics = _metrics(tuple(("", "", "") for _ in demo.STUDY_METRICS))
        layout.addWidget(self.study_evidence_metrics)
        evidence = TablePanel("EVIDENCE SUMMARY", "Confidence refers to the classification shown; values are static examples.",
                              ("#", "RESOURCE", "CLASSIFICATION", "CONFIDENCE", "USER CONFIRMATION", "QUALIFICATION"),
                              (), "studyEvidenceTable")
        for index, width in enumerate((42, 120, 183, 134, 219, 171)):
            evidence.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
            evidence.table.setColumnWidth(index, width)
        self.study_evidence_rows = evidence
        self._bind_context("evidence_summary", evidence.subtitle_label)
        self.study_evidence_attributes = _kv_panel("EVIDENCE ATTRIBUTES", tuple(("", "") for _ in demo.EVIDENCE_ATTRIBUTES),
                                                    "DBMS Lecture Slides: initial uncertainty and later confirmation.")
        layout.addWidget(_row_container(evidence, self.study_evidence_attributes, weights=(3, 2)))
        self._bind_context("evidence_attributes", self.study_evidence_attributes.subtitle_label)
        layout.addWidget(_label("No brain-state claims. Behaviour and software evidence only.", size=9, color=CYAN))
        self.study_evidence_flow = FlowPanel("CONFIRMATION FLOW", "Uncertain resources enter the study chain only after recorded confirmation.", ())
        layout.addWidget(self.study_evidence_flow)
        layout.addStretch(1)
        return page

    def set_overview_data(self, *, metrics: tuple, recent_episode: tuple,
                          study_snapshot: tuple, latest_events: tuple,
                          insights: tuple, journey: tuple) -> None:
        """Display prepared Overview metrics, fields, event rows, and flow nodes."""
        _set_metrics(self.overview_metrics, metrics)
        _set_kv_items(self.overview_recent, recent_episode)
        _set_kv_items(self.overview_study, study_snapshot)
        self.overview_events.set_rows(latest_events)
        _set_kv_items(self.overview_insights, insights)
        self.overview_flow.set_nodes(journey)

    def set_episodes_data(self, *, metrics: tuple, rows: tuple,
                          recent_episode: tuple, flow: tuple) -> None:
        """Replace the ordinary Episodes presentation without linking row selection."""
        _set_metrics(self.episodes_metrics, metrics)
        self.episode_table.set_rows(rows)
        _set_kv_items(self.episodes_recent, recent_episode)
        self.episodes_flow.set_nodes(flow)

    def set_distraction_history_data(self, *, metrics: tuple, rows: tuple,
                                     attributes: tuple, flow: tuple) -> None:
        """Display prepared distraction history fields and flow nodes."""
        _set_metrics(self.distraction_metrics, metrics)
        self.distraction_rows.set_rows(rows)
        _set_kv_items(self.distraction_attributes, attributes)
        self.distraction_flow.set_nodes(flow)

    def set_study_history_data(self, *, metrics: tuple, rows: tuple,
                               jump_nodes: tuple) -> None:
        """Display prepared Study History rows and curated jump connectors."""
        _set_metrics(self.study_history_metrics, metrics)
        self.study_history_rows.set_rows(rows)
        self.study_history_flow.set_nodes(jump_nodes)

    def set_study_evidence_data(self, *, metrics: tuple, rows: tuple,
                                attributes: tuple, confirmation_nodes: tuple) -> None:
        """Display prepared classification evidence without interpretation."""
        _set_metrics(self.study_evidence_metrics, metrics)
        self.study_evidence_rows.set_rows(rows)
        _set_kv_items(self.study_evidence_attributes, attributes)
        self.study_evidence_flow.set_nodes(confirmation_nodes)

    def set_cosecant_data(self, *, main_summary: tuple, recent_break: tuple,
                          metrics: tuple, break_history: tuple,
                          events: tuple, return_history: tuple, flow: tuple) -> None:
        """Display prepared COSECANT break and return facts."""
        _set_strip_items(self.cosecant_main, main_summary)
        _set_strip_items(self.cosecant_recent, recent_break)
        _set_metrics(self.cosecant_metrics, metrics)
        _set_kv_items(self.cosecant_break_history, break_history)
        self.cosecant_events.set_rows(events)
        self.cosecant_returns.set_rows(return_history)
        self.cosecant_flow.set_nodes(flow)

    def _about(self) -> QWidget:
        page, layout = _page()
        info = (
            ("DASHBOARD TYPE", "Reader / Presentation", "View recorded evidence"),
            ("FACES", "SECANT + COSECANT", "Two analysis views in one dashboard"),
            ("EVIDENCE SCOPE", "Behavioural only", "User activity and software events"),
            ("EXPORT", "Study Recovery Report", "One finalized parent session; Study + SECANT + COSECANT"),
        )
        layout.addWidget(_metrics(info))
        purpose = (
            ("Purpose", "Explore distraction, recovery, and study-navigation evidence."),
            ("Authority", "Reader and presentation interface only."),
            ("Background", "Does not control physiology or influence background systems."),
            ("Demo stage", "All values on this screen are static demonstration content."),
        )
        structure = (
            ("OVERVIEW", "Common summary and key metrics"),
            ("DISTRACTION", "Episodes and Distraction History"),
            ("STUDY", "Study History and Evidence"),
            ("ABOUT", "Dashboard scope, data, structure, and rules"),
        )
        purpose_panel = _kv_panel("PURPOSE", purpose)
        self._bind_context("about_stage_label", purpose_panel.presentation_cells[3][0])
        self._bind_context("about_stage", purpose_panel.presentation_cells[3][1])
        layout.addWidget(_row_container(purpose_panel,
                                         _kv_panel("DASHBOARD STRUCTURE", structure)))
        foundation = (
            ("secant_events", "Episode, recovery, and outcome evidence"),
            ("study_resource_events", "Study resource interaction evidence"),
            ("study_resources", "Qualified resource evidence"),
            ("study_events", "Study session and transition evidence"),
            ("cosecant_events", "COSECANT break evidence"),
        )
        boundary = (
            ("Shows", "Observed behaviour, software events, durations, classifications, confirmations"),
            ("Does not claim", "Brain activity, dopamine, mental state, motivation, or neurological condition"),
            ("Current source", "Static Python demonstration fixture only"),
        )
        foundation_panel = _kv_panel("DATA FOUNDATION · FUTURE LABELS ONLY", foundation)
        boundary_panel = _kv_panel("SCIENTIFIC BOUNDARY", boundary)
        self._bind_context("about_foundation_title", foundation_panel.title_label)
        self._bind_context("about_source", boundary_panel.presentation_cells[2][1])
        layout.addWidget(_row_container(foundation_panel, boundary_panel))
        architecture = FlowPanel("READER ARCHITECTURE",
                                    "Future data direction. No database connection exists in this dummy build.",
                                    (("FUTURE INPUT", "Durable projection", "Recorded evidence", "Not connected", "teal", "→"),
                                     ("DASHBOARD", "SECANT + COSECANT", "Read and analyse", "Static demo", "blue", "→"),
                                     ("OUTPUT", "Presentation only", "Visual exploration", "No authority", "purple", "")))
        self._bind_context("about_architecture", architecture.subtitle_label)
        self._bind_context("about_input_category", architecture.node_labels[0][0])
        self._bind_context("about_input_time", architecture.node_labels[0][3])
        self._bind_context("about_dashboard_time", architecture.node_labels[1][3])
        layout.addWidget(architecture)
        layout.addWidget(_label("This dashboard does not control timers, Monitor, Resource Intent, Study, SINE, MIRL, MINE, COSINE, SECANT, or COSECANT.",
                                 size=9, color="#ffd747", wrap=True))
        layout.addStretch(1)
        return page

    def _cosecant(self) -> QWidget:
        page, layout = _page()
        self.cosecant_main = _horizontal_strip(tuple(("", "") for _ in demo.COSECANT_BREAK), active=True)
        self.cosecant_recent = _horizontal_strip(tuple(("", "") for _ in demo.RECENT_BREAK))
        self.cosecant_metrics = _metrics(tuple(("", "", "") for _ in demo.COSECANT_METRICS))
        layout.addWidget(self.cosecant_main)
        layout.addWidget(self.cosecant_recent)
        layout.addWidget(self.cosecant_metrics)
        events = TablePanel("LATEST EVENTS", "Last five recorded-style events for the recent break.",
                            ("EVENT", "TYPE", "TIME"), (), "cosecantEventsTable")
        for index, width in enumerate((384, 144, 108)):
            events.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
            events.table.setColumnWidth(index, width)
        events.table.setStyleSheet(TABLE_STYLE + "QScrollBar:horizontal{height:11px;}")
        returns = TablePanel("RETURN HISTORY", "Intended targets; Unavailable marks a demo read failure.",
                             ("INTENDED TARGET", "RETURN CONFIRMED AT", "CONFIRMATION", "OUTCOME"),
                             (), "cosecantReturnTable")
        for index, width in enumerate((360, 242, 158, 192)):
            returns.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeMode.Fixed)
            returns.table.setColumnWidth(index, width)
        returns.table.setStyleSheet(TABLE_STYLE + "QScrollBar:horizontal{height:11px;}")
        self.cosecant_break_history = _kv_panel("BREAK HISTORY", tuple(("", "") for _ in demo.BREAK_HISTORY))
        self.cosecant_events = events
        self._bind_context("cosecant_events", events.subtitle_label)
        self._bind_context("cosecant_returns", returns.subtitle_label)
        self.cosecant_returns = returns
        layout.addWidget(_row_container(self.cosecant_break_history, events, returns,
                                         weights=(1, 1, 1)))
        self.cosecant_flow = FlowPanel("RECENT COSECANT EPISODE FLOW", "Recorded allowance and return facts; reminder is a state, not a display receipt.", (), semantic_color=True)
        layout.addWidget(self.cosecant_flow)
        layout.addStretch(1)
        return page

    @staticmethod
    def _history_date_picker(object_name: str) -> QComboBox:
        picker = QComboBox()
        picker.setObjectName(object_name)
        picker.setFont(_font(9, 700))
        picker.setMinimumWidth(155)
        picker.setFixedHeight(31)
        picker.setCursor(Qt.CursorShape.PointingHandCursor)
        picker.setStyleSheet(
            "QComboBox{color:#25dce8;background:#0a2638;"
            "border:1px solid rgba(4,217,236,0.56);border-radius:8px;padding:4px 10px;}"
            "QComboBox:hover{border-color:#04d9ec;background:#10364b;}"
            "QComboBox::drop-down{border:none;width:19px;}"
            "QComboBox QAbstractItemView{color:#e6f2ff;background:#0d2639;"
            "selection-background-color:#0b5269;border:1px solid #34647e;}"
        )
        return picker

    def _history_header(self, title: str, subtitle: str, back_name: str,
                        picker: QComboBox, view_button: QPushButton) -> QWidget:
        host = QWidget()
        host.setFixedHeight(58)
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        words = QVBoxLayout()
        words.setSpacing(3)
        words.addWidget(_label(title, size=16, weight=700, color=CYAN))
        words.addWidget(_label(subtitle, size=9, color=MUTED))
        row.addLayout(words)
        row.addStretch(1)
        row.addWidget(picker)
        row.addWidget(view_button)
        back = self._button("← BACK TO CURRENT VIEW", "history")
        back.setObjectName(back_name)
        back.clicked.connect(self.back_from_history)
        row.addWidget(back)
        return host

    @staticmethod
    def _clear_history_detail(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    @staticmethod
    def _history_prompt(layout: QVBoxLayout, title: str, message: str) -> None:
        SecantDeepAnalysis._clear_history_detail(layout)
        panel, _ = _panel(title, message)
        layout.addWidget(panel)

    def _show_history_flow(self) -> None:
        self.stack.adjustSize()
        self.body.verticalScrollBar().setValue(self.body.verticalScrollBar().maximum())

    def _capture_archive_state(self, kind: str) -> dict:
        """Capture only this browser's presentation state for a receiving update."""
        flow = getattr(self, f"historical_{kind}_flow", None)
        selected = (self.selected_secant_episode_id if kind == "secant"
                    else self.selected_study_demo_key)
        tables = [getattr(self, f"_{kind}_archive_panel").table]
        tables += getattr(self, f"_{kind}_detail_layout").parentWidget().findChildren(QTableWidget)
        return {
            "date": getattr(self, f"_{kind}_date_picker").currentData(),
            "selected": selected, "open": flow is not None,
            "flow_x": flow.scroll.horizontalScrollBar().value() if flow is not None else 0,
            "tables": {table.objectName(): (table.horizontalScrollBar().value(),
                                            table.verticalScrollBar().value()) for table in tables},
            "route": self.route, "face": self.face,
            "body_y": self.body.verticalScrollBar().value(),
        }

    def _restore_archive_state(self, kind: str, state: dict) -> None:
        """Rebuild from new records by internal key; never reuse old detail widgets."""
        archive = getattr(self, f"_{kind}_archive")
        token = getattr(self, f"_{kind}_restore_token")
        key = "episode_id" if kind == "secant" else "demo_key"
        selected = next((item for item in archive if item[key] == state["selected"]), None)
        date = state["date"]
        if selected is not None:
            date = (selected["started"].partition(" · ")[0] if kind == "secant" else selected["date"])
        picker = getattr(self, f"_{kind}_date_picker")
        index = picker.findData(date)
        if index > 0:
            picker.setCurrentIndex(index)
        if selected is not None:
            if kind == "secant":
                self.select_secant_episode(selected[key])
            else:
                self.select_study_session(selected[key])
            if state["open"]:
                self._restoring_archive_state = True
                try:
                    if kind == "secant":
                        self.view_secant_episode_flow()
                    else:
                        self.view_study_session_map()
                finally:
                    self._restoring_archive_state = False

        # Inactive archive updates must not move the shared page scroll either.
        self.body.verticalScrollBar().setValue(state["body_y"])

        def restore_scroll() -> None:
            if (getattr(self, f"_{kind}_restore_token") is not token
                    or self.route != state["route"] or self.face != state["face"]):
                return
            self.stack.adjustSize()
            self.body.verticalScrollBar().setValue(state["body_y"])
            tables = [getattr(self, f"_{kind}_archive_panel").table]
            tables += getattr(self, f"_{kind}_detail_layout").parentWidget().findChildren(QTableWidget)
            for table in tables:
                x, y = state["tables"].get(table.objectName(), (0, 0))
                table.horizontalScrollBar().setValue(x)
                table.verticalScrollBar().setValue(y)
            flow = getattr(self, f"historical_{kind}_flow", None)
            if flow is not None:
                flow.scroll.horizontalScrollBar().setValue(state["flow_x"])

        QTimer.singleShot(0, restore_scroll)

    def _past_secant_episodes(self) -> QWidget:
        page, layout = _page()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        picker = self._history_date_picker("secantHistoryDate")
        view_button = self._button("VIEW FLOW", "history_action")
        view_button.setObjectName("viewSecantHistoryFlow")
        view_button.setEnabled(False)
        self._secant_date_picker = picker
        self._secant_view_button = view_button
        layout.addWidget(self._history_header(
            "PAST SECANT EPISODES",
            "Select a date, choose an episode, then view its full flow.",
            "backFromSecantHistory",
            picker, view_button,
        ))
        archive = TablePanel(
            "HISTORICAL EPISODE LIST", "Choose a date above to show static demonstration episodes.",
            ("#", "EPISODE ID", "SOURCE", "STARTED", "STAGE", "OUTCOME"),
            (), "secantArchiveTable",
        )
        archive.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(archive)
        self._secant_archive_panel = archive
        self._bind_context("secant_archive_list", archive.subtitle_label)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(10)
        detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(detail)
        self._secant_detail_layout = detail_layout
        archive.table.itemSelectionChanged.connect(self._secant_archive_row_changed)
        picker.currentIndexChanged.connect(self._filter_secant_history)
        view_button.clicked.connect(self.view_secant_episode_flow)
        self.set_secant_episode_archive(self._secant_archive)
        return page

    def set_secant_episode_archive(self, archive: tuple[dict, ...], *,
                                   empty_state: tuple[str, str] | None = None,
                                   preserve_state: bool = False) -> None:
        """Presentation seam: replace static records with prepared display data later."""
        state = self._capture_archive_state("secant") if preserve_state else None
        self._secant_archive = archive
        self._secant_restore_token = object()
        self._secant_empty_state = empty_state
        picker = self._secant_date_picker
        picker.blockSignals(True)
        picker.clear()
        picker.addItem("SELECT DATE", None)
        for date in dict.fromkeys(item["started"].partition(" · ")[0] for item in archive):
            picker.addItem(date, date)
        picker.setCurrentIndex(0)
        picker.blockSignals(False)
        self._filter_secant_history()

        if state is not None:
            self._restore_archive_state("secant", state)

    def _filter_secant_history(self) -> None:
        # STATIC_DATE_FILTER_ONLY: presentation filtering of the literal archive.
        date = self._secant_date_picker.currentData()
        self._secant_filtered = tuple(
            item for item in self._secant_archive
            if date is not None and item["started"].partition(" · ")[0] == date
        )
        rows = tuple((str(index + 1), item["display_episode_id"], item.get("source") or "Not recorded",
                      item["started"], item["stage"], item["outcome"])
                     for index, item in enumerate(self._secant_filtered))
        table = self._secant_archive_panel.table
        table.blockSignals(True)
        self._secant_archive_panel.set_rows(rows)
        table.clearSelection()
        table.blockSignals(False)
        self.selected_secant_episode_id = None
        self._secant_view_button.setEnabled(False)
        self.historical_secant_events_table = None
        self.historical_secant_flow = None
        if (date is not None and not self._secant_filtered) or not self._secant_archive:
            prompt = (self._secant_empty_state if not self._secant_archive
                      and self._secant_empty_state is not None else
                      ("NO DATA", "No data for the selected SECANT episode view."))
            self._history_prompt(self._secant_detail_layout, *prompt)
        else:
            self._history_prompt(self._secant_detail_layout, "SELECT A HISTORICAL EPISODE",
                                 "Select a date and an episode above, then press VIEW FLOW.")
        self.body.verticalScrollBar().setValue(0)
        if self.route == "past_secant_episodes":
            QTimer.singleShot(0, self.stack.adjustSize)

    def _secant_archive_row_changed(self) -> None:
        row = self._secant_archive_panel.table.currentRow()
        if 0 <= row < len(self._secant_filtered):
            self.select_secant_episode(self._secant_filtered[row]["episode_id"])

    def select_secant_episode(self, episode_id: str) -> None:
        for index, item in enumerate(self._secant_filtered):
            if item["episode_id"] == episode_id:
                break
        else:
            raise ValueError(f"SECANT episode is not on the selected date: {episode_id}")
        table = self._secant_archive_panel.table
        if table.currentRow() != index:
            table.blockSignals(True)
            table.selectRow(index)
            table.blockSignals(False)
        self.selected_secant_episode_id = episode_id
        self._secant_view_button.setEnabled(True)
        self.historical_secant_events_table = None
        self.historical_secant_flow = None
        self._history_prompt(self._secant_detail_layout, "EPISODE SELECTED",
                             f"{item['started']} · {item.get('source') or 'Not recorded'} · {item['outcome']}. Press VIEW FLOW.")
        if self.route == "past_secant_episodes":
            QTimer.singleShot(0, self.stack.adjustSize)

    def view_secant_episode_flow(self) -> None:
        episode_id = self.selected_secant_episode_id
        if episode_id is None:
            return
        item = next((entry for entry in self._secant_filtered
                     if entry["episode_id"] == episode_id), None)
        if item is None:
            return
        source = item.get("source") or "Not recorded"
        layout = self._secant_detail_layout
        self._clear_history_detail(layout)
        layout.addWidget(_horizontal_strip((
            ("EPISODE ID", item["display_episode_id"]),
            ("SOURCE", source),
            ("STAGE REACHED", item["stage"]),
            ("OUTCOME", item["outcome"]),
            ("EVENTS", str(len(item["events"]))),
        )))
        metadata = (
            ("Episode ID", item["display_episode_id"]),
            ("Distraction Source", source),
            ("Started", item["started"]),
            ("Stage Reached", item["stage"]),
            ("Return Intent", item["return_intent"]),
            ("Return Verified", item["verification"]),
            ("Recovery Interruption", item["interruption"]),
            ("Closure", item["closure"]),
            ("Related Study resource", item["study_resource"]),
            ("Event count", str(len(item["events"]))),
        )
        summary = _kv_panel("SELECTED HISTORICAL EPISODE", metadata,
                            "Past episode · static demonstration record.")
        self._bind_context("secant_archive_summary", summary.subtitle_label)
        layout.addWidget(summary)
        events = TablePanel(
            "FULL EVENT HISTORY", "Every recorded demo event for this selected episode.",
            ("#", "TIME", "EVENT", "SOURCE", "TYPE"), item["events"],
            "historicalSecantEventsTable", max_visible_rows=12,
        )
        layout.addWidget(events)
        self.historical_secant_events_table = events.table
        self._bind_context("secant_archive_events", events.subtitle_label)
        flow = FlowPanel(
            f"HISTORICAL SECANT FLOW — {item['display_episode_id']} · {item['started']} · {source}",
            "Complete selected path in recorded order; scroll horizontally for all nodes.",
            item["map_nodes"], large=True, semantic_color=True,
        )
        layout.addWidget(flow)
        self.historical_secant_flow = flow
        if self.route == "past_secant_episodes" and not getattr(self, "_restoring_archive_state", False):
            QTimer.singleShot(0, self._show_history_flow)

    def _past_study_sessions(self) -> QWidget:
        page, layout = _page()
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        picker = self._history_date_picker("studyHistoryDate")
        view_button = self._button("VIEW STUDY MAP", "history_action")
        view_button.setObjectName("viewStudyHistoryMap")
        view_button.setEnabled(False)
        self._study_date_picker = picker
        self._study_view_button = view_button
        layout.addWidget(self._history_header(
            "PAST STUDY SESSIONS",
            "Select a date, choose a session, then view its Study Jump Effect.",
            "backFromStudyHistory",
            picker, view_button,
        ))
        archive = TablePanel(
            "HISTORICAL STUDY SESSION LIST", "Choose a date above to show static demonstration sessions.",
            ("DATE", "STUDY AREA", "DURATION", "RESOURCES"),
            (), "studyArchiveTable",
        )
        archive.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(archive)
        self._study_archive_panel = archive
        self._bind_context("study_archive_list", archive.subtitle_label)
        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.setSpacing(10)
        detail.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        layout.addWidget(detail)
        self._study_detail_layout = detail_layout
        archive.table.itemSelectionChanged.connect(self._study_archive_row_changed)
        picker.currentIndexChanged.connect(self._filter_study_history)
        view_button.clicked.connect(self.view_study_session_map)
        self.set_study_session_archive(self._study_archive)
        return page

    def set_study_session_archive(self, archive: tuple[dict, ...], *,
                                  empty_state: tuple[str, str] | None = None,
                                   preserve_state: bool = False) -> None:
        """Presentation seam: accept prepared session history when wiring is approved."""
        state = self._capture_archive_state("study") if preserve_state else None
        self._study_archive = archive
        self._study_restore_token = object()
        self._study_empty_state = empty_state
        picker = self._study_date_picker
        picker.blockSignals(True)
        picker.clear()
        picker.addItem("SELECT DATE", None)
        for date in dict.fromkeys(item["date"] for item in archive):
            picker.addItem(date, date)
        picker.setCurrentIndex(0)
        picker.blockSignals(False)
        self._filter_study_history()

        if state is not None:
            self._restore_archive_state("study", state)

    def _filter_study_history(self) -> None:
        # STATIC_DATE_FILTER_ONLY: presentation filtering of the literal archive.
        date = self._study_date_picker.currentData()
        self._study_filtered = tuple(
            item for item in self._study_archive if date is not None and item["date"] == date
        )
        rows = tuple((item["date"], item["title"], item["duration"],
                      str(len(item["resources"]))) for item in self._study_filtered)
        table = self._study_archive_panel.table
        table.blockSignals(True)
        self._study_archive_panel.set_rows(rows)
        table.clearSelection()
        table.blockSignals(False)
        self.selected_study_demo_key = None
        self._study_view_button.setEnabled(False)
        self.historical_study_resources_table = None
        self.historical_study_evidence_table = None
        self.historical_study_events_table = None
        self.historical_study_flow = None
        if (date is not None and not self._study_filtered) or not self._study_archive:
            prompt = (self._study_empty_state if not self._study_archive
                      and self._study_empty_state is not None else
                      ("NO DATA", "No data for the selected Study session view."))
            self._history_prompt(self._study_detail_layout, *prompt)
        else:
            self._history_prompt(self._study_detail_layout, "SELECT A HISTORICAL STUDY SESSION",
                                 "Select a date and a session above, then press VIEW STUDY MAP.")
        self.body.verticalScrollBar().setValue(0)
        if self.route == "past_study_sessions":
            QTimer.singleShot(0, self.stack.adjustSize)

    def _study_archive_row_changed(self) -> None:
        row = self._study_archive_panel.table.currentRow()
        if 0 <= row < len(self._study_filtered):
            self.select_study_session(self._study_filtered[row]["demo_key"])

    def select_study_session(self, demo_key: str) -> None:
        for index, item in enumerate(self._study_filtered):
            if item["demo_key"] == demo_key:
                break
        else:
            raise ValueError(f"Study session is not on the selected date: {demo_key}")
        table = self._study_archive_panel.table
        if table.currentRow() != index:
            table.blockSignals(True)
            table.selectRow(index)
            table.blockSignals(False)
        self.selected_study_demo_key = demo_key
        self._study_view_button.setEnabled(True)
        self.historical_study_resources_table = None
        self.historical_study_evidence_table = None
        self.historical_study_events_table = None
        self.historical_study_flow = None
        self._history_prompt(self._study_detail_layout, "STUDY SESSION SELECTED",
                             f"{item['date']} · {item['title']} · {item['duration']}. Press VIEW STUDY MAP.")
        if self.route == "past_study_sessions":
            QTimer.singleShot(0, self.stack.adjustSize)

    def view_study_session_map(self) -> None:
        demo_key = self.selected_study_demo_key
        if demo_key is None:
            return
        item = next((entry for entry in self._study_filtered
                     if entry["demo_key"] == demo_key), None)
        if item is None:
            return
        layout = self._study_detail_layout
        self._clear_history_detail(layout)
        layout.addWidget(_horizontal_strip((
            ("PAST STUDY SESSION", item["title"]),
            ("DATE", item["date"]),
            ("DURATION", item["duration"]),
            ("RESOURCES", str(len(item["resources"]))),
            ("DIRECT STUDY JUMPS", item["direct_study_jumps"]),
        )))
        summary = _kv_panel("SELECTED STUDY SESSION", (
            ("Date", item["date"]),
            ("Study area", item["title"]),
            ("Started", item["started"]),
            ("Ended", item["ended"]),
            ("Duration", item["duration"]),
            ("Primary resource", item["primary"]),
            ("Resource entries", str(len(item["resources"]))),
        ), "Past session · static demonstration record.")
        self._bind_context("study_archive_summary", summary.subtitle_label)
        layout.addWidget(summary)
        resources = TablePanel(
            "FULL STUDY RESOURCE HISTORY",
            "Observed resource candidates; excluded videos never enter the Study Jump Effect.",
            ("#", "RESOURCE", "SUPPORTED FOREGROUND\nDURATION", "FIRST OBSERVED", "LAST OBSERVED", "QUALIFICATION"),
            item["resources"], "historicalStudyResourcesTable", max_visible_rows=12,
        )
        resources.table.horizontalHeader().setFixedHeight(41)
        layout.addWidget(resources)
        self.historical_study_resources_table = resources.table
        evidence = TablePanel(
            "EVIDENCE / QUALIFICATION SUMMARY",
            "Initially uncertain resources enter the jump only after confirmation as study-aligned.",
            ("#", "RESOURCE", "INITIAL", "LATER STATUS", "CONFIRMATION"),
            item["evidence"], "historicalStudyEvidenceTable", max_visible_rows=12,
        )
        layout.addWidget(evidence)
        self.historical_study_evidence_table = evidence.table
        events = TablePanel(
            "SESSION EVENT HISTORY", "Complete static demonstration event chronology.",
            ("#", "TIME", "EVENT", "TYPE"), item["events"],
            "historicalStudyEventsTable", max_visible_rows=12,
        )
        layout.addWidget(events)
        self.historical_study_events_table = events.table
        self._bind_context("study_archive_events", events.subtitle_label)
        flow = FlowPanel(
            f"HISTORICAL STUDY JUMP EFFECT — {item['date']} · {item['title']} · {item['duration']}",
            "Study-resource movement with interruptions and evidence gaps preserved.",
            item["jump_nodes"], large=True, study_jump=True,
        )
        layout.addWidget(flow)
        self.historical_study_flow = flow
        if self.route == "past_study_sessions" and not getattr(self, "_restoring_archive_state", False):
            QTimer.singleShot(0, self._show_history_flow)

    @staticmethod
    def _style() -> str:
        rules = [
            "QWidget#secantCosecantDashboard{background:transparent;}",
            "QFrame#dashboardSurface{background:rgba(26,43,61,0.55);border:1px solid rgba(255,255,255,0.14);border-radius:20px;}",
            "QFrame#dashboardHeader{background:rgba(255,255,255,0.02);border-bottom:1px solid rgba(255,255,255,0.10);}",
            "QFrame#dashboardNav,QFrame#dashboardSubnav{background:rgba(255,255,255,0.015);border-bottom:1px solid rgba(255,255,255,0.08);}",
            "QFrame#dashboardFooter{background:rgba(255,255,255,0.015);border-top:1px solid rgba(255,255,255,0.08);}",
            "QFrame#analysisPanel{background:#0d2639;border:1px solid #23536c;border-radius:13px;}",
            "QFrame#activeBreakStrip{background:#0b3033;border:1px solid #02af86;border-radius:13px;}",
            "QFrame#recentBreakStrip{background:#182b49;border:1px solid #4267a6;border-radius:13px;}",
            "QFrame#metricCard{background:#122b41;border:1px solid #1a7492;border-radius:12px;}",
            "QLabel#keyCell{background:#0d2234;border-bottom:1px solid #1c4157;}",
            "QLabel#valueCell{background:#0c1f30;border-bottom:1px solid #1c4157;}",
            "QPushButton{background:#0a2033;color:#bad8f6;border:1px solid #29506b;border-radius:7px;padding:5px 12px;}",
            "QPushButton:hover{border-color:#04d9ec;color:white;background:#11334b;}",
            "QPushButton:checked{background:#073b48;color:#0ef0fa;border-color:#04d9ec;}",
            "QPushButton[role='export']{color:#ffd747;border-color:#d6ae14;}",
            "QTableWidget{background:#091d2c;alternate-background-color:#0c283b;color:#e6f2ff;border:1px solid #20506a;gridline-color:#24435a;selection-background-color:#0a5566;selection-color:white;}",
            "QHeaderView::section{background:#12364b;color:#b6d9f5;border:none;border-right:1px solid #2d5269;padding:5px;font-weight:600;}",
            "QScrollArea#dashboardBody,QScrollArea#flowScroll{background:transparent;border:none;}",
            "QStackedWidget#dashboardStack{background:transparent;}",
            "QScrollBar:vertical,QScrollBar:horizontal{background:#0a2030;}",
            "QScrollBar::handle:vertical,QScrollBar::handle:horizontal{background:#24647a;border-radius:4px;min-height:25px;min-width:25px;}",
        ]
        for tone, color in TONE.items():
            rules.append(f"QFrame#flowNode[tone='{tone}']{{background:#10293b;border:1px solid {color};border-radius:10px;}}")
        return "\n".join(rules)


class SecantLandingPage(QWidget, _PresentationContext):
    """Static main SECANT face, composed like the COSINE landing page."""

    open_analysis_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._init_context()
        self.setObjectName("secantLandingPage")
        self.setStyleSheet("QWidget#secantLandingPage{background:#08111d;}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("secantLandingScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea#secantLandingScroll{background:transparent;border:none;}"
            "QScrollBar:vertical{background:#102236;width:9px;}"
            "QScrollBar::handle:vertical{background:#345f79;border-radius:4px;min-height:32px;}"
        )
        root.addWidget(scroll)
        body = QWidget()
        body.setObjectName("secantLandingBody")
        body.setStyleSheet("QWidget#secantLandingBody{background:#08111d;}")
        scroll.setWidget(body)
        column = QVBoxLayout(body)
        column.setContentsMargins(34, 22, 34, 42)
        column.setSpacing(20)
        column.addWidget(self._heading())
        column.addWidget(self._status())
        column.addWidget(self._recent())
        column.addWidget(self._metrics())
        column.addWidget(self._information())
        self.recent_flow = FlowPanel(
            "RECENT SECANT EPISODE FLOW",
            "Static demonstration sequence in recorded order; elapsed labels are fixture text.",
            (), large=True, semantic_color=True,
        )
        column.addWidget(self.recent_flow)
        self._bind_context("landing_flow", self.recent_flow.subtitle_label)
        column.addWidget(self._context_label("source_banner", "DEMO VALUES · NOT REAL EVIDENCE", size=8, color=CYAN, mono=True))
        column.addStretch(1)
        self.set_landing_data(status=demo.LANDING_STATUS, recent_episode=demo.RECENT_EPISODE,
                              recent_badges=demo.LANDING_RECENT_BADGES,
                              metrics=demo.OVERVIEW_METRICS[:4], behaviour=demo.LANDING_BEHAVIOUR,
                              latest_events=tuple(reversed(demo.LATEST_SECANT_EVENTS)),
                              journey=demo.SECANT_FLOW)

    def _heading(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        dot = _label("●", size=14, color=TONE["teal"])
        row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(5)
        text.addWidget(_label("SECANT — STUDY RECOVERY REGULATION", size=19, weight=700))
        text.addWidget(_label("Study Escape and Cognitive Attention Navigation Tracker", size=11, color=MUTED))
        row.addLayout(text)
        row.addStretch(1)
        button = QPushButton("OPEN DEEP ANALYSIS")
        button.setObjectName("openSecantDeepAnalysis")
        button.setFont(_font(10, 700))
        button.setMinimumSize(188, 49)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            "QPushButton#openSecantDeepAnalysis{background:rgba(4,217,236,0.04);"
            "color:#02e2e6;border:1px solid #078d99;border-radius:11px;padding:9px 18px;}"
            "QPushButton#openSecantDeepAnalysis:hover{background:rgba(4,217,236,0.14);"
            "border-color:#04d9ec;color:white;}"
        )
        button.clicked.connect(self.open_analysis_requested.emit)
        row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        return host

    def _status(self) -> QWidget:
        card = QFrame()
        card.setObjectName("secantLandingStatus")
        card.setMinimumHeight(98)
        card.setStyleSheet(
            "QFrame#secantLandingStatus{background:rgba(80,54,81,0.48);"
            "border:1px solid rgba(221,92,139,0.48);border-radius:23px;}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(28, 18, 28, 18)
        left = QVBoxLayout()
        left.setSpacing(7)
        self.status_caption = _label("", size=10, color="#d2b5cf", mono=True)
        self.status_message = _label("", size=15, weight=700, color=TONE["red"])
        left.addWidget(self.status_caption)
        left.addWidget(self.status_message)
        row.addLayout(left)
        row.addStretch(1)
        self.status_state = _label("", size=16, weight=700)
        row.addWidget(self.status_state)
        return card

    def _recent(self) -> QWidget:
        card = QFrame()
        card.setObjectName("secantLandingRecent")
        card.setStyleSheet(
            "QFrame#secantLandingRecent{background:rgba(35,49,83,0.85);"
            "border:1px solid rgba(91,123,211,0.47);border-radius:23px;}"
        )
        row = QHBoxLayout(card)
        row.setContentsMargins(26, 21, 26, 21)
        row.setSpacing(26)
        left = QVBoxLayout()
        left.setSpacing(7)
        left.addWidget(_label("RECENT EPISODE", size=9, color=MUTED, mono=True))
        source = QHBoxLayout()
        source.setSpacing(11)
        self.recent_source = _label("", size=22, weight=700)
        self.recent_badge_one = _label("", size=9, color=MUTED, mono=True)
        self.recent_badge_two = _label("", size=9, color=TONE["green"], mono=True)
        source.addWidget(self.recent_source)
        source.addWidget(self.recent_badge_one)
        source.addWidget(self.recent_badge_two)
        source.addStretch(1)
        left.addLayout(source)
        self.recent_id = _label("", size=9, color=MUTED, mono=True)
        left.addWidget(self.recent_id)
        row.addLayout(left, 2)
        fields = []
        for title in ("STAGE REACHED", "CLOSURE", "RECORDED AT", "STUDY RESOURCE"):
            field = QVBoxLayout()
            field.setSpacing(5)
            field.addWidget(_label(title, size=9, color=MUTED, mono=True))
            value_label = _label("", size=10, weight=600, wrap=True)
            field.addWidget(value_label)
            field.addStretch(1)
            row.addLayout(field, 1)
            fields.append(value_label)
        self.recent_fields = tuple(fields)
        return card

    def _metrics(self) -> QWidget:
        host = QWidget()
        row = QHBoxLayout(host)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(16)
        metric_labels = []
        for tone in ("teal", "green", "purple", "blue"):
            card = QFrame()
            card.setObjectName("secantLandingMetric")
            card.setStyleSheet(
                "QFrame#secantLandingMetric{background:rgba(30,44,65,0.94);"
                f"border:1px solid {TONE[tone]};border-radius:23px;}}"
            )
            box = QVBoxLayout(card)
            box.setContentsMargins(20, 17, 20, 17)
            box.setSpacing(5)
            value_label = _label("", size=27, weight=700, color=TONE[tone])
            caption_label = _label("", size=10, weight=700, color=MUTED)
            note_label = _label("", size=9, color=MUTED, wrap=True)
            box.addWidget(value_label)
            box.addWidget(caption_label)
            box.addWidget(note_label)
            row.addWidget(card, 1)
            metric_labels.append((caption_label, value_label, note_label))
        self.metric_labels = tuple(metric_labels)
        return host

    def _information(self) -> QWidget:
        behaviour, left = _panel("DISTRACTION / EPISODE BEHAVIOUR")
        left.setSpacing(10)
        left.addWidget(_label("PLATFORM PATH", size=9, color=MUTED, mono=True))
        path = QFrame()
        path.setObjectName("secantLandingPath")
        path.setStyleSheet(
            "QFrame#secantLandingPath{background:rgba(49,64,104,0.45);"
            "border:1px solid rgba(91,123,211,0.46);border-radius:15px;}"
        )
        path_row = QHBoxLayout(path)
        path_row.setContentsMargins(15, 10, 15, 10)
        self.behaviour_source = _label("", size=13, weight=600)
        path_row.addWidget(self.behaviour_source)
        path_row.addStretch(1)
        self.behaviour_path = _label("", size=8, color=MUTED, mono=True)
        path_row.addWidget(self.behaviour_path)
        left.addWidget(path)
        self.behaviour_stage = _label("", size=10)
        self.behaviour_outcome = _label("", size=10, color=MUTED, wrap=True)
        left.addWidget(self.behaviour_stage)
        left.addWidget(self.behaviour_outcome)
        left.addStretch(1)

        events, right = _panel("LATEST EVENTS", "Last five static demonstration events.")
        event_cells = []
        self._bind_context("landing_events", events.subtitle_label)
        for _ in demo.LATEST_SECANT_EVENTS:
            line = QFrame()
            line.setObjectName("secantLandingEvent")
            line.setStyleSheet(
                "QFrame#secantLandingEvent{background:rgba(7,24,42,0.26);"
                "border:none;border-bottom:1px solid rgba(112,161,190,0.19);}"
            )
            cells = QHBoxLayout(line)
            cells.setContentsMargins(5, 6, 5, 6)
            cells.setSpacing(9)
            dot = _label("●", size=9, color=TONE["purple"])
            event_label = _label("", size=10)
            source_label = _label("", size=9, color=MUTED)
            stamp_label = _label("", size=9, color=MUTED, mono=True)
            cells.addWidget(dot)
            cells.addWidget(event_label, 2)
            cells.addWidget(source_label, 1)
            cells.addWidget(stamp_label)
            event_cells.append((line, dot, event_label, source_label, stamp_label))
            right.addWidget(line)
        right.addStretch(1)
        self.event_cells = tuple(event_cells)
        return _row_container(behaviour, events)

    def set_landing_data(self, *, status: tuple[str, str, str, str],
                         recent_episode: tuple, recent_badges: tuple[str, str],
                         metrics: tuple, behaviour: tuple[str, str, str, str],
                         latest_events: tuple, journey: tuple) -> None:
        """Display prepared landing status, episode, metrics, event rows, and flow."""
        if len(recent_episode) != 6 or len(metrics) != len(self.metric_labels):
            raise ValueError("Landing field count differs from the displayed layout")
        if len(latest_events) > len(self.event_cells):
            raise ValueError("Landing event count exceeds the five displayed slots")
        caption, message, state, tone = status
        self.status_caption.setText(caption)
        self.status_message.setText(message)
        self.status_message.setStyleSheet(f"color:{TONE[tone]};background:transparent;border:none;")
        self.status_state.setText(state)
        self.recent_source.setText(recent_episode[1][1])
        self.recent_id.setText(recent_episode[0][1])
        self.recent_badge_one.setText(recent_badges[0])
        self.recent_badge_two.setText(recent_badges[1])
        for label, (_, value) in zip(self.recent_fields, recent_episode[2:]):
            label.setText(value)
        for labels, (caption, value, note) in zip(self.metric_labels, metrics):
            caption_label, value_label, note_label = labels
            caption_label.setText(caption)
            value_label.setText(value)
            note_label.setText(note)
        for label, value in zip((self.behaviour_source, self.behaviour_path,
                                 self.behaviour_stage, self.behaviour_outcome), behaviour):
            label.setText(value)
        for index, (line, dot, event_label, source_label, stamp_label) in enumerate(self.event_cells):
            if index >= len(latest_events):
                line.hide()
                continue
            _number, stamp, event, source, event_type = latest_events[index]
            line.show()
            dot.setStyleSheet(f"color:{TONE['teal'] if event_type == 'Derived' else TONE['purple']};"
                              "background:transparent;border:none;")
            event_label.setText(event)
            source_label.setText(source)
            stamp_label.setText(stamp)
        self.recent_flow.set_nodes(journey)


class SecantCosecantDashboard(QWidget):
    """Control Station destination: main SECANT face, then Deep Analysis."""

    ROUTES = SecantDeepAnalysis.ROUTES
    close_requested = pyqtSignal()
    refresh_requested = pyqtSignal()
    export_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("secantDashboardPage")
        self.setStyleSheet(self._style())
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.landing = SecantLandingPage()
        root.addWidget(self.landing)
        self.analysis = SecantDeepAnalysis(self)
        self.analysis.hide()
        self.landing.open_analysis_requested.connect(self.open_analysis)
        self.analysis.close_requested.connect(self.show_landing)
        self.analysis.refresh_requested.connect(self.refresh_requested.emit)
        self.analysis.export_requested.connect(self.export_requested.emit)

    def set_export_busy(self, busy: bool, message: str = '') -> None:
        self.analysis._export_button.setEnabled(not busy)
        if message:
            self.analysis._feedback(message)

    def set_presentation_context(self, *, captions: dict[str, str],
                                 refresh_feedback: str = "") -> None:
        """Receive source captions and explicit refresh feedback; empty means silent.

        Keys are restricted to CONTEXT_CAPTION_KEYS. Omitted keys retain their
        current text. No data, environment, or consumer inspection selects mode.
        """
        unknown = captions.keys() - CONTEXT_CAPTION_KEYS
        if unknown or any(not isinstance(value, str) for value in captions.values()):
            raise ValueError("Unknown caption key or non-string presentation text")
        if not isinstance(refresh_feedback, str):
            raise TypeError("refresh_feedback must be prepared text")
        self.landing._apply_context(captions)
        self.analysis._apply_context(captions)
        self.analysis._refresh_feedback = refresh_feedback

    def set_landing_data(self, *, status: tuple[str, str, str, str],
                         recent_episode: tuple, recent_badges: tuple[str, str],
                         metrics: tuple, behaviour: tuple[str, str, str, str],
                         latest_events: tuple, journey: tuple) -> None:
        self.landing.set_landing_data(status=status, recent_episode=recent_episode,
                                      recent_badges=recent_badges, metrics=metrics,
                                      behaviour=behaviour, latest_events=latest_events,
                                      journey=journey)

    def set_overview_data(self, *, metrics: tuple, recent_episode: tuple,
                          study_snapshot: tuple, latest_events: tuple,
                          insights: tuple, journey: tuple) -> None:
        self.analysis.set_overview_data(metrics=metrics, recent_episode=recent_episode,
                                        study_snapshot=study_snapshot, latest_events=latest_events,
                                        insights=insights, journey=journey)

    def set_episodes_data(self, *, metrics: tuple, rows: tuple,
                          recent_episode: tuple, flow: tuple) -> None:
        self.analysis.set_episodes_data(metrics=metrics, rows=rows,
                                        recent_episode=recent_episode, flow=flow)

    def set_distraction_history_data(self, *, metrics: tuple, rows: tuple,
                                     attributes: tuple, flow: tuple) -> None:
        self.analysis.set_distraction_history_data(metrics=metrics, rows=rows,
                                                    attributes=attributes, flow=flow)

    def set_study_history_data(self, *, metrics: tuple, rows: tuple,
                               jump_nodes: tuple) -> None:
        self.analysis.set_study_history_data(metrics=metrics, rows=rows,
                                              jump_nodes=jump_nodes)

    def set_study_evidence_data(self, *, metrics: tuple, rows: tuple,
                                attributes: tuple, confirmation_nodes: tuple) -> None:
        self.analysis.set_study_evidence_data(metrics=metrics, rows=rows,
                                               attributes=attributes,
                                               confirmation_nodes=confirmation_nodes)

    def set_cosecant_data(self, *, main_summary: tuple, recent_break: tuple,
                          metrics: tuple, break_history: tuple,
                          events: tuple, return_history: tuple, flow: tuple) -> None:
        self.analysis.set_cosecant_data(main_summary=main_summary, recent_break=recent_break,
                                         metrics=metrics, break_history=break_history,
                                         events=events, return_history=return_history, flow=flow)

    def set_secant_episode_archive(self, archive: tuple[dict, ...], *,
                                   empty_state: tuple[str, str] | None = None,
                                   preserve_state: bool = False) -> None:
        self.analysis.set_secant_episode_archive(archive, empty_state=empty_state,
                                                  preserve_state=preserve_state)

    def set_study_session_archive(self, archive: tuple[dict, ...], *,
                                  empty_state: tuple[str, str] | None = None,
                                   preserve_state: bool = False) -> None:
        self.analysis.set_study_session_archive(archive, empty_state=empty_state,
                                                  preserve_state=preserve_state)

    @staticmethod
    def _style() -> str:
        return "QWidget#secantDashboardPage{background:#08111d;}"

    def _retheme(self, _theme) -> None:
        self.setStyleSheet(self._style())

    def show_landing(self) -> None:
        self.analysis.close_overlay()

    def open_analysis(self) -> None:
        self.analysis.select_route("overview")
        self.analysis.open_overlay()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.analysis.isVisible():
            self.analysis.setGeometry(self.rect())

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # A new MENU visit always starts at the main SECANT face.
        self.show_landing()


if __name__ == "__main__":
    # Standalone visual UAT entry. Does not instantiate the Control Station engine.
    import sys
    from PyQt6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = SecantCosecantDashboard()
    window.setWindowTitle("MYELIN · SECANT / COSECANT Dummy Dashboard")
    window.resize(1600, 850)
    window.show()
    sys.exit(app.exec())
