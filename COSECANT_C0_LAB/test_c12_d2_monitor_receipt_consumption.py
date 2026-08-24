"""C12-D2 -- Monitor consumes the lifecycle receipts it owns.

C12-D made storage consume the receipts it owns end to end.  The receipts
handed back RAW to Monitor -- session open, session close, emergency, profile
learning update, trigger persistence -- stayed in the lane registry forever,
even once their terminal result had been fully processed.

Measured before the repair:

    21 session cycles      -> 42 retained COMMITTED receipts
    1 admitted trigger     -> 1 retained receipt, _pending_trigger already None

Final invariant:

    PENDING receipt                          -> retained
    TERMINAL receipt still needed by caller   -> retained
    TERMINAL receipt fully consumed by owner  -> forgotten
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

import _lab
from _lab import INSTAGRAM, LECTURE, ScriptedForegroundReader, build_services

from CORE_ENGINE.blacklist import SineThresholdPolicy
from CORE_ENGINE.monitor import PendingTriggerWorkflow, WindowsMonitorCoordinator


DURABLE = 10.0

FAST_THRESHOLDS = SineThresholdPolicy(
    stage_one_seconds=0.3,
    stage_two_cumulative_seconds=1.5,
    offer_retry_seconds=0.1,
)


class _Bench:
    """One real service graph plus a factory for real coordinators."""

    def __init__(self) -> None:
        self.foreground = ScriptedForegroundReader(LECTURE)
        self.services = build_services(
            foreground=self.foreground, fast_cosecant=True
        )
        self.storage = self.services.storage

    def make_coordinator(self) -> WindowsMonitorCoordinator:
        return WindowsMonitorCoordinator(
            profile_type="study",
            services=self.services,
            foreground_reader=self.foreground,
            stop_event=threading.Event(),
            pause_event=threading.Event(),
            ready_event=threading.Event(),
            loop_stopped_event=threading.Event(),
            cleanup_complete_event=threading.Event(),
            telemetry_queue=queue.Queue(),
            command_queue=queue.Queue(),
            poll_seconds=0.2,
        )


@pytest.fixture
def bench():
    harness = _Bench()
    try:
        yield harness
    finally:
        harness.storage.shutdown()


def _outstanding(bench) -> int:
    return bench.storage._lane.outstanding()


def _open_session(bench, coordinator) -> int:
    coordinator._start_session()
    return int(coordinator.session_id)


def _close_session(bench, coordinator, reason: str = "STOPPED") -> None:
    receipt = bench.storage.close_monitor_session(
        session_id=coordinator.session_id, reason=reason
    )
    coordinator._wait_for_commit(
        receipt, timeout_seconds=DURABLE, operation="session close"
    )


# ---------------------------------------------------------------------------
# 1. A RUNNING receipt can never be forgotten
# ---------------------------------------------------------------------------

def test_running_receipt_cannot_be_forgotten(bench):
    gate = threading.Event()
    lane = bench.storage._lane

    def blocking(connection):
        gate.wait(20.0)
        return None

    receipt = lane.submit("C12D2 blocking", blocking)
    try:
        assert receipt.state.name == "RUNNING"
        coordinator = bench.make_coordinator()
        # Monitor's own consumption helper must not release an outstanding
        # transaction, even when asked directly.
        coordinator._consume_receipt(receipt.receipt_id)
        assert lane.receipt(receipt.receipt_id) is not None
        assert bench.storage.forget_receipt(receipt.receipt_id) is False
    finally:
        gate.set()
    settled = lane.wait(receipt.receipt_id, timeout_seconds=DURABLE)
    assert settled is not None and settled.state.name == "COMMITTED"


# ---------------------------------------------------------------------------
# 2 + 3. Session open / close receipts are consumed
# ---------------------------------------------------------------------------

def test_session_open_receipt_is_forgotten_after_consumption(bench):
    baseline = _outstanding(bench)
    coordinator = bench.make_coordinator()
    session_id = _open_session(bench, coordinator)

    assert session_id > 0, "the session must really have been opened"
    assert _outstanding(bench) == baseline, (
        "the session-open receipt survived its own consumption"
    )


def test_session_close_receipt_is_forgotten_after_consumption(bench):
    coordinator = bench.make_coordinator()
    _open_session(bench, coordinator)
    baseline = _outstanding(bench)

    _close_session(bench, coordinator)

    assert _outstanding(bench) == baseline


def test_session_results_are_read_before_any_receipt_is_released(bench):
    """9. No receipt disappears before Monitor reads its result."""

    from PERSISTENCE.database import connect_database

    coordinator = bench.make_coordinator()
    session_id = _open_session(bench, coordinator)

    connection = connect_database(read_only=True)
    try:
        row = connection.execute(
            "SELECT id, profile_type, closed_at_utc FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    assert row["profile_type"] == "study"
    assert row["closed_at_utc"] is None

    _close_session(bench, coordinator, reason="STOPPED")

    connection = connect_database(read_only=True)
    try:
        row = connection.execute(
            "SELECT closed_at_utc, close_reason FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row["closed_at_utc"]
    assert row["close_reason"] == "STOPPED"


# ---------------------------------------------------------------------------
# 4. Emergency receipt
# ---------------------------------------------------------------------------

def test_emergency_receipt_is_forgotten_after_consumption(bench):
    from PERSISTENCE.database import connect_database

    coordinator = bench.make_coordinator()
    session_id = _open_session(bench, coordinator)
    baseline = _outstanding(bench)

    receipt = bench.storage.record_emergency(session_id=session_id)
    committed = coordinator._wait_for_commit(
        receipt, timeout_seconds=DURABLE, operation="emergency record"
    )
    assert committed.state.name == "COMMITTED"

    assert _outstanding(bench) == baseline

    connection = connect_database(read_only=True)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM emergency_events WHERE session_id=?",
            (session_id,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert count == 1, "the emergency fact must still be durable"


# ---------------------------------------------------------------------------
# 8. A FAILED receipt is consumed too, after its failure is read
# ---------------------------------------------------------------------------

def test_failed_receipt_is_consumed_after_its_failure_is_read(bench):
    coordinator = bench.make_coordinator()
    _open_session(bench, coordinator)

    _close_session(bench, coordinator)
    baseline = _outstanding(bench)

    # Closing an already-closed session fails inside the lane.
    doomed = bench.storage.close_monitor_session(
        session_id=coordinator.session_id, reason="STOPPED"
    )
    with pytest.raises(RuntimeError) as failure:
        coordinator._wait_for_commit(
            doomed, timeout_seconds=DURABLE, operation="session close"
        )

    # The failure detail must survive the consumption.
    assert "session close was not committed" in str(failure.value)
    assert _outstanding(bench) == baseline


def test_wait_for_commit_semantics_are_unchanged(bench):
    """Success still returns the terminal receipt with its real identity."""

    coordinator = bench.make_coordinator()
    receipt = bench.storage.open_monitor_session(profile_type="study")
    committed = coordinator._wait_for_commit(
        receipt, timeout_seconds=DURABLE, operation="session open"
    )
    assert committed.state.name == "COMMITTED"
    assert int(committed.result_id) > 0
    assert committed.session_id == committed.result_id


# ---------------------------------------------------------------------------
# 5 + 7. Trigger receipt: retained while pending, released with the clear
# ---------------------------------------------------------------------------

def test_trigger_receipt_survives_while_pending(bench):
    """5. A pending workflow keeps its receipt observable."""

    gate = threading.Event()
    lane = bench.storage._lane
    coordinator = bench.make_coordinator()
    _open_session(bench, coordinator)

    def blocking(connection):
        gate.wait(20.0)
        return None

    receipt = lane.submit("C12D2 pending trigger", blocking)
    coordinator._pending_trigger = PendingTriggerWorkflow(
        candidate_uid="c12d2",
        candidate=object(),
        receipt_id=receipt.receipt_id,
        submitted_monotonic_ns=time.monotonic_ns(),
    )
    try:
        # Reconciliation while RUNNING must change nothing and drop nothing.
        coordinator._reconcile_pending_trigger()
        assert coordinator._pending_trigger is not None
        assert lane.receipt(receipt.receipt_id) is not None
    finally:
        gate.set()
    assert lane.wait(receipt.receipt_id, timeout_seconds=DURABLE) is not None


def test_trigger_receipt_is_released_exactly_with_the_clear(bench):
    """7. Forgotten only as _pending_trigger is cleared -- never before."""

    lane = bench.storage._lane
    coordinator = bench.make_coordinator()
    _open_session(bench, coordinator)

    receipt = lane.submit("C12D2 trigger", lambda connection: None)
    settled = lane.wait(receipt.receipt_id, timeout_seconds=DURABLE)
    assert settled.state.name == "COMMITTED"

    coordinator._pending_trigger = PendingTriggerWorkflow(
        candidate_uid="c12d2",
        candidate=object(),
        receipt_id=receipt.receipt_id,
        submitted_monotonic_ns=time.monotonic_ns(),
    )

    # Terminal, but still owned: the receipt must remain observable.
    assert lane.receipt(receipt.receipt_id) is not None

    coordinator._clear_pending_trigger()

    assert coordinator._pending_trigger is None
    assert lane.receipt(receipt.receipt_id) is None
    # Clearing again is safe and releases nothing further.
    coordinator._clear_pending_trigger()


def test_settle_path_that_keeps_the_workflow_keeps_the_receipt(bench):
    """A shutdown settlement that cannot finish must not drop the receipt."""

    lane = bench.storage._lane
    coordinator = bench.make_coordinator()
    _open_session(bench, coordinator)

    # A committed trigger receipt must carry a real operational event id,
    # exactly as ``persist_trigger`` produces.
    receipt = lane.submit("C12D2 unsettled", lambda connection: 4242)
    settled = lane.wait(receipt.receipt_id, timeout_seconds=DURABLE)
    assert settled is not None and settled.result_id == 4242

    class RefusingTrigger:
        def confirm_durable_admission(self, **kwargs):
            return False

    coordinator._pending_trigger = PendingTriggerWorkflow(
        candidate_uid="c12d2",
        candidate=object(),
        receipt_id=receipt.receipt_id,
        submitted_monotonic_ns=time.monotonic_ns(),
    )
    import dataclasses

    coordinator.services = dataclasses.replace(
        coordinator.services, trigger=RefusingTrigger()
    )
    coordinator._settle_pending_trigger_for_shutdown(wait_seconds=0.0)

    # Admission was refused, the workflow was NOT cleared, so the receipt
    # must still be there for the retry that cleanup performs.
    assert coordinator._pending_trigger is not None
    assert lane.receipt(receipt.receipt_id) is not None
    assert "Committed pending trigger could not be admitted" in "".join(
        coordinator._cleanup_errors
    )


# ---------------------------------------------------------------------------
# 6 + 10. Real end-to-end trigger, and steady state under repetition
# ---------------------------------------------------------------------------

def test_repeated_sessions_do_not_grow_outstanding_receipts(bench):
    """10. Stress: outstanding returns to the steady baseline."""

    baseline = _outstanding(bench)
    for _ in range(25):
        coordinator = bench.make_coordinator()
        _open_session(bench, coordinator)
        _close_session(bench, coordinator)
    grew = _outstanding(bench) - baseline
    assert grew == 0, f"{grew} lifecycle receipts accumulated over 25 cycles"


@pytest.mark.slow
def test_real_trigger_journey_consumes_its_receipt():
    """6. The real Monitor loop: a trigger is admitted, then released.

    The engine is quietened before the assertions.  A blacklisted foreground
    keeps founding NEW candidates, and a freshly pending workflow legitimately
    retains its receipt -- so the claim is checked once every accepted trigger
    has settled, not while the engine is still minting them.
    """

    from _lab import Engine

    with Engine(
        surface=LECTURE,
        poll_seconds=0.2,
        fast_cosecant=True,
        blacklist_thresholds=FAST_THRESHOLDS,
    ) as engine:
        lane = engine.services.storage._lane
        baseline = lane.outstanding()

        engine.look_at(INSTAGRAM)
        engine.wait_until(
            lambda: int(
                getattr(engine.services.trigger.live_view(), "admitted_count", 0)
                or 0
            )
            > 0,
            timeout=120,
            what="a real Executive Blacklist trigger to be durably admitted",
        )

        # POSITIVE CONTROL: the trigger genuinely completed its normal path,
        # so a persist-trigger receipt really was created and consumed.
        admitted = int(
            getattr(engine.services.trigger.live_view(), "admitted_count", 0) or 0
        )
        assert admitted > 0

        # Stop founding new candidates, then let anything in flight settle.
        engine.look_at(LECTURE)
        engine.wait_until(
            lambda: engine.coordinator._pending_trigger is None,
            timeout=30,
            what="every accepted trigger workflow to settle",
        )
        engine.wait_until(
            lambda: lane.outstanding() == baseline,
            timeout=30,
            what="the consumed trigger receipts to be released",
        )
        assert lane.outstanding() == baseline, [
            (record.receipt.state.name, record.operation)
            for record in lane._records.values()
        ]
