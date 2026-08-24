"""C4 — Resource Intent becomes the real BSF.

The missing honest-student entry path: declared Study target + certified
resource evidence + the C2 calculator -> STUDY_ALIGNED, with no SINE popup and
no manual Study-material allowance.

Written before the production patch.
"""

from __future__ import annotations

import time

import pytest

import _lab
from _lab import INSTAGRAM, LECTURE, MRBEAST, OTHER_LECTURE, SHORTS, Surface

from CORE_ENGINE.resource_intent import (
    IntentReason,
    ResourceIntent,
    ResourceIntentAuthority,
    SineContribution,
    StudyContext,
)

NS = 10**9

# A certified selected-video lecture whose title genuinely matches the target.
HONEST_LECTURE = Surface(
    process_name="chrome.exe",
    title="Basal Ganglia Dopamine and Striatum Pathways - YouTube",
    url="https://www.youtube.com/watch?v=HONEST_LECTURE_001",
)
# Same matching Study keywords, but strong entertainment evidence present.
MRBEAST_DISGUISED = Surface(
    process_name="chrome.exe",
    title="MrBeast Dopamine Striatum Basal Ganglia Challenge - YouTube",
    url="https://www.youtube.com/watch?v=MRBEAST_DISGUISE",
)
GAMING_DISGUISED = Surface(
    process_name="chrome.exe",
    title="Minecraft Dopamine Striatum Basal Ganglia Gameplay - YouTube",
    url="https://www.youtube.com/watch?v=GAMING_DISGUISE",
)

SUBJECT = "Neuroscience"
TASK = "Basal Ganglia"
KEYWORDS = ("dopamine", "striatum")
IMPORTANT = ("basal ganglia",)


class _Foreground:
    def __init__(self, surface, seq, at_ns=None):
        self.sequence = seq
        self.hwnd = surface.hwnd
        self.process_id = surface.process_id
        self.process_name = surface.process_name
        self.window_title = surface.title
        self.observed_monotonic_ns = at_ns or time.monotonic_ns()
        self.observed_wall_time_utc = ""
        self.idle_seconds = 0.0


class Session:
    """One Resource Intent session over scripted certified surfaces."""

    def __init__(self, *, keywords=KEYWORDS, important=IMPORTANT,
                 subject=SUBJECT, task=TASK, display_state="ACTIVE",
                 stage_one_target_seconds=None):
        from CORE_ENGINE.blacklist import BlacklistAuthority
        from CORE_ENGINE.browser import BrowserEvidenceAuthority

        self.holder = _lab.ScriptedForegroundReader(LECTURE)
        self.browser = BrowserEvidenceAuthority(
            reader=_lab.make_browser_reader(self.holder)
        )
        self.browser.start_session()
        self.intent = ResourceIntentAuthority()
        self.intent.start_session(profile_type="study")
        if stage_one_target_seconds is None:
            target_authority = BlacklistAuthority()
            target_authority.start_session(personalization_factor=1.0)
            stage_one_target_seconds = target_authority.stage_one_target_seconds()
            target_authority.shutdown()
        assert self.intent.set_stage_one_target_seconds(stage_one_target_seconds)
        self.seq = 0
        self.base_ns = time.monotonic_ns()
        self.intent.publish_study_context(
            StudyContext(
                block_id="BLOCK-C4",
                generation=1,
                display_state=display_state,
                subject=subject,
                task=task,
                protection_active=(display_state == "ACTIVE"),
                planned_break_active=(display_state == "BREAK"),
                remaining_seconds=1800,
                published_monotonic_ns=self.base_ns,
                keywords=keywords,
                important_keywords=important,
            )
        )

    def look(self, surface, *, after_seconds=None):
        at_ns = (
            self.base_ns + int(after_seconds * NS)
            if after_seconds is not None
            else None
        )
        return self.look_at_ns(surface, at_ns=at_ns)

    def look_at_ns(self, surface, *, at_ns=None):
        self.seq += 1
        self.holder.set_surface(surface)
        foreground = _Foreground(surface, self.seq, at_ns)
        evidence = self.browser.observe(foreground)
        self.last_foreground = foreground
        self.last_browser_evidence = evidence
        return self.intent.observe(
            foreground=foreground, browser_evidence=evidence
        )

    def approve_current(self) -> bool:
        now = time.monotonic_ns()
        latest = self.intent._latest
        if latest is None or not latest.resource_key:
            return False
        return self.intent.record_study_material_allowance(
            study_context_token=latest.verdict.study_context_token,
            resource_key=latest.resource_key,
            granted_monotonic_ns=now,
        ).granted


# ---------------------------------------------------------------------------
# THE HONEST STUDENT — the entry path C4 exists to create
# ---------------------------------------------------------------------------


