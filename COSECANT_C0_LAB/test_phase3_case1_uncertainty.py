"""Phase 3 external acceptance: Study Case 1, C1-01 through C1-16."""

from __future__ import annotations

import hashlib
import inspect
import queue
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ULTIMATE = Path(r"C:\Users\Dharshan\Downloads\MYELIN_GENALOGY\MYELIN2.0_ULTIMATE")
if str(ULTIMATE) not in sys.path:
    sys.path.insert(0, str(ULTIMATE))

import COSECANT_STUDY_MODE.view as study_view_module
from COSECANT_STUDY_MODE.cosecant import CosecantPolicy
from COSECANT_STUDY_MODE.view import (
    ResourceIntentTelemetryPanel,
    StudyConfirmationPopup,
    StudyConfirmationPresenter,
    StudyView,
)
from CONTROL_STATION.controller import ControlStationController, TelemetryEvent
from CONTROL_STATION.launcher import ControlPage
from CORE_ENGINE.blacklist import BlacklistAuthority
from CORE_ENGINE.monitor import MonitorContext, WindowsMonitorCoordinator
from CORE_ENGINE.resource_intent import (
    ResourceIntent,
    ResourceIntentAuthority,
    ResourceIntentFact,
    SineContribution,
    StudyConfirmationResponse,
    StudyEffectiveState,
    StudyUserConfirmation,
)
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication
from SINE.sine import SineAuthority, SinePhase, SinePolicy
from CORE_ENGINE.trigger import TriggerAuthority

from _lab import LECTURE, MRBEAST, OTHER_LECTURE, SHORTS, Surface
from test_c4_bsf import HONEST_LECTURE, MRBEAST_DISGUISED, Session
from test_phase1_single_episode_ownership import _candidate, _context


NS = 1_000_000_000


def _uncertain_session() -> Session:
    return Session(keywords=(), important=())


def _prompt(session: Session, surface=LECTURE):
    first = session.look(surface, after_seconds=0)
    started = session.intent.drain_facts()
    assert first.verdict.classification is ResourceIntent.UNCERTAIN
    assert first.verdict.sine_contribution is SineContribution.NONE
    assert {fact.kind for fact in started} == {"STUDY_UNCERTAINTY_STARTED"}

    at_five = session.look(surface, after_seconds=300)
    facts = session.intent.drain_facts()
    request_fact = next(
        fact for fact in facts if fact.kind == "STUDY_CONFIRMATION_POPUP_REQUESTED"
    )
    assert request_fact.popup is not None
    return at_five, request_fact.popup, facts


def _respond(session: Session, request, response: StudyConfirmationResponse) -> int:
    occurred_ns = request.requested_monotonic_ns + 1
    accepted = session.intent.record_study_confirmation_response(
        request_id=request.request_id,
        response=response.value,
        occurred_monotonic_ns=occurred_ns,
        expected_study_context_token=request.study_context_token,
        expected_resource_key=request.resource_key,
    )
    assert accepted
    return occurred_ns


def _continuous_look(session: Session, surfaces, start: int, stop: int):
    latest = None
    seconds = start
    index = 0
    while seconds <= stop:
        latest = session.look(surfaces[index % len(surfaces)], after_seconds=seconds)
        seconds += 5
        index += 1
    if stop >= start and (seconds - 5) != stop:
        latest = session.look(surfaces[index % len(surfaces)], after_seconds=stop)
    return latest


def _look_continuously_until_ns(session: Session, surface, target_ns: int):
    next_ns = session.intent._dwell_last_ns + 5 * NS
    while next_ns < target_ns:
        session.look_at_ns(surface, at_ns=next_ns)
        next_ns += 5 * NS
    return session.look_at_ns(surface, at_ns=target_ns)


def _memory_surface(number: int) -> Surface:
    return Surface(
        process_name="chrome",
        title=f"Focused lecture resource {number} - YouTube",
        url=f"https://www.youtube.com/watch?v=MEMORY_RESOURCE_{number:02d}",
        hwnd=82_000 + number,
        process_id=9_100 + number,
    )


def _confirm_memory_resource(
    session: Session,
    surface: Surface,
    *,
    start_second: int,
    response: StudyConfirmationResponse,
):
    first = session.look(surface, after_seconds=start_second)
    assert first.verdict.classification is ResourceIntent.UNCERTAIN
    session.intent.drain_facts()
    session.look(surface, after_seconds=start_second + 300)
    request = next(
        fact.popup
        for fact in session.intent.drain_facts()
        if fact.kind == "STUDY_CONFIRMATION_POPUP_REQUESTED"
    )
    assert request is not None
    _respond(session, request, response)
    session.intent.drain_facts()
    return request


def _sha256(relative: str) -> str:
    return hashlib.sha256((ULTIMATE / relative).read_bytes()).hexdigest().upper()


def test_c1_01_exact_study_resource_has_no_uncertainty_popup_or_sine():
    session = Session()
    snapshot = session.look(HONEST_LECTURE, after_seconds=0)
    assert snapshot.verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert snapshot.verdict.sine_contribution is SineContribution.WITHHELD
    assert session.intent.drain_facts() == ()
    assert session.intent.live_view().uncertainty_active is False


