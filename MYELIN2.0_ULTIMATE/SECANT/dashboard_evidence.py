"""Read-only, transaction-consistent evidence input for the dashboard adapter.

No persistence imports, schema initialization, runtime objects, or Qt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping
import sqlite3
from datetime import date
import re
import json


def freeze(value):
    """Detach and recursively freeze read-side values, including nested JSON."""
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(v) for v in value)
    return value


TABLES = (
    'sessions', 'secant_events', 'secant_founding_source', 'study_events',
    'study_resource_events', 'study_resources', 'study_resource_boundaries',
    'study_resource_intervals', 'study_resource_observation_evidence',
    'cosecant_events',
    'presentation_aliases',
)


@dataclass(frozen=True)
class EvidenceTable:
    rows: tuple[Mapping, ...]
    status: str  # AVAILABLE, NOT_RECORDED (legacy table absent), UNAVAILABLE
    diagnostic: str = ''

    def __post_init__(self):
        object.__setattr__(self, 'rows', freeze(self.rows))


@dataclass(frozen=True)
class EvidenceSnapshot:
    session_id: int
    tables: Mapping[str, EvidenceTable]
    recorder_receipts: EvidenceTable = field(default_factory=lambda: EvidenceTable((), 'NOT_RECORDED'))

    def __post_init__(self):
        object.__setattr__(self, 'tables', freeze(self.tables))

    def rows(self, table: str) -> tuple[Mapping, ...]:
        return self.tables[table].rows


@dataclass(frozen=True)
class ParentSessionScope:
    """One immutable parent and its transaction-consistent durable evidence."""
    session_id: int
    selection_kind: str
    selection_identity: tuple
    snapshot: EvidenceSnapshot


def resolve_scope(corpus, *, session_id=None, secant_identity=None, study_identity=None):
    """Resolve structured identities against fresh authority; never fall back on a stale selection."""
    if sum(v is not None for v in (session_id, secant_identity, study_identity)) > 1:
        raise ValueError('Select exactly one scope authority')
    kind, identity = 'PARENT', ()
    if secant_identity is not None or study_identity is not None:
        kind = 'SECANT' if secant_identity is not None else 'STUDY'
        identity = secant_identity if kind == 'SECANT' else study_identity
        if not isinstance(identity, tuple) or len(identity) != 3:
            raise ValueError('Structured child identity required')
        session_id = identity[0]
        if type(identity[1]) is not str or not identity[1]:
            raise ValueError('Invalid child identity')
        if kind == 'SECANT' and (type(identity[2]) is not str or not identity[2]):
            raise ValueError('Invalid episode identity')
        if kind == 'STUDY' and (type(identity[2]) is not int or identity[2] <= 0):
            raise ValueError('Invalid Study generation')
    if session_id is None:
        if not corpus:
            raise ValueError('No data: no recorded parent session')
        session_id = max(s.session_id for s in corpus)
    if type(session_id) is not int or session_id <= 0:
        raise ValueError('Invalid parent identity')
    matches = [s for s in corpus if s.session_id == session_id]
    if len(matches) != 1:
        raise ValueError('Selected parent is not durably available')
    snapshot = matches[0]
    parents = snapshot.tables['sessions']
    if parents.status != 'AVAILABLE' or len(parents.rows) != 1 or parents.rows[0]['id'] != session_id:
        raise ValueError('Invalid parent authority')
    if kind == 'SECANT':
        table = snapshot.tables['secant_events']
        found = any((r['session_id'], r['study_context_id'], r['episode_id']) == identity for r in table.rows)
    elif kind == 'STUDY':
        table = snapshot.tables['study_events']
        found = any((r['session_id'], r['study_block_id'], json.loads(r['payload_json']).get('generation')) == identity for r in table.rows)
    else:
        table, found = parents, True
        identity = (session_id,)
    if table.status != 'AVAILABLE' or not found:
        raise ValueError('Stale or unavailable child selection')
    return ParentSessionScope(session_id, kind, identity, snapshot)


def _read_receipts(connection, available):
    if 'myelin_meta' not in available:
        return EvidenceTable((), 'NOT_RECORDED')
    try:
        rows = []
        for key, value in connection.execute("SELECT key,value FROM myelin_meta WHERE key LIKE 'passive_recorder:v1:run:%'"):
            receipt = json.loads(value)
            if not isinstance(receipt, dict) or key != 'passive_recorder:v1:run:' + str(receipt.get('run_id', '')):
                raise ValueError('Recorder receipt identity mismatch')
            sessions = receipt.get('attached_session_ids')
            if not isinstance(sessions, list) or any(type(s) is not int or s <= 0 for s in sessions):
                raise ValueError('Invalid recorder parent scope')
            rows.append(receipt)
        return EvidenceTable(tuple(rows), 'AVAILABLE')
    except (sqlite3.Error, ValueError, TypeError) as error:
        return EvidenceTable((), 'UNAVAILABLE', type(error).__name__)


def _scope_receipts(receipts, sid):
    return EvidenceTable(tuple(r for r in receipts.rows if sid in r['attached_session_ids']),
                         receipts.status, receipts.diagnostic)


def read_snapshot(database_path: str | Path, *, session_id: int) -> EvidenceSnapshot:
    """Read exactly one session in one SQLite snapshot without creating a DB.

    Missing tables are distinguished from read failures and empty result sets.
    The caller owns scope selection. No implicit 'latest session' substitution.
    """
    if type(session_id) is not int or session_id <= 0:
        raise ValueError('A positive explicit session_id is required')
    result = {}
    receipts = EvidenceTable((), 'UNAVAILABLE')
    connection = None
    try:
        uri = Path(database_path).resolve().as_uri() + '?mode=ro'
        connection = sqlite3.connect(uri, uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        available = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        receipts = _scope_receipts(_read_receipts(connection, available), session_id)
        for table in TABLES:
            if table not in available:
                result[table] = EvidenceTable((), 'NOT_RECORDED')
                continue
            parameters = (session_id,)
            if table == 'presentation_aliases':
                clauses = [f"(entity_kind='{kind}' AND native_id IN (SELECT {column} FROM {parent} WHERE session_id=?))"
                           for kind, column, parent in (('SECANT','episode_id','secant_events'), ('COSECANT','break_id','cosecant_events'))
                           if parent in available]
                query = 'SELECT * FROM presentation_aliases WHERE ' + (' OR '.join(clauses) or '0')
                parameters = (session_id,) * len(clauses)
            elif table == 'sessions':
                query = 'SELECT * FROM sessions WHERE id=?'
            elif table == 'secant_founding_source':
                if 'secant_events' not in available:
                    result[table] = EvidenceTable((), 'UNAVAILABLE', 'Missing SECANT parent table')
                    continue
                query = ('SELECT f.* FROM secant_founding_source f '
                         'JOIN secant_events e ON e.event_id=f.event_id WHERE e.session_id=?')
            else:
                query = f'SELECT * FROM {table} WHERE session_id=?'
            try:
                rows = tuple(MappingProxyType(dict(row)) for row in connection.execute(query, parameters))
                result[table] = EvidenceTable(rows, 'AVAILABLE')
            except sqlite3.Error as error:
                result[table] = EvidenceTable((), 'UNAVAILABLE', type(error).__name__)
        connection.rollback()  # End the read transaction; no writes were permitted.
    except (sqlite3.Error, OSError, ValueError) as error:
        result = {table: EvidenceTable((), 'UNAVAILABLE', type(error).__name__) for table in TABLES}
    finally:
        if connection is not None:
            connection.close()
    return EvidenceSnapshot(session_id, MappingProxyType(result), receipts)


def read_display_alias(snapshot: EvidenceSnapshot, entity_kind: str, native_id: str) -> str:
    """Return only a validated persisted alias; missing/invalid mappings fail closed.

    This validator never imports the allocator or creates a temporary alias.
    Native identity remains an internal lookup key.
    """
    table = snapshot.tables.get('presentation_aliases')
    if table is None or table.status != 'AVAILABLE' or entity_kind not in ('SECANT', 'COSECANT'):
        return 'Unavailable'
    rows = [row for row in table.rows if row.get('entity_kind') == entity_kind and row.get('native_id') == native_id]
    if len(rows) != 1:
        return 'Unavailable'
    row = rows[0]
    try:
        ordinal = row['daily_ordinal']
        if row['alias_version'] != 1 or type(ordinal) is not int or ordinal < 1:
            return 'Unavailable'
        day = date.fromisoformat(row['founding_utc_date'])
        alias = row['display_alias']
        match = re.fullmatch(r'(SEC|COSEC)-(\d{8})-(\d{2,})', alias)
        if (not match or match[1] != ('SEC' if entity_kind == 'SECANT' else 'COSEC')
                or match[2] != day.strftime('%d%m%Y') or match[3] != f'{ordinal:02d}'):
            return 'Unavailable'
        return alias
    except (KeyError, TypeError, ValueError):
        return 'Unavailable'


def read_corpus(database_path: str | Path, *, row_limit: int = 250000) -> tuple[EvidenceSnapshot, ...]:
    """Read the historical corpus in one bounded, read-only transaction.

    Failed/oversized child reads are explicitly UNAVAILABLE; other sections
    remain usable. A failed parent population raises. Missing legacy tables
    retain NOT_RECORDED rather than becoming successful empty reads.
    """
    connection = sqlite3.connect(Path(database_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        available = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'sessions' not in available:
            raise ValueError('Session scope authority is missing')
        tables = {}
        receipts = _read_receipts(connection, available)
        for name in TABLES:
            try:
                rows = tuple(MappingProxyType(dict(r)) for r in connection.execute(
                    f'SELECT * FROM {name} LIMIT ?', (row_limit + 1,))) if name in available else ()
                if len(rows) > row_limit:
                    raise ValueError('Dashboard historical read limit exceeded')
                required = ({'id'} if name == 'sessions' else {'event_id'} if name == 'secant_founding_source'
                            else {'entity_kind','native_id'} if name == 'presentation_aliases'
                            else {'session_id'})
                if name == 'secant_events':
                    required |= {'event_id','episode_id'}
                if name == 'cosecant_events':
                    required |= {'break_id'}
                if any(not required.issubset(r) for r in rows):
                    raise ValueError('Missing durable scope columns')
                tables[name] = EvidenceTable(rows, 'AVAILABLE' if name in available else 'NOT_RECORDED')
            except (sqlite3.Error, ValueError) as error:
                if name == 'sessions':
                    raise
                tables[name] = EvidenceTable((), 'UNAVAILABLE', type(error).__name__)
        result = []
        for session in tables['sessions'].rows:
            sid = session['id']
            secant = [r for r in tables['secant_events'].rows if r['session_id'] == sid]
            cosecant = [r for r in tables['cosecant_events'].rows if r['session_id'] == sid]
            event_ids = {r['event_id'] for r in secant}
            aliases = {('SECANT', r['episode_id']) for r in secant} | {('COSECANT', r['break_id']) for r in cosecant}
            scoped = {}
            for name, table in tables.items():
                if name == 'sessions':
                    rows = (session,)
                elif name == 'secant_founding_source':
                    if tables['secant_events'].status == 'UNAVAILABLE':
                        scoped[name] = EvidenceTable((), 'UNAVAILABLE', 'SECANT parent unavailable')
                        continue
                    rows = tuple(r for r in table.rows if r['event_id'] in event_ids)
                elif name == 'presentation_aliases':
                    rows = tuple(r for r in table.rows if (r['entity_kind'], r['native_id']) in aliases)
                else:
                    rows = tuple(r for r in table.rows if r['session_id'] == sid)
                scoped[name] = EvidenceTable(rows, table.status)
            result.append(EvidenceSnapshot(sid, MappingProxyType(scoped), _scope_receipts(receipts, sid)))
        return tuple(sorted(result, key=lambda s: s.session_id))
    finally:
        connection.rollback()
        connection.close()
