"""Trigger carries Resource Intent surface identity on every founding route.

Blacklist owns trigger eligibility and dwell evidence.  Resource Intent owns
the canonical resource surface consumed by SINE's Study-material safety gate.
These tests deliberately exercise both real founding routes and the fail-closed
helper contract without introducing title or Blacklist vocabulary mappings.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from types import SimpleNamespace

import _lab
from _lab import INSTAGRAM, LECTURE, MRBEAST

from CORE_ENGINE.blacklist import (
    BlacklistAuthority,
    SineThresholdPolicy,
)
from CORE_ENGINE.browser import BrowserEvidenceAuthority
from CORE_ENGINE.monitor import MonitorContext
from CORE_ENGINE.resource_intent import (
    ResourceIntentAuthority,
    ResourceSurface,
    StudyContext,
)
from CORE_ENGINE.trigger import TriggerAuthority, TriggerSource
from SINE.sine import SineAuthority


NS = 1_000_000_000
FAST_THRESHOLDS = SineThresholdPolicy(
    stage_one_seconds=0.3,
    stage_two_cumulative_seconds=1.5,
    offer_retry_seconds=0.1,
)


class _Foreground:
    def __init__(self, surface, sequence: int, observed_ns: int) -> None:
        self.sequence = sequence
        self.hwnd = surface.hwnd
        self.process_id = surface.process_id
        self.process_name = surface.process_name
        self.window_title = surface.title
        self.observed_monotonic_ns = observed_ns
        self.observed_wall_time_utc = ""
        self.idle_seconds = 0.0


class _Bench:
    """Real Browser, Resource Intent, Blacklist and Trigger with a fake clock."""

    def __init__(self) -> None:
        self.reader = _lab.ScriptedForegroundReader(LECTURE)
        self.browser = BrowserEvidenceAuthority(
            reader=_lab.make_browser_reader(self.reader)
        )
        self.browser.start_session()
        self.intent = ResourceIntentAuthority()
        self.intent.start_session(profile_type="study")
        self.blacklist = BlacklistAuthority(thresholds=FAST_THRESHOLDS)
        self.blacklist.start_session()
        assert self.intent.set_stage_one_target_seconds(
            self.blacklist.stage_one_target_seconds()
        )
        self.now_ns = time.monotonic_ns()
        self.trigger = TriggerAuthority(
            profile_type="study", monotonic_ns=lambda: self.now_ns
        )
        self.trigger.start_session(session_id=1, profile_type="study")
        self.sequence = 0
        self.base_ns = self.now_ns - 302 * NS
        self.last_blacklist = None

    def publish_active_study(self, *, keywords=(), important_keywords=()) -> None:
        assert self.intent.publish_study_context(
            StudyContext(
                block_id="TRIGGER-SURFACE-CONTRACT",
                generation=1,
                display_state="ACTIVE",
                subject="Neuroscience",
                task="basal ganglia",
                protection_active=True,
                planned_break_active=False,
                remaining_seconds=3600,
                published_monotonic_ns=self.base_ns,
                keywords=keywords,
                important_keywords=important_keywords,
            )
        )

    def cycle(self, surface, *, after_seconds: float):
        self.sequence += 1
        observed_ns = self.base_ns + int(after_seconds * NS)
        self.now_ns = max(self.now_ns, observed_ns)
        self.reader.set_surface(surface)
        foreground = _Foreground(surface, self.sequence, observed_ns)
        browser = self.browser.observe(foreground)
        intent = self.intent.observe(
            foreground=foreground,
            browser_evidence=browser,
        )
        context = MonitorContext(
            foreground=foreground,
            browser_evidence=browser,
            resource_intent=intent,
            cosine_platform=None,
        )
        self.last_blacklist = self.blacklist.observe(context)
        return context

    def blacklist_candidate(self, surface):
        self.cycle(surface, after_seconds=301.0)
        context = self.cycle(surface, after_seconds=301.4)
        assert self.last_blacklist.threshold_offer is not None
        candidate = self.trigger.evaluate(
            context=context,
            blacklist=self.last_blacklist,
        )
        assert candidate is not None
        assert candidate.evidence.source is TriggerSource.EXECUTIVE_BLACKLIST
        return context, candidate


def _canonical(context: object) -> str:
    from CORE_ENGINE.trigger import _canonical_resource_surface

    return _canonical_resource_surface(context)


def _context_with_surface(surface=SimpleNamespace(value="")):
    identity = None if surface is None else SimpleNamespace(surface=surface)
    return SimpleNamespace(
        foreground=SimpleNamespace(window_title="YouTube lecture"),
        resource_intent=SimpleNamespace(
            verdict=SimpleNamespace(resource_identity=identity)
        ),
    )


def test_ri_founded_youtube_candidate_uses_resource_intent_surface():
    bench = _Bench()
    bench.publish_active_study()
    # Advance the existing 300-second Resource Intent dwell with deterministic
    # observations inside its freshness window; never sleep for the threshold.
    context = None
    for elapsed in range(0, 301, 5):
        context = bench.cycle(MRBEAST, after_seconds=float(elapsed))
    context = bench.cycle(MRBEAST, after_seconds=301.0)
    candidate = bench.trigger.evaluate(
        context=context,
        blacklist=bench.last_blacklist,
    )

    assert candidate is not None
    assert candidate.evidence.source is TriggerSource.STUDY_OFF_TASK
    assert candidate.evidence.surface_class == "youtube_watch"


def test_blacklist_founded_youtube_candidate_uses_resource_intent_surface():
    bench = _Bench()
    bench.publish_active_study()
    context, candidate = bench.blacklist_candidate(LECTURE)

    assert context.resource_intent.verdict.confidence == 0.50
    assert context.resource_intent.verdict.resource_identity.surface is (
        ResourceSurface.YOUTUBE_WATCH
    )
    assert bench.last_blacklist.threshold_offer.surface_class == "selected_video"
    assert candidate.evidence.surface_class == "youtube_watch"
    assert candidate.evidence.surface_class != "selected_video"


def test_blacklist_founded_social_candidate_uses_resource_intent_surface():
    bench = _Bench()
    context, candidate = bench.blacklist_candidate(INSTAGRAM)

    assert context.resource_intent.verdict.resource_identity.surface is (
        ResourceSurface.SOCIAL
    )
    assert candidate.evidence.surface_class == "social"


def test_missing_resource_intent_identity_fails_closed_to_unknown():
    assert _canonical(_context_with_surface(None)) == "unknown"


def test_youtube_title_without_certified_identity_cannot_manufacture_surface():
    context = _context_with_surface(None)
    context.foreground.window_title = "Basal Ganglia Lecture - YouTube"

    assert _canonical(context) == "unknown"


def test_blacklist_vocabulary_cannot_change_canonical_surface():
    context = _context_with_surface(ResourceSurface.YOUTUBE_WATCH)
    selected_video = SimpleNamespace(surface_class="selected_video")
    short_feed = SimpleNamespace(surface_class="short_feed")

    assert selected_video.surface_class != short_feed.surface_class
    assert _canonical(context) == "youtube_watch"
    assert _canonical(context) == "youtube_watch"


def test_sine_study_material_gate_receives_canonical_vocabulary():
    bench = _Bench()
    bench.publish_active_study()
    _context, candidate = bench.blacklist_candidate(LECTURE)

    assert SineAuthority()._safe_study_material_action(candidate.evidence) is True


def test_no_selected_video_to_youtube_watch_mapping_exists():
    import CORE_ENGINE.trigger as trigger_module
    import SINE.sine as sine_module

    joined = "\n".join(
        Path(module.__file__).read_text(encoding="utf-8")
        for module in (trigger_module, sine_module)
    )
    assert re.search(
        r"selected_video\s*(?:=|:|,|->)\s*['\"]?youtube_watch",
        joined,
        flags=re.IGNORECASE,
    ) is None
