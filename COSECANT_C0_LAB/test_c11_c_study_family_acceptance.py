"""C11-C — complete Study-family integration acceptance.

LAB TESTING ONLY.  No production file is modified by this phase.

C10, C11-A and C11-B are frozen.  This file asks ONE question:

    can a real user move through the complete Study workflow without
    violating an authority boundary, losing durable state, corrupting
    navigation, or disturbing C10 / C11-A / C11-B?

It drives the ASSEMBLED family end to end -- launcher-shaped construction,
the real StudyView child surfaces, the real StudyPlanner, the real
NoteSession/NotesWorkspace over the real EngineStorage, and the real Monitor
coordinator for break-return physiology.

STANDING LAW re-asserted here, not re-derived:

    PLAN        != BEHAVIOUR
    NOTE        != EVIDENCE
    BUTTON      != FACT
    PREPARATION != START
    ALIGNMENT   != EXACT RETURN IDENTITY
    RUNNING     != COMMITTED

CLOCK CONTRACT -- inherited from C10.4-A/B: Study, COSECANT and SINE run on a
controlled monotonic clock; MIRL, Blacklist and Trigger keep their real
production clocks and carry no absolute-timing assertion.
"""

from __future__ import annotations

import os
import itertools
import threading
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _lab  # noqa: F401  -- installs the production path
from _lab import INSTAGRAM, LECTURE, MRBEAST, OTHER_LECTURE

from PyQt6.QtCore import QDate, QObject, QTime
from PyQt6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from COSECANT_STUDY_MODE.cosecant import CosecantState, CosecantUiAction
from COSECANT_STUDY_MODE.notes import (
    NoteKind,
    NoteSession,
    NotesWorkspace,
    SaveState,
    TextSpan,
)
from COSECANT_STUDY_MODE.planner import (
    DEFAULT_PLAN_ID,
    PlanStatus,
    RecurrenceKind,
    RecurrenceRule,
    StudyPlanner,
    timezone_available,
)
from COSECANT_STUDY_MODE.study import StudyState
from COSECANT_STUDY_MODE.view import StudyView

from test_c10_4_a_golden_assembly import (
    ALREADY_OVER_AT,
    BREAK_SECONDS,
    FINAL_LOCK_AT,
    IMPORTANT,
    KEYWORDS,
    SUBJECT,
    TASK,
    Journey,
)
from test_c10_4_b_stress_matrix import admit_break, reach_final_lock, start_study


ZONE = "Europe/London"
NAMED_ZONES = ("Asia/Kolkata", "Europe/London", "America/New_York")

if not timezone_available(ZONE):
    raise RuntimeError(
        "C11-C requires an IANA timezone database: py -3 -m pip install tzdata"
    )


# ---------------------------------------------------------------------------
# Launcher-shaped assembly.  This mirrors ControlStationWindow's ownership:
# ONE storage facade, ONE planner, ONE NoteSession, ONE NotesWorkspace, ONE
# StudyView, the view held inside a window for the shell's lifetime.
# ---------------------------------------------------------------------------


_KEEPALIVE: list = []


class FakeEngine(QObject):
    """The exact engine surface the Study shell consumes."""

    def __init__(self, *, red: bool = False) -> None:
        super().__init__()
        self.red = red
        self.restore_calls = 0

    def is_protected_red_active(self) -> bool:
        return self.red

    def request_protected_red_restore(self) -> bool:
        self.restore_calls += 1
        return True


class Settings(QObject):
    def snapshot(self):
        class Snap:
            clock_timezone = ZONE

        return Snap()


class Shell:
    """One assembled Study family, built the way the launcher builds it."""

    def __init__(self, storage, *, plan_id: str = DEFAULT_PLAN_ID, red: bool = False):
        self.storage = storage
        self.engine = FakeEngine(red=red)
        self.planner = StudyPlanner(plan_id=plan_id, repository=storage)
        self.session = NoteSession(store=storage)
        self.workspace = NotesWorkspace(session=self.session)
        self.view = StudyView(
            engine=self.engine,
            lifecycle=QObject(),
            settings=Settings(),
            planner=self.planner,
            timezone_choices=NAMED_ZONES,
            notes_workspace=self.workspace,
            note_store=storage,
        )
        self.window = QMainWindow()
        self.stack = QStackedWidget(self.window)
        self.stack.addWidget(self.view)
        self.window.setCentralWidget(self.stack)
        _KEEPALIVE.append(self)

    def shutdown(self) -> bool:
        """The proven B10 order: Notes drain, then the shell releases storage."""

        drained = self.workspace.shutdown(timeout=2.0)
        self.storage.shutdown()
        return bool(drained)


