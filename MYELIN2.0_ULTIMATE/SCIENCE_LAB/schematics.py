"""Chapter 2 -- Parts of MYELIN: presentation-only organ schematics.

``ChapterTwoOrganViewer`` owns the four-organ selector (SINE / MINE /
COSINE / COSECANT) and the "living schematic" for whichever organ is
selected.  Phase 1 built SINE's schematic in full; Phase 2 added MINE's;
Phase 3 added COSINE's; Phase 4 adds COSECANT's.  No Chapter 2 organ
placeholders remain.

This is a SCHEMATIC DEMONSTRATION, not live telemetry: it runs exactly the
same whether or not a MYELIN session is active, and clicking anything here
never reaches SINE, MINE, COSINE, COSECANT, or any other MYELIN authority.
The colours/labels/timings quoted below were verified directly against
SINE/sine.py and SINE/popup.py (Chapter 2 Phase 1 forensic audit),
MINE/mine.py and MINE/popup.py (Chapter 2 Phase 2 forensic audit),
COSINE/cosine.py and COSINE/popup.py (Chapter 2 Phase 3 forensic audit),
and COSECANT_STUDY_MODE/cosecant.py and view.py (Chapter 2 Phase 4
forensic audit); this module never imports any of them at runtime.

Import boundary (same one-directional composition Chapter 1 already
uses): this module may import PyQt6 and UI_THEMES.theme.make_font.  It
must NOT import CORE_ENGINE, SINE, MINE, COSINE, MIRL,
COSECANT_STUDY_MODE, PERSISTENCE, sqlite3, or SCIENCE_LAB.lab (lab.py
hosts this module; this module never reaches back into lab.py, so there
is no import cycle).
"""

from __future__ import annotations

from typing import Callable, Final

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from UI_THEMES.theme import make_font

from .chapters import (
    CHAPTER_TWO_ORGANS,
    COSECANT_BRANCH_FACTS,
    COSECANT_POPUP_FACTS,
    COSECANT_TIMING_FACTS,
    COSINE_BRANCH_FACTS,
    COSINE_PLATFORM_FACTS,
    COSINE_POPUP_FACTS,
    COSINE_TIMING_FACTS,
    MINE_BRANCH_FACTS,
    MINE_STAGE_FACTS,
    MINE_TIMING_FACTS,
    SINE_STAGE_FACTS,
    SINE_TIMING_FACTS,
)

#: Animation step cadence.  Deliberately gentle (not a 30fps canvas): this
#: is a state-change-and-small-repaint demonstration, not a real-time
#: telemetry view, and MYELIN already has real timers running elsewhere.
_STEP_MS: Final = 220

_MUTED_STROKE: Final = "#3B4A63"


def _allow_shrink(widget: QWidget) -> None:
    """Same technique Chapter 1 uses: let a widget shrink below its
    natural width instead of forcing every ancestor layout's minimum
    width up with it."""

    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    widget.setSizePolicy(policy)


# ---------------------------------------------------------------------------
# Deterministic Qt-drawn symbols (never emoji, never a photo -- theme-
# consistent, dimension-stable regardless of platform font/emoji set).
# ---------------------------------------------------------------------------


class _PaintedSymbol(QWidget):
    """Base for small deterministic Qt-drawn symbols."""

    def __init__(self, *, size: int = 64, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = "#94A3B8"
        self._active = False
        self.setFixedSize(size, size)

    def set_accent(self, color: str) -> None:
        self._accent = color
        self.update()

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self.update()

    def _stroke_color(self) -> QColor:
        return QColor(self._accent if self._active else _MUTED_STROKE)


class _HumanSymbol(_PaintedSymbol):
    """USER: simple outline human figure.  Accessible name: "User"."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=56, parent=parent)
        self.setAccessibleName("User")

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        w, h = float(self.width()), float(self.height())
        cx = w / 2
        head_r = h * 0.13
        head_cy = h * 0.20
        painter.drawEllipse(QPointF(cx, head_cy), head_r, head_r)
        torso_top = head_cy + head_r
        torso_bottom = h * 0.62
        painter.drawLine(QPointF(cx, torso_top), QPointF(cx, torso_bottom))
        arm_y = h * 0.40
        painter.drawLine(QPointF(cx - w * 0.22, arm_y + h * 0.10), QPointF(cx, arm_y))
        painter.drawLine(QPointF(cx + w * 0.22, arm_y + h * 0.10), QPointF(cx, arm_y))
        painter.drawLine(QPointF(cx, torso_bottom), QPointF(cx - w * 0.18, h * 0.88))
        painter.drawLine(QPointF(cx, torso_bottom), QPointF(cx + w * 0.18, h * 0.88))
        painter.end()


class _MonitorSymbol(_PaintedSymbol):
    """MONITOR: screen + stand.  Accessible name: "MYELIN Monitor"."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=56, parent=parent)
        self.setAccessibleName("MYELIN Monitor")

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.2)
        painter.setPen(pen)
        w, h = float(self.width()), float(self.height())
        screen = QRectF(w * 0.12, h * 0.12, w * 0.76, h * 0.50)
        painter.drawRoundedRect(screen, 4, 4)
        painter.drawLine(
            QPointF(screen.left() + 6, screen.center().y()),
            QPointF(screen.right() - 6, screen.center().y()),
        )
        painter.drawLine(QPointF(w / 2, screen.bottom()), QPointF(w / 2, h * 0.74))
        painter.drawLine(QPointF(w * 0.30, h * 0.86), QPointF(w * 0.70, h * 0.86))
        painter.end()


class _EvidenceSymbol(_PaintedSymbol):
    """ELIGIBLE OFF-TASK EVIDENCE / TRIGGER: a small pulse/exclamation
    mark -- never a magnifying "surveillance" glass rendered as camera-
    like imagery."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=48, parent=parent)
        self.setAccessibleName("Eligible off-task evidence")

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(w / 2, h * 0.22), QPointF(w / 2, h * 0.58))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._stroke_color()))
        painter.drawEllipse(QPointF(w / 2, h * 0.76), 2.6, 2.6)
        painter.end()


class _SineSymbol(_PaintedSymbol):
    """SINE: ring + intervention pulse + three-stage marker arc.  Reads as
    "intervention / escalation", never a brain scan or ECG."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=72, parent=parent)
        self.setAccessibleName("SINE intervention organ")
        self._lit_stage: str | None = None

    def set_lit_stage(self, stage: str | None) -> None:
        self._lit_stage = stage
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2, h / 2
        r = min(w, h) * 0.34
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.6)
        painter.setPen(pen)
        painter.drawEllipse(QPointF(cx, cy), r, r)

        path = QPainterPath()
        path.moveTo(cx - r * 0.65, cy)
        path.cubicTo(cx - r * 0.30, cy - r * 0.55, cx - r * 0.10, cy + r * 0.55, cx + r * 0.15, cy)
        path.cubicTo(cx + r * 0.35, cy - r * 0.40, cx + r * 0.50, cy + r * 0.30, cx + r * 0.65, cy)
        painter.drawPath(path)

        markers = (
            ("sine_1", cx, cy - r - 7, "#3DDCFF"),
            ("sine_2", cx + r + 7, cy, "#F5A623"),
            ("sine_3", cx, cy + r + 7, "#FF4D6D"),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        for key, mx, my, color in markers:
            lit = key == self._lit_stage
            dot_color = QColor(color) if lit else QColor(color).darker(180)
            painter.setBrush(QBrush(dot_color))
            radius = 4.6 if lit else 3.0
            painter.drawEllipse(QPointF(mx, my), radius, radius)
        painter.end()


class _CheckSymbol(_PaintedSymbol):
    """MIRL: small recovery/return checkmark."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=40, parent=parent)
        self.setAccessibleName("MIRL recovery verification")

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        w, h = float(self.width()), float(self.height())
        path = QPainterPath()
        path.moveTo(w * 0.22, h * 0.52)
        path.lineTo(w * 0.42, h * 0.72)
        path.lineTo(w * 0.80, h * 0.30)
        painter.drawPath(path)
        painter.end()


class _PauseSymbol(_PaintedSymbol):
    """NORMAL BREAK: small neutral pause glyph."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=40, parent=parent)
        self.setAccessibleName("Normal Break")

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._stroke_color()))
        w, h = float(self.width()), float(self.height())
        bar_w = w * 0.16
        painter.drawRoundedRect(QRectF(w * 0.30, h * 0.26, bar_w, h * 0.48), 2, 2)
        painter.drawRoundedRect(QRectF(w * 0.56, h * 0.26, bar_w, h * 0.48), 2, 2)
        painter.end()


class _MessagingSymbol(_PaintedSymbol):
    """CERTIFIED MESSAGING: a chat-bubble card with platform dots.
    Accessible name: "Certified Messaging"."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=52, parent=parent)
        self.setAccessibleName("Certified Messaging")

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.2)
        painter.setPen(pen)
        bubble = QRectF(w * 0.14, h * 0.16, w * 0.72, h * 0.48)
        painter.drawRoundedRect(bubble, 8, 8)
        tail = QPainterPath()
        tail.moveTo(bubble.left() + w * 0.16, bubble.bottom())
        tail.lineTo(bubble.left() + w * 0.10, bubble.bottom() + h * 0.14)
        tail.lineTo(bubble.left() + w * 0.30, bubble.bottom())
        painter.drawPath(tail)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._stroke_color()))
        for dx in (-0.14, 0.0, 0.14):
            painter.drawEllipse(QPointF(bubble.center().x() + dx * w, bubble.center().y()), 2.4, 2.4)
        painter.end()


class _MineSymbol(_PaintedSymbol):
    """MINE: two overlapping chat bubbles + a pulse line -- reads as
    "messaging-specific intervention", never a brain icon.  Mirrors the
    SINE symbol's three-marker convention with MINE's own stage keys
    (mine_1 / mine_2 / recovery) so the same lit-stage grammar teaches
    both organs without either importing the other."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=72, parent=parent)
        self.setAccessibleName("MINE messaging intervention")
        self._lit_stage: str | None = None

    def set_lit_stage(self, stage: str | None) -> None:
        self._lit_stage = stage
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2, h / 2
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.4)
        painter.setPen(pen)

        back = QRectF(cx - w * 0.30, cy - h * 0.26, w * 0.42, h * 0.30)
        painter.drawRoundedRect(back, 7, 7)
        front = QRectF(cx - w * 0.10, cy - h * 0.12, w * 0.42, h * 0.30)
        painter.drawRoundedRect(front, 7, 7)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._stroke_color()))
        for dx in (0.02, 0.13, 0.24):
            painter.drawEllipse(QPointF(front.left() + dx * w, front.center().y()), 2.2, 2.2)

        pulse_pen = QPen(self._stroke_color())
        pulse_pen.setWidthF(2.0)
        painter.setPen(pulse_pen)
        path = QPainterPath()
        path.moveTo(cx - w * 0.28, h * 0.80)
        path.lineTo(cx - w * 0.10, h * 0.80)
        path.lineTo(cx - w * 0.02, h * 0.68)
        path.lineTo(cx + w * 0.06, h * 0.88)
        path.lineTo(cx + w * 0.14, h * 0.80)
        path.lineTo(cx + w * 0.30, h * 0.80)
        painter.drawPath(path)

        markers = (
            ("mine_1", cx, cy - h * 0.42, "#F5A623"),
            ("mine_2", cx + w * 0.40, cy, "#FF4D6D"),
            ("recovery", cx, cy + h * 0.42, "#39D98A"),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        for key, mx, my, color in markers:
            lit = key == self._lit_stage
            dot_color = QColor(color) if lit else QColor(color).darker(180)
            painter.setBrush(QBrush(dot_color))
            radius = 4.6 if lit else 3.0
            painter.drawEllipse(QPointF(mx, my), radius, radius)
        painter.end()


class _TimerSymbol(_PaintedSymbol):
    """A generic qualifying-time clock glyph -- reused for every MINE
    timing node (10:00 gate, 13:15 window, 5-30 minute allowance)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=48, parent=parent)
        self.setAccessibleName("Qualifying messaging timer")

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2, h / 2
        r = min(w, h) * 0.34
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.drawLine(QPointF(cx, cy), QPointF(cx, cy - r * 0.55))
        painter.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.4, cy))
        painter.end()


class _NeutralSymbol(_PaintedSymbol):
    """A neutral / no-credit context glyph -- deliberately distinct from
    SINE's Normal Break pause bars, since MINE's neutral detour is a
    different authority/timer concept (pauses a clock; SINE's Normal
    Break gates a different branch entirely)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=40, parent=parent)
        self.setAccessibleName("Neutral context")

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(QRectF(w * 0.20, h * 0.20, w * 0.60, h * 0.60))
        painter.drawLine(QPointF(w * 0.34, h * 0.5), QPointF(w * 0.66, h * 0.5))
        painter.end()


class _OttSymbol(_PaintedSymbol):
    """CERTIFIED OTT: a small screen + verified check badge.  Accessible
    name: "Certified OTT platform"."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=52, parent=parent)
        self.setAccessibleName("Certified OTT platform")

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.2)
        painter.setPen(pen)
        screen = QRectF(w * 0.12, h * 0.16, w * 0.62, h * 0.46)
        painter.drawRoundedRect(screen, 4, 4)
        play = QPainterPath()
        cx, cy = screen.center().x(), screen.center().y()
        play.moveTo(cx - screen.width() * 0.12, cy - screen.height() * 0.18)
        play.lineTo(cx - screen.width() * 0.12, cy + screen.height() * 0.18)
        play.lineTo(cx + screen.width() * 0.16, cy)
        play.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._stroke_color()))
        painter.drawPath(play)
        check_pen = QPen(self._stroke_color())
        check_pen.setWidthF(2.2)
        check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(check_pen)
        badge_cx, badge_cy = w * 0.78, h * 0.68
        badge_r = w * 0.18
        painter.drawEllipse(QPointF(badge_cx, badge_cy), badge_r, badge_r)
        tick = QPainterPath()
        tick.moveTo(badge_cx - badge_r * 0.45, badge_cy)
        tick.lineTo(badge_cx - badge_r * 0.1, badge_cy + badge_r * 0.4)
        tick.lineTo(badge_cx + badge_r * 0.5, badge_cy - badge_r * 0.35)
        painter.drawPath(tick)
        painter.end()


class _CosineSymbol(_PaintedSymbol):
    """COSINE: a streaming screen with a play triangle and an orbit/loop
    -- reads as "streaming / continued viewing", never a brain icon.
    Mirrors the SINE/MINE symbols' lit-stage marker convention with
    COSINE's own stage keys (intention / break / recovery)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=72, parent=parent)
        self.setAccessibleName("COSINE streaming intervention")
        self._lit_stage: str | None = None

    def set_lit_stage(self, stage: str | None) -> None:
        self._lit_stage = stage
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2, h / 2
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.4)
        painter.setPen(pen)

        screen = QRectF(cx - w * 0.26, cy - h * 0.24, w * 0.52, h * 0.36)
        painter.drawRoundedRect(screen, 6, 6)
        play = QPainterPath()
        sx, sy = screen.center().x(), screen.center().y()
        play.moveTo(sx - screen.width() * 0.14, sy - screen.height() * 0.22)
        play.lineTo(sx - screen.width() * 0.14, sy + screen.height() * 0.22)
        play.lineTo(sx + screen.width() * 0.20, sy)
        play.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._stroke_color()))
        painter.drawPath(play)

        loop_pen = QPen(self._stroke_color())
        loop_pen.setWidthF(2.0)
        painter.setPen(loop_pen)
        loop_rect = QRectF(cx - w * 0.16, cy + h * 0.10, w * 0.32, h * 0.20)
        painter.drawArc(loop_rect, 20 * 16, 300 * 16)
        arrow = QPainterPath()
        tip_x, tip_y = loop_rect.right() - w * 0.02, loop_rect.top() + h * 0.02
        arrow.moveTo(tip_x, tip_y)
        arrow.lineTo(tip_x - w * 0.05, tip_y - h * 0.01)
        arrow.moveTo(tip_x, tip_y)
        arrow.lineTo(tip_x - w * 0.01, tip_y + h * 0.05)
        painter.drawPath(arrow)

        markers = (
            ("intention", cx, cy - h * 0.42, "#38BDF8"),
            ("break", cx + w * 0.40, cy, "#F5A623"),
            ("recovery", cx, cy + h * 0.44, "#39D98A"),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        for key, mx, my, color in markers:
            lit = key == self._lit_stage
            dot_color = QColor(color) if lit else QColor(color).darker(180)
            painter.setBrush(QBrush(dot_color))
            radius = 4.6 if lit else 3.0
            painter.drawEllipse(QPointF(mx, my), radius, radius)
        painter.end()


class _StudySymbol(_PaintedSymbol):
    """STUDY MODE: a small open-book glyph.  Accessible name: "Study
    Mode"."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=52, parent=parent)
        self.setAccessibleName("Study Mode")

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.2)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = w / 2
        top, bottom = h * 0.26, h * 0.68
        spine_top = QPointF(cx, top + h * 0.06)
        left = QPainterPath()
        left.moveTo(cx, spine_top.y())
        left.lineTo(w * 0.22, top)
        left.lineTo(w * 0.22, bottom)
        left.lineTo(cx, bottom - h * 0.06)
        painter.drawPath(left)
        right = QPainterPath()
        right.moveTo(cx, spine_top.y())
        right.lineTo(w * 0.78, top)
        right.lineTo(w * 0.78, bottom)
        right.lineTo(cx, bottom - h * 0.06)
        painter.drawPath(right)
        painter.drawLine(QPointF(cx, spine_top.y()), QPointF(cx, bottom - h * 0.06))
        painter.end()


class _ExactResourceSymbol(_PaintedSymbol):
    """EXACT STUDY RESOURCE: a document/browser card with a small lock
    marker -- reads as "frozen, specific target", never a generic
    checkmark."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=52, parent=parent)
        self.setAccessibleName("Exact registered Study resource")

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.2)
        painter.setPen(pen)
        card = QRectF(w * 0.16, h * 0.14, w * 0.58, h * 0.5)
        painter.drawRoundedRect(card, 4, 4)
        for dy in (0.28, 0.42):
            painter.drawLine(
                QPointF(card.left() + card.width() * 0.16, h * dy),
                QPointF(card.right() - card.width() * 0.16, h * dy),
            )
        lock_cx, lock_cy = w * 0.74, h * 0.72
        body = QRectF(lock_cx - w * 0.14, lock_cy - h * 0.02, w * 0.28, h * 0.2)
        painter.drawRoundedRect(body, 3, 3)
        shackle = QRectF(lock_cx - w * 0.09, lock_cy - h * 0.16, w * 0.18, h * 0.18)
        painter.drawArc(shackle, 0, 180 * 16)
        painter.end()


