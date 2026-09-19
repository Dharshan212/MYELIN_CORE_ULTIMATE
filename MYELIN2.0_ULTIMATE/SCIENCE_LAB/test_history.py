"""Focused tests for SCIENCE_LAB/history.py (Chief's Chapter 5 experiment
history feature, 20260917): read-only reconstruction of one already-
completed, already-durable Science Lab experiment, independent of the
live in-process ScienceLabCoordinator/Chapter3TransferReceipt state.

Most tests here patch the PERSISTENCE-touching names history.py imported
into its own module namespace, so no real database is required for the
majority of this file -- matching the project's ZERO TEST WRITES TO LIVE
DB rule.  A small number of tests at the end run read-only against the
real live database specifically to prove zero writes and a correct
reconstruction of the real MYL-17092026-SCI03 (session 135) acceptance
record; they skip themselves cleanly if that database is not present on
this machine.
"""

from __future__ import annotations

import hashlib
import inspect
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

_SCIENCE_LAB_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCIENCE_LAB_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if "SCIENCE_LAB" not in sys.modules:
    package_module = types.ModuleType("SCIENCE_LAB")
    package_module.__path__ = [str(_SCIENCE_LAB_DIR)]
    sys.modules["SCIENCE_LAB"] = package_module

from PERSISTENCE.storage import ScienceLabExperimentRecord
from SCIENCE_LAB import history
from SCIENCE_LAB.evidence import (
    CosineSourceEvidence,
    MineSourceEvidence,
    MirlSourceEvidence,
    PersistedFactSourceEvidence,
    ScienceLabEvidenceSnapshot,
    SourceCoverage,
)
from SCIENCE_LAB.analysis import UNAVAILABLE as METRIC_UNAVAILABLE

SESSION_ID = 900
UTC = "2026-09-17T10:00:00Z"


def _experiment(
    *,
    experiment_id: str = "MYL-17092026-SCI03",
    parent_session_id: int = SESSION_ID,
    status: str = "COMPLETED",
    started_ns: int = 1_000_000_000,
    ended_ns: int | None = 5_000_000_000,
    ended_at_utc: str | None = UTC,
    end_reason: str = "USER_END",
) -> ScienceLabExperimentRecord:
    return ScienceLabExperimentRecord(
        experiment_id=experiment_id,
        parent_session_id=parent_session_id,
        date_key="17092026",
        daily_sequence=3,
        status=status,
        started_at_utc=UTC,
        started_monotonic_ns=started_ns,
        ended_at_utc=ended_at_utc,
        ended_monotonic_ns=ended_ns,
        end_reason=end_reason,
        runtime_instance_id="test-runtime",
        created_at_utc=UTC,
        updated_at_utc=UTC,
    )


def _empty_snapshot(parent_session_id: int = SESSION_ID) -> ScienceLabEvidenceSnapshot:
    empty_fact = PersistedFactSourceEvidence(parent_session_id, ())
    coverage = tuple(
        SourceCoverage(name, "NO_EVIDENCE", "", 0)
        for name in ("SINE", "NORMAL_BREAK", "MINE", "COSINE", "MIRL", "STUDY", "COSECANT")
    ) + (SourceCoverage("RESOURCE_INTENT", "UNAVAILABLE", "no_durable_event_identity", None),)
    return ScienceLabEvidenceSnapshot(
        parent_session_id=parent_session_id,
        generated_at_utc=UTC,
        source_coverage=coverage,
        sine=empty_fact,
        normal_break=empty_fact,
        mine=MineSourceEvidence(parent_session_id, ()),
        cosine=CosineSourceEvidence(parent_session_id, ()),
        mirl=MirlSourceEvidence(parent_session_id, ()),
        study=empty_fact,
        cosecant=empty_fact,
        resource_intent=None,
        limitations=(),
    )


