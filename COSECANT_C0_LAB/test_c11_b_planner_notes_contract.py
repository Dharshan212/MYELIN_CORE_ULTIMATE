"""C11-B — Planner + Notes + durable outer-shell contract.

LAB TESTING ONLY.  No test file enters MYELIN2.0_ULTIMATE.

The C11-B audit found the internal organs healthy and the CONNECTIVE TISSUE
lesioned.  This file attacks exactly that tissue:

    P-B1  a stale Planner caller can delete/mutate the newest block
    P-B2  a forged occurrence can mint a genuine preparation token
    N-B1  a stale note copy can repaint over the session's newest document
    N-B2  a rejected rename can stay visible as if accepted
    N-B3  a rejected body edit can stay visible as if accepted
    S     two storage facades would open two SQLite write lanes, and no
          Planner / Note repository exists at all

STANDING LAW carried in from C10/C11-A:

    PLAN        != BEHAVIOUR
    NOTE        != EVIDENCE
    BUTTON      != FACT
    PREPARATION != START
    RUNNING     != COMMITTED

VACUITY RULE — every negative assertion is preceded by a positive control
proving the forbidden mechanism was genuinely eligible to fire.
"""

from __future__ import annotations

import os
import threading
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _lab  # noqa: F401  -- installs the production path

from COSECANT_STUDY_MODE.planner import (
    DstStatus,
    PlanBlock,
    PlanOccurrence,
    PlanPriority,
    PlanStatus,
    RecurrenceKind,
    RecurrenceRule,
    StudyPlanner,
)
from COSECANT_STUDY_MODE.notes import (
    BlockKind,
    NoteDocument,
    NoteKind,
    NoteSummary,
    NoteValidationError,
    OpaquePayload,
    create_note,
    document_from_json,
    document_to_json,
    insert_drawing_block,
    insert_formula_block,
    insert_table_block,
    rename_note,
)


ZONE = "Europe/London"

# ---------------------------------------------------------------------------
# ENVIRONMENT REQUIREMENT — GROUP P cannot run without an IANA database.
#
# StudyPlanner requires a real IANA zone: PlanBlock.__post_init__ calls
# planner._zone(), which raises for any name zoneinfo cannot resolve.  Without
# the tzdata package zoneinfo resolves NOTHING -- not even "UTC" -- and not one
# PlanBlock can be constructed.
#
# This is asserted LOUDLY at import rather than skipped.  A silent skip once
# hid this entire group behind an environment gap, and a Planner suite that
# quietly does not run is worse than one that refuses to start.
#
# The fix is the tzdata package, never a looser _zone(): a fixed-offset
# fallback carries no DST transition rules and would destroy exactly the
# civil-time correctness this group exists to protect.
# ---------------------------------------------------------------------------

from COSECANT_STUDY_MODE.planner import timezone_available as _timezone_available

if not _timezone_available(ZONE):
    raise RuntimeError(
        "GROUP P requires an IANA timezone database. Install it with "
        "`py -3 -m pip install tzdata`. Do NOT relax planner._zone() instead."
    )


# ---------------------------------------------------------------------------
# Planner staging
# ---------------------------------------------------------------------------


def add_block(
    planner: StudyPlanner,
    *,
    block_id: str = "BLOCK-1",
    local_date: str = "2026-09-01",
    recurrence: RecurrenceRule | None = None,
) -> PlanBlock:
    """Store one block through the real keyword-only Planner entry point."""

    return planner.add_block(
        subject="Neuroscience",
        task="basal ganglia",
        local_date=local_date,
        local_hour=9,
        local_minute=0,
        timezone_id=ZONE,
        dst_fold=0,
        study_minutes=45,
        break_minutes=10,
        recurrence=recurrence or RecurrenceRule(kind=RecurrenceKind.NONE),
        priority=PlanPriority.NORMAL,
        block_id=block_id,
    )


@pytest.fixture
def planner() -> StudyPlanner:
    return StudyPlanner()


def only_occurrence(planner: StudyPlanner, *, day: str) -> PlanOccurrence:
    projection = planner.project(date_from=day, date_to=day)
    assert projection.occurrences, "the LAB expected one projected occurrence"
    return projection.occurrences[0]


# ---------------------------------------------------------------------------
# GROUP P — Planner authority
# ---------------------------------------------------------------------------


def test_p1_stale_delete_is_rejected(planner):
    """A caller holding version 1 must not delete the version 2 block."""

    stored = add_block(planner)
    stale_version = stored.version

    current = planner.replace_block(replace(stored, task="cerebellar circuits"))
    assert current.version == stale_version + 1

    with pytest.raises(ValueError):
        planner.remove_block(stored.block_id, expected_version=stale_version)

    surviving = planner.block(stored.block_id)
    assert surviving.version == current.version, (
        "a stale caller deleted or replaced the newest planner block"
    )
    assert surviving.task == "cerebellar circuits"


def test_p1_current_delete_is_the_positive_control(planner):
    """POSITIVE CONTROL: a correctly-versioned delete genuinely works."""

    stored = add_block(planner)
    assert planner.remove_block(stored.block_id, expected_version=stored.version)
    assert planner.blocks() == ()


def test_p2_stale_status_mutation_is_rejected(planner):
    """A version 1 caller must not restatus the version 2 block."""

    stored = add_block(planner)
    stale_version = stored.version
    current = planner.replace_block(replace(stored, task="cerebellar circuits"))

    with pytest.raises(ValueError):
        planner.set_status(
            stored.block_id,
            PlanStatus.SKIPPED,
            expected_version=stale_version,
        )

    surviving = planner.block(stored.block_id)
    assert surviving.status is PlanStatus.PLANNED, (
        "a stale caller changed the newest planner block's status"
    )
    assert surviving.version == current.version


def test_p2_current_status_mutation_is_the_positive_control(planner):
    """POSITIVE CONTROL: a correctly-versioned status change genuinely works."""

    stored = add_block(planner)
    updated = planner.set_status(
        stored.block_id,
        PlanStatus.SKIPPED,
        expected_version=stored.version,
    )
    assert updated.status is PlanStatus.SKIPPED
    assert updated.version == stored.version + 1


def test_p3_forged_occurrence_key_is_refused(planner):
    """A genuine block identity must not validate a forged occurrence."""

    stored = add_block(
        planner, recurrence=RecurrenceRule(kind=RecurrenceKind.DAILY)
    )
    genuine = only_occurrence(planner, day="2026-09-02")

    forged = replace(
        genuine,
        occurrence_key=f"{stored.block_id}@2099-01-01",
        local_date="2099-01-01",
        scheduled_start_utc="2099-01-01T00:00:00.000Z",
    )
    result = planner.prepare_cosecant_timer(forged)

    assert result.accepted is False, (
        "a forged occurrence minted a genuine preparation token"
    )
    assert result.preparation is None


def test_p3_forged_scheduled_start_is_refused(planner):
    """Only the schedule Planner itself derives may enter a preparation."""

    add_block(planner)
    genuine = only_occurrence(planner, day="2026-09-01")

    forged = replace(genuine, scheduled_start_utc="2099-01-01T00:00:00.000Z")
    result = planner.prepare_cosecant_timer(forged)

    assert result.accepted is False, (
        "a forged scheduled start was copied into a preparation"
    )


def test_p3_forged_duration_is_refused(planner):
    """Study/break minutes must come from the block, never from the caller."""

    add_block(planner)
    genuine = only_occurrence(planner, day="2026-09-01")

    forged = replace(genuine, study_minutes=999, break_minutes=999)
    result = planner.prepare_cosecant_timer(forged)
    if result.accepted:
        # If a rebuild-from-canonical repair accepts the request, it must at
        # least have discarded the forged figures entirely.
        assert result.preparation.study_seconds == 45 * 60
        assert result.preparation.selected_break_seconds == 10 * 60


def test_p3_occurrence_outside_the_recurrence_is_refused(planner):
    """A date the rule never produces cannot be prepared."""

    stored = add_block(
        planner,
        recurrence=RecurrenceRule(kind=RecurrenceKind.WEEKLY),
        local_date="2026-09-01",       # a Tuesday
    )
    genuine = only_occurrence(planner, day="2026-09-01")

    # 2026-09-02 is a Wednesday: the weekly rule never yields it.
    forged = replace(
        genuine,
        occurrence_key=f"{stored.block_id}@2026-09-02",
        local_date="2026-09-02",
    )
    assert planner.prepare_cosecant_timer(forged).accepted is False


def test_p4_genuine_occurrence_prepares_and_consumes_once(planner):
    """POSITIVE CONTROL: the real preparation concept is not regressed."""

    add_block(planner)
    occurrence = only_occurrence(planner, day="2026-09-01")

    result = planner.prepare_cosecant_timer(occurrence)
    assert result.accepted is True, result.reason
    assert result.reason == "timer_ready_not_started"
    preparation = result.preparation
    assert preparation is not None
    assert preparation.block_id == occurrence.block_id
    assert preparation.occurrence_key == occurrence.occurrence_key
    assert preparation.scheduled_start_utc == occurrence.scheduled_start_utc
    assert preparation.study_seconds == 45 * 60
    assert preparation.selected_break_seconds == 10 * 60

    first = planner.consume_preparation(preparation)
    assert first.accepted is True

    second = planner.consume_preparation(preparation)
    assert second.accepted is False, "a preparation was consumable twice"
    assert second.reason == "preparation_expired"


def test_p4_recurring_occurrence_prepares_with_its_own_date(planner):
    """A recurring occurrence keeps its own projected instant, not the base."""

    add_block(
        planner, recurrence=RecurrenceRule(kind=RecurrenceKind.DAILY)
    )
    second_day = only_occurrence(planner, day="2026-09-03")

    result = planner.prepare_cosecant_timer(second_day)
    assert result.accepted is True, result.reason
    assert result.preparation.occurrence_key.endswith("@2026-09-03")
    assert result.preparation.scheduled_start_utc == second_day.scheduled_start_utc


def _imported_modules(module) -> set[str]:
    """Every module name the file actually imports.

    Scanning the AST rather than raw text: planner.py legitimately NAMES
    ``StudyRuntime`` in prose to record that the user must still press Start,
    and a substring scan would fail on that documentation.
    """

    import ast

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


FORBIDDEN_AUTHORITY_MODULES = (
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
)


def test_p6_planner_never_starts_study_or_cosecant():
    """Planner must import no runtime authority at all."""

    import COSECANT_STUDY_MODE.planner as planner_module

    imported = _imported_modules(planner_module)
    for forbidden in FORBIDDEN_AUTHORITY_MODULES:
        assert forbidden not in imported, (
            f"planner.py imported runtime authority {forbidden}"
        )


# ---------------------------------------------------------------------------
# GROUP N — Notes authority
# ---------------------------------------------------------------------------


class MemoryNoteStore:
    """The narrow NoteStore contract, in memory.

    LAB scaffolding for GROUP N only.  The DURABLE store is what B6 builds and
    what GROUP S tests; these Notes tests are about the UI/authority seam, so
    they must not also depend on SQLite being reachable.
    """

    def __init__(self) -> None:
        self._notes: dict[str, NoteDocument] = {}
        self._lock = threading.RLock()

    def load_note(self, note_id: str) -> NoteDocument:
        with self._lock:
            document = self._notes.get(str(note_id))
        if document is None:
            raise KeyError(f"unknown note {note_id}")
        return document

    def list_notes(self, note_kind=None):
        with self._lock:
            return tuple(
                NoteSummary(
                    note_id=item.note_id,
                    title=item.title,
                    note_kind=item.note_kind,
                    updated_at_utc=item.updated_at_utc,
                    linked_study_block_id=item.linked_study_block_id,
                    linked_plan_id=item.linked_plan_id,
                )
                for item in self._notes.values()
                if note_kind is None or item.note_kind is note_kind
            )

    def save_note(self, document: NoteDocument, *, expected_revision: int):
        with self._lock:
            current = self._notes.get(document.note_id)
            durable = 0 if current is None else current.revision_number
            if int(expected_revision) != durable:
                raise ValueError(
                    f"stale note revision: expected {expected_revision}, "
                    f"durable {durable}"
                )
            committed = replace(document, revision_number=durable + 1)
            self._notes[document.note_id] = committed
            return committed


