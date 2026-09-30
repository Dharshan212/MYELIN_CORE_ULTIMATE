"""Read-only SECANT experiment adapter. Never creates evidence or commands an organ.

An ACTIVE recorder status cannot prove an empty queue: extraction may still be
pending outside that status. Only the existing durable final-flush receipt
certifies readiness. Until then this source is explicitly pending/unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sqlite3

from SECANT.dashboard_evidence import read_snapshot
from SECANT.dashboard_projection import project_secant, resource_title


@dataclass(frozen=True, slots=True)
class SecantFact:
    event_id: str
    name: str
    at_ns: int
    stage: int
    request_id: str
    attempt_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class SecantEpisodeRow:
    session_id: int
    context_id: str
    episode_id: str
    recorder_run_id: str
    display_alias: str
    source_status: str
    founding_source: str
    caption_status: str
    founding_caption: str
    events: tuple[SecantFact, ...]

    @property
    def opening_ns(self):
        return self.events[0].at_ns

    @property
    def closing_ns(self):
        return self.events[-1].at_ns

    @property
    def stage_reached(self):
        return max(e.stage for e in self.events if e.name == 'SECANT_DISPLAYED')

    @property
    def terminal_reason(self):
        return self.events[-1].reason


@dataclass(frozen=True, slots=True)
class SecantSource:
    session_id: int
    status: str
    reason: str
    episodes: tuple[SecantEpisodeRow, ...] = ()
    # All factual IDs, including excluded/incomplete episodes, for disclosure.
    fact_refs: tuple[tuple[str, int, str], ...] = ()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def recorder_readiness(statuses, run_ids=()):
    """Pure final-receipt gate; zero pending in an ACTIVE status is insufficient."""
    if not statuses:
        return 'UNAVAILABLE', 'PENDING / NOT_RECORDED: no final recorder readiness receipt'
    if any(type(s.get('run_id')) is not str or not s['run_id'] for s in statuses):
        return 'UNAVAILABLE', 'Missing recorder identity'
    if len({s.get('run_id') for s in statuses}) != len(statuses):
        return 'UNAVAILABLE', 'Ambiguous recorder status identity'
    if not set(run_ids).issubset({s.get('run_id') for s in statuses}):
        return 'UNAVAILABLE', 'Recorder clock-domain receipt missing'
    # A single session must not be stitched across recorder clock domains.
    if len(statuses) != 1:
        return 'UNAVAILABLE', 'Multiple recorder domains for one session'
    for status in statuses:
        if status.get('contract_version') != 1:
            return 'UNAVAILABLE', 'Unsupported recorder quality contract'
        if (status.get('coverage') != 'BOUNDED_OBSERVATION'
                or status.get('dropped') != 0 or status.get('gap_reasons')):
            return 'UNAVAILABLE', 'Recording loss / recorder gap; not a SECANT behavioural evidence_gap'
        if (status.get('writer_state') != 'CLOSED'
                or status.get('final_flush_committed') is not True
                or status.get('pending') != 0 or not status.get('closed_at_utc')):
            return 'UNAVAILABLE', 'PENDING: recorder final flush has not been committed'
    return 'AVAILABLE', 'Durable final recorder flush committed'


def read_secant_source(session_id: int, database_path=None) -> SecantSource:
    """Use existing final status then the dashboard's read-only snapshot authority.

    Closed recorder receipts are immutable finality fences. No writer, migration,
    schema initialization, alias allocator, or live runtime is opened here.
    """
    if database_path is None:
        from PERSISTENCE.database import database_path as get_path
        database_path = get_path(create_parent=False)
    try:
        with sqlite3.connect(Path(database_path).resolve().as_uri() + '?mode=ro', uri=True) as conn:
            conn.execute('PRAGMA query_only=ON')
            statuses = []
            for key, value in conn.execute("SELECT key,value FROM myelin_meta WHERE key LIKE 'passive_recorder:v1:run:%'"):
                status = json.loads(value)
                if session_id in status.get('attached_session_ids', ()):
                    if key != 'passive_recorder:v1:run:' + str(status.get('run_id', '')):
                        raise ValueError('Recorder identity mismatch')
                    statuses.append(status)
        status, reason = recorder_readiness(statuses)
        if status != 'AVAILABLE':
            return SecantSource(session_id, status, reason)
        snapshot = read_snapshot(database_path, session_id=session_id)
        return certify_source(snapshot, tuple(statuses))
    except (sqlite3.Error, OSError, ValueError, TypeError, KeyError) as error:
        return SecantSource(session_id, 'UNAVAILABLE', f'SECANT read unavailable: {type(error).__name__}')


def certify_source(snapshot, statuses) -> SecantSource:
    """Validate durable identities and complete lifecycles before window filtering."""
    sid = snapshot.session_id
    table = snapshot.tables.get('secant_events')
    if table is None or table.status != 'AVAILABLE':
        return SecantSource(sid, 'UNAVAILABLE', 'SECANT source NOT_RECORDED or unreadable')
    raw = snapshot.rows('secant_events')
    refs = tuple((r['event_id'], r['occurred_monotonic_ns'], r['event_name']) for r in raw
                 if isinstance(r.get('event_id'), str) and r['event_id']
                 and isinstance(r.get('event_name'), str) and r['event_name']
                 and type(r.get('occurred_monotonic_ns')) is int and r['occurred_monotonic_ns'] >= 0)
    status, reason = recorder_readiness(statuses, {r.get('recorder_run_id') for r in raw})
    if status != 'AVAILABLE':
        return SecantSource(sid, status, reason, fact_refs=refs)
    if any(sid not in receipt.get('attached_session_ids', ()) for receipt in statuses):
        return SecantSource(sid, 'UNAVAILABLE', 'Recorder receipt belongs to another session', fact_refs=refs)
    if not raw:
        return SecantSource(sid, 'NO_EVIDENCE', 'Finalized readable SECANT source has no recorded episodes')
    try:
        for r in raw:
            if r['recording_quality'] != 'BOUNDED_OBSERVATION':
                raise ValueError('Recording loss / recorder gap')
            fact = [1, r['session_id'], r['study_context_id'], r['study_target_resource_id'],
                    r['episode_id'], r['event_name'], r['stage'], r['occurred_monotonic_ns'],
                    r['request_id'], r['attempt_id'], r['evidence_id'], r['reason']]
            canonical = _canonical(fact)
            if (r['canonical_fact_json'] != canonical or r['fact_digest'] != _digest(canonical)
                    or r['event_id'] != _digest(_canonical(['secant-event-v1', fact, r['occurrence_ordinal']]))):
                raise ValueError('Durable SECANT identity/content mismatch')
            if not r['study_context_id'].startswith(str(sid) + ':'):
                raise ValueError('Study context belongs to another session')
        episodes = []
        for episode in project_secant(snapshot):
            if episode.status != 'AVAILABLE':
                raise ValueError(episode.diagnostic)
            if episode.founded is None or episode.closed is None:
                raise ValueError('INCOMPLETE: founding or episode closure missing; last event is not closure')
            if len({r['study_target_resource_id'] for r in episode.events}) != 1:
                raise ValueError('Study target changed inside native episode')
            facts = tuple(SecantFact(r['event_id'], r['event_name'], r['occurred_monotonic_ns'],
                                    r['stage'], r['request_id'], r['attempt_id'], r['reason'])
                          for r in episode.events)
            _validate_lifecycle(facts)
            source_status = episode.source_status
            source = episode.source
            if source_status == 'AVAILABLE':
                # The dashboard's lightweight source projection is not the
                # certification boundary. Revalidate the native observation.
                from SECANT.read_model import ExactResource, FoundingSourceEvidence
                try:
                    stored = next(r for r in snapshot.rows('secant_founding_source')
                                  if r['event_id'] == episode.founded['event_id'])
                    payload = json.loads(stored['source_evidence_json'])
                    core = dict(payload)
                    core.pop('display_metadata', None)
                    core['resource'] = ExactResource(**core['resource'])
                    founding = FoundingSourceEvidence(**core)
                    if (founding.meaning != 'OFF_TASK'
                            or founding.observed_monotonic_ns > episode.founded['occurred_monotonic_ns']
                            or not (founding.territory != 'ORDINARY' or founding.confirmed_off_task or founding.certified_ott)):
                        raise ValueError('Invalid founding observation')
                except (ValueError, TypeError, KeyError, StopIteration):
                    source_status, source = 'UNAVAILABLE', {}
            title = 'NOT_RECORDED'
            title_status = 'NOT_RECORDED'
            if source_status == 'AVAILABLE' and source.get('display_metadata') is not None:
                from SECANT.read_model import validate_display_metadata
                try:
                    metadata = validate_display_metadata(source['display_metadata'],
                        observation_id=source['display_observation_id'], observed_ns=source['display_observed_ns'])
                    if metadata is not None:
                        title = resource_title(source, source['display_metadata'],
                            observation_id=source['display_observation_id'], observed_ns=source['display_observed_ns'])
                        title_status = 'AVAILABLE'
                except (ValueError, TypeError, KeyError):
                    title_status, title = 'UNAVAILABLE', 'UNAVAILABLE: invalid recorded display metadata'
            episodes.append(SecantEpisodeRow(sid, episode.identity[1], episode.identity[2],
                episode.events[0]['recorder_run_id'], episode.display_episode_id,
                source_status, str(source.get('key', source_status)), title_status, title, facts))
        return SecantSource(sid, 'AVAILABLE', 'Complete durable SECANT lifecycles; window classification required', tuple(episodes), refs)
    except (ValueError, KeyError, TypeError) as error:
        return SecantSource(sid, 'UNAVAILABLE', str(error), fact_refs=refs)


def _validate_lifecycle(facts):
    if not facts or facts[0].name != 'SECANT_EPISODE_FOUNDED' or facts[-1].name != 'SECANT_EPISODE_CLOSED':
        raise ValueError('Invalid SECANT lifecycle boundaries')
    if any(b.at_ns < a.at_ns for a, b in zip(facts, facts[1:])):
        raise ValueError('Unordered SECANT chronology')
    displays = [f for f in facts if f.name == 'SECANT_DISPLAYED']
    if not displays or displays[0].stage != 1 or displays[0].at_ns != facts[0].at_ns:
        raise ValueError('Episode founding lacks factual SECANT-1 display')
    if displays[0].request_id != facts[0].request_id:
        raise ValueError('Founding/display request mismatch')
    stages = [f.stage for f in displays]
    if any(b < a or b > a + 1 for a, b in zip(stages, stages[1:])):
        raise ValueError('Invalid displayed-stage chronology')
    attempts = {}
    for f in facts:
        if f.name == 'SECANT_ACTION_INTENT' and f.reason != 'RETURN TO STUDY':
            raise ValueError('Unsupported return intent')
        if f.name == 'SECANT_RETURN_STARTED':
            if not f.attempt_id or f.attempt_id in attempts:
                raise ValueError('Invalid recovery attempt identity')
            attempts[f.attempt_id] = ('STARTED', f.at_ns)
        elif f.name in ('SECANT_RETURN_VERIFIED', 'SECANT_RECOVERY_CLOSED', 'SECANT_RECOVERY_INTERRUPTED'):
            phase, at = attempts.get(f.attempt_id, ('MISSING', -1))
            if phase not in ('STARTED', 'VERIFIED') or f.at_ns < at:
                raise ValueError('Recovery event lacks ordered attempt evidence')
            if f.name == 'SECANT_RETURN_VERIFIED':
                if phase != 'STARTED' or f.at_ns - at < 10_000_000_000:
                    raise ValueError('Verification lacks supported minimum chronology')
                attempts[f.attempt_id] = ('VERIFIED', f.at_ns)
            elif f.name == 'SECANT_RECOVERY_CLOSED':
                if phase != 'VERIFIED' or f.at_ns - at < 60_000_000_000:
                    raise ValueError('Recovery closure lacks confirmation chronology')
                attempts[f.attempt_id] = ('CLOSED', f.at_ns)
            else:
                attempts[f.attempt_id] = ('INTERRUPTED', f.at_ns)

    recovered = [f for f in facts if f.name == 'SECANT_RECOVERY_CLOSED']
    if facts[-1].reason == 'recovered':
        if len(recovered) != 1 or recovered[0].at_ns != facts[-1].at_ns:
            raise ValueError('Recovered terminal lacks factual recovery closure')
    elif recovered:
        raise ValueError('Recovery closure conflicts with terminal reason')


def classify(source, start_ns, end_ns):
    """Full episodes first, then half-open experiment membership. No clipping."""
    from .analysis import EvidenceRef, OrganExperimentScope
    if type(start_ns) is not int or type(end_ns) is not int or end_ns <= start_ns:
        raise ValueError('Invalid experiment window')
    if source is None:
        source = SecantSource(0, 'UNAVAILABLE', 'SECANT absent from legacy snapshot')
    refs = tuple(EvidenceRef('SECANT', identity, at, name) for identity, at, name in source.fact_refs if identity)
    if source.status != 'AVAILABLE':
        return (), OrganExperimentScope('SECANT', source.status, 0, 0, 0, source.reason, refs)
    contained, overlap, outside = [], 0, 0
    for episode in source.episodes:
        if start_ns <= episode.opening_ns and episode.closing_ns < end_ns:
            contained.append(episode)
        elif episode.closing_ns < start_ns or episode.opening_ns >= end_ns:
            outside += 1
        else:
            overlap += 1
    status = 'FULLY_CONTAINED' if contained else 'CROSS_BOUNDARY_OVERLAP' if overlap else 'OUTSIDE_WINDOW' if outside else 'NO_EVIDENCE'
    reason = f'{len(contained)} contained; {overlap} overlapping excluded; {outside} outside experiment'
    return tuple(contained), OrganExperimentScope('SECANT', status, len(contained), overlap, outside, reason, refs)


def validate_package_rows(rows, scope, session_id, start_ns, end_ns):
    """Fail closed at both certification and PDF boundaries."""
    if scope is None:
        if rows:
            raise ValueError('SECANT rows lack experiment scope')
        return
    if scope.source != 'SECANT' or scope.fully_contained_count != len(rows):
        raise ValueError('SECANT scope count mismatch')
    if rows and scope.status != 'FULLY_CONTAINED':
        raise ValueError('SECANT rows lack contained certification')
    identities = set()
    for row in rows:
        if not isinstance(row, SecantEpisodeRow) or row.session_id != session_id:
            raise ValueError('SECANT row session/type mismatch')
        _validate_lifecycle(row.events)
        if not start_ns <= row.opening_ns <= row.closing_ns < end_ns:
            raise ValueError('SECANT episode crosses experiment boundary')
        identity = (row.context_id, row.episode_id)
        if identity in identities:
            raise ValueError('Duplicate SECANT episode')
        identities.add(identity)
        expected = {(f.event_id, f.at_ns, f.name) for f in row.events}
        actual = {(ref.durable_id, ref.occurred_monotonic_ns, ref.event_kind)
                  for ref in scope.provenance if ref.source == 'SECANT'}
        if not expected.issubset(actual):
            raise ValueError('SECANT rows lost native provenance')