def test_honest_student_aligns_with_no_popup_and_no_allowance():
    session = Session()
    snapshot = session.look(HONEST_LECTURE)
    verdict = snapshot.verdict

    assert verdict.classification is ResourceIntent.STUDY_ALIGNED, (
        f"an honest certified lecture matching the declared target was "
        f"{verdict.classification.value}, not STUDY_ALIGNED"
    )
    assert verdict.allowance_match is False, "no manual allowance was granted"
    assert verdict.sine_contribution is SineContribution.WITHHELD
    assert verdict.off_task_dwell_seconds == 0.0
    assert IntentReason.STUDY_EVIDENCE_ALIGNED.value in verdict.positive_reason_codes


def test_alignment_does_not_grant_idle_permission():
    """C4 must not repair W-2. Alignment is not idle permission."""

    session = Session()
    verdict = session.look(HONEST_LECTURE).verdict
    assert verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert verdict.study_idle_allowed is False


def test_long_honest_study_never_becomes_distraction():
    """MANDATORY. An auto-aligned lecture must not accrue off-task dwell.

    Without the dwell-candidate fix, a genuine lecture with allowance_match
    False would cross the 300-second target and be reclassified DISTRACTION.
    """

    session = Session()
    for step in range(70):                     # 0..345 seconds, 5s apart
        snapshot = session.look(HONEST_LECTURE, after_seconds=step * 5)
        verdict = snapshot.verdict
        assert verdict.classification is ResourceIntent.STUDY_ALIGNED, (
            f"alignment lost at t={step * 5}s: {verdict.classification.value}"
        )
        assert verdict.off_task_dwell_seconds == 0.0, (
            f"aligned Study accrued {verdict.off_task_dwell_seconds}s of "
            f"off-task dwell at t={step * 5}s"
        )
        assert verdict.sine_contribution is SineContribution.WITHHELD


# ---------------------------------------------------------------------------
# HIGHER AUTHORITY STILL WINS ABOVE THE CALCULATOR
# ---------------------------------------------------------------------------


def test_mrbeast_wins_over_a_perfect_keyword_match():
    """The calculator has no 'mrbeast' term. BSF entertainment evidence does."""

    session = Session()
    verdict = session.look(MRBEAST_DISGUISED).verdict
    assert verdict.classification is not ResourceIntent.STUDY_ALIGNED
    assert verdict.classification is ResourceIntent.DISTRACTION
    assert IntentReason.ENTERTAINMENT.value in verdict.negative_reason_codes


def test_gaming_wins_over_a_perfect_keyword_match():
    session = Session()
    verdict = session.look(GAMING_DISGUISED).verdict
    assert verdict.classification is not ResourceIntent.STUDY_ALIGNED
    assert verdict.classification is ResourceIntent.DISTRACTION


def test_social_surface_still_wins():
    session = Session()
    verdict = session.look(INSTAGRAM).verdict
    assert verdict.classification is ResourceIntent.DISTRACTION
    assert IntentReason.STRONG_DISTRACTION.value in verdict.negative_reason_codes


def test_educational_shorts_still_uncertain_never_aligned():
    session = Session()
    verdict = session.look(SHORTS).verdict
    assert verdict.classification is ResourceIntent.UNCERTAIN
    assert IntentReason.EDUCATIONAL_SHORTS_UNCERTAIN.value in (
        verdict.negative_reason_codes
    )


def test_uncertified_identity_can_never_auto_align():
    """Perfect lexical match on an uncertified surface is not alignment."""

    liar = Surface(
        process_name="notepad.exe",
        title="Basal Ganglia Dopamine and Striatum Pathways",
        url="",
    )
    session = Session()
    verdict = session.look(liar).verdict
    assert verdict.resource_identity.browser_evidence_certified is False
    assert verdict.classification is not ResourceIntent.STUDY_ALIGNED


# ---------------------------------------------------------------------------
# THE CALCULATOR'S OWN SAFETY CAPS SURVIVE AT THE AUTHORITY LAYER
# ---------------------------------------------------------------------------


def test_one_eligible_keyword_cannot_auto_align():
    session = Session(keywords=("dopamine",), important=())
    verdict = session.look(HONEST_LECTURE).verdict
    assert verdict.classification is not ResourceIntent.STUDY_ALIGNED
    assert verdict.classification is ResourceIntent.UNCERTAIN