@pytest.fixture
def workspace(qt_app):
    """One real NotesWorkspace over a real NoteSession.

    ``_show_error`` is replaced with a recorder.  Production raises a MODAL
    ``QMessageBox`` there, which blocks forever when no user is present -- so
    without this substitution the rejected-edit paths could not be exercised
    at all.  The recorder still proves a failure WAS surfaced to the user;
    only the blocking dialog is removed.

    ``_render`` is wrapped with a counter so a test can prove the workspace
    reconciled its widgets from the authoritative document after a rejection,
    without inventing any production API to observe.
    """

    from COSECANT_STUDY_MODE.notes import NotesWorkspace, NoteSession

    session = NoteSession(store=MemoryNoteStore())
    created = NotesWorkspace(session=session)

    created.shown_errors = []
    created._show_error = created.shown_errors.append

    created.render_calls = []
    real_render = created._render

    def counting_render():
        created.render_calls.append(True)
        real_render()

    created._render = counting_render

    yield created
    created.shutdown(timeout=2.0)


@pytest.fixture(scope="session")
def qt_app():
    from PyQt6.QtWidgets import QApplication

    existing = QApplication.instance()
    return existing if existing is not None else QApplication([])


def test_n1_stale_same_note_reopen_shows_the_session_document(workspace):
    """The UI must display the session's document, not the caller's copy."""

    document = workspace.new_note(title="Original Title")
    workspace.link_current_study("STUDYBLOCK1", task="basal ganglia")

    session_document = workspace._session.snapshot().document
    assert session_document is not None
    assert session_document.linked_study_block_id == "STUDYBLOCK1"

    # A stale caller copy of the SAME note, without the accepted link.
    assert workspace.open_document(document) is True

    authoritative = workspace._session.snapshot().document
    assert authoritative.linked_study_block_id == "STUDYBLOCK1", (
        "the session itself lost the accepted edit"
    )
    assert workspace._document is authoritative, (
        "the workspace re-adopted a stale caller copy over the session document"
    )
    assert workspace._document.linked_study_block_id == "STUDYBLOCK1"


def test_n1_new_note_open_is_the_positive_control(workspace):
    """POSITIVE CONTROL: opening a genuinely different note still works."""

    workspace.new_note(title="First Note")
    second = create_note(title="Second Note", note_kind=NoteKind.SESSION)

    assert workspace.open_document(second, requires_save=True) is True
    assert workspace._document.note_id == second.note_id
    assert workspace._document.title == "Second Note"


def test_n2_rejected_rename_restores_the_authoritative_title(workspace):
    """An invalid title must not remain visible as if it were accepted."""

    workspace.new_note(title="Valid Title")
    assert workspace._document.title == "Valid Title"

    workspace.title.setText("   ")            # empty after normalisation
    workspace._rename()

    assert workspace._document.title == "Valid Title", (
        "an invalid title reached the authoritative document"
    )
    assert workspace.title.text() == "Valid Title", (
        "the rejected title is still visible in the editor"
    )


def test_n2_accepted_rename_is_the_positive_control(workspace):
    """POSITIVE CONTROL: a valid rename genuinely reaches the document."""

    workspace.new_note(title="Valid Title")
    workspace.title.setText("Renamed Title")
    workspace._rename()
    assert workspace._document.title == "Renamed Title"


def test_n3_accepted_text_edit_does_not_force_a_rerender(workspace):
    """POSITIVE CONTROL: an accepted keystroke must not repaint the editor.

    Without this, the rejection test below could be satisfied by a workspace
    that simply re-renders after every edit -- which would destroy the caret
    on every keystroke and prove nothing about reconciliation.
    """

    from COSECANT_STUDY_MODE.notes import TextSpan

    workspace.new_note(title="Body Note")
    block = workspace._document.blocks[0]

    workspace.render_calls.clear()
    workspace._text_changed(block.block_id, (TextSpan(text="basal ganglia"),))

    assert workspace.shown_errors == []
    assert workspace._document.blocks[0].content[0].text == "basal ganglia"
    assert workspace.render_calls == [], (
        "an accepted keystroke forced a full re-render"
    )


def test_n3_rejected_text_edit_restores_authority(workspace):
    """A rejected body edit must not stay visible as accepted."""

    from COSECANT_STUDY_MODE.notes import TextSpan

    workspace.new_note(title="Body Note")
    block = workspace._document.blocks[0]
    workspace._text_changed(block.block_id, (TextSpan(text="basal ganglia"),))
    before = workspace._document

    workspace.render_calls.clear()
    workspace.shown_errors.clear()
    workspace._text_changed(block.block_id, (TextSpan(text="x" * 400_000),))

    assert workspace._document is before, (
        "a rejected oversized edit reached the authoritative document"
    )
    assert workspace.shown_errors, "the user was never told the edit failed"
    assert workspace.render_calls, (
        "a rejected body edit left the visible editor unreconciled"
    )


def test_n4_opaque_table_round_trip_is_exact():
    document = insert_table_block(create_note(title="T", note_kind=NoteKind.SESSION))
    block = document.blocks[-1]
    assert block.kind is BlockKind.TABLE
    assert isinstance(block.content, OpaquePayload)

    restored = document_from_json(document_to_json(document))
    restored_block = restored.blocks[-1]
    assert restored_block.content.sha256 == block.content.sha256
    assert restored_block.content.data() == block.content.data()


def test_n5_opaque_formula_round_trip_is_exact():
    document = insert_formula_block(
        create_note(title="F", note_kind=NoteKind.SESSION), "E = mc^2"
    )
    block = document.blocks[-1]
    restored = document_from_json(document_to_json(document))
    assert restored.blocks[-1].content.sha256 == block.content.sha256
    assert restored.blocks[-1].content.data() == block.content.data()


def test_n6_opaque_drawing_round_trip_is_exact():
    document = insert_drawing_block(create_note(title="D", note_kind=NoteKind.SESSION))
    block = document.blocks[-1]
    restored = document_from_json(document_to_json(document))
    assert restored.blocks[-1].content.sha256 == block.content.sha256
    assert restored.blocks[-1].content.data() == block.content.data()


def test_n9_note_content_never_reaches_behavioural_organs():
    """Notes must not import any sensing or behavioural authority."""

    import COSECANT_STUDY_MODE.notes as notes_module

    imported = _imported_modules(notes_module)
    for forbidden in FORBIDDEN_AUTHORITY_MODULES:
        assert forbidden not in imported, (
            f"notes.py imported behavioural authority {forbidden}"
        )


# ---------------------------------------------------------------------------
# GROUP S — shared persistence foundation
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_lane():
    """Give one test a pristine shared-lane singleton, then restore the suite's.

    ``_SharedStorageLane`` is process-wide BY DESIGN -- that is the contract
    under test.  But other LAB modules build ``EngineStorage`` facades (every
    ``Journey`` does) and never release them, so the live owner count is rarely
    zero.  Ownership arithmetic asserted against that shared count would be
    measuring the rest of the suite rather than this repair.

    The singleton is therefore swapped for an empty one for the duration of the
    test and restored afterwards, so "last owner" genuinely means last.
    Anything the test leaves open is shut down rather than leaked.
    """

    from PERSISTENCE.storage import _SharedStorageLane

    with _SharedStorageLane._lock:
        saved_lane = _SharedStorageLane._lane
        saved_owners = set(_SharedStorageLane._owners)
        saved_state = _SharedStorageLane._state
        _SharedStorageLane._lane = None
        _SharedStorageLane._owners = set()
        _SharedStorageLane._state = _SharedStorageLane.IDLE

    yield _SharedStorageLane

    with _SharedStorageLane._lock:
        leftover = _SharedStorageLane._lane
        _SharedStorageLane._lane = saved_lane
        _SharedStorageLane._owners = saved_owners
        _SharedStorageLane._state = saved_state
    if leftover is not None:
        try:
            leftover.shutdown(timeout_seconds=2.0)
        except Exception:               # noqa: BLE001 - teardown must not mask
            pass


def lane_accepts_writes(lane) -> bool:
    """Prove the lane is alive by USING it, not by reading a private flag.

    ``SQLiteTransactionLane`` exposes no public running flag and database.py is
    frozen, so liveness is established functionally: a closed lane raises from
    ``submit``.  The submitted operation touches nothing.
    """

    try:
        lane.submit("c11b lane liveness probe", lambda connection: None)
    except RuntimeError:
        return False
    return True


def test_s1_two_storage_facades_share_one_sqlite_lane(isolated_lane):
    """Two facades in one process must serialise through ONE write lane."""

    from PERSISTENCE.storage import EngineStorage

    first = EngineStorage()
    second = EngineStorage()
    try:
        assert first._lane is second._lane, (
            "two EngineStorage facades opened two independent SQLite lanes"
        )
    finally:
        second.shutdown()
        first.shutdown()


def test_s2_releasing_one_owner_keeps_the_lane_alive(isolated_lane):
    """A Monitor session ending must not kill Control Station persistence."""

    from PERSISTENCE.storage import EngineStorage

    control_station = EngineStorage()
    monitor_like = EngineStorage()
    try:
        lane = control_station._lane
        monitor_like.shutdown()

        assert control_station._lane is lane
        assert lane_accepts_writes(lane) is True, (
            "the shared lane shut down while another owner still held it"
        )
    finally:
        control_station.shutdown()


def test_s3_last_owner_release_shuts_the_lane(isolated_lane):
    """POSITIVE CONTROL: the lane really does close once nobody holds it."""

    from PERSISTENCE.storage import EngineStorage

    first = EngineStorage()
    second = EngineStorage()
    lane = first._lane

    second.shutdown()
    assert lane_accepts_writes(lane) is True

    first.shutdown()
    assert lane_accepts_writes(lane) is False, (
        "the last owner release did not shut the lane"
    )


def test_s4_double_release_cannot_corrupt_the_owner_count(isolated_lane):
    """An idempotent shutdown must not steal another owner's lane."""

    from PERSISTENCE.storage import EngineStorage
    _SharedStorageLane = isolated_lane

    first = EngineStorage()
    second = EngineStorage()
    try:
        assert _SharedStorageLane.owners() == 2
        second.shutdown()
        second.shutdown()
        second.shutdown()
        assert _SharedStorageLane.owners() == 1, (
            "repeated shutdown decremented the shared owner count more than once"
        )
        assert lane_accepts_writes(first._lane) is True, (
            "a double release closed a lane another owner still held"
        )
    finally:
        first.shutdown()


def test_s5_a_new_facade_rebuilds_a_healthy_lane_after_full_release(isolated_lane):
    """After the last owner releases, persistence must be recoverable."""

    from PERSISTENCE.storage import EngineStorage
    _SharedStorageLane = isolated_lane

    first = EngineStorage()
    old_lane = first._lane
    first.shutdown()
    assert _SharedStorageLane.owners() == 0
    assert lane_accepts_writes(old_lane) is False

    revived = EngineStorage()
    try:
        assert revived._lane is not old_lane, "a closed lane was handed out again"
        assert lane_accepts_writes(revived._lane) is True
    finally:
        revived.shutdown()


