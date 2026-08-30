"""External Phase-2 verification for Normal Break physiology.

The production tree is imported read-only.  Tests and test doubles remain in
this external lab; Phase 3 Controller/popup surfaces are intentionally absent.
"""

from __future__ import annotations

import inspect
import queue
import threading
from types import SimpleNamespace

import pytest

import _lab  # noqa: F401 - installs the production tree on sys.path

from CORE_ENGINE.monitor import WindowsMonitorCoordinator
from SINE.normal_break import NormalBreakAuthority, NormalBreakState
from SINE.sine import (
    PopupState,
    SineAuthority,
    SinePhase,
    SinePolicy,
    SineResponse,
    SineStage,
    SineSurface,
)


NS = 1_000_000_000


class ManualClock:
    def __init__(self, now: int = NS) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now


def _candidate(uid: str = "normal-break-candidate"):
    return SimpleNamespace(
        candidate_uid=uid,
        session_id=1,
        profile_type="GENERAL",
        evidence=SimpleNamespace(
            observed_monotonic_ns=NS,
            dwell_seconds=300.0,
            threshold_seconds=300.0,
            study_context_token="",
            resource_key="youtube:normal-break",
            resource_observation_token="normal-break-observation",
            surface_class="youtube_watch",
            browser_evidence_kind="certified_url",
            process_name="chrome",
            process_id=20,
            hwnd=10,
            platform_key="youtube",
        ),
    )


def _break_requested_sine(*, stage_2_delay: float = 600.0):
    clock = ManualClock()
    sine = SineAuthority(
        policy=SinePolicy(
            stage_1_visible_seconds=45.0,
            stage_2_delay_seconds=stage_2_delay,
            stage_2_visible_seconds=60.0,
            stage_3_delay_seconds=795.0,
            stage_3_visible_seconds=600.0,
        ),
        monotonic_ns=clock,
    )
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
    response_facts = sine.advance(now_monotonic_ns=clock.now)
    assert "SINE_BREAK_REQUESTED" in {fact.kind for fact in response_facts}
    return sine, clock, request_id, response_facts


def _hold(sine, request_id, *, started_ns=4 * NS):
    view = sine.live_view()
    assert sine.hold_for_normal_break(
        candidate_uid=view.candidate_uid,
        episode_uid=view.episode_uid,
        break_id="break-1",
        break_generation=1,
        started_monotonic_ns=started_ns,
        source_popup_request_id=request_id,
    )
    sine.advance(now_monotonic_ns=started_ns)
    return view


def test_p2_same_episode_is_held_and_all_sine_deadlines_are_suppressed():
    sine, clock, request_id, _ = _break_requested_sine()
    before = _hold(sine, request_id)

    clock.now = 10_000 * NS
    facts = sine.advance(now_monotonic_ns=clock.now)
    held = sine.live_view()

    assert held.normal_break_held is True
    assert held.episode_uid == before.episode_uid
    assert held.candidate_uid == before.candidate_uid
    assert held.stage is SineStage.SINE_1
    assert "SINE_POPUP_REQUESTED" not in {fact.kind for fact in facts}


@pytest.mark.parametrize(
    "completion_kind",
    ["NORMAL_BREAK_COMPLETED", "NORMAL_BREAK_STOPPED"],
)
def test_p2_completion_or_stop_opens_the_return_gate_and_never_sine2(
    completion_kind,
):
    """CASE A / CASE B -- the break terminal fact opens the gate, not SINE 2."""

    sine, clock, request_id, _ = _break_requested_sine()
    before = _hold(sine, request_id)
    end_ns = 304 * NS

    assert sine.enter_post_normal_break_return_gate(
        candidate_uid=before.candidate_uid,
        episode_uid=before.episode_uid,
        break_id="break-1",
        break_generation=1,
        occurred_monotonic_ns=end_ns,
        completion_kind=completion_kind,
    )
    facts = sine.advance(now_monotonic_ns=end_ns)
    after = sine.live_view()

    assert after.episode_uid == before.episode_uid
    assert after.candidate_uid == before.candidate_uid
    assert after.phase is SinePhase.WAITING_FOR_DISPLAY
    assert after.normal_break_held is False
    assert after.post_normal_break_return_pending is True
    assert after.post_normal_break_completion_kind == completion_kind
    assert after.stage is SineStage.SINE_1
    assert after.stage_3_deadline_monotonic_ns is None

    kinds = {fact.kind for fact in facts}
    assert "SINE_POST_NORMAL_BREAK_RETURN_PENDING" in kinds
    assert "SINE_POST_BREAK_RETURN_GATE_REQUESTED" in kinds
    assert "SINE_POPUP_REQUESTED" not in kinds

    gates = [
        fact.popup
        for fact in facts
        if fact.kind == "SINE_POST_BREAK_RETURN_GATE_REQUESTED"
    ]
    assert len(gates) == 1
    assert gates[0].surface is SineSurface.POST_NORMAL_BREAK_RETURN_GATE
    assert gates[0].stage is SineStage.NONE
    assert gates[0].requested_monotonic_ns == end_ns
    assert gates[0].presentation.headline == "WELCOME BACK"
    assert gates[0].presentation.world == "green"
    assert gates[0].presentation.allowed_responses == (
        SineResponse.RETURN_TO_FOCUS,
    )