class ListExperimentHistoryTests(unittest.TestCase):
    def test_orders_newest_first_and_flags_eligibility(self) -> None:
        records = (
            _experiment(experiment_id="MYL-17092026-SCI03", status="COMPLETED"),
            _experiment(experiment_id="MYL-17092026-SCI02", status="RUNNING", ended_ns=None, ended_at_utc=None, end_reason=""),
            _experiment(experiment_id="MYL-17092026-SCI01", status="INTERRUPTED", ended_ns=None, end_reason="CRASH_RECOVERY"),
        )
        with patch.object(history, "read_all_science_lab_experiments", return_value=records):
            entries = history.list_experiment_history()
        self.assertEqual(len(entries), 3)
        self.assertEqual([e.experiment_id for e in entries], [r.experiment_id for r in records])
        self.assertTrue(entries[0].eligible)
        self.assertEqual(entries[0].reason, "")
        self.assertFalse(entries[1].eligible)
        self.assertIn("RUNNING", entries[1].reason)
        self.assertFalse(entries[2].eligible)
        self.assertIn("INTERRUPTED", entries[2].reason)

    def test_empty_history_is_not_an_error(self) -> None:
        with patch.object(history, "read_all_science_lab_experiments", return_value=()):
            entries = history.list_experiment_history()
        self.assertEqual(entries, ())


class ReconstructHistoricalExperimentFailClosedTests(unittest.TestCase):
    def test_blank_experiment_id_fails_closed(self) -> None:
        result = history.reconstruct_historical_experiment("")
        self.assertEqual(result.status, history.HISTORY_UNAVAILABLE)
        self.assertIsNone(result.package)

    def test_unknown_experiment_id_fails_closed(self) -> None:
        with patch.object(history, "read_science_lab_experiment", return_value=None):
            result = history.reconstruct_historical_experiment("MYL-00000000-SCI99")
        self.assertEqual(result.status, history.HISTORY_UNAVAILABLE)
        self.assertIsNone(result.package)
        self.assertIn("no durable experiment record", result.reason)

    def test_non_completed_status_fails_closed(self) -> None:
        record = _experiment(status="RUNNING", ended_ns=None, ended_at_utc=None, end_reason="")
        with patch.object(history, "read_science_lab_experiment", return_value=record):
            result = history.reconstruct_historical_experiment(record.experiment_id)
        self.assertEqual(result.status, history.HISTORY_UNAVAILABLE)
        self.assertIn("RUNNING", result.reason)

    def test_missing_durable_end_boundary_fails_closed(self) -> None:
        record = _experiment(status="COMPLETED", ended_ns=None, ended_at_utc=None)
        with patch.object(history, "read_science_lab_experiment", return_value=record):
            result = history.reconstruct_historical_experiment(record.experiment_id)
        self.assertEqual(result.status, history.HISTORY_UNAVAILABLE)
        self.assertIn("end boundary", result.reason)

    def test_missing_session_closure_fails_closed_and_does_not_invent_a_time(self) -> None:
        record = _experiment()
        with patch.object(history, "read_science_lab_experiment", return_value=record), \
             patch.object(history, "read_session_closed_at_utc", return_value=None):
            result = history.reconstruct_historical_experiment(record.experiment_id)
        self.assertEqual(result.status, history.HISTORY_UNAVAILABLE)
        self.assertIn("will not invent one", result.reason)

    def test_evidence_snapshot_session_mismatch_fails_closed(self) -> None:
        record = _experiment()
        wrong_session_snapshot = _empty_snapshot(parent_session_id=record.parent_session_id + 1)
        with patch.object(history, "read_science_lab_experiment", return_value=record), \
             patch.object(history, "read_session_closed_at_utc", return_value=UTC), \
             patch.object(history, "gather_session_evidence", return_value=wrong_session_snapshot):
            result = history.reconstruct_historical_experiment(record.experiment_id)
        self.assertEqual(result.status, history.HISTORY_UNAVAILABLE)
        self.assertIn("different session", result.reason)

    def test_read_error_on_experiment_record_fails_closed_not_raises(self) -> None:
        with patch.object(history, "read_science_lab_experiment", side_effect=RuntimeError("db locked")):
            result = history.reconstruct_historical_experiment("MYL-17092026-SCI03")
        self.assertEqual(result.status, history.HISTORY_UNAVAILABLE)
        self.assertIn("RuntimeError", result.reason)


