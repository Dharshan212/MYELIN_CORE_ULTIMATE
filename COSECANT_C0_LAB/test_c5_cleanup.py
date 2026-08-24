"""C5 freeze cleanup — atomicity, fail-closed corruption guards, contracts.

These are corruption tests. Constructing deliberately inconsistent organ
outputs is the point: a fail-closed gate can only be proved by feeding it the
state it is supposed to refuse.
"""

from __future__ import annotations

import dataclasses
import time

import pytest

import _lab
from _lab import Engine, LECTURE

ALIGNING_KEYWORDS = ("direct", "indirect")
ALIGNING_IMPORTANT = ("basal ganglia",)


@pytest.fixture()
def engine():
    with Engine(surface=LECTURE, poll_seconds=0.2, fast_cosecant=True) as running:
        yield running


def _start_aligned_study(engine):
    engine.send(
        "study_prepare",
        subject="Neuroscience",
        task="Basal Ganglia",
        planned_seconds=3600,
        keywords=ALIGNING_KEYWORDS,
        important_keywords=ALIGNING_IMPORTANT,
    )
    engine.wait_until(
        lambda: bool(engine.study().block_id), timeout=15, what="Study prepared"
    )
    engine.send("study_action", action="START")
    engine.wait_until(
        lambda: engine.study().state.value == "ACTIVE", timeout=15, what="ACTIVE"
    )
    time.sleep(1.0)
    assert engine.intent().classification.value == "STUDY_ALIGNED"


# ---------------------------------------------------------------------------
# 2 + 3 — break admission is a transaction
# ---------------------------------------------------------------------------


def test_refused_break_context_rolls_study_back_to_active(engine):
    """RI rejects the BREAK context -> COSECANT rejects -> Study runs again.

    SUCCESS  = PAUSED + BREAK_ACTIVE
    FAILURE  = ACTIVE  + no break, no target

    Anything else leaves the user paused with no break, which silently costs
    them their session.
    """

    _start_aligned_study(engine)

    intent = engine.services.resource_intent
    original_publish = intent.publish_study_context

    def reject_break_contexts(context):
        if context.display_state == "BREAK":
            return False
        return original_publish(context)

    intent.publish_study_context = reject_break_contexts
    try:
        engine.send("study_break", selected_break_seconds=60)
        time.sleep(2.0)
    finally:
        intent.publish_study_context = original_publish

    cosecant = engine.cosecant()
    assert cosecant.state.value == "INACTIVE", (
        "a refused break-context publication left a live break"
    )
    assert cosecant.intended_return_target is None, (
        "a refused break left a hidden return target"
    )
    assert cosecant.break_id == ""

    engine.wait_until(
        lambda: engine.study().state.value == "ACTIVE",
        timeout=15,
        what="Study to roll back to ACTIVE",
    )


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_failed_rollback_resume_raises_rather_than_stranding_study(engine):
    """If the rollback itself fails, that is a degraded state, not a shrug.

    The RuntimeError is raised on the monitor thread on purpose, so pytest's
    unhandled-thread-exception warning is the test SUCCEEDING and is filtered
    rather than suppressed at source.
    """

    _start_aligned_study(engine)

    intent = engine.services.resource_intent
    original_publish = intent.publish_study_context
    original_resume = engine.services.study.resume

    class _Rejected:
        accepted = False
        message = "synthetic resume failure"
        snapshot = None

    def reject_break_contexts(context):
        if context.display_state == "BREAK":
            return False
        return original_publish(context)

    intent.publish_study_context = reject_break_contexts
    engine.services.study.resume = lambda: _Rejected()
    try:
        engine.send("study_break", selected_break_seconds=60)
        # The monitor thread must die loudly rather than continue with Study
        # stranded in PAUSED and no break to release it.
        engine.wait_until(
            lambda: engine.loop_stopped_event.is_set(),
            timeout=20,
            what="the monitor loop to stop on an impossible rollback",
        )
    finally:
        intent.publish_study_context = original_publish
        engine.services.study.resume = original_resume


# ---------------------------------------------------------------------------
# 4 — fail-closed corruption guards on the admission gate
# ---------------------------------------------------------------------------


def _live_context(engine):
    """One real MonitorContext built through the normal artery."""

    observation = engine.foreground.observe()
    return engine.coordinator._classify_observation(observation)


def _refusal(engine, context) -> str:
    return engine.coordinator._break_admission_refusal(context)