@pytest.mark.parametrize(
    "completion_kind",
    ["NORMAL_BREAK_COMPLETED", "NORMAL_BREAK_STOPPED"],
)
def test_p2_acknowledged_gate_rearms_the_sine1_window_instead_of_sine2(
    completion_kind,
):
    """CASE A / CASE B / CASE I -- I'M BACK re-arms, it does not escalate."""

    sine, clock, request_id, _ = _break_requested_sine()
    before = _hold(sine, request_id)
    end_ns = 304 * NS
    assert sine.enter_post_normal_break_return_gate(
        candidate_uid=before.candidate_uid,
        episode_uid=before.episode_uid,
        break_id="break-1",
        break_generation=1,
        occurred_monotonic_ns=end_ns,
        completion_kind=completion_kind,
    )
    sine.advance(now_monotonic_ns=end_ns)

    gate_request_id = sine.live_view().popup_request_id
    gate_shown_ns = end_ns + 1 * NS
    assert sine.popup_shown(
        request_id=gate_request_id,
        shown_monotonic_ns=gate_shown_ns,
        popup_hwnd=303,
    )
    displayed_facts = sine.advance(now_monotonic_ns=gate_shown_ns)
    displayed_kinds = {fact.kind for fact in displayed_facts}
    assert "SINE_POST_BREAK_RETURN_GATE_DISPLAYED" in displayed_kinds
    assert "SINE_DISPLAYED" not in displayed_kinds
    assert "SINE_STAGE_3_SCHEDULED" not in displayed_kinds
    assert sine.live_view().stage is SineStage.SINE_1
    assert sine.live_view().stage_3_deadline_monotonic_ns is None

    acknowledged_ns = gate_shown_ns + 2 * NS
    assert sine.popup_response(
        request_id=gate_request_id,
        response=SineResponse.RETURN_TO_FOCUS,
        occurred_monotonic_ns=acknowledged_ns,
    )
    facts = sine.advance(now_monotonic_ns=acknowledged_ns)
    kinds = {fact.kind for fact in facts}
    assert "SINE_POST_BREAK_RETURN_ACKNOWLEDGED" in kinds
    assert "SINE_STAGE_2_REARMED_AFTER_POST_BREAK_RETURN" in kinds
    # The gate is its own surface: it does not masquerade as ordinary
    # SINE return intent.
    assert "SINE_RETURN_INTENT_RECORDED" not in kinds
    # THE DEFECT THIS TEST OWNS: acknowledgement must NOT request SINE 2.
    assert "SINE_POPUP_REQUESTED" not in kinds

    stage_2_gap_ns = int(SinePolicy().stage_2_delay_seconds * NS)
    clock.now = acknowledged_ns
    after = sine.live_view()
    assert after.episode_uid == before.episode_uid
    assert after.candidate_uid == before.candidate_uid
    assert after.operational_event_id == before.operational_event_id
    assert after.post_normal_break_return_pending is False
    assert after.post_normal_break_completion_kind == completion_kind
    assert after.stage is SineStage.SINE_1
    assert after.phase is SinePhase.ACTIVE
    assert after.stage_3_deadline_monotonic_ns is None
    # No new constant: the same authorized SINE-1 -> SINE-2 gap, re-anchored.
    assert after.stage_2_deadline_monotonic_ns == acknowledged_ns + stage_2_gap_ns
    assert after.next_deadline_seconds == SinePolicy().stage_2_delay_seconds

    # One second early: still nothing.
    early_ns = acknowledged_ns + stage_2_gap_ns - 1 * NS
    assert "SINE_POPUP_REQUESTED" not in {
        fact.kind for fact in sine.advance(now_monotonic_ns=early_ns)
    }
    assert sine.live_view().stage is SineStage.SINE_1

    # At the deadline: SINE 2 at last, as the ordinary amber stage.
    due_ns = acknowledged_ns + stage_2_gap_ns
    due_facts = sine.advance(now_monotonic_ns=due_ns)
    requests = [fact.popup for fact in due_facts if fact.kind == "SINE_POPUP_REQUESTED"]
    assert len(requests) == 1
    assert requests[0].stage is SineStage.SINE_2
    assert requests[0].surface is SineSurface.INTERVENTION
    assert requests[0].requested_monotonic_ns == due_ns
    # Phase 3 intentionally removes the visible CONTINUE SINE choice while
    # retaining the compatibility enum/handler.
    assert requests[0].presentation.allowed_responses == (
        SineResponse.RETURN_TO_FOCUS,
    )
    # WELCOME BACK is the gate; the released SINE 2 is the ordinary amber
    # stage, never a second green surface.
    assert requests[0].presentation.headline == "Still Here?"
    assert requests[0].presentation.world == "amber"
    assert sine.live_view().episode_uid == before.episode_uid


