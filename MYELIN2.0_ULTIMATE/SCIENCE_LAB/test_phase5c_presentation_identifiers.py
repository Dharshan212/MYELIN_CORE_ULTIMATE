"""Phase 5C bug-fix regression tests: report-local presentation aliases for
opaque production identifiers (Chief's revised, full-source-audit ruling).

Production episode/attempt/break identifiers (e.g.
``sine_d98434c3bdcde139472aa6d15a044fdd``) are far longer than the short
synthetic ids Phase-4's own fixtures used (``sine-001``), and overflowed the
frozen Phase-3 table/journey-box geometry on the first real export.  The fix
lives entirely in ``SCIENCE_LAB/report_model.py``: a deterministic,
first-occurrence-ordered, organ-scoped alias is substituted only at the
point a value is placed into a display tuple/label.  Every grouping, count,
and provenance reference must still use the real raw id.  ``report.py`` is
never touched.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import types
import unittest
from dataclasses import replace
from pathlib import Path

_SCIENCE_LAB_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCIENCE_LAB_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if "SCIENCE_LAB" not in sys.modules:
    package_module = types.ModuleType("SCIENCE_LAB")
    package_module.__path__ = [str(_SCIENCE_LAB_DIR)]
    sys.modules["SCIENCE_LAB"] = package_module

from SCIENCE_LAB.analysis import (
    AVAILABLE,
    AnalysisValue,
    CosecantBreakRow,
    CosineEpisodeReportRow,
    MineEpisodeReportRow,
    SineStageRow,
    SuccessfulReturnOnsetLatencyExtrema,
    SuccessfulReturnOnsetLatencySample,
)
from SCIENCE_LAB import report
from SCIENCE_LAB.report_model import (
    ReportModelError,
    _presentation_aliases,
    adapt_certified_report_input,
    plan_report_pages,
)
from SCIENCE_LAB.test_phase4_report_integration import (
    END,
    RETURN_REFERENCE,
    START,
    empty_extrema,
    make_cosecant,
    make_cosine,
    make_mine,
    make_package,
    ref,
)

# The exact real identifier that overflowed the frozen SP7 journey box and
# table cells on the first real MYELIN export (Phase 5C UAT, experiment
# MYL-15092026-SCI01).
REAL_SINE_EPISODE_ID = "sine_d98434c3bdcde139472aa6d15a044fdd"


def long_id(prefix: str, seed: str) -> str:
    """A production-shaped opaque id: ``<prefix>_<32 hex chars>`` -- never a
    short fixture convenience string like Phase-4's own ``sine-001``."""

    return f"{prefix}_{hashlib.md5(seed.encode()).hexdigest()}"


def make_long_sine(episode_ids: tuple[str, ...], *, stages: tuple[int, ...] = (1,),
                    popup_ids: tuple[str, ...] | None = None, verified: bool = True):
    """Build SineStageRow/extrema data shaped like make_sine() but with
    caller-supplied (production-length) episode ids -- one stage row per
    (episode, stage) pair, in the given order, each a distinct popup."""

    stage_rows = []
    samples = []
    base = START
    popup_ids = popup_ids or tuple(f"popup-{i}" for i in range(len(stages)))
    for episode in episode_ids:
        for offset, (stage, popup) in enumerate(zip(stages, popup_ids)):
            t = base + offset * 1_000_000_000
            stage_rows.append(SineStageRow(
                episode, stage, popup, t, f"2026-09-15T10:{offset % 60:02d}:00Z", "", "resource",
                (ref("MIRL", f"display-{episode}-{offset}", t, "sine_displayed"),),
            ))
        if verified:
            display = ref("MIRL", f"display-{episode}", base, "sine_displayed")
            onset = ref("MIRL", f"onset-{episode}", base + 2_000_000_000, "return_verification_started")
            verified_ref = ref("MIRL", f"verified-{episode}", base + 3_000_000_000, "return_verified")
            closed = ref("MIRL", f"closed-{episode}", base + 4_000_000_000, "episode_closed")
            samples.append(SuccessfulReturnOnsetLatencySample(
                episode, long_id("attempt", episode), 2_000_000_000,
                display, onset, verified_ref, closed, (display, onset, verified_ref, closed),
            ))
        base += 20_000_000_000
    if not samples:
        return tuple(stage_rows), empty_extrema()
    refs = tuple(dict.fromkeys(anchor for sample in samples for anchor in sample.supporting_event_chain))
    value = AnalysisValue(AVAILABLE, 2_000_000_000, "ns", RETURN_REFERENCE, refs)
    extrema = SuccessfulReturnOnsetLatencyExtrema(value, value, len(samples), "ns", RETURN_REFERENCE, START, END, tuple(samples))
    return tuple(stage_rows), extrema


