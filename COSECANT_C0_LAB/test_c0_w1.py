"""C0 regression guard for W-1 — timestamp authority collision.

EXPECTED AT C0: FAIL.
EXPECTED AFTER C1: PASS, and must stay passing forever.

cosecant.py uses ONE field, ``_last_monotonic_ns``, for two unrelated jobs:

    1. internal clock progression   (_read_monotonic, called by advance())
    2. incoming evidence ordering   (observe_return)

monitor.py legitimately calls advance() -- which reads the clock NOW -- after
the foreground observation was captured but before it is delivered. The
observation therefore always looks older than the field and is rejected.

These tests deliberately do NOT reorder the monitor. Per the roadmap, the two
timestamp domains must each be independently valid.
"""

from __future__ import annotations

import pytest

import _lab  # noqa: F401  (sets sys.path and isolates storage)

from COSECANT_STUDY_MODE.cosecant import (
    CosecantPolicy,
    CosecantRuntime,
    CosecantState,
    StudyPresence,
    StudyReturnObservation,
)
from COSECANT_STUDY_MODE.study import (
    StudyCompletionReason,
    StudySnapshot,
    StudyState,
)

NS = 10**9


class _Clock:
    def __init__(self, start_ns: int) -> None:
        self.t = start_ns

    def __call__(self) -> int:
        return self.t


class _AcceptingIntent:
    def publish_study_context(self, context) -> bool:
        return True

    def retire_study_context(self, expected_context_token: str = "") -> bool:
        return True


def _paused_study(now_ns: int) -> StudySnapshot:
    return StudySnapshot(
        block_id="BLOCK-W1",
        generation=1,
        state=StudyState.PAUSED,
        subject="Neuroscience",
        task="basal ganglia",
        keywords=("basal", "ganglia"),
        important_keywords=("dopamine",),
        active_epoch_monotonic_ns=now_ns,
        planned_seconds=3600,
        elapsed_seconds=0.0,
        remaining_seconds=3600,
        progress_percent=0.0,
        started_wall_time_utc="",
        paused_wall_time_utc="",
        completed_wall_time_utc="",
        ends_at_wall_time_utc="",
        completion_reason=StudyCompletionReason.NONE,
        last_action="paused for break",
        published_monotonic_ns=now_ns,
    )


@pytest.fixture()
def locked_break():
    """A COSECANT runtime parked in FINAL_LOCK with a controllable clock."""

    from COSECANT_STUDY_MODE.cosecant import CosecantReturnTarget

    clock = _Clock(1_000 * NS)
    runtime = CosecantRuntime(
        context_authority=_AcceptingIntent(),
        policy=CosecantPolicy(),
        monotonic_ns=clock,
    )
    study = _paused_study(clock.t)
    # C5 made the intended return target mandatory; W-1 is about timestamp
    # domains, so any valid target serves.
    started = runtime.start_break(
        study=study,
        selected_break_seconds=600,
        intended_return_target=CosecantReturnTarget(
            study_context_token=study.context_token,
            platform_key="youtube",
            resource_token="W1-RESOURCE",
            observed_monotonic_ns=clock.t,
        ),
    )
    assert started.accepted, started.message

    # 600 break + 300 already-over + 60 final lock, plus a little.
    clock.t = (1_000 + 600 + 300 + 60 + 5) * NS
    runtime.advance()
    assert runtime.snapshot().state is CosecantState.FINAL_LOCK
    return runtime, clock


def _observation(runtime, *, at_ns: int, present: bool = True):
    snapshot = runtime.snapshot()
    return StudyReturnObservation(
        presence=StudyPresence.PRESENT if present else StudyPresence.ABSENT,
        study_block_id=snapshot.study_block_id,
        break_id=snapshot.break_id,
        context_token=snapshot.study_context_token,
        observed_monotonic_ns=at_ns,
        source="RESOURCE_INTENT",
        evidence_token=f"evidence-{at_ns}",
        fresh=True,
        exact_resource_confirmed=present,
    )


def test_observation_captured_before_advance_is_accepted(locked_break):
    """The exact monitor.py ordering must not discard valid evidence.

    monitor._route_context does:
        t_fg = foreground.observed_monotonic_ns   (captured earlier)
        ...
        cosecant.advance()                       (reads the clock NOW)
        cosecant.observe_return(t_fg)            (delivers the older stamp)
    """

    runtime, clock = locked_break

    t_foreground = clock.t + int(0.10 * NS)   # foreground sampled
    clock.t = t_foreground + int(0.05 * NS)   # 50 ms of real cycle work
    runtime.advance()                         # <-- bumps the shared field

    result = runtime.observe_return(_observation(runtime, at_ns=t_foreground))

    assert result.accepted, (
        "A valid return observation captured before advance() was rejected: "
        f"{result.message!r}. This is W-1."
    )


def test_three_continuous_seconds_confirm_under_monitor_ordering(locked_break):
    """The full 3-second proof must survive the real monitor call order."""

    runtime, clock = locked_break
    base = clock.t + NS

    for step in range(4):                      # 0.0, 1.0, 2.0, 3.0 seconds
        t_foreground = base + step * NS
        clock.t = t_foreground + int(0.05 * NS)
        runtime.advance()
        runtime.observe_return(_observation(runtime, at_ns=t_foreground))

    snapshot = runtime.snapshot()
    assert snapshot.state is CosecantState.CONFIRMED, (
        f"FINAL_LOCK never released; state is {snapshot.state.value}. This is W-1."
    )
    assert snapshot.return_confirmed


def test_clock_and_evidence_domains_are_independent(locked_break):
    """An observation timestamp must never poison the internal clock.

    observe_return currently writes the observation stamp into the same field
    _read_monotonic guards, so a future-dated observation can make the very
    next advance() raise "The monotonic clock moved backwards" and kill the
    monitor thread.
    """

    runtime, clock = locked_break

    future = clock.t + 5 * NS
    runtime.observe_return(_observation(runtime, at_ns=future))

    clock.t += int(0.5 * NS)  # the real clock advances normally
    try:
        runtime.advance()
    except RuntimeError as exc:  # pragma: no cover - this is the defect
        pytest.fail(
            f"An observation timestamp corrupted the internal clock: {exc}. "
            "This is W-1: the two timestamp domains must be independent."
        )
