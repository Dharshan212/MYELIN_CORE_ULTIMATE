"""Dedicated Phase-1 MINE presentation family.

This module renders one MINE-1 workflow and one branch-aware, zero-button
MINE-2 window.  It does not observe applications, advance scientific time,
write events, or decide state.  Every user action and factual DISPLAYED
acknowledgement is submitted to :mod:`MINE.mine` with exact generation and
request identity.  Runtime HIDE/RESTORE effects reuse the same window object.
"""
from __future__ import annotations

from CONTROL_STATION.command_delivery import PendingCommand, on_popup_reply

import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from MINE.mine import (
    MineChoice,
    MineCommand,
    MineCommandKind,
    MineCommandResult,
    MineEffect,
    MineEffectKind,
    MinePhase,
)


POPUP_SCHEMA_VERSION: Final = "myelin-mine-popup-v1-isolated"
SHOW_EFFECTS: Final = frozenset(
    {
        MineEffectKind.SHOW_MINE1,
        MineEffectKind.SHOW_IMPORTANT_DURATION,
        MineEffectKind.SHOW_MINE2,
    }
)
CONTROL_EFFECTS: Final = frozenset(
    {
        MineEffectKind.CLOSE_MINE1,
        MineEffectKind.UPDATE_RETURN_CONFIRMING,
        MineEffectKind.HIDE_MINE2,
        MineEffectKind.RESTORE_MINE2,
        MineEffectKind.CLOSE_PRESENTATION,
    }
)
DISPLAY_COMMANDS: Final = frozenset(
    {MineCommandKind.MINE1_DISPLAYED, MineCommandKind.MINE2_DISPLAYED}
)


@dataclass(frozen=True, slots=True)
class PopupRequest:
    effect: MineEffect
    submit_command: Callable[[MineCommand], MineCommandResult]

    def __post_init__(self) -> None:
        if self.effect.kind not in SHOW_EFFECTS:
            raise ValueError("PopupRequest requires a MINE show effect")
        if not callable(self.submit_command):
            raise TypeError("submit_command must be callable")


try:
    from PyQt6.QtCore import QObject, QPoint, Qt, pyqtSignal, pyqtSlot
    from PyQt6.QtGui import QCloseEvent, QCursor, QFont, QGuiApplication, QIntValidator
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as _qt_failure:
    _QT_IMPORT_DETAIL = str(_qt_failure)

    class MinePopupDispatcher:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError(f"MINE popup presentation requires PyQt6: {_QT_IMPORT_DETAIL}")

    def install_mine_dispatcher(*args, **kwargs):
        raise RuntimeError(f"MINE popup presentation requires PyQt6: {_QT_IMPORT_DETAIL}")

    def dispatch_mine_effect(*args, **kwargs) -> bool:
        return False

    def shutdown_mine_dispatcher() -> None:
        return None

