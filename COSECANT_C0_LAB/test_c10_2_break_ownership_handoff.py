"""C10.2 — the SINE -> COSECANT break ownership handoff must be atomic.

EXPECTED BEFORE C10.2: the handoff tests FAIL.
EXPECTED AFTER  C10.2: all PASS, and must stay passing forever.

Monitor's cycle order is:

    sine.observe(context)
      ...
    _admit_pending_break(context)      <- Study PAUSED, COSECANT BREAK_ACTIVE
      ...
    sine.advance(...)

so a managed break can become factually BREAK_ACTIVE while a pre-existing,
non-Protected-Red SINE episode is still logically alive. It would usually
resolve on the NEXT observation, once Resource Intent publishes
APPROVED_BREAK -- but that is one cycle too late for an ownership transfer.

The ownership rule is:

    before the factual break -> SINE may own the intervention
    after  the factual break -> COSECANT alone owns break-return regulation

There must never be a window, however brief, in which BREAK_ACTIVE coexists
with a live SINE episode.

SINE already has the receptor for this -- ``confirm_break_started`` -- and
COSECANT already emits a factual BREAK_STARTED carrying the real break-start
monotonic timestamp. C10.2 is Monitor wiring only: connect the nerve, and use
COSECANT's own timestamp rather than inventing one.

C8.4 is a DIFFERENT boundary and is not what this tests. C8.4 stops new
break-time activity from exciting Trigger -> SINE. It does nothing about a
SINE episode that already existed when the break began.
"""

from __future__ import annotations

import time

import pytest

from _lab import INSTAGRAM, LECTURE, QuietMonitor, SineDriver

from COSECANT_STUDY_MODE.cosecant import CosecantFactKind, CosecantState
from CORE_ENGINE.resource_intent import ResourceIntent, StudyContext

NS = 10**9

SUBJECT = "Neuroscience"
TASK = "basal ganglia"
KEYWORDS = ("direct", "indirect")
IMPORTANT = ("basal ganglia",)
BREAK_SECONDS = 600

LIVE_PHASES = {"waiting_for_display", "active", "protected_red"}


class Bench:
    """A real coordinator with a real Study block and a real SINE episode."""

    def __init__(self) -> None:
        self.quiet = QuietMonitor(LECTURE)
        self.services = self.quiet.services
        self.coordinator = self.quiet.coordinator
        self.intent = self.services.resource_intent
        self.driver = SineDriver(sine=self.services.sine)

        prepared = self.services.study.prepare(
            subject=SUBJECT,
            task=TASK,
            planned_seconds=3600,
            keywords=KEYWORDS,
            important_keywords=IMPORTANT,
        )
        assert getattr(prepared, "accepted", False), "study prepare failed"
        started = self.services.study.start()
        assert getattr(started, "accepted", False), "study start failed"

        study = self.services.study.snapshot()
        assert self.intent.publish_study_context(
            StudyContext(
                block_id=study.block_id,
                generation=study.generation,
                display_state="ACTIVE",
                subject=SUBJECT,
                task=TASK,
                protection_active=True,
                planned_break_active=False,
                remaining_seconds=3600,
                published_monotonic_ns=time.monotonic_ns(),
                keywords=KEYWORDS,
                important_keywords=IMPORTANT,
                context_token=study.context_token,
            )
        )

    # -- helpers -------------------------------------------------------

    def look(self, surface):
        return self.quiet.look_at(surface)

    def sine_live(self):
        return self.services.sine.live_view()

    def sine_is_live(self) -> bool:
        phase = self.sine_live().phase
        return str(getattr(phase, "value", phase)) in LIVE_PHASES

    def cosecant_state(self):
        return self.services.cosecant.snapshot().state

    def study_state(self) -> str:
        state = self.services.study.snapshot().state
        return str(getattr(state, "value", state))

    def open_sine_episode(self) -> str:
        """Open a genuine, non-Protected-Red SINE episode."""

        self.driver.open_episode(self.look(INSTAGRAM))
        live = self.sine_live()
        assert self.sine_is_live(), f"expected a live SINE episode, got {live.phase}"
        assert live.protected_red_active is False, "this control must NOT be Red"
        assert live.candidate_uid, "the episode must carry a candidate identity"
        return live.candidate_uid

    def admit_break(self, surface=LECTURE):
        """Park a break request and let Monitor decide it on one observation."""

        self.coordinator._request_cosecant_break(BREAK_SECONDS)
        context = self.look(surface)
        self.coordinator._admit_pending_break(context)
        return context


