"""C12-A -- a CLOSED EngineStorage facade must not be a durable writer.

Reproduction first.  ``EngineStorage.shutdown()`` sets ``self._closed`` and
releases this facade's ownership of the shared lane, but every write method
calls ``self._lane.submit(...)`` directly and never consults ``_closed``.

When a SECOND facade still owns the shared lane, the lane is very much alive,
so the "dead" facade's submit lands in the real database.  That is a released
owner mutating durable state after its lifetime ended.
"""

from __future__ import annotations

import pytest

import _lab  # noqa: F401  -- isolates APPDATA and puts ULTIMATE on sys.path

from PERSISTENCE.storage import EngineStorage, _SharedStorageLane
from PERSISTENCE.database import connect_database


DURABLE = 10.0


def _session_row(session_id: int):
    connection = connect_database(read_only=True)
    try:
        return connection.execute(
            "SELECT id, profile_type FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
    finally:
        connection.close()


@pytest.fixture
def two_facades():
    a = EngineStorage()
    b = EngineStorage()
    try:
        yield a, b
    finally:
        for facade in (a, b):
            try:
                facade.shutdown()
            except Exception:
                pass


def test_shared_lane_is_actually_shared(two_facades):
    a, b = two_facades
    assert a._lane is b._lane
    assert _SharedStorageLane.owners() >= 2


def test_closed_facade_cannot_write_while_lane_lives(two_facades):
    """The C12-A invariant: CLOSED FACADE != WRITER."""

    a, b = two_facades

    a.shutdown()

    # The lane is still alive because B owns it.
    assert _SharedStorageLane.owners() >= 1
    assert b._lane is not None

    with pytest.raises(RuntimeError):
        a.open_monitor_session(profile_type="C12A closed facade")


def test_closed_facade_batch_append_refuses(two_facades):
    """Batch appends are writes too -- they must refuse, not return False."""

    a, b = two_facades

    receipt = b.open_monitor_session(profile_type="C12A positive control")
    receipt = b.wait(receipt.receipt_id, timeout_seconds=DURABLE)
    session_id = int(receipt.result_id)

    a.shutdown()

    with pytest.raises(RuntimeError):
        a.record_study_snapshot(
            session_id=session_id, action="C12A", snapshot={"x": 1}
        )
    with pytest.raises(RuntimeError):
        a.append_sine_facts([{"fact_id": "c12a", "session_id": session_id}])


def test_surviving_facade_still_writes_after_sibling_shutdown(two_facades):
    """Positive control -- the guard must not poison the healthy owner."""

    a, b = two_facades
    a.shutdown()

    receipt = b.open_monitor_session(profile_type="C12A survivor")
    receipt = b.wait(receipt.receipt_id, timeout_seconds=DURABLE)
    assert receipt is not None and receipt.state.name == "COMMITTED"
    session_id = int(receipt.result_id)

    row = _session_row(session_id)
    assert row is not None
    assert row["profile_type"] == "C12A survivor"

    closed = b.close_monitor_session(session_id=session_id, reason="C12A")
    closed = b.wait(closed.receipt_id, timeout_seconds=DURABLE)
    assert closed.state.name == "COMMITTED"


def test_closed_facade_reads_still_work(two_facades):
    """Read-only APIs are not lane writes; document the chosen contract."""

    a, b = two_facades
    a.shutdown()

    # Reads open their own read-only connection; they never touch the lane.
    state = a.load_profile_learning(profile_key="study")
    assert state is not None
    assert a.list_notes() is not None
    assert a.list_planner_blocks(plan_id="c12a") is not None


def test_shutdown_remains_idempotent(two_facades):
    a, b = two_facades
    a.shutdown()
    a.shutdown()
    assert b._lane is not None