def test_c1_02_fifty_percent_for_five_minutes_requests_two_button_popup_no_sine_or_mirl():
    session = _uncertain_session()
    snapshot, request, facts = _prompt(session)
    assert snapshot.verdict.classification is ResourceIntent.UNCERTAIN
    assert snapshot.verdict.confidence == 0.50
    assert snapshot.verdict.sine_contribution is SineContribution.NONE
    assert request.measured_confidence == 0.50
    assert not any("SINE" in fact.kind or "MIRL" in fact.kind for fact in facts)

    app = QApplication.instance() or QApplication([])
    presenter = StudyConfirmationPresenter()
    shown = []
    presenter.popup_shown.connect(
        lambda request_id, occurred, hwnd: shown.append((request_id, int(hwnd)))
    )
    presenter.apply_fact(
        ResourceIntentFact(
            kind="STUDY_CONFIRMATION_POPUP_REQUESTED",
            message="requested",
            occurred_monotonic_ns=request.requested_monotonic_ns,
            popup_request_id=request.request_id,
            popup=request,
        )
    )
    app.processEvents()
    app.processEvents()
    popup = presenter._popup
    assert popup is not None and popup.isVisible()
    assert shown and shown[0][0] == request.request_id and shown[0][1] > 0
    assert popup.study_button.text() == "THIS IS STUDY MATERIAL"
    assert popup.off_task_button.text() == "I'M COMING BACK"
    presenter.close_all("test_complete")
    app.processEvents()


def test_c1_03_study_confirmation_preserves_measurement_and_withholds_sine():
    session = _uncertain_session()
    _, request, _ = _prompt(session)
    _respond(session, request, StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL)
    latest = session.intent._latest.verdict
    facts = session.intent.drain_facts()
    assert "USER_CONFIRMED_STUDY" in {fact.kind for fact in facts}
    assert latest.classification is ResourceIntent.STUDY_ALIGNED
    assert latest.measured_classification is ResourceIntent.UNCERTAIN
    assert latest.measured_confidence == 0.50
    assert latest.user_confirmation is StudyUserConfirmation.STUDY
    assert latest.effective_operational_state is StudyEffectiveState.STUDY_ALIGNED
    assert latest.sine_contribution is SineContribution.WITHHELD
    assert session.intent.live_view().uncertainty_active is False


def test_c1_04_off_task_confirmation_starts_fresh_watch_not_immediate_sine_one():
    session = _uncertain_session()
    _, request, _ = _prompt(session)
    _respond(session, request, StudyConfirmationResponse.IM_COMING_BACK)
    latest = session.intent._latest.verdict
    facts = session.intent.drain_facts()
    assert "USER_CONFIRMED_OFF_TASK" in {fact.kind for fact in facts}
    assert latest.classification is ResourceIntent.DISTRACTION
    assert latest.measured_classification is ResourceIntent.UNCERTAIN
    assert latest.user_confirmation is StudyUserConfirmation.OFF_TASK
    assert latest.off_task_dwell_seconds == 0.0
    assert latest.sine_contribution is SineContribution.PENDING
    assert not any(fact.kind.startswith("SINE_") for fact in facts)


def test_c1_05_five_then_ten_then_thirteen_fifteen_uses_one_normal_sine_authority():
    session = _uncertain_session()
    _, request, _ = _prompt(session)
    _respond(session, request, StudyConfirmationResponse.IM_COMING_BACK)
    session.intent.drain_facts()
    ready = _continuous_look(session, (LECTURE,), 301, 601)
    assert ready.verdict.sine_contribution is SineContribution.READY
    assert ready.verdict.off_task_dwell_seconds >= 300.0

    trigger_ns = session.base_ns + 601 * NS
    clock = [trigger_ns]
    sine = SineAuthority(monotonic_ns=lambda: clock[0])
    sine.start_session(session_id=1, profile_type="STUDY")
    candidate = _candidate(candidate_uid="study-case1", resource_key=ready.resource_key)
    candidate.profile_type = "STUDY"
    assert sine.request_trigger(
        candidate=candidate,
        operational_event_id=1,
        mirl_display_token=SimpleNamespace(),
    )
    facts = sine.advance(now_monotonic_ns=clock[0])
    sine_1 = next(fact.popup for fact in facts if fact.kind == "SINE_POPUP_REQUESTED")
    assert int(sine_1.stage) == 1

    clock[0] += 1
    assert sine.popup_shown(
        request_id=sine_1.request_id,
        shown_monotonic_ns=clock[0],
        popup_hwnd=101,
    )
    sine.advance(now_monotonic_ns=clock[0])
    stage_2_due = clock[0] + int(600 * NS)
    assert sine.live_view().stage_2_deadline_monotonic_ns == stage_2_due

    clock[0] = stage_2_due
    facts = sine.advance(now_monotonic_ns=clock[0])
    sine_2 = next(fact.popup for fact in facts if fact.kind == "SINE_POPUP_REQUESTED")
    assert int(sine_2.stage) == 2
    clock[0] += 1
    assert sine.popup_shown(
        request_id=sine_2.request_id,
        shown_monotonic_ns=clock[0],
        popup_hwnd=102,
    )
    sine.advance(now_monotonic_ns=clock[0])
    stage_3_due = clock[0] + int(795 * NS)
    assert sine.live_view().stage_3_deadline_monotonic_ns == stage_3_due
    clock[0] = stage_3_due
    facts = sine.advance(now_monotonic_ns=clock[0])
    sine_3 = next(fact.popup for fact in facts if fact.kind == "SINE_POPUP_REQUESTED")
    assert int(sine_3.stage) == 3