def test_s6_concurrent_acquisition_is_thread_safe(isolated_lane):
    """Many threads acquiring at once must still produce exactly one lane."""

    from PERSISTENCE.storage import EngineStorage
    _SharedStorageLane = isolated_lane

    facades: list = []
    errors: list = []
    barrier = threading.Barrier(8)

    def acquire() -> None:
        try:
            barrier.wait(timeout=10)
            facades.append(EngineStorage())
        except Exception as exc:            # noqa: BLE001 - reported, not hidden
            errors.append(exc)

    threads = [threading.Thread(target=acquire) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    try:
        assert errors == [], f"concurrent acquisition raised: {errors}"
        assert len(facades) == 8
        lanes = {id(facade._lane) for facade in facades}
        assert len(lanes) == 1, (
            f"concurrent acquisition produced {len(lanes)} lanes, expected 1"
        )
        assert _SharedStorageLane.owners() == 8
        assert lane_accepts_writes(facades[0]._lane) is True
    finally:
        for facade in facades:
            facade.shutdown()


def test_n7_note_stale_revision_save_is_rejected():
    """Optimistic revision: no last-write-wins overwrite."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        document = create_note(title="Durable Note", note_kind=NoteKind.SESSION)

        first = storage.save_note(document, expected_revision=0)
        assert first.revision_number == 1

        second = storage.save_note(first, expected_revision=1)
        assert second.revision_number == 2

        with pytest.raises(Exception):
            storage.save_note(first, expected_revision=1)

        loaded = storage.load_note(document.note_id)
        assert loaded.revision_number == 2, (
            "a stale writer overwrote a newer durable note revision"
        )
    finally:
        storage.shutdown()


def test_p8_planner_durable_stale_write_is_rejected():
    """A failed persistence write must not advance Planner truth."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        block = add_block(StudyPlanner())
        saved = storage.save_planner_block(
            plan_id="PLAN-1", block=block, expected_version=0
        )
        assert saved.version == block.version

        restored = storage.list_planner_blocks(plan_id="PLAN-1")
        assert len(restored) == 1
        assert restored[0].block_id == block.block_id
        assert restored[0].recurrence == block.recurrence

        with pytest.raises(Exception):
            storage.save_planner_block(
                plan_id="PLAN-1", block=block, expected_version=99
            )

        still = storage.list_planner_blocks(plan_id="PLAN-1")
        assert len(still) == 1
        assert still[0].version == block.version, (
            "a stale durable planner write advanced the stored version"
        )
    finally:
        storage.shutdown()


def test_s7_running_is_never_treated_as_committed():
    """RUNNING != COMMITTED must survive the shared-lane refactor."""

    from PERSISTENCE.database import ReceiptState

    assert ReceiptState.COMMITTED.value == "COMMITTED"
    assert ReceiptState.RUNNING.value == "RUNNING"


def test_p9_plan_id_and_block_id_round_trip_durably(isolated_lane):
    """(plan_id, block_id) is the durable identity, and it survives storage."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner_a = StudyPlanner(plan_id="PLAN-A")
        planner_b = StudyPlanner(plan_id="PLAN-B")
        shared_block_id = "SHARED-BLOCK"

        block_a = add_block(planner_a, block_id=shared_block_id)
        block_b = add_block(
            planner_b, block_id=shared_block_id, local_date="2026-09-04"
        )

        storage.save_planner_block(
            plan_id=planner_a.plan_id, block=block_a, expected_version=0
        )
        storage.save_planner_block(
            plan_id=planner_b.plan_id, block=block_b, expected_version=0
        )

        stored_a = storage.list_planner_blocks(plan_id=planner_a.plan_id)
        stored_b = storage.list_planner_blocks(plan_id=planner_b.plan_id)

        assert len(stored_a) == 1 and len(stored_b) == 1
        assert stored_a[0].local_date == "2026-09-01"
        assert stored_b[0].local_date == "2026-09-04", (
            "the same block_id in a different plan overwrote the first"
        )
    finally:
        storage.shutdown()


def test_p10_recurring_identity_survives_persistence(isolated_lane):
    """Recurrence, DST fold and timezone must round-trip exactly."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-RECUR")
        rule = RecurrenceRule(
            kind=RecurrenceKind.CUSTOM_WEEKDAYS,
            weekdays=(0, 2, 4),
            end_date="2026-12-31",
            exception_dates=("2026-09-09",),
        )
        block = add_block(planner, recurrence=rule)
        storage.save_planner_block(
            plan_id=planner.plan_id, block=block, expected_version=0
        )

        restored = storage.list_planner_blocks(plan_id=planner.plan_id)[0]
        assert restored == block, "a planner block did not round-trip exactly"
        assert restored.recurrence.weekdays == (0, 2, 4)
        assert restored.recurrence.exception_dates == ("2026-09-09",)
        assert restored.timezone_id == ZONE

        # And the restored block must still project the same occurrences.
        revived = StudyPlanner(plan_id=planner.plan_id)
        revived.add_block(
            subject=restored.subject,
            task=restored.task,
            local_date=restored.local_date,
            local_hour=restored.local_hour,
            local_minute=restored.local_minute,
            timezone_id=restored.timezone_id,
            dst_fold=restored.dst_fold,
            study_minutes=restored.study_minutes,
            break_minutes=restored.break_minutes,
            recurrence=restored.recurrence,
            priority=restored.priority,
            block_id=restored.block_id,
        )
        original = planner.project(date_from="2026-09-01", date_to="2026-09-30")
        reloaded = revived.project(date_from="2026-09-01", date_to="2026-09-30")
        assert [item.occurrence_key for item in reloaded.occurrences] == [
            item.occurrence_key for item in original.occurrences
        ]
    finally:
        storage.shutdown()


def test_n8_durable_note_round_trip_preserves_opaque_blocks(isolated_lane):
    """Structured blocks must survive the real durable path byte-for-byte."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        document = insert_drawing_block(
            insert_formula_block(
                insert_table_block(
                    create_note(title="Structured", note_kind=NoteKind.SESSION)
                ),
                "E = mc^2",
            )
        )
        committed = storage.save_note(document, expected_revision=0)
        loaded = storage.load_note(document.note_id)

        assert loaded.revision_number == committed.revision_number == 1
        for original, restored in zip(document.blocks, loaded.blocks):
            if isinstance(original.content, OpaquePayload):
                assert restored.content.sha256 == original.content.sha256
                assert restored.content.data() == original.content.data()

        summaries = storage.list_notes(NoteKind.SESSION)
        assert any(item.note_id == document.note_id for item in summaries)
    finally:
        storage.shutdown()


# ---------------------------------------------------------------------------
# GROUP S (R4) — shared-lane lifecycle under concurrency and failure
#
# The refcount repair closed the "two lanes at once" hole for the STEADY
# state.  These attack the SHUTDOWN WINDOW, where the old writer is still
# draining: publishing the slot before that drain finishes lets a second
# writer exist against one database, which is exactly what one ordered lane
# exists to prevent.
# ---------------------------------------------------------------------------


class BlockingLane:
    """A lane whose shutdown blocks until the test releases it."""

    def __init__(self) -> None:
        self.released = threading.Event()
        self.shutdown_started = threading.Event()
        self.shutdown_calls = 0
        self.raise_on_shutdown = False

    def shutdown(self, timeout_seconds: float = 0.0) -> None:
        self.shutdown_calls += 1
        self.shutdown_started.set()
        self.released.wait(timeout=10)
        if self.raise_on_shutdown:
            raise RuntimeError("SQLite lane failed to drain")

    def submit(self, operation, callback):
        return None


def test_s8_no_second_lane_while_the_old_one_is_still_closing(
    isolated_lane, monkeypatch
):
    """A new lane must not be built while the previous writer is draining."""

    import PERSISTENCE.storage as storage_module

    built: list = []

    def fake_lane():
        lane = BlockingLane()
        built.append(lane)
        return lane

    monkeypatch.setattr(storage_module, "SQLiteTransactionLane", fake_lane)

    first = storage_module.EngineStorage()
    old_lane = first._lane
    assert len(built) == 1

    closer = threading.Thread(target=first.shutdown)
    closer.start()
    assert old_lane.shutdown_started.wait(timeout=5), "shutdown never began"

    # The old writer is mid-drain RIGHT NOW.
    second_holder: list = []
    errors: list = []

    def try_acquire() -> None:
        try:
            second_holder.append(storage_module.EngineStorage())
        except Exception as exc:            # noqa: BLE001 - fail-closed is legal
            errors.append(exc)

    racer = threading.Thread(target=try_acquire)
    racer.start()
    racer.join(timeout=3)
    still_closing = racer.is_alive()

    try:
        assert len(built) == 1, (
            "a SECOND SQLite lane was created while the first was still closing"
        )
    finally:
        old_lane.released.set()
        closer.join(timeout=10)
        racer.join(timeout=10)
        for facade in second_holder:
            facade.shutdown()

    # Either it waited for the drain or it failed closed.  Both are legal;
    # silently building a second writer is not.
    assert still_closing or errors or second_holder, (
        "the racing acquisition neither waited, failed closed, nor succeeded"
    )


def test_s9_failed_shutdown_fails_closed_and_builds_no_second_lane(
    isolated_lane, monkeypatch
):
    """A lane that cannot drain must poison persistence, not be replaced."""

    import PERSISTENCE.storage as storage_module

    built: list = []

    def fake_lane():
        lane = BlockingLane()
        lane.raise_on_shutdown = True
        built.append(lane)
        return lane

    monkeypatch.setattr(storage_module, "SQLiteTransactionLane", fake_lane)

    first = storage_module.EngineStorage()
    built[0].released.set()

    with pytest.raises(RuntimeError):
        first.shutdown()

    with pytest.raises(RuntimeError):
        storage_module.EngineStorage()

    assert len(built) == 1, (
        "a second SQLite lane was created after the first failed to drain"
    )


def test_s10_concurrent_shutdown_of_one_facade_cannot_evict_another(isolated_lane):
    """Two threads shutting the SAME facade must not release another owner."""

    from PERSISTENCE.storage import EngineStorage

    first = EngineStorage()
    second = EngineStorage()
    try:
        barrier = threading.Barrier(4)

        def close_second() -> None:
            barrier.wait(timeout=10)
            second.shutdown()

        threads = [threading.Thread(target=close_second) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        assert isolated_lane.owners() == 1, (
            "concurrent shutdown of one facade removed more than one owner"
        )
        assert lane_accepts_writes(first._lane) is True, (
            "a concurrent double release closed a lane another owner still held"
        )
    finally:
        first.shutdown()


def test_s11_same_owner_release_is_idempotent_under_concurrency(isolated_lane):
    """Releasing one owner token repeatedly must decrement exactly once."""

    from PERSISTENCE.storage import EngineStorage

    holder = EngineStorage()
    victim = EngineStorage()
    try:
        for _ in range(5):
            victim.shutdown()
        assert isolated_lane.owners() == 1
        assert lane_accepts_writes(holder._lane) is True
    finally:
        holder.shutdown()


def test_s12_one_fresh_lane_after_a_complete_successful_shutdown(isolated_lane):
    """POSITIVE CONTROL: a clean full release still allows recovery."""

    from PERSISTENCE.storage import EngineStorage

    first = EngineStorage()
    old_lane = first._lane
    first.shutdown()
    assert isolated_lane.owners() == 0
    assert lane_accepts_writes(old_lane) is False

    revived = EngineStorage()
    try:
        assert revived._lane is not old_lane
        assert lane_accepts_writes(revived._lane) is True
    finally:
        revived.shutdown()


def test_s13_simultaneous_acquisitions_still_converge_on_one_lane(isolated_lane):
    """POSITIVE CONTROL: the normal concurrent path is not broken by R1."""

    from PERSISTENCE.storage import EngineStorage

    facades: list = []
    errors: list = []
    barrier = threading.Barrier(6)

    def acquire() -> None:
        try:
            barrier.wait(timeout=10)
            facades.append(EngineStorage())
        except Exception as exc:            # noqa: BLE001 - reported, not hidden
            errors.append(exc)

    threads = [threading.Thread(target=acquire) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    try:
        assert errors == [], f"concurrent acquisition raised: {errors}"
        assert len({id(facade._lane) for facade in facades}) == 1
        assert isolated_lane.owners() == 6
    finally:
        for facade in facades:
            facade.shutdown()


def test_s14_the_mutable_lane_is_not_public(isolated_lane):
    """Production must not be handed a shutdown handle to shared persistence."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        assert not hasattr(storage, "lane"), (
            "EngineStorage publishes a mutable shared lane; any consumer could "
            "call storage.lane.shutdown() and bypass the owner protocol"
        )
    finally:
        storage.shutdown()


# ---------------------------------------------------------------------------
# GROUP P (R5) — Planner durable lineage
# ---------------------------------------------------------------------------


def durable_planner_block(storage, planner, block):
    storage.save_planner_block(
        plan_id=planner.plan_id, block=block, expected_version=0
    )
    return storage.list_planner_blocks(plan_id=planner.plan_id)[0]


