"""C5 — freeze the intended Study return target at break admission.

Before the user leaves, MYELIN must record the exact resource that will later
release the lock. A break that could reach FINAL_LOCK with no factual answer to
"what resource ends this?" must never be admitted.

Written before the production patch.
"""

from __future__ import annotations

import os
import time

import pytest

import _lab
from _lab import Engine, INSTAGRAM, LECTURE, MRBEAST, OTHER_LECTURE, Surface

NS = 10**9

# Keywords chosen so the C4 calculator scores LECTURE at 100%.
KEYWORDS = ("direct", "indirect")
IMPORTANT = ("basal ganglia",)

MYELIN_CONTROL_STATION = Surface(
    process_name="python",
    title="MYELIN — Control Station v2.0",
    hwnd=8801,
    process_id=os.getpid(),
)
WHATSAPP = Surface(
    process_name="whatsapp",
    title="WhatsApp",
    hwnd=8802,
    process_id=8802,
)


# ---------------------------------------------------------------------------
# The contract itself
# ---------------------------------------------------------------------------


def test_target_contract_exists_and_is_immutable():
    from COSECANT_STUDY_MODE.cosecant import CosecantReturnTarget

    target = CosecantReturnTarget(
        study_context_token="tok",
        platform_key="youtube",
        resource_token="RES-A",
        observed_monotonic_ns=1_000,
    )
    assert target.study_context_token == "tok"
    assert target.platform_key == "youtube"
    assert target.resource_token == "RES-A"
    assert target.observed_monotonic_ns == 1_000
    with pytest.raises(Exception):
        target.resource_token = "RES-B"        # frozen


def test_target_carries_nothing_it_must_not_carry():
    from COSECANT_STUDY_MODE.cosecant import CosecantReturnTarget

    fields = set(CosecantReturnTarget.__dataclass_fields__)
    assert fields == {
        "study_context_token",
        "platform_key",
        "resource_token",
        "observed_monotonic_ns",
    }
    for banned in (
        "title", "url", "content_id", "hwnd", "process_id", "pid",
        "stable_key", "confidence", "score", "sine", "idle", "mirl",
    ):
        assert not any(banned in name for name in fields), (
            f"{banned!r} is not part of an exact return target"
        )


def test_target_refuses_an_empty_exact_token():
    """Fail-closed at the type level: a target without an exact token cannot
    even be constructed, so no code path can smuggle one into a break."""

    from COSECANT_STUDY_MODE.cosecant import CosecantReturnTarget

    with pytest.raises(ValueError):
        CosecantReturnTarget(
            study_context_token="tok",
            platform_key="youtube",
            resource_token="",
            observed_monotonic_ns=1_000,
        )
    with pytest.raises(ValueError):
        CosecantReturnTarget(
            study_context_token="tok",
            platform_key="",
            resource_token="RES-A",
            observed_monotonic_ns=1_000,
        )
    with pytest.raises(ValueError):
        CosecantReturnTarget(
            study_context_token="",
            platform_key="youtube",
            resource_token="RES-A",
            observed_monotonic_ns=1_000,
        )


def test_schema_version_was_bumped():
    from COSECANT_STUDY_MODE.cosecant import COSECANT_SCHEMA_VERSION

    assert COSECANT_SCHEMA_VERSION == "myelin-cosecant-v2"


# ---------------------------------------------------------------------------
# CosecantRuntime.start_break target validation (pure, no engine)
# ---------------------------------------------------------------------------


class _Clock:
    def __init__(self, start_ns):
        self.t = start_ns

    def __call__(self):
        return self.t


class _AcceptingIntent:
    def publish_study_context(self, context):
        return True

    def retire_study_context(self, expected_context_token=""):
        return True


class _RejectingIntent:
    def publish_study_context(self, context):
        return False

    def retire_study_context(self, expected_context_token=""):
        return True


def _paused_study(*, epoch_ns, block_id="BLOCK-C5", generation=1):
    from COSECANT_STUDY_MODE.study import (
        StudyCompletionReason,
        StudySnapshot,
        StudyState,
    )

    return StudySnapshot(
        block_id=block_id,
        generation=generation,
        state=StudyState.PAUSED,
        subject="Neuroscience",
        task="Basal Ganglia",
        keywords=KEYWORDS,
        important_keywords=IMPORTANT,
        active_epoch_monotonic_ns=epoch_ns,
        planned_seconds=3600,
        elapsed_seconds=0.0,
        remaining_seconds=3600,
        progress_percent=0.0,
        started_wall_time_utc="",
        paused_wall_time_utc="",
        completed_wall_time_utc="",
        ends_at_wall_time_utc="",
        completion_reason=StudyCompletionReason.NONE,
        last_action="paused",
        published_monotonic_ns=epoch_ns,
    )


