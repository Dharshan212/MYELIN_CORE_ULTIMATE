"""C8.2 — automatic Study alignment must be valid MIRL recovery input.

EXPECTED BEFORE C8.2: A, B, D fail.
EXPECTED AFTER  C8.2: all PASS, and must stay passing forever.

C4 introduced a legitimate automatic route to STUDY_ALIGNED:

    certified Browser identity + Study evidence -> STUDY_ALIGNED
    allowance_match = False, allowance_active = False

SINE and MIRL still describe Study return in the pre-C4 vocabulary — they
require allowance_match AND allowance_active before they will treat an
observation as a Study return. So a genuine C4 lecture maps to MIRL NEUTRAL
and the 10-second recovery verification never starts.

C8.2 makes the downstream organs trust Resource Intent's published verdict
instead of re-deriving why it was issued. It does NOT let alignment release
SINE: MIRL remains the recovery authority.
"""

from __future__ import annotations

import time

import pytest

from _lab import (
    INSTAGRAM,
    LECTURE,
    MRBEAST,
    QuietMonitor,
    SineDriver,
    Surface,
)

from CORE_ENGINE.resource_intent import ResourceIntent, StudyContext
from MIRL.mirl import MirlAuthority, RecoveryContext

NS = 10**9

SUBJECT = "Neuroscience"
TASK = "basal ganglia"
KEYWORDS = ("direct", "indirect")
IMPORTANT = ("basal ganglia",)

# A certified lecture whose title genuinely matches the declared target, so
# C4 evidence aligns it with NO manual allowance anywhere in the picture.
HONEST_LECTURE = Surface(
    process_name="chrome.exe",
    title="Basal Ganglia Direct and Indirect Pathways - YouTube",
    url="https://www.youtube.com/watch?v=BG_LECTURE_001",
)


def _study_context(*, display_state="ACTIVE", block_id="BLOCK-C82", generation=1):
    return StudyContext(
        block_id=block_id,
        generation=generation,
        display_state=display_state,
        subject=SUBJECT,
        task=TASK,
        protection_active=(display_state == "ACTIVE"),
        planned_break_active=(display_state == "BREAK"),
        remaining_seconds=1800,
        published_monotonic_ns=time.monotonic_ns(),
        keywords=KEYWORDS,
        important_keywords=IMPORTANT,
    )


class Bench:
    """A real QuietMonitor plus a real MIRL, sharing one Study context."""

    def __init__(self, *, block_id="BLOCK-C82", generation=1):
        self.quiet = QuietMonitor(LECTURE)
        published = self.quiet.services.resource_intent.publish_study_context(
            _study_context(block_id=block_id, generation=generation)
        )
        assert published, "the lab could not publish an ACTIVE study context"
        self.mirl = MirlAuthority()

    def look(self, surface):
        return self.quiet.look_at(surface)

    def recovery_context(self, surface) -> RecoveryContext:
        """What MIRL factually makes of this observation."""

        context = self.look(surface)
        return self.mirl._observation_from_monitor_context(context).context


@pytest.fixture()
def bench():
    return Bench()


# ---------------------------------------------------------------------------
# C8.2-A — automatic Study alignment becomes MIRL FOCUS
# ---------------------------------------------------------------------------


def test_c82_a_automatic_study_alignment_becomes_mirl_focus(bench):
    context = bench.look(HONEST_LECTURE)
    verdict = context.resource_intent.verdict

    # Prove this is genuinely the C4 automatic route, not a manual allowance.
    assert verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert verdict.allowance_match is False
    assert context.resource_intent.allowance_active is False

    observation = bench.mirl._observation_from_monitor_context(context)
    assert observation.context is RecoveryContext.FOCUS, (
        "a genuine C4 automatic Study lecture was not recognised as recovery "
        "focus, so MIRL verification can never start. This is C8-L2."
    )


# ---------------------------------------------------------------------------
# C8.2-B — SINE recognises automatic alignment as a recovery HOLD
# ---------------------------------------------------------------------------


