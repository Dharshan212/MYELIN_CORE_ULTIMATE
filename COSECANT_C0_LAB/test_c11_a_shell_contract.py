"""C11-A — outer Study/COSECANT shell contract.

LAB TESTING ONLY.  No test file enters MYELIN2.0_ULTIMATE.

C10 froze the nucleus: the reflex itself is healthy.  This file attacks the
OUTER SHELL -- the afferent path that carries engine snapshots to the eye, and
the efferent path that carries a click back to the muscle.

Four boundary contracts are under test:

    L1  a Study page must open on every navigation, not only the first
    L2  a Study command must name the Study identity the user was looking at
    L3  a return intent must name the COSECANT episode that displayed it
    L4  a stale snapshot must not overwrite or reopen a newer presentation

N5 is a POSITIVE CONTROL, not a repair target: FINAL_LOCK's close/Escape/button
protections already exist and must stay green throughout.

CLOCK CONTRACT -- inherited from C10.4-A/B and binding on every claim here:
    Study/COSECANT/SINE and foreground timestamps are deterministically
    controlled.  MIRL, Blacklist and Trigger keep their real production clocks
    and carry NO absolute-timing assertion.

FAULT SHAPING POLICY -- inherited from C10.4-B:
    Where a stale object cannot arise from a live fixture inside one test, it
    is rebuilt from a REAL captured production snapshot with
    ``dataclasses.replace``.  No snapshot is hand-constructed from nothing and
    no verdict is fabricated.

VACUITY RULE -- standing forensic law after C10.2 / C10.4-B G4 / G5:
    Every negative assertion here is preceded by a positive control proving the
    forbidden mechanism was genuinely eligible to fire.
"""

from __future__ import annotations

import os
import time
from dataclasses import replace

import pytest

# Qt must be told it has no display BEFORE QApplication is constructed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, Qt, QEvent, pyqtSignal
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QStackedWidget, QWidget

import _lab
from _lab import INSTAGRAM, LECTURE

from CONTROL_STATION.navigation import (
    PAGE_CONTROL,
    PAGE_ORDER,
    PAGE_STUDY,
    NavigationController,
)
from COSECANT_STUDY_MODE.cosecant import (
    CosecantSnapshot,
    CosecantState,
    CosecantUiAction,
)
from COSECANT_STUDY_MODE.study import StudySnapshot, StudyState
from COSECANT_STUDY_MODE.view import ContinuityPopup, StudyView, StudyViewState

from test_c10_4_a_golden_assembly import (
    BREAK_SECONDS,
    IMPORTANT,
    KEYWORDS,
    SUBJECT,
    TASK,
    Journey,
)
from test_c10_4_b_stress_matrix import reach_final_lock, start_study


# ---------------------------------------------------------------------------
# Qt scaffolding.  The objects UNDER TEST are the real production StudyView,
# NavigationController and ContinuityPopup.  Only the two collaborators that
# belong to other authorities (Protected Red, the sidebar) are stood in for,
# and each implements the exact contract navigation.py calls.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def app():
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class FakeRedGuard(QObject):
    """The exact ProtectedRedGuard surface navigation.py consumes."""

    state_changed = pyqtSignal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.protected = False
        self.restored = 0

    def is_red_protected(self) -> bool:
        return self.protected

    def restore_authoritative_surface(self) -> bool:
        self.restored += 1
        return True


class FakeSidebar(QObject):
    """The exact sidebar surface navigation.py consumes."""

    page_requested = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.is_open = False
        self.selected: list[str] = []
        self.navigation_enabled: list[bool] = []

    def set_open(self, value: bool) -> None:
        self.is_open = bool(value)

    def select(self, page_name: str) -> None:
        self.selected.append(str(page_name))

    def set_navigation_enabled(self, enabled: bool) -> None:
        self.navigation_enabled.append(bool(enabled))


class Shell:
    """One real NavigationController driving one real StudyView."""

    def __init__(self) -> None:
        self.stack = QStackedWidget()
        self.study = StudyView(
            engine=QObject(),
            lifecycle=QObject(),
            settings=QObject(),
        )
        self.pages = {}
        for name in PAGE_ORDER:
            page = self.study if name == PAGE_STUDY else QWidget()
            self.pages[name] = page
            self.stack.addWidget(page)

        self.red = FakeRedGuard()
        self.sidebar = FakeSidebar()
        self.navigation = NavigationController(
            page_stack=self.stack,
            pages=self.pages,
            study_page=self.study,
            red_guard=self.red,
            sidebar=self.sidebar,
        )

        self.started: list[str] = []
        self.opened: list[str] = []
        self.finished: list[str] = []
        self.rejected: list[tuple[str, str]] = []
        self.navigation.transition_started.connect(self.started.append)
        self.navigation.page_opened.connect(self.opened.append)
        self.navigation.transition_finished.connect(self.finished.append)
        self.navigation.transition_rejected.connect(
            lambda destination, reason: self.rejected.append((destination, reason))
        )

    def current(self) -> QWidget:
        return self.stack.currentWidget()

    def close(self) -> None:
        self.navigation.shutdown()


def _process() -> None:
    QApplication.processEvents()


