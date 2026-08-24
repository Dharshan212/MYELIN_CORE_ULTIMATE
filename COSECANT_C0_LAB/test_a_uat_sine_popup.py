"""UAT-02 / UAT-03 / UAT-04 -- SINE Study popup repair.

HUMAN SYMPTOM (UAT-02): the user pressed THIS IS STUDY MATERIAL and the popup
stayed on "ACTION SENT ... WAITING FOR ACCEPTANCE" forever.

REPRODUCED root mechanism: when SINE REFUSES the callback, no SINE fact is
produced at all.  The presenter only ever learns anything from a fact, so a
refused callback leaves the popup waiting permanently.  Monitor discarded the
return value of ``record_study_material_result``, so the refusal was invisible.

AUTHORITY LAW under test throughout:

    BUTTON          -> user intent only
    RESOURCE INTENT -> decides Study-material allowance
    SINE            -> records the result, decides closure
    POPUP           -> presentation only; closes on an exact SINE close fact

FILE NAME IS DELIBERATE.  pytest collects files alphabetically, so ``test_a_``
makes this module run BEFORE ``test_c11_a_shell_contract``.  That ordering is
required, not cosmetic: constructing ANY second top-level native Qt window
after C11-A's full Study-shell journey segfaults PyQt on this platform.  The
crash is independent of the UAT repair -- it reproduces on window CONSTRUCTION
alone, in tests that never reach the changed placement code -- and no
process-isolation plugin (xdist/forked) is installed to separate them.  This
is a LAB harness fragility, reported and not papered over.
"""

from __future__ import annotations

import os
import queue
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _lab
from _lab import LECTURE, ScriptedForegroundReader, build_services

from CORE_ENGINE.monitor import WindowsMonitorCoordinator
from SINE.sine import PopupState, SineResponse

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtWidgets import QApplication

from SINE.popup import SinePopupPresenter, SinePopupWindow


@pytest.fixture(scope="session")
def qt_app():
    """Reuse one QApplication for the whole run.

    Deliberately ``return``, never ``yield``: a teardown would drop the last
    reference to the QApplication while other Qt test modules still hold live
    objects, which crashes PyQt at interpreter shutdown.  This matches the
    existing C11-A/C11-C pattern.
    """

    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


# ---------------------------------------------------------------------------
# Engine-level bench: the REAL monitor chain, driven synchronously.
# ---------------------------------------------------------------------------

class _Bench:
    def __init__(self) -> None:
        self.foreground = ScriptedForegroundReader(LECTURE)
        self.services = build_services(foreground=self.foreground, fast_cosecant=True)
        self.telemetry: queue.Queue = queue.Queue()
        self.commands: queue.Queue = queue.Queue()
        self.coordinator = WindowsMonitorCoordinator(
            profile_type="study",
            services=self.services,
            foreground_reader=self.foreground,
            stop_event=threading.Event(),
            pause_event=threading.Event(),
            ready_event=threading.Event(),
            loop_stopped_event=threading.Event(),
            cleanup_complete_event=threading.Event(),
            telemetry_queue=self.telemetry,
            command_queue=self.commands,
            poll_seconds=0.2,
        )

    def drain_telemetry(self) -> list:
        out = []
        while True:
            try:
                out.append(self.telemetry.get_nowait())
            except queue.Empty:
                return out

    def rejections(self) -> list[str]:
        return [
            str(item.get("message", ""))
            for item in self.drain_telemetry()
            if item.get("kind") == "engine_command_rejected"
        ]


@pytest.fixture
def bench():
    harness = _Bench()
    # A real durable session: SINE facts are foreign-keyed to it.
    harness.coordinator._start_session()
    try:
        yield harness
    finally:
        harness.services.storage.shutdown()


# ---------------------------------------------------------------------------
# UAT-02 -- the stuck popup
# ---------------------------------------------------------------------------

