"""Single production SQLite schema authority for MYELIN 2.0."""

from __future__ import annotations

import sqlite3
from typing import Final

from PERSISTENCE.database import connect_database


SCHEMA_VERSION: Final = 4
MANAGED_TABLES: Final = frozenset(
    {
        "myelin_meta",
        "sessions",
        "triggers",
        "sine_facts",
        "normal_break_events",
        "mirl_events",
        "cosine_events",
        "mine_events",
        "study_events",
        "cosecant_events",
        "notes",
        "planner_blocks",
        "emergency_events",
        "emergency_followup",
        "profile_learning_state",
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


def _verify_no_interfering_triggers(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='trigger'"
    ).fetchall()
    offenders = [
        str(row[0])
        for row in rows
        if str(row[1]) in MANAGED_TABLES
    ]
    if offenders:
        raise RuntimeError(
            "Unexpected SQLite trigger(s) act on MYELIN tables: "
            + ", ".join(sorted(offenders))
        )


def _verify_required_tables(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    present = {str(row[0]) for row in rows}
    missing = sorted(MANAGED_TABLES - present)
    if missing:
        raise RuntimeError("MYELIN schema is missing table(s): " + ", ".join(missing))
    check = connection.execute("PRAGMA quick_check").fetchone()
    if check is None or str(check[0]).casefold() != "ok":
        raise RuntimeError("SQLite quick_check did not return OK")


def ensure_production_schema() -> None:
    """Install and verify the one production schema before runtime starts."""

    connection = connect_database(read_only=False)
    try:
        # Keep additive schema installation, verification, and the schema-version
        # advance in one transaction.  A malformed pre-existing table or an
        # interfering trigger must fail visibly without falsely marking the
        # database as upgraded.
        connection.executescript("BEGIN IMMEDIATE;\n" + _SCHEMA_SQL)
        _verify_required_tables(connection)
        _migrate_cosine_parent_session(connection)
        _verify_cosine_events(connection)
        _verify_mine_events(connection)
        _migrate_profile_learning_state_return_latency(connection)
        _verify_profile_learning_state(connection)
        _verify_no_interfering_triggers(connection)
        connection.execute(
            "INSERT INTO myelin_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


__all__ = ["MANAGED_TABLES", "SCHEMA_VERSION", "ensure_production_schema"]