def spin_events(seconds: float = 0.6) -> None:
    """Turn the Qt event loop for a bounded time.

    Deliberately far SHORTER than NavigationController.READINESS_TIMEOUT_MS.
    The production timeout is never shortened or bypassed by this LAB; a
    transition that needs five seconds of wall clock has already failed the
    C11 contract under test.
    """

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _process()
        time.sleep(0.005)


# ---------------------------------------------------------------------------
# GROUP L1 — repeated Study navigation readiness
# ---------------------------------------------------------------------------


def test_l1_first_study_navigation_opens_the_page(app):
    """Control -> Study must actually open Study.

    The constructor-time ``ready`` emission is deliberately allowed to fire and
    be consumed FIRST, exactly as it does in the real application, where the
    window is built and shown before the user ever asks for Study Mode.
    """

    shell = Shell()
    try:
        shell.navigation.open_initial_page(PAGE_CONTROL)
        spin_events(0.3)          # constructor singleShot(0) ready fires here
        assert shell.current() is shell.pages[PAGE_CONTROL]

        shell.opened.clear()
        assert shell.navigation.open_page(PAGE_STUDY) is True
        spin_events(0.8)

        assert PAGE_STUDY in shell.opened, (
            "Study never opened; rejections: "
            f"{shell.rejected}; started: {shell.started}"
        )
        assert shell.current() is shell.study
        assert PAGE_STUDY in shell.finished
        assert shell.rejected == []
    finally:
        shell.close()


def test_l1_control_page_navigation_is_the_positive_control(app):
    """A page with neither refresh nor ready opens promptly.

    This is the non-vacuous half of L1: it proves the navigation machinery,
    the event spin and the assertions in this file are all capable of opening
    a page at all, so a Study failure above is about Study.
    """

    shell = Shell()
    try:
        shell.navigation.open_initial_page(PAGE_STUDY)
        spin_events(0.3)
        assert shell.current() is shell.study

        shell.opened.clear()
        assert shell.navigation.open_page(PAGE_CONTROL) is True
        spin_events(0.6)

        assert PAGE_CONTROL in shell.opened
        assert shell.current() is shell.pages[PAGE_CONTROL]
        assert shell.rejected == []
    finally:
        shell.close()


def test_l1_repeated_study_navigation_reconstructs(app):
    """Control -> Study -> Control -> Study again must open Study twice."""

    shell = Shell()
    try:
        shell.navigation.open_initial_page(PAGE_CONTROL)
        spin_events(0.3)

        assert shell.navigation.open_page(PAGE_STUDY) is True
        spin_events(0.8)
        assert shell.current() is shell.study, (
            f"first Study entry failed; rejections: {shell.rejected}"
        )

        assert shell.navigation.open_page(PAGE_CONTROL) is True
        spin_events(0.6)
        assert shell.current() is shell.pages[PAGE_CONTROL]

        shell.opened.clear()
        assert shell.navigation.open_page(PAGE_STUDY) is True
        spin_events(0.8)

        assert PAGE_STUDY in shell.opened, (
            "Study did not open on the SECOND navigation; "
            f"rejections: {shell.rejected}"
        )
        assert shell.current() is shell.study
        assert shell.rejected == []
    finally:
        shell.close()


def test_l1_study_refresh_is_presentation_only(app):
    """Any readiness contract must re-render, never manufacture authority."""

    shell = Shell()
    try:
        refresh = getattr(shell.study, "refresh", None)
        assert callable(refresh), "StudyView must expose a callable refresh()"

        study_before = shell.study._state.study
        cosecant_before = shell.study._state.cosecant
        intent_before = shell.study._state.resource_intent

        refresh()
        spin_events(0.2)

        assert shell.study._state.study is study_before
        assert shell.study._state.cosecant is cosecant_before
        assert shell.study._state.resource_intent is intent_before
    finally:
        shell.close()


def test_l1_readiness_timeout_constant_is_unchanged(app):
    """The production readiness timeout must not be shortened by this repair."""

    assert NavigationController.READINESS_TIMEOUT_MS == 5_000


# ---------------------------------------------------------------------------
# Engine staging shared by L2 / L3
# ---------------------------------------------------------------------------


def send(journey: Journey, kind: str, **payload) -> None:
    """Deliver one command down the REAL Monitor command-ingress path.

    C12-F closed the identity-free tunnel, so this helper now sends the REAL
    PRODUCTION COMMAND SHAPE: the Control Station controller always copies the
    expected-identity fields in, so a command that omitted them was exercising
    a path no user could reach.  A caller that supplies its own identity --
    stale, partial or absent -- still gets exactly what it asked for.
    """

    body = dict(payload)
    if kind in {"study_prepare", "study_action", "study_break"}:
        block_id, generation = study_identity(journey)
        body.setdefault("expected_study_block_id", block_id)
        body.setdefault("expected_study_generation", generation)
    elif kind == "cosecant_return_intent":
        for key, value in cosecant_identity(journey).items():
            body.setdefault(key, value)
    send_raw(journey, kind, **body)


def send_raw(journey: Journey, kind: str, **payload) -> None:
    """Deliver one command EXACTLY as given, adding no identity."""

    journey.coordinator.command_queue.put({"kind": kind, "payload": dict(payload)})
    journey.coordinator._drain_commands()


