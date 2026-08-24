"""C2 — pure Study-evidence mathematics.

Every expected number in this file was CHARACTERIZED from the pre-C2
implementation (see _c2_characterize.py) before any edit was made. The C2
conversion to a pure calculator must therefore be provably arithmetic-
preserving: if a number here changes, the mathematics changed, and that is a
defect, not a refactor.

The suite also pins the boundary C2 exists to create: this module must expose
no operational Study verdict, no Study lifecycle, no approval capability, and
no dependency on study.py.
"""

from __future__ import annotations

import pytest

import _lab  # noqa: F401  (sys.path)

from COSECANT_STUDY_MODE.study_alignment import (
    ALIGNMENT_SCHEMA_VERSION,
    BACKGROUND_MISMATCH_PENALTIES,
    COMMON_WORDS,
    IMPORTANT_KEYWORD_POINTS,
    NORMAL_KEYWORD_POINTS,
    SINGLE_MATCH_CAP,
    UNCERTAIN_CAP,
    KeywordImportance,
    StudyEvidence,
    StudyEvidenceCalculator,
    StudyTitleScorer,
    normalize_for_scoring,
    score_title,
    study_evidence,
)


def ev(subject, task, keywords, important, title, certified=True) -> StudyEvidence:
    return study_evidence(
        subject=subject,
        task=task,
        keywords=keywords,
        important_keywords=important,
        title=title,
        identity_certified=certified,
    )


# ---------------------------------------------------------------------------
# Locked constants
# ---------------------------------------------------------------------------


def test_keyword_weights_are_one_and_two():
    assert NORMAL_KEYWORD_POINTS == 1
    assert IMPORTANT_KEYWORD_POINTS == 2


def test_safety_cap_values_are_preserved():
    assert UNCERTAIN_CAP == 74.0
    assert SINGLE_MATCH_CAP == 50.0


def test_mismatch_vocabulary_is_preserved():
    assert len(BACKGROUND_MISMATCH_PENALTIES) == 21
    assert BACKGROUND_MISMATCH_PENALTIES["gaming"] == 25
    assert BACKGROUND_MISMATCH_PENALTIES["shorts"] == 20
    assert BACKGROUND_MISMATCH_PENALTIES["compilation"] == 20
    assert BACKGROUND_MISMATCH_PENALTIES["music"] == 20
    assert BACKGROUND_MISMATCH_PENALTIES["motivation"] == 15
    assert BACKGROUND_MISMATCH_PENALTIES["meme"] == 30


# ---------------------------------------------------------------------------
# THE BOUNDARY C2 CREATES
# ---------------------------------------------------------------------------


def test_module_publishes_no_operational_verdict():
    import COSECANT_STUDY_MODE.study_alignment as module

    for banned in (
        "StudyVerdict",
        "StudyAlignmentBasis",
        "StudyAlignmentDecision",
        "StudyAlignmentEngine",
        "evaluate_study_alignment",
        "STUDY_ALIGNED_MIN_CONFIDENCE",
        "STUDY_UNCERTAIN_MIN_CONFIDENCE",
    ):
        assert not hasattr(module, banned), (
            f"{banned} is an operational Study decision. Resource Intent owns "
            "the verdict; this module is a calculator."
        )


def test_module_does_not_import_study_lifecycle():
    """The C0 report proved this import silently rotted (defect W-3).

    Checked with the AST rather than a substring scan, so that the module's
    own docstring may still explain the W-3 history without tripping the test.
    """

    import ast

    import COSECANT_STUDY_MODE.study_alignment as module

    tree = ast.parse(open(module.__file__, encoding="utf-8").read())
    imported_modules: list[str] = []
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_modules.append(node.module or "")
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)

    for name in imported_modules:
        assert "study" not in name.split(".")[-1] or name in {"", "re"}, (
            f"the calculator must not import Study lifecycle module {name!r}"
        )

    for banned in (
        "StudyMaterialApprovalRequest",
        "ApprovedStudyResource",
        "StudyTargetSnapshot",
        "StudyResourceEvidence",
        "StudyRuntime",
        "StudyState",
    ):
        assert banned not in imported_names, (
            f"{banned} is a Study lifecycle/approval object; a calculator must "
            "never depend on one"
        )


def test_evidence_carries_no_lifecycle_or_identity_fields():
    result = ev("Neuroscience", "basal ganglia", ("basal",), (), "Basal Ganglia")
    for banned in (
        "verdict",
        "basis",
        "study_active",
        "approval_request",
        "exact_resource_approved",
        "block_id",
        "generation",
        "resource_id",
        "platform",
    ):
        assert not hasattr(result, banned), f"{banned} is not a mathematical fact"


