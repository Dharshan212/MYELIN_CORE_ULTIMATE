"""Phase 1 — reminder-scoped COSECANT return-intent acknowledgement.

The button is intent only.  These tests pin the presentation effect while
proving that the frozen escalation deadlines and three-second factual return
physiology remain authoritative.
"""

from __future__ import annotations

import _lab  # noqa: F401  (production import path + isolated storage)

from PyQt6.QtWidgets import QApplication

from COSECANT_STUDY_MODE.cosecant import (
    CosecantFactKind,
    CosecantReturnTarget,
    CosecantRuntime,
    CosecantState,
    CosecantUiAction,
    StudyPresence,
    StudyReturnObservation,
)
from COSECANT_STUDY_MODE.study import StudyCompletionReason, StudySnapshot, StudyState
from COSECANT_STUDY_MODE.view import ContinuityPopup


NS = 10**9
BREAK_SECONDS = 60
ALREADY_OVER_DELAY = 5 * 60
FINAL_LOCK_DELAY = 60


class Clock:
    def __init__(self) -> None:
        self.now = 10 * NS

    def __call__(self) -> int:
        return self.now

    def advance(self, seconds: float) -> int:
        self.now += int(round(seconds * NS))
        return self.now


class ContextSink:
    def __init__(self) -> None:
        self.published = 0
        self.retired = 0

    def publish_study_context(self, _context) -> bool:
        self.published += 1
        return True

    def retire_study_context(self, expected_context_token: str = "") -> bool:
        assert expected_context_token
        self.retired += 1
        return True