@pytest.fixture(scope="session")
def qt_app():
    existing = QApplication.instance()
    return existing if existing is not None else QApplication([])


@pytest.fixture
def isolated_lane():
    """One pristine shared-lane singleton per test, restored afterwards."""

    from PERSISTENCE.storage import _SharedStorageLane

    with _SharedStorageLane._lock:
        saved = (
            _SharedStorageLane._lane,
            set(_SharedStorageLane._owners),
            _SharedStorageLane._state,
        )
        _SharedStorageLane._lane = None
        _SharedStorageLane._owners = set()
        _SharedStorageLane._state = _SharedStorageLane.IDLE

    yield _SharedStorageLane

    with _SharedStorageLane._lock:
        leftover = _SharedStorageLane._lane
        (
            _SharedStorageLane._lane,
            _SharedStorageLane._owners,
            _SharedStorageLane._state,
        ) = saved
    if leftover is not None:
        try:
            leftover.shutdown(timeout_seconds=2.0)
        except Exception:                       # noqa: BLE001 - teardown only
            pass


@pytest.fixture
def shell(qt_app, isolated_lane):
    from PERSISTENCE.storage import EngineStorage

    built = Shell(EngineStorage())
    yield built
    try:
        built.shutdown()
    except Exception:                           # noqa: BLE001 - teardown only
        pass


_BLOCK_SEQ = itertools.count(1)


def plan_block(planner, *, block_id="", local_date="2026-09-01",
               recurrence=None, hour=9):
    """Store one block.  Ids are unique per call by default: the LAB database
    is shared across this module, so a fixed id would collide with a block an
    earlier test already made durable."""

    block_id = block_id or f"C11C-BLOCK-{next(_BLOCK_SEQ)}"
    return planner.add_block(
        subject="Neuroscience",
        task="basal ganglia",
        local_date=local_date,
        local_hour=hour,
        local_minute=0,
        timezone_id=ZONE,
        dst_fold=0,
        study_minutes=45,
        break_minutes=10,
        recurrence=recurrence or RecurrenceRule(kind=RecurrenceKind.NONE),
        block_id=block_id,
    )


def select_occurrence(panel, *, date="2026-09-01"):
    panel.view_date.setDate(QDate.fromString(date, "yyyy-MM-dd"))
    panel.render()
    panel.block_list.setCurrentRow(0)
    return panel._visible[0] if panel._visible else None


# ---------------------------------------------------------------------------
# 3. COMPLETE USER PATH — construction, PREPARE, START, navigation
# ---------------------------------------------------------------------------


def test_c11c_a_one_study_family_is_constructed(shell):
    """A. One of everything, exactly as the launcher builds it."""

    assert shell.view.planner_panel is not None
    assert shell.view.notes_panel is not None
    assert shell.view.planner_panel._planner is shell.planner
    assert shell.view.notes_panel._workspace is shell.workspace
    assert shell.view.notes_panel._store is shell.storage
    assert shell.workspace._session is shell.session
    assert shell.session._store is shell.storage
    # One storage owner: Notes did not acquire a second facade.
    from PERSISTENCE.storage import _SharedStorageLane

    assert _SharedStorageLane.owners() == 1