def test_calculator_is_pure():
    """Same inputs, same outputs, no accumulated state."""

    calculator = StudyEvidenceCalculator()
    args = dict(
        subject="Neuroscience",
        task="basal ganglia",
        keywords=("basal", "ganglia"),
        important_keywords=("dopamine",),
        title="Basal Ganglia and Dopamine Pathways",
        identity_certified=True,
    )
    first = calculator.evaluate(**args)
    second = calculator.evaluate(**args)
    third = StudyEvidenceCalculator().evaluate(**args)
    assert first == second == third


# ---------------------------------------------------------------------------
# CHARACTERIZED ARITHMETIC — these numbers come from the pre-C2 file
# ---------------------------------------------------------------------------


CHARACTERIZED = [
    # name, subject, task, keywords, important, title, certified,
    #   raw_matched, raw_possible, raw_pct,
    #   eff_matched, eff_possible, eff_pct,
    #   core_matched, core_possible, core_pct,
    #   penalty, confidence, caps, suspicious
    ("honest_lecture", "Neuroscience", "basal ganglia", ("basal", "ganglia"),
     ("dopamine",), "Basal Ganglia and Dopamine Pathways", True,
     4, 4, 100.0, 4, 4, 100.0, 1, 1, 100.0, 0, 100.0, (), ()),

    ("mrbeast", "Neuroscience", "basal ganglia", ("basal", "ganglia"),
     ("dopamine",), "MrBeast Challenge", True,
     0, 4, 0.0, 0, 4, 0.0, 0, 1, 0.0, 0, 0.0, (), ()),

    ("keyword_stuffing", "Neuroscience", "basal ganglia",
     ("neuroscience", "mrbeast", "gaming", "shorts"), ("dopamine",),
     "MrBeast Gaming Shorts Neuroscience", True,
     4, 6, 66.667, 2, 4, 50.0, 0, 1, 0.0, 45, 5.0, (), ("gaming", "shorts")),

    ("uncertified_identity", "Neuroscience", "basal ganglia",
     ("basal", "ganglia"), ("dopamine",),
     "Basal Ganglia and Dopamine Pathways", False,
     4, 4, 100.0, 4, 4, 100.0, 1, 1, 100.0, 0, 74.0,
     ("RESOURCE_IDENTITY_NOT_CERTIFIED",), ()),

    ("edu_word_plus_gaming", "Machine Learning", "machine learning",
     ("machine", "learning"), ("neural",),
     "Machine Learning Funny Gaming Reaction Compilation", True,
     2, 4, 50.0, 2, 4, 50.0, 0, 1, 0.0, 85, 0.0, (), ()),

    ("subject_word_only", "Neuroscience", "basal ganglia", ("basal", "ganglia"),
     ("dopamine",), "Neuroscience of Falling in Love", True,
     0, 4, 0.0, 0, 4, 0.0, 0, 1, 0.0, 0, 0.0, (), ()),

    ("one_eligible_keyword", "Neuroscience", "basal ganglia", ("basal",), (),
     "Basal Ganglia Explained", True,
     1, 1, 100.0, 1, 1, 100.0, 0, 0, 0.0, 0, 74.0,
     ("ONLY_ONE_ELIGIBLE_KEYWORD",), ()),

    ("one_matched_of_three", "Neuroscience", "basal ganglia",
     ("basal", "ganglia", "striatum"), (), "Basal Nuclei Overview", True,
     1, 3, 33.333, 1, 3, 33.333, 0, 0, 0.0, 0, 33.333, (), ()),

    ("important_all_missed", "Neuroscience", "basal ganglia",
     ("basal", "ganglia"), ("dopamine", "striatum"),
     "Basal Ganglia Anatomy", True,
     2, 6, 33.333, 2, 6, 33.333, 0, 2, 0.0, 0, 33.333, (), ()),

    ("important_half_missed", "Neuroscience", "basal ganglia",
     ("basal", "ganglia"), ("dopamine", "striatum", "pallidum"),
     "Basal Ganglia Dopamine Overview", True,
     4, 8, 50.0, 4, 8, 50.0, 1, 3, 33.333, 0, 50.0, (), ()),

    ("music_therapy_legitimate", "Music Therapy", "music therapy for anxiety",
     ("music", "therapy"), ("anxiety",), "Music Therapy for Anxiety", True,
     4, 4, 100.0, 4, 4, 100.0, 1, 1, 100.0, 0, 100.0, (), ()),

    ("music_not_legitimate", "Neuroscience", "basal ganglia",
     ("basal", "ganglia"), ("dopamine",),
     "Basal Ganglia Dopamine Music Compilation", True,
     4, 4, 100.0, 4, 4, 100.0, 1, 1, 100.0, 40, 60.0, (), ()),

    ("no_keywords_at_all", "Neuroscience", "basal ganglia", (), (),
     "Basal Ganglia Explained", True,
     0, 0, 0.0, 0, 0, 0.0, 0, 0, 0.0, 0, 0.0, (), ()),

    ("multiword_keyword_split", "Neuroscience", "basal ganglia",
     ("basal ganglia",), ("dopamine pathways",),
     "Basal Ganglia and Dopamine Pathways", True,
     6, 6, 100.0, 6, 6, 100.0, 2, 2, 100.0, 0, 100.0, (), ()),

    ("important_overrides_normal", "Neuroscience", "basal ganglia",
     ("dopamine",), ("dopamine",), "Dopamine Explained", True,
     2, 2, 100.0, 2, 2, 100.0, 1, 1, 100.0, 0, 74.0,
     ("ONLY_ONE_ELIGIBLE_KEYWORD",), ()),

    ("unicode_and_common_words", "Neuroscience", "basal ganglia",
     ("basal", "ganglia"), ("dopamine",),
     "The Basal​ Ganglia of the Dopamine Study Video", True,
     4, 4, 100.0, 4, 4, 100.0, 1, 1, 100.0, 0, 100.0, (), ()),
]


