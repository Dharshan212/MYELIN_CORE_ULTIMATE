"""Deterministic Phase-4 adapter, planner, PDF, and isolation tests."""

from __future__ import annotations

import argparse
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
    CERTIFIED,
    CROSS_BOUNDARY_OVERLAP,
    FULLY_CONTAINED,
    NO_EVIDENCE,
    NOT_APPLICABLE,
    OUTSIDE_WINDOW,
    UNAVAILABLE,
    AnalysisValue,
    Chapter3Metric,
    Chapter3ResultPackage,
    CosecantBreakRow,
    CosineEpisodeReportRow,
    EvidenceRef,
    MineEpisodeReportRow,
    OrganExperimentScope,
    SineStageRow,
    SuccessfulReturnOnsetLatencyExtrema,
    SuccessfulReturnOnsetLatencySample,
)
from SCIENCE_LAB.evidence import SourceCoverage
from SCIENCE_LAB.handoff import Chapter3TransferReceipt
from SCIENCE_LAB.report_model import (
    COSECANT_ALREADY_OVER_DELAY_NS,
    COSECANT_FINAL_LOCK_DELAY_NS,
    COSECANT_MINIMUM_BREAK_NS,
    ReportModelError,
    adapt_certified_report_input,
    plan_report_pages,
)
from SCIENCE_LAB import report


START = 1_000_000_000
END = 100_000_000_000_000
RETURN_REFERENCE = (
    "opening MIRL SINE display to return_verification_started for the final "
    "attempt durably linked to return_verified and successful episode_closed"
)


def ref(source: str, durable_id: str, at: int, kind: str) -> EvidenceRef:
    return EvidenceRef(source, durable_id, at, kind)


def empty_extrema() -> SuccessfulReturnOnsetLatencyExtrema:
    value = AnalysisValue(UNAVAILABLE, None, "ns", "no eligible successful return-onset sample")
    return SuccessfulReturnOnsetLatencyExtrema(value, value, 0, "ns", RETURN_REFERENCE, START, END, ())


def make_sine(count: int, *, retry: bool = False):
    stage_rows = []
    samples = []
    for index in range(count):
        base = START + (index + 1) * 10_000_000_000
        episode = f"sine-{index + 1:03d}"
        display = ref("MIRL", f"display-{index}", base, "sine_displayed")
        onset = ref("MIRL", f"onset-{index}", base + 2_000_000_000, "return_verification_started")
        verified = ref("MIRL", f"verified-{index}", base + 3_000_000_000, "return_verified")
        closed = ref("MIRL", f"closed-{index}", base + 4_000_000_000, "episode_closed")
        chain = (display, onset, verified, closed)
        stage = index % 3 + 1
        stage_rows.append(SineStageRow(episode, stage, f"popup-{index}", base, f"2026-09-15T10:{index % 60:02d}:00Z", "", "resource", (display,)))
        samples.append(SuccessfulReturnOnsetLatencySample(episode, f"attempt-{index}", 2_000_000_000, display, onset, verified, closed, chain))
    if retry:
        base = START + 10_000_000_000
        stage_rows.append(SineStageRow("sine-001", 1, "popup-retry", base + 1_000_000, "2026-09-15T10:00:01Z", "RETURN", "resource", (ref("SINE", "retry", base + 1_000_000, "SINE_DISPLAYED"),)))
    if not samples:
        return tuple(stage_rows), empty_extrema()
    refs = tuple(dict.fromkeys(anchor for sample in samples for anchor in sample.supporting_event_chain))
    value = AnalysisValue(AVAILABLE, 2_000_000_000, "ns", RETURN_REFERENCE, refs)
    extrema = SuccessfulReturnOnsetLatencyExtrema(value, value, len(samples), "ns", RETURN_REFERENCE, START, END, tuple(samples))
    return tuple(stage_rows), extrema


def make_mine(count: int):
    rows = []
    for index in range(count):
        start = START + (index + 1) * 20_000_000_000
        branch = "I_WILL_COME_BACK" if index % 2 == 0 else "ITS_IMPORTANT"
        rows.append(MineEpisodeReportRow(
            f"mine-{index + 1:03d}", f"MINE-15092026-{index + 1:02d}", branch, None if index % 2 == 0 else 15,
            "RETURNED", "return_verified", True, f"2026-09-15T11:{index % 60:02d}:00Z",
            f"2026-09-15T11:{index % 60:02d}:30Z", start, start + 5_000_000_000,
            (ref("MINE", f"mine-ref-{index}", start, "MINE_EPISODE"),),
        ))
    return tuple(rows)


