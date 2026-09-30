"""Single production SQLite schema authority for MYELIN 2.0."""

from __future__ import annotations

import sqlite3
from typing import Final

from PERSISTENCE.database import connect_database


SCHEMA_VERSION: Final = 9
MANAGED_TABLES: Final = frozenset(
    {
        "myelin_meta",
        "sessions",
        "pie_session_time",
        "triggers",
        "sine_facts",
        "normal_break_events",
        "mirl_events",
        "cosine_events",
        "mine_events",
        "study_events",
        "study_resources",
        "secant_events",
        "study_resource_events",
        "cosecant_events",
        "science_lab_experiments",
        "notes",
        "planner_blocks",
        "emergency_events",
        "emergency_followup",
        "profile_learning_state",
        "presentation_aliases",
    }
)


_SCHEMA_SQL: Final = """
CREATE TABLE IF NOT EXISTS myelin_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_type TEXT NOT NULL,
    started_at_utc TEXT NOT NULL,
    closed_at_utc TEXT,
    close_reason TEXT,
    emergency INTEGER NOT NULL DEFAULT 0 CHECK (emergency IN (0, 1))
);

CREATE TABLE IF NOT EXISTS pie_session_time (
    session_id INTEGER PRIMARY KEY REFERENCES sessions(id),
    social_ms INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(social_ms) = 'integer' AND social_ms >= 0),
    ott_ms INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(ott_ms) = 'integer' AND ott_ms >= 0),
    messaging_ms INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(messaging_ms) = 'integer' AND messaging_ms >= 0),
    focus_ms INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(focus_ms) = 'integer' AND focus_ms >= 0),
    unclassified_ms INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(unclassified_ms) = 'integer' AND unclassified_ms >= 0),
    revision INTEGER NOT NULL DEFAULT 0
        CHECK (typeof(revision) = 'integer' AND revision >= 0),
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    candidate_uid TEXT NOT NULL UNIQUE,
    occurred_monotonic_ns INTEGER NOT NULL CHECK (occurred_monotonic_ns > 0),
    payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sine_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    episode_uid TEXT NOT NULL DEFAULT '',
    candidate_uid TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    popup_request_id TEXT NOT NULL DEFAULT '',
    occurred_monotonic_ns INTEGER NOT NULL CHECK (occurred_monotonic_ns >= 0),
    payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sine_facts_session_time
    ON sine_facts(session_id, occurred_monotonic_ns, id);

CREATE TABLE IF NOT EXISTS normal_break_events (
    event_id TEXT PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    break_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    episode_uid TEXT NOT NULL,
    candidate_uid TEXT NOT NULL,
    kind TEXT NOT NULL,
    occurred_monotonic_ns INTEGER NOT NULL CHECK (occurred_monotonic_ns >= 0),
    payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    UNIQUE(break_id, sequence)
);
CREATE INDEX IF NOT EXISTS ix_normal_break_events_session_time
    ON normal_break_events(session_id, occurred_monotonic_ns, event_id);

CREATE TABLE IF NOT EXISTS mirl_events (
    event_id TEXT PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    episode_id TEXT NOT NULL DEFAULT '',
    episode_sequence INTEGER NOT NULL,
    event_name TEXT NOT NULL,
    occurred_monotonic_ns INTEGER NOT NULL CHECK (occurred_monotonic_ns > 0),
    payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mirl_events_session_time
    ON mirl_events(session_id, occurred_monotonic_ns, event_id);

CREATE TABLE IF NOT EXISTS cosine_events (
    event_id TEXT PRIMARY KEY,
    session_id INTEGER REFERENCES sessions(id),
    cosine_session_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK (generation > 0),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_name TEXT NOT NULL,
    event_class TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL,
    monotonic_ns INTEGER NOT NULL CHECK (monotonic_ns > 0),
    platform_key TEXT NOT NULL DEFAULT '',
    content_title TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL DEFAULT '',
    evidence_token TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    UNIQUE(cosine_session_id, generation, sequence)
);
CREATE INDEX IF NOT EXISTS ix_cosine_events_session_sequence
    ON cosine_events(cosine_session_id, generation, sequence);

CREATE TABLE IF NOT EXISTS mine_events (
    event_id TEXT PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    mine_episode_id TEXT NOT NULL DEFAULT '',
    generation INTEGER NOT NULL CHECK (generation > 0),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    event_name TEXT NOT NULL,
    event_class TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL,
    monotonic_ns INTEGER NOT NULL CHECK (monotonic_ns > 0),
    platform_key TEXT NOT NULL DEFAULT '',
    platform_label TEXT NOT NULL DEFAULT '',
    request_id TEXT NOT NULL DEFAULT '',
    evidence_token TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    UNIQUE(session_id, generation, sequence)
);
CREATE INDEX IF NOT EXISTS ix_mine_events_episode_sequence
    ON mine_events(mine_episode_id, generation, sequence);

CREATE TABLE IF NOT EXISTS study_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    study_block_id TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    occurred_monotonic_ns INTEGER NOT NULL CHECK (occurred_monotonic_ns >= 0),
    payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cosecant_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    break_id TEXT NOT NULL DEFAULT '',
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL,
    occurred_monotonic_ns INTEGER NOT NULL CHECK (occurred_monotonic_ns >= 0),
    payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    UNIQUE(break_id, sequence)
);

CREATE TABLE IF NOT EXISTS science_lab_experiments (
    experiment_id TEXT PRIMARY KEY,
    parent_session_id INTEGER NOT NULL REFERENCES sessions(id),
    date_key TEXT NOT NULL,
    daily_sequence INTEGER NOT NULL CHECK (daily_sequence BETWEEN 1 AND 99),
    status TEXT NOT NULL CHECK (
        status IN ('RUNNING', 'COMPLETED', 'INTERRUPTED')
    ),
    started_at_utc TEXT NOT NULL,
    started_monotonic_ns INTEGER NOT NULL CHECK (started_monotonic_ns > 0),
    ended_at_utc TEXT,
    ended_monotonic_ns INTEGER,
    end_reason TEXT NOT NULL DEFAULT '',
    runtime_instance_id TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,

    UNIQUE(date_key, daily_sequence),

    CHECK (
        length(date_key) = 8
    ),

    CHECK (
        (
            status = 'RUNNING'
            AND ended_at_utc IS NULL
            AND ended_monotonic_ns IS NULL
            AND end_reason = ''
        )
        OR
        (
            status = 'COMPLETED'
            AND ended_at_utc IS NOT NULL
            AND ended_monotonic_ns IS NOT NULL
            AND ended_monotonic_ns >= started_monotonic_ns
            AND end_reason IN ('USER_END', 'PARENT_SESSION_ENDED')
        )
        OR
        (
            status = 'INTERRUPTED'
            AND ended_at_utc IS NOT NULL
            AND ended_monotonic_ns IS NULL
            AND end_reason = 'CRASH_RECOVERY'
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_science_lab_one_running
    ON science_lab_experiments(status)
    WHERE status = 'RUNNING';

CREATE INDEX IF NOT EXISTS ix_science_lab_experiments_parent_start
    ON science_lab_experiments(
        parent_session_id,
        started_monotonic_ns,
        experiment_id
    );

CREATE TABLE IF NOT EXISTS notes (
    note_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    payload_json TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS planner_blocks (
    plan_id TEXT NOT NULL,
    block_id TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    payload_json TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (plan_id, block_id)
);

CREATE TABLE IF NOT EXISTS emergency_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    occurred_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS emergency_followup (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    pending INTEGER NOT NULL CHECK (pending IN (0, 1)),
    emergency_event_id INTEGER REFERENCES emergency_events(id),
    reason_code TEXT NOT NULL DEFAULT '',
    answered_at_utc TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS profile_learning_state (
    profile_key TEXT PRIMARY KEY,
    learned_lambda REAL,
    learned_return_latency_seconds REAL,
    valid_session_count INTEGER NOT NULL DEFAULT 0
        CHECK (valid_session_count >= 0),
    valid_episode_count INTEGER NOT NULL DEFAULT 0
        CHECK (valid_episode_count >= 0),
    last_learning_session_id INTEGER REFERENCES sessions(id),
    last_updated_utc TEXT NOT NULL DEFAULT '',
    model_version TEXT NOT NULL DEFAULT 'myelin-ebbinghaus-profile-learning-v1',
    CHECK (
        (
            learned_lambda IS NULL
            AND learned_return_latency_seconds IS NULL
            AND valid_session_count = 0
            AND valid_episode_count = 0
            AND last_learning_session_id IS NULL
        )
        OR
        (
            learned_lambda > 0.0
            AND learned_return_latency_seconds > 0.0
            AND valid_session_count > 0
            AND valid_episode_count >= valid_session_count
            AND last_learning_session_id IS NOT NULL
        )
    )
);
"""