@pytest.fixture()
def bench() -> Bench:
    return Bench()


# ---------------------------------------------------------------------------
# THE LESION
# ---------------------------------------------------------------------------


def test_accepted_break_resolves_a_pre_existing_sine_episode(bench: Bench):
    """BREAK_ACTIVE must never coexist with a live SINE episode."""

    candidate_uid = bench.open_sine_episode()
    bench.admit_break()

    assert bench.cosecant_state() is CosecantState.BREAK_ACTIVE, (
        "the lab needs a genuinely admitted break"
    )
    assert bench.study_state() == "PAUSED"

    live = bench.sine_live()
    assert not bench.sine_is_live(), (
        "a factual COSECANT break began while the pre-existing SINE episode "
        f"was still alive (phase={live.phase}). Two behavioural authorities "
        "owned the same moment. This is C10-L2."
    )
    assert live.candidate_uid == candidate_uid, (
        "the resolved episode must be the one that existed at admission"
    )


def test_handoff_uses_the_factual_break_started_timestamp(bench: Bench):
    """The handoff must ride COSECANT's own fact, not a fresh clock read."""

    bench.open_sine_episode()

    seen: list = []
    real = bench.services.sine.confirm_break_started

    def spy(*, candidate_uid: str, occurred_monotonic_ns: int) -> bool:
        seen.append((candidate_uid, occurred_monotonic_ns))
        return real(
            candidate_uid=candidate_uid,
            occurred_monotonic_ns=occurred_monotonic_ns,
        )

    bench.services.sine.confirm_break_started = spy

    before = time.monotonic_ns()
    bench.admit_break()
    after = time.monotonic_ns()

    assert seen, "Monitor never told SINE the break had started"
    uid, occurred = seen[0]

    snapshot = bench.services.cosecant.snapshot()
    assert uid, "the handoff must name the exact SINE candidate"
    assert snapshot.break_started_monotonic_ns == occurred, (
        "the handoff timestamp must be COSECANT's factual break start "
        f"({snapshot.break_started_monotonic_ns}), not {occurred}"
    )
    assert before <= occurred <= after, (
        "sanity: the factual timestamp still belongs to this admission"
    )


def test_break_started_fact_is_persisted_before_sine_is_resolved(bench: Bench):
    """Durability first, then ownership transfer."""

    bench.open_sine_episode()

    order: list[str] = []
    real_append = bench.services.storage.append_cosecant_facts
    real_confirm = bench.services.sine.confirm_break_started

    def append(*, session_id, facts):
        if any(
            getattr(f, "kind", None) is CosecantFactKind.BREAK_STARTED for f in facts
        ):
            order.append("persisted")
        return real_append(session_id=session_id, facts=facts)

    def confirm(*, candidate_uid: str, occurred_monotonic_ns: int) -> bool:
        order.append("sine_notified")
        return real_confirm(
            candidate_uid=candidate_uid,
            occurred_monotonic_ns=occurred_monotonic_ns,
        )

    bench.services.storage.append_cosecant_facts = append
    bench.services.sine.confirm_break_started = confirm

    bench.admit_break()

    assert order == ["persisted", "sine_notified"], (
        f"BREAK_STARTED must be durably routed before SINE is resolved; got {order}"
    )


# ---------------------------------------------------------------------------
# CONTROLS — what the handoff must NOT change
# ---------------------------------------------------------------------------


def test_break_admits_normally_with_no_sine_episode(bench: Bench):
    assert not bench.sine_is_live(), "this control starts with no episode"
    bench.admit_break()

    assert bench.cosecant_state() is CosecantState.BREAK_ACTIVE, (
        "an absent SINE episode must not block a legitimate break"
    )
    assert bench.study_state() == "PAUSED"


