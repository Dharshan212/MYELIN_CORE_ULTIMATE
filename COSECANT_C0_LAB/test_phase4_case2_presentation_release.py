"""Phase 4 Case 2: MIRL return entry withholds SINE presentation only."""

from __future__ import annotations

import queue
from types import MethodType, SimpleNamespace

import pytest

import _lab  # noqa: F401 - installs the production tree on sys.path

from CORE_ENGINE.monitor import WindowsMonitorCoordinator
from SINE.sine import (
    PopupState,
    SineAuthority,
    SinePhase,
    SinePolicy,
    SineStage,
)


NS = 1_000_000_000


def _candidate(
    uid: str = "phase4-study-candidate",
    *,
    study_mode: bool = True,
):
    return SimpleNamespace(
        candidate_uid=uid,
        session_id=1,
        profile_type="STUDY" if study_mode else "GENERAL",
        evidence=SimpleNamespace(
            observed_monotonic_ns=1 * NS,
            dwell_seconds=300.0,
            threshold_seconds=300.0,
            study_context_token="study-block-phase4:1" if study_mode else "",
            resource_key="youtube:study-distraction",
            resource_observation_token="study-observation-1",
            surface_class="youtube_watch",
            browser_evidence_kind="certified_url",
            process_name="chrome",
            process_id=20,
            hwnd=10,
            platform_key="youtube",
        ),
    )


def _authority(
    *,
    stage_2_delay: float = 1.0,
    stage_3_delay: float = 1.0,
    study_mode: bool = True,
):
    clock = [1 * NS]
    sine = SineAuthority(
        policy=SinePolicy(
            stage_1_visible_seconds=3600.0,
            stage_2_delay_seconds=stage_2_delay,
            stage_2_visible_seconds=3600.0,
            stage_3_delay_seconds=stage_3_delay,
            stage_3_visible_seconds=3600.0,
        ),
        monotonic_ns=lambda: clock[0],
    )
    sine.start_session(
        session_id=1,
        profile_type="STUDY" if study_mode else "GENERAL",
    )
    assert sine.request_trigger(
        candidate=_candidate(study_mode=study_mode),
        operational_event_id=1,
        mirl_display_token=SimpleNamespace(),
    )
    sine.advance(now_monotonic_ns=clock[0])
    return sine, clock


def _show_current(sine: SineAuthority, clock: list[int], second: int):
    clock[0] = second * NS
    request_id = sine.live_view().popup_request_id
    assert request_id
    assert sine.popup_shown(
        request_id=request_id,
        shown_monotonic_ns=clock[0],
        popup_hwnd=9000 + second,
    )
    sine.advance(now_monotonic_ns=clock[0])
    return request_id


def _protected_red(*, study_mode: bool = True):
    sine, clock = _authority(study_mode=study_mode)
    _show_current(sine, clock, 2)
    clock[0] = 3 * NS
    sine.advance(now_monotonic_ns=clock[0])
    _show_current(sine, clock, 4)
    clock[0] = 5 * NS
    sine.advance(now_monotonic_ns=clock[0])
    request_id = _show_current(sine, clock, 6)
    assert sine.live_view().phase is SinePhase.PROTECTED_RED
    return sine, clock, request_id


def _normal_stage(stage: SineStage):
    sine, clock = _authority(
        study_mode=False,
        stage_2_delay=1.0 if stage >= SineStage.SINE_2 else 100.0,
        stage_3_delay=1.0 if stage >= SineStage.SINE_3 else 100.0,
    )
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