_PROFILE_LEARNING_COLUMNS: Final = {
    "profile_key": ("TEXT", 0, 1),
    "learned_lambda": ("REAL", 0, 0),
    "learned_return_latency_seconds": ("REAL", 0, 0),
    "valid_session_count": ("INTEGER", 1, 0),
    "valid_episode_count": ("INTEGER", 1, 0),
    "last_learning_session_id": ("INTEGER", 0, 0),
    "last_updated_utc": ("TEXT", 1, 0),
    "model_version": ("TEXT", 1, 0),
}


_PIE_SESSION_TIME_COLUMNS: Final = {
    "session_id": ("INTEGER", 0, 1),
    "social_ms": ("INTEGER", 1, 0),
    "ott_ms": ("INTEGER", 1, 0),
    "messaging_ms": ("INTEGER", 1, 0),
    "focus_ms": ("INTEGER", 1, 0),
    "unclassified_ms": ("INTEGER", 1, 0),
    "revision": ("INTEGER", 1, 0),
    "updated_at_utc": ("TEXT", 1, 0),
}


_COSINE_EVENT_COLUMNS: Final = {
    "event_id": ("TEXT", 0, 1),
    "session_id": ("INTEGER", 0, 0),
    "cosine_session_id": ("TEXT", 1, 0),
    "generation": ("INTEGER", 1, 0),
    "sequence": ("INTEGER", 1, 0),
    "event_name": ("TEXT", 1, 0),
    "event_class": ("TEXT", 1, 0),
    "occurred_at_utc": ("TEXT", 1, 0),
    "monotonic_ns": ("INTEGER", 1, 0),
    "platform_key": ("TEXT", 1, 0),
    "content_title": ("TEXT", 1, 0),
    "request_id": ("TEXT", 1, 0),
    "evidence_token": ("TEXT", 1, 0),
    "payload_json": ("TEXT", 1, 0),
    "schema_version": ("TEXT", 1, 0),
}


_MINE_EVENT_COLUMNS: Final = {
    "event_id": ("TEXT", 0, 1),
    "session_id": ("INTEGER", 1, 0),
    "mine_episode_id": ("TEXT", 1, 0),
    "generation": ("INTEGER", 1, 0),
    "sequence": ("INTEGER", 1, 0),
    "event_name": ("TEXT", 1, 0),
    "event_class": ("TEXT", 1, 0),
    "occurred_at_utc": ("TEXT", 1, 0),
    "monotonic_ns": ("INTEGER", 1, 0),
    "platform_key": ("TEXT", 1, 0),
    "platform_label": ("TEXT", 1, 0),
    "request_id": ("TEXT", 1, 0),
    "evidence_token": ("TEXT", 1, 0),
    "payload_json": ("TEXT", 1, 0),
    "schema_version": ("TEXT", 1, 0),
}


_SCIENCE_LAB_EXPERIMENT_COLUMNS: Final = {
    "experiment_id": ("TEXT", 0, 1),
    "parent_session_id": ("INTEGER", 1, 0),
    "date_key": ("TEXT", 1, 0),
    "daily_sequence": ("INTEGER", 1, 0),
    "status": ("TEXT", 1, 0),
    "started_at_utc": ("TEXT", 1, 0),
    "started_monotonic_ns": ("INTEGER", 1, 0),
    "ended_at_utc": ("TEXT", 0, 0),
    "ended_monotonic_ns": ("INTEGER", 0, 0),
    "end_reason": ("TEXT", 1, 0),
    "runtime_instance_id": ("TEXT", 1, 0),
    "created_at_utc": ("TEXT", 1, 0),
    "updated_at_utc": ("TEXT", 1, 0),
}


def _migrate_cosine_parent_session(connection: sqlite3.Connection) -> None:
    """Add the nullable parent identity before creating its dependent index."""

    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(cosine_events)").fetchall()
    }
    if not columns:
        raise RuntimeError("cosine_events table is missing")
    if "session_id" not in columns:
        connection.execute(
            "ALTER TABLE cosine_events "
            "ADD COLUMN session_id INTEGER REFERENCES sessions(id)"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS ix_cosine_events_parent_session_sequence "
        "ON cosine_events(session_id, cosine_session_id, generation, sequence)"
    )


