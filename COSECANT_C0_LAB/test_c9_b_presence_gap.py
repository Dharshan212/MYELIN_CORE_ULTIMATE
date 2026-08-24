"""C9-B — the measured presence gap G = 2.2 s.

EXPECTED BEFORE C9-B: the boundary tests around 2.2 s fail (G is still 1.5).
EXPECTED AFTER  C9-B: all PASS, and must stay passing forever.

C9-A measured 1600 real intervals of E = A(i) - O(i-1) at production cadence
and ChatGPT selected G = 2.2 s from that evidence. This file pins the
behaviour of the two gates that consume it, and — just as importantly — pins
everything a WIDER G must NOT weaken.

Both gates use a strict ``>`` comparison:

    advance()        while RETURN_CONFIRMING:  now - last_presence > G -> stale
    observe_return():                          now - last_presence > G -> restart

so exactly G is NOT a violation. That is asserted explicitly rather than
assumed, because it is the difference between 2.200000 s being valid and
being fatal.

TIMING IS DETERMINISTIC. CosecantRuntime takes an injectable ``monotonic_ns``,
so every instant here is an exact integer nanosecond. There is not one
wall-clock sleep in this file: a gap-boundary test that slept would be
measuring the machine, not the gate.
"""

from __future__ import annotations

import pytest

import _lab  # noqa: F401  (path + isolated storage)

from COSECANT_STUDY_MODE.cosecant import (
    CosecantPolicy,
    CosecantReturnTarget,
    CosecantRuntime,
    CosecantState,
    StudyPresence,
    StudyReturnObservation,
)
from COSECANT_STUDY_MODE.study import StudyCompletionReason, StudySnapshot, StudyState

NS = 10**9

# The measured decision from C9-A.
EXPECTED_G = 2.2
EXPECTED_C = 3.0

BLOCK_ID = "BLOCK-C9B"
SUBJECT = "Neuroscience"
TASK = "basal ganglia"
PLATFORM = "youtube"
TOKEN_A = "RESOURCE-TOKEN-A"
TOKEN_B = "RESOURCE-TOKEN-B"
BREAK_SECONDS = 60


class Clock:
    """An exact, hand-advanced monotonic clock."""

    def __init__(self, start: int = 10 * NS) -> None:
        self.now = int(start)

    def __call__(self) -> int:
        return self.now

    def advance_seconds(self, seconds: float) -> int:
        self.now += int(round(seconds * NS))
        return self.now


class _ContextSink:
    """Minimal StudyContext authority.

    COSECANT only requires that its BREAK context is accepted and retired; the
    subject under test here is COSECANT's own gap arithmetic, so this collaborator
    is intentionally trivial. Cross-organ behaviour is covered by the C5/C6/C8
    suites against the real Resource Intent.
    """

    def __init__(self) -> None:
        self.published = 0
        self.retired = 0

    def publish_study_context(self, context) -> bool:
        self.published += 1
        return True

    def retire_study_context(self, expected_context_token: str = "") -> bool:
        self.retired += 1
        return True


def _study_snapshot(clock: Clock) -> StudySnapshot:
    return StudySnapshot(
        block_id=BLOCK_ID,
        generation=1,
        state=StudyState.PAUSED,
        subject=SUBJECT,
        task=TASK,
        keywords=("direct", "indirect"),
        important_keywords=("basal ganglia",),
        active_epoch_monotonic_ns=1,
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
        published_monotonic_ns=clock.now,
    )