def test_normal_sine_three_return_entry_closes_only_its_surface():
    sine, clock, request_id = _protected_red(study_mode=False)
    before = sine.live_view()

    clock[0] = 16 * NS
    assert sine.withhold_presentation_for_verified_return_entry(
        candidate_uid=before.candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl_return_verified",
    )
    facts = sine.advance(now_monotonic_ns=clock[0])
    assert "SINE_POPUP_CLOSE_REQUESTED" in {fact.kind for fact in facts}

    held = sine.live_view()
    assert held.episode_uid == before.episode_uid
    assert held.phase is SinePhase.PROTECTED_RED
    assert held.protected_red_active is True
    assert held.presentation_withheld_for_recovery is True
    assert held.popup_state is PopupState.CLOSE_REQUESTED

    clock[0] = 17 * NS
    assert sine.popup_closed(
        request_id=request_id,
        reason="mirl_return_entry_verified",
        occurred_monotonic_ns=clock[0],
    )
    sine.advance(now_monotonic_ns=clock[0])
    closed = sine.live_view()
    assert closed.episode_uid == before.episode_uid
    assert closed.phase is SinePhase.PROTECTED_RED
    assert closed.protected_red_active is True
    assert closed.popup_state is PopupState.CLOSED


def test_normal_sine_three_relapse_restores_same_red_episode_not_sine_one():
    sine, clock, request_id = _protected_red(study_mode=False)
    original = sine.live_view()
    clock[0] = 16 * NS
    assert sine.withhold_presentation_for_verified_return_entry(
        candidate_uid=original.candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl_return_verified",
    )
    sine.advance(now_monotonic_ns=clock[0])
    clock[0] = 17 * NS
    assert sine.popup_closed(
        request_id=request_id,
        reason="mirl_return_entry_verified",
        occurred_monotonic_ns=clock[0],
    )
    sine.advance(now_monotonic_ns=clock[0])

    clock[0] = 25 * NS
    assert sine.resume_presentation_after_recovery_relapse(
        candidate_uid=original.candidate_uid,
        occurred_monotonic_ns=clock[0],
        evidence_source="mirl_relapse_detected",
    )
    facts = sine.advance(now_monotonic_ns=clock[0])
    requests = [fact for fact in facts if fact.kind == "SINE_POPUP_REQUESTED"]
    assert len(requests) == 1
    assert requests[0].stage == 3
    assert sine.live_view().episode_uid == original.episode_uid
    assert sine.live_view().stage is SineStage.SINE_3


@pytest.mark.parametrize("stage", [SineStage.SINE_1, SineStage.SINE_2])
def test_normal_sine_one_and_two_cannot_gain_return_entry_withholding(stage):
    sine, clock = _normal_stage(stage)
    before = sine.live_view()
    clock[0] += 10 * NS

    assert not sine.withhold_presentation_for_verified_return_entry(
        candidate_uid=before.candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl_return_verified",
    )
    facts = sine.advance(now_monotonic_ns=clock[0])
    assert "SINE_POPUP_CLOSE_REQUESTED" not in {fact.kind for fact in facts}
    assert sine.live_view().presentation_withheld_for_recovery is False


def test_normal_sine_three_final_recovery_still_resolves_after_early_close():
    sine, clock, request_id = _protected_red(study_mode=False)
    original = sine.live_view()
    clock[0] = 16 * NS
    assert sine.withhold_presentation_for_verified_return_entry(
        candidate_uid=original.candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl_return_verified",
    )
    sine.advance(now_monotonic_ns=clock[0])
    clock[0] = 17 * NS
    assert sine.popup_closed(
        request_id=request_id,
        reason="mirl_return_entry_verified",
        occurred_monotonic_ns=clock[0],
    )
    sine.advance(now_monotonic_ns=clock[0])

    clock[0] = 76 * NS
    assert sine.confirm_verified_return(
        candidate_uid=original.candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl",
    )
    sine.advance(now_monotonic_ns=clock[0])
    final = sine.live_view()
    assert final.episode_uid == original.episode_uid
    assert final.phase is SinePhase.RESOLVED
    assert final.protected_red_active is False