def _index_columns(connection: sqlite3.Connection, name: str) -> tuple[str, ...]:
    escaped = str(name).replace("'", "''")
    rows = connection.execute(f"PRAGMA index_info('{escaped}')").fetchall()
    return tuple(str(row[2]) for row in sorted(rows, key=lambda row: int(row[0])))


def _verify_cosine_events(connection: sqlite3.Connection) -> None:
    rows = connection.execute("PRAGMA table_info(cosine_events)").fetchall()
    observed = {
        str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in rows
    }
    if observed != _COSINE_EVENT_COLUMNS:
        raise RuntimeError("cosine_events schema does not match MYELIN 2.0 Phase 1G")

    foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(cosine_events)"
    ).fetchall()
    if not any(
        str(row[2]) == "sessions"
        and str(row[3]) == "session_id"
        and str(row[4]) == "id"
        for row in foreign_keys
    ):
        raise RuntimeError("cosine_events is missing its parent sessions foreign key")

    index_rows = connection.execute("PRAGMA index_list(cosine_events)").fetchall()
    unique_sequence = any(
        int(row[2]) == 1
        and _index_columns(connection, str(row[1]))
        == ("cosine_session_id", "generation", "sequence")
        for row in index_rows
    )
    if not unique_sequence:
        raise RuntimeError("cosine_events is missing unique episode sequence protection")

    indexes = {
        str(row[1]): _index_columns(connection, str(row[1]))
        for row in index_rows
    }
    if indexes.get("ix_cosine_events_parent_session_sequence") != (
        "session_id",
        "cosine_session_id",
        "generation",
        "sequence",
    ):
        raise RuntimeError("cosine_events parent session index is missing or malformed")


def _verify_mine_events(connection: sqlite3.Connection) -> None:
    rows = connection.execute("PRAGMA table_info(mine_events)").fetchall()
    observed = {
        str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in rows
    }
    if observed != _MINE_EVENT_COLUMNS:
        raise RuntimeError("mine_events schema does not match MYELIN 2.0 Phase 2")

    foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(mine_events)"
    ).fetchall()
    if not any(
        str(row[2]) == "sessions"
        and str(row[3]) == "session_id"
        and str(row[4]) == "id"
        for row in foreign_keys
    ):
        raise RuntimeError("mine_events is missing its parent sessions foreign key")

    index_rows = connection.execute("PRAGMA index_list(mine_events)").fetchall()
    if not any(
        int(row[2]) == 1
        and _index_columns(connection, str(row[1]))
        == ("session_id", "generation", "sequence")
        for row in index_rows
    ):
        raise RuntimeError("mine_events is missing unique generation sequence protection")
    indexes = {
        str(row[1]): _index_columns(connection, str(row[1]))
        for row in index_rows
    }
    if indexes.get("ix_mine_events_episode_sequence") != (
        "mine_episode_id",
        "generation",
        "sequence",
    ):
        raise RuntimeError("mine_events episode index is missing or malformed")


def _verify_science_lab_experiments(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "PRAGMA table_info(science_lab_experiments)"
    ).fetchall()
    observed = {
        str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in rows
    }
    if observed != _SCIENCE_LAB_EXPERIMENT_COLUMNS:
        raise RuntimeError(
            "science_lab_experiments schema does not match MYELIN 2.0 Phase 2.2"
        )

    foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(science_lab_experiments)"
    ).fetchall()
    if not any(
        str(row[2]) == "sessions"
        and str(row[3]) == "parent_session_id"
        and str(row[4]) == "id"
        for row in foreign_keys
    ):
        raise RuntimeError(
            "science_lab_experiments is missing its parent sessions foreign key"
        )

    index_rows = connection.execute(
        "PRAGMA index_list(science_lab_experiments)"
    ).fetchall()
    if not any(
        int(row[2]) == 1
        and _index_columns(connection, str(row[1]))
        == ("date_key", "daily_sequence")
        for row in index_rows
    ):
        raise RuntimeError(
            "science_lab_experiments is missing unique daily sequence protection"
        )

    indexes = {
        str(row[1]): _index_columns(connection, str(row[1]))
        for row in index_rows
    }
    if indexes.get("ix_science_lab_experiments_parent_start") != (
        "parent_session_id",
        "started_monotonic_ns",
        "experiment_id",
    ):
        raise RuntimeError(
            "science_lab_experiments parent session index is missing or malformed"
        )

    one_running = next(
        (
            row
            for row in index_rows
            if str(row[1]) == "ux_science_lab_one_running"
        ),
        None,
    )
    if (
        one_running is None
        or int(one_running[2]) != 1
        or int(one_running[4]) != 1
        or indexes.get("ux_science_lab_one_running") != ("status",)
    ):
        raise RuntimeError(
            "science_lab_experiments one-running index is missing or malformed"
        )


def _verify_profile_learning_state(connection: sqlite3.Connection) -> None:
    rows = connection.execute("PRAGMA table_info(profile_learning_state)").fetchall()
    observed = {
        str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in rows
    }
    if observed != _PROFILE_LEARNING_COLUMNS:
        raise RuntimeError("profile_learning_state schema does not match MYELIN 2.0")

    foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(profile_learning_state)"
    ).fetchall()
    expected_fk = any(
        str(row[2]) == "sessions"
        and str(row[3]) == "last_learning_session_id"
        and str(row[4]) == "id"
        for row in foreign_keys
    )
    if not expected_fk:
        raise RuntimeError(
            "profile_learning_state is missing its sessions provenance foreign key"
        )


