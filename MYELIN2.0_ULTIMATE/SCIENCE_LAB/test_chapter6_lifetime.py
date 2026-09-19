"""Isolated Chapter 6 lifetime-summary contract tests; no live database
access. Uses disposable/injected readers (never the real
PERSISTENCE.storage.read_mirl_events / read_trigger_platform_keys /
read_cosine_events) throughout, per the mandatory lifetime test lists in the
20260915 Lifetime Refresh and Final Four-Card Completion engineering guides.

Reuses the same real ``MirlEvent``-producing fixtures
(``EpisodeBuilder``/``successful_episode``) SCIENCE_LAB/test_phase2_best_worst
_return.py already built and tests, and the real ``COSINE.cosine.CosineEvent``
dataclass for COSINE fixtures -- not hand-rolled duck-typed stand-ins -- so
these tests exercise chapter6_lifetime.py against exactly the same event
shapes production code returns.
"""

from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path

_SCIENCE_LAB_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCIENCE_LAB_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if "SCIENCE_LAB" not in sys.modules:
    _science_lab_package = types.ModuleType("SCIENCE_LAB")
    _science_lab_package.__path__ = [str(_SCIENCE_LAB_DIR)]
    sys.modules["SCIENCE_LAB"] = _science_lab_package

from COSINE.cosine import CosineEvent, EventClass
from SCIENCE_LAB.analysis import AVAILABLE, UNAVAILABLE
from SCIENCE_LAB.chapter6_lifetime import Chapter6LifetimeSummary, build_lifetime_summary
from SCIENCE_LAB.test_phase2_best_worst_return import EpisodeBuilder, successful_episode

NANOSECONDS = 1_000_000_000
FOUR_CARD_KEYS = (
    "best_return", "worst_return", "top_distraction_platform", "top_ott_platform",
)


def returned_episode(episode_id: str, displayed_seconds: int, latency_seconds: int):
    displayed = displayed_seconds * NANOSECONDS
    onset = displayed + latency_seconds * NANOSECONDS
    verified = onset + 10 * NANOSECONDS
    closed = verified + 60 * NANOSECONDS
    return successful_episode(episode_id, displayed, onset, verified, closed)


def events_of(*builders) -> tuple:
    return tuple(event for builder in builders for event in builder.events)


def build_summary(
    *,
    read_mirl_events=lambda: (),
    read_trigger_platform_keys=lambda: (),
    read_cosine_events=lambda: (),
):
    """Every call in this file must inject all three readers -- leaving one
    at its default ``None`` would fall through to the REAL production
    reader and reach the live database, which this file must never do."""

    return build_lifetime_summary(
        read_mirl_events=read_mirl_events,
        read_trigger_platform_keys=read_trigger_platform_keys,
        read_cosine_events=read_cosine_events,
    )


def cosine_closed_event(
    cosine_session_id: str,
    generation: int,
    platform_seconds: dict,
    *,
    event_id: str | None = None,
    sequence: int = 1,
) -> CosineEvent:
    payload = json.dumps({
        "closure_reason": "STOPPED", "closure_outcome": "INCOMPLETE",
        "foreground_ott_seconds": round(sum(platform_seconds.values()), 6),
        "platform_seconds": platform_seconds, "hopper_count": max(0, len(platform_seconds) - 1),
        "chosen_break_minutes": None,
    })
    return CosineEvent(
        event_id=event_id or f"evt-{cosine_session_id}-{generation}",
        session_id=1,
        cosine_session_id=cosine_session_id,
        sequence=sequence,
        event_name="COSINE_SESSION_CLOSED",
        event_class=EventClass.DERIVED,
        occurred_at_utc="2026-01-01T00:00:00Z",
        monotonic_ns=1,
        generation=generation,
        platform_key="",
        content_title="",
        request_id="",
        evidence_token="",
        payload_json=payload,
    )