def test_return_entry_closes_red_surface_but_keeps_same_episode_alive():
    sine, clock, request_id = _protected_red()
    before = sine.live_view()

    clock[0] = 16 * NS
    assert sine.withhold_presentation_for_verified_return_entry(
        candidate_uid=before.candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl_return_verified",
    )
    facts = sine.advance(now_monotonic_ns=clock[0])
    kinds = {fact.kind for fact in facts}
    assert "SINE_PRESENTATION_WITHHELD_FOR_RECOVERY" in kinds
    assert "SINE_POPUP_CLOSE_REQUESTED" in kinds

    held = sine.live_view()
    assert held.episode_uid == before.episode_uid
    assert held.candidate_uid == before.candidate_uid
    assert held.phase is SinePhase.PROTECTED_RED
    assert held.protected_red_active is True
    assert held.presentation_withheld_for_recovery is True
    assert held.popup_state is PopupState.CLOSE_REQUESTED

    clock[0] = 17 * NS
    assert sine.popup_closed(
        request_id=request_id,
        reason="mirl_return_entry_verified",
        occurred_monotonic_ns=clock[0],
    )
    facts = sine.advance(now_monotonic_ns=clock[0])
    assert "SINE_PROTECTED_RED_SURFACE_LOST" not in {fact.kind for fact in facts}
    closed = sine.live_view()
    assert closed.popup_state is PopupState.CLOSED
    assert closed.phase is SinePhase.PROTECTED_RED
    assert closed.presentation_withheld_for_recovery is True


def test_relapse_restores_same_protected_red_episode_not_sine_one():
    sine, clock, request_id = _protected_red()
    original = sine.live_view()
    clock[0] = 16 * NS
    assert sine.withhold_presentation_for_verified_return_entry(
        candidate_uid=original.candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl_return_verified",
    )
    sine.advance(now_monotonic_ns=clock[0])
    clock[0] = 17 * NS
    assert sine.popup_closed(
        request_id=request_id,
        reason="mirl_return_entry_verified",
        occurred_monotonic_ns=clock[0],
    )
    sine.advance(now_monotonic_ns=clock[0])

    clock[0] = 18 * NS
    assert sine.resume_presentation_after_recovery_relapse(
        candidate_uid=original.candidate_uid,
        occurred_monotonic_ns=clock[0],
        evidence_source="mirl_relapse_detected",
    )
    facts = sine.advance(now_monotonic_ns=clock[0])
    kinds = [fact.kind for fact in facts]
    assert "SINE_PRESENTATION_RESUMED_AFTER_RELAPSE" in kinds
    assert "SINE_POPUP_REQUESTED" in kinds
    assert not any(
        fact.kind == "SINE_POPUP_REQUESTED" and fact.stage == 1
        for fact in facts
    )
    resumed = sine.live_view()
    assert resumed.episode_uid == original.episode_uid
    assert resumed.candidate_uid == original.candidate_uid
    assert resumed.stage is SineStage.SINE_3
    assert resumed.popup_state is PopupState.REQUESTED
    assert resumed.presentation_withheld_for_recovery is False


def test_accidental_red_close_still_restores_when_no_recovery_hold_exists():
    sine, clock, request_id = _protected_red()
    clock[0] = 7 * NS
    assert sine.popup_closed(
        request_id=request_id,
        reason="unexpected_window_loss",
        occurred_monotonic_ns=clock[0],
    )
    facts = sine.advance(now_monotonic_ns=clock[0])
    kinds = {fact.kind for fact in facts}
    assert "SINE_PROTECTED_RED_SURFACE_LOST" in kinds
    assert "SINE_POPUP_REQUESTED" in kinds
    assert sine.live_view().protected_red_active is True


