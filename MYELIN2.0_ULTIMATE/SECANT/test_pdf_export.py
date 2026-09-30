"""Single-parent PDF contracts, layout stress and real Qt button coordination."""
from dataclasses import replace
from io import BytesIO
from pathlib import Path
import json
import os
import time
from unittest.mock import patch

import pytest
from pypdf import PdfReader
from PyQt6.QtWidgets import QApplication, QPushButton, QMessageBox
from PyQt6.QtCore import QThreadPool

from .test_dashboard_corrections import (snapshot,secant_rows,break_rows,receipt,seal,
    EvidenceTable,study_event,title_metadata,BLOCK,TOKEN,CONTEXT,NS,mutate_payload)
from .dashboard_evidence import resolve_scope
from .dashboard_projection import prepare_presentation
from .pdf_model import build_report,ReportNotReady,Text,Table,Flow,Section
from .pdf_renderer import render_report,export_report,publish_pdf
from .dashboard_view import SecantCosecantDashboard
from .pdf_controller import PdfController


def scope(rows=None,breaks=None,quality=None,tables=None):
    s=snapshot(secant_rows() if rows is None else rows,break_rows(extension=True,title=True) if breaks is None else breaks,
               quality=quality,tables=tables)
    aliases=[]
    if s.rows('secant_events'):aliases.append(dict(entity_kind='SECANT',native_id='episode',alias_version=1,
        founding_utc_date='2026-09-30',daily_ordinal=1,display_alias='SEC-30092026-01',founding_at_utc='2026-09-30T00:00:01Z'))
    for n,b in enumerate(dict.fromkeys(r['break_id'] for r in s.rows('cosecant_events')),1):
        aliases.append(dict(entity_kind='COSECANT',native_id=b,alias_version=1,founding_utc_date='2026-09-30',
            daily_ordinal=n,display_alias=f'COSEC-30092026-{n:02d}'))
    values=dict(s.tables);values['presentation_aliases']=EvidenceTable(tuple(aliases),'AVAILABLE')
    return resolve_scope((replace(s,tables=values),),session_id=1)


def all_text(model):
    return '\n'.join(p.extract_text() for p in PdfReader(BytesIO(render_report(model).data)).pages)


@pytest.mark.parametrize('stage',[1,2,3])
def test_stages_reconcile(stage):
    s=scope(rows=secant_rows(stage));m=build_report(s)
    assert dict(m.counts)['Validated SECANT episodes']==1
    t=all_text(m);assert f'SECANT-{stage} Displayed' in t and 'Recovered episodes' in t
    assert 'SEC-30092026-01' in t and 'COSEC-30092026-01' in t


def test_dedicated_cover_and_exact_dashboard_summary_values():
    s=scope();m=build_report(s);d=prepare_presentation(s.snapshot,'UTC')
    assert dict(m.dashboard_metrics)['Study']==d['study_history']['metrics']
    assert dict(m.dashboard_metrics)['SECANT']==d['episodes']['metrics']
    assert dict(m.dashboard_metrics)['COSECANT']==d['cosecant']['metrics']
    reader=PdfReader(BytesIO(render_report(m).data))
    cover=reader.pages[0].extract_text()
    page=' '.join(reader.pages[1].extract_text().split())
    for _,metrics in m.dashboard_metrics:
        for label,value,_ in metrics:assert label in page and value in page
    assert 'STUDY RECOVERY REPORT' in cover and 'GUIDE - RECOVER - FOCUS' in cover
    assert 'CAPTURED EPISODES' not in cover and 'Dashboard summary' in page
    assert 'Session / evidence summary' in reader.pages[2].extract_text()


@pytest.mark.parametrize('change',[{'writer_state':'ACTIVE'},{'writer_state':'DRAINING'},
    {'pending':1},{'final_flush_committed':False},{'writer_state':'FAILED'},{'closed_at_utc':None}])
def test_pending_or_failed_scope_never_renders(change):
    with pytest.raises(ReportNotReady):build_report(scope(quality=receipt(**change)))


