"""Read-only analytics surfaces for the MYELIN Control Station.

This file owns the presentation shell for:

* Metric Hub;
* Science Lab;
* Live MIRL;
* COSINE; and
* the Analytics Sheet composer.

Important boundary
------------------
Analytics displays immutable projections supplied by authoritative read
models.  It never opens SQLite, reconstructs an episode, calculates recovery,
decides a COSINE outcome, advances SINE, or changes live engine state.

There is one shared, event-driven refresh lane.  Opening a dashboard or
pressing Refresh requests one complete authoritative bundle.  Overlapping
requests are coalesced and no lifetime polling loop is created.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from PyQt6.QtCore import QDate, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .lifecycle import SurfaceKind


POLL_INTERVAL_MS: Final = 120

#: How long analytics shutdown waits for an already-accepted worker.  Analytics
#: workers READ persistence, and the launcher releases its share of the SQLite
#: lane immediately after ``analytics.shutdown()`` returns, so an unjoined
#: worker would still be inside a database that is going away.  The wait is
#: deliberately BOUNDED: a GUI shutdown must never hang on a stuck reader, so a
#: worker that overruns is reported truthfully instead of waited on forever
#: (C12-C).
ANALYTICS_SHUTDOWN_TIMEOUT_SECONDS: Final = 2.0
MAX_ERROR_LENGTH: Final = 220

PAGE_METRIC_HUB: Final = "metric-hub"
PAGE_SCIENCE_LAB: Final = "science-lab"
PAGE_LIVE_MIRL: Final = "live-mirl"
PAGE_COSINE: Final = "cosine"

PROJECTION_NAMES: Final = {
    PAGE_METRIC_HUB: "metric_hub",
    PAGE_SCIENCE_LAB: "science_lab",
    PAGE_LIVE_MIRL: "live_mirl",
    PAGE_COSINE: "cosine",
}


def _field(value: object, name: str, default=None):
    """Read one prepared field without interpreting its meaning."""

    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _projection(bundle: object, name: str):
    """Select one named projection from the authoritative root bundle."""

    return _field(bundle, name)


def _safe_text(value: object, empty: str = "—", limit: int = 500) -> str:
    if value is None:
        return empty
    cleaned = " ".join(str(value).split())
    return cleaned[:limit] if cleaned else empty


def _display_number(value: object, *, suffix: str = "") -> str:
    """Format an already-calculated number; never derive a new metric."""

    if value is None or type(value) is bool:
        return "—"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    if isinstance(value, float):
        return f"{value:,.2f}{suffix}"
    return _safe_text(value)


def _display_seconds(value: object) -> str:
    return "—" if value is None else f"{_display_number(value)} s"


def _bounded_error(error: BaseException) -> str:
    text = " ".join(f"{type(error).__name__}: {error}".split())
    return text[:MAX_ERROR_LENGTH]


def _publish_latest(target: queue.Queue, item: object) -> None:
    """Keep only the newest undelivered worker result."""

    try:
        target.put_nowait(item)
        return
    except queue.Full:
        pass
    try:
        target.get_nowait()
    except queue.Empty:
        pass
    try:
        target.put_nowait(item)
    except queue.Full:
        pass


def _default_snapshot_provider() -> object:
    """Call the one persistence-owned analytics projection entry point.

    INSTRUCTION: the future PERSISTENCE owner must return immutable prepared
    projections named metric_hub, science_lab, live_mirl and cosine.  Any
    database access or scientific calculation belongs behind that boundary.
    """

    from PERSISTENCE.storage import read_control_station_analytics

    return read_control_station_analytics()


def _default_export_provider(snapshot: object, request: "AnalyticsSheetRequest") -> str:
    """Delegate document generation to the reporting authority."""

    from PERSISTENCE.storage import export_analytics_sheet

    return str(export_analytics_sheet(snapshot=snapshot, request=request))


@dataclass(frozen=True, slots=True)
class AnalyticsSheetRequest:
    """Validated user selection; it contains no calculated analytics."""

    range_start: date
    range_end: date
    include_metric_hub: bool
    include_science_lab: bool
    include_live_mirl: bool
    include_cosine: bool

    def selected_sections(self) -> tuple[str, ...]:
        selected: list[str] = []
        if self.include_metric_hub:
            selected.append(PAGE_METRIC_HUB)
        if self.include_science_lab:
            selected.append(PAGE_SCIENCE_LAB)
        if self.include_live_mirl:
            selected.append(PAGE_LIVE_MIRL)
        if self.include_cosine:
            selected.append(PAGE_COSINE)
        return tuple(selected)


class SharedDashboardRefresh(QObject):
    """One non-blocking projection reader shared by all analytics pages."""

    bundle_ready = pyqtSignal(object)
    refresh_failed = pyqtSignal(str)
    refreshing_changed = pyqtSignal(bool)

    def __init__(
        self,
        provider: Callable[[], object],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._results: queue.Queue = queue.Queue(maxsize=1)
        self._generation = 0
        self._in_flight = False
        self._pending = False
        self._closed = False
        self._worker: threading.Thread | None = None

        self._poll = QTimer(self)
        self._poll.setInterval(POLL_INTERVAL_MS)
        self._poll.timeout.connect(self._take_result)

    @property
    def is_refreshing(self) -> bool:
        return self._in_flight

    def request_refresh(self) -> bool:
        """Start one worker or coalesce into one later refresh."""

        if self._closed:
            return False
        if self._in_flight:
            self._pending = True
            return True

        self._generation += 1
        generation = self._generation
        self._in_flight = True
        self.refreshing_changed.emit(True)

        def read() -> None:
            try:
                bundle = self._provider()
                if bundle is None:
                    raise RuntimeError("analytics read model returned no bundle")
            except Exception as error:  # worker failure must not touch Qt
                _publish_latest(
                    self._results,
                    (generation, None, _bounded_error(error)),
                )
            else:
                _publish_latest(self._results, (generation, bundle, None))

        self._worker = threading.Thread(
            target=read,
            name="MyelinAnalyticsRefresh",
            daemon=True,
        )
        self._worker.start()
        if not self._poll.isActive():
            self._poll.start()
        return True

    def shutdown(
        self,
        *,
        timeout: float = ANALYTICS_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> bool:
        """Reject new work, stop delivery, then wait BOUNDED for the reader.

        Returns whether the accepted worker actually finished.  ``False`` means
        a reader overran the budget and is still touching persistence -- the
        caller is told the truth rather than being blocked indefinitely.
        """

        self._closed = True
        self._pending = False
        self._poll.stop()
        worker = self._worker
        if worker is None or not worker.is_alive():
            self._worker = None
            return True
        worker.join(max(0.0, float(timeout)))
        if worker.is_alive():
            return False
        self._worker = None
        return True

    def _take_result(self) -> None:
        if self._closed:
            self._poll.stop()
            return
        try:
            generation, bundle, error = self._results.get_nowait()
        except queue.Empty:
            return

        self._poll.stop()
        self._in_flight = False
        self.refreshing_changed.emit(False)
        if generation == self._generation:
            if error is None:
                self.bundle_ready.emit(bundle)
            else:
                self.refresh_failed.emit(error)

        if self._pending and not self._closed:
            self._pending = False
            self.request_refresh()


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def _make_card(title: str, value: str = "—", note: str = "") -> QFrame:
    card = QFrame()
    card.setObjectName("analyticsCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(5)
    heading = QLabel(title.upper())
    heading.setObjectName("analyticsCardTitle")
    number = QLabel(value)
    number.setObjectName("analyticsCardValue")
    number.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    layout.addWidget(heading)
    layout.addWidget(number)
    if note:
        detail = QLabel(note)
        detail.setObjectName("analyticsCardNote")
        detail.setWordWrap(True)
        layout.addWidget(detail)
    return card


def _empty_card(message: str) -> QFrame:
    return _make_card("STATUS", "NO DATA", message)


def _table(headers: Sequence[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setObjectName("analyticsTable")
    table.setHorizontalHeaderLabels(list(headers))
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return table


def _replace_rows(table: QTableWidget, rows: Sequence[Sequence[object]]) -> None:
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            table.setItem(
                row_index,
                column_index,
                QTableWidgetItem(_safe_text(value)),
            )


class DashboardPage(QWidget):
    """Common readable shell; subclasses only map prepared fields to widgets."""

    refresh_requested = pyqtSignal()

    def __init__(self, title: str, subtitle: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsPage")
        self._last_projection = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        scroll = QScrollArea()
        scroll.setObjectName("analyticsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(30, 26, 30, 36)
        self.body.setSpacing(18)
        scroll.setWidget(body)
        root.addWidget(scroll)

        header = QHBoxLayout()
        text = QVBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("analyticsPageTitle")
        description = QLabel(subtitle)
        description.setObjectName("analyticsPageSubtitle")
        description.setWordWrap(True)
        self.status = QLabel("NOT LOADED")
        self.status.setObjectName("analyticsStatus")
        text.addWidget(heading)
        text.addWidget(description)
        header.addLayout(text, 1)
        self.refresh_button = QPushButton("REFRESH")
        self.refresh_button.setObjectName("analyticsRefreshButton")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self.status, alignment=Qt.AlignmentFlag.AlignTop)
        header.addWidget(self.refresh_button, alignment=Qt.AlignmentFlag.AlignTop)
        self.body.addLayout(header)

        self.cards = QGridLayout()
        self.cards.setHorizontalSpacing(14)
        self.cards.setVerticalSpacing(14)
        self.body.addLayout(self.cards)

    @property
    def last_projection(self):
        return self._last_projection

    def set_refreshing(self, refreshing: bool) -> None:
        self.refresh_button.setEnabled(not refreshing)
        if refreshing:
            self.status.setText("REFRESHING")

    def show_refresh_failure(self) -> None:
        # Preserve the last honest snapshot instead of replacing it with a
        # plausible empty state after a transient read failure.
        self.status.setText(
            "REFRESH FAILED" if self._last_projection is not None else "UNAVAILABLE"
        )

    def render_projection(self, projection: object) -> None:
        self._last_projection = projection
        self.status.setText("AUTHORITATIVE DATA")

    def _replace_cards(self, values: Sequence[tuple[str, str, str]]) -> None:
        _clear_layout(self.cards)
        for index, (title, value, note) in enumerate(values):
            self.cards.addWidget(_make_card(title, value, note), index // 3, index % 3)


class MetricHubPage(DashboardPage):
    """Metric Hub formatter; all rates and counts arrive pre-calculated."""

    def __init__(self, parent=None) -> None:
        super().__init__(
            "METRIC HUB",
            "Operational overview and MIRL evidence populations",
            parent,
        )
        self.details = _table(("Population", "Status", "Value", "Evidence"))
        self.body.addWidget(self.details)
        self.body.addStretch(1)

    def render_projection(self, projection: object) -> None:
        super().render_projection(projection)
        available = bool(_field(projection, "available", False))
        self.status.setText("ONLINE" if available else "NO EVIDENCE")
        if not available:
            self._replace_cards(
                (("Status", "NO DATA", _safe_text(_field(projection, "status_message"))),)
            )
            _replace_rows(self.details, ())
            return

        self._replace_cards(
            (
                ("Sessions", _display_number(_field(projection, "total_session_count")), "Recorded sessions"),
                ("Operational triggers", _display_number(_field(projection, "total_trigger_count")), "Committed trigger evidence"),
                ("Native MIRL episodes", _display_number(_field(projection, "native_episode_count")), "Native population only"),
                ("Stable recovery rate", _display_number(_field(projection, "verified_stable_recovery_rate_percent"), suffix="%"), "Prepared native metric"),
                ("Episode closure rate", _display_number(_field(projection, "episode_closure_rate_percent"), suffix="%"), "Prepared native metric"),
                ("Mean stable recovery", _display_seconds(_field(projection, "average_stable_recovery_latency_seconds")), "Prepared latency"),
                ("Legacy observations", _display_number(_field(projection, "legacy_observation_count")), "Kept separate from native MIRL"),
                ("Legacy resolved return", _display_number(_field(projection, "legacy_resolved_return_rate_percent"), suffix="%"), "Legacy population only"),
                ("Exclusions", _display_number(_field(projection, "exclusion_count")), _safe_text(_field(projection, "evidence_scope_label"))),
            )
        )
        rows = []
        for detail in tuple(_field(projection, "read_model_detail_rows", ()) or ()):
            rows.append(
                (
                    _field(detail, "population", _field(detail, "label")),
                    _field(detail, "status"),
                    _field(detail, "value"),
                    _field(detail, "evidence", _field(detail, "detail")),
                )
            )
        _replace_rows(self.details, rows)


class ScienceLabPage(DashboardPage):
    """Science Lab displays formulas, evidence scope and supplied values."""

    def __init__(self, parent=None) -> None:
        super().__init__(
            "MYELIN SCIENCE LAB",
            "Scientific presentation of committed behavioral evidence",
            parent,
        )
        self.metrics = _table(("Metric", "Value", "Formula", "Population", "Limit / exclusion"))
        self.body.addWidget(self.metrics)
        self.limitation = QLabel("Scientific evidence limitation: —")
        self.limitation.setObjectName("analyticsEvidenceNote")
        self.limitation.setWordWrap(True)
        self.body.addWidget(self.limitation)
        self.body.addStretch(1)

    def render_projection(self, projection: object) -> None:
        super().render_projection(projection)
        available = bool(_field(projection, "available", False))
        self.status.setText("ONLINE" if available else "NO EVIDENCE")
        limitation = _safe_text(
            _field(projection, "scientific_evidence_limitation"),
            "No scientific evidence statement supplied",
            1_500,
        )
        self.limitation.setText(f"Scientific evidence limitation: {limitation}")
        if not available:
            self._replace_cards(
                (("Status", "NO DATA", _safe_text(_field(projection, "empty_state_reason"))),)
            )
            _replace_rows(self.metrics, ())
            return

        counts = _field(projection, "counts", {}) or {}
        self._replace_cards(
            (
                ("Recovery attempts", _display_number(_field(projection, "recovery_attempt_count")), "Recorded attempts"),
                ("Relapses", _display_number(_field(projection, "relapse_count")), "Recorded relapse evidence"),
                ("Evidence exclusions", _display_number(_field(_field(projection, "metadata"), "exclusion_count")), "Explicitly withheld evidence"),
                ("Native episodes", _display_number(_field(counts, "native_episode_count")), "Native population"),
                ("Operational triggers", _display_number(_field(counts, "total_trigger_count")), "Operational population"),
                ("Legacy observations", _display_number(_field(counts, "legacy_observation_count")), "Separate legacy population"),
            )
        )
        rows = []
        for metric in tuple(_field(projection, "metrics", ()) or ()):
            exclusions = _field(metric, "exclusions", ()) or ()
            note = _field(metric, "na_reason") or "; ".join(map(str, exclusions))
            rows.append(
                (
                    _field(metric, "metric_name"),
                    f"{_display_number(_field(metric, 'value'))} {_safe_text(_field(metric, 'unit'), '')}".strip(),
                    _field(metric, "formula"),
                    _field(metric, "evidence_population"),
                    note,
                )
            )
        _replace_rows(self.metrics, rows)


class LiveMirlPage(DashboardPage):
    """Live MIRL displays stored episode and event projections unchanged."""

    def __init__(self, parent=None) -> None:
        super().__init__(
            "LIVE MIRL",
            "Recorded intervention journeys and recovery evidence",
            parent,
        )
        self.episodes = _table(("Episode", "Status", "Outcome", "Started", "Attempts", "Relapses"))
        self.events = _table(("Sequence", "Time", "Event", "Class", "Reference"))
        self.body.addWidget(self.episodes)
        self.body.addWidget(self.events)
        self.body.addStretch(1)

    def render_projection(self, projection: object) -> None:
        super().render_projection(projection)
        available = bool(_field(projection, "available", False))
        active = tuple(_field(projection, "active_episodes", ()) or ())
        closed = tuple(_field(projection, "recently_closed_episodes", ()) or ())
        self.status.setText("EPISODE ACTIVE" if active else ("ONLINE" if available else "NO EVIDENCE"))
        metadata = _field(projection, "metadata")
        self._replace_cards(
            (
                ("Active episodes", _display_number(len(active)), "Count of supplied active rows"),
                ("Recently closed", _display_number(len(closed)), "Count of supplied recent rows"),
                ("Evidence exclusions", _display_number(_field(metadata, "exclusion_count")), "Authoritative exclusions"),
            )
        )
        episode_rows = []
        for episode in (*active, *closed):
            episode_rows.append(
                (
                    _field(episode, "short_display_id", _field(episode, "episode_id")),
                    _field(episode, "episode_status"),
                    _field(episode, "final_outcome", "IN PROGRESS"),
                    _field(episode, "started_at"),
                    _field(episode, "recovery_attempt_count"),
                    _field(episode, "relapse_count"),
                )
            )
        _replace_rows(self.episodes, episode_rows)

        focus = active[0] if active else (closed[0] if closed else None)
        timeline_rows = []
        for event in tuple(_field(focus, "timeline", ()) or ()):
            timeline_rows.append(
                (
                    _field(event, "episode_seq"),
                    _field(event, "occurred_at"),
                    _field(event, "event_name"),
                    _field(event, "observed_or_derived"),
                    _field(event, "reference", _field(event, "reason_or_outcome_code")),
                )
            )
        _replace_rows(self.events, timeline_rows)


class CosinePage(DashboardPage):
    """COSINE displays its independent, authoritative analysis snapshot."""

    def __init__(self, parent=None) -> None:
        super().__init__(
            "COSINE — STREAMING OVERVIEW",
            "Choice-Oriented Streaming Insight and Navigation Engine",
            parent,
        )
        self.platforms = _table(("Platform", "Check-ins", "Returned", "Finished", "Continued", "Foreground"))
        self.events = _table(("Time", "Platform", "Event", "Content"))
        self.body.addWidget(self.platforms)
        self.body.addWidget(self.events)
        self.body.addStretch(1)

    def render_projection(self, projection: object) -> None:
        super().render_projection(projection)
        quality = _field(projection, "data_quality")
        available = bool(_field(quality, "available", False))
        current = _field(projection, "current")
        overview = _field(projection, "overview")
        self.status.setText(_safe_text(_field(current, "status_label"), "ONLINE" if available else "NO EVIDENCE"))
        self._replace_cards(
            (
                ("Streaming check-ins", _display_number(_field(overview, "streaming_checkins")), "Displayed check-ins"),
                ("Returned to focus", _display_number(_field(overview, "returned_to_focus")), "Confirmed COSINE outcomes"),
                ("Chose to finish", _display_number(_field(overview, "chose_to_finish")), "Confirmed choice"),
                ("Continued watching", _display_number(_field(overview, "continued_watching")), "Confirmed or timed-out outcome"),
                ("Usual return time", _display_seconds(_field(overview, "usual_return_time_seconds")), "Prepared COSINE statistic"),
                ("Current platform", _safe_text(_field(current, "platform_display_name")), _safe_text(_field(current, "content_title"))),
            )
        )
        platform_rows = []
        for platform in tuple(_field(projection, "platform_summaries", ()) or ())[:3]:
            platform_rows.append(
                (
                    _field(platform, "display_name"),
                    _field(platform, "displayed_checkins"),
                    _field(platform, "returned_to_focus"),
                    _field(platform, "chose_to_finish"),
                    _field(platform, "continued_watching"),
                    _display_seconds(_field(platform, "active_foreground_ott_seconds")),
                )
            )
        _replace_rows(self.platforms, platform_rows)

        event_rows = []
        for event in tuple(_field(projection, "latest_events", ()) or ()):
            event_rows.append(
                (
                    _field(event, "occurred_at_utc"),
                    _field(event, "platform_display_name"),
                    _field(event, "event_key"),
                    _field(event, "text"),
                )
            )
        _replace_rows(self.events, event_rows)


class AnalyticsSheetDialog(QDialog):
    """User-facing report selection surface; it calculates no evidence."""

    export_requested = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("analyticsSheetDialog")
        self.setWindowTitle("MYELIN Analytics Sheet")
        self.setModal(False)
        self.resize(620, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 26)
        root.setSpacing(16)
        title = QLabel("ANALYTICS SHEET")
        title.setObjectName("analyticsPageTitle")
        description = QLabel(
            "Choose which authoritative dashboard projections should appear "
            "in the exported sheet."
        )
        description.setObjectName("analyticsPageSubtitle")
        description.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(description)

        dates = QGridLayout()
        dates.addWidget(QLabel("FROM"), 0, 0)
        dates.addWidget(QLabel("TO"), 0, 1)
        self.start_date = QDateEdit(QDate.currentDate().addMonths(-1))
        self.end_date = QDateEdit(QDate.currentDate())
        for editor in (self.start_date, self.end_date):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd MMM yyyy")
        dates.addWidget(self.start_date, 1, 0)
        dates.addWidget(self.end_date, 1, 1)
        root.addLayout(dates)

        self.sections = {
            PAGE_METRIC_HUB: QCheckBox("Metric Hub"),
            PAGE_SCIENCE_LAB: QCheckBox("Science Lab"),
            PAGE_LIVE_MIRL: QCheckBox("Live MIRL"),
            PAGE_COSINE: QCheckBox("COSINE"),
        }
        for checkbox in self.sections.values():
            checkbox.setChecked(True)
            root.addWidget(checkbox)

        self.message = QLabel("Ready")
        self.message.setObjectName("analyticsEvidenceNote")
        self.message.setWordWrap(True)
        root.addWidget(self.message)
        root.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.export_button = buttons.addButton(
            "EXPORT PDF",
            QDialogButtonBox.ButtonRole.AcceptRole,
        )
        buttons.rejected.connect(self.close)
        self.export_button.clicked.connect(self._request_export)
        root.addWidget(buttons)

    def set_busy(self, busy: bool) -> None:
        self.export_button.setEnabled(not busy)
        self.message.setText("Preparing authoritative report…" if busy else "Ready")

    def show_error(self, message: str) -> None:
        self.set_busy(False)
        self.message.setText(_safe_text(message, "Export unavailable"))

    def show_success(self, path: str) -> None:
        self.set_busy(False)
        self.message.setText(f"Saved: {_safe_text(path)}")

    def _request_export(self) -> None:
        start = self.start_date.date().toPyDate()
        end = self.end_date.date().toPyDate()
        if start > end:
            self.show_error("The From date must not be later than the To date.")
            return
        request = AnalyticsSheetRequest(
            range_start=start,
            range_end=end,
            include_metric_hub=self.sections[PAGE_METRIC_HUB].isChecked(),
            include_science_lab=self.sections[PAGE_SCIENCE_LAB].isChecked(),
            include_live_mirl=self.sections[PAGE_LIVE_MIRL].isChecked(),
            include_cosine=self.sections[PAGE_COSINE].isChecked(),
        )
        if not request.selected_sections():
            self.show_error("Select at least one analytics section.")
            return
        self.export_requested.emit(request)


class _AnalyticsExport(QObject):
    """One guarded background export; the reporting owner does the work."""

    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)
    busy_changed = pyqtSignal(bool)

    def __init__(
        self,
        report_access,
        exporter: Callable[[object, AnalyticsSheetRequest], str],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._report_access = report_access
        self._exporter = exporter
        self._snapshot = None
        self._busy = False
        self._closed = False
        # The worker is retained so shutdown can join it (C12-C).  An export
        # discarded its thread entirely, which made a bounded wait impossible.
        self._worker: threading.Thread | None = None
        self._results: queue.Queue = queue.Queue(maxsize=1)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_INTERVAL_MS)
        self._poll.timeout.connect(self._take_result)

    def set_snapshot(self, snapshot: object) -> None:
        self._snapshot = snapshot

    def begin(self, request: AnalyticsSheetRequest) -> bool:
        if self._closed or self._busy:
            return False
        if self._snapshot is None:
            self.failed.emit("Refresh analytics before exporting.")
            return False
        refusal = self._report_access.refusal()
        if refusal is not None:
            self.failed.emit(_safe_text(_field(refusal, "message", refusal)))
            return False
        try:
            lease = self._report_access.begin_export("Analytics Sheet")
        except Exception as error:
            self.failed.emit(_bounded_error(error))
            return False

        snapshot = self._snapshot
        self._busy = True
        self.busy_changed.emit(True)

        def export() -> None:
            try:
                path = self._exporter(snapshot, request)
            except Exception as error:
                result = (None, _bounded_error(error))
            else:
                result = (_safe_text(path), None)
            finally:
                try:
                    lease.release()
                except Exception:
                    pass
            _publish_latest(self._results, result)

        self._worker = threading.Thread(
            target=export,
            name="MyelinAnalyticsExport",
            daemon=True,
        )
        self._worker.start()
        self._poll.start()
        return True

    def shutdown(
        self,
        *,
        timeout: float = ANALYTICS_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> bool:
        """Reject new exports, stop delivery, then wait BOUNDED for the writer.

        Returns whether the accepted export actually finished.
        """

        self._closed = True
        self._poll.stop()
        worker = self._worker
        if worker is None or not worker.is_alive():
            self._worker = None
            return True
        worker.join(max(0.0, float(timeout)))
        if worker.is_alive():
            return False
        self._worker = None
        return True

    def _take_result(self) -> None:
        if self._closed:
            self._poll.stop()
            return
        try:
            path, error = self._results.get_nowait()
        except queue.Empty:
            return
        self._poll.stop()
        self._busy = False
        self.busy_changed.emit(False)
        if error is not None:
            self.failed.emit(error)
        else:
            self.succeeded.emit(path)


class AnalyticsController(QObject):
    """Compose all analytics surfaces around one read-only refresh lane."""

    def __init__(
        self,
        *,
        report_access,
        red_guard,
        snapshot_provider: Callable[[], object] | None = None,
        export_provider: Callable[[object, AnalyticsSheetRequest], str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._report_access = report_access
        self._red_guard = red_guard
        self._closed = False
        self._bundle = None
        self._pages: dict[str, DashboardPage] = {}
        self._composer: AnalyticsSheetDialog | None = None

        self._refresh = SharedDashboardRefresh(
            snapshot_provider or _default_snapshot_provider,
            parent=self,
        )
        self._refresh.bundle_ready.connect(self._deliver_bundle)
        self._refresh.refresh_failed.connect(self._refresh_failed)
        self._refresh.refreshing_changed.connect(self._refreshing_changed)

        self._export = _AnalyticsExport(
            report_access,
            export_provider or _default_export_provider,
            parent=self,
        )

    def create_metric_hub_page(self) -> MetricHubPage:
        return self._create_page(PAGE_METRIC_HUB, MetricHubPage)

    def create_science_lab_page(self) -> ScienceLabPage:
        return self._create_page(PAGE_SCIENCE_LAB, ScienceLabPage)

    def create_live_mirl_page(self) -> LiveMirlPage:
        return self._create_page(PAGE_LIVE_MIRL, LiveMirlPage)

    def create_cosine_page(self) -> CosinePage:
        return self._create_page(PAGE_COSINE, CosinePage)

    def page_opened(self, page_name: str) -> None:
        """Refresh only when an analytics page becomes visible."""

        if page_name in PROJECTION_NAMES:
            self._refresh.request_refresh()

    def open_composer(self) -> bool:
        """Open one Analytics Sheet surface after Red/report checks."""

        if self._closed:
            return False
        if not self._red_guard.allow_surface(SurfaceKind.ANALYTICS_COMPOSER):
            self._red_guard.restore_authoritative_surface()
            return False
        refusal = self._report_access.refusal()
        if refusal is not None:
            return False
        if self._composer is None:
            self._composer = AnalyticsSheetDialog(
                parent=self.parent() if isinstance(self.parent(), QWidget) else None
            )
            self._composer.export_requested.connect(self._export.begin)
            self._export.busy_changed.connect(self._composer.set_busy)
            self._export.failed.connect(self._composer.show_error)
            self._export.succeeded.connect(self._composer.show_success)
        self._composer.show()
        self._composer.raise_()
        self._composer.activateWindow()
        self._refresh.request_refresh()
        return True

    def shutdown(
        self,
        *,
        timeout: float = ANALYTICS_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> bool:
        """Stop delivery and bound-wait for accepted analytics workers.

        Returns whether every accepted worker finished inside the budget.
        Both lanes are always asked to stop even if the first one overruns, and
        a repeat call still reports the current worker truth -- a shutdown that
        returned ``False`` may be retried once the surface is really idle.
        """

        self._closed = True
        budget = max(0.0, float(timeout))
        drained = self._refresh.shutdown(timeout=budget)
        drained = self._export.shutdown(timeout=budget) and drained
        if self._composer is not None:
            self._composer.close()
            self._composer.deleteLater()
            self._composer = None
        return drained

    def _create_page(self, name: str, page_type):
        existing = self._pages.get(name)
        if existing is not None:
            return existing
        page = page_type()
        page.refresh_requested.connect(self._refresh.request_refresh)
        self._pages[name] = page
        return page

    def _deliver_bundle(self, bundle: object) -> None:
        self._bundle = bundle
        self._export.set_snapshot(bundle)
        for page_name, page in self._pages.items():
            projection = _projection(bundle, PROJECTION_NAMES[page_name])
            if projection is not None:
                page.render_projection(projection)
            else:
                page.show_refresh_failure()

    def _refresh_failed(self, _message: str) -> None:
        for page in self._pages.values():
            page.show_refresh_failure()

    def _refreshing_changed(self, refreshing: bool) -> None:
        for page in self._pages.values():
            page.set_refreshing(refreshing)
