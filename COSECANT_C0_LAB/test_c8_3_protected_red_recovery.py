"""C8.3 — Protected Red must not blind the afferent recovery nerve.

EXPECTED BEFORE C8.3: A, B, D, E, G, H fail.
EXPECTED AFTER  C8.3: all PASS, and must stay passing forever.

Monitor publishes SINE's Protected Red state into Resource Intent BEFORE
Resource Intent classifies the observation. Resource Intent then returns
UNCERTAIN/PROTECTED_RED at top precedence, so the factual meaning of the
current resource never surfaces. MIRL cannot see FOCUS, cannot verify a
return, and Monitor therefore never obtains the verified package that is the
only thing allowed to release Red. That is a deadlock.

C8.3 separates two different things that were fused:

    intervention precedence   -- Red suppresses idle permission, SINE
                                 contribution, new allowances and new breaks
    sensory visibility        -- Red must still let MYELIN observe that the
                                 user has factually returned

Protected Red stays protected. It simply stops cutting the nerve that reports
recovery.
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

from CORE_ENGINE.resource_intent import (
    ResourceIntent,
    SineContribution,
    StudyContext,
)
from MIRL.mirl import MirlAuthority, RecoveryContext

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
DOCUMENT = Surface(
    process_name="winword.exe",
    title="Basal Ganglia Pathways Notes.docx - Word",
    url="",
    hwnd=5150,
    process_id=5151,
)


def _study_context(*, block_id="BLOCK-C83", generation=1):
    return StudyContext(
        block_id=block_id,
        generation=generation,
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


class Bench:
    """A real coordinator whose OWN SINE is driven into Protected Red.

    Monitor's ``_classify_observation`` pushes ``sine.protected_red_active()``
    into Resource Intent on every cycle, so a hand-set flag would be
    overwritten immediately. Red therefore has to be real: this escalates the
    coordinator's own SINE through its genuine stage ladder.
    """

    def __init__(self, *, with_study_block: bool = True):
        self.quiet = QuietMonitor(LECTURE)
        self.intent = self.quiet.services.resource_intent
        if with_study_block:
            assert self.intent.publish_study_context(_study_context())
        self.mirl = MirlAuthority()
        self.driver = SineDriver(sine=self.quiet.services.sine)

    def look(self, surface):
        return self.quiet.look_at(surface)

    def red(self, active: bool = True) -> None:
        if not active:
            raise AssertionError("Protected Red cannot be un-set by a test")
        self.driver.escalate_to_protected_red(self.look(INSTAGRAM))
        assert self.quiet.services.sine.protected_red_active() is True
        # One cycle so Monitor publishes the new Red state into Resource Intent.
        snapshot = self.look(INSTAGRAM)
        assert snapshot.resource_intent.protected_red_active is True, (
            "the lab could not put Resource Intent into Protected Red"
        )

    def recovery_context(self, surface) -> RecoveryContext:
        context = self.look(surface)
        return self.mirl._observation_from_monitor_context(context).context

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
# C8.3-A — Red does not mask factual Study alignment
# ---------------------------------------------------------------------------


def test_c83_a_protected_red_does_not_mask_automatic_study_alignment():
    bench = Bench()
    bench.red(True)

    snapshot = bench.look(HONEST_LECTURE)
    verdict = snapshot.resource_intent.verdict

    assert verdict.classification is ResourceIntent.STUDY_ALIGNED, (
        "Protected Red masked the factual Study resource as "
        f"{verdict.classification.value}, so MIRL can never see the return. "
        "This is C8-L3."
    )
    assert snapshot.resource_intent.protected_red_active is True, (
        "Red must remain separately visible on the snapshot"
    )
    # The behavioural exemptions must STILL be withheld. Sensory truth is
    # visible; permission is not granted.
    assert verdict.sine_contribution is SineContribution.NONE
    assert verdict.study_idle_allowed is False, (
        "Red must never grant Study idle permission"
    )


# ---------------------------------------------------------------------------
# C8.3-B — a CONFIRMED manual allowance survives Red as memory
# ---------------------------------------------------------------------------


def test_c83_b_confirmed_allowance_survives_red_as_memory():
    bench = Bench()
    bench.look(LECTURE)
    assert bench.approve_current()
    assert bench.look(LECTURE).resource_intent.verdict.allowance_match is True

    bench.red(True)

    # While off-task the memory must not be exercised.
    off_task = bench.look(INSTAGRAM).resource_intent.verdict
    assert off_task.allowance_match is False
    assert off_task.study_idle_allowed is False

    # Returning to the exact certified resource makes it factual again.
    back = bench.look(LECTURE)
    assert back.resource_intent.verdict.allowance_match is True, (
        "Protected Red destroyed the confirmed exact Study memory, so a "
        "manually allowed resource can never become return evidence. "
        "This is C8-L3."
    )
    assert back.resource_intent.verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert back.resource_intent.verdict.study_idle_allowed is False, (
        "idle permission stays withheld while Red is active"
    )
    assert (
        bench.mirl._observation_from_monitor_context(back).context
        is RecoveryContext.FOCUS
    )


# ---------------------------------------------------------------------------
# C8.3-C — an exact human declaration remains recovery evidence during Red
# ---------------------------------------------------------------------------


def test_c83_c_exact_allowance_survives_red_as_factual_recovery_evidence():
    bench = Bench()
    bench.look(LECTURE)
    assert bench.approve_current()

    bench.red(True)

    verdict = bench.look(LECTURE).resource_intent.verdict
    assert verdict.allowance_match is True, (
        "Protected Red erased the exact resource the user had already declared"
    )
    assert verdict.study_idle_allowed is False


# ---------------------------------------------------------------------------
# C8.3-D — distraction stays visible during Red
# ---------------------------------------------------------------------------


def test_c83_d_distraction_remains_visible_during_red():
    bench = Bench()
    bench.red(True)

    verdict = bench.look(INSTAGRAM).resource_intent.verdict
    assert verdict.classification is ResourceIntent.DISTRACTION, (
        "Red must not hide distraction either -- MIRL needs both signs"
    )
    assert verdict.sine_contribution is SineContribution.NONE, (
        "Red still suppresses any new SINE contribution"
    )
    assert bench.recovery_context(MRBEAST) is RecoveryContext.DISTRACTION


# ---------------------------------------------------------------------------
# C8.3-E — normal mode under Red can still sense productive recovery
# ---------------------------------------------------------------------------


def test_c83_e_normal_mode_red_can_sense_productive_recovery():
    bench = Bench(with_study_block=False)
    bench.red(True)

    assert bench.recovery_context(DOCUMENT) is RecoveryContext.FOCUS, (
        "with no Study block, a certified document is normal-mode focus; "
        "Protected Red must not blind that either. This is C8-L3."
    )


# ---------------------------------------------------------------------------
# C8.3-F — Red never releases from Study alignment alone
# ---------------------------------------------------------------------------


def test_c83_f_red_never_releases_from_alignment_alone():
    bench = Bench()
    bench.red(True)
    driver = bench.driver
    for _ in range(5):
        driver.observe(bench.look(HONEST_LECTURE))

    assert driver.sine.protected_red_active() is True, (
        "Study alignment alone released Protected Red"
    )
    assert driver.live().phase.value not in {"RESOLVED", "CANCELLED"}


# ---------------------------------------------------------------------------
# C8.3-G — APPROVED_BREAK must never release Protected Red
# ---------------------------------------------------------------------------


def test_c83_g_approved_break_cannot_release_protected_red():
    """Kill the dormant break-escape branch permanently."""

    bench = Bench()
    bench.red(True)
    driver = bench.driver

    # Publish a real approved-break context so Resource Intent genuinely
    # reports APPROVED_BREAK, then feed that observation to Red SINE.
    assert bench.intent.publish_study_context(
        StudyContext(
            block_id="BLOCK-C83",
            generation=1,
            display_state="BREAK",
            subject=SUBJECT,
            task=TASK,
            protection_active=False,
            planned_break_active=True,
            remaining_seconds=600,
            published_monotonic_ns=time.monotonic_ns(),
            keywords=KEYWORDS,
            important_keywords=IMPORTANT,
        )
    )
    context = bench.look(INSTAGRAM)
    assert (
        context.resource_intent.verdict.classification
        is ResourceIntent.APPROVED_BREAK
    ), "the lab needs a genuine APPROVED_BREAK observation"

    driver.observe(context)

    assert driver.sine.protected_red_active() is True, (
        "an approved break released Protected Red -- this is the dormant "
        "escape route and it must stay closed"
    )
    assert driver.live().phase.value not in {"RESOLVED", "CANCELLED"}


# ---------------------------------------------------------------------------
# C8.3-H — a managed COSECANT break cannot START under Red
# ---------------------------------------------------------------------------


def test_c83_h_managed_break_cannot_start_under_protected_red():
    bench = Bench()
    services = bench.quiet.services
    coordinator = bench.quiet.coordinator

    prepared = services.study.prepare(
        subject=SUBJECT,
        task=TASK,
        planned_seconds=3600,
        keywords=KEYWORDS,
        important_keywords=IMPORTANT,
    )
    assert bool(getattr(prepared, "accepted", False)), "study prepare failed"
    started = services.study.start()
    assert bool(getattr(started, "accepted", False)), "study start failed"

    # Re-publish the runtime's own context so Resource Intent agrees.
    study_snapshot = services.study.snapshot()
    assert services.resource_intent.publish_study_context(
        StudyContext(
            block_id=study_snapshot.block_id,
            generation=study_snapshot.generation,
            display_state="ACTIVE",
            subject=SUBJECT,
            task=TASK,
            protection_active=True,
            planned_break_active=False,
            remaining_seconds=3600,
            published_monotonic_ns=time.monotonic_ns(),
            keywords=KEYWORDS,
            important_keywords=IMPORTANT,
            context_token=study_snapshot.context_token,
        )
    )

    bench.red(True)
    context = bench.look(HONEST_LECTURE)
    assert context.resource_intent.protected_red_active is True

    refusal = coordinator._break_admission_refusal(context)
    assert refusal, (
        "Monitor admitted a managed COSECANT break while Protected Red was "
        "active -- that is a direct escape from the intervention"
    )
    assert "red" in refusal.lower(), (
        f"the refusal must name Protected Red, got: {refusal!r}"
    )
    assert services.cosecant.snapshot().state.value not in {
        "BREAK_ACTIVE",
        "BREAK_COMPLETE",
    }