def test_gap_disclosed_without_validated_claim():
    rows=secant_rows();rows[0]['recording_quality']='RECORDING_GAP_DETECTED'
    m=build_report(scope(rows=rows,quality=receipt(coverage='RECORDING_GAP_DETECTED',dropped=1,gap_reasons=['overflow'])))
    assert dict(m.counts)['Validated SECANT episodes']==0
    text=all_text(m);assert 'Excluded from validated summaries' in text and 'recorder' in text


@pytest.mark.parametrize('case',['digest','chain','proof','duplicate','incomplete','interrupted','lost','cancelled','titleless','no_data','unavailable'])
def test_factual_edge_cases(case):
    rows=secant_rows();co=break_rows(extension=True,title=True);tables={}
    if case=='digest':rows[0]['fact_digest']='0'*64
    if case=='chain':rows.pop(-2)
    if case=='proof':mutate_payload(co,-1,evidence_token='')
    if case=='duplicate':rows.append(dict(rows[0]))
    if case=='incomplete':rows=rows[:-2]
    if case=='interrupted':
        rows=rows[:-2];r=dict(rows[-1],event_name='SECANT_RECOVERY_INTERRUPTED',occurred_monotonic_ns=16*NS,reason='evidence_gap',evidence_id='');rows.append(seal(r))
    if case=='lost':co=break_rows(outcome='lost')
    if case=='cancelled':co=break_rows(outcome='cancelled')
    if case=='titleless':co=break_rows()
    if case=='no_data':rows=[];co=[]
    if case=='unavailable':tables={'study_events':EvidenceTable((),'UNAVAILABLE')}
    m=build_report(scope(rows=rows,breaks=co,tables=tables));t=all_text(m)
    if case in ('digest','chain','duplicate'):assert dict(m.counts)['Validated SECANT episodes']==0 and 'Unavailable' in t
    if case=='proof':assert dict(m.counts)['Validated COSECANT breaks']==0 and 'Unavailable' in t
    if case=='no_data':assert 'No data' in t
    if case=='unavailable':assert 'Unavailable' in t and dict(m.counts)['Validated SECANT episodes']==1
    if case=='titleless':assert 'Title not recorded' in t
    if case=='lost':assert 'Return confirmation lost' in t
    if case=='cancelled':assert 'Break cancelled' in t


def test_session_wide_sequences_preserved_in_pdf():
    m=build_report(scope(breaks=break_rows('a',1)+break_rows('b',7)+break_rows('c',13)))
    assert dict(m.counts)['Validated COSECANT breaks']==3
    assert 'COSEC-30092026-03' in all_text(m)


def stress_model():
    m=build_report(scope())
    long='BEGIN-LONG '+('Café naïve Ω αβ 研究 😀 '+('longword'*20)+' ')*60+' END-LONG'
    section=Section('Long content / Unicode validation','study',(
        Table('Study block 1 / long caption',('Role','Recorded caption'),(.15,.85),(('PRIMARY',long),('LATER','END-OF-TABLE'))),
        Flow('Study block 1 / connector validation',(
            ('PRIMARY','Resource A','Study-aligned','Recorded','green','Direct observed change'),
            ('LATER','Resource B','Study-aligned','Recorded','green','Interruption recorded'),
            ('PRIMARY','Resource A','Study-aligned','Recorded','green','Evidence gap'),
            ('LATER','Resource C','Study-aligned','Recorded','green',''))),
        Table('Many records',('Number','Evidence'),(.1,.9),tuple((str(i),f'RECORD-{i:03d}') for i in range(120)))))
    return replace(m,sections=(section,))