def _verify_pie_session_time(connection: sqlite3.Connection) -> None:
    rows = connection.execute("PRAGMA table_info(pie_session_time)").fetchall()
    observed = {
        str(row[1]): (str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in rows
    }
    if observed != _PIE_SESSION_TIME_COLUMNS:
        raise RuntimeError("pie_session_time schema does not match MYELIN 2.0")

    foreign_keys = connection.execute(
        "PRAGMA foreign_key_list(pie_session_time)"
    ).fetchall()
    expected_fk = any(
        str(row[2]) == "sessions"
        and str(row[3]) == "session_id"
        and str(row[4]) == "id"
        for row in foreign_keys
    )
    if not expected_fk:
        raise RuntimeError("pie_session_time is missing its sessions foreign key")


def _migrate_profile_learning_state_return_latency(connection: sqlite3.Connection) -> None:
    """Additive upgrade for databases that predate the MBRM Tr-authority fix.

    ``CREATE TABLE IF NOT EXISTS`` above is a no-op against an
    already-existing ``profile_learning_state`` table, so an earlier
    database keeps its original 7-column shape (no
    ``learned_return_latency_seconds``) until explicitly upgraded here.

    Any already-learned row from before this column existed has no real
    historical return-latency evidence.  Per this module's own rule (see
    ``PERSISTENCE.storage``: "this read never invents a fallback lambda"),
    that evidence is not fabricated -- the row is reset to the explicit
    unlearned state instead, so the affected profile simply re-enters the
    session-1 learning phase and starts building real Tr history from here.
    """

    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(profile_learning_state)"
        ).fetchall()
    }
    if not columns or "learned_return_latency_seconds" in columns:
        return
    connection.execute(
        "ALTER TABLE profile_learning_state "
        "ADD COLUMN learned_return_latency_seconds REAL"
    )
    connection.execute(
        "UPDATE profile_learning_state SET "
        "learned_lambda=NULL, learned_return_latency_seconds=NULL, "
        "valid_session_count=0, valid_episode_count=0, "
        "last_learning_session_id=NULL "
        "WHERE learned_lambda IS NOT NULL"
    )


# Phase-1 corrections were independently versioned on v8; aliases advance to v9.
_OWNERSHIP_GUARD_SQL = """CREATE TRIGGER IF NOT EXISTS myelin_schema_no_downgrade
BEFORE UPDATE OF value ON myelin_meta
WHEN OLD.key = 'schema_version'
 AND CAST(NEW.value AS INTEGER) < CAST(OLD.value AS INTEGER)
BEGIN
    SELECT RAISE(ABORT, 'Schema downgrade prohibited');
END;"""
_FOUNDING_SOURCE_SQL = """CREATE TABLE IF NOT EXISTS secant_founding_source (
    event_id TEXT NOT NULL PRIMARY KEY REFERENCES secant_events(event_id),
    source_extension_version INTEGER NOT NULL CHECK (source_extension_version = 1),
    source_evidence_id TEXT NOT NULL CHECK (length(source_evidence_id) > 0),
    source_resource_id TEXT NOT NULL CHECK (length(source_resource_id) > 0),
    source_observed_monotonic_ns INTEGER NOT NULL CHECK (typeof(source_observed_monotonic_ns) = 'integer' AND source_observed_monotonic_ns >= 0),
    source_evidence_json TEXT NOT NULL CHECK (json_valid(source_evidence_json))
);"""


# Observation endpoints, not inferred switch instants or supported durations.
_STUDY_BOUNDARY_SQL = """CREATE TABLE IF NOT EXISTS study_resource_boundaries (
    boundary_id TEXT NOT NULL PRIMARY KEY,
    contract_version INTEGER NOT NULL CHECK (contract_version = 1),
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    capture_id TEXT NOT NULL,
    boundary_ordinal INTEGER NOT NULL CHECK (boundary_ordinal > 0),
    study_context_token TEXT NOT NULL,
    study_block_id TEXT,
    study_generation INTEGER,
    from_observation_id TEXT NOT NULL,
    from_resource_key TEXT NOT NULL,
    from_observation_ordinal INTEGER NOT NULL,
    from_observed_monotonic_ns INTEGER NOT NULL,
    from_observed_at_utc TEXT NOT NULL,
    from_identity_json TEXT NOT NULL CHECK (json_valid(from_identity_json)),
    to_observation_id TEXT NOT NULL,
    to_resource_key TEXT NOT NULL,
    to_observation_ordinal INTEGER NOT NULL,
    to_observed_monotonic_ns INTEGER NOT NULL,
    to_observed_at_utc TEXT NOT NULL,
    to_identity_json TEXT NOT NULL CHECK (json_valid(to_identity_json)),
    capture_gap_reasons_json TEXT NOT NULL CHECK (json_valid(capture_gap_reasons_json)),
    continuity TEXT NOT NULL CHECK (continuity IN ('CONTIGUOUS_OBSERVED_CHANGE', 'CHANGE_ACROSS_EVIDENCE_GAP')),
    gap_reasons_json TEXT NOT NULL CHECK (json_valid(gap_reasons_json)),
    CHECK (from_resource_key != to_resource_key),
    CHECK (from_observation_ordinal >= 0 AND to_observation_ordinal > from_observation_ordinal),
    CHECK (from_observed_monotonic_ns >= 0 AND to_observed_monotonic_ns > from_observed_monotonic_ns),
    UNIQUE (capture_id, boundary_ordinal)
);"""


def _verify_study_boundary_schema(connection, *, required=False):
    rows = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE tbl_name='study_resource_boundaries' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    if not rows and not required:
        return
    expected = [("table", "study_resource_boundaries", "study_resource_boundaries",
        _stored_correction_sql(_STUDY_BOUNDARY_SQL))]
    if [tuple(row) for row in rows] != expected:
        raise RuntimeError("Study boundary schema contract mismatch")
    if connection.execute("PRAGMA foreign_key_check(study_resource_boundaries)").fetchall():
        raise RuntimeError("Study boundary parent-session violation")


def install_correction2_schema(connection):
    """Explicit additive installation after the post-Correction-1 backup."""
    if not connection.in_transaction:
        raise RuntimeError("Correction-2 installation requires an active transaction")
    version = connection.execute("SELECT value FROM myelin_meta WHERE key='schema_version'").fetchone()
    if version is None or str(version[0]) != "8":
        raise RuntimeError("Correction-2 installation requires schema version 8")
    _verify_recorder_schema(connection)
    _verify_founding_source_schema(connection, required=True)
    _verify_no_interfering_triggers(connection)
    connection.execute(_STUDY_BOUNDARY_SQL)
    _verify_study_boundary_schema(connection, required=True)


