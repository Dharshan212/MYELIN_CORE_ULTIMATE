"""Phase 5B EXPORT PDF wiring tests (Chapter 5 -> frozen report generator).

Scope: ``SCIENCE_LAB.chapter5_view`` only.  These tests never touch a real
database, never call ``generate_dev_preview_pdf``/``_build_dev_fixtures``,
and reuse the existing Phase-4 fixture builders (``make_package`` etc.)
instead of inventing new production timing constants.
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SCIENCE_LAB_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCIENCE_LAB_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if "SCIENCE_LAB" not in sys.modules:
    package = types.ModuleType("SCIENCE_LAB")
    package.__path__ = [str(_SCIENCE_LAB_DIR)]
    sys.modules["SCIENCE_LAB"] = package

from PyQt6.QtWidgets import QApplication

from SCIENCE_LAB import chapter5_view as cv
from SCIENCE_LAB.analysis import UNAVAILABLE, SourceCoverage
from SCIENCE_LAB.handoff import Chapter3TransferReceipt
from SCIENCE_LAB.report_model import ReportModelError
from SCIENCE_LAB import report as report_module
from SCIENCE_LAB.test_phase4_report_integration import (
    COSECANT_MINIMUM_BREAK_NS,
    make_cosecant,
    make_package,
)


def _with_resource_intent_coverage(package):
    """``build_chapter5_presentation`` (chapter5_view.py) requires the exact
    RESOURCE_INTENT unavailable-coverage row the real evidence.py always
    attaches; the Phase-4 ``make_package`` fixture omits it because
    report_model.py itself does not need it.  Add it here rather than
    weakening either module's own validation."""

    resource_row = SourceCoverage("RESOURCE_INTENT", UNAVAILABLE, "no_durable_event_identity", None)
    return replace(package, source_coverage=package.source_coverage + (resource_row,))


def make_receipt(**package_kwargs) -> Chapter3TransferReceipt:
    """A properly-constructed (identity- and status-validated) receipt,
    exactly the way the real Chapter 3 -> Chapter 5 handoff builds one."""

    package = _with_resource_intent_coverage(make_package(**package_kwargs))
    return Chapter3TransferReceipt(
        package=package,
        experiment_id=package.experiment_id,
        parent_session_id=package.parent_session_id,
        transferred_at_utc="2026-09-15T10:00:00.000000Z",
    )


def make_unvalidated_receipt(package) -> Chapter3TransferReceipt:
    """Construct a receipt WITHOUT running ``__post_init__`` -- the only way
    to reach an identity-mismatched or non-CERTIFIED receipt at all, since
    the real constructor (handoff.py, frozen/protected) already refuses
    both.  Used only to prove Chapter 5's own click-handler gate is a real,
    independent check and not merely trusting that upstream validation."""

    receipt = object.__new__(Chapter3TransferReceipt)
    object.__setattr__(receipt, "package", package)
    object.__setattr__(receipt, "experiment_id", package.experiment_id)
    object.__setattr__(receipt, "parent_session_id", package.parent_session_id)
    object.__setattr__(receipt, "transferred_at_utc", "2026-09-15T10:00:00.000000Z")
    return receipt


class ExportWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.view = cv.Chapter5ResultsView()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    # -- button state -----------------------------------------------------

    def test_button_disabled_without_receipt(self) -> None:
        self.assertIsNone(self.view.current_receipt)
        self.assertFalse(self.view._export_action._button.isEnabled())

    def test_button_enabled_after_certified_transfer(self) -> None:
        receipt = make_receipt(sine=1)
        self.view.render_transferred_results(receipt)
        self.assertTrue(self.view._export_action._button.isEnabled())
        self.assertIs(self.view.current_receipt, receipt)

    # -- exact-receipt identity --------------------------------------------

    def test_export_uses_exact_current_receipt_object(self) -> None:
        receipt = make_receipt(sine=1)
        self.view.render_transferred_results(receipt)
        with patch.object(cv, "generate_report_pdf") as generator, \
             patch.object(cv.QFileDialog, "getSaveFileName", return_value=("out.pdf", "")), \
             patch.object(cv.QMessageBox, "information"):
            generator.return_value = Path("out.pdf")
            self.view._handle_export_requested()
            generator.assert_called_once()
            passed_source, passed_path = generator.call_args.args
            self.assertIs(passed_source, receipt)
            self.assertEqual(Path(passed_path).name, "out.pdf")

    def test_receipt_a_replaced_by_receipt_b_export_uses_b_never_a(self) -> None:
        receipt_a = make_receipt(experiment_id="MYL-15092026-SCIA", sine=1)
        receipt_b = make_receipt(experiment_id="MYL-15092026-SCIB", mine=1)
        self.view.render_transferred_results(receipt_a)
        self.view.render_transferred_results(receipt_b)
        with patch.object(cv, "generate_report_pdf") as generator, \
             patch.object(cv.QFileDialog, "getSaveFileName", return_value=("out.pdf", "")), \
             patch.object(cv.QMessageBox, "information"):
            generator.return_value = Path("out.pdf")
            self.view._handle_export_requested()
            passed_source = generator.call_args.args[0]
            self.assertIs(passed_source, receipt_b)
            self.assertIsNot(passed_source, receipt_a)

    def test_repeated_export_does_not_mutate_current_receipt(self) -> None:
        receipt = make_receipt(cosine=1)
        self.view.render_transferred_results(receipt)
        with patch.object(cv, "generate_report_pdf") as generator, \
             patch.object(cv.QFileDialog, "getSaveFileName", return_value=("out.pdf", "")), \
             patch.object(cv.QMessageBox, "information"):
            generator.return_value = Path("out.pdf")
            self.view._handle_export_requested()
            self.view._handle_export_requested()
        self.assertEqual(generator.call_count, 2)
        for call in generator.call_args_list:
            self.assertIs(call.args[0], receipt)
        self.assertIs(self.view.current_receipt, receipt)

    # -- save dialog --------------------------------------------------------

    def test_cancel_dialog_makes_zero_generator_calls(self) -> None:
        receipt = make_receipt(sine=1)
        self.view.render_transferred_results(receipt)
        with patch.object(cv, "generate_report_pdf") as generator, \
             patch.object(cv.QFileDialog, "getSaveFileName", return_value=("", "")):
            self.view._handle_export_requested()
            generator.assert_not_called()
        self.assertIs(self.view.current_receipt, receipt)

    def test_pdf_extension_handling(self) -> None:
        self.assertEqual(cv._normalize_pdf_path(Path("report")).name, "report.pdf")
        self.assertEqual(cv._normalize_pdf_path(Path("report.pdf")).name, "report.pdf")
        self.assertEqual(cv._normalize_pdf_path(Path("report.PDF")).name, "report.PDF")
        self.assertEqual(cv._normalize_pdf_path(Path("report.txt")).name, "report.txt.pdf")

    def test_default_filename_is_deterministic_and_windows_safe(self) -> None:
        name = cv._default_export_filename("MYL-15092026-SCI01")
        self.assertEqual(name, "MYELIN_REPORT_MYL-15092026-SCI01.pdf")
        unsafe = cv._default_export_filename('bad<>:"/\\|?*id')
        self.assertNotIn("<", unsafe)
        self.assertTrue(unsafe.endswith(".pdf"))

    # -- generation success / failure ---------------------------------------

    def test_generator_success_shows_information_with_path(self) -> None:
        receipt = make_receipt(sine=1)
        self.view.render_transferred_results(receipt)
        with patch.object(cv, "generate_report_pdf", return_value=Path("saved.pdf")), \
             patch.object(cv.QFileDialog, "getSaveFileName", return_value=("saved.pdf", "")), \
             patch.object(cv.QMessageBox, "information") as info, \
             patch.object(cv.QMessageBox, "warning") as warn:
            self.view._handle_export_requested()
            info.assert_called_once()
            self.assertIn("saved.pdf", info.call_args.args[-1])
            warn.assert_not_called()

    def test_generator_failure_shows_warning_never_success(self) -> None:
        receipt = make_receipt(sine=1)
        self.view.render_transferred_results(receipt)
        with patch.object(cv, "generate_report_pdf", side_effect=RuntimeError("boom")), \
             patch.object(cv.QFileDialog, "getSaveFileName", return_value=("out.pdf", "")), \
             patch.object(cv.QMessageBox, "information") as info, \
             patch.object(cv.QMessageBox, "warning") as warn:
            self.view._handle_export_requested()
            warn.assert_called_once()
            info.assert_not_called()
        self.assertIs(self.view.current_receipt, receipt)

    def test_existing_destination_preserved_on_real_generator_failure(self) -> None:
        """End-to-end through the real frozen generator (not mocked): a
        receipt that passes every Chapter-5 gate (CERTIFIED, identity
        matches) but whose COSECANT row is temporally malformed must still
        be rejected by report_model.py, and any pre-existing file at the
        chosen destination must survive untouched."""

        immediate = make_cosecant(1)[0]
        malformed_row = replace(
            immediate,
            break_complete_monotonic_ns=immediate.break_started_monotonic_ns + COSECANT_MINIMUM_BREAK_NS - 1,
            return_confirmed_monotonic_ns=immediate.break_started_monotonic_ns + COSECANT_MINIMUM_BREAK_NS + 2_999_999_999,
        )
        package = replace(make_package(cosecant=1), cosecant_break_rows=(malformed_row,))
        receipt = Chapter3TransferReceipt(
            package=package,
            experiment_id=package.experiment_id,
            parent_session_id=package.parent_session_id,
            transferred_at_utc="2026-09-15T10:00:00.000000Z",
        )
        self.view._current_receipt = receipt  # bypass build_chapter5_presentation for this backend-only check

        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "prior.pdf"
            output.write_bytes(b"prior-valid-content")
            with patch.object(cv.QFileDialog, "getSaveFileName", return_value=(str(output), "")), \
                 patch.object(cv.QMessageBox, "information") as info, \
                 patch.object(cv.QMessageBox, "warning") as warn:
                self.view._handle_export_requested()
                warn.assert_called_once()
                info.assert_not_called()
            self.assertEqual(output.read_bytes(), b"prior-valid-content")

    # -- defense-in-depth gates ------------------------------------------

    def test_uncertified_package_is_rejected_before_any_dialog(self) -> None:
        draft_package = replace(make_package(sine=1), analysis_status="DRAFT")
        receipt = make_unvalidated_receipt(draft_package)
        self.view._current_receipt = receipt
        with patch.object(cv, "generate_report_pdf") as generator, \
             patch.object(cv.QFileDialog, "getSaveFileName") as dialog, \
             patch.object(cv.QMessageBox, "warning") as warn:
            self.view._handle_export_requested()
            dialog.assert_not_called()
            generator.assert_not_called()
            warn.assert_called_once()

    def test_identity_mismatched_receipt_is_rejected_before_any_dialog(self) -> None:
        package = make_package(sine=1)
        mismatched = object.__new__(Chapter3TransferReceipt)
        object.__setattr__(mismatched, "package", package)
        object.__setattr__(mismatched, "experiment_id", "SOMETHING-ELSE")
        object.__setattr__(mismatched, "parent_session_id", package.parent_session_id)
        object.__setattr__(mismatched, "transferred_at_utc", "2026-09-15T10:00:00.000000Z")
        self.view._current_receipt = mismatched
        with patch.object(cv, "generate_report_pdf") as generator, \
             patch.object(cv.QFileDialog, "getSaveFileName") as dialog, \
             patch.object(cv.QMessageBox, "warning") as warn:
            self.view._handle_export_requested()
            dialog.assert_not_called()
            generator.assert_not_called()
            warn.assert_called_once()

    def test_no_receipt_refuses_before_any_dialog(self) -> None:
        with patch.object(cv, "generate_report_pdf") as generator, \
             patch.object(cv.QFileDialog, "getSaveFileName") as dialog, \
             patch.object(cv.QMessageBox, "warning") as warn:
            self.view._handle_export_requested()
            dialog.assert_not_called()
            generator.assert_not_called()
            warn.assert_called_once()

    # -- dev-fixture / persistence isolation ------------------------------

    def test_production_handler_never_invokes_dev_fixtures(self) -> None:
        receipt = make_receipt(sine=1, mine=1)
        self.view.render_transferred_results(receipt)
        with patch.object(report_module, "_build_dev_fixtures") as dev_fixtures, \
             patch.object(report_module, "generate_dev_preview_pdf") as dev_pdf:
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "real.pdf"
                with patch.object(cv.QFileDialog, "getSaveFileName", return_value=(str(output), "")), \
                     patch.object(cv.QMessageBox, "information"):
                    self.view._handle_export_requested()
            dev_fixtures.assert_not_called()
            dev_pdf.assert_not_called()

    def test_chapter5_view_source_has_no_persistence_or_sqlite_import(self) -> None:
        source = Path(cv.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import sqlite3", source)
        self.assertNotIn("import PERSISTENCE", source)
        self.assertNotIn("from PERSISTENCE", source)
        # The module boundary is documented in the module docstring (which
        # names these two Phase-3-only functions precisely to say they are
        # never used) -- so check bound names, not raw text, for the actual
        # guarantee: chapter5_view never imports either symbol.
        self.assertFalse(hasattr(cv, "generate_dev_preview_pdf"))
        self.assertFalse(hasattr(cv, "_build_dev_fixtures"))


if __name__ == "__main__":
    unittest.main()
