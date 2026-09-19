"""Offscreen Qt regressions for the Metric Hub episode pie and refresh guard."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from CONTROL_STATION.application import MetricHubShowcasePage  # noqa: E402


def _metric(value: int) -> SimpleNamespace:
    return SimpleNamespace(
        status="AVAILABLE",
        value=value,
        reason="available",
    )


def _organ(triggers: int = 1, returned: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        triggers=_metric(triggers),
        returned=_metric(returned),
        trigger_disclosure="Certified trigger evidence.",
        return_disclosure="Certified return evidence.",
    )


def _pie(
    social: int,
    ott: int,
    messaging: int,
    *,
    excluded: int = 0,
) -> SimpleNamespace:
    total = social + ott + messaging
    if total == 0:
        return SimpleNamespace(
            status="NO_DATA",
            social_count=0,
            ott_count=0,
            messaging_count=0,
            eligible_total=0,
            social_percent=None,
            ott_percent=None,
            messaging_percent=None,
            excluded_identity_count=excluded,
            exclusions=(
                (SimpleNamespace(reason_code="SINE_NOT_DISPLAYED", count=excluded),)
                if excluded
                else ()
            ),
            status_message="No documented distraction-intervention episodes.",
        )
    return SimpleNamespace(
        status="AVAILABLE",
        social_count=social,
        ott_count=ott,
        messaging_count=messaging,
        eligible_total=total,
        social_percent=100.0 * social / total,
        ott_percent=100.0 * ott / total,
        messaging_percent=100.0 * messaging / total,
        excluded_identity_count=excluded,
        exclusions=(
            (SimpleNamespace(reason_code="SINE_NOT_DISPLAYED", count=excluded),)
            if excluded
            else ()
        ),
        status_message="Episode distribution available.",
    )


def _projection(pie: SimpleNamespace) -> SimpleNamespace:
    organs = {name: _organ() for name in ("sine", "cosine", "mine", "cosecant")}
    row_organs = {
        name: SimpleNamespace(triggers=_metric(1), returned=_metric(0))
        for name in organs
    }
    row = SimpleNamespace(
        session_id=41,
        ordinal=1,
        is_closed=True,
        combined_triggers=_metric(4),
        combined_returned=_metric(0),
        **row_organs,
    )
    return SimpleNamespace(
        sessions=_metric(1),
        total_triggers=_metric(4),
        total_returned=_metric(0),
        behaviour_distribution=pie,
        available=True,
        session_series_status="AVAILABLE",
        session_series_message="",
        session_rows=(row,),
        **organs,
    )


def _unavailable_pie(reason: str = "Evidence unavailable.") -> SimpleNamespace:
    return SimpleNamespace(
        status="UNAVAILABLE",
        social_count=None,
        ott_count=None,
        messaging_count=None,
        eligible_total=None,
        social_percent=None,
        ott_percent=None,
        messaging_percent=None,
        excluded_identity_count=0,
        exclusions=(),
        status_message=reason,
    )


class MetricHubPieUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.page = MetricHubShowcasePage()

    def tearDown(self) -> None:
        self.page.deleteLater()
        self.app.processEvents()

    def test_available_pie_uses_backend_counts_and_hides_zero_categories(self) -> None:
        self.page.render_projection(_projection(_pie(3, 0, 1)))

        self.assertEqual(self.page._pie_chart.state, "AVAILABLE")
        self.assertEqual(self.page._pie_chart.total, 4)
        self.assertEqual(
            tuple(segment[0] for segment in self.page._pie_chart.segments),
            ("Social", "Messaging"),
        )
        self.assertEqual(set(self.page._pie_legend), {"Social", "OTT", "Messaging"})
        self.assertNotIn("Focus", self.page._pie_legend)
        self.assertFalse(self.page._pie_legend["Social"][0].isHidden())
        self.assertTrue(self.page._pie_legend["OTT"][0].isHidden())
        self.assertFalse(self.page._pie_legend["Messaging"][0].isHidden())
        self.assertEqual(self.page._pie_legend["Social"][1].text(), "3 · 75.0%")

    def test_no_data_and_unavailable_clear_stale_segments(self) -> None:
        self.page._render_behaviour_distribution(_projection(_pie(2, 1, 1)))
        self.assertTrue(self.page._pie_chart.segments)

        self.page._render_behaviour_distribution(_projection(_pie(0, 0, 0)))
        self.assertEqual(self.page._pie_chart.state, "NO_DATA")
        self.assertEqual(self.page._pie_chart.segments, ())
        self.assertTrue(all(row.isHidden() for row, _value in self.page._pie_legend.values()))

        self.page._render_behaviour_distribution(
            SimpleNamespace(behaviour_distribution=_unavailable_pie("Reader failed."))
        )
        self.assertEqual(self.page._pie_chart.state, "UNAVAILABLE")
        self.assertEqual(self.page._pie_chart.segments, ())
        self.assertIn("Reader failed", self.page._pie_status.text())
        self.assertTrue(
            all(not row.isHidden() for row, _value in self.page._pie_legend.values())
        )

    def test_sine_exclusion_caveat_uses_user_facing_wording(self) -> None:
        self.page.render_projection(_projection(_pie(3, 1, 1, excluded=1)))

        self.assertFalse(self.page._pie_exclusions.isHidden())
        self.assertEqual(
            self.page._pie_exclusions.text(),
            "Excluded: 1 SINE trigger (popup not displayed)",
        )
        self.assertNotIn("SINE_NOT_DISPLAYED", self.page._pie_exclusions.text())

    def test_refresh_is_locked_while_active_or_busy_and_stale_calls_do_nothing(self) -> None:
        emissions: list[str] = []
        self.page.refresh_requested.connect(lambda: emissions.append("refresh"))

        self.assertTrue(self.page._refresh_button.isEnabled())
        self.page.set_session_active(True)
        self.assertFalse(self.page._refresh_button.isEnabled())
        self.page._request_manual_refresh()
        self.assertEqual(emissions, [])

        self.page.set_session_active(False)
        self.assertTrue(self.page._refresh_button.isEnabled())
        self.page._request_manual_refresh()
        self.assertEqual(emissions, ["refresh"])

        self.page.set_refreshing(True)
        self.assertFalse(self.page._refresh_button.isEnabled())
        self.page._request_manual_refresh()
        self.assertEqual(emissions, ["refresh"])
        self.page.set_refreshing(False)
        self.assertTrue(self.page._refresh_button.isEnabled())

    def test_pie_updates_preserve_all_five_chart_instances_and_live_rows(self) -> None:
        charts = (self.page._histogram_chart, *self.page._organ_charts.values())
        identities = tuple(id(chart) for chart in charts)

        self.page.render_projection(_projection(_pie(2, 1, 1)))
        self.page.render_projection(_projection(_pie(1, 2, 1)))

        self.assertEqual(tuple(id(chart) for chart in charts), identities)
        self.assertEqual(len(charts), 5)
        self.assertTrue(all(chart.is_live for chart in charts))
        self.assertTrue(all(chart.row_count() == 1 for chart in charts))

    def test_refresh_failure_clears_stale_pie_and_next_projection_recovers(self) -> None:
        self.page.render_projection(_projection(_pie(2, 1, 1)))
        self.page.show_refresh_failure()
        self.assertEqual(self.page._pie_chart.state, "UNAVAILABLE")
        self.assertEqual(self.page._pie_chart.segments, ())

        self.page.render_projection(_projection(_pie(1, 1, 2)))
        self.assertEqual(self.page._pie_chart.state, "AVAILABLE")
        self.assertEqual(self.page._pie_chart.total, 4)
        self.assertEqual(self.page._pie_legend["Messaging"][1].text(), "2 · 50.0%")


if __name__ == "__main__":
    unittest.main()
