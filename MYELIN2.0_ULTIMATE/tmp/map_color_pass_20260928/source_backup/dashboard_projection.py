"""Pure durable SECANT facts. No UI, live engine, SQL, or display-ID policy."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
import json

from .dashboard_evidence import EvidenceSnapshot, read_display_alias
from time_projection import parse_utc_timestamp
import math


EVENT_ORDER = {
    'SECANT_EPISODE_FOUNDED': 0, 'SECANT_DISPLAYED': 1,
    'SECANT_ACTION_INTENT': 2, 'SECANT_FROZEN': 3, 'SECANT_RESUMED': 4,
    'SECANT_RETURN_STARTED': 5, 'SECANT_RETURN_VERIFIED': 6,
    'SECANT_RECOVERY_INTERRUPTED': 7, 'SECANT_RECOVERY_CLOSED': 8,
    'SECANT_EPISODE_CLOSED': 9,
}


@dataclass(frozen=True)
class SecantEpisodeFacts:
    identity: tuple[int, str, str]
    events: tuple[Mapping, ...]
    status: str
    diagnostic: str
    source_status: str
    source: Mapping
    stage_reached: int | None
    founded: Mapping | None
    closed: Mapping | None
    display_episode_id: str = 'Unavailable'

    def named(self, event_name: str) -> tuple[Mapping, ...]:
        return tuple(row for row in self.events if row['event_name'] == event_name)


def _source(founded: Mapping | None, snapshot: EvidenceSnapshot) -> tuple[str, Mapping]:
    table = snapshot.tables['secant_founding_source']
    empty = MappingProxyType({})
    if table.status == 'UNAVAILABLE':
        return 'UNAVAILABLE', empty
    if founded is None:
        return 'NOT_RECORDED', empty
    matches = [row for row in table.rows if row['event_id'] == founded['event_id']]
    if not matches:
        return 'NOT_RECORDED', empty
    if len(matches) != 1:
        return 'UNAVAILABLE', empty
    row = matches[0]
    try:
        payload = json.loads(row['source_evidence_json'])
        resource = payload['resource']
        if (row['source_extension_version'] != 1
                or resource['key'] != row['source_resource_id']
                or payload['evidence_id'] != row['source_evidence_id']
                or payload['observed_monotonic_ns'] != row['source_observed_monotonic_ns']
                or resource['version'] != 1
                or resource['kind'] not in ('BROWSER', 'DESKTOP')):
            raise ValueError('Source authority mismatch')
        return 'AVAILABLE', MappingProxyType(resource)
    except (KeyError, ValueError, TypeError):
        return 'UNAVAILABLE', empty


def project_secant(snapshot: EvidenceSnapshot) -> tuple[SecantEpisodeFacts, ...]:
    """Group exact native identities and validate each episode before display.

    No source is inferred from later samples. Multiple recorder clock domains
    are flagged rather than sorted as one comparable monotonic timeline.
    """
    groups = {}
    for row in snapshot.rows('secant_events'):
        key = (row['session_id'], row['study_context_id'], row['episode_id'])
        groups.setdefault(key, []).append(row)
    result = []
    for key, rows in sorted(groups.items()):
        status, diagnostic = 'AVAILABLE', ''
        founded, closed, stage = None, None, None
        events = tuple(rows)
        try:
            if key[0] != snapshot.session_id or not key[1] or not key[2]:
                raise ValueError('Episode scope mismatch')
            if len({r['event_id'] for r in rows}) != len(rows):
                raise ValueError('Duplicate durable event identity')
            if len({r['recorder_run_id'] for r in rows}) != 1:
                raise ValueError('Multiple recorder clock domains')
            for row in rows:
                if row['contract_version'] != 1 or row['event_name'] not in EVENT_ORDER:
                    raise ValueError('Unsupported SECANT event contract')
                if type(row['occurred_monotonic_ns']) is not int or row['occurred_monotonic_ns'] < 0:
                    raise ValueError('Invalid occurrence clock')
                if type(row['stage']) is not int or not 0 <= row['stage'] <= 3:
                    raise ValueError('Invalid recorded stage')
                parse_utc_timestamp(row['recorded_at_utc'])
            events = tuple(sorted(rows, key=lambda r: (
                r['occurred_monotonic_ns'], EVENT_ORDER[r['event_name']],
                r['occurrence_ordinal'], r['event_id'])))
            foundings = [r for r in events if r['event_name'] == 'SECANT_EPISODE_FOUNDED']
            closures = [r for r in events if r['event_name'] == 'SECANT_EPISODE_CLOSED']
            if len(foundings) > 1 or len(closures) > 1:
                raise ValueError('Ambiguous episode lifecycle')
            founded = foundings[0] if foundings else None
            closed = closures[0] if closures else None
            displayed = [r['stage'] for r in events if r['event_name'] == 'SECANT_DISPLAYED']
            if any(value == 0 for value in displayed):
                raise ValueError('Displayed stage is invalid')
            stage = max(displayed) if displayed else None
            if founded and events[0]['occurred_monotonic_ns'] < founded['occurred_monotonic_ns']:
                raise ValueError('Event predates episode founding')
        except (KeyError, ValueError, TypeError) as error:
            status, diagnostic = 'UNAVAILABLE', str(error)
        source_status, source = _source(founded, snapshot)
        result.append(SecantEpisodeFacts(key, events, status, diagnostic,
                                        source_status, source, stage, founded, closed,
                                        read_display_alias(snapshot, 'SECANT', key[2])))
    return tuple(result)


def _scope(row: Mapping) -> tuple:
    return tuple(row.get(k) for k in ('session_id', 'study_block_id', 'study_generation', 'study_context_token'))


def _object(value: str) -> dict:
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError('Expected evidence object')
    return result


def resource_title(identity: Mapping) -> str:
    """Use only this authority's own title, never a cross-stream title lookup."""
    return str(identity.get('normalized_title') or 'Title not recorded')