def study(clock: Clock, *, generation: int = 1) -> StudySnapshot:
    return StudySnapshot(
        block_id=f"BLOCK-P1-{generation}",
        generation=generation,
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


class Episode:
    def __init__(self, *, generation: int = 1) -> None:
        self.clock = Clock()
        self.sink = ContextSink()
        self.runtime = CosecantRuntime(
            context_authority=self.sink,
            monotonic_ns=self.clock,
        )
        paused = study(self.clock, generation=generation)
        target = CosecantReturnTarget(
            study_context_token=paused.context_token,
            platform_key="youtube",
            resource_token=f"lecture-{generation}",
            observed_monotonic_ns=self.clock.now,
        )
        result = self.runtime.start_break(
            study=paused,
            selected_break_seconds=BREAK_SECONDS,
            intended_return_target=target,
        )
        assert result.accepted, result.message

    def advance(self, seconds: float):
        self.clock.advance(seconds)
        return self.runtime.advance()

    def to_complete(self) -> None:
        self.advance(BREAK_SECONDS)
        assert self.runtime.snapshot().state is CosecantState.BREAK_COMPLETE

    def to_already_over(self) -> None:
        self.to_complete()
        self.advance(ALREADY_OVER_DELAY)
        assert self.runtime.snapshot().state is CosecantState.BREAK_ALREADY_OVER

    def observation(self, *, present: bool = True) -> StudyReturnObservation:
        snapshot = self.runtime.snapshot()
        return StudyReturnObservation(
            presence=StudyPresence.PRESENT if present else StudyPresence.ABSENT,
            study_block_id=snapshot.study_block_id,
            break_id=snapshot.break_id,
            context_token=snapshot.study_context_token,
            observed_monotonic_ns=self.clock.now,
            source="RESOURCE_INTENT",
            evidence_token=f"evidence-{self.clock.now}",
            fresh=True,
            exact_resource_confirmed=present,
        )

    def observe(self, *, present: bool = True):
        return self.runtime.observe_return(self.observation(present=present))


def test_p1_01_break_complete_click_acknowledges_only_presentation():
    episode = Episode()
    episode.to_complete()
    before = episode.runtime.snapshot()
    assert before.popup_required is True

    result = episode.runtime.record_return_intent()
    after = episode.runtime.snapshot()

    assert result.accepted is True
    assert [fact.kind for fact in result.facts] == [
        CosecantFactKind.RETURN_INTENT_RECORDED
    ]
    assert after.popup_required is False
    assert after.state is CosecantState.BREAK_COMPLETE
    assert after.break_id == before.break_id
    assert after.already_over_due_monotonic_ns == before.already_over_due_monotonic_ns
    assert after.final_lock_due_monotonic_ns == before.final_lock_due_monotonic_ns
    assert after.return_confirmed is False
    assert episode.sink.retired == 0


def test_p1_01_authoritative_acknowledgement_hides_the_live_popup():
    app = QApplication.instance() or QApplication([])
    episode = Episode()
    episode.to_complete()
    popup = ContinuityPopup()
    try:
        popup.present_snapshot(episode.runtime.snapshot())
        app.processEvents()
        assert popup.isVisible() is True

        episode.runtime.record_return_intent()
        popup.present_snapshot(episode.runtime.snapshot())
        app.processEvents()
        assert popup.isVisible() is False
    finally:
        popup.close()


def test_p1_02_break_already_over_click_acknowledges_only_that_reminder():
    episode = Episode()
    episode.to_already_over()
    assert episode.runtime.snapshot().popup_required is True

    result = episode.runtime.record_return_intent()
    snapshot = episode.runtime.snapshot()

    assert result.accepted is True
    assert snapshot.popup_required is False
    assert snapshot.state is CosecantState.BREAK_ALREADY_OVER
    assert snapshot.return_confirmed is False


def test_p1_03_acknowledged_complete_does_not_hide_already_over():
    episode = Episode()
    episode.to_complete()
    episode.runtime.record_return_intent()
    assert episode.runtime.snapshot().popup_required is False

    episode.advance(ALREADY_OVER_DELAY)
    snapshot = episode.runtime.snapshot()

    assert snapshot.state is CosecantState.BREAK_ALREADY_OVER
    assert snapshot.popup_required is True
    assert CosecantUiAction.RETURN_TO_STUDY in snapshot.allowed_actions


def test_p1_04_acknowledged_already_over_does_not_hide_final_lock():
    episode = Episode()
    episode.to_already_over()
    episode.runtime.record_return_intent()

    episode.advance(FINAL_LOCK_DELAY)
    snapshot = episode.runtime.snapshot()

    assert snapshot.state is CosecantState.FINAL_LOCK
    assert snapshot.popup_required is True
    assert snapshot.popup_must_remain_open is True
    assert snapshot.allowed_actions == ()


def test_p1_05_return_confirmation_from_acknowledged_reminder_stays_hidden():
    episode = Episode()
    episode.to_complete()
    episode.runtime.record_return_intent()

    episode.observe()
    snapshot = episode.runtime.snapshot()

    assert snapshot.state is CosecantState.RETURN_CONFIRMING
    assert snapshot.popup_required is False
    assert snapshot.final_locked is False


def test_p1_06_return_confirmation_from_final_lock_stays_visible_and_locked():
    episode = Episode()
    episode.to_already_over()
    episode.advance(FINAL_LOCK_DELAY)

    episode.observe()
    snapshot = episode.runtime.snapshot()

    assert snapshot.state is CosecantState.RETURN_CONFIRMING
    assert snapshot.popup_required is True
    assert snapshot.popup_must_remain_open is True
    assert snapshot.final_locked is True


def test_p1_07_acknowledgement_does_not_leak_to_a_new_break():
    episode = Episode(generation=1)
    episode.to_complete()
    episode.runtime.record_return_intent()
    episode.runtime.cancel_for_session_end()

    paused = study(episode.clock, generation=2)
    target = CosecantReturnTarget(
        study_context_token=paused.context_token,
        platform_key="youtube",
        resource_token="lecture-2",
        observed_monotonic_ns=episode.clock.now,
    )
    result = episode.runtime.start_break(
        study=paused,
        selected_break_seconds=BREAK_SECONDS,
        intended_return_target=target,
    )
    assert result.accepted, result.message
    episode.advance(BREAK_SECONDS)
    snapshot = episode.runtime.snapshot()

    assert snapshot.popup_required is True
    assert snapshot.state is CosecantState.BREAK_COMPLETE


def test_p1_08_click_never_confirms_return_or_retires_break_context():
    episode = Episode()
    episode.to_complete()

    episode.runtime.record_return_intent()
    snapshot = episode.runtime.snapshot()

    assert snapshot.return_confirmed is False
    assert snapshot.state is CosecantState.BREAK_COMPLETE
    assert episode.sink.retired == 0


def test_p1_10_exact_three_second_return_after_click_is_unchanged():
    episode = Episode()
    episode.to_complete()
    episode.runtime.record_return_intent()
    episode.observe()
    episode.advance(1.5)
    episode.observe()
    episode.advance(1.5)
    result = episode.observe()
    snapshot = episode.runtime.snapshot()

    assert result.accepted is True
    assert snapshot.state is CosecantState.CONFIRMED
    assert snapshot.return_confirmed is True
    assert episode.sink.retired == 1


def test_p1_11_automatic_exact_return_without_click_is_unchanged():
    episode = Episode()
    episode.to_complete()
    episode.observe()
    assert episode.runtime.snapshot().popup_required is True
    episode.advance(1.5)
    episode.observe()
    episode.advance(1.5)
    episode.observe()

    snapshot = episode.runtime.snapshot()
    assert snapshot.state is CosecantState.CONFIRMED
    assert snapshot.return_confirmed is True
    assert episode.sink.retired == 1