def test_p11_same_version_content_overwrite_is_rejected(isolated_lane):
    """A candidate that does not advance the version is a stale rewrite."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-LINEAGE-1")
        block = add_block(planner)
        durable_planner_block(storage, planner, block)

        # Same version, different content: durable truth would silently change
        # while its version stayed put, so nothing downstream could detect it.
        forged = replace(block, task="rewritten without advancing")
        with pytest.raises(Exception):
            storage.save_planner_block(
                plan_id=planner.plan_id, block=forged, expected_version=1
            )

        still = storage.list_planner_blocks(plan_id=planner.plan_id)[0]
        assert still.task == "basal ganglia", (
            "a same-version candidate overwrote durable planner content"
        )
    finally:
        storage.shutdown()


def test_p12_version_jump_is_rejected(isolated_lane):
    """Lineage must advance by exactly one."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-LINEAGE-2")
        block = add_block(planner)
        durable_planner_block(storage, planner, block)

        jumped = replace(block, version=99)
        with pytest.raises(Exception):
            storage.save_planner_block(
                plan_id=planner.plan_id, block=jumped, expected_version=1
            )

        still = storage.list_planner_blocks(plan_id=planner.plan_id)[0]
        assert still.version == 1, "a version jump reached durable storage"
    finally:
        storage.shutdown()


def test_p13_valid_plus_one_update_is_accepted(isolated_lane):
    """POSITIVE CONTROL: a genuine update genuinely commits."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-LINEAGE-3")
        block = add_block(planner)
        durable_planner_block(storage, planner, block)

        updated = planner.replace_block(replace(block, task="cerebellar circuits"))
        assert updated.version == 2
        storage.save_planner_block(
            plan_id=planner.plan_id, block=updated, expected_version=1
        )

        stored = storage.list_planner_blocks(plan_id=planner.plan_id)[0]
        assert stored.version == 2
        assert stored.task == "cerebellar circuits"
    finally:
        storage.shutdown()


def test_p14_new_block_requires_expected_zero_and_version_one(isolated_lane):
    """A first durable write is expected 0 -> candidate version 1."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-LINEAGE-4")
        block = add_block(planner)
        assert block.version == 1

        storage.save_planner_block(
            plan_id=planner.plan_id, block=block, expected_version=0
        )
        assert storage.list_planner_blocks(plan_id=planner.plan_id)[0].version == 1

        # A bool is not an int; pseudo-versions must be refused outright.
        with pytest.raises(Exception):
            storage.save_planner_block(
                plan_id=planner.plan_id, block=block, expected_version=True
            )
        with pytest.raises(Exception):
            storage.save_planner_block(
                plan_id=planner.plan_id, block=block, expected_version="1"
            )
    finally:
        storage.shutdown()


# ---------------------------------------------------------------------------
# GROUP N (R6) — Note durable identity
# ---------------------------------------------------------------------------


def test_n11_document_revision_must_match_expected_revision(isolated_lane):
    """Persistence must not trust a caller to keep the two consistent."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        document = create_note(title="Authoritative", note_kind=NoteKind.SESSION)
        committed = storage.save_note(document, expected_revision=0)
        assert committed.revision_number == 1

        # A stale document body carrying revision 0, submitted as if the caller
        # knew durable was 1.  Manufacturing revision 2 from that would publish
        # stale content under a newer revision number.
        stale = replace(committed, revision_number=0, title="STALE")
        with pytest.raises(Exception):
            storage.save_note(stale, expected_revision=1)

        loaded = storage.load_note(document.note_id)
        assert loaded.title == "Authoritative", (
            "a stale document overwrote durable note content"
        )
        assert loaded.revision_number == 1
    finally:
        storage.shutdown()


def test_n12_valid_revision_progression_is_accepted(isolated_lane):
    """POSITIVE CONTROL: the normal NoteSession progression still commits."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        document = create_note(title="Progression", note_kind=NoteKind.SESSION)
        first = storage.save_note(document, expected_revision=0)
        assert first.revision_number == 1

        second = storage.save_note(first, expected_revision=1)
        assert second.revision_number == 2

        assert storage.load_note(document.note_id).revision_number == 2
    finally:
        storage.shutdown()


def test_n13_pseudo_revisions_are_rejected(isolated_lane):
    """bool and str are not revision numbers."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        document = create_note(title="Typed", note_kind=NoteKind.SESSION)
        with pytest.raises(Exception):
            storage.save_note(document, expected_revision=True)
        with pytest.raises(Exception):
            storage.save_note(document, expected_revision="0")
        with pytest.raises(Exception):
            storage.save_note(document, expected_revision=-1)
    finally:
        storage.shutdown()


# ---------------------------------------------------------------------------
# GROUP B7.2 — stable Planner collection identity
#
# Durable rows are keyed (plan_id, block_id).  A plan_id minted freshly on
# every launch keys yesterday's rows under a name no later run can produce,
# so plans would persist and never reopen.  These pin the restart contract.
# ---------------------------------------------------------------------------


def test_b72_default_planners_share_one_stable_plan_id():
    """Two default planners must name the SAME collection."""

    from COSECANT_STUDY_MODE.planner import DEFAULT_PLAN_ID

    first = StudyPlanner()
    second = StudyPlanner()

    assert first.plan_id == DEFAULT_PLAN_ID
    assert second.plan_id == first.plan_id, (
        "a rebuilt planner minted a different collection identity; durable "
        "rows from the previous run would be unreachable"
    )
    # And it is a fixed name, not a per-launch token.
    assert DEFAULT_PLAN_ID == "MYELIN-STUDY-PLANNER-V1"


def test_b72_persisted_block_reloads_through_a_reconstructed_planner(isolated_lane):
    """THE RESTART PROOF: instance A stores, a fresh instance B reopens."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        # "Run 1" — the user plans a block and it is stored durably.
        first_run = StudyPlanner()
        block = add_block(first_run, block_id="RESTART-BLOCK")
        storage.save_planner_block(
            plan_id=first_run.plan_id, block=block, expected_version=0
        )

        # "Run 2" — a brand-new planner object, exactly as a relaunch builds.
        second_run = StudyPlanner()
        assert second_run is not first_run

        restored = storage.list_planner_blocks(plan_id=second_run.plan_id)
        assert len(restored) == 1, (
            "the reconstructed planner could not find its own persisted rows"
        )
        assert restored[0].block_id == "RESTART-BLOCK"
        assert restored[0] == block, "the reloaded block was not identical"
    finally:
        storage.shutdown()


def test_b72_explicit_plan_id_still_overrides_the_default(isolated_lane):
    """A named collection stays separable from the default one."""

    from PERSISTENCE.storage import EngineStorage
    from COSECANT_STUDY_MODE.planner import DEFAULT_PLAN_ID

    storage = EngineStorage()
    try:
        named = StudyPlanner(plan_id="PLAN-EXPLICIT")
        assert named.plan_id == "PLAN-EXPLICIT"
        assert named.plan_id != DEFAULT_PLAN_ID

        default = StudyPlanner()
        storage.save_planner_block(
            plan_id=named.plan_id,
            block=add_block(named, block_id="IN-NAMED"),
            expected_version=0,
        )
        storage.save_planner_block(
            plan_id=default.plan_id,
            block=add_block(default, block_id="IN-DEFAULT"),
            expected_version=0,
        )

        named_ids = {row.block_id for row in storage.list_planner_blocks(
            plan_id=named.plan_id
        )}
        default_ids = {row.block_id for row in storage.list_planner_blocks(
            plan_id=default.plan_id
        )}
        # Membership, not exact equality: the default collection is shared with
        # every other test in this process, so it legitimately holds their rows
        # too.  What must hold is that neither block crossed into the other.
        assert "IN-NAMED" in named_ids and "IN-NAMED" not in default_ids, (
            "a block stored in the named collection leaked into the default one"
        )
        assert "IN-DEFAULT" in default_ids and "IN-DEFAULT" not in named_ids, (
            "a block stored in the default collection leaked into the named one"
        )
    finally:
        storage.shutdown()


# ---------------------------------------------------------------------------
# GROUP B7.3 — durability before publication
#
#     validate -> expected-version check -> DURABLE COMMIT -> recheck -> publish
#
# The failure this forbids is publishing first and persisting afterwards: the
# visible plan would then claim something the database never accepted.
# ---------------------------------------------------------------------------


class RefusingRepository:
    """A repository that commits nothing and refuses every write."""

    def __init__(self) -> None:
        self.save_calls = 0
        self.archive_calls = 0

    def list_planner_blocks(self, *, plan_id):
        return ()

    def save_planner_block(self, *, plan_id, block, expected_version):
        self.save_calls += 1
        raise RuntimeError("durable planner write refused")

    def archive_planner_block(self, *, plan_id, block_id, expected_version):
        self.archive_calls += 1
        raise RuntimeError("durable planner archive refused")


def test_b73_failed_commit_does_not_advance_planner_truth():
    """A refused durable write must leave the planner exactly as it was."""

    repository = RefusingRepository()
    planner = StudyPlanner(plan_id="PLAN-DURABILITY", repository=repository)

    with pytest.raises(RuntimeError):
        add_block(planner)

    assert repository.save_calls == 1, "the commit was never even attempted"
    assert planner.blocks() == (), (
        "planner truth advanced past a durable write that was refused"
    )


def test_b73_failed_update_leaves_the_previous_version_current(isolated_lane):
    """An update refused by persistence must not become planner truth."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-DURABILITY-2", repository=storage)
        block = add_block(planner)
        assert planner.block(block.block_id).version == 1

        # Swap in a repository that refuses, then attempt a real edit.
        planner._repository = RefusingRepository()
        with pytest.raises(RuntimeError):
            planner.replace_block(replace(block, task="never committed"))

        surviving = planner.block(block.block_id)
        assert surviving.version == 1, "a refused update advanced the version"
        assert surviving.task == "basal ganglia", (
            "a refused update changed visible planner content"
        )
    finally:
        storage.shutdown()


def test_b73_failed_removal_keeps_the_block_visible():
    """A refused archive must not delete the block from planner truth."""

    repository = RefusingRepository()
    planner = StudyPlanner(plan_id="PLAN-DURABILITY-3")
    block = add_block(planner)                 # no repository yet: memory only
    planner._repository = repository

    with pytest.raises(RuntimeError):
        planner.remove_block(block.block_id, expected_version=block.version)

    assert repository.archive_calls == 1
    assert planner.block(block.block_id) == block, (
        "a refused archive removed the block from planner truth"
    )


def test_b73_successful_commit_publishes_and_persists(isolated_lane):
    """POSITIVE CONTROL: the happy path genuinely does both."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-DURABILITY-4", repository=storage)
        block = add_block(planner)

        assert planner.block(block.block_id) == block
        stored = storage.list_planner_blocks(plan_id=planner.plan_id)
        assert [row.block_id for row in stored] == [block.block_id]

        updated = planner.replace_block(replace(block, task="cerebellar circuits"))
        assert updated.version == 2
        assert planner.block(block.block_id).task == "cerebellar circuits"
        stored = storage.list_planner_blocks(plan_id=planner.plan_id)
        assert stored[0].version == 2
        assert stored[0].task == "cerebellar circuits"

        assert planner.remove_block(block.block_id, expected_version=2)
        assert planner.blocks() == ()
        assert storage.list_planner_blocks(plan_id=planner.plan_id) == ()
    finally:
        storage.shutdown()