_STUDY_INTERVAL_SQL = """CREATE TABLE IF NOT EXISTS study_resource_intervals (
    interval_id TEXT NOT NULL PRIMARY KEY,
    interval_extension_version INTEGER NOT NULL CHECK (interval_extension_version = 1),
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    capture_id TEXT NOT NULL,
    span_ordinal INTEGER NOT NULL CHECK (span_ordinal > 0),
    study_context_token TEXT NOT NULL,
    study_block_id TEXT,
    study_generation INTEGER,
    resource_key TEXT NOT NULL,
    first_observation_id TEXT NOT NULL,
    last_observation_id TEXT NOT NULL,
    first_observation_ordinal INTEGER NOT NULL CHECK (first_observation_ordinal >= 0),
    last_observation_ordinal INTEGER NOT NULL,
    first_observed_monotonic_ns INTEGER NOT NULL CHECK (first_observed_monotonic_ns >= 0),
    last_observed_monotonic_ns INTEGER NOT NULL,
    observation_count INTEGER NOT NULL CHECK (observation_count > 0),
    continuity_max_gap_ns INTEGER NOT NULL CHECK (continuity_max_gap_ns > 0),
    supported_duration_ns INTEGER NOT NULL CHECK (supported_duration_ns >= 0),
    continuity_status TEXT NOT NULL CHECK (continuity_status IN ('SUPPORTED_SPAN', 'SINGLE_OBSERVATION')),
    close_reason TEXT NOT NULL,
    CHECK (last_observation_ordinal - first_observation_ordinal = observation_count - 1),
    CHECK (last_observed_monotonic_ns - first_observed_monotonic_ns = supported_duration_ns),
    CHECK ((observation_count = 1 AND supported_duration_ns = 0 AND continuity_status = 'SINGLE_OBSERVATION'
            AND first_observation_id = last_observation_id)
        OR (observation_count > 1 AND supported_duration_ns > 0 AND continuity_status = 'SUPPORTED_SPAN'
            AND first_observation_id != last_observation_id)),
    CHECK ((study_block_id IS NULL AND study_generation IS NULL)
        OR (study_block_id IS NOT NULL AND study_generation IS NOT NULL AND study_generation > 0)),
    UNIQUE (capture_id, span_ordinal)
);"""


def _verify_study_interval_schema(connection, *, required=False):
    rows = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE tbl_name='study_resource_intervals' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    if not rows and not required:
        return
    expected = [("table", "study_resource_intervals", "study_resource_intervals",
        _stored_correction_sql(_STUDY_INTERVAL_SQL))]
    if [tuple(row) for row in rows] != expected:
        raise RuntimeError("Study interval schema contract mismatch")
    if connection.execute("PRAGMA foreign_key_check(study_resource_intervals)").fetchall():
        raise RuntimeError("Study interval parent-session violation")


def install_correction3_schema(connection):
    """Explicit additive installation; never backfill inferred durations."""
    if not connection.in_transaction:
        raise RuntimeError("Correction-3 installation requires an active transaction")
    version = connection.execute("SELECT value FROM myelin_meta WHERE key='schema_version'").fetchone()
    if version is None or str(version[0]) != "8":
        raise RuntimeError("Correction-3 installation requires schema version 8")
    _verify_recorder_schema(connection)
    _verify_founding_source_schema(connection, required=True)
    _verify_study_boundary_schema(connection, required=True)
    _verify_no_interfering_triggers(connection)
    connection.execute(_STUDY_INTERVAL_SQL)
    _verify_study_interval_schema(connection, required=True)


_STUDY_OBSERVATION_EVIDENCE_SQL = """CREATE TABLE IF NOT EXISTS study_resource_observation_evidence (
    evidence_id TEXT NOT NULL PRIMARY KEY,
    extension_version INTEGER NOT NULL CHECK (extension_version = 1),
    kind TEXT NOT NULL CHECK (kind IN ('OBSERVATION', 'CONFIRMATION')),
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    interval_capture_id TEXT NOT NULL,
    boundary_capture_id TEXT NOT NULL,
    study_context_token TEXT NOT NULL,
    study_block_id TEXT,
    study_generation INTEGER,
    resource_key TEXT NOT NULL,
    identity_json TEXT NOT NULL CHECK (json_valid(identity_json)),
    observation_id TEXT NOT NULL,
    observation_sequence INTEGER NOT NULL CHECK (observation_sequence >= 0),
    observed_monotonic_ns INTEGER NOT NULL CHECK (observed_monotonic_ns >= 0),
    interval_id TEXT,
    request_id TEXT NOT NULL,
    confirmation_applied_monotonic_ns INTEGER,
    authority_json TEXT NOT NULL CHECK (json_valid(authority_json)),
    CHECK ((kind = 'OBSERVATION' AND request_id = ''
            AND confirmation_applied_monotonic_ns IS NULL)
        OR (kind = 'CONFIRMATION' AND interval_id IS NULL AND request_id != ''
            AND confirmation_applied_monotonic_ns >= observed_monotonic_ns)),
    CHECK ((study_block_id IS NULL AND study_generation IS NULL)
        OR (study_block_id IS NOT NULL AND study_generation IS NOT NULL AND study_generation > 0))
);"""


def _verify_study_observation_evidence_schema(connection, *, required=False):
    rows = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE tbl_name='study_resource_observation_evidence' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    if not rows and not required:
        return
    expected = [("table", "study_resource_observation_evidence", "study_resource_observation_evidence",
        _stored_correction_sql(_STUDY_OBSERVATION_EVIDENCE_SQL))]
    if [tuple(row) for row in rows] != expected:
        raise RuntimeError("Study observation evidence schema contract mismatch")
    if connection.execute("PRAGMA foreign_key_check(study_resource_observation_evidence)").fetchall():
        raise RuntimeError("Study observation evidence parent-session violation")


def install_correction4_schema(connection):
    """Explicit additive authority-evidence installation; no historical inference."""
    if not connection.in_transaction:
        raise RuntimeError("Correction-4 installation requires an active transaction")
    version = connection.execute("SELECT value FROM myelin_meta WHERE key='schema_version'").fetchone()
    if version is None or str(version[0]) != "8":
        raise RuntimeError("Correction-4 installation requires schema version 8")
    _verify_recorder_schema(connection)
    _verify_founding_source_schema(connection, required=True)
    _verify_study_boundary_schema(connection, required=True)
    _verify_study_interval_schema(connection, required=True)
    _verify_study_resources(connection)
    _verify_no_interfering_triggers(connection)
    connection.execute(_STUDY_OBSERVATION_EVIDENCE_SQL)
    _verify_study_observation_evidence_schema(connection, required=True)


def _stored_correction_sql(sql):
    # SQLite removes IF NOT EXISTS and the final semicolon in sqlite_master.
    # All remaining definition text must match; names alone grant no exception.
    return sql.replace(" IF NOT EXISTS", "", 1).rstrip(";")