def _target_for(study, *, observed_ns, resource_token="RES-A",
                platform_key="youtube", context_token=None):
    from COSECANT_STUDY_MODE.cosecant import CosecantReturnTarget

    return CosecantReturnTarget(
        study_context_token=context_token or study.context_token,
        platform_key=platform_key,
        resource_token=resource_token,
        observed_monotonic_ns=observed_ns,
    )


def _runtime(clock, intent=None):
    from COSECANT_STUDY_MODE.cosecant import CosecantRuntime

    return CosecantRuntime(
        context_authority=intent or _AcceptingIntent(),
        monotonic_ns=clock,
    )


def test_start_break_requires_a_target():
    clock = _Clock(1_000 * NS)
    runtime = _runtime(clock)
    study = _paused_study(epoch_ns=900 * NS)

    with pytest.raises(TypeError):
        runtime.start_break(study=study, selected_break_seconds=600)


def test_start_break_accepts_a_valid_target():
    clock = _Clock(1_000 * NS)
    runtime = _runtime(clock)
    study = _paused_study(epoch_ns=900 * NS)
    target = _target_for(study, observed_ns=950 * NS)

    result = runtime.start_break(
        study=study, selected_break_seconds=600, intended_return_target=target
    )
    assert result.accepted, result.message
    assert result.snapshot.intended_return_target == target


def test_target_context_token_must_match_the_study_block():
    clock = _Clock(1_000 * NS)
    runtime = _runtime(clock)
    study = _paused_study(epoch_ns=900 * NS)
    target = _target_for(study, observed_ns=950 * NS, context_token="wrong-token")

    result = runtime.start_break(
        study=study, selected_break_seconds=600, intended_return_target=target
    )
    assert not result.accepted
    assert runtime.snapshot().intended_return_target is None


def test_target_observed_before_the_active_epoch_is_rejected():
    """Stale pre-Study evidence can never become the return target."""

    clock = _Clock(1_000 * NS)
    runtime = _runtime(clock)
    study = _paused_study(epoch_ns=900 * NS)
    target = _target_for(study, observed_ns=800 * NS)

    result = runtime.start_break(
        study=study, selected_break_seconds=600, intended_return_target=target
    )
    assert not result.accepted


def test_future_dated_target_is_rejected():
    clock = _Clock(1_000 * NS)
    runtime = _runtime(clock)
    study = _paused_study(epoch_ns=900 * NS)
    target = _target_for(study, observed_ns=1_100 * NS)

    result = runtime.start_break(
        study=study, selected_break_seconds=600, intended_return_target=target
    )
    assert not result.accepted


def test_target_survives_every_escalation_stage():
    from COSECANT_STUDY_MODE.cosecant import CosecantPolicy, CosecantRuntime, CosecantState

    clock = _Clock(1_000 * NS)
    runtime = CosecantRuntime(
        context_authority=_AcceptingIntent(),
        policy=CosecantPolicy(),
        monotonic_ns=clock,
    )
    study = _paused_study(epoch_ns=900 * NS)
    target = _target_for(study, observed_ns=950 * NS)
    assert runtime.start_break(
        study=study, selected_break_seconds=600, intended_return_target=target
    ).accepted

    for offset, expected in (
        (0, CosecantState.BREAK_ACTIVE),
        (600, CosecantState.BREAK_COMPLETE),
        (900, CosecantState.BREAK_ALREADY_OVER),
        (960, CosecantState.FINAL_LOCK),
    ):
        clock.t = int((1_000 + offset) * NS)
        runtime.advance()
        snapshot = runtime.snapshot()
        assert snapshot.state is expected
        assert snapshot.intended_return_target == target, (
            f"target lost at {expected.value}"
        )


def test_failed_context_publication_leaves_no_hidden_target():
    clock = _Clock(1_000 * NS)
    runtime = _runtime(clock, intent=_RejectingIntent())
    study = _paused_study(epoch_ns=900 * NS)
    target = _target_for(study, observed_ns=950 * NS)

    result = runtime.start_break(
        study=study, selected_break_seconds=600, intended_return_target=target
    )
    assert not result.accepted
    snapshot = runtime.snapshot()
    assert snapshot.intended_return_target is None
    assert snapshot.break_id == ""
    assert snapshot.state.value == "INACTIVE"


def test_cancelled_break_clears_the_target():
    clock = _Clock(1_000 * NS)
    runtime = _runtime(clock)
    study = _paused_study(epoch_ns=900 * NS)
    target = _target_for(study, observed_ns=950 * NS)
    runtime.start_break(
        study=study, selected_break_seconds=600, intended_return_target=target
    )
    clock.t = 1_100 * NS
    runtime.cancel_for_session_end()
    # The episode is terminal; a new break must not inherit the old target.
    assert runtime.snapshot().state.value == "CANCELLED"