def test_protected_red_still_refuses_the_break_and_is_never_handed_off(bench: Bench):
    """Red must not become escapable via the new handoff."""

    bench.driver.escalate_to_protected_red(bench.look(INSTAGRAM))
    assert bench.services.sine.protected_red_active() is True

    called: list = []
    real = bench.services.sine.confirm_break_started

    def spy(**kwargs):
        called.append(kwargs)
        return real(**kwargs)

    bench.services.sine.confirm_break_started = spy

    bench.admit_break()

    assert bench.cosecant_state() is not CosecantState.BREAK_ACTIVE, (
        "C8.3's Protected Red break gate must still refuse admission"
    )
    assert bench.study_state() == "ACTIVE", "Study must not have been paused"
    assert called == [], (
        "confirm_break_started must NEVER be used while Protected Red is "
        "active -- that would turn the handoff into a Red escape"
    )
    assert bench.services.sine.protected_red_active() is True


def test_duplicate_break_request_is_rejected_before_admission(bench: Bench):
    """A second request never reaches admission while a break is running.

    This is the EARLY gate in ``_request_cosecant_break``, not the post-pause
    rollback branch. The two are tested separately because an earlier version
    of this file conflated them: it set up an already-active break and then
    claimed to be exercising the rollback path, which
    ``_request_cosecant_break`` had in fact already short-circuited.
    """

    bench.open_sine_episode()
    bench.admit_break()
    assert bench.cosecant_state() is CosecantState.BREAK_ACTIVE

    called: list = []
    real = bench.services.sine.confirm_break_started

    def spy(**kwargs):
        called.append(kwargs)
        return real(**kwargs)

    bench.services.sine.confirm_break_started = spy

    bench.coordinator._request_cosecant_break(BREAK_SECONDS)
    assert bench.coordinator._pending_break_seconds is None, (
        "the duplicate request must be discarded before it can be admitted"
    )
    bench.coordinator._admit_pending_break(bench.look(LECTURE))

    assert called == [], "no ownership transfer may occur without a new break"


def test_start_break_refusal_rolls_study_back_and_never_notifies_sine(bench: Bench):
    """THE ROLLBACK BRANCH: refusal AFTER Study has factually paused.

    Reaching this requires the C5 admission gates to PASS and Study.pause() to
    succeed, so the refusal is injected at ``cosecant.start_break`` -- the only
    place a rejection can land after the pause. The injected refusal asserts
    Study is already PAUSED when it runs, which is what proves the rollback
    branch was genuinely reached rather than short-circuited earlier.
    """

    from COSECANT_STUDY_MODE.cosecant import CosecantResult

    candidate_uid = bench.open_sine_episode()

    observed_state: list[str] = []
    notified: list = []

    real_confirm = bench.services.sine.confirm_break_started

    def confirm_spy(**kwargs):
        notified.append(kwargs)
        return real_confirm(**kwargs)

    def refusing_start_break(*, study, selected_break_seconds, intended_return_target):
        # Study must ALREADY be paused here, or this is not the branch we mean.
        observed_state.append(bench.study_state())
        return CosecantResult(
            accepted=False,
            message="injected refusal after Study paused",
            snapshot=bench.services.cosecant.snapshot(),
            facts=(),
        )

    bench.services.sine.confirm_break_started = confirm_spy
    bench.services.cosecant.start_break = refusing_start_break

    bench.admit_break()

    assert observed_state == ["PAUSED"], (
        "the injected refusal must run AFTER Study.pause() -- otherwise the "
        f"rollback branch was never reached (saw {observed_state})"
    )
    assert bench.study_state() == "ACTIVE", (
        "the existing C5 rollback must restore Study after a refused break"
    )
    assert bench.cosecant_state() is not CosecantState.BREAK_ACTIVE
    assert notified == [], (
        "a break that never started must not transfer ownership to COSECANT"
    )
    live = bench.sine_live()
    assert bench.sine_is_live(), (
        "the pre-existing SINE episode must survive a refused break"
    )
    assert live.candidate_uid == candidate_uid


