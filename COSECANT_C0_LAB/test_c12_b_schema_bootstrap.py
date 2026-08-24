"""C12-B -- schema installation is a BOOTSTRAP act, not a runtime read.

MYELIN serialises every durable write through one ordered SQLite lane.
``ensure_production_schema()`` is not a read: it opens its OWN writable
connection and runs ``BEGIN IMMEDIATE``.  Calling it from a runtime reader
means a dashboard refresh can open a second writable transaction against the
same database while the shared writer lane is live.

These tests instrument ``PERSISTENCE.schema.connect_database`` so a writable
schema connection is distinguishable from lane traffic.
"""

from __future__ import annotations

import threading

import pytest

import _lab  # noqa: F401

import PERSISTENCE.schema as schema_module
import PERSISTENCE.storage as storage
from PERSISTENCE.storage import EngineStorage, _SharedStorageLane


@pytest.fixture
def schema_writes(monkeypatch):
    """Record every writable connection opened by the schema authority."""

    calls: list[str] = []
    real = schema_module.connect_database

    def spy(*, read_only: bool = False):
        calls.append("read_only" if read_only else "WRITABLE")
        return real(read_only=read_only)

    monkeypatch.setattr(schema_module, "connect_database", spy)
    return calls


@pytest.fixture
def live_lane():
    """A live shared writer lane, i.e. real MYELIN runtime conditions."""

    facade = EngineStorage()
    try:
        assert _SharedStorageLane.owners() >= 1
        yield facade
    finally:
        facade.shutdown()


# ---------------------------------------------------------------------------
# The law
# ---------------------------------------------------------------------------

def test_runtime_reads_never_open_a_writable_schema_connection(
    live_lane, schema_writes
):
    """A dashboard refresh must NOT secretly execute BEGIN IMMEDIATE."""

    storage.read_cosine_events()
    storage.read_mirl_events()
    storage.read_control_station_analytics()

    assert schema_writes == [], (
        "runtime reads opened writable schema connections while the shared "
        f"writer lane was live: {schema_writes}"
    )


def test_second_facade_does_not_reinstall_schema(live_lane, schema_writes):
    """Constructing another owner of a LIVE lane is not a bootstrap."""

    second = EngineStorage()
    try:
        assert schema_writes == [], (
            "EngineStorage construction opened a writable schema connection "
            f"while a shared writer lane already existed: {schema_writes}"
        )
    finally:
        second.shutdown()


def test_emergency_followup_query_is_read_only(live_lane, schema_writes):
    """The startup gate's *query* half must not mutate schema at runtime."""

    storage.emergency_followup_required()
    assert schema_writes == []


# ---------------------------------------------------------------------------
# Positive controls -- bootstrap must still work
# ---------------------------------------------------------------------------

def test_bootstrap_still_installs_schema(schema_writes):
    """Explicit bootstrap remains a writable, verifying transaction.

    Deliberately calls the raw installer, so it must only run when no shared
    writer lane is live -- running it against one is precisely the two-writer
    condition C12-B exists to forbid, and earlier LAB modules leave facades
    open for the life of the process.
    """

    if _SharedStorageLane.owners():
        pytest.skip("a shared writer lane is live; bootstrap is not legal here")
    schema_module.ensure_production_schema()
    assert "WRITABLE" in schema_writes


def test_bootstrap_is_latched(schema_writes):
    """A second bootstrap does no schema work at all."""

    storage.bootstrap_production_schema()
    storage.bootstrap_production_schema()
    assert schema_writes == []


def test_bootstrap_refuses_to_run_under_a_live_writer_lane(monkeypatch, live_lane):
    """The ordering law is an invariant, not a convention.

    If the latch were somehow unset while a shared writer lane was live,
    bootstrap must fail closed rather than open a second writable connection.
    """

    monkeypatch.setattr(storage, "_SCHEMA_BOOTSTRAPPED", False)
    with pytest.raises(RuntimeError):
        storage.bootstrap_production_schema()


def test_first_facade_can_bootstrap_standalone():
    """Standalone construction must still yield a usable database.

    A LAB/tool process that builds EngineStorage without going through the
    launcher must not hit 'no such table'.
    """

    facade = EngineStorage()
    try:
        receipt = facade.open_monitor_session(profile_type="C12B standalone")
        receipt = facade.wait(receipt.receipt_id, timeout_seconds=10.0)
        assert receipt is not None and receipt.state.name == "COMMITTED"
    finally:
        facade.shutdown()


def test_reads_work_without_any_facade():
    """Reader entry points must not require a live writer of their own."""

    assert storage.read_cosine_events() is not None
    assert storage.read_mirl_events() is not None
    assert storage.read_control_station_analytics() is not None


def test_concurrent_reads_during_live_writes(live_lane):
    """Hostile: hammer reads while the lane writes.  No second writer."""

    errors: list[BaseException] = []
    stop = threading.Event()

    def reader():
        try:
            while not stop.is_set():
                storage.read_control_station_analytics()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    for thread in threads:
        thread.start()
    try:
        for index in range(25):
            receipt = live_lane.open_monitor_session(
                profile_type=f"C12B load {index}"
            )
            receipt = live_lane.wait(receipt.receipt_id, timeout_seconds=10.0)
            assert receipt.state.name == "COMMITTED", receipt.error
    finally:
        stop.set()
        for thread in threads:
            thread.join(10.0)
    assert errors == [], errors


# ---------------------------------------------------------------------------
# B5 -- the emergency follow-up path is startup-only.  Prove the ordering
# instead of moving the function.
# ---------------------------------------------------------------------------

def test_emergency_followup_gate_runs_before_any_lane_exists():
    """StartupSequence must run the gate BEFORE it builds the window.

    ``record_emergency_followup_reason`` opens a direct writable connection.
    That is safe only because it happens in the startup gate, before
    ``ControlStationWindow`` (and therefore any ``EngineStorage``) exists.
    """

    import ast
    import pathlib

    source = (_lab.ULTIMATE / "CONTROL_STATION" / "launcher.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    sequence = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "StartupSequence"
    )
    methods = {
        node.name: node
        for node in sequence.body
        if isinstance(node, ast.FunctionDef)
    }

    # start() schedules the gate, and nothing else builds a window first.
    start_src = ast.unparse(methods["start"])
    assert "_run_startup_gate" in start_src
    assert "ControlStationWindow" not in start_src

    gate_src = ast.unparse(methods["_run_startup_gate"])
    assert "run_startup_gate" in gate_src
    assert "ControlStationWindow" not in gate_src

    # The window -- and therefore EngineStorage -- is built only afterwards.
    assert "ControlStationWindow(" in ast.unparse(methods["_build_window"])

    completed_src = ast.unparse(methods["_startup_gate_completed"])
    assert "_build_window" in completed_src


def test_launcher_bootstraps_before_constructing_runtime():
    """main() must bootstrap schema before any runtime authority exists."""

    import ast

    source = (_lab.ULTIMATE / "CONTROL_STATION" / "launcher.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    main = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    body = ast.unparse(main)
    bootstrap_at = body.index("bootstrap_production_schema()")
    startup_at = body.index("StartupSequence(")
    assert bootstrap_at < startup_at

    # And the launcher no longer reaches past storage to the raw installer.
    assert "ensure_production_schema" not in source
