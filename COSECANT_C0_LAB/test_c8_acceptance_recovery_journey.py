"""C8.2 + C8.3 combined acceptance — the whole recovery arc through Protected Red.

This is the journey the two lesions together made impossible:

    Study Mode active
      -> genuine Study resource
      -> user goes punk
      -> SINE escalates to Protected Red
      -> user returns to a valid Study resource
      -> Resource Intent STILL publishes factual STUDY_ALIGNED   (C8.3)
      -> Red keeps idle disabled and refuses to self-resolve
      -> MIRL sees FOCUS                                          (C8.2)
      -> MIRL verifies the behavioural return
      -> verified recovery package
      -> SINE.confirm_verified_return(evidence_source="mirl")
      -> Red released

Every organ here is the real production object. MIRL's timing policy is
shortened -- which its own contract sanctions for tests -- so the 10s/60s
gates do not make the run take 70 seconds. Neither gate's MEANING changes.

The final handoff is performed with the same call monitor makes in
``_collect_verified_recovery_learning``; that connector is frozen and was not
touched by this surgery.
"""

from __future__ import annotations

import time

import pytest

from _lab import INSTAGRAM, LECTURE, QuietMonitor, SineDriver, Surface

from CORE_ENGINE.resource_intent import ResourceIntent, StudyContext
from MIRL.mirl import MirlAuthority, MirlPolicy, RecoveryContext

NS = 10**9

SUBJECT = "Neuroscience"
TASK = "basal ganglia"
KEYWORDS = ("direct", "indirect")
IMPORTANT = ("basal ganglia",)

HONEST_LECTURE = Surface(
    process_name="chrome.exe",
    title="Basal Ganglia Direct and Indirect Pathways - YouTube",
    url="https://www.youtube.com/watch?v=BG_LECTURE_001",
)

# Short enough to keep the test fast, long enough that a single observation
# can never satisfy either gate.
FAST_MIRL = MirlPolicy(
    first_display_deadline_seconds=45.0,
    return_verification_seconds=0.4,
    closure_confirmation_seconds=0.6,
    maximum_observation_gap_seconds=30.0,
)


class Journey:
    def __init__(self):
        self.quiet = QuietMonitor(LECTURE)
        self.intent = self.quiet.services.resource_intent
        assert self.intent.publish_study_context(
            StudyContext(
                block_id="BLOCK-C8ACC",
                generation=1,
                display_state="ACTIVE",
                subject=SUBJECT,
                task=TASK,
                protection_active=True,
                planned_break_active=False,
                remaining_seconds=1800,
                published_monotonic_ns=time.monotonic_ns(),
                keywords=KEYWORDS,
                important_keywords=IMPORTANT,
            )
        )
        self.mirl = MirlAuthority(policy=FAST_MIRL)
        self.mirl.start_session(session_id=1, profile_type="study")
        self.driver = SineDriver(sine=self.quiet.services.sine, session_id=1)
        self.driver.fact_sink = self.mirl.record_sine_fact
        self.driver.mirl_token_factory = self._prepare_mirl

    def _prepare_mirl(self, candidate, operational_event_id):
        return self.mirl.prepare_trigger(
            candidate=candidate, operational_event_id=operational_event_id
        )

    def look(self, surface):
        return self.quiet.look_at(surface)

    def feed(self, surface, *, seconds: float, step: float = 0.1):
        """Hold one surface for a wall-clock span, observing like Monitor does."""

        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            context = self.look(surface)
            self.mirl.observe(context)
            last = context
            time.sleep(step)
        return last


def test_c8_combined_red_recovery_journey_releases_sine():
    journey = Journey()

    # 1. The user goes punk and SINE escalates all the way to Protected Red.
    journey.driver.escalate_to_protected_red(journey.look(INSTAGRAM))
    sine = journey.quiet.services.sine
    assert sine.protected_red_active() is True, "the journey needs real Red"

    candidate_uid = journey.driver.last_candidate.candidate_uid
    assert candidate_uid

    # 2. Red is live and Resource Intent now reports facts again.
    red_context = journey.look(HONEST_LECTURE)
    red_verdict = red_context.resource_intent.verdict
    assert red_context.resource_intent.protected_red_active is True
    assert red_verdict.classification is ResourceIntent.STUDY_ALIGNED, (
        "C8.3: Red must not mask the factual Study return"
    )
    assert red_verdict.study_idle_allowed is False, (
        "Red still withholds idle permission"
    )
    assert red_verdict.allowance_match is False, (
        "this is the C4 automatic route, with no manual allowance"
    )

    # 3. MIRL can see the return as focus.
    assert (
        journey.mirl._observation_from_monitor_context(red_context).context
        is RecoveryContext.FOCUS
    ), "C8.2: automatic Study alignment must be recovery focus"

    # 4. Sustained factual focus lets MIRL verify the behavioural return.
    journey.feed(HONEST_LECTURE, seconds=1.6)

    # 5. Red must NOT have released itself from alignment alone -- only from
    #    the verified package handed over below.
    packages = tuple(journey.mirl.drain_verified_recovery_evidence() or ())
    assert packages, (
        "MIRL never produced a verified recovery package, so Protected Red "
        "would still be unreleasable. This is the C8-L2/C8-L3 deadlock."
    )
    package = packages[0]
    verified_ns = int(getattr(package, "return_verified_monotonic_ns", 0) or 0)
    assert verified_ns > 0

    assert sine.protected_red_active() is True, (
        "Red must still be held right up until the verified handoff"
    )

    # 6. The frozen monitor handoff.
    released = sine.confirm_verified_return(
        candidate_uid=str(getattr(package, "candidate_uid", "") or ""),
        verified_monotonic_ns=verified_ns,
        evidence_source="mirl",
    )
    assert released is True, "SINE refused the verified MIRL recovery"
    assert sine.protected_red_active() is False, (
        "Protected Red survived a verified recovery"
    )


def test_c8_journey_red_is_not_released_without_the_verified_package():
    """The same journey, stopped before verification: Red must hold."""

    journey = Journey()
    journey.driver.escalate_to_protected_red(journey.look(INSTAGRAM))
    sine = journey.quiet.services.sine
    assert sine.protected_red_active() is True

    # A brief touch of the Study resource -- less than the verification gate.
    journey.feed(HONEST_LECTURE, seconds=0.2, step=0.05)

    assert not tuple(journey.mirl.drain_verified_recovery_evidence() or ()), (
        "MIRL packaged a recovery it had not finished verifying"
    )
    assert sine.protected_red_active() is True, (
        "Protected Red released without MIRL proof"
    )
