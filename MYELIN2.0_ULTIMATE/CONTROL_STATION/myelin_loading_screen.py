# -*- coding: utf-8 -*-
"""
myelin_loading_screen.py
========================

MYELIN splash / loading screen (PyQt6) — a 1:1 port of ``loading_screen.html``.

Composition, straight from the mockup:

* full-bleed dark stage with a radial cyan tint at 50% / 38%
* decorative neuron/axon network (10 x 6 jittered grid, 2 nearest-neighbour
  edges, travelling signal pulses) at 50% opacity
* corner circuit traces top-left and bottom-right, each with a looping pulse
* the real MYELIN logo asset behind a soft pulsing glow
* MYELIN wordmark, GUIDE - RECOVER - FOCUS tagline
* cycling status line with animated dots
* indeterminate sweeping progress bar in the violet -> cyan gradient
* version / interface caption pinned to the bottom

The animation is decorative. It carries no biological, neurological,
diagnostic or evidence meaning, and this screen reads no MYELIN database,
telemetry queue, detector or SINE schedule.

Logo asset
----------
The logo is loaded from disk, never redrawn — ``myelin_logo.png`` is expected
next to this file or in a conventional assets folder (see ``find_logo``).
Pass an explicit path if your tree differs::

    MyelinLoadingScreen(logo_path="assets/branding/myelin_logo.png")

If the asset genuinely cannot be found the screen still comes up, drawing the
MYELIN mark as a labelled fallback rather than an empty box, and warns on
stderr.

Usage
-----
Standalone preview::

    python myelin_loading_screen.py              # windowed, ~6s
    python myelin_loading_screen.py --fullscreen
    python myelin_loading_screen.py --seconds 12

From the launcher::

    app = QApplication(sys.argv)
    splash = MyelinLoadingScreen()
    splash.start()

    window = ControlStation()                     # slow construction here
    splash.set_status("Connecting telemetry feed")
    splash.finish(window)                         # closes splash, shows window
"""

from __future__ import annotations

import math
import os
import random
import sys

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QLinearGradient,
)
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

__all__ = ["MyelinLoadingScreen", "find_logo", "TOKENS"]


# ============================================================
# Design tokens — loading_screen.html :root
# ============================================================

TOKENS = {
    "base": "#0B0F19",
    "surface-soft": "#111827",
    "text": "#E5E7EB",
    "muted": "#94A3B8",
    "cyan": "#38BDF8",
    "cyan-dim": "#1E7BAE",
    "border": "#334155",
    "violet": "#A78BFA",
    "version": "#475569",
}

UI_FAMILIES = ["Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", "sans-serif"]
MONO_FAMILIES = [
    "Consolas",
    "Cascadia Mono",
    "SFMono-Regular",
    "DejaVu Sans Mono",
    "monospace",
]

STATUS_MESSAGES = (
    "Initializing Control Station",
    "Loading behavioral model",
    "Calibrating SINE stages",
    "Connecting telemetry feed",
)

VERSION_CAPTION = "MYELIN Core v2.0  ·  Neural Telemetry Interface"

LOGO_FILENAMES = (
    "myelin_logo.png",
    "myelin_logo.svg",
    "logo.png",
    "myelin.png",
)

LOGO_DIRS = (
    ".",
    "assets",
    "assets/branding",
    "assets/images",
    "assets/logo",
    "resources",
    "images",
    "ui/assets",
)


def c(key: str) -> QColor:
    return QColor(TOKENS.get(key, key))


def rgba(key: str, alpha: float) -> QColor:
    colour = QColor(TOKENS.get(key, key))
    colour.setAlphaF(max(0.0, min(1.0, alpha)))
    return colour


def mix(fg: str, pct: float, bg: str) -> QColor:
    """CSS color-mix(in srgb, fg pct%, bg)."""
    a, b = QColor(TOKENS.get(fg, fg)), QColor(TOKENS.get(bg, bg))
    k = pct / 100.0
    return QColor(
        round(a.red() * k + b.red() * (1 - k)),
        round(a.green() * k + b.green() * (1 - k)),
        round(a.blue() * k + b.blue() * (1 - k)),
    )


def mkfont(size_px: float, weight: int = 400, mono: bool = False, spacing: float = 0.0) -> QFont:
    """CSS px -> Qt font; letter-spacing is absolute px, as in the mockup."""
    f = QFont()
    f.setFamilies(MONO_FAMILIES if mono else UI_FAMILIES)
    f.setPointSizeF(size_px * 0.75)
    f.setWeight(QFont.Weight(weight))
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def ease_in_out(t: float) -> float:
    """CSS ease-in-out, close enough for decoration (cubic in-out)."""
    t = max(0.0, min(1.0, t))
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