else:
    try:
        from UI_THEMES.theme import AMBER_ALERT_THEME, DEFAULT_THEME, RED_ALERT_THEME, ThemeTokens
    except (ImportError, ModuleNotFoundError):
        AMBER_ALERT_THEME = None
        DEFAULT_THEME = None
        RED_ALERT_THEME = None
        ThemeTokens = object  # type: ignore[assignment,misc]

    def _theme_value(tokens: object, name: str, fallback: str) -> str:
        value = getattr(tokens, name, fallback)
        return str(value or fallback)

    def _resolve_tokens(owner: object | None) -> object:
        controller = getattr(owner, "theme", None)
        tokens = getattr(controller, "current_theme", None)
        return tokens or DEFAULT_THEME

    def _resolve_mine_popup_tokens(effect: "MineEffect", owner: object | None) -> object:
        """Fixed MINE intervention color family: MINE-1 is Amber, MINE-2 is Red.

        This selects the popup's own construction tokens only -- it never
        claims the shared ``ThemeController`` atmosphere, which stays owned
        by the launcher's factual MineSnapshot-driven presentation
        coordinator. Falls back to the current base theme if the shared
        alert worlds are unavailable (e.g. ``UI_THEMES`` import failed).
        """

        if effect.kind is MineEffectKind.SHOW_MINE2 and RED_ALERT_THEME is not None:
            return RED_ALERT_THEME
        if effect.kind is MineEffectKind.SHOW_MINE1 and AMBER_ALERT_THEME is not None:
            return AMBER_ALERT_THEME
        return _resolve_tokens(owner)

    def _font(size: int, *, bold: bool = False, mono: bool = False) -> QFont:
        font = QFont("Consolas" if mono else "Segoe UI")
        font.setPixelSize(size)
        font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        return font

    def _stylesheet(tokens: object) -> str:
        background = _theme_value(tokens, "window_background", "#08111F")
        surface = _theme_value(tokens, "surface_soft", "#101D2D")
        surface_2 = _theme_value(tokens, "surface_2", "#15263A")
        accent = _theme_value(tokens, "cyan", "#36D7FF")
        muted = _theme_value(tokens, "muted", "#9BAFC4")
        text = _theme_value(tokens, "text_primary", "#F4F8FC")
        border = _theme_value(tokens, "border", "#29425C")
        return f"""
        QDialog#minePopup {{ background: {background}; }}
        QFrame#mineCard {{
            background: {surface}; border: 2px solid {accent}; border-radius: 16px;
        }}
        QFrame#mineAccentRail {{
            background: {accent}; border: none; border-radius: 1px;
        }}
        QLabel {{ color: {text}; background: transparent; }}
        QLabel#mineEyebrow, QLabel#mineContext, QLabel#mineFooter {{ color: {muted}; }}
        QLabel#mineHeadline, QLabel#mineStatus {{ color: {accent}; }}
        QLabel#mineBadge {{
            color: {accent}; background: {surface_2}; border: 1px solid {accent};
            border-radius: 9px; padding: 3px 10px;
        }}
        QLineEdit#mineDurationField {{
            color: {text}; background: {surface_2}; border: 2px solid {accent};
            border-radius: 10px; padding: 10px;
        }}
        QLineEdit#mineDurationField:focus {{ border: 2px solid {text}; }}
        QPushButton {{ border-radius: 10px; padding: 12px 20px; }}
        QPushButton#minePrimary {{ color: #071019; background: {accent}; border: none; }}
        QPushButton#minePrimary:hover {{ border: 2px solid {text}; }}
        QPushButton#minePrimary:pressed {{ background: {muted}; }}
        QPushButton#minePrimary:focus {{ border: 2px solid {text}; }}
        QPushButton#mineSecondary {{ color: {accent}; background: transparent; border: 2px solid {accent}; }}
        QPushButton#mineSecondary:hover {{ background: {surface_2}; }}
        QPushButton#mineSecondary:pressed {{ background: {surface}; }}
        QPushButton#mineSecondary:focus {{ border: 2px solid {text}; }}
        QPushButton:disabled {{ color: {muted}; border-color: {border}; background: {surface_2}; }}
        """

    class _MineDialog(QDialog):
        """Common exact-delivery shell; the runtime remains authoritative."""

        display_retry_requested = pyqtSignal(int)
        CARD_WIDTH = 760

        def __init__(self, request: PopupRequest, tokens: object, parent=None) -> None:
            super().__init__(parent)
            self._request = request
            self._tokens = tokens
            self._delivery_in_progress = False
            self._accepted_close = False
            self._display_acknowledged = False
            self._runtime_hidden = False
            self._retired = False
            self._display_retry_scheduled = False
            self._display_retry_serial = 0
            self._automatic_display_retry_used = False
            self._retry_command: tuple[
                MineCommandKind, MineChoice | None, int | None, bool
            ] | None = None
            self._drag_origin: QPoint | None = None
            self.display_retry_requested.connect(
                self._retry_display_delivery,
                Qt.ConnectionType.QueuedConnection,
            )
            self.setModal(False)
            self.setWindowFlags(
                Qt.WindowType.Dialog
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setObjectName("minePopup")
            self.setWindowTitle("MYELIN MINE")
            self.setAccessibleName("MYELIN MINE intervention")
            self.setStyleSheet(_stylesheet(tokens))
            self.setFixedWidth(self.CARD_WIDTH)
            outer = QVBoxLayout(self)
            outer.setContentsMargins(8, 8, 8, 8)
            self.card = QFrame(self)
            self.card.setObjectName("mineCard")
            outer.addWidget(self.card)
            self.body = QVBoxLayout(self.card)
            self.body.setContentsMargins(30, 24, 30, 22)
            self.body.setSpacing(16)
            self._build_header()

        def _build_header(self) -> None:
            row = QHBoxLayout()
            eyebrow = QLabel("MYELIN · MINE", self.card)
            eyebrow.setObjectName("mineEyebrow")
            eyebrow.setFont(_font(13, bold=True, mono=True))
            row.addWidget(eyebrow)
            row.addStretch(1)
            self.badge = QLabel("MESSAGING", self.card)
            self.badge.setObjectName("mineBadge")
            self.badge.setFont(_font(12, bold=True, mono=True))
            row.addWidget(self.badge)
            self.body.addLayout(row)
            rail = QFrame(self.card)
            rail.setObjectName("mineAccentRail")
            rail.setFixedHeight(3)
            self.body.addWidget(rail)

        def _add_headline(self, text: str) -> QLabel:
            label = QLabel(text, self.card)
            label.setObjectName("mineHeadline")
            label.setFont(_font(26, bold=True))
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body.addWidget(label)
            return label

        def _add_message(self, text: str) -> QLabel:
            label = QLabel(text, self.card)
            label.setFont(_font(15))
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body.addWidget(label)
            return label

        def _add_context(self) -> None:
            label = self._request.effect.platform_label or self._request.effect.platform_key
            if not label:
                return
            context = QLabel(f"MESSAGING APP · {label}", self.card)
            context.setObjectName("mineContext")
            context.setFont(_font(13, mono=True))
            context.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body.addWidget(context)

        def _add_delivery_state(self) -> None:
            self.delivery_label = QLabel("AWAITING DISPLAY ACKNOWLEDGEMENT", self.card)
            self.delivery_label.setObjectName("mineStatus")
            self.delivery_label.setFont(_font(12, bold=True, mono=True))
            self.delivery_label.setWordWrap(True)
            self.delivery_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body.addWidget(self.delivery_label)

        def _add_footer(self, text: str) -> None:
            footer = QLabel(text, self.card)
            footer.setObjectName("mineFooter")
            footer.setFont(_font(11, mono=True))
            footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body.addWidget(footer)

        def _button_row(self, buttons: tuple[QPushButton, ...]) -> QHBoxLayout:
            row = QHBoxLayout()
            row.setSpacing(14)
            row.addStretch(1)
            for button in buttons:
                button.setFont(_font(14, bold=True))
                button.setMinimumWidth(230 if len(buttons) > 1 else 260)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                row.addWidget(button)
            row.addStretch(1)
            self.body.addLayout(row)
            return row

        def _deliver(
            self,
            kind: MineCommandKind,
            *,
            choice: MineChoice | None = None,
            duration_minutes: int | None = None,
            close_after_acceptance: bool,
        ) -> bool:
            if self._delivery_in_progress:
                return False
            self._retry_command = (kind, choice, duration_minutes, close_after_acceptance)
            self._delivery_in_progress = True
            self._set_controls_enabled(False)
            self.delivery_label.setText("DELIVERING COMMAND")
            command = MineCommand(
                kind=kind,
                generation=self._request.effect.generation,
                request_id=self._request.effect.request_id,
                occurred_monotonic_ns=time.monotonic_ns(),
                choice=choice,
                duration_minutes=duration_minutes,
            )
            try:
                result = self._request.submit_command(command)
            except Exception as exc:  # noqa: BLE001 - UI delivery boundary
                result = None
                detail = " ".join(str(exc).split())[:180]
            else:
                if isinstance(result, PendingCommand):
                    def completed(reply):
                        try:
                            value = reply.result()
                            message = getattr(value, "message", "Invalid command result")
                        except RuntimeError as error:
                            value, message = None, str(error)
                        self._complete_delivery(kind, close_after_acceptance, value, message)
                    on_popup_reply(result, self, completed)
                    return not bool(result.error)
                detail = (
                    result.message
                    if isinstance(result, MineCommandResult)
                    else "Invalid command result"
                )
            return self._complete_delivery(kind, close_after_acceptance, result, detail)

        def _complete_delivery(self, kind, close_after_acceptance, result, detail):
            """Apply only an actual backend reply, on the GUI thread."""
            self._delivery_in_progress = False
            if not isinstance(result, MineCommandResult) or not result.accepted:
                self.delivery_label.setText(f"NOT ACCEPTED · {detail or 'PLEASE RETRY'}".upper())
                self._set_controls_enabled(kind not in DISPLAY_COMMANDS)
                if kind in DISPLAY_COMMANDS:
                    if isinstance(result, MineCommandResult) and not self._display_request_is_current(
                        kind, result
                    ):
                        self._retired = True
                        self._cancel_display_retry()
                    else:
                        self._schedule_display_retry()
                return False
            if kind in DISPLAY_COMMANDS:
                self._display_acknowledged = True
                self._cancel_display_retry()
            self.delivery_label.setText("COMMAND ACCEPTED")
            if close_after_acceptance and result.close_popup:
                self._accepted_close = True
                self._retired = True
                self._cancel_display_retry()
                self.accept()
            else:
                self._set_controls_enabled(True)
            return True

        def retry_last_delivery(self) -> bool:
            if self._retry_command is None:
                return False
            kind, choice, minutes, close_after = self._retry_command
            return self._deliver(
                kind,
                choice=choice,
                duration_minutes=minutes,
                close_after_acceptance=close_after,
            )

        def _schedule_display_retry(self) -> None:
            """Queue transport-only DISPLAYED redelivery; no scientific time lives here."""

            if (
                self._display_acknowledged
                or self._display_retry_scheduled
                or self._automatic_display_retry_used
                or self._retired
                or self._runtime_hidden
            ):
                return
            if self._retry_command is None or self._retry_command[0] not in DISPLAY_COMMANDS:
                return
            self._display_retry_serial += 1
            serial = self._display_retry_serial
            self._display_retry_scheduled = True
            self._automatic_display_retry_used = True
            self.display_retry_requested.emit(serial)

        def _display_request_is_current(
            self, kind: MineCommandKind, result: MineCommandResult
        ) -> bool:
            snapshot = result.snapshot
            if snapshot.generation != self._request.effect.generation:
                return False
            if kind is MineCommandKind.MINE1_DISPLAYED:
                return (
                    snapshot.phase is MinePhase.MINE1_PENDING
                    and snapshot.mine1_request_id == self._request.effect.request_id
                )
            return (
                snapshot.phase in {MinePhase.MINE2A_PENDING, MinePhase.MINE2B_PENDING}
                and snapshot.mine2_request_id == self._request.effect.request_id
            )

        @pyqtSlot(int)
        def _retry_display_delivery(self, serial: int) -> None:
            if serial != self._display_retry_serial:
                return
            self._display_retry_scheduled = False
            if (
                self._display_acknowledged
                or self._retired
                or self._runtime_hidden
                or not self.isVisible()
            ):
                return
            self.retry_last_delivery()

        def _cancel_display_retry(self) -> None:
            self._display_retry_serial += 1
            self._display_retry_scheduled = False

        def _display_command(self) -> MineCommandKind:
            raise NotImplementedError

        def submit_display_if_pending(self) -> None:
            if self._display_acknowledged:
                return
            self._deliver(self._display_command(), close_after_acceptance=False)

        def showEvent(self, event) -> None:  # noqa: N802
            super().showEvent(event)
            self.submit_display_if_pending()

        @property
        def runtime_hidden(self) -> bool:
            return self._runtime_hidden

        def hide_from_runtime(self) -> None:
            self._runtime_hidden = True
            self._cancel_display_retry()
            self.hide()

        def restore_from_runtime(self) -> None:
            self._runtime_hidden = False
            self.show()
            self.raise_()
            self.activateWindow()

        def raise_for_repeat_show(self) -> None:
            if self._runtime_hidden:
                return
            self.show()
            self.raise_()
            self.activateWindow()

        def force_close_from_runtime(self) -> None:
            self._accepted_close = True
            self._retired = True
            self._cancel_display_retry()
            self.accept()

        def reject(self) -> None:
            self.delivery_label.setText("MINE IS WAITING FOR BACKEND AUTHORITY")

        def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
            if self._accepted_close:
                event.accept()
            else:
                self.delivery_label.setText("MINE IS WAITING FOR BACKEND AUTHORITY")
                event.ignore()

        def keyPressEvent(self, event) -> None:  # noqa: N802
            if event.key() == Qt.Key.Key_Escape:
                event.ignore()
                return
            super().keyPressEvent(event)

        def place_for_effect(self) -> None:
            try:
                screen = QGuiApplication.screenAt(QCursor.pos())
            except Exception:
                screen = None
            screen = screen or QGuiApplication.primaryScreen()
            if screen is None:
                return
            self.adjustSize()
            area = screen.availableGeometry()
            frame = self.frameGeometry()
            self.move(
                area.center().x() - frame.width() // 2,
                area.center().y() - frame.height() // 2,
            )

        def mousePressEvent(self, event) -> None:  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_origin = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                event.accept()
                return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:  # noqa: N802
            if self._drag_origin is not None and (
                event.buttons() & Qt.MouseButton.LeftButton
            ):
                self.move(event.globalPosition().toPoint() - self._drag_origin)
                event.accept()
                return
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event) -> None:  # noqa: N802
            self._drag_origin = None
            super().mouseReleaseEvent(event)

        def _set_controls_enabled(self, enabled: bool) -> None:
            raise NotImplementedError

    class Mine1Popup(_MineDialog):
        """MINE-1 with two choices and a same-window duration workflow."""

        def __init__(self, request: PopupRequest, tokens: object, parent=None) -> None:
            super().__init__(request, tokens, parent)
            self.badge.setText("MINE-1")
            self._add_headline("IT SEEMS YOU HAVE STARTED USING A MESSAGING APP")
            self.message_label = self._add_message(
                "BUT YOU HAVE IMPORTANT WORK — RETURN IF THIS IS NOT IMPORTANT."
            )
            self._add_context()
            self.come_back = QPushButton("I WILL COME BACK", self.card)
            self.come_back.setObjectName("minePrimary")
            self.important = QPushButton("IT'S IMPORTANT", self.card)
            self.important.setObjectName("mineSecondary")
            self.come_back.clicked.connect(
                lambda: self._deliver(
                    MineCommandKind.MINE1_ACTION,
                    choice=MineChoice.I_WILL_COME_BACK,
                    close_after_acceptance=True,
                )
            )
            self.important.clicked.connect(
                lambda: self._deliver(
                    MineCommandKind.MINE1_ACTION,
                    choice=MineChoice.ITS_IMPORTANT,
                    close_after_acceptance=False,
                )
            )
            self.choice_row = self._button_row((self.come_back, self.important))
            self.minutes_field: QLineEdit | None = None
            self.duration_action: QPushButton | None = None
            self.duration_row: QHBoxLayout | None = None
            self._duration_mode = False
            self._add_delivery_state()
            self._add_footer("MINE · INTENTION GATE")
            self._set_controls_enabled(False)

        def _display_command(self) -> MineCommandKind:
            return MineCommandKind.MINE1_DISPLAYED

        def show_duration_entry(self, effect: MineEffect) -> None:
            if self._duration_mode:
                self.raise_for_repeat_show()
                return
            if (
                effect.generation != self._request.effect.generation
                or effect.request_id != self._request.effect.request_id
            ):
                return
            self._duration_mode = True
            self.badge.setText("IT'S IMPORTANT")
            self.message_label.setText(
                "HOW MANY WHOLE MINUTES DO YOU NEED? ENTER ANY VALUE FROM 5 THROUGH 30."
            )
            self.come_back.hide()
            self.important.hide()
            self.minutes_field = QLineEdit(self.card)
            self.minutes_field.setObjectName("mineDurationField")
            self.minutes_field.setPlaceholderText("MINUTES")
            self.minutes_field.setValidator(QIntValidator(0, 9999, self))
            self.minutes_field.setMaxLength(4)
            self.minutes_field.setFixedWidth(170)
            self.minutes_field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.minutes_field.setFont(_font(26, bold=True, mono=True))
            self.minutes_field.setAccessibleName("Important messaging duration in whole minutes")
            self.duration_action = QPushButton("SET IMPORTANT TIME", self.card)
            self.duration_action.setObjectName("minePrimary")
            self.duration_action.clicked.connect(self._submit_duration)
            self.minutes_field.returnPressed.connect(self._submit_duration)
            self.duration_row = QHBoxLayout()
            self.duration_row.addStretch(1)
            self.duration_row.addWidget(self.minutes_field)
            self.duration_row.addWidget(self.duration_action)
            self.duration_row.addStretch(1)
            # Insert immediately before delivery status and footer.
            self.body.insertLayout(max(0, self.body.count() - 2), self.duration_row)
            self.delivery_label.setText("MINE IS WAITING FOR YOUR CHOSEN MINUTES")
            self.minutes_field.setFocus()
            self.adjustSize()

        def _entered_minutes(self) -> int | None:
            if self.minutes_field is None:
                return None
            try:
                return int(self.minutes_field.text().strip())
            except (TypeError, ValueError):
                return None

        def _submit_duration(self) -> None:
            self._deliver(
                MineCommandKind.IMPORTANT_DURATION_SUBMITTED,
                duration_minutes=self._entered_minutes(),
                close_after_acceptance=True,
            )

        def _set_controls_enabled(self, enabled: bool) -> None:
            if self._duration_mode:
                if self.minutes_field is not None:
                    self.minutes_field.setEnabled(enabled)
                if self.duration_action is not None:
                    self.duration_action.setEnabled(enabled)
                return
            self.come_back.setEnabled(enabled)
            self.important.setEnabled(enabled)

    class Mine2Popup(_MineDialog):
        """Branch-specific final MINE-2 callback with zero buttons."""

        def __init__(self, request: PopupRequest, tokens: object, parent=None) -> None:
            super().__init__(request, tokens, parent)
            self.variant = request.effect.presentation_variant
            self.badge.setText(self.variant or "MINE-2")
            if self.variant == "MINE2A":
                headline = "YOU SAID YOU WOULD COME BACK"
                message = request.effect.message or "YOUR IMPORTANT WORK IS WAITING."
            else:
                headline = "YOUR IMPORTANT MESSAGING TIME IS OVER"
                message = request.effect.message or "IT IS TIME TO RETURN."
            self.headline_label = self._add_headline(headline)
            self.message_label = self._add_message(message)
            self.confirming_label = QLabel("", self.card)
            self.confirming_label.setObjectName("mineStatus")
            self.confirming_label.setFont(_font(15, bold=True, mono=True))
            self.confirming_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body.addWidget(self.confirming_label)
            self._add_delivery_state()
            self._add_footer("MINE · FINAL CALLBACK · NO ACTION BUTTONS")
            self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
            self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
            self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
            self.setWindowFlag(Qt.WindowType.WindowSystemMenuHint, False)

        def _display_command(self) -> MineCommandKind:
            return MineCommandKind.MINE2_DISPLAYED

        def set_return_confirming(self, message: str) -> None:
            self.confirming_label.setText(message or "RETURN CONFIRMING")

        def _set_controls_enabled(self, enabled: bool) -> None:
            del enabled

    class MinePopupDispatcher(QObject):  # type: ignore[no-redef]
        """The one GUI-thread owner of all current MINE popup objects."""

        request_popup = pyqtSignal(object)
        control_popup = pyqtSignal(object)
        shutdown_requested = pyqtSignal()

        def __init__(self, app: QApplication, *, owner=None) -> None:
            super().__init__(app)
            self._owner_ref = weakref.ref(owner) if owner is not None else (lambda: None)
            self._mine1_popup: Mine1Popup | None = None
            self._mine2_popup: Mine2Popup | None = None
            self.request_popup.connect(self._show, Qt.ConnectionType.QueuedConnection)
            self.control_popup.connect(self._control, Qt.ConnectionType.QueuedConnection)
            self.shutdown_requested.connect(self.shutdown, Qt.ConnectionType.QueuedConnection)

        def set_owner(self, owner) -> None:
            self._owner_ref = weakref.ref(owner) if owner is not None else (lambda: None)

        @pyqtSlot(object)
        def _show(self, request: object) -> None:
            if not isinstance(request, PopupRequest):
                return
            effect = request.effect
            if effect.kind is MineEffectKind.SHOW_IMPORTANT_DURATION:
                popup = self._mine1_popup
                if popup is not None and self._matches(popup, effect):
                    popup.show_duration_entry(effect)
                return
            slot_name = (
                "_mine1_popup"
                if effect.kind is MineEffectKind.SHOW_MINE1
                else "_mine2_popup"
            )
            popup_class = Mine1Popup if slot_name == "_mine1_popup" else Mine2Popup
            existing = getattr(self, slot_name)
            if existing is not None:
                current = existing._request.effect
                if effect.generation < current.generation:
                    return
                if effect.generation == current.generation:
                    if effect.request_id != current.request_id:
                        return
                    if existing.runtime_hidden:
                        return
                    existing.raise_for_repeat_show()
                    existing.submit_display_if_pending()
                    return
                existing.force_close_from_runtime()
            popup = popup_class(request, _resolve_mine_popup_tokens(effect, self._owner_ref()))
            popup.finished.connect(
                lambda _result=0, p=popup, s=slot_name: self._clear(s, p)
            )
            setattr(self, slot_name, popup)
            popup.place_for_effect()
            popup.show()
            popup.raise_()
            popup.activateWindow()

        @pyqtSlot(object)
        def _control(self, effect: object) -> None:
            if not isinstance(effect, MineEffect):
                return
            if effect.kind is MineEffectKind.CLOSE_MINE1:
                self._close_matching(self._mine1_popup, effect)
                return
            if effect.kind is MineEffectKind.UPDATE_RETURN_CONFIRMING:
                popup = self._mine2_popup
                if popup is not None and self._matches(popup, effect):
                    popup.set_return_confirming(effect.message)
                return
            if effect.kind is MineEffectKind.HIDE_MINE2:
                for popup in self._matching_popups(effect):
                    popup.hide_from_runtime()
                return
            if effect.kind is MineEffectKind.RESTORE_MINE2:
                for popup in self._matching_popups(effect):
                    popup.restore_from_runtime()
                return
            if effect.kind is MineEffectKind.CLOSE_PRESENTATION:
                for popup in self._matching_popups(effect):
                    popup.force_close_from_runtime()

        def _matching_popups(self, effect: MineEffect) -> tuple[_MineDialog, ...]:
            return tuple(
                popup
                for popup in (self._mine1_popup, self._mine2_popup)
                if popup is not None and self._matches(popup, effect)
            )

        @staticmethod
        def _matches(popup: _MineDialog, effect: MineEffect) -> bool:
            request = popup._request.effect
            return (
                request.generation == effect.generation
                and request.request_id == effect.request_id
            )

        @staticmethod
        def _close_matching(popup: _MineDialog | None, effect: MineEffect) -> None:
            if popup is not None and MinePopupDispatcher._matches(popup, effect):
                popup.force_close_from_runtime()

        def _clear(self, slot_name: str, popup: _MineDialog) -> None:
            if getattr(self, slot_name) is popup:
                setattr(self, slot_name, None)

        @pyqtSlot()
        def shutdown(self) -> None:
            for slot_name in ("_mine1_popup", "_mine2_popup"):
                popup = getattr(self, slot_name)
                if popup is not None:
                    popup.force_close_from_runtime()
                setattr(self, slot_name, None)

    _dispatcher_lock = threading.RLock()
    _dispatcher: MinePopupDispatcher | None = None

    def install_mine_dispatcher(
        app: QApplication, *, owner=None
    ) -> MinePopupDispatcher:
        """Install exactly one MINE dispatcher on the QApplication thread."""

        global _dispatcher
        if app is None:
            raise ValueError("QApplication is required")
        with _dispatcher_lock:
            if _dispatcher is None:
                _dispatcher = MinePopupDispatcher(app, owner=owner)
            elif owner is not None:
                _dispatcher.set_owner(owner)
            return _dispatcher

    def dispatch_mine_effect(
        effect: MineEffect,
        *,
        submit_command: Callable[[MineCommand], MineCommandResult],
    ) -> bool:
        """Thread-safe delivery of one backend effect to the GUI dispatcher."""

        with _dispatcher_lock:
            dispatcher = _dispatcher
        if dispatcher is None:
            return False
        if effect.kind in SHOW_EFFECTS:
            dispatcher.request_popup.emit(PopupRequest(effect, submit_command))
            return True
        if effect.kind in CONTROL_EFFECTS:
            dispatcher.control_popup.emit(effect)
            return True
        return False

    def shutdown_mine_dispatcher() -> None:
        with _dispatcher_lock:
            dispatcher = _dispatcher
        if dispatcher is not None:
            dispatcher.shutdown_requested.emit()


__all__ = [
    "CONTROL_EFFECTS",
    "DISPLAY_COMMANDS",
    "POPUP_SCHEMA_VERSION",
    "SHOW_EFFECTS",
    "MinePopupDispatcher",
    "PopupRequest",
    "dispatch_mine_effect",
    "install_mine_dispatcher",
    "shutdown_mine_dispatcher",
]
