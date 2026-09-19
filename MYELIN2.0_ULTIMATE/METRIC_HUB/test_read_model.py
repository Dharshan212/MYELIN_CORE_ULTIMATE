"""Focused disposable-database tests for the lifetime Metric Hub."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from dataclasses import fields, replace
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from COSECANT_STUDY_MODE.cosecant import COSECANT_SCHEMA_VERSION
from CORE_ENGINE.trigger import TRIGGER_SCHEMA_VERSION
from COSINE.cosine import COSINE_SCHEMA_VERSION
from MINE.mine import MINE_SCHEMA_VERSION
from MIRL.mirl import MirlEvent, MirlEventClass, MirlEventName
from SINE.sine import SINE_SCHEMA_VERSION

from METRIC_HUB.read_model import (
    AVAILABLE,
    NO_DATA,
    UNAVAILABLE,
    _project_behaviour_distribution,
    read_lifetime_metric_hub,
)


UTC = "2026-09-17T10:00:00Z"


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY,
            started_at_utc TEXT NOT NULL,
            closed_at_utc TEXT
        );
        CREATE TABLE science_lab_experiments (
            experiment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL
        );
        CREATE TABLE triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            candidate_uid TEXT NOT NULL UNIQUE,
            occurred_monotonic_ns INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE sine_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            episode_uid TEXT NOT NULL,
            candidate_uid TEXT NOT NULL,
            kind TEXT NOT NULL,
            popup_request_id TEXT NOT NULL,
            occurred_monotonic_ns INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE mirl_events (
            event_id TEXT PRIMARY KEY,
            session_id INTEGER,
            episode_id TEXT NOT NULL,
            episode_sequence INTEGER NOT NULL,
            event_name TEXT NOT NULL,
            occurred_monotonic_ns INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE mine_events (
            event_id TEXT PRIMARY KEY,
            session_id INTEGER NOT NULL,
            mine_episode_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            sequence INTEGER NOT NULL,
            event_name TEXT NOT NULL,
            event_class TEXT NOT NULL,
            occurred_at_utc TEXT NOT NULL,
            monotonic_ns INTEGER NOT NULL,
            platform_key TEXT NOT NULL,
            platform_label TEXT NOT NULL,
            request_id TEXT NOT NULL,
            evidence_token TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            schema_version TEXT NOT NULL
        );
        CREATE TABLE cosine_events (
            event_id TEXT PRIMARY KEY,
            session_id INTEGER,
            cosine_session_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            sequence INTEGER NOT NULL,
            event_name TEXT NOT NULL,
            event_class TEXT NOT NULL,
            occurred_at_utc TEXT NOT NULL,
            monotonic_ns INTEGER NOT NULL,
            platform_key TEXT NOT NULL,
            content_title TEXT NOT NULL,
            request_id TEXT NOT NULL,
            evidence_token TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            schema_version TEXT NOT NULL
        );
        CREATE TABLE cosecant_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER,
            break_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL,
            occurred_monotonic_ns INTEGER NOT NULL,
            payload_json TEXT NOT NULL
        );
        """
    )


def _enum_json(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_enum_json(item) for item in value]
    return value


class _MirlEpisode:
    def __init__(self, episode_id: str, candidate_uid: str, session_id: int = 1) -> None:
        self.episode_id = episode_id
        self.candidate_uid = candidate_uid
        self.session_id = session_id
        self.events: list[MirlEvent] = []
        self.sequence = 0
        created = self.add("episode_created", 100)
        self.add("sine_displayed", 100, supports=(created.event_id,), sine_stage=1)

    def add(
        self,
        name: str,
        when: int,
        *,
        attempt_id: str = "",
        attempt_index: int = 0,
        supports: tuple[str, ...] = (),
        reason: str = "",
        sine_stage: int = 0,
    ) -> MirlEvent:
        self.sequence += 1
        event_name = MirlEventName(name)
        derived = {
            MirlEventName.RETURN_UNVERIFIED,
            MirlEventName.RETURN_VERIFIED,
            MirlEventName.EPISODE_CLOSED,
        }
        event = MirlEvent(
            kind=f"MIRL_{name.upper()}",
            event_name=event_name,
            event_class=(
                MirlEventClass.DERIVED
                if event_name in derived
                else MirlEventClass.OBSERVED
            ),
            event_id=f"{self.episode_id}-{self.sequence}-{name}",
            episode_id=self.episode_id,
            episode_sequence=self.sequence,
            occurred_monotonic_ns=when,
            occurred_wall_time_utc=UTC,
            session_id=self.session_id,
            candidate_uid=self.candidate_uid,
            operational_event_id=self.sequence,
            attempt_id=attempt_id,
            attempt_index=attempt_index,
            sine_stage=sine_stage,
            supporting_event_ids=supports,
            reason=reason,
        )
        self.events.append(event)
        return event

    def close_successfully(self) -> None:
        attempt = "attempt-1"
        started = self.add(
            "return_verification_started", 200, attempt_id=attempt, attempt_index=1
        )
        self.add(
            "return_unverified",
            200,
            attempt_id=attempt,
            attempt_index=1,
            supports=(started.event_id,),
        )
        completed = self.add(
            "return_verification_completed", 300, attempt_id=attempt, attempt_index=1
        )
        verified = self.add(
            "return_verified",
            300,
            attempt_id=attempt,
            attempt_index=1,
            supports=(completed.event_id,),
        )
        self.add(
            "closure_confirmation_started",
            300,
            attempt_id=attempt,
            attempt_index=1,
            supports=(verified.event_id,),
        )
        closure = self.add(
            "closure_confirmation_completed", 400, attempt_id=attempt, attempt_index=1
        )
        self.add(
            "episode_closed",
            400,
            attempt_id=attempt,
            attempt_index=1,
            supports=(closure.event_id,),
            reason="RETURNED",
        )


