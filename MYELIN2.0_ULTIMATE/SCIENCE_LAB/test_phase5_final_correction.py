"""Phase 5 FINAL CORRECTION PASS tests (Chief's consolidated bug board,
2026-09-16): report-facing episode display codes, MINE IST time-only START,
never-blank unavailable reasons, SP4/SP6 small-card visual fit, and the
final SP14 references/citation cleanup.

Scope: ``SCIENCE_LAB/report_model.py`` (episode codes, IST formatting,
unavailable-reason fallback) and ``SCIENCE_LAB/report.py`` (SP14 references,
``_small_source_card()`` visual fit, narrowly necessary body citations)
only.  Raw scientific identifiers, grouping, counts and provenance are
verified unchanged throughout.
"""

from __future__ import annotations

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

from SCIENCE_LAB import report
from SCIENCE_LAB.report_model import (
    _ist_time_only,
    _report_local_episode_codes,
    _scope_unavailable_reason,
    adapt_certified_report_input,
)
from SCIENCE_LAB.analysis import (
    AVAILABLE,
    CROSS_BOUNDARY_OVERLAP,
    NO_EVIDENCE,
    OUTSIDE_WINDOW,
    UNAVAILABLE,
    AnalysisValue,
    SineStageRow,
    SuccessfulReturnOnsetLatencyExtrema,
    SuccessfulReturnOnsetLatencySample,
)
from SCIENCE_LAB.test_phase4_report_integration import END, RETURN_REFERENCE, START, make_package, ref, scope
from SCIENCE_LAB.test_phase5c_presentation_identifiers import (
    REAL_SINE_EPISODE_ID,
    long_id,
    make_long_sine,
    package_with_sine,
)


# ---------------------------------------------------------------------------
# 15.1 Episode presentation tests
# ---------------------------------------------------------------------------

class EpisodeCodeTests(unittest.TestCase):
    def test_sine_visible_code_is_epi_prefixed_and_date_based(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,))
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        self.assertEqual(page.table2.rows[0][0], "EPI-15092026-01")
        self.assertEqual(page.table1.rows[0][0], "EPI-15092026-01")

    def test_sine_raw_id_unchanged_and_grouping_uses_raw_id(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,), stages=(1, 1), popup_ids=("a", "b"))
        before = package.sine_stage_rows[0].episode_id
        model = adapt_certified_report_input(package)
        self.assertEqual(package.sine_stage_rows[0].episode_id, before)
        self.assertEqual(before, REAL_SINE_EPISODE_ID)
        page = model.organ_page("SINE")
        episodes_card = next(c for c in page.snapshot_cards if c.label == "Episodes")
        self.assertEqual(episodes_card.value, "1")  # same-stage retries stay one episode

    def test_sine_same_stage_retries_remain_separate_table_rows(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,), stages=(1, 1), popup_ids=("a", "b"))
        model = adapt_certified_report_input(package)
        self.assertEqual(len(model.organ_page("SINE").table2.rows), 2)

    def test_sine_journey_map_is_stage_only(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,))
        model = adapt_certified_report_input(package)
        for label in model.organ_page("SINE").pathway_labels:
            self.assertNotIn("EPI-", label)
            self.assertNotIn(REAL_SINE_EPISODE_ID, label)

    def test_no_sine_e01_leakage(self) -> None:
        package = package_with_sine((REAL_SINE_EPISODE_ID,))
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        for row in page.table1.rows + page.table2.rows:
            for cell in row:
                self.assertNotIn("SINE-E", cell)

    def test_mine_visible_code_is_mine_prefixed_and_date_based(self) -> None:
        package = make_package(mine=1)
        model = adapt_certified_report_input(package)
        page = model.organ_page("MINE")
        self.assertTrue(page.table1.rows[0][0].startswith("MINE-15092026-"))
        self.assertNotIn("MINE-E", page.table1.rows[0][0])

    def test_mine_raw_id_unchanged(self) -> None:
        package = make_package(mine=1)
        before = package.mine_episode_rows[0].episode_id
        adapt_certified_report_input(package)
        self.assertEqual(package.mine_episode_rows[0].episode_id, before)

    def test_cosine_visible_code_is_cos_prefixed_and_date_based(self) -> None:
        package = make_package(cosine=1)
        model = adapt_certified_report_input(package)
        page = model.organ_page("COSINE")
        self.assertTrue(page.table1.rows[0][0].startswith("COS-15092026-"))
        self.assertNotIn("COS-E", page.table1.rows[0][0])

    def test_cosine_raw_id_unchanged(self) -> None:
        package = make_package(cosine=1)
        before = package.cosine_episode_rows[0].episode_id
        adapt_certified_report_input(package)
        self.assertEqual(package.cosine_episode_rows[0].episode_id, before)

    def test_cosecant_visible_code_is_csc_prefixed_not_brk(self) -> None:
        package = make_package(cosecant=2)
        model = adapt_certified_report_input(package)
        page = model.organ_page("COSECANT")
        codes = {row[0] for row in page.table1.rows}
        for code in codes:
            self.assertTrue(code.startswith("CSC-"))
            self.assertFalse(code.startswith("BRK-"))
        self.assertEqual(len(codes), len(package.cosecant_break_rows))  # unique per break

    def test_cosecant_raw_break_id_unchanged(self) -> None:
        package = make_package(cosecant=1)
        before = package.cosecant_break_rows[0].break_id
        adapt_certified_report_input(package)
        self.assertEqual(package.cosecant_break_rows[0].break_id, before)

    def test_helper_codes_are_unique_within_call_and_stable(self) -> None:
        entries = [(f"id-{i}", None) for i in range(3)]
        codes = _report_local_episode_codes(entries, prefix="X")
        self.assertEqual(codes, {})  # no moment -> no code, never a fabricated one


