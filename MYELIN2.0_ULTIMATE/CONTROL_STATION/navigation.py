"""Safe page navigation for the MYELIN Control Station.

This file owns one workspace transition, one loading overlay, its visual
animation, the navigation drawer connection, and Protected Red navigation
blocking.

Important boundary
------------------
Navigation may prepare and display an existing page.  It does not calculate
page data, change Study Mode, decide SINE state, write settings, or infer that
a page is ready.  A page with a readiness signal must publish real readiness;
otherwise the transition is rejected and the current page remains visible.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from PyQt6 import sip
from PyQt6.QtCore import (
    QElapsedTimer,
    QObject,
    QRectF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

PAGE_CONTROL: Final = "control"
PAGE_STUDY: Final = "study-mode"
PAGE_METRIC_HUB: Final = "metric-hub"
PAGE_SCIENCE_LAB: Final = "science-lab"
PAGE_LIVE_MIRL: Final = "live-mirl"
PAGE_MINE: Final = "mine"
PAGE_COSINE: Final = "cosine"
PAGE_SECANT_DASHBOARD: Final = "secant-dashboard"

PAGE_ORDER: Final = (
    PAGE_CONTROL,
    PAGE_STUDY,
    PAGE_METRIC_HUB,
    PAGE_SCIENCE_LAB,
    PAGE_LIVE_MIRL,
    PAGE_MINE,
    PAGE_COSINE,
    PAGE_SECANT_DASHBOARD,
)


@dataclass(frozen=True)
class Destination:
    """Approved text and visual behavior for one workspace."""

    label: str
    loading_title: str
    loading_subtitle: str
    show_loader: bool = True


DESTINATIONS: Final = {
    PAGE_CONTROL: Destination(
        "Control",
        "Preparing Control Station",
        "Restoring engine controls and live telemetry…",
    ),
    PAGE_STUDY: Destination(
        "Study Mode",
        "Preparing Study Mode",
        "Loading your plan, timer and live activity…",
    ),
    PAGE_METRIC_HUB: Destination(
        "Metric Hub",
        "Preparing Metric Hub",
        "Loading lifetime metrics and evidence…",
    ),
    PAGE_SCIENCE_LAB: Destination(
        "Science Lab",
        "Preparing Science Lab",
        "Loading authoritative analysis and evidence…",
    ),
    PAGE_LIVE_MIRL: Destination(
        "Live MIRL",
        "Preparing Live MIRL",
        "Synchronizing episode evidence and recovery history…",
    ),
    PAGE_MINE: Destination(
        "MINE",
        "Preparing MINE",
        "Loading messaging intervention evidence…",
    ),
    PAGE_COSINE: Destination(
        "COSINE",
        "Preparing COSINE",
        "Loading streaming activity and session insights…",
    ),
    PAGE_SECANT_DASHBOARD: Destination(
        "SECANT Dashboard",
        "Preparing SECANT",
        "Loading study-recovery evidence…",
    ),
}


def _theme_role(tokens, name: str, fallback: str) -> str:
    """Read one visual token without changing theme ownership."""

    if isinstance(tokens, Mapping):
        return str(tokens.get(name, fallback))
    return str(getattr(tokens, name.replace("-", "_"), fallback))


class MyelinLoadingSymbol(QWidget):
    """Code-generated MYELIN M used only during page transitions."""

    TICK_MS: Final = 33
    TRAVEL_CYCLE_MS: Final = 2_600
    BREATHE_CYCLE_MS: Final = 3_400

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("myelinLoadingSymbol")
        self.setAccessibleName("Animated MYELIN M")
        self.setMinimumSize(64, 64)
        self._accent = "#3DDCFF"
        self._accent_dim = "#17677A"
        self._reduced_motion = False
        self._timer = QTimer(self)
        self._timer.setInterval(self.TICK_MS)
        self._timer.timeout.connect(self.update)
        self._elapsed = QElapsedTimer()
        self._path = self._build_path()

    @staticmethod
    def _build_path() -> QPainterPath:
        # Approved 100 x 100 MYELIN M geometry from the existing interface.
        path = QPainterPath()
        path.moveTo(14, 84)
        path.lineTo(14, 20)
        path.quadTo(14, 12, 22, 16)
        path.lineTo(50, 54)
        path.lineTo(78, 16)
        path.quadTo(86, 12, 86, 20)
        path.lineTo(86, 84)
        return path

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive()

    def apply_theme(self, tokens) -> None:
        self._accent = _theme_role(tokens, "cyan", "#3DDCFF")
        self._accent_dim = _theme_role(tokens, "cyan-dim", "#17677A")
        self.update()

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        if enabled:
            self.stop()
        self.update()

    def start(self) -> None:
        if self._reduced_motion:
            return
        self._elapsed.start()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        side = min(self.width(), self.height())
        painter.translate((self.width() - side) / 2, (self.height() - side) / 2)
        painter.scale(side / 100.0, side / 100.0)

        if self._reduced_motion or not self._elapsed.isValid():
            travel = 0.0
            breathe = 1.0
        else:
            elapsed_ms = self._elapsed.elapsed()
            travel = (elapsed_ms % self.TRAVEL_CYCLE_MS) / self.TRAVEL_CYCLE_MS
            breathe_phase = (
                elapsed_ms % self.BREATHE_CYCLE_MS
            ) / self.BREATHE_CYCLE_MS
            breathe = (
                math.sin(breathe_phase * 2 * math.pi - math.pi / 2) + 1
            ) / 2

        center = QColor(self._accent)
        center.setAlphaF(0.18 + 0.12 * breathe)
        edge = QColor(center)
        edge.setAlpha(0)
        glow = QRadialGradient(50, 50, 52 + 8 * breathe)
        glow.setColorAt(0, center)
        glow.setColorAt(1, edge)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(-10, -10, 120, 120))

        base_pen = QPen(QColor(self._accent_dim), 5)
        base_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        base_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        base_color = base_pen.color()
        base_color.setAlphaF(0.55)
        base_pen.setColor(base_color)
        painter.setPen(base_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self._path)

        travel_pen = QPen(QColor(self._accent), 5)
        travel_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        travel_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        if not self._reduced_motion:
            travel_pen.setDashPattern([46 / 5, 260 / 5])
            travel_pen.setDashOffset(-(travel * 306) / 5)
        painter.setPen(travel_pen)
        painter.drawPath(self._path)

        painter.setPen(Qt.PenStyle.NoPen)
        nodes = ((14, 84), (14, 18), (50, 54), (86, 18))
        for index, (x, y) in enumerate(nodes):
            opacity = 0.9
            if not self._reduced_motion:
                phase = (travel + index * 0.18) % 1.0
                opacity = 0.25 + 0.75 * (
                    (1 - math.cos(phase * 2 * math.pi)) / 2
                )
            color = QColor(self._accent)
            color.setAlphaF(opacity)
            painter.setBrush(color)
            painter.drawEllipse(QRectF(x - 3.4, y - 3.4, 6.8, 6.8))


class MyelinLoadingOverlay(QWidget):
    """One glass loading surface for every Control Station workspace."""

    painted = pyqtSignal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("myelinLoadingOverlay")
        self.setAccessibleName("MYELIN workspace loading")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._base = QColor("#0B0F19")
        self._visible_requested = False

        self.panel = QWidget(self)
        self.panel.setObjectName("myelinLoadingPanel")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(36, 38, 36, 34)
        panel_layout.setSpacing(7)
        panel_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.symbol = MyelinLoadingSymbol(self.panel)
        self.symbol.setFixedSize(96, 96)
        panel_layout.addWidget(
            self.symbol,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

        self.title_label = QLabel(self.panel)
        self.title_label.setObjectName("myelinLoadingTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setWordWrap(True)
        panel_layout.addWidget(self.title_label)

        self.subtitle_label = QLabel(self.panel)
        self.subtitle_label.setObjectName("myelinLoadingSubtitle")
        self.subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_label.setWordWrap(True)
        panel_layout.addWidget(self.subtitle_label)

        shadow = QGraphicsDropShadowEffect(self.panel)
        shadow.setBlurRadius(60)
        shadow.setOffset(0, 20)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.panel.setGraphicsEffect(shadow)
        self.panel.setFixedWidth(390)
        self.hide()

    def set_copy(self, title: str, subtitle: str) -> None:
        self.title_label.setText(str(title))
        self.subtitle_label.setText(str(subtitle))
        self.setAccessibleDescription(f"{title}. {subtitle}")

    def apply_theme(self, tokens) -> None:
        self.symbol.apply_theme(tokens)
        self._base = QColor(_theme_role(tokens, "window_background", "#0B0F19"))
        surface = QColor(_theme_role(tokens, "surface", "#111827"))
        surface.setAlphaF(0.94)
        border = _theme_role(tokens, "border", "#334155")
        text = _theme_role(tokens, "text_primary", "#F8FAFC")
        muted = _theme_role(tokens, "muted", "#94A3B8")
        self.panel.setStyleSheet(
            "QWidget#myelinLoadingPanel {"
            f" background: {surface.name(QColor.NameFormat.HexArgb)};"
            f" border: 1px solid {border}; border-radius: 18px; }}"
            "QLabel#myelinLoadingTitle {"
            f" color: {text}; font-size: 17px; font-weight: 800;"
            " margin-top: 10px; }"
            "QLabel#myelinLoadingSubtitle {"
            f" color: {muted}; font-size: 12px; }}"
        )
        self.update()

    def set_reduced_motion(self, enabled: bool) -> None:
        self.symbol.set_reduced_motion(enabled)

    def show_overlay(self) -> None:
        self._visible_requested = True
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.symbol.start()
        self.show()
        self.raise_()

    def hide_overlay(self) -> None:
        self._visible_requested = False
        self.symbol.stop()
        self.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        height = max(235, self.panel.sizeHint().height())
        self.panel.setGeometry(
            (self.width() - self.panel.width()) // 2,
            (self.height() - height) // 2,
            self.panel.width(),
            height,
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        dim = QColor(self._base)
        dim.setAlphaF(0.58)
        painter.fillRect(self.rect(), dim)
        painter.end()
        self.painted.emit()


def grab_preparation_background(host: QWidget):
    """Capture only the underlying UI, excluding the transient loader.

    Suppression covers the synchronous grab only; no event loop is pumped.
    A cancelled/destroyed overlay is never restored by the finally block.
    """
    hidden = [overlay for overlay in host.window().findChildren(MyelinLoadingOverlay)
              if overlay.isVisible() and overlay._visible_requested]
    for overlay in hidden:
        overlay.hide()
    try:
        return host.grab()
    finally:
        for overlay in hidden:
            if not sip.isdeleted(overlay) and overlay._visible_requested:
                overlay.show()
                overlay.raise_()


@dataclass
class _ActiveTransition:
    """All resources belonging to one transition generation."""

    destination: str
    generation: int
    activate: Callable[[], None]
    show_loader: bool
    readiness_signal: object | None = None
    readiness_slot: Callable[[], None] | None = None
    ready: bool = False
    minimum_elapsed: bool = False
    activated: bool = False
    external_preparation: bool = False
    surface: bool = False
    source_page: QWidget | None = None
    cancel_preparation: Callable[[], None] | None = None
    cleanup: Callable[[], None] | None = None
    paint_slot: Callable[[], None] | None = None
    destroyed_slot: Callable[..., None] | None = None
    activating: bool = False


class NavigationController(QObject):
    """Single-flight, Protected-Red-aware workspace navigation authority."""

    page_opened = pyqtSignal(str)
    transition_started = pyqtSignal(str)
    transition_finished = pyqtSignal(str)
    transition_rejected = pyqtSignal(str, str)
    preparation_failed = pyqtSignal(str, str)
    preparations_closed = pyqtSignal()

    MINIMUM_DISPLAY_MS: Final = 180
    REDUCED_MOTION_DISPLAY_MS: Final = 80
    READINESS_TIMEOUT_MS: Final = 5_000

    def __init__(
        self,
        *,
        page_stack: QStackedWidget,
        pages: Mapping[str, QWidget],
        study_page: QWidget,
        red_guard,
        sidebar,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._page_stack = page_stack
        self._pages = dict(pages)
        self._study_page = study_page
        self._red_guard = red_guard
        self._enabled_by_lifecycle = True
        self._reduced_motion = False
        self._generation = 0
        self._active: _ActiveTransition | None = None
        self._closed = False
        self._preparers: dict[str, Callable] = {}

        if set(self._pages) != set(PAGE_ORDER):
            raise ValueError("Navigation requires exactly the approved pages")

        self.sidebar = sidebar
        self.sidebar.page_requested.connect(self.open_page)
        self.loading_overlay = MyelinLoadingOverlay(page_stack)

        self._minimum_timer = QTimer(self)
        self._minimum_timer.setSingleShot(True)
        self._minimum_timer.timeout.connect(self._minimum_finished)

        self._readiness_timer = QTimer(self)
        self._readiness_timer.setSingleShot(True)
        self._readiness_timer.timeout.connect(self._readiness_timed_out)

        red_guard.state_changed.connect(self._red_state_changed)
        page_stack.currentChanged.connect(self._stack_changed)

    def register_preparation(self, destination: str, prepare: Callable) -> None:
        """Register a real destination's post-application completion contract."""
        if destination not in self._pages:
            raise ValueError("Unknown preparation destination")
        self._preparers[destination] = prepare

    @property
    def prepared_destination(self) -> str | None:
        active = self._active
        if active is not None and active.external_preparation and active.ready:
            return active.destination
        return None

    def prepare_surface(self, *, owner: QWidget, key: str, title: str,
                        subtitle: str, prepare: Callable[[], None],
                        reveal: Callable[[], None], cleanup: Callable[[], None]) -> bool:
        """Prepare one held child surface with the existing transition owner.

        This is not page navigation and never emits page_opened or reads data.
        Hidden preparation starts after a real loader paint; reveal additionally
        waits for the established visual minimum, with generation/host checks.
        """
        if self._active is not None:
            return self._reject(key, "transition_in_progress")
        if (not self._navigation_is_allowed() or sip.isdeleted(owner)
                or self._page_stack.currentWidget() is not owner):
            return self._reject(key, "surface_not_available")
        self._generation += 1
        active = _ActiveTransition(key, self._generation, reveal, True,
                                   surface=True, source_page=owner, cleanup=cleanup)
        self._active = active
        self._watch_source(active)
        self._apply_enabled_state()
        self.close_sidebar()
        self.loading_overlay.set_copy(title, subtitle)
        self.loading_overlay.show_overlay()
        self.transition_started.emit(key)
        if self._active is not active:
            return False
        self._start_preparation_timers()

        def prepared() -> None:
            if not self._preparation_is_current(active):
                return
            try:
                prepare()
            except Exception:
                if self._active is active:
                    self._reject_active("surface_preparation_failed")
                return
            if self._preparation_is_current(active):
                self._page_became_ready(active.generation)

        self._after_loader_paint(active, prepared)
        return True

    def _start_preparation_timers(self) -> None:
        minimum = (self.REDUCED_MOTION_DISPLAY_MS if self._reduced_motion
                   else self.MINIMUM_DISPLAY_MS)
        self._minimum_timer.start(minimum)
        self._readiness_timer.start(self.READINESS_TIMEOUT_MS)

    def _after_loader_paint(self, active: _ActiveTransition, prepare: Callable) -> None:
        def painted() -> None:
            if self._active is not active:
                return
            self._disconnect_paint(active)
            QTimer.singleShot(0, lambda: prepare() if self._preparation_is_current(active) else None)
        active.paint_slot = painted
        self.loading_overlay.painted.connect(painted)
        self.loading_overlay.update()

    def _watch_source(self, active: _ActiveTransition) -> None:
        source = active.source_page
        if source is not None:
            def destroyed(*_args) -> None:
                if self._active is active:
                    self.abort()
            active.destroyed_slot = destroyed
            source.destroyed.connect(destroyed)

    def _preparation_is_current(self, active: _ActiveTransition) -> bool:
        if self._active is not active:
            return False
        source = active.source_page
        if (self._closed or not self._navigation_is_allowed()
                or source is None or sip.isdeleted(source)
                or self._page_stack.currentWidget() is not source):
            self.abort()
            return False
        return True

    def _stack_changed(self, _index: int) -> None:
        active = self._active
        if (active is not None and not active.activating
                and active.source_page is not None
                and self._page_stack.currentWidget() is not active.source_page):
            self.abort()

    @property
    def sidebar_is_open(self) -> bool:
        return self.sidebar.is_open

    @property
    def is_transitioning(self) -> bool:
        return self._active is not None

    def apply_theme(self, tokens) -> None:
        self.loading_overlay.apply_theme(tokens)
        sidebar_apply_theme = getattr(self.sidebar, "apply_theme", None)
        if callable(sidebar_apply_theme):
            sidebar_apply_theme(tokens)

    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
        self.loading_overlay.set_reduced_motion(enabled)

    def set_enabled(self, enabled: bool) -> None:
        """Apply lifecycle permission without overriding Protected Red."""

        self._enabled_by_lifecycle = bool(enabled)
        if not enabled:
            self.abort()
        self._apply_enabled_state()
        if not enabled:
            self.close_sidebar()

    def toggle_sidebar(self) -> None:
        if not self._navigation_is_allowed():
            self._reject("sidebar", "navigation_protected")
            return
        self.sidebar.set_open(not self.sidebar.is_open)

    def close_sidebar(self) -> None:
        self.sidebar.set_open(False)

    def open_initial_page(self, page_name: str = PAGE_CONTROL) -> None:
        """Select the first page without showing a transition overlay."""

        destination = page_name if page_name in self._pages else PAGE_CONTROL
        self._activate_page(destination)

    def restore_page(self, page_name: str, *, fallback: str = PAGE_CONTROL) -> None:
        """Restore one validated preference without running page preparation."""

        destination = page_name if page_name in self._pages else fallback
        self.open_initial_page(destination)

    def open_page(self, destination: str) -> bool:
        """Safely prepare and open one approved workspace."""

        if destination not in self._pages:
            return self._reject(destination, "unknown_destination")
        if self._active is not None:
            return self._reject(destination, "transition_in_progress")
        if not self._navigation_is_allowed():
            self._red_guard.restore_authoritative_surface()
            return self._reject(destination, "protected_red_intervention")
        if self._page_stack.currentWidget() is self._pages[destination]:
            self.close_sidebar()
            return True

        # Leaving Study Mode may require its own asynchronous save/stop gate.
        if (
            self._page_stack.currentWidget() is self._study_page
            and destination != PAGE_STUDY
        ):
            return self._prepare_to_leave_study(destination)
        return self._start_transition(destination)

    def _prepare_to_leave_study(self, destination: str) -> bool:
        prepare_to_leave = getattr(self._study_page, "prepare_to_leave_async", None)
        if not callable(prepare_to_leave):
            return self._reject(destination, "study_leave_contract_missing")

        outcome = {"settled": False, "accepted": False}
        self._generation += 1
        generation = self._generation

        def completed(success: bool) -> None:
            if (outcome["settled"] or generation != self._generation
                    or not self._navigation_is_allowed()
                    or self._page_stack.currentWidget() is not self._study_page):
                return
            outcome["settled"] = True
            if success:
                outcome["accepted"] = self._start_transition(destination)
            else:
                self._reject(destination, "study_leave_refused")

        try:
            admitted = bool(prepare_to_leave(completed))
        except Exception:
            return self._reject(destination, "study_leave_failed")
        if outcome["settled"]:
            return bool(outcome["accepted"])
        return admitted

    def _start_transition(self, destination: str) -> bool:
        if self._active is not None or not self._navigation_is_allowed():
            return self._reject(destination, "preparation_no_longer_allowed")
        copy = DESTINATIONS[destination]
        page = self._pages[destination]
        self._generation += 1
        active = _ActiveTransition(
            destination=destination,
            generation=self._generation,
            activate=lambda: self._activate_page(destination),
            show_loader=copy.show_loader,
            minimum_elapsed=not copy.show_loader,
            source_page=self._page_stack.currentWidget(),
        )
        self._active = active
        self._watch_source(active)
        self._apply_enabled_state()
        self.close_sidebar()

        if copy.show_loader:
            self.loading_overlay.set_copy(
                copy.loading_title,
                copy.loading_subtitle,
            )
            self.loading_overlay.show_overlay()

        self.transition_started.emit(destination)
        if self._active is not active:
            return False

        registered = self._preparers.get(destination)
        if registered is not None:
            active.external_preparation = True
            self._start_preparation_timers()
            self._after_loader_paint(active, lambda: self._prepare_registered(active, registered))
            return True

        # Instruction: prepare exactly once. Activation below only switches
        # the QStackedWidget, fixing the old duplicate Study refresh.
        prepare, readiness_signal = self._page_preparation(page, destination)
        active.readiness_signal = readiness_signal

        if readiness_signal is not None:
            def ready() -> None:
                self._page_became_ready(active.generation)

            active.readiness_slot = ready
            readiness_signal.connect(ready)

        try:
            if prepare is not None:
                prepare()
        except Exception:
            self._reject_active("page_preparation_failed")
            return False

        # A synchronous readiness signal may already have finished the whole
        # transition while prepare() was running.
        if self._active is not active:
            return True

        if readiness_signal is None:
            QTimer.singleShot(
                0,
                lambda generation=active.generation: self._page_became_ready(
                    generation
                ),
            )
        elif not active.ready:
            self._readiness_timer.start(self.READINESS_TIMEOUT_MS)

        if copy.show_loader:
            minimum = (
                self.REDUCED_MOTION_DISPLAY_MS
                if self._reduced_motion
                else self.MINIMUM_DISPLAY_MS
            )
            self._minimum_timer.start(minimum)
        return True

    def _prepare_registered(self, active: _ActiveTransition, prepare: Callable) -> None:
        if not self._preparation_is_current(active):
            return

        def completed(success: bool, error: str = "") -> None:
            if not self._preparation_is_current(active):
                return
            if not success:
                self._reject_active(error or "page_preparation_failed")
                return
            self._page_became_ready(active.generation)

        try:
            cancel = prepare(completed)
        except Exception:
            if self._active is active:
                self._reject_active("page_preparation_failed")
            return
        if callable(cancel):
            if self._active is active:
                active.cancel_preparation = cancel
            else:
                cancel()

    def _page_preparation(
        self,
        page: QWidget,
        destination: str,
    ) -> tuple[Callable[[], None] | None, object | None]:
        if destination == PAGE_STUDY:
            prepare = getattr(page, "refresh", None)
        else:
            prepare = getattr(page, "request_refresh", None)
        prepare = prepare if callable(prepare) else None

        readiness_signal = getattr(page, "ready", None)
        if readiness_signal is not None and not hasattr(readiness_signal, "connect"):
            readiness_signal = None
        return prepare, readiness_signal

    def _page_became_ready(self, generation: int) -> None:
        active = self._active
        if active is None or active.generation != int(generation):
            return
        active.ready = True
        self._disconnect_readiness(active)
        self._readiness_timer.stop()
        self._activate_when_safe(active)

    def _activate_when_safe(self, active: _ActiveTransition) -> None:
        if self._active is not active or not active.ready or active.activated:
            return
        if active.surface:
            if not active.minimum_elapsed or not self._preparation_is_current(active):
                return
        if not self._navigation_is_allowed():
            self._red_guard.restore_authoritative_surface()
            self._reject_active("protected_red_intervention")
            return

        try:
            active.activating = True
            active.activate()
        except Exception:
            self._reject_active("page_activation_failed")
            return
        finally:
            active.activating = False
        if self._active is not active:
            return
        active.activated = True
        self._finish_when_ready(active)

    def _minimum_finished(self) -> None:
        active = self._active
        if active is None:
            return
        active.minimum_elapsed = True
        self._activate_when_safe(active)
        self._finish_when_ready(active)

    def _finish_when_ready(self, active: _ActiveTransition) -> None:
        if (
            self._active is not active
            or not active.ready
            or not active.activated
            or not active.minimum_elapsed
        ):
            return

        destination = active.destination
        self._finish_active()
        self.transition_finished.emit(destination)

    def _readiness_timed_out(self) -> None:
        # Never convert timeout into readiness. The old code opened a page after
        # five seconds even when its readiness fact never arrived.
        self._reject_active("readiness_timeout")

    def _activate_page(self, destination: str) -> None:
        page = self._pages[destination]
        self._page_stack.setCurrentWidget(page)
        self.sidebar.select(destination)
        self.page_opened.emit(destination)

    def abort(self) -> None:
        """Cancel one transition and disconnect every owned callback."""

        self._generation += 1
        if self._active is None:
            return
        self._finish_active()

    def _reject_active(self, reason: str) -> None:
        active = self._active
        if active is None:
            return
        destination = active.destination
        self._finish_active()
        self.transition_rejected.emit(destination, reason)
        if self._navigation_is_allowed():
            self.preparation_failed.emit(destination, reason)

    def _finish_active(self) -> None:
        active = self._active
        self._active = None
        self._minimum_timer.stop()
        self._readiness_timer.stop()
        if active is not None:
            self._disconnect_readiness(active)
            self._disconnect_paint(active)
            if (active.source_page is not None and not sip.isdeleted(active.source_page)
                    and active.destroyed_slot is not None):
                try:
                    active.source_page.destroyed.disconnect(active.destroyed_slot)
                except (TypeError, RuntimeError):
                    pass
            if active.cancel_preparation is not None:
                try:
                    active.cancel_preparation()
                except Exception:
                    pass
            if not active.activated and active.cleanup is not None:
                try:
                    active.cleanup()
                except Exception:
                    pass
        if not sip.isdeleted(self.loading_overlay):
            self.loading_overlay.hide_overlay()
        self._apply_enabled_state()

    def _disconnect_paint(self, active: _ActiveTransition) -> None:
        if active.paint_slot is not None and not sip.isdeleted(self.loading_overlay):
            try:
                self.loading_overlay.painted.disconnect(active.paint_slot)
            except (TypeError, RuntimeError):
                pass
        active.paint_slot = None

    @staticmethod
    def _disconnect_readiness(active: _ActiveTransition) -> None:
        if active.readiness_signal is None or active.readiness_slot is None:
            return
        try:
            active.readiness_signal.disconnect(active.readiness_slot)
        except (TypeError, RuntimeError):
            return
        finally:
            active.readiness_signal = None
            active.readiness_slot = None

    def _navigation_is_allowed(self) -> bool:
        if self._closed or not self._enabled_by_lifecycle:
            return False
        try:
            return not self._red_guard.is_red_protected()
        except Exception:
            return False

    def _apply_enabled_state(self) -> None:
        enabled = (
            self._enabled_by_lifecycle
            and self._active is None
            and self._navigation_is_allowed()
        )
        try:
            self.sidebar.set_navigation_enabled(enabled)
        except RuntimeError:
            pass  # The host may already be destroying its child widgets.

    def _red_state_changed(self, active: bool) -> None:
        if active:
            self.abort()
            self.close_sidebar()
            self._red_guard.restore_authoritative_surface()
        self._apply_enabled_state()

    def _reject(self, destination: str, reason: str) -> bool:
        self.transition_rejected.emit(str(destination), str(reason))
        return False

    def shutdown(self) -> None:
        """Stop visual timers and invalidate any unfinished transition."""

        if self._closed:
            return
        self._closed = True
        self.abort()
        self.preparations_closed.emit()
        self.close_sidebar()
        self.loading_overlay.hide_overlay()
