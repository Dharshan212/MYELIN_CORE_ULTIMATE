"""Phase-1 contract tests for the isolated Normal Break mini organ."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest


ULTIMATE = Path(
    r"C:\Users\Dharshan\Downloads\MYELIN_GENALOGY\MYELIN2.0_ULTIMATE"
)
if str(ULTIMATE) not in sys.path:
    sys.path.insert(0, str(ULTIMATE))

from SINE.normal_break import (  # noqa: E402
    NANOSECONDS_PER_SECOND,
    NormalBreakAuthority,
    NormalBreakFactKind,
    NormalBreakState,
    NormalBreakTerminationReason,
)


class ManualClock:
    def __init__(self, value: int = 1_000_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


class Ids:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"break-{self.value}"


def authority(*, now: int = 1_000_000_000) -> tuple[NormalBreakAuthority, ManualClock]:
    clock = ManualClock(now)
    runtime = NormalBreakAuthority(
        monotonic_ns=clock,
        wall_clock_utc=lambda: datetime(2026, 8, 26, tzinfo=timezone.utc),
        break_id_factory=Ids(),
    )
    return runtime, clock


def request(runtime: NormalBreakAuthority, *, now: int | None = None):
    return runtime.request_duration(
        session_id=41,
        episode_uid="episode-1",
        candidate_uid="candidate-1",
        source_sine_popup_request_id="popup-1",
        requested_monotonic_ns=now,
    )


def start(
    runtime: NormalBreakAuthority,
    *,
    minutes: object = 5,
    now: int | None = None,
):
    pending = runtime.snapshot()
    return runtime.start_break(
        break_id=pending.break_id,
        generation=pending.generation,
        episode_uid=pending.episode_uid,
        candidate_uid=pending.candidate_uid,
        source_sine_popup_request_id=pending.source_sine_popup_request_id,
        selected_minutes=minutes,
        started_monotonic_ns=now,
    )


def stop(runtime: NormalBreakAuthority, *, now: int):
    active = runtime.snapshot()
    return runtime.stop_break(
        break_id=active.break_id,
        generation=active.generation,
        episode_uid=active.episode_uid,
        candidate_uid=active.candidate_uid,
        occurred_monotonic_ns=now,
    )


def test_p1_01_to_03_starts_idle_and_request_has_exact_identity_without_default():
    runtime, _ = authority()
    initial = runtime.snapshot()
    assert initial.state is NormalBreakState.IDLE
    assert initial.selected_minutes is None
    assert not initial.active

    result = request(runtime, now=2_000_000_000)
    assert result.accepted
    snapshot = result.snapshot
    assert snapshot.state is NormalBreakState.AWAITING_DURATION
    assert snapshot.session_id == 41
    assert snapshot.episode_uid == "episode-1"
    assert snapshot.candidate_uid == "candidate-1"
    assert snapshot.source_sine_popup_request_id == "popup-1"
    assert snapshot.break_id == "break-1"
    assert snapshot.generation == 1
    assert snapshot.selected_minutes is None
    assert result.facts[0].kind is NormalBreakFactKind.DURATION_REQUESTED


@pytest.mark.parametrize("minutes", [5, 6, 30])
def test_p1_04_valid_whole_minute_bounds_and_exact_deadline(minutes: int):
    runtime, _ = authority()
    request(runtime, now=10_000)
    result = start(runtime, minutes=minutes, now=20_000)
    assert result.accepted
    snapshot = result.snapshot
    assert snapshot.state is NormalBreakState.ACTIVE
    assert snapshot.selected_minutes == minutes
    assert snapshot.started_monotonic_ns == 20_000
    assert snapshot.deadline_monotonic_ns == (
        20_000 + minutes * 60 * NANOSECONDS_PER_SECOND
    )
    fact = result.facts[0]
    assert fact.kind is NormalBreakFactKind.STARTED
    assert fact.break_id == snapshot.break_id
    assert fact.generation == snapshot.generation


@pytest.mark.parametrize(
    "minutes",
    [0, 1, 4, 31, 999_999, -7, 7.5, 5.0, "hello", "", None, True],
)
def test_p1_05_to_09_invalid_duration_is_rejected_without_start(minutes: object):
    runtime, _ = authority()
    request(runtime, now=10_000)
    result = start(runtime, minutes=minutes, now=20_000)
    assert not result.accepted
    assert result.facts == ()
    assert result.snapshot.state is NormalBreakState.AWAITING_DURATION
    assert result.snapshot.selected_minutes is None
    assert not runtime.active


def test_p1_10_cancel_means_break_never_started():
    runtime, _ = authority()
    pending = request(runtime, now=100).snapshot
    result = runtime.cancel_duration(
        break_id=pending.break_id,
        generation=pending.generation,
        episode_uid=pending.episode_uid,
        candidate_uid=pending.candidate_uid,
        source_sine_popup_request_id=pending.source_sine_popup_request_id,
        occurred_monotonic_ns=101,
    )
    assert result.accepted
    assert result.snapshot.state is NormalBreakState.IDLE
    assert result.facts[0].kind is NormalBreakFactKind.CANCELLED
    assert not any(
        fact.kind is NormalBreakFactKind.STARTED for fact in runtime.drain_facts()
    )


def test_cancel_rejects_stale_generation_and_preserves_current_request():
    runtime, _ = authority()
    pending = request(runtime, now=100).snapshot
    result = runtime.cancel_duration(
        break_id=pending.break_id,
        generation=pending.generation + 1,
        episode_uid=pending.episode_uid,
        candidate_uid=pending.candidate_uid,
        source_sine_popup_request_id=pending.source_sine_popup_request_id,
        occurred_monotonic_ns=101,
    )
    assert not result.accepted
    assert result.snapshot == pending


def test_numeric_identity_impostors_cannot_start_numeric_looking_branch():
    runtime = NormalBreakAuthority(
        break_id_factory=lambda: "123",
        monotonic_ns=lambda: 100,
    )
    pending = runtime.request_duration(
        episode_uid="456",
        candidate_uid="789",
        source_sine_popup_request_id="101",
        requested_monotonic_ns=100,
    ).snapshot

    malformed = runtime.start_break(
        break_id=123,  # type: ignore[arg-type]
        generation=pending.generation,
        episode_uid=456,  # type: ignore[arg-type]
        candidate_uid=789,  # type: ignore[arg-type]
        source_sine_popup_request_id=101,  # type: ignore[arg-type]
        selected_minutes=5,
        started_monotonic_ns=200,
    )
    assert not malformed.accepted
    assert malformed.facts == ()
    assert malformed.snapshot == pending
    assert malformed.snapshot.state is NormalBreakState.AWAITING_DURATION


def test_numeric_identity_impostors_cannot_cancel_numeric_looking_branch():
    runtime = NormalBreakAuthority(
        break_id_factory=lambda: "123",
        monotonic_ns=lambda: 100,
    )
    pending = runtime.request_duration(
        episode_uid="456",
        candidate_uid="789",
        source_sine_popup_request_id="101",
        requested_monotonic_ns=100,
    ).snapshot

    malformed = runtime.cancel_duration(
        break_id=123,  # type: ignore[arg-type]
        generation=pending.generation,
        episode_uid=456,  # type: ignore[arg-type]
        candidate_uid=789,  # type: ignore[arg-type]
        source_sine_popup_request_id=101,  # type: ignore[arg-type]
        occurred_monotonic_ns=200,
    )
    assert not malformed.accepted
    assert malformed.facts == ()
    assert malformed.snapshot == pending
    assert malformed.snapshot.state is NormalBreakState.AWAITING_DURATION


def test_p1_11_break_identity_is_unique_and_generation_advances():
    runtime, _ = authority()
    first = request(runtime, now=100).snapshot
    cancelled = runtime.cancel_duration(
        break_id=first.break_id,
        generation=first.generation,
        episode_uid=first.episode_uid,
        candidate_uid=first.candidate_uid,
        source_sine_popup_request_id=first.source_sine_popup_request_id,
        occurred_monotonic_ns=101,
    )
    assert cancelled.accepted
    second = request(runtime, now=200).snapshot
    assert second.break_id != first.break_id
    assert second.generation == first.generation + 1


def test_p1_13_14_advance_before_and_at_deadline_completes_once():
    runtime, _ = authority()
    request(runtime, now=100)
    active = start(runtime, minutes=5, now=200).snapshot
    deadline = active.deadline_monotonic_ns
    assert deadline is not None

    before = runtime.advance(now_monotonic_ns=deadline - 1)
    assert before.accepted
    assert before.facts == ()
    assert before.snapshot.state is NormalBreakState.ACTIVE

    at = runtime.advance(now_monotonic_ns=deadline)
    assert at.accepted
    assert at.facts[0].kind is NormalBreakFactKind.COMPLETED
    assert at.facts[0].occurred_monotonic_ns == deadline
    assert at.snapshot.state is NormalBreakState.IDLE

    duplicate = runtime.advance(now_monotonic_ns=deadline + 1)
    assert not duplicate.accepted
    assert duplicate.facts == ()


def test_advance_after_deadline_records_the_authoritative_deadline_not_poll_delay():
    runtime, _ = authority()
    request(runtime, now=100)
    active = start(runtime, minutes=5, now=200).snapshot
    deadline = active.deadline_monotonic_ns
    assert deadline is not None
    result = runtime.advance(now_monotonic_ns=deadline + 15 * NANOSECONDS_PER_SECOND)
    assert result.facts[0].occurred_monotonic_ns == deadline


def test_concurrent_deadline_advances_emit_exactly_one_completion():
    runtime, _ = authority()
    request(runtime, now=100)
    active = start(runtime, minutes=5, now=200).snapshot
    deadline = active.deadline_monotonic_ns
    assert deadline is not None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(
            pool.map(
                lambda _: runtime.advance(now_monotonic_ns=deadline),
                range(32),
            )
        )

    completions = [
        fact
        for result in results
        for fact in result.facts
        if fact.kind is NormalBreakFactKind.COMPLETED
    ]
    assert len(completions) == 1
    assert runtime.snapshot().state is NormalBreakState.IDLE


def test_p1_15_16_stop_ends_active_break_and_stale_stop_is_noop():
    runtime, _ = authority()
    request(runtime, now=100)
    active = start(runtime, now=200).snapshot
    result = stop(runtime, now=300)
    assert result.accepted
    assert [fact.kind for fact in result.facts] == [
        NormalBreakFactKind.STOP_REQUESTED,
        NormalBreakFactKind.STOPPED,
    ]
    assert result.snapshot.state is NormalBreakState.IDLE

    stale = runtime.stop_break(
        break_id=active.break_id,
        generation=active.generation,
        episode_uid=active.episode_uid,
        candidate_uid=active.candidate_uid,
        occurred_monotonic_ns=301,
    )
    assert not stale.accepted
    assert stale.facts == ()


def test_p1_17_old_generation_cannot_mutate_newer_break():
    runtime, _ = authority()
    old = request(runtime, now=100).snapshot
    runtime.cancel_duration(
        break_id=old.break_id,
        generation=old.generation,
        episode_uid=old.episode_uid,
        candidate_uid=old.candidate_uid,
        source_sine_popup_request_id=old.source_sine_popup_request_id,
        occurred_monotonic_ns=101,
    )
    current = request(runtime, now=200).snapshot

    stale = runtime.start_break(
        break_id=old.break_id,
        generation=old.generation,
        episode_uid=old.episode_uid,
        candidate_uid=old.candidate_uid,
        source_sine_popup_request_id=old.source_sine_popup_request_id,
        selected_minutes=5,
        started_monotonic_ns=201,
    )
    assert not stale.accepted
    assert stale.snapshot == current


def test_p1_18_timer_has_no_global_pause_input_and_deadline_keeps_aging():
    runtime, _ = authority()
    request(runtime, now=100)
    active = start(runtime, minutes=7, now=200).snapshot
    assert "pause" not in runtime.advance.__annotations__
    deadline = active.deadline_monotonic_ns
    assert deadline is not None
    assert runtime.advance(now_monotonic_ns=deadline).facts[0].kind is (
        NormalBreakFactKind.COMPLETED
    )


@pytest.mark.parametrize("reason", list(NormalBreakTerminationReason))
def test_p1_19_active_break_termination_invalidates_authority(reason):
    runtime, _ = authority()
    request(runtime, now=100)
    start(runtime, now=200)
    result = runtime.terminate(reason=reason, occurred_monotonic_ns=300)
    assert result.accepted
    assert result.facts[0].kind is NormalBreakFactKind.TERMINATED
    assert result.facts[0].reason == reason.value
    assert result.snapshot.state is NormalBreakState.IDLE
    assert result.snapshot.break_id == ""
    assert not runtime.active


def test_pending_request_can_be_terminated_without_creating_break_start():
    runtime, _ = authority()
    request(runtime, now=100)
    result = runtime.terminate(
        reason=NormalBreakTerminationReason.SHUTDOWN,
        occurred_monotonic_ns=101,
    )
    assert result.accepted
    assert result.facts[0].started_monotonic_ns is None
    assert result.snapshot.state is NormalBreakState.IDLE


def test_p1_20_fresh_runtime_never_restores_previous_break():
    runtime, _ = authority()
    request(runtime, now=100)
    start(runtime, now=200)
    fresh, _ = authority(now=300)
    assert fresh.snapshot().state is NormalBreakState.IDLE
    assert fresh.snapshot().generation == 0
    assert not hasattr(fresh, "restore")


def test_p1_21_to_24_module_has_no_forbidden_domain_or_qt_imports():
    source = (ULTIMATE / "SINE" / "normal_break.py").read_text(encoding="utf-8")
    for forbidden in (
        "PyQt",
        "COSECANT",
        "ResourceIntent",
        "MirlAuthority",
        "TriggerAuthority",
        "BlacklistAuthority",
        "SineStage",
    ):
        assert f"import {forbidden}" not in source
        assert f"from {forbidden}" not in source


def test_exact_nonempty_identity_is_required_for_duration_request():
    runtime, _ = authority()
    with pytest.raises(ValueError):
        runtime.request_duration(
            episode_uid="",
            candidate_uid="candidate-1",
            source_sine_popup_request_id="popup-1",
        )


def test_transition_timestamp_cannot_predate_current_state():
    runtime, _ = authority()
    request(runtime, now=200)
    with pytest.raises(ValueError):
        start(runtime, minutes=5, now=199)
    assert runtime.snapshot().state is NormalBreakState.AWAITING_DURATION


def test_drain_facts_returns_each_fact_once_in_sequence_order():
    runtime, _ = authority()
    request(runtime, now=100)
    start(runtime, now=200)
    facts = runtime.drain_facts()
    assert [fact.kind for fact in facts] == [
        NormalBreakFactKind.DURATION_REQUESTED,
        NormalBreakFactKind.STARTED,
    ]
    assert [fact.sequence for fact in facts] == [1, 2]
    assert runtime.drain_facts() == ()


def test_start_rollback_is_exact_identity_bound_and_returns_idle():
    runtime, _ = authority()
    request(runtime, now=100)
    active = start(runtime, now=200).snapshot
    result = runtime.rollback_start(
        break_id=active.break_id,
        generation=active.generation,
        episode_uid=active.episode_uid,
        candidate_uid=active.candidate_uid,
        reason="sine_hold_refused",
        occurred_monotonic_ns=201,
    )
    assert result.accepted
    assert result.facts[0].kind is NormalBreakFactKind.START_ROLLED_BACK
    assert result.facts[0].reason == "sine_hold_refused"
    assert result.snapshot.state is NormalBreakState.IDLE


def test_p1_25_real_storage_persists_identity_bound_start_and_terminal_facts(tmp_path):
    """Use a fresh process so production's once-per-process bootstrap is exact."""

    script = textwrap.dedent(
        f"""
        import sqlite3
        import sys
        from pathlib import Path

        sys.path.insert(0, {str(ULTIMATE)!r})
        from PERSISTENCE.database import database_path
        from PERSISTENCE.storage import EngineStorage
        from SINE.normal_break import NormalBreakAuthority

        ids = iter(("persisted-break-1", "persisted-break-2", "persisted-break-3"))
        runtime = NormalBreakAuthority(break_id_factory=lambda: next(ids))
        pending = runtime.request_duration(
            episode_uid="episode-persisted",
            candidate_uid="candidate-persisted",
            source_sine_popup_request_id="popup-persisted",
            requested_monotonic_ns=100,
        ).snapshot
        runtime.start_break(
            break_id=pending.break_id,
            generation=pending.generation,
            episode_uid=pending.episode_uid,
            candidate_uid=pending.candidate_uid,
            source_sine_popup_request_id=pending.source_sine_popup_request_id,
            selected_minutes=5,
            started_monotonic_ns=200,
        )
        active = runtime.snapshot()
        runtime.stop_break(
            break_id=active.break_id,
            generation=active.generation,
            episode_uid=active.episode_uid,
            candidate_uid=active.candidate_uid,
            occurred_monotonic_ns=300,
        )

        terminated = NormalBreakAuthority(break_id_factory=lambda: next(ids))
        terminated_pending = terminated.request_duration(
            episode_uid="episode-terminated",
            candidate_uid="candidate-terminated",
            source_sine_popup_request_id="popup-terminated",
            requested_monotonic_ns=400,
        ).snapshot
        terminated.start_break(
            break_id=terminated_pending.break_id,
            generation=terminated_pending.generation,
            episode_uid=terminated_pending.episode_uid,
            candidate_uid=terminated_pending.candidate_uid,
            source_sine_popup_request_id=terminated_pending.source_sine_popup_request_id,
            selected_minutes=6,
            started_monotonic_ns=500,
        )
        from SINE.normal_break import NormalBreakTerminationReason
        terminated.terminate(
            reason=NormalBreakTerminationReason.SHUTDOWN,
            occurred_monotonic_ns=600,
        )

        rolled_back = NormalBreakAuthority(break_id_factory=lambda: next(ids))
        rollback_pending = rolled_back.request_duration(
            episode_uid="episode-rollback",
            candidate_uid="candidate-rollback",
            source_sine_popup_request_id="popup-rollback",
            requested_monotonic_ns=700,
        ).snapshot
        rollback_active = rolled_back.start_break(
            break_id=rollback_pending.break_id,
            generation=rollback_pending.generation,
            episode_uid=rollback_pending.episode_uid,
            candidate_uid=rollback_pending.candidate_uid,
            source_sine_popup_request_id=rollback_pending.source_sine_popup_request_id,
            selected_minutes=7,
            started_monotonic_ns=800,
        ).snapshot
        rolled_back.rollback_start(
            break_id=rollback_active.break_id,
            generation=rollback_active.generation,
            episode_uid=rollback_active.episode_uid,
            candidate_uid=rollback_active.candidate_uid,
            reason="sine_hold_refused",
            occurred_monotonic_ns=900,
        )

        storage = EngineStorage()
        facts = (
            runtime.drain_facts()
            + terminated.drain_facts()
            + rolled_back.drain_facts()
        )
        assert storage.append_normal_break_facts(facts)
        storage.shutdown()

        connection = sqlite3.connect(database_path())
        rows = connection.execute(
            "SELECT break_id, generation, episode_uid, candidate_uid, kind, "
            "occurred_monotonic_ns, schema_version, payload_json "
            "FROM normal_break_events ORDER BY rowid"
        ).fetchall()
        version = connection.execute(
            "SELECT value FROM myelin_meta WHERE key='schema_version'"
        ).fetchone()[0]
        connection.close()

        assert [row[4] for row in rows] == [
            "NORMAL_BREAK_DURATION_REQUESTED",
            "NORMAL_BREAK_STARTED",
            "NORMAL_BREAK_STOP_REQUESTED",
            "NORMAL_BREAK_STOPPED",
            "NORMAL_BREAK_DURATION_REQUESTED",
            "NORMAL_BREAK_STARTED",
            "NORMAL_BREAK_TERMINATED",
            "NORMAL_BREAK_DURATION_REQUESTED",
            "NORMAL_BREAK_STARTED",
            "NORMAL_BREAK_START_ROLLED_BACK",
        ]
        assert [row[0] for row in rows] == [
            "persisted-break-1",
            "persisted-break-1",
            "persisted-break-1",
            "persisted-break-1",
            "persisted-break-2",
            "persisted-break-2",
            "persisted-break-2",
            "persisted-break-3",
            "persisted-break-3",
            "persisted-break-3",
        ]
        assert all(row[1] == 1 for row in rows)
        assert all(row[2] for row in rows)
        assert all(row[3] for row in rows)
        assert rows[1][5] == 200
        assert rows[3][5] == 300
        assert rows[6][5] == 600
        assert rows[9][5] == 900
        assert all(row[6] == "myelin-normal-break-v1" for row in rows)
        assert all(f'"break_id":"{{row[0]}}"' in row[7] for row in rows)
        assert version == "3"
        print("NORMAL_BREAK_PERSISTENCE_OK")
        """
    )
    environment = os.environ.copy()
    environment["APPDATA"] = str(tmp_path)
    environment["XDG_DATA_HOME"] = str(tmp_path)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-B", "-c", script],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "NORMAL_BREAK_PERSISTENCE_OK" in completed.stdout
