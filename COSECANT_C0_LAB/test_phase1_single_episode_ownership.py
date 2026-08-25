"""Phase 1: one unresolved SINE episode owns intervention until release.

This is an external verification lab.  It imports production authorities but
does not write tests, reports, databases, or caches into MYELIN2.0_ULTIMATE.
"""

from __future__ import annotations

import ast
import inspect
import queue
import sys
import textwrap
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

ULTIMATE = Path(r"C:\Users\Dharshan\Downloads\MYELIN_GENALOGY\MYELIN2.0_ULTIMATE")
if str(ULTIMATE) not in sys.path:
    sys.path.insert(0, str(ULTIMATE))

from COSECANT_STUDY_MODE.cosecant import CosecantState
from CORE_ENGINE.monitor import (
    ForegroundObservation,
    MonitorContext,
    WindowsMonitorCoordinator,
)
from CORE_ENGINE.trigger import mbrm_session_personalization
from SINE.sine import (
    PopupState,
    SineAuthority,
    SinePhase,
    SinePolicy,
    SineResponse,
)


class _CosineProbe:
    def __init__(self) -> None:
        self.observe_calls = 0
        self.advance_calls = 0

    def observe(self, observation):
        self.observe_calls += 1
        return ()

    def advance(self, *, now_ns):
        self.advance_calls += 1
        return ()

    def snapshot(self, *, now_ns):
        return SimpleNamespace(phase="IDLE")


class _MirlProbe:
    def __init__(self) -> None:
        self.observe_calls = 0

    def observe(self, context):
        self.observe_calls += 1
        return ()


class _SineProbe:
    def __init__(self, *, phase: SinePhase, episode_uid: str, popup_state=None) -> None:
        self.phase = phase
        self.episode_uid = episode_uid
        self.popup_state = popup_state
        self.observe_calls = 0
        self.advance_calls = 0

    def live_view(self):
        return SimpleNamespace(
            phase=self.phase,
            episode_uid=self.episode_uid,
            popup_state=self.popup_state,
        )

    def observe(self, context):
        self.observe_calls += 1

    def advance(self, *, now_monotonic_ns):
        self.advance_calls += 1
        return ()

    def protected_red_active(self):
        return self.phase is SinePhase.PROTECTED_RED


class _BlacklistProbe:
    def __init__(self) -> None:
        self.observe_calls = 0
        self.contexts = []

    def observe(self, context):
        self.observe_calls += 1
        self.contexts.append(context)
        return SimpleNamespace(disposition="submitted")


class _TriggerProbe:
    def __init__(self, candidate=None) -> None:
        self.candidate = candidate
        self.evaluate_calls = 0

    def evaluate(self, *, context, blacklist):
        self.evaluate_calls += 1
        return self.candidate


class _StudyProbe:
    def __init__(self) -> None:
        self.advance_calls = 0

    def snapshot(self):
        # Current Monitor refreshes its break-return target from every Study
        # snapshot before routing SINE.  This Phase-1 probe has no active Study
        # block, so it supplies the explicit inert identity instead of omitting
        # the modern collaborator method.
        return SimpleNamespace(
            state="INACTIVE",
            block_id="",
            generation=0,
            context_token="",
        )

    def advance(self):
        self.advance_calls += 1
        return SimpleNamespace(state="INACTIVE")


class _CosecantProbe:
    def __init__(self) -> None:
        self.advance_calls = 0
        self.snapshot_calls = 0
        self._snapshot = SimpleNamespace(state=CosecantState.INACTIVE)

    def advance(self):
        self.advance_calls += 1
        return SimpleNamespace(facts=(), snapshot=self._snapshot)

    def snapshot(self):
        self.snapshot_calls += 1
        return self._snapshot