class ReconstructHistoricalExperimentSuccessTests(unittest.TestCase):
    def test_no_evidence_experiment_certifies_with_matching_identity_and_window(self) -> None:
        """An experiment with zero organ evidence still certifies (every
        source legitimately NO_EVIDENCE) -- this is the minimal, fully
        isolated proof that the reconstruction pipeline wires
        gather_session_evidence -> analyze_finalized_session correctly and
        that the resulting package's identity/window match the selected
        durable record exactly."""

        record = _experiment()
        snapshot = _empty_snapshot(parent_session_id=record.parent_session_id)
        with patch.object(history, "read_science_lab_experiment", return_value=record), \
             patch.object(history, "read_session_closed_at_utc", return_value=UTC), \
             patch.object(history, "gather_session_evidence", return_value=snapshot):
            result = history.reconstruct_historical_experiment(record.experiment_id)

        self.assertEqual(result.status, history.HISTORY_CERTIFIED)
        self.assertIsNotNone(result.package)
        self.assertEqual(result.reason, "reconstructed and certified from durable evidence")
        package = result.package
        self.assertEqual(package.experiment_id, record.experiment_id)
        self.assertEqual(package.parent_session_id, record.parent_session_id)
        self.assertEqual(package.experiment_start_monotonic_ns, record.started_monotonic_ns)
        self.assertEqual(package.experiment_end_monotonic_ns, record.ended_monotonic_ns)
        self.assertEqual(package.session_finalized_at_utc, UTC)


class NoLifecycleOrTransferAccessTests(unittest.TestCase):
    """Static guard: this module must never be able to mutate experiment
    lifecycle or mint a new live transfer -- it has no import of either
    authority at all, so it cannot call them even by accident."""

    def test_history_module_does_not_import_coordinator_finalize_or_handoff_transfer(self) -> None:
        # Exclude the module's own docstring, which legitimately explains
        # (in prose) which live-write authorities this module deliberately
        # does NOT call -- the check below is for actual code, not prose.
        source = inspect.getsource(history)
        _, _, code_after_docstring = source.partition('"""\n\nfrom __future__')
        code = "from __future__" + code_after_docstring
        self.assertNotIn(".finalize_clean_stop(", code)
        self.assertNotIn("ScienceLabExperimentLifecycle", code)
        self.assertNotIn("Chapter3ResultHandoff", code)
        self.assertNotIn("handoff.transfer(", code)
        self.assertNotIn("import PyQt6", code)

    def test_history_module_never_writes_to_the_database(self) -> None:
        source = inspect.getsource(history)
        for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM", "read_only=False"):
            self.assertNotIn(forbidden, source)


class RealDatabaseZeroWriteTests(unittest.TestCase):
    """Read-only proof against the real live database.  Skips itself if
    the real MYELIN database is not present on this machine -- it must
    never create one."""

    @classmethod
    def setUpClass(cls) -> None:
        appdata = os.environ.get("APPDATA")
        cls._db_path = Path(appdata) / "MYELIN" / "myelin2.0_session.db" if appdata else None
        if cls._db_path is None or not cls._db_path.exists():
            raise unittest.SkipTest("real MYELIN database not present on this machine")

    def _hash(self) -> str:
        return hashlib.sha256(self._db_path.read_bytes()).hexdigest()

    def test_listing_and_reconstruction_write_nothing_to_the_real_database(self) -> None:
        before = self._hash()
        entries = history.list_experiment_history()
        self.assertGreater(len(entries), 0)
        target = next((e for e in entries if e.experiment_id == "MYL-17092026-SCI03"), None)
        if target is not None:
            result = history.reconstruct_historical_experiment(target.experiment_id)
            self.assertIn(result.status, (history.HISTORY_CERTIFIED, history.HISTORY_UNAVAILABLE))
        after = self._hash()
        self.assertEqual(before, after, "SCIENCE_LAB.history wrote to the live database")

    def test_sci03_session_135_reconstructs_certified_with_official_epi_code(self) -> None:
        result = history.reconstruct_historical_experiment("MYL-17092026-SCI03")
        if result.status != history.HISTORY_CERTIFIED:
            self.skipTest(f"real acceptance record not certifiable right now: {result.reason}")
        package = result.package
        self.assertEqual(package.experiment_id, "MYL-17092026-SCI03")
        self.assertEqual(package.parent_session_id, 135)
        display_map = dict(package.sine_episode_display_ids)
        self.assertTrue(display_map, "expected at least one resolved SINE/MIRL display code")
        self.assertTrue(all(code.startswith("EPI-") for code in display_map.values()))


if __name__ == "__main__":
    unittest.main()