def test_c1_06_no_response_reprompts_after_next_five_minutes_without_sine():
    session = _uncertain_session()
    _, first, _ = _prompt(session)
    session.look(LECTURE, after_seconds=600)
    facts = session.intent.drain_facts()
    second = next(
        fact.popup for fact in facts if fact.kind == "STUDY_CONFIRMATION_POPUP_REQUESTED"
    )
    assert second is not None
    assert second.request_id != first.request_id
    assert second.uncertainty_episode_uid == first.uncertainty_episode_uid
    assert second.prompt_number == 2
    assert not any(fact.kind.startswith("SINE_") for fact in facts)


def test_c1_07_uncertain_resource_switch_does_not_reset_clarification_timer():
    session = _uncertain_session()
    session.look(LECTURE, after_seconds=0)
    episode = session.intent.live_view().uncertainty_episode_uid
    session.intent.drain_facts()
    session.look(OTHER_LECTURE, after_seconds=150)
    assert session.intent.live_view().uncertainty_episode_uid == episode
    session.look(LECTURE, after_seconds=300)
    facts = session.intent.drain_facts()
    request = next(
        fact.popup for fact in facts if fact.kind == "STUDY_CONFIRMATION_POPUP_REQUESTED"
    )
    assert request.uncertainty_episode_uid == episode
    assert request.requested_monotonic_ns == session.base_ns + 300 * NS


def test_c1_08_automatic_study_alignment_stops_clarification_without_sine():
    session = Session()
    first = session.look(SHORTS, after_seconds=0)
    assert first.verdict.classification is ResourceIntent.UNCERTAIN
    session.intent.drain_facts()
    aligned = session.look(HONEST_LECTURE, after_seconds=120)
    facts = session.intent.drain_facts()
    assert aligned.verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert aligned.verdict.sine_contribution is SineContribution.WITHHELD
    assert session.intent.live_view().uncertainty_active is False
    assert "STUDY_UNCERTAINTY_RESOLVED" in {fact.kind for fact in facts}
    assert not any(fact.kind.startswith("SINE_") for fact in facts)


def test_c1_09_automatic_distraction_starts_at_confirmation_without_backdating():
    session = Session()
    assert session.look(SHORTS, after_seconds=0).verdict.classification is ResourceIntent.UNCERTAIN
    session.intent.drain_facts()
    confirmed = session.look(MRBEAST, after_seconds=120)
    assert confirmed.verdict.classification is ResourceIntent.DISTRACTION
    assert confirmed.verdict.off_task_dwell_seconds == 0.0
    assert confirmed.verdict.sine_contribution is SineContribution.PENDING
    ready = _continuous_look(session, (MRBEAST,), 125, 420)
    assert ready.verdict.off_task_dwell_seconds == pytest.approx(300.0, abs=0.01)
    assert ready.verdict.sine_contribution is SineContribution.READY


def test_c1_10_confirmed_study_does_not_authorize_a_new_distractive_resource():
    session = _uncertain_session()
    _, request, _ = _prompt(session)
    _respond(session, request, StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL)
    session.intent.drain_facts()
    distraction = session.look(MRBEAST, after_seconds=301)
    assert distraction.verdict.classification is ResourceIntent.DISTRACTION
    assert distraction.verdict.allowance_match is False
    assert distraction.verdict.off_task_dwell_seconds == 0.0
    assert distraction.verdict.sine_contribution is SineContribution.PENDING


def test_c1_11_confirmed_watch_survives_repeated_distractive_video_switches():
    session = _uncertain_session()
    _, request, _ = _prompt(session)
    _respond(session, request, StudyConfirmationResponse.IM_COMING_BACK)
    session.intent.drain_facts()
    ready = _continuous_look(
        session,
        (MRBEAST, MRBEAST_DISGUISED),
        301,
        601,
    )
    assert ready.verdict.off_task_dwell_seconds >= 300.0
    assert ready.verdict.sine_contribution is SineContribution.READY


def test_c1_12_active_sine_keeps_episode_and_original_stage_two_deadline_on_switch():
    clock = [1_000_000_000]
    sine = SineAuthority(monotonic_ns=lambda: clock[0])
    sine.start_session(session_id=1, profile_type="STUDY")
    candidate = _candidate(candidate_uid="case1-active")
    candidate.profile_type = "STUDY"
    assert sine.request_trigger(
        candidate=candidate,
        operational_event_id=1,
        mirl_display_token=SimpleNamespace(),
    )
    sine.advance(now_monotonic_ns=clock[0])
    request_id = sine.live_view().popup_request_id
    clock[0] += 1
    assert sine.popup_shown(
        request_id=request_id,
        shown_monotonic_ns=clock[0],
        popup_hwnd=201,
    )
    sine.advance(now_monotonic_ns=clock[0])
    before = sine.live_view()
    sine.observe(_context(sequence=2, resource_key="video-b"))
    sine.observe(_context(sequence=3, resource_key="video-c"))
    after = sine.live_view()
    assert after.phase is SinePhase.ACTIVE
    assert after.episode_uid == before.episode_uid
    assert after.stage_2_deadline_monotonic_ns == before.stage_2_deadline_monotonic_ns


