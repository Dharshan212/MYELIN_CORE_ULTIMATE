"""Offscreen regressions for guarded GET CHART navigation."""

from __future__ import annotations

import json
import os
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from CONTROL_STATION.get_chart import (
    LOCKED_BODY,
    LOCKED_TITLE,
    ChartAccessRevoked,
    GetChartController,
    NeonPosterWindow,
)
from GET_CHART import read_model as chart_read_model
from METRIC_HUB.read_model import (
    UNAVAILABLE,
    BehaviourDistributionProjection,
    LifetimeMetricHubProjection,
    MetricValue,
    OrganMetric,
)


class _Engine(QObject):
    engine_status_changed = pyqtSignal(object)
    engine_stopped = pyqtSignal()
    engine_failed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.active = False

    def is_session_active(self) -> bool:
        return self.active

    def publish(self, status: str, *, active: bool) -> None:
        self.active = active
        self.engine_status_changed.emit(status)


class _Lifecycle:
    def __init__(self) -> None:
        self.stop_calls = 0

    def request_stop(self):
        self.stop_calls += 1
        return object()


class _Analytics:
    def __init__(self) -> None:
        self.open_calls = 0

    def open_composer(self) -> bool:
        self.open_calls += 1
        return True


class _ExportPoster(NeonPosterWindow):
    def __init__(self) -> None:
        super().__init__()
        self.pdf_calls = 0
        self.jpg_calls = 0
        self.export_grants = []

    def export_a3_pdf(self, token, access_is_current) -> bool:
        self.pdf_calls += 1
        self.export_grants.append((token, access_is_current))
        return access_is_current(token)

    def export_high_resolution_jpg(self, token, access_is_current) -> bool:
        self.jpg_calls += 1
        self.export_grants.append((token, access_is_current))
        return access_is_current(token)


def _unavailable_metric(label: str) -> MetricValue:
    return MetricValue(UNAVAILABLE, None, "No certified evidence.", label)


def _certified_projection() -> LifetimeMetricHubProjection:
    organs = tuple(
        OrganMetric(
            name,
            _unavailable_metric(f"{name} triggers"),
            _unavailable_metric(f"{name} returns"),
            "Certified trigger disclosure.",
            "Certified return disclosure.",
        )
        for name in ("SINE", "COSINE", "MINE", "COSECANT")
    )
    behaviour = BehaviourDistributionProjection(
        UNAVAILABLE,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        0,
        (),
        "Certified Metric Hub evidence.",
        "No certified evidence.",
    )
    return LifetimeMetricHubProjection(
        sessions=_unavailable_metric("sessions"),
        total_triggers=_unavailable_metric("triggers"),
        total_returned=_unavailable_metric("returns"),
        sine=organs[0],
        cosine=organs[1],
        mine=organs[2],
        cosecant=organs[3],
        behaviour_distribution=behaviour,
        generated_at_utc="2026-09-18T00:00:00Z",
        snapshot_id="certified-snapshot",
        source_path="read-only-test-source",
        read_only=True,
        status=UNAVAILABLE,
        status_message="No certified evidence.",
    )


def _poster_contract() -> chart_read_model.PosterChartData:
    return chart_read_model.PosterChartData(
        lifetime_summary=_certified_projection(),
        sine=chart_read_model._unavailable_sine("No SINE evidence."),
        mine=chart_read_model._unavailable_mine("No MINE evidence."),
        cosine=chart_read_model._unavailable_cosine("No COSINE evidence."),
        cosecant=chart_read_model._unavailable_cosecant("No COSECANT evidence."),
        generated_at_utc="2026-09-18T00:00:00Z",
    )

class GetChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.engine = _Engine()
        self.lifecycle = _Lifecycle()
        self.analytics = _Analytics()
        self.chart_data = _poster_contract()
        self.button = QPushButton("GET CHART")
        self.poster = _ExportPoster()
        self.controller = GetChartController(
            engine=self.engine,
            lifecycle=self.lifecycle,
            analytics_opener=self.analytics.open_composer,
            data_provider=lambda: self.chart_data,
        )
        self.controller.register_button(self.button)
        self.controller.register_poster(self.poster)
        self.engine.engine_status_changed.connect(self.controller.lifecycle_changed)
        self.engine.engine_stopped.connect(self.controller.lifecycle_changed)
        self.engine.engine_failed.connect(self.controller.lifecycle_changed)

    def tearDown(self) -> None:
        self.controller.shutdown()
        self.button.deleteLater()
        self.app.processEvents()

    def test_fully_stopped_opens_one_registered_poster(self) -> None:
        self.assertTrue(self.controller.open_poster())
        first_identity = id(self.controller.poster)
        self.assertTrue(self.poster.isVisible())
        self.assertTrue(self.controller.open_poster())
        self.assertEqual(id(self.controller.poster), first_identity)

    def test_all_active_lifecycle_states_and_live_worker_truth_are_locked(self) -> None:
        for state in ("STARTING", "ACTIVE", "PAUSED", "STOPPING", "EMERGENCY"):
            with self.subTest(state=state):
                self.engine.publish(state, active=True)
                self.assertFalse(self.controller.open_poster())
                self.assertFalse(self.poster.isVisible())
                self.assertTrue(self.button.isEnabled())
                self.assertIn("🔒", self.button.text())
        self.engine.publish("STOPPED_WITH_WORKER", active=True)
        self.assertFalse(self.controller.open_poster())

    def test_locked_dialog_has_exact_copy_and_is_not_duplicated(self) -> None:
        self.engine.publish("ACTIVE", active=True)
        self.controller.open_poster()
        dialog = self.controller._locked_dialog
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.windowTitle(), LOCKED_TITLE)
        self.assertEqual(dialog.findChild(QLabel, "getChartLockedBody").text(), LOCKED_BODY)
        self.controller.open_poster()
        self.assertIs(self.controller._locked_dialog, dialog)

    def test_close_leaves_session_running(self) -> None:
        self.engine.publish("ACTIVE", active=True)
        self.controller.open_poster()
        self.controller._locked_dialog.close_button.click()
        self.assertTrue(self.engine.active)
        self.assertEqual(self.lifecycle.stop_calls, 0)

    def test_stop_uses_lifecycle_and_unlocks_only_after_confirmed_termination(self) -> None:
        self.engine.publish("PAUSED", active=True)
        self.controller.open_poster()
        self.controller._locked_dialog.stop_button.click()
        self.assertEqual(self.lifecycle.stop_calls, 1)
        self.assertIn("🔒", self.button.text())

        self.engine.publish("STOPPING", active=True)
        self.assertIn("🔒", self.button.text())
        self.engine.active = False
        self.engine.engine_stopped.emit()
        self.assertEqual(self.button.text(), "GET CHART")

    def test_refused_or_cancelled_stop_does_not_unlock(self) -> None:
        self.engine.publish("ACTIVE", active=True)
        self.controller.open_poster()
        self.controller._locked_dialog.stop_button.click()
        self.controller.lifecycle_changed("COMMAND_REFUSED")
        self.assertIn("🔒", self.button.text())
        self.assertFalse(self.controller.open_poster())

    def test_direct_analytics_and_export_entry_points_cannot_bypass_lock(self) -> None:
        self.engine.publish("ACTIVE", active=True)
        self.assertFalse(self.controller.open_analytics_sheet())
        self.assertFalse(self.controller.export_a3_pdf())
        self.assertFalse(self.controller.export_high_resolution_jpg())
        self.assertEqual(self.analytics.open_calls, 0)
        self.assertEqual(self.poster.pdf_calls, 0)
        self.assertEqual(self.poster.jpg_calls, 0)

    def test_stopped_poster_can_open_original_analytics_and_export_entry_points(self) -> None:
        self.assertTrue(self.controller.open_analytics_sheet())
        self.assertEqual(self.analytics.open_calls, 1)
        self.assertTrue(self.controller.export_a3_pdf())
        self.assertTrue(self.controller.export_high_resolution_jpg())
        self.assertEqual(self.poster.pdf_calls, 1)
        self.assertEqual(self.poster.jpg_calls, 1)

    def test_opening_analytics_preserves_the_open_posters_access_grant(self) -> None:
        self.assertTrue(self.controller.open_poster())
        token = self.poster.access_token

        self.assertTrue(self.controller.open_analytics_sheet())
        self.assertTrue(self.controller.access_is_current(token))
        self.assertTrue(self.poster.isVisible())
        self.assertTrue(self.controller.open_poster())
        self.assertEqual(self.poster.access_token, token)

    def test_stopped_lifecycle_fact_does_not_revoke_the_open_poster(self) -> None:
        self.assertTrue(self.controller.open_poster())
        token = self.poster.access_token

        self.engine.publish("STOPPED", active=False)

        self.assertTrue(self.controller.access_is_current(token))
        self.assertTrue(self.poster.isVisible())

    def test_sequential_exports_preserve_the_open_posters_access_grant(self) -> None:
        self.assertTrue(self.controller.open_poster())
        token = self.poster.access_token

        self.assertTrue(self.controller.export_a3_pdf())
        self.assertTrue(self.controller.access_is_current(token))
        self.assertTrue(self.controller.export_high_resolution_jpg())
        self.assertTrue(self.controller.access_is_current(token))
        self.assertEqual(
            tuple(grant_token for grant_token, _predicate in self.poster.export_grants),
            (token, token),
        )

    def test_session_start_revokes_open_poster_and_invalidates_old_token(self) -> None:
        self.assertTrue(self.controller.open_poster())
        token = self.poster.access_token
        self.assertTrue(self.controller.access_is_current(token))
        self.engine.publish("STARTING", active=True)
        self.assertFalse(self.poster.isVisible())
        self.assertFalse(self.controller.access_is_current(token))

    def test_guarded_loader_returns_exact_certified_projection(self) -> None:
        self.assertTrue(self.controller.open_poster())
        self.assertIs(
            self.controller.load_chart_data(self.poster.access_token),
            self.chart_data,
        )

    def test_session_start_during_data_load_discards_the_result(self) -> None:
        self.assertTrue(self.controller.open_poster())
        token = self.poster.access_token

        def racing_provider():
            self.engine.publish("STARTING", active=True)
            return self.chart_data

        self.controller._data_provider = racing_provider
        with self.assertRaises(ChartAccessRevoked):
            self.controller.load_chart_data(token)

    def test_session_start_during_export_invalidates_the_export_grant(self) -> None:
        self.assertTrue(self.controller.open_poster())
        self.assertTrue(self.controller.export_a3_pdf())
        token, predicate = self.poster.export_grants[-1]

        self.engine.publish("STARTING", active=True)

        self.assertFalse(predicate(token))
        self.assertFalse(self.poster.isVisible())

    def test_poster_read_model_wraps_and_validates_certified_projection(self) -> None:
        summary = _certified_projection()
        evidence = chart_read_model._EvidenceSnapshot(
            frozenset(), (), (), (), (), (), ()
        )
        with patch.object(
            chart_read_model,
            "read_lifetime_metric_hub",
            return_value=summary,
        ) as reader, patch.object(
            chart_read_model,
            "_read_evidence",
            return_value=evidence,
        ):
            projection = chart_read_model.read_poster_chart_data()
        self.assertIs(projection.lifetime_summary, summary)
        self.assertIsInstance(projection, chart_read_model.PosterChartData)
        reader.assert_called_once_with(None)

        with self.assertRaises(ValueError):
            chart_read_model.validate_poster_chart_data(
                replace(
                    projection,
                    lifetime_summary=replace(summary, read_only=False),
                )
            )
        with self.assertRaises(ValueError):
            chart_read_model.validate_poster_chart_data(
                replace(
                    projection,
                    lifetime_summary=replace(
                        summary,
                        sine=replace(summary.sine, organ="MIRL"),
                    ),
                )
            )

    def test_sine_contract_preserves_episode_funnel_and_separate_returns(self) -> None:
        source = chart_read_model._EvidenceSnapshot(
            frozenset({1}), (), (), (), (), (), ()
        )
        displays = (
            SimpleNamespace(
                session_id=1, episode_uid="sine-1", candidate_uid="candidate-1",
                stage=1, occurred_wall_time_utc="2026-09-18T00:00:00Z",
                occurred_monotonic_ns=10, row_id=1,
            ),
            SimpleNamespace(
                session_id=1, episode_uid="sine-1", candidate_uid="candidate-1",
                stage=2, occurred_wall_time_utc="2026-09-18T00:00:01Z",
                occurred_monotonic_ns=20, row_id=2,
            ),
            SimpleNamespace(
                session_id=1, episode_uid="sine-1", candidate_uid="candidate-1",
                stage=3, occurred_wall_time_utc="2026-09-18T00:00:02Z",
                occurred_monotonic_ns=30, row_id=3,
            ),
            SimpleNamespace(
                session_id=1, episode_uid="sine-2", candidate_uid="candidate-2",
                stage=1, occurred_wall_time_utc="2026-09-18T00:01:00Z",
                occurred_monotonic_ns=40, row_id=4,
            ),
            SimpleNamespace(
                session_id=1, episode_uid="sine-2", candidate_uid="candidate-2",
                stage=2, occurred_wall_time_utc="2026-09-18T00:01:01Z",
                occurred_monotonic_ns=50, row_id=5,
            ),
        )
        with patch.object(
            chart_read_model.certified_metric_reader,
            "_sine_displays",
            return_value=displays,
        ), patch.object(
            chart_read_model,
            "_map_verified_sine_returns",
            return_value=frozenset({"sine-1"}),
        ):
            projection = chart_read_model._project_sine(source)

        self.assertEqual(projection.status, chart_read_model.AVAILABLE)
        self.assertEqual(
            tuple((stage.count, stage.denominator) for stage in projection.funnel),
            ((2, 2), (2, 2), (1, 2)),
        )
        self.assertEqual(projection.verified_return_episode_ids, ("sine-1",))
        self.assertEqual(projection.verified_return_denominator, 2)
        with self.assertRaises(ValueError):
            replace(
                projection,
                funnel=(
                    replace(projection.funnel[0], denominator=3),
                    *projection.funnel[1:],
                ),
            )

    def test_mine_contract_uses_recorded_choices_and_documented_outcomes(self) -> None:
        source = chart_read_model._EvidenceSnapshot(
            frozenset({1}), (), (), (object(),), (), (), ()
        )
        choice_event = SimpleNamespace(
            event_name="RETURN_INTENT_RECORDED",
            occurred_at_utc="2026-09-18T00:02:00Z",
        )
        episode = SimpleNamespace(
            session_id=1,
            generation=1,
            mine_episode_id="mine-1",
            display_episode_id="display-1",
            branch="I_WILL_COME_BACK",
            events=(choice_event,),
            closure_outcome="RETURNED",
            closure_reason="documented",
            ended_at_utc="2026-09-18T00:03:00Z",
            return_verified=True,
        )
        with patch.object(
            chart_read_model,
            "project_mine_events",
            return_value=SimpleNamespace(
                available=True, status_message="available", episodes=(episode,)
            ),
        ):
            projection = chart_read_model._project_mine(
                source, "2026-09-18T01:00:00Z"
            )

        self.assertEqual(projection.choices[0].choice, "I_WILL_COME_BACK")
        self.assertEqual(projection.choices[0].closure_outcome, "RETURNED")
        self.assertEqual(projection.outcome_buckets[0].choice_denominator, 1)

    def test_cosine_contract_exposes_only_genuine_recorded_timestamps(self) -> None:
        source = chart_read_model._EvidenceSnapshot(
            frozenset({1}), (), (), (), (object(),), (), ()
        )
        event = SimpleNamespace(
            event_id="cosine-event-1", sequence=1, event_name="SESSION_STARTED",
            occurred_at_utc="2026-09-18T00:04:00Z",
        )
        episode = SimpleNamespace(
            cosine_session_id="cosine-1", generation=1, parent_session_id=1,
            started_at_utc="2026-09-18T00:04:00Z", ended_at_utc=None,
            events=(event,),
        )
        with patch.object(
            chart_read_model,
            "project_cosine_events",
            return_value=SimpleNamespace(
                available=True, status_message="available", episodes=(episode,)
            ),
        ):
            projection = chart_read_model._project_cosine(
                source, "2026-09-18T01:00:00Z"
            )

        recorded = projection.episodes[0].events[0]
        self.assertEqual(recorded.occurred_at_utc, "2026-09-18T00:04:00Z")
        self.assertFalse(hasattr(projection.episodes[0], "viewing_duration"))
        self.assertFalse(hasattr(projection.episodes[0], "duration_seconds"))

    def test_cosecant_contract_preserves_recorded_deadline_and_return_milestone(self) -> None:
        def row(sequence, kind, effective, observed, wall, evidence=""):
            payload = {
                "sequence": sequence,
                "kind": kind,
                "break_id": "break-1",
                "study_block_id": "study-1",
                "effective_monotonic_ns": effective,
                "observed_monotonic_ns": observed,
                "occurred_wall_time_utc": wall,
                "evidence_token": evidence,
            }
            return {
                "session_id": 1,
                "break_id": "break-1",
                "kind": kind,
                "payload_json": json.dumps(payload),
            }

        rows = (
            row(1, "BREAK_STARTED", 100, 100, "2026-09-18T00:05:00Z"),
            row(2, "BREAK_COMPLETE", 200, 205, "2026-09-18T00:10:05Z"),
            row(
                3, "RETURN_CONFIRMED", 240, 241,
                "2026-09-18T00:10:41Z", "exact-resource-proof",
            ),
        )
        source = chart_read_model._EvidenceSnapshot(
            frozenset({1}), (), (), (), (), rows, ()
        )
        with patch.object(
            chart_read_model.certified_metric_reader,
            "_cosecant_metric",
        ):
            projection = chart_read_model._project_cosecant(source)

        milestones = projection.breaks[0].milestones
        self.assertEqual(milestones[1].kind, "BREAK_COMPLETE")
        self.assertEqual(milestones[1].effective_monotonic_ns, 200)
        self.assertTrue(projection.breaks[0].return_confirmed)
        self.assertEqual(projection.confirmed_return_count, 1)

    def test_missing_organ_evidence_is_explicitly_unavailable(self) -> None:
        source = chart_read_model._EvidenceSnapshot(
            frozenset(), None, None, None, None, None,
            (("sessions", "sessions table missing"),),
        )
        projections = (
            chart_read_model._project_sine(source),
            chart_read_model._project_mine(source, "2026-09-18T01:00:00Z"),
            chart_read_model._project_cosine(source, "2026-09-18T01:00:00Z"),
            chart_read_model._project_cosecant(source),
        )
        self.assertTrue(
            all(item.status == chart_read_model.UNAVAILABLE for item in projections)
        )

    def test_application_source_replaces_direct_analytics_destination(self) -> None:
        source = (Path(__file__).with_name("application.py")).read_text(encoding="utf-8")
        self.assertNotIn(
            "self.shell.analytics_requested.connect(self.analytics.open_composer)",
            source,
        )
        self.assertIn("self.shell.get_chart_requested.connect(self.get_chart.open_poster)", source)
        self.assertIn("analytics_opener=self.analytics.open_composer", source)
        self.assertIn("data_provider=read_poster_chart_data", source)
        self.assertIn("self.get_chart.shutdown()", source)

    def test_existing_analytics_a4_export_implementation_is_preserved(self) -> None:
        source = (Path(__file__).with_name("analytics.py")).read_text(encoding="utf-8")
        self.assertIn('"EXPORT PDF"', source)
        self.assertIn("def open_composer(self) -> bool:", source)
        self.assertIn("export_analytics_sheet", source)


if __name__ == "__main__":
    unittest.main()