def test_c11c_b_prepare_reaches_ready_and_does_not_start(shell):
    """B + C. PREPARE -> READY; START is a separate explicit command."""

    journey = Journey()
    card = shell.view.timer_card
    card.subject_input.setText(SUBJECT)
    card.task_input.setText(TASK)
    card.keywords_input.setText("basal ganglia")
    card.important_keywords_input.setText("dopamine")

    emitted: list = []
    shell.view.prepare_requested.connect(lambda *args: emitted.append(args))
    card.prepare_button.click()

    assert len(emitted) == 1
    subject, task, planned, brk, block_id, generation, kw, imp = emitted[0]
    assert subject == SUBJECT and task == TASK
    assert kw == ("basal ganglia",) and imp == ("dopamine",), (
        "the explicit keyword fields did not survive the prepare wire"
    )

    # The engine side: PREPARE yields READY, never ACTIVE.
    result = journey.services.study.prepare(
        subject=subject, task=task, planned_seconds=planned,
        keywords=kw, important_keywords=imp,
    )
    assert result.accepted
    ready = journey.services.study.snapshot()
    assert ready.state is StudyState.READY, "PREPARE started Study"
    assert ready.subject == SUBJECT and ready.task == TASK
    assert journey.cosecant().state is CosecantState.INACTIVE, (
        "COSECANT started merely because Study was prepared"
    )

    # C. Only the explicit START moves READY -> ACTIVE.
    assert journey.services.study.start().accepted
    active = journey.services.study.snapshot()
    assert active.state is StudyState.ACTIVE
    assert active.block_id == ready.block_id
    assert active.generation == ready.generation
    assert active.remaining_seconds > 0, "the countdown did not begin"
    assert journey.cosecant().state is CosecantState.INACTIVE, (
        "COSECANT started merely because Study started"
    )


def test_c11c_d_navigation_during_active_study_is_inert(shell):
    """D. Child navigation while ACTIVE disturbs no authority."""

    journey = Journey()
    start_study(journey)
    study = journey.services.study.snapshot()
    assert study.state is StudyState.ACTIVE
    cosecant_before = journey.cosecant()
    intent_before = journey.services.resource_intent.live_view()

    shell.view.set_study_snapshot(study)
    shell.view.set_cosecant_snapshot(cosecant_before)
    view_study = shell.view._state.study
    view_cosecant = shell.view._state.cosecant

    for _ in range(3):
        shell.view.show_planner()
        shell.view.show_notes()
        shell.view.show_main_study()

    # Presentation kept exactly what it was given.
    assert shell.view._state.study is view_study
    assert shell.view._state.cosecant is view_cosecant
    # Engine truth never moved.
    after = journey.services.study.snapshot()
    assert after.state is StudyState.ACTIVE
    assert after.block_id == study.block_id
    assert after.generation == study.generation
    assert journey.cosecant().state is cosecant_before.state
    assert journey.cosecant().generation == cosecant_before.generation
    assert (
        journey.services.resource_intent.live_view().classification
        is intent_before.classification
    )


# ---------------------------------------------------------------------------
# 4. PLANNER -> STUDY REAL CHAIN
# ---------------------------------------------------------------------------


def test_c11c_planner_chain_reaches_ready_only(shell):
    """4. Plan -> persist -> canonical occurrence -> SET TIMER -> READY. STOP."""

    created = plan_block(shell.planner)
    stored = shell.storage.list_planner_blocks(plan_id=shell.planner.plan_id)
    # Membership, not an exact count: this LAB database is shared with the
    # C11-B module, which also writes into the default collection.
    assert created.block_id in {b.block_id for b in stored}, (
        "the planner block was not durable"
    )

    shell.view.show_planner()
    panel = shell.view.planner_panel
    occurrence = select_occurrence(panel)
    assert occurrence is not None

    emitted: list = []
    shell.view.prepare_requested.connect(lambda *args: emitted.append(args))
    panel.set_timer_button.click()

    assert len(emitted) == 1, f"no prepare dispatched: {panel.status_text()}"
    subject, task, planned, brk, block_id, generation, kw, imp = emitted[0]
    assert subject == "Neuroscience" and task == "basal ganglia"
    assert planned == 45 * 60 and brk == 10 * 60
    assert kw == () and imp == (), "Planner inferred keyword data"
    # Returned to MAIN STUDY so the user can press START themselves.
    assert shell.view.workspace.currentIndex() == 0

    # And the engine side of that request stops at READY.
    journey = Journey()
    assert journey.services.study.prepare(
        subject=subject, task=task, planned_seconds=planned,
        keywords=kw, important_keywords=imp,
    ).accepted
    assert journey.services.study.snapshot().state is StudyState.READY
    assert journey.cosecant().state is CosecantState.INACTIVE


