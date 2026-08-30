"""RED: terminal Study scope cancels only its exact active Study SINE episode."""

from __future__ import annotations

import queue
from types import MethodType, SimpleNamespace

import _lab  # noqa: F401 - installs the production tree on sys.path

from COSECANT_STUDY_MODE.study import StudyCompletionReason, StudyState
from CORE_ENGINE.monitor import WindowsMonitorCoordinator
from SINE.sine import SineAuthority, SinePhase, SinePolicy, SineStage


NS = 1_000_000_000
STUDY_TOKEN = "study-red-block:1"


def _candidate(*, study_mode: bool = True):
    return SimpleNamespace(
        candidate_uid=("red-study-candidate" if study_mode else "red-normal-candidate"),
        session_id=1,
        profile_type=("STUDY" if study_mode else "GENERAL"),
        evidence=SimpleNamespace(
            observed_monotonic_ns=1 * NS,
            dwell_seconds=300.0,
            threshold_seconds=300.0,
            study_context_token=(STUDY_TOKEN if study_mode else ""),
            resource_key="youtube:red-terminal",
            resource_observation_token="red-terminal-observation",
            surface_class="youtube_watch",
            browser_evidence_kind="certified_url",
            process_name="chrome",
            process_id=20,
            hwnd=10,
            platform_key="youtube",
        ),
    )


def _authority(*, study_mode: bool = True):
    clock = [1 * NS]
    sine = SineAuthority(
        policy=SinePolicy(
            stage_1_visible_seconds=3600.0,
            stage_2_delay_seconds=1.0,
            stage_2_visible_seconds=3600.0,
            stage_3_delay_seconds=1.0,
            stage_3_visible_seconds=3600.0,
        ),
        monotonic_ns=lambda: clock[0],
    )
    sine.start_session(
        session_id=1,
        profile_type=("STUDY" if study_mode else "GENERAL"),
    )
    assert sine.request_trigger(
        candidate=_candidate(study_mode=study_mode),
        operational_event_id=1,
        mirl_display_token=SimpleNamespace(),
    )
    sine.advance(now_monotonic_ns=clock[0])
    return sine, clock


def _show_current(sine: SineAuthority, clock: list[int], second: int) -> None:
    clock[0] = second * NS
    request_id = sine.live_view().popup_request_id
    assert request_id
    assert sine.popup_shown(
        request_id=request_id,
        shown_monotonic_ns=clock[0],
        popup_hwnd=8000 + second,
    )
    sine.advance(now_monotonic_ns=clock[0])


def _at_stage(stage: SineStage, *, study_mode: bool = True):
    sine, clock = _authority(study_mode=study_mode)
    _show_current(sine, clock, 2)
    if stage >= SineStage.SINE_2:
        clock[0] = 3 * NS
        sine.advance(now_monotonic_ns=clock[0])
        _show_current(sine, clock, 4)
    if stage >= SineStage.SINE_3:
        clock[0] = 5 * NS
        sine.advance(now_monotonic_ns=clock[0])
        _show_current(sine, clock, 6)
    assert sine.live_view().stage is stage
    return sine, clock


def _cancel(sine: SineAuthority, clock: list[int], *, reason="TARGET_REACHED"):
    clock[0] += 1
    accepted = sine.cancel_matching_study_episode(
        study_context_token=STUDY_TOKEN,
        occurred_monotonic_ns=clock[0],
        completion_reason=reason,
    )
    facts = sine.advance(now_monotonic_ns=clock[0])
    return accepted, facts


def test_target_reached_cancels_exact_study_sine1_closes_popup_and_never_schedules_sine2():
    sine, clock = _at_stage(SineStage.SINE_1)
    original = sine.live_view()

    accepted, facts = _cancel(sine, clock)

    assert accepted is True
    assert sine.live_view().phase is SinePhase.CANCELLED
    assert sine.live_view().episode_uid == original.episode_uid
    assert sine.live_view().candidate_uid == original.candidate_uid
    assert any(fact.kind == "SINE_POPUP_CLOSE_REQUESTED" for fact in facts)
    assert any(fact.kind == "SINE_EPISODE_CANCELLED" for fact in facts)
    assert not any(fact.kind == "SINE_EPISODE_RESOLVED" for fact in facts)
    later = sine.advance(now_monotonic_ns=10_000 * NS)
    assert not any(
        fact.kind == "SINE_POPUP_REQUESTED" and fact.stage == 2 for fact in later
    )


def test_target_reached_cancels_exact_study_sine2_and_never_schedules_sine3():
    sine, clock = _at_stage(SineStage.SINE_2)
    accepted, _facts = _cancel(sine, clock)
    assert accepted is True
    later = sine.advance(now_monotonic_ns=10_000 * NS)
    assert sine.live_view().phase is SinePhase.CANCELLED
    assert not any(
        fact.kind == "SINE_POPUP_REQUESTED" and fact.stage == 3 for fact in later
    )


def test_exact_study_scope_can_cancel_protected_red_without_weakening_normal_red():
    study_sine, study_clock = _at_stage(SineStage.SINE_3)
    assert study_sine.live_view().protected_red_active is True
    accepted, facts = _cancel(study_sine, study_clock)
    assert accepted is True
    assert study_sine.live_view().phase is SinePhase.CANCELLED
    assert study_sine.live_view().protected_red_active is False
    assert any(fact.kind == "SINE_EPISODE_CANCELLED" for fact in facts)

    normal_sine, normal_clock = _at_stage(SineStage.SINE_3, study_mode=False)
    original = normal_sine.live_view()
    accepted, facts = _cancel(normal_sine, normal_clock)
    assert accepted is True
    assert facts == ()
    assert normal_sine.live_view().phase is SinePhase.PROTECTED_RED
    assert normal_sine.live_view().episode_uid == original.episode_uid
    assert normal_sine.live_view().protected_red_active is True


