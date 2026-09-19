"""Guarded GET CHART navigation and renderer integration contract.

This module owns access to the MYELIN Neon Poster.  It deliberately does not
calculate chart values or paint the poster: the registered poster surface
(``GET_CHART.poster.NeonPosterWindow``) owns presentation and the existing
analytics controller remains the owner of the Analytics Sheet and its A4 PDF
export.

Renderer contract
-----------------
``GetChartController.register_poster`` accepts one long-lived QWidget with
``analytics_requested``, ``a3_pdf_requested`` and ``jpg_requested`` signals,
plus ``present(access_token, access_is_current, load_chart_data)`` and
``revoke_access()`` methods.  The guarded loader returns the exact immutable
``GET_CHART.read_model.PosterChartData`` contract.  A renderer may
also implement ``export_a3_pdf(access_token, access_is_current)`` and
``export_high_resolution_jpg(access_token, access_is_current)``.  The supplied
predicate must be checked again immediately before publishing an asynchronous
result or replacing an output file.  This prevents a stopped-session snapshot
from being delivered after monitoring has started.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QPainter
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# The final painter, layout and exports live in GET_CHART.poster.  The class is
# re-exported here so ``from CONTROL_STATION.get_chart import NeonPosterWindow``
# (used by application.py and the regression tests) keeps working unchanged.
from GET_CHART.poster import NeonPosterWindow


LOCKED_TITLE: Final = "CHART NOT AVAILABLE"
LOCKED_BODY: Final = (
    "Charts are locked while MYELIN is running.\n\n"
    "Stop MYELIN to view chart."
)


class ChartAccessRevoked(RuntimeError):
    """Raised when a data load loses its stopped-session access grant."""


# Presentation values mirror LifecycleConfirmSurface (START MYELIN?) so the two
# confirmations read as one interface.  They are reproduced here, not imported:
# lifecycle.py owns that surface and is not modified by this presentation patch.
_OVERLAY_RGBA: Final = (4, 9, 13, 218)
_CARD_STYLE: Final = (
    "QFrame#getChartLockedCard { background: #101821; border: 1px solid #29404f;"
    " border-radius: 14px; }"
    "QLabel { color: #edf7fb; background: transparent; border: 0; }"
    "QPushButton:focus { border: 1px solid #6f9bb3; }"
    "QPushButton:pressed { background: #0b1218; }"
)


class ChartLockedDialog(QWidget):
    """One reusable, non-nested lock explanation and safe-stop choice.

    Presented like the START MYELIN confirmation: a dimmed, in-window overlay
    over the Control Station with one centred navy card.  It is a child of the
    Control Station window (no second top-level window, no title bar), so it
    always follows that window's size and position.  Without a host window it
    falls back to a small frameless window that shows only the card.
    """

    stop_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        if parent is None:
            super().__init__(
                None,
                Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint,
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        else:
            super().__init__(parent)
        self._host = parent
        self._filter_installed = False
        self._previous_focus: QWidget | None = None

        self.setObjectName("getChartLockedDialog")
        self.setWindowTitle(LOCKED_TITLE)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(LOCKED_TITLE)
        self.setAccessibleDescription(LOCKED_BODY)

        self.card = QFrame(self)
        self.card.setObjectName("getChartLockedCard")
        self.card.setMinimumWidth(460)
        self.card.setMaximumWidth(560)
        self.card.setStyleSheet(_CARD_STYLE)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(32, 30, 32, 26)
        card_layout.setSpacing(14)

        self.title_label = QLabel(LOCKED_TITLE, self.card)
        self.title_label.setObjectName("getChartLockedTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setAccessibleName(LOCKED_TITLE)
        self.title_label.setStyleSheet(
            "font-size: 20px; font-weight: 700; letter-spacing: 1px;"
        )
        card_layout.addWidget(self.title_label)

        body = QLabel(LOCKED_BODY, self.card)
        body.setObjectName("getChartLockedBody")
        body.setWordWrap(True)
        body.setAccessibleDescription(LOCKED_BODY)
        body.setStyleSheet("font-size: 14px; color: #b8cad4;")
        card_layout.addWidget(body)
        card_layout.addSpacing(8)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        actions.addStretch(1)
        self.close_button = QPushButton("CLOSE", self.card)
        self.close_button.setObjectName("getChartLockedCloseButton")
        self.close_button.setAccessibleName("CLOSE")
        self.stop_button = QPushButton("STOP MYELIN", self.card)
        self.stop_button.setObjectName("getChartLockedStopButton")
        self.stop_button.setAccessibleName("STOP MYELIN")
        self.close_button.clicked.connect(self.reject)
        self.stop_button.clicked.connect(self._request_stop)
        actions.addWidget(self.close_button)
        actions.addWidget(self.stop_button)
        card_layout.addLayout(actions)
        self.setTabOrder(self.close_button, self.stop_button)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.hide()

    def present(self) -> None:
        """Show (or re-raise) the single card; safe to call repeatedly."""

        host = self._host
        if host is not None:
            if not self._filter_installed:
                host.installEventFilter(self)
                self._filter_installed = True
                focus = host.focusWidget()
                self._previous_focus = focus if isinstance(focus, QWidget) else None
            self.setGeometry(host.rect())
        self.show()
        self.raise_()
        if host is None:
            self.activateWindow()
        # CLOSE is the default so a stray Enter can never request a stop.
        self.close_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def reject(self) -> None:
        """Dismiss only.  Never stops MYELIN and never changes chart access."""

        self.close()

    def _request_stop(self) -> None:
        # This dialog is the user's explicit stop confirmation.  The signal is
        # wired only to LifecycleController.request_stop; it never reaches the
        # worker or its thread primitives directly.
        self.stop_requested.emit()
        self.reject()

    # -- keyboard: stay inside the card, Escape only dismisses ---------------

    def focusNextPrevChild(self, next_: bool) -> bool:  # noqa: N802
        order = (self.close_button, self.stop_button)
        current = self.focusWidget()
        index = order.index(current) if current in order else -1
        target = order[(index + (1 if next_ else -1)) % len(order)]
        target.setFocus(
            Qt.FocusReason.TabFocusReason if next_ else Qt.FocusReason.BacktabFocusReason
        )
        return True

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            event.accept()
            self.reject()
            return
        if key in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            event.accept()
            focused = self.focusWidget()
            button = focused if focused in (self.close_button, self.stop_button) else self.close_button
            button.click()
            return
        super().keyPressEvent(event)

    # -- the overlay swallows input meant for the dimmed window ---------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802
        event.accept()

    # -- lifecycle: no overlay may outlive the dialog ------------------------

    def hideEvent(self, event) -> None:  # noqa: N802
        self._release_host()
        super().hideEvent(event)

    def _release_host(self) -> None:
        host = self._host
        if host is not None and self._filter_installed:
            host.removeEventFilter(self)
        self._filter_installed = False
        previous, self._previous_focus = self._previous_focus, None
        if previous is not None and not previous.isHidden():
            try:
                previous.setFocus(Qt.FocusReason.OtherFocusReason)
            except RuntimeError:
                pass

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if (
            watched is self._host
            and self.isVisible()
            and event.type() in {QEvent.Type.Resize, QEvent.Type.Move}
        ):
            self.setGeometry(self._host.rect())
        return False

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._host is None:
            return  # standalone fallback: only the card is drawn
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(*_OVERLAY_RGBA))
        painter.end()


class GetChartController(QObject):
    """Single guarded entry point for poster, analytics and poster exports."""

    access_changed = pyqtSignal(bool)  # True only while chart access is allowed.

    def __init__(
        self,
        *,
        engine,
        lifecycle,
        analytics_opener: Callable[[], bool],
        data_provider: Callable[[], object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._engine = engine
        self._lifecycle = lifecycle
        self._analytics_opener = analytics_opener
        self._data_provider = data_provider
        self._host = parent
        self._button: QPushButton | None = None
        self._poster: QWidget | None = None
        self._locked_dialog: ChartLockedDialog | None = None
        # One stopped-session generation can authorize the poster and all of
        # its subordinate actions.  Only a lifecycle fact (or shutdown)
        # revokes it; opening Analytics or exporting must not revoke the
        # still-open poster.
        self._access_generation = 1
        self._last_locked: bool | None = None
        self._closed = False

    @property
    def poster(self) -> QWidget | None:
        return self._poster

    @property
    def access_generation(self) -> int:
        return self._access_generation

    def register_button(self, button: QPushButton) -> None:
        if self._button is not None and self._button is not button:
            raise RuntimeError("GET CHART button is already registered")
        self._button = button
        self._sync_access_state()

    def register_poster(self, poster: QWidget) -> None:
        """Register exactly one long-lived poster surface."""

        if self._poster is not None and self._poster is not poster:
            raise RuntimeError("MYELIN Neon Poster is already registered")
        for signal_name in (
            "analytics_requested",
            "a3_pdf_requested",
            "jpg_requested",
        ):
            signal = getattr(poster, signal_name, None)
            if signal is None or not hasattr(signal, "connect"):
                raise TypeError(f"Poster is missing {signal_name}")
        for method_name in ("present", "revoke_access"):
            if not callable(getattr(poster, method_name, None)):
                raise TypeError(f"Poster is missing {method_name}()")

        if self._poster is None:
            poster.analytics_requested.connect(self.open_analytics_sheet)
            poster.a3_pdf_requested.connect(self.export_a3_pdf)
            poster.jpg_requested.connect(self.export_high_resolution_jpg)
        self._poster = poster
        self._sync_access_state()

    def lifecycle_changed(self, *_ignored: object) -> None:
        """Re-read the authoritative engine rule after every lifecycle fact."""

        locked = self._session_locked()
        if locked:
            self._access_generation += 1
        self._sync_access_state(locked=locked)

    def open_poster(self) -> bool:
        """Open the registered poster only under a current stopped-session grant."""

        if not self._admit_or_explain():
            return False
        poster = self._poster
        if poster is None:
            return False

        token = self._current_access_token()
        if not self.access_is_current(token):
            return False
        poster.present(token, self.access_is_current, self.load_chart_data)
        # A custom surface may start asynchronous work from present().  Recheck
        # immediately so a re-entrant start cannot leave the surface visible.
        if not self.access_is_current(token):
            poster.revoke_access()
            return False
        return True

    def open_analytics_sheet(self) -> bool:
        """Preserve the original Analytics Sheet behind the same chart guard."""

        if not self._admit_or_explain():
            return False
        token = self._current_access_token()
        if not self.access_is_current(token):
            return False
        opened = bool(self._analytics_opener())
        return bool(opened and self.access_is_current(token))

    def export_a3_pdf(self) -> bool:
        return self._dispatch_poster_export("export_a3_pdf")

    def export_high_resolution_jpg(self) -> bool:
        return self._dispatch_poster_export("export_high_resolution_jpg")

    def access_is_current(self, access_token: int) -> bool:
        """Validate a load/export token at every asynchronous delivery boundary."""

        return bool(
            not self._closed
            and int(access_token) == self._access_generation
            and not self._session_locked()
        )

    def load_chart_data(self, access_token: int) -> object:
        """Run one read and reject its result if lifecycle truth changed."""

        if not self.access_is_current(access_token):
            raise ChartAccessRevoked("chart access is no longer current")
        projection = self._data_provider()
        if not self.access_is_current(access_token):
            raise ChartAccessRevoked("chart access changed while data was loading")
        return projection

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._access_generation += 1
        if self._locked_dialog is not None:
            self._locked_dialog.close()
            self._locked_dialog.deleteLater()
            self._locked_dialog = None
        if self._poster is not None:
            self._poster.revoke_access()
            self._poster.close()
            self._poster.deleteLater()
            self._poster = None

    def _dispatch_poster_export(self, method_name: str) -> bool:
        if not self._admit_or_explain():
            return False
        poster = self._poster
        exporter = getattr(poster, method_name, None) if poster is not None else None
        if not callable(exporter):
            return False
        token = self._current_access_token()
        if not self.access_is_current(token):
            return False
        result = bool(exporter(token, self.access_is_current))
        return bool(result and self.access_is_current(token))

    def _current_access_token(self) -> int:
        return self._access_generation

    def _admit_or_explain(self) -> bool:
        if self._closed:
            return False
        if self._session_locked():
            self._show_locked_dialog()
            self._sync_access_state()
            return False
        return True

    def _session_locked(self) -> bool:
        # Fail closed if the one authoritative query itself becomes unavailable.
        try:
            return bool(self._engine.is_session_active())
        except Exception:
            return True

    def _sync_access_state(self, *, locked: bool | None = None) -> None:
        locked = self._closed or (
            self._session_locked() if locked is None else bool(locked)
        )
        button = self._button
        if button is not None:
            # Keep the button enabled: the locked click must explain the rule
            # and offer the existing safe lifecycle stop action.
            button.setEnabled(not self._closed)
            button.setText("🔒 GET CHART" if locked else "GET CHART")
            button.setProperty("chartLocked", locked)
            button.setAccessibleName(
                "GET CHART (locked while MYELIN is running)"
                if locked
                else "GET CHART"
            )
            button.setToolTip(
                "Charts are locked while MYELIN is running. Click for options."
                if locked
                else "Open MYELIN Neon Poster"
            )
            style = button.style()
            style.unpolish(button)
            style.polish(button)
            button.update()

        if locked and self._poster is not None:
            self._poster.revoke_access()
        if locked != self._last_locked:
            self._last_locked = locked
            self.access_changed.emit(not locked)

    def _show_locked_dialog(self) -> None:
        if self._locked_dialog is None:
            self._locked_dialog = ChartLockedDialog(self._host)
            self._locked_dialog.stop_requested.connect(self._request_safe_stop)
        self._locked_dialog.present()

    def _request_safe_stop(self) -> None:
        # LifecycleController owns admission, Protected Red and the engine
        # command.  The result is intentionally not interpreted as completion;
        # only a later is_session_active() == False can unlock GET CHART.
        self._lifecycle.request_stop()
        self._sync_access_state()
