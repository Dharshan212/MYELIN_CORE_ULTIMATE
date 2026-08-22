"""Safe lifecycle authority for the MYELIN Control Station.

This file owns the decisions around Start, Stop, Exit, Emergency and
Protected Red.  It combines the useful parts of the old lifecycle contracts,
confirmation surface, coordinator and Red adapter into one readable module.

Important boundary
------------------
Lifecycle decides whether a command may be sent.  It does not monitor Windows,
run SINE, stop worker threads directly, write emergency records, or invent
engine success.  The Core Engine performs the work; lifecycle waits for and
publishes factual results.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Final

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .controller import EngineStatus


START_TITLE: Final = "START MYELIN?"
START_BODY: Final = "MYELIN will begin local behavioral monitoring."
START_CANCEL: Final = "CANCEL"
START_CONFIRM: Final = "START MYELIN"

EXIT_TITLE: Final = "EXIT MYELIN?"
EXIT_BODY: Final = "The monitoring engine and any active study session will stop."
EXIT_CANCEL: Final = "CANCEL"
EXIT_CONFIRM: Final = "EXIT MYELIN"

SHUTDOWN_TIMEOUT_MS: Final = 8_000


class StartupGateResult(str, Enum):
    """Terminal result of the mandatory emergency follow-up gate."""

    CLEAR_TO_START = "clear_to_start"
    BLOCKED = "blocked"
    USER_EXITED = "user_exited"


class ConfirmationKind(str, Enum):
    START = "start"
    EXIT = "exit"


class SurfaceKind(str, Enum):
    """Only surfaces that need a Protected Red decision."""

    START_CONFIRMATION = "start_confirmation"
    EXIT_CONFIRMATION = "exit_confirmation"
    ANALYTICS_COMPOSER = "analytics_composer"
    FILE_DIALOG = "file_dialog"
    TRAY_NOTIFICATION = "tray_notification"
    TRAY_MENU = "tray_menu"
    MINI_CONTROLLER = "mini_controller"


class ActionKind(str, Enum):
    """Only actions routed or protected by the clean Control Station."""

    ENGINE_START = "engine_start"
    ENGINE_STOP = "engine_stop"
    ENGINE_PAUSE = "engine_pause"
    ENGINE_RESUME = "engine_resume"
    APPLICATION_EXIT = "application_exit"
    ADMINISTRATIVE_SHUTDOWN = "administrative_shutdown"
    EMERGENCY_EXIT = "emergency_exit"
    OS_SHUTDOWN = "os_shutdown"
    OPEN_MAIN_WINDOW = "open_main_window"
    RESTORE_FROM_TRAY = "restore_from_tray"


class ActionOutcome(str, Enum):
    """Factual result vocabulary; no value claims more than was observed."""

    CONFIRMATION_SHOWN = "confirmation_shown"
    DUPLICATE_RAISED = "duplicate_raised"
    CONFLICTING_REQUEST = "conflicting_request"
    COMMAND_DISPATCHED = "command_dispatched"
    COMMAND_REFUSED = "command_refused"
    CANCELLED = "cancelled"
    BLOCKED_BY_RED = "blocked_by_red"
    STALE_STATE = "stale_state"
    UNSUPPORTED_STATE = "unsupported_state"
    SHUTDOWN_WAITING = "shutdown_waiting"
    SHUTDOWN_AUTHORIZED = "shutdown_authorized"
    SHUTDOWN_FAILED = "shutdown_failed"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class LifecycleResult:
    """One immutable result from the lifecycle authority."""

    action: ActionKind
    outcome: ActionOutcome
    request_token: int
    observed_status: str = ""
    detail: str = ""


@dataclass(frozen=True)
class EngineStateToken:
    """Engine status plus revision, preventing stale Start confirmation."""

    status: EngineStatus
    revision: int


@dataclass(frozen=True)
class _ConfirmationSlot:
    kind: ConfirmationKind
    generation: int
    expected_engine: EngineStateToken
    surface: "LifecycleConfirmSurface"


BLOCKED_RED_SURFACES: Final = frozenset(
    {
        SurfaceKind.START_CONFIRMATION,
        SurfaceKind.EXIT_CONFIRMATION,
        SurfaceKind.ANALYTICS_COMPOSER,
        SurfaceKind.FILE_DIALOG,
        SurfaceKind.TRAY_NOTIFICATION,
    }
)

DEGRADED_RED_SURFACES: Final = frozenset(
    {
        SurfaceKind.TRAY_MENU,
        SurfaceKind.MINI_CONTROLLER,
    }
)

ALLOWED_RED_ACTIONS: Final = frozenset(
    {
        ActionKind.OPEN_MAIN_WINDOW,
        ActionKind.RESTORE_FROM_TRAY,
        ActionKind.EMERGENCY_EXIT,
        ActionKind.OS_SHUTDOWN,
    }
)


class ProtectedRedGuard(QObject):
    """Fail-closed view of the Core Engine's authoritative Red state.

    This guard never creates, closes or changes a SINE stage.  It only asks
    the controller for current truth and requests restoration when Red must
    remain visible.
    """

    state_changed = pyqtSignal(bool)
    authority_unavailable = pyqtSignal(str)

    def __init__(
        self,
        *,
        query: Callable[[], bool],
        request_restore: Callable[[], bool],
        state_signal,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._query = query
        self._request_restore = request_restore
        self._last_known: bool | None = None
        state_signal.connect(self._receive_authoritative_state)

    def is_red_protected(self) -> bool:
        """Re-query every decision; any authority failure means protected."""

        try:
            active = bool(self._query())
        except Exception as exc:
            self._publish_query_failure(exc)
            return True

        self._last_known = active
        return active

    def allow_surface(self, surface: SurfaceKind) -> bool:
        return not (
            self.is_red_protected() and surface in BLOCKED_RED_SURFACES
        )

    def allow_action(self, action: ActionKind) -> bool:
        if not self.is_red_protected():
            return True
        return action in ALLOWED_RED_ACTIONS

    def surface_is_degraded(self, surface: SurfaceKind) -> bool:
        return self.is_red_protected() and surface in DEGRADED_RED_SURFACES

    def restore_authoritative_surface(self) -> bool:
        """Request Red restoration and never manufacture success."""

        if not self.is_red_protected():
            return True
        try:
            restored = bool(self._request_restore())
        except Exception as exc:
            self.authority_unavailable.emit(type(exc).__name__[:80])
            return False
        if not restored:
            self.authority_unavailable.emit("restore_refused")
        return restored

    def refresh(self) -> bool:
        previous = self._last_known
        active = self.is_red_protected()
        if previous is None or active != previous:
            self.state_changed.emit(active)
        return active

    def _publish_query_failure(self, exc: BaseException) -> None:
        # The old adapter failed closed but forgot to publish the state change.
        # Publishing it here keeps both synchronous decisions and UI state safe.
        changed = self._last_known is not True
        self._last_known = True
        self.authority_unavailable.emit(type(exc).__name__[:80])
        if changed:
            self.state_changed.emit(True)

    def _remember(self, active: bool) -> None:
        changed = self._last_known is None or active != self._last_known
        self._last_known = active
        if changed:
            self.state_changed.emit(active)

    def _receive_authoritative_state(self, active: bool) -> None:
        self._remember(bool(active))


class LifecycleConfirmSurface(QWidget):
    """One in-window Start or Exit confirmation with no nested event loop."""

    confirmed = pyqtSignal(int)
    cancelled = pyqtSignal(int)

    def __init__(
        self,
        host: QWidget,
        *,
        kind: ConfirmationKind,
        red_query: Callable[[], bool],
    ) -> None:
        super().__init__(host)
        self._host = host
        self._kind = kind
        self._red_query = red_query
        self._generation = 0
        self._presented = False
        self._resolved = False
        self._previous_focus: QWidget | None = None

        is_start = kind is ConfirmationKind.START
        title = START_TITLE if is_start else EXIT_TITLE
        body = START_BODY if is_start else EXIT_BODY
        cancel_text = START_CANCEL if is_start else EXIT_CANCEL
        confirm_text = START_CONFIRM if is_start else EXIT_CONFIRM

        self.setObjectName(
            "startConfirmation" if is_start else "exitConfirmation"
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(title)
        self.setAccessibleDescription(body)

        card = QFrame(self)
        card.setObjectName("lifecycleConfirmationCard")
        card.setMinimumWidth(460)
        card.setMaximumWidth(560)
        card.setStyleSheet(
            "QFrame { background: #101821; border: 1px solid #29404f;"
            " border-radius: 14px; }"
            "QLabel { color: #edf7fb; border: 0; }"
        )
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 190))
        card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(32, 30, 32, 26)
        card_layout.setSpacing(14)

        title_label = QLabel(title, card)
        title_label.setWordWrap(True)
        title_label.setAccessibleName(title)
        title_label.setStyleSheet(
            "font-size: 20px; font-weight: 700; letter-spacing: 1px;"
        )
        card_layout.addWidget(title_label)

        body_label = QLabel(body, card)
        body_label.setWordWrap(True)
        body_label.setAccessibleDescription(body)
        body_label.setStyleSheet("font-size: 14px; color: #b8cad4;")
        card_layout.addWidget(body_label)
        card_layout.addSpacing(8)

        button_row = QHBoxLayout()
        button_row.setSpacing(12)
        button_row.addStretch(1)

        self.cancel_button = QPushButton(cancel_text, card)
        self.cancel_button.setObjectName("lifecycleCancelButton")
        self.cancel_button.setAccessibleName(cancel_text)
        self.cancel_button.clicked.connect(self._cancel)
        button_row.addWidget(self.cancel_button)

        self.confirm_button = QPushButton(confirm_text, card)
        self.confirm_button.setObjectName(
            "lifecycleStartButton" if is_start else "lifecycleExitButton"
        )
        self.confirm_button.setAccessibleName(confirm_text)
        self.confirm_button.setAccessibleDescription(body)
        self.confirm_button.clicked.connect(self._confirm)
        button_row.addWidget(self.confirm_button)

        card_layout.addLayout(button_row)
        self.setTabOrder(self.cancel_button, self.confirm_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.hide()

    @property
    def is_presented(self) -> bool:
        return self._presented

    def present(self, generation: int) -> None:
        """Show one generation and move keyboard focus inside the card."""

        self._generation = int(generation)
        self._resolved = False
        self._presented = True
        focus = self._host.focusWidget()
        self._previous_focus = focus if isinstance(focus, QWidget) else None
        self.setGeometry(self._host.rect())
        self._host.installEventFilter(self)
        self.show()
        self.raise_()

        # Start defaults to confirm. Exit defaults to cancel so Enter cannot
        # accidentally close MYELIN.
        default = (
            self.confirm_button
            if self._kind is ConfirmationKind.START
            else self.cancel_button
        )
        default.setFocus(Qt.FocusReason.OtherFocusReason)

    def raise_existing(self) -> None:
        if not self._presented:
            return
        self.setGeometry(self._host.rect())
        self.show()
        self.raise_()

    def dismiss(self) -> None:
        self._presented = False
        self._host.removeEventFilter(self)
        self.hide()
        previous = self._previous_focus
        self._previous_focus = None
        if previous is not None and not previous.isHidden():
            try:
                previous.setFocus(Qt.FocusReason.OtherFocusReason)
            except RuntimeError:
                return

    def _confirm(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        generation = self._generation
        self.dismiss()
        self.confirmed.emit(generation)

    def _cancel(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        generation = self._generation
        self.dismiss()
        self.cancelled.emit(generation)

    def _red_owns_keyboard(self) -> bool:
        try:
            return bool(self._red_query())
        except Exception:
            return True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            if self._red_owns_keyboard():
                event.ignore()
                return
            event.accept()
            self._cancel()
            return

        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if self._red_owns_keyboard():
                event.ignore()
                return
            event.accept()
            if self._kind is ConfirmationKind.START:
                self._confirm()
            else:
                self._cancel()
            return

        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            watched is self._host
            and event.type() == QEvent.Type.Resize
            and self._presented
        ):
            self.setGeometry(self._host.rect())
        return False

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(4, 9, 13, 218))
        painter.end()
        super().paintEvent(event)


class ShutdownBarrier:
    """Thread-safe single admission for one bounded shutdown attempt."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = False
        self._reason = ""

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    def begin(self, reason: str) -> bool:
        with self._lock:
            if self._active:
                return False
            self._active = True
            self._reason = str(reason)[:80]
            return True

    def reset(self) -> None:
        """Permit a retry only after a failed or cancelled shutdown attempt."""

        with self._lock:
            self._active = False
            self._reason = ""