def test_b73_load_persisted_rehydrates_a_reconstructed_planner(isolated_lane):
    """The restart path: durable truth repopulates a fresh planner object."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        first_run = StudyPlanner(plan_id="PLAN-REHYDRATE", repository=storage)
        block = add_block(first_run, block_id="REHYDRATE-BLOCK")

        second_run = StudyPlanner(plan_id="PLAN-REHYDRATE", repository=storage)
        assert second_run.blocks() == (), "a fresh planner started non-empty"

        loaded = second_run.load_persisted()
        assert [item.block_id for item in loaded] == ["REHYDRATE-BLOCK"]
        assert second_run.block("REHYDRATE-BLOCK") == block

        # And the rehydrated planner can still project the occurrence.
        occurrence = only_occurrence(second_run, day="2026-09-01")
        assert occurrence.block_id == "REHYDRATE-BLOCK"
    finally:
        storage.shutdown()


def test_b73_in_memory_planner_is_unchanged_without_a_repository():
    """POSITIVE CONTROL: the pure in-memory authority still behaves as before."""

    planner = StudyPlanner(plan_id="PLAN-NO-REPO")
    block = add_block(planner)
    assert planner.block(block.block_id) == block
    assert planner.load_persisted() == ()

    updated = planner.replace_block(replace(block, task="cerebellar circuits"))
    assert updated.version == 2
    assert planner.remove_block(block.block_id, expected_version=2) is True

# ---------------------------------------------------------------------------
# GROUP B7.4 — Planner -> Study READY handoff
#
#     canonical persisted occurrence -> one-use preparation
#     -> explicit SET STUDY TIMER -> stale identity/version recheck
#     -> Protected Red recheck -> Controller.prepare_study -> Study READY -> STOP
#
# PREPARATION != START.  Nothing here may begin Study or COSECANT.
# ---------------------------------------------------------------------------

from PyQt6.QtCore import QObject as _QtObject


class FakeEngine(_QtObject):
    """The exact engine surface confirm_planner_timer consumes."""

    def __init__(self, *, red: bool = False) -> None:
        super().__init__()
        self.red = red
        self.restore_calls = 0

    def is_protected_red_active(self) -> bool:
        return self.red

    def request_protected_red_restore(self) -> bool:
        self.restore_calls += 1
        return True


_B74_KEEPALIVE: list = []


def planner_study_view(engine):
    from PyQt6.QtCore import QObject
    from COSECANT_STUDY_MODE.view import StudyView

    view = StudyView(engine=engine, lifecycle=QObject(), settings=QObject())
    _B74_KEEPALIVE.append(view)
    return view


def prepared(planner, *, day: str = "2026-09-01"):
    occurrence = only_occurrence(planner, day=day)
    result = planner.prepare_cosecant_timer(occurrence)
    assert result.accepted, result.reason
    return result.preparation


def test_b74_set_study_timer_dispatches_one_prepare(qt_app):
    """POSITIVE CONTROL: the happy path genuinely reaches prepare_study."""

    engine = FakeEngine()
    view = planner_study_view(engine)
    try:
        emitted: list = []
        view.prepare_requested.connect(lambda *args: emitted.append(args))

        planner = StudyPlanner(plan_id="PLAN-HANDOFF-1")
        add_block(planner)
        reason = view.confirm_planner_timer(planner, prepared(planner))

        assert reason == "", f"handoff refused: {reason}"
        assert len(emitted) == 1
        subject, task, study_seconds, break_seconds, block_id, generation, kw, imp = emitted[0]
        assert subject == "Neuroscience"
        assert task == "basal ganglia"
        assert study_seconds == 45 * 60
        assert break_seconds == 10 * 60
        # No Study snapshot published yet -> the empty identity, not a guess.
        assert block_id == "" and generation == 0
        # Planner declares no keywords and must not invent any.
        assert kw == () and imp == ()
    finally:
        view.close()


def test_b74_protected_red_refuses_the_handoff(qt_app):
    """Red blocks preparation at COMMAND TIME, not just in the paint."""

    engine = FakeEngine(red=True)
    view = planner_study_view(engine)
    try:
        emitted: list = []
        view.prepare_requested.connect(lambda *args: emitted.append(args))

        planner = StudyPlanner(plan_id="PLAN-HANDOFF-2")
        add_block(planner)
        preparation = prepared(planner)

        reason = view.confirm_planner_timer(planner, preparation)

        assert reason == "protected_red"
        assert emitted == [], "a Study PREPARE escaped during Protected Red"
        assert engine.restore_calls == 1, (
            "the authoritative Red surface was not restored"
        )

        # The one-use token must NOT have been burned by the refusal.
        engine.red = False
        assert view.confirm_planner_timer(planner, preparation) == "", (
            "a Red refusal consumed the preparation the user must re-use"
        )
        assert len(emitted) == 1
    finally:
        view.close()


def test_b74_stale_preparation_is_refused(qt_app):
    """A preparation whose block moved on must not reach Study."""

    engine = FakeEngine()
    view = planner_study_view(engine)
    try:
        emitted: list = []
        view.prepare_requested.connect(lambda *args: emitted.append(args))

        planner = StudyPlanner(plan_id="PLAN-HANDOFF-3")
        block = add_block(planner)
        preparation = prepared(planner)

        # The user edits the block after preparing it.
        planner.replace_block(replace(block, task="cerebellar circuits"))

        reason = view.confirm_planner_timer(planner, preparation)
        assert reason != "", "a stale preparation reached Study"
        assert emitted == []
    finally:
        view.close()


def test_b74_preparation_is_one_use(qt_app):
    """The same preparation cannot dispatch twice."""

    engine = FakeEngine()
    view = planner_study_view(engine)
    try:
        emitted: list = []
        view.prepare_requested.connect(lambda *args: emitted.append(args))

        planner = StudyPlanner(plan_id="PLAN-HANDOFF-4")
        add_block(planner)
        preparation = prepared(planner)

        assert view.confirm_planner_timer(planner, preparation) == ""
        assert view.confirm_planner_timer(planner, preparation) == "preparation_expired"
        assert len(emitted) == 1, "a one-use preparation dispatched twice"
    finally:
        view.close()


def test_b74_handoff_carries_the_current_study_identity(qt_app, real_study_snapshot):
    """The Planner path uses the same identity fence as every Study action."""

    engine = FakeEngine()
    view = planner_study_view(engine)
    try:
        emitted: list = []
        view.prepare_requested.connect(lambda *args: emitted.append(args))
        view.set_study_snapshot(real_study_snapshot)

        planner = StudyPlanner(plan_id="PLAN-HANDOFF-5")
        add_block(planner)
        assert view.confirm_planner_timer(planner, prepared(planner)) == ""

        _s, _t, _ss, _bs, block_id, generation, _k, _i = emitted[0]
        assert block_id == real_study_snapshot.block_id
        assert generation == real_study_snapshot.generation
    finally:
        view.close()


def test_b74_planner_never_starts_study_or_cosecant(qt_app):
    """PREPARATION != START.  The seam touches no runtime at all."""

    import inspect
    from COSECANT_STUDY_MODE.view import StudyView

    source = inspect.getsource(StudyView.confirm_planner_timer)
    for forbidden in (
        "start(",
        "start_break",
        "request_study_action",
        "request_study_break",
        "record_return_intent",
        "cosecant",
    ):
        assert forbidden not in source, (
            f"the Planner handoff references runtime action {forbidden!r}"
        )
    # It reaches Study only through the existing prepare_requested signal.
    assert "prepare_requested.emit" in source


@pytest.fixture
def real_study_snapshot():
    """One REAL StudySnapshot from the engine, for the identity fence test."""

    from test_c10_4_a_golden_assembly import Journey
    from test_c10_4_b_stress_matrix import start_study

    journey = Journey()
    start_study(journey)
    return journey.services.study.snapshot()


# ---------------------------------------------------------------------------
# GROUP B8 — Study Planner user interface
#
# Presentation and assembly.  Every planning FACT still belongs to
# StudyPlanner; these prove the panel renders that truth, routes mutations
# through the authority, and reaches Study only via the B7 seam.
# ---------------------------------------------------------------------------


NAMED_ZONES = ("Asia/Kolkata", "Europe/London", "America/New_York")


_B8_KEEPALIVE: list = []


def planner_view(engine=None, *, planner=None, configured="Europe/London"):
    """One real StudyView with a real Planner child surface.

    Kept alive for the module: a collected StudyView destroys its C++
    children, and any later test that turns the Qt event loop would then
    process a deferred deletion against memory Python still references.
    """

    from PyQt6.QtCore import QObject
    from COSECANT_STUDY_MODE.view import StudyView

    class Settings(QObject):
        def snapshot(self):
            class Snap:
                clock_timezone = configured
            return Snap()

    view = StudyView(
        engine=engine or FakeEngine(),
        lifecycle=QObject(),
        settings=Settings(),
        planner=planner if planner is not None else StudyPlanner(plan_id="PLAN-UI"),
        timezone_choices=NAMED_ZONES,
    )
    _B8_KEEPALIVE.append(view)
    return view


def fill_form(panel, *, subject="Neuroscience", task="basal ganglia",
              date="2026-09-01", hour=9, minute=0):
    from PyQt6.QtCore import QDate, QTime

    panel.subject_input.setText(subject)
    panel.task_input.setText(task)
    panel.date_input.setDate(QDate.fromString(date, "yyyy-MM-dd"))
    panel.time_input.setTime(QTime(hour, minute))
    panel.view_date.setDate(QDate.fromString(date, "yyyy-MM-dd"))


def select_first(panel, *, date="2026-09-01"):
    """Point DAY view at the planned date, render, and select the first row."""

    from PyQt6.QtCore import QDate

    panel.view_date.setDate(QDate.fromString(date, "yyyy-MM-dd"))
    panel.render()
    panel.block_list.setCurrentRow(0)
    return panel._visible[0] if panel._visible else None


def test_b8_1_exactly_one_planner_instance_is_used(qt_app):
    """The panel must operate the SAME planner the view was given."""

    planner = StudyPlanner(plan_id="PLAN-ONE")
    view = planner_view(planner=planner)
    try:
        assert view.planner_panel is not None
        assert view.planner_panel._planner is planner
        assert view._planner is planner
        # Reopening the surface must not build another planner.
        view.show_planner()
        view.show_main_study()
        view.show_planner()
        assert view.planner_panel._planner is planner
        assert planner.plan_id == "PLAN-ONE"
    finally:
        view.close()


def test_b8_2_persisted_blocks_render_after_reopening(qt_app, isolated_lane):
    """Activation reloads durable truth and renders it."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-REOPEN", repository=storage)
        add_block(planner, block_id="PERSISTED-BLOCK")

        # A NEW planner object, as a relaunch builds, with nothing in memory.
        reopened = StudyPlanner(plan_id="PLAN-REOPEN", repository=storage)
        assert reopened.blocks() == ()

        view = planner_view(planner=reopened)
        try:
            view.show_planner()          # activate() -> load_persisted -> render
            panel = view.planner_panel
            select_first(panel)
            assert len(panel._visible) == 1, (
                f"persisted block did not render; status: {panel.status_text()}"
            )
            assert panel._visible[0].block_id == "PERSISTED-BLOCK"
        finally:
            view.close()
    finally:
        storage.shutdown()


def test_b8_3_create_through_the_form_reaches_the_authority(qt_app):
    """POSITIVE CONTROL: SAVE BLOCK genuinely creates planner truth."""

    planner = StudyPlanner(plan_id="PLAN-CREATE")
    view = planner_view(planner=planner)
    try:
        view.show_planner()
        panel = view.planner_panel
        fill_form(panel)
        panel.save_button.click()

        blocks = planner.blocks()
        assert len(blocks) == 1, f"nothing was created; {panel.status_text()}"
        assert blocks[0].subject == "Neuroscience"
        assert blocks[0].timezone_id in NAMED_ZONES
        assert len(panel._visible) == 1
    finally:
        view.close()


def test_b8_3_invalid_create_is_refused_honestly(qt_app):
    """A refused mutation must not pretend to have succeeded."""

    planner = StudyPlanner(plan_id="PLAN-CREATE-BAD")
    view = planner_view(planner=planner)
    try:
        view.show_planner()
        panel = view.planner_panel
        fill_form(panel, subject="   ", task="   ")
        panel.save_button.click()

        assert planner.blocks() == (), "an invalid block reached the authority"
        assert panel.status_text(), "the user was not told the save failed"
    finally:
        view.close()


def test_b8_4_edit_updates_through_the_authority(qt_app):
    """EDIT then SAVE routes a versioned replace_block."""

    planner = StudyPlanner(plan_id="PLAN-EDIT")
    view = planner_view(planner=planner)
    try:
        view.show_planner()
        panel = view.planner_panel
        block = add_block(planner)
        select_first(panel)

        panel.edit_button.click()
        assert panel._editing_block_id == block.block_id
        panel.task_input.setText("cerebellar circuits")
        panel.save_button.click()

        current = planner.block(block.block_id)
        assert current.task == "cerebellar circuits"
        assert current.version == 2, "the edit did not advance the version"
    finally:
        view.close()