def test_uat02_refused_study_material_result_is_reported_not_silent(bench):
    """The repair: a refused authority callback must never disappear.

    ``record_study_material_result`` is driven with a request id SINE has
    never heard of -- the same refusal shape a superseded or stale occurrence
    produces.  Before the repair Monitor discarded the ``False`` and emitted
    nothing at all.
    """

    fact = _study_material_requested_fact("popup_never_registered")

    assert bench.coordinator._route_sine_fact(fact, None) is False

    messages = bench.rejections()
    assert any("Study Material result" in message for message in messages), messages
    assert any("popup was not informed" in message for message in messages), messages


def test_uat02_refusal_produces_no_close_fact(bench):
    """A refusal must NOT be papered over by closing the popup anyway."""

    fact = _study_material_requested_fact("popup_never_registered")
    bench.coordinator._route_sine_fact(fact, None)

    from PERSISTENCE.database import connect_database

    connection = connect_database(read_only=True)
    try:
        kinds = [row[0] for row in connection.execute("SELECT kind FROM sine_facts")]
    finally:
        connection.close()
    assert "SINE_POPUP_CLOSE_REQUESTED" not in kinds
    assert "SINE_STUDY_MATERIAL_RESULT" not in kinds


def test_uat02_monitor_acknowledges_rejected_user_action(bench):
    """A refused click must return to the controller instead of disappearing."""

    import queue

    from CONTROL_STATION.controller import EngineCommand

    acknowledgement = queue.Queue(maxsize=1)
    bench.commands.put_nowait(
        EngineCommand(
            kind="sine_user_action",
            payload={
                "request_id": "popup_never_registered",
                "response": "this_is_study_material",
                "occurred_monotonic_ns": time.monotonic_ns(),
            },
            response_queue=acknowledgement,
        )
    )

    bench.coordinator._drain_commands()

    assert acknowledgement.get_nowait() is False


def _study_material_requested_fact(request_id: str):
    """A REAL SineFact of the exact kind Monitor routes for this request."""

    from datetime import datetime, timezone

    from SINE.sine import SineFact

    return SineFact(
        kind="SINE_STUDY_MATERIAL_REQUESTED",
        message="UAT-02 reproduction",
        occurred_monotonic_ns=time.monotonic_ns(),
        occurred_wall_time_utc=datetime.now(timezone.utc).isoformat(),
        session_id=None,
        episode_uid="uat02_episode",
        candidate_uid="uat02_candidate",
        operational_event_id=1,
        stage=1,
        occurrence=1,
        popup_request_id=request_id,
        response="this_is_study_material",
    )


# ---------------------------------------------------------------------------
# UAT-02 A-W -- Chief's real offered-button journey
# ---------------------------------------------------------------------------

def _pump_sine(bench, presenter, qt_app, facts, *, until=None) -> None:
    """Route real queued SINE facts through Monitor and the real presenter."""

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        emitted = tuple(
            bench.services.sine.advance(now_monotonic_ns=time.monotonic_ns())
            or ()
        )
        for fact in emitted:
            bench.coordinator._route_sine_fact(fact, bench._uat_context.foreground)
        qt_app.processEvents()
        if until is not None and until():
            return
        if not emitted:
            time.sleep(0.005)
    if until is not None:
        raise AssertionError("timed out while routing the UAT SINE journey")


