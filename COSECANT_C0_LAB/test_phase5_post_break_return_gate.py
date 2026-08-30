"""Phase 5 acceptance: the post-Normal-Break WELCOME BACK acknowledgement gate.

The locked law under test:

    NORMAL_BREAK_COMPLETED / NORMAL_BREAK_STOPPED  !=  SINE 2 DISPLAYED
    WELCOME BACK                                    !=  SINE 2

A factual break termination opens one acknowledgement gate on the SAME held
episode.  The user's I'M BACK on that exact gate surface closes the gate and
RE-ARMS the ordinary SINE-1 -> SINE-2 window from that acknowledgement -- it is
not itself a SINE-2 request.  SINE 2 exists only if eligible distraction
survives that whole window, after which SINE-2 -> SINE-3 timing, Activity pause
and MIRL recovery pause all continue unchanged.

    I'M BACK  !=  SINE 2 REQUESTED
    I'M BACK  ==  re-anchor the already-authorized 600 s (x F) SINE-1 window

Cases A/B/C/I are driven here end to end through the real Monitor handoff;
cases D/E/F/G/H stay with their existing owners:

    CASE D  test_phase3_normal_break_presentation.py
    CASE E  test_phase4_case2_presentation_release.py
    CASE F  test_phase4_case2_presentation_release.py
    CASE G  test_phase3_sine_activity_pause.py
    CASE H  test_phase3_sine_activity_pause.py
"""

from __future__ import annotations

import os
import queue
import threading
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication, QPushButton

import _lab  # noqa: F401 - installs the production tree on sys.path

from CORE_ENGINE.monitor import (
    SineAuthority as SineAuthorityProtocol,
    WindowsMonitorCoordinator,
)
from SINE.normal_break import NormalBreakAuthority
from SINE.popup import SinePopupWindow
from SINE.sine import (
    SineAuthority,
    SinePhase,
    SinePolicy,
    SineResponse,
    SineStage,
    SineSurface,
)


NS = 1_000_000_000


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


class ManualClock:
    def __init__(self, now: int = 1 * NS) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


class StorageProbe:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.normal_facts: list[object] = []

    def append_sine_facts(self, facts):
        self.order.extend(f"sine:{fact.kind}" for fact in facts)
        return True

    def append_normal_break_facts(self, facts):
        self.normal_facts.extend(facts)
        self.order.extend(f"normal:{fact.kind.value}" for fact in facts)
        return True

    def append_mirl_events(self, events):
        return True


class MirlProbe:
    def __init__(self) -> None:
        self.sine_facts: list[object] = []

    def record_sine_fact(self, fact):
        self.sine_facts.append(fact)

    def drain_events(self):
        return ()

    def observe(self, context):
        return ()

    def record_recovery_observation(self, observation):
        return ()


class TriggerProbe:
    def __init__(self) -> None:
        self.facts: list[object] = []

    def record_intervention_fact(self, fact):
        self.facts.append(fact)

    def evaluate(self, **kwargs):
        return None


class BlacklistProbe:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.paused = False
        self.pause_history: list[bool] = []

    def set_paused(self, value: bool) -> None:
        self.paused = bool(value)
        self.pause_history.append(bool(value))
        self.order.append(f"blacklist:{bool(value)}")


def _candidate():
    return SimpleNamespace(
        candidate_uid="phase5-candidate",
        session_id=1,
        profile_type="GENERAL",
        evidence=SimpleNamespace(
            observed_monotonic_ns=1 * NS,
            dwell_seconds=300.0,
            threshold_seconds=300.0,
            study_context_token="",
            resource_key="youtube:phase5-distraction",
            resource_observation_token="phase5-observation",
            surface_class="youtube_watch",
            browser_evidence_kind="certified_url",
            process_name="chrome",
            process_id=44,
            hwnd=11,
            platform_key="youtube",
        ),
    )


