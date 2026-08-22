"""Pure Study-evidence mathematics for MYELIN.

C2 scope
--------
This module is a CALCULATOR. It answers exactly one question:

    "How strong, and how structured, is the evidence that this observed title
     serves the declared Study target?"

It does NOT answer:

    "Is the user studying?"          -> CORE_ENGINE/resource_intent.py (BSF)
    "Is Study Mode active?"          -> COSECANT_STUDY_MODE/study.py
    "May this resource be allowed?"  -> CORE_ENGINE/resource_intent.py

Therefore this module deliberately publishes no operational Study verdict, no
Study lifecycle state, and no approval capability, and it imports nothing from
``study.py``. There is exactly one Study verdict authority in MYELIN and it is
Resource Intent.

Inputs are plain values, never runtime objects. That is not stylistic: before
C2 this file imported ``StudyMaterialApprovalRequest`` from ``study.py`` and
constructed it with a stale signature, so every STUDY_UNCERTAIN evaluation
raised TypeError. Nothing imported this module, so nothing caught it for an
entire generation. Plain-value inputs remove that whole class of silent rot.

Title text never certifies identity. ``identity_certified`` is supplied by the
caller from certified browser/resource evidence and is used only to cap
confidence; this module never infers it from words.

Reading the output
------------------
``confidence_percent`` is capped evidence strength, and ``safety_caps`` names
every cap that was actually applied. A caller deciding Study protection should
read BOTH: the number says how strong the lexical case is, the cap codes say
why it may not be trusted on its own. A caller must never treat a high number
as proof of resource identity.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Final


ALIGNMENT_SCHEMA_VERSION: Final = "myelin-study-evidence-v4"
NORMAL_KEYWORD_POINTS: Final = 1
IMPORTANT_KEYWORD_POINTS: Final = 2

# Confidence ceilings applied when the evidence STRUCTURE is too weak to be
# trusted on its own.  These are caps on the NUMBER, not verdict thresholds:
# the bands that turn a number into STUDY_ALIGNED / UNCERTAIN / OFF_TASK
# belong to Resource Intent and deliberately do not live here.
UNCERTAIN_CAP: Final = 74.0
SINGLE_MATCH_CAP: Final = 50.0

# These words are too generic to prove a Study target.  This is NOT mismatch
# vocabulary; these tokens simply carry zero positive Study score.
COMMON_WORDS: Final[frozenset[str]] = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "study",
        "the",
        "this",
        "to",
        "video",
        "with",
    }
)

# Background mismatch vocabulary.  Penalties are percentage points, not
# platform rules and not a blacklist.  A term is neutralised when Subject/Task
# explicitly contains it, which lets legitimate domains such as Music Therapy,
# Chemical Reaction, or Sports Highlights be represented without global bans.
BACKGROUND_MISMATCH_PENALTIES: Final[dict[str, int]] = {
    "asmr": 30,
    "celebrity": 20,
    "compilation": 20,
    "detox": 20,
    "funny": 20,
    "gameplay": 30,
    "gaming": 25,
    "highlights": 20,
    "lofi": 25,
    "meme": 30,
    "memes": 30,
    "motivation": 15,
    "music": 20,
    "prank": 30,
    "reaction": 20,
    "reels": 20,
    "shorts": 20,
    "song": 25,
    "songs": 25,
    "trailer": 25,
    "vlog": 25,
}

_TOKEN_RE: Final = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*|\d+", re.UNICODE)


class KeywordImportance(str, Enum):
    """The two user-controlled positive keyword weights."""

    NORMAL = "NORMAL"
    IMPORTANT = "IMPORTANT"


@dataclass(frozen=True, slots=True)
class KeywordEvidence:
    """One normalized Study keyword and whether the title contains it."""

    keyword: str
    importance: KeywordImportance
    points: int
    matched: bool


@dataclass(frozen=True, slots=True)
class TitleScore:
    """Raw lexical title score.

    This raw score intentionally includes ALL user-entered keywords.  The
    calculator then removes suspicious keywords before computing confidence,
    so the raw evidence stays auditable rather than silently rewritten.
    """

    original_title: str
    normalized_title: str
    matched_points: int
    possible_points: int
    score_percent: float
    keyword_evidence: tuple[KeywordEvidence, ...]
    ignored_keywords: tuple[str, ...]
    schema_version: str = ALIGNMENT_SCHEMA_VERSION

    @property
    def has_scoring_keywords(self) -> bool:
        return self.possible_points > 0

    @property
    def matched_keywords(self) -> tuple[str, ...]:
        return tuple(item.keyword for item in self.keyword_evidence if item.matched)

    @property
    def unmatched_keywords(self) -> tuple[str, ...]:
        return tuple(
            item.keyword for item in self.keyword_evidence if not item.matched
        )


@dataclass(frozen=True, slots=True)
class BackgroundMismatchEvidence:
    """One background mismatch term relevant to the current evaluation."""

    term: str
    penalty_points: int
    present_in_title: bool
    present_in_user_keywords: bool
    legitimized_by_subject_task: bool
    applied_title_penalty: bool
    suspicious_target_keyword: bool


@dataclass(frozen=True, slots=True)
class StudyEvidence:
    """Immutable mathematical evidence about one title/target pair.

    Deliberately absent: verdict, basis, study_active, approval_request,
    exact_resource_approved, block_id, generation, resource_id, platform.
    Those are lifecycle or identity facts owned by other organs.
    """

    original_title: str
    normalized_title: str

    raw_matched_points: int
    raw_possible_points: int
    raw_score_percent: float
    keyword_evidence: tuple[KeywordEvidence, ...]
    ignored_keywords: tuple[str, ...]

    effective_matched_points: int
    effective_possible_points: int
    effective_score_percent: float

    core_matched_count: int
    core_possible_count: int
    core_coverage_percent: float

    mismatch_penalty_percent: int
    mismatch_evidence: tuple[BackgroundMismatchEvidence, ...]
    suspicious_keywords: tuple[str, ...]

    identity_certified: bool
    confidence_percent: float
    safety_caps: tuple[str, ...]
    reasons: tuple[str, ...]
    schema_version: str = ALIGNMENT_SCHEMA_VERSION

    @property
    def title_score(self) -> TitleScore:
        """Rebuild the raw lexical view for auditing."""

        return TitleScore(
            original_title=self.original_title,
            normalized_title=self.normalized_title,
            matched_points=self.raw_matched_points,
            possible_points=self.raw_possible_points,
            score_percent=self.raw_score_percent,
            keyword_evidence=self.keyword_evidence,
            ignored_keywords=self.ignored_keywords,
        )

    @property
    def matched_keyword_count(self) -> int:
        return sum(1 for item in self.keyword_evidence if item.matched)


class StudyTitleScorer:
    """Pure deterministic scorer for Study keywords versus one resource title."""

    def score(
        self,
        *,
        keywords: Iterable[str] = (),
        important_keywords: Iterable[str] = (),
        title: str,
    ) -> TitleScore:
        original_title = str(title)
        title_tokens = _meaningful_tokens(original_title)
        title_token_set = frozenset(title_tokens)
        normalized_title = " ".join(title_tokens)

        keyword_rules, ignored = _build_keyword_rules(
            normal_keywords=tuple(keywords),
            important_keywords=tuple(important_keywords),
        )

        evidence: list[KeywordEvidence] = []
        matched_points = 0
        possible_points = 0

        for keyword, importance, points in keyword_rules:
            matched = keyword in title_token_set
            possible_points += points
            if matched:
                matched_points += points
            evidence.append(
                KeywordEvidence(
                    keyword=keyword,
                    importance=importance,
                    points=points,
                    matched=matched,
                )
            )

        score_percent = (
            (matched_points / possible_points) * 100.0 if possible_points else 0.0
        )

        return TitleScore(
            original_title=original_title,
            normalized_title=normalized_title,
            matched_points=matched_points,
            possible_points=possible_points,
            score_percent=round(score_percent, 3),
            keyword_evidence=tuple(evidence),
            ignored_keywords=ignored,
        )


class StudyEvidenceCalculator:
    """Stateless owner of the Study confidence mathematics.

    Every call is independent.  The calculator holds no session, no Study
    block, and no memory of previous evaluations.
    """

    def __init__(self, *, title_scorer: StudyTitleScorer | None = None) -> None:
        self._title_scorer = title_scorer or StudyTitleScorer()

    def evaluate(
        self,
        *,
        subject: str,
        task: str,
        keywords: Iterable[str] = (),
        important_keywords: Iterable[str] = (),
        title: str,
        identity_certified: bool,
    ) -> StudyEvidence:
        if type(identity_certified) is not bool:
            raise TypeError("identity_certified must be a bool")

        raw_score = self._title_scorer.score(
            keywords=keywords,
            important_keywords=important_keywords,
            title=title,
        )
        subject_task_tokens = frozenset(_meaningful_tokens(f"{subject} {task}"))
        user_keyword_tokens = frozenset(
            item.keyword for item in raw_score.keyword_evidence
        )
        title_tokens = frozenset(_meaningful_tokens(title))

        mismatch_evidence = _build_mismatch_evidence(
            subject_task_tokens=subject_task_tokens,
            user_keyword_tokens=user_keyword_tokens,
            title_tokens=title_tokens,
        )
        suspicious_keywords = tuple(
            item.term for item in mismatch_evidence if item.suspicious_target_keyword
        )
        suspicious_set = frozenset(suspicious_keywords)

        eligible_evidence = tuple(
            item
            for item in raw_score.keyword_evidence
            if item.keyword not in suspicious_set
        )
        effective_possible = sum(item.points for item in eligible_evidence)
        effective_matched = sum(
            item.points for item in eligible_evidence if item.matched
        )
        effective_title_percent = (
            (effective_matched / effective_possible) * 100.0
            if effective_possible
            else 0.0
        )

        core_evidence = tuple(
            item
            for item in eligible_evidence
            if item.importance is KeywordImportance.IMPORTANT
        )
        core_possible_count = len(core_evidence)
        core_matched_count = sum(1 for item in core_evidence if item.matched)
        core_coverage_percent = (
            (core_matched_count / core_possible_count) * 100.0
            if core_possible_count
            else 0.0
        )

        mismatch_penalty = min(
            100,
            sum(
                item.penalty_points
                for item in mismatch_evidence
                if item.applied_title_penalty
            ),
        )

        confidence = max(0.0, effective_title_percent - mismatch_penalty)
        matched_keyword_count = sum(1 for item in eligible_evidence if item.matched)
        eligible_keyword_count = len(eligible_evidence)

        safety_caps: list[str] = []
        reasons: list[str] = []

        if suspicious_keywords:
            reasons.append(
                "Suspicious user keywords were excluded because Subject/Task did not support them"
            )

        if mismatch_penalty:
            reasons.append(
                f"Background mismatch evidence reduced confidence by {mismatch_penalty} percentage points"
            )
            # Any unresolved mismatch evidence blocks automatic protection even
            # if the remaining positive score is high.
            confidence = _apply_cap(
                confidence,
                UNCERTAIN_CAP,
                "BACKGROUND_MISMATCH_PRESENT",
                safety_caps,
            )

        if not identity_certified:
            confidence = _apply_cap(
                confidence,
                UNCERTAIN_CAP,
                "RESOURCE_IDENTITY_NOT_CERTIFIED",
                safety_caps,
            )
            reasons.append(
                "Uncertified resource identity cannot receive automatic Study protection"
            )

        if eligible_keyword_count == 0:
            confidence = 0.0
            reasons.append("No eligible Study keywords remained for scoring")
        elif eligible_keyword_count == 1:
            confidence = _apply_cap(
                confidence,
                UNCERTAIN_CAP,
                "ONLY_ONE_ELIGIBLE_KEYWORD",
                safety_caps,
            )
            reasons.append(
                "One Study keyword alone is not enough for automatic alignment"
            )
        elif matched_keyword_count == 1:
            confidence = _apply_cap(
                confidence,
                SINGLE_MATCH_CAP,
                "ONLY_ONE_KEYWORD_MATCHED",
                safety_caps,
            )
            reasons.append(
                "A single matching keyword cannot automatically prove Study alignment"
            )

        if core_possible_count:
            if core_matched_count == 0:
                confidence = _apply_cap(
                    confidence,
                    SINGLE_MATCH_CAP,
                    "NO_IMPORTANT_KEYWORD_MATCHED",
                    safety_caps,
                )
                reasons.append("No important Study keyword matched the current title")
            elif core_possible_count >= 2 and core_coverage_percent < 50.0:
                confidence = _apply_cap(
                    confidence,
                    SINGLE_MATCH_CAP,
                    "IMPORTANT_KEYWORD_COVERAGE_BELOW_HALF",
                    safety_caps,
                )
                reasons.append("Less than half of important Study keywords matched")

        confidence = round(max(0.0, min(100.0, confidence)), 3)

        return StudyEvidence(
            original_title=raw_score.original_title,
            normalized_title=raw_score.normalized_title,
            raw_matched_points=raw_score.matched_points,
            raw_possible_points=raw_score.possible_points,
            raw_score_percent=raw_score.score_percent,
            keyword_evidence=raw_score.keyword_evidence,
            ignored_keywords=raw_score.ignored_keywords,
            effective_matched_points=effective_matched,
            effective_possible_points=effective_possible,
            effective_score_percent=round(effective_title_percent, 3),
            core_matched_count=core_matched_count,
            core_possible_count=core_possible_count,
            core_coverage_percent=round(core_coverage_percent, 3),
            mismatch_penalty_percent=mismatch_penalty,
            mismatch_evidence=mismatch_evidence,
            suspicious_keywords=suspicious_keywords,
            identity_certified=identity_certified,
            confidence_percent=confidence,
            safety_caps=tuple(safety_caps),
            reasons=tuple(reasons),
        )


def score_title(
    *,
    keywords: Iterable[str] = (),
    important_keywords: Iterable[str] = (),
    title: str,
) -> TitleScore:
    """Raw lexical title-score valve."""

    return StudyTitleScorer().score(
        keywords=keywords,
        important_keywords=important_keywords,
        title=title,
    )


def study_evidence(
    *,
    subject: str,
    task: str,
    keywords: Iterable[str] = (),
    important_keywords: Iterable[str] = (),
    title: str,
    identity_certified: bool,
) -> StudyEvidence:
    """One-call valve for the complete Study-evidence calculation."""

    return StudyEvidenceCalculator().evaluate(
        subject=subject,
        task=task,
        keywords=keywords,
        important_keywords=important_keywords,
        title=title,
        identity_certified=identity_certified,
    )


def normalize_for_scoring(text: str) -> str:
    """Return the normalized, common-word-free lexical form used by the scorer."""

    return " ".join(_meaningful_tokens(text))


def _build_keyword_rules(
    *,
    normal_keywords: tuple[str, ...],
    important_keywords: tuple[str, ...],
) -> tuple[
    tuple[tuple[str, KeywordImportance, int], ...],
    tuple[str, ...],
]:
    # Each meaningful keyword word carries points once.  Multi-word user entries
    # are split into component words.  IMPORTANT wins instead of double-counting.
    rules: dict[str, tuple[KeywordImportance, int]] = {}
    ignored: list[str] = []

    for raw in normal_keywords:
        tokens = _meaningful_tokens(raw)
        if not tokens:
            ignored.append(str(raw))
            continue
        for token in tokens:
            rules.setdefault(
                token,
                (KeywordImportance.NORMAL, NORMAL_KEYWORD_POINTS),
            )

    for raw in important_keywords:
        tokens = _meaningful_tokens(raw)
        if not tokens:
            ignored.append(str(raw))
            continue
        for token in tokens:
            rules[token] = (
                KeywordImportance.IMPORTANT,
                IMPORTANT_KEYWORD_POINTS,
            )

    ordered = tuple(
        (keyword, importance, points)
        for keyword, (importance, points) in rules.items()
    )
    return ordered, tuple(ignored)


def _build_mismatch_evidence(
    *,
    subject_task_tokens: frozenset[str],
    user_keyword_tokens: frozenset[str],
    title_tokens: frozenset[str],
) -> tuple[BackgroundMismatchEvidence, ...]:
    evidence: list[BackgroundMismatchEvidence] = []
    for term, penalty in BACKGROUND_MISMATCH_PENALTIES.items():
        in_title = term in title_tokens
        in_keywords = term in user_keyword_tokens
        legitimized = term in subject_task_tokens
        suspicious_keyword = in_keywords and not legitimized
        applied_penalty = in_title and not legitimized
        if in_title or in_keywords:
            evidence.append(
                BackgroundMismatchEvidence(
                    term=term,
                    penalty_points=penalty,
                    present_in_title=in_title,
                    present_in_user_keywords=in_keywords,
                    legitimized_by_subject_task=legitimized,
                    applied_title_penalty=applied_penalty,
                    suspicious_target_keyword=suspicious_keyword,
                )
            )
    return tuple(evidence)


def _apply_cap(
    value: float,
    cap: float,
    reason: str,
    applied: list[str],
) -> float:
    if value > cap:
        applied.append(reason)
        return cap
    return value


def _meaningful_tokens(text: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", str(text)).casefold()
    raw_tokens = _TOKEN_RE.findall(normalized)
    return tuple(token for token in raw_tokens if token not in COMMON_WORDS)


__all__ = [
    "ALIGNMENT_SCHEMA_VERSION",
    "BACKGROUND_MISMATCH_PENALTIES",
    "BackgroundMismatchEvidence",
    "COMMON_WORDS",
    "IMPORTANT_KEYWORD_POINTS",
    "KeywordEvidence",
    "KeywordImportance",
    "NORMAL_KEYWORD_POINTS",
    "SINGLE_MATCH_CAP",
    "StudyEvidence",
    "StudyEvidenceCalculator",
    "StudyTitleScorer",
    "TitleScore",
    "UNCERTAIN_CAP",
    "normalize_for_scoring",
    "score_title",
    "study_evidence",
]