def prepare_and_start(journey: Journey, *, task: str) -> StudySnapshot:
    services = journey.services
    result = services.study.prepare(
        subject=SUBJECT,
        task=task,
        planned_seconds=3600,
        keywords=KEYWORDS,
        important_keywords=IMPORTANT,
    )
    assert getattr(result, "accepted", False), getattr(result, "message", "")
    assert getattr(services.study.start(), "accepted", False)
    return services.study.snapshot()


def study_identity(journey: Journey) -> tuple[str, int]:
    snapshot = journey.services.study.snapshot()
    return snapshot.block_id, snapshot.generation


# ---------------------------------------------------------------------------
# GROUP L2 — stale Study command identity
# ---------------------------------------------------------------------------


def test_l2_current_identity_pause_is_accepted(journey_factory):
    """POSITIVE CONTROL: the current generation genuinely accepts PAUSE.

    Without this, the stale-rejection test below would be vacuous -- a refusal
    proves nothing if PAUSE could never have worked in the first place.
    """

    journey = journey_factory()
    start_study(journey)
    block_id, generation = study_identity(journey)
    assert journey.services.study.snapshot().state is StudyState.ACTIVE

    send(
        journey,
        "study_action",
        action="PAUSE",
        expected_study_block_id=block_id,
        expected_study_generation=generation,
    )

    assert journey.services.study.snapshot().state is StudyState.PAUSED


def test_l2_stale_generation_pause_cannot_pause_a_newer_block(journey_factory):
    """An action issued against generation 1 must not reach generation 2."""

    journey = journey_factory()
    start_study(journey)
    stale_block_id, stale_generation = study_identity(journey)

    assert getattr(journey.services.study.complete(), "accepted", False)
    prepare_and_start(journey, task="cerebellar circuits")
    fresh_block_id, fresh_generation = study_identity(journey)

    assert fresh_generation != stale_generation
    assert journey.services.study.snapshot().state is StudyState.ACTIVE

    before = list(journey.fact_kinds)
    send(
        journey,
        "study_action",
        action="PAUSE",
        expected_study_block_id=stale_block_id,
        expected_study_generation=stale_generation,
    )

    current = journey.services.study.snapshot()
    assert current.state is StudyState.ACTIVE, (
        "a generation-1 PAUSE paused the generation-2 Study block"
    )
    assert current.block_id == fresh_block_id
    assert current.generation == fresh_generation
    assert journey.fact_kinds == before


def test_l2_stale_generation_break_request_is_refused(journey_factory):
    """A START BREAK issued against an old Study generation must not park."""

    journey = journey_factory()
    start_study(journey)
    stale_block_id, stale_generation = study_identity(journey)

    assert getattr(journey.services.study.complete(), "accepted", False)
    prepare_and_start(journey, task="cerebellar circuits")
    fresh_block_id, fresh_generation = study_identity(journey)
    assert fresh_generation != stale_generation

    send(
        journey,
        "study_break",
        selected_break_seconds=BREAK_SECONDS,
        expected_study_block_id=stale_block_id,
        expected_study_generation=stale_generation,
    )

    assert journey.coordinator._pending_break_seconds is None, (
        "a stale-generation break request was parked for admission"
    )

    journey.route(LECTURE, 40.0)
    assert journey.cosecant().state is CosecantState.INACTIVE
    assert journey.services.study.snapshot().state is StudyState.ACTIVE


def test_l2_current_identity_break_request_is_the_positive_control(journey_factory):
    """POSITIVE CONTROL: a correctly-identified break request genuinely parks
    and is genuinely admitted, so the refusal above is not vacuous."""

    journey = journey_factory()
    start_study(journey)
    block_id, generation = study_identity(journey)

    send(
        journey,
        "study_break",
        selected_break_seconds=BREAK_SECONDS,
        expected_study_block_id=block_id,
        expected_study_generation=generation,
    )
    assert journey.coordinator._pending_break_seconds == BREAK_SECONDS

    journey.route(LECTURE, 3.0)
    assert journey.cosecant().state is CosecantState.BREAK_ACTIVE
    assert journey.services.study.snapshot().state is StudyState.PAUSED


def test_l2_break_admission_rechecks_identity_at_admission(journey_factory):
    """The parked break belongs to the Study block that asked for it.

    A break request is parked until the next observation, so validating only at
    request time leaves a window in which Study identity can move underneath a
    pending break.  Only the requesting Study identity may receive it.
    """

    journey = journey_factory()
    start_study(journey)
    block_id, generation = study_identity(journey)

    send(
        journey,
        "study_break",
        selected_break_seconds=BREAK_SECONDS,
        expected_study_block_id=block_id,
        expected_study_generation=generation,
    )
    assert journey.coordinator._pending_break_seconds == BREAK_SECONDS

    # Study identity moves BEFORE the parked request is admitted.
    assert getattr(journey.services.study.complete(), "accepted", False)
    prepare_and_start(journey, task="cerebellar circuits")
    fresh_block_id, fresh_generation = study_identity(journey)
    assert fresh_generation != generation

    journey.route(LECTURE, 40.0)
    journey.route(LECTURE, 41.5)

    assert journey.cosecant().state is CosecantState.INACTIVE, (
        "a break parked by an older Study generation was admitted to a newer one"
    )
    current = journey.services.study.snapshot()
    assert current.state is StudyState.ACTIVE, (
        "a stale parked break paused the newer Study block"
    )
    assert current.block_id == fresh_block_id