class _CosecantSymbol(_PaintedSymbol):
    """COSECANT: a clock face + a return loop + a small study tick --
    reads as "break timing / return regulation", never a brain icon.
    Mirrors the SINE/MINE/COSINE symbols' lit-stage marker convention
    with COSECANT's own stage keys (break / overdue / recovery)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(size=72, parent=parent)
        self.setAccessibleName("COSECANT break-return regulator")
        self._lit_stage: str | None = None

    def set_lit_stage(self, stage: str | None) -> None:
        self._lit_stage = stage
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2, h / 2
        r = min(w, h) * 0.28
        pen = QPen(self._stroke_color())
        pen.setWidthF(2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawEllipse(QPointF(cx, cy - h * 0.04), r, r)
        painter.drawLine(QPointF(cx, cy - h * 0.04), QPointF(cx, cy - h * 0.04 - r * 0.55))
        painter.drawLine(QPointF(cx, cy - h * 0.04), QPointF(cx + r * 0.4, cy - h * 0.04))

        loop_pen = QPen(self._stroke_color())
        loop_pen.setWidthF(2.0)
        painter.setPen(loop_pen)
        loop_rect = QRectF(cx - r * 1.15, cy + h * 0.10, r * 1.6, h * 0.22)
        painter.drawArc(loop_rect, 15 * 16, 320 * 16)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._stroke_color()))
        tick = QPainterPath()
        tick.moveTo(cx - w * 0.06, h * 0.86)
        tick.lineTo(cx - w * 0.01, h * 0.90)
        tick.lineTo(cx + w * 0.08, h * 0.80)
        pen2 = QPen(self._stroke_color())
        pen2.setWidthF(2.0)
        pen2.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen2.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen2)
        painter.drawPath(tick)

        markers = (
            ("break", cx, cy - h * 0.42, "#39D98A"),
            ("overdue", cx + w * 0.42, cy - h * 0.02, "#F5A623"),
            ("recovery", cx - w * 0.42, cy - h * 0.02, "#39D98A"),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        for key, mx, my, color in markers:
            lit = key == self._lit_stage
            dot_color = QColor(color) if lit else QColor(color).darker(180)
            painter.setBrush(QBrush(dot_color))
            radius = 4.6 if lit else 3.0
            painter.drawEllipse(QPointF(mx, my), radius, radius)
        painter.end()


# ---------------------------------------------------------------------------
# Small reusable presentation pieces
# ---------------------------------------------------------------------------


class _Node(QFrame):
    """One labelled schematic node: a painted symbol, a title, and an
    optional one-line caption.  ``set_active`` drives both the symbol's
    own colour and the frame's glow via the existing dynamic-property /
    QSS-repolish convention (matching labChapterButton's chapterState)."""

    def __init__(
        self,
        symbol: _PaintedSymbol,
        title: str,
        caption: str = "",
        *,
        accent: str = "#38BDF8",
        object_name: str = "chapter2Node",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setProperty("nodeActive", False)
        _allow_shrink(self)
        self._symbol = symbol
        self._accent = accent
        symbol.set_accent(accent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(4)
        icon_row = QHBoxLayout()
        icon_row.addStretch(1)
        icon_row.addWidget(symbol)
        icon_row.addStretch(1)
        layout.addLayout(icon_row)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setFont(make_font(11, 700))
        _allow_shrink(title_label)
        layout.addWidget(title_label)
        self._title_label = title_label

        if caption:
            caption_label = QLabel(caption)
            caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption_label.setWordWrap(True)
            caption_label.setFont(make_font(9, 400))
            caption_label.setProperty("role", "muted")
            _allow_shrink(caption_label)
            layout.addWidget(caption_label)

    def set_active(self, active: bool) -> None:
        self._symbol.set_active(active)
        self.setProperty("nodeActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self._title_label.setProperty("role", "cyan" if active else "muted")
        self._title_label.style().unpolish(self._title_label)
        self._title_label.style().polish(self._title_label)


class _Connector(QFrame):
    """A row (or column) of chevrons with one "hot" position at a time --
    a deterministic moving-signal effect without a continuous-redraw
    canvas.  ``set_active_index(-1)`` clears every chevron back to idle.
    """

    def __init__(self, *, count: int = 3, vertical: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter2Connector")
        layout_cls = QVBoxLayout if vertical else QHBoxLayout
        layout = layout_cls(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        glyph = "⌄" if vertical else "›"
        self._labels: list[QLabel] = []
        for _ in range(count):
            label = QLabel(glyph)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFont(make_font(13, 700))
            label.setProperty("connectorActive", False)
            layout.addWidget(label)
            self._labels.append(label)
        self._active_index = -1
        self._reduced_motion = False
        self._pulse_index = 0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._advance_pulse)

    def set_reduced_motion(self, reduced: bool) -> None:
        self._reduced_motion = reduced
        if reduced:
            self._pulse_timer.stop()
            self.set_active_index(-1)

    def set_active_index(self, index: int) -> None:
        if index == self._active_index:
            return
        self._active_index = index
        for position, label in enumerate(self._labels):
            active = position == index
            label.setProperty("connectorActive", active)
            label.style().unpolish(label)
            label.style().polish(label)

    def pulse_once(self, interval_ms: int = 90) -> None:
        """Animate one signal pulse travelling across the chevrons.

        A no-op under reduced motion: the chevrons stay visible (they are
        always drawn) but do not move -- per the reduced-motion contract,
        the pathway must still be understandable without animation.
        """

        if self._reduced_motion:
            return
        self._pulse_index = 0
        self._pulse_timer.start(interval_ms)

    def _advance_pulse(self) -> None:
        self.set_active_index(self._pulse_index)
        self._pulse_index += 1
        if self._pulse_index > len(self._labels):
            self._pulse_timer.stop()
            self.set_active_index(-1)

    def stop(self) -> None:
        self._pulse_timer.stop()


class _DemoButton(QPushButton):
    """A demo-only button: hover/press/focus feedback, and its
    ``clicked`` signal only ever drives the local animation state -- it
    is wired exclusively to schematic methods in this module, never to
    any MYELIN authority."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("chapter2DemoButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(make_font(10.5, 700, spacing=0.4))


class _MiniPopup(QFrame):
    """A miniature explanatory SINE popup -- visually in the same
    language as the real SINE popup, but a completely separate widget.
    Never imports or instantiates SINE.popup.SinePopupWindow."""

    button_clicked = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter2PopupDemo")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        self._badge = QLabel("SINE 1")
        self._badge.setObjectName("chapter2StageBadge")
        self._badge.setFont(make_font(9.5, 700, spacing=0.6))
        top_row.addWidget(self._badge)
        top_row.addStretch(1)
        demo_tag = QLabel("SCHEMATIC")
        demo_tag.setProperty("role", "muted")
        demo_tag.setFont(make_font(8.5, 700, spacing=0.8))
        top_row.addWidget(demo_tag)
        layout.addLayout(top_row)

        self._headline = QLabel("Cognitive Drift Detected")
        self._headline.setWordWrap(True)
        self._headline.setFont(make_font(12.5, 700))
        _allow_shrink(self._headline)
        layout.addWidget(self._headline)

        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setProperty("role", "muted")
        self._message.setFont(make_font(10, 400))
        _allow_shrink(self._message)
        layout.addWidget(self._message)

        self._button_row = QHBoxLayout()
        self._button_row.setSpacing(8)
        layout.addLayout(self._button_row)
        self._buttons: list[_DemoButton] = []

        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(180)
        self._glow_ticks = 0
        self._glow_timer.timeout.connect(self._advance_glow)
        self._reduced_motion = False

    def set_reduced_motion(self, reduced: bool) -> None:
        self._reduced_motion = reduced
        if reduced:
            self._glow_timer.stop()
            self.setProperty("popupGlow", False)
            self.style().unpolish(self)
            self.style().polish(self)

    def show_stage(self, stage_key: str) -> None:
        facts = SINE_STAGE_FACTS[stage_key]
        self._badge.setText(facts["label"])
        self._badge.setProperty("accent", facts["accent"])
        self._badge.style().unpolish(self._badge)
        self._badge.style().polish(self._badge)
        self._headline.setText(facts["headline"])
        self._message.setText(facts["message"])

        while self._button_row.count():
            item = self._button_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons = []
        for label in facts["buttons"]:
            button = _DemoButton(label)
            button.clicked.connect(lambda _checked=False, text=label: self.button_clicked.emit(text))
            self._button_row.addWidget(button)
            self._buttons.append(button)
        if not facts["buttons"]:
            no_buttons = QLabel("NO BUTTONS · AWAITING VERIFIED FOCUS RETURN")
            no_buttons.setProperty("role", "muted")
            no_buttons.setWordWrap(True)
            no_buttons.setFont(make_font(9, 700, spacing=0.4))
            _allow_shrink(no_buttons)
            self._button_row.addWidget(no_buttons)

        self.pulse()

    def set_buttons_enabled(self, enabled: bool) -> None:
        for button in self._buttons:
            button.setEnabled(enabled)

    def pulse(self) -> None:
        if self._reduced_motion:
            return
        self._glow_ticks = 0
        self.setProperty("popupGlow", True)
        self.style().unpolish(self)
        self.style().polish(self)
        if not self._glow_timer.isActive():
            self._glow_timer.start()

    def _advance_glow(self) -> None:
        self._glow_ticks += 1
        glow_on = self._glow_ticks % 2 == 1
        self.setProperty("popupGlow", glow_on)
        self.style().unpolish(self)
        self.style().polish(self)
        if self._glow_ticks >= 4:
            self._glow_timer.stop()
            self.setProperty("popupGlow", False)
            self.style().unpolish(self)
            self.style().polish(self)

    def stop(self) -> None:
        self._glow_timer.stop()


class _MineMiniPopup(QFrame):
    """A miniature explanatory MINE popup -- a completely separate widget.
    Never imports or instantiates MINE.popup.Mine1Popup/Mine2Popup.

    Handles MINE-1's two-choice card, its in-place duration-entry
    transform (the runtime turns the SAME window into a duration workflow
    rather than opening a second popup -- see MINE/popup.py), and both
    zero-button MINE-2 variants."""

    button_clicked = pyqtSignal(str)
    duration_submitted = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter2PopupDemo")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        self._badge = QLabel("MINE-1")
        self._badge.setObjectName("chapter2StageBadge")
        self._badge.setFont(make_font(9.5, 700, spacing=0.6))
        top_row.addWidget(self._badge)
        top_row.addStretch(1)
        demo_tag = QLabel("SCHEMATIC")
        demo_tag.setProperty("role", "muted")
        demo_tag.setFont(make_font(8.5, 700, spacing=0.8))
        top_row.addWidget(demo_tag)
        layout.addLayout(top_row)

        self._headline = QLabel("")
        self._headline.setWordWrap(True)
        self._headline.setFont(make_font(12.5, 700))
        _allow_shrink(self._headline)
        layout.addWidget(self._headline)

        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setProperty("role", "muted")
        self._message.setFont(make_font(10, 400))
        _allow_shrink(self._message)
        layout.addWidget(self._message)

        self._duration_widget = QWidget()
        duration_row = QHBoxLayout(self._duration_widget)
        duration_row.setContentsMargins(0, 0, 0, 0)
        duration_row.setSpacing(8)
        duration_caption = QLabel("MINUTES:")
        duration_caption.setProperty("role", "muted")
        duration_caption.setFont(make_font(9.5, 700, spacing=0.4))
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(5, 30)
        self._duration_spin.setValue(10)
        duration_row.addWidget(duration_caption)
        duration_row.addWidget(self._duration_spin)
        duration_row.addStretch(1)
        layout.addWidget(self._duration_widget)
        self._duration_widget.setVisible(False)

        self._button_row = QHBoxLayout()
        self._button_row.setSpacing(8)
        layout.addLayout(self._button_row)
        self._buttons: list[_DemoButton] = []

        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(180)
        self._glow_ticks = 0
        self._glow_target = 4
        self._glow_timer.timeout.connect(self._advance_glow)
        self._reduced_motion = False
        self._critical = False

    def set_reduced_motion(self, reduced: bool) -> None:
        self._reduced_motion = reduced
        if reduced:
            self._glow_timer.stop()
            self.setProperty("popupGlow", False)
            self.style().unpolish(self)
            self.style().polish(self)

    def show_stage(self, stage_key: str) -> None:
        facts = MINE_STAGE_FACTS[stage_key]
        self._badge.setText(facts["label"])
        self._badge.setProperty("accent", facts["accent"])
        self._badge.style().unpolish(self._badge)
        self._badge.style().polish(self._badge)
        self._headline.setText(facts["headline"])
        self._message.setText(facts["message"])
        self._duration_widget.setVisible(stage_key == "mine_1_duration")

        while self._button_row.count():
            item = self._button_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons = []
        for label in facts["buttons"]:
            button = _DemoButton(label)
            button.clicked.connect(lambda _checked=False, text=label: self._on_button(text))
            self._button_row.addWidget(button)
            self._buttons.append(button)
        if not facts["buttons"]:
            no_buttons = QLabel("NO BUTTONS · AWAITING VERIFIED FOCUS RETURN")
            no_buttons.setProperty("role", "muted")
            no_buttons.setWordWrap(True)
            no_buttons.setFont(make_font(9, 700, spacing=0.4))
            _allow_shrink(no_buttons)
            self._button_row.addWidget(no_buttons)

        self._critical = stage_key in ("mine_2a", "mine_2b")
        self.setProperty("popupVariant", "critical" if self._critical else "normal")
        self.style().unpolish(self)
        self.style().polish(self)
        self.pulse()

    def _on_button(self, label: str) -> None:
        if label == "SET IMPORTANT TIME":
            self.duration_submitted.emit(self._duration_spin.value())
        self.button_clicked.emit(label)

    def set_buttons_enabled(self, enabled: bool) -> None:
        for button in self._buttons:
            button.setEnabled(enabled)

    def pulse(self) -> None:
        if self._reduced_motion:
            return
        self._glow_ticks = 0
        self._glow_target = 6 if self._critical else 4
        self.setProperty("popupGlow", True)
        self.style().unpolish(self)
        self.style().polish(self)
        if not self._glow_timer.isActive():
            self._glow_timer.start()

    def _advance_glow(self) -> None:
        self._glow_ticks += 1
        glow_on = self._glow_ticks % 2 == 1
        self.setProperty("popupGlow", glow_on)
        self.style().unpolish(self)
        self.style().polish(self)
        if self._glow_ticks >= self._glow_target:
            self._glow_timer.stop()
            self.setProperty("popupGlow", False)
            self.style().unpolish(self)
            self.style().polish(self)

    def stop(self) -> None:
        self._glow_timer.stop()


class _CosineMiniPopup(QFrame):
    """A miniature explanatory COSINE popup -- a completely separate
    widget.  Never imports or instantiates any of
    COSINE.popup.Cosine{Intention,Duration,BreakAck,FinalCallback}Popup.

    Handles the intention gate's two-choice card, both duration-entry
    variants (SET A LIMIT / BREAK LENGTH -- one CosineDurationPopup class
    with two factual presentation variants in the real runtime), the
    break acknowledgement (with the chosen minutes displayed), and the
    zero-button final callback."""

    button_clicked = pyqtSignal(str)
    duration_submitted = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter2PopupDemo")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        self._badge = QLabel("INTENTION")
        self._badge.setObjectName("chapter2StageBadge")
        self._badge.setFont(make_font(9.5, 700, spacing=0.6))
        top_row.addWidget(self._badge)
        top_row.addStretch(1)
        demo_tag = QLabel("SCHEMATIC")
        demo_tag.setProperty("role", "muted")
        demo_tag.setFont(make_font(8.5, 700, spacing=0.8))
        top_row.addWidget(demo_tag)
        layout.addLayout(top_row)

        self._headline = QLabel("")
        self._headline.setWordWrap(True)
        self._headline.setFont(make_font(12.5, 700))
        _allow_shrink(self._headline)
        layout.addWidget(self._headline)

        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setProperty("role", "muted")
        self._message.setFont(make_font(10, 400))
        _allow_shrink(self._message)
        layout.addWidget(self._message)

        self._duration_display = QLabel("")
        self._duration_display.setFont(make_font(14, 700))
        self._duration_display.setProperty("role", "cyan")
        layout.addWidget(self._duration_display)
        self._duration_display.setVisible(False)

        self._context_label = QLabel("")
        self._context_label.setWordWrap(True)
        self._context_label.setProperty("role", "muted")
        self._context_label.setFont(make_font(9, 700, spacing=0.3))
        _allow_shrink(self._context_label)
        layout.addWidget(self._context_label)
        self._context_label.setVisible(False)

        self._duration_widget = QWidget()
        duration_row = QHBoxLayout(self._duration_widget)
        duration_row.setContentsMargins(0, 0, 0, 0)
        duration_row.setSpacing(8)
        duration_caption = QLabel("MINUTES:")
        duration_caption.setProperty("role", "muted")
        duration_caption.setFont(make_font(9.5, 700, spacing=0.4))
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(
            COSINE_TIMING_FACTS["break_minutes_min"], COSINE_TIMING_FACTS["break_minutes_max"]
        )
        self._duration_spin.setValue(30)
        duration_row.addWidget(duration_caption)
        duration_row.addWidget(self._duration_spin)
        duration_row.addStretch(1)
        layout.addWidget(self._duration_widget)
        self._duration_widget.setVisible(False)

        self._button_row = QHBoxLayout()
        self._button_row.setSpacing(8)
        layout.addLayout(self._button_row)
        self._buttons: list[_DemoButton] = []

        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(180)
        self._glow_ticks = 0
        self._glow_target = 4
        self._glow_timer.timeout.connect(self._advance_glow)
        self._reduced_motion = False
        self._critical = False

    def set_reduced_motion(self, reduced: bool) -> None:
        self._reduced_motion = reduced
        if reduced:
            self._glow_timer.stop()
            self.setProperty("popupGlow", False)
            self.style().unpolish(self)
            self.style().polish(self)

    def show_stage(self, stage_key: str) -> None:
        facts = COSINE_POPUP_FACTS[stage_key]
        self._badge.setText(facts["label"])
        self._badge.setProperty("accent", facts["accent"])
        self._badge.style().unpolish(self._badge)
        self._badge.style().polish(self._badge)
        self._headline.setText(facts["headline"])
        self._message.setText(facts["message"])

        self._context_label.setText(facts.get("context", ""))
        self._context_label.setVisible(bool(facts.get("context")))
        self._duration_widget.setVisible(stage_key in ("set_a_limit", "break_length"))
        self._duration_display.setVisible(False)

        while self._button_row.count():
            item = self._button_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons = []
        for label in facts["buttons"]:
            button = _DemoButton(label)
            button.clicked.connect(lambda _checked=False, text=label: self._on_button(text))
            self._button_row.addWidget(button)
            self._buttons.append(button)
        if not facts["buttons"]:
            no_buttons = QLabel("FINAL CALLBACK · NO ACTION BUTTONS")
            no_buttons.setProperty("role", "muted")
            no_buttons.setWordWrap(True)
            no_buttons.setFont(make_font(9, 700, spacing=0.4))
            _allow_shrink(no_buttons)
            self._button_row.addWidget(no_buttons)

        self._critical = stage_key == "final_callback"
        self.setProperty("popupVariant", "critical" if self._critical else "normal")
        self.style().unpolish(self)
        self.style().polish(self)
        self.pulse()

    def show_break_set(self, minutes: int) -> None:
        self.show_stage("break_set")
        self._duration_display.setText(f"{minutes} MINS")
        self._duration_display.setVisible(True)

    def _on_button(self, label: str) -> None:
        if label in ("START WATCHING", "SET TIME"):
            self.duration_submitted.emit(self._duration_spin.value())
        self.button_clicked.emit(label)

    def set_buttons_enabled(self, enabled: bool) -> None:
        for button in self._buttons:
            button.setEnabled(enabled)

    def pulse(self) -> None:
        if self._reduced_motion:
            return
        self._glow_ticks = 0
        self._glow_target = 6 if self._critical else 4
        self.setProperty("popupGlow", True)
        self.style().unpolish(self)
        self.style().polish(self)
        if not self._glow_timer.isActive():
            self._glow_timer.start()

    def _advance_glow(self) -> None:
        self._glow_ticks += 1
        glow_on = self._glow_ticks % 2 == 1
        self.setProperty("popupGlow", glow_on)
        self.style().unpolish(self)
        self.style().polish(self)
        if self._glow_ticks >= self._glow_target:
            self._glow_timer.stop()
            self.setProperty("popupGlow", False)
            self.style().unpolish(self)
            self.style().polish(self)

    def stop(self) -> None:
        self._glow_timer.stop()


class _CosecantMiniPopup(QFrame):
    """A miniature explanatory COSECANT popup -- a completely separate
    widget.  Never imports or instantiates
    COSECANT_STUDY_MODE.view.ContinuityPopup.

    Handles the two reminder stages (BREAK COMPLETE / BREAK ALREADY OVER,
    each with a RETURN TO STUDY intent-only button), the zero-button
    FINAL LOCK, and the zero-button RETURN DETECTED verification stage.
    The real popup hides its button whenever ``snapshot.final_locked`` is
    true (FINAL_LOCK itself, and any RETURN_CONFIRMING that originated
    from FINAL_LOCK) -- this class mirrors that invariant simply by
    having zero buttons in both of those COSECANT_POPUP_FACTS entries;
    it never fabricates one."""

    button_clicked = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter2PopupDemo")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        self._badge = QLabel("BREAK COMPLETE")
        self._badge.setObjectName("chapter2StageBadge")
        self._badge.setFont(make_font(9.5, 700, spacing=0.6))
        top_row.addWidget(self._badge)
        top_row.addStretch(1)
        demo_tag = QLabel("SCHEMATIC")
        demo_tag.setProperty("role", "muted")
        demo_tag.setFont(make_font(8.5, 700, spacing=0.8))
        top_row.addWidget(demo_tag)
        layout.addLayout(top_row)

        self._headline = QLabel("")
        self._headline.setWordWrap(True)
        self._headline.setFont(make_font(12.5, 700))
        _allow_shrink(self._headline)
        layout.addWidget(self._headline)

        self._message = QLabel("")
        self._message.setWordWrap(True)
        self._message.setProperty("role", "muted")
        self._message.setFont(make_font(10, 400))
        _allow_shrink(self._message)
        layout.addWidget(self._message)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setProperty("role", "cyan")
        self._status_label.setFont(make_font(9, 700, spacing=0.3))
        _allow_shrink(self._status_label)
        layout.addWidget(self._status_label)

        self._countdown_label = QLabel("")
        self._countdown_label.setFont(make_font(18, 700))
        self._countdown_label.setProperty("role", "cyan")
        self._countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._countdown_label)
        self._countdown_label.setVisible(False)

        self._button_row = QHBoxLayout()
        self._button_row.setSpacing(8)
        layout.addLayout(self._button_row)
        self._buttons: list[_DemoButton] = []

        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(180)
        self._glow_ticks = 0
        self._glow_target = 4
        self._glow_timer.timeout.connect(self._advance_glow)
        self._reduced_motion = False
        self._critical = False

    def set_reduced_motion(self, reduced: bool) -> None:
        self._reduced_motion = reduced
        if reduced:
            self._glow_timer.stop()
            self.setProperty("popupGlow", False)
            self.style().unpolish(self)
            self.style().polish(self)

    def show_stage(self, stage_key: str) -> None:
        facts = COSECANT_POPUP_FACTS[stage_key]
        self._badge.setText(facts["label"])
        self._badge.setProperty("accent", facts["accent"])
        self._badge.style().unpolish(self._badge)
        self._badge.style().polish(self._badge)
        self._headline.setText(facts["headline"])
        self._message.setText(facts["message"])
        self._status_label.setText(facts["status"])
        self._countdown_label.setVisible(False)
        self._countdown_label.setText("")

        while self._button_row.count():
            item = self._button_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons = []
        for label in facts["buttons"]:
            button = _DemoButton(label)
            button.clicked.connect(lambda _checked=False, text=label: self.button_clicked.emit(text))
            self._button_row.addWidget(button)
            self._buttons.append(button)
        if not facts["buttons"] and stage_key == "final_lock":
            no_buttons = QLabel("NO BUTTONS · EXACT STUDY RETURN REQUIRED")
            no_buttons.setProperty("role", "muted")
            no_buttons.setWordWrap(True)
            no_buttons.setFont(make_font(9, 700, spacing=0.4))
            _allow_shrink(no_buttons)
            self._button_row.addWidget(no_buttons)

        self._critical = stage_key == "final_lock"
        self.setProperty("popupVariant", "critical" if self._critical else "normal")
        self.style().unpolish(self)
        self.style().polish(self)
        self.pulse()

    def set_countdown(self, text: str) -> None:
        self._countdown_label.setText(text)
        self._countdown_label.setVisible(bool(text))

    def set_buttons_enabled(self, enabled: bool) -> None:
        for button in self._buttons:
            button.setEnabled(enabled)

    def pulse(self) -> None:
        if self._reduced_motion:
            return
        self._glow_ticks = 0
        self._glow_target = 6 if self._critical else 4
        self.setProperty("popupGlow", True)
        self.style().unpolish(self)
        self.style().polish(self)
        if not self._glow_timer.isActive():
            self._glow_timer.start()

    def _advance_glow(self) -> None:
        self._glow_ticks += 1
        glow_on = self._glow_ticks % 2 == 1
        self.setProperty("popupGlow", glow_on)
        self.style().unpolish(self)
        self.style().polish(self)
        if self._glow_ticks >= self._glow_target:
            self._glow_timer.stop()
            self.setProperty("popupGlow", False)
            self.style().unpolish(self)
            self.style().polish(self)

    def stop(self) -> None:
        self._glow_timer.stop()


def _timing_label(text: str, tooltip: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("chapter2TimingLabel")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setFont(make_font(9.5, 700))
    label.setToolTip(tooltip)
    return label


def _small_caption(text: str, *, role: str = "muted", bold: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("role", role)
    label.setFont(make_font(9.5, 700 if bold else 400))
    _allow_shrink(label)
    return label


def _info_strip(rows: tuple[tuple[str, str], ...]) -> QFrame:
    """The bottom ROLE / INPUT / ACTION / OUTPUT / CONNECTED SYSTEM strip."""

    frame = QFrame()
    frame.setObjectName("chapter2InfoStrip")
    _allow_shrink(frame)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(5)
    for heading, body in rows:
        row = QHBoxLayout()
        row.setSpacing(8)
        heading_label = QLabel(heading)
        heading_label.setProperty("role", "cyan")
        heading_label.setFont(make_font(9.5, 700, spacing=0.6))
        heading_label.setFixedWidth(150)
        row.addWidget(heading_label)
        body_label = QLabel(body)
        body_label.setWordWrap(True)
        body_label.setFont(make_font(10, 400))
        _allow_shrink(body_label)
        row.addWidget(body_label, 1)
        layout.addLayout(row)
    return frame


class SineSchematic(QWidget):
    """The Chapter 2 Phase 1 living schematic for SINE.

    Presentation-only: every click here only changes local widget state.
    Nothing in this class calls SINE, MIRL, Normal Break, or any other
    MYELIN authority, and it runs identically whether or not a MYELIN
    session is active.
    """

    content_size_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reduced_motion = False
        self._is_paused = False
        self._pending_steps: list[tuple[int, "Callable[[], None]"]] = []
        self._last_sequence: list[tuple[int, "Callable[[], None]"]] = []
        self._intro_played = False

        self._step_timer = QTimer(self)
        self._step_timer.setSingleShot(True)
        self._step_timer.timeout.connect(self._advance_sequence)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(14)

        root.addWidget(self._build_banner())
        root.addWidget(self._build_observation_band())
        self._popup = _MiniPopup()
        self._popup.button_clicked.connect(self._on_demo_button)
        root.addWidget(self._popup)
        root.addWidget(self._build_branch_row())
        root.addWidget(self._build_escalation_band())
        root.addWidget(
            _info_strip(
                (
                    ("ROLE", "Escalating intervention authority."),
                    ("INPUT", "Durable eligible trigger evidence."),
                    ("ACTION", "Blue → Amber → Protected Red."),
                    ("OUTPUT", "Intervention facts / response intent."),
                    ("CONNECTED SYSTEM", "MIRL recovery verification · Normal Break branch."),
                )
            )
        )
        root.addWidget(
            _small_caption(
                "General SINE pathway shown. Study Mode uses its own "
                "study-specific presentation while preserving SINE "
                "authority.",
            )
        )
        root.addWidget(self._build_demo_controls())
        # Same discipline as Chapter 1's vertical-geometry fix: without a
        # trailing stretch, the outer _ChapterStack's forced page height
        # would distribute any rounding surplus into these cards instead
        # of leaving it here.
        root.addStretch(1)

        self._popup.show_stage("sine_1")
        self._popup.set_buttons_enabled(False)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_banner(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        badge_row = QHBoxLayout()
        badge = QLabel("SCHEMATIC DEMONSTRATION · NOT LIVE TELEMETRY")
        badge.setObjectName("chapter2DemoBadge")
        badge.setWordWrap(True)
        badge.setFont(make_font(9.5, 700, spacing=0.6))
        # Deliberately NOT _allow_shrink here: this label sits beside an
        # addStretch(1) sibling, and an Ignored-policy widget loses that
        # space race entirely (observed: it was allocated zero width).
        # Its own text is short enough not to need shrink protection.
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        layout.addLayout(badge_row)
        layout.addWidget(
            _small_caption(
                "Select an organ to explore how its signal pathway moves "
                "through MYELIN. DEMO SPEED — TIMING NOT TO SCALE.",
            )
        )
        return frame

    def _build_observation_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        self._user_node = _Node(_HumanSymbol(), "USER", "Works on an intended task.", accent="#38BDF8")
        self._monitor_node = _Node(_MonitorSymbol(), "MONITOR", "Observes certified software context.", accent="#38BDF8")
        self._evidence_node = _Node(_EvidenceSymbol(), "ELIGIBLE OFF-TASK EVIDENCE", "Durable candidate admitted.", accent="#38BDF8")

        self._sine_symbol = _SineSymbol()
        self._sine_node = _Node(self._sine_symbol, "SINE", "Blue · gentle intervention.", accent="#3DDCFF", object_name="chapter2SineNode")

        self._conn_user_monitor = _Connector()
        self._conn_monitor_evidence = _Connector()
        self._conn_evidence_sine = _Connector()

        for widget in (
            self._user_node,
            self._conn_user_monitor,
            self._monitor_node,
            self._conn_monitor_evidence,
            self._evidence_node,
            self._conn_evidence_sine,
            self._sine_node,
        ):
            layout.addWidget(widget, 1 if isinstance(widget, _Node) else 0)

        return frame

    def _build_branch_row(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        outer = QHBoxLayout(frame)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(18)

        # Return / MIRL column
        return_column = QVBoxLayout()
        return_column.setSpacing(6)
        return_row = QHBoxLayout()
        return_row.setSpacing(6)
        self._return_intent_node = _Node(_EvidenceSymbol(), "RETURN INTENT", "Recorded when I'M BACK is pressed.", accent="#38BDF8")
        self._conn_return_mirl = _Connector()
        self._mirl_node = _Node(_CheckSymbol(), "MIRL", "Verifies recovery.", accent="#39D98A")
        return_row.addWidget(self._return_intent_node, 1)
        return_row.addWidget(self._conn_return_mirl)
        return_row.addWidget(self._mirl_node, 1)
        return_column.addLayout(return_row)
        return_column.addWidget(
            _small_caption("Button press records intent. MIRL verifies recovery.")
        )
        self._resolved_label = _small_caption("", role="cyan", bold=True)
        return_column.addWidget(self._resolved_label)
        outer.addLayout(return_column, 1)

        # Normal Break column
        break_column = QVBoxLayout()
        break_column.setSpacing(6)
        break_row = QHBoxLayout()
        break_row.setSpacing(6)
        self._break_node = _Node(_PauseSymbol(), "NORMAL BREAK", "Break authority decides the pathway.", accent="#94A3B8")
        self._conn_break_gate = _Connector()
        self._break_gate_node = _Node(_CheckSymbol(), "WELCOME BACK", "Not a SINE stage.", accent="#39D98A")
        break_row.addWidget(self._break_node, 1)
        break_row.addWidget(self._conn_break_gate)
        break_row.addWidget(self._break_gate_node, 1)
        break_column.addLayout(break_row)
        break_column.addWidget(
            _small_caption(
                "Re-arms the ordinary SINE-1 → SINE-2 interval after "
                "acknowledgement. Carries SineStage.NONE."
            )
        )
        outer.addLayout(break_column, 1)

        return frame

    def _build_escalation_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading_row = QHBoxLayout()
        heading = QLabel("ESCALATION PATH")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self._escalation_button = _DemoButton("SHOW ESCALATION")
        self._escalation_button.clicked.connect(self._on_show_escalation)
        heading_row.addWidget(self._escalation_button)
        layout.addLayout(heading_row)

        row = QHBoxLayout()
        row.setSpacing(6)

        sine1_symbol = _SineSymbol()
        sine1_symbol.set_lit_stage("sine_1")
        self._sine1_mini_node = _Node(sine1_symbol, "SINE 1", "45s display.", accent="#3DDCFF")

        sine2_symbol = _SineSymbol()
        sine2_symbol.set_lit_stage("sine_2")
        self._sine2_node = _Node(sine2_symbol, "SINE 2", "60s display.", accent="#F5A623")

        sine3_symbol = _SineSymbol()
        sine3_symbol.set_lit_stage("sine_3")
        self._sine3_node = _Node(sine3_symbol, "SINE 3 · PROTECTED", "No buttons.", accent="#FF4D6D")

        conn_a = _Connector()
        timing_a = _timing_label(f"{SINE_TIMING_FACTS['stage_1_to_2_baseline']} × F", SINE_TIMING_FACTS["f_tooltip"])
        conn_b = _Connector()
        timing_b = _timing_label(f"{SINE_TIMING_FACTS['stage_2_to_3_baseline']} × F", SINE_TIMING_FACTS["f_tooltip"])
        self._conn_escalation_mirl = _Connector()
        self._mirl_verified_node = _Node(_CheckSymbol(), "VERIFIED RECOVERY", "Recovery authority = MIRL.", accent="#39D98A")

        for widget in (
            self._sine1_mini_node,
            conn_a,
            timing_a,
            self._sine2_node,
            conn_b,
            timing_b,
            self._sine3_node,
            self._conn_escalation_mirl,
            self._mirl_verified_node,
        ):
            row.addWidget(widget, 1 if isinstance(widget, _Node) else 0)
        layout.addLayout(row)

        self._escalation_connectors = (conn_a, conn_b, self._conn_escalation_mirl)
        return frame

    def _build_demo_controls(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        label = QLabel("DEMO CONTROLS")
        label.setProperty("role", "cyan")
        label.setFont(make_font(9.5, 700, spacing=0.8))
        layout.addWidget(label)
        layout.addStretch(1)

        self._play_button = _DemoButton("PLAY FLOW")
        self._pause_button = _DemoButton("PAUSE")
        self._replay_button = _DemoButton("REPLAY")
        self._reduced_motion_button = _DemoButton("REDUCED MOTION")
        self._reduced_motion_button.setCheckable(True)

        self._play_button.clicked.connect(self._on_play)
        self._pause_button.clicked.connect(self.pause)
        self._replay_button.clicked.connect(self.replay)
        self._reduced_motion_button.toggled.connect(self._on_reduced_motion_toggled)

        for button in (self._play_button, self._pause_button, self._replay_button, self._reduced_motion_button):
            layout.addWidget(button)

        return frame

    # ------------------------------------------------------------------
    # Animation engine -- a plain sequential step queue, not a canvas.
    # Every step is (delay_ms, callable).  Pausing stops the timer and
    # keeps the remaining steps; resuming/PLAY continues them; REPLAY
    # restarts the last sequence that was run.
    # ------------------------------------------------------------------

    def _run_sequence(self, steps, *, remember: bool = True) -> None:
        self._step_timer.stop()
        if remember:
            self._last_sequence = list(steps)
        self._pending_steps = list(steps)
        self._is_paused = False
        self._advance_sequence()

    def _advance_sequence(self) -> None:
        if self._is_paused or not self._pending_steps:
            return
        delay, action = self._pending_steps.pop(0)
        action()
        if self._pending_steps:
            self._step_timer.start(0 if self._reduced_motion else delay)

    def pause(self) -> None:
        self._is_paused = True
        self._step_timer.stop()

    def _on_play(self) -> None:
        if self._is_paused and self._pending_steps:
            self._is_paused = False
            self._advance_sequence()
        elif not self._pending_steps:
            self._run_sequence(self._intro_steps())

    def replay(self) -> None:
        self._run_sequence(self._last_sequence or self._intro_steps(), remember=False)

    def _on_reduced_motion_toggled(self, checked: bool) -> None:
        self._reduced_motion = checked
        for connector in (
            self._conn_user_monitor,
            self._conn_monitor_evidence,
            self._conn_evidence_sine,
            self._conn_return_mirl,
            self._conn_break_gate,
            *self._escalation_connectors,
        ):
            connector.set_reduced_motion(checked)
        self._popup.set_reduced_motion(checked)

    def _reset_visual_state(self) -> None:
        for node in (
            self._user_node,
            self._monitor_node,
            self._evidence_node,
            self._sine_node,
            self._return_intent_node,
            self._mirl_node,
            self._break_node,
            self._break_gate_node,
            self._mirl_verified_node,
        ):
            node.set_active(False)
        self._sine_symbol.set_lit_stage(None)
        self._resolved_label.setText("")
        self._popup.show_stage("sine_1")
        self._popup.set_buttons_enabled(False)

    def _intro_steps(self):
        return [
            (_STEP_MS, lambda: self._user_node.set_active(True)),
            (_STEP_MS, self._conn_user_monitor.pulse_once),
            (_STEP_MS, lambda: self._monitor_node.set_active(True)),
            (_STEP_MS, self._conn_monitor_evidence.pulse_once),
            (_STEP_MS, lambda: self._evidence_node.set_active(True)),
            (_STEP_MS, self._conn_evidence_sine.pulse_once),
            (_STEP_MS, lambda: (self._sine_node.set_active(True), self._sine_symbol.set_lit_stage("sine_1"))),
            (_STEP_MS, lambda: self._popup.show_stage("sine_1")),
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(True)),
        ]

    def _return_demo_steps(self):
        return [
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(False)),
            (_STEP_MS, lambda: self._return_intent_node.set_active(True)),
            (_STEP_MS, self._conn_return_mirl.pulse_once),
            (_STEP_MS, lambda: self._mirl_node.set_active(True)),
            (_STEP_MS, lambda: self._resolved_label.setText("VERIFIED RETURN · RESOLVED")),
        ]

    def _break_demo_steps(self):
        return [
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(False)),
            (_STEP_MS, lambda: self._break_node.set_active(True)),
            (_STEP_MS, self._conn_break_gate.pulse_once),
            (_STEP_MS, lambda: self._break_gate_node.set_active(True)),
        ]

    def _escalation_demo_steps(self):
        conn_a, conn_b, conn_mirl = self._escalation_connectors
        return [
            (_STEP_MS, lambda: (self._sine1_mini_node.set_active(True))),
            (_STEP_MS, conn_a.pulse_once),
            (_STEP_MS, lambda: self._sine2_node.set_active(True)),
            (_STEP_MS, conn_b.pulse_once),
            (_STEP_MS, lambda: self._sine3_node.set_active(True)),
            (_STEP_MS, conn_mirl.pulse_once),
            (_STEP_MS, lambda: self._mirl_verified_node.set_active(True)),
            (_STEP_MS, lambda: self._resolved_label.setText("VERIFIED RETURN · RESOLVED")),
        ]

    def _on_demo_button(self, label: str) -> None:
        if label in ("I'M BACK", "I'M BACK NOW"):
            self._run_sequence(self._return_demo_steps())
        elif label == "NEED A BREAK":
            self._run_sequence(self._break_demo_steps())

    def _on_show_escalation(self) -> None:
        self._run_sequence(self._escalation_demo_steps())

    # ------------------------------------------------------------------
    # Qt lifecycle: never animate while hidden.
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().showEvent(event)
        if not self._intro_played:
            self._intro_played = True
            self._run_sequence(self._intro_steps())

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().hideEvent(event)
        self._step_timer.stop()
        self._is_paused = False
        self._pending_steps = []
        for connector in (
            self._conn_user_monitor,
            self._conn_monitor_evidence,
            self._conn_evidence_sine,
            self._conn_return_mirl,
            self._conn_break_gate,
            *self._escalation_connectors,
        ):
            connector.stop()
        self._popup.stop()


class MineSchematic(QWidget):
    """The Chapter 2 Phase 2 living schematic for MINE.

    Presentation-only, same discipline as ``SineSchematic``: every click
    here only changes local widget state.  Nothing in this class calls
    MINE, MIRL, Study Mode, or any other MYELIN authority, and it runs
    identically whether or not a MYELIN session is active.

    Architectural boundary this class exists to teach correctly: MINE
    owns its own return-confirmation sequence (RETURN CONFIRMING ->
    RETURN VERIFYING -> STABILITY CONFIRMING) -- unlike SINE, it is never
    routed through a MIRL node.  This class has no MIRL reference at all.
    """

    content_size_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reduced_motion = False
        self._is_paused = False
        self._pending_steps: list[tuple[int, "Callable[[], None]"]] = []
        self._last_sequence: list[tuple[int, "Callable[[], None]"]] = []
        self._intro_played = False

        self._step_timer = QTimer(self)
        self._step_timer.setSingleShot(True)
        self._step_timer.timeout.connect(self._advance_sequence)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(14)

        root.addWidget(self._build_banner())
        root.addWidget(self._build_entry_band())
        self._popup = _MineMiniPopup()
        self._popup.button_clicked.connect(self._on_demo_button)
        self._popup.duration_submitted.connect(self._on_duration_submitted)
        root.addWidget(self._popup)
        root.addWidget(self._build_branch_row())
        root.addWidget(self._build_recovery_band())
        root.addWidget(self._build_boundary_notes())
        root.addWidget(
            _info_strip(
                (
                    ("ROLE", "Messaging-specific intervention authority."),
                    ("INPUT", "Certified messaging context from MONITOR."),
                    ("FIRST GATE", f"{MINE_TIMING_FACTS['initial_gate']} supported messaging time."),
                    ("BRANCH A", "I WILL COME BACK → new 13:15 messaging window."),
                    ("BRANCH B", "IT'S IMPORTANT → 5–30 min allowance."),
                    ("FINAL CALLBACK", "MINE-2A / MINE-2B → no buttons."),
                    (
                        "RETURN",
                        f"{MINE_TIMING_FACTS['final_callback_hide_seconds']}s + "
                        f"{MINE_TIMING_FACTS['return_verification_seconds']}s + "
                        f"{MINE_TIMING_FACTS['closure_confirmation_seconds']}s confirmation sequence.",
                    ),
                )
            )
        )
        root.addWidget(
            _info_strip(
                (
                    ("INITIAL GATE", f"{MINE_TIMING_FACTS['initial_gate']} supported messaging."),
                    ("RETURN-INTENT WINDOW", f"{MINE_TIMING_FACTS['return_intent_window']} supported messaging."),
                    (
                        "IMPORTANT ALLOWANCE",
                        f"{MINE_TIMING_FACTS['important_minutes_min']}–"
                        f"{MINE_TIMING_FACTS['important_minutes_max']} min, chosen by user.",
                    ),
                    ("FINAL VISUAL", f"{MINE_TIMING_FACTS['final_callback_hide_seconds']} s."),
                    ("RETURN VERIFY", f"{MINE_TIMING_FACTS['return_verification_seconds']} s."),
                    ("CLOSURE STABILITY", f"{MINE_TIMING_FACTS['closure_confirmation_seconds']} s."),
                )
            )
        )
        root.addWidget(_small_caption("DEMO TIMING NOT TO SCALE.", bold=True))
        root.addWidget(self._build_demo_controls())
        root.addStretch(1)

        self._popup.show_stage("mine_1")
        self._popup.set_buttons_enabled(False)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_banner(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        badge_row = QHBoxLayout()
        badge = QLabel("SCHEMATIC DEMONSTRATION · NOT LIVE TELEMETRY")
        badge.setObjectName("chapter2DemoBadge")
        badge.setWordWrap(True)
        badge.setFont(make_font(9.5, 700, spacing=0.6))
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        layout.addLayout(badge_row)
        layout.addWidget(
            _small_caption(
                "MINE receives certified messaging context from MONITOR. "
                "It does not identify messaging applications independently.",
            )
        )
        return frame

    def _build_entry_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        self._user_node = _Node(_HumanSymbol(), "USER", "Works on an intended task.", accent="#38BDF8")
        self._monitor_node = _Node(_MonitorSymbol(), "MONITOR", "Observes certified software context.", accent="#38BDF8")
        self._messaging_node = _Node(
            _MessagingSymbol(), "CERTIFIED MESSAGING", "MONITOR routes messaging context to MINE.", accent="#38BDF8"
        )
        self._gate_node = _Node(
            _TimerSymbol(), MINE_TIMING_FACTS["initial_gate"], "Supported messaging time.", accent="#F5A623"
        )

        self._mine_symbol = _MineSymbol()
        self._mine_node = _Node(
            self._mine_symbol,
            "MINE",
            "Messaging-specific intervention.",
            accent="#B7A1FF",
            object_name="chapter2MineNode",
        )

        self._conn_user_monitor = _Connector()
        self._conn_monitor_messaging = _Connector()
        self._conn_messaging_gate = _Connector()
        self._conn_gate_mine = _Connector()

        for widget in (
            self._user_node,
            self._conn_user_monitor,
            self._monitor_node,
            self._conn_monitor_messaging,
            self._messaging_node,
            self._conn_messaging_gate,
            self._gate_node,
            self._conn_gate_mine,
            self._mine_node,
        ):
            layout.addWidget(widget, 1 if isinstance(widget, _Node) else 0)

        return frame

    def _build_branch_row(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        outer = QHBoxLayout(frame)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(14)
        outer.addWidget(self._build_branch_a(), 1)
        outer.addWidget(self._build_branch_b(), 1)
        return frame

    def _build_branch_a(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading = QLabel("BRANCH A · I WILL COME BACK")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        heading.setWordWrap(True)
        _allow_shrink(heading)
        layout.addWidget(heading)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._return_intent_node = _Node(
            _EvidenceSymbol(), "RETURN INTENT", "Recorded when I WILL COME BACK is pressed.", accent="#F5A623"
        )
        self._conn_return_clock = _Connector()
        self._clock_node = _Node(
            _TimerSymbol(), MINE_TIMING_FACTS["return_intent_window"], "New qualifying messaging window.", accent="#F5A623"
        )
        for widget in (self._return_intent_node, self._conn_return_clock, self._clock_node):
            row.addWidget(widget, 1 if isinstance(widget, _Node) else 0)
        layout.addLayout(row)

        layout.addWidget(_small_caption("NEW CLOCK STARTS HERE — starts after MINE-1, not at original messaging entry.", bold=True))
        layout.addWidget(
            _small_caption(
                f"Continuous example: {MINE_TIMING_FACTS['initial_gate']} + "
                f"{MINE_TIMING_FACTS['return_intent_window']} = {MINE_TIMING_FACTS['continuous_total']}",
                role="cyan",
                bold=True,
            )
        )

        neutral_button_row = QHBoxLayout()
        self._neutral_demo_button = _DemoButton("SHOW NEUTRAL DETOUR")
        self._neutral_demo_button.clicked.connect(lambda: self._run_sequence(self._neutral_detour_steps()))
        neutral_button_row.addWidget(self._neutral_demo_button)
        neutral_button_row.addStretch(1)
        layout.addLayout(neutral_button_row)

        neutral_row = QHBoxLayout()
        neutral_row.setSpacing(6)
        self._neutral_node = _Node(_NeutralSymbol(), "NEUTRAL", "Unsupported context.", accent="#94A3B8")
        self._conn_neutral = _Connector()
        neutral_row.addWidget(self._neutral_node, 1)
        neutral_row.addWidget(self._conn_neutral)
        neutral_row.addWidget(_small_caption(MINE_BRANCH_FACTS["neutral_pause_note"], role="cyan", bold=True), 1)
        layout.addLayout(neutral_row)

        platform_button_row = QHBoxLayout()
        self._platform_demo_button = _DemoButton("SHOW PLATFORM SWITCH")
        self._platform_demo_button.clicked.connect(lambda: self._run_sequence(self._platform_switch_steps()))
        platform_button_row.addWidget(self._platform_demo_button)
        platform_button_row.addStretch(1)
        layout.addLayout(platform_button_row)

        platform_row = QHBoxLayout()
        platform_row.setSpacing(6)
        self._platform_chips: list[QLabel] = []
        for label_text in ("PLATFORM A", "PLATFORM B", "PLATFORM C"):
            chip = _small_caption(label_text, role="muted", bold=True)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            platform_row.addWidget(chip, 1)
            self._platform_chips.append(chip)
        layout.addLayout(platform_row)
        layout.addWidget(_small_caption(MINE_BRANCH_FACTS["platform_switch_note"]))

        early_row = QHBoxLayout()
        self._early_return_a_button = _DemoButton("EARLY FOCUS RETURN")
        self._early_return_a_button.clicked.connect(lambda: self._run_sequence(self._early_return_a_steps()))
        early_row.addWidget(self._early_return_a_button)
        early_row.addStretch(1)
        layout.addLayout(early_row)
        layout.addWidget(_small_caption(MINE_BRANCH_FACTS["early_return_note"]))

        conn_row = QHBoxLayout()
        self._conn_clock_mine2a = _Connector()
        self._mine2a_node = _Node(_EvidenceSymbol(), "MINE-2A", "FINAL CALLBACK · NO BUTTONS", accent="#FF4D6D")
        conn_row.addWidget(self._conn_clock_mine2a)
        conn_row.addWidget(self._mine2a_node, 1)
        layout.addLayout(conn_row)

        self._branch_a_connectors = (self._conn_return_clock, self._conn_neutral, self._conn_clock_mine2a)
        return frame

    def _build_branch_b(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading = QLabel("BRANCH B · IT'S IMPORTANT")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        heading.setWordWrap(True)
        _allow_shrink(heading)
        layout.addWidget(heading)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._duration_choice_node = _Node(
            _TimerSymbol(),
            f"{MINE_TIMING_FACTS['important_minutes_min']}–{MINE_TIMING_FACTS['important_minutes_max']} MIN",
            "Whole-minute duration entry.",
            accent="#F5A623",
        )
        self._conn_duration_allowance = _Connector()
        self._allowance_node = _Node(_TimerSymbol(), "IMPORTANT ALLOWANCE", "Chosen by user.", accent="#F5A623")
        for widget in (self._duration_choice_node, self._conn_duration_allowance, self._allowance_node):
            row.addWidget(widget, 1 if isinstance(widget, _Node) else 0)
        layout.addLayout(row)

        self._allowance_caption = _small_caption("", role="cyan", bold=True)
        layout.addWidget(self._allowance_caption)
        layout.addWidget(
            _small_caption(
                "Runs on MINE's effective clock. Global Pause freezes it — "
                "ordinary neutral context does not."
            )
        )

        early_row = QHBoxLayout()
        self._early_return_b_button = _DemoButton("EARLY FOCUS RETURN")
        self._early_return_b_button.clicked.connect(lambda: self._run_sequence(self._early_return_b_steps()))
        early_row.addWidget(self._early_return_b_button)
        early_row.addStretch(1)
        layout.addLayout(early_row)
        layout.addWidget(
            _small_caption("Returning early can close MINE without waiting for allowance expiry.")
        )

        conn_row = QHBoxLayout()
        self._conn_allowance_mine2b = _Connector()
        self._mine2b_node = _Node(_EvidenceSymbol(), "MINE-2B", "FINAL CALLBACK · NO BUTTONS", accent="#FF4D6D")
        conn_row.addWidget(self._conn_allowance_mine2b)
        conn_row.addWidget(self._mine2b_node, 1)
        layout.addLayout(conn_row)

        self._branch_b_connectors = (self._conn_duration_allowance, self._conn_allowance_mine2b)
        return frame

    def _build_recovery_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading_row = QHBoxLayout()
        heading = QLabel("MINE'S OWN RECOVERY SEQUENCE")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        heading.setWordWrap(True)
        _allow_shrink(heading)
        heading_row.addWidget(heading, 1)
        self._relapse_button = _DemoButton("SHOW RELAPSE")
        self._relapse_button.clicked.connect(lambda: self._run_sequence(self._relapse_steps()))
        heading_row.addWidget(self._relapse_button)
        layout.addLayout(heading_row)
        layout.addWidget(_small_caption(MINE_BRANCH_FACTS["recovery_owner_note"], role="cyan", bold=True))

        row = QHBoxLayout()
        row.setSpacing(6)
        self._focus_observed_node = _Node(_CheckSymbol(), "FOCUS OBSERVED", "", accent="#39D98A")
        conn1 = _Connector()
        self._confirming_node = _Node(
            _TimerSymbol(), "RETURN CONFIRMING", f"{MINE_TIMING_FACTS['final_callback_hide_seconds']} s", accent="#39D98A"
        )
        conn2 = _Connector()
        self._verifying_node = _Node(
            _TimerSymbol(), "RETURN VERIFYING", f"{MINE_TIMING_FACTS['return_verification_seconds']} s", accent="#39D98A"
        )
        conn3 = _Connector()
        self._stability_node = _Node(
            _TimerSymbol(), "STABILITY CONFIRMING", f"{MINE_TIMING_FACTS['closure_confirmation_seconds']} s", accent="#39D98A"
        )
        conn4 = _Connector()
        self._closed_node = _Node(_CheckSymbol(), "MINE CLOSED", "Return confirmed.", accent="#39D98A")
        for widget in (
            self._focus_observed_node,
            conn1,
            self._confirming_node,
            conn2,
            self._verifying_node,
            conn3,
            self._stability_node,
            conn4,
            self._closed_node,
        ):
            row.addWidget(widget, 1 if isinstance(widget, _Node) else 0)
        layout.addLayout(row)

        self._recovery_caption = _small_caption("", role="cyan", bold=True)
        layout.addWidget(self._recovery_caption)
        layout.addWidget(
            _small_caption("Popup hides during Return Confirming; verification continues in the background.")
        )

        self._recovery_connectors = (conn1, conn2, conn3, conn4)
        return frame

    def _build_boundary_notes(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        layout.addWidget(_small_caption(MINE_BRANCH_FACTS["study_preemption_note"], bold=True))
        layout.addWidget(_small_caption(MINE_BRANCH_FACTS["global_pause_note"], bold=True))
        return frame

    def _build_demo_controls(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        label = QLabel("DEMO CONTROLS")
        label.setProperty("role", "cyan")
        label.setFont(make_font(9.5, 700, spacing=0.8))
        layout.addWidget(label)
        layout.addStretch(1)

        self._play_button = _DemoButton("PLAY FLOW")
        self._pause_button = _DemoButton("PAUSE")
        self._replay_button = _DemoButton("REPLAY")
        self._reduced_motion_button = _DemoButton("REDUCED MOTION")
        self._reduced_motion_button.setCheckable(True)

        self._play_button.clicked.connect(self._on_play)
        self._pause_button.clicked.connect(self.pause)
        self._replay_button.clicked.connect(self.replay)
        self._reduced_motion_button.toggled.connect(self._on_reduced_motion_toggled)

        for button in (self._play_button, self._pause_button, self._replay_button, self._reduced_motion_button):
            layout.addWidget(button)

        return frame

    # ------------------------------------------------------------------
    # Animation engine -- same plain sequential step queue as
    # SineSchematic (duplicated rather than shared, so neither class's
    # animation state can ever leak into the other's).
    # ------------------------------------------------------------------

    def _run_sequence(self, steps, *, remember: bool = True) -> None:
        self._step_timer.stop()
        if remember:
            self._last_sequence = list(steps)
        self._pending_steps = list(steps)
        self._is_paused = False
        self._advance_sequence()

    def _advance_sequence(self) -> None:
        if self._is_paused or not self._pending_steps:
            return
        delay, action = self._pending_steps.pop(0)
        action()
        if self._pending_steps:
            self._step_timer.start(0 if self._reduced_motion else delay)

    def pause(self) -> None:
        self._is_paused = True
        self._step_timer.stop()

    def _on_play(self) -> None:
        if self._is_paused and self._pending_steps:
            self._is_paused = False
            self._advance_sequence()
        elif not self._pending_steps:
            self._run_sequence(self._intro_steps())

    def replay(self) -> None:
        self._reset_visual_state()
        self._run_sequence(self._last_sequence or self._intro_steps(), remember=False)

    def _on_reduced_motion_toggled(self, checked: bool) -> None:
        self._reduced_motion = checked
        for connector in (
            self._conn_user_monitor,
            self._conn_monitor_messaging,
            self._conn_messaging_gate,
            self._conn_gate_mine,
            *self._branch_a_connectors,
            *self._branch_b_connectors,
            *self._recovery_connectors,
        ):
            connector.set_reduced_motion(checked)
        self._popup.set_reduced_motion(checked)

    def _reset_visual_state(self) -> None:
        for node in (
            self._user_node,
            self._monitor_node,
            self._messaging_node,
            self._gate_node,
            self._mine_node,
            self._return_intent_node,
            self._clock_node,
            self._neutral_node,
            self._mine2a_node,
            self._duration_choice_node,
            self._allowance_node,
            self._mine2b_node,
            self._focus_observed_node,
            self._confirming_node,
            self._verifying_node,
            self._stability_node,
            self._closed_node,
        ):
            node.set_active(False)
        self._mine_symbol.set_lit_stage(None)
        for chip in self._platform_chips:
            self._set_chip_role(chip, "muted")
        self._allowance_caption.setText("")
        self._recovery_caption.setText("")
        self._popup.setVisible(True)
        self._popup.show_stage("mine_1")
        self._popup.set_buttons_enabled(False)

    def _intro_steps(self):
        return [
            (_STEP_MS, lambda: self._user_node.set_active(True)),
            (_STEP_MS, self._conn_user_monitor.pulse_once),
            (_STEP_MS, lambda: self._monitor_node.set_active(True)),
            (_STEP_MS, self._conn_monitor_messaging.pulse_once),
            (_STEP_MS, lambda: self._messaging_node.set_active(True)),
            (_STEP_MS, self._conn_messaging_gate.pulse_once),
            (_STEP_MS, lambda: self._gate_node.set_active(True)),
            (_STEP_MS, self._conn_gate_mine.pulse_once),
            (_STEP_MS, lambda: (self._mine_node.set_active(True), self._mine_symbol.set_lit_stage("mine_1"))),
            (_STEP_MS, lambda: self._popup.show_stage("mine_1")),
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(True)),
        ]

    def _on_demo_button(self, label: str) -> None:
        if label == "I WILL COME BACK":
            self._run_sequence(self._return_intent_steps())
        elif label == "IT'S IMPORTANT":
            self._run_sequence(self._important_duration_steps())

    def _on_duration_submitted(self, minutes: int) -> None:
        self._run_sequence(self._allowance_steps(minutes))

    def _return_intent_steps(self):
        return [
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(False)),
            (_STEP_MS, lambda: self._return_intent_node.set_active(True)),
            (_STEP_MS, self._conn_return_clock.pulse_once),
            (_STEP_MS, lambda: (self._clock_node.set_active(True), self._mine_symbol.set_lit_stage(None))),
            (_STEP_MS, self._conn_clock_mine2a.pulse_once),
            (_STEP_MS, lambda: (self._mine2a_node.set_active(True), self._mine_symbol.set_lit_stage("mine_2"))),
            (_STEP_MS, lambda: self._popup.show_stage("mine_2a")),
        ] + self._recovery_steps(critical=True)

    def _important_duration_steps(self):
        return [
            (_STEP_MS, lambda: self._popup.show_stage("mine_1_duration")),
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(True)),
        ]

    def _allowance_steps(self, minutes: int):
        return [
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(False)),
            (_STEP_MS, lambda: self._duration_choice_node.set_active(True)),
            (_STEP_MS, self._conn_duration_allowance.pulse_once),
            (_STEP_MS, lambda: self._allowance_node.set_active(True)),
            (_STEP_MS, lambda: self._allowance_caption.setText(f"{minutes} MIN ALLOWANCE")),
            (_STEP_MS, self._conn_allowance_mine2b.pulse_once),
            (_STEP_MS, lambda: (self._mine2b_node.set_active(True), self._mine_symbol.set_lit_stage("mine_2"))),
            (_STEP_MS, lambda: self._popup.show_stage("mine_2b")),
        ] + self._recovery_steps(critical=True)

    def _early_return_a_steps(self):
        return [
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(False)),
        ] + self._recovery_steps(critical=False, early=True)

    def _early_return_b_steps(self):
        return [
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(False)),
        ] + self._recovery_steps(critical=False, early=True)

    def _recovery_steps(self, *, critical: bool, early: bool = False):
        del critical
        conn1, conn2, conn3, conn4 = self._recovery_connectors
        steps = []
        if early:
            steps.append(
                (_STEP_MS, lambda: self._recovery_caption.setText("Early return — recovery begins before MINE-2."))
            )
        steps += [
            (_STEP_MS, lambda: self._focus_observed_node.set_active(True)),
            (_STEP_MS, conn1.pulse_once),
            (_STEP_MS, lambda: self._confirming_node.set_active(True)),
            (_STEP_MS, lambda: self._popup.setVisible(False)),
            (_STEP_MS, conn2.pulse_once),
            (_STEP_MS, lambda: self._verifying_node.set_active(True)),
            (_STEP_MS, conn3.pulse_once),
            (_STEP_MS, lambda: self._stability_node.set_active(True)),
            (_STEP_MS, conn4.pulse_once),
            (_STEP_MS, lambda: (self._closed_node.set_active(True), self._mine_symbol.set_lit_stage("recovery"))),
            (_STEP_MS, lambda: self._recovery_caption.setText("RETURN CONFIRMED · MINE CLOSED")),
        ]
        return steps

    def _relapse_steps(self):
        return [
            (_STEP_MS, lambda: self._verifying_node.set_active(True)),
            (_STEP_MS, lambda: self._recovery_caption.setText("MESSAGING RELAPSE")),
            (_STEP_MS, lambda: self._popup.setVisible(True)),
            (_STEP_MS, lambda: self._recovery_caption.setText("SAME MINE-2 RESTORED · TRY RETURN AGAIN")),
        ]

    def _neutral_detour_steps(self):
        conn = self._conn_neutral
        return [
            (_STEP_MS, lambda: self._clock_node.set_active(True)),
            (_STEP_MS, conn.pulse_once),
            (_STEP_MS, lambda: self._neutral_node.set_active(True)),
            (_STEP_MS, lambda: self._neutral_node.set_active(False)),
            (_STEP_MS, conn.pulse_once),
            (_STEP_MS, lambda: self._clock_node.set_active(True)),
        ]

    def _set_chip_role(self, chip: QLabel, role: str) -> None:
        chip.setProperty("role", role)
        chip.style().unpolish(chip)
        chip.style().polish(chip)

    def _platform_switch_steps(self):
        steps = []
        for chip in self._platform_chips:
            steps.append((_STEP_MS, lambda c=chip: self._set_chip_role(c, "cyan")))
        for chip in self._platform_chips:
            steps.append((_STEP_MS, lambda c=chip: self._set_chip_role(c, "muted")))
        return steps

    # ------------------------------------------------------------------
    # Qt lifecycle: never animate while hidden.
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().showEvent(event)
        if not self._intro_played:
            self._intro_played = True
            self._run_sequence(self._intro_steps())

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().hideEvent(event)
        self._step_timer.stop()
        self._is_paused = False
        self._pending_steps = []
        for connector in (
            self._conn_user_monitor,
            self._conn_monitor_messaging,
            self._conn_messaging_gate,
            self._conn_gate_mine,
            *self._branch_a_connectors,
            *self._branch_b_connectors,
            *self._recovery_connectors,
        ):
            connector.stop()
        self._popup.stop()


class CosineSchematic(QWidget):
    """The Chapter 2 Phase 3 living schematic for COSINE.

    Presentation-only, same discipline as ``SineSchematic``/``MineSchematic``:
    every click here only changes local widget state.  Nothing in this
    class calls COSINE, MIRL, Study Mode, or any other MYELIN authority,
    and it runs identically whether or not a MYELIN session is active.

    Forensic correction this class exists to teach correctly: the CURRENT
    COSINE architecture is NOT the older 23:15 / "10 MORE MIN" /
    "FINISH MY SHOW" concept -- those names survive only as legacy
    compatibility enum values in the runtime and never appear here.  The
    current initial gate is 5:00; the current intention choices are
    SORRY, I'LL COME BACK and YEAH, I WANT SOME BREAK; continued OTT
    after a return intention converts to a bounded 10-200 minute break,
    never an old "10 MORE MIN" popup.
    """

    content_size_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reduced_motion = False
        self._is_paused = False
        self._pending_steps: list[tuple[int, "Callable[[], None]"]] = []
        self._last_sequence: list[tuple[int, "Callable[[], None]"]] = []
        self._intro_played = False
        self._chosen_minutes = 30

        self._step_timer = QTimer(self)
        self._step_timer.setSingleShot(True)
        self._step_timer.timeout.connect(self._advance_sequence)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(14)

        root.addWidget(self._build_banner())
        root.addWidget(self._build_entry_band())
        self._popup = _CosineMiniPopup()
        self._popup.button_clicked.connect(self._on_demo_button)
        self._popup.duration_submitted.connect(self._on_duration_submitted)
        root.addWidget(self._popup)
        root.addWidget(self._build_branch_row())
        root.addWidget(self._build_break_band())
        root.addWidget(self._build_recovery_band())
        root.addWidget(self._build_hopper_band())
        root.addWidget(self._build_boundary_notes())
        root.addWidget(self._build_platforms_strip())
        root.addWidget(
            _info_strip(
                (
                    ("ROLE", "Streaming intervention authority."),
                    ("INPUT", "Certified OTT context from MONITOR."),
                    ("FIRST GATE", f"{COSINE_TIMING_FACTS['initial_gate']} supported OTT time."),
                    ("BRANCH A", "SORRY, I'LL COME BACK → new 5:00 OTT window."),
                    ("BRANCH B", "YEAH, I WANT SOME BREAK → 10–200 min duration."),
                    ("BREAK", "ENJOY THE SHOW · YAY acknowledges, does not extend the deadline."),
                    ("FINAL CALLBACK", "HOPE YOU ENJOYED THE SHOW → no buttons."),
                    (
                        "RETURN",
                        f"{COSINE_TIMING_FACTS['final_callback_hide_seconds']}s hide milestone inside "
                        f"{COSINE_TIMING_FACTS['return_verification_seconds']}s verify + "
                        f"{COSINE_TIMING_FACTS['closure_confirmation_seconds']}s closure.",
                    ),
                )
            )
        )
        root.addWidget(
            _info_strip(
                (
                    ("INITIAL GATE", f"{COSINE_TIMING_FACTS['initial_gate']} supported OTT."),
                    ("RETURN-INTENT WINDOW", f"{COSINE_TIMING_FACTS['return_intent_window']} supported OTT."),
                    (
                        "BREAK DURATION",
                        f"{COSINE_TIMING_FACTS['break_minutes_min']}–"
                        f"{COSINE_TIMING_FACTS['break_minutes_max']} min, chosen by user.",
                    ),
                    (
                        "FINAL-CALLBACK HIDE",
                        f"{COSINE_TIMING_FACTS['final_callback_hide_seconds']} s milestone inside verification.",
                    ),
                    ("RETURN VERIFY", f"{COSINE_TIMING_FACTS['return_verification_seconds']} s total."),
                    ("CLOSURE STABILITY", f"{COSINE_TIMING_FACTS['closure_confirmation_seconds']} s."),
                )
            )
        )
        root.addWidget(_small_caption("DEMO TIMING NOT TO SCALE.", bold=True))
        root.addWidget(self._build_demo_controls())
        root.addStretch(1)

        self._popup.show_stage("intention")
        self._popup.set_buttons_enabled(False)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_banner(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        badge_row = QHBoxLayout()
        badge = QLabel("SCHEMATIC DEMONSTRATION · NOT LIVE TELEMETRY")
        badge.setObjectName("chapter2DemoBadge")
        badge.setWordWrap(True)
        badge.setFont(make_font(9.5, 700, spacing=0.6))
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        layout.addLayout(badge_row)
        layout.addWidget(
            _small_caption(
                "COSINE receives certified OTT context from MONITOR. It does "
                "not identify streaming platforms from window-title text by itself.",
            )
        )
        return frame

    def _build_entry_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        self._user_node = _Node(_HumanSymbol(), "USER", "Works on an intended task.", accent="#38BDF8")
        self._monitor_node = _Node(_MonitorSymbol(), "MONITOR", "Observes certified software context.", accent="#38BDF8")
        self._ott_node = _Node(
            _OttSymbol(), "CERTIFIED OTT", "Native app / certified host identity.", accent="#38BDF8"
        )
        self._gate_node = _Node(
            _TimerSymbol(), COSINE_TIMING_FACTS["initial_gate"], "Supported OTT time.", accent="#38BDF8"
        )

        self._cosine_symbol = _CosineSymbol()
        self._cosine_node = _Node(
            self._cosine_symbol,
            "COSINE",
            "Streaming intervention.",
            accent="#7C9CFF",
            object_name="chapter2CosineNode",
        )

        self._conn_user_monitor = _Connector()
        self._conn_monitor_ott = _Connector()
        self._conn_ott_gate = _Connector()
        self._conn_gate_cosine = _Connector()

        for widget in (
            self._user_node,
            self._conn_user_monitor,
            self._monitor_node,
            self._conn_monitor_ott,
            self._ott_node,
            self._conn_ott_gate,
            self._gate_node,
            self._conn_gate_cosine,
            self._cosine_node,
        ):
            layout.addWidget(widget, 1 if isinstance(widget, _Node) else 0)

        return frame

    def _build_branch_row(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        outer = QHBoxLayout(frame)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(14)
        outer.addWidget(self._build_branch_a(), 1)
        outer.addWidget(self._build_branch_b(), 1)
        return frame

    def _build_branch_a(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading = QLabel("BRANCH A · SORRY, I'LL COME BACK")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        heading.setWordWrap(True)
        _allow_shrink(heading)
        layout.addWidget(heading)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._return_intention_node = _Node(
            _EvidenceSymbol(), "RETURN INTENTION", "An intention only -- not verified recovery.", accent="#38BDF8"
        )
        self._conn_return_window = _Connector()
        self._window_node = _Node(
            _TimerSymbol(), COSINE_TIMING_FACTS["return_intent_window"], "New OTT window.", accent="#38BDF8"
        )
        for widget in (self._return_intention_node, self._conn_return_window, self._window_node):
            row.addWidget(widget, 1 if isinstance(widget, _Node) else 0)
        layout.addLayout(row)

        layout.addWidget(
            _small_caption(
                "NEW WINDOW STARTS AFTER YOUR CHOICE — not measured from the original episode start.", bold=True
            )
        )

        early_row = QHBoxLayout()
        self._early_return_a_button = _DemoButton("EARLY FOCUS RETURN")
        self._early_return_a_button.clicked.connect(lambda: self._run_sequence(self._early_return_a_steps()))
        early_row.addWidget(self._early_return_a_button)
        early_row.addStretch(1)
        layout.addLayout(early_row)
        layout.addWidget(_small_caption("Actual focus can begin recovery before any break workflow."))

        fail_row = QHBoxLayout()
        self._failed_return_button = _DemoButton("5:00 OTT COMPLETES")
        self._failed_return_button.clicked.connect(lambda: self._run_sequence(self._failed_return_steps()))
        fail_row.addWidget(self._failed_return_button)
        fail_row.addStretch(1)
        layout.addLayout(fail_row)
        layout.addWidget(_small_caption(COSINE_BRANCH_FACTS["failed_return_note"]))

        return frame

    def _build_branch_b(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading = QLabel("BRANCH B · YEAH, I WANT SOME BREAK")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        heading.setWordWrap(True)
        _allow_shrink(heading)
        layout.addWidget(heading)

        row = QHBoxLayout()
        row.setSpacing(6)
        self._break_intent_node = _Node(
            _EvidenceSymbol(), "BREAK INTENT", "Directly opens the duration workflow.", accent="#38BDF8"
        )
        row.addWidget(self._break_intent_node, 1)
        layout.addLayout(row)

        layout.addWidget(
            _small_caption(
                "Opens the SAME duration-entry popup used by the failed-return "
                "branch, in its BREAK LENGTH presentation."
            )
        )

        demo_row = QHBoxLayout()
        self._direct_break_button = _DemoButton("OPEN DURATION ENTRY")
        self._direct_break_button.clicked.connect(lambda: self._run_sequence(self._direct_break_steps()))
        demo_row.addWidget(self._direct_break_button)
        demo_row.addStretch(1)
        layout.addLayout(demo_row)

        return frame

    def _build_break_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading = QLabel("BREAK ACTIVE")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        layout.addWidget(heading)
        layout.addWidget(_small_caption("Runs on COSINE's effective clock. Global Pause freezes it."))

        row = QHBoxLayout()
        row.setSpacing(6)
        self._break_active_node = _Node(_TimerSymbol(), "BREAK ACTIVE", "Chosen by user.", accent="#F5A623")
        row.addWidget(self._break_active_node, 1)
        layout.addLayout(row)

        self._break_caption = _small_caption("", role="cyan", bold=True)
        layout.addWidget(self._break_caption)

        early_row = QHBoxLayout()
        self._early_return_break_button = _DemoButton("EARLY FOCUS RETURN")
        self._early_return_break_button.clicked.connect(
            lambda: self._run_sequence(self._early_return_break_steps())
        )
        early_row.addWidget(self._early_return_break_button)
        early_row.addStretch(1)
        layout.addLayout(early_row)
        layout.addWidget(_small_caption("Returning early can close COSINE without waiting for the break deadline."))

        deadline_row = QHBoxLayout()
        self._deadline_button = _DemoButton("BREAK DEADLINE")
        self._deadline_button.clicked.connect(lambda: self._run_sequence(self._deadline_steps()))
        deadline_row.addWidget(self._deadline_button)
        deadline_row.addStretch(1)
        layout.addLayout(deadline_row)

        return frame

    def _build_recovery_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading_row = QHBoxLayout()
        heading = QLabel("COSINE'S RETURN CHAIN")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        heading.setWordWrap(True)
        _allow_shrink(heading)
        heading_row.addWidget(heading, 1)
        self._relapse_button = _DemoButton("SHOW OTT RELAPSE")
        self._relapse_button.clicked.connect(lambda: self._run_sequence(self._relapse_steps()))
        heading_row.addWidget(self._relapse_button)
        layout.addLayout(heading_row)
        layout.addWidget(_small_caption(COSINE_BRANCH_FACTS["hide_milestone_note"], role="cyan", bold=True))

        row = QHBoxLayout()
        row.setSpacing(6)
        self._focus_observed_node = _Node(_CheckSymbol(), "FOCUS OBSERVED", "", accent="#39D98A")
        conn1 = _Connector()
        self._confirming_node = _Node(
            _TimerSymbol(),
            "RETURN CONFIRMING",
            f"{COSINE_TIMING_FACTS['final_callback_hide_seconds']} s hide",
            accent="#39D98A",
        )
        conn2 = _Connector()
        self._verifying_node = _Node(
            _TimerSymbol(),
            "RETURN VERIFYING",
            f"{COSINE_TIMING_FACTS['return_verification_seconds']} s total",
            accent="#39D98A",
        )
        conn3 = _Connector()
        self._stability_node = _Node(
            _TimerSymbol(),
            "STABILITY CONFIRMING",
            f"{COSINE_TIMING_FACTS['closure_confirmation_seconds']} s",
            accent="#39D98A",
        )
        conn4 = _Connector()
        self._closed_node = _Node(_CheckSymbol(), "COSINE CLOSED", "Return confirmed.", accent="#39D98A")
        for widget in (
            self._focus_observed_node,
            conn1,
            self._confirming_node,
            conn2,
            self._verifying_node,
            conn3,
            self._stability_node,
            conn4,
            self._closed_node,
        ):
            row.addWidget(widget, 1 if isinstance(widget, _Node) else 0)
        layout.addLayout(row)

        self._recovery_caption = _small_caption("", role="cyan", bold=True)
        layout.addWidget(self._recovery_caption)
        layout.addWidget(
            _small_caption("Final-callback route: popup hides at 3 s; early-return routes verify directly.")
        )

        self._recovery_connectors = (conn1, conn2, conn3, conn4)
        return frame

    def _build_hopper_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        heading_row = QHBoxLayout()
        heading = QLabel("PLATFORM HOPPER")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self._hopper_button = _DemoButton("SHOW PLATFORM HOP")
        self._hopper_button.clicked.connect(lambda: self._run_sequence(self._hopper_steps()))
        heading_row.addWidget(self._hopper_button)
        layout.addLayout(heading_row)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        self._hopper_chips: list[QLabel] = []
        for label_text in ("NETFLIX", "PRIME VIDEO", "DISNEY+"):
            chip = _small_caption(label_text, role="muted", bold=True)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip_row.addWidget(chip, 1)
            self._hopper_chips.append(chip)
        layout.addLayout(chip_row)
        layout.addWidget(_small_caption(COSINE_BRANCH_FACTS["hopper_note"]))
        return frame

    def _build_boundary_notes(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        layout.addWidget(_small_caption(COSINE_BRANCH_FACTS["study_preemption_note"], bold=True))
        layout.addWidget(_small_caption(COSINE_BRANCH_FACTS["global_pause_note"], bold=True))
        return frame

    def _build_platforms_strip(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2InfoStrip")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)
        heading = QLabel("CURRENT SUPPORTED PLATFORMS")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(9.5, 700, spacing=0.8))
        layout.addWidget(heading)
        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for index, name in enumerate(COSINE_PLATFORM_FACTS):
            chip = _small_caption(name.upper())
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(chip, index // 4, index % 4)
        layout.addLayout(grid)
        layout.addWidget(_small_caption("YouTube is not part of the current COSINE platform map."))
        return frame

    def _build_demo_controls(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        label = QLabel("DEMO CONTROLS")
        label.setProperty("role", "cyan")
        label.setFont(make_font(9.5, 700, spacing=0.8))
        layout.addWidget(label)
        layout.addStretch(1)

        self._play_button = _DemoButton("PLAY FLOW")
        self._pause_button = _DemoButton("PAUSE")
        self._replay_button = _DemoButton("REPLAY")
        self._reduced_motion_button = _DemoButton("REDUCED MOTION")
        self._reduced_motion_button.setCheckable(True)

        self._play_button.clicked.connect(self._on_play)
        self._pause_button.clicked.connect(self.pause)
        self._replay_button.clicked.connect(self.replay)
        self._reduced_motion_button.toggled.connect(self._on_reduced_motion_toggled)

        for button in (self._play_button, self._pause_button, self._replay_button, self._reduced_motion_button):
            layout.addWidget(button)

        return frame

    # ------------------------------------------------------------------
    # Animation engine -- same plain sequential step queue as
    # SineSchematic/MineSchematic (duplicated rather than shared, so no
    # animation state can leak between organs).
    # ------------------------------------------------------------------

    def _run_sequence(self, steps, *, remember: bool = True) -> None:
        self._step_timer.stop()
        if remember:
            self._last_sequence = list(steps)
        self._pending_steps = list(steps)
        self._is_paused = False
        self._advance_sequence()

    def _advance_sequence(self) -> None:
        if self._is_paused or not self._pending_steps:
            return
        delay, action = self._pending_steps.pop(0)
        action()
        if self._pending_steps:
            self._step_timer.start(0 if self._reduced_motion else delay)

    def pause(self) -> None:
        self._is_paused = True
        self._step_timer.stop()

    def _on_play(self) -> None:
        if self._is_paused and self._pending_steps:
            self._is_paused = False
            self._advance_sequence()
        elif not self._pending_steps:
            self._run_sequence(self._intro_steps())

    def replay(self) -> None:
        self._reset_visual_state()
        self._run_sequence(self._last_sequence or self._intro_steps(), remember=False)

    def _on_reduced_motion_toggled(self, checked: bool) -> None:
        self._reduced_motion = checked
        for connector in (
            self._conn_user_monitor,
            self._conn_monitor_ott,
            self._conn_ott_gate,
            self._conn_gate_cosine,
            self._conn_return_window,
            *self._recovery_connectors,
        ):
            connector.set_reduced_motion(checked)
        self._popup.set_reduced_motion(checked)

    def _reset_visual_state(self) -> None:
        for node in (
            self._user_node,
            self._monitor_node,
            self._ott_node,
            self._gate_node,
            self._cosine_node,
            self._return_intention_node,
            self._window_node,
            self._break_intent_node,
            self._break_active_node,
            self._focus_observed_node,
            self._confirming_node,
            self._verifying_node,
            self._stability_node,
            self._closed_node,
        ):
            node.set_active(False)
        self._cosine_symbol.set_lit_stage(None)
        for chip in self._hopper_chips:
            self._set_chip_role(chip, "muted")
        self._break_caption.setText("")
        self._recovery_caption.setText("")
        self._popup.setVisible(True)
        self._popup.show_stage("intention")
        self._popup.set_buttons_enabled(False)

    def _intro_steps(self):
        return [
            (_STEP_MS, lambda: self._user_node.set_active(True)),
            (_STEP_MS, self._conn_user_monitor.pulse_once),
            (_STEP_MS, lambda: self._monitor_node.set_active(True)),
            (_STEP_MS, self._conn_monitor_ott.pulse_once),
            (_STEP_MS, lambda: self._ott_node.set_active(True)),
            (_STEP_MS, self._conn_ott_gate.pulse_once),
            (_STEP_MS, lambda: self._gate_node.set_active(True)),
            (_STEP_MS, self._conn_gate_cosine.pulse_once),
            (_STEP_MS, lambda: (self._cosine_node.set_active(True), self._cosine_symbol.set_lit_stage("intention"))),
            (_STEP_MS, lambda: self._popup.show_stage("intention")),
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(True)),
        ]

    def _on_demo_button(self, label: str) -> None:
        if label == "SORRY, I'LL COME BACK":
            self._run_sequence(self._return_intention_steps())
        elif label == "YEAH, I WANT SOME BREAK":
            self._run_sequence(self._direct_break_from_intention_steps())
        elif label == "YAY":
            self._run_sequence(self._yay_steps())

    def _on_duration_submitted(self, minutes: int) -> None:
        self._chosen_minutes = minutes
        self._run_sequence(self._break_start_steps(minutes))

    def _return_intention_steps(self):
        return [
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(False)),
            (_STEP_MS, lambda: self._popup.setVisible(False)),
            (_STEP_MS, lambda: self._return_intention_node.set_active(True)),
            (_STEP_MS, self._conn_return_window.pulse_once),
            (_STEP_MS, lambda: (self._window_node.set_active(True), self._cosine_symbol.set_lit_stage(None))),
        ]

    def _early_return_a_steps(self):
        return self._recovery_steps(early=True)

    def _failed_return_steps(self):
        return [
            (_STEP_MS, lambda: self._window_node.set_active(True)),
            (_STEP_MS, lambda: (self._popup.setVisible(True), self._popup.show_stage("set_a_limit"))),
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(True)),
        ]

    def _direct_break_from_intention_steps(self):
        return [
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(False)),
            (_STEP_MS, lambda: self._break_intent_node.set_active(True)),
            (_STEP_MS, lambda: self._popup.show_stage("break_length")),
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(True)),
        ]

    def _direct_break_steps(self):
        return [
            (_STEP_MS, lambda: self._break_intent_node.set_active(True)),
            (_STEP_MS, lambda: (self._popup.setVisible(True), self._popup.show_stage("break_length"))),
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(True)),
        ]

    def _break_start_steps(self, minutes: int):
        return [
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(False)),
            (_STEP_MS, lambda: self._break_active_node.set_active(True)),
            (_STEP_MS, lambda: self._break_caption.setText(f"{minutes} MIN BREAK")),
            (_STEP_MS, lambda: (self._popup.show_break_set(minutes), self._cosine_symbol.set_lit_stage("break"))),
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(True)),
        ]

    def _yay_steps(self):
        return [
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(False)),
            (_STEP_MS, lambda: self._popup.setVisible(False)),
            (_STEP_MS, lambda: self._break_caption.setText("ACKNOWLEDGED · SAME DEADLINE CONTINUES")),
        ]

    def _early_return_break_steps(self):
        return self._recovery_steps(early=True)

    def _deadline_steps(self):
        return [
            (
                _STEP_MS,
                lambda: (
                    self._popup.setVisible(True),
                    self._popup.show_stage("final_callback"),
                    self._cosine_symbol.set_lit_stage("break"),
                ),
            ),
        ] + self._recovery_steps(early=False)

    def _recovery_steps(self, *, early: bool):
        conn1, conn2, conn3, conn4 = self._recovery_connectors
        steps = []
        if early:
            steps.append(
                (
                    _STEP_MS,
                    lambda: self._recovery_caption.setText("Early return — recovery begins before any final callback."),
                )
            )
        steps += [
            (_STEP_MS, lambda: self._focus_observed_node.set_active(True)),
            (_STEP_MS, conn1.pulse_once),
            (_STEP_MS, lambda: self._confirming_node.set_active(True)),
            (_STEP_MS, lambda: self._popup.setVisible(False)),
            (_STEP_MS, conn2.pulse_once),
            (_STEP_MS, lambda: self._verifying_node.set_active(True)),
            (_STEP_MS, conn3.pulse_once),
            (_STEP_MS, lambda: self._stability_node.set_active(True)),
            (_STEP_MS, conn4.pulse_once),
            (_STEP_MS, lambda: (self._closed_node.set_active(True), self._cosine_symbol.set_lit_stage("recovery"))),
            (_STEP_MS, lambda: self._recovery_caption.setText("RETURN CONFIRMED · COSINE CLOSED")),
        ]
        return steps

    def _relapse_steps(self):
        return [
            (_STEP_MS, lambda: self._verifying_node.set_active(True)),
            (_STEP_MS, lambda: self._recovery_caption.setText("OTT RELAPSE")),
            (_STEP_MS, lambda: self._popup.setVisible(True)),
            (_STEP_MS, lambda: self._recovery_caption.setText("SAME FINAL CALLBACK RESTORED · TRY RETURN AGAIN")),
        ]

    def _set_chip_role(self, chip: QLabel, role: str) -> None:
        chip.setProperty("role", role)
        chip.style().unpolish(chip)
        chip.style().polish(chip)

    def _hopper_steps(self):
        steps = []
        for chip in self._hopper_chips:
            steps.append((_STEP_MS, lambda c=chip: self._set_chip_role(c, "cyan")))
        for chip in self._hopper_chips:
            steps.append((_STEP_MS, lambda c=chip: self._set_chip_role(c, "muted")))
        return steps

    # ------------------------------------------------------------------
    # Qt lifecycle: never animate while hidden.
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().showEvent(event)
        if not self._intro_played:
            self._intro_played = True
            self._run_sequence(self._intro_steps())

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().hideEvent(event)
        self._step_timer.stop()
        self._is_paused = False
        self._pending_steps = []
        for connector in (
            self._conn_user_monitor,
            self._conn_monitor_ott,
            self._conn_ott_gate,
            self._conn_gate_cosine,
            self._conn_return_window,
            *self._recovery_connectors,
        ):
            connector.stop()
        self._popup.stop()


class CosecantSchematic(QWidget):
    """The Chapter 2 Phase 4 living schematic for COSECANT -- the final
    Chapter 2 organ.

    Presentation-only, same discipline as ``SineSchematic`` /
    ``MineSchematic`` / ``CosineSchematic``: every click here only
    changes local widget state.  Nothing in this class calls COSECANT,
    Study, Monitor, or any other MYELIN authority, and it runs
    identically whether or not a MYELIN session is active.

    Architectural boundaries this class exists to teach correctly:
    RETURN TO STUDY is intent only, never return evidence; FINAL_LOCK has
    zero buttons and is released only by the exact registered Study
    resource, never generic focus; COSECANT confirms return but never
    resumes Study itself -- Monitor/the coordinator does.
    """

    content_size_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reduced_motion = False
        self._is_paused = False
        self._pending_steps: list[tuple[int, "Callable[[], None]"]] = []
        self._last_sequence: list[tuple[int, "Callable[[], None]"]] = []
        self._intro_played = False

        self._step_timer = QTimer(self)
        self._step_timer.setSingleShot(True)
        self._step_timer.timeout.connect(self._advance_sequence)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(14)

        root.addWidget(self._build_banner())
        root.addWidget(self._build_entry_band())
        self._popup = _CosecantMiniPopup()
        self._popup.button_clicked.connect(self._on_demo_button)
        root.addWidget(self._popup)
        root.addWidget(self._build_break_band())
        root.addWidget(self._build_overdue_band())
        root.addWidget(self._build_comparison_band())
        root.addWidget(self._build_verification_band())
        root.addWidget(self._build_boundary_notes())
        root.addWidget(
            _info_strip(
                (
                    ("ROLE", "Approved Study break-return regulation authority."),
                    ("INPUT", "Exact Study resource + break admission from MONITOR."),
                    ("BREAK", "User-selected duration (60 s – 24 h). No canonical length."),
                    ("REMINDERS", "BREAK COMPLETE → +5:00 → BREAK ALREADY OVER → +1:00 → FINAL LOCK."),
                    ("BUTTON", "RETURN TO STUDY → intent only, never evidence."),
                    ("RELEASE", "Only the exact registered Study resource. Never generic focus."),
                    ("RETURN", f"{COSECANT_TIMING_FACTS['return_confirmation_seconds']} continuous seconds → RETURN CONFIRMED."),
                    ("RESUME", "COSECANT confirms return. Monitor/coordinator resumes Study."),
                )
            )
        )
        root.addWidget(
            _info_strip(
                (
                    ("BREAK BOUNDS", f"{COSECANT_TIMING_FACTS['break_minimum_seconds']} s minimum, {COSECANT_TIMING_FACTS['break_maximum_hours']} h maximum."),
                    ("OVERDUE +5", f"{COSECANT_TIMING_FACTS['already_over_delay']} after break end."),
                    ("FINAL LOCK +1", f"{COSECANT_TIMING_FACTS['final_lock_delay']} after that."),
                    ("RETURN VERIFY", f"{COSECANT_TIMING_FACTS['return_confirmation_seconds']} continuous seconds of exact presence."),
                )
            )
        )
        root.addWidget(_small_caption("DEMO TIMING NOT TO SCALE.", bold=True))
        root.addWidget(self._build_demo_controls())
        root.addStretch(1)

        self._popup.show_stage("break_complete")
        self._popup.set_buttons_enabled(False)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_banner(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        badge_row = QHBoxLayout()
        badge = QLabel("SCHEMATIC DEMONSTRATION · NOT LIVE TELEMETRY")
        badge.setObjectName("chapter2DemoBadge")
        badge.setWordWrap(True)
        badge.setFont(make_font(9.5, 700, spacing=0.6))
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        layout.addLayout(badge_row)
        layout.addWidget(
            _small_caption(
                "COSECANT does not infer return from a button click or generic "
                "focus. It confirms return using the exact registered Study resource.",
            )
        )
        return frame

    def _build_entry_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(6)

        self._user_node = _Node(_HumanSymbol(), "USER", "Studies an intended resource.", accent="#38BDF8")
        self._study_node = _Node(_StudySymbol(), "STUDY MODE", "Owns the intended Study block.", accent="#38BDF8")
        self._resource_node = _Node(
            _ExactResourceSymbol(), "EXACT STUDY RESOURCE", "Frozen as the return target.", accent="#38BDF8"
        )
        self._request_node = _Node(
            _EvidenceSymbol(), "APPROVED BREAK REQUEST", "Parked until admission.", accent="#38BDF8"
        )
        self._monitor_node = _Node(
            _MonitorSymbol(), "MONITOR", "Confirms the exact return target.", accent="#38BDF8"
        )

        self._cosecant_symbol = _CosecantSymbol()
        self._cosecant_node = _Node(
            self._cosecant_symbol,
            "COSECANT",
            "Break-return regulation.",
            accent="#39D98A",
            object_name="chapter2CosecantNode",
        )

        self._conn_user_study = _Connector()
        self._conn_study_resource = _Connector()
        self._conn_resource_request = _Connector()
        self._conn_request_monitor = _Connector()
        self._conn_monitor_cosecant = _Connector()

        for widget in (
            self._user_node,
            self._conn_user_study,
            self._study_node,
            self._conn_study_resource,
            self._resource_node,
            self._conn_resource_request,
            self._request_node,
            self._conn_request_monitor,
            self._monitor_node,
            self._conn_monitor_cosecant,
            self._cosecant_node,
        ):
            layout.addWidget(widget, 1 if isinstance(widget, _Node) else 0)

        return frame

    def _build_break_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading = QLabel("BREAK ACTIVE")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        layout.addWidget(heading)
        layout.addWidget(
            _small_caption(
                "A break request is parked until the next real MONITOR observation "
                "confirms the exact return target. Study pauses only after admission succeeds."
            )
        )

        row = QHBoxLayout()
        row.setSpacing(6)
        self._break_active_node = _Node(
            _TimerSymbol(), "BREAK ACTIVE", "Study paused. Return target registered.", accent="#39D98A"
        )
        row.addWidget(self._break_active_node, 1)
        layout.addLayout(row)

        duration_row = QHBoxLayout()
        duration_row.setSpacing(8)
        duration_caption = QLabel("BREAK DURATION (DEMO VALUE — MINUTES):")
        duration_caption.setProperty("role", "muted")
        duration_caption.setFont(make_font(9, 700, spacing=0.3))
        self._duration_spin = QSpinBox()
        self._duration_spin.setRange(1, 1440)
        self._duration_spin.setValue(10)
        duration_row.addWidget(duration_caption)
        duration_row.addWidget(self._duration_spin)
        duration_row.addStretch(1)
        layout.addLayout(duration_row)
        layout.addWidget(
            _small_caption(
                "Example only. The real minimum is 60 seconds and the maximum is "
                "24 hours -- COSECANT does not enforce a standard break length."
            )
        )

        replay_row = QHBoxLayout()
        self._replay_request_button = _DemoButton("SHOW BREAK REQUEST")
        self._replay_request_button.clicked.connect(lambda: self._run_sequence(self._break_request_steps()))
        replay_row.addWidget(self._replay_request_button)
        replay_row.addStretch(1)
        layout.addLayout(replay_row)

        return frame

    def _build_overdue_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading_row = QHBoxLayout()
        heading = QLabel("OVERDUE ESCALATION")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self._overdue_button = _DemoButton("SHOW OVERDUE PATH")
        self._overdue_button.clicked.connect(lambda: self._run_sequence(self._overdue_steps()))
        heading_row.addWidget(self._overdue_button)
        layout.addLayout(heading_row)
        layout.addWidget(
            _small_caption("BREAK COMPLETE begins immediately at the break deadline -- the +5:00 delay comes after it, not before.")
        )

        row = QHBoxLayout()
        row.setSpacing(6)
        self._break_complete_node = _Node(
            _TimerSymbol(), "BREAK COMPLETE", "Return intent available.", accent="#39D98A"
        )
        conn_a = _Connector()
        timing_a = _timing_label(f"+{COSECANT_TIMING_FACTS['already_over_delay']}", "5 minutes after break completion.")
        self._break_already_over_node = _Node(
            _TimerSymbol(), "BREAK ALREADY OVER", "Return intent still available.", accent="#F5A623"
        )
        conn_b = _Connector()
        timing_b = _timing_label(f"+{COSECANT_TIMING_FACTS['final_lock_delay']}", "1 minute after Break Already Over.")
        self._final_lock_node = _Node(
            _EvidenceSymbol(), "FINAL LOCK", "COME BACK PLEASE · no buttons.", accent="#FF4D6D"
        )
        for widget in (
            self._break_complete_node,
            conn_a,
            timing_a,
            self._break_already_over_node,
            conn_b,
            timing_b,
            self._final_lock_node,
        ):
            row.addWidget(widget, 1 if isinstance(widget, _Node) else 0)
        layout.addLayout(row)

        self._intent_node = _Node(_EvidenceSymbol(), "RETURN INTENT", "Recorded when RETURN TO STUDY is pressed.", accent="#F5A623")
        layout.addWidget(self._intent_node)
        layout.addWidget(_small_caption(COSECANT_BRANCH_FACTS["button_intent_note"], role="cyan", bold=True))

        self._overdue_connectors = (conn_a, conn_b)
        return frame

    def _build_comparison_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        outer = QHBoxLayout(frame)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(18)

        intent_column = QVBoxLayout()
        intent_column.setSpacing(6)
        intent_row = QHBoxLayout()
        intent_row.setSpacing(6)
        self._button_node = _Node(_EvidenceSymbol(), "RETURN TO STUDY", "= RETURN INTENT.", accent="#F5A623")
        self._button_evidence_node = _Node(_ExactResourceSymbol(), "EXACT RESOURCE", "= RETURN EVIDENCE.", accent="#39D98A")
        intent_row.addWidget(self._button_node, 1)
        intent_row.addWidget(self._button_evidence_node, 1)
        intent_column.addLayout(intent_row)
        intent_column.addWidget(_small_caption("INTENT ≠ EVIDENCE", role="cyan", bold=True))
        outer.addLayout(intent_column, 1)

        focus_column = QVBoxLayout()
        focus_column.setSpacing(6)
        focus_row = QHBoxLayout()
        focus_row.setSpacing(6)
        self._generic_focus_node = _Node(_NeutralSymbol(), "GENERIC FOCUS", "✕ Does not release the lock.", accent="#94A3B8")
        self._exact_resource_compare_node = _Node(
            _ExactResourceSymbol(), "EXACT STUDY RESOURCE", "✓ Can start confirmation.", accent="#39D98A"
        )
        focus_row.addWidget(self._generic_focus_node, 1)
        focus_row.addWidget(self._exact_resource_compare_node, 1)
        focus_column.addLayout(focus_row)
        focus_column.addWidget(
            _small_caption(COSECANT_BRANCH_FACTS["exact_resource_note"], role="cyan", bold=True)
        )
        outer.addLayout(focus_column, 1)

        return frame

    def _build_verification_band(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading_row = QHBoxLayout()
        heading = QLabel("EXACT RETURN VERIFICATION")
        heading.setProperty("role", "cyan")
        heading.setFont(make_font(10.5, 700, spacing=1.0))
        heading.setWordWrap(True)
        _allow_shrink(heading)
        heading_row.addWidget(heading, 1)
        layout.addLayout(heading_row)
        layout.addWidget(_small_caption(COSECANT_BRANCH_FACTS["continuity_note"], role="cyan", bold=True))

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self._generic_focus_demo_button = _DemoButton("SHOW GENERIC FOCUS FIRST")
        self._generic_focus_demo_button.clicked.connect(lambda: self._run_sequence(self._generic_focus_steps()))
        self._exact_return_button = _DemoButton("SHOW EXACT RETURN")
        self._exact_return_button.clicked.connect(lambda: self._run_sequence(self._exact_return_steps()))
        self._return_loss_button = _DemoButton("SHOW RETURN LOSS")
        self._return_loss_button.clicked.connect(lambda: self._run_sequence(self._return_loss_steps()))
        button_row.addWidget(self._generic_focus_demo_button)
        button_row.addWidget(self._exact_return_button)
        button_row.addWidget(self._return_loss_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        layout.addWidget(
            _small_caption(
                "SHOW EXACT RETURN works from any reminder stage or Final Lock -- "
                "Final Lock is an escalation, not a mandatory stage every break must reach."
            )
        )

        row = QHBoxLayout()
        row.setSpacing(6)
        self._return_confirmed_node = _Node(_CheckSymbol(), "RETURN CONFIRMED", "Break context retired.", accent="#39D98A")
        conn = _Connector()
        self._study_resumes_node = _Node(
            _StudySymbol(), "STUDY RESUMES", "Monitor/coordinator resumes Study -- not COSECANT itself.", accent="#39D98A"
        )
        row.addWidget(self._return_confirmed_node, 1)
        row.addWidget(conn)
        row.addWidget(self._study_resumes_node, 1)
        layout.addLayout(row)

        self._escalation_caption = _small_caption("", role="cyan", bold=True)
        layout.addWidget(self._escalation_caption)
        layout.addWidget(_small_caption(COSECANT_BRANCH_FACTS["loss_note"]))

        self._conn_confirmed_resume = conn
        return frame

    def _build_boundary_notes(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)
        layout.addWidget(_small_caption(COSECANT_BRANCH_FACTS["exact_target_note"], bold=True))
        layout.addWidget(_small_caption(COSECANT_BRANCH_FACTS["resume_boundary_note"], bold=True))
        return frame

    def _build_demo_controls(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2SchematicCard")
        _allow_shrink(frame)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        label = QLabel("DEMO CONTROLS")
        label.setProperty("role", "cyan")
        label.setFont(make_font(9.5, 700, spacing=0.8))
        layout.addWidget(label)
        layout.addStretch(1)

        self._play_button = _DemoButton("PLAY FLOW")
        self._pause_button = _DemoButton("PAUSE")
        self._replay_button = _DemoButton("REPLAY")
        self._reduced_motion_button = _DemoButton("REDUCED MOTION")
        self._reduced_motion_button.setCheckable(True)

        self._play_button.clicked.connect(self._on_play)
        self._pause_button.clicked.connect(self.pause)
        self._replay_button.clicked.connect(self.replay)
        self._reduced_motion_button.toggled.connect(self._on_reduced_motion_toggled)

        for button in (self._play_button, self._pause_button, self._replay_button, self._reduced_motion_button):
            layout.addWidget(button)

        return frame

    # ------------------------------------------------------------------
    # Animation engine -- same plain sequential step queue as
    # SineSchematic/MineSchematic/CosineSchematic (duplicated rather than
    # shared, so no animation state can leak between organs).
    # ------------------------------------------------------------------

    def _run_sequence(self, steps, *, remember: bool = True) -> None:
        self._step_timer.stop()
        if remember:
            self._last_sequence = list(steps)
        self._pending_steps = list(steps)
        self._is_paused = False
        self._advance_sequence()

    def _advance_sequence(self) -> None:
        if self._is_paused or not self._pending_steps:
            return
        delay, action = self._pending_steps.pop(0)
        action()
        if self._pending_steps:
            self._step_timer.start(0 if self._reduced_motion else delay)

    def pause(self) -> None:
        self._is_paused = True
        self._step_timer.stop()

    def _on_play(self) -> None:
        if self._is_paused and self._pending_steps:
            self._is_paused = False
            self._advance_sequence()
        elif not self._pending_steps:
            self._run_sequence(self._intro_steps())

    def replay(self) -> None:
        self._reset_visual_state()
        self._run_sequence(self._last_sequence or self._intro_steps(), remember=False)

    def _on_reduced_motion_toggled(self, checked: bool) -> None:
        self._reduced_motion = checked
        for connector in (
            self._conn_user_study,
            self._conn_study_resource,
            self._conn_resource_request,
            self._conn_request_monitor,
            self._conn_monitor_cosecant,
            *self._overdue_connectors,
            self._conn_confirmed_resume,
        ):
            connector.set_reduced_motion(checked)
        self._popup.set_reduced_motion(checked)

    def _reset_visual_state(self) -> None:
        for node in (
            self._user_node,
            self._study_node,
            self._resource_node,
            self._request_node,
            self._monitor_node,
            self._cosecant_node,
            self._break_active_node,
            self._intent_node,
            self._break_complete_node,
            self._break_already_over_node,
            self._final_lock_node,
            self._generic_focus_node,
            self._return_confirmed_node,
            self._study_resumes_node,
        ):
            node.set_active(False)
        self._cosecant_symbol.set_lit_stage(None)
        self._escalation_caption.setText("")
        self._popup.setVisible(True)
        self._popup.set_countdown("")
        self._popup.show_stage("break_complete")
        self._popup.set_buttons_enabled(False)

    def _intro_steps(self):
        return [
            (_STEP_MS, lambda: self._user_node.set_active(True)),
            (_STEP_MS, self._conn_user_study.pulse_once),
            (_STEP_MS, lambda: self._study_node.set_active(True)),
            (_STEP_MS, self._conn_study_resource.pulse_once),
            (_STEP_MS, lambda: self._resource_node.set_active(True)),
            (_STEP_MS, self._conn_resource_request.pulse_once),
            (_STEP_MS, lambda: self._request_node.set_active(True)),
            (_STEP_MS, self._conn_request_monitor.pulse_once),
            (_STEP_MS, lambda: self._monitor_node.set_active(True)),
            (_STEP_MS, self._conn_monitor_cosecant.pulse_once),
            (_STEP_MS, lambda: (self._cosecant_node.set_active(True), self._cosecant_symbol.set_lit_stage("break"))),
            (_STEP_MS, lambda: self._break_active_node.set_active(True)),
            (_STEP_MS, lambda: self._popup.show_stage("break_complete")),
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(True)),
        ]

    def _break_request_steps(self):
        return [
            (_STEP_MS, lambda: self._request_node.set_active(True)),
            (_STEP_MS, self._conn_request_monitor.pulse_once),
            (_STEP_MS, lambda: self._monitor_node.set_active(True)),
            (_STEP_MS, self._conn_monitor_cosecant.pulse_once),
            (_STEP_MS, lambda: (self._cosecant_node.set_active(True), self._cosecant_symbol.set_lit_stage("break"))),
            (_STEP_MS, lambda: self._break_active_node.set_active(True)),
        ]

    def _on_demo_button(self, label: str) -> None:
        if label == "RETURN TO STUDY":
            self._run_sequence(self._return_intent_steps())

    def _return_intent_steps(self):
        return [
            (_STEP_MS, lambda: self._popup.set_buttons_enabled(False)),
            (_STEP_MS, lambda: self._intent_node.set_active(True)),
            (
                _STEP_MS,
                lambda: self._escalation_caption.setText(
                    "RETURN INTENT RECORDED — not return evidence. Waiting for the exact Study resource."
                ),
            ),
        ]

    def _overdue_steps(self):
        conn_a, conn_b = self._overdue_connectors
        return [
            (_STEP_MS, lambda: self._break_complete_node.set_active(True)),
            (_STEP_MS, conn_a.pulse_once),
            (
                _STEP_MS,
                lambda: (self._break_already_over_node.set_active(True), self._cosecant_symbol.set_lit_stage("overdue")),
            ),
            (_STEP_MS, lambda: (self._popup.show_stage("break_already_over"), self._popup.set_buttons_enabled(True))),
            (_STEP_MS, conn_b.pulse_once),
            (_STEP_MS, lambda: self._final_lock_node.set_active(True)),
            (_STEP_MS, lambda: self._popup.show_stage("final_lock")),
        ]

    def _generic_focus_steps(self):
        return [
            (_STEP_MS, lambda: self._generic_focus_node.set_active(True)),
            (_STEP_MS, lambda: self._escalation_caption.setText("GENERIC FOCUS OBSERVED — does not release COSECANT.")),
            (_STEP_MS, lambda: self._generic_focus_node.set_active(False)),
        ]

    def _exact_return_steps(self):
        return [
            (_STEP_MS, lambda: self._exact_resource_compare_node.set_active(True)),
            (
                _STEP_MS,
                lambda: (self._popup.show_stage("return_confirming"), self._cosecant_symbol.set_lit_stage("recovery")),
            ),
            (_STEP_MS, lambda: self._popup.set_countdown("3")),
            (_STEP_MS, lambda: self._popup.set_countdown("2")),
            (_STEP_MS, lambda: self._popup.set_countdown("1")),
            (_STEP_MS, lambda: (self._popup.set_countdown("✓"), self._return_confirmed_node.set_active(True))),
            (_STEP_MS, lambda: self._escalation_caption.setText("RETURN CONFIRMED")),
            (_STEP_MS, self._conn_confirmed_resume.pulse_once),
            (_STEP_MS, lambda: self._study_resumes_node.set_active(True)),
            (
                _STEP_MS,
                lambda: self._escalation_caption.setText("COSECANT CONFIRMS RETURN · COORDINATOR RESUMES STUDY"),
            ),
        ]

    def _return_loss_steps(self):
        return [
            (_STEP_MS, lambda: (self._popup.show_stage("return_confirming"), self._popup.set_countdown("2"))),
            (
                _STEP_MS,
                lambda: self._escalation_caption.setText("EXACT RESOURCE BECOMES UNCERTAIN / MISMATCHED / STALE"),
            ),
            (_STEP_MS, lambda: self._popup.set_countdown("")),
            (_STEP_MS, lambda: (self._popup.show_stage("break_already_over"), self._popup.set_buttons_enabled(True))),
            (
                _STEP_MS,
                lambda: self._escalation_caption.setText("CONFIRMATION LOST — RETURNED TO CURRENT OVERDUE STAGE"),
            ),
        ]

    # ------------------------------------------------------------------
    # Qt lifecycle: never animate while hidden.
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().showEvent(event)
        if not self._intro_played:
            self._intro_played = True
            self._run_sequence(self._intro_steps())

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().hideEvent(event)
        self._step_timer.stop()
        self._is_paused = False
        self._pending_steps = []
        for connector in (
            self._conn_user_study,
            self._conn_study_resource,
            self._conn_resource_request,
            self._conn_request_monitor,
            self._conn_monitor_cosecant,
            *self._overdue_connectors,
            self._conn_confirmed_resume,
        ):
            connector.stop()
        self._popup.stop()


class _OrganStack(QStackedWidget):
    """Sizes to the CURRENT organ pane only -- the same technique as
    lab.py's ``_ChapterStack``, duplicated locally so this module never
    imports lab.py (chapters -> schematics -> lab stays one-directional).
    """

    def sizeHint(self):  # noqa: N802 -- Qt override
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self):  # noqa: N802 -- Qt override
        current = self.currentWidget()
        return current.minimumSizeHint() if current is not None else super().minimumSizeHint()

    def hasHeightForWidth(self) -> bool:  # noqa: N802 -- Qt override
        current = self.currentWidget()
        return current.hasHeightForWidth() if current is not None else super().hasHeightForWidth()

    def heightForWidth(self, width: int) -> int:  # noqa: N802 -- Qt override
        current = self.currentWidget()
        if current is not None and current.hasHeightForWidth():
            return current.heightForWidth(width)
        return super().heightForWidth(width)


class ChapterTwoOrganViewer(QWidget):
    """Chapter 2's own organ selector + living schematic host.

    This is Chapter 2's LEVEL 2 navigation (SINE / MINE / COSINE /
    COSECANT) -- entirely separate from the LAB CHAPTERS drawer (LEVEL 1),
    which this widget never touches.  Presentation-only: selecting an
    organ never reads the current MYELIN session, never touches Science
    Lab evidence, and never starts/commands any engine.
    """

    organ_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._organ_buttons: dict[str, QPushButton] = {}
        self._organ_index: dict[str, int] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(14)

        root.addWidget(self._build_hero())
        root.addWidget(self._build_selector())

        self._stack = _OrganStack()
        root.addWidget(self._stack)

        self._sine_schematic = SineSchematic()
        self._register_organ("sine", self._sine_schematic)
        self._mine_schematic = MineSchematic()
        self._register_organ("mine", self._mine_schematic)
        self._cosine_schematic = CosineSchematic()
        self._register_organ("cosine", self._cosine_schematic)
        self._cosecant_schematic = CosecantSchematic()
        self._register_organ("cosecant", self._cosecant_schematic)

        root.addStretch(1)

        self._select_organ("sine")

    def _build_hero(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(6)

        eyebrow = QLabel("CHAPTER 2")
        eyebrow.setProperty("role", "cyan")
        eyebrow.setFont(make_font(11, 700, spacing=1.6))
        layout.addWidget(eyebrow)

        title = QLabel("PARTS OF MYELIN")
        title.setFont(make_font(24, 800, spacing=0.5))
        title.setWordWrap(True)
        _allow_shrink(title)
        layout.addWidget(title)

        subtitle = QLabel("Living Organ Schematics")
        subtitle.setProperty("role", "muted")
        subtitle.setFont(make_font(13, 500))
        layout.addWidget(subtitle)
        layout.addSpacing(4)

        body = QLabel("Select an organ to explore how its signal pathway moves through MYELIN.")
        body.setWordWrap(True)
        _allow_shrink(body)
        body.setFont(make_font(12.5, 400))
        layout.addWidget(body)

        return frame

    def _build_selector(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter2OrganSelector")
        _allow_shrink(frame)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        for organ in CHAPTER_TWO_ORGANS:
            button = QPushButton(organ["title"])
            button.setObjectName("chapter2OrganButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(make_font(11, 700, spacing=0.6))
            button.setToolTip(organ["subtitle"])
            button.setAccessibleName(f"{organ['title']} organ")
            button.clicked.connect(lambda _checked=False, key=organ["key"]: self._select_organ(key))
            layout.addWidget(button, 1)
            self._organ_buttons[organ["key"]] = button
        return frame

    def _register_organ(self, key: str, widget: QWidget) -> None:
        self._organ_index[key] = self._stack.addWidget(widget)

    def _select_organ(self, key: str) -> None:
        index = self._organ_index.get(key)
        if index is None:
            return
        self._stack.setCurrentIndex(index)
        for organ_key, button in self._organ_buttons.items():
            button.setChecked(organ_key == key)
        self._sync_organ_stack_height()
        self.organ_changed.emit()

    def _sync_organ_stack_height(self) -> None:
        current = self._stack.currentWidget()
        if current is None:
            return
        width = self._stack.width()
        if width <= 0:
            width = self._stack.sizeHint().width()
        if width > 0 and current.hasHeightForWidth():
            height = current.heightForWidth(width)
        else:
            height = current.sizeHint().height()
        self._stack.setFixedHeight(max(height, 1))
