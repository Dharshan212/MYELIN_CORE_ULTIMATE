"""One Windows tray and minimize authority for MYELIN.

This file combines the useful parts of the old tray controller, state
projection, icon badge and minimize policy.

It owns:

* exactly one system-tray icon and menu;
* the in-memory status badge and factual tooltip;
* adaptive, taskbar-only and tray-only minimize behavior; and
* safe tray actions routed through existing lifecycle authorities.

Important boundary
------------------
The tray does not run a timer, change Study/COSECANT state, decide SINE, stop a
worker thread, or close the application directly.  It displays prepared facts
and requests actions from the controller or lifecycle authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Final

from PyQt6.QtCore import QEvent, QObject, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from .controller import EngineStatus
from .lifecycle import ActionKind, SurfaceKind


class MinimizeBehavior(str, Enum):
    """Validated user preference for the Windows minimize button."""

    ADAPTIVE = "adaptive"
    TASKBAR = "taskbar"
    TRAY = "tray"


class MinimizeDisposition(str, Enum):
    HIDE_TO_TRAY = "hide_to_tray"
    KEEP_IN_TASKBAR = "keep_in_taskbar"


class TrayState(str, Enum):
    IDLE = "IDLE"
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    BREAK = "BREAK"
    STOPPING = "STOPPING"
    ERROR = "ERROR"
    RED_PROTECTED = "RED PROTECTED"


STATE_ACCENT: Final = {
    TrayState.IDLE: "#94A3B8",
    TrayState.STARTING: "#38BDF8",
    TrayState.ACTIVE: "#22C55E",
    TrayState.PAUSED: "#FBBF24",
    TrayState.BREAK: "#38BDF8",
    TrayState.STOPPING: "#94A3B8",
    TrayState.ERROR: "#F43F5E",
    TrayState.RED_PROTECTED: "#F43F5E",
}

FINAL_COSECANT_STATES: Final = frozenset(
    {
        "FINAL_WAIT",
        "FINAL_LOCKED",
        "RETURN_CONFIRMING",
        "FINAL_DECISION",
    }
)


def _field(snapshot, name: str, default=None):
    """Read one prepared view field without changing its meaning."""

    if isinstance(snapshot, Mapping):
        return snapshot.get(name, default)
    return getattr(snapshot, name, default)


def _format_clock(seconds: object) -> str:
    try:
        bounded = max(0, int(seconds))
    except (TypeError, ValueError):
        bounded = 0
    hours, remainder = divmod(bounded, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _study_display_state(study) -> str:
    return str(_field(study, "display_state", "")).strip().upper()


def _cosecant_state(study) -> str:
    return str(_field(study, "cosecant_state", "")).strip().upper()


def _study_is_running(study) -> bool:
    return _study_display_state(study) in {
        "ACTIVE",
        "PAUSED",
        "BREAK",
    }


def _compose_state_badge(
    base_icon: QIcon,
    accent_hex: str,
    *,
    size: int = 32,
) -> QIcon:
    """Overlay a status dot without modifying the original ICO asset."""

    source = base_icon.pixmap(QSize(size, size))
    if source.isNull():
        return base_icon

    canvas = QPixmap(size, size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(0, 0, source)
        dot = max(6, int(size * 0.34))
        margin = max(1, int(size * 0.04))
        x = size - dot - margin
        y = size - dot - margin
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#0B0F19"))
        painter.drawEllipse(x - 2, y - 2, dot + 4, dot + 4)
        painter.setBrush(QColor(accent_hex))
        painter.drawEllipse(x, y, dot, dot)
    finally:
        painter.end()
    return QIcon(canvas)


def _derive_tray_state(
    engine_status: EngineStatus,
    study,
    *,
    red_protected: bool,
) -> TrayState:
    """Derive presentation state only; Red has highest precedence."""

    if red_protected:
        return TrayState.RED_PROTECTED
    if engine_status in {EngineStatus.ERROR, EngineStatus.EMERGENCY}:
        return TrayState.ERROR
    if engine_status is EngineStatus.STOPPING:
        return TrayState.STOPPING
    if engine_status is EngineStatus.STARTING:
        return TrayState.STARTING

    display = _study_display_state(study)
    if display == "BREAK":
        return TrayState.BREAK
    if display == "PAUSED" or engine_status is EngineStatus.PAUSED:
        return TrayState.PAUSED
    if display == "ACTIVE" or engine_status is EngineStatus.ACTIVE:
        return TrayState.ACTIVE
    return TrayState.IDLE


def _study_subject(study) -> str:
    return (
        str(_field(study, "subject", "")).strip()
        or str(_field(study, "task", "")).strip()
        or "Study"
    )


def _study_status_text(study) -> str:
    """Describe Study truth without offering a manual COSECANT bypass."""

    display = _study_display_state(study)
    cosecant = _cosecant_state(study)

    if cosecant in FINAL_COSECANT_STATES:
        if cosecant == "RETURN_CONFIRMING":
            return "Return detected - confirming continuous study presence"
        return "Return required - open the intended study resource"

    if display == "BREAK":
        if bool(_field(study, "break_complete", False)):
            return "Break complete - return to the intended study resource"
        remaining = _field(study, "break_remaining_seconds")
        if type(remaining) is int:
            return f"Break - {_format_clock(remaining)} remaining"
        return "Break in progress"

    if display in {"ACTIVE", "PAUSED"}:
        state = "Study paused" if display == "PAUSED" else "Study active"
        return (
            f"{state} - {_study_subject(study)} - "
            f"{_format_clock(_field(study, 'remaining_seconds', 0))} remaining"
        )
    if display == "COMPLETE":
        return "Study session ended"
    return "No study block running"


def _compose_tooltip(
    state: TrayState,
    engine_status: EngineStatus,
    study,
) -> str:
    """Create short factual Windows tray text from prepared snapshots."""

    if state is TrayState.RED_PROTECTED:
        return "MYELIN - Protected intervention open"
    if state is TrayState.ERROR:
        if engine_status is EngineStatus.EMERGENCY:
            return "MYELIN - Emergency shutdown"
        return "MYELIN - Engine error"
    if state is TrayState.STARTING:
        return "MYELIN - Starting"
    if state is TrayState.STOPPING:
        return "MYELIN - Stopping"
    if _study_is_running(study):
        return f"MYELIN - {_study_status_text(study)}"[:127]
    if state is TrayState.PAUSED:
        return "MYELIN - Engine paused"
    if state is TrayState.ACTIVE:
        return "MYELIN - Engine active"
    return "MYELIN - Idle"


class MinimizePolicy:
    """Pure deterministic decision; it never changes the window itself."""

    def __init__(self, behavior: MinimizeBehavior) -> None:
        self._behavior = behavior

    @property
    def behavior(self) -> MinimizeBehavior:
        return self._behavior

    def set_behavior(self, behavior: MinimizeBehavior) -> None:
        self._behavior = behavior

    def decide(
        self,
        *,
        engine_running: bool,
        study_running: bool,
        tray_enabled: bool,
        tray_available: bool,
    ) -> MinimizeDisposition:
        if not tray_enabled or not tray_available:
            return MinimizeDisposition.KEEP_IN_TASKBAR
        if self._behavior is MinimizeBehavior.TASKBAR:
            return MinimizeDisposition.KEEP_IN_TASKBAR
        if self._behavior is MinimizeBehavior.TRAY:
            return MinimizeDisposition.HIDE_TO_TRAY
        if engine_running or study_running:
            return MinimizeDisposition.HIDE_TO_TRAY
        return MinimizeDisposition.KEEP_IN_TASKBAR


class TrayController(QObject):
    """Own exactly one system-tray icon and its safe action projection."""

    blocked_by_red = pyqtSignal(str)
    availability_changed = pyqtSignal(bool)

    def __init__(
        self,
        *,
        engine,
        lifecycle,
        settings,
        parent: QWidget | None = None,
    ) -> None:
        if parent is None:
            raise ValueError("TrayController requires its Control Station host")
        super().__init__(parent)

        from UI_THEMES.theme import resource_icon

        self._host = parent
        self._engine = engine
        self._lifecycle = lifecycle
        self._settings = settings
        self._guard = lifecycle.red_guard
        self._base_icon = resource_icon("icons/Myelin_Loading_Screen.ico")
        self._engine_status = engine.status
        self._study_snapshot = None
        self._state = TrayState.IDLE
        self._enabled = True
        self._started = False
        self._destroyed = False
        self._first_notice_shown = False
        self._policy = MinimizePolicy(MinimizeBehavior.ADAPTIVE)

        # Exactly one icon is constructed. start() only shows this instance.
        self._tray = QSystemTrayIcon(self._base_icon, self)
        self._tray.activated.connect(self._tray_activated)
        self._menu = QMenu(parent)
        self._build_menu()
        self._tray.setContextMenu(self._menu)

        engine.engine_status_changed.connect(self.apply_engine_status)
        engine.study_view_changed.connect(self.apply_study_snapshot)
        self._guard.state_changed.connect(self._red_state_changed)
        parent.installEventFilter(self)

        self._load_initial_preferences()
        self.refresh()

    @property
    def state(self) -> TrayState:
        return self._state

    @property
    def is_available(self) -> bool:
        if not self._enabled or self._destroyed:
            return False
        try:
            return bool(QSystemTrayIcon.isSystemTrayAvailable())
        except Exception:
            return False

    def _load_initial_preferences(self) -> None:
        try:
            preferences = self._settings.snapshot()
        except Exception:
            return
        self._enabled = bool(_field(preferences, "tray_enabled", True))
        self.apply_minimize_behavior(
            _field(preferences, "minimize_behavior", MinimizeBehavior.ADAPTIVE)
        )

    def apply_minimize_behavior(self, behavior) -> None:
        """Apply one validated preference and reject unknown values safely."""

        try:
            validated = (
                behavior
                if isinstance(behavior, MinimizeBehavior)
                else MinimizeBehavior(str(behavior).lower())
            )
        except (TypeError, ValueError):
            validated = MinimizeBehavior.ADAPTIVE
        self._policy.set_behavior(validated)

    def set_tray_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self._tray.hide()
        elif self._started:
            self.start()

    def start(self) -> bool:
        """Show the one owned tray icon when Windows reports availability."""

        if self._destroyed:
            return False
        available = self.is_available
        self.availability_changed.emit(available)
        if not available:
            self._tray.hide()
            return False
        self._started = True
        self.refresh()
        self._tray.show()
        return True

    def _build_menu(self) -> None:
        self.action_open = QAction("Open MYELIN", self._menu)
        self.action_open.triggered.connect(self._open_window)

        # Status is intentionally read-only. Study mutations belong to the
        # authoritative Study/COSECANT interface, never the tray.
        self.action_status = QAction("No study block running", self._menu)
        self.action_status.setEnabled(False)

        self.action_pause = QAction("Pause MYELIN", self._menu)
        self.action_pause.triggered.connect(self._pause_or_resume_engine)

        self.action_stop = QAction("Stop MYELIN", self._menu)
        self.action_stop.triggered.connect(self._stop_engine)

        self.action_exit = QAction("Exit MYELIN", self._menu)
        self.action_exit.triggered.connect(self._request_exit)

        self._menu.addAction(self.action_open)
        self._menu.addSeparator()
        self._menu.addAction(self.action_status)
        self._menu.addAction(self.action_pause)
        self._menu.addAction(self.action_stop)
        self._menu.addSeparator()
        self._menu.addAction(self.action_exit)

    def apply_engine_status(self, status) -> None:
        if self._destroyed:
            return
        try:
            self._engine_status = (
                status if isinstance(status, EngineStatus) else EngineStatus(status)
            )
        except (TypeError, ValueError):
            self._engine_status = EngineStatus.ERROR
        self.refresh()

    def apply_study_snapshot(self, snapshot) -> None:
        if self._destroyed:
            return
        self._study_snapshot = snapshot
        self.refresh()

    def refresh(self) -> None:
        if self._destroyed:
            return
        red = self._guard.is_red_protected()
        self._state = _derive_tray_state(
            self._engine_status,
            self._study_snapshot,
            red_protected=red,
        )
        self._tray.setIcon(
            _compose_state_badge(
                self._base_icon,
                STATE_ACCENT[self._state],
            )
        )
        self._tray.setToolTip(
            _compose_tooltip(
                self._state,
                self._engine_status,
                self._study_snapshot,
            )
        )
        self._sync_menu(red)

    def _sync_menu(self, red: bool) -> None:
        study_running = _study_is_running(self._study_snapshot)
        self.action_status.setText(_study_status_text(self._study_snapshot))

        if study_running:
            # Do not pause only the monitor while a Study timer continues.
            self.action_pause.setText("Study controls available in MYELIN")
            self.action_pause.setEnabled(False)
        else:
            paused = self._engine_status is EngineStatus.PAUSED
            self.action_pause.setText(
                "Resume MYELIN" if paused else "Pause MYELIN"
            )
            self.action_pause.setEnabled(
                not red
                and self._engine_status
                in {EngineStatus.ACTIVE, EngineStatus.PAUSED}
            )

        self.action_stop.setEnabled(
            not red
            and not study_running
            and self._engine_status
            in {EngineStatus.STARTING, EngineStatus.ACTIVE, EngineStatus.PAUSED}
        )
        self.action_exit.setEnabled(
            self._guard.allow_surface(SurfaceKind.EXIT_CONFIRMATION)
        )
        self.action_open.setEnabled(True)
        self.action_open.setText(
            "Open MYELIN (protected)" if red else "Open MYELIN"
        )

    def _open_window(self) -> None:
        if not self._guard.allow_action(ActionKind.OPEN_MAIN_WINDOW):
            self._refuse(ActionKind.OPEN_MAIN_WINDOW)
            return
        self._host.showNormal()
        self._host.show()
        self._host.raise_()
        self._host.activateWindow()
        if self._guard.is_red_protected():
            self._guard.restore_authoritative_surface()

    def _pause_or_resume_engine(self) -> None:
        self.refresh()
        if _study_is_running(self._study_snapshot):
            self._open_window()
            return

        paused = self._engine.status is EngineStatus.PAUSED
        action = ActionKind.ENGINE_RESUME if paused else ActionKind.ENGINE_PAUSE
        if not self._guard.allow_action(action):
            self._refuse(action)
            return
        admitted = self._engine.resume() if paused else self._engine.pause()
        if not admitted:
            self.refresh()

    def _stop_engine(self) -> None:
        if not self._guard.allow_action(ActionKind.ENGINE_STOP):
            self._refuse(ActionKind.ENGINE_STOP)
            return
        self._lifecycle.request_stop()

    def _request_exit(self) -> None:
        # The confirmation belongs to the main window, so restore it first.
        self._open_window()
        if not self._guard.allow_surface(SurfaceKind.EXIT_CONFIRMATION):
            self._refuse(ActionKind.APPLICATION_EXIT)
            return
        self._lifecycle.request_exit()

    def _refuse(self, action: ActionKind) -> None:
        self.blocked_by_red.emit(action.value)
        self._guard.restore_authoritative_surface()

    def _tray_activated(
        self,
        reason: QSystemTrayIcon.ActivationReason,
    ) -> None:
        if reason is QSystemTrayIcon.ActivationReason.DoubleClick:
            self._open_window()

    def _red_state_changed(self, _active: bool) -> None:
        self.refresh()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            watched is self._host
            and event.type() == QEvent.Type.WindowStateChange
            and self._host.isMinimized()
        ):
            # Let Qt complete the native minimize first, then apply the policy.
            QTimer.singleShot(0, self._apply_minimize_decision)
        return False

    def _apply_minimize_decision(self) -> None:
        if self._destroyed or not self._host.isMinimized():
            return

        if self._guard.is_red_protected():
            # Protected Red must remain visible and cannot be hidden to tray.
            self._open_window()
            self._guard.restore_authoritative_surface()
            return

        disposition = self._policy.decide(
            engine_running=self._engine.is_session_active(),
            study_running=_study_is_running(self._study_snapshot),
            tray_enabled=self._enabled,
            tray_available=self.is_available,
        )
        if disposition is MinimizeDisposition.KEEP_IN_TASKBAR:
            return

        self._host.hide()
        self._show_first_notice()

    def _show_first_notice(self) -> bool:
        if self._first_notice_shown or not self.is_available:
            return False
        if not self._guard.allow_surface(SurfaceKind.TRAY_NOTIFICATION):
            return False

        detail = (
            "Your study block continues. Open MYELIN from the tray icon."
            if _study_is_running(self._study_snapshot)
            else "Monitoring continues. Open MYELIN from the tray icon."
        )
        self._tray.showMessage(
            "MYELIN is still running",
            detail,
            QSystemTrayIcon.MessageIcon.Information,
            4_500,
        )
        self._first_notice_shown = True
        return True

    def shutdown(self) -> None:
        """Destroy the one tray instance after lifecycle authorizes exit."""

        if self._destroyed:
            return
        self._destroyed = True
        self._host.removeEventFilter(self)
        self._tray.hide()
        self._tray.setContextMenu(None)
        self._menu.clear()
        self._menu.deleteLater()
        self._tray.deleteLater()