def test_l2_malformed_expected_identity_is_rejected(journey_factory):
    """A partially supplied expected identity is refused, never treated as legacy."""

    journey = journey_factory()
    start_study(journey)
    block_id, _generation = study_identity(journey)

    # send_raw: the point of this test is a HALF-supplied identity, so the
    # helper must not complete it (C12-F).
    send_raw(journey, "study_action", action="PAUSE", expected_study_block_id=block_id)

    assert journey.services.study.snapshot().state is StudyState.ACTIVE, (
        "a half-supplied identity was silently accepted as a legacy command"
    )


def test_l2_absent_expected_identity_is_rejected(journey_factory):
    """C12-F: an identity-free Study command is refused, not exempted.

    This replaces the old legacy-tunnel test.  The production caller matrix
    proved every live sender supplies the pair unconditionally, so a command
    that omits it is malformed -- and a malformed command that could still
    mutate Study state was a hole straight through the C11-A fence.
    """

    journey = journey_factory()
    start_study(journey)

    # POSITIVE CONTROL: the same PAUSE genuinely works when it names itself.
    send(journey, "study_action", action="PAUSE")
    assert journey.services.study.snapshot().state is StudyState.PAUSED
    send(journey, "study_action", action="RESUME")
    assert journey.services.study.snapshot().state is StudyState.ACTIVE

    send_raw(journey, "study_action", action="PAUSE")

    assert journey.services.study.snapshot().state is StudyState.ACTIVE, (
        "an identity-free command bypassed the stale-generation fence"
    )


# ---------------------------------------------------------------------------
# GROUP L3 — stale COSECANT return-intent identity
# ---------------------------------------------------------------------------


def cosecant_identity(journey: Journey) -> dict:
    snapshot = journey.cosecant()
    return {
        "expected_break_id": snapshot.break_id,
        "expected_cosecant_generation": snapshot.generation,
        "expected_study_block_id": snapshot.study_block_id,
        "expected_study_generation": snapshot.study_generation,
    }


def reach_break_complete(journey: Journey, *, at: float) -> float:
    """Drive one real break to BREAK_COMPLETE, where RETURN_TO_STUDY is legal.

    The break is spent on a NON-study surface.  Routing the exact intended
    Study resource here would be a factual return, and COSECANT would
    correctly leave BREAK_COMPLETE for RETURN_CONFIRMING before the test ever
    reached the action-allowed state it is trying to exercise.
    """

    journey.route(LECTURE, at)
    journey.coordinator._request_cosecant_break(BREAK_SECONDS)
    journey.route(LECTURE, at + 1.5)
    assert journey.cosecant().state is CosecantState.BREAK_ACTIVE
    complete_at = at + 1.5 + BREAK_SECONDS + 1.0
    journey.route(INSTAGRAM, complete_at)
    assert journey.cosecant().state is CosecantState.BREAK_COMPLETE
    return complete_at


def test_l3_current_break_identity_records_intent(journey_factory):
    """POSITIVE CONTROL: the current break genuinely accepts a return intent."""

    journey = journey_factory()
    start_study(journey)
    reach_break_complete(journey, at=3.0)

    snapshot = journey.cosecant()
    assert CosecantUiAction.RETURN_TO_STUDY in snapshot.allowed_actions
    assert snapshot.final_locked is False

    before = list(journey.fact_kinds)
    send(journey, "cosecant_return_intent", **cosecant_identity(journey))

    assert "RETURN_INTENT_RECORDED" in journey.fact_kinds[len(before):], (
        f"no intent fact was recorded; facts: {journey.fact_kinds[len(before):]}"
    )
    # RETURN INTENT is not RETURN CONFIRMED -- the break must still be running.
    after = journey.cosecant()
    assert after.state is CosecantState.BREAK_COMPLETE
    assert after.return_confirmed is False


def test_l3_stale_break_intent_cannot_write_into_a_newer_break(journey_factory):
    """Break 1's Return click must not record a fact against break 2."""

    journey = journey_factory()
    _started_at, r = reach_final_lock(journey)

    # reach_final_lock staged break 1 in FINAL_LOCK; capture its identity.
    first = journey.cosecant()
    stale = {
        "expected_break_id": first.break_id,
        "expected_cosecant_generation": first.generation,
        "expected_study_block_id": first.study_block_id,
        "expected_study_generation": first.study_generation,
    }
    assert stale["expected_break_id"]

    # Confirm the exact return so break 1 genuinely retires.
    for step in (0.0, 1.5, 3.0):
        journey.route(LECTURE, r + step)
    assert journey.cosecant().return_confirmed is True

    # Break 2, genuinely reaching an action-allowed state.
    reach_break_complete(journey, at=r + 10.0)
    active = journey.cosecant()
    assert active.break_id != stale["expected_break_id"]
    assert CosecantUiAction.RETURN_TO_STUDY in active.allowed_actions

    before_facts = list(journey.fact_kinds)
    before_batches = list(journey.batches_accepted)

    send(journey, "cosecant_return_intent", **stale)

    assert journey.fact_kinds == before_facts, (
        "break 1's return intent produced a durable fact during break 2: "
        f"{journey.fact_kinds[len(before_facts):]}"
    )
    assert journey.batches_accepted == before_batches, (
        "a refused return intent reached persistence"
    )
    after = journey.cosecant()
    assert after.break_id == active.break_id
    assert after.state is CosecantState.BREAK_COMPLETE
    assert after.return_confirmed is False


