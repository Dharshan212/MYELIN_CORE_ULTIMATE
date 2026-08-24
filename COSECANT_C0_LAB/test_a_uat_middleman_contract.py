"""Final Study-Material law: one human declaration, no hidden middleman."""

from __future__ import annotations

import dataclasses
import time

import pytest

import _lab
from _lab import ScriptedForegroundReader, Surface, build_services

from CORE_ENGINE.resource_intent import AllowanceOutcome, ResourceIntent, StudyContext


PBS_A = Surface(
    process_name="chrome",
    title="Your Brain: Who's in Control? | Full Documentary | NOVA | PBS - YouTube",
    url="https://www.youtube.com/watch?v=NOVA_BRAIN_A",
)
PBS_B = Surface(
    process_name="chrome",
    title="The Brain with David Eagleman | PBS - YouTube",
    url="https://www.youtube.com/watch?v=PBS_BRAIN_B",
)
SNIPPING_TOOL = Surface(
    process_name="snippingtool",
    title="Snipping Tool",
    url="",
)


class Bench:
    def __init__(self) -> None:
        self.foreground = ScriptedForegroundReader(PBS_A)
        self.services = build_services(foreground=self.foreground, fast_cosecant=True)
        self.intent = self.services.resource_intent
        self.browser = self.services.browser
        self.browser.start_session()
        self.intent.start_session(profile_type="general")

        assert self.services.study.prepare(
            subject="Neuroscience",
            task="Your Brain: Who's in Control?",
            planned_seconds=3600,
            keywords=(),
            important_keywords=(),
        ).accepted
        assert self.services.study.start().accepted
        self.publish_context()

    def publish_context(self) -> None:
        snapshot = self.services.study.snapshot()
        state = snapshot.state.value
        assert self.intent.publish_study_context(
            StudyContext(
                block_id=snapshot.block_id,
                generation=snapshot.generation,
                display_state=state,
                subject=snapshot.subject,
                task=snapshot.task,
                protection_active=state == "ACTIVE",
                planned_break_active=state == "BREAK",
                remaining_seconds=max(0, int(snapshot.remaining_seconds or 0)),
                published_monotonic_ns=time.monotonic_ns(),
                keywords=snapshot.keywords,
                important_keywords=snapshot.important_keywords,
            )
        )

    def observe(self, surface: Surface):
        self.foreground.set_surface(surface)
        foreground = self.foreground.observe()
        evidence = self.browser.observe(foreground)
        return self.intent.observe(foreground=foreground, browser_evidence=evidence)

    def declare(self, snapshot):
        return self.intent.record_study_material_allowance(
            study_context_token=snapshot.verdict.study_context_token,
            resource_key=snapshot.resource_key,
            granted_monotonic_ns=time.monotonic_ns(),
        )


@pytest.fixture
def bench():
    harness = Bench()
    try:
        yield harness
    finally:
        harness.services.storage.shutdown()


def test_a_uncertain_exact_resource_accepts_the_human_declaration(bench):
    before = bench.observe(PBS_A)
    assert before.verdict.classification is ResourceIntent.UNCERTAIN
    assert before.verdict.confidence == 0.50
    assert before.verdict.resource_identity.browser_evidence_certified is True
    assert before.resource_key

    result = bench.declare(before)

    assert result.granted is True
    assert result.outcome is AllowanceOutcome.GRANTED
    assert result.record is not None
    assert result.record.resource_key == before.resource_key


def test_a2_same_exact_resource_becomes_study_aligned_at_100_percent(bench):
    before = bench.observe(PBS_A)
    assert bench.declare(before).granted

    after = bench.observe(PBS_A)

    assert after.verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert after.verdict.confidence == 1.00
    assert after.verdict.allowance_match is True


def test_b_study_end_before_declaration_is_rejected(bench):
    offer = bench.observe(PBS_A)
    assert bench.services.study.complete().accepted
    bench.publish_context()

    result = bench.declare(offer)

    assert result.granted is False
    assert result.outcome is AllowanceOutcome.DENIED_NO_ACTIVE_BLOCK
    assert bench.intent._allowance is None


def test_c_wrong_exact_resource_does_not_inherit_allowance(bench):
    video_a = bench.observe(PBS_A)
    assert bench.declare(video_a).granted

    video_b = bench.observe(PBS_B)

    assert video_b.resource_key != video_a.resource_key
    assert video_b.verdict.classification is not ResourceIntent.STUDY_ALIGNED
    assert video_b.verdict.allowance_match is False


def test_d_missing_exact_resource_is_rejected(bench):
    offer = bench.observe(PBS_A)

    result = bench.intent.record_study_material_allowance(
        study_context_token=offer.verdict.study_context_token,
        resource_key="",
        granted_monotonic_ns=time.monotonic_ns(),
    )

    assert result.granted is False
    assert result.outcome is AllowanceOutcome.DENIED_UNSAFE_SURFACE
    assert bench.intent._allowance is None


def test_d2_sine_does_not_offer_the_button_without_an_exact_binding():
    from SINE.sine import SineAuthority

    evidence = {
        "study_context_token": "study-token",
        "resource_key": "",
        "resource_observation_token": "observation-token",
        "surface_class": "youtube_watch",
        "browser_evidence_kind": "confirmed_selected_video",
    }
    assert SineAuthority()._safe_study_material_action(evidence) is False


def test_e_focus_interruption_does_not_make_the_declaration_fake_stale(bench):
    offer = bench.observe(PBS_A)
    assert bench.declare(offer).granted

    bench.observe(SNIPPING_TOOL)
    after = bench.observe(PBS_A)

    assert after.verdict.classification is ResourceIntent.STUDY_ALIGNED
    assert after.verdict.confidence == 1.00


def test_f_allowance_has_no_provisional_or_expiry_bureaucracy():
    from CORE_ENGINE.resource_intent import AllowanceRecord

    names = {field.name for field in dataclasses.fields(AllowanceRecord)}
    assert "provisional" not in names
    assert "expires_monotonic_ns" not in names


def test_g_old_middleman_symbols_are_physically_absent_from_production():
    old_symbols = {
        "StudyInterventionRequest",
        "StudyInterventionSelection",
        "StudyInterventionMode",
        "capture_study_intervention",
        "activate_study_intervention",
        "study_material_action_is_current",
        "grant_study_material",
        "close_study_intervention",
        "_intervention_request",
        "_intervention_identity",
        "_awaiting_revalidation",
        "_request_matches",
        "_study_interventions",
        "study_material_capture_refused",
        "DENIED_STALE_REQUEST",
        "DENIED_RESOURCE_CHANGED",
    }
    production = _lab.ULTIMATE
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in production.rglob("*.py")
    )
    present = {symbol for symbol in old_symbols if symbol in text}
    assert not present, present