class MetricHubFixture:
    def __init__(self, root: Path) -> None:
        self.path = root / "metric-hub.db"
        self.connection = sqlite3.connect(self.path)
        _create_schema(self.connection)

    def close(self) -> None:
        self.connection.commit()
        self.connection.close()

    def sessions(self, *identities: int) -> None:
        for index, identity in enumerate(identities):
            self.session(
                identity,
                started_at_utc=f"2026-09-17T09:{index:02d}:00Z",
            )

    def session(
        self,
        identity: int,
        *,
        started_at_utc: str,
        closed_at_utc: str | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO sessions(id,started_at_utc,closed_at_utc) VALUES(?,?,?)",
            (identity, started_at_utc, closed_at_utc),
        )

    def sine(
        self,
        episode: str,
        candidate: str,
        stage: int,
        request: str,
        *,
        session_id: int = 1,
        kind: str = "SINE_DISPLAYED",
        when: int = 100,
        wall: str = UTC,
    ) -> None:
        payload = {
            "kind": kind,
            "session_id": session_id,
            "episode_uid": episode,
            "candidate_uid": candidate,
            "stage": stage,
            "popup_request_id": request,
            "occurred_monotonic_ns": when,
            "occurred_wall_time_utc": wall,
            "schema_version": SINE_SCHEMA_VERSION,
        }
        self.connection.execute(
            "INSERT INTO sine_facts(session_id,episode_uid,candidate_uid,kind,"
            "popup_request_id,occurred_monotonic_ns,payload_json) VALUES(?,?,?,?,?,?,?)",
            (session_id, episode, candidate, kind, request, when, json.dumps(payload)),
        )

    def trigger(
        self,
        candidate: str,
        *,
        session_id: int = 1,
        platform: str = "youtube",
        surface: str = "youtube_watch",
        source: str = "executive_blacklist",
        reason: str = "executive_blacklist_dwell",
        source_rule_id: str = "EB-YOUTUBE-VIDEO-001",
        study_context_token: str = "",
        when: int = 90,
    ) -> None:
        payload = {
            "candidate_uid": candidate,
            "candidate_number": 1,
            "session_id": session_id,
            "profile_type": "GENERAL",
            "reason": reason,
            "created_monotonic_ns": when,
            "trigger": True,
            "schema_version": TRIGGER_SCHEMA_VERSION,
            "evidence": {
                "source": source,
                "source_rule_id": source_rule_id,
                "source_policy_version": "test-policy-v1",
                "observed_monotonic_ns": when,
                "platform_key": platform,
                "surface_class": surface,
                "study_context_token": study_context_token,
                "evidence_digest": f"digest-{candidate}",
            },
            "recovery_model": {"model_category": "social_feed"},
        }
        self.connection.execute(
            "INSERT INTO triggers(session_id,candidate_uid,occurred_monotonic_ns,payload_json) "
            "VALUES(?,?,?,?)",
            (session_id, candidate, when, json.dumps(payload)),
        )

    def mirl(self, episode: _MirlEpisode) -> None:
        for event in episode.events:
            payload = {
                field.name: _enum_json(getattr(event, field.name))
                for field in fields(MirlEvent)
            }
            self.connection.execute(
                "INSERT INTO mirl_events VALUES(?,?,?,?,?,?,?)",
                (
                    event.event_id,
                    event.session_id,
                    event.episode_id,
                    event.episode_sequence,
                    event.event_name.value,
                    event.occurred_monotonic_ns,
                    json.dumps(payload),
                ),
            )

    def mine(
        self,
        sequence: int,
        name: str,
        event_class: str,
        *,
        session_id: int = 1,
        generation: int = 1,
        episode: str = "mine-1",
        payload: dict | None = None,
    ) -> None:
        stored_episode = "" if name == "MINE_CANDIDATE_STARTED" else episode
        self.connection.execute(
            "INSERT INTO mine_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"mine-{session_id}-{generation}-{sequence}",
                session_id,
                stored_episode,
                generation,
                sequence,
                name,
                event_class,
                f"2026-09-17T10:00:{sequence:02d}Z",
                sequence * 100,
                "whatsapp",
                "WhatsApp",
                f"mine-request-{generation}-{sequence}",
                f"mine-evidence-{generation}-{sequence}",
                json.dumps(payload or {}),
                MINE_SCHEMA_VERSION,
            ),
        )

    def cosine(
        self,
        sequence: int,
        name: str,
        event_class: str,
        *,
        session_id: int = 1,
        generation: int = 1,
        episode: str = "cosine-1",
        payload: dict | None = None,
    ) -> None:
        self.connection.execute(
            "INSERT INTO cosine_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"cosine-{session_id}-{generation}-{sequence}",
                session_id,
                episode,
                generation,
                sequence,
                name,
                event_class,
                f"2026-09-17T11:00:{sequence:02d}Z",
                sequence * 100,
                "netflix",
                "Example",
                f"cosine-request-{generation}-{sequence}",
                f"cosine-evidence-{generation}-{sequence}",
                json.dumps(payload or {}),
                COSINE_SCHEMA_VERSION,
            ),
        )

    def cosecant(
        self,
        sequence: int,
        kind: str,
        *,
        session_id: int = 1,
        break_id: str = "break-1",
        from_state: str = "BREAK_ACTIVE",
        to_state: str = "BREAK_ACTIVE",
        evidence_token: str = "",
    ) -> None:
        payload = {
            "sequence": sequence,
            "kind": kind,
            "break_id": break_id,
            "study_block_id": "study-1",
            "from_state": from_state,
            "to_state": to_state,
            "effective_monotonic_ns": sequence * 100,
            "observed_monotonic_ns": sequence * 100,
            "occurred_wall_time_utc": f"2026-09-17T12:00:{sequence:02d}Z",
            "message": kind,
            "evidence_token": evidence_token,
            "schema_version": COSECANT_SCHEMA_VERSION,
        }
        self.connection.execute(
            "INSERT INTO cosecant_events(session_id,break_id,sequence,kind,"
            "occurred_monotonic_ns,payload_json) VALUES(?,?,?,?,?,?)",
            (session_id, break_id, sequence, kind, sequence * 100, json.dumps(payload)),
        )