def package_with_sine(episode_ids, **kwargs) -> "Chapter3ResultPackage":
    rows, extrema = make_long_sine(episode_ids, **kwargs)
    # Official EPI-DDMMYYYY-NN codes are resolved from MIRL's live projection
    # during real certification (SCIENCE_LAB/analysis.py); these isolated
    # report_model.py tests fabricate the resolved table directly, in the
    # given episode_ids order, matching the pre-existing test expectations.
    display_ids = tuple(
        (episode_id, f"EPI-15092026-{index + 1:02d}")
        for index, episode_id in enumerate(dict.fromkeys(episode_ids))
    )
    return replace(
        make_package(sine=0),
        sine_stage_rows=rows,
        successful_return_onset_latency_extrema=extrema,
        sine_episode_display_ids=display_ids,
    )


class PresentationAliasHelperTests(unittest.TestCase):
    def test_deterministic_first_occurrence_order(self) -> None:
        ids = (long_id("sine", "b"), long_id("sine", "a"), long_id("sine", "b"))
        alias = _presentation_aliases(ids, prefix="SINE-E")
        self.assertEqual(alias[ids[0]], "SINE-E01")
        self.assertEqual(alias[ids[1]], "SINE-E02")
        self.assertEqual(len(alias), 2)  # unique-within-call, order preserved

    def test_never_truncation_based_stays_unique_on_shared_prefix(self) -> None:
        shared = "sine_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ids = (shared + "1", shared + "2", shared + "3")
        alias = _presentation_aliases(ids, prefix="SINE-E")
        self.assertEqual(len(set(alias.values())), 3)

    def test_width_expands_past_ninety_nine(self) -> None:
        ids = tuple(long_id("sine", str(i)) for i in range(150))
        alias = _presentation_aliases(ids, prefix="SINE-E")
        self.assertEqual(alias[ids[0]], "SINE-E001")
        self.assertEqual(alias[ids[149]], "SINE-E150")


class SineIdentifierTests(unittest.TestCase):
    def test_1_exact_real_sine_id_does_not_overflow(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,))
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        self.assertNotIn(REAL_SINE_EPISODE_ID, page.table2.rows[0])
        self.assertEqual(page.table2.rows[0][0], "EPI-15092026-01")

    def test_2_multiple_distinct_long_episode_ids(self) -> None:
        ids = tuple(long_id("sine", str(i)) for i in range(3))
        package = package_with_sine(ids)
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        aliases = [row[0] for row in page.table2.rows]
        self.assertEqual(aliases, ["EPI-15092026-01", "EPI-15092026-02", "EPI-15092026-03"])
        for raw in ids:
            self.assertNotIn(raw, page.table2.rows[ids.index(raw)])

    def test_3_one_episode_multiple_stages_shares_one_alias(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,), stages=(1, 2), popup_ids=("popup-a", "popup-b"))
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        self.assertEqual(len(page.table2.rows), 2)
        self.assertEqual(page.table2.rows[0][0], page.table2.rows[1][0])

    def test_4_same_stage_retry_not_collapsed(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,), stages=(1, 1), popup_ids=("popup-a", "popup-b"))
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        self.assertEqual(len(page.table2.rows), 2)

    def test_5_long_attempt_id_gets_its_own_alias(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,))
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        recovery_row = page.table1.rows[0]
        self.assertNotIn(REAL_SINE_EPISODE_ID, recovery_row)
        self.assertTrue(any(cell.startswith("ATT-") for cell in recovery_row))
        self.assertEqual(recovery_row[0], "EPI-15092026-01")

    def test_pathway_has_no_database_identifier(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,))
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        for label in page.pathway_labels:
            self.assertNotIn(REAL_SINE_EPISODE_ID, label)
            self.assertNotIn("EPI-", label)  # not even the display code belongs here

    def test_sine1_retry_sine2_remains_three_visible_pathway_nodes(self) -> None:
        package = package_with_sine(
            (REAL_SINE_EPISODE_ID,), stages=(1, 1, 2), popup_ids=("popup-a", "popup-b", "popup-c"),
        )
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        stage_nodes = [label for label in page.pathway_labels if label != "VERIFIED RETURN"]
        self.assertEqual(stage_nodes, ["SINE-1", "SINE-1", "SINE-2"])

    def test_13_scientific_episode_count_uses_raw_identity_not_alias(self) -> None:
        # Two stage rows, same real episode id, two distinct retries --
        # must still count as ONE certified episode identity.
        package = package_with_sine((REAL_SINE_EPISODE_ID,), stages=(1, 1), popup_ids=("popup-a", "popup-b"))
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        episodes_card = next(card for card in page.snapshot_cards if card.label == "Episodes")
        self.assertEqual(episodes_card.value, "1")

    def test_14_provenance_unchanged_by_aliasing(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,))
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        for prov_ref in package.sine_stage_rows[0].provenance:
            self.assertIn(prov_ref, page.provenance)

    def test_12_raw_package_identifiers_unchanged_after_adaptation(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,))
        before = package.sine_stage_rows[0].episode_id
        adapt_certified_report_input(package)
        after = package.sine_stage_rows[0].episode_id
        self.assertEqual(before, after)
        self.assertEqual(after, REAL_SINE_EPISODE_ID)


