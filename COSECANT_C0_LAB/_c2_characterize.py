"""Characterize the CURRENT study_alignment.py mathematics before C2.

Run against the pre-C2 file. The numbers it prints become the frozen
expectations in test_c2_math.py, so the conversion to a pure calculator can
be proved to preserve the mathematics exactly.

The current file raises TypeError on its STUDY_UNCERTAIN + certified path
(it constructs StudyMaterialApprovalRequest with a stale signature). That is
defect W-3. A test-only shim neutralises the constructor so every arithmetic
path can be reached for characterization. Production is not modified.
"""

from __future__ import annotations

import _lab  # noqa: F401  (sys.path)

import COSECANT_STUDY_MODE.study_alignment as SA
from COSECANT_STUDY_MODE.study import (
    StudyResourceEvidence,
    StudyState,
    StudyTargetSnapshot,
)


class _ShimApprovalRequest:
    """Stand-in so the W-3 TypeError cannot mask the arithmetic."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


SA.StudyMaterialApprovalRequest = _ShimApprovalRequest


def target(subject, task, keywords, important):
    return StudyTargetSnapshot(
        block_id="B", generation=1, state=StudyState.ACTIVE, study_active=True,
        subject=subject, task=task, keywords=keywords,
        important_keywords=important,
        active_epoch_monotonic_ns=1, published_monotonic_ns=1,
    )


def resource(title, certified=True):
    return StudyResourceEvidence(
        platform="youtube",
        resource_id="vid" if certified else "",
        title=title,
        identity_certified=certified,
        observed_monotonic_ns=10**9,
    )


CASES = [
    ("honest_lecture",
     ("Neuroscience", "basal ganglia", ("basal", "ganglia"), ("dopamine",)),
     ("Basal Ganglia and Dopamine Pathways", True)),
    ("mrbeast",
     ("Neuroscience", "basal ganglia", ("basal", "ganglia"), ("dopamine",)),
     ("MrBeast Challenge", True)),
    ("keyword_stuffing",
     ("Neuroscience", "basal ganglia",
      ("neuroscience", "mrbeast", "gaming", "shorts"), ("dopamine",)),
     ("MrBeast Gaming Shorts Neuroscience", True)),
    ("uncertified_identity",
     ("Neuroscience", "basal ganglia", ("basal", "ganglia"), ("dopamine",)),
     ("Basal Ganglia and Dopamine Pathways", False)),
    ("edu_word_plus_gaming",
     ("Machine Learning", "machine learning", ("machine", "learning"), ("neural",)),
     ("Machine Learning Funny Gaming Reaction Compilation", True)),
    ("subject_word_only",
     ("Neuroscience", "basal ganglia", ("basal", "ganglia"), ("dopamine",)),
     ("Neuroscience of Falling in Love", True)),
    ("one_eligible_keyword",
     ("Neuroscience", "basal ganglia", ("basal",), ()),
     ("Basal Ganglia Explained", True)),
    ("one_matched_of_three",
     ("Neuroscience", "basal ganglia", ("basal", "ganglia", "striatum"), ()),
     ("Basal Nuclei Overview", True)),
    ("important_all_missed",
     ("Neuroscience", "basal ganglia", ("basal", "ganglia"), ("dopamine", "striatum")),
     ("Basal Ganglia Anatomy", True)),
    ("important_half_missed",
     ("Neuroscience", "basal ganglia", ("basal", "ganglia"),
      ("dopamine", "striatum", "pallidum")),
     ("Basal Ganglia Dopamine Overview", True)),
    ("music_therapy_legitimate",
     ("Music Therapy", "music therapy for anxiety", ("music", "therapy"), ("anxiety",)),
     ("Music Therapy for Anxiety", True)),
    ("music_not_legitimate",
     ("Neuroscience", "basal ganglia", ("basal", "ganglia"), ("dopamine",)),
     ("Basal Ganglia Dopamine Music Compilation", True)),
    ("no_keywords_at_all",
     ("Neuroscience", "basal ganglia", (), ()),
     ("Basal Ganglia Explained", True)),
    ("multiword_keyword_split",
     ("Neuroscience", "basal ganglia", ("basal ganglia",), ("dopamine pathways",)),
     ("Basal Ganglia and Dopamine Pathways", True)),
    ("important_overrides_normal",
     ("Neuroscience", "basal ganglia", ("dopamine",), ("dopamine",)),
     ("Dopamine Explained", True)),
    ("unicode_and_common_words",
     ("Neuroscience", "basal ganglia", ("basal", "ganglia"), ("dopamine",)),
     ("The Basal​ Ganglia of the Dopamine Study Video", True)),
]


def main() -> None:
    print("# characterization of pre-C2 study_alignment.py")
    print("# name | raw_matched | raw_possible | raw_pct | eff_matched |"
          " eff_possible | eff_pct | core_matched | core_possible |"
          " core_pct | penalty | confidence | caps | suspicious")
    for name, tgt, res in CASES:
        decision = SA.StudyAlignmentEngine().evaluate(
            target=target(*tgt), resource=resource(*res)
        )
        ts = decision.title_score
        print(
            f"{name} | {ts.matched_points} | {ts.possible_points} |"
            f" {ts.score_percent} | {decision.effective_matched_points} |"
            f" {decision.effective_possible_points} |"
            f" {decision.effective_title_score_percent} |"
            f" {decision.core_matched_count} | {decision.core_possible_count} |"
            f" {decision.core_coverage_percent} |"
            f" {decision.mismatch_penalty_percent} |"
            f" {decision.confidence_percent} | {list(decision.safety_caps)} |"
            f" {list(decision.suspicious_keywords)}"
        )


if __name__ == "__main__":
    main()
