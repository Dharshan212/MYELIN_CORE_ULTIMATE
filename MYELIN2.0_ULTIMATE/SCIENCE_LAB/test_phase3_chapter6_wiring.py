"""Isolated Chapter 6 EVIDENCE view-layer tests; no database access.

Supersedes the old Chapter-3-transfer-era version of this file (built around
``render_transferred_results``/``current_receipt``, retired by the 20260915
Lifetime Database Refresh wiring), and updated again for the 20260915 Final
Four-Card Evidence Completion (PRIMARY REGULATION DOMAIN and TOP FOCUS
PLATFORM removed; TOP DISTRACTION PLATFORM and TOP OTT PLATFORM now real
lifetime aggregations). The invariants this file protects: exactly four
cards, in order BEST RETURN / WORST RETURN / TOP DISTRACTION PLATFORM / TOP
OTT PLATFORM; no local scientific min()/max()/counting selection inside the
view; an unsupported result remains UNAVAILABLE; repeated updates replace
state rather than accumulating; the EVIDENCE topic retains its latest
rendered state across topic switches even while hidden; no removed-card
text remains anywhere in the page; and no chapter dependency (Chapter 3 /
Chapter 5 / handoff) exists in this file's import surface any more.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

os_environ_flag = "QT_QPA_PLATFORM"
import os

os.environ.setdefault(os_environ_flag, "offscreen")

_SCIENCE_LAB_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCIENCE_LAB_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if "SCIENCE_LAB" not in sys.modules:
    package = types.ModuleType("SCIENCE_LAB")
    package.__path__ = [str(_SCIENCE_LAB_DIR)]
    sys.modules["SCIENCE_LAB"] = package

from PyQt6.QtWidgets import QApplication

from SCIENCE_LAB.chapter6_lifetime import Chapter6LifetimeSummary, LifetimeMetricResult
from SCIENCE_LAB.chapter6_view import _EVIDENCE_CARDS, Chapter6ConclusionView

AVAILABLE = "AVAILABLE"
UNAVAILABLE = "UNAVAILABLE"

UNSUPPORTED_KEYS = (
    "top_distraction_platform",
    "top_ott_platform",
)


def unavailable(key: str, reason: str = "no evidence") -> LifetimeMetricResult:
    return LifetimeMetricResult(key, UNAVAILABLE, None, "", reason)


def available_ns(key: str, value_ns: int, *, count: int = 1) -> LifetimeMetricResult:
    return LifetimeMetricResult(
        key, AVAILABLE, value_ns, "ns",
        f"lifetime latency across {count} eligible episode(s).",
        supporting_count=count,
    )


def available_platform(key: str, label: str, *, count: int = 1) -> LifetimeMetricResult:
    return LifetimeMetricResult(
        key, AVAILABLE, label, "",
        f"{label} leads with {count} supporting record(s).",
        supporting_count=count,
    )


def make_summary(
    *,
    best_value_ns: int | None = None,
    worst_value_ns: int | None = None,
    generated_at_utc: str = "2026-09-15T00:00:00Z",
    count: int = 1,
) -> Chapter6LifetimeSummary:
    best = (
        available_ns("best_return", best_value_ns, count=count)
        if best_value_ns is not None
        else unavailable("best_return")
    )
    worst = (
        available_ns("worst_return", worst_value_ns, count=count)
        if worst_value_ns is not None
        else unavailable("worst_return")
    )
    return Chapter6LifetimeSummary(
        generated_at_utc=generated_at_utc,
        best_return=best,
        worst_return=worst,
        top_distraction_platform=unavailable("top_distraction_platform", "no certified structured platform_key"),
        top_ott_platform=unavailable("top_ott_platform", "no certified supported-time evidence"),
    )


class Chapter6EvidenceLifetimeWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.view = Chapter6ConclusionView()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    def state(self, key: str) -> tuple[str, str, str]:
        return self.view._evidence_cards[key].presentation_state()

    def assert_unsupported_unavailable(self) -> None:
        for key in UNSUPPORTED_KEYS:
            with self.subTest(key=key):
                value, status, _reason = self.state(key)
                self.assertEqual(value, "UNAVAILABLE")
                self.assertEqual(status, "UNAVAILABLE")

    # ---- initial state ----

    def test_four_cards_exist_in_order_and_start_not_refreshed(self) -> None:
        self.assertEqual(len(self.view._evidence_cards), 4)
        self.assertEqual(
            list(self.view._evidence_cards.keys()),
            ["best_return", "worst_return", "top_distraction_platform", "top_ott_platform"],
        )
        for key in self.view._evidence_cards:
            value, status, reason = self.state(key)
            self.assertEqual(value, "NOT REFRESHED")
            self.assertEqual(status, "NOT REFRESHED")
            self.assertIn("REFRESH", reason)
        self.assertNotIn(
            "AWAITING TRANSFER",
            " ".join(self.state(key)[1] for key in self.view._evidence_cards),
        )

    def test_removed_cards_have_no_trace_in_the_evidence_page(self) -> None:
        self.assertNotIn("primary_regulation_domain", self.view._evidence_cards)
        self.assertNotIn("top_focus_platform", self.view._evidence_cards)
        titles = " ".join(entry["title"] for entry in _EVIDENCE_CARDS)
        self.assertNotIn("PRIMARY REGULATION DOMAIN", titles)
        self.assertNotIn("TOP FOCUS PLATFORM", titles)

    def test_refresh_button_starts_enabled_and_emits_one_request(self) -> None:
        received = []
        self.view.refresh_lifetime_requested.connect(lambda: received.append(1))
        button = self.view._evidence_provenance._refresh_button
        self.assertTrue(button.isEnabled())
        button.click()
        self.assertEqual(len(received), 1)
        self.assertFalse(button.isEnabled())
        self.assertEqual(button.text(), "REFRESHING...")

    def test_button_re_enables_after_render_lifetime_summary(self) -> None:
        button = self.view._evidence_provenance._refresh_button
        button.click()
        self.view.render_lifetime_summary(make_summary(best_value_ns=42_000_000_000))
        self.assertTrue(button.isEnabled())
        self.assertEqual(button.text(), "REFRESH")

    # ---- rendering ----

    def test_rejects_wrong_type(self) -> None:
        with self.assertRaises(TypeError):
            self.view.render_lifetime_summary(object())

    def test_zero_eligible_samples_render_unavailable_not_zero(self) -> None:
        self.view.render_lifetime_summary(make_summary())
        for key in ("best_return", "worst_return"):
            value, status, _reason = self.state(key)
            self.assertEqual(value, "UNAVAILABLE")
            self.assertEqual(status, "UNAVAILABLE")
        self.assert_unsupported_unavailable()

    def test_one_sample_renders_identical_best_and_worst(self) -> None:
        self.view.render_lifetime_summary(
            make_summary(best_value_ns=42_000_000_000, worst_value_ns=42_000_000_000)
        )
        self.assertEqual(self.state("best_return")[:2], ("42 s", "AVAILABLE"))
        self.assertEqual(self.state("worst_return")[:2], ("42 s", "AVAILABLE"))

    def test_platform_card_renders_string_value_verbatim(self) -> None:
        summary = make_summary(best_value_ns=1_000_000_000)
        summary = Chapter6LifetimeSummary(
            generated_at_utc=summary.generated_at_utc,
            best_return=summary.best_return,
            worst_return=summary.worst_return,
            top_distraction_platform=available_platform("top_distraction_platform", "YouTube", count=7),
            top_ott_platform=available_platform("top_ott_platform", "Prime Video", count=3),
        )
        self.view.render_lifetime_summary(summary)
        self.assertEqual(self.state("top_distraction_platform")[:2], ("YouTube", "AVAILABLE"))
        self.assertEqual(self.state("top_ott_platform")[:2], ("Prime Video", "AVAILABLE"))

    def test_no_local_min_max_selection_in_view(self) -> None:
        # the view must render exactly the value the summary carries, never
        # recompute a smaller/larger one itself
        self.view.render_lifetime_summary(
            make_summary(best_value_ns=5_000_000_000, worst_value_ns=500_000_000_000)
        )
        self.assertEqual(self.state("best_return")[0], "5 s")
        self.assertEqual(self.state("worst_return")[0], "8 min 20 s")

    def test_repeated_refresh_replaces_state_without_accumulating(self) -> None:
        self.view.render_lifetime_summary(make_summary(best_value_ns=1_000_000_000))
        self.assertEqual(self.state("best_return")[0], "1 s")
        self.view.render_lifetime_summary(make_summary(best_value_ns=9_000_000_000))
        self.assertEqual(self.state("best_return")[0], "9 s")
        # widget identity must not change across refreshes (no recreation)
        card_before = self.view._evidence_cards["best_return"]
        self.view.render_lifetime_summary(make_summary(best_value_ns=3_000_000_000))
        self.assertIs(self.view._evidence_cards["best_return"], card_before)

    def test_read_error_path_reenables_button_without_crashing(self) -> None:
        button = self.view._evidence_provenance._refresh_button
        button.click()
        self.view.render_lifetime_read_error("read_error:RuntimeError")
        self.assertTrue(button.isEnabled())
        self.assertIn("read_error", self.view._evidence_provenance._body.text())

    def test_hidden_evidence_topic_still_receives_rendered_state(self) -> None:
        self.assertEqual(self.view.current_topic_key(), "overview")
        self.view.render_lifetime_summary(make_summary(best_value_ns=42_000_000_000))
        self.assertEqual(self.view.current_topic_key(), "overview")
        self.assertEqual(self.state("best_return")[0], "42 s")

        self.view._select_topic("evidence")
        self.app.processEvents()
        self.assertEqual(self.state("best_return")[0], "42 s")
        self.view._select_topic("overview")
        self.view._select_topic("evidence")
        self.app.processEvents()
        self.assertEqual(self.state("best_return")[0], "42 s")
        self.assert_unsupported_unavailable()

    def test_provenance_strip_shows_generated_timestamp_after_refresh(self) -> None:
        self.view.render_lifetime_summary(
            make_summary(best_value_ns=1_000_000_000, generated_at_utc="2026-09-15T12:34:56Z")
        )
        self.assertIn("2026-09-15T12:34:56Z", self.view._evidence_provenance._body.text())

    def test_no_chapter3_chapter5_handoff_dependency(self) -> None:
        import ast

        import SCIENCE_LAB.chapter6_view as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
        for forbidden in ("chapter3_view", "chapter5_view", "handoff", "Chapter3"):
            for module_name in imported_modules:
                self.assertNotIn(forbidden, module_name)


if __name__ == "__main__":
    unittest.main()