def make_cosine(count: int, *, all_durations: bool = False):
    rows = []
    for index in range(count):
        start = START + (index + 1) * 30_000_000_000
        choice = "CHOSEN_WATCH" if all_durations or index % 2 == 1 else "RETURN_INTENT"
        chosen_minutes = 20 + (index % 3) * 5 if all_durations else (None if index % 2 == 0 else 20)
        rows.append(CosineEpisodeReportRow(
            f"cosine-{index + 1:03d}", f"COS-15092026-{index + 1:02d}", "prime", "Prime Video", choice,
            chosen_minutes, index % 3, "CLOSED", "returned_from_ott",
            f"2026-09-15T12:{index % 60:02d}:00Z", f"2026-09-15T12:{index % 60:02d}:30Z",
            start, start + 5_000_000_000, (ref("COSINE", f"cosine-ref-{index}", start, "COSINE_EPISODE"),),
        ))
    return tuple(rows)


def make_cosecant(count: int, *, latency_status: str = AVAILABLE):
    rows = []
    for index in range(count):
        start = START + 40_000_000_000 + index * 480_000_000_000
        complete = start + COSECANT_MINIMUM_BREAK_NS
        reminder = None
        final_lock = None
        if latency_status == AVAILABLE:
            if index % 3 == 0:
                confirmed = complete + 3_000_000_000
            elif index % 3 == 1:
                reminder = complete + COSECANT_ALREADY_OVER_DELAY_NS
                confirmed = reminder + 3_000_000_000
            else:
                reminder = complete + COSECANT_ALREADY_OVER_DELAY_NS
                final_lock = reminder + COSECANT_FINAL_LOCK_DELAY_NS
                confirmed = final_lock + 3_000_000_000
            latency, reason = confirmed - complete, "BREAK_COMPLETE to RETURN_CONFIRMED"
        elif latency_status == NOT_APPLICABLE:
            confirmed, latency, reason = start + 1_000_000_000, None, "returned before break completion"
        else:
            confirmed, latency, reason = None, None, "no factual RETURN_CONFIRMED"
            reminder = complete + COSECANT_ALREADY_OVER_DELAY_NS
            if index % 2 == 1:
                final_lock = reminder + COSECANT_FINAL_LOCK_DELAY_NS
        anchor = ref("COSECANT", f"break-ref-{index}", start, "BREAK_STARTED")
        rows.append(CosecantBreakRow(
            f"break-{index + 1:03d}", start, complete,
            reminder, final_lock,
            confirmed, latency, latency_status, reason, (anchor,),
        ))
    return tuple(rows)


def scope(source: str, count: int, *, overlap: int = 0, status: str | None = None) -> OrganExperimentScope:
    if status is None:
        status = FULLY_CONTAINED if count else (CROSS_BOUNDARY_OVERLAP if overlap else OUTSIDE_WINDOW)
    provenance = (ref(source, f"{source.lower()}-overlap", START + 1, "CROSS_BOUNDARY_OVERLAP"),) if overlap else ()
    reason = "fully-contained rows available" if count else ("episode crossed experiment boundary" if overlap else "no episode in selected experiment")
    return OrganExperimentScope(source, status, count, overlap, 0 if count or overlap else 1, reason, provenance)


def make_package(
    *, experiment_id: str = "MYL-15092026-SCI01", sine: int = 0, mine: int = 0,
    cosine: int = 0, cosecant: int = 0, mine_overlap: int = 0,
    cosine_overlap: int = 0, retry: bool = False, cosecant_latency: str = AVAILABLE,
    cosine_all_durations: bool = False,
) -> Chapter3ResultPackage:
    sine_rows, extrema = make_sine(sine, retry=retry)
    mine_rows = make_mine(mine)
    cosine_rows = make_cosine(cosine, all_durations=cosine_all_durations)
    cosecant_rows = make_cosecant(cosecant, latency_status=cosecant_latency)
    coverage = tuple(
        SourceCoverage(name, AVAILABLE if count else NO_EVIDENCE, "certified rows present" if count else "no matching evidence", count)
        for name, count in (
            ("SINE", len(sine_rows)), ("MIRL", len(extrema.samples)), ("MINE", len(mine_rows)),
            ("COSINE", len(cosine_rows)), ("COSECANT", len(cosecant_rows)),
        )
    )
    metrics = (Chapter3Metric("relapses", "Relapses", AVAILABLE, 0, "count", "certified MIRL relapse count"),)
    package_ref = ref("SCIENCE_LAB_EXPERIMENT", experiment_id, START, "COMPLETED_EXPERIMENT_WINDOW")
    sine_episode_ids = tuple(dict.fromkeys(
        [row.episode_id for row in sine_rows] + [sample.episode_id for sample in extrema.samples]
    ))
    sine_episode_display_ids = tuple(
        (episode_id, f"EPI-15092026-{index + 1:02d}")
        for index, episode_id in enumerate(sine_episode_ids)
    )
    return Chapter3ResultPackage(
        experiment_id, 42, "2026-09-15T10:00:00Z", "2026-09-15T14:00:00Z", START, END,
        "2026-09-15T14:00:01Z", coverage, (), metrics, (), (), (), (), (package_ref,), CERTIFIED,
        extrema, sine_rows, mine_rows, cosine_rows, cosecant_rows,
        scope("MINE", len(mine_rows), overlap=mine_overlap),
        scope("COSINE", len(cosine_rows), overlap=cosine_overlap),
        sine_episode_display_ids,
    )