# ============================================================
# Asset resolution — repository- and PyInstaller-safe
# ============================================================


def _roots() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    roots = [here, os.path.dirname(here)]
    bundled = getattr(sys, "_MEIPASS", None)  # PyInstaller one-file runtime
    if bundled:
        roots.insert(0, bundled)
    frozen_dir = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv else None
    if frozen_dir and frozen_dir not in roots:
        roots.append(frozen_dir)
    return roots


def find_logo(explicit: str | None = None) -> str | None:
    """Locate the MYELIN logo asset. Never guesses at pixels — returns a path."""
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    for root in _roots():
        for folder in LOGO_DIRS:
            for name in LOGO_FILENAMES:
                candidate = os.path.normpath(os.path.join(root, folder, name))
                if os.path.isfile(candidate):
                    return candidate
    return None


# ============================================================
# Decorative background — neuron/axon network
# ============================================================


class NeuronField(QWidget):
    """10x6 jittered node grid, 2 nearest-neighbour edges, travelling pulses.

    Decorative only: no biological, neurological, diagnostic or evidence
    meaning is implied by anything drawn here.
    """

    COLS, ROWS = 10, 6
    JITTER = 60.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._nodes: list[tuple[float, float, float]] = []
        self._edges: list[tuple[int, int]] = []
        self._pulses: list[list] = []
        self._frame = QTimer(self)
        self._frame.timeout.connect(self._tick)
        self._spawn = QTimer(self)
        self._spawn.timeout.connect(self._spawn_pulse)

    def start(self) -> None:
        if not self._frame.isActive():
            self._frame.start(33)
        if not self._spawn.isActive():
            self._spawn.start(220)

    def stop(self) -> None:
        self._frame.stop()
        self._spawn.stop()
        self._pulses.clear()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._build()

    def _build(self) -> None:
        w, h = max(1, self.width()), max(1, self.height())
        self._nodes = [
            (
                (col / (self.COLS - 1)) * w + (random.random() - 0.5) * self.JITTER,
                (row / (self.ROWS - 1)) * h + (random.random() - 0.5) * self.JITTER,
                1.2 + random.random() * 1.4,
            )
            for row in range(self.ROWS)
            for col in range(self.COLS)
        ]
        self._edges = []
        for i, n in enumerate(self._nodes):
            nearest = sorted(
                (
                    (math.hypot(n[0] - m[0], n[1] - m[1]), j)
                    for j, m in enumerate(self._nodes)
                    if j != i
                )
            )[:2]
            self._edges.extend((i, j) for _, j in nearest)
        self._pulses = []

    def _spawn_pulse(self) -> None:
        if not self._edges:
            return
        a, b = random.choice(self._edges)
        self._pulses.append([a, b, 0.0, 0.008 + random.random() * 0.01])

    def _tick(self) -> None:
        for p in self._pulses:
            p[2] += p[3]
        self._pulses = [p for p in self._pulses if p[2] < 1.0]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._nodes:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(0.5)  # #bgCanvas { opacity: 0.5 }

        pen = QPen(rgba("cyan", 0.08))
        pen.setWidthF(1.0)
        p.setPen(pen)
        for a, b in self._edges:
            na, nb = self._nodes[a], self._nodes[b]
            p.drawLine(QPointF(na[0], na[1]), QPointF(nb[0], nb[1]))

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rgba("cyan", 0.18))
        for x, y, r in self._nodes:
            p.drawEllipse(QPointF(x, y), r, r)

        for a, b, t, _speed in self._pulses:
            na, nb = self._nodes[a], self._nodes[b]
            point = QPointF(na[0] + (nb[0] - na[0]) * t, na[1] + (nb[1] - na[1]) * t)
            grad = QRadialGradient(point, 6.0)
            grad.setColorAt(0.0, rgba("cyan", 0.8))
            grad.setColorAt(1.0, rgba("cyan", 0.0))
            p.setBrush(QBrush(grad))
            p.drawEllipse(point, 6.0, 6.0)
        p.end()