def test_a_healthy_observation_is_admitted(engine):
    """Control: the same construction must admit when nothing is corrupted."""

    _start_aligned_study(engine)
    assert _refusal(engine, _live_context(engine)) == ""


def test_case_6_held_previous_browser_evidence_refuses_the_break(engine):
    """A held read proves the LAST resource, never the current one."""

    _start_aligned_study(engine)
    context = _live_context(engine)
    assert context.browser_evidence.authoritative is True

    held = dataclasses.replace(
        context.browser_evidence, holding_previous_strong_evidence=True
    )
    assert held.authoritative is True, (
        "precondition: a held read still reports authoritative, which is "
        "exactly why the gate needs its own check"
    )

    refusal = _refusal(engine, dataclasses.replace(context, browser_evidence=held))
    assert refusal, "a held browser read was accepted as a return target"
    assert "held" in refusal.lower()


def test_case_8_browser_and_resource_intent_token_disagreement_refuses(engine):
    """Two organs disagreeing about the resource is never a valid target."""

    _start_aligned_study(engine)
    context = _live_context(engine)
    real_token = context.browser_evidence.evidence.resource_token
    assert real_token

    forged = dataclasses.replace(
        context.browser_evidence.evidence,
        resource_token=real_token[::-1] + "X",
    )
    disagreeing = dataclasses.replace(context.browser_evidence, evidence=forged)

    refusal = _refusal(
        engine, dataclasses.replace(context, browser_evidence=disagreeing)
    )
    assert refusal, "a Browser/Resource Intent disagreement was accepted"
    assert "resource" in refusal.lower()


def test_case_8b_platform_disagreement_refuses(engine):
    _start_aligned_study(engine)
    context = _live_context(engine)

    forged = dataclasses.replace(
        context.browser_evidence.evidence, platform_key="not-youtube"
    )
    disagreeing = dataclasses.replace(context.browser_evidence, evidence=forged)

    refusal = _refusal(
        engine, dataclasses.replace(context, browser_evidence=disagreeing)
    )
    assert refusal
    assert "platform" in refusal.lower()


def test_an_emptied_browser_token_refuses_the_break(engine):
    """Fail-closed: a route that cannot prove an exact resource founds nothing."""

    _start_aligned_study(engine)
    context = _live_context(engine)

    forged = dataclasses.replace(
        context.browser_evidence.evidence, resource_token=""
    )
    stripped = dataclasses.replace(context.browser_evidence, evidence=forged)

    refusal = _refusal(engine, dataclasses.replace(context, browser_evidence=stripped))
    assert refusal
    assert "exact identity" in refusal.lower()


# ---------------------------------------------------------------------------
# 5 + 6 — contract cleanup
# ---------------------------------------------------------------------------


def test_monitor_protocol_declares_the_real_start_break_contract():
    """The declared nerve contract must equal the actual organ contract."""

    import inspect

    from CORE_ENGINE.monitor import CosecantAuthority

    declared = set(inspect.signature(CosecantAuthority.start_break).parameters)
    assert "intended_return_target" in declared, (
        "Monitor's CosecantAuthority Protocol still declares the pre-C5 "
        "start_break signature"
    )

    from COSECANT_STUDY_MODE.cosecant import CosecantRuntime

    actual = set(inspect.signature(CosecantRuntime.start_break).parameters)
    assert declared - {"self"} == actual - {"self"}, (
        f"declared {sorted(declared)} != actual {sorted(actual)}"
    )


def test_target_exposes_no_comparison_api_yet():
    """C5 stores the target. C6 decides how it is compared."""

    from COSECANT_STUDY_MODE.cosecant import CosecantReturnTarget

    assert not hasattr(CosecantReturnTarget, "matches"), (
        "the comparison valve belongs to C6, after its own source analysis"
    )


def test_target_still_fails_closed_on_empty_identity():
    """Removing matches() must not weaken the type's own guarantee."""

    from COSECANT_STUDY_MODE.cosecant import CosecantReturnTarget

    for bad in ({"resource_token": ""}, {"platform_key": ""},
                {"study_context_token": ""}):
        fields = {
            "study_context_token": "tok",
            "platform_key": "youtube",
            "resource_token": "RES-A",
            "observed_monotonic_ns": 1_000,
        }
        fields.update(bad)
        with pytest.raises(ValueError):
            CosecantReturnTarget(**fields)
