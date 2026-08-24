"""C6 guard -- the exact return nerve.

EXPECTED BEFORE C6: FAIL.
EXPECTED AFTER C6:  PASS, and must stay passing forever.

C5 froze the intended return target. Nothing compares against it yet, so
``monitor._observe_cosecant_return`` still derives the whole exact-return fact
from ``verdict.study_idle_allowed`` -- an IDLE POLICY permission that is False
for the entire duration of an approved break. That is W-2.

C6 connects the comparison nerve:

    current certified Browser platform + opaque resource token
        vs
    the frozen CosecantReturnTarget

These tests are written against the OBSERVABLE fact Monitor delivers to
COSECANT (``StudyReturnObservation.exact_resource_confirmed``) and against the
named derivation that produces it. They deliberately do NOT re-specify the
3-second verifier, which already exists downstream and is not C6's job.

Run the fast tiers with:
    py -3 -m pytest test_c6_exact_return.py -q -m "not slow"
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from _lab import (
    Engine,
    INSTAGRAM,
    LECTURE,
    MRBEAST,
    OTHER_LECTURE,
    QuietMonitor,
    SHORTS,
    Surface,
    freeze_target,
)

from CORE_ENGINE.resource_intent import ResourceIntent
from COSECANT_STUDY_MODE.cosecant import CosecantReturnTarget, StudyPresence

NS = 10**9

# Same window and process as LECTURE, but a different video: the C4.5 W-8
# case, now used to prove that a shared title cannot forge an exact return.
SAME_TITLE_DIFFERENT_VIDEO = Surface(
    process_name="chrome.exe",
    title=LECTURE.title,
    url="https://www.youtube.com/watch?v=IMPOSTOR_042",
)

# The address bar cannot be read. Browser holds the previous strong evidence,
# which proves the LAST resource, never the current one.
UNREADABLE = Surface(
    process_name="chrome.exe",
    title=LECTURE.title,
    url="",
)

NOT_A_BROWSER = Surface(
    process_name="notepad.exe",
    title="basal ganglia notes.txt - Notepad",
    url="",
    hwnd=777,
    process_id=778,
)


# ---------------------------------------------------------------------------
# Tier 1 -- the derivation itself, on a quiet (never-running) coordinator
# ---------------------------------------------------------------------------


@pytest.fixture()
def quiet():
    engine = QuietMonitor(LECTURE)
    engine.on_break(block_id="BLOCK-C6")
    return engine


@pytest.fixture()
def frozen(quiet):
    """The intended return target, frozen from the real LECTURE observation."""

    context = quiet.look_at(LECTURE)
    target = freeze_target(context)
    assert target.platform_key == "youtube"
    assert target.resource_token, "C5 cannot freeze a target without an exact token"
    return target


# -- A: the exact intended target ------------------------------------------


def test_a_exact_intended_target_is_confirmed(quiet, frozen):
    """The whole point of C6: the frozen resource, seen again, proves return."""

    context = quiet.look_at(LECTURE)
    assert quiet.exact(context, frozen) is True, (
        "the exact frozen Study resource must prove an exact return"
    )


# -- B: same platform, different resource -----------------------------------


def test_b_same_platform_different_resource_is_not_a_return(quiet, frozen):
    context = quiet.look_at(OTHER_LECTURE)
    assert context.resource_intent.verdict.resource_identity.platform_key == "youtube"
    assert quiet.exact(context, frozen) is False, (
        "a different video on the same platform is not the intended resource"
    )


# -- C: different platform --------------------------------------------------


def test_c_different_platform_is_not_a_return(quiet, frozen):
    context = quiet.look_at(INSTAGRAM)
    assert quiet.exact(context, frozen) is False


def test_c_entertainment_on_the_same_platform_is_not_a_return(quiet, frozen):
    context = quiet.look_at(MRBEAST)
    assert quiet.exact(context, frozen) is False


# -- D / P: identical title, different token --------------------------------


def test_d_identical_title_different_token_is_not_a_return(quiet, frozen):
    """W-8's case, from the other direction: titles must carry no authority."""

    context = quiet.look_at(SAME_TITLE_DIFFERENT_VIDEO)
    identity = context.resource_intent.verdict.resource_identity
    assert identity.platform_key == "youtube"
    assert identity.opaque_resource_token != frozen.resource_token
    assert quiet.exact(context, frozen) is False, (
        "an identical window title must never forge an exact return"
    )