class CornerTrace(QWidget):
    """220x60 corner circuit trace with a looping signal pulse (3.6s)."""

    W, H = 220.0, 60.0
    DURATION_MS = 3600

    def __init__(self, rotated: bool = False, delay_ms: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(int(self.W), int(self.H))
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._rotated = rotated
        self._t = -delay_ms / self.DURATION_MS
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._line1 = self._path([(0, 46), (30, 46), (48, 26), (80, 26), (80, 12)])
        self._line2 = self._path([(10, 14), (40, 14), (56, 30), (120, 30)])
        self._motion = self._path(
            [(0, 46), (30, 46), (48, 26), (80, 26), (80, 30), (200, 30)]
        )
        self._nodes = ((10, 14), (48, 26), (0, 46))

    @staticmethod
    def _path(points) -> QPainterPath:
        path = QPainterPath(QPointF(*points[0]))
        for point in points[1:]:
            path.lineTo(QPointF(*point))
        return path

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start(33)

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._t += 33.0 / self.DURATION_MS
        if self._t > 1.0:
            self._t -= 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(0.55)  # .corner-trace { opacity: .55 }
        if self._rotated:  # .br { transform: rotate(180deg) }
            p.translate(self.W, self.H)
            p.rotate(180)

        pen = QPen(c("border"))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self._line1)
        p.drawPath(self._line2)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c("muted"))
        for x, y in self._nodes:
            p.drawEllipse(QPointF(x, y), 2.0, 2.0)

        if self._timer.isActive() and self._t >= 0.0:
            point = self._motion.pointAtPercent(min(1.0, self._t))
            glow = QRadialGradient(point, 6.0)  # drop-shadow(0 0 4px cyan .6)
            glow.setColorAt(0.0, rgba("cyan", 0.6))
            glow.setColorAt(1.0, rgba("cyan", 0.0))
            p.setBrush(QBrush(glow))
            p.drawEllipse(point, 6.0, 6.0)
            p.setBrush(c("cyan"))
            p.drawEllipse(point, 2.6, 2.6)
        p.end()


# ============================================================
# Logo badge — real asset behind a pulsing glow
# ============================================================