def _break_requested_sine(clock: ManualClock):
    sine = SineAuthority(policy=SinePolicy(), monotonic_ns=clock)
    sine.start_session(session_id=1, profile_type="GENERAL")
    assert sine.request_trigger(
        candidate=_candidate(),
        operational_event_id=1,
        mirl_display_token=SimpleNamespace(),
    )
    sine.advance(now_monotonic_ns=clock.now)
    request_id = sine.live_view().popup_request_id

    clock.now = 2 * NS
    assert sine.popup_shown(
        request_id=request_id,
        shown_monotonic_ns=clock.now,
        popup_hwnd=101,
    )
    sine.advance(now_monotonic_ns=clock.now)

    clock.now = 3 * NS
    assert sine.popup_response(
        request_id=request_id,
        response=SineResponse.REQUEST_BREAK,
        occurred_monotonic_ns=clock.now,
    )
    return sine, request_id, sine.advance(now_monotonic_ns=clock.now)


def _coordinator():
    clock = ManualClock()
    sine, request_id, response_facts = _break_requested_sine(clock)
    order: list[str] = []
    break_ids = iter(("phase5-break", "phase5-break-2"))
    services = SimpleNamespace(
        sine=sine,
        normal_break=NormalBreakAuthority(
            monotonic_ns=clock,
            break_id_factory=lambda: next(break_ids),
        ),
        storage=StorageProbe(order),
        mirl=MirlProbe(),
        trigger=TriggerProbe(),
        blacklist=BlacklistProbe(order),
    )
    coordinator = WindowsMonitorCoordinator(
        profile_type="GENERAL",
        services=services,
        foreground_reader=SimpleNamespace(),
        stop_event=threading.Event(),
        pause_event=threading.Event(),
        ready_event=threading.Event(),
        loop_stopped_event=threading.Event(),
        cleanup_complete_event=threading.Event(),
        telemetry_queue=queue.Queue(),
        command_queue=queue.Queue(),
        poll_seconds=0.1,
    )
    coordinator.session_id = 1
    coordinator._monotonic_ns = clock
    for fact in response_facts:
        coordinator._route_sine_fact(fact, None)

    pending = services.normal_break.snapshot()
    payload = SimpleNamespace(
        break_id=pending.break_id,
        generation=pending.generation,
        episode_uid=pending.episode_uid,
        candidate_uid=pending.candidate_uid,
        source_sine_popup_request_id=pending.source_sine_popup_request_id,
        selected_minutes=5,
    )
    clock.now = 4 * NS
    assert coordinator._start_normal_break(payload)
    return coordinator, services, sine, clock, payload


def _terminate_break(coordinator, services, sine, clock, *, stop: bool):
    """End the break naturally or by STOP; both must reach the same gate."""

    if stop:
        clock.now = 60 * NS
        assert coordinator._handle_normal_break_command(
            "normal_break_stop",
            SimpleNamespace(
                break_id=services.normal_break.snapshot().break_id,
                generation=services.normal_break.snapshot().generation,
                episode_uid=sine.live_view().episode_uid,
                candidate_uid=sine.live_view().candidate_uid,
                source_sine_popup_request_id=(
                    services.normal_break.snapshot().source_sine_popup_request_id
                ),
            ),
        )
    else:
        deadline = services.normal_break.snapshot().deadline_monotonic_ns
        clock.now = deadline + 3 * NS
        assert coordinator._advance_normal_break(clock.now, None)


def _show_and_route(coordinator, sine, clock, *, at_ns: int, hwnd: int) -> str:
    clock.now = at_ns
    request_id = sine.live_view().popup_request_id
    assert request_id
    assert sine.popup_shown(
        request_id=request_id,
        shown_monotonic_ns=at_ns,
        popup_hwnd=hwnd,
    )
    for fact in sine.advance(now_monotonic_ns=at_ns):
        coordinator._route_sine_fact(fact, None)
    return request_id


