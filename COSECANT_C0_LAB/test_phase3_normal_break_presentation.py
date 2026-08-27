"""External Phase-3 acceptance for Normal Break presentation and transport."""

from __future__ import annotations

import os
import queue
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

import _lab  # noqa: F401 - installs the production tree on sys.path

from CONTROL_STATION.controller import ControlStationController, TERMINAL_KINDS
from CONTROL_STATION.launcher import ControlPage
from SINE.normal_break import NormalBreakAuthority
from SINE.popup import (
    NormalBreakActiveWindow,
    NormalBreakPresenter,
    NormalBreakSelectorWindow,
)
from SINE.sine import SineAuthority, SineResponse, SineStage


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance


def _pending(runtime: NormalBreakAuthority, *, now_ns: int | None = None):
    now = time.monotonic_ns() if now_ns is None else now_ns
    result = runtime.request_duration(
        episode_uid="episode-1",
        candidate_uid="candidate-1",
        source_sine_popup_request_id="popup-1",
        requested_monotonic_ns=now,
        session_id=1,
    )
    assert result.accepted
    runtime.drain_facts()
    return result.facts[0]


def _started(runtime: NormalBreakAuthority, pending, *, minutes: int = 5):
    result = runtime.start_break(
        **{
            "break_id": pending.break_id,
            "generation": pending.generation,
            "episode_uid": pending.episode_uid,
            "candidate_uid": pending.candidate_uid,
            "source_sine_popup_request_id": pending.source_sine_popup_request_id,
        },
        selected_minutes=minutes,
        started_monotonic_ns=pending.occurred_monotonic_ns + 1,
    )
    assert result.accepted
    runtime.drain_facts()
    return result.facts[0]


def _episode(*, study: bool = False, completion: str = ""):
    return SimpleNamespace(
        study_mode=study,
        resource_title="Resource",
        post_normal_break_completion_kind=completion,
    )


class _EngineStub(QObject):
    engine_status_changed = pyqtSignal(object)

    def __init__(self, *, stop_result: bool = True) -> None:
        super().__init__()
        self.stop_result = stop_result
        self.stop_payloads = []

    def pause(self):
        return True

    def set_profile_type(self, _profile):
        return True

    def request_normal_break_stop(self, payload):
        self.stop_payloads.append(dict(payload))
        return self.stop_result


class _LifecycleStub:
    def request_start(self):
        return True

    def request_stop(self):
        return True

    def request_emergency(self):
        return True


class _ProfilesStub:
    def all_profiles(self):
        return (SimpleNamespace(label="General", key="general"),)

    def set_active(self, _key):
        return True


def _control_page(*, stop_result: bool = True):
    engine = _EngineStub(stop_result=stop_result)
    page = ControlPage(
        engine=engine,
        lifecycle=_LifecycleStub(),
        profiles=_ProfilesStub(),
    )
    return page, engine


def test_p3_normal_sine_button_matrix_and_study_contract_are_exact():
    sine = SineAuthority()

    normal_1 = sine._presentation(_episode(), SineStage.SINE_1)
    normal_2 = sine._presentation(_episode(), SineStage.SINE_2)
    normal_3 = sine._presentation(_episode(), SineStage.SINE_3)
    assert normal_1.allowed_responses == (
        SineResponse.RETURN_TO_FOCUS,
        SineResponse.REQUEST_BREAK,
    )
    assert normal_2.allowed_responses == (SineResponse.RETURN_TO_FOCUS,)
    assert SineResponse.CONTINUE_SINE not in normal_2.allowed_responses
    assert normal_3.allowed_responses == ()

    for stage in (SineStage.SINE_1, SineStage.SINE_2):
        assert sine._presentation(_episode(study=True), stage).allowed_responses == (
            SineResponse.RETURN_TO_FOCUS,
        )
    assert sine._presentation(
        _episode(study=True), SineStage.SINE_3
    ).allowed_responses == ()


@pytest.mark.parametrize(
    "completion",
    ["NORMAL_BREAK_COMPLETED", "NORMAL_BREAK_STOPPED"],
)
def test_p3_post_break_sine2_is_the_welcome_back_surface(completion):
    presentation = SineAuthority()._presentation(
        _episode(completion=completion),
        SineStage.SINE_2,
    )
    assert presentation.headline == "WELCOME BACK"
    assert "refreshed" in presentation.message.lower()
    assert "come back to focus" in presentation.message.lower()
    assert presentation.allowed_responses == (SineResponse.RETURN_TO_FOCUS,)


def test_p3_ordinary_normal_sine2_is_not_mislabeled_welcome_back():
    presentation = SineAuthority()._presentation(_episode(), SineStage.SINE_2)
    assert presentation.headline == "Still Here?"
    assert presentation.allowed_responses == (SineResponse.RETURN_TO_FOCUS,)


