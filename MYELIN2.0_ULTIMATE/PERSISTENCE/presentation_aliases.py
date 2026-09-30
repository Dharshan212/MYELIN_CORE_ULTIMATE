"""Write-once presentation identities allocated only by the persistence writer.

Callers hold a BEGIN IMMEDIATE transaction. No view or read projection imports
this allocator. Fact rows are never changed by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sqlite3

from time_projection import parse_utc_timestamp


TABLE_SQL = """CREATE TABLE presentation_aliases (
    entity_kind TEXT NOT NULL CHECK (entity_kind IN ('SECANT', 'COSECANT')),
    native_id TEXT NOT NULL CHECK (length(native_id) > 0),
    founding_utc_date TEXT NOT NULL CHECK (
        length(founding_utc_date) = 10 AND date(founding_utc_date) IS NOT NULL
        AND date(founding_utc_date) = founding_utc_date),
    daily_ordinal INTEGER NOT NULL CHECK (typeof(daily_ordinal) = 'integer' AND daily_ordinal > 0),
    display_alias TEXT NOT NULL UNIQUE,
    assigned_at_utc TEXT NOT NULL,
    alias_version INTEGER NOT NULL CHECK (alias_version = 1),
    founding_at_utc TEXT NOT NULL CHECK (substr(founding_at_utc, 1, 10) = founding_utc_date),
    founding_time_basis TEXT NOT NULL,
    founding_event_id TEXT NOT NULL CHECK (length(founding_event_id) > 0),
    PRIMARY KEY (entity_kind, native_id),
    UNIQUE (entity_kind, founding_utc_date, daily_ordinal),
    CHECK (display_alias =
        CASE entity_kind WHEN 'SECANT' THEN 'SEC-' ELSE 'COSEC-' END ||
        substr(founding_utc_date, 9, 2) || substr(founding_utc_date, 6, 2) ||
        substr(founding_utc_date, 1, 4) || '-' || printf('%02d', daily_ordinal))
)"""
TRIGGERS = {
    'presentation_aliases_no_update': """CREATE TRIGGER presentation_aliases_no_update
BEFORE UPDATE ON presentation_aliases
BEGIN
    SELECT RAISE(ABORT, 'Presentation aliases are immutable');
END""",
    'presentation_aliases_no_delete': """CREATE TRIGGER presentation_aliases_no_delete
BEFORE DELETE ON presentation_aliases
BEGIN
    SELECT RAISE(ABORT, 'Presentation aliases cannot be deleted');
END""",
    # REPLACE can implicitly delete without firing DELETE triggers when
    # recursive_triggers is OFF. Reject all replacement conflicts up front.
    'presentation_aliases_no_replace': """CREATE TRIGGER presentation_aliases_no_replace
BEFORE INSERT ON presentation_aliases
WHEN EXISTS (SELECT 1 FROM presentation_aliases
    WHERE (entity_kind = NEW.entity_kind AND native_id = NEW.native_id)
       OR display_alias = NEW.display_alias
       OR (entity_kind = NEW.entity_kind AND founding_utc_date = NEW.founding_utc_date
           AND daily_ordinal = NEW.daily_ordinal))
BEGIN
    SELECT RAISE(ABORT, 'Presentation alias reassignment prohibited');