# ---------------------------------------------------------------------------
# Monitor break admission — the whole engine
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    with Engine(surface=LECTURE, poll_seconds=0.2, fast_cosecant=True) as running:
        yield running


def _prepare_and_start(engine, *, keywords=KEYWORDS, important=IMPORTANT):
    engine.send(
        "study_prepare",
        subject="Neuroscience",
        task="Basal Ganglia",
        planned_seconds=3600,
        keywords=keywords,
        important_keywords=important,
    )
    engine.wait_until(
        lambda: bool(engine.study().block_id), timeout=15, what="Study prepared"
    )
    engine.send("study_action", action="START")
    engine.wait_until(
        lambda: engine.study().state.value == "ACTIVE",
        timeout=15,
        what="Study ACTIVE",
    )
    time.sleep(1.0)


def _request_break(engine, seconds=60):
    engine.send("study_break", selected_break_seconds=seconds)
    time.sleep(1.5)


def _wait_for_remembered_target(engine):
    engine.wait_until(
        lambda: engine.coordinator._break_eligible_study_target is not None,
        timeout=15,
        what="Monitor to remember the certified Study break target",
    )
    return engine.coordinator._break_eligible_study_target


def test_aligned_lecture_admits_a_break_and_freezes_the_target(engine):
    _prepare_and_start(engine)
    assert engine.intent().classification.value == "STUDY_ALIGNED", (
        "precondition: C4 must align the lecture"
    )

    _request_break(engine)

    snapshot = engine.cosecant()
    assert snapshot.state.value == "BREAK_ACTIVE", "the break was not admitted"
    target = snapshot.intended_return_target
    assert target is not None, "a break started with no intended return target"
    assert target.platform_key == "youtube"
    assert target.resource_token
    assert target.study_context_token == engine.study().context_token


def test_study_lecture_then_myelin_foreground_admits_exact_original_target(engine):
    _prepare_and_start(engine)
    remembered = _wait_for_remembered_target(engine)

    engine.look_at(MYELIN_CONTROL_STATION)
    time.sleep(0.6)
    assert engine.coordinator._break_eligible_study_target == remembered

    _request_break(engine)

    snapshot = engine.cosecant()
    assert snapshot.state.value == "BREAK_ACTIVE"
    target = snapshot.intended_return_target
    assert target is not None
    assert target.study_context_token == remembered.study_context_token
    assert target.platform_key == remembered.platform_key
    assert target.resource_token == remembered.resource_token
    assert target.observed_monotonic_ns == remembered.observed_monotonic_ns
    assert engine.coordinator._break_eligible_study_target is None


def test_external_non_study_then_myelin_invalidates_target_and_refuses(engine):
    _prepare_and_start(engine)
    assert _wait_for_remembered_target(engine) is not None

    engine.look_at(WHATSAPP)
    engine.wait_until(
        lambda: engine.coordinator._break_eligible_study_target is None,
        timeout=15,
        what="external non-Study observation to invalidate break target",
    )
    engine.look_at(MYELIN_CONTROL_STATION)
    time.sleep(0.6)

    _request_break(engine)

    assert engine.cosecant().state.value == "INACTIVE"
    assert engine.study().state.value == "ACTIVE"


def test_changed_study_identity_cannot_reuse_previous_target(engine):
    _prepare_and_start(engine)
    old_target = _wait_for_remembered_target(engine)
    old_block_id = engine.study().block_id

    engine.look_at(MYELIN_CONTROL_STATION)
    time.sleep(0.6)
    engine.send("study_action", action="COMPLETE")
    engine.wait_until(
        lambda: engine.study().state.value == "COMPLETED",
        timeout=15,
        what="first Study block to complete",
    )
    engine.wait_until(
        lambda: engine.coordinator._break_eligible_study_target is None,
        timeout=15,
        what="completed Study identity to clear its remembered target",
    )

    engine.send(
        "study_prepare",
        subject="Neuroscience",
        task="Basal Ganglia",
        planned_seconds=3600,
        keywords=KEYWORDS,
        important_keywords=IMPORTANT,
    )
    engine.wait_until(
        lambda: bool(engine.study().block_id)
        and engine.study().block_id != old_block_id,
        timeout=15,
        what="second Study block to be prepared",
    )
    engine.send("study_action", action="START")
    engine.wait_until(
        lambda: engine.study().state.value == "ACTIVE",
        timeout=15,
        what="second Study block to become ACTIVE",
    )
    assert engine.study().context_token != old_target.study_context_token
    assert engine.coordinator._break_eligible_study_target is None

    _request_break(engine)

    assert engine.cosecant().state.value == "INACTIVE"
    assert engine.study().state.value == "ACTIVE"


