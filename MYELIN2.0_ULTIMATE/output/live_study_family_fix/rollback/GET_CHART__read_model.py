"""Immutable, read-only chart projections for the MYELIN Neon Poster.

The poster owns no scientific interpretation. This module adapts existing
certified readers into four explicit chart contracts:

* SINE uses genuine numbered display episodes and the approved scoped Chapter 6
  return-chain validator. Escalation reach and verified returns stay separate.
* MINE uses ``MineReadAuthority`` choices and documented closure outcomes.
* COSINE uses ``CosineReadAuthority`` event identities and UTC timestamps only;
  it deliberately exposes no continuous-viewing duration.
* COSECANT uses the Metric Hub's existing fact validator, retaining only
  recorded deadlines/milestones and exact-resource return confirmation.

The canonical SQLite database is opened with ``mode=ro`` and ``query_only``.
No schema bootstrap, migration, write, inferred interval, or invented value is
performed here.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

from COSINE.read_model import project_cosine_events
from METRIC_HUB import read_model as certified_metric_reader
from METRIC_HUB.read_model import LifetimeMetricHubProjection, read_lifetime_metric_hub
from MINE.read_model import project_mine_events
from MIRL.mirl import MirlEvent, MirlEventName
from PERSISTENCE.database import SQLITE_BUSY_TIMEOUT_MS, database_path


AVAILABLE: Final = "AVAILABLE"
NO_DATA: Final = "NO_DATA"
UNAVAILABLE: Final = "UNAVAILABLE"
POSTER_ORGANS: Final = ("SINE", "COSINE", "MINE", "COSECANT")
_STAGES: Final = (1, 2, 3)
_MINE_CHOICES: Final = frozenset({"I_WILL_COME_BACK", "ITS_IMPORTANT"})
_COSECANT_MILESTONES: Final = frozenset(
    {
        "BREAK_STARTED",
        "BREAK_COMPLETE",
        "BREAK_ALREADY_OVER",
        "FINAL_LOCKED",
        "RETURN_INTENT_RECORDED",
        "RETURN_CONFIRMATION_STARTED",
        "RETURN_CONFIRMATION_RESTARTED",
        "RETURN_CONFIRMATION_LOST",
        "RETURN_CONFIRMED",
    }
)


def _valid_status(value: str) -> bool:
    return value in {AVAILABLE, NO_DATA, UNAVAILABLE}


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@dataclass(frozen=True, slots=True)
class SineEpisodeProjection:
    session_id: int
    episode_id: str
    candidate_uid: str
    first_displayed_at_utc: str
    stages_reached: tuple[int, ...]
    verified_return: bool

    def __post_init__(self) -> None:
        if type(self.session_id) is not int or self.session_id <= 0:
            raise ValueError("SINE episode requires a positive parent session")
        if not all(
            _nonempty(value)
            for value in (
                self.episode_id,
                self.candidate_uid,
                self.first_displayed_at_utc,
            )
        ):
            raise ValueError("SINE episode identity and timestamp are required")
        if self.stages_reached not in {(1,), (1, 2), (1, 2, 3)}:
            raise ValueError("SINE stages must form the approved escalation prefix")
        if type(self.verified_return) is not bool:
            raise TypeError("SINE verified-return truth must be boolean")


@dataclass(frozen=True, slots=True)
class SineFunnelStageProjection:
    stage: int
    episode_ids: tuple[str, ...]
    count: int | None
    denominator: int | None

    def __post_init__(self) -> None:
        if self.stage not in _STAGES:
            raise ValueError("SINE funnel stage must be 1, 2 or 3")
        if self.count is None or self.denominator is None:
            if self.count is not None or self.denominator is not None or self.episode_ids:
                raise ValueError("unavailable SINE stage cannot carry partial values")
            return
        if type(self.count) is not int or type(self.denominator) is not int:
            raise TypeError("SINE funnel counts must be integers")
        if self.count < 0 or self.denominator < self.count:
            raise ValueError("SINE funnel denominator must contain its numerator")
        if self.count != len(self.episode_ids) or len(set(self.episode_ids)) != self.count:
            raise ValueError("SINE funnel identity count does not reconcile")


@dataclass(frozen=True, slots=True)
class SineChartProjection:
    status: str
    episodes: tuple[SineEpisodeProjection, ...]
    funnel: tuple[SineFunnelStageProjection, ...]
    verified_return_episode_ids: tuple[str, ...]
    verified_return_count: int | None
    verified_return_denominator: int | None
    status_message: str

    def __post_init__(self) -> None:
        if not _valid_status(self.status) or not _nonempty(self.status_message):
            raise ValueError("SINE chart requires an explicit status and message")
        if tuple(stage.stage for stage in self.funnel) != _STAGES:
            raise ValueError("SINE chart requires exactly three ordered funnel stages")
        if self.status == UNAVAILABLE:
            if self.episodes or self.verified_return_episode_ids:
                raise ValueError("unavailable SINE chart cannot carry episodes")
            if self.verified_return_count is not None or self.verified_return_denominator is not None:
                raise ValueError("unavailable SINE return values must be absent")
            return
        if (self.status == AVAILABLE) is not bool(self.episodes):
            raise ValueError("SINE availability must match its episode population")
        identities = tuple(row.episode_id for row in self.episodes)
        if len(set(identities)) != len(identities):
            raise ValueError("SINE episode identities must be unique")
        verified = tuple(row.episode_id for row in self.episodes if row.verified_return)
        if verified != self.verified_return_episode_ids:
            raise ValueError("SINE verified-return identities do not reconcile")
        if self.verified_return_count != len(verified):
            raise ValueError("SINE verified-return count does not reconcile")
        if self.verified_return_denominator != len(self.episodes):
            raise ValueError("SINE return denominator must be the episode population")
        denominator = len(self.episodes)
        for stage in self.funnel:
            expected_ids = tuple(
                row.episode_id for row in self.episodes if stage.stage in row.stages_reached
            )
            if stage.episode_ids != expected_ids:
                raise ValueError("SINE funnel identities do not reconcile")
            if stage.denominator != denominator:
                raise ValueError("SINE funnel denominator does not reconcile")
            denominator = len(expected_ids)


@dataclass(frozen=True, slots=True)
class MineChoiceOutcomeProjection:
    session_id: int
    generation: int
    mine_episode_id: str
    display_episode_id: str
    choice: str
    chosen_at_utc: str
    closure_outcome: str | None
    closure_reason: str | None
    ended_at_utc: str | None
    return_verified: bool

    def __post_init__(self) -> None:
        if type(self.session_id) is not int or self.session_id <= 0:
            raise ValueError("MINE choice requires a positive parent session")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("MINE choice requires a positive generation")
        if self.choice not in _MINE_CHOICES:
            raise ValueError("MINE choice is not an approved MINE-1 choice")
        if not all(
            _nonempty(value)
            for value in (
                self.mine_episode_id,
                self.display_episode_id,
                self.chosen_at_utc,
            )
        ):
            raise ValueError("MINE choice identity and timestamp are required")
        if type(self.return_verified) is not bool:
            raise TypeError("MINE return verification must be boolean")


@dataclass(frozen=True, slots=True)
class MineOutcomeBucketProjection:
    choice: str
    outcome: str
    episode_ids: tuple[str, ...]
    count: int
    choice_denominator: int

    def __post_init__(self) -> None:
        if self.choice not in _MINE_CHOICES or not _nonempty(self.outcome):
            raise ValueError("MINE outcome bucket requires an approved choice/outcome")
        if self.count != len(self.episode_ids) or len(set(self.episode_ids)) != self.count:
            raise ValueError("MINE outcome identities do not reconcile")
        if self.count < 0 or self.choice_denominator < self.count:
            raise ValueError("MINE choice denominator must contain its outcome")


@dataclass(frozen=True, slots=True)
class MineChartProjection:
    status: str
    choices: tuple[MineChoiceOutcomeProjection, ...]
    outcome_buckets: tuple[MineOutcomeBucketProjection, ...]
    choice_denominator: int | None
    documented_outcome_count: int | None
    status_message: str

    def __post_init__(self) -> None:
        if not _valid_status(self.status) or not _nonempty(self.status_message):
            raise ValueError("MINE chart requires an explicit status and message")
        if self.status == UNAVAILABLE:
            if self.choices or self.outcome_buckets:
                raise ValueError("unavailable MINE chart cannot carry choices")
            if self.choice_denominator is not None or self.documented_outcome_count is not None:
                raise ValueError("unavailable MINE counts must be absent")
            return
        if (self.status == AVAILABLE) is not bool(self.choices):
            raise ValueError("MINE availability must match its choice population")
        identities = tuple(row.mine_episode_id for row in self.choices)
        if len(set(identities)) != len(identities):
            raise ValueError("MINE episode identities must be unique")
        if self.choice_denominator != len(self.choices):
            raise ValueError("MINE choice denominator does not reconcile")
        documented = sum(row.closure_outcome is not None for row in self.choices)
        if self.documented_outcome_count != documented:
            raise ValueError("MINE documented-outcome count does not reconcile")
        choice_counts = Counter(row.choice for row in self.choices)
        grouped: dict[tuple[str, str], list[str]] = {}
        for row in self.choices:
            if row.closure_outcome is not None:
                grouped.setdefault((row.choice, row.closure_outcome), []).append(
                    row.mine_episode_id
                )
        expected_buckets = tuple(
            (choice, outcome, tuple(episode_ids), len(episode_ids), choice_counts[choice])
            for (choice, outcome), episode_ids in sorted(grouped.items())
        )
        actual_buckets = tuple(
            (
                bucket.choice,
                bucket.outcome,
                bucket.episode_ids,
                bucket.count,
                bucket.choice_denominator,
            )
            for bucket in self.outcome_buckets
        )
        if actual_buckets != expected_buckets:
            raise ValueError("MINE outcome buckets or denominators do not reconcile")


@dataclass(frozen=True, slots=True)
class CosineRecordedEventProjection:
    event_id: str
    sequence: int
    event_name: str
    occurred_at_utc: str

    def __post_init__(self) -> None:
        if not all(
            _nonempty(value)
            for value in (self.event_id, self.event_name, self.occurred_at_utc)
        ):
            raise ValueError("COSINE events require identity, name and recorded UTC")
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("COSINE event sequence must be positive")


@dataclass(frozen=True, slots=True)
class CosineEpisodeTimelineProjection:
    cosine_session_id: str
    generation: int
    parent_session_id: int | None
    started_at_utc: str
    ended_at_utc: str | None
    events: tuple[CosineRecordedEventProjection, ...]

    def __post_init__(self) -> None:
        if not _nonempty(self.cosine_session_id) or not _nonempty(self.started_at_utc):
            raise ValueError("COSINE episode identity and start timestamp are required")
        if type(self.generation) is not int or self.generation <= 0:
            raise ValueError("COSINE generation must be positive")
        if self.parent_session_id is not None and (
            type(self.parent_session_id) is not int or self.parent_session_id <= 0
        ):
            raise ValueError("COSINE parent session must be positive when recorded")
        sequences = tuple(event.sequence for event in self.events)
        if sequences != tuple(range(1, len(sequences) + 1)):
            raise ValueError("COSINE events must retain their recorded episode sequence")


@dataclass(frozen=True, slots=True)
class CosineChartProjection:
    status: str
    episodes: tuple[CosineEpisodeTimelineProjection, ...]
    episode_denominator: int | None
    timestamp_count: int | None
    status_message: str

    def __post_init__(self) -> None:
        if not _valid_status(self.status) or not _nonempty(self.status_message):
            raise ValueError("COSINE chart requires an explicit status and message")
        if self.status == UNAVAILABLE:
            if self.episodes or self.episode_denominator is not None or self.timestamp_count is not None:
                raise ValueError("unavailable COSINE chart cannot carry values")
            return
        if (self.status == AVAILABLE) is not bool(self.episodes):
            raise ValueError("COSINE availability must match its episode population")
        identities = tuple(
            (episode.cosine_session_id, episode.generation) for episode in self.episodes
        )
        if len(set(identities)) != len(identities):
            raise ValueError("COSINE episode identities must be unique")
        if self.episode_denominator != len(self.episodes):
            raise ValueError("COSINE episode denominator does not reconcile")
        if self.timestamp_count != sum(len(episode.events) for episode in self.episodes):
            raise ValueError("COSINE timestamp count does not reconcile")


@dataclass(frozen=True, slots=True)
class CosecantMilestoneProjection:
    sequence: int
    kind: str
    effective_monotonic_ns: int
    observed_monotonic_ns: int
    occurred_at_utc: str
    evidence_token: str

    def __post_init__(self) -> None:
        if self.kind not in _COSECANT_MILESTONES or not _nonempty(self.occurred_at_utc):
            raise ValueError("COSECANT milestone kind/timestamp is not approved")
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("COSECANT milestone sequence must be positive")
        if any(
            type(value) is not int or value < 0
            for value in (self.effective_monotonic_ns, self.observed_monotonic_ns)
        ):
            raise ValueError("COSECANT milestone clocks must be recorded non-negative integers")


@dataclass(frozen=True, slots=True)
class CosecantBreakProjection:
    session_id: int
    break_id: str
    study_block_id: str
    milestones: tuple[CosecantMilestoneProjection, ...]
    return_confirmed: bool

    def __post_init__(self) -> None:
        if type(self.session_id) is not int or self.session_id <= 0:
            raise ValueError("COSECANT break requires a positive parent session")
        if not _nonempty(self.break_id) or not _nonempty(self.study_block_id):
            raise ValueError("COSECANT break and study identities are required")
        sequences = tuple(milestone.sequence for milestone in self.milestones)
        if sequences != tuple(sorted(sequences)) or len(set(sequences)) != len(sequences):
            raise ValueError("COSECANT milestones must retain unique recorded order")
        confirmed = any(item.kind == "RETURN_CONFIRMED" for item in self.milestones)
        if self.return_confirmed is not confirmed:
            raise ValueError("COSECANT return confirmation does not reconcile")


@dataclass(frozen=True, slots=True)
class CosecantChartProjection:
    status: str
    breaks: tuple[CosecantBreakProjection, ...]
    break_denominator: int | None
    confirmed_return_count: int | None
    status_message: str

    def __post_init__(self) -> None:
        if not _valid_status(self.status) or not _nonempty(self.status_message):
            raise ValueError("COSECANT chart requires an explicit status and message")
        if self.status == UNAVAILABLE:
            if self.breaks or self.break_denominator is not None or self.confirmed_return_count is not None:
                raise ValueError("unavailable COSECANT chart cannot carry values")
            return
        if (self.status == AVAILABLE) is not bool(self.breaks):
            raise ValueError("COSECANT availability must match its break population")
        identities = tuple((row.session_id, row.break_id) for row in self.breaks)
        if len(set(identities)) != len(identities):
            raise ValueError("COSECANT break identities must be unique")
        if self.break_denominator != len(self.breaks):
            raise ValueError("COSECANT break denominator does not reconcile")
        if self.confirmed_return_count != sum(row.return_confirmed for row in self.breaks):
            raise ValueError("COSECANT confirmed-return count does not reconcile")


@dataclass(frozen=True, slots=True)
class SecantChartProjection:
    status: str
    highest_stage_counts: tuple[int, int, int] | None
    founded_episodes: int | None
    return_attempts: int | None
    verified_events: int | None
    interrupted_recoveries: int | None
    recovered_episodes: int | None
    incomplete_episodes: int | None
    status_message: str

    def __post_init__(self) -> None:
        if not _valid_status(self.status):
            raise ValueError("SECANT poster status is invalid")
        values = (self.founded_episodes, self.return_attempts, self.verified_events,
                  self.interrupted_recoveries, self.recovered_episodes, self.incomplete_episodes)
        if self.status == UNAVAILABLE:
            if self.highest_stage_counts is not None or any(value is not None for value in values):
                raise ValueError("Unavailable SECANT cannot carry values")
            return
        if self.highest_stage_counts is None or any(type(v) is not int or v < 0 for v in self.highest_stage_counts + values):
            raise ValueError("SECANT counts must be non-negative integers")
        if sum(self.highest_stage_counts) != self.founded_episodes:
            raise ValueError("SECANT highest-stage counts must be exclusive")
        if self.status == NO_DATA and self.founded_episodes != 0:
            raise ValueError("SECANT no-data population must be zero")


def secant_chart_from_family(family) -> SecantChartProjection:
    if family is None or family.errors.get("secant"):
        return SecantChartProjection(UNAVAILABLE, None, None, None, None, None, None, None,
                                     "SECANT evidence unavailable")
    episodes = family.secant
    stages = tuple(sum(row["highest_stage"] == stage for row in episodes) for stage in (1, 2, 3))
    events = tuple(event for episode in episodes for event in episode["events"])
    count = lambda name: sum(event["event_name"] == name for event in events)
    return SecantChartProjection(AVAILABLE if episodes else NO_DATA, stages, len(episodes),
        count("SECANT_RETURN_STARTED"), count("SECANT_RETURN_VERIFIED"),
        count("SECANT_RECOVERY_INTERRUPTED"), sum(row["recovered"] for row in episodes),
        sum(not row["closed"] for row in episodes), "All recorded SECANT episodes")


@dataclass(frozen=True, slots=True)
class PosterChartData:
    lifetime_summary: LifetimeMetricHubProjection
    sine: SineChartProjection
    mine: MineChartProjection
    cosine: CosineChartProjection
    cosecant: CosecantChartProjection
    generated_at_utc: str
    secant: SecantChartProjection | None = None
    study_blocks_started: int | None = None

    @property
    def snapshot_id(self) -> str:
        return self.lifetime_summary.snapshot_id

    @property
    def read_only(self) -> bool:
        return self.lifetime_summary.read_only

    @property
    def organs(self):
        return self.lifetime_summary.organs

    @property
    def session_rows(self):
        return self.lifetime_summary.session_rows


@dataclass(frozen=True, slots=True)
class _EvidenceSnapshot:
    session_ids: frozenset[int]
    sine_rows: tuple[object, ...] | None
    mirl_events: tuple[MirlEvent, ...] | None
    mine_events: tuple[object, ...] | None
    cosine_events: tuple[object, ...] | None
    cosecant_rows: tuple[object, ...] | None
    errors: tuple[tuple[str, str], ...]

    def error_for(self, source: str) -> str | None:
        return dict(self.errors).get(source)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _bounded_error(error: BaseException) -> str:
    return f"{type(error).__name__}: {' '.join(str(error).split())}"[:240]


def _unavailable_funnel() -> tuple[SineFunnelStageProjection, ...]:
    return tuple(SineFunnelStageProjection(stage, (), None, None) for stage in _STAGES)


def _unavailable_sine(reason: str) -> SineChartProjection:
    return SineChartProjection(UNAVAILABLE, (), _unavailable_funnel(), (), None, None, reason)


def _unavailable_mine(reason: str) -> MineChartProjection:
    return MineChartProjection(UNAVAILABLE, (), (), None, None, reason)


def _unavailable_cosine(reason: str) -> CosineChartProjection:
    return CosineChartProjection(UNAVAILABLE, (), None, None, reason)


def _unavailable_cosecant(reason: str) -> CosecantChartProjection:
    return CosecantChartProjection(UNAVAILABLE, (), None, None, reason)


def _read_evidence(database_file: str | Path | None) -> _EvidenceSnapshot:
    path = Path(database_file) if database_file is not None else database_path(create_parent=False)
    sources = ("sessions", "sine", "mirl", "mine", "cosine", "cosecant")
    if not path.is_file():
        reason = "Poster database is missing."
        return _EvidenceSnapshot(
            frozenset(), None, None, None, None, None,
            tuple((name, reason) for name in sources),
        )

    errors: dict[str, str] = {}
    try:
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=SQLITE_BUSY_TIMEOUT_MS / 1000,
            check_same_thread=False,
        )
    except (OSError, sqlite3.Error) as error:
        reason = f"Poster read failed: {_bounded_error(error)}"
        return _EvidenceSnapshot(
            frozenset(), None, None, None, None, None,
            tuple((name, reason) for name in sources),
        )

    connection.row_factory = sqlite3.Row

    def load(source: str, columns: tuple[str, ...], query: str):
        try:
            return certified_metric_reader._required_table(connection, source, columns, query)
        except Exception as error:
            errors[source] = _bounded_error(error)
            return None

    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
        connection.execute("BEGIN")
        sessions = load(
            "sessions",
            ("id", "started_at_utc", "closed_at_utc"),
            "SELECT id, started_at_utc, closed_at_utc FROM sessions ORDER BY id",
        )
        sine_rows = load(
            "sine_facts",
            (
                "id", "session_id", "episode_uid", "candidate_uid", "kind",
                "popup_request_id", "occurred_monotonic_ns", "payload_json",
            ),
            "SELECT id, session_id, episode_uid, candidate_uid, kind, popup_request_id, "
            "occurred_monotonic_ns, payload_json FROM sine_facts "
            "ORDER BY occurred_monotonic_ns, id",
        )
        mirl_rows = load(
            "mirl_events",
            (
                "event_id", "session_id", "episode_id", "episode_sequence",
                "event_name", "occurred_monotonic_ns", "payload_json",
            ),
            "SELECT event_id, session_id, episode_id, episode_sequence, event_name, "
            "occurred_monotonic_ns, payload_json FROM mirl_events "
            "ORDER BY occurred_monotonic_ns, event_id",
        )
        mine_rows = load(
            "mine_events",
            (
                "event_id", "session_id", "mine_episode_id", "generation", "sequence",
                "event_name", "event_class", "occurred_at_utc", "monotonic_ns",
                "platform_key", "platform_label", "request_id", "evidence_token",
                "payload_json", "schema_version",
            ),
            "SELECT * FROM mine_events ORDER BY session_id, generation, sequence, event_id",
        )
        cosine_rows = load(
            "cosine_events",
            (
                "event_id", "session_id", "cosine_session_id", "generation", "sequence",
                "event_name", "event_class", "occurred_at_utc", "monotonic_ns",
                "platform_key", "content_title", "request_id", "evidence_token",
                "payload_json", "schema_version",
            ),
            "SELECT * FROM cosine_events "
            "ORDER BY cosine_session_id, generation, sequence, event_id",
        )
        cosecant_rows = load(
            "cosecant_events",
            (
                "id", "session_id", "break_id", "sequence", "kind",
                "occurred_monotonic_ns", "payload_json",
            ),
            "SELECT id, session_id, break_id, sequence, kind, occurred_monotonic_ns, "
            "payload_json FROM cosecant_events ORDER BY break_id, sequence, id",
        )

        session_ids: frozenset[int] = frozenset()
        if sessions is not None:
            try:
                _metric, identifiers, _sources = certified_metric_reader._session_population(sessions)
                session_ids = frozenset(identifiers)
            except Exception as error:
                errors["sessions"] = _bounded_error(error)

        mirl_events = None
        if mirl_rows is not None:
            try:
                mirl_events = certified_metric_reader._mirl_events(mirl_rows)
            except Exception as error:
                errors["mirl"] = _bounded_error(error)

        mine_events = None
        if mine_rows is not None:
            try:
                mine_events = certified_metric_reader._mine_events(mine_rows)
            except Exception as error:
                errors["mine"] = _bounded_error(error)

        cosine_events = None
        if cosine_rows is not None:
            try:
                cosine_events = certified_metric_reader._cosine_events(cosine_rows)
            except Exception as error:
                errors["cosine"] = _bounded_error(error)

        return _EvidenceSnapshot(
            session_ids,
            sine_rows,
            mirl_events,
            mine_events,
            cosine_events,
            cosecant_rows,
            tuple(sorted(errors.items())),
        )
    finally:
        connection.rollback()
        connection.close()


def _map_verified_sine_returns(
    displays: tuple[object, ...],
    mirl_events: tuple[MirlEvent, ...],
    session_ids: frozenset[int],
) -> frozenset[str]:
    samples, skipped = certified_metric_reader._scoped_sine_return_samples(mirl_events)
    if skipped:
        raise ValueError(
            f"scoped Chapter 6 validation excluded {skipped} returned episode(s)"
        )
    events_by_episode: dict[str, list[MirlEvent]] = {}
    for event in mirl_events:
        events_by_episode.setdefault(event.episode_id, []).append(event)
    stage1_by_join: dict[tuple[int, str, str], set[str]] = {}
    for display in displays:
        if display.stage == 1:
            key = (display.session_id, display.candidate_uid, display.occurred_wall_time_utc)
            stage1_by_join.setdefault(key, set()).add(display.episode_uid)

    mapped: dict[str, str] = {}
    sine_owner: dict[str, str] = {}
    for sample in samples:
        created = [
            event
            for event in events_by_episode.get(sample.episode_id, ())
            if event.event_name is MirlEventName.EPISODE_CREATED
        ]
        if len(created) != 1:
            raise ValueError("validated MIRL return lacks one episode-created identity")
        origin = created[0]
        if (
            type(origin.session_id) is not int
            or origin.session_id not in session_ids
            or not origin.candidate_uid
        ):
            raise ValueError("validated MIRL return lacks a valid parent/candidate")
        matches = stage1_by_join.get(
            (origin.session_id, origin.candidate_uid, origin.occurred_wall_time_utc),
            set(),
        )
        if len(matches) != 1:
            raise ValueError("validated MIRL return cannot map to one SINE episode")
        sine_episode = next(iter(matches))
        previous = sine_owner.setdefault(sine_episode, sample.episode_id)
        if previous != sample.episode_id:
            raise ValueError("multiple MIRL episodes map to one SINE episode")
        mapped[sample.episode_id] = sine_episode
    return frozenset(mapped.values())


def _project_sine(source: _EvidenceSnapshot) -> SineChartProjection:
    shared_error = source.error_for("sessions")
    sine_error = source.error_for("sine_facts") or source.error_for("sine")
    mirl_error = source.error_for("mirl_events") or source.error_for("mirl")
    if shared_error or sine_error or mirl_error:
        return _unavailable_sine(
            "SINE episode evidence is unavailable: "
            + (shared_error or sine_error or mirl_error or "unknown source error")
        )
    if source.sine_rows is None or source.mirl_events is None:
        return _unavailable_sine("SINE episode evidence is unavailable.")
    try:
        displays = certified_metric_reader._sine_displays(
            source.sine_rows, set(source.session_ids)
        )
        returned = _map_verified_sine_returns(
            displays, source.mirl_events, source.session_ids
        )
        groups: dict[str, list[object]] = {}
        for display in displays:
            groups.setdefault(display.episode_uid, []).append(display)

        episodes: list[SineEpisodeProjection] = []
        for episode_id, values in groups.items():
            ordered = sorted(values, key=lambda item: (item.occurred_monotonic_ns, item.row_id))
            session_ids = {item.session_id for item in ordered}
            candidates = {item.candidate_uid for item in ordered}
            if len(session_ids) != 1 or len(candidates) != 1:
                raise ValueError("SINE episode lineage is ambiguous")
            first_by_stage = {}
            for item in ordered:
                first_by_stage.setdefault(item.stage, item)
            stages = tuple(sorted(first_by_stage))
            if stages not in {(1,), (1, 2), (1, 2, 3)}:
                raise ValueError("SINE escalation stages do not form an approved prefix")
            episodes.append(
                SineEpisodeProjection(
                    session_id=next(iter(session_ids)),
                    episode_id=episode_id,
                    candidate_uid=next(iter(candidates)),
                    first_displayed_at_utc=first_by_stage[1].occurred_wall_time_utc,
                    stages_reached=stages,
                    verified_return=episode_id in returned,
                )
            )
        episodes.sort(key=lambda row: (row.first_displayed_at_utc, row.episode_id))
        frozen = tuple(episodes)
        funnel: list[SineFunnelStageProjection] = []
        denominator = len(frozen)
        for stage in _STAGES:
            identities = tuple(row.episode_id for row in frozen if stage in row.stages_reached)
            funnel.append(SineFunnelStageProjection(stage, identities, len(identities), denominator))
            denominator = len(identities)
        returned_ids = tuple(row.episode_id for row in frozen if row.verified_return)
        return SineChartProjection(
            AVAILABLE if frozen else NO_DATA,
            frozen,
            tuple(funnel),
            returned_ids,
            len(returned_ids),
            len(frozen),
            (
                "Recorded SINE episode escalation and separately validated returns."
                if frozen
                else "No recorded SINE display episodes."
            ),
        )
    except Exception as error:
        return _unavailable_sine(
            f"SINE episode validation failed: {_bounded_error(error)}"
        )


def _project_mine(source: _EvidenceSnapshot, stamp: str) -> MineChartProjection:
    error = (
        source.error_for("sessions")
        or source.error_for("mine_events")
        or source.error_for("mine")
    )
    if error or source.mine_events is None:
        return _unavailable_mine(f"MINE episode evidence is unavailable: {error or 'read failed'}")
    projection = project_mine_events(
        source.mine_events,
        presentation_timezone="local",
        generated_at_utc=stamp,
    )
    if not projection.available:
        return _unavailable_mine(projection.status_message)
    try:
        rows: list[MineChoiceOutcomeProjection] = []
        for episode in projection.episodes:
            if episode.branch is None:
                continue
            choice_event = next(
                (
                    event
                    for event in episode.events
                    if event.event_name
                    in {"RETURN_INTENT_RECORDED", "IMPORTANT_INTENT_RECORDED"}
                ),
                None,
            )
            if choice_event is None:
                raise ValueError("MINE branch lacks its durable choice event")
            rows.append(
                MineChoiceOutcomeProjection(
                    episode.session_id,
                    episode.generation,
                    episode.mine_episode_id,
                    episode.display_episode_id,
                    episode.branch,
                    choice_event.occurred_at_utc,
                    episode.closure_outcome,
                    episode.closure_reason,
                    episode.ended_at_utc,
                    episode.return_verified,
                )
            )
        frozen = tuple(rows)
        choice_counts = Counter(row.choice for row in frozen)
        grouped: dict[tuple[str, str], list[str]] = {}
        for row in frozen:
            if row.closure_outcome is not None:
                grouped.setdefault((row.choice, row.closure_outcome), []).append(
                    row.mine_episode_id
                )
        buckets = tuple(
            MineOutcomeBucketProjection(
                choice,
                outcome,
                tuple(identities),
                len(identities),
                choice_counts[choice],
            )
            for (choice, outcome), identities in sorted(grouped.items())
        )
        documented = sum(row.closure_outcome is not None for row in frozen)
        return MineChartProjection(
            AVAILABLE if frozen else NO_DATA,
            frozen,
            buckets,
            len(frozen),
            documented,
            (
                "Actual recorded MINE-1 choices and documented subsequent outcomes."
                if frozen
                else "No recorded MINE-1 choices."
            ),
        )
    except Exception as error:
        return _unavailable_mine(f"MINE chart validation failed: {_bounded_error(error)}")


def _project_cosine(source: _EvidenceSnapshot, stamp: str) -> CosineChartProjection:
    error = (
        source.error_for("sessions")
        or source.error_for("cosine_events")
        or source.error_for("cosine")
    )
    if error or source.cosine_events is None:
        return _unavailable_cosine(
            f"COSINE event evidence is unavailable: {error or 'read failed'}"
        )
    projection = project_cosine_events(
        source.cosine_events,
        presentation_timezone="local",
        generated_at_utc=stamp,
    )
    if not projection.available:
        return _unavailable_cosine(projection.status_message)
    try:
        episodes = tuple(
            CosineEpisodeTimelineProjection(
                episode.cosine_session_id,
                episode.generation,
                episode.parent_session_id,
                episode.started_at_utc,
                episode.ended_at_utc,
                tuple(
                    CosineRecordedEventProjection(
                        event.event_id,
                        event.sequence,
                        event.event_name,
                        event.occurred_at_utc,
                    )
                    for event in episode.events
                ),
            )
            for episode in projection.episodes
        )
        return CosineChartProjection(
            AVAILABLE if episodes else NO_DATA,
            episodes,
            len(episodes),
            sum(len(episode.events) for episode in episodes),
            (
                "Recorded COSINE event timestamps; no continuous viewing duration is inferred."
                if episodes
                else "No recorded COSINE episodes."
            ),
        )
    except Exception as error:
        return _unavailable_cosine(
            f"COSINE timeline validation failed: {_bounded_error(error)}"
        )


def _project_cosecant(source: _EvidenceSnapshot) -> CosecantChartProjection:
    shared_error = source.error_for("sessions")
    error = source.error_for("cosecant_events") or source.error_for("cosecant")
    if shared_error or error or source.cosecant_rows is None:
        return _unavailable_cosecant(
            "COSECANT evidence is unavailable: "
            + (shared_error or error or "read failed")
        )
    try:
        certified_metric_reader._cosecant_metric(
            source.cosecant_rows, set(source.session_ids)
        )
        groups: dict[tuple[int, str], list[dict]] = {}
        for row in source.cosecant_rows:
            break_id = str(row["break_id"] or "")
            kind = str(row["kind"])
            if not break_id and kind == "SAFE_SHUTDOWN":
                continue
            payload = json.loads(str(row["payload_json"]))
            groups.setdefault((int(row["session_id"]), break_id), []).append(payload)

        breaks: list[CosecantBreakProjection] = []
        for (session_id, break_id), facts in groups.items():
            ordered = sorted(facts, key=lambda fact: int(fact["sequence"]))
            start = next(
                (fact for fact in ordered if fact["kind"] == "BREAK_STARTED"),
                None,
            )
            if start is None:
                continue
            milestones = tuple(
                CosecantMilestoneProjection(
                    int(fact["sequence"]),
                    str(fact["kind"]),
                    int(fact["effective_monotonic_ns"]),
                    int(fact["observed_monotonic_ns"]),
                    str(fact["occurred_wall_time_utc"]),
                    str(fact.get("evidence_token") or ""),
                )
                for fact in ordered
                if str(fact["kind"]) in _COSECANT_MILESTONES
            )
            breaks.append(
                CosecantBreakProjection(
                    session_id,
                    break_id,
                    str(start["study_block_id"]),
                    milestones,
                    any(item.kind == "RETURN_CONFIRMED" for item in milestones),
                )
            )
        breaks.sort(
            key=lambda row: (
                row.milestones[0].occurred_at_utc if row.milestones else "",
                row.session_id,
                row.break_id,
            )
        )
        frozen = tuple(breaks)
        return CosecantChartProjection(
            AVAILABLE if frozen else NO_DATA,
            frozen,
            len(frozen),
            sum(row.return_confirmed for row in frozen),
            (
                "Recorded COSECANT break deadlines and return milestones."
                if frozen
                else "No recorded COSECANT breaks."
            ),
        )
    except Exception as error:
        return _unavailable_cosecant(
            f"COSECANT milestone validation failed: {_bounded_error(error)}"
        )


def validate_poster_chart_data(projection: object) -> PosterChartData:
    """Fail closed unless every poster projection satisfies its frozen contract."""

    if not isinstance(projection, PosterChartData):
        raise TypeError("poster data must be PosterChartData")
    summary = projection.lifetime_summary
    if not isinstance(summary, LifetimeMetricHubProjection):
        raise TypeError("poster data requires a LifetimeMetricHubProjection summary")
    expected_types = (
        (projection.sine, SineChartProjection),
        (projection.mine, MineChartProjection),
        (projection.cosine, CosineChartProjection),
        (projection.cosecant, CosecantChartProjection),
    )
    if any(not isinstance(value, expected) for value, expected in expected_types):
        raise TypeError("poster data requires all four immutable chart projections")
    if projection.secant is not None and not isinstance(projection.secant, SecantChartProjection):
        raise TypeError("poster SECANT data requires its immutable projection")
    if projection.study_blocks_started is not None and (
        type(projection.study_blocks_started) is not int or projection.study_blocks_started < 0
    ):
        raise ValueError("Study block count must be a non-negative integer")
    if summary.read_only is not True:
        raise ValueError("poster data must come from a read-only snapshot")
    if not _nonempty(summary.snapshot_id) or not _nonempty(projection.generated_at_utc):
        raise ValueError("poster data requires snapshot identity and generation time")
    names = tuple(organ.organ.strip().upper() for organ in summary.organs)
    if names != POSTER_ORGANS:
        raise ValueError("poster summary must contain SINE, COSINE, MINE and COSECANT")
    for row in summary.session_rows:
        if type(row.session_id) is not int or row.session_id <= 0:
            raise ValueError("poster session rows require positive session identities")
        if type(row.ordinal) is not int or row.ordinal <= 0:
            raise ValueError("poster session rows require positive ordinals")
        if type(row.is_closed) is not bool:
            raise ValueError("poster session closure must be factual boolean data")
    return projection


def read_poster_chart_data(
    database_file: str | Path | None = None,
) -> PosterChartData:
    """Read one summary plus four separately validated poster projections."""

    stamp = _utc_now()
    summary = read_lifetime_metric_hub(database_file)
    source = _read_evidence(database_file)
    family = None
    try:
        from GET_CHART.study_family_evidence import read_study_family

        family = read_study_family(database_file if database_file is not None else database_path(create_parent=False))
    except Exception:
        pass
    study_count = None
    if family is not None and not family.errors.get("study"):
        study_count = sum(
            bool(block.get("payload", {}).get("started_wall_time_utc"))
            for _session_id, result in family.studies for block in result.get("blocks", ())
        )
    return validate_poster_chart_data(
        PosterChartData(
            lifetime_summary=summary,
            sine=_project_sine(source),
            mine=_project_mine(source, stamp),
            cosine=_project_cosine(source, stamp),
            cosecant=_project_cosecant(source),
            generated_at_utc=stamp,
            secant=secant_chart_from_family(family),
            study_blocks_started=study_count,
        )
    )


__all__ = [
    "AVAILABLE",
    "NO_DATA",
    "UNAVAILABLE",
    "CosecantBreakProjection",
    "CosecantChartProjection",
    "CosecantMilestoneProjection",
    "SecantChartProjection",
    "secant_chart_from_family",
    "CosineChartProjection",
    "CosineEpisodeTimelineProjection",
    "CosineRecordedEventProjection",
    "MineChartProjection",
    "MineChoiceOutcomeProjection",
    "MineOutcomeBucketProjection",
    "PosterChartData",
    "SineChartProjection",
    "SineEpisodeProjection",
    "SineFunnelStageProjection",
    "read_poster_chart_data",
    "validate_poster_chart_data",
]