def test_p_the_title_is_not_consulted_at_all(quiet, frozen):
    """Same title -> refused; different title, right token -> confirmed."""

    impostor = quiet.look_at(SAME_TITLE_DIFFERENT_VIDEO)
    assert impostor.foreground.window_title == LECTURE.title
    assert quiet.exact(impostor, frozen) is False

    renamed = Surface(
        process_name=LECTURE.process_name,
        title="A completely different window title",
        url=LECTURE.url,
    )
    context = quiet.look_at(renamed)
    assert context.foreground.window_title != LECTURE.title
    assert quiet.exact(context, frozen) is True, (
        "the exact resource token, not the title, decides an exact return"
    )


# -- E: a different valid lecture -------------------------------------------


def test_e_a_different_valid_lecture_is_still_not_the_intended_one(quiet, frozen):
    """Study-aligned is not the same signal as intended-return-target."""

    context = quiet.look_at(OTHER_LECTURE)
    assert quiet.exact(context, frozen) is False, (
        "another genuine lecture may be Study material, but it is not the "
        "resource this break froze"
    )


# -- F: empty current resource token ----------------------------------------


def test_f_empty_current_resource_token_never_matches(quiet, frozen):
    """A strong read with no exact token cannot release a lock."""

    context = quiet.look_at(SHORTS)
    evidence = context.browser_evidence.evidence
    assert evidence.platform_key == "youtube"
    assert evidence.resource_token == "", "SHORTS must have no exact resource token"
    assert quiet.exact(context, frozen) is False


def test_f_an_empty_frozen_token_cannot_even_exist():
    """C5's fail-closed rule, restated so C6 can rely on it."""

    with pytest.raises(ValueError):
        CosecantReturnTarget(
            study_context_token="ctx",
            platform_key="youtube",
            resource_token="",
            observed_monotonic_ns=1,
        )


# -- G: held previous browser evidence --------------------------------------


def test_g_held_previous_evidence_never_proves_a_return(quiet, frozen):
    """A held read proves the LAST resource; it must not release the lock."""

    context = quiet.look_at(UNREADABLE)
    assert context.browser_evidence.holding_previous_strong_evidence is True, (
        "the lab expected Browser to hold the previous strong read here"
    )
    assert context.browser_evidence.authoritative is True, (
        "a held read is still authoritative -- which is exactly why C6 must "
        "reject it explicitly"
    )
    assert quiet.exact(context, frozen) is False


# -- H: browser evidence unavailable / unsafe -------------------------------


def test_h_non_browser_foreground_never_proves_a_return(quiet, frozen):
    context = quiet.look_at(NOT_A_BROWSER)
    assert context.browser_evidence.authoritative is False
    assert quiet.exact(context, frozen) is False


# -- J: stale evidence ------------------------------------------------------


def test_j_stale_resource_intent_observation_never_proves_a_return(quiet, frozen):
    """Contract-level: if Resource Intent ever reports not-fresh, exact is False."""

    context = quiet.look_at(LECTURE)
    assert quiet.exact(context, frozen) is True

    stale = replace(
        context, resource_intent=replace(context.resource_intent, fresh=False)
    )
    assert quiet.exact(stale, frozen) is False, (
        "stale evidence must never prove presence"
    )


# -- K: wrong Study context token -------------------------------------------


