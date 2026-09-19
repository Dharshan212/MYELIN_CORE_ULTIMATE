"""Isolated Phase 2 contract tests; no persistence or live database access."""

from __future__ import annotations

import dataclasses
import unittest
from dataclasses import fields
from pathlib import Path
import sys
import types
from types import SimpleNamespace

# The production SCIENCE_LAB package initializer owns Qt workspace exports.
# These pure-analysis tests deliberately load the package as a namespace so a
# GUI runtime is neither needed nor initialized.
_SCIENCE_LAB_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCIENCE_LAB_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if "SCIENCE_LAB" not in sys.modules:
    _science_lab_package = types.ModuleType("SCIENCE_LAB")
    _science_lab_package.__path__ = [str(_SCIENCE_LAB_DIR)]
    sys.modules["SCIENCE_LAB"] = _science_lab_package

from MIRL.mirl import MirlEvent, MirlEventClass, MirlEventName
from PERSISTENCE.storage import ScienceLabExperimentRecord
from SCIENCE_LAB.analysis import (
    ANALYSIS_UNAVAILABLE,
    AVAILABLE,
    CERTIFIED,
    NO_COMPLETED_EXPERIMENT,
    UNAVAILABLE,
    Chapter3ResultPackage,
    analyze_finalized_session,
)
from SCIENCE_LAB.evidence import (
    CosineSourceEvidence,
    MineSourceEvidence,
    MirlSourceEvidence,
    PersistedFactSourceEvidence,
    ScienceLabEvidenceSnapshot,
    SourceCoverage,
)
from SCIENCE_LAB.handoff import Chapter3ResultHandoff


SESSION_ID = 17
WINDOW_START = 100
WINDOW_END = 2_000
UTC = "2026-09-14T00:00:00Z"


class EpisodeBuilder:
    def __init__(self, episode_id: str, displayed_ns: int) -> None:
        self.episode_id = episode_id
        self.events: list[MirlEvent] = []
        self._sequence = 0
        created = self.add("episode_created", displayed_ns)
        self.add(
            "sine_displayed",
            displayed_ns,
            supports=(created.event_id,),
            sine_stage=1,
        )

    def add(
        self,
        name: str,
        when: int,
        *,
        attempt_id: str = "",
        attempt_index: int = 0,
        supports: tuple[str, ...] = (),
        reason: str = "",
        sine_stage: int = 0,
    ) -> MirlEvent:
        self._sequence += 1
        event_name = MirlEventName(name)
        derived = {
            MirlEventName.RETURN_UNVERIFIED,
            MirlEventName.RETURN_VERIFIED,
            MirlEventName.RELAPSE_DETECTED,
            MirlEventName.EPISODE_RESUMED,
            MirlEventName.EPISODE_CLOSED,
        }
        event = MirlEvent(
            kind=f"MIRL_{name.upper()}",
            event_name=event_name,
            event_class=(
                MirlEventClass.DERIVED if event_name in derived else MirlEventClass.OBSERVED
            ),
            event_id=f"{self.episode_id}-{self._sequence}-{name}",
            episode_id=self.episode_id,
            episode_sequence=self._sequence,
            occurred_monotonic_ns=when,
            occurred_wall_time_utc=UTC,
            session_id=SESSION_ID,
            candidate_uid=f"candidate-{self.episode_id}",
            operational_event_id=self._sequence,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            sine_stage=sine_stage,
            supporting_event_ids=supports,
            reason=reason,
        )
        self.events.append(event)
        return event

    def interrupt_attempt(
        self,
        attempt_id: str,
        attempt_index: int,
        start_ns: int,
        interrupt_ns: int,
    ) -> None:
        started = self.add(
            "return_verification_started",
            start_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
        )
        self.add(
            "return_unverified",
            start_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            supports=(started.event_id,),
        )
        interrupted = self.add(
            "return_verification_interrupted",
            interrupt_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
        )
        self.add(
            "episode_resumed",
            interrupt_ns,
            supports=(interrupted.event_id,),
            reason="verification_interruption",
        )

    def relapsed_attempt(
        self,
        attempt_id: str,
        attempt_index: int,
        start_ns: int,
        verified_ns: int,
        relapse_ns: int,
    ) -> None:
        _started, verified, _closure_started = self.verified_attempt(
            attempt_id, attempt_index, start_ns, verified_ns
        )
        interrupted = self.add(
            "closure_confirmation_interrupted",
            relapse_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
        )
        relapse = self.add(
            "relapse_detected",
            relapse_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            supports=(interrupted.event_id,),
        )
        self.add(
            "episode_resumed",
            relapse_ns,
            supports=(relapse.event_id,),
            reason="closure_interruption",
        )
        self.assert_event_present(verified.event_id)

    def verified_attempt(
        self,
        attempt_id: str,
        attempt_index: int,
        start_ns: int,
        verified_ns: int,
    ) -> tuple[MirlEvent, MirlEvent, MirlEvent]:
        started = self.add(
            "return_verification_started",
            start_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
        )
        self.add(
            "return_unverified",
            start_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            supports=(started.event_id,),
        )
        completed = self.add(
            "return_verification_completed",
            verified_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
        )
        verified = self.add(
            "return_verified",
            verified_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            supports=(completed.event_id,),
        )
        closure_started = self.add(
            "closure_confirmation_started",
            verified_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            supports=(verified.event_id,),
        )
        return started, verified, closure_started

    def close_successfully(
        self,
        attempt_id: str,
        attempt_index: int,
        start_ns: int,
        verified_ns: int,
        closed_ns: int,
    ) -> tuple[MirlEvent, MirlEvent, MirlEvent]:
        started, verified, _closure_started = self.verified_attempt(
            attempt_id, attempt_index, start_ns, verified_ns
        )
        completed = self.add(
            "closure_confirmation_completed",
            closed_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
        )
        closed = self.add(
            "episode_closed",
            closed_ns,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            supports=(completed.event_id,),
            reason="RETURNED",
        )
        return started, verified, closed

    def assert_event_present(self, event_id: str) -> None:
        if not any(event.event_id == event_id for event in self.events):
            raise AssertionError("test fixture lost an event")