class _EmergencyFollowupSurface(QWidget):
    """Mandatory presentation owned by Lifecycle, never by Persistence."""

    REASONS = (
        ("not_interested_in_working", "Not interested in working"),
        ("headache_or_eye_strain", "Headache or eye strain"),
        ("exhausted_or_sleepy", "Exhausted or sleepy"),
        ("felt_unwell", "Felt unwell"),
        ("family_responsibility", "Family responsibility"),
        ("guests_or_social_interruption", "Guests or social interruption"),
        ("went_outside", "Went outside"),
        ("medical_emergency", "Medical emergency"),
        ("technical_problem", "Technical problem"),
        ("prefer_not_to_say", "Prefer not to say"),
    )

    def __init__(self, *, parent: QWidget, completed: Callable[[StartupGateResult], None]) -> None:
        super().__init__(parent, Qt.WindowType.Dialog | Qt.WindowType.WindowTitleHint)
        self.setWindowTitle("MYELIN Emergency Follow-up")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(430)
        self._completed = completed
        self._settled = False
        layout = QVBoxLayout(self)
        title = QLabel("Before MYELIN starts", self)
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)
        layout.addWidget(QLabel("Why did you use Emergency Stop last time?", self))
        self._status = QLabel("Choose one reason. It is stored only after acceptance.", self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        for code, label in self.REASONS:
            button = QPushButton(label, self)
            button.clicked.connect(lambda _checked=False, c=code: self._submit(c))
            layout.addWidget(button)

    def _submit(self, code: str) -> None:
        if self._settled:
            return
        try:
            from PERSISTENCE.storage import record_emergency_followup_reason
            accepted = bool(record_emergency_followup_reason(code))
        except Exception:
            accepted = False
        if not accepted:
            self._status.setText("The reason was not durably accepted. Please try again.")
            return
        self._settled = True
        self.hide()
        self.deleteLater()
        self._completed(StartupGateResult.CLEAR_TO_START)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._settled:
            event.accept()
        else:
            event.ignore()
            self._status.setText("This follow-up must be completed before MYELIN starts.")


class LifecycleController(QObject):
    """The sole Control Station lifecycle action and confirmation authority."""

    action_resolved = pyqtSignal(object)  # LifecycleResult
    request_resolved = pyqtSignal(str, str)
    blocked_by_red = pyqtSignal(str)
    navigation_enabled = pyqtSignal(bool)
    exit_authorized = pyqtSignal()
    shutdown_timed_out = pyqtSignal(str)

    STARTABLE: Final = frozenset(
        {EngineStatus.IDLE, EngineStatus.STOPPED, EngineStatus.ERROR}
    )
    STOPPABLE: Final = frozenset(
        {EngineStatus.STARTING, EngineStatus.ACTIVE, EngineStatus.PAUSED}
    )

    def __init__(
        self,
        *,
        engine,
        parent: QWidget | None = None,
    ) -> None:
        if parent is None:
            raise ValueError("LifecycleController requires its Control Station host")
        super().__init__(parent)
        self._host = parent
        self._engine = engine
        self._generation = 0
        self._engine_revision = 0
        self._slot: _ConfirmationSlot | None = None
        self._resolved_tokens: set[tuple[ActionKind, int]] = set()
        self._shutdown_barrier = ShutdownBarrier()
        self._shutdown_action: ActionKind | None = None
        self._shutdown_token = 0
        self._emergency_exit_permitted = False

        self.red_guard = ProtectedRedGuard(
            query=engine.is_protected_red_active,
            request_restore=engine.request_protected_red_restore,
            state_signal=engine.protected_red_changed,
            parent=self,
        )
        self.red_guard.state_changed.connect(self._red_state_changed)

        engine.engine_status_changed.connect(self._engine_status_changed)
        engine.engine_stopped.connect(self._engine_finished)
        engine.engine_failed.connect(self._engine_failed)
        engine.emergency_completed.connect(self._emergency_completed)

        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.setSingleShot(True)
        self._shutdown_timer.timeout.connect(self._shutdown_timeout)

    # ------------------------------------------------------------------
    # Mandatory startup emergency follow-up gate
    # ------------------------------------------------------------------
    @staticmethod
    def run_startup_gate(
        *,
        parent: QWidget,
        completed: Callable[[StartupGateResult], None],
    ) -> None:
        """Run the mandatory emergency follow-up without giving UI to storage."""

        try:
            from PERSISTENCE.storage import emergency_followup_required
            required = bool(emergency_followup_required())
        except Exception:
            QTimer.singleShot(0, lambda: completed(StartupGateResult.BLOCKED))
            return
        if not required:
            QTimer.singleShot(0, lambda: completed(StartupGateResult.CLEAR_TO_START))
            return
        surface = _EmergencyFollowupSurface(parent=parent, completed=completed)
        # Parent ownership keeps the mandatory non-modal object alive.
        setattr(parent, "_myelin_emergency_followup_surface", surface)
        surface.show()
        surface.raise_()
        surface.activateWindow()

    # ------------------------------------------------------------------
    # Start and Exit confirmations
    # ------------------------------------------------------------------
    def request_start(self) -> ActionOutcome:
        return self._request_confirmation(ConfirmationKind.START)

    def request_exit(self) -> ActionOutcome:
        return self._request_confirmation(ConfirmationKind.EXIT)

    def _request_confirmation(self, kind: ConfirmationKind) -> ActionOutcome:
        if self._shutdown_barrier.active:
            return self._request_result(kind, ActionOutcome.DUPLICATE)

        surface_kind = (
            SurfaceKind.START_CONFIRMATION
            if kind is ConfirmationKind.START
            else SurfaceKind.EXIT_CONFIRMATION
        )
        if not self.red_guard.allow_surface(surface_kind):
            self._dismiss_confirmation()
            self.red_guard.restore_authoritative_surface()
            self.blocked_by_red.emit(surface_kind.value)
            return self._request_result(kind, ActionOutcome.BLOCKED_BY_RED)

        if self._slot is not None:
            self._slot.surface.raise_existing()
            outcome = (
                ActionOutcome.DUPLICATE_RAISED
                if self._slot.kind is kind
                else ActionOutcome.CONFLICTING_REQUEST
            )
            return self._request_result(kind, outcome)

        self._generation += 1
        surface = LifecycleConfirmSurface(
            self._host,
            kind=kind,
            red_query=self.red_guard.is_red_protected,
        )
        self._slot = _ConfirmationSlot(
            kind=kind,
            generation=self._generation,
            expected_engine=self._capture_engine_token(),
            surface=surface,
        )
        surface.confirmed.connect(self._confirmation_accepted)
        surface.cancelled.connect(self._confirmation_cancelled)
        surface.present(self._generation)
        self.navigation_enabled.emit(False)
        return self._request_result(kind, ActionOutcome.CONFIRMATION_SHOWN)

    def _confirmation_accepted(self, generation: int) -> None:
        slot = self._take_confirmation(generation)
        if slot is None:
            return

        if slot.kind is ConfirmationKind.START:
            self._dispatch_start(slot)
        else:
            self._dispatch_confirmed_exit(slot)
        slot.surface.deleteLater()

    def _confirmation_cancelled(self, generation: int) -> None:
        slot = self._take_confirmation(generation)
        if slot is None:
            return
        action = (
            ActionKind.ENGINE_START
            if slot.kind is ConfirmationKind.START
            else ActionKind.APPLICATION_EXIT
        )
        self._emit_result(action, ActionOutcome.CANCELLED, slot.generation)
        slot.surface.deleteLater()
        self._restore_navigation_if_safe()

    def _dispatch_start(self, slot: _ConfirmationSlot) -> LifecycleResult:
        action = ActionKind.ENGINE_START
        if not self._claim(action, slot.generation):
            return self._emit_result(action, ActionOutcome.DUPLICATE, slot.generation)
        if not self.red_guard.allow_action(action):
            self.red_guard.restore_authoritative_surface()
            self.blocked_by_red.emit(action.value)
            return self._emit_result(
                action, ActionOutcome.BLOCKED_BY_RED, slot.generation
            )

        current = self._capture_engine_token()
        if current != slot.expected_engine:
            self._restore_navigation_if_safe()
            return self._emit_result(action, ActionOutcome.STALE_STATE, slot.generation)
        if current.status not in self.STARTABLE:
            self._restore_navigation_if_safe()
            return self._emit_result(
                action, ActionOutcome.UNSUPPORTED_STATE, slot.generation
            )

        admitted = bool(self._engine.start_engine())
        outcome = (
            ActionOutcome.COMMAND_DISPATCHED
            if admitted
            else ActionOutcome.COMMAND_REFUSED
        )
        result = self._emit_result(action, outcome, slot.generation)
        self._restore_navigation_if_safe()
        return result

    def _dispatch_confirmed_exit(
        self,
        slot: _ConfirmationSlot,
    ) -> LifecycleResult:
        """Recheck Red at the action boundary before admitting Exit."""

        action = ActionKind.APPLICATION_EXIT
        if not self._claim(action, slot.generation):
            return self._emit_result(action, ActionOutcome.DUPLICATE, slot.generation)
        if not self.red_guard.allow_action(action):
            self.red_guard.restore_authoritative_surface()
            self.blocked_by_red.emit(action.value)
            return self._emit_result(
                action,
                ActionOutcome.BLOCKED_BY_RED,
                slot.generation,
            )
        return self._begin_shutdown(action, slot.generation, "confirmed_exit")

    # ------------------------------------------------------------------
    # Stop, Emergency and other shutdown entry points
    # ------------------------------------------------------------------
    def request_stop(self) -> LifecycleResult:
        self._generation += 1
        token = self._generation
        action = ActionKind.ENGINE_STOP
        if not self._claim(action, token):
            return self._emit_result(action, ActionOutcome.DUPLICATE, token)
        if not self.red_guard.allow_action(action):
            self.red_guard.restore_authoritative_surface()
            return self._emit_result(action, ActionOutcome.BLOCKED_BY_RED, token)
        if self._engine.status not in self.STOPPABLE:
            return self._emit_result(action, ActionOutcome.UNSUPPORTED_STATE, token)
        admitted = bool(self._engine.stop())
        return self._emit_result(
            action,
            (
                ActionOutcome.COMMAND_DISPATCHED
                if admitted
                else ActionOutcome.COMMAND_REFUSED
            ),
            token,
        )

    def request_emergency(self) -> LifecycleResult:
        """Bypass Red, ask Core Engine once, then wait for factual permission."""

        self._dismiss_confirmation()
        self._generation += 1
        token = self._generation
        action = ActionKind.EMERGENCY_EXIT
        if not self._claim(action, token):
            return self._emit_result(action, ActionOutcome.DUPLICATE, token)

        if not self._engine.is_session_active():
            return self._begin_shutdown(action, token, "emergency_no_session")

        admitted = bool(self._engine.emergency())
        if not admitted:
            return self._emit_result(action, ActionOutcome.COMMAND_REFUSED, token)

        if not self._shutdown_barrier.begin("emergency"):
            return self._emit_result(action, ActionOutcome.DUPLICATE, token)
        self._shutdown_action = action
        self._shutdown_token = token
        self.navigation_enabled.emit(False)
        self._shutdown_timer.start(SHUTDOWN_TIMEOUT_MS)
        return self._emit_result(action, ActionOutcome.COMMAND_DISPATCHED, token)

    def request_programmatic_shutdown(self) -> LifecycleResult:
        self._dismiss_confirmation()
        self._generation += 1
        token = self._generation
        action = ActionKind.ADMINISTRATIVE_SHUTDOWN
        if not self.red_guard.allow_action(action):
            self.red_guard.restore_authoritative_surface()
            return self._emit_result(action, ActionOutcome.BLOCKED_BY_RED, token)
        return self._begin_shutdown(action, token, "administrative_shutdown")

    def authorize_os_shutdown(self) -> LifecycleResult:
        self._dismiss_confirmation()
        self._generation += 1
        return self._begin_shutdown(
            ActionKind.OS_SHUTDOWN,
            self._generation,
            "os_shutdown",
        )

    # ------------------------------------------------------------------
    # Non-blocking shutdown barrier
    # ------------------------------------------------------------------
    def _begin_shutdown(
        self,
        action: ActionKind,
        token: int,
        reason: str,
    ) -> LifecycleResult:
        if not self._shutdown_barrier.begin(reason):
            return self._emit_result(action, ActionOutcome.DUPLICATE, token)

        self._shutdown_action = action
        self._shutdown_token = int(token)
        self.navigation_enabled.emit(False)

        if not self._engine.is_session_active():
            return self._authorize_shutdown()

        if self._engine.status in self.STOPPABLE:
            if not self._engine.stop():
                return self._fail_shutdown("Core Engine refused the stop command")

        self._shutdown_timer.start(SHUTDOWN_TIMEOUT_MS)
        return self._emit_result(action, ActionOutcome.SHUTDOWN_WAITING, token)

    def _engine_finished(self) -> None:
        if self._shutdown_barrier.active:
            self._advance_shutdown()

    def _engine_failed(self, _message: str) -> None:
        if self._shutdown_barrier.active:
            self._advance_shutdown()

    def _advance_shutdown(self) -> None:
        if self._engine.is_session_active():
            return
        if (
            self._shutdown_action is ActionKind.EMERGENCY_EXIT
            and not self._emergency_exit_permitted
        ):
            return
        self._authorize_shutdown()

    def _emergency_completed(self, exit_permitted: bool) -> None:
        if self._shutdown_action is not ActionKind.EMERGENCY_EXIT:
            return
        if not exit_permitted:
            self._fail_shutdown("Core Engine did not permit emergency exit")
            return

        self._emergency_exit_permitted = True
        self._advance_shutdown()

    def _authorize_shutdown(self) -> LifecycleResult:
        self._shutdown_timer.stop()
        action = self._shutdown_action or ActionKind.APPLICATION_EXIT
        token = self._shutdown_token
        result = self._emit_result(
            action,
            ActionOutcome.SHUTDOWN_AUTHORIZED,
            token,
        )
        self.exit_authorized.emit()
        return result

    def _shutdown_timeout(self) -> None:
        reason = self._shutdown_barrier.reason or "shutdown"
        self.shutdown_timed_out.emit(reason)
        self._fail_shutdown("Core Engine did not finish before the safety deadline")

    def _fail_shutdown(self, detail: str) -> LifecycleResult:
        self._shutdown_timer.stop()
        action = self._shutdown_action or ActionKind.APPLICATION_EXIT
        token = self._shutdown_token
        self._shutdown_barrier.reset()
        self._shutdown_action = None
        self._shutdown_token = 0
        self._emergency_exit_permitted = False
        self._restore_navigation_if_safe()
        return self._emit_result(
            action,
            ActionOutcome.SHUTDOWN_FAILED,
            token,
            detail,
        )

    # ------------------------------------------------------------------
    # Small lifecycle helpers
    # ------------------------------------------------------------------
    def _capture_engine_token(self) -> EngineStateToken:
        return EngineStateToken(self._engine.status, self._engine_revision)

    def _engine_status_changed(self, _status: EngineStatus) -> None:
        self._engine_revision += 1

    def _red_state_changed(self, active: bool) -> None:
        if active:
            if self._slot is not None:
                kind = self._slot.kind
                self._dismiss_confirmation()
                self.blocked_by_red.emit(kind.value)
            self.navigation_enabled.emit(False)
            self.red_guard.restore_authoritative_surface()
            return
        self._restore_navigation_if_safe()

    def _take_confirmation(self, generation: int) -> _ConfirmationSlot | None:
        slot = self._slot
        if slot is None or slot.generation != int(generation):
            return None
        self._slot = None
        return slot

    def _dismiss_confirmation(self) -> None:
        slot = self._slot
        self._slot = None
        if slot is not None:
            slot.surface.dismiss()
            slot.surface.deleteLater()

    def _restore_navigation_if_safe(self) -> None:
        enabled = (
            self._slot is None
            and not self._shutdown_barrier.active
            and not self.red_guard.is_red_protected()
        )
        self.navigation_enabled.emit(enabled)

    def _claim(self, action: ActionKind, token: int) -> bool:
        key = (action, int(token))
        if key in self._resolved_tokens:
            return False
        self._resolved_tokens.add(key)
        return True

    def _request_result(
        self,
        kind: ConfirmationKind,
        outcome: ActionOutcome,
    ) -> ActionOutcome:
        self.request_resolved.emit(kind.value, outcome.value)
        return outcome

    def _emit_result(
        self,
        action: ActionKind,
        outcome: ActionOutcome,
        token: int,
        detail: str = "",
    ) -> LifecycleResult:
        result = LifecycleResult(
            action=action,
            outcome=outcome,
            request_token=int(token),
            observed_status=self._engine.status.value,
            detail=" ".join(str(detail).split())[:160],
        )
        self.action_resolved.emit(result)
        return result

    def shutdown(self) -> None:
        """Remove presentation resources after shutdown is authorized."""

        self._shutdown_timer.stop()
        self._dismiss_confirmation()