def test_l3_final_locked_intent_is_refused(journey_factory):
    """FINAL_LOCK exposes no return action, so no intent may be recorded."""

    journey = journey_factory()
    reach_final_lock(journey)

    snapshot = journey.cosecant()
    assert snapshot.final_locked is True
    assert CosecantUiAction.RETURN_TO_STUDY not in snapshot.allowed_actions

    before = list(journey.fact_kinds)
    send(journey, "cosecant_return_intent", **cosecant_identity(journey))

    assert journey.fact_kinds == before, (
        "a return intent was recorded while FINAL_LOCK held the break"
    )
    assert journey.cosecant().return_confirmed is False


def test_l3_absent_return_intent_identity_is_rejected(journey_factory):
    """C12-F: an identity-free return intent is refused, not exempted.

    The break-return button is the one presentation control that reaches a
    durable fact, so an identity-free command here wrote real history without
    naming the episode it came from.
    """

    journey = journey_factory()
    start_study(journey)
    reach_break_complete(journey, at=3.0)

    before = list(journey.fact_kinds)
    send_raw(journey, "cosecant_return_intent")

    assert "RETURN_INTENT_RECORDED" not in journey.fact_kinds[len(before):], (
        "an identity-free return intent recorded a durable fact"
    )

    # POSITIVE CONTROL: the same command succeeds once it names its episode.
    send(journey, "cosecant_return_intent")
    assert "RETURN_INTENT_RECORDED" in journey.fact_kinds[len(before):]


# ---------------------------------------------------------------------------
# GROUP L4 — stale snapshot / popup generation ordering
# ---------------------------------------------------------------------------


def test_l4_newer_study_snapshot_is_accepted(app, real_snapshots):
    """POSITIVE CONTROL: a fresh Study snapshot genuinely reaches the view."""

    study, _cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        view.set_study_snapshot(study)
        assert view._state.study is study

        newer = replace(
            study,
            generation=study.generation + 1,
            published_monotonic_ns=study.published_monotonic_ns + 1_000,
        )
        view.set_study_snapshot(newer)
        assert view._state.study is newer
    finally:
        view.close()


def test_l4_older_study_generation_cannot_overwrite(app, real_snapshots):
    """A generation that has already been superseded must not be displayed."""

    study, _cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        current = replace(
            study,
            generation=study.generation + 5,
            published_monotonic_ns=study.published_monotonic_ns + 5_000,
        )
        view.set_study_snapshot(current)
        assert view._state.study is current

        view.set_study_snapshot(study)          # older generation
        assert view._state.study is current, (
            "an older Study generation overwrote a newer displayed one"
        )
    finally:
        view.close()


def test_l4_older_study_publication_within_a_generation_cannot_overwrite(
    app, real_snapshots
):
    """Same generation, earlier publication instant -- reject."""

    study, _cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        newer = replace(
            study, published_monotonic_ns=study.published_monotonic_ns + 5_000
        )
        view.set_study_snapshot(newer)
        view.set_study_snapshot(study)
        assert view._state.study is newer

        # Equal publication is allowed: a redraw is not a regression.
        same = replace(newer)
        view.set_study_snapshot(same)
        assert view._state.study is same
    finally:
        view.close()


def test_l4_newer_cosecant_snapshot_is_accepted(app, real_snapshots):
    """POSITIVE CONTROL: a fresh COSECANT snapshot genuinely reaches the view."""

    _study, cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        view.set_cosecant_snapshot(cosecant)
        assert view._state.cosecant is cosecant

        newer = replace(
            cosecant,
            generation=cosecant.generation + 1,
            break_id=cosecant.break_id + "-2",
            fact_sequence=cosecant.fact_sequence + 1,
        )
        view.set_cosecant_snapshot(newer)
        assert view._state.cosecant is newer
    finally:
        view.close()


def test_l4_older_cosecant_generation_cannot_overwrite(app, real_snapshots):
    """An older COSECANT episode must not replace the current one."""

    _study, cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        current = replace(
            cosecant,
            generation=cosecant.generation + 3,
            break_id=cosecant.break_id + "-current",
            fact_sequence=cosecant.fact_sequence + 9,
        )
        view.set_cosecant_snapshot(current)
        assert view._state.cosecant is current

        view.set_cosecant_snapshot(cosecant)
        assert view._state.cosecant is current, (
            "an older COSECANT generation overwrote a newer displayed one"
        )
    finally:
        view.close()


def test_l4_lower_fact_sequence_in_the_same_generation_cannot_overwrite(
    app, real_snapshots
):
    """Within one episode, a rewound durable sequence is a regression."""

    _study, cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        newer = replace(cosecant, fact_sequence=cosecant.fact_sequence + 4)
        view.set_cosecant_snapshot(newer)
        view.set_cosecant_snapshot(cosecant)
        assert view._state.cosecant is newer

        # Equal sequence within the same episode/state is a legal projection
        # update: countdown and progress move without a new durable fact.
        projection = replace(newer, seconds_to_next_stage=1)
        view.set_cosecant_snapshot(projection)
        assert view._state.cosecant is projection
    finally:
        view.close()