def project_study(snapshot: EvidenceSnapshot) -> dict:
    """Project timer snapshots and individual foreground visits without gap filling.

    Internal keys remain separate from display values. Incomplete or malformed
    evidence fails closed; successful empty input remains distinct from absence.
    """
    result = dict(status='AVAILABLE', blocks=[], resources=[], visits=[], jumps=[], diagnostics=[])
    for name in ('study_events', 'study_resources', 'study_resource_intervals',
                 'study_resource_boundaries', 'study_resource_observation_evidence'):
        if snapshot.tables[name].status != 'AVAILABLE':
            result['diagnostics'].append((name, snapshot.tables[name].status))
    try:
        blocks = {}
        for row in sorted(snapshot.rows('study_events'), key=lambda r: r['id']):
            p = _object(row['payload_json'])
            if row['session_id'] != snapshot.session_id or p.get('block_id') != row['study_block_id']:
                raise ValueError('Study timer scope mismatch')
            generation = p.get('generation')
            if (generation == 0 and not row['study_block_id'] and row['action'] == 'SAFE_SHUTDOWN'
                    and p.get('elapsed_seconds') == 0 and not p.get('started_wall_time_utc')):
                continue  # Shutdown without any prepared/started Study block.
            if type(generation) is not int or generation <= 0:
                raise ValueError('Invalid Study generation')
            elapsed = p.get('elapsed_seconds')
            if type(elapsed) not in (float, int) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError('Invalid recorded Study timer')
            key = (snapshot.session_id, row['study_block_id'], generation)
            block = blocks.setdefault(key, dict(key=key, events=[]))
            if block.get('elapsed', 0) > elapsed:
                raise ValueError('Study elapsed reset within one generation')
            block.update(elapsed=elapsed, payload=p)
            block['events'].append(dict(row))
        result['blocks'] = list(blocks.values())
        roles = {}
        for row in snapshot.rows('study_resources'):
            identity = _object(row['identity_json'])
            if (row['contract_version'] != 1 or identity.get('key') != row['resource_key']
                    or identity.get('kind') != row['identity_kind'] or identity.get('version') != row['identity_version']
                    or row['qualified_monotonic_ns'] < row['first_aligned_monotonic_ns']
                    or row['role'] not in ('PRIMARY', 'LATER') or row['session_id'] != snapshot.session_id):
                raise ValueError('Invalid Study resource authority')
            key = _scope(row) + (row['resource_key'],)
            if key in roles:
                raise ValueError('Duplicate Study qualification')
            roles[key] = dict(row)
            result['resources'].append(dict(row, title=resource_title(identity)))
        observations = {}
        for row in snapshot.rows('study_resource_observation_evidence'):
            identity = _object(row['identity_json'])
            p = _object(row['authority_json'])
            if (row['extension_version'] != 1 or identity.get('key') != row['resource_key']
                    or p.get('resource', {}).get('key') != row['resource_key']
                    or row['session_id'] != snapshot.session_id):
                raise ValueError('Invalid observation identity')
            for field in ('measured_confidence', 'confidence'):
                value = p.get(field)
                if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1):
                    raise ValueError('Invalid measured confidence')
            observations.setdefault(row['interval_id'], []).append(dict(row, authority=p, identity=identity))
        visits = []
        for row in snapshot.rows('study_resource_intervals'):
            rows = sorted(observations.get(row['interval_id'], []),
                          key=lambda r: (r.get('confirmation_applied_monotonic_ns') or r['observed_monotonic_ns'],
                                         r['kind'] != 'OBSERVATION', r['evidence_id']))
            observed = [r for r in rows if r['kind'] == 'OBSERVATION']
            first, last = row['first_observed_monotonic_ns'], row['last_observed_monotonic_ns']
            count, duration = row['observation_count'], row['supported_duration_ns']
            if (row['interval_extension_version'] != 1 or first > last or duration != last-first
                    or len(observed) != count or not observed):
                raise ValueError('Incomplete or invalid supported interval')
            if (observed[0]['observation_id'] != row['first_observation_id']
                    or observed[-1]['observation_id'] != row['last_observation_id']
                    or observed[0]['observed_monotonic_ns'] != first
                    or observed[-1]['observed_monotonic_ns'] != last):
                raise ValueError('Interval endpoint mismatch')
            if any(_scope(r) != _scope(row) or r['resource_key'] != row['resource_key']
                   or r['interval_capture_id'] != row['capture_id'] for r in rows):
                raise ValueError('Cross-scope interval evidence')
            if count == 1:
                if duration != 0 or row['continuity_status'] != 'SINGLE_OBSERVATION':
                    raise ValueError('Invalid single observation')
            else:
                if duration <= 0 or row['continuity_status'] != 'SUPPORTED_SPAN':
                    raise ValueError('Invalid supported span')
                for left, right in zip(observed, observed[1:]):
                    delta = right['observed_monotonic_ns'] - left['observed_monotonic_ns']
                    if right['observation_sequence'] != left['observation_sequence'] + 1 or not 0 < delta <= row['continuity_max_gap_ns']:
                        raise ValueError('Unsupported interval continuity')
            qualified = roles.get(_scope(row) + (row['resource_key'],))
            initial, effective = rows[0]['authority'], rows[-1]['authority']
            eligible = bool(qualified and qualified['qualified_monotonic_ns'] <= last
                            and effective.get('classification') == 'STUDY_ALIGNED'
                            and (initial.get('measured_classification') != 'UNCERTAIN'
                                 or effective.get('user_confirmation') == 'STUDY'))
            visits.append(dict(row, title=resource_title(observed[0]['identity']),
                               qualification=qualified['role'] if qualified else 'Not qualified',
                               initial=initial, effective=effective, evidence=rows,
                               eligible=eligible))
        visits.sort(key=lambda r: (_scope(r), r['capture_id'], r['span_ordinal']))
        for scope in {_scope(v) for v in visits}:
            if len({v['capture_id'] for v in visits if _scope(v)==scope}) > 1:
                raise ValueError('Multiple interval capture domains need a validated chronology')
        result['visits'] = visits
        boundaries = snapshot.rows('study_resource_boundaries')
        # Study-only nodes preserve separate visits. A connector must account
        # for every omitted visit and every exact endpoint boundary between them.
        for index, visit in enumerate(visits):
            if not visit['eligible']:
                continue
            result['jumps'].append(dict(visit=visit, connector=''))
            if len(result['jumps']) < 2:
                previous_index = index
                continue
            previous = visits[previous_index]
            chain = visits[previous_index:index+1]
            continuous = (_scope(previous) == _scope(visit) and previous['capture_id'] == visit['capture_id'])
            for left, right in zip(chain, chain[1:]):
                links = [b for b in boundaries if _scope(b) == _scope(left)
                         and b['from_observation_id'] == left['last_observation_id']
                         and b['to_observation_id'] == right['first_observation_id']
                         and b['from_resource_key'] == left['resource_key']
                         and b['to_resource_key'] == right['resource_key']]
                continuous = continuous and len(links) == 1
                if links:
                    b = links[0]
                    continuous = continuous and b['continuity'] == 'CONTIGUOUS_OBSERVED_CHANGE'
                    continuous = continuous and not json.loads(b['gap_reasons_json']) and not json.loads(b['capture_gap_reasons_json'])
                    continuous = continuous and b.get('contract_version') == 1
                    continuous = continuous and b.get('from_observed_monotonic_ns') == left['last_observed_monotonic_ns']
                    continuous = continuous and b.get('to_observed_monotonic_ns') == right['first_observed_monotonic_ns']
                    continuous = continuous and b.get('to_observation_ordinal', -1) == b.get('from_observation_ordinal', -3) + 1
                    delta = right['first_observed_monotonic_ns'] - left['last_observed_monotonic_ns']
                    continuous = continuous and 0 < delta <= min(left['continuity_max_gap_ns'], right['continuity_max_gap_ns'])
            if not continuous:
                connector = 'Evidence gap'
            elif (index == previous_index + 1 and previous['resource_key'] != visit['resource_key']
                  and previous['effective'].get('classification') == 'STUDY_ALIGNED'
                  and visit['initial'].get('classification') == 'STUDY_ALIGNED'):
                connector = 'Direct observed change'
            elif any(r['effective'].get('classification') == 'DISTRACTION' for r in chain[1:-1]):
                connector = 'Interruption recorded'
            else:
                connector = 'Evidence gap'
            result['jumps'][-2]['connector'] = connector
            previous_index = index
    except (KeyError, ValueError, TypeError) as error:
        result.update(status='UNAVAILABLE', visits=[], jumps=[])
        result['diagnostics'].append(('validation', str(error)))
    return result


