"""SECANT presentation adapter. No production GUI or authority is registered.

A host supplies render/close functions. Their return is not proof of display or
closure; host lifecycle events must explicitly acknowledge those facts.
"""
from dataclasses import dataclass
from enum import Enum
from uuid import uuid4
import time
from .read_model import Stage, StudyScope


class Action(str, Enum):
    RETURN_TO_STUDY = "RETURN TO STUDY"
    NEED_BREAK = "NEED BREAK"


@dataclass(frozen=True, slots=True)
class Presentation:
    stage: Stage
    color: str
    title: str
    actions: tuple[Action, ...]


def presentation(stage: Stage) -> Presentation:
    if stage is Stage.SECANT_1:
        return Presentation(stage, "blue", "Return to your Study resource", (Action.RETURN_TO_STUDY, Action.NEED_BREAK))
    if stage is Stage.SECANT_2:
        return Presentation(stage, "amber", "Your Study return is still pending", (Action.RETURN_TO_STUDY,))
    if stage is Stage.SECANT_3:
        return Presentation(stage, "red", "Return to your Study resource to recover", ())
    raise ValueError("SECANT stage required")


@dataclass(frozen=True, slots=True)
class PopupRequest:
    request_id: str
    scope: StudyScope
    episode_id: str
    stage: Stage
    at_ns: int


@dataclass(frozen=True, slots=True)
class PopupReceipt:
    request_id: str
    scope: StudyScope
    kind: str
    at_ns: int
    action: Action | None = None
    detail: str = ""
    display_id: str = ""
    sequence: int = 0
    received_at_ns: int = 0  # Transport stamps delivery; never replaces occurrence.