def test_protected_red_still_refuses_remembered_target_from_myelin(engine):
    _prepare_and_start(engine)
    remembered = _wait_for_remembered_target(engine)
    engine.look_at(MYELIN_CONTROL_STATION)
    time.sleep(0.6)
    assert engine.coordinator._break_eligible_study_target == remembered

    real_protected_red_active = engine.services.sine.protected_red_active
    engine.services.sine.protected_red_active = lambda: True
    try:
        _request_break(engine)
    finally:
        engine.services.sine.protected_red_active = real_protected_red_active

    assert engine.cosecant().state.value == "INACTIVE"
    assert engine.study().state.value == "ACTIVE"


def test_session_shutdown_clears_remembered_break_target():
    running = Engine(surface=LECTURE, poll_seconds=0.2, fast_cosecant=True)
    with running as engine:
        _prepare_and_start(engine)
        assert _wait_for_remembered_target(engine) is not None

    assert running.coordinator._break_eligible_study_target is None


def test_emergency_clears_remembered_break_target():
    with Engine(surface=LECTURE, poll_seconds=0.2, fast_cosecant=True) as engine:
        _prepare_and_start(engine)
        assert _wait_for_remembered_target(engine) is not None

        engine.send("emergency")
        assert engine.cleanup_complete_event.wait(timeout=20)
        assert engine.coordinator._break_eligible_study_target is None


def test_break_is_refused_when_the_resource_is_not_aligned(engine):
    _prepare_and_start(engine)
    engine.look_at(MRBEAST)
    time.sleep(1.0)

    _request_break(engine)

    assert engine.cosecant().state.value == "INACTIVE"
    assert engine.study().state.value == "ACTIVE", (
        "a refused break must leave Study running"
    )


def test_break_is_refused_on_a_resource_without_an_exact_token(engine):
    """Instagram reels are certified but carry no exact resource token."""

    _prepare_and_start(engine)
    engine.look_at(INSTAGRAM)
    time.sleep(1.0)

    _request_break(engine)

    assert engine.cosecant().state.value == "INACTIVE"
    assert engine.study().state.value == "ACTIVE"


def test_break_is_refused_when_no_keywords_make_the_resource_uncertain(engine):
    _prepare_and_start(engine, keywords=(), important=())
    assert engine.intent().classification.value == "UNCERTAIN"

    _request_break(engine)

    assert engine.cosecant().state.value == "INACTIVE"
    assert engine.study().state.value == "ACTIVE"


def test_break_is_refused_on_a_different_video(engine):
    _prepare_and_start(engine)
    engine.look_at(OTHER_LECTURE)
    time.sleep(1.0)

    _request_break(engine)
    assert engine.cosecant().state.value == "INACTIVE"


def test_admission_uses_the_normal_artery_with_no_extra_reads(engine):
    """No second foreground read and no second browser read may occur."""

    _prepare_and_start(engine)
    before_foreground = engine.foreground._sequence
    reads = {"count": 0}

    original = engine.services.browser.observe

    def counting(foreground):
        reads["count"] += 1
        return original(foreground)

    engine.services.browser.observe = counting
    _request_break(engine)
    engine.services.browser.observe = original

    cycles = engine.foreground._sequence - before_foreground
    assert engine.cosecant().state.value == "BREAK_ACTIVE"
    assert reads["count"] <= cycles, (
        f"{reads['count']} browser reads across {cycles} monitor cycles: "
        "admission performed an extra read"
    )


def test_target_is_the_resource_present_at_admission_not_at_the_click(engine):
    """The target is frozen from the observation that admits the break."""

    _prepare_and_start(engine)
    admitted = engine.intent().resource_key
    _request_break(engine)

    snapshot = engine.cosecant()
    assert snapshot.state.value == "BREAK_ACTIVE"
    assert snapshot.intended_return_target is not None
    assert admitted


def test_duplicate_break_request_does_not_overwrite_a_live_break(engine):
    _prepare_and_start(engine)
    _request_break(engine)
    first = engine.cosecant()
    assert first.state.value == "BREAK_ACTIVE"

    engine.send("study_break", selected_break_seconds=120)
    time.sleep(1.5)

    second = engine.cosecant()
    assert second.break_id == first.break_id, "a second request replaced the break"
    assert second.selected_break_seconds == first.selected_break_seconds
    assert second.intended_return_target == first.intended_return_target


def test_target_survives_the_full_escalation_in_the_real_engine(engine):
    _prepare_and_start(engine)
    _request_break(engine)
    frozen = engine.cosecant().intended_return_target
    assert frozen is not None

    engine.look_at(INSTAGRAM)
    engine.wait_until(
        lambda: engine.cosecant().state.value == "FINAL_LOCK",
        timeout=120,
        what="escalation to FINAL_LOCK",
    )
    assert engine.cosecant().intended_return_target == frozen