def successful_episode(
    episode_id: str,
    displayed_ns: int,
    return_started_ns: int,
    return_verified_ns: int,
    episode_closed_ns: int,
) -> EpisodeBuilder:
    builder = EpisodeBuilder(episode_id, displayed_ns)
    builder.close_successfully(
        f"attempt-{episode_id}",
        1,
        return_started_ns,
        return_verified_ns,
        episode_closed_ns,
    )
    return builder


def _live_mirl_rows(events: tuple[MirlEvent, ...]) -> tuple:
    """Fabricate one live-MIRL projection row per distinct episode_id in
    ``events`` -- these isolated tests exercise return-onset extrema
    computation, not display-code resolution, so a deterministic per-
    episode code is enough to let ``_resolve_sine_mirl_display_codes``
    resolve without guessing."""

    episode_ids = sorted({str(getattr(event, "episode_id", "")) for event in events if getattr(event, "episode_id", "")})
    return tuple(
        SimpleNamespace(
            episode_id=episode_id,
            short_display_id=f"EPI-14092026-{index + 1:02d}",
            candidate_uid=f"candidate-{episode_id}",
            started_at=UTC,
            session_id=SESSION_ID,
        )
        for index, episode_id in enumerate(episode_ids)
    )


def snapshot(events: tuple[MirlEvent, ...]) -> ScienceLabEvidenceSnapshot:
    empty_fact = PersistedFactSourceEvidence(SESSION_ID, ())
    empty_mine = MineSourceEvidence(SESSION_ID, ())
    empty_cosine = CosineSourceEvidence(SESSION_ID, ())
    mirl_status = AVAILABLE if events else "NO_EVIDENCE"
    coverage = (
        SourceCoverage("SINE", "NO_EVIDENCE", "", 0),
        SourceCoverage("NORMAL_BREAK", "NO_EVIDENCE", "", 0),
        SourceCoverage("MINE", "NO_EVIDENCE", "", 0),
        SourceCoverage("COSINE", "NO_EVIDENCE", "", 0),
        SourceCoverage("MIRL", mirl_status, "", len(events)),
        SourceCoverage("STUDY", "NO_EVIDENCE", "", 0),
        SourceCoverage("COSECANT", "NO_EVIDENCE", "", 0),
        SourceCoverage("RESOURCE_INTENT", UNAVAILABLE, "no_durable_event_identity", None),
    )
    return ScienceLabEvidenceSnapshot(
        parent_session_id=SESSION_ID,
        generated_at_utc=UTC,
        source_coverage=coverage,
        sine=empty_fact,
        normal_break=empty_fact,
        mine=empty_mine,
        cosine=empty_cosine,
        mirl=MirlSourceEvidence(SESSION_ID, events, live_mirl_rows=_live_mirl_rows(events)),
        study=empty_fact,
        cosecant=empty_fact,
        resource_intent=None,
        limitations=(),
    )