def test_p2_ignored_gate_never_escalates_to_sine3():
    """CASE C -- no acknowledgement means no SINE 2, therefore no SINE 3."""

    sine, clock, request_id, _ = _break_requested_sine()
    before = _hold(sine, request_id)
    end_ns = 304 * NS
    assert sine.enter_post_normal_break_return_gate(
        candidate_uid=before.candidate_uid,
        episode_uid=before.episode_uid,
        break_id="break-1",
        break_generation=1,
        occurred_monotonic_ns=end_ns,
        completion_kind="NORMAL_BREAK_COMPLETED",
    )
    sine.advance(now_monotonic_ns=end_ns)
    gate_request_id = sine.live_view().popup_request_id
    gate_shown_ns = end_ns + 1 * NS
    assert sine.popup_shown(
        request_id=gate_request_id,
        shown_monotonic_ns=gate_shown_ns,
        popup_hwnd=304,
    )
    sine.advance(now_monotonic_ns=gate_shown_ns)

    far_future_ns = gate_shown_ns + int(
        (SinePolicy().stage_3_delay_seconds + 600.0) * NS
    )
    kinds = {
        fact.kind for fact in sine.advance(now_monotonic_ns=far_future_ns)
    }
    assert "SINE_POPUP_REQUESTED" not in kinds
    assert "SINE_POPUP_EXPIRED" not in kinds
    view = sine.live_view()
    assert view.stage is SineStage.SINE_1
    assert view.post_normal_break_return_pending is True
    assert view.stage_3_deadline_monotonic_ns is None
    assert view.protected_red_active is False
    assert view.popup_request_id == gate_request_id


def test_p2_gate_refuses_the_generic_activity_clock():
    """CASE G boundary -- the gate is a specialist hold, not ordinary Activity."""

    sine, clock, request_id, _ = _break_requested_sine()
    before = _hold(sine, request_id)
    end_ns = 304 * NS
    assert sine.enter_post_normal_break_return_gate(
        candidate_uid=before.candidate_uid,
        episode_uid=before.episode_uid,
        break_id="break-1",
        break_generation=1,
        occurred_monotonic_ns=end_ns,
        completion_kind="NORMAL_BREAK_COMPLETED",
    )
    sine.advance(now_monotonic_ns=end_ns)
    gate_request_id = sine.live_view().popup_request_id
    gate_shown_ns = end_ns + 1 * NS
    assert sine.popup_shown(
        request_id=gate_request_id,
        shown_monotonic_ns=gate_shown_ns,
        popup_hwnd=305,
    )
    sine.advance(now_monotonic_ns=gate_shown_ns)

    later_ns = gate_shown_ns + 1 * NS
    assert (
        sine.pause_escalation_for_activity(
            candidate_uid=before.candidate_uid,
            occurred_monotonic_ns=later_ns,
            evidence_source="monitor_ordinary_activity",
        )
        is False
    )
    assert (
        sine.resume_escalation_after_activity(
            candidate_uid=before.candidate_uid,
            occurred_monotonic_ns=later_ns,
            evidence_source="monitor_non_activity_policy",
        )
        is False
    )
    assert sine.live_view().activity_clock_paused is False
    assert sine.live_view().post_normal_break_return_pending is True


def test_p2_rearmed_window_is_eligible_time_not_wall_clock():
    """Phase-3 Activity keeps its authority over the re-armed SINE-1 window."""

    sine, clock, request_id, _ = _break_requested_sine()
    before = _hold(sine, request_id)
    end_ns = 304 * NS
    assert sine.enter_post_normal_break_return_gate(
        candidate_uid=before.candidate_uid,
        episode_uid=before.episode_uid,
        break_id="break-1",
        break_generation=1,
        occurred_monotonic_ns=end_ns,
        completion_kind="NORMAL_BREAK_COMPLETED",
    )
    sine.advance(now_monotonic_ns=end_ns)
    gate_request_id = sine.live_view().popup_request_id
    gate_shown_ns = end_ns + 1 * NS
    assert sine.popup_shown(
        request_id=gate_request_id,
        shown_monotonic_ns=gate_shown_ns,
        popup_hwnd=306,
    )
    sine.advance(now_monotonic_ns=gate_shown_ns)
    acknowledged_ns = gate_shown_ns + 1 * NS
    assert sine.popup_response(
        request_id=gate_request_id,
        response=SineResponse.RETURN_TO_FOCUS,
        occurred_monotonic_ns=acknowledged_ns,
    )
    sine.advance(now_monotonic_ns=acknowledged_ns)

    # 100 s of the window burn down, then ordinary Activity takes over.
    paused_ns = acknowledged_ns + 100 * NS
    assert sine.pause_escalation_for_activity(
        candidate_uid=before.candidate_uid,
        occurred_monotonic_ns=paused_ns,
        evidence_source="monitor_ordinary_activity",
    )
    sine.advance(now_monotonic_ns=paused_ns)
    remaining = SinePolicy().stage_2_delay_seconds - 100.0
    assert sine.live_view().activity_clock_paused is True
    assert sine.live_view().next_deadline_seconds == remaining

    # Hours of ordinary Activity cannot escalate a paused window.
    idle_ns = paused_ns + 3600 * NS
    assert "SINE_POPUP_REQUESTED" not in {
        fact.kind for fact in sine.advance(now_monotonic_ns=idle_ns)
    }
    assert sine.live_view().stage is SineStage.SINE_1

    resumed_ns = idle_ns + 1 * NS
    assert sine.resume_escalation_after_activity(
        candidate_uid=before.candidate_uid,
        occurred_monotonic_ns=resumed_ns,
        evidence_source="monitor_sine_driving_distraction",
    )
    sine.advance(now_monotonic_ns=resumed_ns)
    assert sine.live_view().stage_2_deadline_monotonic_ns == (
        resumed_ns + int(remaining * NS)
    )

    due_ns = resumed_ns + int(remaining * NS)
    requests = [
        fact
        for fact in sine.advance(now_monotonic_ns=due_ns)
        if fact.kind == "SINE_POPUP_REQUESTED"
    ]
    assert len(requests) == 1
    assert requests[0].stage == 2