def test_c11c_planner_touches_no_other_authority():
    """4. Planner imports nothing that could start or classify anything."""

    import ast
    import COSECANT_STUDY_MODE.planner as planner_module

    tree = ast.parse(open(planner_module.__file__, encoding="utf-8").read())
    imported: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    for forbidden in (
        "COSECANT_STUDY_MODE.study",
        "COSECANT_STUDY_MODE.cosecant",
        "COSECANT_STUDY_MODE.study_alignment",
        "CORE_ENGINE.monitor",
        "CORE_ENGINE.browser",
        "CORE_ENGINE.resource_intent",
        "CORE_ENGINE.blacklist",
        "CORE_ENGINE.trigger",
        "SINE.sine",
        "MIRL.mirl",
    ):
        assert forbidden not in imported, f"planner.py imported {forbidden}"


# ---------------------------------------------------------------------------
# 5. PLANNER RESTART PROOF
# ---------------------------------------------------------------------------


def test_c11c_planner_survives_a_clean_restart(qt_app, isolated_lane):
    """5. Run 1 plans and shuts down; Run 2 reconstructs and finds it."""

    from PERSISTENCE.storage import EngineStorage

    run_one = Shell(EngineStorage(), plan_id="C11C-RESTART-PLAN")
    rule = RecurrenceRule(
        kind=RecurrenceKind.CUSTOM_WEEKDAYS,
        weekdays=(0, 2, 4),
        end_date="2026-12-31",
    )
    created = plan_block(run_one.planner, block_id="RESTART-BLOCK", recurrence=rule)
    occurrence_before = run_one.planner.project(
        date_from="2026-09-02", date_to="2026-09-02"
    ).occurrences
    assert run_one.shutdown() is True

    # Run 2: brand-new objects, exactly as a relaunch builds them.
    run_two = Shell(EngineStorage(), plan_id="C11C-RESTART-PLAN")
    try:
        # A bare StudyPlanner() names the SAME collection on every launch.
        assert StudyPlanner().plan_id == DEFAULT_PLAN_ID == StudyPlanner().plan_id, (
            "a relaunch would mint a different planner collection"
        )
        assert run_two.planner.plan_id == run_one.planner.plan_id
        assert run_two.planner.blocks() == ()

        loaded = run_two.planner.load_persisted()
        assert len(loaded) == 1, "the persisted planner block did not return"
        block = loaded[0]
        assert block == created, "the reloaded block was not identical"
        assert block.version == created.version
        assert block.recurrence == rule
        assert block.timezone_id == ZONE

        occurrence_after = run_two.planner.project(
            date_from="2026-09-02", date_to="2026-09-02"
        ).occurrences
        assert [o.occurrence_key for o in occurrence_after] == [
            o.occurrence_key for o in occurrence_before
        ], "occurrence identity did not survive the restart"
    finally:
        run_two.shutdown()


# ---------------------------------------------------------------------------
# 6 + 7. NOTES REAL CHAIN AND RESTART
# ---------------------------------------------------------------------------


def test_c11c_notes_chain_and_restart(qt_app, isolated_lane):
    """6 + 7. Create, edit, save, leave, reopen, restart -- all durable."""

    from PERSISTENCE.storage import EngineStorage

    run_one = Shell(EngineStorage())
    run_one.view.show_notes()
    panel = run_one.view.notes_panel
    assert panel.create_note(title="Direct Pathway") is True

    document = run_one.workspace._document
    note_id = document.note_id
    block_id = document.blocks[0].block_id
    run_one.workspace._text_changed(
        block_id, (TextSpan(text="dopamine direct pathway lecture"),)
    )
    assert run_one.session.flush(timeout=3.0) is True
    run_one.workspace._refresh_status()
    assert run_one.workspace.save_label.text() == SaveState.SAVED.value

    # Leave Notes and come back: the same note is still current.
    run_one.view.show_main_study()
    run_one.view.show_notes()
    panel.refresh()
    assert any(s.note_id == note_id for s in panel._summaries)

    durable = run_one.storage.load_note(note_id)
    assert durable.revision_number >= 1
    assert durable.blocks[0].content[0].text == "dopamine direct pathway lecture"
    revision_before = durable.revision_number
    assert run_one.shutdown() is True

    # Run 2: reconstruct and reopen.
    run_two = Shell(EngineStorage())
    try:
        run_two.view.show_notes()
        run_two.view.notes_panel.refresh()
        summaries = run_two.view.notes_panel._summaries
        assert any(s.note_id == note_id for s in summaries), (
            "the persisted note did not survive the restart"
        )
        assert run_two.view.notes_panel.open_note(note_id) is True
        reopened = run_two.workspace._document
        assert reopened.note_id == note_id
        assert reopened.revision_number == revision_before
        assert reopened.blocks[0].content[0].text == (
            "dopamine direct pathway lecture"
        )
    finally:
        run_two.shutdown()