def project_cosecant(snapshot: EvidenceSnapshot) -> tuple[dict, ...]:
    """Keep break completion, return confirmation and shutdown as separate facts."""
    groups = {}
    for row in snapshot.rows('cosecant_events'):
        if not row['break_id'] and row['kind'] == 'SAFE_SHUTDOWN':
            continue  # Idle runtime shutdown is not a break entity.
        groups.setdefault(row['break_id'], []).append(row)
    result = []
    for native, rows in groups.items():
        item = dict(native_id=native, display_break_id=read_display_alias(snapshot, 'COSECANT', native),
                    status='AVAILABLE', events=[], started=None, target=None, allowance=None)
        try:
            previous = 0
            for row in sorted(rows, key=lambda r: r['sequence']):
                p = _object(row['payload_json'])
                if (row['session_id'] != snapshot.session_id or p['break_id'] != native
                        or p['kind'] != row['kind'] or p['sequence'] != row['sequence']
                        or row['sequence'] != previous + 1):
                    raise ValueError('Invalid break chronology')
                parse_utc_timestamp(p['occurred_wall_time_utc'])
                previous = row['sequence']
                item['events'].append(dict(row, payload=p))
                if row['kind'] == 'BREAK_STARTED':
                    if item['started'] is not None:
                        raise ValueError('Duplicate break start')
                    item['started'] = p
                    if 'selected_break_extension_version' in p:
                        if p['selected_break_extension_version'] != 1 or type(p['selected_break_seconds']) is not int or p['selected_break_seconds'] <= 0:
                            raise ValueError('Invalid allowance')
                        item['allowance'] = p['selected_break_seconds']
                    if 'return_target_extension_version' in p:
                        if p['return_target_extension_version'] != 1 or not isinstance(p['return_target'], dict):
                            raise ValueError('Invalid return target')
                        item['target'] = p['return_target']
                        if (item['target'].get('identity_version') != 1
                                or item['target'].get('identity_kind') not in ('BROWSER','DESKTOP')):
                            raise ValueError('Invalid authoritative return identity')
                        if item['target']['identity_kind']=='BROWSER' and not (
                                item['target'].get('platform_key') and item['target'].get('resource_token')):
                            raise ValueError('Incomplete browser return identity')
        except (KeyError, ValueError, TypeError) as error:
            item.update(status='UNAVAILABLE', diagnostic=str(error))
        result.append(item)
    return tuple(result)


