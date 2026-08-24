"""C0 regression guard for W-2 — idle permission used as return evidence.

EXPECTED AT C0: FAIL.
EXPECTED AFTER C6: PASS, and must stay passing forever.

monitor._observe_cosecant_return derives the entire break-return evidence from

    exact = bool(verdict.study_idle_allowed)

But ``study_idle_allowed`` is an IDLE POLICY permission, not a statement about
which resource is in focus. It requires ``context.active``, and during an
approved break COSECANT itself publishes display_state="BREAK", so
``context.active`` is False for the whole break. Resource Intent also returns
APPROVED_BREAK from an earlier precedence rule, so the verdict is never
STUDY_ALIGNED either.

Result: every observation delivered to COSECANT during a break carries
presence=ABSENT and exact_resource_confirmed=False.

These tests are written against the OBSERVABLE contract, not against the shape
of the future fix, so they stay valid whatever the new field is called.
"""

from __future__ import annotations

import time

import pytest

import _lab
from _lab import LECTURE, MRBEAST, OTHER_LECTURE

from CORE_ENGINE.resource_intent import (
    ResourceIntent,
    ResourceIntentAuthority,
    StudyContext,
    build_observation,
    build_resource_identity,
)

NS = 10**9


class _Foreground:
    def __init__(self, surface, seq=1):
        self.sequence = seq
        self.hwnd = surface.hwnd
        self.process_id = surface.process_id
        self.process_name = surface.process_name
        self.window_title = surface.title
        self.observed_monotonic_ns = time.monotonic_ns()
        self.observed_wall_time_utc = ""
        self.idle_seconds = 0.0


def _browser_snapshot(surface, foreground):
    from CORE_ENGINE.browser import BrowserEvidenceAuthority

    reader_source = _lab.ScriptedForegroundReader(surface)
    authority = BrowserEvidenceAuthority(reader=_lab.make_browser_reader(reader_source))
    authority.start_session()
    return authority.observe(foreground)


def _break_context(*, subject="Neuroscience", task="basal ganglia"):
    return StudyContext(
        block_id="BLOCK-W2",
        generation=1,
        display_state="BREAK",
        subject=subject,
        task=task,
        protection_active=False,
        planned_break_active=True,
        remaining_seconds=120,
        published_monotonic_ns=time.monotonic_ns(),
    )


def _observe(intent, surface, seq=1):
    foreground = _Foreground(surface, seq=seq)
    evidence = _browser_snapshot(surface, foreground)
    return intent.observe(foreground=foreground, browser_evidence=evidence)


@pytest.fixture()
def intent_on_break():
    intent = ResourceIntentAuthority()
    intent.start_session(profile_type="study")
    assert intent.publish_study_context(_break_context())
    return intent


def test_monitor_derivation_proves_presence_on_the_exact_resource():
    """Ask monitor's LIVE derivation to prove presence on the exact resource.

    C6 NOTE -- this test previously inlined a verbatim copy of the C0 line::

        exact = bool(verdict.study_idle_allowed)

    and asserted it was truthy. That copy could only ever be satisfied by
    widening ``study_idle_allowed``, which is precisely the forbidden fix that
    ``test_study_idle_allowed_is_not_a_presence_fact`` below exists to block:
    the two assertions in this file were mutually unsatisfiable. The frozen
    copy also contradicted this module's own stated rule -- test the OBSERVABLE
    contract, never the shape of the implementation.

    It now calls whatever derivation monitor actually uses. The requirement is
    unchanged and is still the real W-2 requirement: during an approved break,
    with the exact intended certified Study resource in the foreground, monitor
    must report an exact return.
    """

    quiet = _lab.QuietMonitor(LECTURE)
    quiet.on_break(block_id="BLOCK-W2")

    frozen = _lab.freeze_target(quiet.look_at(LECTURE))
    context = quiet.look_at(LECTURE)
    exact = quiet.exact(context, frozen)

    assert exact, (
        "During an approved break, with the exact intended certified Study "
        "resource in the foreground, monitor derives "
        f"exact_resource_confirmed={exact} "
        f"(classification={context.resource_intent.verdict.classification.value})."
        " COSECANT can therefore never begin the 3-second proof. This is W-2."
    )


def test_break_context_still_certifies_the_resource(intent_on_break):
    """The evidence COSECANT needs exists; only the reported fact is missing.

    This test documents that the raw material for the C6 fix is already
    present during a break: certified identity and a stable resource token.
    It should pass at C0 and keep passing.
    """

    snapshot = _observe(intent_on_break, LECTURE)
    identity = snapshot.verdict.resource_identity

    assert identity.browser_evidence_certified, "certified route evidence is present"
    assert identity.opaque_resource_token, "a stable exact resource token is present"
    assert identity.platform_key == "youtube"


def test_resource_intent_can_distinguish_intended_from_other_during_break(
    intent_on_break,
):
    """Different videos must remain distinguishable while a break is running.

    Passes at C0. It guards the C6 fix against being implemented in a way that
    collapses distinct resources into "same platform".
    """

    lecture = _observe(intent_on_break, LECTURE, seq=1)
    other = _observe(intent_on_break, OTHER_LECTURE, seq=2)
    punk = _observe(intent_on_break, MRBEAST, seq=3)

    tokens = {
        lecture.verdict.resource_identity.opaque_resource_token,
        other.verdict.resource_identity.opaque_resource_token,
        punk.verdict.resource_identity.opaque_resource_token,
    }
    assert len(tokens) == 3, "three distinct videos must yield three identities"


def test_study_idle_allowed_is_not_a_presence_fact(intent_on_break):
    """Pin the conceptual boundary the C6 fix must respect.

    ``study_idle_allowed`` must NOT be widened to make COSECANT work. It is an
    idle-policy permission and it also feeds COSINE's focus_confirmed input at
    monitor.py:1128. This test asserts it stays False during a break even
    after C6, so a future engineer cannot "fix" W-2 the forbidden way.
    """

    snapshot = _observe(intent_on_break, LECTURE)
    assert snapshot.verdict.study_idle_allowed is False, (
        "study_idle_allowed must remain False during an approved break; "
        "COSECANT return evidence must come from a separate fact."
    )
    assert snapshot.verdict.classification is ResourceIntent.APPROVED_BREAK
