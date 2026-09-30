"""Immutable single-parent report model. Durable readers only; no UI or writes."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections import Counter
import hashlib
import json

from .dashboard_evidence import ParentSessionScope
from .dashboard_projection import prepare_presentation, duration_text, secant_event_clock, resource_title
from time_projection import parse_utc_timestamp, project_utc_timestamp


class ReportNotReady(ValueError):
    """Selected durable evidence cannot yet support a final report."""


@dataclass(frozen=True)
class Text:
    value: str


@dataclass(frozen=True)
class Table:
    title: str
    columns: tuple[str, ...]
    widths: tuple[float, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Flow:
    title: str
    # Same semantic tuple as dashboard FlowPanel; geometry belongs to renderer.
    nodes: tuple[tuple[str, str, str, str, str, str], ...]


@dataclass(frozen=True)
class Section:
    title: str
    family: str
    blocks: tuple[Text | Table | Flow, ...]


@dataclass(frozen=True)
class ReportModel:
    session_id: int
    generated_at: str
    timezone_key: str
    evidence_state: str
    evidence_digest: str
    counts: tuple[tuple[str, int], ...]
    dashboard_metrics: tuple[tuple[str, tuple[tuple[str, str, str], ...]], ...]
    sections: tuple[Section, ...]


def require_finalized(scope: ParentSessionScope):
    """Finality is a recorder fence, independent of behavioral/quality outcome."""
    if not isinstance(scope, ParentSessionScope) or scope.session_id != scope.snapshot.session_id:
        raise ReportNotReady('Unavailable: invalid parent-session scope.')
    snapshot = scope.snapshot
    parent = snapshot.tables['sessions']
    if parent.status != 'AVAILABLE' or len(parent.rows) != 1 or parent.rows[0]['id'] != scope.session_id:
        raise ReportNotReady('Unavailable: parent-session evidence cannot be read.')
    table = snapshot.recorder_receipts
    if table.status != 'AVAILABLE' or len(table.rows) != 1:
        raise ReportNotReady('Recording finalization is unavailable: a single durable recorder receipt is required.')
    receipt = table.rows[0]
    try:
        if (type(receipt['contract_version']) is not int or receipt['contract_version'] != 1
                or scope.session_id not in receipt['attached_session_ids']
                or not isinstance(receipt['run_id'], str) or not receipt['run_id']):
            raise ValueError('Invalid recorder receipt identity')
        if any(type(receipt[k]) is not int or receipt[k] < 0 for k in ('pending','dropped')):
            raise ValueError('Invalid recorder counts')
        if receipt['coverage'] not in ('BOUNDED_OBSERVATION','RECORDING_GAP_DETECTED'):
            raise ValueError('Invalid coverage contract')
        if receipt['writer_state'] == 'FAILED':
            raise ValueError('Recorder writer failed')
        if (receipt['writer_state'] != 'CLOSED' or receipt['final_flush_committed'] is not True
                or receipt['pending'] != 0 or not receipt['closed_at_utc']):
            raise ReportNotReady('Recording finalization is pending. Stop alone is not finality. Export after the recorder closes and the finalized history is reopened.')
        parse_utc_timestamp(receipt['closed_at_utc'])
        if any(r.get('recorder_run_id') != receipt['run_id'] for r in snapshot.rows('secant_events')):
            raise ValueError('Recorder clock-domain mismatch')
    except ReportNotReady:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ReportNotReady('Unavailable: invalid recorder final-flush evidence.') from error
    return receipt


def build_report(scope: ParentSessionScope, timezone_key='UTC', *, generated_at=None) -> ReportModel:
    receipt = require_finalized(scope)
    snapshot = scope.snapshot
    model = prepare_presentation(snapshot, timezone_key)  # One scoped snapshot, never DashboardIntegration.last_model.
    episodes, study, breaks = model['secant_facts'], model['study_facts'], model['cosecant_facts']
    valid = [e for e in episodes if e.summary_eligible]
    valid_breaks = [b for b in breaks if b['status']=='AVAILABLE']
    def human(value):
        return str(value).replace('_',' ').capitalize() if value not in (None,'') else 'Not recorded'
    def stamp(value):
        if not value:return 'Not recorded'
        try:return project_utc_timestamp(value,timezone_key).strftime('%d %b %Y  %H:%M:%S')
        except (ValueError,TypeError):return 'Unavailable'
    def state(name):
        return {'AVAILABLE':'No data','NOT_RECORDED':'Not recorded','UNAVAILABLE':'Unavailable'}[snapshot.tables[name].status]
    def table(title, columns, widths, rows):
        return Table(title,tuple(columns),tuple(widths),tuple(tuple(str(c) for c in r) for r in rows))
    parent = snapshot.rows('sessions')[0]
    count_pairs = (
        ('Study blocks',len(study['blocks']) if study['status']=='AVAILABLE' else 0),
        ('Recorded SECANT episodes',len(episodes)),('Validated SECANT episodes',len(valid)),
        ('Excluded SECANT episodes',len(episodes)-len(valid)),
        ('Recorded COSECANT breaks',len(breaks)),('Validated COSECANT breaks',len(valid_breaks)),
        ('Study visits',len(study['visits']) if study['status']=='AVAILABLE' else 0))
    scope_rows = [('Parent MYELIN session',str(scope.session_id)),('Started',stamp(parent.get('started_at_utc'))),
        ('Closed',stamp(parent.get('closed_at_utc'))),('Session lifecycle',human(parent.get('close_reason'))),
        ('Recorder evidence state','FINALIZED'),('Recorder coverage',human(receipt['coverage'])),
        ('Pending / dropped recorder items',f"{receipt['pending']} / {receipt['dropped']}"),
        ('Report timezone',timezone_key)]
    for label,value in count_pairs:
        source = 'study_events' if label.startswith('Study') else 'secant_events' if 'SECANT episodes' in label else 'cosecant_events'
        scope_rows.append((label, 'Unavailable' if source=='study_events' and study['status']!='AVAILABLE' else
                           str(value) if snapshot.tables[source].status=='AVAILABLE' else state(source)))
    sections = [Section('Session / evidence summary','study',(
        Text('One parent MYELIN session. Study is the shared context for off-task recovery (SECANT) and approved-break return (COSECANT).'),
        table('Session scope',('Field','Recorded value','Field','Recorded value'),(.23,.27,.23,.27),
              [(*scope_rows[i],*(scope_rows[i+1] if i+1<len(scope_rows) else ('',''))) for i in range(0,len(scope_rows),2)]),
        Text('Finalized means the recorder has committed its final flush. It does not certify that every child record is valid. Excluded and unavailable evidence is disclosed separately.')))]
    stages=Counter(e.stage_reached for e in valid)
    secant_summary=[('Validated episodes',len(valid)),('Highest displayed stage',f'SECANT-{max(stages)}' if stages else state('secant_events')),
        ('Stage distribution',', '.join(f'SECANT-{s}: {stages[s]}' for s in (1,2,3))),
        ('Return attempts',sum(len(e.named('SECANT_RETURN_STARTED')) for e in valid)),
        ('Verified-return events',sum(len(e.named('SECANT_RETURN_VERIFIED')) for e in valid)),
        ('Recovery interruptions',sum(len(e.named('SECANT_RECOVERY_INTERRUPTED')) for e in valid)),
        ('Recovered episodes',sum(bool(e.closed and e.closed['reason']=='recovered') for e in valid)),
        ('Incomplete validated episodes',sum(e.closed is None for e in valid)),
        ('Invalid / non-finalized-quality episodes excluded',len(episodes)-len(valid))]
    closures=Counter(e.closed['reason'] for e in valid if e.closed)
    secant_summary.append(('Closure reasons',', '.join(f'{human(k)}: {v}' for k,v in sorted(closures.items())) or 'Not recorded'))
    secant_blocks=[Text('A verified-return event is not a recovered episode. Episode closure alone is not recovery. Behavioral evidence_gap is distinct from recorder recording loss.')]
    if episodes:secant_blocks.append(table('Validated SECANT summary',('Measure','Value'),(.55,.45),secant_summary))
    else:secant_blocks.append(Text(state('secant_events')))
    index=[]
    for e,a in zip(episodes, [next(r for r in model['secant_archive'] if r['scope_identity']==e.identity) for e in episodes]):
        index.append((e.display_episode_id,a['started'],e.source.get('kind','Not recorded')+'\n'+a['source'],
                      f"{a['stage']}\n{a['outcome']}\n{e.quality_status}"))
    if index:secant_blocks.append(table('SECANT episode index',('Episode','Founded','Source / recorded caption','Stage / outcome / quality'),(.20,.21,.32,.27),index))
    sections.append(Section('SECANT / study recovery','secant',tuple(secant_blocks)))
    for e in episodes:
        a=next(r for r in model['secant_archive'] if r['scope_identity']==e.identity)
        blocks=[Text(f"Evidence validity: {e.status}. Recorder quality: {e.quality_status}. " +
                     ('Included in validated summaries.' if e.summary_eligible else 'Excluded from validated summaries.')),
                table(e.display_episode_id+' / context',('Field','Recorded value'),(.26,.74),[
                    ('Founding source caption',a['source']),('Study target caption',a['study_resource']),
                    ('Highest displayed stage',a['stage']),('Terminal outcome',a['outcome'])])]
        if e.status == 'AVAILABLE':
            events=[]
            for i,r in enumerate(e.events,1):
                basis,when=secant_event_clock(r)
                label=human(r['event_name'].removeprefix('SECANT_'))
                if r['event_name']=='SECANT_DISPLAYED':label=f"SECANT-{r['stage']} Displayed"
                events.append((i,stamp(when),basis,label,human(r['reason'])))
            blocks.append(table(e.display_episode_id+' / event chronology',('#','Time','Clock basis','Event','Recorded detail'),(.07,.19,.14,.26,.34),events))
            blocks.append(Flow(e.display_episode_id+' / recovery flow',tuple(a['map_nodes'])))
        else:blocks.append(Text('Unavailable: '+e.diagnostic))
        sections.append(Section(e.display_episode_id,'secant',tuple(blocks)))
    study_blocks=[Text('Recorded Study timer elapsed is not Supported Foreground Duration. Resource captions describe recorded observations; exact resource identity remains authoritative.')]
    if study['status']!='AVAILABLE':
        study_blocks.append(Text('Unavailable: required Study evidence failed validation. Other organ sections remain available.'))
    else:
        rows=[]
        for i,b in enumerate(study['blocks'],1):
            p=b['payload'];rows.append((f'Study block {i}',p.get('subject') or 'Not recorded',p.get('task') or 'Not recorded',
                duration_text(b['elapsed']),human(p.get('state')),human(p.get('completion_reason'))))
        if rows:study_blocks.append(table('Study blocks',('Block','Subject','Task','Timer elapsed','Lifecycle','Completion reason'),(.12,.2,.28,.14,.12,.14),rows))
        else:study_blocks.append(Text(state('study_events')))
        if study['visits']:
            study_blocks.append(table('Dashboard Study evidence attributes',('Field','Recorded value'),(.28,.72),model['study_evidence']['attributes']))
            study_blocks.append(Flow('Dashboard classification / confirmation flow',tuple(model['study_evidence']['confirmation_nodes'])))
    sections.append(Section('Study / shared context','study',tuple(study_blocks)))
    if study['status']=='AVAILABLE':
        for i,b in enumerate(study['blocks'],1):
            key=b['key'];title=f'Study block {i}'
            resources=[r for r in study['resources'] if (r['session_id'],r['study_block_id'],r['study_generation'])==key]
            visits=[v for v in study['visits'] if (v['session_id'],v['study_block_id'],v['study_generation'])==key]
            archive=next(r for r in model['study_archive'] if r['scope_identity']==key)
            blocks=[]
            if archive['events']:
                blocks.append(table(title+' / lifecycle chronology',('#','Recorded at','Event','Evidence'),(.06,.24,.45,.25),archive['events']))
            if resources:
                blocks.append(table(title+' / qualified resources',('Role','Recorded caption','First aligned','Qualified'),(.12,.48,.2,.2),
                    [(r['role'],r['title'],stamp(r['first_aligned_at_utc']),stamp(r['qualified_at_utc'])) for r in resources]))
            else:blocks.append(Text('Qualified resources: '+state('study_resources')))
            if visits:
                blocks.append(table(title+' / foreground visits',('#','Caption','Supported duration','First observed','Last observed','Qualification'),(.07,.29,.15,.16,.16,.17),archive['resources']))
                # Dashboard evidence is per visit: initial measured class,
                # effective class and recorded user confirmation. Raw samples
                # remain in immutable scope provenance, not invented extra rows.
                blocks.append(table(title+' / classification and confirmation evidence',
                    ('#','Caption','Measured class','Effective class','User confirmation'),
                    (.07,.36,.19,.19,.19),archive['evidence']))
            else:blocks.append(Text('Foreground visits: '+state('study_resource_intervals')))
            jumps=tuple(archive['jump_nodes'])
            blocks.append(Text('Study Jump connectors retain Direct observed change, Interruption recorded and Evidence gap. Omitted distractions are not drawn as Study resource nodes.'))
            if jumps:blocks.append(Flow(title+' / Study Jump',jumps))
            else:blocks.append(Text('Study Jump: '+state('study_resource_intervals')))
            sections.append(Section(title+' / resources and evidence','study',tuple(blocks)))
    co_blocks=[Text('Completed allowance means its deadline was reached. Confirmed return requires the validated same-break proof chain. No recorded confirmation does not mean failed return.')]
    if breaks:
        co_blocks.append(table('COSECANT summary',('Measure','Count'),(.75,.25),[
            ('Recorded breaks',len(breaks)),('Validated breaks',len(valid_breaks)),
            *[(label,sum(any(r['kind']==kind for r in b['events']) for b in valid_breaks)) for label,kind in (
                ('Completed allowances','BREAK_COMPLETE'),('Confirmed returns','RETURN_CONFIRMED'),('Cancelled breaks','BREAK_CANCELLED'),
                ('Overdue reminders reached','BREAK_ALREADY_OVER'),('Final locks reached','FINAL_LOCKED'))],
            ('Invalid breaks excluded',len(breaks)-len(valid_breaks))]))
        index=[]
        for b in breaks:
            if b['status']!='AVAILABLE':
                index.append((b['display_break_id'],'Unavailable','Unavailable','Unavailable'));continue
            target=b['target'];caption=resource_title(target,(b['started'] or {}).get('return_target_display_metadata'),
                observed_ns=target.get('observed_monotonic_ns')) if target else 'Title not recorded'
            kinds={r['kind'] for r in b['events']}
            confirmation='Confirmed' if 'RETURN_CONFIRMED' in kinds else 'Not recorded'
            cancellation='Cancelled' if 'BREAK_CANCELLED' in kinds else 'Not recorded'
            index.append((b['display_break_id'],stamp(b['started']['occurred_wall_time_utc'])+'\nAllowance: '+duration_text(b['allowance']),
                caption,human(b['events'][-1]['payload']['to_state'])+'\nConfirmation: '+confirmation+'\nCancellation: '+cancellation))
        co_blocks.append(table('COSECANT break index',('Break','Started / allowance','Return target caption','State / confirmation / cancellation'),(.20,.23,.29,.28),index))
    else:co_blocks.append(Text(state('cosecant_events')))
    sections.append(Section('COSECANT / approved-break return','cosecant',tuple(co_blocks)))
    from .dashboard_projection import _cosecant_flow_tone
    for b in breaks:
        blocks=[]
        if b['status']=='AVAILABLE':
            target=b['target']
            blocks.append(Text('Intended return target kind: '+(target.get('identity_kind','Not recorded') if target else 'Not recorded')+'. Native target identity remains internal provenance.'))
            blocks.append(table(b['display_break_id']+' / event chronology',('Seq.','Occurred at','Event','From state','To state','Proof reference'),(.08,.19,.28,.15,.15,.15),[
                (r['sequence'],stamp(r['payload']['occurred_wall_time_utc']),human(r['kind']),human(r['payload']['from_state']),human(r['payload']['to_state']),
                 'Recorded' if r['payload'].get('evidence_token') else 'Not recorded') for r in b['events']]))
            nodes=tuple(('COSECANT',human(r['kind']),human(r['payload']['to_state']),stamp(r['payload']['occurred_wall_time_utc']),_cosecant_flow_tone(r['kind']),'') for r in b['events'])
            blocks.append(Flow(b['display_break_id']+' / return flow',nodes))
        else:blocks.append(Text('Unavailable: '+b.get('diagnostic','Invalid required evidence')))
        sections.append(Section(b['display_break_id'],'cosecant',tuple(blocks)))
    notes=[Text('This is read-only behavioral software evidence. It makes no neurological, clinical, attention or cognitive claims.'),
        Text('Title not recorded: absent title metadata. Not recorded: an optional fact was never captured. No data: a readable scope contains no applicable records. Unavailable: required evidence is unreadable or invalid.'),
        Text('Finalized recording does not imply complete sensing. Supported foreground spans contain only supported observations; gaps are not filled.'),
        Text('Native identities and proof tokens remain internal provenance. Human-facing SEC and COSEC aliases are the existing persisted presentation identities.')]
    for name,t in snapshot.tables.items():
        if t.status!='AVAILABLE':notes.append(Text(name+': '+state(name)))
    for e in episodes:
        if not e.summary_eligible:notes.append(Text(f'{e.display_episode_id}: excluded. {e.diagnostic or e.quality_diagnostic}'))
    for b in breaks:
        if b['status']!='AVAILABLE':notes.append(Text(b['display_break_id']+': excluded. '+b.get('diagnostic','Invalid evidence')))
    if study['diagnostics']:notes.append(Text('Study evidence notes: '+ '; '.join(f'{k}: {v}' for k,v in study['diagnostics'])))
    sections.append(Section('Evidence quality / reading notes','quality',tuple(notes)))
    def plain(v):
        if hasattr(v,'items'):return {k:plain(x) for k,x in v.items()}
        if isinstance(v,(list,tuple)):return [plain(x) for x in v]
        return v
    payload={k:dict(status=t.status,rows=plain(t.rows)) for k,t in snapshot.tables.items()}
    payload['recorder_receipts']=plain(snapshot.recorder_receipts.rows)
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    generated=generated_at or datetime.now(timezone.utc)
    if generated.tzinfo is None:raise ValueError('Timezone-aware generation timestamp required')
    dashboard_metrics=(('Study',tuple(model['study_history']['metrics'])),
        ('SECANT',tuple(model['episodes']['metrics'])),('COSECANT',tuple(model['cosecant']['metrics'])))
    return ReportModel(scope.session_id,stamp(generated.isoformat()),timezone_key,'FINALIZED',digest,count_pairs,dashboard_metrics,tuple(sections))