def test_b8_5_stale_edit_refuses_safely(qt_app):
    """A block that moved on underneath the panel cannot be mutated blind."""

    planner = StudyPlanner(plan_id="PLAN-STALE")
    view = planner_view(planner=planner)
    try:
        view.show_planner()
        panel = view.planner_panel
        block = add_block(planner)
        select_first(panel)

        # Authority moves on, then the panel's stale row is removed.
        planner.remove_block(block.block_id, expected_version=block.version)
        panel.remove_button.click()

        assert panel.status_text(), "a stale action reported nothing"
        assert planner.blocks() == ()
    finally:
        view.close()


def test_b8_6_remove_and_skip_use_supported_contracts(qt_app):
    """Only mutations the Planner actually supports are exposed."""

    planner = StudyPlanner(plan_id="PLAN-ACTIONS")
    view = planner_view(planner=planner)
    try:
        view.show_planner()
        panel = view.planner_panel

        block = add_block(planner)
        select_first(panel)
        panel.skip_button.click()
        assert planner.block(block.block_id).status is PlanStatus.SKIPPED

        select_first(panel)
        panel.duplicate_button.click()
        assert len(planner.blocks()) == 2, "duplicate did not create a block"

        panel.set_mode("list")
        panel.block_list.setCurrentRow(0)
        panel.remove_button.click()
        assert len(planner.blocks()) == 1
    finally:
        view.close()


def test_b8_7_recurrence_renders_canonical_occurrences(qt_app):
    """DAY view lists exactly the occurrences Planner projects."""

    planner = StudyPlanner(plan_id="PLAN-RECUR-UI")
    view = planner_view(planner=planner)
    try:
        view.show_planner()
        panel = view.planner_panel
        add_block(planner, recurrence=RecurrenceRule(kind=RecurrenceKind.DAILY))

        from PyQt6.QtCore import QDate

        panel.view_date.setDate(QDate.fromString("2026-09-05", "yyyy-MM-dd"))
        panel.render()

        assert len(panel._visible) == 1
        occurrence = panel._visible[0]
        expected = planner.project(
            date_from="2026-09-05", date_to="2026-09-05"
        ).occurrences[0]
        assert occurrence == expected, (
            "the panel rendered something other than canonical planner truth"
        )
        assert occurrence.occurrence_key.endswith("@2026-09-05")
    finally:
        view.close()


def test_b8_8_conflict_warning_comes_from_planner_truth(qt_app):
    """Overlap detection is Planner's; Qt must not compute its own."""

    import inspect
    from COSECANT_STUDY_MODE.view import StudyPlannerPanel

    planner = StudyPlanner(plan_id="PLAN-CONFLICT")
    view = planner_view(planner=planner)
    try:
        view.show_planner()
        panel = view.planner_panel
        add_block(planner, block_id="A")
        add_block(planner, block_id="B")       # same date and time -> overlap
        select_first(panel)

        projection = planner.project(date_from="2026-09-01", date_to="2026-09-01")
        assert projection.warnings, "the LAB expected Planner to warn"
        assert "⚠" in panel.conflict_label.text(), (
            "the planner warning was not presented"
        )

        # And the panel owns no overlap algorithm of its own.
        source = inspect.getsource(StudyPlannerPanel)
        for forbidden in ("overlap_minutes =", "def _conflicts", "def _overlap"):
            assert forbidden not in source, (
                f"the panel computes its own conflicts via {forbidden!r}"
            )
    finally:
        view.close()


def test_b8_9_named_timezone_is_offered_and_stored(qt_app):
    """A named IANA zone reaches the stored block verbatim."""

    planner = StudyPlanner(plan_id="PLAN-TZ-NAMED")
    view = planner_view(planner=planner, configured="Asia/Kolkata")
    try:
        view.show_planner()
        panel = view.planner_panel
        assert panel.selected_timezone() == "Asia/Kolkata", (
            "a valid configured named zone was not preselected"
        )
        fill_form(panel)
        panel.save_button.click()
        assert planner.blocks()[0].timezone_id == "Asia/Kolkata"
    finally:
        view.close()


def test_b8_10_local_is_never_stored_as_a_planner_timezone(qt_app):
    """"local" is not an IANA name and must never become planner truth."""

    planner = StudyPlanner(plan_id="PLAN-TZ-LOCAL")
    view = planner_view(planner=planner, configured="local")
    try:
        view.show_planner()
        panel = view.planner_panel

        # Nothing named "local" is offered at all.
        offered = {
            panel.timezone_input.itemData(index)
            for index in range(panel.timezone_input.count())
        }
        assert "local" not in offered
        assert panel.selected_timezone() in NAMED_ZONES
        assert panel.status_text(), (
            "the user was not told a named Planner timezone is required"
        )

        fill_form(panel)
        panel.save_button.click()
        stored = planner.blocks()[0].timezone_id
        assert stored != "local"
        assert timezone_available_check(stored), (
            f"a zone without DST rules was stored: {stored}"
        )
    finally:
        view.close()


def timezone_available_check(name: str) -> bool:
    from COSECANT_STUDY_MODE.planner import timezone_available

    return timezone_available(name)


def test_b8_11_fixed_offset_fallback_never_reaches_the_planner(qt_app):
    """An unresolvable configured zone is dropped, never offset-substituted."""

    planner = StudyPlanner(plan_id="PLAN-TZ-BAD")
    view = planner_view(planner=planner, configured="Not/AZone")
    try:
        view.show_planner()
        panel = view.planner_panel
        assert panel.selected_timezone() in NAMED_ZONES
        fill_form(panel)
        panel.save_button.click()
        assert planner.blocks()[0].timezone_id in NAMED_ZONES
    finally:
        view.close()


def test_b8_12_set_study_timer_uses_the_canonical_occurrence(qt_app):
    """SET STUDY TIMER prepares from the selected canonical occurrence."""

    engine = FakeEngine()
    planner = StudyPlanner(plan_id="PLAN-SET-TIMER")
    view = planner_view(engine, planner=planner)
    try:
        emitted: list = []
        view.prepare_requested.connect(lambda *args: emitted.append(args))
        view.show_planner()
        panel = view.planner_panel
        add_block(planner)
        select_first(panel)

        panel.set_timer_button.click()

        assert len(emitted) == 1, f"no prepare dispatched; {panel.status_text()}"
        subject, task, study_seconds, break_seconds, _b, _g, kw, imp = emitted[0]
        assert subject == "Neuroscience" and task == "basal ganglia"
        assert study_seconds == 45 * 60 and break_seconds == 10 * 60
        assert kw == () and imp == (), "the Planner invented keyword data"
        # And the user is returned to MAIN STUDY to press START themselves.
        assert view.workspace.currentIndex() == 0
    finally:
        view.close()


def test_b8_13_red_refusal_remains_safe_from_the_panel(qt_app):
    """Protected Red blocks the panel's handoff at command time."""

    engine = FakeEngine(red=True)
    planner = StudyPlanner(plan_id="PLAN-SET-RED")
    view = planner_view(engine, planner=planner)
    try:
        emitted: list = []
        view.prepare_requested.connect(lambda *args: emitted.append(args))
        view.show_planner()
        panel = view.planner_panel
        add_block(planner)
        select_first(panel)

        panel.set_timer_button.click()

        assert emitted == [], "a Study PREPARE escaped during Protected Red"
        assert engine.restore_calls == 1
        assert "protected_red" in panel.status_text()
        # Still on the Planner surface, and told why.
        assert view.workspace.currentIndex() != 0
    finally:
        view.close()


def test_b8_14_stale_preparation_refuses_from_the_panel(qt_app):
    """A block edited after selection cannot be timed blind."""

    engine = FakeEngine()
    planner = StudyPlanner(plan_id="PLAN-SET-STALE")
    view = planner_view(engine, planner=planner)
    try:
        emitted: list = []
        view.prepare_requested.connect(lambda *args: emitted.append(args))
        view.show_planner()
        panel = view.planner_panel
        block = add_block(planner)
        select_first(panel)

        # The block moves on; the panel's rendered occurrence is now stale.
        planner.replace_block(replace(block, task="cerebellar circuits"))
        panel.set_timer_button.click()

        assert emitted == [], "a stale occurrence reached Study"
        assert panel.status_text()
    finally:
        view.close()


def test_b8_16_set_study_timer_never_starts_study_or_cosecant(qt_app):
    """PREPARATION != START, all the way from the panel button."""

    import inspect
    from COSECANT_STUDY_MODE.view import StudyPlannerPanel

    source = inspect.getsource(StudyPlannerPanel)
    for forbidden in (
        "study_action_requested",
        "break_requested",
        "return_intent_requested",
        "record_return_intent",
        "start_break",
        "CosecantRuntime",
        "StudyRuntime",
    ):
        assert forbidden not in source, (
            f"the Planner panel references runtime action {forbidden!r}"
        )


def test_b8_18_opening_the_planner_does_not_disturb_study(qt_app, real_study_snapshot):
    """Child navigation is presentation only."""

    planner = StudyPlanner(plan_id="PLAN-NAV")
    view = planner_view(planner=planner)
    try:
        view.set_study_snapshot(real_study_snapshot)
        before = view._state.study

        view.show_planner()
        view.show_main_study()
        view.show_planner()
        view.show_main_study()

        assert view._state.study is before, (
            "moving between Study child surfaces changed the Study snapshot"
        )
        assert view.state_pill.text() == f"STUDY · {before.state.value}"
    finally:
        view.close()


def test_b8_19_planner_navigation_does_not_alter_cosecant(qt_app, real_cosecant_snapshot):
    """COSECANT presentation survives Planner navigation untouched."""

    cosecant = real_cosecant_snapshot
    planner = StudyPlanner(plan_id="PLAN-NAV-COSECANT")
    view = planner_view(planner=planner)
    try:
        view.set_cosecant_snapshot(cosecant)
        before = view._state.cosecant

        view.show_planner()
        view.show_main_study()

        assert view._state.cosecant is before, (
            "Planner navigation replaced the COSECANT snapshot"
        )
    finally:
        view.close()


def test_b8_20_launcher_showcase_surfaces_remain_intact():
    """B8 assembly must not have disturbed the approved showcase work."""

    import CONTROL_STATION.launcher as launcher

    for name in (
        "MetricHubShowcasePage",
        "LiveMirlShowcasePage",
        "ComingSoonPage",
        "ControlPage",
        "ControlStationSidebar",
        "ControlStationShell",
    ):
        assert hasattr(launcher, name), f"launcher lost {name}"

    source = open(launcher.__file__, encoding="utf-8").read()
    assert "MINE" in source, "the MINE Continuity surface disappeared"
    # The seven approved pages are unchanged.
    assert len(launcher.PAGE_ORDER) == 7


@pytest.fixture(scope="module")
def real_cosecant_snapshot():
    """One REAL CosecantSnapshot from a genuine break, for navigation tests."""

    from COSECANT_STUDY_MODE.cosecant import CosecantState
    from test_c10_4_a_golden_assembly import BREAK_SECONDS, Journey
    from test_c10_4_b_stress_matrix import start_study
    from _lab import LECTURE

    journey = Journey()
    start_study(journey)
    journey.route(LECTURE, 3.0)
    journey.coordinator._request_cosecant_break(BREAK_SECONDS)
    journey.route(LECTURE, 4.5)
    assert journey.cosecant().state is CosecantState.BREAK_ACTIVE
    return journey.cosecant()


# ---------------------------------------------------------------------------
# GROUP B9 — Study Notes surface + durable workspace
#
# Assembly and presentation.  Note FACTS stay in NoteSession/NotesWorkspace
# and the durable NoteStore.  NOTES ARE OPAQUE: no content may reach any
# sensing or behavioural organ, only linkage IDs.
# ---------------------------------------------------------------------------


_B9_KEEPALIVE: list = []