def _open_real_study_material_popup(bench, qt_app):
    """Reach one factually displayed popup from the real UNCERTAIN path."""

    from CORE_ENGINE.blacklist import SineThresholdPolicy
    from CORE_ENGINE.resource_intent import ResourceIntent, ResourceSurface
    from CORE_ENGINE.trigger import TriggerSource
    from SINE.sine import SineFact

    # A. The production Study authority is genuinely ACTIVE. No keywords are
    # declared, which is the exact live 50% UNCERTAIN path Chief reported.
    assert bench.services.study.prepare(
        subject="Neuroscience",
        task="basal ganglia",
        planned_seconds=3600,
        keywords=(),
        important_keywords=(),
    ).accepted
    assert bench.services.study.start().accepted
    study = bench.services.study.snapshot()
    assert study.state.value == "ACTIVE"
    bench.coordinator._sync_study_context_with_resource_intent(study)

    # Only the LAB dwell policy is shortened. Resource Intent's production
    # constants and all production clocks remain untouched.
    bench.services.blacklist._thresholds = SineThresholdPolicy(
        stage_one_seconds=0.3,
        stage_two_cumulative_seconds=1.5,
        offer_retry_seconds=0.1,
    )
    first = bench.coordinator._classify_observation(bench.foreground.observe())
    bench.services.blacklist.observe(first)
    time.sleep(0.35)
    context = bench.coordinator._classify_observation(bench.foreground.observe())
    blacklist = bench.services.blacklist.observe(context)
    verdict = context.resource_intent.verdict

    # B/C. This is a certified YouTube watch, but with no declared Study
    # keywords it is factually UNCERTAIN at exactly 50% before allowance.
    assert verdict.classification is ResourceIntent.UNCERTAIN
    assert verdict.confidence == 0.50
    assert verdict.resource_identity.surface is ResourceSurface.YOUTUBE_WATCH
    assert blacklist.threshold_offer is not None

    candidate = bench.services.trigger.evaluate(
        context=context,
        blacklist=blacklist,
    )
    assert candidate is not None
    assert candidate.evidence.source is TriggerSource.EXECUTIVE_BLACKLIST
    assert candidate.reason == "executive_blacklist_dwell"
    assert candidate.evidence.surface_class == "youtube_watch"
    bench._uat_context = context

    presenter = SinePopupPresenter(reduced_motion=True)
    presented_facts = []
    popup_response_results = []
    allowance_results = []
    record_result_results = []
    popup_closed_results = []

    presenter.popup_shown.connect(
        lambda request_id, occurred_ns, hwnd: bench.coordinator._handle_sine_command(
            "sine_popup_shown",
            {
                "request_id": request_id,
                "occurred_monotonic_ns": int(occurred_ns),
                "popup_hwnd": int(hwnd),
            },
        )
    )
    presenter.popup_failed.connect(
        lambda request_id, reason, occurred_ns: bench.coordinator._handle_sine_command(
            "sine_popup_failed",
            {
                "request_id": request_id,
                "reason": reason,
                "occurred_monotonic_ns": int(occurred_ns),
            },
        )
    )
    presenter.user_action.connect(
        lambda request_id, response, occurred_ns: bench.coordinator._handle_sine_command(
            "sine_user_action",
            {
                "request_id": request_id,
                "response": response,
                "occurred_monotonic_ns": int(occurred_ns),
            },
        )
    )
    presenter.popup_closed.connect(
        lambda request_id, reason, occurred_ns: bench.coordinator._handle_sine_command(
            "sine_popup_closed",
            {
                "request_id": request_id,
                "reason": reason,
                "occurred_monotonic_ns": int(occurred_ns),
            },
        )
    )

    original_publish = bench.coordinator._publish_domain_fact

    def publish_and_present(domain, fact, observation):
        original_publish(domain, fact, observation)
        if domain == "sine" and isinstance(fact, SineFact):
            presented_facts.append(fact)
            presenter.apply_fact(fact)

    bench.coordinator._publish_domain_fact = publish_and_present

    original_popup_response = bench.services.sine.popup_response

    def record_popup_response(**kwargs):
        result = original_popup_response(**kwargs)
        popup_response_results.append(result)
        return result

    bench.services.sine.popup_response = record_popup_response

    original_allowance = (
        bench.services.resource_intent.record_study_material_allowance
    )

    def record_allowance(**kwargs):
        result = original_allowance(**kwargs)
        allowance_results.append(result)
        return result

    bench.services.resource_intent.record_study_material_allowance = record_allowance

    original_record_result = bench.services.sine.record_study_material_result

    def record_study_material_result(**kwargs):
        result = original_record_result(**kwargs)
        record_result_results.append(result)
        return result

    bench.services.sine.record_study_material_result = record_study_material_result

    original_popup_closed = bench.services.sine.popup_closed

    def record_popup_closed(**kwargs):
        result = original_popup_closed(**kwargs)
        popup_closed_results.append(result)
        return result

    bench.services.sine.popup_closed = record_popup_closed

    bench.coordinator._begin_trigger_persistence(candidate)
    receipt_deadline = time.monotonic() + 5.0
    while bench.coordinator._pending_trigger is not None:
        bench.coordinator._reconcile_pending_trigger()
        if time.monotonic() >= receipt_deadline:
            raise AssertionError("trigger persistence did not settle")
        time.sleep(0.005)

    _pump_sine(
        bench,
        presenter,
        qt_app,
        presented_facts,
        until=lambda: bool(presenter.active_request_ids()),
    )
    request_id = presenter.active_request_ids()[0]
    _pump_sine(
        bench,
        presenter,
        qt_app,
        presented_facts,
        until=lambda: (
            bench.services.sine._popups[request_id].state is PopupState.DISPLAYED
        ),
    )
    window = presenter._windows[request_id]
    episode = bench.services.sine._episode

    # D-H. The Blacklist founded the trigger, Resource Intent supplied the
    # resource identity, SINE allowed the action, and the popup really exists.
    assert episode is not None and episode.study_material_action_allowed is True
    assert SineResponse.THIS_IS_STUDY_MATERIAL in (
        window.request.presentation.allowed_responses
    )
    assert window.isVisible()
    assert episode.study_context_token == context.resource_intent.verdict.study_context_token
    assert episode.resource_key == context.resource_intent.resource_key

    return {
        "study": study,
        "context": context,
        "candidate": candidate,
        "presenter": presenter,
        "window": window,
        "request_id": request_id,
        "facts": presented_facts,
        "popup_response_results": popup_response_results,
        "allowance_results": allowance_results,
        "record_result_results": record_result_results,
        "popup_closed_results": popup_closed_results,
    }


