"""Phase 3: factual ordinary Activity pauses only the SINE escalation clock."""

from __future__ import annotations

from types import MethodType, SimpleNamespace

import pytest

import _lab  # noqa: F401 - installs the production tree on sys.path

from CORE_ENGINE.blacklist import Disposition
from CORE_ENGINE.monitor import (
    ForegroundObservation,
    MonitorContext,
    WindowsMonitorCoordinator,
)
from CORE_ENGINE.resource_intent import ResourceSurface
from SINE.sine import SineAuthority, SinePhase, SinePolicy, SineResponse, SineStage


NS = 1_000_000_000


def _candidate(*, study_mode: bool = False):
    return SimpleNamespace(
        candidate_uid="phase3-activity-candidate",
        session_id=1,
        profile_type="STUDY" if study_mode else "GENERAL",
        evidence=SimpleNamespace(
            observed_monotonic_ns=1 * NS,
            dwell_seconds=300.0,
            threshold_seconds=300.0,
            study_context_token="study-phase3:1" if study_mode else "",
            resource_key="youtube:phase3-distraction",
            resource_observation_token="phase3-observation",
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
    stage_1_visible: float = 3600.0,
    stage_2_delay: float = 1.0,
    stage_3_delay: float = 100.0,
    study_mode: bool = False,
):
    clock = [1 * NS]
    sine = SineAuthority(
        policy=SinePolicy(
            stage_1_visible_seconds=stage_1_visible,
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


def _show_current(sine: SineAuthority, clock: list[int], second: int) -> str:
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


def _normal_sine_two():
    sine, clock = _authority()
    _show_current(sine, clock, 2)
    clock[0] = 3 * NS
    sine.advance(now_monotonic_ns=clock[0])
    _show_current(sine, clock, 4)
    assert sine.live_view().stage_3_deadline_monotonic_ns == 104 * NS
    return sine, clock


def _post_break_sine_two():
    """Drive the post-break path all the way to a FACTUAL SINE 2.

    I'M BACK only re-arms the SINE-1 -> SINE-2 window, so the helper must
    cross that window before SINE 2 exists at all.  The gap is set to 4 s so
    the acknowledgement at t=7 lands the re-armed deadline on t=11, keeping
    every downstream timing assertion below anchored where it was.
    """

    sine, clock = _authority(stage_2_delay=4.0)
    source_request_id = _show_current(sine, clock, 2)
    original = sine.live_view()
    clock[0] = 3 * NS
    assert sine.popup_response(
        request_id=source_request_id,
        response=SineResponse.REQUEST_BREAK,
        occurred_monotonic_ns=clock[0],
    )
    sine.advance(now_monotonic_ns=clock[0])
    clock[0] = 4 * NS
    assert sine.hold_for_normal_break(
        candidate_uid=original.candidate_uid,
        episode_uid=original.episode_uid,
        break_id="phase3-break",
        break_generation=1,
        started_monotonic_ns=clock[0],
        source_popup_request_id=source_request_id,
    )
    sine.advance(now_monotonic_ns=clock[0])
    clock[0] = 6 * NS
    assert sine.enter_post_normal_break_return_gate(
        candidate_uid=original.candidate_uid,
        episode_uid=original.episode_uid,
        break_id="phase3-break",
        break_generation=1,
        occurred_monotonic_ns=clock[0],
        completion_kind="NORMAL_BREAK_COMPLETED",
    )
    sine.advance(now_monotonic_ns=clock[0])
    gate_request_id = _show_current(sine, clock, 7)
    clock[0] = 7 * NS
    assert sine.popup_response(
        request_id=gate_request_id,
        response=SineResponse.RETURN_TO_FOCUS,
        occurred_monotonic_ns=clock[0],
    )
    sine.advance(now_monotonic_ns=clock[0])
    # Still SINE 1 -- the re-armed window has to elapse first.
    assert sine.live_view().stage is SineStage.SINE_1
    assert sine.live_view().stage_2_deadline_monotonic_ns == 11 * NS
    clock[0] = 11 * NS
    sine.advance(now_monotonic_ns=clock[0])
    _show_current(sine, clock, 11)
    return sine, clock, original


def test_activity_freezes_sine_two_and_distraction_resumes_exact_remaining_time():
    sine, clock = _normal_sine_two()
    original = sine.live_view()
    clock[0] = 24 * NS
    assert sine.pause_escalation_for_activity(
        candidate_uid=original.candidate_uid,
        occurred_monotonic_ns=clock[0],
        evidence_source="monitor_ordinary_activity",
    )
    sine.advance(now_monotonic_ns=clock[0])
    assert sine.live_view().activity_clock_paused is True
    assert sine.live_view().next_deadline_seconds == 80.0

    clock[0] = 524 * NS
    hidden_facts = sine.advance(now_monotonic_ns=clock[0])
    assert not any(
        fact.kind == "SINE_POPUP_REQUESTED" and fact.stage == 3
        for fact in hidden_facts
    )
    assert sine.live_view().next_deadline_seconds == 80.0
    assert sine.live_view().episode_uid == original.episode_uid
    assert sine.live_view().stage is SineStage.SINE_2

    clock[0] = 525 * NS
    assert sine.resume_escalation_after_activity(
        candidate_uid=original.candidate_uid,
        occurred_monotonic_ns=clock[0],
        evidence_source="monitor_sine_driving_distraction",
    )
    resume_facts = sine.advance(now_monotonic_ns=clock[0])
    assert "SINE_POPUP_REQUESTED" not in {fact.kind for fact in resume_facts}
    assert sine.live_view().stage_3_deadline_monotonic_ns == 605 * NS
    assert sine.live_view().activity_clock_paused is False

    clock[0] = 604 * NS
    assert "SINE_POPUP_REQUESTED" not in {
        fact.kind for fact in sine.advance(now_monotonic_ns=clock[0])
    }
    clock[0] = 605 * NS
    requests = [
        fact
        for fact in sine.advance(now_monotonic_ns=clock[0])
        if fact.kind == "SINE_POPUP_REQUESTED"
    ]
    assert len(requests) == 1
    assert requests[0].stage == 3
    assert sine.live_view().episode_uid == original.episode_uid


def test_activity_pause_does_not_pause_the_current_popup_display_window():
    sine, clock = _authority(
        stage_1_visible=10.0,
        stage_2_delay=100.0,
    )
    _show_current(sine, clock, 2)
    original = sine.live_view()
    clock[0] = 5 * NS
    assert sine.pause_escalation_for_activity(
        candidate_uid=original.candidate_uid,
        occurred_monotonic_ns=clock[0],
        evidence_source="monitor_ordinary_activity",
    )
    sine.advance(now_monotonic_ns=clock[0])

    clock[0] = 12 * NS
    facts = sine.advance(now_monotonic_ns=clock[0])
    kinds = {fact.kind for fact in facts}
    assert "SINE_POPUP_EXPIRED" in kinds
    assert "SINE_POPUP_CLOSE_REQUESTED" in kinds
    assert "SINE_POPUP_REQUESTED" not in kinds
    assert sine.live_view().next_deadline_seconds == 97.0


def test_mirl_recovery_pause_inherits_activity_frozen_remaining_time():
    sine, clock, original = _post_break_sine_two()
    before = sine.live_view()
    assert before.stage_3_deadline_monotonic_ns == 111 * NS

    clock[0] = 31 * NS
    assert sine.pause_escalation_for_activity(
        candidate_uid=before.candidate_uid,
        occurred_monotonic_ns=clock[0],
        evidence_source="monitor_ordinary_activity",
    )
    sine.advance(now_monotonic_ns=clock[0])
    assert sine.live_view().next_deadline_seconds == 80.0

    clock[0] = 41 * NS
    assert sine.withhold_presentation_for_verified_return_entry(
        candidate_uid=before.candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl_return_verified",
    )
    sine.advance(now_monotonic_ns=clock[0])
    transferred = sine.live_view()
    assert transferred.activity_clock_paused is False
    assert transferred.presentation_withheld_for_recovery is True
    assert transferred.next_deadline_seconds == 80.0

    clock[0] = 541 * NS
    assert "SINE_POPUP_REQUESTED" not in {
        fact.kind for fact in sine.advance(now_monotonic_ns=clock[0])
    }
    assert sine.live_view().next_deadline_seconds == 80.0

    clock[0] = 542 * NS
    assert sine.resume_presentation_after_recovery_relapse(
        candidate_uid=before.candidate_uid,
        occurred_monotonic_ns=clock[0],
        evidence_source="mirl_relapse_detected",
    )
    sine.advance(now_monotonic_ns=clock[0])
    assert sine.live_view().stage_3_deadline_monotonic_ns == 622 * NS
    assert sine.live_view().episode_uid == original.episode_uid


class _SineProbe:
    def __init__(self, **overrides):
        values = dict(
            candidate_uid="candidate-monitor",
            episode_uid="episode-monitor",
            phase=SinePhase.ACTIVE,
            study_mode=False,
            protected_red_active=False,
            presentation_withheld_for_recovery=False,
            normal_break_held=False,
        )
        values.update(overrides)
        self.view = SimpleNamespace(**values)
        self.calls: list[str] = []

    def live_view(self):
        return self.view

    def pause_escalation_for_activity(self, **_kwargs):
        self.calls.append("PAUSE")
        return True

    def resume_escalation_after_activity(self, **_kwargs):
        self.calls.append("RUN")
        return True


def _monitor_probe(
    *,
    sine_overrides=None,
    break_state="IDLE",
    break_active=False,
    cosine_phase="IDLE",
):
    sine = _SineProbe(**(sine_overrides or {}))
    normal_break = SimpleNamespace(
        active=break_active,
        snapshot=lambda: SimpleNamespace(state=break_state),
    )
    coordinator = SimpleNamespace(
        services=SimpleNamespace(
            sine=sine,
            normal_break=normal_break,
            cosine=SimpleNamespace(
                snapshot=lambda **_kwargs: SimpleNamespace(phase=cosine_phase)
            ),
        ),
        _normal_break_resume_fault=False,
    )
    coordinator._normal_break_owns_pause = MethodType(
        WindowsMonitorCoordinator._normal_break_owns_pause,
        coordinator,
    )
    coordinator._sync_sine_activity_clock = MethodType(
        WindowsMonitorCoordinator._sync_sine_activity_clock,
        coordinator,
    )
    return coordinator, sine


def _context(*, surface=ResourceSurface.UNKNOWN, title="ordinary foreground"):
    foreground = ForegroundObservation(
        sequence=1,
        hwnd=10,
        process_id=20,
        process_name="python",
        window_title=title,
        observed_monotonic_ns=20 * NS,
        observed_wall_time_utc="2026-08-27T00:00:20Z",
        idle_seconds=0.0,
    )
    intent = SimpleNamespace(
        verdict=SimpleNamespace(
            resource_identity=SimpleNamespace(surface=surface),
        )
    )
    return MonitorContext(
        foreground=foreground,
        browser_evidence=SimpleNamespace(),
        resource_intent=intent,
    )


def _blacklist(*, actionable: bool, disposition: Disposition):
    return SimpleNamespace(
        verdict=SimpleNamespace(
            actionable=actionable,
            disposition=disposition,
        )
    )


def test_monitor_pauses_myelin_control_station_from_authoritative_fallback_facts():
    coordinator, sine = _monitor_probe()
    assert coordinator._sync_sine_activity_clock(
        _context(title="MYELIN — Control Station v2.0"),
        _blacklist(actionable=False, disposition=Disposition.UNSUPPORTED),
    )
    assert sine.calls == ["PAUSE"]


@pytest.mark.parametrize(
    ("surface", "actionable", "disposition", "break_state", "cosine_phase"),
    [
        (ResourceSurface.SOCIAL, True, Disposition.ACCUSED, "IDLE", "IDLE"),
        (ResourceSurface.MESSAGING, False, Disposition.HANDOFF, "IDLE", "IDLE"),
        (ResourceSurface.UNKNOWN, False, Disposition.UNSUPPORTED, "AWAITING_DURATION", "IDLE"),
        (ResourceSurface.UNKNOWN, False, Disposition.UNSUPPORTED, "IDLE", "ACTIVE"),
    ],
)
def test_monitor_keeps_clock_running_for_distraction_selector_messaging_and_cosine(
    surface,
    actionable,
    disposition,
    break_state,
    cosine_phase,
):
    coordinator, sine = _monitor_probe(
        break_state=break_state,
        cosine_phase=cosine_phase,
    )
    assert coordinator._sync_sine_activity_clock(
        _context(surface=surface, title="must not be classified from this title"),
        _blacklist(actionable=actionable, disposition=disposition),
    )
    assert sine.calls == ["RUN"]


@pytest.mark.parametrize(
    "probe_options",
    [
        {"sine_overrides": {"study_mode": True}},
        {
            "sine_overrides": {
                "phase": SinePhase.PROTECTED_RED,
                "protected_red_active": True,
            }
        },
        {"sine_overrides": {"presentation_withheld_for_recovery": True}},
        {"break_active": True},
    ],
)
def test_monitor_does_not_replace_specialist_study_red_recovery_or_break_holds(
    probe_options,
):
    coordinator, sine = _monitor_probe(**probe_options)
    assert coordinator._sync_sine_activity_clock(
        _context(),
        _blacklist(actionable=False, disposition=Disposition.UNSUPPORTED),
    )
    assert sine.calls == []