# ---------------------------------------------------------------------------
# CASE A / CASE B -- both terminal routes reach the same acknowledgement gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("stop", "completion_kind"),
    [
        (False, "NORMAL_BREAK_COMPLETED"),
        (True, "NORMAL_BREAK_STOPPED"),
    ],
)
def test_break_termination_opens_the_gate_and_requests_no_sine2(
    stop,
    completion_kind,
):
    coordinator, services, sine, clock, payload = _coordinator()
    before = sine.live_view()
    assert before.normal_break_held is True

    _terminate_break(coordinator, services, sine, clock, stop=stop)

    order = services.storage.order
    assert f"normal:{completion_kind}" in order
    assert "sine:SINE_POST_NORMAL_BREAK_RETURN_PENDING" in order
    assert "sine:SINE_POST_BREAK_RETURN_GATE_REQUESTED" in order
    # THE FORBIDDEN OLD SEQUENCE: a SINE popup request off the break terminal.
    assert "sine:SINE_POPUP_REQUESTED" not in order[order.index(f"normal:{completion_kind}"):]

    view = sine.live_view()
    assert view.episode_uid == before.episode_uid
    assert view.candidate_uid == before.candidate_uid
    assert view.normal_break_held is False
    assert view.post_normal_break_return_pending is True
    assert view.post_normal_break_completion_kind == completion_kind
    assert view.stage is SineStage.SINE_1
    assert view.stage_3_deadline_monotonic_ns is None
    assert view.next_deadline_seconds is None
    assert services.blacklist.paused is False

    # No new episode, no new candidate, no new trigger, no fake SINE 1.
    gate_facts = [
        fact
        for fact in services.mirl.sine_facts
        if fact.kind == "SINE_POST_BREAK_RETURN_GATE_REQUESTED"
    ]
    assert len(gate_facts) == 1
    gate = gate_facts[0].popup
    assert gate.surface is SineSurface.POST_NORMAL_BREAK_RETURN_GATE
    assert gate.stage is SineStage.NONE
    assert gate.episode_uid == before.episode_uid
    assert gate.candidate_uid == before.candidate_uid
    assert gate.operational_event_id == before.operational_event_id
    assert not any(
        fact.kind == "SINE_DISPLAYED" and fact.stage in (2, 3)
        for fact in services.mirl.sine_facts
    )