class LogoBadge(QWidget):
    """260x240 logo plate: pulsing radial glow (3.2s) + the MYELIN asset."""

    SIZE = QSize(260, 240)
    DURATION_MS = 3200

    def __init__(self, logo_path: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self.logo_path = find_logo(logo_path)
        self._pixmap = QPixmap()
        if self.logo_path:
            source = QPixmap(self.logo_path)
            if source.isNull():
                sys.stderr.write(
                    "[MYELIN] loading screen: could not decode logo asset at %s; "
                    "falling back to the drawn mark.\n" % self.logo_path
                )
            else:
                ratio = self.devicePixelRatioF() or 1.0
                self._pixmap = source.scaled(
                    QSize(int(self.SIZE.width() * ratio), int(self.SIZE.height() * ratio)),
                    Qt.AspectRatioMode.KeepAspectRatio,  # CSS object-fit: contain
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._pixmap.setDevicePixelRatio(ratio)
        else:
            sys.stderr.write(
                "[MYELIN] loading screen: logo asset not found (looked for %s under %s); "
                "falling back to the drawn mark.\n"
                % (", ".join(LOGO_FILENAMES), ", ".join(LOGO_DIRS))
            )

    @property
    def has_asset(self) -> bool:
        return not self._pixmap.isNull()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start(33)

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._phase = (self._phase + 33.0 / self.DURATION_MS) % 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # @keyframes pulseGlow: 0/100% opacity .7 scale .97, 50% opacity 1 scale 1.04
        wave = ease_in_out(1.0 - abs(self._phase * 2.0 - 1.0))
        opacity = 0.7 + 0.3 * wave
        scale = 0.97 + 0.07 * wave

        centre = QPointF(self.width() / 2.0, self.height() / 2.0)
        radius = (max(self.width(), self.height()) / 2.0 + 30) * scale
        glow = QRadialGradient(centre, radius)
        glow.setColorAt(0.0, QColor(56, 189, 248, int(0.28 * 255)))
        glow.setColorAt(0.45, QColor(167, 139, 250, int(0.12 * 255)))
        glow.setColorAt(0.70, QColor(56, 189, 248, 0))
        p.setOpacity(opacity)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(centre, radius, radius)
        p.setOpacity(1.0)

        if self.has_asset:
            size = self._pixmap.size() / (self._pixmap.devicePixelRatio() or 1.0)
            target = QPointF(
                (self.width() - size.width()) / 2.0, (self.height() - size.height()) / 2.0
            )
            # soft cyan bloom standing in for drop-shadow(0 0 22px rgba(56,189,248,.25))
            bloom = QRadialGradient(centre, max(size.width(), size.height()) / 1.9)
            bloom.setColorAt(0.0, QColor(56, 189, 248, int(0.25 * 255)))
            bloom.setColorAt(1.0, QColor(56, 189, 248, 0))
            p.setBrush(QBrush(bloom))
            p.drawEllipse(centre, size.width() / 1.9, size.height() / 1.9)
            p.drawPixmap(target, self._pixmap)
        else:
            self._draw_fallback_mark(p)
        p.end()

    def _draw_fallback_mark(self, p: QPainter) -> None:
        """Explicit 'asset missing' mark — never an empty box."""
        rect = QRectF(self.rect()).adjusted(48, 48, -48, -48)
        grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        grad.setColorAt(0.0, c("violet"))
        grad.setColorAt(1.0, c("cyan"))
        pen = QPen(QBrush(grad), 9.0)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(rect.left(), rect.top()))
        path.lineTo(QPointF(rect.center().x(), rect.bottom()))
        path.lineTo(QPointF(rect.right(), rect.top()))
        p.drawPath(path)
        p.setPen(c("muted"))
        p.setFont(mkfont(10, 400, mono=True, spacing=1.0))
        p.drawText(
            QRectF(0, self.height() - 18, self.width(), 16),
            Qt.AlignmentFlag.AlignHCenter,
            "logo asset not found",
        )


# ============================================================
# Indeterminate sweep bar
# ============================================================


class NeonProgressBar(QWidget):
    """One hero determinate neon progress bar. Presentation only.

    Holds no timer and simulates nothing -- ``set_progress`` is the only
    way its fill changes, driven by real startup-stage milestones from
    ``StartupSequence``.
    """

    WIDTH = 420
    HEIGHT = 14

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._percent = 0

    # Interface parity with the other decorative widgets this screen
    # start()s/stop()s in a loop; this bar has no animation of its own.
    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def set_progress(self, percent: int) -> None:
        clamped = max(0, min(100, int(percent)))
        if clamped == self._percent:
            return
        self._percent = clamped
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        radius = outer.height() / 2.0

        track = QPainterPath()
        track.addRoundedRect(outer, radius, radius)
        p.fillPath(track, c("base"))

        inner = outer.adjusted(1.5, 1.5, -1.5, -1.5)
        if self._percent > 0 and inner.width() > 0:
            fill_w = inner.width() * (self._percent / 100.0)
            fill = QRectF(inner.left(), inner.top(), fill_w, inner.height())

            glow_rect = fill.adjusted(-4, -4, 4, 4)
            glow = QPainterPath()
            glow.addRoundedRect(glow_rect, glow_rect.height() / 2.0, glow_rect.height() / 2.0)
            p.fillPath(glow, rgba("cyan", 0.22))

            clip = QPainterPath()
            clip.addRoundedRect(inner, inner.height() / 2.0, inner.height() / 2.0)
            p.save()
            p.setClipPath(clip)

            grad = QLinearGradient(fill.topLeft(), fill.topRight())
            grad.setColorAt(0.0, c("cyan-dim"))
            grad.setColorAt(1.0, c("cyan"))
            bar = QPainterPath()
            bar.addRoundedRect(fill, inner.height() / 2.0, inner.height() / 2.0)
            p.fillPath(bar, QBrush(grad))

            edge_w = min(6.0, fill.width())
            edge = QRectF(fill.right() - edge_w, fill.top(), edge_w, fill.height())
            p.fillRect(edge, rgba("text", 0.9))
            p.restore()

        pen = QPen(c("cyan"))
        pen.setWidthF(1.2)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(track)
        p.end()


# ============================================================
# The loading screen
# ============================================================


class MyelinLoadingScreen(QWidget):
    """Frameless MYELIN splash. Call :meth:`start`, then :meth:`finish`."""

    dismissed = pyqtSignal()

    DEFAULT_SIZE = QSize(1000, 720)
    DOT_INTERVAL_MS = 350  # steps(4, end) over 1.4s
    MESSAGE_INTERVAL_MS = 1800

    def __init__(
        self,
        logo_path: str | None = None,
        fullscreen: bool = False,
        messages=STATUS_MESSAGES,
        stay_on_top: bool = True,
        allow_dismiss: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        # Qt.WindowType.SplashScreen is the purpose-built splash type: on
        # Windows it carries WS_EX_TOOLWINDOW, which keeps this window off
        # the taskbar so MYELIN shows one taskbar button, not two.  This is
        # the same pair QSplashScreen itself uses.
        flags = Qt.WindowType.SplashScreen | Qt.WindowType.FramelessWindowHint
        if stay_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)

        self.setWindowTitle("MYELIN — Loading")
        self.setAutoFillBackground(False)
        self._fullscreen = fullscreen
        self._allow_dismiss = allow_dismiss
        self._messages = list(messages) or [""]
        self._message_index = 0
        self._pinned = False
        self._dot_step = 0
        self._base_text = self._messages[0]

        self.field = NeuronField(self)
        self.trace_tl = CornerTrace(False, 0, self)
        self.trace_br = CornerTrace(True, 1400, self)

        # ---- centre panel ----
        self.panel = QWidget(self)
        self.panel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.logo = LogoBadge(logo_path)
        lay.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(8 + 6)  # .logo-wrap margin-bottom + .wordmark margin-top

        wordmark = QLabel("MYELIN")
        wordmark.setFont(mkfont(44, 800, spacing=14.0))
        wordmark.setStyleSheet("color: %s; background: transparent;" % TOKENS["text"])
        wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # CSS margin-left:-14px cancels the trailing letter-space so the
        # wordmark sits optically centred rather than 7px right of centre.
        wordmark.setContentsMargins(0, 0, 14, 0)
        lay.addWidget(wordmark, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(14)

        tagline = QLabel("GUIDE – RECOVER – FOCUS")
        tagline.setFont(mkfont(13, 400, mono=True, spacing=5.0))
        tagline.setStyleSheet(
            "color: %s; background: transparent;" % rgba("cyan", 0.85).name(QColor.NameFormat.HexArgb)
        )
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setContentsMargins(0, 0, 5, 0)
        lay.addWidget(tagline, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(46)

        header_row = QWidget(self.panel)
        header_row.setFixedWidth(NeonProgressBar.WIDTH)
        header_row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        header_lay = QHBoxLayout(header_row)
        header_lay.setContentsMargins(0, 0, 0, 0)
        header_lay.setSpacing(0)

        self.loading_label = QLabel("LOADING")
        self.loading_label.setFont(mkfont(11.5, 700, mono=True, spacing=2.0))
        self.loading_label.setStyleSheet("color: %s; background: transparent;" % TOKENS["muted"])

        self.percent_label = QLabel("0%")
        self.percent_label.setFont(mkfont(11.5, 700, mono=True))
        self.percent_label.setStyleSheet("color: %s; background: transparent;" % TOKENS["cyan"])
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        header_lay.addWidget(self.loading_label, 0, Qt.AlignmentFlag.AlignLeft)
        header_lay.addStretch(1)
        header_lay.addWidget(self.percent_label, 0, Qt.AlignmentFlag.AlignRight)
        lay.addWidget(header_row, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(6)

        self.bar = NeonProgressBar()
        self._progress = 0
        lay.addWidget(self.bar, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(14)

        self.status = QLabel(self._messages[0])
        self.status.setFont(mkfont(13, 400))
        self.status.setStyleSheet("color: %s; background: transparent;" % TOKENS["muted"])
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.status, 0, Qt.AlignmentFlag.AlignHCenter)

        # ---- bottom caption ----
        self.version = QLabel(VERSION_CAPTION, self)
        self.version.setFont(mkfont(10.5, 400, mono=True, spacing=1.0))
        self.version.setStyleSheet("color: %s; background: transparent;" % TOKENS["version"])
        self.version.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # ---- timers ----
        self._dots = QTimer(self)
        self._dots.timeout.connect(self._tick_dots)
        self._cycle = QTimer(self)
        self._cycle.timeout.connect(self._tick_message)

        if not fullscreen:
            self.resize(self.DEFAULT_SIZE)

    # ---------------- lifecycle ----------------
    def start(self) -> None:
        """Show the screen and start every animation."""
        if self._fullscreen:
            self.showFullScreen()
        else:
            self._centre_on_active_screen()
            self.show()
        self.field.start()
        self.trace_tl.start()
        self.trace_br.start()
        self.logo.start()
        self.bar.start()
        self._dots.start(self.DOT_INTERVAL_MS)
        self._cycle.start(self.MESSAGE_INTERVAL_MS)
        self.raise_()
        self.activateWindow()
        QApplication.processEvents()

    def stop(self) -> None:
        """Stop every timer. Safe to call more than once."""
        for widget in (self.field, self.trace_tl, self.trace_br, self.logo, self.bar):
            widget.stop()
        self._dots.stop()
        self._cycle.stop()

    def set_status(self, text: str) -> None:
        """Pin a caller-supplied status line and stop the canned cycle."""
        self._pinned = True
        self._cycle.stop()
        self._base_text = text
        self.status.setText(text + "." * self._dot_step)
        QApplication.processEvents()

    def set_progress(self, percent: int, text: str = "") -> None:
        """Advance the determinate stage indicator. Never moves backwards.

        ``text`` is optional so a caller can bump the percentage alone; when
        given it is pinned via :meth:`set_status`, the one status authority.
        """
        clamped = max(0, min(100, int(percent)))
        if clamped < self._progress:
            return
        self._progress = clamped
        self.bar.set_progress(clamped)
        self.percent_label.setText(f"{clamped}%")
        if text:
            self.set_status(text)
        QApplication.processEvents()

    def resume_cycle(self) -> None:
        self._pinned = False
        if self.isVisible():
            self._cycle.start(self.MESSAGE_INTERVAL_MS)

    def finish(self, window: QWidget | None = None) -> None:
        """Close the splash and hand off to ``window`` (QSplashScreen-style)."""
        self.stop()
        self.close()
        if window is not None:
            window.show()
            window.raise_()
            window.activateWindow()

    # ---------------- internals ----------------
    def _centre_on_active_screen(self) -> None:
        """Place the splash on the screen under the cursor (multi-monitor safe)."""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        size = self.DEFAULT_SIZE.boundedTo(available.size() * 0.9)
        self.resize(size)
        self.move(available.center() - self.rect().center())

    def _tick_dots(self) -> None:
        self._dot_step = (self._dot_step + 1) % 4
        self.status.setText(self._base_text + "." * self._dot_step)

    def _tick_message(self) -> None:
        if self._pinned:
            return
        self._message_index = (self._message_index + 1) % len(self._messages)
        self._base_text = self._messages[self._message_index]
        self.status.setText(self._base_text + "." * self._dot_step)

    # ---------------- events ----------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.field.setGeometry(self.rect())
        self.trace_tl.move(26, 26)
        self.trace_br.move(
            self.width() - self.trace_br.width() - 26,
            self.height() - self.trace_br.height() - 26,
        )
        panel = self.panel.sizeHint()
        self.panel.setGeometry(  # .stage centres .panel exactly; .version is absolute
            int((self.width() - panel.width()) / 2),
            int((self.height() - panel.height()) / 2),
            panel.width(),
            panel.height(),
        )
        self.version.setGeometry(0, self.height() - 22 - 14, self.width(), 16)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if self._allow_dismiss and event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.stop()
            self.close()
            self.dismissed.emit()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._allow_dismiss:
            self.stop()
            self.close()
            self.dismissed.emit()

    def closeEvent(self, event) -> None:  # noqa: N802
        self.stop()  # no stray timers after the splash goes away
        super().closeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        """Full-bleed base with the radial cyan tint at 50% / 38%."""
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        centre = QPointF(rect.width() * 0.5, rect.height() * 0.38)
        radius = max(
            math.hypot(centre.x(), centre.y()),
            math.hypot(rect.width() - centre.x(), rect.height() - centre.y()),
        )
        grad = QRadialGradient(centre, radius)
        grad.setColorAt(0.0, mix("cyan", 7, "base"))
        grad.setColorAt(0.65, c("base"))
        grad.setColorAt(1.0, c("base"))
        p.fillRect(rect, QBrush(grad))
        p.end()


# ============================================================
# Standalone preview
# ============================================================


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    fullscreen = "--fullscreen" in argv
    seconds = 6.0
    if "--seconds" in argv:
        try:
            seconds = float(argv[argv.index("--seconds") + 1])
        except (IndexError, ValueError):
            pass
    logo = None
    if "--logo" in argv:
        try:
            logo = argv[argv.index("--logo") + 1]
        except IndexError:
            pass

    app = QApplication(argv)
    app.setApplicationName("MYELIN Loading")
    app.setFont(mkfont(13, 400))

    splash = MyelinLoadingScreen(logo_path=logo, fullscreen=fullscreen, allow_dismiss=True)
    splash.start()
    if splash.logo.has_asset:
        print("[MYELIN] logo asset: %s" % splash.logo.logo_path)

    QTimer.singleShot(int(seconds * 1000), splash.finish)
    QTimer.singleShot(int(seconds * 1000) + 250, app.quit)
    splash.dismissed.connect(app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())