@pytest.mark.parametrize("invalid", ["", "4", "31", "5.5", "-5", "five"])
def test_p3_selector_has_no_default_and_rejects_invalid_duration_locally(app, invalid):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-1")
    selector = NormalBreakSelectorWindow(_pending(runtime))
    emitted = []
    selector.start_requested.connect(emitted.append)
    assert selector._minutes.text() == ""
    selector._minutes.setText(invalid)
    selector._request_start()
    assert emitted == []
    selector.force_close()
    app.processEvents()


@pytest.mark.parametrize("minutes", [5, 30])
def test_p3_selector_emits_exact_identity_and_whole_duration(app, minutes):
    runtime = NormalBreakAuthority(break_id_factory=lambda: f"break-{minutes}")
    pending = _pending(runtime)
    selector = NormalBreakSelectorWindow(pending)
    emitted = []
    selector.start_requested.connect(emitted.append)
    selector._minutes.setText(str(minutes))
    selector._request_start()
    assert emitted == [
        {
            "break_id": pending.break_id,
            "generation": pending.generation,
            "episode_uid": pending.episode_uid,
            "candidate_uid": pending.candidate_uid,
            "source_sine_popup_request_id": pending.source_sine_popup_request_id,
            "selected_minutes": minutes,
        }
    ]
    selector.force_close()
    app.processEvents()


def test_p3_selector_latches_first_valid_start_and_suppresses_repeated_actions(app):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-latched-start")
    selector = NormalBreakSelectorWindow(_pending(runtime))
    starts = []
    cancels = []
    selector.start_requested.connect(starts.append)
    selector.cancel_requested.connect(cancels.append)
    selector._minutes.setText("5")

    selector._minutes.returnPressed.emit()
    selector._minutes.returnPressed.emit()
    selector._start.click()
    selector._cancel.click()

    assert len(starts) == 1
    assert cancels == []
    assert selector._action_in_flight is True
    assert selector._minutes.isEnabled() is False
    assert selector._start.isEnabled() is False
    assert selector._cancel.isEnabled() is False
    selector.force_close()
    app.processEvents()


def test_p3_selector_latches_cancel_and_suppresses_following_start_or_cancel(app):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-latched-cancel")
    selector = NormalBreakSelectorWindow(_pending(runtime))
    starts = []
    cancels = []
    selector.start_requested.connect(starts.append)
    selector.cancel_requested.connect(cancels.append)
    selector._minutes.setText("5")

    selector._cancel.click()
    selector._minutes.returnPressed.emit()
    selector._start.click()
    selector._cancel.click()

    assert starts == []
    assert len(cancels) == 1
    assert selector._action_in_flight is True
    assert selector._minutes.isEnabled() is False
    assert selector._start.isEnabled() is False
    assert selector._cancel.isEnabled() is False
    selector.force_close()
    app.processEvents()


def test_p3_selector_backend_rejection_unlocks_exactly_one_retry(app):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-retry")
    selector = NormalBreakSelectorWindow(_pending(runtime))
    starts = []
    selector.start_requested.connect(starts.append)
    selector._minutes.setText("5")

    selector._request_start()
    selector.set_authority_result("BACKEND REJECTED", allow_retry=True)

    assert selector._action_in_flight is False
    assert selector._minutes.isEnabled() is True
    assert selector._start.isEnabled() is True
    assert selector._cancel.isEnabled() is True
    selector._request_start()
    selector._request_start()
    assert len(starts) == 2
    selector.force_close()
    app.processEvents()


def test_p3_cancel_is_exact_identity_and_never_starts_break(app):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-cancel")
    pending = _pending(runtime)
    selector = NormalBreakSelectorWindow(pending)
    emitted = []
    selector.cancel_requested.connect(emitted.append)
    selector._request_cancel()
    assert emitted == [
        {
            "break_id": pending.break_id,
            "generation": pending.generation,
            "episode_uid": pending.episode_uid,
            "candidate_uid": pending.candidate_uid,
            "source_sine_popup_request_id": pending.source_sine_popup_request_id,
        }
    ]
    result = runtime.cancel_duration(**emitted[0])
    assert result.accepted
    assert all(fact.kind.value != "NORMAL_BREAK_STARTED" for fact in result.facts)
    selector.force_close()
    app.processEvents()