# ---------------------------------------------------------------------------
# CASE A / CASE B / CASE I -- I'M BACK is the release fact
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stop", [False, True])
def test_acknowledgement_rearms_the_sine1_window_and_never_escalates(stop):
    coordinator, services, sine, clock, payload = _coordinator()
    before = sine.live_view()
    _terminate_break(coordinator, services, sine, clock, stop=stop)

    gate_shown_ns = clock.now + 1 * NS
    gate_request_id = _show_and_route(
        coordinator, sine, clock, at_ns=gate_shown_ns, hwnd=501
    )
    assert "sine:SINE_POST_BREAK_RETURN_GATE_DISPLAYED" in services.storage.order
    assert "sine:SINE_DISPLAYED" not in services.storage.order[
        services.storage.order.index("sine:SINE_POST_BREAK_RETURN_GATE_REQUESTED"):
    ]
    assert sine.live_view().phase is SinePhase.ACTIVE
    assert sine.live_view().stage_3_deadline_monotonic_ns is None

    acknowledged_ns = gate_shown_ns + 2 * NS
    clock.now = acknowledged_ns
    assert sine.popup_response(
        request_id=gate_request_id,
        response=SineResponse.RETURN_TO_FOCUS,
        occurred_monotonic_ns=acknowledged_ns,
    )
    facts = sine.advance(now_monotonic_ns=acknowledged_ns)
    for fact in facts:
        coordinator._route_sine_fact(fact, None)

    kinds = [fact.kind for fact in facts]
    assert "SINE_POST_BREAK_RETURN_ACKNOWLEDGED" in kinds
    assert "SINE_STAGE_2_REARMED_AFTER_POST_BREAK_RETURN" in kinds
    assert "SINE_RETURN_INTENT_RECORDED" not in kinds
    # THE DEFECT THE 2026-08-27 WINDOWS RUN EXPOSED: acknowledgement used to
    # request SINE 2 in the same instant.  It must not.
    assert "SINE_POPUP_REQUESTED" not in kinds

    stage_2_gap_ns = int(SinePolicy().stage_2_delay_seconds * NS)
    after = sine.live_view()
    # CASE I -- identity is unbroken across SINE1 -> break -> gate -> SINE 2.
    assert after.episode_uid == before.episode_uid
    assert after.candidate_uid == before.candidate_uid
    assert after.operational_event_id == before.operational_event_id
    assert after.post_normal_break_return_pending is False
    assert after.stage is SineStage.SINE_1
    assert after.phase is SinePhase.ACTIVE
    assert after.stage_3_deadline_monotonic_ns is None
    assert after.stage_2_deadline_monotonic_ns == acknowledged_ns + stage_2_gap_ns
    assert after.next_deadline_seconds == SinePolicy().stage_2_delay_seconds

    # One second short of the window: still SINE 1, still no surface.
    early_ns = acknowledged_ns + stage_2_gap_ns - 1 * NS
    clock.now = early_ns
    early_facts = sine.advance(now_monotonic_ns=early_ns)
    for fact in early_facts:
        coordinator._route_sine_fact(fact, None)
    assert "SINE_POPUP_REQUESTED" not in {fact.kind for fact in early_facts}
    assert sine.live_view().stage is SineStage.SINE_1

    # At the deadline SINE 2 is requested, anchored to the acknowledgement.
    due_ns = acknowledged_ns + stage_2_gap_ns
    clock.now = due_ns
    due_facts = sine.advance(now_monotonic_ns=due_ns)
    for fact in due_facts:
        coordinator._route_sine_fact(fact, None)
    requests = [fact.popup for fact in due_facts if fact.kind == "SINE_POPUP_REQUESTED"]
    assert len(requests) == 1
    assert requests[0].stage is SineStage.SINE_2
    assert requests[0].requested_monotonic_ns == due_ns

    # Only the FACTUAL SINE-2 display arms SINE 3, at the unchanged 795 s.
    sine_two_shown_ns = due_ns + 9 * NS
    _show_and_route(coordinator, sine, clock, at_ns=sine_two_shown_ns, hwnd=502)
    armed = sine.live_view()
    assert armed.stage is SineStage.SINE_2
    assert armed.stage_3_deadline_monotonic_ns == (
        sine_two_shown_ns + int(SinePolicy().stage_3_delay_seconds * NS)
    )
    # Phase-1 provenance survives the gate, so this exact SINE 2 keeps its
    # MIRL return-entry withholding eligibility.
    assert armed.post_normal_break_completion_kind in {
        "NORMAL_BREAK_COMPLETED",
        "NORMAL_BREAK_STOPPED",
    }


def test_no_new_trigger_or_episode_is_founded_during_the_rearmed_window():
    """The re-armed window is the SAME episode, not a fresh SINE-1 watch."""

    coordinator, services, sine, clock, payload = _coordinator()
    before = sine.live_view()
    _terminate_break(coordinator, services, sine, clock, stop=False)
    gate_shown_ns = clock.now + 1 * NS
    gate_request_id = _show_and_route(
        coordinator, sine, clock, at_ns=gate_shown_ns, hwnd=507
    )
    acknowledged_ns = gate_shown_ns + 1 * NS
    clock.now = acknowledged_ns
    assert sine.popup_response(
        request_id=gate_request_id,
        response=SineResponse.RETURN_TO_FOCUS,
        occurred_monotonic_ns=acknowledged_ns,
    )
    for fact in sine.advance(now_monotonic_ns=acknowledged_ns):
        coordinator._route_sine_fact(fact, None)

    # Monitor still refuses to found a new trigger: one live episode owns
    # intervention for the whole re-armed window.
    assert coordinator._sine_owns_intervention() is True
    mid_ns = acknowledged_ns + int(
        SinePolicy().stage_2_delay_seconds * NS / 2
    )
    clock.now = mid_ns
    mid_facts = sine.advance(now_monotonic_ns=mid_ns)
    for fact in mid_facts:
        coordinator._route_sine_fact(fact, None)
    assert coordinator._sine_owns_intervention() is True

    view = sine.live_view()
    assert view.episode_uid == before.episode_uid
    assert view.candidate_uid == before.candidate_uid
    assert view.stage is SineStage.SINE_1
    # Nothing at all is manufactured mid-window: no fake SINE 1, no SINE 2,
    # no second gate.
    assert mid_facts == ()
    routed_after_ack = services.storage.order[
        services.storage.order.index("sine:SINE_POST_BREAK_RETURN_ACKNOWLEDGED"):
    ]
    assert "sine:SINE_POPUP_REQUESTED" not in routed_after_ack
    assert "sine:SINE_POST_BREAK_RETURN_GATE_REQUESTED" not in routed_after_ack
    assert "sine:SINE_TRIGGER_ACCEPTED" not in routed_after_ack


