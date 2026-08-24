"""C0 permanent concept tests — the rules that must never regress.

These encode the LATEST concept (CONVERSATION_TO_FINALISE_THE_IDEA.txt, from
the COSECANT heading down), not any donor behaviour.

    1. Study Mode ON is not permission.
    2. A verified alignment is not a permanent passport -- going punk revokes
       it on the very next observation.
    3. Revocation returns the user to NORMAL Trigger/SINE policy. Resource
       Intent must not itself schedule an intervention.
    4. Wrong lecture is not a return. Same platform is not a return.
       UNCERTAIN is not a return. One observation is not a return.

Tests marked ``xfail(strict=True)`` are the ones the roadmap expects to start
passing at a named phase. Strict means they will FAIL LOUDLY once they pass,
which forces the report to be updated rather than silently drifting.
"""

from __future__ import annotations

import time

import pytest

import _lab
from _lab import INSTAGRAM, LECTURE, MRBEAST, OTHER_LECTURE, SHORTS

from CORE_ENGINE.resource_intent import (
    ResourceIntent,
    ResourceIntentAuthority,
    SineContribution,
    StudyContext,
)

NS = 10**9


class _Foreground:
    def __init__(self, surface, seq):
        self.sequence = seq
        self.hwnd = surface.hwnd
        self.process_id = surface.process_id
        self.process_name = surface.process_name
        self.window_title = surface.title
        self.observed_monotonic_ns = time.monotonic_ns()
        self.observed_wall_time_utc = ""
        self.idle_seconds = 0.0


class _Session:
    """One Resource Intent session driven by scripted surfaces."""

    def __init__(self, *, display_state="ACTIVE", subject="Neuroscience",
                 task="basal ganglia", keywords=(), important_keywords=()):
        from CORE_ENGINE.browser import BrowserEvidenceAuthority

        self.surface_holder = _lab.ScriptedForegroundReader(LECTURE)
        self.browser = BrowserEvidenceAuthority(
            reader=_lab.make_browser_reader(self.surface_holder)
        )
        self.browser.start_session()
        self.intent = ResourceIntentAuthority()
        self.intent.start_session(profile_type="study")
        self.seq = 0
        self.intent.publish_study_context(
            StudyContext(
                block_id="BLOCK-CONCEPT",
                generation=1,
                display_state=display_state,
                subject=subject,
                task=task,
                protection_active=(display_state == "ACTIVE"),
                planned_break_active=(display_state == "BREAK"),
                remaining_seconds=1800,
                published_monotonic_ns=time.monotonic_ns(),
                keywords=keywords,
                important_keywords=important_keywords,
            )
        )

    def look(self, surface):
        self.seq += 1
        self.surface_holder.set_surface(surface)
        foreground = _Foreground(surface, self.seq)
        evidence = self.browser.observe(foreground)
        return self.intent.observe(foreground=foreground, browser_evidence=evidence)

    def approve_current_resource(self) -> bool:
        """Walk the real SINE-popup allowance path to reach STUDY_ALIGNED."""

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
# 1. Study Mode ON is not permission
# ---------------------------------------------------------------------------


def test_study_mode_on_alone_does_not_align_youtube():
    session = _Session()
    snapshot = session.look(LECTURE)
    assert snapshot.verdict.classification is not ResourceIntent.STUDY_ALIGNED, (
        "Study Mode ON must never by itself make a YouTube video Study-aligned."
    )


def test_study_mode_off_gives_no_exemption():
    from CORE_ENGINE.browser import BrowserEvidenceAuthority

    holder = _lab.ScriptedForegroundReader(LECTURE)
    browser = BrowserEvidenceAuthority(reader=_lab.make_browser_reader(holder))
    browser.start_session()
    intent = ResourceIntentAuthority()
    intent.start_session(profile_type="study")

    foreground = _Foreground(LECTURE, 1)
    snapshot = intent.observe(
        foreground=foreground, browser_evidence=browser.observe(foreground)
    )
    assert snapshot.verdict.classification is not ResourceIntent.STUDY_ALIGNED
    assert snapshot.verdict.study_idle_allowed is False


# ---------------------------------------------------------------------------
# 2 + 3. THE PUNK RULE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "punk_surface, label",
    [
        (MRBEAST, "unrelated YouTube entertainment"),
        (SHORTS, "YouTube Shorts with educational words"),
        (INSTAGRAM, "Instagram reels"),
        (OTHER_LECTURE, "a different video entirely"),
    ],
)
def test_alignment_is_not_a_permanent_passport(punk_surface, label):
    """Verified alignment must die on the very next differing observation.

    Alignment is established here through the real allowance path, which is
    the only route to STUDY_ALIGNED before C4. The point of this test is the
    REVOCATION half, which must keep working unchanged after C4.
    """

    session = _Session()
    session.look(LECTURE)
    assert session.approve_current_resource(), "allowance path unavailable"

    aligned = session.look(LECTURE)  # revalidation observation
    assert aligned.verdict.classification is ResourceIntent.STUDY_ALIGNED, (
        "precondition failed: the exact approved resource should align"
    )
    assert aligned.verdict.sine_contribution is SineContribution.WITHHELD

    gone_punk = session.look(punk_surface)
    assert gone_punk.verdict.classification is not ResourceIntent.STUDY_ALIGNED, (
        f"Study exemption survived a change to {label}. Alignment is not a passport."
    )
    assert gone_punk.verdict.allowance_match is False
    assert gone_punk.verdict.study_idle_allowed is False