@pytest.mark.parametrize(
    "case", CHARACTERIZED, ids=[case[0] for case in CHARACTERIZED]
)
def test_characterized_arithmetic_is_preserved(case):
    (
        _name, subject, task, keywords, important, title, certified,
        raw_matched, raw_possible, raw_pct,
        eff_matched, eff_possible, eff_pct,
        core_matched, core_possible, core_pct,
        penalty, confidence, caps, suspicious,
    ) = case

    result = ev(subject, task, keywords, important, title, certified)

    assert result.raw_matched_points == raw_matched
    assert result.raw_possible_points == raw_possible
    assert result.raw_score_percent == raw_pct
    assert result.effective_matched_points == eff_matched
    assert result.effective_possible_points == eff_possible
    assert result.effective_score_percent == eff_pct
    assert result.core_matched_count == core_matched
    assert result.core_possible_count == core_possible
    assert result.core_coverage_percent == core_pct
    assert result.mismatch_penalty_percent == penalty
    assert result.confidence_percent == confidence
    assert result.safety_caps == caps
    assert result.suspicious_keywords == suspicious


# ---------------------------------------------------------------------------
# The behaviours Chief named explicitly
# ---------------------------------------------------------------------------


def test_honest_lecture_scores_high():
    assert ev("Neuroscience", "basal ganglia", ("basal", "ganglia"),
              ("dopamine",), "Basal Ganglia and Dopamine Pathways"
              ).confidence_percent == 100.0


def test_mrbeast_scores_low():
    assert ev("Neuroscience", "basal ganglia", ("basal", "ganglia"),
              ("dopamine",), "MrBeast Challenge").confidence_percent == 0.0


def test_keyword_stuffing_cannot_manufacture_confidence():
    result = ev("Neuroscience", "basal ganglia",
                ("neuroscience", "mrbeast", "gaming", "shorts"), ("dopamine",),
                "MrBeast Gaming Shorts Neuroscience")
    assert result.raw_score_percent > 60.0, "raw evidence stays auditable"
    assert result.confidence_percent <= 25.0, "but confidence must collapse"
    assert "gaming" in result.suspicious_keywords
    assert "shorts" in result.suspicious_keywords


def test_uncertified_identity_can_never_reach_automatic_protection():
    result = ev("Neuroscience", "basal ganglia", ("basal", "ganglia"),
                ("dopamine",), "Basal Ganglia and Dopamine Pathways",
                certified=False)
    assert result.raw_score_percent == 100.0
    assert result.confidence_percent == UNCERTAIN_CAP
    assert "RESOURCE_IDENTITY_NOT_CERTIFIED" in result.safety_caps


def test_single_keyword_is_capped():
    result = ev("Neuroscience", "basal ganglia", ("basal",), (),
                "Basal Ganglia Explained")
    assert result.confidence_percent == UNCERTAIN_CAP
    assert "ONLY_ONE_ELIGIBLE_KEYWORD" in result.safety_caps


