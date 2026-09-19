"""Phase 2 typed report-projection tests: isolated, no persistence or live
database access.  Covers SINE stage rows, COSECANT break/escalation rows and
the locked post-break latency definition, and -- most importantly -- proves
MINE/COSINE experiment-window scoping cannot leak a whole-session episode
into a different, non-overlapping experiment's report.
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_SCIENCE_LAB_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCIENCE_LAB_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if "SCIENCE_LAB" not in sys.modules:
    _science_lab_package = types.ModuleType("SCIENCE_LAB")
    _science_lab_package.__path__ = [str(_SCIENCE_LAB_DIR)]
    sys.modules["SCIENCE_LAB"] = _science_lab_package

from PERSISTENCE.storage import ScienceLabExperimentRecord, ScienceLabSourceRecord
from SCIENCE_LAB.analysis import (
    AVAILABLE,
    CERTIFIED,
    CROSS_BOUNDARY_OVERLAP,
    FULLY_CONTAINED,
    NOT_APPLICABLE,
    OUTSIDE_WINDOW,
    UNAVAILABLE,
    Chapter3ResultPackage,
    analyze_finalized_session,
)
from dataclasses import fields
from SCIENCE_LAB.evidence import (
    CosineSourceEvidence,
    MineSourceEvidence,
    MirlSourceEvidence,
    PersistedFactSourceEvidence,
    ScienceLabEvidenceSnapshot,
    SourceCoverage,
)

SESSION_ID = 42
WINDOW_START = 1_000_000_000
WINDOW_END = 5_000_000_000
UTC = "2026-09-15T00:00:00Z"

_NO_EVIDENCE = ("SINE", "NORMAL_BREAK", "MINE", "COSINE", "MIRL", "STUDY", "COSECANT")


def _record(*, source: str, kind: str, ns: int, payload: dict, event_id: str = "") -> ScienceLabSourceRecord:
    return ScienceLabSourceRecord(
        source_system=source,
        source_event_id=event_id or f"{source.lower()}:{kind}:{ns}",
        session_id=SESSION_ID,
        kind=kind,
        occurred_monotonic_ns=ns,
        payload_json=json.dumps(payload),
        created_at_utc=UTC,
    )


def _experiment(*, start: int = WINDOW_START, end: int = WINDOW_END) -> ScienceLabExperimentRecord:
    return ScienceLabExperimentRecord(
        experiment_id="experiment-completed",
        parent_session_id=SESSION_ID,
        date_key="15092026",
        daily_sequence=1,
        status="COMPLETED",
        started_at_utc=UTC,
        started_monotonic_ns=start,
        ended_at_utc=UTC,
        ended_monotonic_ns=end,
        end_reason="USER_END",
        runtime_instance_id="isolated-test",
        created_at_utc=UTC,
        updated_at_utc=UTC,
    )


def _snapshot(**overrides) -> ScienceLabEvidenceSnapshot:
    coverage_overrides = overrides.pop("_coverage", {})
    empty_fact = PersistedFactSourceEvidence(SESSION_ID, ())
    empty_mine = MineSourceEvidence(SESSION_ID, ())
    empty_cosine = CosineSourceEvidence(SESSION_ID, ())
    empty_mirl = MirlSourceEvidence(SESSION_ID, ())
    sources = {
        "sine": empty_fact,
        "normal_break": empty_fact,
        "mine": empty_mine,
        "cosine": empty_cosine,
        "mirl": empty_mirl,
        "study": empty_fact,
        "cosecant": empty_fact,
    }
    sources.update(overrides)
    coverage_status = {name: "NO_EVIDENCE" for name in _NO_EVIDENCE}
    coverage_status.update(coverage_overrides)

    def _population(name: str) -> tuple:
        evidence = sources[name.lower()]
        if name == "MIRL":
            return getattr(evidence, "events", ())
        if name in {"MINE", "COSINE"}:
            return getattr(evidence, "episodes", ())
        return getattr(evidence, "records", ())

    coverage = tuple(
        SourceCoverage(name, coverage_status.get(name, "NO_EVIDENCE"), "", len(_population(name)))
        for name in _NO_EVIDENCE
    ) + (SourceCoverage("RESOURCE_INTENT", UNAVAILABLE, "no_durable_event_identity", None),)
    return ScienceLabEvidenceSnapshot(
        parent_session_id=SESSION_ID,
        generated_at_utc=UTC,
        source_coverage=coverage,
        sine=sources["sine"],
        normal_break=sources["normal_break"],
        mine=sources["mine"],
        cosine=sources["cosine"],
        mirl=sources["mirl"],
        study=sources["study"],
        cosecant=sources["cosecant"],
        resource_intent=None,
        limitations=(),
    )


def _analyze(snapshot: ScienceLabEvidenceSnapshot, *, start: int = WINDOW_START, end: int = WINDOW_END):
    finalized = SimpleNamespace(
        parent_session_id=SESSION_ID,
        evidence_snapshot=snapshot,
        finalized_at_utc=UTC,
    )
    return analyze_finalized_session(
        finalized=finalized,
        experiments=(_experiment(start=start, end=end),),
    )


class SineStageRowTests(unittest.TestCase):
    def test_stage_and_response_are_read_from_durable_payload(self) -> None:
        records = (
            _record(
                source="SINE", kind="SINE_DISPLAYED", ns=WINDOW_START + 100,
                payload={
                    "episode_uid": "ep-1", "stage": 1, "popup_request_id": "popup-a",
                    "response": "", "resource_key": "", "occurred_wall_time_utc": UTC,
                    "candidate_uid": "candidate-ep-1",
                },
            ),
            _record(
                source="SINE", kind="SINE_RESPONSE_RECORDED", ns=WINDOW_START + 200,
                payload={
                    "episode_uid": "ep-1", "stage": 1, "popup_request_id": "popup-a",
                    "response": "RETURN_TO_FOCUS", "resource_key": "",
                },
            ),
            _record(
                source="SINE", kind="SINE_DISPLAYED", ns=WINDOW_START + 300,
                payload={
                    "episode_uid": "ep-1", "stage": 2, "popup_request_id": "popup-b",
                    "response": "", "resource_key": "res-1", "occurred_wall_time_utc": UTC,
                },
            ),
        )
        snap = _snapshot(
            sine=PersistedFactSourceEvidence(SESSION_ID, records),
            mirl=MirlSourceEvidence(
                SESSION_ID,
                (
                    SimpleNamespace(
                        session_id=SESSION_ID, event_id="mirl-evt-1",
                        occurred_monotonic_ns=WINDOW_START, event_name="episode_created",
                    ),
                ),
                live_mirl_rows=(
                    SimpleNamespace(
                        episode_id="mirl-episode-1", short_display_id="EPI-15092026-01",
                        candidate_uid="candidate-ep-1", started_at=UTC, session_id=SESSION_ID,
                    ),
                ),
            ),
            _coverage={"SINE": AVAILABLE, "MIRL": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.status, CERTIFIED)
        rows = {row.stage: row for row in outcome.package.sine_stage_rows}
        self.assertEqual(rows[1].episode_id, "ep-1")
        self.assertEqual(rows[1].popup_request_id, "popup-a")
        self.assertEqual(rows[1].response, "RETURN_TO_FOCUS")
        self.assertEqual(rows[1].display_monotonic_ns, WINDOW_START + 100)
        self.assertEqual(rows[2].response, "")
        self.assertEqual(rows[2].resource_key, "res-1")

    def test_response_without_its_display_in_window_is_excluded_not_fabricated(self) -> None:
        records = (
            _record(
                source="SINE", kind="SINE_DISPLAYED", ns=WINDOW_START - 500,
                payload={
                    "episode_uid": "ep-2", "stage": 1, "popup_request_id": "popup-c",
                    "response": "", "resource_key": "",
                },
            ),
            _record(
                source="SINE", kind="SINE_RESPONSE_RECORDED", ns=WINDOW_START + 100,
                payload={
                    "episode_uid": "ep-2", "stage": 1, "popup_request_id": "popup-c",
                    "response": "CONTINUE_SINE",
                },
            ),
        )
        snap = _snapshot(
            sine=PersistedFactSourceEvidence(SESSION_ID, records),
            _coverage={"SINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.sine_stage_rows, ())

    def test_a_retried_display_of_the_same_stage_is_two_rows_not_one(self) -> None:
        # SINE/sine.py:_request_stage proves the same (episode_uid, stage)
        # can be factually displayed twice (display-failure/surface-lost
        # retry) with two different popup_request_ids.  Both must survive
        # as distinct rows -- the second must never overwrite the first.
        records = (
            _record(
                source="SINE", kind="SINE_DISPLAYED", ns=WINDOW_START + 100,
                payload={
                    "episode_uid": "ep-3", "stage": 1, "popup_request_id": "popup-first",
                    "response": "", "resource_key": "", "occurred_wall_time_utc": UTC,
                    "candidate_uid": "candidate-ep-3",
                },
            ),
            _record(
                source="SINE", kind="SINE_DISPLAYED", ns=WINDOW_START + 400,
                payload={
                    "episode_uid": "ep-3", "stage": 1, "popup_request_id": "popup-retry",
                    "response": "", "resource_key": "",
                },
            ),
            _record(
                source="SINE", kind="SINE_RESPONSE_RECORDED", ns=WINDOW_START + 450,
                payload={
                    "episode_uid": "ep-3", "stage": 1, "popup_request_id": "popup-retry",
                    "response": "REQUEST_BREAK",
                },
            ),
        )
        snap = _snapshot(
            sine=PersistedFactSourceEvidence(SESSION_ID, records),
            mirl=MirlSourceEvidence(
                SESSION_ID,
                (
                    SimpleNamespace(
                        session_id=SESSION_ID, event_id="mirl-evt-3",
                        occurred_monotonic_ns=WINDOW_START, event_name="episode_created",
                    ),
                ),
                live_mirl_rows=(
                    SimpleNamespace(
                        episode_id="mirl-episode-3", short_display_id="EPI-15092026-01",
                        candidate_uid="candidate-ep-3", started_at=UTC, session_id=SESSION_ID,
                    ),
                ),
            ),
            _coverage={"SINE": AVAILABLE, "MIRL": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.status, CERTIFIED)
        rows = outcome.package.sine_stage_rows
        self.assertEqual(len(rows), 2)
        by_popup = {row.popup_request_id: row for row in rows}
        self.assertEqual(by_popup["popup-first"].response, "")
        self.assertEqual(by_popup["popup-retry"].response, "REQUEST_BREAK")
        self.assertEqual({row.stage for row in rows}, {1})
        self.assertEqual({row.episode_id for row in rows}, {"ep-3"})


class CosecantBreakRowTests(unittest.TestCase):
    def _cosecant_records(self, break_id: str, kinds_ns: dict[str, int]) -> tuple[ScienceLabSourceRecord, ...]:
        return tuple(
            _record(
                source="COSECANT", kind=kind, ns=ns,
                payload={"break_id": break_id, "effective_monotonic_ns": ns},
            )
            for kind, ns in kinds_ns.items()
        )

    def test_locked_latency_definition_break_complete_to_return_confirmed(self) -> None:
        records = self._cosecant_records(
            "break-1",
            {
                "BREAK_STARTED": WINDOW_START + 100,
                "BREAK_COMPLETE": WINDOW_START + 200,
                "BREAK_ALREADY_OVER": WINDOW_START + 500,
                "FINAL_LOCKED": WINDOW_START + 800,
                "RETURN_CONFIRMED": WINDOW_START + 1_000,
            },
        )
        snap = _snapshot(
            cosecant=PersistedFactSourceEvidence(SESSION_ID, records),
            _coverage={"COSECANT": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.status, CERTIFIED)
        row = outcome.package.cosecant_break_rows[0]
        self.assertEqual(row.break_id, "break-1")
        self.assertEqual(row.post_break_return_latency_status, AVAILABLE)
        self.assertEqual(row.post_break_return_latency_ns, 800)  # 1000 - 200
        self.assertEqual(row.break_already_over_monotonic_ns, WINDOW_START + 500)
        self.assertEqual(row.final_locked_monotonic_ns, WINDOW_START + 800)

    def test_returning_before_break_completion_is_not_applicable_never_zero_or_negative(self) -> None:
        records = self._cosecant_records(
            "break-2",
            {
                "BREAK_STARTED": WINDOW_START + 100,
                "RETURN_CONFIRMED": WINDOW_START + 150,
                # No BREAK_COMPLETE fact at all -- user returned early.
            },
        )
        snap = _snapshot(
            cosecant=PersistedFactSourceEvidence(SESSION_ID, records),
            _coverage={"COSECANT": AVAILABLE},
        )
        outcome = _analyze(snap)
        row = outcome.package.cosecant_break_rows[0]
        self.assertEqual(row.post_break_return_latency_status, NOT_APPLICABLE)
        self.assertIsNone(row.post_break_return_latency_ns)
        self.assertEqual(row.post_break_return_latency_reason, "returned before break completion")

    def test_no_certified_return_confirmed_is_unavailable_not_zero(self) -> None:
        records = self._cosecant_records(
            "break-3",
            {"BREAK_STARTED": WINDOW_START + 100, "BREAK_COMPLETE": WINDOW_START + 200},
        )
        snap = _snapshot(
            cosecant=PersistedFactSourceEvidence(SESSION_ID, records),
            _coverage={"COSECANT": AVAILABLE},
        )
        outcome = _analyze(snap)
        row = outcome.package.cosecant_break_rows[0]
        self.assertEqual(row.post_break_return_latency_status, UNAVAILABLE)
        self.assertIsNone(row.post_break_return_latency_ns)


def _mine_episode(episode_id: str, **overrides):
    base = dict(
        session_id=SESSION_ID,
        mine_episode_id=episode_id,
        display_episode_id=f"MINE-15092026-{episode_id}",
        is_closed=True,
        branch="IT_S_IMPORTANT",
        important_duration_minutes=10,
        closure_outcome="RETURNED",
        closure_reason="",
        return_verified=True,
        started_at_utc=UTC,
        ended_at_utc=UTC,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _mine_raw_events(episode_id: str, *timestamps: int):
    return tuple(
        SimpleNamespace(
            mine_episode_id=episode_id,
            monotonic_ns=ns,
            event_id=f"mine-evt-{episode_id}-{ns}",
            event_name="MESSAGING_PLATFORM_ENTERED",
        )
        for ns in timestamps
    )


def _cosine_episode(cosine_session_id: str, generation: int, **overrides):
    base = dict(
        parent_session_id=SESSION_ID,
        cosine_session_id=cosine_session_id,
        generation=generation,
        is_closed=True,
        starting_platform_key="netflix",
        starting_platform_label="Netflix",
        user_choice="BREAK",
        chosen_break_minutes=25,
        hopper_count=0,
        closure_outcome="RETURNED",
        closure_reason="",
        started_at_utc=UTC,
        ended_at_utc=UTC,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _cosine_source_evidence(episodes, raw_events=()) -> CosineSourceEvidence:
    """Official display codes are normally resolved from COSINE's own live,
    cross-session ``episode_display_ids()`` (see evidence.py); these
    isolated tests fabricate a deterministic per-episode code directly
    since they exercise experiment-window scoping, not code resolution."""

    display_ids = tuple(
        (episode.cosine_session_id, episode.generation, f"COS-15092026-{index + 1:02d}")
        for index, episode in enumerate(episodes)
    )
    return CosineSourceEvidence(SESSION_ID, tuple(episodes), raw_events, display_ids)


def _cosine_raw_events(cosine_session_id: str, generation: int, *timestamps: int):
    return tuple(
        SimpleNamespace(
            cosine_session_id=cosine_session_id,
            generation=generation,
            monotonic_ns=ns,
            event_id=f"cosine-evt-{cosine_session_id}-{generation}-{ns}",
            event_name="HOPPER_TRANSITION",
        )
        for ns in timestamps
    )


class MineCosineExperimentScopingTests(unittest.TestCase):
    """The exact contamination scenario Chief specified: a MINE/COSINE
    episode that belongs to a DIFFERENT experiment inside the same parent
    session must never appear in this experiment's typed rows -- and the
    five deterministic boundary states Chief required for both organs."""

    _mine_episode = staticmethod(_mine_episode)
    _mine_raw_events = staticmethod(_mine_raw_events)
    _cosine_episode = staticmethod(_cosine_episode)
    _cosine_raw_events = staticmethod(_cosine_raw_events)

    def test_episode_fully_inside_window_is_included(self) -> None:
        episode = self._mine_episode("ep-in")
        raw = self._mine_raw_events("ep-in", WINDOW_START + 100, WINDOW_START + 200)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (episode,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(len(outcome.package.mine_episode_rows), 1)
        self.assertEqual(outcome.package.mine_episode_rows[0].episode_id, "ep-in")
        scope = outcome.package.mine_experiment_scope
        self.assertEqual(scope.status, FULLY_CONTAINED)
        self.assertEqual((scope.fully_contained_count, scope.cross_boundary_overlap_count, scope.outside_window_count), (1, 0, 0))

    def test_episode_belonging_to_an_earlier_different_experiment_is_excluded(self) -> None:
        # This is Chief's exact Experiment A / Experiment B scenario: the
        # episode is real, closed, and belongs to this parent session --
        # but its factual monotonic span sits entirely before this
        # experiment's own window, so it must not contaminate this report.
        episode = self._mine_episode("ep-other-experiment")
        raw = self._mine_raw_events(
            "ep-other-experiment", WINDOW_START - 900, WINDOW_START - 800
        )
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (episode,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.mine_episode_rows, ())
        self.assertEqual(outcome.package.mine_experiment_scope.status, OUTSIDE_WINDOW)

    def test_whole_session_count_no_longer_implies_experiment_membership(self) -> None:
        # Regression guard for the exact bug Chief's ruling rejected: a
        # non-zero whole-session MINE count must not be read as "this
        # experiment used MINE" when every actual episode sits outside the
        # selected experiment's window.
        episode = self._mine_episode("ep-outside")
        raw = self._mine_raw_events("ep-outside", WINDOW_START - 900, WINDOW_START - 800)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (episode,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        whole_mine = next(row for row in outcome.package.whole_myelin_summary if row.source == "MINE")
        self.assertEqual(whole_mine.count, 1)  # whole-session count is non-zero
        self.assertEqual(outcome.package.mine_episode_rows, ())  # but this experiment has none
        self.assertEqual(outcome.package.mine_experiment_scope.status, OUTSIDE_WINDOW)

    def test_boundary_starts_before_ends_inside_is_cross_boundary_not_unused(self) -> None:
        episode = self._mine_episode("ep-starts-before")
        raw = self._mine_raw_events("ep-starts-before", WINDOW_START - 50, WINDOW_START + 50)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (episode,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.mine_episode_rows, ())
        scope = outcome.package.mine_experiment_scope
        self.assertEqual(scope.status, CROSS_BOUNDARY_OVERLAP)
        self.assertEqual(scope.cross_boundary_overlap_count, 1)
        self.assertTrue(scope.provenance)
        # Chief's requirement: this must be distinguishable from "not used".
        self.assertNotEqual(scope.status, OUTSIDE_WINDOW)

    def test_boundary_starts_inside_ends_after_is_cross_boundary_not_unused(self) -> None:
        episode = self._mine_episode("ep-starts-inside")
        raw = self._mine_raw_events("ep-starts-inside", WINDOW_END - 50, WINDOW_END + 50)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (episode,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.mine_episode_rows, ())
        self.assertEqual(outcome.package.mine_experiment_scope.status, CROSS_BOUNDARY_OVERLAP)

    def test_boundary_spans_the_entire_experiment_is_cross_boundary(self) -> None:
        episode = self._mine_episode("ep-spans-all")
        raw = self._mine_raw_events("ep-spans-all", WINDOW_START - 500, WINDOW_END + 500)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (episode,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.mine_episode_rows, ())
        self.assertEqual(outcome.package.mine_experiment_scope.status, CROSS_BOUNDARY_OVERLAP)

    def test_boundary_completely_outside_is_outside_window(self) -> None:
        episode = self._mine_episode("ep-far-outside")
        raw = self._mine_raw_events("ep-far-outside", WINDOW_END + 1_000, WINDOW_END + 2_000)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (episode,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.mine_episode_rows, ())
        self.assertEqual(outcome.package.mine_experiment_scope.status, OUTSIDE_WINDOW)

    def test_boundary_completely_inside_is_fully_contained(self) -> None:
        episode = self._mine_episode("ep-well-inside")
        raw = self._mine_raw_events("ep-well-inside", WINDOW_START + 10, WINDOW_END - 10)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (episode,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(len(outcome.package.mine_episode_rows), 1)
        self.assertEqual(outcome.package.mine_experiment_scope.status, FULLY_CONTAINED)

    def test_cosine_episode_from_a_different_experiment_is_excluded(self) -> None:
        episode = self._cosine_episode("cos-1", 1)
        raw = self._cosine_raw_events("cos-1", 1, WINDOW_START - 700, WINDOW_START - 600)
        snap = _snapshot(
            cosine=_cosine_source_evidence((episode,), raw),
            _coverage={"COSINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.cosine_episode_rows, ())
        self.assertEqual(outcome.package.cosine_experiment_scope.status, OUTSIDE_WINDOW)

    def test_cosine_episode_inside_window_is_included_with_organ_fields_intact(self) -> None:
        episode = self._cosine_episode("cos-2", 1)
        raw = self._cosine_raw_events("cos-2", 1, WINDOW_START + 10, WINDOW_START + 20)
        snap = _snapshot(
            cosine=_cosine_source_evidence((episode,), raw),
            _coverage={"COSINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        row = outcome.package.cosine_episode_rows[0]
        self.assertEqual(row.chosen_break_minutes, 25)
        self.assertEqual(row.starting_platform_key, "netflix")
        self.assertEqual(outcome.package.cosine_experiment_scope.status, FULLY_CONTAINED)

    def test_cosine_boundary_starts_before_ends_inside_is_cross_boundary(self) -> None:
        episode = self._cosine_episode("cos-3", 1)
        raw = self._cosine_raw_events("cos-3", 1, WINDOW_START - 30, WINDOW_START + 30)
        snap = _snapshot(
            cosine=_cosine_source_evidence((episode,), raw),
            _coverage={"COSINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.cosine_episode_rows, ())
        scope = outcome.package.cosine_experiment_scope
        self.assertEqual(scope.status, CROSS_BOUNDARY_OVERLAP)
        self.assertTrue(scope.provenance)

    def test_cosine_boundary_starts_inside_ends_after_is_cross_boundary(self) -> None:
        episode = self._cosine_episode("cos-4", 1)
        raw = self._cosine_raw_events("cos-4", 1, WINDOW_END - 30, WINDOW_END + 30)
        snap = _snapshot(
            cosine=_cosine_source_evidence((episode,), raw),
            _coverage={"COSINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.cosine_episode_rows, ())
        self.assertEqual(outcome.package.cosine_experiment_scope.status, CROSS_BOUNDARY_OVERLAP)

    def test_cosine_boundary_spans_the_entire_experiment_is_cross_boundary(self) -> None:
        episode = self._cosine_episode("cos-5", 1)
        raw = self._cosine_raw_events("cos-5", 1, WINDOW_START - 500, WINDOW_END + 500)
        snap = _snapshot(
            cosine=_cosine_source_evidence((episode,), raw),
            _coverage={"COSINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.cosine_episode_rows, ())
        self.assertEqual(outcome.package.cosine_experiment_scope.status, CROSS_BOUNDARY_OVERLAP)

    def test_provenance_traces_to_a_real_durable_event_identity_and_kind(self) -> None:
        # Item 3: EPISODE_OPENED/EPISODE_CLOSED must never appear as if they
        # were durable event kinds -- the EvidenceRef must carry the actual
        # raw event's own event_id/event_name.
        episode = self._mine_episode("ep-provenance")
        raw = self._mine_raw_events("ep-provenance", WINDOW_START + 5, WINDOW_START + 15)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (episode,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        row = outcome.package.mine_episode_rows[0]
        self.assertEqual(len(row.provenance), 2)
        for ref in row.provenance:
            self.assertEqual(ref.source, "MINE")
            self.assertEqual(ref.event_kind, "MESSAGING_PLATFORM_ENTERED")  # real event_name, not a synthetic label
            self.assertIn("mine-evt-ep-provenance-", ref.durable_id)  # real raw event_id
            self.assertIn(ref.occurred_monotonic_ns, (WINDOW_START + 5, WINDOW_START + 15))
            self.assertNotIn("EPISODE_OPENED", (ref.event_kind,))
            self.assertNotIn("EPISODE_CLOSED", (ref.event_kind,))


class MixedEpisodeMembershipTests(unittest.TestCase):
    """Chief's final Phase 2 edge case: a fully-contained episode and a
    cross-boundary episode can exist in the SAME experiment at the same
    time.  The contained one must still produce a row; the cross-boundary
    one must still be disclosed in the scope summary -- neither may make
    the other disappear.  Five combinations, both organs, ten tests."""

    # -- MINE --------------------------------------------------------

    def test_mine_one_contained_plus_one_cross_boundary(self) -> None:
        contained = _mine_episode("ep-a")
        overlapping = _mine_episode("ep-b")
        raw = (
            *_mine_raw_events("ep-a", WINDOW_START + 100, WINDOW_START + 200),
            *_mine_raw_events("ep-b", WINDOW_START + 300, WINDOW_END + 50),
        )
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (contained, overlapping), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        rows = outcome.package.mine_episode_rows
        self.assertEqual({row.episode_id for row in rows}, {"ep-a"})
        scope = outcome.package.mine_experiment_scope
        self.assertEqual(scope.status, FULLY_CONTAINED)
        self.assertEqual(scope.fully_contained_count, 1)
        self.assertEqual(scope.cross_boundary_overlap_count, 1)
        self.assertTrue(scope.provenance, "the excluded overlapping episode must not disappear")
        self.assertIn("1 additional episode(s) crossed the experiment boundary", scope.reason)

    def test_mine_two_contained_plus_one_cross_boundary(self) -> None:
        contained_a = _mine_episode("ep-a")
        contained_c = _mine_episode("ep-c")
        overlapping = _mine_episode("ep-b")
        raw = (
            *_mine_raw_events("ep-a", WINDOW_START + 100, WINDOW_START + 200),
            *_mine_raw_events("ep-c", WINDOW_START + 400, WINDOW_START + 500),
            *_mine_raw_events("ep-b", WINDOW_START - 50, WINDOW_START + 50),
        )
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (contained_a, contained_c, overlapping), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        rows = outcome.package.mine_episode_rows
        self.assertEqual({row.episode_id for row in rows}, {"ep-a", "ep-c"})
        scope = outcome.package.mine_experiment_scope
        self.assertEqual(scope.status, FULLY_CONTAINED)
        self.assertEqual(scope.fully_contained_count, 2)
        self.assertEqual(scope.cross_boundary_overlap_count, 1)
        self.assertTrue(scope.provenance)

    def test_mine_only_cross_boundary_is_unavailable_not_unused(self) -> None:
        overlapping = _mine_episode("ep-b")
        raw = _mine_raw_events("ep-b", WINDOW_START - 50, WINDOW_START + 50)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (overlapping,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.mine_episode_rows, ())
        scope = outcome.package.mine_experiment_scope
        self.assertEqual(scope.status, CROSS_BOUNDARY_OVERLAP)
        self.assertEqual(scope.fully_contained_count, 0)
        self.assertEqual(scope.cross_boundary_overlap_count, 1)
        self.assertTrue(scope.provenance)
        self.assertNotEqual(scope.status, OUTSIDE_WINDOW)

    def test_mine_only_outside_is_outside_window(self) -> None:
        outside = _mine_episode("ep-far")
        raw = _mine_raw_events("ep-far", WINDOW_END + 1_000, WINDOW_END + 2_000)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (outside,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.mine_episode_rows, ())
        scope = outcome.package.mine_experiment_scope
        self.assertEqual(scope.status, OUTSIDE_WINDOW)
        self.assertEqual((scope.fully_contained_count, scope.cross_boundary_overlap_count), (0, 0))

    def test_mine_contained_only(self) -> None:
        contained = _mine_episode("ep-a")
        raw = _mine_raw_events("ep-a", WINDOW_START + 100, WINDOW_START + 200)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (contained,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(len(outcome.package.mine_episode_rows), 1)
        scope = outcome.package.mine_experiment_scope
        self.assertEqual(scope.status, FULLY_CONTAINED)
        self.assertEqual((scope.fully_contained_count, scope.cross_boundary_overlap_count), (1, 0))
        self.assertEqual(scope.provenance, ())  # nothing overlapping to disclose

    # -- COSINE (mirrors MINE exactly) --------------------------------

    def test_cosine_one_contained_plus_one_cross_boundary(self) -> None:
        contained = _cosine_episode("cos-a", 1)
        overlapping = _cosine_episode("cos-b", 1)
        raw = (
            *_cosine_raw_events("cos-a", 1, WINDOW_START + 10, WINDOW_START + 20),
            *_cosine_raw_events("cos-b", 1, WINDOW_START - 10, WINDOW_START + 10),
        )
        snap = _snapshot(
            cosine=_cosine_source_evidence((contained, overlapping), raw),
            _coverage={"COSINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        rows = outcome.package.cosine_episode_rows
        self.assertEqual({row.episode_id for row in rows}, {"cos-a:1"})
        scope = outcome.package.cosine_experiment_scope
        self.assertEqual(scope.status, FULLY_CONTAINED)
        self.assertEqual(scope.fully_contained_count, 1)
        self.assertEqual(scope.cross_boundary_overlap_count, 1)
        self.assertTrue(scope.provenance)

    def test_cosine_two_contained_plus_one_cross_boundary(self) -> None:
        contained_a = _cosine_episode("cos-a", 1)
        contained_c = _cosine_episode("cos-c", 1)
        overlapping = _cosine_episode("cos-b", 1)
        raw = (
            *_cosine_raw_events("cos-a", 1, WINDOW_START + 10, WINDOW_START + 20),
            *_cosine_raw_events("cos-c", 1, WINDOW_START + 30, WINDOW_START + 40),
            *_cosine_raw_events("cos-b", 1, WINDOW_END - 10, WINDOW_END + 10),
        )
        snap = _snapshot(
            cosine=_cosine_source_evidence((contained_a, contained_c, overlapping), raw),
            _coverage={"COSINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        rows = outcome.package.cosine_episode_rows
        self.assertEqual({row.episode_id for row in rows}, {"cos-a:1", "cos-c:1"})
        scope = outcome.package.cosine_experiment_scope
        self.assertEqual(scope.status, FULLY_CONTAINED)
        self.assertEqual(scope.fully_contained_count, 2)
        self.assertEqual(scope.cross_boundary_overlap_count, 1)
        self.assertTrue(scope.provenance)

    def test_cosine_only_cross_boundary_is_unavailable_not_unused(self) -> None:
        overlapping = _cosine_episode("cos-b", 1)
        raw = _cosine_raw_events("cos-b", 1, WINDOW_START - 10, WINDOW_START + 10)
        snap = _snapshot(
            cosine=_cosine_source_evidence((overlapping,), raw),
            _coverage={"COSINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.cosine_episode_rows, ())
        scope = outcome.package.cosine_experiment_scope
        self.assertEqual(scope.status, CROSS_BOUNDARY_OVERLAP)
        self.assertEqual(scope.fully_contained_count, 0)
        self.assertEqual(scope.cross_boundary_overlap_count, 1)
        self.assertTrue(scope.provenance)
        self.assertNotEqual(scope.status, OUTSIDE_WINDOW)

    def test_cosine_only_outside_is_outside_window(self) -> None:
        outside = _cosine_episode("cos-far", 1)
        raw = _cosine_raw_events("cos-far", 1, WINDOW_END + 1_000, WINDOW_END + 2_000)
        snap = _snapshot(
            cosine=_cosine_source_evidence((outside,), raw),
            _coverage={"COSINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.package.cosine_episode_rows, ())
        scope = outcome.package.cosine_experiment_scope
        self.assertEqual(scope.status, OUTSIDE_WINDOW)
        self.assertEqual((scope.fully_contained_count, scope.cross_boundary_overlap_count), (0, 0))

    def test_cosine_contained_only(self) -> None:
        contained = _cosine_episode("cos-a", 1)
        raw = _cosine_raw_events("cos-a", 1, WINDOW_START + 10, WINDOW_START + 20)
        snap = _snapshot(
            cosine=_cosine_source_evidence((contained,), raw),
            _coverage={"COSINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(len(outcome.package.cosine_episode_rows), 1)
        scope = outcome.package.cosine_experiment_scope
        self.assertEqual(scope.status, FULLY_CONTAINED)
        self.assertEqual((scope.fully_contained_count, scope.cross_boundary_overlap_count), (1, 0))
        self.assertEqual(scope.provenance, ())


class AvailabilityPassthroughTests(unittest.TestCase):
    def test_unavailable_and_no_evidence_organs_yield_empty_rows_without_crashing(self) -> None:
        outcome = _analyze(_snapshot())
        self.assertEqual(outcome.status, CERTIFIED)
        self.assertEqual(outcome.package.sine_stage_rows, ())
        self.assertEqual(outcome.package.mine_episode_rows, ())
        self.assertEqual(outcome.package.cosine_episode_rows, ())
        self.assertEqual(outcome.package.cosecant_break_rows, ())
        self.assertEqual(outcome.package.mine_experiment_scope.status, "NO_EVIDENCE")
        self.assertEqual(outcome.package.cosine_experiment_scope.status, "NO_EVIDENCE")


class PackageFieldOrderingTests(unittest.TestCase):
    def test_new_trailing_fields_default_to_empty_or_none(self) -> None:
        by_name = {field.name: field for field in fields(Chapter3ResultPackage)}
        for name in (
            "sine_stage_rows", "mine_episode_rows", "cosine_episode_rows", "cosecant_break_rows",
        ):
            self.assertEqual(by_name[name].default, ())
        for name in ("mine_experiment_scope", "cosine_experiment_scope"):
            self.assertIsNone(by_name[name].default)


if __name__ == "__main__":
    unittest.main()