def test_uat02_complete_declaration_close_and_alignment_journey(bench, qt_app):
    journey = _open_real_study_material_popup(bench, qt_app)
    presenter = journey["presenter"]
    window = journey["window"]
    request_id = journey["request_id"]
    try:
        # I/J. Press the real visible button through Qt -> Presenter -> Monitor
        # -> SINE and record the authority's actual Boolean acceptance.
        window._buttons[SineResponse.THIS_IS_STUDY_MATERIAL].click()
        _pump_sine(
            bench,
            presenter,
            qt_app,
            journey["facts"],
            until=lambda: request_id not in presenter.active_request_ids(),
        )
        _pump_sine(bench, presenter, qt_app, journey["facts"])

        kinds = [fact.kind for fact in journey["facts"]]
        assert journey["popup_response_results"] == [True]
        assert "SINE_STUDY_MATERIAL_REQUESTED" in kinds

        # L-O. The SINE fact carried the captured Study/resource binding;
        # Monitor accepted the declaration and Resource Intent stored it.
        requested = [
            fact
            for fact in journey["facts"]
            if fact.kind == "SINE_STUDY_MATERIAL_REQUESTED"
        ]
        assert len(requested) == 1
        assert (
            requested[0].study_context_token
            == journey["context"].resource_intent.verdict.study_context_token
        )
        assert requested[0].resource_key == journey["context"].resource_intent.resource_key
        assert len(journey["allowance_results"]) == 1
        grant = journey["allowance_results"][0]
        assert grant.granted is True
        assert grant.outcome.value == "granted"
        assert journey["record_result_results"] == [True]
        assert "SINE_STUDY_MATERIAL_RESULT" in kinds

        # P-T. SINE alone requested closure and the presenter routed the same id.
        close_facts = [
            fact
            for fact in journey["facts"]
            if fact.kind == "SINE_POPUP_CLOSE_REQUESTED"
        ]
        assert len(close_facts) == 1
        assert close_facts[0].popup_request_id == request_id
        assert request_id not in presenter.active_request_ids()
        assert journey["popup_closed_results"] == [True]

        # U-W. The next normal observation of that exact certified resource is
        # classified by Resource Intent as STUDY_ALIGNED at confidence 1.00.
        after = bench.coordinator._classify_observation(bench.foreground.observe())
        bench.services.sine.observe(after)
        allowance = bench.services.resource_intent._allowance
        assert allowance is not None and allowance.active is True
        assert after.resource_intent.verdict.classification.value == "STUDY_ALIGNED"
        assert after.resource_intent.verdict.confidence == 1.00
    finally:
        presenter.emergency_close_all("disposed_by_test")
        qt_app.processEvents()