def test_keyword_stuffing_cannot_manufacture_alignment():
    """The real attack: junk keywords AND a junk resource.

    The stuffed terms are stripped from scoring as suspicious, and they are
    ALSO penalised where they appear in the title, so the fabricated match
    collapses (100 raw -> 35 confidence).
    """

    stuffed = Surface(
        process_name="chrome.exe",
        title="Gaming Shorts Dopamine Striatum Compilation - YouTube",
        url="https://www.youtube.com/watch?v=STUFFED_001",
    )
    session = Session(
        keywords=("dopamine", "striatum", "gaming", "shorts"), important=()
    )
    verdict = session.look(stuffed).verdict
    assert verdict.classification is not ResourceIntent.STUDY_ALIGNED


def test_stuffed_keywords_are_stripped_but_honest_evidence_still_counts():
    """Stuffing junk EARNS NOTHING; it also must not punish honest study.

    Declaring "gaming" and "shorts" alongside real keywords, then watching a
    genuine lecture, still aligns -- on the surviving honest evidence only.
    The junk is excluded from scoring, so it can neither help nor hurt.
    That is what suspicious-keyword exclusion is for.
    """

    honest = Session(keywords=("dopamine", "striatum"), important=("basal ganglia",))
    stuffed = Session(
        keywords=("dopamine", "striatum", "gaming", "shorts"),
        important=("basal ganglia",),
    )

    honest_verdict = honest.look(HONEST_LECTURE).verdict
    stuffed_verdict = stuffed.look(HONEST_LECTURE).verdict

    assert honest_verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert stuffed_verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert stuffed_verdict.confidence == honest_verdict.confidence, (
        "the stuffed keywords must not change the outcome in either direction"
    )


def test_subject_word_only_does_not_align():
    unrelated = Surface(
        process_name="chrome.exe",
        title="The Neuroscience of Falling in Love - YouTube",
        url="https://www.youtube.com/watch?v=LOVE_001",
    )
    session = Session()
    verdict = session.look(unrelated).verdict
    assert verdict.classification is not ResourceIntent.STUDY_ALIGNED


# ---------------------------------------------------------------------------
# NO-KEYWORD LEGACY COMPATIBILITY  (the current UI supplies none)
# ---------------------------------------------------------------------------


def test_legacy_no_keyword_payload_keeps_generic_uncertain():
    session = Session(keywords=(), important=())
    verdict = session.look(HONEST_LECTURE).verdict

    assert verdict.classification is ResourceIntent.UNCERTAIN, (
        "no declared keywords means nothing to score; that is not proof of "
        "distraction"
    )
    assert verdict.confidence == 0.50
    assert verdict.classification is not ResourceIntent.DISTRACTION


def test_no_keywords_on_an_obvious_distraction_still_uses_existing_rules():
    session = Session(keywords=(), important=())
    verdict = session.look(MRBEAST).verdict
    assert verdict.classification is ResourceIntent.DISTRACTION


def test_all_keywords_suspicious_is_not_the_no_keyword_path():
    """raw > 0 but effective == 0 must NOT get the innocent fallback."""

    session = Session(keywords=("gaming", "shorts"), important=())
    verdict = session.look(HONEST_LECTURE).verdict
    assert verdict.classification is not ResourceIntent.STUDY_ALIGNED
    assert verdict.confidence != 0.50 or verdict.classification is (
        ResourceIntent.DISTRACTION
    )


# ---------------------------------------------------------------------------
# BANDS
# ---------------------------------------------------------------------------


def test_below_twenty_five_becomes_distraction_and_dwells():
    session = Session()
    first = session.look(OTHER_LECTURE, after_seconds=0)
    assert first.verdict.classification is ResourceIntent.DISTRACTION
    assert first.verdict.sine_contribution is SineContribution.PENDING

    ready = None
    for step in range(1, 70):
        ready = session.look(OTHER_LECTURE, after_seconds=step * 5)
    assert ready.verdict.sine_contribution is SineContribution.READY
    assert ready.verdict.off_task_dwell_seconds >= 300.0


def test_middle_band_is_uncertain():
    """A partial match must land between the bands, not at either extreme."""

    session = Session(
        keywords=("dopamine", "striatum", "cerebellum", "cortex"),
        important=(),
    )
    verdict = session.look(HONEST_LECTURE).verdict
    assert verdict.classification is ResourceIntent.UNCERTAIN
    assert IntentReason.STUDY_EVIDENCE_UNCERTAIN.value in (
        verdict.negative_reason_codes
    )


# ---------------------------------------------------------------------------
# THE PUNK RULE AFTER C4
# ---------------------------------------------------------------------------


def test_punk_transition_removes_alignment_immediately():
    session = Session()
    assert session.look(HONEST_LECTURE, after_seconds=0).verdict.classification is (
        ResourceIntent.STUDY_ALIGNED
    )

    punk = session.look(MRBEAST, after_seconds=5).verdict
    assert punk.classification is not ResourceIntent.STUDY_ALIGNED
    assert punk.sine_contribution is not SineContribution.READY, (
        "losing alignment must hand back to dwell/Trigger timing, not fire "
        "an immediate SINE contribution"
    )
    assert punk.off_task_dwell_seconds == 0.0