def test_c11c_note_content_is_never_evidence(shell):
    """6. NOTE != EVIDENCE, proven against the live engine."""

    journey = Journey()
    start_study(journey)
    intent_before = journey.services.resource_intent.live_view()

    shell.view.show_notes()
    shell.view.notes_panel.create_note(title="Basal ganglia lecture")
    block_id = shell.workspace._document.blocks[0].block_id
    shell.workspace._text_changed(
        block_id,
        (TextSpan(text="This YouTube video IS the basal ganglia lecture."),),
    )
    assert shell.session.flush(timeout=3.0)

    # Nothing the user wrote reached any sensing organ.
    after = journey.services.resource_intent.live_view()
    assert after.classification is intent_before.classification
    assert after.display_title == intent_before.display_title
    assert journey.cosecant().state is CosecantState.INACTIVE
    assert journey.services.study.snapshot().state is StudyState.ACTIVE

    # And an off-task resource is still off-task despite the note text.
    context = journey.route(MRBEAST, 10.0)
    from CORE_ENGINE.resource_intent import ResourceIntent

    assert context.resource_intent.verdict.classification is not (
        ResourceIntent.STUDY_ALIGNED
    ), "a note certified an entertainment resource as Study material"


# ---------------------------------------------------------------------------
# 8 + 9 + 14. STUDY -> BREAK -> COSECANT, EXACT RETURN, FINAL_LOCK
# ---------------------------------------------------------------------------


def test_c11c_full_break_return_chain():
    """8. The C10 ladder, driven end to end through the real coordinator."""

    journey = Journey()
    start_study(journey)
    started_at = admit_break(journey)

    assert journey.cosecant().state is CosecantState.BREAK_ACTIVE
    assert journey.services.study.snapshot().state is StudyState.PAUSED, (
        "Study did not pause when COSECANT took the break"
    )

    journey.route(INSTAGRAM, started_at + BREAK_SECONDS + 1.0)
    assert journey.cosecant().state is CosecantState.BREAK_COMPLETE

    journey.route(INSTAGRAM, started_at + ALREADY_OVER_AT)
    assert journey.cosecant().state is CosecantState.BREAK_ALREADY_OVER

    journey.route(INSTAGRAM, started_at + FINAL_LOCK_AT)
    locked = journey.cosecant()
    assert locked.state is CosecantState.FINAL_LOCK
    assert locked.final_locked is True
    assert locked.allowed_actions == (), "FINAL_LOCK offered an action"

    # The exact intended resource, continuously, for three seconds.
    r = started_at + FINAL_LOCK_AT + 5.0
    journey.route(LECTURE, r)
    assert journey.cosecant().state is CosecantState.RETURN_CONFIRMING
    journey.route(LECTURE, r + 1.5)
    assert journey.cosecant().return_confirmed is False, (
        "a return confirmed before three continuous seconds"
    )
    journey.route(LECTURE, r + 3.0)
    assert journey.cosecant().return_confirmed is True

    assert journey.fact_kinds.count("RETURN_CONFIRMED") == 1
    assert all(journey.batches_accepted)


