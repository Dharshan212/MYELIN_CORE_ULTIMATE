"""COSINE popup presentation for MYELIN.

This file draws the mascot, check-in and Welcome Back surfaces.  It emits
``CosineCommand`` objects and displays delivery status.  It never changes
COSINE state, detects a platform, writes an event or decides an outcome.

Critical acknowledgement rule
-----------------------------
A popup closes only when ``CosineRuntime.submit_command`` returns an accepted
result for the exact generation/request.  Queue failure, stale identity or a
durability failure leaves the popup open with a retry message.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from COSINE.cosine import (
    CommandKind,
    CommandResult,
    CosineChoice,
    CosineCommand,
    CosineEffect,
    EffectKind,
    PLATFORM_LABELS,
)


POPUP_SCHEMA_VERSION: Final = "myelin-cosine-popup-v1"
WELCOME_TIMEOUT_SECONDS: Final = 30


@dataclass(frozen=True, slots=True)
class PopupRequest:
    effect: CosineEffect
    submit_command: Callable[[CosineCommand], CommandResult]

    def __post_init__(self) -> None:
        if self.effect.kind not in {EffectKind.SHOW_CHECKIN, EffectKind.SHOW_WELCOME}:
            raise ValueError("PopupRequest requires a COSINE show effect")
        if not callable(self.submit_command):
            raise TypeError("submit_command must be callable")


try:
    from PyQt6.QtCore import (
        QEasingCurve,
        QObject,
        QPointF,
        QPropertyAnimation,
        QRectF,
        Qt,
        QTimer,
        pyqtProperty,
        pyqtSignal,
        pyqtSlot,
    )
    from PyQt6.QtGui import QColor, QCloseEvent, QPainter, QPen
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as _qt_failure:
    _QT_IMPORT_DETAIL = str(_qt_failure)

    class CosinePopupDispatcher:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError(
                f"COSINE popup presentation requires PyQt6: {_QT_IMPORT_DETAIL}"
            )

    def install_cosine_dispatcher(*args, **kwargs):
        raise RuntimeError(
            f"COSINE popup presentation requires PyQt6: {_QT_IMPORT_DETAIL}"
        )

else:
    class CosineMascot(QWidget):
        """Presentation-only COSINE companion with a soft blink animation."""

        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setObjectName("cosineMascot")
            self.setFixedSize(150, 130)
            self._eye_close = 0.0
            self._warmth = 0.0
            self._blink_timer = QTimer(self)
            self._blink_timer.setSingleShot(True)
            self._blink_timer.timeout.connect(self._start_blink)
            self._blink_animation = QPropertyAnimation(self, b"eyeClose", self)
            self._blink_animation.setDuration(260)
            self._blink_animation.setStartValue(0.0)
            self._blink_animation.setKeyValueAt(0.5, 1.0)
            self._blink_animation.setEndValue(0.0)
            self._blink_animation.finished.connect(self._schedule_blink)
            self._ack = QPropertyAnimation(self, b"warmth", self)
            self._ack.setDuration(420)
            self._ack.setStartValue(0.0)
            self._ack.setKeyValueAt(0.5, 1.0)
            self._ack.setEndValue(0.0)
            self._schedule_blink()

        def acknowledge(self) -> None:
            self._ack.stop()
            self._ack.start()

        def stop(self) -> None:
            self._blink_timer.stop()
            self._blink_animation.stop()
            self._ack.stop()

        def _schedule_blink(self) -> None:
            self._blink_timer.start(random.randint(2500, 5200))

        def _start_blink(self) -> None:
            self._blink_animation.stop()
            self._blink_animation.start()

        def _get_eye_close(self) -> float:
            return self._eye_close

        def _set_eye_close(self, value: float) -> None:
            self._eye_close = float(value)
            self.update()

        eyeClose = pyqtProperty(float, _get_eye_close, _set_eye_close)

        def _get_warmth(self) -> float:
            return self._warmth

        def _set_warmth(self, value: float) -> None:
            self._warmth = float(value)
            self.update()

        warmth = pyqtProperty(float, _get_warmth, _set_warmth)

        def paintEvent(self, event) -> None:  # noqa: N802
            del event
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            center = QPointF(self.width() / 2, self.height() / 2 + 4)
            glow = QColor("#6ad9ff")
            glow.setAlpha(80 + int(self._warmth * 100))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, 57, 50)
            painter.setBrush(QColor("#102b45"))
            painter.setPen(QPen(QColor("#65d7ff"), 2.5))
            painter.drawEllipse(center, 50, 44)
            eye_height = max(1.2, 9 * (1.0 - self._eye_close))
            painter.setBrush(QColor("#e8f8ff"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(48, 55, 14, eye_height))
            painter.drawEllipse(QRectF(88, 55, 14, eye_height))
            painter.setPen(QPen(QColor("#7de1ff"), 2.2))
            painter.drawArc(QRectF(59, 68, 32, 19), 205 * 16, 130 * 16)


    class _CosineDialog(QDialog):
        """Shared protected delivery surface."""

        def __init__(self, request: PopupRequest, parent=None) -> None:
            super().__init__(parent)
            self._request = request
            self._delivery_in_progress = False
            self._accepted_close = False
            self._display_acknowledged = False
            self._retry_command: tuple[CommandKind, CosineChoice | None, bool] | None = None
            self.setModal(False)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.setWindowFlag(Qt.WindowType.Tool, True)
            self.setObjectName("cosinePopup")
            self.setMinimumWidth(560)

        def _deliver(
            self,
            kind: CommandKind,
            *,
            choice: CosineChoice | None = None,
            close_after_acceptance: bool,
        ) -> bool:
            if self._delivery_in_progress:
                return False
            self._retry_command = (kind, choice, close_after_acceptance)
            self._delivery_in_progress = True
            if hasattr(self, "retry_button"):
                self.retry_button.setVisible(False)
            self._set_buttons_enabled(False)
            self.delivery_label.setText("Delivering command…")
            command = CosineCommand(
                kind=kind,
                generation=self._request.effect.generation,
                request_id=self._request.effect.request_id,
                choice=choice,
                occurred_monotonic_ns=time.monotonic_ns(),
            )
            try:
                result = self._request.submit_command(command)
            except Exception as exc:
                result = None
                detail = " ".join(str(exc).split())[:180]
            else:
                detail = result.message if isinstance(result, CommandResult) else "Invalid command result"
            self._delivery_in_progress = False
            if not isinstance(result, CommandResult) or not result.accepted:
                self.delivery_label.setText(f"NOT ACCEPTED · {detail or 'Please retry'}")
                # A failed DISPLAYED command must be retried before choices
                # become usable.  This prevents a confusing invalid action.
                self._set_buttons_enabled(
                    kind not in {CommandKind.CHECKIN_DISPLAYED, CommandKind.WELCOME_DISPLAYED}
                )
                if hasattr(self, "retry_button"):
                    self.retry_button.setVisible(True)
                return False
            self.delivery_label.setText("COMMAND ACCEPTED")
            self.mascot.acknowledge()
            if kind in {CommandKind.CHECKIN_DISPLAYED, CommandKind.WELCOME_DISPLAYED}:
                self._display_acknowledged = True
            self._delivery_accepted(kind)
            if close_after_acceptance and result.close_popup:
                self._accepted_close = True
                QTimer.singleShot(280, self.accept)
            else:
                self._set_buttons_enabled(True)
            return True

        def _retry_delivery(self) -> None:
            if self._retry_command is None:
                return
            kind, choice, close_after = self._retry_command
            self._deliver(kind, choice=choice, close_after_acceptance=close_after)

        def _delivery_accepted(self, kind: CommandKind) -> None:
            del kind

        def force_close_from_runtime(self) -> None:
            """Close only after an authoritative runtime CLOSE effect."""

            self._accepted_close = True
            self.accept()

        def reject(self) -> None:
            # User/window-manager dismissal is not a COSINE action.
            self.delivery_label.setText("Choose an action inside COSINE")

        def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
            if self._accepted_close:
                self.mascot.stop()
                event.accept()
            else:
                self.delivery_label.setText("COSINE is waiting for an accepted action")
                event.ignore()

        def _set_buttons_enabled(self, enabled: bool) -> None:
            raise NotImplementedError


    class CosineCheckinPopup(_CosineDialog):
        def __init__(self, request: PopupRequest, parent=None) -> None:
            super().__init__(request, parent)
            root = QVBoxLayout(self)
            root.setContentsMargins(30, 26, 30, 24)
            root.setSpacing(12)
            self.mascot = CosineMascot(self)
            root.addWidget(self.mascot, 0, Qt.AlignmentFlag.AlignHCenter)
            platform = PLATFORM_LABELS.get(
                request.effect.platform_key,
                request.effect.platform_key.replace("_", " ").title(),
            )
            heading = QLabel("STILL WATCHING?", self)
            heading.setObjectName("cosinePopupHeading")
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(heading)
            context = platform
            if request.effect.content_title:
                context = f"{platform} · {request.effect.content_title}"
            subtitle = QLabel(context, self)
            subtitle.setObjectName("cosinePopupContext")
            subtitle.setWordWrap(True)
            subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(subtitle)
            row = QHBoxLayout()
            self.more = QPushButton("10 MORE MIN", self)
            self.finish = QPushButton("FINISH MY SHOW", self)
            self.more.setObjectName("cosineTenMoreButton")
            self.finish.setObjectName("cosineFinishShowButton")
            self.more.clicked.connect(
                lambda: self._deliver(
                    CommandKind.CHECKIN_ACTION,
                    choice=CosineChoice.TEN_MORE_MIN,
                    close_after_acceptance=True,
                )
            )
            self.finish.clicked.connect(
                lambda: self._deliver(
                    CommandKind.CHECKIN_ACTION,
                    choice=CosineChoice.FINISH_MY_SHOW,
                    close_after_acceptance=True,
                )
            )
            row.addWidget(self.more)
            row.addWidget(self.finish)
            root.addLayout(row)
            self.delivery_label = QLabel("Awaiting display acknowledgement", self)
            self.delivery_label.setObjectName("cosineDeliveryState")
            self.delivery_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(self.delivery_label)
            self.retry_button = QPushButton("RETRY DELIVERY", self)
            self.retry_button.setVisible(False)
            self.retry_button.clicked.connect(self._retry_delivery)
            root.addWidget(self.retry_button)
            self._expiry = QTimer(self)
            self._expiry.setSingleShot(True)
            self._expiry.setInterval(5 * 60 * 1000)
            self._expiry.timeout.connect(self._expire)

        def showEvent(self, event) -> None:  # noqa: N802
            super().showEvent(event)
            if not self._display_acknowledged:
                self._deliver(
                    CommandKind.CHECKIN_DISPLAYED,
                    close_after_acceptance=False,
                )

        def _delivery_accepted(self, kind: CommandKind) -> None:
            if kind is CommandKind.CHECKIN_DISPLAYED:
                self._expiry.start()

        def _expire(self) -> None:
            accepted = self._deliver(
                CommandKind.CHECKIN_EXPIRED,
                close_after_acceptance=True,
            )
            if not accepted:
                self._expiry.start(10_000)

        def _set_buttons_enabled(self, enabled: bool) -> None:
            self.more.setEnabled(enabled)
            self.finish.setEnabled(enabled)


    class CosineWelcomePopup(_CosineDialog):
        def __init__(self, request: PopupRequest, parent=None) -> None:
            super().__init__(request, parent)
            root = QVBoxLayout(self)
            root.setContentsMargins(30, 26, 30, 24)
            root.setSpacing(12)
            self.mascot = CosineMascot(self)
            root.addWidget(self.mascot, 0, Qt.AlignmentFlag.AlignHCenter)
            heading = QLabel("WELCOME BACK", self)
            heading.setObjectName("cosineWelcomeHeading")
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(heading)
            subtitle = QLabel("How are you feeling after your show?", self)
            subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(subtitle)
            row = QHBoxLayout()
            self.yay = QPushButton("YAY", self)
            self.tired = QPushButton("I’M TIRED", self)
            self.yay.clicked.connect(
                lambda: self._deliver(
                    CommandKind.WELCOME_ACTION,
                    choice=CosineChoice.YAY,
                    close_after_acceptance=True,
                )
            )
            self.tired.clicked.connect(
                lambda: self._deliver(
                    CommandKind.WELCOME_ACTION,
                    choice=CosineChoice.IM_TIRED,
                    close_after_acceptance=True,
                )
            )
            row.addWidget(self.yay)
            row.addWidget(self.tired)
            root.addLayout(row)
            self.delivery_label = QLabel("Awaiting display acknowledgement", self)
            self.delivery_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(self.delivery_label)
            self.retry_button = QPushButton("RETRY DELIVERY", self)
            self.retry_button.setVisible(False)
            self.retry_button.clicked.connect(self._retry_delivery)
            root.addWidget(self.retry_button)
            self._expiry = QTimer(self)
            self._expiry.setSingleShot(True)
            self._expiry.setInterval(WELCOME_TIMEOUT_SECONDS * 1000)
            self._expiry.timeout.connect(self._expire)

        def showEvent(self, event) -> None:  # noqa: N802
            super().showEvent(event)
            if not self._display_acknowledged:
                self._deliver(
                    CommandKind.WELCOME_DISPLAYED,
                    close_after_acceptance=False,
                )

        def _delivery_accepted(self, kind: CommandKind) -> None:
            if kind is CommandKind.WELCOME_DISPLAYED:
                self._expiry.start()

        def _expire(self) -> None:
            accepted = self._deliver(
                CommandKind.WELCOME_EXPIRED,
                close_after_acceptance=True,
            )
            if not accepted:
                self._expiry.start(10_000)

        def _set_buttons_enabled(self, enabled: bool) -> None:
            self.yay.setEnabled(enabled)
            self.tired.setEnabled(enabled)


    class CosinePopupDispatcher(QObject):  # type: ignore[no-redef]
        """The one GUI-thread owner of COSINE popup instances."""

        request_popup = pyqtSignal(object)
        close_popup = pyqtSignal(object)
        shutdown_requested = pyqtSignal()

        def __init__(self, app: QApplication) -> None:
            super().__init__(app)
            self._checkin: CosineCheckinPopup | None = None
            self._welcome: CosineWelcomePopup | None = None
            self.request_popup.connect(self._show, Qt.ConnectionType.QueuedConnection)
            self.close_popup.connect(self._close, Qt.ConnectionType.QueuedConnection)
            self.shutdown_requested.connect(self.shutdown, Qt.ConnectionType.QueuedConnection)

        @pyqtSlot(object)
        def _show(self, request: object) -> None:
            if not isinstance(request, PopupRequest):
                return
            if request.effect.kind is EffectKind.SHOW_CHECKIN:
                if self._checkin is not None:
                    self._checkin.force_close_from_runtime()
                popup = CosineCheckinPopup(request)
                popup.finished.connect(lambda: self._clear_checkin(popup))
                self._checkin = popup
            else:
                if self._welcome is not None:
                    self._welcome.force_close_from_runtime()
                popup = CosineWelcomePopup(request)
                popup.finished.connect(lambda: self._clear_welcome(popup))
                self._welcome = popup
            popup.show()
            popup.raise_()
            popup.activateWindow()

        @pyqtSlot(object)
        def _close(self, effect: object) -> None:
            if not isinstance(effect, CosineEffect):
                return
            if effect.kind is EffectKind.CLOSE_CHECKIN and self._checkin is not None:
                if self._matches(self._checkin, effect):
                    self._checkin.force_close_from_runtime()
            elif effect.kind is EffectKind.CLOSE_WELCOME and self._welcome is not None:
                if self._matches(self._welcome, effect):
                    self._welcome.force_close_from_runtime()

        @staticmethod
        def _matches(popup: _CosineDialog, effect: CosineEffect) -> bool:
            request = popup._request.effect
            return (
                request.generation == effect.generation
                and request.request_id == effect.request_id
            )

        def _clear_checkin(self, popup: CosineCheckinPopup) -> None:
            if self._checkin is popup:
                self._checkin = None

        def _clear_welcome(self, popup: CosineWelcomePopup) -> None:
            if self._welcome is popup:
                self._welcome = None

        @pyqtSlot()
        def shutdown(self) -> None:
            if self._checkin is not None:
                self._checkin.force_close_from_runtime()
            if self._welcome is not None:
                self._welcome.force_close_from_runtime()
            self._checkin = None
            self._welcome = None


    _dispatcher_lock = threading.RLock()
    _dispatcher: CosinePopupDispatcher | None = None


    def install_cosine_dispatcher(app: QApplication) -> CosinePopupDispatcher:
        """Install exactly one dispatcher on the QApplication main thread."""

        global _dispatcher
        if app is None:
            raise ValueError("QApplication is required")
        with _dispatcher_lock:
            if _dispatcher is None:
                _dispatcher = CosinePopupDispatcher(app)
            return _dispatcher


    def dispatch_cosine_effect(
        effect: CosineEffect,
        *,
        submit_command: Callable[[CosineCommand], CommandResult],
    ) -> bool:
        """Thread-safe effect delivery from the engine/controller."""

        with _dispatcher_lock:
            dispatcher = _dispatcher
        if dispatcher is None:
            return False
        if effect.kind in {EffectKind.SHOW_CHECKIN, EffectKind.SHOW_WELCOME}:
            dispatcher.request_popup.emit(PopupRequest(effect, submit_command))
            return True
        if effect.kind in {EffectKind.CLOSE_CHECKIN, EffectKind.CLOSE_WELCOME}:
            dispatcher.close_popup.emit(effect)
            return True
        return False


    def shutdown_cosine_dispatcher() -> None:
        with _dispatcher_lock:
            dispatcher = _dispatcher
        if dispatcher is not None:
            dispatcher.shutdown_requested.emit()


__all__ = [
    "POPUP_SCHEMA_VERSION",
    "CosinePopupDispatcher",
    "PopupRequest",
    "dispatch_cosine_effect",
    "install_cosine_dispatcher",
    "shutdown_cosine_dispatcher",
]