class Break:
    """One COSECANT break driven on an exact clock, parked in RETURN_CONFIRMING."""

    def __init__(self) -> None:
        self.clock = Clock()
        self.sink = _ContextSink()
        self.runtime = CosecantRuntime(
            context_authority=self.sink,
            monotonic_ns=self.clock,
        )
        study = _study_snapshot(self.clock)
        self.context_token = study.context_token
        target = CosecantReturnTarget(
            study_context_token=self.context_token,
            platform_key=PLATFORM,
            resource_token=TOKEN_A,
            observed_monotonic_ns=self.clock.now,
        )
        result = self.runtime.start_break(
            study=study,
            selected_break_seconds=BREAK_SECONDS,
            intended_return_target=target,
        )
        assert result.accepted, result.message
        self.snapshot = self.runtime.snapshot()

    # -- evidence ------------------------------------------------------

    def observation(
        self,
        *,
        present: bool = True,
        exact: bool = True,
        fresh: bool = True,
        token: str = "",
        presence: StudyPresence | None = None,
    ) -> StudyReturnObservation:
        snapshot = self.runtime.snapshot()
        if presence is None:
            presence = StudyPresence.PRESENT if present else StudyPresence.ABSENT
        return StudyReturnObservation(
            presence=presence,
            study_block_id=snapshot.study_block_id,
            break_id=snapshot.break_id,
            context_token=snapshot.study_context_token,
            observed_monotonic_ns=self.clock.now,
            source="RESOURCE_INTENT",
            evidence_token=token or f"ev-{self.clock.now}",
            fresh=fresh,
            exact_resource_confirmed=exact,
        )

    def observe(self, **kwargs):
        return self.runtime.observe_return(self.observation(**kwargs))

    def state(self) -> CosecantState:
        return self.runtime.snapshot().state

    def elapsed(self) -> float:
        return self.runtime.snapshot().confirmation_elapsed_seconds

    # -- staging -------------------------------------------------------

    def begin_confirmation(self) -> None:
        """Run the break out and land in RETURN_CONFIRMING on the exact target."""

        self.clock.advance_seconds(BREAK_SECONDS + 1)
        self.runtime.advance()
        self.observe()
        assert self.state() is CosecantState.RETURN_CONFIRMING, self.state()


@pytest.fixture()
def running() -> Break:
    episode = Break()
    episode.begin_confirmation()
    return episode


# ---------------------------------------------------------------------------
# The constant itself
# ---------------------------------------------------------------------------


def test_policy_carries_the_measured_gap():
    policy = CosecantPolicy()
    assert policy.maximum_presence_gap_seconds == EXPECTED_G, (
        "G must be the value C9-A measured and C9-B authorised"
    )
    assert policy.return_confirmation_seconds == EXPECTED_C, (
        "the 3-second proof is not part of this surgery"
    )
    assert policy.maximum_presence_gap_seconds < policy.return_confirmation_seconds, (
        "G must remain strictly below C, or the continuity gate becomes "
        "meaningless against the proof it guards"
    )


# ---------------------------------------------------------------------------
# The gap boundary
# ---------------------------------------------------------------------------


def test_gap_below_g_preserves_confirmation(running: Break):
    """An ordinary interval -- including C9-A's slowest successful read."""

    # Elapsed continuity is the real assertion. A lost confirmation is
    # immediately RESTARTED by the very next proving observation, so state
    # alone cannot distinguish "preserved" from "reset to zero" -- only a
    # monotonically growing confirmation_elapsed_seconds can.
    # Continuity may legitimately RIPEN into CONFIRMED here: these gaps sum past
    # the 3-second proof, and reaching it is the strongest possible evidence
    # that nothing was reset along the way.
    intact = {CosecantState.RETURN_CONFIRMING, CosecantState.CONFIRMED}
    previous = running.elapsed()
    for gap in (1.5, 1.5794, 2.0824):
        running.clock.advance_seconds(gap)
        running.runtime.advance()
        running.observe()
        assert running.state() in intact, (
            f"a {gap}s gap must not disturb confirmation under G={EXPECTED_G}; "
            f"state fell to {running.state()}"
        )
        current = running.elapsed()
        if running.state() is CosecantState.CONFIRMED:
            # Terminal: elapsed freezes at the proving value, so require only
            # that it did not collapse back toward zero.
            assert current >= previous, (
                f"a {gap}s gap reset an already-complete proof "
                f"({previous} -> {current})"
            )
        else:
            assert current > previous, (
                f"a {gap}s gap reset the proof (elapsed {previous} -> "
                f"{current}); the confirmation was restarted, not preserved"
            )
        previous = current
    assert previous >= EXPECTED_C, (
        "three uninterrupted within-G intervals summing past 3s should have "
        "accumulated a complete proof"
    )


