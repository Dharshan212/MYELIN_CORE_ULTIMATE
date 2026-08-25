"""Phase 2 — Study-SINE action cleanup and green COSECANT presentation."""

from __future__ import annotations

import ast
import pathlib
import time
from types import SimpleNamespace

import pytest

import _lab  # noqa: F401  (production import path + isolated storage)

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QPushButton

from COSECANT_STUDY_MODE.cosecant import (
    CosecantReturnTarget,
    CosecantRuntime,
    CosecantState,
    CosecantUiAction,
)
from COSECANT_STUDY_MODE.study import StudyCompletionReason, StudySnapshot, StudyState
from COSECANT_STUDY_MODE.view import ContinuityPopup, StudyConfirmationPopup
from SINE.popup import SinePopupWindow
from SINE.sine import (
    SineAuthority,
    SinePopupRequest,
    SineResponse,
    SineStage,
)
from UI_THEMES.theme import DEFAULT_THEME, build_application_stylesheet


NS = 10**9


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setStyleSheet(build_application_stylesheet())
    yield instance


def _episode(*, study_mode: bool):
    return SimpleNamespace(
        study_mode=study_mode,
        study_material_action_allowed=True,
        resource_title="Basal Ganglia Direct and Indirect Pathways",
    )


def _presentation(stage: SineStage, *, study_mode: bool = True):
    return SineAuthority()._presentation(
        _episode(study_mode=study_mode),
        stage,
    )


def _sine_window(stage: SineStage) -> SinePopupWindow:
    presentation = _presentation(stage)
    return SinePopupWindow(
        SinePopupRequest(
            request_id=f"phase2-{int(stage)}",
            episode_uid="phase2-episode",
            candidate_uid="phase2-candidate",
            operational_event_id=int(stage),
            stage=stage,
            occurrence=1,
            requested_monotonic_ns=time.monotonic_ns(),
            visible_seconds=45.0,
            protected=stage is SineStage.SINE_3,
            presentation=presentation,
        ),
        reduced_motion=True,
    )


@pytest.mark.parametrize("stage", [SineStage.SINE_1, SineStage.SINE_2])
def test_p2_01_to_06_study_sine_has_one_centered_return_button(app, stage):
    presentation = _presentation(stage)
    assert presentation.allowed_responses == (SineResponse.RETURN_TO_FOCUS,)
    assert SineResponse.THIS_IS_STUDY_MATERIAL not in presentation.allowed_responses

    window = _sine_window(stage)
    try:
        window.show()
        app.processEvents()
        assert set(window._buttons) == {SineResponse.RETURN_TO_FOCUS}
        button = window._buttons[SineResponse.RETURN_TO_FOCUS]
        assert button.text() == "RETURN TO STUDY"
        shell_center = button.parentWidget().rect().center().x()
        assert abs(button.geometry().center().x() - shell_center) <= 2
    finally:
        window.force_close("disposed_by_test")
        app.processEvents()


def test_p2_07_study_sine_3_has_zero_buttons(app):
    presentation = _presentation(SineStage.SINE_3)
    assert presentation.allowed_responses == ()
    window = _sine_window(SineStage.SINE_3)
    try:
        window.show()
        app.processEvents()
        assert window._buttons == {}
        assert window.findChildren(QPushButton) == []
    finally:
        window.force_close("disposed_by_test")
        app.processEvents()


def test_p2_09_uncertainty_popup_keeps_both_clarification_actions(app):
    popup = StudyConfirmationPopup()
    try:
        assert popup.study_button.text() == "THIS IS STUDY MATERIAL"
        assert popup.off_task_button.text() == "I'M COMING BACK"
    finally:
        popup.close()


def test_p2_10_return_to_study_button_is_intent_only(app):
    window = _sine_window(SineStage.SINE_1)
    seen: list[str] = []
    window.user_action.connect(lambda _request, response, _at: seen.append(response))
    try:
        window.show()
        app.processEvents()
        window._buttons[SineResponse.RETURN_TO_FOCUS].click()
        app.processEvents()
        assert seen == [SineResponse.RETURN_TO_FOCUS.value]
        assert window._authority_close_allowed is False
        assert window.isVisible() is True
    finally:
        window.force_close("disposed_by_test")
        app.processEvents()


def test_p2_11_normal_sine_action_policy_is_unchanged():
    assert _presentation(SineStage.SINE_1, study_mode=False).allowed_responses == (
        SineResponse.RETURN_TO_FOCUS,
        SineResponse.REQUEST_BREAK,
    )
    assert _presentation(SineStage.SINE_2, study_mode=False).allowed_responses == (
        SineResponse.RETURN_TO_FOCUS,
        SineResponse.CONTINUE_SINE,
    )
    assert _presentation(SineStage.SINE_3, study_mode=False).allowed_responses == ()