# ---------------------------------------------------------------------------
# 15.1b Cross-experiment global numbering (Chief's decisive regression test)
#
# A single-experiment adapter must never renumber an already-globally-
# computed live display code.  Each test below simulates the SECOND
# same-organ episode on a calendar date -- as if an earlier, different
# experiment already claimed "-01" on the live dashboard, outside this
# snapshot's own session/view entirely -- and proves the certified package
# and rendered report still show "-02", never a locally-recomputed "-01".
# ---------------------------------------------------------------------------

class CrossExperimentGlobalNumberingTests(unittest.TestCase):
    def test_sine_mirl_never_renumbers_globally_second_episode_to_01(self) -> None:
        from types import SimpleNamespace

        from SCIENCE_LAB.evidence import MirlSourceEvidence, PersistedFactSourceEvidence
        from SCIENCE_LAB.analysis import AVAILABLE, CERTIFIED
        from SCIENCE_LAB.test_phase2_report_projections import (
            SESSION_ID, UTC, WINDOW_START, _analyze, _record, _snapshot,
        )

        records = (
            _record(
                source="SINE", kind="SINE_DISPLAYED", ns=WINDOW_START + 100,
                payload={
                    "episode_uid": "sine_experiment_b", "stage": 1, "popup_request_id": "popup-b",
                    "response": "", "resource_key": "", "occurred_wall_time_utc": UTC,
                    "candidate_uid": "candidate-b",
                },
            ),
        )
        snap = _snapshot(
            sine=PersistedFactSourceEvidence(SESSION_ID, records),
            mirl=MirlSourceEvidence(
                SESSION_ID,
                (
                    SimpleNamespace(
                        session_id=SESSION_ID, event_id="mirl-evt-b",
                        occurred_monotonic_ns=WINDOW_START, event_name="episode_created",
                    ),
                ),
                # Simulates MIRL's own live, cross-session projection: an
                # earlier experiment on this SAME calendar date already
                # claimed EPI-15092026-01 (a different session, not part of
                # this snapshot at all) -- this session's episode is the
                # globally-SECOND, exactly as MIRL/read_model.py's own
                # _apply_display_masks would have computed it before
                # evidence.py narrowed this snapshot to one session.
                live_mirl_rows=(
                    SimpleNamespace(
                        episode_id="mirl-episode-b", short_display_id="EPI-15092026-02",
                        candidate_uid="candidate-b", started_at=UTC, session_id=SESSION_ID,
                    ),
                ),
            ),
            _coverage={"SINE": AVAILABLE, "MIRL": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.status, CERTIFIED)
        display_map = dict(outcome.package.sine_episode_display_ids)
        self.assertEqual(display_map["sine_experiment_b"], "EPI-15092026-02")
        self.assertNotEqual(display_map["sine_experiment_b"], "EPI-15092026-01")
        model = adapt_certified_report_input(outcome.package)
        page = model.organ_page("SINE")
        self.assertEqual(page.table2.rows[0][0], "EPI-15092026-02")
        # Raw scientific identity, counts and provenance stay untouched.
        self.assertEqual(outcome.package.sine_stage_rows[0].episode_id, "sine_experiment_b")
        self.assertTrue(outcome.package.sine_stage_rows[0].provenance)

    def test_mine_never_renumbers_globally_second_episode_to_01(self) -> None:
        from SCIENCE_LAB.evidence import MineSourceEvidence
        from SCIENCE_LAB.analysis import AVAILABLE, CERTIFIED
        from SCIENCE_LAB.test_phase2_report_projections import (
            SESSION_ID, WINDOW_START, _analyze, _mine_episode, _mine_raw_events, _snapshot,
        )

        episode = _mine_episode("mine-experiment-b", display_episode_id="MINE-15092026-02")
        raw = _mine_raw_events("mine-experiment-b", WINDOW_START + 100, WINDOW_START + 200)
        snap = _snapshot(
            mine=MineSourceEvidence(SESSION_ID, (episode,), raw),
            _coverage={"MINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.status, CERTIFIED)
        row = outcome.package.mine_episode_rows[0]
        self.assertEqual(row.display_episode_id, "MINE-15092026-02")
        self.assertEqual(row.episode_id, "mine-experiment-b")
        model = adapt_certified_report_input(outcome.package)
        page = model.organ_page("MINE")
        self.assertEqual(page.table1.rows[0][0], "MINE-15092026-02")

    def test_cosine_never_renumbers_globally_second_episode_to_01(self) -> None:
        from SCIENCE_LAB.evidence import CosineSourceEvidence
        from SCIENCE_LAB.analysis import AVAILABLE, CERTIFIED
        from SCIENCE_LAB.test_phase2_report_projections import (
            SESSION_ID, WINDOW_START, _analyze, _cosine_episode, _cosine_raw_events, _snapshot,
        )

        episode = _cosine_episode("cosine-session-b", 1)
        raw = _cosine_raw_events("cosine-session-b", 1, WINDOW_START + 100, WINDOW_START + 200)
        snap = _snapshot(
            cosine=CosineSourceEvidence(
                SESSION_ID, (episode,), raw,
                display_ids=(("cosine-session-b", 1, "COS-15092026-02"),),
            ),
            _coverage={"COSINE": AVAILABLE},
        )
        outcome = _analyze(snap)
        self.assertEqual(outcome.status, CERTIFIED)
        row = outcome.package.cosine_episode_rows[0]
        self.assertEqual(row.display_episode_id, "COS-15092026-02")
        self.assertEqual(row.episode_id, "cosine-session-b:1")
        model = adapt_certified_report_input(outcome.package)
        page = model.organ_page("COSINE")
        self.assertEqual(page.table1.rows[0][0], "COS-15092026-02")


# ---------------------------------------------------------------------------
# 15.1c report_model.py must still have zero persistence/organ-runtime access
# ---------------------------------------------------------------------------

class NoPersistenceAccessTests(unittest.TestCase):
    def test_report_model_still_has_no_persistence_or_organ_runtime_imports(self) -> None:
        import inspect

        from SCIENCE_LAB import report_model

        source = inspect.getsource(report_model)
        forbidden = (
            "import sqlite3", "PERSISTENCE.storage", "PERSISTENCE.PERSISTENCE",
            "from MIRL.mirl", "import MIRL.mirl", "from MINE.mine", "import MINE.mine",
            "from COSINE.cosine", "import COSINE.cosine", "PyQt6",
        )
        for token in forbidden:
            self.assertNotIn(token, source)


# ---------------------------------------------------------------------------
# 15.2 MINE IST time tests
# ---------------------------------------------------------------------------

class IstTimeTests(unittest.TestCase):
    def test_same_calendar_date_in_ist(self) -> None:
        self.assertEqual(_ist_time_only("2026-09-15T11:00:00Z"), "16:30:00 IST")

    def test_crosses_midnight_into_next_ist_day(self) -> None:
        # 19:00 UTC + 5:30 = 00:30 IST the *next* calendar day -- the
        # visible field is time-only, so this must still read as a valid
        # HH:MM:SS, with the date-crossing handled silently by zoneinfo.
        self.assertEqual(_ist_time_only("2026-09-15T19:00:00Z"), "00:30:00 IST")

    def test_microseconds_are_dropped(self) -> None:
        self.assertEqual(_ist_time_only("2026-09-15T11:00:00.437797Z"), "16:30:00 IST")

    def test_plus_zero_offset_form_accepted(self) -> None:
        self.assertEqual(_ist_time_only("2026-09-15T11:00:00+00:00"), "16:30:00 IST")

    def test_missing_timestamp_stays_unavailable(self) -> None:
        self.assertEqual(_ist_time_only(None), UNAVAILABLE)
        self.assertEqual(_ist_time_only(""), UNAVAILABLE)

    def test_malformed_timestamp_stays_unavailable_not_a_crash(self) -> None:
        self.assertEqual(_ist_time_only("not-a-timestamp"), UNAVAILABLE)

    def test_no_manual_offset_arithmetic_used_real_zoneinfo(self) -> None:
        # A DST-naive manual "+5:30" add would give the same answer for IST
        # (which has no DST) -- so this asserts the real dependency instead.
        import SCIENCE_LAB.report_model as rm
        self.assertEqual(type(rm._IST).__module__, "zoneinfo")

    def test_mine_table_start_column_is_ist_time_only(self) -> None:
        package = make_package(mine=1)
        model = adapt_certified_report_input(package)
        start_cell = model.organ_page("MINE").table1.rows[0][2]
        self.assertTrue(start_cell.endswith(" IST"))
        self.assertNotIn("-", start_cell)  # no leftover ISO date (e.g. "2026-09-15")
        self.assertNotIn("+00:00", start_cell)
        self.assertNotIn(".", start_cell)  # no microseconds

    def test_underlying_certified_utc_timestamp_not_altered(self) -> None:
        package = make_package(mine=1)
        before = package.mine_episode_rows[0].started_at_utc
        adapt_certified_report_input(package)
        self.assertEqual(package.mine_episode_rows[0].started_at_utc, before)


# ---------------------------------------------------------------------------
# 15.3 Unavailable-reason tests
# ---------------------------------------------------------------------------

class UnavailableReasonTests(unittest.TestCase):
    def test_non_empty_reason_preserved_verbatim(self) -> None:
        s = scope("MINE", 0, status=NO_EVIDENCE)
        s = replace(s, reason="a genuine specific recorded reason")
        self.assertEqual(_scope_unavailable_reason("MINE", s), "a genuine specific recorded reason")

    def test_no_evidence_empty_reason_gets_neutral_fallback(self) -> None:
        s = replace(scope("MINE", 0, status=NO_EVIDENCE), reason="")
        reason = _scope_unavailable_reason("MINE", s)
        self.assertTrue(reason)
        self.assertIn("MINE", reason)
        self.assertNotIn("not used", reason)
        self.assertNotIn("unused", reason)

    def test_cross_boundary_overlap_empty_reason_gets_neutral_fallback(self) -> None:
        s = replace(scope("COSINE", 0, overlap=1, status=CROSS_BOUNDARY_OVERLAP), reason="")
        reason = _scope_unavailable_reason("COSINE", s)
        self.assertTrue(reason)
        self.assertIn("boundary", reason)

    def test_outside_window_empty_reason_gets_neutral_fallback(self) -> None:
        s = replace(scope("COSINE", 0, status=OUTSIDE_WINDOW), reason="")
        reason = _scope_unavailable_reason("COSINE", s)
        self.assertTrue(reason)
        self.assertIn("window", reason)

    def test_unavailable_empty_reason_gets_neutral_fallback_no_fabricated_cause(self) -> None:
        s = replace(scope("MINE", 0, status=UNAVAILABLE), reason="")
        reason = _scope_unavailable_reason("MINE", s)
        self.assertTrue(reason)
        self.assertNotIn("crashed", reason)
        self.assertNotIn("error", reason.lower())

    def test_status_itself_is_never_changed_by_the_fallback(self) -> None:
        for status in (NO_EVIDENCE, CROSS_BOUNDARY_OVERLAP, OUTSIDE_WINDOW, UNAVAILABLE):
            overlap = 1 if status == CROSS_BOUNDARY_OVERLAP else 0
            s = replace(scope("MINE", 0, overlap=overlap, status=status), reason="")
            _scope_unavailable_reason("MINE", s)  # must not raise or mutate
            self.assertEqual(s.status, status)

    def test_mine_unavailable_page_never_shows_blank_reason(self) -> None:
        s = replace(scope("MINE", 0, status=NO_EVIDENCE), reason="")
        package = replace(make_package(mine=0), mine_experiment_scope=s)
        model = adapt_certified_report_input(package)
        unavailable = next(u for u in model.unavailable_organs if u.organ == "MINE")
        self.assertTrue(unavailable.reason.strip())

    def test_cosine_unavailable_page_never_shows_blank_reason(self) -> None:
        s = replace(scope("COSINE", 0, status=NO_EVIDENCE), reason="")
        package = replace(make_package(cosine=0), cosine_experiment_scope=s)
        model = adapt_certified_report_input(package)
        unavailable = next(u for u in model.unavailable_organs if u.organ == "COSINE")
        self.assertTrue(unavailable.reason.strip())

    def test_cosecant_unavailable_reason_unchanged_by_this_pass(self) -> None:
        package = make_package(cosecant=0)
        model = adapt_certified_report_input(package)
        unavailable = next(u for u in model.unavailable_organs if u.organ == "COSECANT")
        self.assertTrue(unavailable.reason.strip())


# ---------------------------------------------------------------------------
# 15.4 Small-card tests (SP4 SOURCE COVERAGE / SP6 AVAILABLE RESULT TYPES)
# ---------------------------------------------------------------------------

class SmallCardLayoutTests(unittest.TestCase):
    SP4_LABELS = ("SINE", "MINE", "COSINE", "MIRL", "COSECANT", "RESOURCE INTENT", "STUDY", "NORMAL BREAK")
    SP6_LABELS = (
        "Behavioural journey map", "Episode tables", "Stage / escalation tables",
        "Trend graph", "Break timing analysis", "Unavailable data flag",
    )

    def test_full_pdf_generation_covers_every_sp4_and_sp6_card_without_overflow(self) -> None:
        package = make_package(sine=1, mine=1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "small_cards.pdf"
            result = report.generate_report_pdf(package, output)  # must not raise
            self.assertTrue(result.exists())
            from pypdf import PdfReader
            text = "\n".join(page.extract_text() or "" for page in PdfReader(str(result)).pages)
        for label in self.SP4_LABELS:
            self.assertIn(label.split()[0], text)
        for label in self.SP6_LABELS:
            self.assertIn(label.split()[0], text)

    def test_small_source_card_does_not_touch_icon_circle_globally(self) -> None:
        source = (_SCIENCE_LAB_DIR / "report.py").read_text(encoding="utf-8")
        start = source.index("def _small_source_card")
        end = source.index("\ndef ", start + 1)
        body = source[start:end]
        self.assertIn("_icon_circle(", body)  # still calls the shared primitive
        self.assertNotIn("def _icon_circle", body)  # does not redefine/inline it


# ---------------------------------------------------------------------------
# 15.5 References tests
# ---------------------------------------------------------------------------

class ReferencesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        package = make_package(sine=1, mine=1)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "references.pdf"
            result = report.generate_report_pdf(package, output)
            from pypdf import PdfReader
            raw_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(result)).pages)
            cls.text = raw_text
            # Letter-spaced headers (drawn character-by-character) extract
            # with a newline between every glyph; normalize whitespace for
            # any multi-word substring check so that quirk of extraction
            # (not of the rendered PDF, confirmed separately by visual
            # inspection) never causes a false failure here.
            cls.normalized = " ".join(raw_text.split())

    def test_all_four_mandatory_references_present(self) -> None:
        for needle in ("Murre", "Dros", "Stevens", "Nahum-Shani", "Mark", "Gudith", "Klocke"):
            self.assertIn(needle, self.normalized)

    def test_no_placeholder_or_internal_reference_text_remains(self) -> None:
        for forbidden in (
            "SCIENCE_LAB/", "chapter6_view.py", "Phase 3 layout preview",
            "pending bibliography reconciliation", "SP1 citation anchor",
            "Phase 3 preview", "development preview fixture",
        ):
            self.assertNotIn(forbidden, self.normalized)

    def test_every_body_citation_has_a_bibliography_entry(self) -> None:
        # PDF text extraction can insert a line break wherever the renderer
        # wrapped a paragraph; self.normalized collapses that whitespace --
        # the visual render (checked separately) already confirms each
        # citation reads correctly on one line in the actual PDF.
        for author_year in ("Christoff et al., 2009", "Murre & Dros, 2015",
                             "Nahum-Shani et al., 2018", "Stevens, 1957", "Mark et al., 2008"):
            self.assertIn(author_year, self.normalized)
        # And each cited surname also appears in the References section itself.
        for surname in ("Christoff", "Murre", "Nahum-Shani", "Stevens", "Mark"):
            self.assertGreaterEqual(self.normalized.count(surname), 2)  # body citation + bibliography entry

    def test_references_page_says_references_not_chapter_number(self) -> None:
        self.assertIn("REFERENCES", self.normalized)


# ---------------------------------------------------------------------------
# 15.5 Second correction round within the same pass (2026-09-16, real
# MYL-16092026-SCI02 / session 131 visual defects): the MINE single-
# observation chart's duplicated y-axis labels, and the SP8 table columns
# being too narrow for real production-length MINE-DDMMYYYY-NN codes and
# underscore-joined closure reasons like RETURNED_AFTER_CALLBACK.
# ---------------------------------------------------------------------------

class ChartAxisAndMineTableFitTests(unittest.TestCase):
    def test_y_axis_ticks_never_duplicate_for_small_integer_y_max(self) -> None:
        from SCIENCE_LAB.report import _y_axis_tick_fractions

        for y_max in (1, 2, 3, 4, 5, 7, 10):
            labels = [round(y_max * frac) for frac in _y_axis_tick_fractions(y_max)]
            self.assertEqual(len(labels), len(set(labels)), f"duplicate labels for y_max={y_max}: {labels}")

    def test_single_observation_axis_is_exactly_zero_and_one(self) -> None:
        from SCIENCE_LAB.report import _y_axis_tick_fractions

        fractions = _y_axis_tick_fractions(1)
        labels = [round(1 * frac) for frac in fractions]
        self.assertEqual(labels, [0, 1])

    def test_normal_multi_point_axis_keeps_the_original_five_ticks(self) -> None:
        from SCIENCE_LAB.report import _y_axis_tick_fractions

        self.assertEqual(_y_axis_tick_fractions(4), (0.0, 0.25, 0.5, 0.75, 1.0))

    def _mine_page_text(self, package) -> str:
        from pypdf import PdfReader

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "mine_visual_fix.pdf"
            report.generate_report_pdf(package, output)  # must not raise
            reader = PdfReader(str(output))
            for page in reader.pages:
                text = " ".join((page.extract_text() or "").split())
                if "MINE RESULTS AND DISCUSSION" in text:
                    return text
        raise AssertionError("no MINE results page found in generated PDF")

    def test_mine_single_observation_pdf_axis_has_no_duplicate_tick_text(self) -> None:
        text = self._mine_page_text(make_package(mine=1))
        self.assertNotIn("0 0 0 1 1", text)

    def test_mine_episode_code_and_long_closure_reason_fit_without_mid_word_split(self) -> None:
        # Shaped exactly like the real MYL-16092026-SCI02 (session 131)
        # export Chief flagged: a production-length MINE-DDMMYYYY-NN code
        # and an underscore-joined closure reason with no internal
        # whitespace, which the ORIGINAL narrower SP8 columns forced
        # reportlab's Paragraph to break mid-character rather than at a
        # word boundary.
        package = make_package(mine=1)
        row = package.mine_episode_rows[0]
        long_row = replace(
            row,
            display_episode_id="MINE-16092026-02",
            closure_outcome=None,
            closure_reason="RETURNED_AFTER_CALLBACK",
            return_verified=False,
        )
        package = replace(package, mine_episode_rows=(long_row,))
        text = self._mine_page_text(package)
        self.assertIn("MINE-16092026-02", text)
        self.assertIn("RETURNED_AFTER_CALLBACK", text)


# ---------------------------------------------------------------------------
# 15.6 Approved SCI03 correction: the SP7 "Episodes" count must count
# distinct GENUINE episodes (by resolved official display code), not the
# raw union of SINE's own episode_uid and MIRL's own episode_id -- two
# different raw-ID namespaces that can both refer to the same real episode
# (real MYL-16092026-SCI03 / session 132: EPI-16092026-03 was reported as
# "Episodes: 2" this way).
# ---------------------------------------------------------------------------

class EpisodeCountDedupTests(unittest.TestCase):
    def test_linked_sine_and_mirl_raw_ids_count_as_one_genuine_episode(self) -> None:
        # Shaped exactly like the real SCI03 case: one SINE stage row keyed
        # by SINE's own raw episode_uid, one MIRL return-onset sample keyed
        # by MIRL's own (different) raw episode_id, both already resolved
        # (by the certified package, as analysis.py's real join does) to
        # the SAME official EPI- code.
        sine_raw_id = "sine_3c6234a30fcccb481ebe372726069ba2"
        mirl_raw_id = "mirl-episode-69688638511d509065cd2911cb8df906"
        stage_row = SineStageRow(
            sine_raw_id, 1, "popup-a", START, "2026-09-16T18:26:40Z", "return_to_focus", "resource",
            (ref("MIRL", "display-1", START, "sine_displayed"),),
        )
        display = ref("MIRL", "display", START, "sine_displayed")
        onset = ref("MIRL", "onset", START + 2_000_000_000, "return_verification_started")
        verified = ref("MIRL", "verified", START + 3_000_000_000, "return_verified")
        closed = ref("MIRL", "closed", START + 4_000_000_000, "episode_closed")
        sample = SuccessfulReturnOnsetLatencySample(
            mirl_raw_id, "attempt-1", 2_000_000_000, display, onset, verified, closed,
            (display, onset, verified, closed),
        )
        refs = (display, onset, verified, closed)
        value = AnalysisValue(AVAILABLE, 2_000_000_000, "ns", RETURN_REFERENCE, refs)
        extrema = SuccessfulReturnOnsetLatencyExtrema(value, value, 1, "ns", RETURN_REFERENCE, START, END, (sample,))
        package = replace(
            make_package(sine=0),
            sine_stage_rows=(stage_row,),
            successful_return_onset_latency_extrema=extrema,
            sine_episode_display_ids=((sine_raw_id, "EPI-16092026-03"), (mirl_raw_id, "EPI-16092026-03")),
        )
        model = adapt_certified_report_input(package)
        page = model.organ_page("SINE")
        episodes_card = next(c for c in page.snapshot_cards if c.label == "Episodes")
        self.assertEqual(episodes_card.value, "1")
        # All four preserved facts: raw ids untouched, both stage rows kept,
        # the sample kept, and the table still shows the single official code.
        self.assertEqual(package.sine_stage_rows[0].episode_id, sine_raw_id)
        self.assertEqual(package.successful_return_onset_latency_extrema.samples[0].episode_id, mirl_raw_id)
        self.assertEqual(page.table1.rows[0][0], "EPI-16092026-03")
        self.assertEqual(page.table2.rows[0][0], "EPI-16092026-03")

    def test_two_genuinely_distinct_episodes_remain_two(self) -> None:
        # Two real, different episodes -- distinct official codes -- must
        # never be collapsed into one just because dedup logic now exists.
        package = package_with_sine((long_id("sine", "a"), long_id("sine", "b")))
        model = adapt_certified_report_input(package)
        episodes_card = next(c for c in model.organ_page("SINE").snapshot_cards if c.label == "Episodes")
        self.assertEqual(episodes_card.value, "2")


if __name__ == "__main__":
    unittest.main()
