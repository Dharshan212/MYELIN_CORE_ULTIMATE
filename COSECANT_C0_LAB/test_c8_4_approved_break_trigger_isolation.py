"""C8.4 — an approved COSECANT break may be OBSERVED but may not found SINE.

EXPECTED BEFORE C8.4: A, B, C, F fail.
EXPECTED AFTER  C8.4: all PASS, and must stay passing forever.

Resource Intent already publishes APPROVED_BREAK truthfully whenever the Study
context is COSECANT's managed BREAK context, and its own SINE contribution is
correctly withheld. But Trigger's Executive-Blacklist lane converts any valid
current threshold offer into a candidate without ever asking whether a break
owns the moment. So a legitimate 10-minute break could mint a SINE trigger
halfway through the very break COSECANT is supposed to regulate.

The boundary this pins is deliberately narrow:

    Blacklist  -- may still observe and describe the activity
    Trigger    -- must refuse to turn that evidence into an intervention
    COSECANT   -- owns the break-return regulation

"Allow the break" must never become "go blind during the break", so these
tests assert the factual Blacklist observation SURVIVES while only the
candidate is refused.
"""

from __future__ import annotations

import time

import pytest

import _lab
from _lab import LECTURE, Surface

from CORE_ENGINE.blacklist import BlacklistAuthority, SineThresholdPolicy
from CORE_ENGINE.browser import BrowserEvidenceAuthority
from CORE_ENGINE.monitor import MonitorContext
from CORE_ENGINE.resource_intent import (
    ResourceIntent,
    ResourceIntentAuthority,
    StudyContext,
)
from CORE_ENGINE.trigger import TriggerAuthority

NS = 10**9

SUBJECT = "Neuroscience"
TASK = "basal ganglia"
KEYWORDS = ("direct", "indirect")
IMPORTANT = ("basal ganglia",)

# Thresholds shortened so a threshold offer exists within a test, not within
# five real minutes. Only the LAB policy is shortened; production is untouched.
FAST_THRESHOLDS = SineThresholdPolicy(
    stage_one_seconds=0.3,
    stage_two_cumulative_seconds=1.5,
    offer_retry_seconds=0.1,
)

# CANONICAL PROCESS IDENTITY. Foreground process names are extensionless
# everywhere in MYELIN; only browser.py carries ".exe". Trigger's scope match
# compares the foreground name against Resource Intent's observation, and
# Resource Intent strips ".exe" while Trigger does not -- so a ".exe" name can
# never satisfy Trigger. The shared _lab surfaces predate that rule and still
# carry ".exe", which is why no lab test has ever minted an Executive
# Blacklist candidate. These C8.4 fixtures use the canonical form so the
# control tests can prove the lane genuinely works.
BREAK_SOCIAL = Surface(
    process_name="chrome",
    title="Instagram",
    url="https://www.instagram.com/reels/REEL_555",
)
BREAK_ENTERTAINMENT = Surface(
    process_name="chrome",
    title="MrBeast $1,000,000 Challenge Gaming Reaction - YouTube",
    url="https://www.youtube.com/watch?v=MRBEAST_999",
)


class _Foreground:
    def __init__(self, surface, seq, at_ns):
        self.sequence = seq
        self.hwnd = surface.hwnd
        self.process_id = surface.process_id
        self.process_name = surface.process_name
        self.window_title = surface.title
        self.observed_monotonic_ns = at_ns
        self.observed_wall_time_utc = ""
        self.idle_seconds = 0.0