class _Clock:
    def __init__(self) -> None:
        self.now = 10 * NS

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += int(round(seconds * NS))


class _ContextSink:
    def publish_study_context(self, _context) -> bool:
        return True

    def retire_study_context(self, expected_context_token: str = "") -> bool:
        return bool(expected_context_token)


def _runtime_at_complete():
    clock = _Clock()
    runtime = CosecantRuntime(context_authority=_ContextSink(), monotonic_ns=clock)
    study = StudySnapshot(
        block_id="BLOCK-P2",
        generation=1,
        state=StudyState.PAUSED,
        subject="Neuroscience",
        task="lecture",
        keywords=("brain",),
        important_keywords=("lecture",),
        active_epoch_monotonic_ns=1,
        planned_seconds=3600,
        elapsed_seconds=0.0,
        remaining_seconds=3600,
        progress_percent=0.0,
        started_wall_time_utc="",
        paused_wall_time_utc="",
        completed_wall_time_utc="",
        ends_at_wall_time_utc="",
        completion_reason=StudyCompletionReason.NONE,
        last_action="paused for break",
        published_monotonic_ns=clock.now,
    )
    target = CosecantReturnTarget(
        study_context_token=study.context_token,
        platform_key="youtube",
        resource_token="lecture-p2",
        observed_monotonic_ns=clock.now,
    )
    assert runtime.start_break(
        study=study,
        selected_break_seconds=60,
        intended_return_target=target,
    ).accepted
    clock.advance(60)
    runtime.advance()
    assert runtime.snapshot().state is CosecantState.BREAK_COMPLETE
    return runtime, clock


def _visible_buttons(popup: ContinuityPopup) -> list[QPushButton]:
    return [button for button in popup.findChildren(QPushButton) if button.isVisible()]


def test_p2_12_break_complete_is_green_with_one_centered_return_button(app):
    runtime, _clock = _runtime_at_complete()
    popup = ContinuityPopup()
    try:
        popup.present_snapshot(runtime.snapshot())
        app.processEvents()
        assert popup.message_label.text() == "BREAK COMPLETE"
        assert _visible_buttons(popup) == [popup.return_button]
        assert popup.return_button.text() == "RETURN TO STUDY"
        shell_center = popup.return_button.parentWidget().rect().center().x()
        assert abs(popup.return_button.geometry().center().x() - shell_center) <= 2
    finally:
        popup.close()


def test_p2_13_break_already_over_is_green_with_one_return_button(app):
    runtime, clock = _runtime_at_complete()
    clock.advance(5 * 60)
    runtime.advance()
    popup = ContinuityPopup()
    try:
        popup.present_snapshot(runtime.snapshot())
        app.processEvents()
        assert popup.message_label.text() == "BREAK ALREADY OVER"
        assert _visible_buttons(popup) == [popup.return_button]
    finally:
        popup.close()


def test_p2_14_final_lock_stays_green_and_has_zero_buttons(app):
    runtime, clock = _runtime_at_complete()
    clock.advance(5 * 60)
    runtime.advance()
    clock.advance(60)
    runtime.advance()
    snapshot = runtime.snapshot()
    popup = ContinuityPopup()
    try:
        popup.present_snapshot(snapshot)
        app.processEvents()
        assert snapshot.state is CosecantState.FINAL_LOCK
        assert snapshot.allowed_actions == ()
        assert popup.message_label.text() == "COME BACK PLEASE"
        assert _visible_buttons(popup) == []
        assert popup.protected_label.isVisible() is True
    finally:
        popup._snapshot = None
        popup.close()


def test_p2_12_to_14_cosecant_theme_uses_only_the_green_stage_family():
    stylesheet = build_application_stylesheet()
    assert "QFrame#cosecantPopupShell" in stylesheet
    assert "QLabel#cosecantPopupStatusDot" in stylesheet
    assert "QPushButton#cosecantReturnIntentButton" in stylesheet
    assert DEFAULT_THEME.green in stylesheet

    source = (_lab.ULTIMATE / "UI_THEMES" / "theme.py").read_text(encoding="utf-8")
    block = source.split("/* COSECANT continuity popup", 1)[1].split('"""', 1)[0]
    assert "{green}" in block
    assert "{cyan}" not in block
    assert "{amber}" not in block
    assert "{red}" not in block


def test_p2_17_continuity_popup_contains_no_timer_or_return_verifier():
    path = _lab.ULTIMATE / "COSECANT_STUDY_MODE" / "view.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    popup_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ContinuityPopup"
    )
    calls = {
        node.func.id
        for node in ast.walk(popup_class)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "QTimer" not in calls
    assert "CosecantRuntime" not in calls
    assert "StudyReturnObservation" not in calls