def test_c82_b_sine_holds_open_on_automatic_alignment(bench):
    driver = SineDriver()
    distraction = bench.look(INSTAGRAM)
    driver.open_episode(distraction)
    assert driver.live().study_mode is True, "the lab needs a Study-mode episode"

    aligned = bench.look(HONEST_LECTURE)
    assert aligned.resource_intent.verdict.allowance_match is False
    driver.observe(aligned)

    live = driver.live()
    assert live.phase.value not in {"RESOLVED", "CANCELLED"}, (
        "factual Study alignment must not resolve a SINE episode by itself"
    )
    assert live.last_fact == "SINE_STUDY_ALIGNMENT_AWAITING_RECOVERY", (
        "SINE did not record the awaiting-verified-recovery hold for a valid "
        "C4 automatic alignment. This is C8-L2 on the SINE side."
    )


# ---------------------------------------------------------------------------
# C8.2-C — one Study-aligned sample can never release SINE
# ---------------------------------------------------------------------------


def test_c82_c_alignment_alone_never_resolves_the_episode(bench):
    driver = SineDriver()
    driver.open_episode(bench.look(INSTAGRAM))

    for _ in range(5):
        driver.observe(bench.look(HONEST_LECTURE))

    assert driver.live().phase.value not in {"RESOLVED", "CANCELLED"}, (
        "repeated Study alignment must still not substitute for MIRL proof"
    )


# ---------------------------------------------------------------------------
# C8.2-E — manual allowance route still produces FOCUS (no C8.1 regression)
# ---------------------------------------------------------------------------


def test_c82_e_manual_allowance_route_still_focuses(bench):
    intent = bench.quiet.services.resource_intent
    bench.look(LECTURE)

    now = time.monotonic_ns()
    latest = intent._latest
    assert latest is not None and latest.resource_key
    assert intent.record_study_material_allowance(
        study_context_token=latest.verdict.study_context_token,
        resource_key=latest.resource_key,
        granted_monotonic_ns=now,
    ).granted

    context = bench.look(LECTURE)
    assert context.resource_intent.verdict.allowance_match is True
    observation = bench.mirl._observation_from_monitor_context(context)
    assert observation.context is RecoveryContext.FOCUS, (
        "the manual allowance recovery route must keep working"
    )


# ---------------------------------------------------------------------------
# C8.2-F — a different Study block cannot advance the old episode
# ---------------------------------------------------------------------------


def test_c82_f_wrong_study_generation_does_not_advance_recovery(bench):
    driver = SineDriver()
    driver.open_episode(bench.look(INSTAGRAM))
    episode_token = driver.live().episode_uid
    assert episode_token

    # A genuinely different Study block publishes a different context token.
    published = bench.quiet.services.resource_intent.publish_study_context(
        _study_context(block_id="BLOCK-OTHER", generation=2)
    )
    assert published

    other = bench.look(HONEST_LECTURE)
    other_token = other.resource_intent.verdict.study_context_token
    driver.observe(other)

    live = driver.live()
    assert other_token, "the lab expected a real second Study context token"
    assert live.phase.value not in {"RESOLVED", "CANCELLED"}, (
        "a different Study block must not resolve the old episode"
    )


# ---------------------------------------------------------------------------
# C8.2-G — UNCERTAIN is not FOCUS
# ---------------------------------------------------------------------------


def test_c82_g_uncertain_is_never_focus(bench):
    from _lab import SHORTS

    assert bench.recovery_context(SHORTS) is not RecoveryContext.FOCUS, (
        "an UNCERTAIN educational-looking surface is not recovery focus"
    )


# ---------------------------------------------------------------------------
# C8.2-H — DISTRACTION still reads as distraction
# ---------------------------------------------------------------------------


def test_c82_h_distraction_still_reads_as_distraction(bench):
    assert bench.recovery_context(INSTAGRAM) is RecoveryContext.DISTRACTION
    assert bench.recovery_context(MRBEAST) is RecoveryContext.DISTRACTION
