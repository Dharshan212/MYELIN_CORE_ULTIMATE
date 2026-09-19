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

from PyQt6.QtCore import QObject, QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QWidget

from CONTROL_STATION.get_chart import (
    LOCKED_BODY,
    LOCKED_TITLE,
    ChartAccessRevoked,
    ChartLockedDialog,
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


class _WhiteHost(QWidget):
    """Stand-in Control Station window: opaque white so dimming is measurable."""

    def __init__(self) -> None:
        super().__init__()
        self.resize(1000, 700)
        self.presses = 0
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(255, 255, 255))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.presses += 1


class _CountingLifecycle(_Lifecycle):
    pass


def _near(color: QColor, expected: tuple[int, int, int], tolerance: int) -> bool:
    return all(
        abs(actual - wanted) <= tolerance
        for actual, wanted in zip((color.red(), color.green(), color.blue()), expected)
    )


class ChartLockedDialogAppearanceTests(unittest.TestCase):
    """The CHART NOT AVAILABLE card must look like START MYELIN and act like before."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.engine = _Engine()
        self.lifecycle = _Lifecycle()
        self.host = _WhiteHost()
        self.button = QPushButton("GET CHART", self.host)
        self.button.move(820, 640)  # keep the probe corner (2, 2) on plain host
        self.poster = _ExportPoster()
        self.controller = GetChartController(
            engine=self.engine,
            lifecycle=self.lifecycle,
            analytics_opener=lambda: True,
            data_provider=_poster_contract,
            parent=self.host,
        )
        self.controller.register_button(self.button)
        self.controller.register_poster(self.poster)
        for signal in (
            self.engine.engine_status_changed,
            self.engine.engine_stopped,
            self.engine.engine_failed,
        ):
            signal.connect(self.controller.lifecycle_changed)
        self.host.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.controller.shutdown()
        self.host.close()
        self.host.deleteLater()
        self.app.sendPostedEvents(None, 16)  # QEvent.DeferredDelete
        self.app.processEvents()

    # -- helpers --------------------------------------------------------------

    def show_dialog(self) -> ChartLockedDialog:
        self.engine.publish("ACTIVE", active=True)
        self.assertFalse(self.controller.open_poster())
        self.app.processEvents()
        dialog = self.controller._locked_dialog
        self.assertIsNotNone(dialog)
        self.assertTrue(dialog.isVisible())
        return dialog

    def frame(self):
        return self.host.grab().toImage()

    @staticmethod
    def px(image, x: float, y: float) -> QColor:
        """Sample in logical coordinates; grab() is device-pixel-ratio scaled."""

        ratio = image.devicePixelRatio()
        return image.pixelColor(int(x * ratio), int(y * ratio))

    def card_rect(self, dialog: ChartLockedDialog) -> QRect:
        return QRect(dialog.card.mapTo(self.host, QPoint(0, 0)), dialog.card.size())

    def dialogs(self) -> list:
        return self.host.findChildren(ChartLockedDialog)

    # -- visual ---------------------------------------------------------------

    def test_card_is_centred_over_the_control_station(self) -> None:
        dialog = self.show_dialog()
        self.assertEqual(dialog.geometry(), self.host.rect())
        card = self.card_rect(dialog)
        self.assertLessEqual(abs(card.center().x() - self.host.rect().center().x()), 1)
        self.assertLessEqual(abs(card.center().y() - self.host.rect().center().y()), 1)
        self.assertTrue(self.host.rect().contains(card))
        self.assertGreaterEqual(card.width(), 460)
        self.assertLessEqual(card.width(), 560)

    def test_background_is_dimmed_but_not_opaque_black(self) -> None:
        dialog = self.show_dialog()
        corner = self.px(self.frame(), 2, 2)
        # white under rgba(4, 9, 13, 218): dark, yet the window still shows through
        self.assertTrue(_near(corner, (40, 45, 48), 3), corner.name())
        self.assertNotEqual((corner.red(), corner.green(), corner.blue()), (4, 9, 13))
        # the card itself is not dimmed
        card = self.card_rect(dialog)
        inside = self.px(self.frame(), card.x() + 12, card.center().y())
        self.assertTrue(_near(inside, (16, 24, 33), 2), inside.name())

    def test_card_border_and_rounded_corners(self) -> None:
        dialog = self.show_dialog()
        card = self.card_rect(dialog)
        image = self.frame()
        ratio = image.devicePixelRatio()
        row = int(card.center().y() * ratio)
        edge_pixels = [
            image.pixelColor(int(card.x() * ratio) + offset, row) for offset in (-1, 0, 1, 2)
        ]
        self.assertTrue(
            any(_near(color, (41, 64, 79), 14) for color in edge_pixels),
            [color.name() for color in edge_pixels],
        )
        corner = self.px(image, card.x() + 1, card.y() + 1)
        overlay = (40, 45, 48)
        self.assertTrue(_near(corner, overlay, 10), f"corner is not rounded: {corner.name()}")

    def test_type_hierarchy_matches_start_confirmation(self) -> None:
        dialog = self.show_dialog()
        title = dialog.findChild(QLabel, "getChartLockedTitle")
        body = dialog.findChild(QLabel, "getChartLockedBody")
        self.assertEqual(title.text(), LOCKED_TITLE)
        self.assertEqual(body.text(), LOCKED_BODY)
        self.assertEqual(title.font().pixelSize(), 20)
        self.assertTrue(title.font().bold())
        self.assertEqual(body.font().pixelSize(), 14)
        self.assertLess(body.font().weight(), title.font().weight())
        self.assertIn("#b8cad4", body.styleSheet())
        self.assertEqual(len(dialog.findChildren(QLabel)), 2, "no extra copy may be added")
        self.assertLess(title.geometry().top(), body.geometry().top())

    def test_style_values_match_the_start_confirmation_source(self) -> None:
        lifecycle_source = (Path(__file__).with_name("lifecycle.py")).read_text(encoding="utf-8")
        chart_source = (Path(__file__).with_name("get_chart.py")).read_text(encoding="utf-8")
        for literal in ("#101821", "#29404f", "border-radius: 14px", "#b8cad4"):
            self.assertIn(literal, lifecycle_source)
            self.assertIn(literal, chart_source)
        self.assertIn("QColor(4, 9, 13, 218)", lifecycle_source)
        self.assertIn("_OVERLAY_RGBA: Final = (4, 9, 13, 218)", chart_source)

    def test_buttons_are_bottom_right_aligned_and_unclipped(self) -> None:
        dialog = self.show_dialog()
        card = self.card_rect(dialog)
        close, stop = dialog.close_button, dialog.stop_button
        self.assertEqual([close.text(), stop.text()], ["CLOSE", "STOP MYELIN"])
        self.assertEqual(len(dialog.findChildren(QPushButton)), 2)
        close_box = QRect(close.mapTo(self.host, QPoint(0, 0)), close.size())
        stop_box = QRect(stop.mapTo(self.host, QPoint(0, 0)), stop.size())
        self.assertLessEqual(abs(stop_box.right() - (card.right() - 32)), 1)
        self.assertLess(close_box.right(), stop_box.left())
        self.assertEqual(stop_box.left() - close_box.right() - 1, 12)
        self.assertEqual(close_box.height(), stop_box.height())
        self.assertGreater(close_box.center().x(), card.center().x())
        self.assertGreater(close_box.top(), card.center().y())
        for box, button in ((close_box, close), (stop_box, stop)):
            self.assertTrue(card.contains(box))
            self.assertLessEqual(button.fontMetrics().horizontalAdvance(button.text()), button.width())

    def test_text_is_never_clipped(self) -> None:
        dialog = self.show_dialog()
        for label in dialog.findChildren(QLabel):
            needed = label.fontMetrics().boundingRect(
                QRect(0, 0, label.width(), 10000), int(Qt.TextFlag.TextWordWrap), label.text()
            )
            self.assertLessEqual(needed.height(), label.height() + 1, label.text())

    def test_it_is_an_in_window_card_with_no_title_bar(self) -> None:
        dialog = self.show_dialog()
        self.assertFalse(dialog.isWindow(), "must not be a second top-level window")
        self.assertIs(dialog.parent(), self.host)
        self.assertFalse(dialog.windowFlags() & Qt.WindowType.Dialog == Qt.WindowType.Dialog)

    def test_card_follows_the_window_when_it_is_moved_or_resized(self) -> None:
        dialog = self.show_dialog()
        for size in ((1400, 800), (760, 520), (500, 320)):
            self.host.resize(*size)
            self.app.processEvents()
            self.assertEqual(dialog.geometry(), self.host.rect())
            card = self.card_rect(dialog)
            self.assertTrue(self.host.rect().contains(card), f"card clipped at {size}")
            self.assertLessEqual(abs(card.center().x() - self.host.rect().center().x()), 1)
        self.host.move(40, 55)
        self.app.processEvents()
        self.assertEqual(dialog.geometry(), self.host.rect())

    def test_default_and_visible_keyboard_focus(self) -> None:
        dialog = self.show_dialog()
        self.assertIs(dialog.focusWidget(), dialog.close_button, "default must not be STOP")
        self.assertIn(":focus", dialog.card.styleSheet())
        QTest.keyClick(dialog, Qt.Key.Key_Tab)
        self.assertIs(dialog.focusWidget(), dialog.stop_button)
        QTest.keyClick(dialog, Qt.Key.Key_Tab)
        self.assertIs(dialog.focusWidget(), dialog.close_button, "focus must stay inside the card")
        QTest.keyClick(dialog, Qt.Key.Key_Backtab)
        self.assertIs(dialog.focusWidget(), dialog.stop_button)

    def test_overlay_swallows_clicks_meant_for_the_dimmed_window(self) -> None:
        dialog = self.show_dialog()
        QTest.mouseClick(dialog, Qt.MouseButton.LeftButton, pos=QPoint(6, 6))
        self.assertEqual(self.host.presses, 0)
        self.assertTrue(dialog.isVisible(), "a click outside the card must not dismiss it")

    # -- overlay lifetime -------------------------------------------------------

    def test_overlay_disappears_completely_after_dismissal(self) -> None:
        dialog = self.show_dialog()
        dialog.close_button.click()
        self.app.processEvents()
        self.assertFalse(dialog.isVisible())
        self.assertTrue(_near(self.px(self.frame(), 2, 2), (255, 255, 255), 0))

    def test_no_stale_overlay_after_stop_then_a_new_session(self) -> None:
        dialog = self.show_dialog()
        dialog.stop_button.click()
        self.app.processEvents()
        self.assertFalse(dialog.isVisible())
        self.engine.publish("STOPPED", active=False)
        self.engine.publish("STARTING", active=True)
        self.engine.publish("ACTIVE", active=True)
        self.app.processEvents()
        self.assertEqual([d for d in self.dialogs() if d.isVisible()], [])
        self.assertTrue(_near(self.px(self.frame(), 2, 2), (255, 255, 255), 0))

    def test_shutdown_removes_dialog_and_overlay(self) -> None:
        self.show_dialog()
        self.controller.shutdown()
        self.app.sendPostedEvents(None, 16)
        self.app.processEvents()
        self.assertEqual(self.dialogs(), [])
        self.assertTrue(_near(self.px(self.frame(), 2, 2), (255, 255, 255), 0))
        self.assertFalse(self.controller.open_poster())

    # -- behaviour that must be unchanged ---------------------------------------

    def test_close_dismisses_without_stopping_or_unlocking(self) -> None:
        dialog = self.show_dialog()
        dialog.close_button.click()
        self.assertEqual(self.lifecycle.stop_calls, 0)
        self.assertTrue(self.engine.active)
        self.assertFalse(dialog.isVisible())
        self.assertIn("\U0001f512", self.button.text())
        self.assertFalse(self.controller.open_poster())
        self.assertFalse(self.poster.isVisible())

    def test_stop_uses_the_existing_signal_and_lifecycle_request(self) -> None:
        dialog = self.show_dialog()
        emitted = []
        dialog.stop_requested.connect(lambda: emitted.append(True))
        dialog.stop_button.click()
        self.assertEqual(emitted, [True])
        self.assertEqual(self.lifecycle.stop_calls, 1)
        self.assertFalse(dialog.isVisible())

    def test_refused_stop_does_not_unlock_the_chart(self) -> None:
        dialog = self.show_dialog()
        dialog.stop_button.click()
        self.controller.lifecycle_changed("COMMAND_REFUSED")
        self.assertTrue(self.engine.active)
        self.assertIn("\U0001f512", self.button.text())
        self.assertFalse(self.controller.open_poster())
        self.assertFalse(self.poster.isVisible())

    def test_repeated_clicks_reuse_one_dialog(self) -> None:
        first = self.show_dialog()
        for _ in range(4):
            self.assertFalse(self.controller.open_poster())
        self.assertIs(self.controller._locked_dialog, first)
        self.assertEqual(len(self.dialogs()), 1)
        first.close_button.click()
        self.assertFalse(self.controller.open_poster())
        self.assertIs(self.controller._locked_dialog, first)
        self.assertEqual(len(self.dialogs()), 1)
        self.assertTrue(first.isVisible())

    def test_escape_dismisses_but_cannot_bypass_the_lock(self) -> None:
        dialog = self.show_dialog()
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertFalse(dialog.isVisible())
        self.assertEqual(self.lifecycle.stop_calls, 0)
        self.assertTrue(self.engine.active)
        self.assertFalse(self.controller.open_poster())
        self.assertFalse(self.poster.isVisible())

    def test_enter_on_the_default_button_never_requests_a_stop(self) -> None:
        dialog = self.show_dialog()
        QTest.keyClick(dialog, Qt.Key.Key_Return)
        self.assertEqual(self.lifecycle.stop_calls, 0)
        self.assertFalse(dialog.isVisible())

    def test_paused_and_running_stay_locked_and_stopped_opens_the_poster(self) -> None:
        for state in ("ACTIVE", "PAUSED"):
            self.engine.publish(state, active=True)
            self.assertFalse(self.controller.open_poster())
            self.assertFalse(self.poster.isVisible())
        self.controller._locked_dialog.close_button.click()
        self.engine.publish("STOPPED", active=False)
        self.assertTrue(self.controller.open_poster())
        self.app.processEvents()
        self.assertTrue(self.poster.isVisible())

    def test_without_a_host_window_the_card_still_shows_alone(self) -> None:
        standalone = ChartLockedDialog()
        standalone.present()
        self.app.processEvents()
        self.assertTrue(standalone.isVisible())
        self.assertEqual(standalone.windowTitle(), LOCKED_TITLE)
        standalone.close_button.click()
        self.assertFalse(standalone.isVisible())
        standalone.deleteLater()


if __name__ == "__main__":
    unittest.main()