class BuildLifetimeSummaryTests(unittest.TestCase):
    def test_summary_is_immutable_dataclass_with_four_keyed_results(self) -> None:
        summary = build_summary()
        self.assertIsInstance(summary, Chapter6LifetimeSummary)
        for key in FOUR_CARD_KEYS:
            result = getattr(summary, key)
            self.assertEqual(result.key, key)

    def test_empty_lifetime_history_is_unavailable_not_zero(self) -> None:
        summary = build_summary()
        for key in FOUR_CARD_KEYS:
            result = getattr(summary, key)
            self.assertEqual(result.status, UNAVAILABLE)
            self.assertIsNone(result.value)

    def test_one_valid_successful_closed_episode(self) -> None:
        events = events_of(returned_episode("epi-1", 1, 42))
        summary = build_summary(read_mirl_events=lambda: events)
        self.assertEqual(summary.best_return.status, AVAILABLE)
        self.assertEqual(summary.best_return.value, summary.worst_return.value)
        self.assertEqual(summary.best_return.value, 42 * NANOSECONDS)
        self.assertEqual(summary.best_return.supporting_count, 1)

    def test_many_eligible_episodes_across_multiple_sessions(self) -> None:
        # different "sessions" simulated via unrelated monotonic bases --
        # each episode's latency is still an intra-episode difference, so
        # this must not corrupt the lifetime min/max.
        builder_a = returned_episode("epi-a", 1, 10)
        builder_b = returned_episode("epi-b", 999_999, 90)
        builder_c = returned_episode("epi-c", 5, 33)
        events = events_of(builder_a, builder_b, builder_c)
        summary = build_summary(read_mirl_events=lambda: events)
        self.assertEqual(summary.best_return.value, 10 * NANOSECONDS)
        self.assertEqual(summary.worst_return.value, 90 * NANOSECONDS)
        self.assertEqual(summary.best_return.supporting_count, 3)

    def test_relapse_then_final_successful_attempt_counts_only_final_onset(self) -> None:
        builder = EpisodeBuilder("epi-relapse", displayed_ns=1 * NANOSECONDS)
        builder.relapsed_attempt(
            "attempt-1", 1,
            start_ns=2 * NANOSECONDS,
            verified_ns=3 * NANOSECONDS,
            relapse_ns=4 * NANOSECONDS,
        )
        builder.close_successfully(
            "attempt-2", 2,
            start_ns=50 * NANOSECONDS,
            verified_ns=51 * NANOSECONDS,
            closed_ns=52 * NANOSECONDS,
        )
        summary = build_summary(read_mirl_events=lambda: tuple(builder.events))
        self.assertEqual(summary.best_return.status, AVAILABLE)
        self.assertEqual(summary.best_return.value, 49 * NANOSECONDS)  # 50 - 1

    def test_interrupted_attempt_alone_never_becomes_a_sample(self) -> None:
        builder = EpisodeBuilder("epi-interrupted", displayed_ns=1 * NANOSECONDS)
        builder.interrupt_attempt(
            "attempt-1", 1,
            start_ns=2 * NANOSECONDS,
            interrupt_ns=3 * NANOSECONDS,
        )
        summary = build_summary(read_mirl_events=lambda: tuple(builder.events))
        self.assertEqual(summary.best_return.status, UNAVAILABLE)

    def test_evidence_gap_episode_is_skipped_not_crashed(self) -> None:
        # an episode_closed(RETURNED) with no supporting durable chain at all
        builder = EpisodeBuilder("epi-gap", displayed_ns=1 * NANOSECONDS)
        builder.add(
            "episode_closed", 2 * NANOSECONDS,
            attempt_id="attempt-1", attempt_index=1, reason="RETURNED",
        )
        summary = build_summary(read_mirl_events=lambda: tuple(builder.events))
        self.assertEqual(summary.best_return.status, UNAVAILABLE)
        self.assertIn("excluded", summary.best_return.reason)

    def test_broken_support_chain_is_excluded_but_valid_episode_still_counts(self) -> None:
        good = returned_episode("epi-good", 1, 15)
        broken = EpisodeBuilder("epi-broken", displayed_ns=1 * NANOSECONDS)
        broken.add(
            "episode_closed", 2 * NANOSECONDS,
            attempt_id="attempt-1", attempt_index=1, reason="RETURNED",
        )
        events = events_of(good) + tuple(broken.events)
        summary = build_summary(read_mirl_events=lambda: events)
        self.assertEqual(summary.best_return.status, AVAILABLE)
        self.assertEqual(summary.best_return.value, 15 * NANOSECONDS)
        self.assertIn("excluded", summary.best_return.reason)

    def test_ambiguous_closure_identity_is_excluded(self) -> None:
        # two separately-built RETURNED closes sharing one episode_id
        first = successful_episode("epi-dup", 1 * NANOSECONDS, 2 * NANOSECONDS, 3 * NANOSECONDS, 4 * NANOSECONDS)
        second = successful_episode("epi-dup", 1 * NANOSECONDS, 5 * NANOSECONDS, 6 * NANOSECONDS, 7 * NANOSECONDS)
        events = events_of(first, second)
        summary = build_summary(read_mirl_events=lambda: events)
        self.assertEqual(summary.best_return.status, UNAVAILABLE)
        self.assertIn("excluded", summary.best_return.reason)

    def test_identical_best_and_worst_at_n_equals_one(self) -> None:
        events = events_of(returned_episode("epi-single", 1, 7))
        summary = build_summary(read_mirl_events=lambda: events)
        self.assertEqual(summary.best_return.value, summary.worst_return.value)

    def test_true_min_max_at_n_greater_than_one(self) -> None:
        events = events_of(
            returned_episode("epi-x", 1, 5),
            returned_episode("epi-y", 100, 500),
            returned_episode("epi-z", 200, 50),
        )
        summary = build_summary(read_mirl_events=lambda: events)
        self.assertEqual(summary.best_return.value, 5 * NANOSECONDS)
        self.assertEqual(summary.worst_return.value, 500 * NANOSECONDS)

    def test_read_error_surfaces_as_unavailable_not_a_crash_and_not_zero(self) -> None:
        def _raise():
            raise RuntimeError("simulated disk failure")

        summary = build_summary(read_mirl_events=_raise)
        self.assertEqual(summary.best_return.status, UNAVAILABLE)
        self.assertTrue(summary.best_return.reason.startswith("read_error:"))
        self.assertIsNone(summary.best_return.value)

    def test_no_science_lab_experiment_window_is_applied(self) -> None:
        # an episode far outside any plausible "experiment window" still
        # counts -- lifetime scope has no window at all.
        events = events_of(returned_episode("epi-far", 999_999_999, 3))
        summary = build_summary(read_mirl_events=lambda: events)
        self.assertEqual(summary.best_return.status, AVAILABLE)

    def test_repeated_calls_are_independent_and_do_not_accumulate(self) -> None:
        events = events_of(returned_episode("epi-repeat", 1, 9))
        first = build_summary(read_mirl_events=lambda: events)
        second = build_summary(read_mirl_events=lambda: events)
        self.assertEqual(first.best_return.value, second.best_return.value)
        self.assertIsNot(first, second)

    def test_no_scientific_selection_happens_outside_min_max_of_certified_samples(self) -> None:
        # sanity: values are always exactly drawn from the sample population
        events = events_of(
            returned_episode("epi-p", 1, 11),
            returned_episode("epi-q", 50, 22),
        )
        summary = build_summary(read_mirl_events=lambda: events)
        values = {11 * NANOSECONDS, 22 * NANOSECONDS}
        self.assertIn(summary.best_return.value, values)
        self.assertIn(summary.worst_return.value, values)


