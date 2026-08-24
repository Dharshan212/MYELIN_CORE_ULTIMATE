"""C8.1 — held / uncertified Browser evidence must not authorize a manual allowance.

EXPECTED BEFORE C8.1: TEST B and TEST D FAIL.
EXPECTED AFTER  C8.1: all PASS, and must stay passing forever.

Browser deliberately holds the last strong exact resource across a transient
read failure:

    authoritative                    = True
    holding_previous_strong_evidence = True
    status                          != OK

Resource Intent already marks that identity ``browser_evidence_certified =
False``. But the manual allowance matcher compares only stable keys, so the
HELD MEMORY of the previous exact resource can still be exercised as CURRENT
factual permission — producing STUDY_ALIGNED / allowance_match /
study_idle_allowed on an observation that proves nothing about right now.

C8.1 reuses the authority Resource Intent already owns —
``is_allowance_eligible(identity)`` — in the exact allowance matcher. It does
not add a grace timer, does not look at
``holding_previous_strong_evidence`` directly, and does not invent a universal
browser-certification rule for non-browser allowance surfaces.

Run with:
    py -3 -m pytest test_c8_1_manual_allowance_certification.py -q
"""

from __future__ import annotations

import time

import pytest

import _lab
from _lab import LECTURE, OTHER_LECTURE, Surface

from CORE_ENGINE.browser import BrowserUrlReadStatus
from CORE_ENGINE.resource_intent import (
    IntentReason,
    ResourceIntent,
    ResourceIntentAuthority,
    StudyContext,
    is_allowance_eligible,
)

NS = 10**9

SUBJECT = "Neuroscience"
TASK = "basal ganglia"

# The SAME window, process and title as LECTURE, but the address bar cannot be
# read this cycle. Browser's stabiliser holds the previous strong LECTURE
# evidence, so every stable-key ingredient is unchanged while certification is
# lost. This is the exact transient the lesion rides on.
HELD_LECTURE = Surface(
    process_name=LECTURE.process_name,
    title=LECTURE.title,
    url="",
    hwnd=LECTURE.hwnd,
    process_id=LECTURE.process_id,
)

# A non-browser allowance surface. is_allowance_eligible() requires only a
# title here, so C8.1 must NOT start demanding browser certification for it.
DOCUMENT = Surface(
    process_name="winword.exe",
    title="Basal Ganglia Pathways Notes.docx - Word",
    url="",
    hwnd=5150,
    process_id=5151,
)


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


class Session:
    """One real Resource Intent session over real Browser certification."""

    def __init__(self, *, subject=SUBJECT, task=TASK):
        from CORE_ENGINE.browser import BrowserEvidenceAuthority

        self.holder = _lab.ScriptedForegroundReader(LECTURE)
        self.browser = BrowserEvidenceAuthority(
            reader=_lab.make_browser_reader(self.holder)
        )
        self.browser.start_session()
        self.intent = ResourceIntentAuthority()
        self.intent.start_session(profile_type="study")
        self.seq = 0
        self.evidence = None
        self.intent.publish_study_context(
            StudyContext(
                block_id="BLOCK-C81",
                generation=1,
                display_state="ACTIVE",
                subject=subject,
                task=task,
                protection_active=True,
                planned_break_active=False,
                remaining_seconds=1800,
                published_monotonic_ns=time.monotonic_ns(),
            )
        )

    def look(self, surface):
        self.seq += 1
        self.holder.set_surface(surface)
        foreground = _Foreground(surface, self.seq)
        self.evidence = self.browser.observe(foreground)
        return self.intent.observe(
            foreground=foreground, browser_evidence=self.evidence
        )

    def approve_current(self) -> bool:
        """Record the human declaration for the current exact resource."""

        now = time.monotonic_ns()
        latest = self.intent._latest
        if latest is None or not latest.resource_key:
            return False
        return self.intent.record_study_material_allowance(
            study_context_token=latest.verdict.study_context_token,
            resource_key=latest.resource_key,
            granted_monotonic_ns=now,
        ).granted

    def confirmed_allowance_on(self, surface) -> None:
        """Drive a surface to an exact human-declared allowance."""

        self.look(surface)
        assert self.approve_current(), "the allowance path was unavailable"
        verdict = self.look(surface).verdict
        assert verdict.allowance_match is True, (
            "the lab could not establish a confirmed manual allowance"
        )


def _assert_held_but_uncertified(session, snapshot) -> None:
    """Pin the exact Browser/Resource Intent state this lesion requires."""

    evidence = session.evidence
    assert evidence.holding_previous_strong_evidence is True, (
        "the lab expected Browser to hold its previous strong read"
    )
    assert evidence.authoritative is True, (
        "a held read stays authoritative -- that is why the allowance path "
        "must reject it explicitly"
    )
    assert evidence.status is not BrowserUrlReadStatus.OK, (
        "a held read must not report a current OK status"
    )
    identity = snapshot.verdict.resource_identity
    assert identity.browser_evidence_certified is False, (
        "Resource Intent already knows a held read is not certified"
    )
    assert is_allowance_eligible(identity) is False, (
        "the existing eligibility authority already refuses this identity"
    )