def test_l4_popup_presents_the_current_generation(app, real_snapshots):
    """POSITIVE CONTROL: the popup genuinely presents a required snapshot."""

    _study, cosecant = real_snapshots
    popup = ContinuityPopup()
    try:
        required = replace(
            cosecant,
            state=CosecantState.BREAK_COMPLETE,
            popup_required=True,
            popup_must_remain_open=False,
            final_locked=False,
            allowed_actions=(CosecantUiAction.RETURN_TO_STUDY,),
        )
        popup.present_snapshot(required)
        assert popup._snapshot is required
        assert popup.return_button.isVisible() is True
    finally:
        popup.close()


def test_l4_popup_refuses_an_older_generation(app, real_snapshots):
    """A retired episode's snapshot must not overwrite the current display."""

    _study, cosecant = real_snapshots
    popup = ContinuityPopup()
    try:
        old = replace(
            cosecant,
            state=CosecantState.BREAK_COMPLETE,
            popup_required=True,
            final_locked=False,
            allowed_actions=(CosecantUiAction.RETURN_TO_STUDY,),
        )
        current = replace(
            old,
            generation=old.generation + 2,
            break_id=old.break_id + "-2",
            fact_sequence=old.fact_sequence + 5,
        )
        popup.present_snapshot(current)
        assert popup._snapshot is current

        popup.present_snapshot(old)
        assert popup._snapshot is current, (
            "an older COSECANT generation replaced the presented snapshot"
        )
    finally:
        popup.close()


def test_l4_terminal_generation_cannot_be_visually_reopened(app, real_snapshots):
    """After a confirmed/terminal projection, a stale FINAL_LOCK must not reopen."""

    _study, cosecant = real_snapshots
    popup = ContinuityPopup()
    try:
        locked = replace(
            cosecant,
            state=CosecantState.FINAL_LOCK,
            popup_required=True,
            popup_must_remain_open=True,
            final_locked=True,
            allowed_actions=(),
        )
        popup.present_snapshot(locked)
        assert popup._snapshot is locked

        confirmed = replace(
            locked,
            state=CosecantState.CONFIRMED,
            popup_required=False,
            popup_must_remain_open=False,
            final_locked=False,
            return_confirmed=True,
            fact_sequence=locked.fact_sequence + 1,
        )
        popup.present_snapshot(confirmed)
        assert popup.isVisible() is False

        popup.present_snapshot(locked)          # the retired FINAL_LOCK returns
        assert popup.isVisible() is False, (
            "a stale FINAL_LOCK snapshot reopened a terminal presentation"
        )
        assert popup._snapshot is confirmed
    finally:
        popup.close()


# ---------------------------------------------------------------------------
# GROUP N5 — FINAL_LOCK positive control (regression guard, NOT a repair)
# ---------------------------------------------------------------------------


def test_n5_final_lock_exposes_no_return_button(app, real_snapshots):
    _study, cosecant = real_snapshots
    popup = ContinuityPopup()
    try:
        locked = replace(
            cosecant,
            state=CosecantState.FINAL_LOCK,
            popup_required=True,
            popup_must_remain_open=True,
            final_locked=True,
            allowed_actions=(),
        )
        popup.present_snapshot(locked)
        assert popup.return_button.isVisible() is False
        assert popup.return_button.isEnabled() is False
    finally:
        popup.close()


def test_n5_final_lock_survives_close_and_escape(app, real_snapshots):
    _study, cosecant = real_snapshots
    popup = ContinuityPopup()
    try:
        locked = replace(
            cosecant,
            state=CosecantState.FINAL_LOCK,
            popup_required=True,
            popup_must_remain_open=True,
            final_locked=True,
            allowed_actions=(),
        )
        popup.present_snapshot(locked)
        assert popup.isVisible() is True

        popup.close()
        # close() runs closeEvent synchronously; spinning the loop here would
        # process a queued destruction from an earlier test.
        assert popup.isVisible() is True, "close() dismissed a FINAL_LOCK notice"

        popup.keyPressEvent(
            QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        )

        assert popup.isVisible() is True, "Escape dismissed a FINAL_LOCK notice"
        assert popup._snapshot is locked
    finally:
        popup.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        popup._snapshot = None
        popup.close()


def test_n5_presentation_cannot_manufacture_a_confirmed_return(journey_factory):
    """No presentation action releases the engine.  Only observed return does."""

    journey = journey_factory()
    reach_final_lock(journey)

    before = list(journey.fact_kinds)
    send(journey, "cosecant_return_intent", **cosecant_identity(journey))

    snapshot = journey.cosecant()
    assert snapshot.state is CosecantState.FINAL_LOCK
    assert snapshot.return_confirmed is False
    assert "RETURN_CONFIRMED" not in journey.fact_kinds[len(before):]


# ---------------------------------------------------------------------------
# GROUP T — C11-A factual telemetry rows
# ---------------------------------------------------------------------------


def test_t_telemetry_rows_project_published_cosecant_fields(app, real_snapshots):
    """The new rows must read snapshot fields, never compute a second truth."""

    study, cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        locked = replace(
            cosecant,
            state=CosecantState.FINAL_LOCK,
            final_locked=True,
            selected_break_seconds=600,
            popup_required=False,
        )
        view.set_study_snapshot(study)
        view.set_cosecant_snapshot(locked)

        values = view.telemetry._values
        assert "selected_break" in values
        assert "return_status" in values
        assert "final_lock" in values
        assert values["final_lock"].text() == "YES"
        assert values["selected_break"].text() == "10:00"
    finally:
        view.close()