class TopDistractionPlatformTests(unittest.TestCase):
    """Mandatory TOP DISTRACTION PLATFORM tests from the 20260915 Final
    Four-Card Completion guide."""

    def test_no_trigger_rows_is_unavailable(self) -> None:
        summary = build_summary(read_trigger_platform_keys=lambda: ())
        self.assertEqual(summary.top_distraction_platform.status, UNAVAILABLE)
        self.assertIsNone(summary.top_distraction_platform.value)

    def test_one_platform_only(self) -> None:
        keys = ("youtube",) * 10
        summary = build_summary(read_trigger_platform_keys=lambda: keys)
        result = summary.top_distraction_platform
        self.assertEqual(result.status, AVAILABLE)
        self.assertEqual(result.value, "YouTube")
        self.assertEqual(result.supporting_count, 10)

    def test_multiple_platforms_greatest_count_wins(self) -> None:
        keys = ("youtube",) * 10 + ("instagram",) * 4 + ("facebook",) * 2
        summary = build_summary(read_trigger_platform_keys=lambda: keys)
        self.assertEqual(summary.top_distraction_platform.value, "YouTube")
        self.assertEqual(summary.top_distraction_platform.supporting_count, 10)

    def test_equal_max_is_a_tie(self) -> None:
        keys = ("youtube",) * 10 + ("instagram",) * 10
        summary = build_summary(read_trigger_platform_keys=lambda: keys)
        result = summary.top_distraction_platform
        self.assertEqual(result.status, AVAILABLE)
        self.assertEqual(result.value, "TIE")
        self.assertIn("YouTube", result.reason)
        self.assertIn("Instagram", result.reason)

    def test_missing_or_blank_platform_key_rows_are_ignored_safely(self) -> None:
        keys = ("youtube", "", "   ", None, "youtube")
        summary = build_summary(read_trigger_platform_keys=lambda: keys)
        result = summary.top_distraction_platform
        self.assertEqual(result.status, AVAILABLE)
        self.assertEqual(result.value, "YouTube")
        self.assertEqual(result.supporting_count, 2)

    def test_malformed_reader_failure_fails_closed_not_crashed(self) -> None:
        def _raise():
            raise RuntimeError("simulated trigger read failure")

        summary = build_summary(read_trigger_platform_keys=_raise)
        result = summary.top_distraction_platform
        self.assertEqual(result.status, UNAVAILABLE)
        self.assertTrue(result.reason.startswith("read_error:"))

    def test_repeated_refresh_same_result_no_duplication(self) -> None:
        keys = ("youtube",) * 3 + ("instagram",) * 1
        first = build_summary(read_trigger_platform_keys=lambda: keys)
        second = build_summary(read_trigger_platform_keys=lambda: keys)
        self.assertEqual(first.top_distraction_platform.value, second.top_distraction_platform.value)
        self.assertEqual(
            first.top_distraction_platform.supporting_count,
            second.top_distraction_platform.supporting_count,
        )

    def test_unknown_platform_key_falls_back_to_normalized_display(self) -> None:
        keys = ("some_unlisted_key",) * 3
        summary = build_summary(read_trigger_platform_keys=lambda: keys)
        self.assertEqual(summary.top_distraction_platform.value, "Some Unlisted Key")