def page_count(pdf_path: Path) -> int:
    from pypdf import PdfReader
    return len(PdfReader(str(pdf_path)).pages)


class Phase4ReportModelTests(unittest.TestCase):
    def test_organ_combination_page_counts(self):
        # Study anatomy adds one page; legacy packages also disclose SECANT
        # as unavailable, including when all four older organs have results.
        cases = ((1, 1, 1, 1, 17), (1, 1, 1, 0, 16), (1, 1, 0, 0, 15), (1, 0, 0, 0, 14), (0, 0, 0, 0, 13))
        for sine, mine, cosine, cosecant, expected in cases:
            model = adapt_certified_report_input(make_package(sine=sine, mine=mine, cosine=cosine, cosecant=cosecant))
            self.assertEqual(len(plan_report_pages(model).pages), expected)

    def test_overlap_only_and_mixed_disclosure(self):
        overlap = adapt_certified_report_input(make_package(mine_overlap=1, cosine_overlap=1))
        self.assertEqual({item.status for item in overlap.unavailable_organs if item.organ in {"MINE", "COSINE"}}, {CROSS_BOUNDARY_OVERLAP})
        mixed = adapt_certified_report_input(make_package(mine=2, cosine=1, mine_overlap=1, cosine_overlap=1))
        self.assertIn("2 complete episode(s) analysed; 1 overlapping", mixed.organ_page("MINE").overlap_note)
        self.assertIn("1 complete episode(s) analysed; 1 overlapping", mixed.organ_page("COSINE").overlap_note)

    def test_same_stage_retry_is_not_collapsed(self):
        model = adapt_certified_report_input(make_package(sine=1, retry=True))
        self.assertEqual(len(model.organ_page("SINE").table2.rows), 2)

    def test_cosecant_latency_states_never_become_zero(self):
        early = adapt_certified_report_input(make_package(cosecant=1, cosecant_latency=NOT_APPLICABLE))
        self.assertIn("NOT APPLICABLE", early.organ_page("COSECANT").table1.rows[0][-1])
        missing = adapt_certified_report_input(make_package(cosecant=1, cosecant_latency=UNAVAILABLE))
        self.assertIn("UNAVAILABLE", missing.organ_page("COSECANT").table1.rows[0][-1])

    def test_cosecant_temporal_integrity_rejects_impossible_sequences(self):
        immediate, reminder_path, final_path = make_cosecant(3)
        malformed = {
            "break_below_frozen_minimum": replace(
                immediate,
                break_complete_monotonic_ns=immediate.break_started_monotonic_ns + COSECANT_MINIMUM_BREAK_NS - 1,
                return_confirmed_monotonic_ns=immediate.break_started_monotonic_ns + COSECANT_MINIMUM_BREAK_NS + 2_999_999_999,
            ),
            "five_seconds_is_not_five_minutes": replace(
                immediate,
                break_already_over_monotonic_ns=immediate.break_complete_monotonic_ns + 5_000_000_000,
            ),
            "reminder_after_return": replace(
                immediate,
                break_already_over_monotonic_ns=immediate.break_complete_monotonic_ns + COSECANT_ALREADY_OVER_DELAY_NS,
            ),
            "final_lock_requires_reminder": replace(
                immediate,
                final_locked_monotonic_ns=immediate.break_complete_monotonic_ns + COSECANT_ALREADY_OVER_DELAY_NS + COSECANT_FINAL_LOCK_DELAY_NS,
            ),
            "final_lock_requires_full_subsequent_minute": replace(
                final_path,
                final_locked_monotonic_ns=final_path.break_already_over_monotonic_ns + COSECANT_FINAL_LOCK_DELAY_NS - 1,
            ),
            "latency_must_equal_certified_anchor_difference": replace(
                reminder_path,
                post_break_return_latency_ns=reminder_path.post_break_return_latency_ns - 1,
            ),
        }
        for name, row in malformed.items():
            with self.subTest(name=name), self.assertRaises(ReportModelError):
                adapt_certified_report_input(replace(make_package(cosecant=1), cosecant_break_rows=(row,)))

        early = make_cosecant(1, latency_status=NOT_APPLICABLE)[0]
        early_with_escalation = replace(
            early,
            break_already_over_monotonic_ns=early.break_complete_monotonic_ns + COSECANT_ALREADY_OVER_DELAY_NS,
        )
        with self.assertRaises(ReportModelError):
            adapt_certified_report_input(
                replace(make_package(cosecant=1, cosecant_latency=NOT_APPLICABLE), cosecant_break_rows=(early_with_escalation,))
            )

    def test_optional_unsupported_fields_stay_unavailable(self):
        model = adapt_certified_report_input(make_package(mine=1, cosine=1))
        mine_cards = {card.label: card.value for card in model.organ_page("MINE").snapshot_cards}
        cosine_cards = {card.label: card.value for card in model.organ_page("COSINE").snapshot_cards}
        self.assertEqual(mine_cards["MINE-1 displays"], UNAVAILABLE)
        self.assertEqual(mine_cards["Final callbacks"], UNAVAILABLE)
        self.assertEqual(cosine_cards["Intention checks"], UNAVAILABLE)
        self.assertEqual(cosine_cards["Callbacks"], UNAVAILABLE)

    def test_long_tables_insert_immediate_continuations(self):
        model = adapt_certified_report_input(make_package(sine=40, mine=40, cosine=40, cosecant=40))
        plan = plan_report_pages(model)
        for organ in ("SINE", "MINE", "COSINE", "COSECANT"):
            index = next(i for i, item in enumerate(plan.pages) if item.kind == "organ" and item.organ == organ)
            self.assertEqual(plan.pages[index + 1].kind, "continuation")
            self.assertEqual(plan.pages[index + 1].organ, organ)

    def test_sequential_experiments_do_not_contaminate(self):
        first = adapt_certified_report_input(make_package(experiment_id="EXP-A", mine=2))
        second = adapt_certified_report_input(make_package(experiment_id="EXP-B", cosine=1))
        self.assertEqual(first.parent_session_id, second.parent_session_id)
        self.assertIsNotNone(first.organ_page("MINE"))
        self.assertIsNone(second.organ_page("MINE"))
        self.assertIsNotNone(second.organ_page("COSINE"))
        self.assertNotEqual(first.experiment_id, second.experiment_id)

    def test_stale_receipt_identity_is_rejected(self):
        package = make_package(sine=1)
        receipt = Chapter3TransferReceipt(package, package.experiment_id, package.parent_session_id, "2026-09-15T15:00:00Z")
        object.__setattr__(receipt, "experiment_id", "STALE")
        with self.assertRaises(ReportModelError):
            adapt_certified_report_input(receipt)

    def test_cross_session_receipt_is_rejected(self):
        package = make_package(sine=1)
        receipt = Chapter3TransferReceipt(package, package.experiment_id, package.parent_session_id, "2026-09-15T15:00:00Z")
        object.__setattr__(receipt, "parent_session_id", package.parent_session_id + 1)
        with self.assertRaises(ReportModelError):
            adapt_certified_report_input(receipt)

    def test_malformed_or_uncertified_input_is_rejected(self):
        with self.assertRaises(ReportModelError):
            adapt_certified_report_input(replace(make_package(), analysis_status="DRAFT"))
        with self.assertRaises(ReportModelError):
            adapt_certified_report_input(replace(make_package(), experiment_id=""))

    def test_renderer_has_no_direct_persistence_or_sqlite_import(self):
        source = Path(report.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import sqlite3", source)
        self.assertNotIn("from PERSISTENCE", source)


class Phase4PdfTests(unittest.TestCase):
    def test_dynamic_chart_titles_and_overall_card_obey_audit_rules(self):
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "chart-laws.pdf"
            report.generate_report_pdf(make_package(sine=1, mine=1, cosine=1, cosecant=1), output)
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(output)).pages)
            self.assertIn("OVERALL EXPERIMENT", text)
            self.assertNotIn("MIRL / OVERALL", text)
            self.assertIn("SINE | SINGLE CERTIFIED OBSERVATION", text)
            self.assertIn("MINE BRANCH DISTRIBUTION | SINGLE CERTIFIED OBSERVATION", text)
            self.assertIn("COSECANT | SINGLE CERTIFIED OBSERVATION", text)
            self.assertNotIn("SINE TREND GRAPH", text)
            self.assertNotIn("MINE TREND GRAPH", text)
            self.assertNotIn("COSECANT TREND GRAPH", text)

    def test_large_chart_tick_labels_are_thinned_without_dropping_points(self):
        indices = report._visible_chart_tick_indices(80, 6)
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[-1], 79)
        self.assertLessEqual(len(indices), 6)
        model = adapt_certified_report_input(
            make_package(sine=80, cosine=80, cosecant=80, cosine_all_durations=True)
        )
        for organ in ("SINE", "COSINE", "COSECANT"):
            self.assertEqual(len(model.organ_page(organ).chart.values), 80)

    def test_required_volume_matrix_preserves_rows_and_renders(self):
        volumes = (0, 1, 2, 5, 10, 20, 40, 80)
        with tempfile.TemporaryDirectory() as directory:
            for organ in ("SINE", "MINE", "COSINE", "COSECANT"):
                for count in volumes:
                    with self.subTest(organ=organ, count=count):
                        options = {organ.lower(): count}
                        if organ == "COSINE":
                            options["cosine_all_durations"] = True
                        model = adapt_certified_report_input(make_package(**options))
                        plan = plan_report_pages(model)
                        organ_page = model.organ_page(organ)
                        if count == 0:
                            self.assertIsNone(organ_page)
                        else:
                            self.assertIsNotNone(organ_page)
                            continued = sum(
                                len(page.rows)
                                for page in plan.pages
                                if page.kind == "continuation" and page.organ == organ and page.table_number == 1
                            )
                            self.assertEqual(min(2, len(organ_page.table1.rows)) + continued, count)
                        output = Path(directory) / f"{organ.lower()}-{count}.pdf"
                        report.generate_report_pdf(make_package(**options), output)
                        self.assertEqual(page_count(output), len(plan.pages))

    def test_integration_generation_does_not_use_dev_fixture_fallback(self):
        original = report._build_dev_fixtures
        report._build_dev_fixtures = lambda: (_ for _ in ()).throw(AssertionError("dev fallback called"))
        try:
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "integration.pdf"
                report.generate_report_pdf(make_package(sine=1, mine=1), output)
                self.assertEqual(page_count(output), 15)
        finally:
            report._build_dev_fixtures = original

    def test_integration_pdf_contains_no_phase3_placeholders(self):
        from pypdf import PdfReader
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "all-four.pdf"
            report.generate_report_pdf(make_package(sine=1, mine=1, cosine=1, cosecant=1), output)
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(output)).pages)
            for forbidden in ("CERTIFIED VALUE", "EPISODE ID", "[X]", "[Y]", "development preview fixture"):
                self.assertNotIn(forbidden, text)
            self.assertEqual(page_count(output), 17)

    def test_failed_generation_preserves_prior_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "prior.pdf"
            output.write_bytes(b"prior-valid-content")
            with self.assertRaises(ReportModelError):
                report.generate_report_pdf(replace(make_package(), analysis_status="DRAFT"), output)
            self.assertEqual(output.read_bytes(), b"prior-valid-content")


SCENARIOS = {
    "phase4_all_four": dict(sine=1, mine=1, cosine=1, cosecant=1),
    "phase4_two_organs": dict(sine=2, cosecant=2),
    "phase4_overlap_only": dict(mine_overlap=1, cosine_overlap=1),
    "phase4_mixed_overlap": dict(mine=2, cosine=1, mine_overlap=1, cosine_overlap=1),
    "phase4_long_tables": dict(sine=40, mine=40, cosine=40, cosecant=40, cosine_all_durations=True),
}


def write_previews(output_directory: Path) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    for name, options in SCENARIOS.items():
        output = output_directory / f"{name}.pdf"
        report.generate_report_pdf(make_package(experiment_id=name.upper(), **options), output)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        print(f"{output}|pages={page_count(output)}|sha256={digest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--write-previews", action="store_true")
    args, remaining = parser.parse_known_args()
    if args.write_previews:
        write_previews(_PROJECT_ROOT / "output" / "pdf")
    else:
        unittest.main(argv=[sys.argv[0], *remaining])
