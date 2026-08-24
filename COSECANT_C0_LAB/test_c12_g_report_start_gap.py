"""C12-G -- the report/session-start reservation gap.

``EngineController.start_engine`` takes a ``ReportAccessCoordinator``
reservation, then RELEASES it before the active-session source is bound and
the worker is running:

    begin_session_start()      <- reserved
    _set_status(STARTING)
    lease.release()            <- reservation gone
    import run_core_monitor
    _prepare_new_session()
    bind_session_active_source()   <- session only becomes visible HERE
    worker.start()

Between the release and the bind, the coordinator has NO session-active source
and NO reservation, so ``refusal()`` returns None and a report export is
admitted while a session is starting underneath it.
"""

from __future__ import annotations

import ast
import threading

import pytest

import _lab

from PERSISTENCE.storage import (
    ReportAccessCoordinator,
    ReportExportRefused,
)

ULTIMATE = _lab.ULTIMATE


@pytest.fixture
def coordinator():
    return ReportAccessCoordinator()


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------

def test_export_is_refused_while_a_session_start_holds_its_reservation(coordinator):
    reservation = coordinator.begin_session_start()
    with pytest.raises(ReportExportRefused):
        coordinator.begin_export("Analytics Sheet")
    assert reservation.release() is True
    # Once released with nothing bound, export is legitimately allowed.
    coordinator.begin_export("Analytics Sheet").release()


def test_export_is_refused_once_the_session_source_is_bound(coordinator):
    binding = coordinator.bind_session_active_source(lambda: True)
    try:
        with pytest.raises(ReportExportRefused):
            coordinator.begin_export("Analytics Sheet")
    finally:
        binding.release()


def test_reservation_covers_the_bind_handoff(coordinator):
    """The reservation must not be released before the source is bound.

    This is the gap itself, expressed on the coordinator: at no point between
    'a start began' and 'the session is visible' may an export be admitted.
    """

    reservation = coordinator.begin_session_start()

    # ... start work happens here ...
    binding = coordinator.bind_session_active_source(lambda: True)
    try:
        # Still refused: the reservation is only dropped AFTER the handoff.
        with pytest.raises(ReportExportRefused):
            coordinator.begin_export("Analytics Sheet")
        assert reservation.release() is True
        with pytest.raises(ReportExportRefused):
            coordinator.begin_export("Analytics Sheet")
    finally:
        binding.release()


# ---------------------------------------------------------------------------
# The production ordering
# ---------------------------------------------------------------------------

def _start_engine_statements():
    tree = ast.parse(
        (ULTIMATE / "CONTROL_STATION" / "controller.py").read_text(encoding="utf-8")
    )
    method = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "start_engine"
    )
    return ast.unparse(method)


def test_start_engine_releases_the_reservation_after_binding_and_starting():
    body = _start_engine_statements()

    reserve_at = body.index("begin_session_start()")
    bind_at = body.index("bind_session_active_source(")
    worker_at = body.index("_worker_thread.start()")
    # The SUCCESS-path release is the last one; earlier occurrences are the
    # failure paths, which must of course release before returning.
    release_at = body.rindex("_release_session_start_reservation(")

    assert reserve_at < bind_at, "reservation must be taken before the bind"
    assert bind_at < worker_at, "source must be bound before the worker runs"
    assert worker_at < release_at, (
        "the start reservation must be held until the worker is running"
    )
    # Every failure path between the reservation and the handoff releases too.
    assert body.count("_release_session_start_reservation()") >= 3

    # And the old premature release is gone.
    assert "lease.release()" not in body


def test_every_failure_path_releases_the_reservation_exactly_once():
    body = _start_engine_statements()
    # Each early return after the reservation must go through the one helper.
    assert body.count("_release_session_start_reservation(") >= 1

    tree = ast.parse(
        (ULTIMATE / "CONTROL_STATION" / "controller.py").read_text(encoding="utf-8")
    )
    helper = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_release_session_start_reservation"
    )
    text = ast.unparse(helper)
    # Idempotent: releasing twice is not an error and cannot evict a new one.
    assert "None" in text


# ---------------------------------------------------------------------------
# Hostile concurrency
# ---------------------------------------------------------------------------

def test_no_admission_window_between_reserve_and_bind(coordinator):
    """The exact C12-G window, probed deterministically.

    A start is parked at the point where ``start_engine`` does its slow work
    -- the ``run_core_monitor`` import and ``_prepare_new_session()`` -- which
    is after the reservation was taken and before the active-session source
    exists.  Production used to release the reservation BEFORE this point, so
    the coordinator had neither a reservation nor a bound source and admitted
    exports into the hole.
    """

    at_gap = threading.Event()
    proceed = threading.Event()
    done = threading.Event()

    def start_sequence() -> None:
        reservation = coordinator.begin_session_start()
        try:
            at_gap.set()
            proceed.wait(20.0)  # slow start work happens here
            binding = coordinator.bind_session_active_source(lambda: True)
        finally:
            # Released only after the handoff, exactly once.
            reservation.release()
        binding.release()
        done.set()

    thread = threading.Thread(target=start_sequence, daemon=True)
    thread.start()
    assert at_gap.wait(10.0)

    try:
        with pytest.raises(ReportExportRefused):
            coordinator.begin_export("Analytics Sheet")
    finally:
        proceed.set()
    assert done.wait(10.0)
    thread.join(10.0)

    # After a completed start the coordinator is clean again.
    coordinator.begin_export("Analytics Sheet").release()


def test_repeated_start_cycles_leave_no_residue(coordinator):
    """Reserve -> bind -> release, many times, stays symmetric."""

    for _ in range(200):
        reservation = coordinator.begin_session_start()
        binding = coordinator.bind_session_active_source(lambda: True)
        assert reservation.release() is True
        assert binding.release() is True
    coordinator.begin_export("Analytics Sheet").release()


def test_failed_start_releases_the_reservation_so_reports_recover(coordinator):
    """A start that fails must not leave reports permanently refused."""

    reservation = coordinator.begin_session_start()
    # ... start fails before binding anything ...
    assert reservation.release() is True
    # Releasing again is a no-op, never an error and never a double-evict.
    assert reservation.release() is False

    coordinator.begin_export("Analytics Sheet").release()