def _verify_founding_source_schema(connection, *, required=False):
    rows = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE (tbl_name='secant_founding_source' OR name='myelin_schema_no_downgrade') "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
    if not rows and not required:
        return  # Pre-installation v8 remains readable; no implicit live migration.
    expected = [
        ("trigger", "myelin_schema_no_downgrade", "myelin_meta", _stored_correction_sql(_OWNERSHIP_GUARD_SQL)),
        ("table", "secant_founding_source", "secant_founding_source", _stored_correction_sql(_FOUNDING_SOURCE_SQL)),
    ]
    if [tuple(row) for row in rows] != expected:
        raise RuntimeError("Correction-1 ownership/source schema contract mismatch")
    if connection.execute("PRAGMA foreign_key_check(secant_founding_source)").fetchall():
        raise RuntimeError("Founding-source foreign-key violation")
    if connection.execute("SELECT 1 FROM secant_founding_source AS s JOIN secant_events AS e "
            "ON e.event_id=s.event_id WHERE e.event_name!='SECANT_EPISODE_FOUNDED' LIMIT 1").fetchone():
        raise RuntimeError("Founding source attached to a non-founding event")


def install_correction1_schema(connection):
    """Explicit migration inside the caller's backed-up, exclusive maintenance flow.

    Never commit here: guard and table must share the caller's transaction.
    This is not called by normal startup on an existing v8 database.
    """
    if not connection.in_transaction:
        raise RuntimeError("Correction-1 installation requires an active transaction")
    version = connection.execute("SELECT value FROM myelin_meta WHERE key='schema_version'").fetchone()
    if version is None or str(version[0]) != "8":
        raise RuntimeError("Correction-1 installation requires schema version 8")
    _verify_recorder_schema(connection)
    _verify_no_interfering_triggers(connection)
    connection.execute(_OWNERSHIP_GUARD_SQL)
    connection.execute(_FOUNDING_SOURCE_SQL)
    _verify_founding_source_schema(connection, required=True)
    _verify_no_interfering_triggers(connection)


def _verify_no_interfering_triggers(connection: sqlite3.Connection) -> None:
    from PERSISTENCE.presentation_aliases import TRIGGERS
    allowed = {("myelin_schema_no_downgrade", "myelin_meta",
                _stored_correction_sql(_OWNERSHIP_GUARD_SQL))}
    allowed.update((name, "presentation_aliases", sql) for name, sql in TRIGGERS.items())
    rows = connection.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='trigger'"
    ).fetchall()
    offenders = [
        str(row[0])
        for row in rows
        if tuple(row) not in allowed
    ]
    if offenders:
        raise RuntimeError(
            "Unexpected SQLite trigger(s) act on MYELIN tables: "
            + ", ".join(sorted(offenders))
        )


def _verify_required_tables(connection: sqlite3.Connection, *, require_aliases=True) -> None:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    present = {str(row[0]) for row in rows}
    required = MANAGED_TABLES if require_aliases else MANAGED_TABLES - {"presentation_aliases"}
    missing = sorted(required - present)
    if missing:
        raise RuntimeError("MYELIN schema is missing table(s): " + ", ".join(missing))
    check = connection.execute("PRAGMA quick_check").fetchone()
    if check is None or str(check[0]).casefold() != "ok":
        raise RuntimeError("SQLite quick_check did not return OK")


_STUDY_RESOURCE_SQL = "CREATE TABLE IF NOT EXISTS study_resources (\n    resource_fact_id TEXT NOT NULL PRIMARY KEY,\n    session_id INTEGER NOT NULL REFERENCES sessions(id),\n    study_block_id TEXT NOT NULL,\n    study_generation INTEGER NOT NULL CHECK (typeof(study_generation) = 'integer' AND study_generation > 0),\n    study_context_token TEXT NOT NULL,\n    resource_key TEXT NOT NULL,\n    identity_kind TEXT NOT NULL CHECK (identity_kind IN ('BROWSER', 'DESKTOP')),\n    identity_version INTEGER NOT NULL CHECK (identity_version = 1),\n    identity_json TEXT NOT NULL CHECK (json_valid(identity_json)),\n    role TEXT NOT NULL CHECK (role IN ('PRIMARY', 'LATER')),\n    first_aligned_monotonic_ns INTEGER NOT NULL CHECK (typeof(first_aligned_monotonic_ns) = 'integer' AND first_aligned_monotonic_ns >= 0),\n    qualified_monotonic_ns INTEGER NOT NULL CHECK (typeof(qualified_monotonic_ns) = 'integer' AND qualified_monotonic_ns >= first_aligned_monotonic_ns),\n    first_aligned_at_utc TEXT NOT NULL,\n    qualified_at_utc TEXT NOT NULL,\n    provenance_json TEXT NOT NULL CHECK (json_valid(provenance_json)),\n    contract_version INTEGER NOT NULL CHECK (contract_version = 1),\n    inserted_at_utc TEXT NOT NULL,\n    UNIQUE (session_id, study_block_id, study_generation, identity_kind, identity_version, resource_key)\n);\nCREATE UNIQUE INDEX IF NOT EXISTS study_resources_one_primary\n    ON study_resources(session_id, study_block_id, study_generation) WHERE role = 'PRIMARY';\n"


def _verify_study_resources(connection):
    import re
    actual = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='study_resources'").fetchone()
    expected = _STUDY_RESOURCE_SQL.split("CREATE UNIQUE INDEX")[0].strip().rstrip(";")
    normalize = lambda value: re.sub(r"\s+", "", value.lower().replace("if not exists", ""))
    if actual is None or normalize(actual[0]) != normalize(expected):
        raise RuntimeError("study_resources immutable schema contract mismatch")
    foreign = connection.execute("PRAGMA foreign_key_list(study_resources)").fetchall()
    if not any(row[2] == "sessions" and row[3] == "session_id" and row[4] == "id" for row in foreign):
        raise RuntimeError("study_resources parent FK missing")
    index = connection.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='study_resources_one_primary'").fetchone()
    expected_index = "CREATE UNIQUE INDEX" + _STUDY_RESOURCE_SQL.split("CREATE UNIQUE INDEX",1)[1]
    if index is None or normalize(index[0].rstrip(";")) != normalize(expected_index.strip().rstrip(";")):
        raise RuntimeError("study_resources PRIMARY uniqueness contract mismatch")
    if connection.execute("PRAGMA foreign_key_check(study_resources)").fetchall():
        raise RuntimeError("study_resources FK verification failed")




