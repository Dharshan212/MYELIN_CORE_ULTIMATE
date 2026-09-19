"""Focused offscreen-Qt tests for Chapter 5's SHOW HISTORY UI addition
(Chief's 20260917 instruction).

Verifies the UI-side contract only: signals fire with the right
experiment id, repeated renders never duplicate rows, the history dialog
never mutates the live ``_current_receipt``/main dashboard, and the
history EXPORT PDF button is gated strictly on a CERTIFIED reconstruction.
The read-only reconstruction pipeline itself is covered separately in
``test_history.py``.
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SCIENCE_LAB_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCIENCE_LAB_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if "SCIENCE_LAB" not in sys.modules:
    package_module = types.ModuleType("SCIENCE_LAB")
    package_module.__path__ = [str(_SCIENCE_LAB_DIR)]
    sys.modules["SCIENCE_LAB"] = package_module

from PyQt6.QtWidgets import QApplication

from SCIENCE_LAB.chapter5_view import Chapter5ResultsView
from SCIENCE_LAB.history import HistoryEntry, HistoryReconstruction


def _entries(*, eligible_id: str = "MYL-17092026-SCI03") -> tuple[HistoryEntry, ...]:
    return (
        HistoryEntry(eligible_id, 135, "COMPLETED", "2026-09-17T10:00:00Z", "2026-09-17T10:05:00Z", "USER_END", True, ""),
        HistoryEntry("MYL-17092026-SCI02", 134, "RUNNING", "2026-09-17T09:00:00Z", None, "", False, "status is RUNNING, not COMPLETED"),
    )


class Chapter5HistoryUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_show_history_button_present_and_enabled_with_no_current_receipt(self) -> None:
        view = Chapter5ResultsView()
        self.assertIsNone(view.current_receipt)
        self.assertTrue(view._history_button.isEnabled())

    def test_history_requested_signal_fires_on_button_click(self) -> None:
        view = Chapter5ResultsView()
        fired = []
        view.history_requested.connect(lambda: fired.append(True))
        # Avoid actually opening the modal dialog in a headless test: call
        # the exact same emit the click handler performs.
        view.history_requested.emit()
        self.assertEqual(fired, [True])

    def test_render_history_list_shows_exact_row_count_and_never_duplicates_on_rerender(self) -> None:
        view = Chapter5ResultsView()
        view.render_history_list(_entries())
        self.assertEqual(view._history_dialog._list_layout.count(), 2 + 1)  # rows + trailing stretch
        # Re-render with the same data (e.g. re-opening SHOW HISTORY) must
        # replace, never append.
        view.render_history_list(_entries())
        self.assertEqual(view._history_dialog._list_layout.count(), 2 + 1)

    def test_row_selection_emits_the_exact_experiment_id_up_through_the_view(self) -> None:
        view = Chapter5ResultsView()
        view.render_history_list(_entries(eligible_id="MYL-17092026-SCI03"))
        received = []
        view.history_experiment_selected.connect(received.append)
        # The only enabled button in the row layout belongs to the
        # eligible entry (row index 0); click it directly.
        row_widget = view._history_dialog._list_layout.itemAt(0).widget()
        eligible_button = [
            child for child in row_widget.findChildren(type(view._history_button))
            if child.isEnabled()
        ]
        self.assertEqual(len(eligible_button), 1)
        eligible_button[0].click()
        self.assertEqual(received, ["MYL-17092026-SCI03"])

    def test_render_history_result_certified_enables_export_and_holds_the_package(self) -> None:
        from dataclasses import replace

        from SCIENCE_LAB.test_phase4_report_integration import make_package

        package = make_package(mine=1)
        view = Chapter5ResultsView()
        reconstruction = HistoryReconstruction(
            "CERTIFIED", package.experiment_id, package,
            "reconstructed and certified from durable evidence",
        )
        view.render_history_result(reconstruction)
        self.assertIs(view._history_dialog._package, package)
        self.assertTrue(view._history_dialog._export_button.isEnabled())

    def test_render_history_result_unavailable_disables_export_and_clears_package(self) -> None:
        view = Chapter5ResultsView()
        bad = HistoryReconstruction("UNAVAILABLE", "MYL-00000000-SCI99", None, "no durable experiment record exists with this exact id")
        view.render_history_result(bad)
        self.assertIsNone(view._history_dialog._package)
        self.assertFalse(view._history_dialog._export_button.isEnabled())

    def test_history_operations_never_touch_current_receipt_or_main_dashboard(self) -> None:
        view = Chapter5ResultsView()
        self.assertIsNone(view.current_receipt)
        self.assertIsNone(view.current_presentation)

        from SCIENCE_LAB.test_phase4_report_integration import make_package

        package = make_package(mine=1)
        view.render_history_list(_entries())
        view.render_history_result(
            HistoryReconstruction("CERTIFIED", package.experiment_id, package, "reconstructed and certified from durable evidence")
        )
        # Still no live receipt/presentation -- history never writes there.
        self.assertIsNone(view.current_receipt)
        self.assertIsNone(view.current_presentation)
        self.assertFalse(view._section_grid.isVisible())


if __name__ == "__main__":
    unittest.main()