def test_stage_deadline_is_preserved_while_hidden_and_consumed_on_relapse():
    sine, clock = _authority(stage_2_delay=100.0, stage_3_delay=100.0)
    _show_current(sine, clock, 2)
    initial = sine.live_view()
    deadline = initial.stage_2_deadline_monotonic_ns
    assert deadline == 102 * NS

    clock[0] = 12 * NS
    assert sine.withhold_presentation_for_verified_return_entry(
        candidate_uid=initial.candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl_return_verified",
    )
    sine.advance(now_monotonic_ns=clock[0])
    clock[0] = 200 * NS
    hidden_facts = sine.advance(now_monotonic_ns=clock[0])
    assert "SINE_POPUP_REQUESTED" not in {fact.kind for fact in hidden_facts}
    assert sine.live_view().stage_2_deadline_monotonic_ns == deadline

    clock[0] = 201 * NS
    assert sine.resume_presentation_after_recovery_relapse(
        candidate_uid=initial.candidate_uid,
        occurred_monotonic_ns=clock[0],
        evidence_source="mirl_relapse_detected",
    )
    relapse_facts = sine.advance(now_monotonic_ns=clock[0])
    requests = [fact for fact in relapse_facts if fact.kind == "SINE_POPUP_REQUESTED"]
    assert len(requests) == 1
    assert requests[0].stage == 2
    assert sine.live_view().episode_uid == initial.episode_uid


def test_final_verified_recovery_still_terminally_resolves_after_hidden_entry():
    sine, clock, request_id = _protected_red()
    original = sine.live_view()
    clock[0] = 16 * NS
    assert sine.withhold_presentation_for_verified_return_entry(
        candidate_uid=original.candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl_return_verified",
    )
    sine.advance(now_monotonic_ns=clock[0])
    clock[0] = 17 * NS
    assert sine.popup_closed(
        request_id=request_id,
        reason="mirl_return_entry_verified",
        occurred_monotonic_ns=clock[0],
    )
    sine.advance(now_monotonic_ns=clock[0])

    clock[0] = 76 * NS
    assert sine.confirm_verified_return(
        candidate_uid=original.candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl",
    )
    sine.advance(now_monotonic_ns=clock[0])
    final = sine.live_view()
    assert final.phase is SinePhase.RESOLVED
    assert final.protected_red_active is False
    assert final.episode_uid == original.episode_uid


def test_monitor_routes_only_durable_mirl_entry_and_relapse_facts_to_sine():
    order: list[str] = []

    class _Sine:
        def withhold_presentation_for_verified_return_entry(self, **kwargs):
            order.append(f"hold:{kwargs['candidate_uid']}")
            return True

        def resume_presentation_after_recovery_relapse(self, **kwargs):
            order.append(f"resume:{kwargs['candidate_uid']}")
            return True

    coordinator = SimpleNamespace(
        services=SimpleNamespace(
            storage=SimpleNamespace(
                append_mirl_events=lambda events: order.append("persist") or True
            ),
            sine=_Sine(),
        ),
        telemetry_queue=queue.Queue(),
    )
    coordinator._route_mirl_sine_presentation = MethodType(
        WindowsMonitorCoordinator._route_mirl_sine_presentation,
        coordinator,
    )
    coordinator._publish_domain_fact = (
        lambda domain, event, observation: order.append(f"publish:{event.kind}")
    )
    coordinator._collect_verified_recovery_learning = lambda observation: order.append(
        "collect"
    )
    events = (
        SimpleNamespace(
            kind="MIRL_RETURN_VERIFIED",
            candidate_uid="candidate-one",
            occurred_monotonic_ns=10 * NS,
        ),
        SimpleNamespace(
            kind="MIRL_RELAPSE_DETECTED",
            candidate_uid="candidate-one",
            occurred_monotonic_ns=20 * NS,
        ),
    )

    WindowsMonitorCoordinator._persist_mirl_events(coordinator, events)

    assert order == [
        "persist",
        "hold:candidate-one",
        "publish:MIRL_RETURN_VERIFIED",
        "resume:candidate-one",
        "publish:MIRL_RELAPSE_DETECTED",
        "collect",
    ]
