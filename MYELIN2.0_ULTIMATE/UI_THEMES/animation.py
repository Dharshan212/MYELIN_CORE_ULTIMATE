"""Shared startup animations and Control Station custom painters.

The Engine Core ring, distraction bars, status dots and the decorative axon
network are painted here rather than in the launcher, keeping ``launcher.py``
to shell and page composition.

The axon/network animation is decorative.  It carries no biological,
neurological, diagnostic or evidence meaning.
"""
from __future__ import annotations

import math
import random

from PyQt6.QtCore import QLineF, QPointF, QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QLabel, QProgressBar, QSizePolicy, QVBoxLayout, QWidget

class _AnimatedWidget(QWidget):
    """Frame-timer base.  ``start()``/``stop()`` keep their old meaning; the
    timer additionally pauses whenever the widget is not on screen, so a
    hidden decoration cannot keep repainting at 25fps forever."""

    def __init__(self, parent=None):
        super().__init__(parent); self._phase=0; self._wanted=False; self._timer=QTimer(self); self._timer.setInterval(40); self._timer.timeout.connect(self._tick)
    def _tick(self): self._phase=(self._phase+1)%100; self.update()
    def start(self):
        self._wanted = True
        if self.isVisible() and not self._timer.isActive(): self._timer.start()
    def stop(self):
        self._wanted = False
        self._timer.stop()
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if self._wanted and not self._timer.isActive(): self._timer.start()
    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        self._timer.stop()

class LoadingBackdrop(_AnimatedWidget):
    def paintEvent(self, event):
        del event; p=QPainter(self); p.fillRect(self.rect(), QColor("#0B0F19")); p.end()

class LoadingCornerTrace(_AnimatedWidget):
    def __init__(self, *, rotated=False, delay_ms=0, parent=None):
        super().__init__(parent); self._rotated=bool(rotated); self._delay=max(0,int(delay_ms))
    def start(self):
        if self._delay: QTimer.singleShot(self._delay, super().start)
        else: super().start()
    def paintEvent(self, event):
        del event; p=QPainter(self); pen=QPen(QColor("#3DDCFF"),2); p.setPen(pen); r=self.rect().adjusted(10,10,-10,-10); p.drawLine(r.topLeft(), r.topRight() if not self._rotated else r.bottomLeft()); p.end()

class LoadingLogoBadge(QLabel):
    def __init__(self, *, logo_path: str, parent=None):
        super().__init__(parent); self.setFixedSize(112,112); self.setAlignment(__import__('PyQt6.QtCore',fromlist=['Qt']).Qt.AlignmentFlag.AlignCenter)
        pix=QPixmap(str(logo_path)); self.setPixmap(pix.scaled(96,96) if not pix.isNull() else QPixmap())
    def start(self): pass
    def stop(self): pass

class LoadingSweepBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent); self.setRange(0,0); self.setFixedSize(320,6); self.setTextVisible(False)
    def start(self): self.show()
    def stop(self): pass