def test_c1_13_clarification_facts_never_found_mirl():
    session = _uncertain_session()
    _, request, _ = _prompt(session)
    _respond(session, request, StudyConfirmationResponse.IM_COMING_BACK)
    facts = session.intent.drain_facts()
    assert facts
    assert all(isinstance(fact, ResourceIntentFact) for fact in facts)
    assert not any("MIRL" in fact.kind or "SINE_DISPLAYED" in fact.kind for fact in facts)
    route_source = inspect.getsource(WindowsMonitorCoordinator._drain_resource_intent_facts)
    assert "mirl" not in route_source.casefold()


def test_c1_14_clarification_path_contains_no_lambda_update():
    response_source = inspect.getsource(
        __import__(
            "CORE_ENGINE.resource_intent",
            fromlist=["ResourceIntentAuthority"],
        ).ResourceIntentAuthority.record_study_confirmation_response
    )
    assert "lambda" not in response_source.casefold()
    assert "profile" not in response_source.casefold()


def test_c1_15_ebbinghaus_and_sine_timing_authorities_are_byte_exact():
    # Phase 4 adds only SINE-owned presentation withholding/resumption around
    # MIRL's verified recovery entry. The timing authority remains byte-pinned
    # at this reviewed Phase-4 implementation and its policy values below stay
    # independently explicit.
    assert _sha256("SINE/sine.py") == "2F7B0C5E7D24A85A2D1963624B15F2EED87A60C7CA56951833245DAC4AD0CE82"
    assert _sha256("CORE_ENGINE/trigger.py") == "161BB48E6ACBD15A2754A15E1F41540AAE289EB6CA1D0E880B81BC8120B4FC7A"
    assert SinePolicy().stage_2_delay_seconds == 600.0
    assert SinePolicy().stage_3_delay_seconds == 795.0


def test_c1_16_cosecant_policy_and_implementation_are_unchanged():
    assert _sha256("COSECANT_STUDY_MODE/cosecant.py") == "F6EFC96795F8BC4BA930BB53C16E6720A745C9097D8016D1642FBC40761A0ACB"
    policy = CosecantPolicy()
    assert policy.already_over_delay_seconds == 300.0
    assert policy.final_lock_delay_seconds == 60.0
    assert policy.return_confirmation_seconds == 3.0


def test_p3_r6_r7_popup_and_action_provenance_are_not_sine():
    session = _uncertain_session()
    _, request, facts = _prompt(session)
    request_fact = next(
        fact for fact in facts if fact.kind == "STUDY_CONFIRMATION_POPUP_REQUESTED"
    )
    assert isinstance(request_fact, ResourceIntentFact)
    assert request_fact.popup_request_id == request.request_id
    assert not request_fact.kind.startswith("SINE_")
    _respond(session, request, StudyConfirmationResponse.IM_COMING_BACK)
    action = next(
        fact
        for fact in session.intent.drain_facts()
        if fact.kind == "USER_CONFIRMED_OFF_TASK"
    )
    assert action.user_confirmation is StudyUserConfirmation.OFF_TASK
    assert action.kind != "SINE_RETURN_INTENT_RECORDED"


def test_p3_r1_normal_non_study_sine_still_requests_sine_one():
    clock = [1_000_000_000]
    sine = SineAuthority(monotonic_ns=lambda: clock[0])
    sine.start_session(session_id=1, profile_type="GENERAL")
    assert sine.request_trigger(
        candidate=_candidate(candidate_uid="p3-normal-non-study"),
        operational_event_id=1,
        mirl_display_token=SimpleNamespace(),
    )
    sine.advance(now_monotonic_ns=clock[0])
    view = sine.live_view()
    assert view.phase is SinePhase.WAITING_FOR_DISPLAY
    assert view.popup_request_id