def test_k_a_target_from_another_study_block_never_matches(quiet, frozen):
    """The right video under the wrong Study block is not this break's return."""

    context = quiet.look_at(LECTURE)
    foreign = freeze_target(context, study_context_token="SOME-OTHER-STUDY-CONTEXT")
    assert foreign.resource_token == frozen.resource_token
    assert quiet.exact(context, foreign) is False


# -- no target at all -------------------------------------------------------


def test_no_frozen_target_can_never_confirm(quiet):
    """Fail closed: no memory trace means no comparison, not a free pass."""

    context = quiet.look_at(LECTURE)
    assert quiet.exact(context, None) is False


# -- Q: independence from study_idle_allowed --------------------------------


def test_q_exact_return_does_not_depend_on_study_idle_allowed(quiet, frozen):
    """The forbidden nerve stays cut, and the new one still fires."""

    context = quiet.look_at(LECTURE)
    verdict = context.resource_intent.verdict

    assert verdict.study_idle_allowed is False, (
        "study_idle_allowed must remain False during an approved break"
    )
    assert verdict.classification is ResourceIntent.APPROVED_BREAK
    assert quiet.exact(context, frozen) is True, (
        "exact return must be proved by resource identity, not idle permission"
    )


# ---------------------------------------------------------------------------
# Tier 2 -- what Monitor actually hands to COSECANT during a real break
# ---------------------------------------------------------------------------


class _Spy:
    """Record every StudyReturnObservation without changing what COSECANT does."""

    def __init__(self, engine: Engine) -> None:
        self.seen: list = []
        self._real = engine.services.cosecant.observe_return
        engine.services.cosecant.observe_return = self._observe

    def _observe(self, observation):
        self.seen.append(observation)
        return self._real(observation)

    def after(self, marker: int) -> list:
        return [o for o in self.seen if o.observed_monotonic_ns > marker]

    def wait_for(self, engine: Engine, marker: int, *, count: int = 2) -> list:
        engine.wait_until(
            lambda: len(self.after(marker)) >= count,
            timeout=15,
            what=f"{count} return observations after the surface change",
        )
        return self.after(marker)


def _start_study(engine: Engine) -> None:
    engine.send(
        "study_prepare",
        subject="Neuroscience",
        task="basal ganglia",
        planned_seconds=3600,
        keywords=("direct", "indirect"),
        important_keywords=("basal ganglia",),
    )
    engine.send("study_action", action="START")
    engine.wait_until(
        lambda: engine.study().state.value == "ACTIVE",
        timeout=15,
        what="Study Mode to become ACTIVE",
    )


def _start_break(engine: Engine) -> None:
    engine.send("study_break", selected_break_seconds=60)
    engine.wait_until(
        lambda: engine.cosecant().state.value == "BREAK_ACTIVE",
        timeout=15,
        what="the approved break to start",
    )


@pytest.fixture()
def broken_engine():
    """A real engine inside a real, still-running approved break."""

    with Engine(surface=LECTURE, poll_seconds=0.2, fast_cosecant=True) as running:
        spy = _Spy(running)
        _start_study(running)
        _start_break(running)
        yield running, spy


def test_monitor_reports_exact_return_on_the_frozen_resource(broken_engine):
    """The end of W-2, measured where it actually matters."""

    engine, spy = broken_engine
    target = engine.cosecant().intended_return_target
    assert target is not None, "C5 must have frozen a return target"

    marker = time.monotonic_ns()
    engine.look_at(LECTURE)
    observations = spy.wait_for(engine, marker)

    assert any(o.exact_resource_confirmed for o in observations), (
        "Monitor never told COSECANT the user was on the exact frozen "
        "resource. This is W-2."
    )
    assert any(o.presence is StudyPresence.PRESENT for o in observations)
    assert any(o.proves_presence for o in observations), (
        "the observation must satisfy the COSECANT proves_presence contract"
    )


def test_monitor_reports_absence_on_a_different_video(broken_engine):
    engine, spy = broken_engine

    marker = time.monotonic_ns()
    engine.look_at(OTHER_LECTURE)
    observations = spy.wait_for(engine, marker)

    assert not any(o.exact_resource_confirmed for o in observations)
    assert not any(o.proves_presence for o in observations)