def duration_text(seconds) -> str:
    if seconds is None:
        return 'Not recorded'
    if 0 < seconds < 1:
        return '<1s'
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return (f'{hours}h ' if hours else '') + f'{minutes}m {seconds:02d}s'


def _human(value: str) -> str:
    return str(value).replace('_', ' ').capitalize()


def prepare_presentation(snapshot: EvidenceSnapshot, timezone_key: str) -> dict:
    """Prepare the frozen setter contract without importing Qt or dummy fixtures."""
    from time_projection import project_utc_timestamp

    def stamp(value, full=False):
        if not value:
            return 'Not recorded'
        try:
            return project_utc_timestamp(value, timezone_key).strftime('%d %b %Y · %H:%M:%S' if full else '%H:%M:%S')
        except ValueError:
            return 'Unavailable'

    def table_state(name):
        return {'AVAILABLE': 'No data', 'NOT_RECORDED': 'Not recorded', 'UNAVAILABLE': 'Unavailable'}[snapshot.tables[name].status]

    def metric(name, value, note='Selected MYELIN session'):
        return (name, str(value), note)

    secant = project_secant(snapshot)
    study = project_study(snapshot)
    breaks = project_cosecant(snapshot)
    secant_archive = []
    all_events = []
    for episode in secant:
        source = (resource_title(episode.source) if episode.source_status == 'AVAILABLE' else
                  'Unavailable' if episode.source_status == 'UNAVAILABLE' else 'Not recorded')
        stage = f'SECANT-{episode.stage_reached}' if episode.stage_reached else 'Not recorded'
        closure = _human(episode.closed['reason']) if episode.closed else 'In progress'
        valid = episode.status == 'AVAILABLE'
        mapping = next((r for r in snapshot.rows('presentation_aliases')
                        if r['entity_kind'] == 'SECANT' and r['native_id'] == episode.identity[2]), {})
        events, nodes = [], []
        for index, event in enumerate(episode.events if valid else ()):
            name = {'SECANT_ACTION_INTENT': 'Return to Study Selected',
                    'SECANT_RETURN_STARTED': 'Return Process Started',
                    'SECANT_RETURN_VERIFIED': 'Return Verified',
                    'SECANT_RECOVERY_INTERRUPTED': 'Recovery Interrupted',
                    'SECANT_RECOVERY_CLOSED': 'Recovery Closed',
                    'SECANT_EPISODE_CLOSED': 'Episode Closed',
                    'SECANT_EPISODE_FOUNDED': 'Episode Founded',
                    'SECANT_DISPLAYED': 'SECANT Displayed'}.get(event['event_name'], _human(event['event_name']))
            detail = _human(event['reason']) if event['reason'] else (f"Stage {event['stage']}" if event['stage'] else 'Recorded')
            events.append((str(index+1), stamp(event['recorded_at_utc']), name, source, 'Recorded'))
            nodes.append(('SECANT', name, detail, stamp(event['recorded_at_utc']), 'cyan', ''))
        intents = episode.named('SECANT_ACTION_INTENT')
        verified = episode.named('SECANT_RETURN_VERIFIED')
        interruptions = episode.named('SECANT_RECOVERY_INTERRUPTED')
        targets = [r for r in study['resources'] if episode.founded
                   and r['resource_key'] == episode.founded['study_target_resource_id']]
        secant_archive.append(dict(episode_id=episode.identity[2], display_episode_id=episode.display_episode_id,
            source=source, started=stamp(mapping.get('founding_at_utc'), True),
            stage=stage if valid else 'Unavailable', outcome=closure if valid else 'Unavailable',
            return_intent=('Recorded · '+stamp(intents[-1]['recorded_at_utc'])) if intents else 'None',
            verification=('Confirmed · '+stamp(verified[-1]['recorded_at_utc'])) if verified else 'None',
            interruption=', '.join(dict.fromkeys(_human(r['reason']) for r in interruptions)) or 'None',
            closure=closure, study_resource=targets[0]['title'] if len(targets)==1 else 'Not recorded',
            platform=episode.source.get('platform_key') or 'Not recorded', events=tuple(events), map_nodes=tuple(nodes),
            recorded_at=stamp(episode.events[-1]['recorded_at_utc'], True) if episode.events else 'Not recorded'))
        all_events.extend((r['recorded_at_utc'], display) for r,display in zip(episode.events,events))
    secant_archive.sort(key=lambda item: next((r.get('founding_at_utc', '') for r in snapshot.rows('presentation_aliases')
                           if r['entity_kind']=='SECANT' and r['native_id']==item['episode_id']), ''), reverse=True)
    all_events = [(str(i+1),)+display[1:] for i,(_,display) in enumerate(
        sorted(all_events, key=lambda pair: parse_utc_timestamp(pair[0])))]
    missing = table_state('secant_events')
    recent = secant_archive[0] if secant_archive else dict.fromkeys(
        ('display_episode_id','source','stage','outcome','recorded_at','study_resource','return_intent','verification','interruption','closure'), missing)
    recent_fields = tuple(zip(('Episode ID','Distraction Source','Stage Reached','Closure','Recorded At','Current study material'),
                             (recent[k] for k in ('display_episode_id','source','stage','outcome','recorded_at','study_resource'))))
    recent_flow = secant_archive[0]['map_nodes'] if secant_archive else ()
    secant_ok = snapshot.tables['secant_events'].status == 'AVAILABLE' and all(e.status=='AVAILABLE' for e in secant)
    counts = [len(secant), sum(len(e.named('SECANT_RETURN_VERIFIED')) for e in secant),
              sum(len(e.named('SECANT_RECOVERY_INTERRUPTED')) for e in secant)]
    secant_metrics = tuple(metric(n,v if secant_ok else ('Unavailable' if snapshot.tables['secant_events'].status=='AVAILABLE' else table_state('secant_events'))) for n,v in zip(
        ('CAPTURED EPISODES','VERIFIED RETURNS','INTERRUPTED RECOVERIES'),counts))
    resources = study['resources']
    study_ok = study['status']=='AVAILABLE'
    role_ok = snapshot.tables['study_resources'].status=='AVAILABLE' and study_ok
    timer_ok = snapshot.tables['study_events'].status=='AVAILABLE' and study_ok
    jumps = study['jumps']
    direct = sum(j['connector']=='Direct observed change' for j in jumps)
    confirmed = {(_scope(v),v['resource_key']) for v in study['visits']
                 if v['initial'].get('measured_classification')=='UNCERTAIN'
                 and v['effective'].get('user_confirmation') == 'STUDY'
                 and v['effective'].get('classification')=='STUDY_ALIGNED'
                 and v['qualification'] in ('PRIMARY','LATER')}
    timer = duration_text(sum(b['elapsed'] for b in study['blocks'])) if study['blocks'] else table_state('study_events')
    study_missing = 'Unavailable' if not study_ok or any(status == 'UNAVAILABLE' for _,status in study['diagnostics']) else 'Not recorded'
    study_metrics = (metric('STUDY RESOURCES',len(resources) if role_ok else study_missing),
        metric('DIRECT STUDY JUMPS',('Not recorded' if study['blocks'] and not study['visits'] else direct) if study_ok and not study['diagnostics'] else study_missing),
        metric('TOTAL STUDY TIME',timer if timer_ok else study_missing,'Recorded Study timer elapsed'),
        metric('CONFIRMED UNCERTAIN RESOURCES',('Not recorded' if study['blocks'] and not study['visits'] else len(confirmed)) if study_ok and not study['diagnostics'] else study_missing))

    def observation_stamp(visit, first):
        oid = visit['first_observation_id'] if first else visit['last_observation_id']
        values = set()
        for b in snapshot.rows('study_resource_boundaries'):
            if _scope(b) != _scope(visit):
                continue
            for side in ('from','to'):
                if b[side+'_observation_id']==oid:
                    values.add(b[side+'_observed_at_utc'])
        return stamp(next(iter(values))) if len(values)==1 else 'Unavailable' if values else 'Not recorded'

    def history_rows(visits):
        return tuple((str(i+1), v['title'], 'Single observation' if v['continuity_status']=='SINGLE_OBSERVATION'
                      else duration_text(v['supported_duration_ns']/1e9), observation_stamp(v,True),
                      observation_stamp(v,False),v['qualification']) for i,v in enumerate(visits))

    def confirmation(p):
        value=p.get('user_confirmation')
        return {'NONE':'None','STUDY':'Confirmed','OFF_TASK':'Confirmed off-task'}.get(value,
            'Not recorded' if value is None else 'Unavailable')

    def confidence(p, field):
        return f"{p[field]*100:.0f}%" if p.get(field) is not None else 'Not recorded'

    def evidence_rows(visits, archive=False):
        if archive:
            return tuple((str(i+1),v['title'],str(v['initial'].get('measured_classification','Not recorded')).replace('_',' '),
                          str(v['effective'].get('classification','Not recorded')).replace('_',' '),confirmation(v['effective'])) for i,v in enumerate(visits))
        return tuple((str(i+1),v['title'],str(v['initial'].get('measured_classification','Not recorded')).replace('_',' '),
                      confidence(v['initial'],'measured_confidence'),confirmation(v['effective']),v['qualification']) for i,v in enumerate(visits))

    def jump_nodes(entries):
        return tuple((j['visit']['qualification'],j['visit']['title'],'Study-aligned',
                      observation_stamp(j['visit'],False),'green',j['connector']) for j in entries)

    study_archive=[]
    for block in study['blocks']:
        p=block['payload'];key=block['key']
        visits=[v for v in study['visits'] if _scope(v)[:3]==key]
        block_jumps=[j for j in jumps if _scope(j['visit'])[:3]==key]
        primary=next((r['title'] for r in resources if _scope(r)[:3]==key and r['role']=='PRIMARY'),'Not recorded')
        started=stamp(p.get('started_wall_time_utc'),True)
        study_archive.append(dict(demo_key=json.dumps(key),date=started.partition(' · ')[0],title=p.get('subject') or 'Not recorded',
            started=started,ended=stamp(p.get('completed_wall_time_utc'),True),duration=duration_text(block['elapsed']),
            primary=primary,resources=history_rows(visits),evidence=evidence_rows(visits,True),
            direct_study_jumps=str(sum(j['connector']=='Direct observed change' for j in block_jumps)),
            events=tuple((str(i+1),stamp(r['created_at_utc']),_human(r['action']),'Recorded') for i,r in enumerate(block['events'])),
            jump_nodes=jump_nodes(block_jumps)))
    attr_visit = next((v for v in study['visits'] if v['initial'].get('measured_classification')=='UNCERTAIN'),
                      study['visits'][0] if study['visits'] else None)
    attr_values = (attr_visit['title'],str(attr_visit['initial'].get('measured_classification','Not recorded')).replace('_',' '),
        confidence(attr_visit['initial'],'measured_confidence'),confirmation(attr_visit['effective']),
        str(attr_visit['effective'].get('classification','Not recorded')).replace('_',' '),confidence(attr_visit['effective'],'confidence'),
        attr_visit['qualification'],'Behavioural only') if attr_visit else (('Unavailable' if not study_ok else table_state('study_resource_observation_evidence')),)*8
    evidence_attrs=tuple(zip(('Resource','Initial Classification','Initial Confidence','User Confirmation','Effective Classification',
                             'Effective Confidence','Qualification','Evidence scope'),attr_values))
    confirmation_nodes=tuple(('OBSERVATION' if r['kind']=='OBSERVATION' else 'CONFIRMATION',
        str(r['authority'].get('measured_classification' if r['kind']=='OBSERVATION' else 'classification','Not recorded')).replace('_',' '),
        confidence(r['authority'],'measured_confidence' if r['kind']=='OBSERVATION' else 'confidence'),
        'Not recorded','amber' if r['authority'].get('measured_classification')=='UNCERTAIN' else 'green','')
        for r in (attr_visit['evidence'] if attr_visit else []) if r['kind']=='CONFIRMATION' or r==attr_visit['evidence'][0])

    breaks=sorted(breaks,key=lambda b:(b['started'] or {}).get('occurred_wall_time_utc',''),reverse=True)
    co=breaks[0] if breaks else None
    co_missing=table_state('cosecant_events')
    def co_value(b):
        if b['status']!='AVAILABLE': return ('Unavailable',)*5
        kinds={r['kind'] for r in b['events']}
        target=resource_title(b['target']) if b['target'] is not None else 'Not recorded'
        outcome='Returned' if 'RETURN_CONFIRMED' in kinds else 'Break Cancelled' if 'BREAK_CANCELLED' in kinds else 'Closed' if 'SAFE_SHUTDOWN' in kinds else 'In progress'
        returned=next((r['payload']['occurred_wall_time_utc'] for r in reversed(b['events']) if r['kind']=='RETURN_CONFIRMED'),None)
        return target,outcome,stamp(returned) if returned else 'None',('Confirmed' if returned else
            'Interrupted' if 'RETURN_CONFIRMATION_INTERRUPTED' in kinds else 'None'),duration_text(b['allowance'])
    target,outcome,returned,confirmation_value,allowance=co_value(co) if co else (co_missing,)*5
    co_alias=co['display_break_id'] if co else co_missing
    co_events=co['events'] if co and co['status']=='AVAILABLE' else []
    co_metrics=tuple(metric(label,sum(any(r['kind']==event for r in b['events']) for b in breaks)
                       if snapshot.tables['cosecant_events'].status=='AVAILABLE' and all(b['status']=='AVAILABLE' for b in breaks) else ('Unavailable' if snapshot.tables['cosecant_events'].status=='AVAILABLE' else table_state('cosecant_events')))
        for label,event in [('RECORDED BREAKS','BREAK_STARTED'),('COMPLETED ALLOWANCES','BREAK_COMPLETE'),('CONFIRMED RETURNS','RETURN_CONFIRMED'),('CANCELLED BREAKS','BREAK_CANCELLED')])
    co_flow=tuple(('COSECANT',_human(r['kind']),_human(r['payload']['to_state']),stamp(r['payload']['occurred_wall_time_utc']),'blue','') for r in co_events)
    overview_metrics=secant_metrics+study_metrics[:3]
    distraction_metrics=secant_metrics+(metric('DISTRACTION SOURCES',len({e.source.get('key') for e in secant if e.source_status=='AVAILABLE'})
        if secant_ok and snapshot.tables['secant_founding_source'].status=='AVAILABLE' else table_state('secant_founding_source')),)
    context={
        'source_banner':f'RECORDED EVIDENCE · SESSION {snapshot.session_id}',
        'about_architecture':'Recorded evidence is read and supplied through presentation setters.',
        'about_dashboard_time':'Prepared values','about_foundation_title':'DATA FOUNDATION',
        'about_input_category':'RECORDED INPUT','about_input_time':'Read-only',
        'about_source':'Read-only MYELIN database projection','about_stage':'Display values are prepared from recorded evidence.',
        'about_stage_label':'SOURCE SCOPE'}
    for name in ('cosecant_events','cosecant_returns','distraction_attributes','episodes_flow','episodes_summary','evidence_attributes','evidence_summary',
                 'landing_events','landing_flow','overview_events','overview_flow','overview_insights','secant_archive_events','secant_archive_list',
                 'secant_archive_summary','study_archive_events','study_archive_list','study_archive_summary'):
        context[name]='Recorded evidence in the selected scope.'
    context['overview_events']=context['landing_events']='Recorded event times; occurrence order preserved.'
    context['secant_archive_events']='Recorded event times; occurrence order preserved.'
    if any(e.display_episode_id=='Unavailable' for e in secant) or any(b['display_break_id']=='Unavailable' for b in breaks):
        context['source_banner'] += ' · Alias unavailable'
    primary=next((r['title'] for r in resources if r['role']=='PRIMARY'),'Not recorded')
    later=next((r['title'] for r in resources if r['role']=='LATER'),'None')
    return dict(context=context, study_facts=study, cosecant_facts=breaks,
        landing=dict(status=('●  EPISODE',recent['outcome'],'RECORDED','cyan'),recent_episode=recent_fields,
            recent_badges=(recent['outcome'],recent['stage']),metrics=overview_metrics[:4],
            behaviour=(recent['source'],recent.get('platform',missing),recent['stage'],recent['outcome']),latest_events=tuple(reversed(all_events[-5:])),journey=recent_flow),
        overview=dict(metrics=overview_metrics,recent_episode=recent_fields,
            study_snapshot=tuple(zip(('Primary resource','Later resource','Confirmed uncertain resources','Observed study path','Distraction videos'),
                                     (primary,later,study_metrics[3][1],'Qualified Study resources','Excluded'))),latest_events=tuple(all_events),
            insights=(('Scope',f'Session {snapshot.session_id}'),
                      ('Session lifecycle',(snapshot.rows('sessions')[0].get('close_reason') or 'In progress') if snapshot.rows('sessions') else table_state('sessions')),
                      ('Study area',study['blocks'][-1]['payload'].get('subject') or 'Not recorded' if study['blocks'] else table_state('study_events')),
                      ('Study Jump','Gaps and interruptions remain distinct.')),journey=recent_flow),
        episodes=dict(metrics=distraction_metrics,rows=tuple((str(i+1),r['display_episode_id'],r['source'],r['stage'],r['outcome'],r['recorded_at']) for i,r in enumerate(secant_archive)),recent_episode=recent_fields,flow=recent_flow),
        distraction_history=dict(metrics=distraction_metrics,rows=tuple((str(i+1),r['source'],r['started'],r['stage'],r['return_intent'],r['verification'],r['closure']) for i,r in enumerate(secant_archive)),
            attributes=tuple(zip(('Distraction Source','Return Intent','Return Verified','Stage Reached','Closure','Outcome scope','Recovery Interruption','Recorded At'),
                (recent['source'],recent['return_intent'],recent['verification'],recent['stage'],recent['closure'],'Behavioural only',recent['interruption'],recent['recorded_at']))),flow=recent_flow),
        study_history=dict(metrics=study_metrics,rows=history_rows([v for v in study['visits'] if v['eligible']]),jump_nodes=jump_nodes(jumps)),
        study_evidence=dict(metrics=study_metrics,rows=evidence_rows(study['visits']),attributes=evidence_attrs,confirmation_nodes=confirmation_nodes),
        cosecant=dict(main_summary=tuple(zip(('BREAK ID','LAST RECORDED STATE','BREAK TYPE','SELECTED ALLOWANCE','RETURN TARGET','OUTCOME'),
                 (co_alias,_human(co_events[-1]['payload']['to_state']) if co_events else co_missing,'Not recorded' if co and co['started'] else co_missing,allowance,target,outcome))),
            recent_break=tuple(zip(('Break ID','Selected Allowance','Return Target','Return Confirmation','Outcome','Recorded At'),
                 (co_alias,allowance,target,confirmation_value,outcome,stamp(co_events[-1]['created_at_utc'],True) if co_events else co_missing))),metrics=co_metrics,
            break_history=tuple(zip(('Break ID','Break Type','Selected Allowance','Return Target','Allowance Status','Return Status','Outcome'),
                 (co_alias,'Not recorded' if co and co['started'] else co_missing,allowance,target,
                  'Completed' if any(r['kind']=='BREAK_COMPLETE' for r in co_events) else 'Cancelled' if any(r['kind']=='BREAK_CANCELLED' for r in co_events) else 'Not recorded',confirmation_value,outcome))),
            events=tuple((_human(r['kind']),'Recorded',stamp(r['payload']['occurred_wall_time_utc'])) for r in co_events),
            return_history=tuple((co_value(b)[0],co_value(b)[2],co_value(b)[3],co_value(b)[1]) for b in breaks),flow=co_flow),
        secant_archive=tuple(secant_archive),study_archive=tuple(study_archive))