def test_c11c_exact_return_identity_is_authoritative():
    """9. ALIGNMENT != EXACT RETURN IDENTITY."""

    journey = Journey()
    _started, r = reach_final_lock(journey)

    # A different lecture: Study-shaped, but not the frozen target.
    journey.route(OTHER_LECTURE, r)
    journey.route(OTHER_LECTURE, r + 1.5)
    journey.route(OTHER_LECTURE, r + 3.0)
    assert journey.cosecant().return_confirmed is False, (
        "a different exact resource confirmed the return"
    )
    assert journey.cosecant().state is CosecantState.FINAL_LOCK

    # Interrupted presence resets the three-second proof.
    journey.route(LECTURE, r + 10.0)
    assert journey.cosecant().state is CosecantState.RETURN_CONFIRMING
    journey.route(INSTAGRAM, r + 11.5)
    journey.route(LECTURE, r + 13.0)
    journey.route(LECTURE, r + 14.5)
    assert journey.cosecant().return_confirmed is False, (
        "an interrupted presence still confirmed"
    )

    # Continuous exact presence does confirm.
    journey.route(LECTURE, r + 16.0)
    assert journey.cosecant().return_confirmed is True


def test_c11c_final_lock_has_no_ui_escape_but_does_release(shell):
    """14. No close/Escape/navigation escape; the factual path still works."""

    from COSECANT_STUDY_MODE.view import ContinuityPopup

    journey = Journey()
    _started, r = reach_final_lock(journey)
    locked = journey.cosecant()

    popup = ContinuityPopup()
    _KEEPALIVE.append(popup)
    popup.present_snapshot(locked)
    assert popup.return_button.isVisible() is False
    assert popup.return_button.isEnabled() is False

    popup.close()
    assert popup.isVisible() is True, "close() escaped FINAL_LOCK"

    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtGui import QKeyEvent

    popup.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert popup.isVisible() is True, "Escape escaped FINAL_LOCK"

    # Navigating the Study child surfaces cannot release it either.
    shell.view.set_cosecant_snapshot(locked)
    shell.view.show_planner()
    shell.view.show_notes()
    shell.view.show_main_study()
    assert journey.cosecant().state is CosecantState.FINAL_LOCK
    assert journey.cosecant().return_confirmed is False

    # And it is NOT a deadlock: the factual path releases it.
    for step in (0.0, 1.5, 3.0):
        journey.route(LECTURE, r + step)
    assert journey.cosecant().return_confirmed is True

    popup._snapshot = None
    popup.close()


# ---------------------------------------------------------------------------
# 10. SINE / MIRL NON-INTERFERENCE
# ---------------------------------------------------------------------------


def test_c11c_planner_and_notes_do_not_move_sine_or_mirl(shell):
    """10. Planning and note-taking are not behaviour."""

    journey = Journey()
    start_study(journey)
    sine_before = journey.services.sine.live_view()
    mirl_before = journey.services.mirl.live_view()

    plan_block(shell.planner)
    shell.view.show_planner()
    select_occurrence(shell.view.planner_panel)
    shell.view.show_notes()
    shell.view.notes_panel.create_note(title="Planning notes")
    block_id = shell.workspace._document.blocks[0].block_id
    shell.workspace._text_changed(block_id, (TextSpan(text="revise later"),))
    assert shell.session.flush(timeout=3.0)
    shell.view.show_main_study()

    assert journey.services.sine.live_view() == sine_before, (
        "Planner/Notes activity moved SINE"
    )
    assert journey.services.mirl.live_view() == mirl_before, (
        "Planner/Notes activity moved MIRL"
    )


# ---------------------------------------------------------------------------
# 11. PROTECTED RED
# ---------------------------------------------------------------------------