class InMemoryPieFixture(MetricHubFixture):
    """Pure in-memory source for the new episode-distribution contract."""

    def __init__(self) -> None:
        self.path = Path(":memory:")
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        _create_schema(self.connection)

    def project(self):
        self.connection.commit()
        session_ids = {
            int(row[0]) for row in self.connection.execute("SELECT id FROM sessions")
        }

        def rows(query: str) -> tuple[sqlite3.Row, ...]:
            return tuple(self.connection.execute(query).fetchall())

        return _project_behaviour_distribution(
            trigger_rows=rows(
                "SELECT id,session_id,candidate_uid,occurred_monotonic_ns,payload_json "
                "FROM triggers ORDER BY id"
            ),
            sine_rows=rows(
                "SELECT id,session_id,episode_uid,candidate_uid,kind,popup_request_id,"
                "occurred_monotonic_ns,payload_json FROM sine_facts ORDER BY id"
            ),
            mine_rows=rows("SELECT * FROM mine_events ORDER BY session_id,generation,sequence"),
            cosine_rows=rows(
                "SELECT * FROM cosine_events "
                "ORDER BY session_id,cosine_session_id,generation,sequence"
            ),
            session_ids=session_ids,
            stamp=UTC,
        )

    def mine_lineage(
        self,
        *,
        session_id: int = 1,
        generation: int = 1,
        episode: str = "mine-episode",
        platform: str = "whatsapp",
        entered_platform: str | None = None,
        include_display: bool = True,
        duplicate_display: bool = False,
    ) -> None:
        entered_platform = platform if entered_platform is None else entered_platform
        request = f"mine-request-{session_id}-{generation}"
        evidence = f"mine-evidence-{session_id}-{generation}"
        specs = [
            (1, "", "MINE_CANDIDATE_STARTED", "OBSERVED", platform, evidence, "", {}),
            (2, "", "MESSAGING_PLATFORM_ENTERED", "OBSERVED", entered_platform, evidence, "", {}),
            (3, "", "MINE_INITIAL_GATE_ELIGIBLE", "DERIVED", "", "", request, {}),
            (4, "", "MINE1_REQUESTED", "DERIVED", "", "", request, {"request_id": request}),
        ]
        if include_display:
            specs.append(
                (5, episode, "MINE1_DISPLAYED", "PRESENTATION", "", "", request, {"request_id": request})
            )
            next_sequence = 6
            if duplicate_display:
                specs.append(
                    (6, episode, "MINE1_DISPLAYED", "PRESENTATION", "", "", request, {"request_id": request})
                )
                next_sequence = 7
            specs.append(
                (next_sequence, episode, "MINE_EPISODE_STARTED", "DERIVED", "", "", request, {"request_id": request})
            )
        for sequence, stored_episode, name, event_class, key, token, request_id, payload in specs:
            self.connection.execute(
                "INSERT INTO mine_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"mine-pie-{session_id}-{generation}-{sequence}",
                    session_id,
                    stored_episode,
                    generation,
                    sequence,
                    name,
                    event_class,
                    f"2026-09-17T10:00:{sequence:02d}Z",
                    sequence * 100,
                    key,
                    key.title() if key else "",
                    request_id,
                    token,
                    json.dumps(payload),
                    MINE_SCHEMA_VERSION,
                ),
            )

    def cosine_lineage(
        self,
        *,
        session_id: int = 1,
        generation: int = 1,
        episode: str = "cosine-episode",
        platform: str = "netflix",
        entered_platform: str | None = None,
        switched_platform: str | None = None,
        include_display: bool = True,
        final_callback: bool = False,
    ) -> None:
        entered_platform = platform if entered_platform is None else entered_platform
        request = f"cosine-request-{session_id}-{generation}"
        evidence = f"cosine-evidence-{session_id}-{generation}"
        specs = [
            (1, "COSINE_SESSION_STARTED", "OBSERVED", platform, evidence, "", {"evidence_source": "CERTIFIED_HOST"}),
            (2, "OTT_PLATFORM_ENTERED", "OBSERVED", entered_platform, evidence, "", {}),
        ]
        sequence = 3
        if switched_platform is not None:
            specs.append(
                (
                    sequence,
                    "HOPPER_TRANSITION",
                    "OBSERVED",
                    switched_platform,
                    "switched-evidence",
                    "",
                    {"from_platform": entered_platform, "to_platform": switched_platform},
                )
            )
            sequence += 1
        specs.extend(
            (
                (sequence, "INTENT_GATE_ELIGIBLE", "DERIVED", "", "", request, {}),
                (sequence + 1, "INTENT_GATE_REQUESTED", "DERIVED", "", "", request, {"request_id": request}),
            )
        )
        if include_display:
            specs.append(
                (sequence + 2, "INTENT_GATE_DISPLAYED", "PRESENTATION", "", "", request, {})
            )
            if final_callback:
                specs.append(
                    (sequence + 3, "FINAL_CALLBACK_DISPLAYED", "PRESENTATION", "", "", "callback", {})
                )
        for event_sequence, name, event_class, key, token, request_id, payload in specs:
            self.connection.execute(
                "INSERT INTO cosine_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    f"cosine-pie-{session_id}-{generation}-{event_sequence}",
                    session_id,
                    episode,
                    generation,
                    event_sequence,
                    name,
                    event_class,
                    f"2026-09-17T11:00:{event_sequence:02d}Z",
                    event_sequence * 100,
                    key,
                    "Example",
                    request_id,
                    token,
                    json.dumps(payload),
                    COSINE_SCHEMA_VERSION,
                ),
            )