def test_p3_resource_intent_fact_reaches_presenter_and_semantic_live_telemetry():
    applied = []
    emitted = []
    fact = ResourceIntentFact(
        kind="STUDY_CONFIRMATION_POPUP_REQUESTED",
        message="Study material remains 50% uncertain",
        occurred_monotonic_ns=300 * NS,
        popup_request_id="study-confirmation-1",
    )
    ignored_signal = SimpleNamespace(emit=lambda value: None)
    fake = SimpleNamespace(
        _telemetry_queue=queue.Queue(),
        _study_confirmation_presenter=SimpleNamespace(apply_fact=applied.append),
        telemetry_received=SimpleNamespace(emit=emitted.append),
        control_view_changed=ignored_signal,
        study_view_changed=ignored_signal,
        cosine_live_status_changed=ignored_signal,
        resource_intent_live_status_changed=ignored_signal,
        sine_watch_status_changed=ignored_signal,
        mine_watch_status_changed=ignored_signal,
        mirl_health_status_changed=ignored_signal,
    )
    fake._route_prepared_view = lambda kind, raw: (
        ControlStationController._route_prepared_view(fake, kind, raw)
    )
    fake._telemetry_queue.put_nowait(
        {
            "time": "2026-08-24T00:05:00+00:00",
            "kind": "resource_intent_fact",
            "app": "",
            "title": "",
            "message": fact.message,
            "badge": "STUDY CONFIRM",
            "feed_text": "50% UNCERTAIN — confirmation requested",
            "tone": "amber",
            "fact": fact,
        }
    )

    assert ControlStationController._drain_telemetry(fake, drain_all=True) == 1
    assert applied == [fact]
    assert emitted == [
        TelemetryEvent(
            time="2026-08-24T00:05:00+00:00",
            kind="resource_intent_fact",
            app="",
            title="",
            message=fact.message,
            badge="STUDY CONFIRM",
            feed_text="50% UNCERTAIN — confirmation requested",
            tone="amber",
        )
    ]


def test_monitor_study_gate_requires_resource_intent_ready_not_blacklist_age():
    coordinator = object.__new__(WindowsMonitorCoordinator)
    coordinator.services = SimpleNamespace()
    uncertain = SimpleNamespace(
        resource_intent=SimpleNamespace(
            verdict=SimpleNamespace(
                classification=ResourceIntent.UNCERTAIN,
                sine_contribution=SineContribution.NONE,
                study_context_token="study-case1",
            )
        )
    )
    pending = SimpleNamespace(
        resource_intent=SimpleNamespace(
            verdict=SimpleNamespace(
                classification=ResourceIntent.DISTRACTION,
                sine_contribution=SineContribution.PENDING,
                study_context_token="study-case1",
            )
        )
    )
    ready = SimpleNamespace(
        resource_intent=SimpleNamespace(
            verdict=SimpleNamespace(
                classification=ResourceIntent.DISTRACTION,
                sine_contribution=SineContribution.READY,
                study_context_token="study-case1",
            )
        )
    )
    assert not coordinator._study_trigger_admission_open(uncertain)
    assert not coordinator._study_trigger_admission_open(pending)
    assert coordinator._study_trigger_admission_open(ready)


@pytest.mark.parametrize("personalization_factor", [0.5, 1.0, 1.5])
def test_phase3_correction_study_ready_uses_exact_blacklist_target(
    personalization_factor,
):
    blacklist = BlacklistAuthority()
    blacklist.start_session(personalization_factor=personalization_factor)
    target_seconds = blacklist.stage_one_target_seconds()
    session = Session(
        keywords=(),
        important=(),
        stage_one_target_seconds=target_seconds,
    )
    _, request, _ = _prompt(session)
    confirmed_ns = _respond(
        session,
        request,
        StudyConfirmationResponse.IM_COMING_BACK,
    )
    session.intent.drain_facts()

    before = _look_continuously_until_ns(
        session,
        LECTURE,
        confirmed_ns + int(target_seconds * NS) - 1,
    )
    assert before.verdict.sine_contribution is SineContribution.PENDING
    assert before.verdict.off_task_dwell_seconds < target_seconds

    ready = session.look_at_ns(
        LECTURE,
        at_ns=confirmed_ns + int(target_seconds * NS),
    )
    assert ready.verdict.sine_contribution is SineContribution.READY
    assert ready.verdict.off_task_dwell_seconds == target_seconds
    assert session.intent.live_view().dwell_target_seconds == target_seconds
    assert session.intent.live_view().uncertainty_target_seconds == 300.0


def test_phase3_correction_monitor_copies_blacklist_target_without_calculation():
    blacklist = BlacklistAuthority()
    blacklist.start_session(personalization_factor=0.5)
    intent = ResourceIntentAuthority()
    intent.start_session(profile_type="STUDY")
    coordinator = object.__new__(WindowsMonitorCoordinator)
    coordinator.services = SimpleNamespace(
        blacklist=blacklist,
        resource_intent=intent,
    )

    supplied = coordinator._bind_stage_one_target()
    assert supplied == blacklist.stage_one_target_seconds()
    assert intent._stage_one_target_seconds == supplied