# Reviewed passive-observation contract. No native event backfill.
_RECORDER_SQL = "CREATE TABLE secant_events (\n    event_id TEXT NOT NULL PRIMARY KEY CHECK (length(event_id) = 64),\n    contract_version INTEGER NOT NULL CHECK (contract_version = 1),\n    session_id INTEGER NOT NULL REFERENCES sessions(id),\n    study_context_id TEXT NOT NULL CHECK (length(study_context_id) > 0),\n    study_target_resource_id TEXT NOT NULL,\n    episode_id TEXT NOT NULL CHECK (length(episode_id) > 0),\n    fact_digest TEXT NOT NULL CHECK (length(fact_digest) = 64),\n    occurrence_ordinal INTEGER NOT NULL CHECK (\n        typeof(occurrence_ordinal) = 'integer' AND occurrence_ordinal > 0),\n    event_name TEXT NOT NULL CHECK (event_name IN (\n        'SECANT_EPISODE_FOUNDED', 'SECANT_DISPLAYED',\n        'SECANT_ACTION_INTENT', 'SECANT_FROZEN', 'SECANT_RESUMED',\n        'SECANT_RETURN_STARTED', 'SECANT_RETURN_VERIFIED',\n        'SECANT_RECOVERY_CLOSED', 'SECANT_RECOVERY_INTERRUPTED',\n        'SECANT_EPISODE_CLOSED')),\n    stage INTEGER NOT NULL CHECK (typeof(stage) = 'integer' AND stage BETWEEN 0 AND 3),\n    occurred_monotonic_ns INTEGER NOT NULL CHECK (\n        typeof(occurred_monotonic_ns) = 'integer' AND occurred_monotonic_ns >= 0),\n    request_id TEXT NOT NULL,\n    attempt_id TEXT NOT NULL,\n    evidence_id TEXT NOT NULL,\n    reason TEXT NOT NULL,\n    canonical_fact_json TEXT NOT NULL CHECK (json_valid(canonical_fact_json)),\n    recorder_run_id TEXT NOT NULL CHECK (length(recorder_run_id) > 0),\n    recorder_received_monotonic_ns INTEGER NOT NULL CHECK (\n        typeof(recorder_received_monotonic_ns) = 'integer'\n        AND recorder_received_monotonic_ns >= 0),\n    recorder_received_at_utc TEXT NOT NULL,\n    recording_quality TEXT NOT NULL CHECK (recording_quality IN (\n        'BOUNDED_OBSERVATION', 'RECORDING_GAP_DETECTED')),\n    recorded_at_utc TEXT NOT NULL,\n    UNIQUE (session_id, study_context_id, episode_id,\n            fact_digest, occurrence_ordinal),\n    CHECK (event_name != 'SECANT_DISPLAYED' OR stage BETWEEN 1 AND 3),\n    CHECK (event_name != 'SECANT_ACTION_INTENT' OR reason = 'RETURN TO STUDY'),\n    CHECK (event_name NOT IN ('SECANT_FROZEN', 'SECANT_RESUMED')\n           OR reason = 'uncertainty')\n);\nCREATE INDEX ix_secant_events_session_episode_time\n    ON secant_events(session_id, study_context_id, episode_id,\n                     occurred_monotonic_ns, event_id);\nCREATE TABLE study_resource_events (\n    event_id TEXT NOT NULL PRIMARY KEY CHECK (length(event_id) = 64),\n    contract_version INTEGER NOT NULL CHECK (contract_version = 1),\n    session_id INTEGER NOT NULL REFERENCES sessions(id),\n    recorder_run_id TEXT NOT NULL CHECK (length(recorder_run_id) > 0),\n    observation_ordinal INTEGER NOT NULL CHECK (\n        typeof(observation_ordinal) = 'integer' AND observation_ordinal > 0),\n    event_kind TEXT NOT NULL CHECK (event_kind IN (\n        'RESOURCE_STATE_FIRST_OBSERVED', 'RESOURCE_STATE_CHANGE_OBSERVED')),\n    study_context_token TEXT NOT NULL CHECK (length(study_context_token) > 0),\n    study_block_id TEXT,\n    study_generation INTEGER,\n    resource_key TEXT NOT NULL CHECK (length(resource_key) > 0),\n    display_title TEXT NOT NULL,\n    process_name TEXT NOT NULL,\n    resource_surface TEXT NOT NULL,\n    study_app_category TEXT NOT NULL,\n    classification TEXT NOT NULL,\n    measured_classification TEXT NOT NULL,\n    effective_operational_state TEXT NOT NULL,\n    confidence REAL NOT NULL CHECK (\n        typeof(confidence) IN ('integer', 'real') AND confidence BETWEEN 0 AND 1),\n    measured_confidence REAL NOT NULL CHECK (\n        typeof(measured_confidence) IN ('integer', 'real')\n        AND measured_confidence BETWEEN 0 AND 1),\n    user_confirmation TEXT NOT NULL,\n    state_digest TEXT NOT NULL CHECK (length(state_digest) = 64),\n    canonical_state_json TEXT NOT NULL CHECK (json_valid(canonical_state_json)),\n    source_lane TEXT NOT NULL CHECK (source_lane IN (\n        'CONTROL_VIEW', 'RESOURCE_INTENT_LIVE_VIEW')),\n    timestamp_basis TEXT NOT NULL CHECK (timestamp_basis IN (\n        'COHERENT_FOREGROUND_OBSERVATION', 'RECORDER_RECEIPT')),\n    source_observation_sequence INTEGER,\n    source_observed_monotonic_ns INTEGER,\n    source_observed_at_utc TEXT,\n    recorder_received_monotonic_ns INTEGER NOT NULL CHECK (\n        typeof(recorder_received_monotonic_ns) = 'integer'\n        AND recorder_received_monotonic_ns >= 0),\n    recorder_received_at_utc TEXT NOT NULL,\n    provenance_json TEXT NOT NULL CHECK (json_valid(provenance_json)),\n    recording_quality TEXT NOT NULL CHECK (recording_quality IN (\n        'BOUNDED_OBSERVATION', 'RECORDING_GAP_DETECTED')),\n    recorded_at_utc TEXT NOT NULL,\n    UNIQUE (recorder_run_id, session_id, observation_ordinal),\n    CHECK ((study_block_id IS NULL AND study_generation IS NULL) OR\n           (study_block_id IS NOT NULL AND length(study_block_id) > 0\n            AND study_generation IS NOT NULL\n            AND typeof(study_generation) = 'integer' AND study_generation > 0)),\n    CHECK (\n        (timestamp_basis = 'RECORDER_RECEIPT'\n         AND source_observation_sequence IS NULL\n         AND source_observed_monotonic_ns IS NULL\n         AND source_observed_at_utc IS NULL)\n        OR\n        (timestamp_basis = 'COHERENT_FOREGROUND_OBSERVATION'\n         AND source_lane = 'CONTROL_VIEW'\n         AND source_observation_sequence IS NOT NULL\n         AND typeof(source_observation_sequence) = 'integer'\n         AND source_observation_sequence > 0\n         AND source_observed_monotonic_ns IS NOT NULL\n         AND typeof(source_observed_monotonic_ns) = 'integer'\n         AND source_observed_monotonic_ns >= 0\n         AND source_observed_at_utc IS NOT NULL\n         AND length(source_observed_at_utc) > 0)\n    )\n);\nCREATE INDEX ix_study_resource_events_scope_order\n    ON study_resource_events(session_id, study_context_token,\n                             recorder_run_id, observation_ordinal);\nCREATE INDEX ix_study_resource_events_resource\n    ON study_resource_events(session_id, study_context_token, resource_key);"
_RECORDER_TABLES = frozenset({"secant_events", "study_resource_events"})