def experiment(status: str, *, start: int = WINDOW_START, end: int = WINDOW_END):
    completed = status == "COMPLETED"
    return ScienceLabExperimentRecord(
        experiment_id=f"experiment-{status.lower()}",
        parent_session_id=SESSION_ID,
        date_key="14092026",
        daily_sequence=1,
        status=status,
        started_at_utc=UTC,
        started_monotonic_ns=start,
        ended_at_utc=UTC if completed else None,
        ended_monotonic_ns=end if completed else None,
        end_reason="USER_END" if completed else "",
        runtime_instance_id="isolated-test",
        created_at_utc=UTC,
        updated_at_utc=UTC,
    )


def analyze(events: tuple[MirlEvent, ...], *, status: str = "COMPLETED"):
    finalized = SimpleNamespace(
        parent_session_id=SESSION_ID,
        evidence_snapshot=snapshot(events),
        finalized_at_utc=UTC,
    )
    return analyze_finalized_session(
        finalized=finalized,
        experiments=(experiment(status),),
    )


def extrema(outcome):
    if outcome.package is None:
        raise AssertionError(outcome.reason)
    result = outcome.package.successful_return_onset_latency_extrema
    if result is None:
        raise AssertionError("return-onset extrema missing")
    return result


class Phase2BestWorstReturnTests(unittest.TestCase):
    def test_zero_samples_and_only_completed_experiments_are_analyzed(self) -> None:
        completed = analyze(())
        self.assertEqual(completed.status, CERTIFIED)
        result = extrema(completed)
        self.assertEqual(result.eligible_sample_count, 0)
        self.assertEqual(result.best_successful_return_onset_latency.status, UNAVAILABLE)
        self.assertEqual(result.worst_successful_return_onset_latency.status, UNAVAILABLE)
        self.assertIsNone(result.best_successful_return_onset_latency.value)

        self.assertEqual(analyze((), status="RUNNING").status, NO_COMPLETED_EXPERIMENT)
        self.assertEqual(
            analyze((), status="INTERRUPTED").status,
            NO_COMPLETED_EXPERIMENT,
        )

    def test_one_sample_uses_return_onset_and_requires_later_proof(self) -> None:
        episode = successful_episode("one", 150, 300, 410, 800)
        outcome = analyze(tuple(episode.events))
        result = extrema(outcome)
        self.assertEqual(result.eligible_sample_count, 1)
        self.assertEqual(result.best_successful_return_onset_latency.value, 150)
        self.assertEqual(result.worst_successful_return_onset_latency.value, 150)
        sample = result.samples[0]
        self.assertEqual(sample.successful_return_onset.event_kind, "return_verification_started")
        self.assertEqual(sample.return_verified.event_kind, "return_verified")
        self.assertEqual(sample.episode_closed.event_kind, "episode_closed")
        self.assertNotEqual(sample.latency_ns, 410 - 150)
        self.assertNotEqual(sample.latency_ns, 800 - 150)

        old = next(metric for metric in outcome.package.key_metrics if metric.code == "return_latency")
        self.assertEqual(old.status, UNAVAILABLE)
        self.assertEqual(old.samples[0].value, 410 - 150)

    def test_multiple_samples_compute_minimum_and_maximum(self) -> None:
        episodes = (
            successful_episode("multi-a", 150, 250, 300, 500),
            successful_episode("multi-b", 400, 750, 800, 1_000),
            successful_episode("multi-c", 1_050, 1_250, 1_300, 1_600),
        )
        result = extrema(analyze(tuple(event for item in episodes for event in item.events)))
        self.assertEqual(result.eligible_sample_count, 3)
        self.assertEqual(result.best_successful_return_onset_latency.value, 100)
        self.assertEqual(result.worst_successful_return_onset_latency.value, 350)

    def test_best_and_worst_ties_retain_every_supporting_episode(self) -> None:
        episodes = (
            successful_episode("tie-best-a", 120, 220, 260, 350),
            successful_episode("tie-best-b", 400, 500, 540, 650),
            successful_episode("tie-worst-a", 700, 1_000, 1_040, 1_150),
            successful_episode("tie-worst-b", 1_200, 1_500, 1_540, 1_700),
        )
        result = extrema(analyze(tuple(event for item in episodes for event in item.events)))
        best_ids = {ref.durable_id for ref in result.best_successful_return_onset_latency.provenance}
        worst_ids = {ref.durable_id for ref in result.worst_successful_return_onset_latency.provenance}
        self.assertTrue(any(event_id.startswith("tie-best-a-") for event_id in best_ids))
        self.assertTrue(any(event_id.startswith("tie-best-b-") for event_id in best_ids))
        self.assertTrue(any(event_id.startswith("tie-worst-a-") for event_id in worst_ids))
        self.assertTrue(any(event_id.startswith("tie-worst-b-") for event_id in worst_ids))

    def test_failed_attempt_then_success_uses_only_successful_attempt(self) -> None:
        episode = EpisodeBuilder("retry", 150)
        episode.interrupt_attempt("attempt-retry-a", 1, 220, 260)
        episode.close_successfully("attempt-retry-b", 2, 500, 620, 900)
        result = extrema(analyze(tuple(episode.events)))
        self.assertEqual(result.eligible_sample_count, 1)
        self.assertEqual(result.samples[0].attempt_id, "attempt-retry-b")
        self.assertEqual(result.samples[0].latency_ns, 350)

    def test_verified_relapse_then_closure_emits_one_final_attempt_sample(self) -> None:
        episode = EpisodeBuilder("relapse", 150)
        episode.relapsed_attempt("attempt-relapse-a", 1, 220, 320, 450)
        episode.close_successfully("attempt-relapse-b", 2, 700, 820, 1_200)
        result = extrema(analyze(tuple(episode.events)))
        self.assertEqual(result.eligible_sample_count, 1)
        self.assertEqual(result.samples[0].attempt_id, "attempt-relapse-b")
        self.assertEqual(result.samples[0].latency_ns, 550)

    def test_any_required_anchor_outside_experiment_excludes_episode(self) -> None:
        cases = {
            "opening_display": successful_episode("outside-display", 90, 200, 300, 500),
            "return_started": successful_episode("outside-start", 150, 2_000, 2_050, 2_100),
            "return_verified": successful_episode("outside-verified", 150, 200, 2_000, 2_100),
            "episode_closed": successful_episode("outside-close", 150, 200, 300, 2_000),
        }
        for label, episode in cases.items():
            with self.subTest(label=label):
                result = extrema(analyze(tuple(episode.events)))
                self.assertEqual(result.eligible_sample_count, 0)
                self.assertEqual(result.best_successful_return_onset_latency.status, UNAVAILABLE)

    def test_interrupted_and_never_closed_attempts_never_become_samples(self) -> None:
        interrupted = EpisodeBuilder("interrupted", 150)
        interrupted.interrupt_attempt("attempt-interrupted", 1, 250, 300)
        open_episode = EpisodeBuilder("open", 500)
        open_episode.verified_attempt("attempt-open", 1, 600, 700)
        events = tuple((*interrupted.events, *open_episode.events))
        result = extrema(analyze(events))
        self.assertEqual(result.eligible_sample_count, 0)

    def test_evidence_gap_final_attempt_fails_closed_and_aborted_episode_is_excluded(self) -> None:
        gap = EpisodeBuilder("gap", 150)
        _started, _verified, _closure_started = gap.verified_attempt(
            "attempt-gap", 1, 250, 350
        )
        gap.add(
            "evidence_gap",
            400,
            attempt_id="attempt-gap",
            attempt_index=1,
        )
        closure_completed = gap.add(
            "closure_confirmation_completed",
            600,
            attempt_id="attempt-gap",
            attempt_index=1,
        )
        gap.add(
            "episode_closed",
            600,
            attempt_id="attempt-gap",
            attempt_index=1,
            supports=(closure_completed.event_id,),
            reason="RETURNED",
        )
        self.assertEqual(analyze(tuple(gap.events)).status, ANALYSIS_UNAVAILABLE)

        aborted = EpisodeBuilder("aborted", 700)
        aborted.add("episode_closed", 800, reason="ABORTED")
        result = extrema(analyze(tuple(aborted.events)))
        self.assertEqual(result.eligible_sample_count, 0)

    def test_broken_success_support_chain_fails_closed(self) -> None:
        episode = successful_episode("broken", 150, 250, 350, 600)
        closed = episode.events[-1]
        episode.events[-1] = MirlEvent(
            **{
                field.name: (
                    ("missing-closure-completion",)
                    if field.name == "supporting_event_ids"
                    else getattr(closed, field.name)
                )
                for field in fields(MirlEvent)
            }
        )
        outcome = analyze(tuple(episode.events))
        self.assertEqual(outcome.status, ANALYSIS_UNAVAILABLE)
        self.assertIsNone(outcome.package)

    def test_package_field_is_optional_for_older_constructor_contracts(self) -> None:
        # Phase 2 appended six further optional report-projection fields
        # after this one (sine_stage_rows, mine_episode_rows,
        # cosine_episode_rows, cosecant_break_rows, mine_experiment_scope,
        # cosine_experiment_scope) -- so this field is no longer necessarily
        # last.  What must still hold for an older positional-unaware
        # caller: this field keeps its name/None default, and every field
        # after it (whatever gets added later) also has a default, so
        # nothing required was ever inserted into that optional tail.
        all_fields = fields(Chapter3ResultPackage)
        by_name = {field.name: field for field in all_fields}
        extrema_field = by_name["successful_return_onset_latency_extrema"]
        self.assertIsNone(extrema_field.default)
        extrema_index = all_fields.index(extrema_field)
        for field in all_fields[extrema_index:]:
            has_default = field.default is not dataclasses.MISSING or field.default_factory is not dataclasses.MISSING
            self.assertTrue(has_default, f"{field.name} must remain optional")

    def test_phase2_report_projection_fields_default_to_empty(self) -> None:
        by_name = {field.name: field for field in fields(Chapter3ResultPackage)}
        for name in (
            "sine_stage_rows",
            "mine_episode_rows",
            "cosine_episode_rows",
            "cosecant_break_rows",
        ):
            self.assertEqual(by_name[name].default, ())

    def test_existing_handoff_transports_the_complete_extended_package(self) -> None:
        episode = successful_episode("handoff", 150, 300, 410, 800)
        outcome = analyze(tuple(episode.events))
        authority = Chapter3ResultHandoff()
        receipt = authority.transfer(outcome)
        self.assertIs(receipt.package, outcome.package)
        self.assertEqual(
            receipt.package.successful_return_onset_latency_extrema.eligible_sample_count,
            1,
        )


if __name__ == "__main__":
    unittest.main()