def study_fixture_scope():
    """Persisted-shaped visits: direct jump, omitted distraction, then a gap."""
    domain=dict(session_id=1,study_block_id=BLOCK,study_generation=1,study_context_token=TOKEN)
    visits=[];observations=[];resources=[];boundaries=[]
    keys=('a','b','off','a','c')
    for i,key in enumerate(keys,1):
        at=i*NS;oid=f'observation-{i}';identity=dict(key=key,kind='WINDOW',version=1,normalized_title=f'Resource {key}')
        aligned=key!='off';classification='STUDY_ALIGNED' if aligned else 'DISTRACTION'
        authority=dict(resource=identity,classification=classification,measured_classification=classification,
                       measured_confidence=.9,confidence=.9,user_confirmation='NONE')
        visits.append(dict(domain,interval_id=i,capture_id='capture',span_ordinal=i,resource_key=key,
            interval_extension_version=1,first_observed_monotonic_ns=at,last_observed_monotonic_ns=at,
            observation_count=1,supported_duration_ns=0,first_observation_id=oid,last_observation_id=oid,
            continuity_status='SINGLE_OBSERVATION',continuity_max_gap_ns=2*NS))
        observations.append(dict(domain,interval_id=i,interval_capture_id='capture',resource_key=key,
            extension_version=1,identity_json=json.dumps(identity),authority_json=json.dumps(authority),
            observed_monotonic_ns=at,observation_id=oid,observation_sequence=i,evidence_id=f'e-{i}',kind='OBSERVATION'))
        if aligned and key not in [r['resource_key'] for r in resources]:
            resources.append(dict(domain,resource_key=key,contract_version=1,identity_kind='WINDOW',identity_version=1,
                identity_json=json.dumps(identity),role='PRIMARY' if key=='a' else 'LATER',
                first_aligned_monotonic_ns=at,qualified_monotonic_ns=at,
                first_aligned_at_utc='2026-09-30T00:00:01Z',qualified_at_utc='2026-09-30T00:00:01Z'))
        if 1<i<5:
            boundaries.append(dict(domain,contract_version=1,from_observation_id=f'observation-{i-1}',
                to_observation_id=oid,from_resource_key=keys[i-2],to_resource_key=key,
                continuity='CONTIGUOUS_OBSERVED_CHANGE',gap_reasons_json='[]',capture_gap_reasons_json='[]',
                from_observed_monotonic_ns=at-NS,to_observed_monotonic_ns=at,
                from_observation_ordinal=i-1,to_observation_ordinal=i,
                from_observed_at_utc=f'2026-09-30T00:00:0{i-1}Z',to_observed_at_utc=f'2026-09-30T00:00:0{i}Z'))
    tables={name:EvidenceTable(tuple(rows),'AVAILABLE') for name,rows in (
        ('study_events',[study_event()]),('study_resources',resources),('study_resource_intervals',visits),
        ('study_resource_observation_evidence',observations),('study_resource_boundaries',boundaries))}
    return scope(tables=tables)


def test_recorded_study_connectors_and_dashboard_evidence():
    s=study_fixture_scope();dashboard=prepare_presentation(s.snapshot,'UTC');facts=dashboard['study_facts']
    assert facts['status']=='AVAILABLE'
    assert [j['connector'] for j in facts['jumps']]==['Direct observed change','Interruption recorded','Evidence gap','']
    m=build_report(s);text=all_text(m)
    for label in ('Direct observed change','Interruption recorded','Evidence gap','PRIMARY','LATER','90%',
                  'lifecycle chronology','Started','Resource off'):
        assert label in text
    study_section=next(section for section in m.sections if section.title=='Study / shared context')
    attrs=next(block for block in study_section.blocks if isinstance(block,Table) and block.title=='Dashboard Study evidence attributes')
    assert attrs.rows==dashboard['study_evidence']['attributes']


def test_long_rows_unicode_and_continuation():
    m=stress_model();result=render_report(m);reader=PdfReader(BytesIO(result.data));text='\n'.join(p.extract_text() for p in reader.pages)
    assert 'BEGIN-LONG' in text and 'END-LONG' in text and 'END-OF-TABLE' in text
    assert 'RECORD-119' in text and 'CONTINUED' in text
    assert 'Café' in text and 'Rendering substitutions' in text and result.substitutions
    assert 'CONTINUED' not in reader.pages[2].extract_text().split('Recorded caption')[0]
    for page in reader.pages:
        assert abs(float(page.mediabox.width)-595.28)<1 and abs(float(page.mediabox.height)-841.89)<1
    # Source text remains untouched despite unsupported glyph substitution.
    assert '研究 😀' in m.sections[0].blocks[0].rows[0][1]


def test_atomic_save_collision_and_failure(tmp_path):
    rendered=render_report(build_report(scope()));dest=tmp_path/'report.pdf'
    publish_pdf(rendered,dest);original=dest.read_bytes()
    with pytest.raises(FileExistsError):publish_pdf(rendered,dest)
    with patch('SECANT.pdf_renderer.os.replace',side_effect=PermissionError('locked')):
        with pytest.raises(PermissionError):publish_pdf(rendered,dest,overwrite=True)
    assert dest.read_bytes()==original and not list(tmp_path.glob('.myelin-study-*'))
    with pytest.raises(ValueError):publish_pdf(rendered,tmp_path/'absent'/'bad.pdf')
    publish_pdf(rendered,dest,overwrite=True)