class TopOttPlatformTests(unittest.TestCase):
    """Mandatory TOP OTT PLATFORM tests from the 20260915 Final Four-Card
    Completion guide."""

    def test_no_valid_closed_history_is_unavailable(self) -> None:
        summary = build_summary(read_cosine_events=lambda: ())
        self.assertEqual(summary.top_ott_platform.status, UNAVAILABLE)
        self.assertIsNone(summary.top_ott_platform.value)

    def test_one_platform(self) -> None:
        events = (cosine_closed_event("cs-1", 1, {"prime_video": 1000.0}),)
        summary = build_summary(read_cosine_events=lambda: events)
        result = summary.top_ott_platform
        self.assertEqual(result.status, AVAILABLE)
        self.assertEqual(result.value, "Prime Video")
        self.assertEqual(result.supporting_count, 1)

    def test_multiple_platforms_greatest_seconds_wins(self) -> None:
        events = (
            cosine_closed_event("cs-1", 1, {"prime_video": 1000.0}),
            cosine_closed_event("cs-2", 1, {"netflix": 500.0}),
        )
        summary = build_summary(read_cosine_events=lambda: events)
        self.assertEqual(summary.top_ott_platform.value, "Prime Video")

    def test_multi_platform_hopper_session_allocates_each_platform_separately(self) -> None:
        events = (cosine_closed_event("cs-1", 1, {"prime_video": 600.0, "netflix": 300.0}),)
        summary = build_summary(read_cosine_events=lambda: events)
        self.assertEqual(summary.top_ott_platform.value, "Prime Video")

    def test_multiple_sessions_accumulate_across_all_valid_closed_sessions(self) -> None:
        events = (
            cosine_closed_event("cs-1", 1, {"netflix": 400.0}),
            cosine_closed_event("cs-2", 1, {"netflix": 700.0}),
        )
        summary = build_summary(read_cosine_events=lambda: events)
        self.assertEqual(summary.top_ott_platform.value, "Netflix")
        self.assertEqual(summary.top_ott_platform.supporting_count, 2)

    def test_exact_tie(self) -> None:
        events = (
            cosine_closed_event("cs-1", 1, {"prime_video": 1000.0}),
            cosine_closed_event("cs-2", 1, {"netflix": 1000.0}),
        )
        summary = build_summary(read_cosine_events=lambda: events)
        result = summary.top_ott_platform
        self.assertEqual(result.status, AVAILABLE)
        self.assertEqual(result.value, "TIE")
        self.assertIn("Netflix", result.reason)
        self.assertIn("Prime Video", result.reason)

    def test_malformed_duration_is_skipped_per_record(self) -> None:
        events = (
            cosine_closed_event("cs-1", 1, {"netflix": 1000.0}),
            CosineEvent(
                event_id="evt-bad", session_id=1, cosine_session_id="cs-2", sequence=1,
                event_name="COSINE_SESSION_CLOSED", event_class=EventClass.DERIVED,
                occurred_at_utc="2026-01-01T00:00:00Z", monotonic_ns=1, generation=1,
                platform_key="", content_title="", request_id="", evidence_token="",
                payload_json="{not valid json",
            ),
        )
        summary = build_summary(read_cosine_events=lambda: events)
        self.assertEqual(summary.top_ott_platform.value, "Netflix")

    def test_open_unclosed_session_without_certified_supported_time_is_excluded(self) -> None:
        open_event = CosineEvent(
            event_id="evt-open", session_id=1, cosine_session_id="cs-1", sequence=1,
            event_name="COSINE_SESSION_STARTED", event_class=EventClass.DERIVED,
            occurred_at_utc="2026-01-01T00:00:00Z", monotonic_ns=1, generation=1,
            platform_key="netflix", content_title="", request_id="", evidence_token="",
            payload_json="{}",
        )
        summary = build_summary(read_cosine_events=lambda: (open_event,))
        self.assertEqual(summary.top_ott_platform.status, UNAVAILABLE)

    def test_repeated_refresh_deterministic_identical_result(self) -> None:
        events = (cosine_closed_event("cs-1", 1, {"prime_video": 800.0}),)
        first = build_summary(read_cosine_events=lambda: events)
        second = build_summary(read_cosine_events=lambda: events)
        self.assertEqual(first.top_ott_platform.value, second.top_ott_platform.value)
        self.assertEqual(first.top_ott_platform.reason, second.top_ott_platform.reason)

    def test_duplicate_closure_for_same_session_generation_counted_once(self) -> None:
        events = (
            cosine_closed_event("cs-1", 1, {"netflix": 1000.0}, event_id="evt-1"),
            cosine_closed_event("cs-1", 1, {"netflix": 1000.0}, event_id="evt-2"),
        )
        summary = build_summary(read_cosine_events=lambda: events)
        self.assertEqual(summary.top_ott_platform.supporting_count, 1)

    def test_read_error_surfaces_as_unavailable_not_a_crash(self) -> None:
        def _raise():
            raise RuntimeError("simulated COSINE read failure")

        summary = build_summary(read_cosine_events=_raise)
        result = summary.top_ott_platform
        self.assertEqual(result.status, UNAVAILABLE)
        self.assertTrue(result.reason.startswith("read_error:"))


if __name__ == "__main__":
    unittest.main()