class Bench:
    """Real Browser + Resource Intent + Blacklist + Trigger, one cycle at a time."""

    def __init__(self):
        self.reader = _lab.ScriptedForegroundReader(LECTURE)
        self.browser = BrowserEvidenceAuthority(
            reader=_lab.make_browser_reader(self.reader)
        )
        self.browser.start_session()
        self.intent = ResourceIntentAuthority()
        self.intent.start_session(profile_type="study")
        self.blacklist = BlacklistAuthority(thresholds=FAST_THRESHOLDS)
        self.blacklist.start_session()
        self.trigger = TriggerAuthority(profile_type="study")
        self.trigger.start_session(session_id=1, profile_type="study")
        self.seq = 0
        self.base_ns = time.monotonic_ns()
        self.last_blacklist = None

    # -- study context -------------------------------------------------

    def publish(self, display_state: str, *, block_id="BLOCK-C84", generation=1):
        return self.intent.publish_study_context(
            StudyContext(
                block_id=block_id,
                generation=generation,
                display_state=display_state,
                subject=SUBJECT,
                task=TASK,
                protection_active=(display_state == "ACTIVE"),
                planned_break_active=(display_state == "BREAK"),
                remaining_seconds=600,
                published_monotonic_ns=time.monotonic_ns(),
                keywords=KEYWORDS,
                important_keywords=IMPORTANT,
            )
        )

    def retire(self):
        self.intent.retire_study_context()

    # -- one monitor cycle ---------------------------------------------

    def cycle(self, surface, *, after_seconds: float):
        self.seq += 1
        at_ns = self.base_ns + int(after_seconds * NS)
        self.reader.set_surface(surface)
        foreground = _Foreground(surface, self.seq, at_ns)
        evidence = self.browser.observe(foreground)
        snapshot = self.intent.observe(
            foreground=foreground, browser_evidence=evidence
        )
        context = MonitorContext(
            foreground=foreground,
            browser_evidence=evidence,
            resource_intent=snapshot,
            cosine_platform=None,
        )
        self.last_blacklist = self.blacklist.observe(context)
        return context

    def candidate(self, context):
        return self.trigger.evaluate(
            context=context, blacklist=self.last_blacklist
        )

    def dwell_until_offer(self, surface, *, start=1.0, step=0.2, limit=40):
        """Hold one surface until Blacklist publishes a threshold offer."""

        elapsed = start
        for _ in range(limit):
            context = self.cycle(surface, after_seconds=elapsed)
            if _lab_offer(self.last_blacklist) is not None:
                return context
            elapsed += step
        raise AssertionError("the lab never reached a Blacklist threshold offer")


def _lab_offer(snapshot):
    return getattr(snapshot, "threshold_offer", None)


# ---------------------------------------------------------------------------
# C8.4-A / C8.4-B — the lesion, on real Resource Intent BREAK truth
# ---------------------------------------------------------------------------


def test_c84_a_approved_break_offer_founds_no_trigger_candidate():
    bench = Bench()
    assert bench.publish("BREAK")

    context = bench.dwell_until_offer(BREAK_SOCIAL)

    # This is genuine Resource Intent truth, not a hand-edited enum.
    assert (
        context.resource_intent.verdict.classification
        is ResourceIntent.APPROVED_BREAK
    ), "the lab needs a real APPROVED_BREAK verdict"
    assert _lab_offer(bench.last_blacklist) is not None, (
        "the lab needs a real current threshold offer"
    )

    assert bench.candidate(context) is None, (
        "an approved COSECANT break minted an Executive Blacklist trigger "
        "candidate. COSECANT owns break regulation; this is C8-L4."
    )


def test_c84_b_repeated_break_offers_never_found_a_candidate():
    bench = Bench()
    assert bench.publish("BREAK")
    bench.dwell_until_offer(BREAK_SOCIAL)

    elapsed = 12.0
    for _ in range(8):
        context = bench.cycle(BREAK_SOCIAL, after_seconds=elapsed)
        assert bench.candidate(context) is None, (
            "a later break observation founded an intervention"
        )
        elapsed += 0.4


# ---------------------------------------------------------------------------
# C8.4-C — observation is NOT erased; only intervention founding is refused
# ---------------------------------------------------------------------------


def test_c84_c_blacklist_still_observes_the_break_activity():
    """Allowing the break must not blind MYELIN to what happened in it."""

    bench = Bench()
    assert bench.publish("BREAK")
    context = bench.dwell_until_offer(BREAK_SOCIAL)

    snapshot = bench.last_blacklist
    offer = _lab_offer(snapshot)

    assert offer is not None, (
        "Blacklist stopped observing during an approved break -- C8.4 must "
        "suppress the intervention, not the sensing"
    )
    assert float(getattr(offer, "dwell_seconds", 0.0)) > 0.0, (
        "the factual dwell must still be measured"
    )
    assert str(getattr(offer, "resource_key", "") or ""), (
        "the factual resource identity must still be described"
    )
    assert bool(getattr(snapshot, "threshold_reached", True)) or offer is not None

    # And still: no intervention.
    assert bench.candidate(context) is None


# ---------------------------------------------------------------------------
# C8.4-D — normal Executive Blacklist is NOT globally disabled
# ---------------------------------------------------------------------------


