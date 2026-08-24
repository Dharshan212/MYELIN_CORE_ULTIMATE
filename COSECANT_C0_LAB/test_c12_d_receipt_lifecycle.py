"""C12-D -- terminal receipts must not accumulate forever.

``SQLiteTransactionLane`` kept one ``_ReceiptRecord`` per submitted write in a
dictionary that was never pruned, so a long MYELIN process grew one in-memory
record per durable write.

The repair is a CONSUMPTION, not a cap:

    pending receipt          -> can never disappear
    terminal outcome         -> stays observable while an owner still reads it
    owner has finished       -> receipt is explicitly forgotten

Storage owns every ``_terminal()`` write end to end, so it consumes those
itself.  Receipts returned raw to a caller stay until that caller forgets them.
"""

from __future__ import annotations

import threading

import pytest

import _lab  # noqa: F401

from PERSISTENCE.storage import EngineStorage


DURABLE = 10.0


@pytest.fixture
def facade():
    storage = EngineStorage()
    try:
        yield storage
    finally:
        storage.shutdown()


@pytest.fixture
def session(facade):
    receipt = facade.open_monitor_session(profile_type="C12D")
    receipt = facade.wait(receipt.receipt_id, timeout_seconds=DURABLE)
    assert receipt.state.name == "COMMITTED"
    facade.forget_receipt(receipt.receipt_id)
    return int(receipt.result_id)


# ---------------------------------------------------------------------------
# The growth lesion
# ---------------------------------------------------------------------------

def test_storage_owned_writes_do_not_accumulate(facade, session):
    """500 durable writes must not leave 500 records behind."""

    baseline = facade._lane.outstanding()
    for index in range(500):
        assert facade.record_study_snapshot(
            session_id=session, action=f"c12d{index}", snapshot={"i": index}
        )
    assert facade._lane.outstanding() == baseline, (
        "storage-owned writes accumulated receipts: "
        f"{facade._lane.outstanding()} vs baseline {baseline}"
    )


def test_every_storage_owned_write_family_consumes(facade, session):
    baseline = facade._lane.outstanding()
    assert facade.append_sine_facts(
        [{"kind": "c12d", "session_id": session, "payload": {}}]
    ) is not None
    assert facade.record_study_snapshot(
        session_id=session, action="c12d", snapshot={}
    )
    assert facade._lane.outstanding() == baseline


def test_concurrent_writers_do_not_accumulate(facade, session):
    baseline = facade._lane.outstanding()
    errors: list[BaseException] = []

    def worker(tag: int) -> None:
        try:
            for index in range(40):
                facade.record_study_snapshot(
                    session_id=session,
                    action=f"c12d-{tag}-{index}",
                    snapshot={"i": index},
                )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(tag,)) for tag in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60.0)
    assert errors == [], errors
    assert facade._lane.outstanding() == baseline


# ---------------------------------------------------------------------------
# The invariants the cleanup must not break
# ---------------------------------------------------------------------------

def test_pending_receipt_can_never_be_forgotten(facade):
    """An outstanding transaction must stay observable."""

    gate = threading.Event()
    lane = facade._lane

    def blocking(connection):
        gate.wait(20.0)
        return None

    receipt = lane.submit("C12D blocking", blocking)
    try:
        assert receipt.state.name == "RUNNING"
        assert lane.forget(receipt.receipt_id) is False
        assert lane.receipt(receipt.receipt_id) is not None
        assert facade.forget_receipt(receipt.receipt_id) is False
    finally:
        gate.set()
    settled = lane.wait(receipt.receipt_id, timeout_seconds=DURABLE)
    assert settled is not None and settled.state.name == "COMMITTED"


def test_terminal_receipt_stays_observable_until_forgotten(facade):
    """Caller-owned receipts survive until their owner consumes them."""

    receipt = facade.open_monitor_session(profile_type="C12D owner")
    settled = facade.wait(receipt.receipt_id, timeout_seconds=DURABLE)
    assert settled.state.name == "COMMITTED"

    # Still there -- the owner has not said it is finished.
    assert facade.receipt(receipt.receipt_id) is not None
    assert facade.receipt(receipt.receipt_id) is not None

    assert facade.forget_receipt(receipt.receipt_id) is True
    assert facade.receipt(receipt.receipt_id) is None
    # Forgetting twice is not an error, just nothing to release.
    assert facade.forget_receipt(receipt.receipt_id) is False


def test_failed_receipt_is_consumable_and_reports_its_error(facade):
    lane = facade._lane

    def explode(connection):
        raise RuntimeError("C12D deliberate failure")

    receipt = lane.submit("C12D failing", explode)
    settled = lane.wait(receipt.receipt_id, timeout_seconds=DURABLE)
    assert settled.state.name == "FAILED"
    assert "C12D deliberate failure" in settled.error
    assert lane.forget(receipt.receipt_id) is True
    assert lane.receipt(receipt.receipt_id) is None


def test_unknown_receipt_forget_is_false(facade):
    assert facade.forget_receipt("no-such-receipt") is False
    assert facade.forget_receipt("") is False


def test_durable_state_is_unaffected_by_consumption(facade, session):
    """Forgetting a receipt must never touch the database."""

    from PERSISTENCE.database import connect_database

    for index in range(20):
        facade.record_study_snapshot(
            session_id=session, action=f"c12d-durable-{index}", snapshot={}
        )
    connection = connect_database(read_only=True)
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM study_events WHERE session_id=?", (session,)
        ).fetchone()[0]
    finally:
        connection.close()
    assert count >= 20