def test_gap_exactly_at_g_is_not_a_violation(running: Break):
    """Production compares with strict >, so exactly G remains valid."""

    before = running.elapsed()
    running.clock.advance_seconds(EXPECTED_G)
    running.runtime.advance()
    assert running.state() is CosecantState.RETURN_CONFIRMING, (
        "exactly G must not be treated as stale by advance()"
    )
    running.observe()
    assert running.state() is CosecantState.RETURN_CONFIRMING, (
        "exactly G must not restart confirmation in observe_return()"
    )
    assert running.elapsed() > before, (
        "an exactly-G interval must continue accumulating proof, not reset it"
    )


def test_gap_just_above_g_loses_confirmation(running: Break):
    running.clock.advance_seconds(EXPECTED_G + 0.001)
    running.runtime.advance()
    assert running.state() is not CosecantState.RETURN_CONFIRMING, (
        "a gap beyond G must lose continuous presence"
    )


def test_gap_above_g_in_observe_return_restarts_the_proof(running: Break):
    """If advance() has not already reset it, observe_return() must restart."""

    episode = Break()
    episode.begin_confirmation()
    first = episode.elapsed()
    episode.clock.advance_seconds(EXPECTED_G + 0.5)
    # observe_return without an intervening advance()
    episode.observe()
    assert episode.elapsed() <= first + 0.001, (
        "a gap beyond G must restart the 3-second window, not extend it"
    )


# ---------------------------------------------------------------------------
# What a WIDER G must NOT weaken
# ---------------------------------------------------------------------------


def test_reaching_g_does_not_complete_the_proof(running: Break):
    """2.2s of tolerance is not 3s of proof."""

    running.clock.advance_seconds(EXPECTED_G)
    running.runtime.advance()
    running.observe()
    assert running.state() is CosecantState.RETURN_CONFIRMING
    assert running.runtime.snapshot().return_confirmed is False, (
        "a single within-G interval must never satisfy the 3-second proof"
    )


def test_exact_return_still_needs_three_continuous_seconds():
    episode = Break()
    episode.begin_confirmation()

    # 2.9s of continuous exact presence, in within-G steps: still not enough.
    for _ in range(2):
        episode.clock.advance_seconds(1.45)
        episode.runtime.advance()
        episode.observe()
    assert episode.runtime.snapshot().return_confirmed is False, (
        f"{episode.elapsed()}s must not confirm a 3-second proof"
    )
    assert episode.elapsed() < EXPECTED_C

    # Cross 3.0s.
    episode.clock.advance_seconds(0.2)
    episode.runtime.advance()
    episode.observe()
    assert episode.runtime.snapshot().return_confirmed is True, (
        "3 continuous seconds of exact presence must still confirm"
    )


def test_absent_evidence_still_blocks_confirmation(running: Break):
    running.clock.advance_seconds(1.0)
    running.runtime.advance()
    running.observe(present=False, exact=False)
    assert running.runtime.snapshot().return_confirmed is False
    assert running.state() is not CosecantState.RETURN_CONFIRMING, (
        "factual absence must lose confirmation regardless of a wider G"
    )


def test_uncertain_evidence_still_blocks_confirmation(running: Break):
    running.clock.advance_seconds(1.0)
    running.runtime.advance()
    running.observe(presence=StudyPresence.UNCERTAIN, exact=False)
    assert running.runtime.snapshot().return_confirmed is False


def test_wrong_resource_still_blocks_confirmation(running: Break):
    """A wider G must not let a non-exact resource accumulate proof."""

    running.clock.advance_seconds(1.0)
    running.runtime.advance()
    running.observe(exact=False)
    assert running.runtime.snapshot().return_confirmed is False
    assert running.state() is not CosecantState.RETURN_CONFIRMING