class PopupPresenter:
    """Presentation only: buttons emit intent, never close an episode."""

    def __init__(self, render, close, emit, *, clock_ns=time.monotonic_ns):
        self._render, self._close, self._emit = render, close, emit
        self._clock_ns = clock_ns
        self._display_id = ""
        self._sequence = 0
        self._receipts = []
        self._flushing = False
        self._action_sequence = 0
        self._request = None
        self._state = "EMPTY"
        self._last_ns = -1
        self._seen: set[str] = set()
        self._action_sent = False

    def deliver(self, request: PopupRequest) -> bool:
        if (not isinstance(request, PopupRequest) or not request.request_id.startswith("secant-popup-")
                or request.request_id in self._seen or self._state in {"REQUESTED", "DISPLAYED", "CLOSE_REQUESTED"}
                or type(request.at_ns) is not int or request.at_ns < self._last_ns):
            return False
        if self._receipts and not self.flush_receipts():
            return False  # An undelivered terminal fact cannot be orphaned.
        content = presentation(request.stage)
        self._seen.add(request.request_id)
        self._request, self._state = request, "REQUESTED"
        self._last_ns = request.at_ns
        self._action_sent = False
        self._display_id = ""
        self._sequence = 0
        try:
            self._render(request, content)
        except Exception as error:
            # The host must call displayed synchronously at factual display.
            # A render exception after display is not a never-displayed fact.
            if self._state == "REQUESTED":
                self.failed(request.request_id, self._clock_ns(), str(error))
            return False
        return True

    def _matches(self, request_id, at_ns):
        return (self._request is not None and request_id == self._request.request_id
                and type(at_ns) is int and at_ns >= self._last_ns)

    def _receipt(self, kind, at_ns, action=None, detail=""):
        self._last_ns = at_ns
        self._sequence += 1
        self._receipts.append(PopupReceipt(self._request.request_id, self._request.scope,
            kind, at_ns, action, detail, self._display_id, self._sequence))
        self.flush_receipts()

    def flush_receipts(self) -> bool:
        """Retry the same immutable envelope on failed transport, without loss."""
        if self._flushing:
            return False
        self._flushing = True
        try:
            while self._receipts:
                try:
                    accepted = self._emit(self._receipts[0])
                except Exception:
                    return False
                if accepted is False:
                    return False
                self._receipts.pop(0)
            return True
        finally:
            self._flushing = False

    def displayed(self, request_id: str, at_ns: int) -> bool:
        if (not self._matches(request_id, at_ns) or self._display_id
                or self._state not in {"REQUESTED", "CLOSE_REQUESTED"}):
            return False
        closing = self._state == "CLOSE_REQUESTED"
        self._display_id = "secant-display-" + uuid4().hex
        self._state = "CLOSE_REQUESTED" if closing else "DISPLAYED"
        self._receipt("DISPLAYED", at_ns)
        return True

    def action(self, request_id: str, action: Action, at_ns: int) -> bool:
        if (not self._matches(request_id, at_ns) or self._state != "DISPLAYED" or self._action_sent
                or not isinstance(action, Action) or action not in presentation(self._request.stage).actions):
            return False
        self._action_sent = True
        self._action_sequence = self._sequence + 1
        self._receipt("ACTION", at_ns, action)
        return True

    def request_close(self, request_id: str, at_ns: int) -> bool:
        if (self._request is None or request_id != self._request.request_id
                or type(at_ns) is not int or at_ns < self._request.at_ns
                or self._state not in {"REQUESTED", "DISPLAYED", "CLOSE_REQUESTED"}):
            return False
        self._state = "CLOSE_REQUESTED"
        try:
            self._close(request_id)
        except Exception as error:
            self._receipt("CLOSE_FAILED", self._clock_ns(), detail=str(error))
            return False
        return True

    def closed(self, request_id: str, at_ns: int) -> bool:
        if not self._matches(request_id, at_ns) or self._state not in {"DISPLAYED", "CLOSE_REQUESTED"}:
            return False
        self._state = "CLOSED"
        self._receipt("CLOSED", at_ns)
        return True

    def failed(self, request_id: str, at_ns: int, detail: str) -> bool:
        if (not self._matches(request_id, at_ns) or self._display_id
                or self._state not in {"REQUESTED", "CLOSE_REQUESTED"}):
            return False
        self._state = "FAILED"
        self._receipt("FAILED", at_ns, detail=detail)
        return True


    def action_result(self, request_id: str, accepted: bool, *, action_sequence=None) -> bool:
        if (self._request is None or request_id != self._request.request_id
                or self._state != "DISPLAYED"
                or (action_sequence is not None and action_sequence != self._action_sequence)):
            return False
        if not accepted:
            self._action_sent = False
        return True