def notes_view(storage, *, planner=None):
    """One real StudyView with a real Notes child surface.

    Every view is kept alive for the module. StudyNotesPanel REPARENTS the
    NotesWorkspace into the view, so letting a view be collected destroys the
    C++ workspace while Python still holds it -- and the next test that turns
    the Qt event loop then touches freed memory.
    """

    from PyQt6.QtCore import QObject
    from COSECANT_STUDY_MODE.notes import NoteSession, NotesWorkspace
    from COSECANT_STUDY_MODE.view import StudyView

    class Settings(QObject):
        def snapshot(self):
            class S:
                clock_timezone = "Europe/London"
            return S()

    session = NoteSession(store=storage)
    workspace = NotesWorkspace(session=session)
    view = StudyView(
        engine=FakeEngine(),
        lifecycle=QObject(),
        settings=Settings(),
        planner=planner,
        timezone_choices=NAMED_ZONES,
        notes_workspace=workspace,
        note_store=storage,
    )
    _B9_KEEPALIVE.append((view, workspace, session))
    return view, workspace, session


def test_b9_1_one_long_lived_workspace_is_used(qt_app, isolated_lane):
    """The panel operates the SAME workspace the view was given."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            assert view.notes_panel is not None
            assert view.notes_panel._workspace is workspace
            assert workspace._session is session
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_2_the_shell_storage_facade_is_reused(qt_app, isolated_lane):
    """No second EngineStorage or lane is created for Notes."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            assert view.notes_panel._store is storage
            assert session._store is storage
            # One facade, one lane, one owner.
            assert isolated_lane.owners() == 1, (
                "Notes assembly acquired an extra storage owner"
            )
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_3_reopening_notes_builds_no_second_worker(qt_app, isolated_lane):
    """Navigating in and out reuses the same session and executor."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            executor = session._executor
            for _ in range(3):
                view.show_notes()
                view.show_main_study()
            assert view.notes_panel._workspace is workspace
            assert workspace._session is session
            assert session._executor is executor, (
                "reopening Notes built another autosave worker"
            )
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_4_create_note_and_5_reload_persisted(qt_app, isolated_lane):
    """POSITIVE CONTROL: create reaches the store and reloads by identity."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            view.show_notes()
            panel = view.notes_panel
            assert panel.create_note(title="Basal Ganglia") is True
            note_id = workspace._document.note_id

            assert session.flush(timeout=3.0) is True, "the new note never saved"
            panel.refresh()
            assert any(s.note_id == note_id for s in panel._summaries), (
                f"the created note did not appear; {panel.status_text()}"
            )

            stored = storage.load_note(note_id)
            assert stored.title == "Basal Ganglia"
            assert stored.revision_number >= 1
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_6_edit_saves_and_7_revision_increments(qt_app, isolated_lane):
    """An accepted edit advances the durable revision exactly once."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            view.show_notes()
            view.notes_panel.create_note(title="Revision One")
            note_id = workspace._document.note_id
            assert session.flush(timeout=3.0)
            first = storage.load_note(note_id).revision_number

            workspace.title.setText("Revision Two")
            workspace._rename()
            assert workspace._document.title == "Revision Two"
            assert session.flush(timeout=3.0)

            second = storage.load_note(note_id)
            assert second.title == "Revision Two"
            assert second.revision_number == first + 1, (
                f"revision went {first} -> {second.revision_number}"
            )
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_8_stale_save_is_rejected_and_9_never_shows_saved(qt_app, isolated_lane):
    """A stale revision must not overwrite durable truth, or claim SAVED."""

    from COSECANT_STUDY_MODE.notes import SaveState
    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            view.show_notes()
            view.notes_panel.create_note(title="Durable Title")
            note_id = workspace._document.note_id
            assert session.flush(timeout=3.0)

            # Another writer advances the durable revision behind this session.
            durable = storage.load_note(note_id)
            storage.save_note(durable, expected_revision=durable.revision_number)
            newest = storage.load_note(note_id)
            assert newest.revision_number == durable.revision_number + 1

            # The session still believes the older revision; its next save is stale.
            workspace.title.setText("Stale Overwrite")
            workspace._rename()
            session.flush(timeout=3.0)

            assert view.notes_panel.save_state() is SaveState.FAILED, (
                "a stale save reported success"
            )
            workspace._refresh_status()  # what the 250ms timer calls, no event loop
            assert workspace.save_label.text() != SaveState.SAVED.value, (
                "the UI showed SAVED for a rejected save"
            )
            assert storage.load_note(note_id).title == newest.title, (
                "a stale save overwrote newer durable truth"
            )
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_10_stale_same_note_reopen_remains_safe(qt_app, isolated_lane):
    """The B3 repair must survive B9 assembly."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            view.show_notes()
            view.notes_panel.create_note(title="Authoritative")
            stale = workspace._document
            workspace.link_current_study("STUDYBLOCKB9", task="basal ganglia")

            assert workspace.open_document(stale) is True
            authoritative = session.snapshot().document
            assert authoritative.linked_study_block_id == "STUDYBLOCKB9"
            assert workspace._document is authoritative, (
                "the workspace re-adopted a stale caller copy"
            )
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_11_oversized_edit_cannot_diverge_visible_truth(qt_app, isolated_lane):
    """A rejected edit keeps the last accepted document and says so."""

    from COSECANT_STUDY_MODE.notes import TextSpan
    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            view.show_notes()
            view.notes_panel.create_note(title="Bounded")
            block = workspace._document.blocks[0]
            workspace._text_changed(block.block_id, (TextSpan(text="basal ganglia"),))
            before = workspace._document

            errors: list = []
            workspace._show_error = errors.append
            workspace._text_changed(block.block_id, (TextSpan(text="x" * 400_000),))

            assert workspace._document is before, (
                "a rejected oversized edit became visible truth"
            )
            assert errors, "the user was not told the edit failed"
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_12_study_linkage_round_trips(qt_app, isolated_lane):
    """Study linkage is metadata that survives persistence."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            view.set_study_snapshot(real_study_snapshot_value())
            assert view.open_note_for_current_study() is True
            note_id = workspace._document.note_id
            assert session.flush(timeout=3.0)

            stored = storage.load_note(note_id)
            assert stored.linked_study_block_id == view._state.study.block_id
            assert stored.linked_plan_id == ""
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_13_planner_linkage_round_trips(qt_app, isolated_lane):
    """Planner linkage is metadata that survives persistence."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-NOTE-LINK")
        block = add_block(planner)
        view, workspace, session = notes_view(storage, planner=planner)
        try:
            assert view.open_note_for_planner_block(block) is True
            note_id = workspace._document.note_id
            assert session.flush(timeout=3.0)

            stored = storage.load_note(note_id)
            assert stored.linked_plan_id == "PLAN-NOTE-LINK"
            assert stored.linked_plan_block_id == block.block_id
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_14_navigation_leaves_the_study_snapshot_unchanged(qt_app, isolated_lane):
    """Main / Planner / Notes switching is presentation only."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-NAV-NOTES")
        view, workspace, session = notes_view(storage, planner=planner)
        try:
            view.set_study_snapshot(real_study_snapshot_value())
            before = view._state.study

            view.show_notes()
            view.show_planner()
            view.show_notes()
            view.show_main_study()

            assert view._state.study is before, (
                "child navigation changed the Study snapshot"
            )
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_15_navigation_leaves_cosecant_unchanged(
    qt_app, isolated_lane, real_cosecant_snapshot
):
    """COSECANT presentation survives Notes navigation untouched."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            view.set_cosecant_snapshot(real_cosecant_snapshot)
            before = view._state.cosecant

            view.show_notes()
            view.show_main_study()
            view.show_notes()

            assert view._state.cosecant is before, (
                "Notes navigation replaced the COSECANT snapshot"
            )
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_16_to_19_notes_never_reach_a_behavioural_organ():
    """NOTES ARE OPAQUE: no sensing or behavioural import, anywhere."""

    import COSECANT_STUDY_MODE.notes as notes_module

    imported = _imported_modules(notes_module)
    for forbidden in FORBIDDEN_AUTHORITY_MODULES:
        assert forbidden not in imported, (
            f"notes.py imported behavioural authority {forbidden}"
        )

    # And the Notes SURFACE added in B9 reads no content for any purpose.
    import inspect
    from COSECANT_STUDY_MODE.view import StudyNotesPanel

    source = inspect.getsource(StudyNotesPanel)
    # Precise identifiers only.  A substring scan for a word like "browser"
    # would match this panel's own prose about a note BROWSER and prove
    # nothing about what it touches.
    for forbidden in (
        "ResourceIntentLiveView",
        "resource_intent.",
        "BrowserEvidence",
        "browser.",
        "blacklist.",
        "SineAuthority",
        "MirlAuthority",
        "CosecantRuntime",
        "CosecantSnapshot",
        "observe_return",
        "StudyRuntime",
        ".blocks",
    ):
        assert forbidden not in source, (
            f"the Notes panel touches {forbidden!r}"
        )


def test_b9_20_bounded_notes_shutdown_completes(qt_app, isolated_lane):
    """Shutdown is bounded and reports honestly."""

    import time as _time
    from COSECANT_STUDY_MODE.notes import SaveState
    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            view.show_notes()
            view.notes_panel.create_note(title="Drain Me")

            started = _time.monotonic()
            assert view.notes_panel.shutdown(timeout=2.0) is True
            elapsed = _time.monotonic() - started

            assert elapsed < 10.0, f"shutdown was not bounded: {elapsed:.1f}s"
            assert session.snapshot().save_state is SaveState.CLOSED
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()


def test_b9_20_navigation_gate_waits_for_the_notes_flush(qt_app, isolated_lane):
    """prepare_to_leave_async must not report success on a failed flush.

    Asserted on the SYNCHRONOUS decision and its visible consequence, never by
    turning the Qt event loop.  Spinning here would deliver deferred deletions
    queued by other suites in the same process and touch freed memory; the
    deferred ``completed`` hop itself is Qt plumbing that C11-A already covers
    through NavigationController's study_leave_refused path.
    """

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        view, workspace, session = notes_view(storage)
        try:
            view.show_notes()
            view.notes_panel.create_note(title="Leaving")

            # POSITIVE CONTROL: a clean drain is admitted and says nothing bad.
            view.notes_panel._set_status("")
            assert view.prepare_to_leave_async(lambda _ok: None) is True
            assert "could not be saved" not in view.notes_panel.status_text()

            # A refusing flush must tell the user and keep them on Study.
            calls: list = []

            def refuse(**_kw):
                calls.append(True)
                return False

            view.notes_panel.prepare_to_leave = refuse
            view.notes_panel._set_status("")
            assert view.prepare_to_leave_async(lambda _ok: None) is True
            assert calls == [True], "the gate never attempted a flush"
            assert "could not be saved" in view.notes_panel.status_text(), (
                "navigation was allowed silently despite an unsaved note"
            )
        finally:
            workspace.shutdown(timeout=2.0)
            view.close()
    finally:
        storage.shutdown()
        storage.shutdown()


def test_b9_21_launcher_owns_one_storage_and_releases_it_once():
    """Storage closes only through the existing ownership path."""

    import inspect
    import CONTROL_STATION.launcher as launcher

    source = inspect.getsource(launcher.ControlStationWindow)
    assert source.count("EngineStorage()") == 1, (
        "the launcher constructs more than one storage facade"
    )
    assert source.count("self.storage.shutdown()") == 1
    assert "NoteSession(store=self.storage)" in source, (
        "Notes did not reuse the shell storage facade"
    )
    # Notes drain must precede the storage release.
    assert source.index("self.notes_workspace.shutdown(") < source.index(
        "self.storage.shutdown()"
    ), "storage was released before Notes had drained"


def test_b9_22_launcher_showcase_remains_intact():
    import CONTROL_STATION.launcher as launcher

    for name in (
        "MetricHubShowcasePage",
        "LiveMirlShowcasePage",
        "ComingSoonPage",
        "ControlPage",
        "ControlStationSidebar",
        "ControlStationShell",
    ):
        assert hasattr(launcher, name), f"launcher lost {name}"
    assert len(launcher.PAGE_ORDER) == 7


def real_study_snapshot_value():
    from test_c10_4_a_golden_assembly import Journey
    from test_c10_4_b_stress_matrix import start_study

    journey = Journey()
    start_study(journey)
    return journey.services.study.snapshot()


