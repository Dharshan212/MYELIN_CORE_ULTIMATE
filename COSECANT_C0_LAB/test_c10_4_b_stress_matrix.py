"""C10.4-B — consolidated COSECANT nucleus stress matrix.

LAB TESTING ONLY. No production file is modified.

C10.4-A proved the clean assembled journey. This file attacks it: wrong
resources, degraded evidence, the exact G/C boundary, FINAL_LOCK integrity,
break-time SINE/Trigger isolation, replay and second-break isolation, legal
terminal exits, and durable fact ordering.

CLOCK CONTRACT -- identical to C10.4-A, and binding on every claim here:

    The coordinator's real organ-routing path is exercised without the
    production sleep loop. Study/COSECANT/SINE and foreground timestamps are
    deterministically controlled; MIRL, Blacklist and Trigger keep their real
    production clocks and carry NO absolute-timing assertions.

FAULT SHAPING POLICY
    Where a condition cannot arise from a surface fixture, it is shaped at the
    CONTEXT BOUNDARY -- the immutable MonitorContext is rebuilt with
    dataclasses.replace before routing. Production state is never reached into
    and rewritten, and no verdict is fabricated to make a journey pass.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

import _lab
from _lab import INSTAGRAM, LECTURE, MRBEAST, OTHER_LECTURE, SHORTS, Surface

from COSECANT_STUDY_MODE.cosecant import CosecantState
from COSECANT_STUDY_MODE.study import StudyState
from CORE_ENGINE.blacklist import BlacklistAuthority, SineThresholdPolicy
from CORE_ENGINE.resource_intent import ResourceIntent

from test_c10_4_a_golden_assembly import (
    ALREADY_OVER_AT,
    BREAK_SECONDS,
    FINAL_LOCK_AT,
    IMPORTANT,
    KEYWORDS,
    NS,
    SUBJECT,
    TASK,
    Journey,
)

# Same window/process as LECTURE but unreadable: Browser holds its previous
# strong read, which proves the LAST resource and never the current one.
HELD = Surface(
    process_name=LECTURE.process_name,
    title=LECTURE.title,
    url="",
    hwnd=LECTURE.hwnd,
    process_id=LECTURE.process_id,
)
NOT_A_BROWSER = Surface(
    process_name="notepad",
    title="basal ganglia notes.txt - Notepad",
    url="",
    hwnd=909,
    process_id=910,
)

FAST_THRESHOLDS = SineThresholdPolicy(
    stage_one_seconds=0.3,
    stage_two_cumulative_seconds=1.5,
    offer_retry_seconds=0.1,
)


# ---------------------------------------------------------------------------
# Shared staging
# ---------------------------------------------------------------------------


def build(journey: Journey, surface, at_seconds: float):
    """Produce one real MonitorContext without routing it yet."""

    journey.clock.set_seconds_from(journey.base, at_seconds)
    journey.reader.set_surface(surface)
    observation = replace(
        journey.reader.observe(), observed_monotonic_ns=journey.clock.now
    )
    return journey.coordinator._classify_observation(observation)


def route_built(journey: Journey, context) -> None:
    journey.coordinator._route_context(context)


def start_study(journey: Journey) -> None:
    services = journey.services
    assert getattr(
        services.study.prepare(
            subject=SUBJECT,
            task=TASK,
            planned_seconds=3600,
            keywords=KEYWORDS,
            important_keywords=IMPORTANT,
        ),
        "accepted",
        False,
    )
    assert getattr(services.study.start(), "accepted", False)
    journey.route(LECTURE, 1.0)          # warm-up: publishes the Study context
    context = journey.route(LECTURE, 2.0)
    assert (
        context.resource_intent.verdict.classification
        is ResourceIntent.STUDY_ALIGNED
    ), "the LAB needs a genuinely aligned Lecture A"


def admit_break(journey: Journey, at: float = 3.0) -> float:
    journey.coordinator._request_cosecant_break(BREAK_SECONDS)
    journey.route(LECTURE, at)
    snapshot = journey.cosecant()
    assert snapshot.state is CosecantState.BREAK_ACTIVE, "break was not admitted"
    return (snapshot.break_started_monotonic_ns - journey.base) / NS


def reach_final_lock(journey: Journey) -> tuple[float, float]:
    """Return (started_at, r) with COSECANT parked in FINAL_LOCK."""

    start_study(journey)
    started_at = admit_break(journey)
    journey.route(INSTAGRAM, started_at + FINAL_LOCK_AT)
    assert journey.cosecant().state is CosecantState.FINAL_LOCK
    return started_at, started_at + FINAL_LOCK_AT + 5.0


@pytest.fixture()
def locked() -> tuple[Journey, float, float]:
    journey = Journey()
    started_at, r = reach_final_lock(journey)
    return journey, started_at, r


# ---------------------------------------------------------------------------
# GROUP 1 — exact-return rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "surface, label",
    [
        (OTHER_LECTURE, "a different exact video"),
        (MRBEAST, "entertainment on the same platform"),
        (INSTAGRAM, "a different platform"),
        (SHORTS, "a certified read with no exact resource token"),
        (HELD, "held previous Browser evidence"),
        (NOT_A_BROWSER, "uncertified / non-browser evidence"),
    ],
)
def test_g1_wrong_evidence_never_confirms(locked, surface, label):
    journey, _started, r = locked

    for step in (0.0, 1.5, 3.0, 4.5):
        journey.route(surface, r + step)
        assert journey.cosecant().return_confirmed is False, (
            f"{label} released the break"
        )
        assert journey.study_state() == "PAUSED", (
            f"{label} resumed Study without a factual return"
        )
    assert journey.cosecant().state is CosecantState.FINAL_LOCK


def test_g1_stale_resource_intent_never_confirms(locked):
    """Shaped at the boundary: production sets fresh=True whenever ns > 0."""

    journey, _started, r = locked

    for step in (0.0, 1.5, 3.0, 4.5):
        context = build(journey, LECTURE, r + step)
        stale = replace(
            context,
            resource_intent=replace(context.resource_intent, fresh=False),
        )
        route_built(journey, stale)
        assert journey.cosecant().return_confirmed is False
        assert journey.study_state() == "PAUSED"


def test_g1_resource_intent_browser_token_disagreement_never_confirms(locked):
    journey, _started, r = locked

    for step in (0.0, 1.5, 3.0, 4.5):
        context = build(journey, LECTURE, r + step)
        verdict = context.resource_intent.verdict
        identity = verdict.resource_identity
        shaped = replace(
            context,
            resource_intent=replace(
                context.resource_intent,
                verdict=replace(
                    verdict,
                    resource_identity=replace(
                        identity, opaque_resource_token="DISAGREEING-TOKEN"
                    ),
                ),
            ),
        )
        route_built(journey, shaped)
        assert journey.cosecant().return_confirmed is False
        assert journey.study_state() == "PAUSED"


def test_g1_resource_intent_browser_platform_disagreement_never_confirms(locked):
    journey, _started, r = locked

    for step in (0.0, 1.5, 3.0, 4.5):
        context = build(journey, LECTURE, r + step)
        verdict = context.resource_intent.verdict
        identity = verdict.resource_identity
        shaped = replace(
            context,
            resource_intent=replace(
                context.resource_intent,
                verdict=replace(
                    verdict,
                    resource_identity=replace(identity, platform_key="not-youtube"),
                ),
            ),
        )
        route_built(journey, shaped)
        assert journey.cosecant().return_confirmed is False
        assert journey.study_state() == "PAUSED"


def test_g1_uncertified_identity_never_confirms(locked):
    journey, _started, r = locked

    for step in (0.0, 1.5, 3.0, 4.5):
        context = build(journey, LECTURE, r + step)
        verdict = context.resource_intent.verdict
        identity = verdict.resource_identity
        shaped = replace(
            context,
            resource_intent=replace(
                context.resource_intent,
                verdict=replace(
                    verdict,
                    resource_identity=replace(
                        identity, browser_evidence_certified=False
                    ),
                ),
            ),
        )
        route_built(journey, shaped)
        assert journey.cosecant().return_confirmed is False
        assert journey.study_state() == "PAUSED"


def test_g1_exact_lecture_a_then_confirms(locked):
    """The control: after all that rejection, the real key still works."""

    journey, _started, r = locked

    journey.route(LECTURE, r)
    assert journey.cosecant().state is CosecantState.RETURN_CONFIRMING
    journey.route(LECTURE, r + 1.5)
    journey.route(LECTURE, r + 3.0)
    assert journey.cosecant().return_confirmed is True
    assert journey.study().state is StudyState.ACTIVE


# ---------------------------------------------------------------------------
# GROUP 2 — frozen G / C physiology
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gap", [2.199, 2.200])
def test_g2_gap_within_g_preserves_continuity(gap):
    journey = Journey()
    _started, r = reach_final_lock(journey)

    journey.route(LECTURE, r)
    assert journey.cosecant().state is CosecantState.RETURN_CONFIRMING
    first = journey.cosecant().confirmation_elapsed_seconds

    journey.route(LECTURE, r + gap)
    snapshot = journey.cosecant()
    assert snapshot.state is CosecantState.RETURN_CONFIRMING
    assert snapshot.confirmation_elapsed_seconds > first, (
        f"a {gap}s gap restarted the proof instead of extending it "
        f"({first} -> {snapshot.confirmation_elapsed_seconds})"
    )
    assert snapshot.return_confirmed is False, (
        "a within-G gap must never itself constitute the 3-second proof"
    )


def test_g2_gap_beyond_g_restarts_the_proof():
    journey = Journey()
    _started, r = reach_final_lock(journey)

    journey.route(LECTURE, r)
    first = journey.cosecant().confirmation_elapsed_seconds
    assert journey.cosecant().state is CosecantState.RETURN_CONFIRMING

    journey.route(LECTURE, r + 2.201)
    snapshot = journey.cosecant()
    assert snapshot.confirmation_elapsed_seconds <= first + 0.001, (
        f"a 2.201s gap must restart the proof, got elapsed "
        f"{snapshot.confirmation_elapsed_seconds}"
    )
    assert snapshot.return_confirmed is False


def test_g2_continuous_within_g_sequence_confirms():
    journey = Journey()
    _started, r = reach_final_lock(journey)

    for step in (0.0, 1.5, 3.0):
        journey.route(LECTURE, r + step)
    assert journey.cosecant().return_confirmed is True


def test_g2_restarted_sequence_does_not_confirm_at_three_seconds():
    """0.0 -> 2.201 -> 3.0 restarts at 2.201, so 3.0 cannot be the proof."""

    journey = Journey()
    _started, r = reach_final_lock(journey)

    journey.route(LECTURE, r)
    journey.route(LECTURE, r + 2.201)
    journey.route(LECTURE, r + 3.0)

    snapshot = journey.cosecant()
    assert snapshot.return_confirmed is False, (
        "the restarted window only accumulated "
        f"{snapshot.confirmation_elapsed_seconds}s and must not confirm"
    )
    assert snapshot.confirmation_elapsed_seconds < 3.0


# ---------------------------------------------------------------------------
# GROUP 3 — FINAL_LOCK physiology
# ---------------------------------------------------------------------------


def test_g3_final_lock_exposes_no_escape(locked):
    journey, _started, _r = locked
    snapshot = journey.cosecant()

    assert snapshot.state is CosecantState.FINAL_LOCK
    assert snapshot.allowed_actions == ()
    assert snapshot.popup_must_remain_open is True
    assert snapshot.final_locked is True
    assert journey.services.cosecant.record_return_intent().accepted is False, (
        "return intent must not release FINAL_LOCK"
    )
    assert journey.study_state() == "PAUSED"


def test_g3_lost_confirmation_restores_final_lock(locked):
    """It must restore to the stage due NOW, not to an earlier one."""

    journey, _started, r = locked

    journey.route(LECTURE, r)
    assert journey.cosecant().state is CosecantState.RETURN_CONFIRMING
    assert journey.cosecant().final_locked is True, (
        "a confirmation that began at FINAL_LOCK stays presentationally locked"
    )

    journey.route(OTHER_LECTURE, r + 1.0)
    restored = journey.cosecant()
    assert restored.state is CosecantState.FINAL_LOCK, (
        f"lost confirmation restored to {restored.state} instead of FINAL_LOCK"
    )
    assert restored.state is not CosecantState.BREAK_COMPLETE
    assert restored.state is not CosecantState.BREAK_ALREADY_OVER

    # A fresh factual sequence still confirms normally afterwards.
    for step in (2.5, 4.0, 5.5):
        journey.route(LECTURE, r + step)
    assert journey.cosecant().return_confirmed is True
    assert journey.study().state is StudyState.ACTIVE


# ---------------------------------------------------------------------------
# GROUP 4 — break-time SINE / Trigger isolation
# ---------------------------------------------------------------------------


def _short_threshold_blacklist(journey: Journey) -> list:
    """Swap in the sanctioned short-threshold Blacklist and record its offers.

    The returned list collects every cycle in which Blacklist actually
    published a threshold offer. Without it the isolation assertion would be
    unfalsifiable: "Trigger founded nothing" is trivially true if Blacklist
    never reached threshold in the first place.
    """

    offers: list = []
    blacklist = BlacklistAuthority(thresholds=FAST_THRESHOLDS)
    blacklist.start_session()
    real_observe = blacklist.observe

    def observe(context):
        snapshot = real_observe(context)
        if getattr(snapshot, "threshold_offer", None) is not None:
            offers.append(snapshot)
        return snapshot

    blacklist.observe = observe
    services = replace(journey.services, blacklist=blacklist)
    journey.services = services
    journey.coordinator.services = services
    return offers


def test_g4_no_new_sine_intervention_during_any_break_stage():
    journey = Journey()
    start_study(journey)
    offers = _short_threshold_blacklist(journey)
    started_at = admit_break(journey)

    stages = {
        "BREAK_ACTIVE": started_at + 10.0,
        "BREAK_COMPLETE": started_at + BREAK_SECONDS + 1,
        "BREAK_ALREADY_OVER": started_at + ALREADY_OVER_AT + 1,
        "FINAL_LOCK": started_at + FINAL_LOCK_AT + 1,
    }
    for expected, at in stages.items():
        # Dwell on social evidence so Blacklist genuinely reaches threshold.
        for tick in range(4):
            context = journey.route(INSTAGRAM, at + tick * 0.5)
            assert (
                context.resource_intent.verdict.classification
                is ResourceIntent.APPROVED_BREAK
            ), "the break must own the surface for this to mean anything"
        state = journey.cosecant().state
        assert str(getattr(state, "value", state)) == expected, (
            f"expected {expected}, COSECANT was {state}"
        )
        live = journey.services.trigger.live_view()
        assert int(getattr(live, "admitted_count", 0) or 0) == 0, (
            f"a SINE intervention was founded during {expected}; COSECANT "
            "must be the sole break authority"
        )
        assert not bool(getattr(live, "pending_candidate_uid", "")), (
            f"a candidate was minted during {expected}"
        )
        assert journey.services.sine.protected_red_active() is False
        assert not journey.sine_is_live()

    # The assertion above is only meaningful if Blacklist genuinely reached
    # threshold during the break -- otherwise Trigger had nothing to refuse.
    assert offers, (
        "Blacklist never published a threshold offer during the break, so "
        "this test proved nothing about Trigger suppression"
    )


def test_g4_normal_triggering_returns_after_the_break():
    """Suppression must be state-scoped, never session-wide."""

    journey = Journey()
    start_study(journey)
    _short_threshold_blacklist(journey)
    started_at = admit_break(journey)
    r = started_at + FINAL_LOCK_AT + 5.0

    journey.route(INSTAGRAM, started_at + FINAL_LOCK_AT)
    for step in (0.0, 1.5, 3.0):
        journey.route(LECTURE, r + step)
    assert journey.cosecant().return_confirmed is True
    assert journey.study().state is StudyState.ACTIVE

    # Ordinary off-task behaviour after the break must be eligible again.
    minted = False
    at = r + 5.0
    for _ in range(30):
        context = journey.route(INSTAGRAM, at)
        classification = context.resource_intent.verdict.classification
        if classification is not ResourceIntent.APPROVED_BREAK:
            live = journey.services.trigger.live_view()
            if int(getattr(live, "admitted_count", 0) or 0) > 0 or bool(
                getattr(live, "pending_candidate_uid", "")
            ):
                minted = True
                break
        at += 0.5

    assert minted, (
        "normal Blacklist -> Trigger eligibility never returned after the "
        "break ended; C8.4 suppression must not be session-wide"
    )


# ---------------------------------------------------------------------------
# GROUP 5 — retirement, replay refusal, second break
# ---------------------------------------------------------------------------


def test_g5_old_break_evidence_cannot_confirm_again():
    journey = Journey()
    started_at, r = reach_final_lock(journey)

    first_break_id = journey.cosecant().break_id
    first_target = journey.cosecant().intended_return_target

    for step in (0.0, 1.5, 3.0):
        journey.route(LECTURE, r + step)
    assert journey.cosecant().return_confirmed is True
    confirmed_count = journey.fact_kinds.count("RETURN_CONFIRMED")
    assert confirmed_count == 1

    # Replay the same exact evidence after the episode retired.
    for step in (4.5, 6.0, 7.5):
        journey.route(LECTURE, r + step)
    assert journey.fact_kinds.count("RETURN_CONFIRMED") == confirmed_count, (
        "retired break evidence produced a second confirmation"
    )
    assert first_break_id
    assert first_target is not None


def test_g5_second_break_has_its_own_identity_and_target():
    journey = Journey()
    started_at, r = reach_final_lock(journey)

    first_break_id = journey.cosecant().break_id
    first_target = journey.cosecant().intended_return_target

    for step in (0.0, 1.5, 3.0):
        journey.route(LECTURE, r + step)
    assert journey.study().state is StudyState.ACTIVE

    # A second legitimate break in the same Study block.
    second_at = r + 10.0
    journey.route(LECTURE, second_at)
    journey.coordinator._request_cosecant_break(BREAK_SECONDS)
    journey.route(LECTURE, second_at + 1.5)

    snapshot = journey.cosecant()
    assert snapshot.state is CosecantState.BREAK_ACTIVE, "second break refused"
    assert snapshot.break_id != first_break_id, "break identity must be fresh"

    second_target = snapshot.intended_return_target
    assert second_target is not None
    assert second_target is not first_target, "target memory must be re-frozen"
    assert snapshot.generation > 1, "a second break is a new COSECANT generation"


def test_g5_break_one_identity_cannot_release_break_two():
    """The generation barrier, attacked while break 2 is genuinely ACTIVE.

    Everything about this observation is perfect -- PRESENT, fresh, exact
    resource confirmed, current Study block, current context token -- EXCEPT
    that it carries break 1's break_id. Episode identity alone must refuse it.

    This is deliberately about episode identity, not Browser evidence quality;
    G1 already covers the evidence-quality matrix.
    """

    from COSECANT_STUDY_MODE.cosecant import StudyPresence, StudyReturnObservation

    journey = Journey()
    started_at, r = reach_final_lock(journey)

    first = journey.cosecant()
    first_break_id = first.break_id
    first_block_id = first.study_block_id
    first_context_token = first.study_context_token
    assert first_break_id

    for step in (0.0, 1.5, 3.0):
        journey.route(LECTURE, r + step)
    assert journey.cosecant().return_confirmed is True

    # Break 2, genuinely admitted in the same Study block.
    second_at = r + 10.0
    journey.route(LECTURE, second_at)
    journey.coordinator._request_cosecant_break(BREAK_SECONDS)
    journey.route(LECTURE, second_at + 1.5)

    active = journey.cosecant()
    assert active.state is CosecantState.BREAK_ACTIVE
    second_break_id = active.break_id
    assert second_break_id != first_break_id

    # The intended architecture: SAME Study block, NEW COSECANT episode.
    # Asserting it here is what makes break_id provably the only foreign field
    # below -- otherwise the observation is built from break 1's values and
    # the "only wrong thing" claim rests on an unstated assumption.
    assert active.study_block_id == first_block_id
    assert active.study_context_token == first_context_token

    before_facts = list(journey.fact_kinds)
    before_batches = list(journey.batches_accepted)
    journey.clock.set_seconds_from(journey.base, second_at + 3.0)

    stale_episode = StudyReturnObservation(
        presence=StudyPresence.PRESENT,
        study_block_id=active.study_block_id,
        break_id=first_break_id,               # <-- the ONLY foreign field
        context_token=active.study_context_token,
        observed_monotonic_ns=journey.clock.now,
        source="RESOURCE_INTENT",
        evidence_token="replayed-break-one",
        fresh=True,
        exact_resource_confirmed=True,
    )
    result = journey.services.cosecant.observe_return(stale_episode)

    assert result.accepted is False, (
        "break 1's episode identity was accepted during break 2"
    )
    assert result.facts == (), (
        "a refused foreign observation must not even construct a fact"
    )

    # Route the REJECTED result through the real persistence path. Without
    # this, asserting fact_kinds is unchanged proves nothing about durability:
    # nothing routed the result, so nothing could have been appended whatever
    # the result carried. Routing it makes the no-side-effect claim real.
    journey.coordinator._route_cosecant_result(result)

    after = journey.cosecant()
    assert after.state is CosecantState.BREAK_ACTIVE, (
        "break 2 must be undisturbed by a foreign episode's evidence"
    )
    assert after.break_id == second_break_id
    assert after.return_confirmed is False
    assert journey.fact_kinds == before_facts, (
        "a refused foreign observation must emit no durable facts; "
        f"new facts: {journey.fact_kinds[len(before_facts):]}"
    )
    assert journey.batches_accepted == before_batches, (
        "a refused foreign observation must not reach persistence at all"
    )


# ---------------------------------------------------------------------------
# GROUP 6 — legal terminal exits
# ---------------------------------------------------------------------------


def test_g6_session_cancellation_never_fakes_a_return():
    journey = Journey()
    start_study(journey)
    admit_break(journey)
    assert journey.cosecant().state is CosecantState.BREAK_ACTIVE

    result = journey.services.cosecant.cancel_for_session_end()
    assert result.accepted is True

    # Route the terminal result through the REAL persistence path. Asserting
    # only the in-memory state would leave the durable terminal fact unproven.
    journey.coordinator._route_cosecant_result(result)

    snapshot = journey.cosecant()
    assert snapshot.state is CosecantState.CANCELLED
    assert snapshot.return_confirmed is False
    assert journey.fact_kinds.count("BREAK_CANCELLED") == 1, (
        f"exactly one durable BREAK_CANCELLED expected, saw {journey.fact_kinds}"
    )
    assert all(journey.batches_accepted), "every fact batch must be durable"
    assert "RETURN_CONFIRMED" not in journey.fact_kinds, (
        "a cancelled break must never produce a confirmed return"
    )


def test_g6_safe_shutdown_never_fakes_a_return():
    journey = Journey()
    started_at, r = reach_final_lock(journey)

    journey.route(LECTURE, r)
    assert journey.cosecant().state is CosecantState.RETURN_CONFIRMING

    result = journey.services.cosecant.shutdown()
    assert result.accepted is True

    journey.coordinator._route_cosecant_result(result)

    snapshot = journey.cosecant()
    assert snapshot.state is CosecantState.SHUTDOWN
    assert snapshot.return_confirmed is False
    assert journey.fact_kinds.count("SAFE_SHUTDOWN") == 1, (
        f"exactly one durable SAFE_SHUTDOWN expected, saw {journey.fact_kinds}"
    )
    assert all(journey.batches_accepted), "every fact batch must be durable"
    assert "RETURN_CONFIRMED" not in journey.fact_kinds, (
        "shutdown during confirmation must not manufacture a recovery"
    )


# ---------------------------------------------------------------------------
# GROUP 7 — durable ordering under confirmation loss
# ---------------------------------------------------------------------------


def test_g7_confirmation_loss_ordering_is_durably_recorded():
    journey = Journey()
    started_at, r = reach_final_lock(journey)

    journey.route(LECTURE, r)                    # start confirmation
    journey.route(OTHER_LECTURE, r + 1.0)        # lose it
    for step in (2.5, 4.0, 5.5):                 # confirm cleanly afterwards
        journey.route(LECTURE, r + step)

    assert journey.cosecant().return_confirmed is True
    assert all(journey.batches_accepted), "every fact batch must be durable"

    confirmation_facts = [
        kind
        for kind in journey.fact_kinds
        if kind.startswith("RETURN_CONFIRMATION") or kind == "RETURN_CONFIRMED"
    ]

    # Report the factual sequence production actually emits rather than
    # asserting an invented event name. Both existing restart mechanisms are
    # accepted; what must hold is that a LOST precedes the next START/RESTART,
    # and that RETURN_CONFIRMED comes last exactly once.
    assert confirmation_facts[0] == "RETURN_CONFIRMATION_STARTED", (
        f"unexpected opening fact: {confirmation_facts}"
    )
    assert "RETURN_CONFIRMATION_LOST" in confirmation_facts, (
        f"a lost confirmation must be recorded: {confirmation_facts}"
    )
    lost_at = confirmation_facts.index("RETURN_CONFIRMATION_LOST")
    resumed = [
        kind
        for kind in confirmation_facts[lost_at + 1:]
        if kind
        in {"RETURN_CONFIRMATION_STARTED", "RETURN_CONFIRMATION_RESTARTED"}
    ]
    assert resumed, (
        f"confirmation must restart after a loss: {confirmation_facts}"
    )
    assert confirmation_facts[-1] == "RETURN_CONFIRMED", (
        f"the sequence must end confirmed: {confirmation_facts}"
    )
    assert confirmation_facts.count("RETURN_CONFIRMED") == 1