class AxonCanvas(QWidget):
    """Decorative MYELIN network animation.

    Ported from the mockup's ``#axonCanvas``: a 7x4 jittered node grid, each
    node wired to its two or three nearest neighbours, with signal pulses
    travelling the edges.  It carries no biological, neurological, diagnostic
    or evidence meaning.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._nodes: list[tuple[float, float, float]] = []
        self._edges: list[tuple[int, int]] = []
        self._pulses: list[list] = []
        # Static geometry is rebuilt on resize only, never per frame.
        self._edge_lines: list[QLineF] | None = None
        self._clip_path: QPainterPath | None = None
        self._wanted = False
        self._frame = QTimer(self)
        self._frame.timeout.connect(self._tick)
        self._spawn = QTimer(self)
        self._spawn.timeout.connect(self._spawn_pulse)

    def start(self) -> None:
        self._wanted = True
        if not self.isVisible():
            return
        if not self._frame.isActive():
            self._frame.start(33)
        if not self._spawn.isActive():
            self._spawn.start(260)

    def stop(self) -> None:
        self._wanted = False
        self._frame.stop()
        self._spawn.stop()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._wanted:
            self.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        # Pause the timers but keep ``_wanted``, so the caller's intent
        # survives the page being switched away from and back to.
        super().hideEvent(event)
        self._frame.stop()
        self._spawn.stop()

    def set_reduced_motion(self, reduced: bool) -> None:
        if reduced:
            self.stop()
            self._pulses = []
            self.update()
        else:
            self.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._build()

    def _build(self) -> None:
        w, h = max(1, self.width()), max(1, self.height())
        cols, rows = 7, 4
        mx, my = w * 0.08, h * 0.12
        self._nodes = []
        for r in range(rows):
            for c in range(cols):
                jx = (random.random() - 0.5) * (w / cols) * 0.5
                jy = (random.random() - 0.5) * (h / rows) * 0.5
                self._nodes.append((
                    mx + (c / (cols - 1)) * (w - mx * 2) + jx,
                    my + (r / (rows - 1)) * (h - my * 2) + jy,
                    1.6 + random.random() * 1.6,
                ))

        self._edges = []
        seen: set[tuple[int, int]] = set()
        for i, n in enumerate(self._nodes):
            nearest = sorted(
                (
                    (math.hypot(n[0] - m[0], n[1] - m[1]), j)
                    for j, m in enumerate(self._nodes)
                    if j != i
                )
            )[: 2 + random.randint(0, 1)]
            for _, j in nearest:
                key = (min(i, j), max(i, j))
                if key not in seen:
                    seen.add(key)
                    self._edges.append(key)
        self._pulses = []
        self._rebuild_static()

    def _rebuild_static(self) -> None:
        """Cache the edge segments and the rounded clip.

        The network only changes on resize, so the per-edge ``QLineF`` list and
        the clip path are built here instead of inside every frame.  Measured
        at 900x300 with this 28-node / 50-edge network, batching the edges into
        one ``drawLines`` call is ~24% cheaper per frame than the original
        per-edge ``drawLine`` loop; the node ellipses stay a plain loop because
        that measured faster than folding them into a compound path."""

        from UI_THEMES.theme import RADIUS_LG

        self._edge_lines = [
            QLineF(
                self._nodes[a_index][0], self._nodes[a_index][1],
                self._nodes[b_index][0], self._nodes[b_index][1],
            )
            for a_index, b_index in self._edges
        ]

        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), RADIUS_LG, RADIUS_LG)
        self._clip_path = clip

    def _spawn_pulse(self) -> None:
        if not self._edges:
            return
        edge = random.choice(self._edges)
        self._pulses.append([edge, 0.0, 0.010 + random.random() * 0.012])

    def _tick(self) -> None:
        # Nothing is moving: skip the repaint entirely rather than redrawing
        # an identical frame.  The static network is already on screen.
        if not self._pulses:
            return
        for pulse in self._pulses:
            pulse[1] += pulse[2]
        self._pulses = [p for p in self._pulses if p[1] < 1.0]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        if not self._nodes:
            return
        from UI_THEMES.theme import DEFAULT_THEME, qalpha

        if self._edge_lines is None:
            self._rebuild_static()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setClipPath(self._clip_path)
        p.setOpacity(0.55)
        line = QColor(DEFAULT_THEME.cyan)

        pen = QPen(qalpha(line, 0.16))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawLines(self._edge_lines)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qalpha(line, 0.40))
        for x, y, r in self._nodes:
            p.drawEllipse(QPointF(x, y), r, r)

        for (a, b), t, _speed in self._pulses:
            na, nb = self._nodes[a], self._nodes[b]
            x = na[0] + (nb[0] - na[0]) * t
            y = na[1] + (nb[1] - na[1]) * t
            grad = QRadialGradient(QPointF(x, y), 7.0)
            grad.setColorAt(0.0, qalpha(line, 0.9))
            grad.setColorAt(1.0, qalpha(line, 0.0))
            p.setBrush(QBrush(grad))
            p.drawEllipse(QPointF(x, y), 7.0, 7.0)
        p.end()


class EngineRing(QWidget):
    """168px session ring: track plus a cyan progress arc with a soft glow."""

    SIZE = 168

    def __init__(self, progress: float = 0.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from UI_THEMES.theme import label

        self.setObjectName("plainBox")
        self.setFixedSize(self.SIZE, self.SIZE)
        self._progress = progress

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        lay.addStretch(1)
        self.time_label = label("00:00", 24, 600, "text", mono=True, spacing=1.0)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.time_label)
        caption = label("Session time", 10, 400, "muted", spacing=1.3, upper=True)
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(caption)
        lay.addStretch(1)

    def set_progress(self, value: float) -> None:
        try:
            resolved = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            resolved = 0.0
        if abs(resolved - self._progress) > 0.001:
            self._progress = resolved
            self.update()

    def set_elapsed_seconds(self, seconds: int) -> None:
        """Format live elapsed session seconds supplied by the controller."""

        seconds = max(0, int(seconds))
        minutes, secs = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        self.time_label.setText(
            "%d:%02d:%02d" % (hours, minutes, secs) if hours
            else "%02d:%02d" % (minutes, secs)
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        from UI_THEMES.theme import DEFAULT_THEME as t, qalpha

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r = self.rect().adjusted(0, 0, -1, -1)

        p.setBrush(QColor(t.surface_soft))
        pen = QPen(QColor(t.border))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawEllipse(QRectF(r))

        scale = self.SIZE / 220.0
        stroke = 6 * scale
        radius = 105 * scale
        cx = cy = self.SIZE / 2.0
        arc = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)

        track = QPen(QColor(t.border))
        track.setWidthF(stroke)
        track.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(track)
        p.drawEllipse(arc)

        span = int(-360 * 16 * self._progress)
        glow = QPen(qalpha(QColor(t.cyan), 0.16))
        glow.setWidthF(stroke + 3)
        glow.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(glow)
        p.drawArc(arc, 90 * 16, span)

        fill = QPen(QColor(t.cyan))
        fill.setWidthF(stroke)
        fill.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(fill)
        p.drawArc(arc, 90 * 16, span)
        p.end()


class BarTrack(QWidget):
    """8px rounded distraction/outcome bar."""

    def __init__(
        self,
        pct: float = 0.0,
        colour: str = "cyan",
        height: int = 8,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("plainBox")
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._pct = pct
        self._colour = colour

    def set_progress(self, pct: float, colour: str | None = None) -> None:
        """Update an existing track in place; no widget is recreated."""

        try:
            new_pct = max(0.0, min(1.0, float(pct)))
        except (TypeError, ValueError):
            new_pct = 0.0
        new_colour = self._colour if colour is None else str(colour)
        if new_pct == self._pct and new_colour == self._colour:
            return
        self._pct = new_pct
        self._colour = new_colour
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        from UI_THEMES.theme import DEFAULT_THEME as t

        roles = {
            "cyan": t.cyan, "red": t.red, "amber": t.amber,
            "green": t.green, "rose": "#FB7185", "blue": "#60A5FA",
            "muted": t.muted,
        }
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        h = self.height()
        radius = 6 if h <= 8 else 4
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.surface_soft))
        p.drawRoundedRect(QRectF(0, 0, self.width(), h), radius, radius)
        width = self.width() * max(0.0, min(1.0, self._pct))
        if width > 0:
            p.setBrush(QColor(roles.get(self._colour, self._colour)))
            p.drawRoundedRect(QRectF(0, 0, width, h), radius, radius)
        p.end()


class Dot(QWidget):
    """Small glowing status dot (cyan by default)."""

    def __init__(
        self,
        size: int = 5,
        colour: str = "cyan",
        glow: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("plainBox")
        self.setFixedSize(size + (6 if glow else 0), size + (6 if glow else 0))
        self._size = size
        self._colour = colour
        self._glow = glow
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_colour(self, colour: str) -> None:
        if colour != self._colour:
            self._colour = colour
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        from UI_THEMES.theme import DEFAULT_THEME as t, qalpha

        roles = {
            "cyan": t.cyan, "red": t.red, "amber": t.amber,
            "green": t.green, "violet": t.violet, "muted": t.muted,
        }
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        colour = QColor(roles.get(self._colour, self._colour))
        centre = QPointF(self.width() / 2, self.height() / 2)
        p.setPen(Qt.PenStyle.NoPen)
        if self._glow:
            grad = QRadialGradient(centre, self._size)
            grad.setColorAt(0.0, qalpha(colour, 0.55))
            grad.setColorAt(1.0, qalpha(colour, 0.0))
            p.setBrush(QBrush(grad))
            p.drawEllipse(centre, self._size, self._size)
        p.setBrush(colour)
        p.drawEllipse(centre, self._size / 2.0, self._size / 2.0)
        p.end()


class CircuitTrace(QWidget):
    """Header circuit-trace line art with a looping signal pulse (190x46).

    Ported exactly from the donor.  Purely decorative: it carries no
    biological, neurological, diagnostic or evidence meaning.
    """

    W, H = 190.0, 46.0
    MIN_W = 90  # below this the trace stops reading as line art and is hidden

    def __init__(self, mirrored: bool = False, delay_ms: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Horizontally compressible: the art scales with the available width
        # so a tight topbar squeezes decoration, never the wordmark.
        self.setFixedHeight(int(self.H))
        self.setMinimumWidth(self.MIN_W)
        self.setMaximumWidth(int(self.W))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._mirrored = mirrored
        self._t = -delay_ms / 3200.0
        self._wanted = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self._line1 = self._path([(0, 34), (28, 34), (44, 18), (70, 18), (70, 8)])
        self._line2 = self._path([(8, 10), (34, 10), (48, 24), (100, 24)])
        self._accent = self._path([(100, 24), (190, 24)])
        self._motion = self._path(
            [(0, 34), (28, 34), (44, 18), (70, 18), (70, 24), (190, 24)]
        )
        self._nodes = [(8, 10, 2), (44, 18, 2), (0, 34, 2), (130, 24, 1.6), (160, 24, 1.6)]

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(int(self.W), int(self.H))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.MIN_W, int(self.H))

    @staticmethod
    def _path(points) -> QPainterPath:
        path = QPainterPath(QPointF(*points[0]))
        for pt in points[1:]:
            path.lineTo(QPointF(*pt))
        return path

    def start(self) -> None:
        self._wanted = True
        if self.isVisible() and not self._timer.isActive():
            self._timer.start(33)

    def stop(self) -> None:
        self._wanted = False
        self._timer.stop()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._wanted and not self._timer.isActive():
            self._timer.start(33)

    def hideEvent(self, event) -> None:  # noqa: N802
        # BrandConsole hides the traces when the topbar gets tight; without
        # this they would keep animating off screen.
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self) -> None:
        self._t += 33.0 / 3200.0
        if self._t > 1.0:
            self._t -= 1.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        from UI_THEMES.theme import DEFAULT_THEME as t, qalpha

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(0.8)
        if self._mirrored:
            p.translate(self.width(), 0)
            p.scale(-1, 1)
        if self.W:
            p.scale(self.width() / self.W, 1.0)
        art = p.transform()

        pen = QPen(QColor(t.border))
        pen.setWidthF(1.0)
        pen.setCosmetic(True)  # stay 1px under the horizontal squeeze
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self._line1)
        p.drawPath(self._line2)

        apen = QPen(QColor(t.cyan_dim))
        apen.setWidthF(1.0)
        apen.setCosmetic(True)
        apen.setDashPattern([2, 4])
        p.setPen(apen)
        p.drawPath(self._accent)

        # Dots and the signal pulse are drawn in device space so they stay round.
        p.resetTransform()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.muted))
        for x, y, r in self._nodes:
            p.drawEllipse(art.map(QPointF(x, y)), r, r)

        if self._timer.isActive() and self._t >= 0.0:
            pt = art.map(self._motion.pointAtPercent(min(1.0, self._t)))
            glow = QRadialGradient(pt, 6.0)
            glow.setColorAt(0.0, qalpha(QColor(t.cyan), 0.55))
            glow.setColorAt(1.0, qalpha(QColor(t.cyan), 0.0))
            p.setBrush(QBrush(glow))
            p.drawEllipse(pt, 6.0, 6.0)
            p.setBrush(QColor(t.cyan))
            p.drawEllipse(pt, 2.6, 2.6)
        p.end()


class BrandMark(QWidget):
    """The MYELIN header glyph: two violet-to-cyan curves plus a centre dot.

    Repainted natively from the donor's ``SVG_BRAND_HEADER`` path data
    (``M6 30 Q13 12,20 22 T34 10`` and ``M6 10 Q13 28,20 18 T34 30``, both in
    a 40x40 view box) rather than through QtSvg, which nothing else in this
    tree depends on.
    """

    def __init__(self, size: int = 26, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        from UI_THEMES.theme import DEFAULT_THEME as t

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        scale = self.width() / 40.0
        p.scale(scale, scale)

        gradient = QLinearGradient(0, 0, 40, 40)
        gradient.setColorAt(0.0, QColor(t.violet))
        gradient.setColorAt(1.0, QColor(t.cyan))

        primary = QPainterPath(QPointF(6, 30))
        primary.quadTo(13, 12, 20, 22)
        primary.quadTo(27, 32, 34, 10)
        secondary = QPainterPath(QPointF(6, 10))
        secondary.quadTo(13, 28, 20, 18)
        secondary.quadTo(27, 8, 34, 30)

        pen = QPen(QBrush(gradient), 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setBrush(Qt.BrushStyle.NoBrush)

        p.setOpacity(0.6)
        p.setPen(pen)
        p.drawPath(secondary)

        p.setOpacity(1.0)
        p.setPen(pen)
        p.drawPath(primary)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(t.text_primary))
        p.drawEllipse(QPointF(20, 20), 2.6, 2.6)
        p.end()


class NavIcon(QWidget):
    """One 18px stroke glyph for a sidebar navigation row.

    The glyphs are the mockup's own 24x24 ``nav-row-icon`` paths, scaled to
    18px exactly as ``.nav-row-icon svg`` does.  Decorative only: the icon
    reports nothing and decides nothing.  The sidebar tells it which colour
    to wear when the checked or enabled state of its row changes, mirroring
    ``.nav-row.active .nav-row-icon`` in the stylesheet.
    """

    SIZE = 18
    VIEWBOX = 24.0

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plainBox")
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._paths = self._glyph(str(name))
        self._colour = QColor("#94A3B8")

    def set_colour(self, colour) -> None:
        resolved = QColor(colour)
        if resolved != self._colour:
            self._colour = resolved
            self.update()

    @staticmethod
    def _glyph(name: str) -> list:
        """The mockup's stroke paths for one nav row, in 24x24 user units."""

        paths: list = []
        if name == "control":
            face = QPainterPath()
            face.addEllipse(QPointF(12, 12), 9, 9)
            hands = QPainterPath()
            hands.moveTo(12, 7)
            hands.lineTo(12, 12)
            hands.lineTo(15, 14)
            paths += [face, hands]
        elif name == "study-mode":
            cover = QPainterPath()
            cover.moveTo(18, 3)
            cover.lineTo(6, 3)
            cover.cubicTo(4.9, 3, 4, 3.9, 4, 5)
            cover.lineTo(4, 19)
            cover.cubicTo(4, 20.1, 4.9, 21, 6, 21)
            cover.lineTo(18, 21)
            cover.lineTo(18, 3)
            rules = QPainterPath()
            rules.moveTo(8, 8)
            rules.lineTo(14, 8)
            rules.moveTo(8, 12)
            rules.lineTo(13, 12)
            paths += [cover, rules]
        elif name == "metric-hub":
            axes = QPainterPath()
            axes.moveTo(3, 3)
            axes.lineTo(3, 21)
            axes.lineTo(21, 21)
            trend = QPainterPath()
            trend.moveTo(7, 15)
            trend.lineTo(11, 10)
            trend.lineTo(14, 13)
            trend.lineTo(19, 6)
            paths += [axes, trend]
        elif name == "science-lab":
            flask = QPainterPath()
            flask.moveTo(9, 2)
            flask.lineTo(9, 8)
            flask.lineTo(3.4, 17.6)
            flask.cubicTo(2.6, 19.0, 3.6, 20.7, 5.2, 20.7)
            flask.lineTo(18.8, 20.7)
            flask.cubicTo(20.4, 20.7, 21.4, 19.0, 20.6, 17.6)
            flask.lineTo(15, 8)
            flask.lineTo(15, 2)
            neck = QPainterPath()
            neck.moveTo(9, 2)
            neck.lineTo(15, 2)
            paths += [flask, neck]
        elif name == "live-mirl":
            pulse = QPainterPath()
            pulse.moveTo(2, 12)
            pulse.lineTo(5, 12)
            pulse.lineTo(7, 5)
            pulse.lineTo(11, 19)
            pulse.lineTo(14, 9)
            pulse.lineTo(16, 14)
            pulse.lineTo(22, 14)
            paths.append(pulse)
        elif name == "mine":
            bubble = QPainterPath()
            bubble.moveTo(20, 4)
            bubble.lineTo(4, 4)
            bubble.lineTo(4, 16)
            bubble.lineTo(8, 16)
            bubble.lineTo(8, 20.5)
            bubble.lineTo(13, 16)
            bubble.lineTo(20, 16)
            bubble.lineTo(20, 4)
            dots = QPainterPath()
            for x in (8.5, 12.0, 15.5):
                dots.addEllipse(QPointF(x, 10), 0.85, 0.85)
            paths += [bubble, dots]
        elif name == "sensehub":
            core = QPainterPath()
            core.addEllipse(QPointF(12, 12), 2.3, 2.3)
            waves = QPainterPath()
            for radius in (5.6, 9.0):
                box = (12 - radius, 12 - radius, radius * 2, radius * 2)
                waves.arcMoveTo(*box, 50)
                waves.arcTo(*box, 50, 80)
                waves.arcMoveTo(*box, 230)
                waves.arcTo(*box, 230, 80)
            paths += [core, waves]
        elif name == "cosine":
            wave = QPainterPath()
            wave.moveTo(2, 12)
            wave.cubicTo(4, 6, 6, 6, 8, 12)
            wave.cubicTo(10, 18, 12, 18, 14, 12)
            wave.cubicTo(16, 6, 18, 6, 20, 12)
            paths.append(wave)
        return paths

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        if not self._paths:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        scale = self.SIZE / self.VIEWBOX
        p.scale(scale, scale)
        pen = QPen(self._colour)
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for path in self._paths:
            p.drawPath(path)
        p.end()