class BehaviourDistributionTests(unittest.TestCase):
    def test_empty_complete_sources_are_no_data_not_unavailable(self) -> None:
        fixture = InMemoryPieFixture()
        fixture.sessions(1)
        projection = fixture.project()
        fixture.close()
        self.assertEqual(projection.status, NO_DATA)
        self.assertEqual(
            (projection.social_count, projection.ott_count, projection.messaging_count),
            (0, 0, 0),
        )
        self.assertEqual(projection.eligible_total, 0)
        self.assertIsNone(projection.social_percent)

    def test_three_organs_count_first_displays_and_conserve_percentages(self) -> None:
        fixture = InMemoryPieFixture()
        fixture.sessions(1)
        fixture.trigger("candidate-1")
        fixture.sine("sine-1", "candidate-1", 1, "sine-request")
        fixture.mine_lineage()
        fixture.cosine_lineage(final_callback=True)
        projection = fixture.project()
        fixture.close()
        self.assertEqual(projection.status, AVAILABLE)
        self.assertEqual(
            (projection.social_count, projection.ott_count, projection.messaging_count),
            (1, 1, 1),
        )
        self.assertEqual(projection.eligible_total, 3)
        self.assertAlmostEqual(
            projection.social_percent
            + projection.ott_percent
            + projection.messaging_percent,
            100.0,
        )

    def test_sine_stage_retries_deduplicate_and_unshown_trigger_is_excluded(self) -> None:
        fixture = InMemoryPieFixture()
        fixture.sessions(1)
        fixture.trigger("shown")
        fixture.trigger("unshown", when=91)
        fixture.sine("sine-1", "shown", 1, "first", when=100)
        fixture.sine("sine-1", "shown", 1, "retry", when=101)
        fixture.sine("sine-1", "shown", 2, "stage-2", when=200)
        fixture.sine("sine-1", "shown", 3, "stage-3", when=300)
        projection = fixture.project()
        fixture.close()
        self.assertEqual(projection.social_count, 1)
        self.assertEqual(projection.eligible_total, 1)
        self.assertEqual(
            {item.reason_code: item.count for item in projection.exclusions},
            {"SINE_NOT_DISPLAYED": 1},
        )

    def test_contextual_sine_policy_accepts_off_task_and_rejects_aligned_or_activity(self) -> None:
        fixture = InMemoryPieFixture()
        fixture.sessions(1)
        fixture.trigger(
            "off-task",
            source="study_off_task",
            reason="study_off_task_dwell",
            source_rule_id="RI-STUDY-OFF-TASK-READY-001",
            study_context_token="study-context",
        )
        fixture.sine("sine-off-task", "off-task", 1, "shown-1")
        fixture.trigger(
            "aligned",
            source="study_aligned",
            reason="study_aligned",
            source_rule_id="RI-STUDY-ALIGNED-001",
            study_context_token="study-context",
            when=91,
        )
        fixture.sine("sine-aligned", "aligned", 1, "shown-2", when=110)
        fixture.trigger("activity", surface="activity", when=92)
        fixture.sine("sine-activity", "activity", 1, "shown-3", when=120)
        projection = fixture.project()
        fixture.close()
        self.assertEqual(projection.social_count, 1)
        self.assertEqual(projection.excluded_identity_count, 2)
        reasons = {item.reason_code for item in projection.exclusions}
        self.assertEqual(
            reasons,
            {"SINE_CONTEXT_UNSUPPORTED", "SINE_CATEGORY_UNSUPPORTED"},
        )

    def test_mine_uses_same_generation_platform_and_rejects_contradiction(self) -> None:
        fixture = InMemoryPieFixture()
        fixture.sessions(1)
        fixture.mine_lineage(generation=1, episode="mine-good")
        fixture.mine_lineage(
            generation=2,
            episode="mine-bad",
            platform="whatsapp",
            entered_platform="discord",
        )
        projection = fixture.project()
        fixture.close()
        self.assertEqual(projection.messaging_count, 1)
        self.assertEqual(
            {item.reason_code: item.count for item in projection.exclusions},
            {"MINE_PLATFORM_AMBIGUOUS": 1},
        )

    def test_mine_duplicate_first_display_is_not_a_second_episode(self) -> None:
        fixture = InMemoryPieFixture()
        fixture.sessions(1)
        fixture.mine_lineage(duplicate_display=True)
        projection = fixture.project()
        fixture.close()
        self.assertEqual(projection.messaging_count, 0)
        self.assertEqual(projection.status, NO_DATA)
        self.assertEqual(projection.exclusions[0].reason_code, "MINE_LINEAGE_AMBIGUOUS")

    def test_cosine_platform_switch_before_display_selects_same_episode_ott(self) -> None:
        fixture = InMemoryPieFixture()
        fixture.sessions(1)
        fixture.cosine_lineage(switched_platform="prime_video", final_callback=True)
        projection = fixture.project()
        fixture.close()
        self.assertEqual(projection.ott_count, 1)
        self.assertEqual(projection.eligible_total, 1)

    def test_cosine_contradictory_platform_and_unshown_session_do_not_count(self) -> None:
        fixture = InMemoryPieFixture()
        fixture.sessions(1)
        fixture.cosine_lineage(
            generation=1,
            episode="cosine-bad",
            platform="netflix",
            entered_platform="prime_video",
        )
        fixture.cosine_lineage(
            generation=2,
            episode="cosine-unshown",
            include_display=False,
        )
        projection = fixture.project()
        fixture.close()
        self.assertEqual(projection.ott_count, 0)
        self.assertEqual(projection.excluded_identity_count, 1)
        self.assertEqual(projection.exclusions[0].reason_code, "COSINE_PLATFORM_AMBIGUOUS")

    def test_two_episodes_and_two_organs_in_one_parent_session_remain_distinct(self) -> None:
        fixture = InMemoryPieFixture()
        fixture.sessions(1)
        for index in (1, 2):
            candidate = f"candidate-{index}"
            fixture.trigger(candidate, when=80 + index)
            fixture.sine(f"sine-{index}", candidate, 1, f"request-{index}", when=100 + index)
        fixture.mine_lineage(generation=1, episode="mine-1")
        fixture.mine_lineage(generation=2, episode="mine-2")
        fixture.cosine_lineage(generation=1, episode="cosine-1")
        projection = fixture.project()
        fixture.close()
        self.assertEqual(
            (projection.social_count, projection.ott_count, projection.messaging_count),
            (2, 1, 2),
        )
        self.assertEqual(projection.eligible_total, 5)

    def test_orphan_parent_makes_overall_pie_evidence_untrustworthy(self) -> None:
        fixture = InMemoryPieFixture()
        fixture.sessions(1)
        fixture.mine_lineage(session_id=99)
        with self.assertRaises(RuntimeError):
            fixture.project()
        fixture.close()


class MetricHubReadModelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def fixture(self) -> MetricHubFixture:
        return MetricHubFixture(self.root)

    def test_session_count_uses_rows_including_gaps_and_empty_ledgers_are_zero(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1, 2, 4)
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)
        self.assertEqual(projection.sessions.value, 3)
        self.assertEqual([row.session_id for row in projection.session_rows], [1, 2, 4])
        self.assertNotIn(3, {row.session_id for row in projection.session_rows})
        self.assertTrue(all(row.combined_triggers.value == 0 for row in projection.session_rows))
        self.assertTrue(all(row.combined_returned.value == 0 for row in projection.session_rows))
        self.assertEqual(projection.total_triggers.value, 0)
        self.assertEqual(projection.total_returned.value, 0)

    def test_missing_database_is_unavailable_and_is_not_created(self) -> None:
        missing = self.root / "missing.db"
        projection = read_lifetime_metric_hub(missing)
        self.assertEqual(projection.sessions.status, UNAVAILABLE)
        self.assertEqual(projection.behaviour_distribution.status, UNAVAILABLE)
        self.assertFalse(missing.exists())

    def test_missing_required_pie_ledger_fails_only_the_pie_closed(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.connection.execute("DROP TABLE triggers")
        fixture.close()

        projection = read_lifetime_metric_hub(fixture.path)

        self.assertEqual(projection.sessions.status, AVAILABLE)
        self.assertEqual(projection.total_triggers.status, AVAILABLE)
        self.assertEqual(projection.behaviour_distribution.status, UNAVAILABLE)
        self.assertIn(
            "Required pie source unavailable",
            projection.behaviour_distribution.status_message,
        )

    def test_reader_open_error_is_unavailable_without_replacing_the_file(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.close()
        before = hashlib.sha256(fixture.path.read_bytes()).hexdigest()

        with patch(
            "METRIC_HUB.read_model.sqlite3.connect",
            side_effect=sqlite3.OperationalError("test reader denied"),
        ):
            projection = read_lifetime_metric_hub(fixture.path)

        self.assertEqual(projection.behaviour_distribution.status, UNAVAILABLE)
        self.assertIn("test reader denied", projection.status_message)
        self.assertTrue(fixture.path.is_file())
        self.assertEqual(before, hashlib.sha256(fixture.path.read_bytes()).hexdigest())

    def test_trigger_ledger_participates_in_snapshot_identity(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.connection.commit()
        first = read_lifetime_metric_hub(fixture.path)

        fixture.trigger("accepted-but-not-displayed")
        fixture.connection.commit()
        second = read_lifetime_metric_hub(fixture.path)
        fixture.close()

        self.assertNotEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(second.behaviour_distribution.status, NO_DATA)
        self.assertEqual(second.behaviour_distribution.excluded_identity_count, 1)
        self.assertEqual(
            second.behaviour_distribution.exclusions[0].reason_code,
            "SINE_NOT_DISPLAYED",
        )

    def test_sine_rule_e_dedups_relapse_receipt_and_counts_new_episode(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.sine("episode-x", "candidate-x", 1, "x-1", when=100)
        fixture.sine("episode-x", "candidate-x", 2, "x-2", when=200)
        fixture.sine("episode-x", "candidate-x", 3, "x-3", when=300)
        fixture.sine("episode-x", "candidate-x", 3, "x-3", when=300)
        fixture.sine("episode-x", "candidate-x", 3, "x-3-relapse", when=400)
        fixture.sine("episode-y", "candidate-y", 1, "y-1", when=500)
        fixture.sine("episode-y", "candidate-y", 3, "y-3", when=600)
        fixture.sine(
            "episode-x",
            "candidate-x",
            0,
            "gate",
            kind="SINE_POST_BREAK_RETURN_GATE_DISPLAYED",
            when=700,
        )
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)
        self.assertEqual(projection.sine.triggers.value, 5)
        self.assertEqual(projection.sine.triggers.source_count, 7)

    def test_sine_scoped_chapter6_return_maps_to_genuine_episode(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.sine("sine-1", "candidate-1", 1, "popup-1", wall=UTC)
        episode = _MirlEpisode("mirl-1", "candidate-1")
        episode.close_successfully()
        fixture.mirl(episode)
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)
        self.assertEqual(projection.sine.returned.status, AVAILABLE)
        self.assertEqual(projection.sine.returned.value, 1)
        self.assertEqual(projection.session_rows[0].sine.returned.value, 1)

    def test_three_sine_stages_without_verified_return_reports_three_and_zero(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.sine("sine-1", "candidate-1", 1, "popup-1", when=100)
        fixture.sine("sine-1", "candidate-1", 2, "popup-2", when=200)
        fixture.sine("sine-1", "candidate-1", 3, "popup-3", when=300)
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)
        self.assertEqual(projection.sine.triggers.value, 3)
        self.assertEqual(projection.sine.returned.value, 0)

    def test_broken_scoped_chapter6_chain_is_unavailable_not_raw_count(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.sine("sine-1", "candidate-1", 1, "popup-1", wall=UTC)
        episode = _MirlEpisode("mirl-1", "candidate-1")
        episode.close_successfully()
        episode.events[-1] = replace(
            episode.events[-1], supporting_event_ids=("missing-proof",)
        )
        fixture.mirl(episode)
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)
        self.assertEqual(projection.sine.returned.status, UNAVAILABLE)
        self.assertEqual(projection.total_returned.status, UNAVAILABLE)
        self.assertEqual(projection.session_rows[0].sine.returned.status, UNAVAILABLE)

    def test_ambiguous_sine_episode_identity_fails_closed(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.sine("episode-a", "candidate-1", 1, "popup-a")
        fixture.sine("episode-b", "candidate-1", 1, "popup-b", when=200)
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)
        self.assertEqual(projection.sine.triggers.status, UNAVAILABLE)
        self.assertEqual(projection.total_triggers.status, UNAVAILABLE)
        self.assertEqual(projection.sessions.value, 1)
        self.assertEqual(projection.session_series_status, UNAVAILABLE)

    def test_mine_and_cosine_stage_reappearances_count_once_and_returns_validate(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.mine(1, "MINE_CANDIDATE_STARTED", "OBSERVED")
        fixture.mine(2, "MINE_EPISODE_STARTED", "DERIVED")
        fixture.mine(3, "MINE1_DISPLAYED", "PRESENTATION")
        fixture.mine(4, "MINE2A_DISPLAYED", "PRESENTATION")
        fixture.mine(5, "MINE2A_DISPLAYED", "PRESENTATION")
        outcome = "RETURNED_AFTER_CALLBACK"
        fixture.mine(6, "RETURN_CONFIRMED", "DERIVED", payload={"closure_outcome": outcome})
        fixture.mine(
            7,
            "MINE_SESSION_CLOSED",
            "DERIVED",
            payload={"closure_reason": "VERIFIED_RETURN", "closure_outcome": outcome},
        )

        fixture.cosine(1, "COSINE_SESSION_STARTED", "DERIVED")
        fixture.cosine(2, "INTENT_GATE_DISPLAYED", "PRESENTATION")
        fixture.cosine(3, "DURATION_REQUESTED", "DERIVED")
        fixture.cosine(4, "BREAK_ACK_DISPLAYED", "PRESENTATION")
        fixture.cosine(5, "FINAL_CALLBACK_DISPLAYED", "PRESENTATION")
        fixture.cosine(6, "FINAL_CALLBACK_DISPLAYED", "PRESENTATION")
        cosine_outcome = "RETURNED_AFTER_CALLBACK"
        fixture.cosine(
            7, "RETURN_CONFIRMED", "DERIVED", payload={"closure_outcome": cosine_outcome}
        )
        fixture.cosine(
            8,
            "COSINE_SESSION_CLOSED",
            "DERIVED",
            payload={
                "closure_reason": "RETURN_CONFIRMED",
                "closure_outcome": cosine_outcome,
            },
        )
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)
        self.assertEqual((projection.mine.triggers.value, projection.mine.returned.value), (2, 1))
        self.assertEqual((projection.cosine.triggers.value, projection.cosine.returned.value), (3, 1))
        self.assertEqual(projection.total_triggers.value, 5)
        self.assertEqual(projection.total_returned.value, 2)
        self.assertIn("PARTIAL", projection.cosine.trigger_disclosure)

    def test_cosecant_repeated_final_is_one_stage_and_new_break_counts_again(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.cosecant(1, "BREAK_STARTED", to_state="BREAK_ACTIVE")
        fixture.cosecant(2, "BREAK_COMPLETE", to_state="BREAK_COMPLETE")
        fixture.cosecant(
            3,
            "BREAK_ALREADY_OVER",
            from_state="BREAK_COMPLETE",
            to_state="BREAK_ALREADY_OVER",
        )
        fixture.cosecant(
            4, "FINAL_LOCKED", from_state="BREAK_ALREADY_OVER", to_state="FINAL_LOCK"
        )
        fixture.cosecant(5, "FINAL_LOCKED", from_state="FINAL_LOCK", to_state="FINAL_LOCK")
        fixture.cosecant(
            6,
            "RETURN_CONFIRMED",
            from_state="RETURN_CONFIRMING",
            to_state="CONFIRMED",
            evidence_token="exact-resource-proof",
        )
        fixture.cosecant(1, "BREAK_STARTED", break_id="break-2", to_state="BREAK_ACTIVE")
        fixture.cosecant(2, "BREAK_COMPLETE", break_id="break-2", to_state="BREAK_COMPLETE")
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)
        self.assertEqual(projection.cosecant.triggers.value, 4)
        self.assertEqual(projection.cosecant.returned.value, 1)
        self.assertEqual(projection.total_triggers.value, 4)
        self.assertEqual(projection.total_returned.value, 1)
        self.assertIn("not independently witnessed", projection.cosecant.trigger_disclosure)

    def test_session_close_and_experiment_rows_do_not_change_session_population(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1, 2, 4)
        fixture.connection.execute(
            "UPDATE sessions SET closed_at_utc=? WHERE id=2", (UTC,)
        )
        fixture.connection.execute(
            "INSERT INTO science_lab_experiments(session_id) VALUES(?)", (2,)
        )
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)
        self.assertEqual(projection.sessions.value, 3)
        self.assertTrue(next(row for row in projection.session_rows if row.session_id == 2).is_closed)

    def test_one_unavailable_organ_only_blocks_associated_headlines(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.mine(1, "MINE_CANDIDATE_STARTED", "OBSERVED")
        fixture.connection.execute("UPDATE mine_events SET session_id=99")
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)
        self.assertEqual(projection.sessions.value, 1)
        self.assertEqual(projection.sine.triggers.value, 0)
        self.assertEqual(projection.cosine.triggers.value, 0)
        self.assertEqual(projection.cosecant.triggers.value, 0)
        self.assertEqual(projection.mine.triggers.status, UNAVAILABLE)
        self.assertEqual(projection.total_triggers.status, UNAVAILABLE)
        self.assertEqual(projection.total_returned.status, UNAVAILABLE)
        self.assertEqual(projection.session_rows[0].mine.triggers.status, UNAVAILABLE)
        self.assertEqual(projection.session_rows[0].combined_triggers.status, UNAVAILABLE)

    def test_fixture_database_bytes_are_unchanged_by_projection(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1)
        fixture.close()
        before = hashlib.sha256(fixture.path.read_bytes()).hexdigest()
        projection = read_lifetime_metric_hub(fixture.path)
        after = hashlib.sha256(fixture.path.read_bytes()).hexdigest()
        self.assertEqual(projection.status, AVAILABLE)
        self.assertEqual(before, after)

    def test_read_only_path_resolution_does_not_create_app_data_directory(self) -> None:
        from PERSISTENCE.database import database_path

        isolated = self.root / "never-created" / "Roaming"
        with patch.dict(os.environ, {"APPDATA": str(isolated)}):
            expected = isolated / "MYELIN" / "myelin2.0_session.db"
            self.assertEqual(database_path(create_parent=False), expected.resolve())
            self.assertFalse(expected.parent.exists())

    def test_shared_analytics_bundle_preserves_legacy_and_adds_lifetime_projection(self) -> None:
        import PERSISTENCE.storage as storage

        legacy = object()
        lifetime = object()
        mirl = SimpleNamespace(
            metric_hub=legacy,
            science_lab=object(),
            live_mirl=object(),
        )
        with (
            patch("METRIC_HUB.read_model.read_lifetime_metric_hub", return_value=lifetime),
            patch.object(storage, "read_mirl_snapshot", return_value=mirl),
            patch.object(storage, "read_cosine_events", return_value=()),
            patch.object(storage, "read_mine_events", return_value=()),
            patch.object(
                storage,
                "bootstrap_production_schema",
                side_effect=AssertionError("dashboard read attempted schema bootstrap"),
            ),
        ):
            snapshot = storage.read_control_station_analytics("local")

        self.assertIs(snapshot.metric_hub, legacy)
        self.assertIs(snapshot.lifetime_metric_hub, lifetime)

    def test_session_rows_use_started_utc_then_session_id_chronology(self) -> None:
        fixture = self.fixture()
        fixture.session(4, started_at_utc="2026-09-17T09:30:00Z")
        fixture.session(2, started_at_utc="2026-09-17T09:20:00Z")
        fixture.session(1, started_at_utc="2026-09-17T09:10:00Z")
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)
        self.assertEqual([row.session_id for row in projection.session_rows], [1, 2, 4])
        self.assertEqual([row.ordinal for row in projection.session_rows], [1, 2, 3])
        self.assertEqual(projection.session_rows[0].order_key[1], 1)

    def test_committed_insert_and_close_refresh_one_unified_projection(self) -> None:
        fixture = self.fixture()
        fixture.session(1, started_at_utc="2026-09-17T09:00:00Z")
        fixture.connection.commit()
        first = read_lifetime_metric_hub(fixture.path)
        self.assertEqual(len(first.session_rows), 1)
        self.assertFalse(first.session_rows[0].is_closed)

        fixture.session(2, started_at_utc="2026-09-17T09:30:00Z")
        fixture.connection.commit()
        second = read_lifetime_metric_hub(fixture.path)
        self.assertEqual(len(second.session_rows), 2)
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)

        fixture.sine("session-2", "candidate-2", 1, "request-2", session_id=2)
        fixture.connection.execute(
            "UPDATE sessions SET closed_at_utc=? WHERE id=2", (UTC,)
        )
        fixture.connection.commit()
        third = read_lifetime_metric_hub(fixture.path)
        fixture.close()
        self.assertEqual(len(third.session_rows), 2)
        row = next(item for item in third.session_rows if item.session_id == 2)
        self.assertTrue(row.is_closed)
        self.assertEqual(row.sine.triggers.value, 1)
        self.assertEqual(third.sine.triggers.value, 1)
        self.assertNotEqual(second.snapshot_id, third.snapshot_id)

    def test_cross_organ_session_rows_reconcile_all_eight_contributions(self) -> None:
        fixture = self.fixture()
        fixture.sessions(1, 2)
        fixture.sine("sine-1", "candidate-1", 1, "sine-request", session_id=1)
        sine_episode = _MirlEpisode("mirl-1", "candidate-1", session_id=1)
        sine_episode.close_successfully()
        fixture.mirl(sine_episode)

        fixture.mine(1, "MINE_CANDIDATE_STARTED", "OBSERVED", session_id=2)
        fixture.mine(2, "MINE_EPISODE_STARTED", "DERIVED", session_id=2)
        fixture.mine(3, "MINE1_DISPLAYED", "PRESENTATION", session_id=2)
        fixture.mine(4, "MINE2A_DISPLAYED", "PRESENTATION", session_id=2)
        mine_outcome = "RETURNED_AFTER_CALLBACK"
        fixture.mine(
            5,
            "RETURN_CONFIRMED",
            "DERIVED",
            session_id=2,
            payload={"closure_outcome": mine_outcome},
        )
        fixture.mine(
            6,
            "MINE_SESSION_CLOSED",
            "DERIVED",
            session_id=2,
            payload={
                "closure_reason": "VERIFIED_RETURN",
                "closure_outcome": mine_outcome,
            },
        )

        fixture.cosine(1, "COSINE_SESSION_STARTED", "DERIVED", session_id=2)
        fixture.cosine(2, "INTENT_GATE_DISPLAYED", "PRESENTATION", session_id=2)
        fixture.cosine(3, "BREAK_ACK_DISPLAYED", "PRESENTATION", session_id=2)
        fixture.cosine(4, "FINAL_CALLBACK_DISPLAYED", "PRESENTATION", session_id=2)
        cosine_outcome = "RETURNED_AFTER_CALLBACK"
        fixture.cosine(
            5,
            "RETURN_CONFIRMED",
            "DERIVED",
            session_id=2,
            payload={"closure_outcome": cosine_outcome},
        )
        fixture.cosine(
            6,
            "COSINE_SESSION_CLOSED",
            "DERIVED",
            session_id=2,
            payload={
                "closure_reason": "RETURN_CONFIRMED",
                "closure_outcome": cosine_outcome,
            },
        )

        fixture.cosecant(
            1, "BREAK_STARTED", session_id=2, break_id="break-2", to_state="BREAK_ACTIVE"
        )
        fixture.cosecant(
            2, "BREAK_COMPLETE", session_id=2, break_id="break-2", to_state="BREAK_COMPLETE"
        )
        fixture.cosecant(
            3,
            "RETURN_CONFIRMED",
            session_id=2,
            break_id="break-2",
            from_state="RETURN_CONFIRMING",
            to_state="CONFIRMED",
            evidence_token="resource-2",
        )
        fixture.close()
        projection = read_lifetime_metric_hub(fixture.path)

        row1, row2 = projection.session_rows
        self.assertEqual(row1.session_id, 1)
        self.assertEqual((row1.combined_triggers.value, row1.combined_returned.value), (1, 1))
        self.assertEqual(row2.session_id, 2)
        self.assertEqual((row2.combined_triggers.value, row2.combined_returned.value), (6, 3))
        for name in ("sine", "cosine", "mine", "cosecant"):
            organ = getattr(projection, name)
            self.assertEqual(
                sum(getattr(row, name).triggers.value for row in projection.session_rows),
                organ.triggers.value,
            )
            self.assertEqual(
                sum(getattr(row, name).returned.value for row in projection.session_rows),
                organ.returned.value,
            )
        self.assertEqual(
            sum(row.combined_triggers.value for row in projection.session_rows),
            projection.total_triggers.value,
        )
        self.assertEqual(
            sum(row.combined_returned.value for row in projection.session_rows),
            projection.total_returned.value,
        )
        self.assertEqual(projection.session_series_status, AVAILABLE)

    def test_host_refresh_contract_is_post_commit_coalesced_and_generation_safe(self) -> None:
        root = Path(__file__).resolve().parents[1]
        database = (root / "PERSISTENCE" / "database.py").read_text(encoding="utf-8")
        monitor = (root / "CORE_ENGINE" / "monitor.py").read_text(encoding="utf-8")
        controller = (root / "CONTROL_STATION" / "controller.py").read_text(encoding="utf-8")
        analytics = (root / "CONTROL_STATION" / "analytics.py").read_text(encoding="utf-8")

        lane = database[database.index("def _run(self)") : database.index("__all__")]
        self.assertLess(lane.index("connection.commit()"), lane.index("record.done.set()"))
        cleanup = monitor[monitor.index("def _cleanup(self)") : monitor.index("def _settle_pending_trigger_for_shutdown")]
        self.assertLess(cleanup.index("close_monitor_session"), cleanup.index("return True"))
        run_block = monitor[monitor.index("def run(self)") : monitor.index("def _start_session")]
        self.assertLess(run_block.index("cleanup_ok = self._cleanup()"), run_block.index("cleanup_complete_event.set()"))
        finish = controller[controller.index("def _finish_worker_exit") : controller.index("def shutdown")]
        self.assertIn("self._set_status(EngineStatus.STOPPED)", finish)
        engine_hook = analytics[analytics.index("def engine_status_changed") : analytics.index("def telemetry_received")]
        self.assertIn("self._refresh.request_refresh()", engine_hook)
        open_hook = analytics[analytics.index("def page_opened") : analytics.index("def request_today_session_health_refresh")]
        self.assertIn("self._refresh.request_refresh()", open_hook)
        delivery = analytics[analytics.index("def _take_result") : analytics.index("def _clear_layout")]
        self.assertIn("if generation == self._generation", delivery)


if __name__ == "__main__":
    unittest.main()