# ---------------------------------------------------------------------------
# GROUP L5 — engine session presentation epoch
#
# L4's ordering guards are correct WITHIN one Core Engine session.  Each new
# session builds fresh StudyRuntime and CosecantRuntime authorities whose
# generations legitimately restart, so a presentation baseline carried across
# a restart would refuse the new session's genuine truth as stale.
#
# The reset below is an EXPLICIT SESSION BOUNDARY, never an ordering exception:
# every L4 rejection above must remain exactly as strong inside one session.
# ---------------------------------------------------------------------------


def test_l5_a_study_presentation_resets_between_engine_sessions(app, real_snapshots):
    """A new session's lower Study generation must not be refused as stale."""

    study, cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        old_session = replace(
            study,
            generation=study.generation + 7,
            published_monotonic_ns=study.published_monotonic_ns + 7_000,
        )
        view.set_study_snapshot(old_session)
        view.set_cosecant_snapshot(cosecant)
        assert view._state.study is old_session
        assert view._state.cosecant is cosecant

        # The production session-reset presentation contract.
        view.render(None)

        assert view._state.study is None, "stale Study identity survived the reset"
        assert view._state.cosecant is None
        assert view.state_pill.text() == f"STUDY · {StudyState.EMPTY.value}"

        # A genuinely NEW session publishes a LOWER generation.
        new_session = replace(
            study,
            generation=1,
            published_monotonic_ns=study.published_monotonic_ns - 50_000,
        )
        view.set_study_snapshot(new_session)
        assert view._state.study is new_session, (
            "a new engine session's Study snapshot was refused as stale"
        )
    finally:
        view.close()


def test_l5_a_ordering_is_still_strict_inside_one_session(app, real_snapshots):
    """POSITIVE CONTROL: the reset did not weaken L4 within a session."""

    study, _cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        current = replace(
            study,
            generation=study.generation + 7,
            published_monotonic_ns=study.published_monotonic_ns + 7_000,
        )
        view.set_study_snapshot(current)
        view.set_study_snapshot(study)          # older, NO reset in between
        assert view._state.study is current, (
            "L5 weakened same-session Study ordering"
        )
    finally:
        view.close()


def test_l5_b_cosecant_ordering_baseline_resets(app, real_snapshots):
    """A new session's lower COSECANT generation must not be refused."""

    _study, cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        old_session = replace(
            cosecant,
            generation=cosecant.generation + 6,
            break_id=cosecant.break_id + "-old-session",
            fact_sequence=cosecant.fact_sequence + 40,
        )
        view.set_cosecant_snapshot(old_session)
        assert view._state.cosecant is old_session

        view.render(None)
        assert view._state.cosecant is None

        new_session = replace(
            cosecant,
            generation=1,
            break_id=cosecant.break_id + "-new-session",
            fact_sequence=1,
        )
        view.set_cosecant_snapshot(new_session)
        assert view._state.cosecant is new_session, (
            "a new engine session's COSECANT snapshot was refused as stale"
        )
    finally:
        view.close()


def test_l5_b_cosecant_ordering_is_still_strict_inside_one_session(
    app, real_snapshots
):
    """POSITIVE CONTROL: same-session COSECANT ordering is untouched."""

    _study, cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        current = replace(
            cosecant,
            generation=cosecant.generation + 6,
            fact_sequence=cosecant.fact_sequence + 40,
        )
        view.set_cosecant_snapshot(current)
        view.set_cosecant_snapshot(cosecant)    # older, NO reset in between
        assert view._state.cosecant is current, (
            "L5 weakened same-session COSECANT ordering"
        )
    finally:
        view.close()


def test_l5_c_popup_ordering_baseline_resets(app, real_snapshots):
    """The popup's own baseline must clear at a session boundary."""

    _study, cosecant = real_snapshots
    popup = ContinuityPopup()
    try:
        old_session = replace(
            cosecant,
            state=CosecantState.BREAK_COMPLETE,
            generation=cosecant.generation + 6,
            break_id=cosecant.break_id + "-old-session",
            fact_sequence=cosecant.fact_sequence + 40,
            popup_required=True,
            popup_must_remain_open=False,
            final_locked=False,
            allowed_actions=(CosecantUiAction.RETURN_TO_STUDY,),
        )
        popup.present_snapshot(old_session)
        assert popup._snapshot is old_session
        assert popup.isVisible() is True

        popup.reset_presentation_epoch()

        assert popup._snapshot is None, "the popup kept an old session baseline"
        assert popup.isVisible() is False

        new_session = replace(
            old_session,
            generation=1,
            break_id=cosecant.break_id + "-new-session",
            fact_sequence=1,
        )
        popup.present_snapshot(new_session)
        assert popup._snapshot is new_session, (
            "a new engine session's popup snapshot was refused as stale"
        )
        assert popup.isVisible() is True
    finally:
        popup.close()