class StudyRing(QWidget):
    """210px Study countdown ring: track, cyan arc, countdown, caption.

    This is the mockup's ``.sm-ring-wrap`` -- a 220 unit viewBox, r=100, a
    7px stroke, filled clockwise from twelve o'clock.

    It is fed the Study runtime's own fields (remaining seconds, progress,
    state), so it is a Study timer ring and not a COSECANT one: while a
    planned break runs, Study is PAUSED and this ring holds still.  COSECANT's
    own state and deadline are shown separately in the telemetry panel.

    Presentation only.  The caller passes an already-formatted countdown
    string and a 0..1 fraction; the ring never reads a study runtime, never
    advances a deadline and never decides a state.
    """

    SIZE = 210

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from UI_THEMES.theme import label

        self.setObjectName("plainBox")
        self.setFixedSize(self.SIZE, self.SIZE)
        self._progress = 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addStretch(1)
        self.time_label = label("00:00", 40, 700, "text", mono=True, spacing=1.0)
        self.time_label.setObjectName("studyRingCountdown")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.time_label)
        self.caption_label = label("READY TO START", 10.5, 400, "muted", spacing=1.4)
        self.caption_label.setObjectName("studyRingCaption")
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.caption_label)
        lay.addStretch(1)

    def set_progress(self, value: float) -> None:
        try:
            resolved = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            resolved = 0.0
        if abs(resolved - self._progress) > 0.001:
            self._progress = resolved
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        from UI_THEMES.theme import DEFAULT_THEME as t, qalpha

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        scale = self.SIZE / 220.0
        stroke = 7 * scale
        radius = 100 * scale
        centre = self.SIZE / 2.0
        arc = QRectF(centre - radius, centre - radius, radius * 2, radius * 2)

        track = QPen(QColor(t.border))
        track.setWidthF(stroke)
        track.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(track)
        p.drawEllipse(arc)

        span = int(-360 * 16 * self._progress)
        if span:
            glow = QPen(qalpha(QColor(t.cyan), 0.18))
            glow.setWidthF(stroke + 4)
            glow.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(glow)
            p.drawArc(arc, 90 * 16, span)

            fill = QPen(QColor(t.cyan))
            fill.setWidthF(stroke)
            fill.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(fill)
            p.drawArc(arc, 90 * 16, span)
        p.end()


__all__ = [
    "AxonCanvas",
    "BrandMark",
    "CircuitTrace",
    "BarTrack",
    "Dot",
    "EngineRing",
    "LoadingBackdrop",
    "LoadingCornerTrace",
    "LoadingLogoBadge",
    "LoadingSweepBar",
    "NavIcon",
    "StudyRing",
]