def test_p3_presenter_opens_active_only_after_started_fact_and_closes_on_stop(app):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-flow")
    pending = _pending(runtime)
    presenter = NormalBreakPresenter()
    presenter.apply_fact(pending)
    app.processEvents()
    assert presenter._selector is not None
    assert presenter._active is None

    started = _started(runtime, pending)
    presenter.apply_fact(started)
    app.processEvents()
    assert presenter._selector is None
    assert isinstance(presenter._active, NormalBreakActiveWindow)
    assert presenter._active._deadline_ns == started.deadline_monotonic_ns

    stopped = runtime.stop_break(
        break_id=started.break_id,
        generation=started.generation,
        episode_uid=started.episode_uid,
        candidate_uid=started.candidate_uid,
        occurred_monotonic_ns=started.occurred_monotonic_ns + 2,
    )
    assert stopped.accepted
    for fact in stopped.facts:
        presenter.apply_fact(fact)
    app.processEvents()
    assert presenter._active is None
    presenter.close_all()


def test_p3_natural_completion_closes_active_surface(app):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-complete")
    pending = _pending(runtime)
    started = _started(runtime, pending)
    presenter = NormalBreakPresenter()
    presenter.apply_fact(started)
    app.processEvents()
    assert presenter._active is not None

    completed = runtime.advance(now_monotonic_ns=started.deadline_monotonic_ns)
    assert completed.accepted
    presenter.apply_fact(completed.facts[0])
    app.processEvents()
    assert presenter._active is None
    presenter.close_all()


def test_p3_active_popup_is_noninteractive_and_has_exact_three_second_timeout(app):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-brief-popup")
    pending = _pending(runtime)
    started = _started(runtime, pending)
    window = NormalBreakActiveWindow(started)

    assert window._presentation_timer.isSingleShot() is True
    assert window._presentation_timer.interval() == 3_000
    assert window._enjoy.text() == "ENJOY YOUR BREAK"
    assert window._status.text() == "SAME SINE EPISODE HELD"
    assert all(
        button.text() != "STOP BREAK"
        for button in window.findChildren(QPushButton)
    )
    assert not hasattr(window, "stop_requested")

    window.present()
    app.processEvents()
    assert window.isVisible()
    QTest.qWait(3_250)

    assert sip.isdeleted(window)
    assert runtime.snapshot().active is True
    assert runtime.snapshot().break_id == started.break_id
    assert runtime.drain_facts() == ()


def test_p3_popup_timeout_forgets_surface_without_reopening_or_emitting_stop(app):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-one-popup")
    pending = _pending(runtime)
    started = _started(runtime, pending)
    presenter = NormalBreakPresenter()
    stop_payloads = []
    presenter.stop_requested.connect(stop_payloads.append)

    presenter.apply_fact(started)
    app.processEvents()
    active = presenter._active
    assert active is not None
    active._presentation_timeout_reached()
    app.processEvents()

    assert presenter._active is None
    assert stop_payloads == []
    assert runtime.snapshot().active is True
    assert runtime.drain_facts() == ()
    app.processEvents()
    assert presenter._active is None
    presenter.close_all()


def test_p3_selector_has_no_three_second_presentation_timeout(app):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-selector-stays")
    selector = NormalBreakSelectorWindow(_pending(runtime))
    selector.present()
    app.processEvents()
    assert selector.isVisible()
    assert not hasattr(selector, "_presentation_timer")
    selector.force_close()
    app.processEvents()


def test_p3_control_station_normal_break_card_starts_inactive(app):
    page, _engine = _control_page()
    assert page._normal_break_hint.text() == "Inactive"
    assert page._normal_break_source_value.text() == "\u2014"
    assert page._normal_break_elapsed.text() == "\u2014 / \u2014"
    assert page._normal_break_state.text() == "Inactive"
    assert page._normal_break_progress.text() == "\u2014"
    assert page._normal_break_stop.isHidden()
    page.deleteLater()
    app.processEvents()


def test_p3_control_station_projects_source_timestamps_progress_and_stop_identity(
    app, monkeypatch
):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-card")
    pending = _pending(runtime, now_ns=1_000_000_000)
    started = _started(runtime, pending)
    page, engine = _control_page()
    page._latest_blacklist_live_view = SimpleNamespace(
        resource_label="Instagram"
    )
    monkeypatch.setattr(
        "CONTROL_STATION.launcher.time.monotonic_ns",
        lambda: started.started_monotonic_ns + 134_000_000_000,
    )

    page.render_normal_break_fact(started)

    assert page._normal_break_hint.text() == "Active"
    assert page._normal_break_source_value.text() == "Instagram"
    assert page._normal_break_elapsed.text() == "02:14 / 05:00"
    assert page._normal_break_state.text() == "Active"
    assert page._normal_break_progress.text() == "45%"
    assert not page._normal_break_stop.isHidden()
    assert page._normal_break_stop.isEnabled()

    page._normal_break_stop.click()
    page._normal_break_stop.click()
    assert engine.stop_payloads == [
        {
            "break_id": started.break_id,
            "generation": started.generation,
            "episode_uid": started.episode_uid,
            "candidate_uid": started.candidate_uid,
        }
    ]
    assert page._normal_break_stop_in_flight is True
    assert page._normal_break_stop.isEnabled() is False

    stopped = runtime.stop_break(
        break_id=started.break_id,
        generation=started.generation,
        episode_uid=started.episode_uid,
        candidate_uid=started.candidate_uid,
        occurred_monotonic_ns=started.started_monotonic_ns + 135_000_000_000,
    )
    assert stopped.accepted
    for fact in stopped.facts:
        page.render_normal_break_fact(fact)
    assert page._normal_break_state.text() == "Inactive"
    assert page._normal_break_stop.isHidden()
    page.deleteLater()
    app.processEvents()