# ---------------------------------------------------------------------------
# CASE C -- an ignored gate never escalates
# ---------------------------------------------------------------------------


def test_ignored_gate_produces_no_sine2_and_no_sine3_ever():
    coordinator, services, sine, clock, payload = _coordinator()
    _terminate_break(coordinator, services, sine, clock, stop=False)
    gate_shown_ns = clock.now + 1 * NS
    gate_request_id = _show_and_route(
        coordinator, sine, clock, at_ns=gate_shown_ns, hwnd=503
    )

    far_future_ns = gate_shown_ns + int(
        (SinePolicy().stage_3_delay_seconds + 3600.0) * NS
    )
    clock.now = far_future_ns
    facts = sine.advance(now_monotonic_ns=far_future_ns)
    for fact in facts:
        coordinator._route_sine_fact(fact, None)

    assert [fact.kind for fact in facts] == []
    view = sine.live_view()
    assert view.stage is SineStage.SINE_1
    assert view.post_normal_break_return_pending is True
    assert view.protected_red_active is False
    assert view.stage_3_deadline_monotonic_ns is None
    assert view.popup_request_id == gate_request_id


# ---------------------------------------------------------------------------
# Gate integrity
# ---------------------------------------------------------------------------


def test_a_lost_gate_surface_is_restored_not_abandoned():
    coordinator, services, sine, clock, payload = _coordinator()
    _terminate_break(coordinator, services, sine, clock, stop=False)
    gate_shown_ns = clock.now + 1 * NS
    gate_request_id = _show_and_route(
        coordinator, sine, clock, at_ns=gate_shown_ns, hwnd=504
    )

    lost_ns = gate_shown_ns + 1 * NS
    assert sine.popup_closed(
        request_id=gate_request_id,
        reason="surface_lost",
        occurred_monotonic_ns=lost_ns,
    )
    kinds = {fact.kind for fact in sine.advance(now_monotonic_ns=lost_ns)}
    assert "SINE_POST_BREAK_RETURN_GATE_SURFACE_LOST" in kinds
    assert "SINE_POST_BREAK_RETURN_GATE_REQUESTED" in kinds

    restored = sine.live_view()
    assert restored.post_normal_break_return_pending is True
    assert restored.popup_request_id != gate_request_id


def test_a_stale_gate_occurrence_cannot_acknowledge_the_return():
    coordinator, services, sine, clock, payload = _coordinator()
    _terminate_break(coordinator, services, sine, clock, stop=False)
    gate_shown_ns = clock.now + 1 * NS
    stale_request_id = _show_and_route(
        coordinator, sine, clock, at_ns=gate_shown_ns, hwnd=505
    )

    lost_ns = gate_shown_ns + 1 * NS
    assert sine.popup_closed(
        request_id=stale_request_id,
        reason="surface_lost",
        occurred_monotonic_ns=lost_ns,
    )
    sine.advance(now_monotonic_ns=lost_ns)

    assert (
        sine.popup_response(
            request_id=stale_request_id,
            response=SineResponse.RETURN_TO_FOCUS,
            occurred_monotonic_ns=lost_ns + 1 * NS,
        )
        is False
    )
    assert sine.live_view().post_normal_break_return_pending is True