@pytest.mark.skipif(os.name!='nt',reason='Windows file sharing contract')
def test_real_windows_locked_destination(tmp_path):
    import ctypes
    from ctypes import wintypes
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    k.CreateFileW.restype=wintypes.HANDLE;k.CloseHandle.argtypes=[wintypes.HANDLE]
    dest=tmp_path/'locked.pdf';dest.write_bytes(b'original')
    handle=k.CreateFileW(str(dest),0x80000000,1,None,3,0,None)
    assert handle not in (None,ctypes.c_void_p(-1).value)
    try:
        with pytest.raises(PermissionError):publish_pdf(render_report(build_report(scope())),dest,overwrite=True)
        assert dest.read_bytes()==b'original'
    finally:k.CloseHandle(handle)
    assert not list(tmp_path.glob('.myelin-study-*'))


@pytest.fixture(scope='module')
def app():
    app=QApplication.instance() or QApplication([])
    yield app
    QThreadPool.globalInstance().waitForDone(20000)


def wait(app,controller):
    deadline=time.monotonic()+20
    while controller.busy and time.monotonic()<deadline:
        app.processEvents();time.sleep(.005)
    app.processEvents();assert not controller.busy


@pytest.mark.parametrize('case',['save','cancel','overwrite_yes','overwrite_no','pending','stale','repeat','current_race'])
def test_real_button_controller(app,tmp_path,case):
    view=SecantCosecantDashboard();dest=tmp_path/'button.pdf';s=scope();requests=[];current=[1]
    if case.startswith('overwrite'):dest.write_bytes(b'old')
    def read(**selection):
        requests.append(selection)
        if case=='stale':raise ValueError('Stale selection')
        return scope(quality=receipt(writer_state='ACTIVE')) if case=='pending' else s
    controller=PdfController(view,read,lambda:'UTC',lambda:current[0])
    view.export_requested.connect(controller.request)
    choice='' if case=='cancel' else str(dest)
    answer=QMessageBox.StandardButton.No if case=='overwrite_no' else QMessageBox.StandardButton.Yes
    with patch('SECANT.pdf_controller.QFileDialog.getSaveFileName',return_value=(choice,'PDF')) as dialog, \
         patch('SECANT.pdf_controller.QMessageBox.question',return_value=answer), \
         patch('SECANT.pdf_controller.QMessageBox.information'),patch('SECANT.pdf_controller.QMessageBox.warning'):
        button=view.findChild(QPushButton,'dashboardExportPdf');button.click();current[0]=2
        wait(app,controller)
        assert requests[0]['session_id']==1 and requests[0]['use_current'] is False
        if case in ('pending','stale'):assert not dialog.called and not dest.exists()
        elif case=='cancel':assert not dest.exists()
        elif case=='overwrite_no':assert dest.read_bytes()==b'old'
        else:assert dest.read_bytes().startswith(b'%PDF-')
        if case=='repeat':button.click();wait(app,controller);assert controller.last_result
    view.close()


@pytest.mark.parametrize('kind',['secant','study'])
def test_historical_button_emits_structured_identity(app,kind):
    view=SecantCosecantDashboard();events=[];view.export_requested.connect(events.append)
    m=prepare_presentation(scope(tables={'study_events':EvidenceTable((study_event(),),'AVAILABLE')}).snapshot,'UTC')
    a=view.analysis
    if kind=='secant':
        a.route='past_secant_episodes';a._secant_filtered=m['secant_archive'];a.selected_secant_episode_id='episode'
    else:
        a.route='past_study_sessions';a._study_filtered=m['study_archive'];a.selected_study_demo_key=m['study_archive'][0]['demo_key']
    view.findChild(QPushButton,'dashboardExportPdf').click()
    assert events==[{kind+'_identity':(1,CONTEXT,'episode') if kind=='secant' else (1,BLOCK,1)}]
    view.close()