# ---------------------------------------------------------------------------
# GROUP B10 — final assembly, Qt lifetime proof, hostile regression
#
# B9 exposed a real Qt ownership fact: StudyNotesPanel REPARENTS the
# long-lived NotesWorkspace into the StudyView tree, so whoever owns the view
# also owns the workspace's C++ lifetime.  In the LAB that produced crashes
# once views were garbage collected.  These tests establish, factually, that
# the PRODUCTION ownership order cannot reach the same condition.
#
# Liveness is measured with sip.isdeleted -- the actual C++ object state --
# not by inference from Python references.
# ---------------------------------------------------------------------------


def qt_alive(obj) -> bool:
    """True while the underlying C++ object still exists."""

    from PyQt6 import sip

    return not sip.isdeleted(obj)


def owned_shell(storage, *, planner=None):
    """The REAL production ownership shape.

    ControlStationWindow holds the workspace AND the StudyView; the view sits
    in a QStackedWidget inside the window's central widget.  This reproduces
    exactly that chain so the lifetime claims are about the real structure.
    """

    from PyQt6.QtCore import QObject
    from PyQt6.QtWidgets import QMainWindow, QStackedWidget
    from COSECANT_STUDY_MODE.notes import NoteSession, NotesWorkspace
    from COSECANT_STUDY_MODE.view import StudyView

    class Settings(QObject):
        def snapshot(self):
            class S:
                clock_timezone = "Europe/London"
            return S()

    session = NoteSession(store=storage)
    workspace = NotesWorkspace(session=session)
    view = StudyView(
        engine=FakeEngine(),
        lifecycle=QObject(),
        settings=Settings(),
        planner=planner,
        timezone_choices=NAMED_ZONES,
        notes_workspace=workspace,
        note_store=storage,
    )
    window = QMainWindow()
    stack = QStackedWidget(window)
    stack.addWidget(view)
    window.setCentralWidget(stack)

    holder = (window, stack, view, workspace, session)
    _B10_KEEPALIVE.append(holder)
    return holder


_B10_KEEPALIVE: list = []


def launcher_window_source() -> str:
    import inspect
    import CONTROL_STATION.launcher as launcher

    return inspect.getsource(launcher.ControlStationWindow)


# -- L1..L7 : production Qt ownership / lifetime -----------------------------


def test_b10_l1_exactly_one_production_studyview_is_constructed():
    """One StudyView for the shell lifetime, built once in _create_pages."""

    source = launcher_window_source()
    assert source.count("StudyView(") == 1, (
        "the launcher constructs more than one StudyView"
    )
    assert source.count("NotesWorkspace(") == 1
    assert source.count("NoteSession(") == 1


def test_b10_l2_navigation_never_destroys_the_view_or_workspace(
    qt_app, isolated_lane
):
    """MAIN / PLANNER / NOTES cycling leaves both C++ objects alive."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-B10-NAV")
        window, stack, view, workspace, session = owned_shell(
            storage, planner=planner
        )
        try:
            for _ in range(4):
                view.show_notes()
                view.show_planner()
                view.show_main_study()
                assert qt_alive(view), "navigation destroyed the StudyView"
                assert qt_alive(workspace), "navigation destroyed the workspace"
        finally:
            workspace.shutdown(timeout=2.0)
    finally:
        storage.shutdown()


def test_b10_l3_reopening_notes_never_reconstructs_the_workspace(
    qt_app, isolated_lane
):
    """The same workspace object and session survive every reopen."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        window, stack, view, workspace, session = owned_shell(storage)
        try:
            executor = session._executor
            for _ in range(4):
                view.show_notes()
                view.show_main_study()
                assert view.notes_panel._workspace is workspace
                assert workspace._session is session
                assert session._executor is executor
                assert qt_alive(workspace)
        finally:
            workspace.shutdown(timeout=2.0)
    finally:
        storage.shutdown()


def test_b10_l4_workspace_stays_valid_until_its_bounded_shutdown(
    qt_app, isolated_lane
):
    """The workspace is a live QObject right up to the shutdown call."""

    from COSECANT_STUDY_MODE.notes import SaveState
    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        window, stack, view, workspace, session = owned_shell(storage)
        view.show_notes()
        view.notes_panel.create_note(title="Lifetime")

        assert qt_alive(workspace)
        assert workspace.shutdown(timeout=2.0) is True
        # Shutdown ENDS the session; it does not destroy the widget.
        assert qt_alive(workspace), (
            "the bounded shutdown destroyed the Qt object"
        )
        assert session.snapshot().save_state is SaveState.CLOSED
    finally:
        storage.shutdown()


def test_b10_l5_window_close_does_not_destroy_the_workspace(
    qt_app, isolated_lane
):
    """_finish_shutdown runs BEFORE close(), and close() destroys nothing.

    ControlStationWindow does not set WA_DeleteOnClose, so closing the window
    hides it.  Even if the order were reversed, the workspace would still be a
    live object when its shutdown was called.
    """

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        window, stack, view, workspace, session = owned_shell(storage)
        try:
            window.show()
            window.close()

            assert qt_alive(window)
            assert qt_alive(view), "closing the window destroyed the StudyView"
            assert qt_alive(workspace), (
                "closing the window destroyed the NotesWorkspace"
            )
            # And the bounded shutdown still succeeds afterwards.
            assert workspace.shutdown(timeout=2.0) is True
        finally:
            pass
    finally:
        storage.shutdown()


def test_b10_l6_no_study_or_notes_widget_deletes_itself_on_close():
    """WA_DeleteOnClose would make the C++ lifetime implicit.  None is set."""

    from pathlib import Path

    root = Path(
        __import__("COSECANT_STUDY_MODE.view", fromlist=["view"]).__file__
    ).parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "WA_DeleteOnClose" in text:
            offenders.append(path.name)
    # SINE's own transient popup legitimately self-deletes; nothing in the
    # Study family may, because the shell owns those lifetimes explicitly.
    assert offenders == ["popup.py"], (
        f"unexpected WA_DeleteOnClose owners: {offenders}"
    )

    import inspect
    from COSECANT_STUDY_MODE.view import StudyNotesPanel, StudyPlannerPanel, StudyView

    for widget in (StudyView, StudyNotesPanel, StudyPlannerPanel):
        source = inspect.getsource(widget)
        assert "WA_DeleteOnClose" not in source
        assert "deleteLater" not in source, (
            f"{widget.__name__} schedules its own deletion"
        )


def test_b10_l7_shutdown_order_is_notes_then_engine_then_storage():
    """Ordering is source-factual, not assumed."""

    source = launcher_window_source()
    notes = source.index("self.notes_workspace.shutdown(")
    engine = source.index("self.engine.shutdown()")
    storage = source.index("self.storage.shutdown()")
    close = source.index("QTimer.singleShot(0, self._close_and_quit_application)")

    assert notes < engine < storage < close, (
        f"shutdown order is wrong: notes={notes} engine={engine} "
        f"storage={storage} close={close}"
    )
    # Nothing touches the workspace after the window is asked to close.
    tail = source[close:]
    assert "notes_workspace" not in tail, (
        "the launcher reaches the workspace after requesting window close"
    )
    assert "self.storage." not in tail


# -- assembly authority invariants -------------------------------------------


def test_b10_authority_boundaries_hold_across_the_study_family():
    """Each organ imports only what its own job needs."""

    import COSECANT_STUDY_MODE.planner as planner_module
    import COSECANT_STUDY_MODE.notes as notes_module

    for module in (planner_module, notes_module):
        imported = _imported_modules(module)
        for forbidden in FORBIDDEN_AUTHORITY_MODULES:
            assert forbidden not in imported, (
                f"{module.__name__} imported {forbidden}"
            )

    # The view PRESENTS engine truth, so it may read those read-models, but it
    # must not own persistence or command routing.
    import COSECANT_STUDY_MODE.view as view_module

    view_imports = _imported_modules(view_module)
    assert "PERSISTENCE.storage" not in view_imports, (
        "the view imported persistence directly"
    )
    assert "PERSISTENCE.database" not in view_imports
    assert "CORE_ENGINE.monitor" not in view_imports


def test_b10_view_writes_no_sql():
    """UI never constructs SQL; storage is the only persistence boundary."""

    import inspect
    from COSECANT_STUDY_MODE.view import StudyNotesPanel, StudyPlannerPanel

    for widget in (StudyNotesPanel, StudyPlannerPanel):
        source = inspect.getsource(widget)
        # Real SQL markers, not English words: "Select a named Planner
        # timezone" is user-facing prose, and a keyword scan would flag it.
        for token in (
            ".execute(",
            "connect_database",
            "sqlite3",
            "INSERT INTO",
            "SELECT ",
            " FROM ",
            "DELETE FROM",
        ):
            if token == "SELECT ":
                assert "SELECT " not in source.replace("Select a named", ""), (
                    f"{widget.__name__} contains a SQL SELECT"
                )
                continue
            assert token not in source, (
                f"{widget.__name__} contains SQL token {token!r}"
            )


# -- navigation isolation, measured on real snapshots ------------------------


def test_b10_navigation_preserves_every_published_truth(
    qt_app, isolated_lane, real_cosecant_snapshot
):
    """Child navigation changes the visible page and nothing else."""

    from PERSISTENCE.storage import EngineStorage

    storage = EngineStorage()
    try:
        planner = StudyPlanner(plan_id="PLAN-B10-ISO")
        window, stack, view, workspace, session = owned_shell(
            storage, planner=planner
        )
        try:
            study = real_study_snapshot_value()
            view.set_study_snapshot(study)
            view.set_cosecant_snapshot(real_cosecant_snapshot)
            before_study = view._state.study
            before_cosecant = view._state.cosecant
            before_intent = view._state.resource_intent

            for _ in range(3):
                view.show_planner()
                view.show_notes()
                view.show_main_study()

            assert view._state.study is before_study
            assert view._state.cosecant is before_cosecant
            assert view._state.resource_intent is before_intent
            # Identity, generation and countdown truth are all untouched.
            assert view._state.study.block_id == study.block_id
            assert view._state.study.generation == study.generation
            assert view._state.study.remaining_seconds == study.remaining_seconds
            assert view._state.cosecant.state is real_cosecant_snapshot.state
            assert (
                view._state.cosecant.break_ends_monotonic_ns
                == real_cosecant_snapshot.break_ends_monotonic_ns
            )
        finally:
            workspace.shutdown(timeout=2.0)
    finally:
        storage.shutdown()


# -- C11-A protections still alive -------------------------------------------


def test_b10_c11a_protections_are_still_present():
    """The C11-A repairs must not have been eroded by C11-B assembly."""

    import inspect
    from COSECANT_STUDY_MODE.view import ContinuityPopup, StudyView

    view_source = inspect.getsource(StudyView)
    # Stale Study identity fence on every sensitive action.
    assert "_expected_study_identity" in view_source
    # Presentation epoch reset.
    assert "reset_presentation_epoch" in view_source
    # Navigation readiness contract.
    assert "def refresh" in view_source

    popup_source = inspect.getsource(ContinuityPopup)
    # FINAL_LOCK guards.
    assert "popup_must_remain_open" in popup_source
    assert "def closeEvent" in popup_source
    assert "def keyPressEvent" in popup_source
    # Ordering guard is applied before the snapshot is adopted.
    assert "_cosecant_supersedes" in popup_source


def test_b10_within_session_ordering_is_still_strict(qt_app, real_cosecant_snapshot):
    """C11-A L4 ordering must survive B8/B9 construction changes."""

    from PyQt6.QtCore import QObject
    from COSECANT_STUDY_MODE.view import StudyView

    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    _B10_KEEPALIVE.append(view)

    current = replace(
        real_cosecant_snapshot,
        generation=real_cosecant_snapshot.generation + 4,
        fact_sequence=real_cosecant_snapshot.fact_sequence + 20,
    )
    view.set_cosecant_snapshot(current)
    view.set_cosecant_snapshot(real_cosecant_snapshot)     # older, no reset
    assert view._state.cosecant is current, (
        "C11-B assembly weakened same-session COSECANT ordering"
    )