def test_gate_refuses_every_response_that_is_not_the_return_action():
    coordinator, services, sine, clock, payload = _coordinator()
    _terminate_break(coordinator, services, sine, clock, stop=False)
    gate_shown_ns = clock.now + 1 * NS
    gate_request_id = _show_and_route(
        coordinator, sine, clock, at_ns=gate_shown_ns, hwnd=506
    )

    for response in (
        SineResponse.REQUEST_BREAK,
        SineResponse.CONTINUE_SINE,
        SineResponse.THIS_IS_STUDY_MATERIAL,
    ):
        assert (
            sine.popup_response(
                request_id=gate_request_id,
                response=response,
                occurred_monotonic_ns=gate_shown_ns + 1 * NS,
            )
            is False
        )
    assert sine.live_view().post_normal_break_return_pending is True


# ---------------------------------------------------------------------------
# Interface contract (roadmap section 16)
# ---------------------------------------------------------------------------


def test_monitor_sine_protocol_declares_the_full_authority_surface():
    for name in (
        "enter_post_normal_break_return_gate",
        "pause_escalation_for_activity",
        "resume_escalation_after_activity",
    ):
        assert hasattr(SineAuthorityProtocol, name)
    assert not hasattr(SineAuthorityProtocol, "resume_from_normal_break_as_sine2")
    assert isinstance(SineAuthority(), SineAuthorityProtocol)


# ---------------------------------------------------------------------------
# Presentation contract
# ---------------------------------------------------------------------------


def _gate_request(stop: bool = False):
    coordinator, services, sine, clock, payload = _coordinator()
    _terminate_break(coordinator, services, sine, clock, stop=stop)
    return next(
        fact.popup
        for fact in services.mirl.sine_facts
        if fact.kind == "SINE_POST_BREAK_RETURN_GATE_REQUESTED"
    )


def test_gate_window_renders_welcome_back_without_claiming_a_sine_stage(app):
    window = SinePopupWindow(_gate_request())
    try:
        assert window.is_post_normal_break_return_gate is True
        assert window.is_protected_red is False
        assert window.request.presentation.badge != "SINE 2"
        assert window._headline.text() == "WELCOME BACK"
        buttons = window.findChildren(QPushButton)
        assert [button.text() for button in buttons] == ["I'M BACK"]
    finally:
        window.force_close("test_teardown")
        app.processEvents()


def test_gate_button_emits_return_intent_without_closing_itself(app):
    window = SinePopupWindow(_gate_request(stop=True))
    emitted = []
    window.user_action.connect(
        lambda request_id, response, occurred_ns: emitted.append(
            (request_id, response)
        )
    )
    try:
        window._emit_action(SineResponse.RETURN_TO_FOCUS)
        assert emitted == [(window.request.request_id, "return_to_focus")]
        assert window._closed_reported is False
    finally:
        window.force_close("test_teardown")
        app.processEvents()


def test_sine_two_can_no_longer_be_rendered_as_the_green_welcome_back(app):
    gate = _gate_request()
    import dataclasses

    from SINE.sine import _weber_fechner_projection

    disguised = dataclasses.replace(
        gate,
        stage=SineStage.SINE_2,
        surface=SineSurface.INTERVENTION,
        presentation=dataclasses.replace(
            gate.presentation,
            weber_fechner=_weber_fechner_projection(SineStage.SINE_2),
        ),
    )
    with pytest.raises(ValueError):
        SinePopupWindow(disguised)


def test_a_gate_request_may_not_carry_a_sine_stage(app):
    gate = _gate_request()
    import dataclasses

    with pytest.raises(ValueError):
        SinePopupWindow(dataclasses.replace(gate, stage=SineStage.SINE_2))