def test_c11c_red_refuses_then_releases_the_same_preparation(qt_app, isolated_lane):
    """11. Red refuses at command time and does not burn the token."""

    from PERSISTENCE.storage import EngineStorage

    built = Shell(EngineStorage(), plan_id="C11C-RED", red=True)
    try:
        plan_block(built.planner)
        built.view.show_planner()
        panel = built.view.planner_panel
        occurrence = select_occurrence(panel)
        result = built.planner.prepare_cosecant_timer(occurrence)
        assert result.accepted
        preparation = result.preparation

        emitted: list = []
        built.view.prepare_requested.connect(lambda *args: emitted.append(args))

        assert built.view.confirm_planner_timer(built.planner, preparation) == (
            "protected_red"
        )
        assert emitted == [], "a Study PREPARE escaped during Protected Red"
        assert built.engine.restore_calls == 1, (
            "the authoritative Red surface was not restored"
        )

        # Red clears: the SAME preparation is still usable, exactly once.
        built.engine.red = False
        assert built.view.confirm_planner_timer(built.planner, preparation) == ""
        assert len(emitted) == 1
        assert built.view.confirm_planner_timer(built.planner, preparation) == (
            "preparation_expired"
        )
        assert len(emitted) == 1, "a one-use preparation dispatched twice"
    finally:
        built.shutdown()


# ---------------------------------------------------------------------------
# 12. STALE / RACE ATTACKS
# ---------------------------------------------------------------------------


def test_c11c_stale_and_race_attacks_are_refused(shell):
    """12. A-H, driven against the assembled family."""

    planner = shell.planner

    # A. stale Planner version
    block = plan_block(planner, block_id="ATTACK-A")
    current = planner.replace_block(replace(block, task="cerebellar circuits"))
    with pytest.raises(ValueError):
        planner.remove_block(block.block_id, expected_version=block.version)
    assert planner.block(block.block_id).version == current.version

    # B. forged occurrence
    genuine = planner.project(
        date_from="2026-09-01", date_to="2026-09-01"
    ).occurrences[0]
    forged = replace(genuine, scheduled_start_utc="2099-01-01T00:00:00.000Z")
    assert planner.prepare_cosecant_timer(forged).accepted is False

    # C + D. stale and reused one-use preparation
    fresh = planner.project(
        date_from="2026-09-01", date_to="2026-09-01"
    ).occurrences[0]
    prepared = planner.prepare_cosecant_timer(fresh)
    assert prepared.accepted
    assert planner.consume_preparation(prepared.preparation).accepted is True
    assert planner.consume_preparation(prepared.preparation).accepted is False

    later = planner.project(
        date_from="2026-09-01", date_to="2026-09-01"
    ).occurrences[0]
    stale_prep = planner.prepare_cosecant_timer(later)
    assert stale_prep.accepted
    planner.replace_block(
        replace(planner.block("ATTACK-A"), task="moved on again")
    )
    assert planner.consume_preparation(stale_prep.preparation).accepted is False

    # E. stale Note revision
    shell.view.show_notes()
    shell.view.notes_panel.create_note(title="Attack Note")
    note_id = shell.workspace._document.note_id
    assert shell.session.flush(timeout=3.0)
    durable = shell.storage.load_note(note_id)
    with pytest.raises(Exception):
        shell.storage.save_note(
            replace(durable, revision_number=0, title="STALE"),
            expected_revision=durable.revision_number,
        )
    assert shell.storage.load_note(note_id).title == durable.title

    # F. rejected oversized edit
    before = shell.workspace._document
    errors: list = []
    shell.workspace._show_error = errors.append
    shell.workspace._text_changed(
        before.blocks[0].block_id, (TextSpan(text="x" * 400_000),)
    )
    assert shell.workspace._document is before
    assert errors, "the user was not told the oversized edit failed"

    # G. stale Study identity
    journey = Journey()
    start_study(journey)
    stale_id, stale_gen = (
        journey.services.study.snapshot().block_id,
        journey.services.study.snapshot().generation,
    )
    assert journey.services.study.complete().accepted
    assert journey.services.study.prepare(
        subject=SUBJECT, task="cerebellar circuits", planned_seconds=3600,
        keywords=KEYWORDS, important_keywords=IMPORTANT,
    ).accepted
    assert journey.services.study.start().accepted
    journey.coordinator.command_queue.put({
        "kind": "study_action",
        "payload": {
            "action": "PAUSE",
            "expected_study_block_id": stale_id,
            "expected_study_generation": stale_gen,
        },
    })
    journey.coordinator._drain_commands()
    assert journey.services.study.snapshot().state is StudyState.ACTIVE, (
        "a stale Study identity paused a newer generation"
    )

    # H. older COSECANT presentation fact
    cosecant = journey.cosecant()
    newer = replace(
        cosecant,
        generation=cosecant.generation + 3,
        fact_sequence=cosecant.fact_sequence + 9,
    )
    shell.view.set_cosecant_snapshot(newer)
    shell.view.set_cosecant_snapshot(cosecant)
    assert shell.view._state.cosecant is newer, (
        "an older COSECANT fact replaced a newer same-session one"
    )


