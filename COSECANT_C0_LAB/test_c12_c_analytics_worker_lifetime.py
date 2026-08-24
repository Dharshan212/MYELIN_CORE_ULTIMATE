"""C12-C -- analytics workers must not outlive analytics shutdown.

``SharedDashboardRefresh`` and ``_AnalyticsExport`` each start a daemon
thread that reads MYELIN persistence.  Their ``shutdown()`` stops the Qt
delivery timer but never waits for the worker, so ``analytics.shutdown()``
can return while a reader is still inside the database that the launcher is
about to release two lines later.

The repaired contract:

    shutdown begins
        -> reject new analytics work
        -> stop UI delivery timers
        -> BOUNDED wait for accepted workers
        -> return truthful success/failure
"""

from __future__ import annotations

import threading
import time

import pytest

import _lab  # noqa: F401

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication

from datetime import date

from CONTROL_STATION.analytics import (
    PAGE_METRIC_HUB,
    AnalyticsController,
    AnalyticsSheetRequest,
    SharedDashboardRefresh,
    _AnalyticsExport,
)


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


class _Gate:
    """A provider that blocks inside the worker until released."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()

    def __call__(self, *args, **kwargs):
        self.entered.set()
        self.release.wait(20.0)
        self.finished.set()
        return "C12C"


SHEET_REQUEST = AnalyticsSheetRequest(
    range_start=date(2026, 1, 1),
    range_end=date(2026, 1, 31),
    include_metric_hub=True,
    include_science_lab=True,
    include_live_mirl=True,
    include_cosine=True,
)


class _FakeLease:
    def release(self) -> None:
        pass


class _FakeReportAccess:
    def refusal(self):
        return None

    def begin_export(self, owner: str):
        return _FakeLease()


def _live_worker_names() -> set[str]:
    return {
        thread.name
        for thread in threading.enumerate()
        if thread.is_alive()
        and thread.name in {"MyelinAnalyticsRefresh", "MyelinAnalyticsExport"}
    }


# ---------------------------------------------------------------------------
# Refresh worker
# ---------------------------------------------------------------------------

def test_refresh_shutdown_waits_for_its_worker(qt_app):
    gate = _Gate()
    refresh = SharedDashboardRefresh(gate)
    assert refresh.request_refresh() is True
    assert gate.entered.wait(10.0)

    # A shutdown that cannot finish must say so, not lie.
    assert refresh.shutdown(timeout=0.4) is False
    assert "MyelinAnalyticsRefresh" in _live_worker_names()

    gate.release.set()
    assert refresh.shutdown(timeout=10.0) is True
    assert "MyelinAnalyticsRefresh" not in _live_worker_names()


def test_refresh_rejects_work_after_shutdown(qt_app):
    refresh = SharedDashboardRefresh(lambda: "bundle")
    assert refresh.shutdown(timeout=5.0) is True
    assert refresh.request_refresh() is False


def test_refresh_shutdown_is_idempotent_and_bounded(qt_app):
    refresh = SharedDashboardRefresh(lambda: "bundle")
    assert refresh.shutdown(timeout=5.0) is True
    started = time.monotonic()
    assert refresh.shutdown(timeout=5.0) is True
    assert time.monotonic() - started < 1.0


# ---------------------------------------------------------------------------
# Export worker
# ---------------------------------------------------------------------------

def test_export_shutdown_waits_for_its_worker(qt_app):
    gate = _Gate()
    export = _AnalyticsExport(_FakeReportAccess(), lambda snapshot, request: gate())
    export.set_snapshot(object())
    assert export.begin(SHEET_REQUEST) is True
    assert gate.entered.wait(10.0)

    assert export.shutdown(timeout=0.4) is False
    assert "MyelinAnalyticsExport" in _live_worker_names()

    gate.release.set()
    assert export.shutdown(timeout=10.0) is True
    assert "MyelinAnalyticsExport" not in _live_worker_names()


def test_export_rejects_work_after_shutdown(qt_app):
    export = _AnalyticsExport(_FakeReportAccess(), lambda snapshot, request: "x")
    export.set_snapshot(object())
    assert export.shutdown(timeout=5.0) is True
    assert export.begin(SHEET_REQUEST) is False


# ---------------------------------------------------------------------------
# Controller -- the launcher's actual call site
# ---------------------------------------------------------------------------

class _RedGuard:
    def allow_surface(self, kind):
        return True

    def restore_authoritative_surface(self):
        pass


def test_controller_shutdown_bounded_and_truthful(qt_app):
    gate = _Gate()
    controller = AnalyticsController(
        report_access=_FakeReportAccess(),
        red_guard=_RedGuard(),
        snapshot_provider=gate,
    )
    controller.page_opened(PAGE_METRIC_HUB)
    assert gate.entered.wait(10.0)

    started = time.monotonic()
    assert controller.shutdown(timeout=0.4) is False
    assert time.monotonic() - started < 5.0  # bounded: no infinite GUI wait

    gate.release.set()
    assert controller.shutdown(timeout=10.0) is True
    assert _live_worker_names() == set()


def test_controller_clean_shutdown_reports_success(qt_app):
    controller = AnalyticsController(
        report_access=_FakeReportAccess(),
        red_guard=_RedGuard(),
        snapshot_provider=lambda: "bundle",
    )
    assert controller.shutdown(timeout=5.0) is True
    assert controller.open_composer() is False
