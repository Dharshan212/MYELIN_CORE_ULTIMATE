"""Phase-1 reader regressions. Fixtures are synthetic; no production DB writes."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from unittest.mock import patch

import pytest

from CORE_ENGINE.resource_intent import study_context_token
from SECANT.dashboard_evidence import (TABLES, EvidenceTable, EvidenceSnapshot,
                                      read_snapshot, read_corpus, resolve_scope)
from SECANT.dashboard_projection import (project_secant, project_cosecant, project_study,
    prepare_presentation, recorder_quality, secant_occurred_at, _secant_target_title)
from SECANT.dashboard_integration import DashboardIntegration


NS = 1_000_000_000
BLOCK = 'block-a'
TOKEN = study_context_token(BLOCK, 1)
CONTEXT = '1:' + TOKEN


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def seal(row):
    fact = [1] + [row[k] for k in ('session_id','study_context_id','study_target_resource_id',
        'episode_id','event_name','stage','occurred_monotonic_ns','request_id','attempt_id','evidence_id','reason')]
    row['canonical_fact_json'] = canonical(fact)
    row['fact_digest'] = sha(row['canonical_fact_json'])
    row['event_id'] = sha(canonical(['secant-event-v1', fact, row['occurrence_ordinal']]))
    return row


def secant_rows(stage=1):
    specs = [('SECANT_EPISODE_FOUNDED',1,0,'request-1','','',''),
             ('SECANT_DISPLAYED',1,1,'request-1','','','')]
    for value in range(2, stage+1):
        specs.append(('SECANT_DISPLAYED',value,value,'request-'+str(value),'','',''))
    specs += [('SECANT_ACTION_INTENT',4,stage,'request-'+str(stage),'','','RETURN TO STUDY'),
              ('SECANT_RETURN_STARTED',5,0,'','attempt','start-proof',''),
              ('SECANT_RETURN_VERIFIED',15,0,'','attempt','verified-proof',''),
              ('SECANT_RECOVERY_CLOSED',75,0,'','attempt','closed-proof',''),
              ('SECANT_EPISODE_CLOSED',75,stage,'','','','recovered')]
    result = []
    for name, at, level, request, attempt, evidence, reason in specs:
        result.append(seal(dict(contract_version=1,session_id=1,study_context_id=CONTEXT,
            study_target_resource_id='resource',episode_id='episode',event_name=name,stage=level,
            occurred_monotonic_ns=at*NS,occurrence_ordinal=1,request_id=request,attempt_id=attempt,
            evidence_id=evidence,reason=reason,recorder_run_id='run',recording_quality='BOUNDED_OBSERVATION',
            recorder_received_monotonic_ns=100*NS,recorder_received_at_utc='2026-09-30T00:01:40Z',
            recorded_at_utc='2026-09-30T01:00:00Z')))
    return result


def receipt(**changes):
    value = dict(run_id='run',contract_version=1,attached_session_ids=[1],coverage='BOUNDED_OBSERVATION',
        writer_state='CLOSED',pending=0,dropped=0,gap_reasons=[],final_flush_committed=True,
        closed_at_utc='2026-09-30T00:02:00Z')
    value.update(changes)
    return value


def snapshot(secant=(), breaks=(), *, quality=None, tables=None, sid=1):
    values = {name:EvidenceTable((), 'AVAILABLE') for name in TABLES}
    values.update(sessions=EvidenceTable((dict(id=sid),),'AVAILABLE'),
                  secant_events=EvidenceTable(tuple(secant),'AVAILABLE'),
                  cosecant_events=EvidenceTable(tuple(breaks),'AVAILABLE'))
    values.update(tables or {})
    return EvidenceSnapshot(sid, values, EvidenceTable((quality or receipt(),),'AVAILABLE'))


def title_metadata(at=NS):
    return dict(observed_caption='Recorded title',normalized_caption='Recorded title',
        source_observation_id='observation',source_observation_sequence=1,
        source_observed_monotonic_ns=at,metadata_version=1,
        normalization_version='resource-intent-normalise-title-v1')


def break_rows(native='break-a', first=1, extension=False, title=False, outcome='confirmed'):
    specs = [('BREAK_STARTED','INACTIVE','BREAK_ACTIVE',1),
             ('BREAK_COMPLETE','BREAK_ACTIVE','BREAK_COMPLETE',61),
             ('BREAK_ALREADY_OVER','BREAK_COMPLETE','BREAK_ALREADY_OVER',361),
             ('FINAL_LOCKED','BREAK_ALREADY_OVER','FINAL_LOCK',421),
             ('RETURN_CONFIRMATION_STARTED','FINAL_LOCK','RETURN_CONFIRMING',422)]
    if outcome == 'lost':
        specs += [('RETURN_CONFIRMATION_LOST','RETURN_CONFIRMING','FINAL_LOCK',423)]
    elif outcome == 'cancelled':
        specs += [('BREAK_CANCELLED','RETURN_CONFIRMING','CANCELLED',423)]
    else:
        specs += [('RETURN_CONFIRMED','RETURN_CONFIRMING','CONFIRMED',425)]
    result = []
    for offset, (kind,before,after,at) in enumerate(specs):
        p=dict(schema_version='myelin-cosecant-v2',sequence=first+offset,kind=kind,break_id=native,
            study_block_id=BLOCK,from_state=before,to_state=after,effective_monotonic_ns=at*NS,
            observed_monotonic_ns=at*NS,occurred_wall_time_utc=(datetime(2026,9,30,tzinfo=timezone.utc)+timedelta(seconds=at)).isoformat(),
            evidence_token='proof-'+str(offset) if kind in ('RETURN_CONFIRMATION_STARTED','RETURN_CONFIRMED') else '')
        if extension and offset == 0:
            p.update(selected_break_extension_version=1,selected_break_seconds=60,
                return_target_extension_version=1,return_target_study_generation=1,
                return_target=dict(study_context_token=TOKEN,platform_key='browser',resource_token='opaque',
                    observed_monotonic_ns=NS,identity_kind='BROWSER',resource_key='',process_name='',
                    process_id=0,hwnd=0,normalized_title='',identity_version=1))
            if title:p['return_target_display_metadata']=title_metadata()
        result.append(dict(id=first+offset,session_id=1,sequence=first+offset,break_id=native,kind=kind,
            occurred_monotonic_ns=at*NS,payload_json=json.dumps(p),created_at_utc=p['occurred_wall_time_utc']))
    return result


def mutate_payload(rows, index, **changes):
    p=json.loads(rows[index]['payload_json']);p.update(changes)
    rows[index]['payload_json']=json.dumps(p)


@pytest.mark.parametrize('stage',[1,2,3])
def test_valid_stage_and_recovery(stage):
    e=project_secant(snapshot(secant_rows(stage)))[0]
    assert e.status == 'AVAILABLE' and e.summary_eligible and e.stage_reached == stage
    assert e.closed['reason']=='recovered'


def test_verified_is_not_recovered():
    e=project_secant(snapshot(secant_rows()[:-2]))[0]
    assert e.summary_eligible and e.closed is None and len(e.named('SECANT_RETURN_VERIFIED'))==1


def test_missing_recovery_closure():
    rows=secant_rows();rows.pop(-2)
    assert project_secant(snapshot(rows))[0].status=='UNAVAILABLE'


def test_recovery_closure_requires_terminal_link():
    assert project_secant(snapshot(secant_rows()[:-1]))[0].status=='UNAVAILABLE'


def test_nonrecovered_terminal():
    rows=secant_rows();rows.pop(-2);rows[-1]['reason']='session_end';seal(rows[-1])
    e=project_secant(snapshot(rows))[0]
    assert e.summary_eligible and e.closed['reason']=='session_end'


@pytest.mark.parametrize('field,value', [('fact_digest','0'*64),('canonical_fact_json','[]'),('event_id','tampered')])
def test_damaged_fact(field,value):
    rows=secant_rows();rows[0][field]=value
    assert project_secant(snapshot(rows))[0].status=='UNAVAILABLE'


@pytest.mark.parametrize('change', ['order','domain','target','founding','request','early_closure','foreign_attempt'])
def test_invalid_secant_links(change):
    rows=secant_rows()
    if change=='order':rows[-1]['occurred_monotonic_ns']=2*NS;seal(rows[-1])
    if change=='domain':rows[-1]['recorder_run_id']='other'
    if change=='target':rows[-1]['study_target_resource_id']='other';seal(rows[-1])
    if change=='founding':rows.pop(0)
    if change=='request':rows[1]['request_id']='other';seal(rows[1])
    if change=='early_closure':rows[-2]['occurred_monotonic_ns']=20*NS;seal(rows[-2])
    if change=='foreign_attempt':rows[-2]['attempt_id']='other';seal(rows[-2])
    assert project_secant(snapshot(rows))[0].status=='UNAVAILABLE'


def test_behavioral_gap_is_not_recorder_gap():
    rows=secant_rows()[:-2]
    row=dict(rows[-1],event_name='SECANT_RECOVERY_INTERRUPTED',occurred_monotonic_ns=16*NS,reason='evidence_gap',evidence_id='')
    rows.append(seal(row))
    e=project_secant(snapshot(rows))[0]
    assert e.summary_eligible and e.quality_status=='FINALIZED'


def test_recorder_gap_keeps_episode_without_derived_claims():
    rows=secant_rows()
    for row in rows:row['recording_quality']='RECORDING_GAP_DETECTED'
    s=snapshot(rows,quality=receipt(coverage='RECORDING_GAP_DETECTED',dropped=1,gap_reasons=['overflow']))
    e=project_secant(s)[0]
    assert e.status=='AVAILABLE' and not e.summary_eligible and len(e.events)==7
    m=prepare_presentation(s,'UTC');a=m['secant_archive'][0]
    assert a['stage']=='Unavailable' and a['closure']=='Unavailable'
    assert m['episodes']['metrics'][0][1]=='0' and len(a['events'])==7


@pytest.mark.parametrize('change,status', [
    ({'writer_state':'ACTIVE','final_flush_committed':False,'closed_at_utc':None},'PENDING'),
    ({'writer_state':'DRAINING'},'PENDING'),({'pending':1},'PENDING'),
    ({'dropped':1},'RECORDING_GAP_DETECTED'),({'coverage':'RECORDING_GAP_DETECTED'},'RECORDING_GAP_DETECTED'),
    ({'writer_state':'FAILED'},'UNAVAILABLE'),({'run_id':'other'},'UNAVAILABLE'),
    ({'attached_session_ids':[2]},'UNAVAILABLE'),({'pending':False},'UNAVAILABLE'),
    ({'final_flush_committed':'true'},'UNAVAILABLE'),({'closed_at_utc':'bad'},'UNAVAILABLE')])
def test_finality_contract(change,status):
    assert recorder_quality(snapshot(secant_rows(),quality=receipt(**change)))['status']==status


def test_missing_receipt_and_reopened_finality():
    s=snapshot(secant_rows())
    assert recorder_quality(replace(s,recorder_receipts=EvidenceTable((),'NOT_RECORDED')))['status']=='NOT_RECORDED'
    assert recorder_quality(s)['status']=='FINALIZED'
    # Session Stop/close_reason is not used as a recorder fence.
    tables=dict(s.tables);tables['sessions']=EvidenceTable((dict(id=1,close_reason='stopped'),),'AVAILABLE')
    active=replace(s,tables=tables,recorder_receipts=EvidenceTable((receipt(writer_state='ACTIVE'),),'AVAILABLE'))
    assert recorder_quality(active)['status']=='PENDING'


def test_active_empty_recorder_is_not_certified_zero():
    s=snapshot(quality=receipt(writer_state='ACTIVE',final_flush_committed=False))
    assert prepare_presentation(s,'UTC')['episodes']['metrics'][0][1]=='Pending'


def test_gap_without_receipt_still_exposes_recorded_loss():
    rows=secant_rows();rows[0]['recording_quality']='RECORDING_GAP_DETECTED'
    s=replace(snapshot(rows),recorder_receipts=EvidenceTable((),'NOT_RECORDED'))
    assert recorder_quality(s)['status']=='RECORDING_GAP_DETECTED'


def test_occurrence_time_is_not_database_write_time():
    row=secant_rows()[0]
    assert secant_occurred_at(row)=='2026-09-30T00:00:01.000000Z'
    m=prepare_presentation(snapshot(secant_rows()),'UTC')
    assert m['secant_archive'][0]['events'][0][1]=='00:00:01'
    assert m['secant_archive'][0]['recorded_at'].endswith('01:00:00')


def test_legacy_clock_fallback_is_explicit():
    rows=secant_rows()
    for r in rows:
        del r['recorder_received_monotonic_ns'];del r['recorder_received_at_utc']
    model=prepare_presentation(snapshot(rows),'UTC')
    event=model['secant_archive'][0]['events'][0]
    assert event[1]=='01:00:00' and event[4].startswith('RECORDED AT')


def test_half_missing_clock_pair_is_invalid():
    rows=secant_rows();del rows[0]['recorder_received_at_utc']
    assert project_secant(snapshot(rows))[0].status=='UNAVAILABLE'


def test_paired_clock_rounds_down_across_midnight():
    row=dict(secant_rows()[0],occurred_monotonic_ns=0,recorder_received_monotonic_ns=1,
             recorder_received_at_utc='2026-09-30T00:00:00Z')
    assert secant_occurred_at(row)=='2026-09-29T23:59:59.999999Z'


def test_old_source_title_missing():
    e=project_secant(snapshot(secant_rows()))[0]
    assert e.source_status=='NOT_RECORDED'
    assert prepare_presentation(snapshot(secant_rows()),'UTC')['secant_archive'][0]['source']=='Title not recorded'


def test_new_founding_source_title():
    rows=secant_rows()
    source=dict(resource=dict(kind='BROWSER',key='off-task',platform_key='browser',resource_token='other'),
        evidence_id='observation',observed_monotonic_ns=NS,meaning='OFF_TASK',classification='DISTRACTION',
        territory='VIDEO',confirmed_off_task=False,certified_ott=True,display_metadata=title_metadata())
    source['resource'].update(version=1)
    extension=dict(event_id=rows[0]['event_id'],source_extension_version=1,source_resource_id='off-task',
        source_evidence_id='observation',source_observed_monotonic_ns=NS,source_evidence_json=json.dumps(source))
    s=snapshot(rows,tables={'secant_founding_source':EvidenceTable((extension,),'AVAILABLE')})
    assert prepare_presentation(s,'UTC')['secant_archive'][0]['source']=='Recorded title'


@pytest.mark.parametrize('wrong',['context','block','generation','resource','parent'])
def test_title_join_never_borrows(wrong):
    e=project_secant(snapshot(secant_rows()))[0]
    resource=dict(session_id=1,study_block_id=BLOCK,study_generation=1,study_context_token=TOKEN,
                  resource_key='resource',title='Own title')
    study=dict(blocks=[dict(key=(1,BLOCK,1))],resources=[resource])
    assert _secant_target_title(e,study)=='Own title'
    field={'context':'study_context_token','block':'study_block_id','generation':'study_generation',
           'resource':'resource_key','parent':'session_id'}[wrong]
    resource[field]=2 if wrong in ('generation','parent') else 'other'
    assert _secant_target_title(e,study)=='Title not recorded'


def test_three_session_wide_breaks():
    rows=break_rows('a',1)+break_rows('b',7)+break_rows('c',13)
    result=project_cosecant(snapshot(breaks=rows))
    assert len(result)==3 and all(b['status']=='AVAILABLE' for b in result)
    assert [b['events'][0]['sequence'] for b in result]==[1,7,13]


@pytest.mark.parametrize('extension,title',[(False,False),(True,False),(True,True)])
def test_cosecant_optional_history(extension,title):
    s=snapshot(breaks=break_rows(extension=extension,title=title))
    b=project_cosecant(s)[0];assert b['status']=='AVAILABLE'
    assert b['allowance']==(60 if extension else None)
    summary=dict(prepare_presentation(s,'UTC')['cosecant']['recent_break'])
    assert summary['Return Target']==('Recorded title' if title else 'Title not recorded')
    assert summary['Return Confirmation']=='Confirmed'


@pytest.mark.parametrize('token',['', '   ', None, 12])
def test_invalid_confirmation_token(token):
    rows=break_rows();mutate_payload(rows,-1,evidence_token=token)
    b=project_cosecant(snapshot(breaks=rows))[0]
    assert b['status']=='UNAVAILABLE'


@pytest.mark.parametrize('change',['missing_start','missing_confirmation_start','order','scope','clock','target_scope','sequence_gap','schema','proof_start'])
def test_invalid_cosecant_chain(change):
    rows=break_rows(extension=True)
    if change=='missing_start':rows.pop(0)
    if change=='missing_confirmation_start':rows.pop(-2)
    if change=='order':mutate_payload(rows,-1,effective_monotonic_ns=420*NS)
    if change=='scope':mutate_payload(rows,-1,study_block_id='another-block')
    if change=='clock':mutate_payload(rows,-1,observed_monotonic_ns=1)
    if change=='target_scope':
        p=json.loads(rows[0]['payload_json']);p['return_target']['study_context_token']='another';rows[0]['payload_json']=json.dumps(p)
    if change=='sequence_gap':rows.pop(2)
    if change=='schema':mutate_payload(rows,-1,schema_version='unknown')
    if change=='proof_start':mutate_payload(rows,-2,evidence_token='')
    assert project_cosecant(snapshot(breaks=rows))[0]['status']=='UNAVAILABLE'


def test_duplicate_session_sequence_rejected():
    assert all(b['status']=='UNAVAILABLE' for b in project_cosecant(snapshot(breaks=break_rows('a')+break_rows('b'))))


def test_lost_and_cancelled_are_distinct():
    for outcome, expected in [('lost','In progress'),('cancelled','Break Cancelled')]:
        s=snapshot(breaks=break_rows(outcome=outcome));b=project_cosecant(s)[0]
        assert b['status']=='AVAILABLE'
        summary=dict(prepare_presentation(s,'UTC')['cosecant']['recent_break'])
        assert summary['Outcome']==expected
        assert summary['Return Confirmation']==('Interrupted' if outcome=='lost' else 'Not recorded')


def test_monitor_sample_can_precede_due_stage_dispatch_clock():
    rows=break_rows()
    # advance() dispatches a milestone, then Monitor passes its earlier sample.
    mutate_payload(rows,3,observed_monotonic_ns=422*NS+1)
    rows[3]['occurred_monotonic_ns']=422*NS+1
    assert project_cosecant(snapshot(breaks=rows))[0]['status']=='AVAILABLE'


def test_restart_requires_a_fresh_three_second_chain():
    rows=break_rows()
    confirmed=rows.pop()
    restart=dict(rows[-1],id=6,sequence=6,kind='RETURN_CONFIRMATION_RESTARTED',occurred_monotonic_ns=424*NS)
    p=json.loads(restart['payload_json']);p.update(sequence=6,kind=restart['kind'],from_state='RETURN_CONFIRMING',
        effective_monotonic_ns=424*NS,observed_monotonic_ns=424*NS,evidence_token='new-start')
    restart['payload_json']=json.dumps(p);rows.append(restart)
    confirmed.update(id=7,sequence=7,occurred_monotonic_ns=427*NS)
    mutate_payload([confirmed],0,sequence=7,effective_monotonic_ns=427*NS,observed_monotonic_ns=427*NS)
    rows.append(confirmed)
    assert project_cosecant(snapshot(breaks=rows))[0]['status']=='AVAILABLE'
    mutate_payload(rows,-1,effective_monotonic_ns=425*NS)
    assert project_cosecant(snapshot(breaks=rows))[0]['status']=='UNAVAILABLE'


def study_event():
    return dict(id=1,session_id=1,study_block_id=BLOCK,action='STARTED',created_at_utc='2026-09-30T00:00:00Z',
                payload_json=json.dumps(dict(block_id=BLOCK,generation=1,elapsed_seconds=10,subject='Study',task='Task')))


def test_structured_scope_resolution_and_deep_immutability():
    s=snapshot(secant_rows(),tables={'study_events':EvidenceTable((study_event(),),'AVAILABLE')})
    other=snapshot(sid=2)
    assert resolve_scope((s,other)).session_id==2
    assert resolve_scope((s,other),session_id=1).session_id==1
    assert resolve_scope((s,other),secant_identity=(1,CONTEXT,'episode')).session_id==1
    assert resolve_scope((s,other),study_identity=(1,BLOCK,1)).session_id==1
    scope=resolve_scope((s,),session_id=1)
    with pytest.raises(FrozenInstanceError):scope.session_id=2
    with pytest.raises(TypeError):scope.snapshot.tables['sessions'].rows[0]['id']=2
    with pytest.raises(TypeError):scope.snapshot.recorder_receipts.rows[0]['attached_session_ids'][0]=2


@pytest.mark.parametrize('kwargs',[{'session_id':True},{'session_id':0},{'session_id':999},
    {'secant_identity':(1,CONTEXT,'stale')},{'study_identity':(1,BLOCK,2)},
    {'study_identity':(1,BLOCK,True)},{'secant_identity':'SEC-30092026-01'},
    {'session_id':1,'secant_identity':(1,CONTEXT,'episode')}])
def test_invalid_stale_scope_never_falls_back(kwargs):
    with pytest.raises(ValueError):resolve_scope((snapshot(secant_rows()),),**kwargs)


class Signal:
    def connect(self, callback):self.callback=callback


class View:
    refresh_requested=Signal()
    def __getattr__(self,name):return lambda *args,**kwargs: None


def test_integration_preserves_valid_history_and_resolves_fresh_scope():
    s=snapshot(secant_rows());bad=snapshot(sid=2,tables={'study_events':EvidenceTable((),'UNAVAILABLE')})
    integration=DashboardIntegration(View(),'unused',lambda:1,lambda:'UTC')
    with patch('SECANT.dashboard_integration.read_corpus',return_value=(s,bad)):
        integration.refresh()
        assert len(integration.last_model['secant_archive'])==1
        assert integration.read_parent_scope().session_id==1
    with patch('SECANT.dashboard_integration.read_corpus',return_value=(bad,)):
        with pytest.raises(ValueError):integration.read_parent_scope(secant_identity=(1,CONTEXT,'episode'))


def test_missing_data_section_isolation():
    failed={'study_events':EvidenceTable((),'UNAVAILABLE')}
    m=prepare_presentation(snapshot(secant_rows(),break_rows(),tables=failed),'UTC')
    assert m['study_facts']['status']=='UNAVAILABLE'
    assert m['secant_facts'][0].summary_eligible and m['cosecant_facts'][0]['status']=='AVAILABLE'
    assert dict(m['cosecant']['recent_break'])['Return Confirmation']=='Confirmed'
    empty=prepare_presentation(snapshot(),'UTC')
    assert dict(empty['cosecant']['recent_break'])['Outcome']=='No data'


def test_readers_never_create_missing_database(tmp_path):
    path=tmp_path/'missing.db'
    s=read_snapshot(path,session_id=1)
    assert all(t.status=='UNAVAILABLE' for t in s.tables.values()) and not path.exists()
    with pytest.raises(sqlite3.OperationalError):read_corpus(path)
    assert not path.exists()


def test_readonly_legacy_database_and_receipt_snapshot(tmp_path):
    path=tmp_path/'synthetic.db'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE sessions (id INTEGER PRIMARY KEY)');c.execute('INSERT INTO sessions VALUES(1)')
        c.execute('CREATE TABLE myelin_meta (key TEXT,value TEXT)')
        c.execute('INSERT INTO myelin_meta VALUES(?,?)',('passive_recorder:v1:run:run',json.dumps(receipt())))
    before=path.read_bytes()
    s=read_snapshot(path,session_id=1);corpus=read_corpus(path)
    assert s.tables['secant_events'].status=='NOT_RECORDED'
    assert s.recorder_receipts.status=='AVAILABLE' and corpus[0].recorder_receipts.rows[0]['writer_state']=='CLOSED'
    assert path.read_bytes()==before


def test_bad_child_schema_does_not_erase_parent_or_other_sections(tmp_path):
    path=tmp_path/'synthetic_bad_child.db'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE sessions (id INTEGER PRIMARY KEY)');c.execute('INSERT INTO sessions VALUES(1)')
        c.execute('CREATE TABLE secant_events (bad TEXT)');c.execute("INSERT INTO secant_events VALUES('bad')")
    before=path.read_bytes()
    s=read_corpus(path)[0]
    assert s.tables['secant_events'].status=='UNAVAILABLE'
    assert s.tables['sessions'].status=='AVAILABLE'
    assert s.tables['cosecant_events'].status=='NOT_RECORDED'
    assert path.read_bytes()==before