# ---------------------------------------------------------------------------
# TEST A — control: a healthy certified manual allowance stays healthy
# ---------------------------------------------------------------------------


def test_a_certified_manual_allowance_remains_healthy():
    session = Session()
    session.confirmed_allowance_on(LECTURE)

    verdict = session.look(LECTURE).verdict
    assert verdict.allowance_match is True
    assert verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert verdict.study_idle_allowed is True
    assert IntentReason.EXACT_ALLOWANCE.value in verdict.positive_reason_codes


# ---------------------------------------------------------------------------
# TEST B — the lesion: held evidence must not satisfy an existing allowance
# ---------------------------------------------------------------------------


def test_b_held_previous_evidence_cannot_satisfy_an_existing_allowance():
    session = Session()
    session.confirmed_allowance_on(LECTURE)

    snapshot = session.look(HELD_LECTURE)
    _assert_held_but_uncertified(session, snapshot)

    verdict = snapshot.verdict
    assert verdict.allowance_match is False, (
        "held memory of the previous exact resource was exercised as CURRENT "
        "manual permission. This is C8-L1."
    )
    assert verdict.study_idle_allowed is False, (
        "an uncertified held read must not grant Study idle permission"
    )
    assert not (
        verdict.classification is ResourceIntent.STUDY_ALIGNED
        and IntentReason.EXACT_ALLOWANCE.value in verdict.positive_reason_codes
    ), "the observation became STUDY_ALIGNED through EXACT_ALLOWANCE"


# ---------------------------------------------------------------------------
# TEST C — a transient hold must not permanently destroy a valid allowance
# ---------------------------------------------------------------------------


def test_c_transient_hold_suspends_but_does_not_destroy_the_allowance():
    session = Session()
    session.confirmed_allowance_on(LECTURE)

    held = session.look(HELD_LECTURE).verdict
    assert held.allowance_match is False
    assert held.study_idle_allowed is False

    recovered = session.look(LECTURE).verdict
    assert recovered.allowance_match is True, (
        "a confirmed allowance must survive one transient Browser read failure"
    )
    assert recovered.classification is ResourceIntent.STUDY_ALIGNED
    assert recovered.study_idle_allowed is True


# ---------------------------------------------------------------------------
# TEST D — held evidence cannot exercise or revoke an exact allowance
# ---------------------------------------------------------------------------


def test_d_held_evidence_cannot_exercise_or_revoke_an_exact_allowance():
    session = Session()
    session.look(LECTURE)
    assert session.approve_current(), "the allowance path was unavailable"

    snapshot = session.look(HELD_LECTURE)
    _assert_held_but_uncertified(session, snapshot)
    assert snapshot.verdict.allowance_match is False

    # The uncertified observation cannot exercise permission, but it also must
    # not erase the user's exact-resource declaration.
    after = session.look(LECTURE).verdict
    assert after.allowance_match is True, (
        "held evidence revoked the exact human declaration instead of merely "
        "failing its present-tense certification gate"
    )
    assert after.study_idle_allowed is True


# ---------------------------------------------------------------------------
# TEST E — control: the exact certified resource uses its allowance
# ---------------------------------------------------------------------------


def test_e_certified_exact_resource_uses_the_allowance():
    session = Session()
    session.look(LECTURE)
    assert session.approve_current(), "the allowance path was unavailable"

    verdict = session.look(LECTURE).verdict
    assert verdict.allowance_match is True, (
        "a certified exact resource must use the human-declared allowance"
    )
    assert verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert verdict.study_idle_allowed is True


# ---------------------------------------------------------------------------
# TEST F — C4.5 A->B exact-resource separation remains frozen
# ---------------------------------------------------------------------------


def test_f_allowance_does_not_transfer_to_a_different_certified_video():
    session = Session()
    session.confirmed_allowance_on(LECTURE)

    verdict = session.look(OTHER_LECTURE).verdict
    assert verdict.allowance_match is False, (
        "a manual allowance must never transfer to a different exact resource"
    )


# ---------------------------------------------------------------------------
# TEST G — control: non-browser allowance surfaces must not be over-tightened
# ---------------------------------------------------------------------------


def test_g_document_allowance_does_not_require_browser_certification():
    """is_allowance_eligible() is the authority, and it exempts documents."""

    session = Session()
    session.look(DOCUMENT)
    identity = session.intent.live_view()
    assert identity is not None

    snapshot = session.look(DOCUMENT)
    resource = snapshot.verdict.resource_identity
    assert resource.browser_evidence_certified is False, (
        "a Word document has no browser certification by construction"
    )
    assert is_allowance_eligible(resource) is True, (
        "the existing authority already allows document surfaces"
    )

    assert session.approve_current(), "a document must still be allowable"
    verdict = session.look(DOCUMENT).verdict
    assert verdict.allowance_match is True, (
        "C8.1 must reuse is_allowance_eligible(), not invent a universal "
        "browser-certification requirement"
    )