def test_phase3_correction_one_ready_founds_one_trigger_and_one_sine_one():
    blacklist = BlacklistAuthority()
    blacklist.start_session(personalization_factor=0.5)
    target_seconds = blacklist.stage_one_target_seconds()
    session = Session(
        keywords=(),
        important=(),
        stage_one_target_seconds=target_seconds,
    )
    _, request, _ = _prompt(session)
    confirmed_ns = _respond(
        session,
        request,
        StudyConfirmationResponse.IM_COMING_BACK,
    )
    session.intent.drain_facts()

    switched = _look_continuously_until_ns(
        session,
        MRBEAST,
        confirmed_ns + int(target_seconds * NS),
    )
    assert switched.verdict.sine_contribution is SineContribution.READY
    assert switched.verdict.off_task_dwell_seconds == target_seconds

    context = MonitorContext(
        foreground=session.last_foreground,
        browser_evidence=session.last_browser_evidence,
        resource_intent=switched,
    )
    blacklist_snapshot = blacklist.observe(context)
    assert blacklist_snapshot.target_seconds == target_seconds

    clock = [session.last_foreground.observed_monotonic_ns]
    trigger = TriggerAuthority(monotonic_ns=lambda: clock[0])
    trigger.start_session(session_id=1, profile_type="STUDY")
    candidate = trigger.evaluate(context=context, blacklist=blacklist_snapshot)
    assert candidate is not None
    assert trigger.evaluate(context=context, blacklist=blacklist_snapshot) is candidate

    sine = SineAuthority(monotonic_ns=lambda: clock[0])
    sine.start_session(session_id=1, profile_type="STUDY")
    assert sine.request_trigger(
        candidate=candidate,
        operational_event_id=1,
        mirl_display_token=SimpleNamespace(),
    )
    assert not sine.request_trigger(
        candidate=candidate,
        operational_event_id=2,
        mirl_display_token=SimpleNamespace(),
    )
    sine.advance(now_monotonic_ns=clock[0])
    assert sine.live_view().phase is SinePhase.WAITING_FOR_DISPLAY


def test_windows_acceptance_popup_foreground_cannot_reject_its_own_request():
    session = _uncertain_session()
    _, request, _ = _prompt(session)
    popup_surface = Surface(
        process_name="python",
        title="MYELIN — STUDY CONFIRMATION",
        hwnd=81_002,
        process_id=9_002,
    )

    # Reproduce the Windows race exactly: MYELIN becomes latest foreground
    # before its factual SHOWN callback reaches Resource Intent.
    session.look_at_ns(
        popup_surface,
        at_ns=request.requested_monotonic_ns + 1,
    )
    assert session.intent.record_study_confirmation_popup_shown(
        request_id=request.request_id,
        shown_monotonic_ns=request.requested_monotonic_ns + 2,
        popup_hwnd=popup_surface.hwnd,
    )
    accepted_ns = request.requested_monotonic_ns + 3
    assert session.intent.record_study_confirmation_response(
        request_id=request.request_id,
        response=StudyConfirmationResponse.IM_COMING_BACK.value,
        occurred_monotonic_ns=accepted_ns,
        expected_study_context_token=request.study_context_token,
        expected_resource_key=request.resource_key,
    )

    accepted_facts = session.intent.drain_facts()
    assert "USER_CONFIRMED_OFF_TASK" in {fact.kind for fact in accepted_facts}
    latest = session.intent._latest.verdict
    assert latest.resource_identity.stable_key == request.resource_key
    assert latest.classification is ResourceIntent.DISTRACTION
    assert latest.confidence == 1.0
    assert latest.measured_classification is ResourceIntent.UNCERTAIN
    assert latest.measured_confidence == 0.50
    assert latest.off_task_dwell_seconds == 0.0

    returned = session.look_at_ns(LECTURE, at_ns=accepted_ns + NS)
    assert returned.verdict.classification is ResourceIntent.DISTRACTION
    assert returned.verdict.confidence == 1.0
    assert returned.verdict.user_confirmation is StudyUserConfirmation.OFF_TASK
    assert returned.verdict.off_task_dwell_seconds == 1.0
    assert not any(
        fact.kind == "STUDY_UNCERTAINTY_STARTED"
        for fact in session.intent.drain_facts()
    )


def test_windows_acceptance_genuine_external_resource_change_stays_stale_safe():
    session = _uncertain_session()
    _, request, _ = _prompt(session)
    other_uncertain = Surface(
        process_name="chrome",
        title="Another unresolved lecture - YouTube",
        url="https://www.youtube.com/watch?v=OTHER_UNCERTAIN_003",
        hwnd=81_003,
        process_id=9_003,
    )
    session.look_at_ns(
        other_uncertain,
        at_ns=request.requested_monotonic_ns + 1,
    )
    assert not session.intent.record_study_confirmation_response(
        request_id=request.request_id,
        response=StudyConfirmationResponse.IM_COMING_BACK.value,
        occurred_monotonic_ns=request.requested_monotonic_ns + 2,
        expected_study_context_token=request.study_context_token,
        expected_resource_key=request.resource_key,
    )