def test_returning_to_the_lecture_realigns():
    session = Session()
    session.look(HONEST_LECTURE, after_seconds=0)
    session.look(MRBEAST, after_seconds=5)
    back = session.look(HONEST_LECTURE, after_seconds=10).verdict
    assert back.classification is ResourceIntent.STUDY_ALIGNED
    assert back.off_task_dwell_seconds == 0.0


# ---------------------------------------------------------------------------
# REGRESSIONS
# ---------------------------------------------------------------------------


def test_manual_allowance_still_works_and_still_grants_idle():
    session = Session(keywords=(), important=())
    session.look(LECTURE)
    assert session.approve_current(), "allowance path unavailable"

    verdict = session.look(LECTURE).verdict
    assert verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert verdict.allowance_match is True
    assert verdict.study_idle_allowed is True
    assert verdict.sine_contribution is SineContribution.WITHHELD


def test_lifecycle_precedence_still_wins_above_the_calculator():
    """Lifecycle authorities outrank the Study evidence calculator.

    C8.3 NOTE -- this test used to assert that Protected Red forces
    classification UNCERTAIN. That contract was deliberately replaced: Red is
    an efferent intervention state and must not cut the afferent nerve that
    reports what the user is factually looking at, because MIRL can only
    verify a return it is allowed to observe, and Red is released only from
    MIRL's verified package. Red masking the classification deadlocked its own
    release (C8-L3).

    What Red must still do is withhold PERMISSION, so that is what is asserted
    now. COSINE precedence is unchanged and still masks the classification.
    """

    session = Session()
    assert session.look(HONEST_LECTURE).verdict.classification is (
        ResourceIntent.STUDY_ALIGNED
    )

    session.intent.set_protected_red(True)
    red_verdict = session.look(HONEST_LECTURE).verdict
    assert red_verdict.classification is ResourceIntent.STUDY_ALIGNED, (
        "Red must keep reporting the factual resource"
    )
    assert red_verdict.study_idle_allowed is False, (
        "Red must still withhold Study idle permission"
    )
    assert red_verdict.sine_contribution is SineContribution.NONE, (
        "Red must still withhold any SINE contribution"
    )
    session.intent.set_protected_red(False)

    session.intent.set_cosine_active(True)
    assert session.look(HONEST_LECTURE).verdict.classification is (
        ResourceIntent.UNCERTAIN
    )
    session.intent.set_cosine_active(False)


def test_approved_break_still_wins_above_the_calculator():
    session = Session(display_state="BREAK")
    verdict = session.look(HONEST_LECTURE).verdict
    assert verdict.classification is ResourceIntent.APPROVED_BREAK


def test_paused_study_does_not_align():
    session = Session()
    session.intent.publish_study_context(
        StudyContext(
            block_id="BLOCK-C4", generation=1, display_state="PAUSED",
            subject=SUBJECT, task=TASK, protection_active=False,
            planned_break_active=False, remaining_seconds=1800,
            published_monotonic_ns=time.monotonic_ns(),
            keywords=KEYWORDS, important_keywords=IMPORTANT,
        )
    )
    verdict = session.look(HONEST_LECTURE).verdict
    assert verdict.classification is ResourceIntent.UNCERTAIN
    assert IntentReason.STUDY_PAUSED.value in verdict.negative_reason_codes


def test_classifier_version_was_bumped():
    """The verdict carries the CURRENT classifier provenance string.

    C8.1 NOTE -- this pin read "myelin-resource-intent-v2" when C4 introduced
    automatic Study alignment. C8.1 changed the meaning of an EXACT_ALLOWANCE
    verdict (the current identity must now be allowance-eligible, so a held
    uncertified Browser read can no longer exercise old permission) and
    therefore bumped the provenance string to v3 by specification.

        C8.3 NOTE -- bumped again to v4, because Protected Red no longer replaces
        the factual classification. Every v3 verdict recorded during Red said
        UNCERTAIN regardless of the real resource, so v3 and v4 rows are not
        comparable. The test's purpose is unchanged: Trigger persists this string
        as source policy, so verdicts with different semantics must not silently
        share one version.

        PHASE 3 NOTE -- bumped to v5 because measured 50% Study uncertainty no
        longer ages into distraction. Human confirmation is now preserved as a
        separate fact and the uncertain interval is excluded from SINE dwell.
    """

    session = Session()
    assert session.look(HONEST_LECTURE).verdict.classifier_version == (
        "myelin-resource-intent-v5"
    )