def test_p2_post_break_sine3_deadline_anchors_only_on_factual_sine2_display():
    """CASE A timing -- SINE 3 is armed by the SINE-2 display, not the gate."""

    sine, clock, request_id, _ = _break_requested_sine()
    before = _hold(sine, request_id)
    end_ns = 304 * NS
    assert sine.enter_post_normal_break_return_gate(
        candidate_uid=before.candidate_uid,
        episode_uid=before.episode_uid,
        break_id="break-1",
        break_generation=1,
        occurred_monotonic_ns=end_ns,
        completion_kind="NORMAL_BREAK_COMPLETED",
    )
    sine.advance(now_monotonic_ns=end_ns)
    assert sine.live_view().stage_3_deadline_monotonic_ns is None

    gate_request_id = sine.live_view().popup_request_id
    gate_shown_ns = end_ns + 1 * NS
    assert sine.popup_shown(
        request_id=gate_request_id,
        shown_monotonic_ns=gate_shown_ns,
        popup_hwnd=201,
    )
    sine.advance(now_monotonic_ns=gate_shown_ns)
    assert sine.live_view().stage_3_deadline_monotonic_ns is None

    acknowledged_ns = gate_shown_ns + 3 * NS
    assert sine.popup_response(
        request_id=gate_request_id,
        response=SineResponse.RETURN_TO_FOCUS,
        occurred_monotonic_ns=acknowledged_ns,
    )
    sine.advance(now_monotonic_ns=acknowledged_ns)
    assert sine.live_view().stage_3_deadline_monotonic_ns is None

    # The re-armed SINE-1 window must elapse before SINE 2 exists at all.
    due_ns = acknowledged_ns + int(SinePolicy().stage_2_delay_seconds * NS)
    sine.advance(now_monotonic_ns=due_ns)
    assert sine.live_view().stage_3_deadline_monotonic_ns is None

    shown_ns = due_ns + 7 * NS
    stage_2_request = sine.live_view().popup_request_id
    assert sine.popup_shown(
        request_id=stage_2_request,
        shown_monotonic_ns=shown_ns,
        popup_hwnd=202,
    )
    sine.advance(now_monotonic_ns=shown_ns)
    assert sine.live_view().stage_3_deadline_monotonic_ns == (
        shown_ns + int(SinePolicy().stage_3_delay_seconds * NS)
    )


def test_p2_failed_handoff_restores_original_sine1_timing():
    sine, _, request_id, _ = _break_requested_sine()
    original = _hold(sine, request_id)
    original_deadline = original.stage_2_deadline_monotonic_ns

    assert sine.cancel_normal_break_hold(
        candidate_uid=original.candidate_uid,
        episode_uid=original.episode_uid,
        break_id="break-1",
        break_generation=1,
        occurred_monotonic_ns=5 * NS,
        reason="integration_rollback",
    )
    sine.advance(now_monotonic_ns=5 * NS)
    restored = sine.live_view()
    assert restored.normal_break_held is False
    assert restored.episode_uid == original.episode_uid
    assert restored.stage_2_deadline_monotonic_ns == original_deadline


class StorageProbe:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.normal_facts = []
        self.fail_normal_kinds = set()

    def append_sine_facts(self, facts):
        self.order.extend(f"sine:{fact.kind}" for fact in facts)
        return True

    def append_normal_break_facts(self, facts):
        if any(fact.kind.value in self.fail_normal_kinds for fact in facts):
            return False
        self.normal_facts.extend(facts)
        self.order.extend(f"normal:{fact.kind.value}" for fact in facts)
        return True

    def append_mirl_events(self, events):
        return True


class MirlProbe:
    def __init__(self) -> None:
        self.sine_facts = []
        self.ordinary_calls = 0
        self.explicit = []

    def record_sine_fact(self, fact):
        self.sine_facts.append(fact)

    def drain_events(self):
        return ()

    def observe(self, context):
        self.ordinary_calls += 1
        return ()

    def record_recovery_observation(self, observation):
        self.explicit.append(observation)
        return ()


class TriggerProbe:
    def __init__(self) -> None:
        self.facts = []
        self.evaluate_calls = 0

    def record_intervention_fact(self, fact):
        self.facts.append(fact)

    def evaluate(self, **kwargs):
        self.evaluate_calls += 1
        return object()


class BlacklistProbe:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.paused = False
        self.pause_history = []

    def set_paused(self, paused):
        self.order.append(f"blacklist:{paused}")
        self.paused = bool(paused)
        self.pause_history.append(bool(paused))