def create_qt_presenter(emit, parent=None, *, clock_ns=time.monotonic_ns):
    """Create an inert-until-delivered SECANT GUI host on the Qt GUI thread.

    Only show/close events acknowledge presentation. Clock faces may project
    published deadlines; escalation and recovery authority never belong here.
    """
    from PyQt6.QtCore import Qt, QThread
    from CONTROL_STATION.timer_display import countdown, secant_remaining, start_frames
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout
    app = QApplication.instance()
    if app is None or QThread.currentThread() != app.thread():
        raise RuntimeError("SECANT presentation requires the QApplication GUI thread")

    class Window(QDialog):
        def __init__(self, request, content):
            super().__init__(parent)
            self.request = request
            self.authorized_close = False
            self.setWindowTitle("MYELIN SECANT")
            from UI_THEMES.theme import secant_popup_stylesheet, secant_popup_palette
            from PyQt6.QtGui import QColor
            from PyQt6.QtWidgets import QFrame, QHBoxLayout, QGraphicsDropShadowEffect, QProgressBar
            self.setObjectName("secantDialog")
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.FramelessWindowHint)
            self.setStyleSheet(secant_popup_stylesheet(content.color))
            outer = QVBoxLayout(self)
            outer.setContentsMargins(20, 20, 20, 20)
            shell = QFrame(self)
            shell.setObjectName("secantShell")
            outer.addWidget(shell)
            glow = QGraphicsDropShadowEffect(shell)
            glow.setBlurRadius(28)
            glow.setOffset(0, 0)
            glow_color = QColor(secant_popup_palette(content.color)[0])
            glow_color.setAlpha(45)
            glow.setColor(glow_color)
            shell.setGraphicsEffect(glow)
            layout = QVBoxLayout(shell)
            layout.setContentsMargins(34, 28, 34, 28)
            layout.setSpacing(18)
            def text(value, name, centered=True):
                widget = QLabel(value)
                widget.setObjectName(name)
                widget.setTextFormat(Qt.TextFormat.PlainText)
                widget.setWordWrap(True)
                if centered:
                    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
                return widget
            header = QHBoxLayout()
            eyebrow = text("●  MYELIN · SESSION ALERT", "secantEyebrow", False)
            eyebrow.setWordWrap(False)
            header.addWidget(eyebrow)
            header.addStretch()
            badge = text(f"SECANT-{int(request.stage)}", "secantBadge")
            badge.setMinimumWidth(114)
            header.addWidget(badge)
            layout.addLayout(header)
            layout.addSpacing(8)
            titles = {1: "Study focus notice", 2: "Study return pending", 3: "Study return required"}
            bodies = {
                1: "The active study block is running. Return to the registered study resource.",
                2: "The study session is still off-track. Return to the registered study resource.",
                3: "The study session remains off-track. Return to the registered study resource so recovery can be verified.",
            }
            layout.addWidget(text(titles[int(request.stage)], "secantTitle"))
            layout.addWidget(text(bodies[int(request.stage)], "secantBody"))
            self.resource = text("REGISTERED RESOURCE · Awaiting projection", "secantResource")
            self.resource.setMaximumHeight(56)
            layout.addWidget(self.resource)
            layout.addStretch(1)
            self.status = text("Awaiting SECANT projection", "secantStatus")
            layout.addWidget(self.status)
            self.buttons = []
            actions = QHBoxLayout()
            actions.setSpacing(16)
            actions.addStretch()
            for index, action in enumerate(content.actions):
                button = QPushButton(action.value)
                button.setObjectName("secantPrimary" if index == 0 else "secantSecondary")
                button.setMinimumSize(230, 58)
                button.clicked.connect(lambda _checked=False, a=action: self.act(a))
                actions.addWidget(button)
                self.buttons.append(button)
            actions.addStretch()
            if self.buttons:
                layout.addLayout(actions)
            else:
                layout.addWidget(text("NO BUTTONS · RETURN TO YOUR STUDY RESOURCE", "secantProtected"))
            layout.addSpacing(6)
            self.progress = QProgressBar()
            self.progress.setObjectName("secantProgress")
            self.progress.setTextVisible(False)
            self.progress.setFixedHeight(6)
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            layout.addWidget(self.progress)
            self.timing = text("SECANT TIMING · —", "secantTiming")
            layout.addWidget(self.timing)
            layout.addWidget(text("STUDY ACTIVE · SECANT INTERVENTION", "secantFooter"))
            self.resize(860, 560)

        def place_on_cursor_screen(self):
            # Choose the cursor's screen at presentation, as SINE does.
            screen = QApplication.screenAt(QCursor.pos()) or app.primaryScreen()
            if screen is None:
                return
            area = screen.availableGeometry()
            self.resize(min(self.width(), area.width() - 24), min(self.height(), area.height() - 24))
            self.move(
                area.x() + max(12, (area.width() - self.width()) // 2),
                area.y() + max(12, (area.height() - self.height()) // 2),
            )

        def project(self, value):
            from .read_model import SecantProjection, RecoveryPhase
            if value is None:
                self._timer_projection = None
                self.resource.setText("REGISTERED RESOURCE · Awaiting projection")
                self.status.setText("Awaiting SECANT projection")
                self.timing.setText("SECANT TIMING · —")
                self.progress.setRange(0, 1)
                self.progress.setValue(0)
                return
            if (not isinstance(value, SecantProjection) or value.scope != self.request.scope
                    or value.popup_request_id != self.request.request_id
                    or (self.request.episode_id and value.episode_id != self.request.episode_id)):
                return
            self._timer_projection = value
            if not hasattr(self, "_timer_frame"):
                self._timer_frame = start_frames(self, self._refresh_clock)
            # State and recovery remain factual. Only the escalation clock projects.
            def duration(ns):
                if ns is None:
                    return "—"
                seconds = max(0, ns // 1_000_000_000)
                return f"{seconds // 60:02d}:{seconds % 60:02d}"
            target = next((f.resource for f in value.resources
                if f.resource.key == self.request.scope.target_resource_id), None)
            resource = (target.normalized_title or target.platform_key or target.process_name) if target else "Registered Study resource"
            self.resource.setText("REGISTERED RESOURCE · " + resource)
            self.resource.setToolTip(resource)
            self.status.setText("SECANT · " + value.popup_state.replace("_", " "))
            remaining = countdown(secant_remaining(value))
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
            r = value.recovery
            if value.frozen_reasons and any(x != "recovery" for x in value.frozen_reasons):
                timing = "HOLD · " + " / ".join(value.frozen_reasons).upper() + " · " + remaining
            elif r.phase in (RecoveryPhase.VERIFYING, RecoveryPhase.CONFIRMING):
                verifying = r.phase is RecoveryPhase.VERIFYING
                elapsed = r.verification_elapsed_ns if verifying else r.closure_elapsed_ns
                target_ns = r.verification_target_ns if verifying else r.closure_target_ns
                timing = ("RETURN VERIFY " if verifying else "CLOSURE ") + duration(elapsed) + " / " + duration(target_ns)
                if target_ns is not None and target_ns > 0:
                    self.progress.setRange(0, target_ns // 1_000_000)
                    self.progress.setValue(elapsed // 1_000_000)
            elif int(value.stage) == 3:
                timing = "RED · RETURN REQUIRED"
            else:
                timing = "ESCALATION REMAINING · " + remaining
            self.timing.setText(timing)

        def _refresh_clock(self):
            from .read_model import RecoveryPhase
            value = getattr(self, "_timer_projection", None)
            if (value is None or self.authorized_close or value.terminal_reason
                    or value.frozen_reasons or value.cleanup_pending
                    or value.recovery.phase in (RecoveryPhase.VERIFYING, RecoveryPhase.CONFIRMING)
                    or int(value.stage) not in (1, 2)):
                return
            self.timing.setText("ESCALATION REMAINING · " + countdown(secant_remaining(value)))

        def act(self, action):
            if adapter.action(self.request.request_id, action, clock_ns()):
                for button in self.buttons:
                    button.setEnabled(False)

        def showEvent(self, event):
            super().showEvent(event)
            adapter.displayed(self.request.request_id, clock_ns())

        def reject(self):
            if self.authorized_close:
                self.close()

        def closeEvent(self, event):
            if self.authorized_close:
                event.accept()
            else:
                event.ignore()

    class Host:
        def __init__(self):
            self.window = None
            self.projection = None

        def render(self, request, content):
            self.window = Window(request, content)
            self.window.project(self.projection)
            self.window.place_on_cursor_screen()
            self.window.show()
            self.window.raise_()

        def set_projection(self, projection):
            from .read_model import SecantProjection
            if projection is not None and not isinstance(projection, SecantProjection):
                return
            self.projection = projection
            if self.window is not None:
                self.window.project(projection)

        def close(self, request_id):
            if self.window is None or self.window.request.request_id != request_id:
                raise RuntimeError("SECANT close identity mismatch")
            self.window.authorized_close = True
            self.window.close()
            if self.window.isVisible():
                raise RuntimeError("SECANT surface withdrawal was not factual")
            adapter.closed(request_id, clock_ns())

        def action_result(self, request_id, accepted, *, action_sequence=None):
            if not adapter.action_result(request_id, accepted, action_sequence=action_sequence):
                return False
            if self.window and not accepted:
                for button in self.window.buttons:
                    button.setEnabled(True)
            return True

    host = Host()
    adapter = PopupPresenter(host.render, host.close, emit, clock_ns=clock_ns)
    adapter.host = host
    return adapter