# ---------------------------------------------------------------------------
# FAIL-LOUD GUARDS — dual authority must never be reachable silently
# ---------------------------------------------------------------------------


def test_sine_refusing_the_handoff_raises_rather_than_leaving_two_authorities(
    bench: Bench,
):
    """Guard A. COSECANT is already durable; a refused handoff must be loud."""

    bench.open_sine_episode()

    persisted: list = []
    real_append = bench.services.storage.append_cosecant_facts

    def append(*, session_id, facts):
        if any(
            getattr(f, "kind", None) is CosecantFactKind.BREAK_STARTED for f in facts
        ):
            persisted.append(True)
        return real_append(session_id=session_id, facts=facts)

    bench.services.storage.append_cosecant_facts = append
    bench.services.sine.confirm_break_started = (
        lambda *, candidate_uid, occurred_monotonic_ns: False
    )

    with pytest.raises(RuntimeError) as excinfo:
        bench.admit_break()

    message = str(excinfo.value).lower()
    assert "handoff" in message or "authorities" in message, (
        f"the failure must name the ownership problem, got: {excinfo.value}"
    )
    assert persisted, (
        "BREAK_STARTED must still have been durably routed before the handoff "
        "was attempted -- durability does not depend on SINE agreeing"
    )
    assert bench.cosecant_state() is CosecantState.BREAK_ACTIVE, (
        "the factual break really did start; the error is about ownership"
    )


def test_accepted_break_without_break_started_fact_raises(bench: Bench):
    """Guard B. No fallback clock, no manufactured timestamp."""

    from COSECANT_STUDY_MODE.cosecant import CosecantResult

    empty = CosecantResult(
        accepted=True,
        message="accepted but carrying no BREAK_STARTED fact",
        snapshot=bench.services.cosecant.snapshot(),
        facts=(),
    )
    with pytest.raises(RuntimeError) as excinfo:
        bench.coordinator._break_started_monotonic_ns(empty)
    assert "break_started" in str(excinfo.value).lower()


def test_break_started_fact_with_zero_timestamp_raises(bench: Bench):
    """A present-but-invalid timestamp must fail the same way as an absent one."""

    from COSECANT_STUDY_MODE.cosecant import CosecantFact, CosecantResult

    zero = CosecantFact(
        sequence=1,
        kind=CosecantFactKind.BREAK_STARTED,
        break_id="break",
        study_block_id="block",
        from_state=CosecantState.INACTIVE,
        to_state=CosecantState.BREAK_ACTIVE,
        effective_monotonic_ns=0,
        observed_monotonic_ns=0,
        occurred_wall_time_utc="",
        message="zero timestamp",
    )
    result = CosecantResult(
        accepted=True,
        message="accepted with an unusable timestamp",
        snapshot=bench.services.cosecant.snapshot(),
        facts=(zero,),
    )
    with pytest.raises(RuntimeError):
        bench.coordinator._break_started_monotonic_ns(result)


def test_non_study_resource_still_refuses_admission(bench: Bench):
    """The C5 gates are unchanged: an unaligned resource founds no break."""

    bench.open_sine_episode()
    bench.admit_break(surface=INSTAGRAM)

    assert bench.cosecant_state() is not CosecantState.BREAK_ACTIVE
    assert bench.study_state() == "ACTIVE"
    assert bench.sine_is_live(), (
        "a refused break must leave the existing SINE episode alone"
    )


def test_no_new_sine_stage_matures_after_ownership_transfers(bench: Bench):
    """A same-cycle escalation deadline must not outlive the handoff."""

    bench.open_sine_episode()
    bench.admit_break()
    assert bench.cosecant_state() is CosecantState.BREAK_ACTIVE

    # Drive SINE's own scheduler well past its next stage deadline.
    now = time.monotonic_ns() + 10 * NS
    bench.services.sine.advance(now_monotonic_ns=now)

    assert not bench.sine_is_live(), (
        "a SINE stage matured after COSECANT took ownership of the break"
    )
    assert bench.services.sine.protected_red_active() is False