def _execute_recorder_schema(connection):
    # execute, not executescript: preserve the caller's migration transaction.
    for statement in _RECORDER_SQL.split(";"):
        if statement.strip():
            connection.execute(statement)


def _verify_recorder_schema(connection):
    # Compare exact installed SQL (including CHECK/UNIQUE/FK contracts) with
    # SQLite's own normalized representation of the reviewed DDL.
    expected = sqlite3.connect(":memory:")
    try:
        expected.executescript(_RECORDER_SQL)
        wanted = expected.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        actual = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE tbl_name IN ('secant_events','study_resource_events') AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        if [tuple(row) for row in actual] != [tuple(row) for row in wanted]:
            raise RuntimeError("Passive recorder v8 schema contract mismatch")
        for table in _RECORDER_TABLES:
            for pragma in ("table_info", "foreign_key_list", "index_list"):
                a = [tuple(row) for row in connection.execute(f"PRAGMA {pragma}({table})")]
                b = [tuple(row) for row in expected.execute(f"PRAGMA {pragma}({table})")]
                if a != b:
                    raise RuntimeError("Passive recorder structural contract mismatch: " + table)
            if connection.execute(f"PRAGMA foreign_key_check({table})").fetchall():
                raise RuntimeError("Passive recorder foreign-key violation")
    finally:
        expected.close()


def install_presentation_alias_schema(connection: sqlite3.Connection) -> None:
    """Approved additive v8→v9 migration in the caller's writer transaction.

    Only a complete Phase-1 v8 database is eligible. Existing fact tables and
    their rows remain untouched. Seed once, then advance the ownership version.
    """
    from PERSISTENCE.presentation_aliases import (
        install_table, seed_foundings, corpus_foundings, verify_schema, verify_coverage)
    if not connection.in_transaction:
        raise RuntimeError("Alias migration requires an active writer transaction")
    row = connection.execute("SELECT value FROM myelin_meta WHERE key='schema_version'").fetchone()
    if row is None or str(row[0]) != "8":
        raise RuntimeError("Alias migration requires schema version 8")
    _verify_recorder_schema(connection)
    _verify_founding_source_schema(connection, required=True)
    _verify_study_boundary_schema(connection, required=True)
    _verify_study_interval_schema(connection, required=True)
    _verify_study_observation_evidence_schema(connection, required=True)
    _verify_no_interfering_triggers(connection)
    install_table(connection)
    seed_foundings(connection, corpus_foundings(connection))
    verify_schema(connection)
    verify_coverage(connection)
    connection.execute("UPDATE myelin_meta SET value='9' WHERE key='schema_version'")
    _verify_no_interfering_triggers(connection)


def ensure_production_schema() -> None:
    """Install and verify the one production schema before runtime starts."""

    connection = connect_database(read_only=False)
    try:
        # Keep additive schema installation, verification, and the schema-version
        # advance in one transaction.  A malformed pre-existing table or an
        # interfering trigger must fail visibly without falsely marking the
        # database as upgraded.
        has_meta = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='myelin_meta'").fetchone()
        row = connection.execute("SELECT value FROM myelin_meta WHERE key='schema_version'").fetchone() if has_meta else None
        version = int(row[0]) if row else 0
        if version > SCHEMA_VERSION:
            raise RuntimeError("Refusing to downgrade a newer schema")
        if version >= 6:
            connection.execute("BEGIN IMMEDIATE")
            if version == 6:
                for statement in _STUDY_RESOURCE_SQL.split(";"):
                    if statement.strip():
                        connection.execute(statement)
            _verify_study_resources(connection)
            if version < 8:
                # Existing names fail instead of masking an unfinished migration.
                _execute_recorder_schema(connection)
            _verify_recorder_schema(connection)
            _verify_required_tables(connection, require_aliases=version >= 9)
            _verify_no_interfering_triggers(connection)
            _verify_founding_source_schema(connection)
            _verify_study_boundary_schema(connection)
            _verify_study_interval_schema(connection)
            _verify_study_observation_evidence_schema(connection)
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Foreign-key check failed during v8 migration")
            if version < 8:
                connection.execute("UPDATE myelin_meta SET value='8' WHERE key='schema_version'")
            if version < 9:
                install_presentation_alias_schema(connection)
            from PERSISTENCE.presentation_aliases import verify_schema, verify_coverage
            verify_schema(connection)
            verify_coverage(connection)
            connection.commit()
            return
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA_SQL + _STUDY_RESOURCE_SQL)
        _execute_recorder_schema(connection)
        _verify_recorder_schema(connection)
        _verify_study_resources(connection)
        _verify_required_tables(connection, require_aliases=False)
        _migrate_cosine_parent_session(connection)
        _verify_cosine_events(connection)
        _verify_mine_events(connection)
        _verify_science_lab_experiments(connection)
        _migrate_profile_learning_state_return_latency(connection)
        _verify_profile_learning_state(connection)
        _verify_pie_session_time(connection)
        _verify_no_interfering_triggers(connection)
        connection.execute(
            "INSERT INTO myelin_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("8",),
        )
        install_correction1_schema(connection)
        install_correction2_schema(connection)
        install_correction3_schema(connection)
        install_correction4_schema(connection)
        install_presentation_alias_schema(connection)
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


__all__ = ["MANAGED_TABLES", "SCHEMA_VERSION", "ensure_production_schema"]