class SineOrderProxy:
    def __init__(self, sine, order):
        self._sine = sine
        self._order = order

    def hold_for_normal_break(self, **kwargs):
        self._order.append("sine:hold")
        return self._sine.hold_for_normal_break(**kwargs)

    def __getattr__(self, name):
        return getattr(self._sine, name)


def _coordinator_for_handoff():
    sine, clock, request_id, response_facts = _break_requested_sine()
    order = []
    break_ids = iter(("break-monitor", "break-monitor-2", "break-monitor-3"))
    normal_break = NormalBreakAuthority(
        monotonic_ns=clock,
        break_id_factory=lambda: next(break_ids),
    )
    storage = StorageProbe(order)
    mirl = MirlProbe()
    trigger = TriggerProbe()
    blacklist = BlacklistProbe(order)
    services = SimpleNamespace(
        sine=SineOrderProxy(sine, order),
        normal_break=normal_break,
        storage=storage,
        mirl=mirl,
        trigger=trigger,
        blacklist=blacklist,
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
    pending = normal_break.snapshot()
    payload = SimpleNamespace(
        break_id=pending.break_id,
        generation=pending.generation,
        episode_uid=pending.episode_uid,
        candidate_uid=pending.candidate_uid,
        source_sine_popup_request_id=pending.source_sine_popup_request_id,
        selected_minutes=5,
    )
    return coordinator, services, sine, clock, payload


def test_p2_monitor_persists_start_before_sine_hold_and_pauses_blacklist():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    clock.now = 4 * NS
    assert coordinator._start_normal_break(payload)

    start_index = services.storage.order.index("normal:NORMAL_BREAK_STARTED")
    hold_index = services.storage.order.index("sine:hold")
    pause_index = services.storage.order.index("blacklist:True")
    assert start_index < hold_index < pause_index
    assert services.normal_break.active is True
    assert sine.live_view().normal_break_held is True
    assert services.blacklist.paused is True
    assert payload.candidate_uid in coordinator._normal_break_learning_ineligible_candidate_uids


def test_p3_duplicate_start_while_active_is_rejected_without_mutating_break_or_sine():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    clock.now = 4 * NS
    assert coordinator._start_normal_break(payload)

    active_before = services.normal_break.snapshot()
    sine_before = sine.live_view()
    clock.now = 5 * NS

    assert coordinator._start_normal_break(payload) is False

    active_after = services.normal_break.snapshot()
    sine_after = sine.live_view()
    assert active_after.state is NormalBreakState.ACTIVE
    assert active_after.break_id == active_before.break_id
    assert active_after.generation == active_before.generation
    assert active_after.episode_uid == active_before.episode_uid
    assert active_after.candidate_uid == active_before.candidate_uid
    assert sine_after.normal_break_held is True
    assert sine_after.episode_uid == sine_before.episode_uid
    assert sine_after.candidate_uid == sine_before.candidate_uid

    kinds = [fact.kind.value for fact in services.storage.normal_facts]
    assert kinds.count("NORMAL_BREAK_STARTED") == 1
    assert "NORMAL_BREAK_CANCELLED" not in kinds
    assert "NORMAL_BREAK_TERMINATED" not in kinds
    assert "NORMAL_BREAK_START_ROLLED_BACK" not in kinds


def test_p2_monitor_stop_unwinds_blacklist_and_requests_same_episode_sine2():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    clock.now = 4 * NS
    assert coordinator._start_normal_break(payload)
    original_episode = sine.live_view().episode_uid

    clock.now = 25 * NS
    stop = SimpleNamespace(
        break_id=payload.break_id,
        generation=payload.generation,
        episode_uid=payload.episode_uid,
        candidate_uid=payload.candidate_uid,
    )
    assert coordinator._handle_normal_break_command("normal_break_stop", stop)
    resumed = sine.live_view()
    assert resumed.episode_uid == original_episode
    assert resumed.phase is SinePhase.WAITING_FOR_DISPLAY
    assert services.blacklist.paused is False
    assert services.blacklist.pause_history[-2:] == [True, False]


def test_p3_duplicate_stop_is_rejected_after_one_same_episode_sine2_resume():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    clock.now = 4 * NS
    assert coordinator._start_normal_break(payload)
    original_episode = sine.live_view().episode_uid
    stop = SimpleNamespace(
        break_id=payload.break_id,
        generation=payload.generation,
        episode_uid=payload.episode_uid,
        candidate_uid=payload.candidate_uid,
    )

    clock.now = 25 * NS
    assert coordinator._handle_normal_break_command("normal_break_stop", stop)
    assert coordinator._handle_normal_break_command("normal_break_stop", stop) is False

    resumed = sine.live_view()
    assert resumed.episode_uid == original_episode
    assert resumed.phase is SinePhase.WAITING_FOR_DISPLAY
    kinds = [fact.kind.value for fact in services.storage.normal_facts]
    assert kinds.count("NORMAL_BREAK_STOPPED") == 1
    assert kinds.count("NORMAL_BREAK_STOP_REQUESTED") == 1


def test_p2_monitor_natural_completion_persists_at_deadline_then_unwinds():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    clock.now = 4 * NS
    assert coordinator._start_normal_break(payload)
    deadline = services.normal_break.snapshot().deadline_monotonic_ns
    original_episode = sine.live_view().episode_uid

    clock.now = deadline + 99 * NS
    assert coordinator._advance_normal_break(clock.now, None)
    resumed = sine.live_view()
    completed = [
        fact
        for fact in services.storage.normal_facts
        if fact.kind.value == "NORMAL_BREAK_COMPLETED"
    ]
    assert len(completed) == 1
    assert completed[0].occurred_monotonic_ns == deadline
    assert resumed.episode_uid == original_episode
    assert resumed.phase is SinePhase.WAITING_FOR_DISPLAY
    assert services.blacklist.paused is False


def test_p2_cancel_is_a_t_joint_and_never_marks_learning_ineligible():
    coordinator, services, sine, _, payload = _coordinator_for_handoff()
    deadline = sine.live_view().stage_2_deadline_monotonic_ns
    cancel = SimpleNamespace(
        break_id=payload.break_id,
        generation=payload.generation,
        episode_uid=payload.episode_uid,
        candidate_uid=payload.candidate_uid,
        source_sine_popup_request_id=payload.source_sine_popup_request_id,
    )
    assert coordinator._handle_normal_break_command("normal_break_cancel", cancel)
    assert services.normal_break.snapshot().state is NormalBreakState.IDLE
    assert sine.live_view().stage_2_deadline_monotonic_ns == deadline
    assert payload.candidate_uid not in coordinator._normal_break_learning_ineligible_candidate_uids
    assert services.blacklist.pause_history == []


def test_p2_selector_stale_after_sine_advances_rejects_start_and_clears_branch():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    deadline = sine.live_view().stage_2_deadline_monotonic_ns
    clock.now = deadline
    sine.advance(now_monotonic_ns=deadline)
    assert sine.live_view().phase is SinePhase.WAITING_FOR_DISPLAY
    assert sine.live_view().popup_request_id != payload.source_sine_popup_request_id

    assert coordinator._start_normal_break(payload) is False
    assert services.normal_break.snapshot().state is NormalBreakState.IDLE
    assert sine.live_view().normal_break_held is False
    assert services.blacklist.paused is False


class RefusingHoldProxy(SineOrderProxy):
    def hold_for_normal_break(self, **kwargs):
        self._order.append("sine:hold-refused")
        return False


class RefusingResumeProxy(SineOrderProxy):
    def enter_post_normal_break_return_gate(self, **kwargs):
        self._order.append("sine:resume-refused")
        return False


def test_p2_sine_hold_refusal_durably_rolls_back_and_leaves_gates_open():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    services.sine = RefusingHoldProxy(sine, services.storage.order)
    clock.now = 4 * NS

    assert coordinator._start_normal_break(payload) is False
    assert services.normal_break.snapshot().state is NormalBreakState.IDLE
    assert sine.live_view().normal_break_held is False
    assert services.blacklist.paused is False
    assert coordinator._normal_break_owns_pause() is False
    assert "normal:NORMAL_BREAK_START_ROLLED_BACK" in services.storage.order


def test_p2_abandoned_selector_is_retired_and_next_episode_can_request_break():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    assert services.normal_break.snapshot().state is NormalBreakState.AWAITING_DURATION

    deadline = sine.live_view().stage_2_deadline_monotonic_ns
    clock.now = deadline
    for fact in sine.advance(now_monotonic_ns=deadline):
        coordinator._route_sine_fact(fact, None)
    assert coordinator._reconcile_pending_normal_break_selector(
        occurred_monotonic_ns=deadline,
        observation=None,
    )
    assert services.normal_break.snapshot().state is NormalBreakState.IDLE
    assert any(
        fact.kind.value == "NORMAL_BREAK_CANCELLED"
        for fact in services.storage.normal_facts
    )

    assert sine.confirm_verified_return(
        candidate_uid=payload.candidate_uid,
        verified_monotonic_ns=deadline + NS,
        evidence_source="test_verified_return",
    )
    sine.advance(now_monotonic_ns=deadline + NS)
    clock.now = deadline + 2 * NS
    assert sine.request_trigger(
        candidate=_candidate("second-normal-break-candidate"),
        operational_event_id=2,
        mirl_display_token=SimpleNamespace(),
    )
    facts = sine.advance(now_monotonic_ns=clock.now)
    request_id = sine.live_view().popup_request_id
    clock.now += NS
    assert sine.popup_shown(
        request_id=request_id,
        shown_monotonic_ns=clock.now,
        popup_hwnd=303,
    )
    sine.advance(now_monotonic_ns=clock.now)
    clock.now += NS
    assert sine.popup_response(
        request_id=request_id,
        response=SineResponse.REQUEST_BREAK,
        occurred_monotonic_ns=clock.now,
    )
    facts = sine.advance(now_monotonic_ns=clock.now)
    for fact in facts:
        coordinator._route_sine_fact(fact, None)
    second = services.normal_break.snapshot()
    assert second.state is NormalBreakState.AWAITING_DURATION
    assert second.candidate_uid == "second-normal-break-candidate"


def test_p2_resolved_sine1_retires_selector_before_stage2_deadline():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    original_deadline = sine.live_view().stage_2_deadline_monotonic_ns
    resolved_ns = 10 * NS
    assert resolved_ns < original_deadline

    clock.now = resolved_ns
    assert sine.confirm_verified_return(
        candidate_uid=payload.candidate_uid,
        verified_monotonic_ns=resolved_ns,
        evidence_source="test_verified_return_before_stage2",
    )
    assert sine.live_view().phase is SinePhase.RESOLVED

    assert coordinator._reconcile_pending_normal_break_selector(
        occurred_monotonic_ns=resolved_ns,
        observation=None,
    )
    assert services.normal_break.snapshot().state is NormalBreakState.IDLE
    assert any(
        fact.kind.value == "NORMAL_BREAK_CANCELLED"
        for fact in services.storage.normal_facts
    )

    assert coordinator._start_normal_break(payload) is False
    assert not any(
        fact.kind.value == "NORMAL_BREAK_STARTED"
        for fact in services.storage.normal_facts
    )


def test_p2_exact_stage2_deadline_start_is_rejected_before_started_fact():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    deadline = sine.live_view().stage_2_deadline_monotonic_ns
    clock.now = deadline

    assert coordinator._start_normal_break(payload) is False
    assert services.normal_break.snapshot().state is NormalBreakState.IDLE
    assert not any(
        fact.kind.value == "NORMAL_BREAK_STARTED"
        for fact in services.storage.normal_facts
    )
    assert sine.live_view().normal_break_held is False

    sine.advance(now_monotonic_ns=deadline)
    assert sine.live_view().stage is SineStage.SINE_1
    assert sine.live_view().phase is SinePhase.WAITING_FOR_DISPLAY
    assert sine.live_view().popup_request_id != payload.source_sine_popup_request_id


def test_p2_sine_hold_socket_itself_refuses_exact_stage2_deadline():
    sine, clock, request_id, _ = _break_requested_sine()
    view = sine.live_view()
    deadline = view.stage_2_deadline_monotonic_ns
    clock.now = deadline
    assert not sine.hold_for_normal_break(
        candidate_uid=view.candidate_uid,
        episode_uid=view.episode_uid,
        break_id="deadline-break",
        break_generation=1,
        started_monotonic_ns=deadline,
        source_popup_request_id=request_id,
    )
    assert sine.live_view().normal_break_held is False


def _assert_integrity_fault_is_mirl_neutral(coordinator, services, sine):
    from MIRL.mirl import RecoveryContext
    from test_phase1_single_episode_ownership import _context

    before_ordinary = services.mirl.ordinary_calls
    before_explicit = len(services.mirl.explicit)
    events = coordinator._observe_mirl_for_context(_context())
    assert events == ()
    assert services.mirl.ordinary_calls == before_ordinary
    assert len(services.mirl.explicit) == before_explicit + 1
    assert services.mirl.explicit[-1].context is RecoveryContext.NEUTRAL
    assert services.trigger.evaluate_calls == 0
    assert coordinator._normal_break_resume_fault is True
    assert coordinator._normal_break_owns_pause() is True
    assert sine.live_view().normal_break_held is True
    assert services.blacklist.paused is False
    assert not sine.confirm_verified_return(
        candidate_uid=sine.live_view().candidate_uid,
        verified_monotonic_ns=sine.live_view().stage_2_deadline_monotonic_ns + NS,
        evidence_source="must_not_bypass_normal_break_handoff",
    )


def test_p2_terminal_persistence_failure_stays_mirl_neutral_fail_closed():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    clock.now = 4 * NS
    assert coordinator._start_normal_break(payload)
    services.storage.fail_normal_kinds.add("NORMAL_BREAK_COMPLETED")
    deadline = services.normal_break.snapshot().deadline_monotonic_ns
    clock.now = deadline

    assert coordinator._advance_normal_break(deadline, None) is False
    assert services.normal_break.snapshot().state is NormalBreakState.IDLE
    _assert_integrity_fault_is_mirl_neutral(coordinator, services, sine)


def test_p2_sine_resume_refusal_stays_mirl_neutral_fail_closed():
    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    clock.now = 4 * NS
    assert coordinator._start_normal_break(payload)
    services.sine = RefusingResumeProxy(sine, services.storage.order)
    deadline = services.normal_break.snapshot().deadline_monotonic_ns
    clock.now = deadline

    assert coordinator._advance_normal_break(deadline, None) is False
    assert services.normal_break.snapshot().state is NormalBreakState.IDLE
    _assert_integrity_fault_is_mirl_neutral(coordinator, services, sine)


@pytest.mark.parametrize("reason_name", ["EMERGENCY", "SHUTDOWN", "SESSION_END"])
def test_p2_nonresuming_termination_unwinds_blacklist(reason_name):
    from SINE.normal_break import NormalBreakTerminationReason

    coordinator, services, sine, clock, payload = _coordinator_for_handoff()
    clock.now = 4 * NS
    assert coordinator._start_normal_break(payload)
    before = sine.live_view()

    reason = getattr(NormalBreakTerminationReason, reason_name)
    assert coordinator._terminate_normal_break(reason)
    after = sine.live_view()
    assert services.normal_break.snapshot().state is NormalBreakState.IDLE
    assert services.blacklist.paused is False
    assert after.episode_uid == before.episode_uid
    assert after.stage is SineStage.SINE_1
    assert after.normal_break_held is True
    assert after.post_normal_break_completion_kind == ""


def test_p2_break_episode_releases_recovery_but_cannot_train_tr_or_lambda():
    package = SimpleNamespace(
        session_id=1,
        profile_type="general",
        candidate_uid="normal-break-candidate",
        episode_id="mirl-episode-1",
        return_verified_monotonic_ns=100 * NS,
        schema_version="irrelevant-because-break-excluded-first",
        verified_recovery_elapsed_seconds=30.0,
    )

    class LearningMirl:
        def __init__(self):
            self.packages = [package]

        def drain_verified_recovery_evidence(self):
            result, self.packages = tuple(self.packages), []
            return result

    class LearningSine:
        def __init__(self):
            self.releases = []

        def confirm_verified_return(self, **kwargs):
            self.releases.append(kwargs)
            return True

    class LearningTrigger:
        def __init__(self):
            self.estimates = 0

        def estimate_observed_lambda(self, **kwargs):
            self.estimates += 1
            raise AssertionError("Break-containing episode must not estimate lambda")

    sine = LearningSine()
    trigger = LearningTrigger()
    services = SimpleNamespace(mirl=LearningMirl(), sine=sine, trigger=trigger)
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
    coordinator._profile_learning_key = "general"
    coordinator._normal_break_learning_ineligible_candidate_uids.add(
        "normal-break-candidate"
    )

    coordinator._collect_verified_recovery_learning()
    assert len(sine.releases) == 1
    assert trigger.estimates == 0
    assert coordinator._observed_lambda_estimates == []


def test_p2_active_break_replaces_ordinary_mirl_with_one_neutral_and_blocks_trigger():
    from MIRL.mirl import RecoveryContext
    from test_phase1_single_episode_ownership import _context, _coordinator

    coordinator, services, founded = _coordinator(
        phase=SinePhase.IDLE,
        episode_uid="",
        candidate=object(),
    )
    active = SimpleNamespace(
        active=True,
        advance=lambda **kwargs: SimpleNamespace(accepted=True, facts=()),
        snapshot=lambda: SimpleNamespace(break_id="break-active"),
    )
    services.normal_break = active
    explicit = []
    services.mirl.record_recovery_observation = lambda observation: (
        explicit.append(observation) or ()
    )

    coordinator._route_context(_context())

    assert services.mirl.observe_calls == 0
    assert len(explicit) == 1
    assert explicit[0].context is RecoveryContext.NEUTRAL
    assert services.trigger.evaluate_calls == 0
    assert founded == []


def test_p2_productive_and_distracting_foregrounds_both_remain_mirl_neutral():
    from MIRL.mirl import RecoveryContext
    from test_phase1_single_episode_ownership import _context, _coordinator

    coordinator, services, _ = _coordinator(
        phase=SinePhase.IDLE,
        episode_uid="",
        candidate=None,
    )
    services.normal_break = SimpleNamespace(
        active=True,
        advance=lambda **kwargs: SimpleNamespace(accepted=True, facts=()),
        snapshot=lambda: SimpleNamespace(break_id="break-active"),
    )
    explicit = []
    services.mirl.record_recovery_observation = lambda observation: (
        explicit.append(observation) or ()
    )

    coordinator._route_context(
        _context(sequence=1, classification="STUDY_ALIGNED", study_idle_allowed=True)
    )
    coordinator._route_context(_context(sequence=2, classification="DISTRACTION"))
    assert services.mirl.observe_calls == 0
    assert [item.context for item in explicit] == [
        RecoveryContext.NEUTRAL,
        RecoveryContext.NEUTRAL,
    ]


def test_p2_protected_red_refuses_normal_break_hold():
    from test_phase4_case2_presentation_release import _protected_red

    sine, clock, request_id = _protected_red(study_mode=False)
    view = sine.live_view()
    clock[0] += NS
    assert not sine.hold_for_normal_break(
        candidate_uid=view.candidate_uid,
        episode_uid=view.episode_uid,
        break_id="red-break",
        break_generation=1,
        started_monotonic_ns=clock[0],
        source_popup_request_id=request_id,
    )
    assert sine.live_view().phase is SinePhase.PROTECTED_RED


def test_p2_global_pause_branch_advances_only_normal_break_clock():
    source = inspect.getsource(WindowsMonitorCoordinator._monitor_loop)
    pause_branch = source.split("if self.pause_event.is_set():", 1)[1].split(
        "self._reconcile_pending_trigger()", 1
    )[0]
    assert "_advance_normal_break" in pause_branch
    assert "foreground_reader.observe" not in pause_branch


def test_p2_phase3_presentation_files_are_not_part_of_the_integration_surface():
    source = inspect.getsource(WindowsMonitorCoordinator._handle_normal_break_command)
    assert "self.services.controller" not in source
    assert "self.services.popup" not in source