def test_uat02_study_end_before_click_rejects_without_allowance(bench, qt_app):
    journey = _open_real_study_material_popup(bench, qt_app)
    presenter = journey["presenter"]
    window = journey["window"]
    request_id = journey["request_id"]
    try:
        assert bench.services.study.complete().accepted
        window._buttons[SineResponse.THIS_IS_STUDY_MATERIAL].click()
        _pump_sine(
            bench,
            presenter,
            qt_app,
            journey["facts"],
            until=lambda: bool(journey["record_result_results"]),
        )

        assert journey["popup_response_results"] == [True]
        assert journey["allowance_results"] == []
        assert journey["record_result_results"] == [True]
        assert bench.services.resource_intent._allowance is None
        assert request_id in presenter.active_request_ids()
        assert window.isVisible()
        assert "STUDY MATERIAL ALLOWANCE NOT APPLIED" in window._status.text()
        assert "NO ACTIVE BLOCK" in window._status.text()
        assert all(button.isEnabled() for button in window._buttons.values())
        assert not any(
            fact.kind == "SINE_POPUP_CLOSE_REQUESTED"
            for fact in journey["facts"]
        )
    finally:
        presenter.emergency_close_all("disposed_by_test")
        qt_app.processEvents()


# ---------------------------------------------------------------------------
# A / B -- the button is intent only
# ---------------------------------------------------------------------------

def test_a0_controller_queue_rejection_unlocks_the_exact_popup(qt_app):
    """A full engine queue must not leave the clicked popup pending forever."""

    from CONTROL_STATION.controller import ControlStationController, EngineCommand

    class Presenter:
        def __init__(self):
            self.rejections = []

        def show_action_rejection(self, request_id, message):
            self.rejections.append((request_id, message))
            return True

    controller = ControlStationController()
    presenter = Presenter()
    controller._sine_presenter = presenter
    while not controller._command_queue.full():
        controller._command_queue.put_nowait(EngineCommand(kind="occupied"))

    accepted = controller._submit_sine_user_action(
        "popup_queue_full",
        "this_is_study_material",
        time.monotonic_ns(),
    )

    assert accepted is False
    assert presenter.rejections == [
        ("popup_queue_full", "ACTION NOT SENT · ENGINE BUSY · TRY AGAIN")
    ]

def test_a_button_click_emits_exactly_one_user_intent(qt_app):
    window, seen = _build_window_with_study_button()
    try:
        button = window._buttons[SineResponse.THIS_IS_STUDY_MATERIAL]
        button.click()
        assert seen == [SineResponse.THIS_IS_STUDY_MATERIAL.value], seen
    finally:
        _dispose(window)