def test_p3_control_station_rejected_stop_unlocks_exact_active_break(app):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-retry-stop")
    pending = _pending(runtime)
    started = _started(runtime, pending)
    page, engine = _control_page(stop_result=False)
    page.render_normal_break_fact(started)

    page._normal_break_stop.click()

    assert len(engine.stop_payloads) == 1
    assert page._active_normal_break_fact is started
    assert page._normal_break_stop_in_flight is False
    assert page._normal_break_stop.isEnabled() is True
    page.deleteLater()
    app.processEvents()


def test_p3_control_station_natural_completion_resets_card_without_ui_authority(app):
    runtime = NormalBreakAuthority(break_id_factory=lambda: "break-card-complete")
    pending = _pending(runtime)
    started = _started(runtime, pending)
    page, engine = _control_page()
    page.render_normal_break_fact(started)
    assert page._normal_break_state.text() == "Active"

    completed = runtime.advance(now_monotonic_ns=started.deadline_monotonic_ns)
    assert completed.accepted
    assert engine.stop_payloads == []
    for fact in completed.facts:
        page.render_normal_break_fact(fact)

    assert page._normal_break_hint.text() == "Inactive"
    assert page._normal_break_source_value.text() == "\u2014"
    assert page._normal_break_elapsed.text() == "\u2014 / \u2014"
    assert page._normal_break_progress.text() == "\u2014"
    assert page._normal_break_stop.isHidden()
    page.deleteLater()
    app.processEvents()


def test_p3_control_station_live_telemetry_extends_past_new_break_card(app):
    page, _engine = _control_page()
    page.resize(1500, 1800)
    page.show()
    app.processEvents()

    feed_bottom = page._feed_card.mapTo(page, page._feed_card.rect().bottomLeft()).y()
    break_bottom = page._normal_break_card.mapTo(
        page, page._normal_break_card.rect().bottomLeft()
    ).y()
    assert feed_bottom >= break_bottom
    page.close()
    page.deleteLater()
    app.processEvents()


def test_p3_controller_transports_exact_action_and_waits_for_ack():
    controller = ControlStationController()
    payload = {
        "break_id": "break-1",
        "generation": 1,
        "episode_uid": "episode-1",
        "candidate_uid": "candidate-1",
        "source_sine_popup_request_id": "popup-1",
        "selected_minutes": 5,
    }
    captured = []

    def enqueue(kind, supplied, response):
        captured.append((kind, supplied))
        response.put_nowait(True)
        return True

    controller._enqueue_command = enqueue
    controller._normal_break_presenter = SimpleNamespace(
        show_command_result=lambda *args, **kwargs: None
    )
    assert controller._submit_normal_break_command("start", payload)
    assert captured == [("normal_break_start", payload)]


def test_p3_normal_break_facts_have_reserved_transport_and_still_reach_telemetry(app):
    assert "normal_break_fact" in TERMINAL_KINDS
    delivered = []
    dashboard = []
    controller = ControlStationController()
    controller._normal_break_presenter = SimpleNamespace(apply_fact=delivered.append)
    controller.normal_break_fact_changed.connect(dashboard.append)
    fact = object()
    assert not ControlStationController._route_prepared_view(
        controller,
        "normal_break_fact",
        {"kind": "normal_break_fact", "fact": fact},
    )
    assert delivered == [fact]
    assert dashboard == [fact]


def test_p3_controller_reuses_existing_exact_stop_transport():
    controller = ControlStationController()
    payload = {
        "break_id": "break-stop",
        "generation": 4,
        "episode_uid": "episode-stop",
        "candidate_uid": "candidate-stop",
    }
    captured = []

    def enqueue(kind, supplied, response):
        captured.append((kind, supplied))
        response.put_nowait(True)
        return True

    controller._enqueue_command = enqueue
    controller._normal_break_presenter = SimpleNamespace(
        show_command_result=lambda *args, **kwargs: None
    )
    assert controller.request_normal_break_stop(payload)
    assert captured == [("normal_break_stop", payload)]