class OtherOrganIdentifierTests(unittest.TestCase):
    def test_6_long_mine_episode_ids(self) -> None:
        rows = make_mine(2)
        long_rows = tuple(replace(row, episode_id=long_id("mine", row.episode_id)) for row in rows)
        package = replace(make_package(mine=0), mine_episode_rows=long_rows,
                           mine_experiment_scope=make_package(mine=2).mine_experiment_scope)
        model = adapt_certified_report_input(package)
        page = model.organ_page("MINE")
        aliases = {row[0] for row in page.table1.rows}
        self.assertEqual(aliases, {"MINE-15092026-01", "MINE-15092026-02"})
        for row in page.table1.rows:
            self.assertTrue(all(not cell.startswith("mine_") for cell in row))

    def test_7_long_cosine_episode_ids(self) -> None:
        rows = make_cosine(2)
        long_rows = tuple(replace(row, episode_id=long_id("cosine", row.episode_id)) for row in rows)
        package = replace(make_package(cosine=0), cosine_episode_rows=long_rows,
                           cosine_experiment_scope=make_package(cosine=2).cosine_experiment_scope)
        model = adapt_certified_report_input(package)
        page = model.organ_page("COSINE")
        aliases = {row[0] for row in page.table1.rows}
        self.assertEqual(aliases, {"COS-15092026-01", "COS-15092026-02"})

    def test_8_long_cosecant_break_ids(self) -> None:
        rows = make_cosecant(2)
        long_rows = tuple(replace(row, break_id=long_id("cosecant", row.break_id)) for row in rows)
        package = replace(make_package(cosecant=0), cosecant_break_rows=long_rows)
        model = adapt_certified_report_input(package)
        page = model.organ_page("COSECANT")
        aliases = {row[0] for row in page.table1.rows}
        self.assertEqual(aliases, {"CSC-15092026-01", "CSC-15092026-02"})
        for row in page.table2.rows:
            self.assertTrue(row[0].startswith("CSC-"))

    def test_9_alias_uniqueness_with_several_long_ids_coexisting(self) -> None:
        rows = make_mine(5)
        long_rows = tuple(replace(row, episode_id=long_id("mine", f"{i}-shared-prefix")) for i, row in enumerate(rows))
        package = replace(make_package(mine=0), mine_episode_rows=long_rows,
                           mine_experiment_scope=make_package(mine=5).mine_experiment_scope)
        model = adapt_certified_report_input(package)
        page = model.organ_page("MINE")
        aliases = [row[0] for row in page.table1.rows]
        self.assertEqual(len(aliases), len(set(aliases)))


class ContinuationPageTests(unittest.TestCase):
    def test_10_continuation_pages_carry_alias_not_raw_id(self) -> None:
        ids = tuple(long_id("sine", str(i)) for i in range(30))
        package = package_with_sine(ids)
        model = adapt_certified_report_input(package)
        plan = plan_report_pages(model)
        continuation_pages = [p for p in plan.pages if p.kind == "continuation" and p.organ == "SINE" and p.table_number == 2]
        self.assertTrue(continuation_pages)
        for planned in continuation_pages:
            for row in planned.rows:
                self.assertTrue(row[0].startswith("EPI-"))
                for raw in ids:
                    self.assertNotIn(raw, row)


class FullPdfGenerationTests(unittest.TestCase):
    def test_11_full_pdf_generation_no_overflow_with_real_shaped_id(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID, long_id("sine", "second")), stages=(1, 2))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "real_shaped.pdf"
            result = report.generate_report_pdf(package, output)
            self.assertTrue(result.exists())
            from pypdf import PdfReader
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(result)).pages)
            self.assertNotIn(REAL_SINE_EPISODE_ID, text)

    def test_15_report_py_unchanged_since_this_fix(self) -> None:
        # Superseded by the Phase 5 final correction pass, which explicitly
        # reopens report.py for SP14 references and the _small_source_card()
        # visual fit (see test_phase5_final_correction.py for that pass's
        # own hash/content regression coverage) -- this test now only
        # confirms report.py still compiles and importing it still works,
        # rather than asserting byte-identity to a hash this pass is
        # authorized to move past.
        import py_compile
        py_compile.compile(str(_SCIENCE_LAB_DIR / "report.py"), doraise=True)


if __name__ == "__main__":
    unittest.main()