def test_b_button_does_not_locally_close_the_popup(qt_app):
    window, _seen = _build_window_with_study_button()
    try:
        window._buttons[SineResponse.THIS_IS_STUDY_MATERIAL].click()
        assert window.isVisible() or not window._authority_close_allowed, (
            "the button closed the popup without a SINE close fact"
        )
        assert window._authority_close_allowed is False
    finally:
        _dispose(window)


def test_b2_only_authority_close_may_close_the_window(qt_app):
    """Presentation closes on an exact SINE close fact, never on intent."""

    import ast
    import pathlib

    source = (_lab.ULTIMATE / "SINE" / "popup.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    emit = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_emit_action"
    )
    body = ast.unparse(emit)
    assert "self.close()" not in body
    assert "force_close" not in body


# ---------------------------------------------------------------------------
# C -- denial keeps the popup open and retryable
# ---------------------------------------------------------------------------

def test_c_denied_result_keeps_popup_open_and_retryable(qt_app):
    window, _seen = _build_window_with_study_button()
    try:
        window.show_action_result(
            "STUDY MATERIAL ALLOWANCE NOT APPLIED · resource not eligible",
            allow_retry=True,
        )
        assert window._authority_close_allowed is False
        text = window._status.text().upper()
        assert "NOT APPLIED" in text, window._status.text()
        for button in window._buttons.values():
            assert button.isEnabled(), "denial must leave the buttons retryable"
    finally:
        _dispose(window)


def test_c2_presenter_surfaces_denial_reason_and_never_closes(qt_app):
    """The presenter's denial branch shows the reason and allows retry."""

    import ast

    source = (_lab.ULTIMATE / "SINE" / "popup.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    apply_fact = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "_apply_fact_on_gui_thread"
    )
    body = ast.unparse(apply_fact)
    denial = body.split("SINE_STUDY_MATERIAL_RESULT")[1]
    denial = denial.split("SINE_PROTECTED_RED_AWAITING_RECOVERY")[0]
    assert "STUDY MATERIAL ALLOWANCE NOT APPLIED" in denial
    assert "allow_retry=True" in denial
    assert "close_from_authority" not in denial, (
        "a denied Study-material request must not close the popup"
    )


# ---------------------------------------------------------------------------
# E / F -- stale and cross-popup safety
# ---------------------------------------------------------------------------

def test_e_stale_request_is_refused_and_not_falsely_closed(bench):
    sine = bench.services.sine
    assert (
        sine.record_study_material_result(
            request_id="popup_stale",
            granted=True,
            occurred_monotonic_ns=time.monotonic_ns(),
            reason="granted",
        )
        is False
    )


def test_f_granted_result_for_popup_a_cannot_close_popup_b(qt_app):
    """The presenter routes a close strictly by popup_request_id."""

    import ast

    source = (_lab.ULTIMATE / "SINE" / "popup.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    close = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_close_on_gui_thread"
    )
    body = ast.unparse(close)
    assert "self._windows.get(str(request_id or ''))" in body.replace('"', "'")
    assert "for " not in body, "a close must never fan out across popups"


def test_g_presenter_closes_the_exact_popup_on_close_requested(qt_app):
    window, _seen = _build_window_with_study_button()
    try:
        assert window._authority_close_allowed is False
        assert window.close_from_authority("study_material_allowance_granted") is True
        assert window._authority_close_allowed is True
    finally:
        _dispose(window)


# ---------------------------------------------------------------------------
# UAT-03 -- centring
# ---------------------------------------------------------------------------