# ---------------------------------------------------------------------------
# 13. NAVIGATION + PRESENTATION EPOCH
# ---------------------------------------------------------------------------


def test_c11c_presentation_epoch_reset_survives_assembly(shell):
    """13. A new engine session clears presentation, not engine truth."""

    journey = Journey()
    start_study(journey)
    study = journey.services.study.snapshot()
    _started = admit_break(journey)
    cosecant = journey.cosecant()

    shell.view.set_study_snapshot(study)
    shell.view.set_cosecant_snapshot(cosecant)
    shell.view.show_planner()
    shell.view.show_notes()
    shell.view.show_main_study()
    assert shell.view._state.study is not None

    # A NEW engine presentation epoch.
    shell.view.render(None)
    assert shell.view._state.study is None
    assert shell.view._state.cosecant is None
    assert shell.view.state_pill.text() == f"STUDY · {StudyState.EMPTY.value}"

    # Authoritative engine truth is untouched by a presentation reset.
    assert journey.services.study.snapshot().state is StudyState.PAUSED
    assert journey.cosecant().state is cosecant.state
    assert journey.cosecant().break_id == cosecant.break_id

    # And a new session's lower generation is accepted, not refused as stale.
    fresh = replace(study, generation=1, published_monotonic_ns=1)
    shell.view.set_study_snapshot(fresh)
    assert shell.view._state.study is fresh


# ---------------------------------------------------------------------------
# 15. SHUTDOWN / RELAUNCH
# ---------------------------------------------------------------------------


def test_c11c_shutdown_is_clean_and_data_survives(qt_app, isolated_lane):
    """15. Bounded shutdown, one lane, no stray threads, durable relaunch."""

    from PERSISTENCE.storage import EngineStorage, _SharedStorageLane

    before_threads = {t.name for t in threading.enumerate()}

    run_one = Shell(EngineStorage(), plan_id="C11C-SURVIVE-PLAN")
    plan_block(run_one.planner, block_id="SURVIVOR")
    run_one.view.show_notes()
    run_one.view.notes_panel.create_note(title="Survivor Note")
    note_id = run_one.workspace._document.note_id
    assert run_one.session.flush(timeout=3.0)

    assert _SharedStorageLane.owners() == 1, "a second storage owner appeared"
    assert run_one.shutdown() is True
    assert _SharedStorageLane.owners() == 0, "the shell did not release storage"
    assert run_one.session.snapshot().save_state is SaveState.CLOSED

    # No autosave worker left running.
    leaked = {
        t.name
        for t in threading.enumerate()
        if t.is_alive() and "myelin-note-save" in t.name
    } - before_threads
    assert leaked == set(), f"Notes threads survived shutdown: {leaked}"

    # Relaunch: both organs' data returns.
    run_two = Shell(EngineStorage(), plan_id="C11C-SURVIVE-PLAN")
    try:
        assert _SharedStorageLane.owners() == 1
        blocks = run_two.planner.load_persisted()
        assert [b.block_id for b in blocks] == ["SURVIVOR"]
        assert run_two.storage.load_note(note_id).title == "Survivor Note"
    finally:
        run_two.shutdown()


def test_c11c_no_second_sqlite_writer_across_the_family(qt_app, isolated_lane):
    """15. The shell and a Monitor-like owner share ONE lane."""

    from PERSISTENCE.storage import EngineStorage, _SharedStorageLane

    shell_storage = EngineStorage()
    monitor_like = EngineStorage()
    try:
        assert shell_storage._lane is monitor_like._lane
        assert _SharedStorageLane.owners() == 2
        monitor_like.shutdown()
        assert _SharedStorageLane.owners() == 1
        # The shell can still write after the Monitor-like owner ends.
        assert shell_storage.list_planner_blocks(plan_id="ANY") == ()
    finally:
        shell_storage.shutdown()