def test_wrong_study_token_fails_closed_and_idempotent_replay_emits_no_duplicate():
    sine, clock = _at_stage(SineStage.SINE_1)
    original = sine.live_view()
    clock[0] += 1
    assert sine.cancel_matching_study_episode(
        study_context_token="study-other-block:9",
        occurred_monotonic_ns=clock[0],
        completion_reason="TARGET_REACHED",
    ) is False
    assert sine.live_view().phase is SinePhase.ACTIVE
    assert sine.live_view().episode_uid == original.episode_uid
    assert sine.advance(now_monotonic_ns=clock[0]) == ()

    accepted, facts = _cancel(sine, clock, reason="USER_COMPLETED")
    assert accepted is True
    assert sum(fact.kind == "SINE_EPISODE_CANCELLED" for fact in facts) == 1
    clock[0] += NS
    assert sine.cancel_matching_study_episode(
        study_context_token=STUDY_TOKEN,
        occurred_monotonic_ns=clock[0],
        completion_reason="USER_COMPLETED",
    ) is True
    assert sine.advance(now_monotonic_ns=clock[0]) == ()


def test_no_episode_is_harmless_and_normal_sine_is_untouched():
    empty = SineAuthority()
    empty.start_session(session_id=1, profile_type="STUDY")
    assert empty.cancel_matching_study_episode(
        study_context_token=STUDY_TOKEN,
        occurred_monotonic_ns=1,
        completion_reason="TARGET_REACHED",
    ) is True

    normal, clock = _at_stage(SineStage.SINE_1, study_mode=False)
    original = normal.live_view()
    accepted, facts = _cancel(normal, clock)
    assert accepted is True
    assert facts == ()
    assert normal.live_view().phase is SinePhase.ACTIVE
    assert normal.live_view().episode_uid == original.episode_uid


class _SineTerminalRecorder:
    def __init__(self, accepted: bool = True):
        self.accepted = accepted
        self.calls = []

    def cancel_matching_study_episode(self, **payload):
        self.calls.append(payload)
        return self.accepted


class _Storage:
    def __init__(self):
        self.rows = []

    def record_study_snapshot(self, **payload):
        self.rows.append(payload)
        return True


class _Intent:
    def __init__(self):
        self.retired = 0

    def retire_study_context(self):
        self.retired += 1


def _snapshot(reason: StudyCompletionReason, *, token=STUDY_TOKEN, timestamp=9 * NS):
    return SimpleNamespace(
        state=StudyState.COMPLETED,
        completion_reason=reason,
        block_id="study-red-block",
        generation=1,
        context_token=token,
        published_monotonic_ns=timestamp,
    )


def _monitor(sine=None):
    monitor = WindowsMonitorCoordinator.__new__(WindowsMonitorCoordinator)
    monitor.session_id = 1
    monitor.telemetry_queue = queue.Queue()
    monitor._last_study_completion_signature = None
    monitor._break_eligible_study_target = None
    monitor.services = SimpleNamespace(
        sine=sine or _SineTerminalRecorder(),
        storage=_Storage(),
        resource_intent=_Intent(),
    )
    monitor._reconcile_break_target_with_study = MethodType(
        lambda self, snapshot: None,
        monitor,
    )
    return monitor


def test_automatic_target_reached_uses_canonical_snapshot_identity_before_marking_handled():
    monitor = _monitor()
    snapshot = _snapshot(StudyCompletionReason.TARGET_REACHED)

    monitor._sync_study_context_after_advance(snapshot)

    assert monitor.services.sine.calls == [{
        "study_context_token": STUDY_TOKEN,
        "occurred_monotonic_ns": 9 * NS,
        "completion_reason": "TARGET_REACHED",
    }]
    assert monitor.services.resource_intent.retired == 1
    assert monitor.services.storage.rows[0]["action"] == "TARGET_REACHED"
    assert monitor._last_study_completion_signature == ("study-red-block", 1)

    monitor._sync_study_context_after_advance(snapshot)
    assert len(monitor.services.sine.calls) == 1


def test_manual_complete_uses_same_terminal_helper_and_exact_user_completed_reason():
    monitor = _monitor()
    monitor._sync_study_context_with_resource_intent = MethodType(
        lambda self, snapshot: self.services.resource_intent.retire_study_context(),
        monitor,
    )
    snapshot = _snapshot(StudyCompletionReason.USER_COMPLETED, timestamp=11 * NS)

    monitor._handle_study_result(
        "COMPLETE",
        SimpleNamespace(accepted=True, snapshot=snapshot, message="Study completed"),
    )

    assert monitor.services.sine.calls == [{
        "study_context_token": STUDY_TOKEN,
        "occurred_monotonic_ns": 11 * NS,
        "completion_reason": "USER_COMPLETED",
    }]
    assert monitor.services.storage.rows[0]["action"] == "COMPLETE"
    assert monitor._last_study_completion_signature == ("study-red-block", 1)


def test_safe_shutdown_is_not_expanded_into_the_red_terminal_nerve():
    monitor = _monitor()
    assert monitor._terminate_matching_study_sine(
        _snapshot(StudyCompletionReason.SAFE_SHUTDOWN)
    ) is True
    assert monitor.services.sine.calls == []