def _expected_centre(area: QRect, width: int, height: int) -> tuple[int, int]:
    return (
        area.x() + max(12, (area.width() - width) // 2),
        area.y() + max(12, (area.height() - height) // 2),
    )


def test_k_single_monitor_popup_is_geometrically_centred(qt_app):
    window, _seen = _build_window_with_study_button()
    try:
        window._place_window()
        screen = QApplication.screenAt(QPoint(0, 0)) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x, y = _expected_centre(area, window.width(), window.height())
        assert (window.x(), window.y()) == (x, y)
        # Genuinely centred, not merely "not at the right edge".
        assert abs(
            (window.x() + window.width() // 2) - (area.x() + area.width() // 2)
        ) <= 1
    finally:
        _dispose(window)


def test_l_popup_is_centred_on_the_selected_screen(qt_app):
    """Placement follows the chosen screen, never the primary by assumption."""

    import ast

    source = (_lab.ULTIMATE / "SINE" / "popup.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    place = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_place_window"
    )
    body = ast.unparse(place)
    assert "QApplication.screenAt(point)" in body
    assert "availableGeometry()" in body
    # x now derives from the width difference, not from the right edge.
    assert "area.width() - self.width()) // 2" in body
    assert "area.width() - self.width() - 28" not in body


def test_m_work_area_with_taskbar_is_respected(qt_app):
    """availableGeometry (not geometry) is the placement basis."""

    import ast

    source = (_lab.ULTIMATE / "SINE" / "popup.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    place = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_place_window"
    )
    body = ast.unparse(place)
    assert "availableGeometry" in body
    assert "screen.geometry()" not in body

    window, _seen = _build_window_with_study_button()
    try:
        window._place_window()
        screen = QApplication.screenAt(QPoint(0, 0)) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        assert window.x() >= area.x()
        assert window.y() >= area.y()
    finally:
        _dispose(window)


# ---------------------------------------------------------------------------
# UAT-04 -- countdown
# ---------------------------------------------------------------------------

def test_p_same_popup_cannot_start_its_countdown_twice(qt_app):
    """CASE A is disproved: the same occurrence cannot restart its timer."""

    window, _seen = _build_window_with_study_button()
    try:
        window.present()
        qt_app.processEvents()
        assert window._shown_reported is True
        first = window._elapsed.elapsed()
        time.sleep(0.15)

        # Every ordinary foreground event -- alt-tab, Snipping Tool, a
        # screenshot -- can only ever re-enter this path.  It is guarded.
        window._report_shown_once()
        window._report_shown_once()
        qt_app.processEvents()

        second = window._elapsed.elapsed()
        assert second >= first, "the countdown restarted on a repeat show"
        assert second >= 140, f"elapsed went backwards: {first} -> {second}"
    finally:
        _dispose(window)


def test_n_focus_loss_does_not_restart_the_countdown(qt_app):
    window, _seen = _build_window_with_study_button()
    try:
        window.present()
        qt_app.processEvents()
        time.sleep(0.15)
        before = window._elapsed.elapsed()

        window.clearFocus()
        window.hide()
        window.show()
        qt_app.processEvents()

        after = window._elapsed.elapsed()
        assert after >= before, "focus loss restarted the same popup's countdown"
    finally:
        _dispose(window)


def test_q_a_new_request_gets_its_own_timer(qt_app):
    """CASE B: a NEW occurrence legitimately owns a NEW countdown."""

    first, _a = _build_window_with_study_button(request_id="popup_uat_1")
    second, _b = _build_window_with_study_button(request_id="popup_uat_2")
    try:
        assert first is not second
        assert first.request.request_id != second.request.request_id
        assert first._elapsed is not second._elapsed
    finally:
        _dispose(first, second)


def test_q2_real_stage_replacement_has_new_identity_and_legal_reason():
    """A real SINE-1 -> SINE-2 deadline creates a new occurrence and timer."""

    from types import SimpleNamespace

    from SINE.sine import SineAuthority, SinePolicy

    ns = 1_000_000_000
    clock = [time.monotonic_ns()]
    sine = SineAuthority(
        policy=SinePolicy(
            stage_1_visible_seconds=3600.0,
            stage_2_delay_seconds=1.0,
            stage_2_visible_seconds=3600.0,
            stage_3_delay_seconds=3600.0,
            stage_3_visible_seconds=3600.0,
        ),
        monotonic_ns=lambda: clock[0],
    )
    sine.start_session(session_id=1, profile_type="study")
    candidate = SimpleNamespace(
        candidate_uid="uat04-stage-candidate",
        session_id=1,
        profile_type="study",
        evidence=SimpleNamespace(
            observed_monotonic_ns=clock[0],
            dwell_seconds=0.0,
            threshold_seconds=0.0,
            study_context_token="uat04-study-context",
            resource_key="uat04-resource",
            resource_observation_token="uat04-observation",
            surface_class="youtube_watch",
            browser_evidence_kind="certified_url",
            process_name="chrome",
            process_id=1,
            hwnd=1,
            platform_key="youtube",
        ),
    )
    assert sine.request_trigger(
        candidate=candidate,
        operational_event_id=1,
        mirl_display_token=None,
    )
    first_facts = sine.advance(now_monotonic_ns=clock[0])
    old = next(fact.popup for fact in first_facts if fact.kind == "SINE_POPUP_REQUESTED")

    clock[0] += 1
    assert sine.popup_shown(
        request_id=old.request_id,
        shown_monotonic_ns=clock[0],
        popup_hwnd=100,
    )
    sine.advance(now_monotonic_ns=clock[0])

    clock[0] += ns
    replacement_facts = sine.advance(now_monotonic_ns=clock[0])
    new_fact = next(
        fact for fact in replacement_facts if fact.kind == "SINE_POPUP_REQUESTED"
    )
    new = new_fact.popup

    assert old.request_id != new.request_id
    assert int(old.stage) == 1
    assert int(new.stage) == 2
    assert old.occurrence == 1
    assert new.occurrence == 1
    assert old.candidate_uid == new.candidate_uid == candidate.candidate_uid
    assert new_fact.reason == "stage_2_deadline_reached"
    assert any(
        fact.kind == "SINE_POPUP_CLOSE_REQUESTED"
        and fact.popup_request_id == old.request_id
        and fact.reason == "superseded"
        for fact in replacement_facts
    )


# ---------------------------------------------------------------------------
# Shared popup builder
# ---------------------------------------------------------------------------

def _dispose(*windows) -> None:
    """Close and actually delete popups inside the test.

    ``WA_DeleteOnClose`` schedules a deferred delete.  Draining it here keeps
    the C++ objects from being destroyed during interpreter shutdown, which
    crashes PyQt.
    """

    app = QApplication.instance()
    for window in windows:
        try:
            window.force_close("disposed_by_test")
        except Exception:
            pass
    if app is not None:
        app.processEvents()


def _build_window_with_study_button(request_id: str = "popup_uat"):
    """One real SinePopupWindow offering THIS IS STUDY MATERIAL."""

    from SINE.sine import (
        SinePopupRequest,
        SinePresentation,
        _weber_fechner_projection,
        SineStage,
    )

    presentation = SinePresentation(
        world="blue",
        badge="SINE 1",
        headline="Study focus notice",
        message="The active study block is running.",
        study_mode=True,
        resource_title="Basal Ganglia Direct and Indirect Pathways",
        allowed_responses=(
            SineResponse.RETURN_TO_FOCUS,
            SineResponse.THIS_IS_STUDY_MATERIAL,
        ),
        weber_fechner=_weber_fechner_projection(SineStage.SINE_1),
    )
    request = SinePopupRequest(
        request_id=request_id,
        episode_uid="uat_episode",
        candidate_uid="uat_candidate",
        operational_event_id=1,
        stage=SineStage.SINE_1,
        occurrence=1,
        requested_monotonic_ns=time.monotonic_ns(),
        visible_seconds=45.0,
        protected=False,
        presentation=presentation,
    )
    seen: list[str] = []
    window = SinePopupWindow(request, reduced_motion=True)
    window.user_action.connect(lambda _rid, response, _ns: seen.append(response))
    return window, seen
