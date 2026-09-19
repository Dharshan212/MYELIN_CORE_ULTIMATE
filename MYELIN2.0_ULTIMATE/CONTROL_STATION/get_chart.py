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

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
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


class ChartLockedDialog(QDialog):
    """One reusable, non-nested lock explanation and safe-stop choice."""

    stop_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("getChartLockedDialog")
        self.setWindowTitle(LOCKED_TITLE)
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        body = QLabel(LOCKED_BODY, self)
        body.setObjectName("getChartLockedBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.close_button = QPushButton("CLOSE", self)
        self.stop_button = QPushButton("STOP MYELIN", self)
        self.close_button.clicked.connect(self.reject)
        self.stop_button.clicked.connect(self._request_stop)
        actions.addWidget(self.close_button)
        actions.addWidget(self.stop_button)
        layout.addLayout(actions)

    def present(self) -> None:
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def _request_stop(self) -> None:
        # This dialog is the user's explicit stop confirmation.  The signal is
        # wired only to LifecycleController.request_stop; it never reaches the
        # worker or its thread primitives directly.
        self.stop_requested.emit()
        self.reject()


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