def test_stale_evidence_still_blocks_confirmation(running: Break):
    running.clock.advance_seconds(1.0)
    running.runtime.advance()
    running.observe(fresh=False)
    assert running.runtime.snapshot().return_confirmed is False


def test_final_lock_stays_locked_until_factual_return():
    """A wider tolerance must not soften FINAL_LOCK."""

    episode = Break()
    policy = CosecantPolicy()
    # Walk the real escalation ladder to FINAL_LOCK.
    episode.clock.advance_seconds(
        BREAK_SECONDS
        + policy.already_over_delay_seconds
        + policy.final_lock_delay_seconds
        + 1
    )
    episode.runtime.advance()
    assert episode.state() is CosecantState.FINAL_LOCK

    snapshot = episode.runtime.snapshot()
    assert snapshot.allowed_actions == (), "FINAL_LOCK must expose no escape"
    assert snapshot.popup_must_remain_open is True
    assert episode.runtime.record_return_intent().accepted is False, (
        "intent must not release FINAL_LOCK"
    )

    # Wrong resource, repeatedly, within G: still locked.
    for _ in range(4):
        episode.clock.advance_seconds(1.0)
        episode.runtime.advance()
        episode.observe(exact=False)
    assert episode.runtime.snapshot().return_confirmed is False
    assert episode.state() is CosecantState.FINAL_LOCK

    # The exact resource, held 3 continuous seconds, still releases it.
    for _ in range(4):
        episode.clock.advance_seconds(1.0)
        episode.runtime.advance()
        episode.observe()
    assert episode.runtime.snapshot().return_confirmed is True, (
        "factual return verification must still release FINAL_LOCK"
    )


# ---------------------------------------------------------------------------
# The C9-A tail events, replayed as gaps
# ---------------------------------------------------------------------------


def test_measured_ordinary_tail_is_covered_but_failure_tail_is_not():
    """Replay the five real intervals above 2.0s from C9-A.

    This encodes the C9-B rationale as an executable check: the slowest
    ORDINARY successful observation stays inside G, while the non-steady,
    degraded-evidence and transition excursions deliberately fall outside it.
    G is not sized to swallow pre-gate admission work, Browser/UIA failures or
    identity changes.

    The four excluded events are NOT one kind of thing, and C9-A separated
    them deliberately: one is a break-admission transient recorded while
    COSECANT was still INACTIVE, one is a resource/identity transition that
    carried a SUCCESSFUL read, and two are degraded Browser evidence.
    """

    covered = 2.082418          # browser_status ok, ordinary successful read
    not_covered = (
        2.538306,               # break-admission transient (COSECANT INACTIVE)
        2.653100,               # identity transition
        2.676700,               # address_value_invalid
        2.828300,               # window_not_found
    )

    assert covered < EXPECTED_G, (
        "the slowest measured ordinary successful read must fall inside G"
    )
    for value in not_covered:
        assert value > EXPECTED_G, (
            f"{value}s is a non-steady, degraded-evidence or transition event "
            "and must remain outside G"
        )

    episode = Break()
    episode.begin_confirmation()
    before = episode.elapsed()
    episode.clock.advance_seconds(covered)
    episode.runtime.advance()
    episode.observe()
    assert episode.state() is CosecantState.RETURN_CONFIRMING, (
        "the measured ordinary tail must survive the gate"
    )
    assert episode.elapsed() > before, (
        "the measured ordinary tail must EXTEND the proof, not restart it -- "
        "state alone would also be RETURN_CONFIRMING after a reset"
    )

    episode.clock.advance_seconds(not_covered[-1])
    episode.runtime.advance()
    assert episode.state() is not CosecantState.RETURN_CONFIRMING, (
        "a 2.83s degraded-evidence gap must still break continuity"
    )