def test_monitor_reports_absence_on_entertainment(broken_engine):
    engine, spy = broken_engine

    marker = time.monotonic_ns()
    engine.look_at(INSTAGRAM)
    observations = spy.wait_for(engine, marker)

    assert not any(o.exact_resource_confirmed for o in observations)


def test_i_uncertain_resource_intent_keeps_uncertain_presence(broken_engine):
    """Uncertainty semantics survive C6, and never prove a return."""

    engine, spy = broken_engine
    coordinator = engine.coordinator

    marker = time.monotonic_ns()
    engine.look_at(NOT_A_BROWSER)
    observations = spy.wait_for(engine, marker)
    assert not any(o.exact_resource_confirmed for o in observations)

    # Production keeps Resource Intent in APPROVED_BREAK for the whole break,
    # so UNCERTAIN is asserted at the contract level: whenever Resource Intent
    # is uncertain, presence must stay UNCERTAIN rather than collapse to ABSENT.
    context = coordinator._classify_observation(engine.foreground.observe())
    uncertain = replace(
        context,
        resource_intent=replace(
            context.resource_intent,
            verdict=replace(
                context.resource_intent.verdict,
                classification=ResourceIntent.UNCERTAIN,
            ),
        ),
    )
    assert coordinator._presence_for(uncertain, exact=False) is StudyPresence.UNCERTAIN
    assert coordinator._presence_for(uncertain, exact=True) is StudyPresence.PRESENT


# ---------------------------------------------------------------------------
# Tier 3 -- the existing 3-second verifier, now that it is being fed
# ---------------------------------------------------------------------------


def _drive_to_final_lock(engine: Engine) -> None:
    _start_study(engine)
    _start_break(engine)
    engine.look_at(INSTAGRAM)
    engine.wait_until(
        lambda: engine.cosecant().state.value == "FINAL_LOCK",
        timeout=120,
        what="the escalation to reach FINAL_LOCK",
    )


def _begin_confirmation(engine: Engine) -> None:
    engine.look_at(LECTURE)
    engine.wait_until(
        lambda: engine.cosecant().state.value == "RETURN_CONFIRMING",
        timeout=15,
        what="the 3-second confirmation to start",
    )


@pytest.mark.slow
def test_l_exact_resource_for_less_than_three_seconds_does_not_confirm():
    """Confirmation starts, but two seconds is not three."""

    with Engine(surface=LECTURE, poll_seconds=0.2, fast_cosecant=True) as engine:
        _drive_to_final_lock(engine)
        _begin_confirmation(engine)

        snapshot = engine.cosecant()
        assert snapshot.return_confirmed is False
        assert snapshot.confirmation_elapsed_seconds < 3.0


@pytest.mark.slow
def test_n_switching_to_the_wrong_video_loses_the_confirmation():
    with Engine(surface=LECTURE, poll_seconds=0.2, fast_cosecant=True) as engine:
        _drive_to_final_lock(engine)
        _begin_confirmation(engine)

        engine.look_at(OTHER_LECTURE)
        engine.wait_until(
            lambda: engine.cosecant().state.value == "FINAL_LOCK",
            timeout=15,
            what="the confirmation to be lost",
        )
        assert engine.cosecant().return_confirmed is False


@pytest.mark.slow
def test_o_losing_browser_evidence_loses_the_confirmation():
    with Engine(surface=LECTURE, poll_seconds=0.2, fast_cosecant=True) as engine:
        _drive_to_final_lock(engine)
        _begin_confirmation(engine)

        engine.look_at(NOT_A_BROWSER)
        engine.wait_until(
            lambda: engine.cosecant().state.value == "FINAL_LOCK",
            timeout=15,
            what="the confirmation to be lost",
        )
        assert engine.cosecant().return_confirmed is False