def _context(
    *,
    sequence: int = 1,
    resource_key: str = "resource-a",
    process_name: str = "chrome",
    classification: str = "DISTRACTION",
    study_idle_allowed: bool = False,
) -> MonitorContext:
    foreground = ForegroundObservation(
        sequence=sequence,
        hwnd=1000 + sequence,
        process_id=2000 + sequence,
        process_name=process_name,
        window_title=f"surface-{resource_key}",
        observed_monotonic_ns=10_000_000_000 + sequence,
        observed_wall_time_utc="2026-08-24T00:00:00+00:00",
        idle_seconds=0.0,
    )
    verdict = SimpleNamespace(
        study_idle_allowed=study_idle_allowed,
        classification=classification,
        study_context_token="",
        observation_token=f"observation-{sequence}",
        resource_identity=SimpleNamespace(stable_key=resource_key),
    )
    return MonitorContext(
        foreground=foreground,
        browser_evidence=SimpleNamespace(),
        resource_intent=SimpleNamespace(
            verdict=verdict,
            fresh=True,
            cosine_active=False,
        ),
    )


def _coordinator(*, phase: SinePhase, episode_uid: str, popup_state=None, candidate=None):
    cosine = _CosineProbe()
    mirl = _MirlProbe()
    sine = _SineProbe(
        phase=phase,
        episode_uid=episode_uid,
        popup_state=popup_state,
    )
    blacklist = _BlacklistProbe()
    trigger = _TriggerProbe(candidate=candidate)
    study = _StudyProbe()
    cosecant = _CosecantProbe()
    services = SimpleNamespace(
        cosine=cosine,
        mirl=mirl,
        sine=sine,
        blacklist=blacklist,
        trigger=trigger,
        study=study,
        cosecant=cosecant,
        storage=SimpleNamespace(),
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
    founded = []
    coordinator._begin_trigger_persistence = founded.append
    return coordinator, services, founded


def test_p1_01_idle_sine_allows_one_founding_trigger_after_all_observers_run():
    candidate = object()
    coordinator, services, founded = _coordinator(
        phase=SinePhase.IDLE,
        episode_uid="",
        candidate=candidate,
    )

    coordinator._route_context(_context())

    assert services.trigger.evaluate_calls == 1
    assert founded == [candidate]
    assert services.mirl.observe_calls == 1
    assert services.sine.observe_calls == 1
    assert services.blacklist.observe_calls == 1
    assert services.study.advance_calls == 1
    assert services.cosecant.advance_calls == 1
    assert services.sine.advance_calls == 1


def test_p1_04_05_06_live_owner_blocks_new_founder_but_not_observation_or_timers():
    cases = [
        (SinePhase.WAITING_FOR_DISPLAY, PopupState.REQUESTED),
        (SinePhase.ACTIVE, PopupState.DISPLAYED),
        (SinePhase.ACTIVE, PopupState.CLOSED),
        (SinePhase.PROTECTED_RED, PopupState.DISPLAYED),
    ]
    for phase, popup_state in cases:
        coordinator, services, founded = _coordinator(
            phase=phase,
            episode_uid="episode-owner",
            popup_state=popup_state,
            candidate=object(),
        )

        coordinator._route_context(_context(sequence=1, resource_key="resource-a"))
        coordinator._route_context(_context(sequence=2, resource_key="resource-b"))

        assert services.trigger.evaluate_calls == 0, phase
        assert founded == [], phase
        assert services.mirl.observe_calls == 2, phase
        assert services.sine.observe_calls == 2, phase
        assert services.blacklist.observe_calls == 2, phase
        assert services.study.advance_calls == 2, phase
        assert services.cosecant.advance_calls == 2, phase
        assert services.sine.advance_calls == 2, phase


def test_p1_mandatory_popup_closed_app_switch_and_youtube_return_sequence():
    coordinator, services, founded = _coordinator(
        phase=SinePhase.ACTIVE,
        episode_uid="original-sine-episode",
        popup_state=PopupState.CLOSED,
        candidate=object(),
    )
    sequence = (
        _context(
            sequence=1,
            resource_key="python",
            process_name="python",
            classification="UNCERTAIN",
        ),
        _context(
            sequence=2,
            resource_key="snipping-tool",
            process_name="snippingtool",
            classification="UNCERTAIN",
        ),
        _context(
            sequence=3,
            resource_key="explorer",
            process_name="explorer",
            classification="UNCERTAIN",
        ),
        _context(
            sequence=4,
            resource_key="youtube-video",
            process_name="chrome",
            classification="DISTRACTION",
        ),
        _context(
            sequence=5,
            resource_key="verified-study-resource",
            process_name="chrome",
            classification="STUDY_ALIGNED",
            study_idle_allowed=True,
        ),
    )

    for context in sequence:
        coordinator._route_context(context)

    assert services.trigger.evaluate_calls == 0
    assert founded == []
    assert services.blacklist.observe_calls == len(sequence)
    assert services.mirl.observe_calls == len(sequence)
    assert services.study.advance_calls == len(sequence)
    assert services.cosecant.advance_calls == len(sequence)
    assert services.sine.advance_calls == len(sequence)


def test_p1_study_b_active_sine_does_not_stop_resource_intent_reclassification():
    coordinator, services, _ = _coordinator(
        phase=SinePhase.ACTIVE,
        episode_uid="episode-owner",
        popup_state=PopupState.CLOSED,
    )
    observation = _context().foreground
    calls = []
    browser_fact = SimpleNamespace(host_authoritative=False, certified_host="")
    services.browser = SimpleNamespace(
        observe=lambda foreground: calls.append(("browser", foreground)) or browser_fact
    )

    class IntentProbe:
        def set_protected_red(self, active):
            calls.append(("protected_red", active))

        def set_cosine_active(self, active):
            calls.append(("cosine_active", active))

        def set_cosine_resource_owned(self, active):
            calls.append(("cosine_resource_owned", active))

        def observe(self, *, foreground, browser_evidence):
            calls.append(("resource_intent_observe", foreground, browser_evidence))
            return SimpleNamespace(verdict=SimpleNamespace(classification="UNCERTAIN"))

    services.resource_intent = IntentProbe()

    context = coordinator._classify_observation(observation)

    assert context.foreground is observation
    assert any(call[0] == "resource_intent_observe" for call in calls)


def test_p1_08_terminal_sine_releases_gate_for_a_future_trigger():
    for phase in (SinePhase.RESOLVED, SinePhase.CANCELLED):
        candidate = object()
        coordinator, services, founded = _coordinator(
            phase=phase,
            episode_uid="historical-episode",
            candidate=candidate,
        )

        coordinator._route_context(_context())

        assert services.trigger.evaluate_calls == 1, phase
        assert founded == [candidate], phase


def _candidate(*, candidate_uid: str = "candidate-1", resource_key: str = "resource-a"):
    return SimpleNamespace(
        candidate_uid=candidate_uid,
        session_id=1,
        profile_type="GENERAL",
        evidence=SimpleNamespace(
            observed_monotonic_ns=1_000_000_000,
            dwell_seconds=300.0,
            threshold_seconds=300.0,
            study_context_token="",
            resource_key=resource_key,
            resource_observation_token="resource-observation-1",
            surface_class="youtube_watch",
            browser_evidence_kind="certified_url",
            process_name="chrome",
            process_id=20,
            hwnd=10,
            platform_key="youtube",
        ),
    )


def _display_sine_one():
    clock = [1_000_000_000]
    sine = SineAuthority(monotonic_ns=lambda: clock[0])
    sine.start_session(session_id=1, profile_type="GENERAL")
    assert sine.request_trigger(
        candidate=_candidate(),
        operational_event_id=1,
        mirl_display_token=SimpleNamespace(),
    )
    sine.advance(now_monotonic_ns=clock[0])
    request_id = sine.live_view().popup_request_id
    clock[0] = 2_000_000_000
    assert sine.popup_shown(
        request_id=request_id,
        shown_monotonic_ns=clock[0],
        popup_hwnd=300,
    )
    sine.advance(now_monotonic_ns=clock[0])
    return sine, clock, request_id


def test_p1_02_03_return_button_closes_popup_without_reanchoring_or_resolving():
    sine, clock, request_id = _display_sine_one()
    displayed = sine.live_view()
    deadline = displayed.stage_2_deadline_monotonic_ns
    assert deadline == 2_000_000_000 + int(SinePolicy().stage_2_delay_seconds * 1e9)

    clock[0] = 3_000_000_000
    assert sine.popup_response(
        request_id=request_id,
        response=SineResponse.RETURN_TO_FOCUS,
        occurred_monotonic_ns=clock[0],
    )
    facts = sine.advance(now_monotonic_ns=clock[0])
    assert "SINE_RETURN_INTENT_RECORDED" in {fact.kind for fact in facts}
    assert "SINE_POPUP_CLOSE_REQUESTED" in {fact.kind for fact in facts}
    assert sine.live_view().phase is SinePhase.ACTIVE

    clock[0] = 4_000_000_000
    assert sine.popup_closed(
        request_id=request_id,
        reason="accepted_return_intent",
        occurred_monotonic_ns=clock[0],
    )
    closed = sine.live_view()
    assert closed.phase is SinePhase.ACTIVE
    assert closed.popup_state is PopupState.CLOSED
    assert closed.episode_uid == displayed.episode_uid
    assert closed.stage_2_deadline_monotonic_ns == deadline


def test_p1_04_real_sine_resource_switch_preserves_same_unresolved_episode():
    sine, clock, request_id = _display_sine_one()
    original = sine.live_view()
    clock[0] = 3_000_000_000
    assert sine.popup_response(
        request_id=request_id,
        response=SineResponse.RETURN_TO_FOCUS,
        occurred_monotonic_ns=clock[0],
    )
    assert sine.popup_closed(
        request_id=request_id,
        reason="accepted_return_intent",
        occurred_monotonic_ns=clock[0] + 1,
    )

    sine.observe(_context(sequence=3, resource_key="resource-b"))
    switched = sine.live_view()

    assert switched.phase is SinePhase.ACTIVE
    assert switched.episode_uid == original.episode_uid
    assert switched.candidate_uid == original.candidate_uid
    assert switched.stage_2_deadline_monotonic_ns == original.stage_2_deadline_monotonic_ns


def test_p1_07_only_verified_recovery_releases_the_real_episode():
    sine, clock, _ = _display_sine_one()
    candidate_uid = sine.live_view().candidate_uid
    clock[0] = 12_000_000_000

    assert sine.confirm_verified_return(
        candidate_uid=candidate_uid,
        verified_monotonic_ns=clock[0],
        evidence_source="mirl",
    )
    assert sine.live_view().phase is SinePhase.RESOLVED


def test_p1_09_scientific_and_return_contracts_remain_exact():
    signature = inspect.signature(mbrm_session_personalization)
    assert signature.parameters["learned_lambda_per_minute"].default is inspect.Parameter.empty
    assert signature.parameters["reference_lambda_per_minute"].default is inspect.Parameter.empty
    projection = mbrm_session_personalization(
        learned_lambda_per_minute=2.0,
        reference_lambda_per_minute=4.0,
    )
    assert projection.personalization_factor == 0.5
    assert SinePolicy().stage_2_delay_seconds == 600.0
    assert SinePolicy().stage_3_delay_seconds == 795.0

    tree = ast.parse(textwrap.dedent(inspect.getsource(SineAuthority.popup_response)))
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "_resolve_episode" not in called_attributes
    assert "confirm_verified_return" not in called_attributes


def load_tests(loader, tests, pattern):
    del loader, tests, pattern
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value, description=name))
    return suite


if __name__ == "__main__":
    unittest.main(verbosity=2)