def test_returning_to_the_approved_resource_realigns():
    """After going punk, coming back to the exact approved video re-aligns."""

    session = _Session()
    session.look(LECTURE)
    assert session.approve_current_resource()
    assert session.look(LECTURE).verdict.classification is ResourceIntent.STUDY_ALIGNED

    session.look(MRBEAST)
    back = session.look(LECTURE)
    assert back.verdict.classification is ResourceIntent.STUDY_ALIGNED


def test_going_punk_does_not_itself_schedule_an_intervention():
    """Revocation returns to NORMAL policy; it is not an instant SINE.

    Resource Intent must not become a second Trigger. Immediately after the
    switch, SINE contribution must not be READY -- the off-task dwell has not
    been served yet.
    """

    session = _Session()
    session.look(LECTURE)
    assert session.approve_current_resource()
    session.look(LECTURE)

    punk = session.look(MRBEAST)
    assert punk.verdict.sine_contribution is not SineContribution.READY, (
        "Going punk must hand back to normal dwell/Trigger timing, not fire "
        "an immediate SINE contribution."
    )


# ---------------------------------------------------------------------------
# 4. Break return: what is NOT a return
# ---------------------------------------------------------------------------


def test_same_platform_is_not_the_same_resource():
    session = _Session(display_state="BREAK")
    lecture = session.look(LECTURE)
    other = session.look(OTHER_LECTURE)

    assert lecture.verdict.resource_identity.platform_key == "youtube"
    assert other.verdict.resource_identity.platform_key == "youtube"
    assert (
        lecture.verdict.resource_identity.opaque_resource_token
        != other.verdict.resource_identity.opaque_resource_token
    ), "two different YouTube videos must never share an exact identity"


def test_shorts_route_is_never_rescued_by_educational_words():
    """A certified Shorts route outranks any lexical similarity."""

    session = _Session()
    snapshot = session.look(SHORTS)
    assert snapshot.verdict.classification is not ResourceIntent.STUDY_ALIGNED
    assert snapshot.verdict.resource_identity.surface.value == "youtube_shorts"


def test_title_alone_never_certifies_identity():
    """A title claiming to be the lecture, on an uncertified surface, fails."""

    liar = _lab.Surface(
        process_name="notepad.exe",
        title="Basal Ganglia Direct and Indirect Pathways - YouTube",
        url="",
    )
    session = _Session()
    snapshot = session.look(liar)
    assert snapshot.verdict.classification is not ResourceIntent.STUDY_ALIGNED
    assert snapshot.verdict.resource_identity.browser_evidence_certified is False
    assert snapshot.verdict.resource_identity.opaque_resource_token == ""


# ---------------------------------------------------------------------------
# The honest student — opened at C4
# ---------------------------------------------------------------------------


def test_honest_student_aligns_without_any_popup_click():
    """The whole purpose of the point system.

    No SINE popup. No 'THIS IS STUDY MATERIAL' click. No manual allowance.
    A genuine, certified lecture matching the declared Study target must
    align on evidence alone.

    Written at C0 as a strict xfail. C4 wired the calculator into Resource
    Intent and it now passes -- but only once a target is actually declared,
    which is why the keywords are explicit here.
    """

    session = _Session(
        keywords=("direct", "indirect"), important_keywords=("basal ganglia",)
    )
    snapshot = session.look(LECTURE)
    assert snapshot.verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert snapshot.verdict.allowance_match is False
    assert snapshot.verdict.sine_contribution is SineContribution.WITHHELD


def test_study_mode_on_with_no_declared_target_still_does_not_align():
    """The counterpart. Declaring nothing scores nothing, and nothing is not
    proof of anything -- so the pre-C4 UNCERTAIN fallback survives."""

    session = _Session()
    snapshot = session.look(LECTURE)
    assert snapshot.verdict.classification is ResourceIntent.UNCERTAIN
    assert snapshot.verdict.confidence == 0.50


def test_keyword_stuffing_cannot_manufacture_alignment():
    """A declared target cannot rescue certified entertainment evidence."""

    session = _Session(
        subject="Neuroscience",
        task="basal ganglia",
        keywords=("mrbeast", "challenge"),
        important_keywords=("basal ganglia",),
    )
    snapshot = session.look(MRBEAST)
    assert snapshot.verdict.classification is not ResourceIntent.STUDY_ALIGNED