def test_l5_c_ordinary_snapshot_cannot_reset_the_popup_epoch(app, real_snapshots):
    """POSITIVE CONTROL: only the explicit reset clears the baseline."""

    _study, cosecant = real_snapshots
    popup = ContinuityPopup()
    try:
        current = replace(
            cosecant,
            state=CosecantState.FINAL_LOCK,
            generation=cosecant.generation + 6,
            fact_sequence=cosecant.fact_sequence + 40,
            popup_required=True,
            popup_must_remain_open=True,
            final_locked=True,
            allowed_actions=(),
        )
        popup.present_snapshot(current)

        stale = replace(current, generation=1, fact_sequence=1)
        popup.present_snapshot(stale)
        assert popup._snapshot is current, (
            "an ordinary CosecantSnapshot reset the presentation epoch"
        )
        assert popup.return_button.isVisible() is False
    finally:
        popup._snapshot = None
        popup.close()


def test_l5_d_controller_emits_the_presentation_reset(app):
    """A reset production never calls would be vacuous.

    This drives the REAL ControlStationController, so the assertion is about
    production wiring rather than about the View's own method existing.
    """

    from CONTROL_STATION.controller import ControlStationController

    controller = ControlStationController()
    try:
        received: list[object] = []
        controller.study_view_changed.connect(received.append)

        controller._prepare_new_session()

        assert received, (
            "_prepare_new_session emitted no Study presentation reset"
        )
        assert received[-1] is None, (
            "the session reset must be the None sentinel, not a manufactured "
            f"snapshot: {received[-1]!r}"
        )
    finally:
        controller.deleteLater()


def test_l5_d_reset_sentinel_reaches_the_view(app, real_snapshots):
    """The controller's sentinel and the view's render contract must agree."""

    from CONTROL_STATION.controller import ControlStationController

    study, cosecant = real_snapshots
    controller = ControlStationController()
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        controller.study_view_changed.connect(view.render)
        view.set_study_snapshot(study)
        view.set_cosecant_snapshot(cosecant)
        assert view._state.study is study

        controller._prepare_new_session()

        assert view._state.study is None
        assert view._state.cosecant is None
    finally:
        view.close()
        controller.deleteLater()


def test_l5_e_reset_clears_the_expected_identity_for_a_fresh_prepare(
    app, real_snapshots
):
    """An old session's identity must not deadlock the new session's PREPARE."""

    study, _cosecant = real_snapshots
    view = StudyView(engine=QObject(), lifecycle=QObject(), settings=QObject())
    try:
        # COMPLETED, not PAUSED: PREPARE is correctly disabled while a block is
        # ACTIVE or PAUSED, so a paused fixture would make the control below
        # unclickable and the test vacuous for the wrong reason.
        old_session = replace(
            study,
            state=StudyState.COMPLETED,
            generation=study.generation + 7,
        )
        view.set_study_snapshot(old_session)
        assert view.timer_card.prepare_button.isEnabled()

        # POSITIVE CONTROL: while that session is live the view genuinely
        # emits the old identity, so the assertion after the reset is not
        # trivially true of a view that never carried an identity at all.
        emitted: list[tuple] = []
        view.prepare_requested.connect(
            lambda *args: emitted.append(args)
        )
        view.timer_card.subject_input.setText("Neuroscience")
        view.timer_card.task_input.setText("basal ganglia")
        view.timer_card.prepare_button.click()
        assert emitted, "PREPARE emitted nothing while a session was live"
        assert emitted[-1][4] == old_session.block_id
        assert emitted[-1][5] == old_session.generation

        view.render(None)

        emitted.clear()
        view.timer_card.prepare_button.click()
        assert emitted, "PREPARE emitted nothing after the session reset"
        assert emitted[-1][4] == "", (
            f"a stale block_id survived the reset: {emitted[-1][4]!r}"
        )
        assert emitted[-1][5] == 0, (
            f"a stale generation survived the reset: {emitted[-1][5]!r}"
        )
    finally:
        view.close()


def test_l5_e_fresh_session_prepare_is_admitted_by_the_engine(journey_factory):
    """The empty identity a reset view sends is accepted by a fresh runtime.

    Closes the loop: L5-E's ("", 0) is not merely different from the stale
    identity, it is the identity a never-prepared StudyRuntime actually
    publishes, so Monitor's C11-A guard admits the first PREPARE.
    """

    journey = journey_factory()
    study = journey.services.study.snapshot()
    assert str(study.block_id) == ""
    assert int(study.generation) == 0

    send(
        journey,
        "study_prepare",
        subject=SUBJECT,
        task=TASK,
        planned_seconds=3600,
        expected_study_block_id="",
        expected_study_generation=0,
    )

    prepared = journey.services.study.snapshot()
    assert prepared.state is StudyState.READY, (
        "a fresh-session PREPARE carrying the empty identity was rejected"
    )
    assert prepared.block_id, "StudyRuntime must still mint the new block id"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def journey_factory():
    created: list[Journey] = []

    def make() -> Journey:
        journey = Journey()
        created.append(journey)
        return journey

    yield make


@pytest.fixture(scope="module")
def real_snapshots():
    """One REAL StudySnapshot and one REAL CosecantSnapshot from the engine.

    Captured from a genuine assembled journey rather than hand-built, so every
    ordering test above operates on production-shaped objects.
    """

    journey = Journey()
    start_study(journey)
    journey.route(LECTURE, 3.0)
    journey.coordinator._request_cosecant_break(BREAK_SECONDS)
    journey.route(LECTURE, 4.5)
    assert journey.cosecant().state is CosecantState.BREAK_ACTIVE
    return journey.services.study.snapshot(), journey.cosecant()