END""",
}


@dataclass(frozen=True)
class Founding:
    entity_kind: str
    native_id: str
    at_utc: str
    time_basis: str
    event_id: str


def install_table(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        raise RuntimeError('Alias installation requires the migration transaction')
    connection.execute(TABLE_SQL)
    for sql in TRIGGERS.values():
        connection.execute(sql)


def verify_schema(connection: sqlite3.Connection) -> None:
    wanted = [('table', 'presentation_aliases', 'presentation_aliases', TABLE_SQL)]
    wanted += [('trigger', name, 'presentation_aliases', sql) for name, sql in TRIGGERS.items()]
    actual = [tuple(row) for row in connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE tbl_name='presentation_aliases' AND name NOT LIKE 'sqlite_%'")]
    if sorted(actual) != sorted(wanted):
        raise RuntimeError('Presentation alias schema contract mismatch')


def assign_alias(connection: sqlite3.Connection, founding: Founding) -> str:
    """Return an existing immutable alias, or allocate MAX+1 under the writer lock."""
    if not connection.in_transaction:
        raise RuntimeError('Alias allocation requires a writer transaction')
    if (founding.entity_kind not in ('SECANT', 'COSECANT')
            or not founding.native_id or not founding.event_id or not founding.time_basis):
        raise ValueError('Complete authoritative founding identity required')
    instant = parse_utc_timestamp(founding.at_utc)
    canonical = instant.isoformat(timespec='microseconds').replace('+00:00', 'Z')
    date = instant.date().isoformat()
    existing = connection.execute(
        'SELECT display_alias,founding_utc_date FROM presentation_aliases WHERE entity_kind=? AND native_id=?',
        (founding.entity_kind, founding.native_id)).fetchone()
    if existing is not None:
        if existing[1] != date:
            raise ValueError('Founding date conflicts with permanent alias; reassignment prohibited')
        return existing[0]
    ordinal = connection.execute(
        'SELECT COALESCE(MAX(daily_ordinal),0)+1 FROM presentation_aliases WHERE entity_kind=? AND founding_utc_date=?',
        (founding.entity_kind, date)).fetchone()[0]
    prefix = 'SEC' if founding.entity_kind == 'SECANT' else 'COSEC'
    alias = f'{prefix}-{instant:%d%m%Y}-{ordinal:02d}'
    assigned = datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    connection.execute('INSERT INTO presentation_aliases('
        'entity_kind,native_id,founding_utc_date,daily_ordinal,display_alias,assigned_at_utc,'
        'alias_version,founding_at_utc,founding_time_basis,founding_event_id) VALUES(?,?,?,?,?,?,1,?,?,?)',
        (founding.entity_kind, founding.native_id, date, ordinal, alias, assigned,
         canonical, founding.time_basis, founding.event_id))
    return alias


def seed_foundings(connection: sqlite3.Connection, foundings) -> None:
    """Initial corpus is chronological once. Existing mappings are never ranked again."""
    for founding in sorted(foundings, key=lambda f: (
            f.entity_kind, parse_utc_timestamp(f.at_utc), f.native_id, f.event_id)):
        assign_alias(connection, founding)


def secant_founding(row) -> Founding:
    """Approved UTC reconstruction from the founding record's own paired clocks.

    Receipt UTC is an anchor, never a substitute founding date. Round the
    reconstructed instant down to a microsecond, retaining the correct date
    even when a sub-microsecond subtraction crosses UTC midnight.
    """
    if row['event_name'] != 'SECANT_EPISODE_FOUNDED' or row['contract_version'] != 1:
        raise ValueError('Authoritative SECANT founding record required')
    occurred, received = row['occurred_monotonic_ns'], row['recorder_received_monotonic_ns']
    if (type(occurred) is not int or type(received) is not int
            or not 0 <= occurred <= received or not row['recorder_run_id']):
        raise ValueError('Invalid SECANT founding clock pair')
    instant = parse_utc_timestamp(row['recorder_received_at_utc']) - timedelta(
        microseconds=(received - occurred + 999) // 1000)
    return Founding('SECANT', row['episode_id'],
        instant.isoformat(timespec='microseconds').replace('+00:00', 'Z'),
        'FOUNDING_RECORD_PAIRED_CLOCKS_V1', row['event_id'])


def cosecant_founding(row) -> Founding:
    payload = json.loads(row['payload_json'])
    if (row['kind'] != 'BREAK_STARTED' or payload.get('kind') != 'BREAK_STARTED'
            or payload.get('break_id') != row['break_id']):
        raise ValueError('Authoritative COSECANT start record required')
    instant = parse_utc_timestamp(payload.get('occurred_wall_time_utc'))
    return Founding('COSECANT', row['break_id'],
        instant.isoformat(timespec='microseconds').replace('+00:00', 'Z'),
        'BREAK_STARTED_WALL_UTC_V1', str(row['id']))


def corpus_foundings(connection: sqlite3.Connection) -> tuple[Founding, ...]:
    def dict_rows(query):
        cursor = connection.execute(query)
        names = tuple(column[0] for column in cursor.description)
        return (dict(zip(names, row)) for row in cursor)
    return tuple(secant_founding(row) for row in dict_rows(
        "SELECT * FROM secant_events WHERE event_name='SECANT_EPISODE_FOUNDED'")) + tuple(
        cosecant_founding(row) for row in dict_rows(
        "SELECT * FROM cosecant_events WHERE kind='BREAK_STARTED'"))


def assign_secant_event(connection: sqlite3.Connection, event_id: str) -> str:
    cursor = connection.execute('SELECT * FROM secant_events WHERE event_id=?', (event_id,))
    row = cursor.fetchone()
    if row is None:
        raise ValueError('SECANT founding event is not durable in this transaction')
    return assign_alias(connection, secant_founding(dict(zip((c[0] for c in cursor.description), row))))


def assign_cosecant_event(connection: sqlite3.Connection, event_id: int) -> str:
    cursor = connection.execute('SELECT * FROM cosecant_events WHERE id=?', (event_id,))
    row = cursor.fetchone()
    if row is None:
        raise ValueError('COSECANT start is not durable in this transaction')
    return assign_alias(connection, cosecant_founding(dict(zip((c[0] for c in cursor.description), row))))


def verify_coverage(connection: sqlite3.Connection) -> None:
    """Read-only startup/maintenance integrity check; never repairs missing aliases."""
    expected = {(f.entity_kind, f.native_id): f for f in corpus_foundings(connection)}
    rows = connection.execute('SELECT entity_kind,native_id,founding_utc_date,display_alias,'
        'daily_ordinal,alias_version FROM presentation_aliases').fetchall()
    actual = {(r[0],r[1]) for r in rows}
    if actual != expected.keys():
        raise RuntimeError('Missing or orphaned durable presentation aliases')
    for kind, native, date, alias, ordinal, version in rows:
        founded = parse_utc_timestamp(expected[(kind,native)].at_utc)
        prefix = 'SEC' if kind == 'SECANT' else 'COSEC'
        if (date != founded.date().isoformat() or version != 1
                or alias != f'{prefix}-{founded:%d%m%Y}-{ordinal:02d}'):
            raise RuntimeError('Durable alias evidence mismatch')