def test_c84_d_executive_blacklist_still_works_outside_a_break():
    bench = Bench()
    # No study block at all: ordinary Executive Blacklist territory.
    context = bench.dwell_until_offer(BREAK_SOCIAL)

    assert (
        context.resource_intent.verdict.classification
        is not ResourceIntent.APPROVED_BREAK
    )
    assert bench.candidate(context) is not None, (
        "C8.4 over-suppressed: Executive Blacklist can no longer found a "
        "candidate outside an approved break"
    )


def test_c84_e_active_study_distraction_still_founds_a_candidate():
    bench = Bench()
    assert bench.publish("ACTIVE")
    context = bench.dwell_until_offer(BREAK_ENTERTAINMENT)

    assert (
        context.resource_intent.verdict.classification
        is not ResourceIntent.APPROVED_BREAK
    )
    assert bench.candidate(context) is not None, (
        "the ordinary Study distraction pathway must be unchanged"
    )


# ---------------------------------------------------------------------------
# C8.4-I — suppression is state-scoped, not session-wide
# ---------------------------------------------------------------------------


def test_c84_i_suppression_ends_when_the_break_ends():
    bench = Bench()
    assert bench.publish("BREAK")
    break_context = bench.dwell_until_offer(BREAK_SOCIAL)
    assert bench.candidate(break_context) is None

    # The break is retired and ordinary Study resumes.
    assert bench.publish("ACTIVE")

    elapsed = 20.0
    minted = None
    for _ in range(40):
        context = bench.cycle(BREAK_SOCIAL, after_seconds=elapsed)
        if (
            context.resource_intent.verdict.classification
            is not ResourceIntent.APPROVED_BREAK
        ):
            minted = bench.candidate(context)
            if minted is not None:
                break
        elapsed += 0.4

    assert minted is not None, (
        "C8.4 suppression outlived the break. It must be scoped to the factual "
        "APPROVED_BREAK state, never to the whole session."
    )


# ---------------------------------------------------------------------------
# C8.4-F — the whole COSECANT break lifecycle stays SINE-free
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_c84_f_no_candidate_across_the_whole_break_lifecycle():
    """BREAK_ACTIVE -> COMPLETE -> ALREADY_OVER -> FINAL_LOCK, all silent."""

    from _lab import Engine

    with Engine(
        surface=LECTURE,
        poll_seconds=0.2,
        fast_cosecant=True,
        blacklist_thresholds=FAST_THRESHOLDS,
    ) as engine:
        engine.send(
            "study_prepare",
            subject=SUBJECT,
            task=TASK,
            planned_seconds=3600,
            keywords=KEYWORDS,
            important_keywords=IMPORTANT,
        )
        engine.send("study_action", action="START")
        engine.wait_until(
            lambda: engine.study().state.value == "ACTIVE",
            timeout=15,
            what="Study Mode to become ACTIVE",
        )
        engine.send("study_break", selected_break_seconds=60)
        engine.wait_until(
            lambda: engine.cosecant().state.value == "BREAK_ACTIVE",
            timeout=15,
            what="the approved break to start",
        )

        engine.look_at(BREAK_SOCIAL)

        seen_states = set()
        deadline = time.monotonic() + 110
        while time.monotonic() < deadline:
            state = engine.cosecant().state.value
            seen_states.add(state)
            live = engine.services.trigger.live_view()
            assert int(getattr(live, "admitted_count", 0) or 0) == 0, (
                f"a trigger candidate was admitted during {state}; COSECANT "
                "must be the sole break authority"
            )
            assert engine.services.sine.protected_red_active() is False
            if state == "FINAL_LOCK":
                break
            time.sleep(0.3)

        assert "FINAL_LOCK" in seen_states, (
            "COSECANT did not escalate normally -- suppressing SINE must not "
            "suppress COSECANT"
        )
        assert {"BREAK_ACTIVE", "BREAK_COMPLETE"} <= seen_states

        # C8.4-H: the exact return still works, unchanged from C6/C7.
        engine.look_at(LECTURE)
        engine.wait_until(
            lambda: engine.cosecant().return_confirmed,
            timeout=25,
            what="the 3-second exact return confirmation",
        )
        engine.wait_until(
            lambda: engine.study().state.value == "ACTIVE",
            timeout=15,
            what="Study to resume",
        )

        # C8.4-I end to end: normal intervention founding returns afterwards.
        engine.look_at(BREAK_SOCIAL)
        engine.wait_until(
            lambda: int(
                getattr(engine.services.trigger.live_view(), "admitted_count", 0)
                or 0
            )
            > 0,
            timeout=30,
            what="normal Executive Blacklist triggering to resume after the break",
        )