def test_windows_acceptance_popup_centres_on_source_hwnd_work_area(monkeypatch):
    session = _uncertain_session()
    _, request, _ = _prompt(session)
    assert request.source_hwnd == LECTURE.hwnd
    monitor_two = QRect(1920, 0, 1920, 1040)
    resolved_hwnds = []

    def resolve_source(hwnd):
        resolved_hwnds.append(hwnd)
        return monitor_two

    monkeypatch.setattr(
        study_view_module,
        "_work_area_for_source_hwnd",
        resolve_source,
    )
    app = QApplication.instance() or QApplication([])
    popup = StudyConfirmationPopup()
    popup.present_request(request)
    app.processEvents()
    expected_x = monitor_two.x() + max(12, (monitor_two.width() - popup.width()) // 2)
    expected_y = monitor_two.y() + max(12, (monitor_two.height() - popup.height()) // 2)
    assert resolved_hwnds == [request.source_hwnd]
    assert popup.x() == expected_x
    assert popup.y() == expected_y
    popup.reset_presentation_epoch()
    app.processEvents()


def test_windows_acceptance_popup_hwnd_survives_controller_and_monitor_transport():
    enqueued = []
    controller = SimpleNamespace(
        _enqueue_command=lambda kind, payload: enqueued.append((kind, payload)) or True
    )
    assert ControlStationController._send_study_confirmation_callback(
        controller,
        "study_confirmation_popup_shown",
        "request-a",
        500,
        popup_hwnd=81_004,
    )
    kind, payload = enqueued[0]
    assert kind == "study_confirmation_popup_shown"
    assert payload["popup_hwnd"] == 81_004

    received = []

    class _Authority:
        def record_study_confirmation_popup_shown(self, **fields):
            received.append(fields)
            return True

        def drain_facts(self):
            return ()

    coordinator = object.__new__(WindowsMonitorCoordinator)
    coordinator.services = SimpleNamespace(resource_intent=_Authority())
    coordinator.telemetry_queue = queue.Queue()
    assert coordinator._handle_study_confirmation_command(kind, payload)
    assert received == [
        {
            "request_id": "request-a",
            "shown_monotonic_ns": 500,
            "popup_hwnd": 81_004,
        }
    ]


def test_phase31_a_study_b_off_task_then_return_a_reuses_exact_study_slot():
    session = _uncertain_session()
    study_a = _memory_surface(1)
    off_task_b = _memory_surface(2)
    _confirm_memory_resource(
        session,
        study_a,
        start_second=0,
        response=StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL,
    )
    _confirm_memory_resource(
        session,
        off_task_b,
        start_second=301,
        response=StudyConfirmationResponse.IM_COMING_BACK,
    )

    assert len(session.intent.study_memory_entries()) == 2
    returned = session.look(study_a, after_seconds=602)
    assert returned.verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert returned.verdict.confidence == 1.0
    assert returned.verdict.measured_classification is ResourceIntent.UNCERTAIN
    assert returned.verdict.measured_confidence == 0.50
    assert returned.verdict.user_confirmation is StudyUserConfirmation.STUDY
    assert returned.verdict.sine_contribution is SineContribution.WITHHELD
    assert not any(
        fact.kind == "STUDY_UNCERTAINTY_STARTED"
        for fact in session.intent.drain_facts()
    )


def test_phase31_seven_slots_reuse_without_duplicates_and_evict_exact_lru():
    session = _uncertain_session()
    surfaces = tuple(_memory_surface(number) for number in range(1, 9))
    requests = []
    for index, surface in enumerate(surfaces[:7]):
        requests.append(
            _confirm_memory_resource(
                session,
                surface,
                start_second=index * 301,
                response=(
                    StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL
                    if index % 2 == 0
                    else StudyConfirmationResponse.IM_COMING_BACK
                ),
            )
        )
    entries = session.intent.study_memory_entries()
    assert len(entries) == 7
    assert len({entry.resource_key for entry in entries}) == 7

    # Seeing resource 1 again reuses and touches its existing slot.
    session.look(surfaces[0], after_seconds=7 * 301)
    assert len(session.intent.study_memory_entries()) == 7
    session.intent.drain_facts()

    _confirm_memory_resource(
        session,
        surfaces[7],
        start_second=7 * 301 + 1,
        response=StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL,
    )
    remaining = {
        entry.resource_key for entry in session.intent.study_memory_entries()
    }
    assert len(remaining) == 7
    assert requests[0].resource_key in remaining
    assert requests[1].resource_key not in remaining

    returned_evicted = session.look(surfaces[1], after_seconds=7 * 301 + 302)
    assert returned_evicted.verdict.user_confirmation is StudyUserConfirmation.NONE
    assert returned_evicted.verdict.classification is ResourceIntent.UNCERTAIN


def test_phase31_lru_never_selects_the_current_active_resource():
    session = _uncertain_session()
    surfaces = tuple(_memory_surface(number) for number in range(11, 19))
    for index, surface in enumerate(surfaces[:7]):
        _confirm_memory_resource(
            session,
            surface,
            start_second=index * 301,
            response=StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL,
        )
    entries = session.intent.study_memory_entries()
    protected = entries[0]
    next_victim = entries[1]
    session.intent._active_resource_key = protected.resource_key
    from CORE_ENGINE.resource_intent import StudyConfirmationRecord

    session.intent._remember_confirmation(
        session.intent._context,
        StudyConfirmationRecord(
            study_context_token=session.intent._context.context_token,
            resource_key="synthetic-resource-eight",
            observation_token="synthetic-observation-eight",
            measured_classification=ResourceIntent.UNCERTAIN,
            measured_confidence=0.50,
            user_confirmation=StudyUserConfirmation.STUDY,
            effective_operational_state=StudyEffectiveState.STUDY_ALIGNED,
            confirmed_monotonic_ns=session.base_ns + 9_999 * NS,
            source="USER_CONFIRMED_STUDY",
        ),
    )
    keys = {entry.resource_key for entry in session.intent.study_memory_entries()}
    assert protected.resource_key in keys
    assert next_victim.resource_key not in keys
    assert "synthetic-resource-eight" in keys
    assert len(keys) == 7


def test_phase31_study_retirement_clears_all_seven_slots():
    session = _uncertain_session()
    for index in range(1, 8):
        _confirm_memory_resource(
            session,
            _memory_surface(30 + index),
            start_second=(index - 1) * 301,
            response=StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL,
        )
    assert len(session.intent.study_memory_entries()) == 7
    assert session.intent.retire_study_context(
        session.intent._context.context_token
    )
    assert session.intent.study_memory_entries() == ()


def test_phase31_control_card_uses_sine_applied_intervals_not_blacklist_target():
    app = QApplication.instance() or QApplication([])
    signal = SimpleNamespace(connect=lambda callback: None)
    page = ControlPage(
        engine=SimpleNamespace(
            pause=lambda: None,
            set_profile_type=lambda key: None,
            engine_status_changed=signal,
        ),
        lifecycle=SimpleNamespace(
            request_start=lambda: None,
            request_stop=lambda: None,
            request_emergency=lambda: None,
        ),
        profiles=SimpleNamespace(
            all_profiles=lambda: (
                SimpleNamespace(label="General", key="general"),
            ),
            set_active=lambda key: True,
        ),
    )
    page.render(
        SimpleNamespace(
            session_id=1,
            blacklist=SimpleNamespace(
                resource_label="YOUTUBE · LONG FORM",
                resource_title="Exact test resource",
                disposition="ACCUSED",
                state="THRESHOLD_REACHED",
                confidence="HIGH",
                reason="Stage-1 threshold reached",
                dwell_elapsed_seconds=623.0,
                dwell_target_seconds=300.0,
            ),
            mirl=None,
            cosine=None,
        )
    )
    assert page._dwell_value.text() == "10:23 / 05:00"

    page.render_sine(
        SimpleNamespace(
            stage=1,
            phase="ACTIVE",
            next_deadline_seconds=408.0,
            protected_red_active=False,
            stage_2_delay_seconds_applied=600.0,
            stage_3_delay_seconds_applied=795.0,
        )
    )
    assert page._dwell_value.text() == "03:12 / 10:00"

    page.render_sine(
        SimpleNamespace(
            stage=2,
            phase="ACTIVE",
            next_deadline_seconds=391.0,
            protected_red_active=False,
            stage_2_delay_seconds_applied=600.0,
            stage_3_delay_seconds_applied=795.0,
        )
    )
    assert page._dwell_value.text() == "06:44 / 13:15"

    page.render_sine(
        SimpleNamespace(
            stage=3,
            phase="PROTECTED_RED",
            next_deadline_seconds=None,
            protected_red_active=True,
            stage_2_delay_seconds_applied=600.0,
            stage_3_delay_seconds_applied=795.0,
        )
    )
    assert page._dwell_value.text() == "RETURN REQUIRED"
    source = inspect.getsource(ControlPage._render_current_authority_interval)
    assert "600" not in source and "795" not in source
    app.processEvents()


def test_phase31_missing_blacklist_target_withholds_clock_without_hiding_distraction():
    """A read-only classification path cannot invent a Stage-1 target."""

    session = _uncertain_session()
    session.intent._stage_one_target_seconds = None
    snapshot = session.look(MRBEAST, after_seconds=0)

    assert snapshot.verdict.classification is ResourceIntent.DISTRACTION
    assert snapshot.verdict.sine_contribution is SineContribution.NONE
    assert snapshot.verdict.off_task_dwell_seconds == 0.0
    assert session.intent._dwell_key is None


def test_phase31_resource_intent_panel_switches_from_stage_one_to_sine_authority():
    app = QApplication.instance() or QApplication([])
    session = _uncertain_session()
    session.look(MRBEAST, after_seconds=0)
    panel = ResourceIntentTelemetryPanel()
    panel.render(session.intent.live_view())
    assert panel._values["dwell"].text() == "00:00 / 05:00"

    panel.render_sine(
        SimpleNamespace(
            stage=1,
            phase="active",
            next_deadline_seconds=599.0,
            protected_red_active=False,
            stage_2_delay_seconds_applied=600.0,
            stage_3_delay_seconds_applied=795.0,
        )
    )
    assert panel._values["dwell"].text() == "00:01 / 10:00"

    panel.render_sine(
        SimpleNamespace(
            stage=2,
            phase="active",
            next_deadline_seconds=794.0,
            protected_red_active=False,
            stage_2_delay_seconds_applied=600.0,
            stage_3_delay_seconds_applied=795.0,
        )
    )
    assert panel._values["dwell"].text() == "00:01 / 13:15"

    panel.render_sine(
        SimpleNamespace(
            stage=3,
            phase="protected_red",
            next_deadline_seconds=None,
            protected_red_active=True,
            stage_2_delay_seconds_applied=600.0,
            stage_3_delay_seconds_applied=795.0,
        )
    )
    assert panel._values["dwell"].text() == "RETURN REQUIRED"

    projection_source = inspect.getsource(
        ResourceIntentTelemetryPanel._render_authoritative_dwell
    )
    connection_source = inspect.getsource(StudyView._connect_engine_signals)
    assert "600" not in projection_source and "795" not in projection_source
    assert "sine_watch_status_changed" in connection_source
    assert "self.resource_intent.render_sine" in connection_source
    app.processEvents()
