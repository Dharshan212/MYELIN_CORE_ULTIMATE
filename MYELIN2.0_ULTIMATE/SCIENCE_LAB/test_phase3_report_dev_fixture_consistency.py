"""Phase 3 fix-pass regression test (Chief's ruling item 5): SP6's Results
Overview status for each organ must agree with that organ's own results-page
Data status card.  Both fixture-only checks -- no production data, no I/O.
"""

from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace

from SCIENCE_LAB import report


class DevFixtureConsistencyTests(unittest.TestCase):
    def test_shipped_dev_fixtures_are_internally_consistent(self):
        fixtures = report._build_dev_fixtures()
        report._check_dev_fixture_consistency(fixtures)  # must not raise

    def test_mismatched_status_is_rejected(self):
        fixtures = report._build_dev_fixtures()
        broken_cards = [
            dict(card) if card.get("organ") != "COSINE" else {**card, "status": "AVAILABLE"}
            for card in fixtures["sp6"].organ_overview_cards
        ]
        fixtures["sp6"] = SimpleNamespace(
            **{**vars(fixtures["sp6"]), "organ_overview_cards": broken_cards}
        )
        with self.assertRaises(report.MyelinReportError):
            report._check_dev_fixture_consistency(fixtures)

    def test_generate_dev_preview_pdf_runs_the_check(self):
        # A tampered fixture builder must stop generation before any page is
        # drawn, not just leave a silently wrong PDF on disk.
        original = report._build_dev_fixtures

        def _tampered():
            fixtures = original()
            cards = [
                dict(card) if card.get("organ") != "MINE" else {**card, "status": "UNAVAILABLE"}
                for card in fixtures["sp6"].organ_overview_cards
            ]
            fixtures["sp6"] = SimpleNamespace(**{**vars(fixtures["sp6"]), "organ_overview_cards": cards})
            return fixtures

        report._build_dev_fixtures = _tampered
        try:
            with self.assertRaises(report.MyelinReportError):
                report.generate_dev_preview_pdf("__phase3_consistency_should_not_be_written__.pdf")
        finally:
            report._build_dev_fixtures = original


if __name__ == "__main__":
    unittest.main()