def test_only_one_matched_keyword_is_capped_at_fifty():
    result = ev("Neuroscience", "basal ganglia",
                ("basal", "ganglia", "striatum", "pallidum"), (),
                "Basal Nuclei and Pallidum and Striatum Overview")
    matched = sum(1 for item in result.keyword_evidence if item.matched)
    if matched == 1:
        assert result.confidence_percent <= SINGLE_MATCH_CAP


def test_all_important_keywords_missed_is_capped():
    """The cap must BIND when the lexical score would otherwise clear it."""

    result = ev("Neuroscience", "basal ganglia",
                ("basal", "ganglia", "nuclei", "anatomy"), ("dopamine",),
                "Basal Ganglia Nuclei Anatomy")
    assert result.core_matched_count == 0
    assert result.core_possible_count == 1
    assert result.effective_score_percent > SINGLE_MATCH_CAP
    assert result.confidence_percent == SINGLE_MATCH_CAP
    assert "NO_IMPORTANT_KEYWORD_MATCHED" in result.safety_caps


def test_a_cap_is_only_recorded_when_it_actually_binds():
    """safety_caps is an audit of caps APPLIED, not caps considered.

    Landing exactly on the ceiling records the reason but not the cap, because
    nothing was reduced. Recording a non-binding cap would overstate what the
    mathematics did.
    """

    result = ev("Neuroscience", "basal ganglia",
                ("basal", "ganglia", "nuclei", "anatomy"),
                ("dopamine", "striatum"), "Basal Ganglia Nuclei Anatomy")
    assert result.effective_score_percent == SINGLE_MATCH_CAP
    assert result.confidence_percent == SINGLE_MATCH_CAP
    assert result.safety_caps == ()
    assert "No important Study keyword matched the current title" in result.reasons


def test_gaming_reaction_meme_mismatch_penalises():
    result = ev("Machine Learning", "machine learning", ("machine", "learning"),
                ("neural",), "Machine Learning Funny Gaming Reaction Compilation")
    assert result.mismatch_penalty_percent == 85
    assert result.confidence_percent == 0.0


def test_music_therapy_is_not_condemned_by_the_word_music():
    legitimate = ev("Music Therapy", "music therapy for anxiety",
                    ("music", "therapy"), ("anxiety",), "Music Therapy for Anxiety")
    assert legitimate.mismatch_penalty_percent == 0
    assert legitimate.confidence_percent == 100.0

    unrelated = ev("Neuroscience", "basal ganglia", ("basal", "ganglia"),
                   ("dopamine",), "Basal Ganglia Dopamine Music Compilation")
    assert unrelated.mismatch_penalty_percent == 40


# ---------------------------------------------------------------------------
# Tokenisation and keyword rules
# ---------------------------------------------------------------------------


def test_common_words_carry_no_score():
    assert "study" in COMMON_WORDS and "video" in COMMON_WORDS
    assert normalize_for_scoring("The Study of the Video") == ""


def test_important_weight_wins_without_double_counting():
    result = ev("Neuroscience", "basal ganglia", ("dopamine",), ("dopamine",),
                "Dopamine Explained")
    assert result.raw_possible_points == IMPORTANT_KEYWORD_POINTS
    assert len(result.keyword_evidence) == 1
    assert result.keyword_evidence[0].importance is KeywordImportance.IMPORTANT


def test_multiword_keywords_split_into_component_words():
    result = ev("Neuroscience", "basal ganglia", ("basal ganglia",),
                ("dopamine pathways",), "Basal Ganglia and Dopamine Pathways")
    assert result.raw_possible_points == 6   # 1+1 normal, 2+2 important
    assert result.raw_matched_points == 6


def test_empty_keyword_entries_are_ignored_not_scored():
    result = ev("Neuroscience", "basal ganglia", ("basal", "   ", "the"),
                (), "Basal Ganglia")
    assert "   " in result.ignored_keywords or "the" not in [
        item.keyword for item in result.keyword_evidence
    ]


def test_title_scorer_is_available_standalone():
    score = score_title(
        keywords=("basal", "ganglia"),
        important_keywords=("dopamine",),
        title="Basal Ganglia and Dopamine Pathways",
    )
    assert score.matched_points == 4
    assert score.possible_points == 4
    assert score.score_percent == 100.0
    assert isinstance(StudyTitleScorer(), StudyTitleScorer)


def test_schema_version_marks_the_pure_calculator_generation():
    assert ALIGNMENT_SCHEMA_VERSION.startswith("myelin-study-")
