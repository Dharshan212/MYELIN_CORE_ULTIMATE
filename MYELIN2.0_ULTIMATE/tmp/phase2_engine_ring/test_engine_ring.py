"""Real in-memory organ authorities -> existing Qt signals -> existing ring."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import time
import pytest
from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QWidget
from CONTROL_STATION import application as ui
from CONTROL_STATION.controller import EngineStatus
from CONTROL_STATION.lifecycle import LifecycleController
from MINE import mine as m
from COSINE import cosine as c
import test_contextual_lock as harness

NS = 10**9
OUT = Path(__file__).resolve().parent
class Sink:
    def __init__(self): self.events = []
    def append_mine_events(self, events): self.events.extend(events); return True
    def append_cosine_events(self, events): self.events.extend(events); return True

class Engine(harness.Engine):
    pause_eligibility_changed = pyqtSignal(object)
    sine_watch_status_changed = pyqtSignal(object)
    mine_watch_status_changed = pyqtSignal(object)
    cosine_live_status_changed = pyqtSignal(object)
    secant_projection_changed = pyqtSignal(object)
    study_view_changed = pyqtSignal(object)
    current_session_id_changed = pyqtSignal(object)
    sid = 41
    def pause_control_allowed(self): return False
    def current_session_id(self): return self.sid

@pytest.fixture(scope='session')
def app():
    value = QApplication.instance() or QApplication([])
    for name in ('segoeui.ttf', 'segoeuib.ttf', 'consola.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/'+name)
    value.setStyleSheet(ui.build_application_stylesheet())
    return value

@pytest.fixture
def station(app):
    parent = QWidget()
    engine = Engine(parent)
    lifecycle = LifecycleController(engine=engine, parent=parent)
    profiles = SimpleNamespace(all_profiles=lambda: [SimpleNamespace(label='General', key='general')],
                               set_active=lambda key: False)
    page = ui.ControlPage(engine=engine, lifecycle=lifecycle, profiles=profiles)
    engine.sine_watch_status_changed.connect(page.render_sine)
    engine.mine_watch_status_changed.connect(page.render_mine)
    engine.cosine_live_status_changed.connect(page.render_cosine)
    engine.engine_stopped.connect(page.reset_runtime_presentation)
    engine.current_session_id_changed.connect(lambda sid: page.reset_runtime_presentation() if sid is None else None)
    engine.transition(EngineStatus.ACTIVE)
    errors = []
    import sys
    previous = sys.excepthook
    sys.excepthook = lambda *error: errors.append(str(error[1]))
    yield engine, page
    sys.excepthook = previous
    assert not errors, errors
    for timer in page.findChildren(QTimer): timer.stop()
    page.deleteLater(); parent.deleteLater()

class Timeline:
    def __init__(self, family):
        self.family, self.ns, self.seq, self.sink = family, NS, 0, Sink()
        self.runtime = m.MineRuntime(event_sink=self.sink) if family == 'mine' else c.CosineRuntime(event_sink=self.sink)
        self.runtime.bind_parent_session(41)
    def observe(self, seconds=0, focus=False, neutral=False):
        self.ns += int(seconds*NS); self.seq += 1
        if self.family == 'mine':
            kind = m.MineObservationKind.NEUTRAL if neutral else m.MineObservationKind.FOCUS if focus else m.MineObservationKind.MESSAGING
            observation = m.MineObservation(kind, self.ns, self.seq, int(seconds*NS),
                '' if focus or neutral else 'whatsapp', '' if focus or neutral else 'WhatsApp')
        else:
            platform = None if focus or neutral else c.certify_platform_evidence(
                process_name='netflix.exe', process_id=123, hwnd=456, observed_monotonic_ns=self.ns)
            observation = c.CosineObservation(platform, focus, False, self.ns, self.seq, int(seconds*NS))
        self.runtime.observe(observation)
        return self.snapshot()
    def snapshot(self): return self.runtime.snapshot(now_ns=self.ns)
    def command(self, kind, request_id, choice=None, minutes=None):
        self.ns += 1_000_000
        generation = self.snapshot().generation
        command = (m.MineCommand(kind, generation, request_id, self.ns, choice, minutes)
                   if self.family == 'mine' else c.CosineCommand(kind, generation, request_id, choice, self.ns, minutes))
        result = self.runtime.submit_command(command)
        assert result.accepted, result.message
        return result.snapshot
    def active_intervention(self):
        self.observe()
        self.observe(600 if self.family == 'mine' else 300)
        snapshot = self.snapshot()
        if self.family == 'mine':
            self.request = snapshot.mine1_request_id
            return self.command(m.MineCommandKind.MINE1_DISPLAYED, self.request)
        self.request = snapshot.checkin_request_id
        return self.command(c.CommandKind.INTENT_GATE_DISPLAYED, self.request)
    def allowance(self):
        self.active_intervention()
        if self.family == 'mine':
            self.command(m.MineCommandKind.MINE1_ACTION, self.request, m.MineChoice.ITS_IMPORTANT)
            return self.command(m.MineCommandKind.IMPORTANT_DURATION_SUBMITTED, self.request, minutes=5)
        self.command(c.CommandKind.INTENT_ACTION, self.request, c.CosineChoice.INTENTIONAL_BREAK)
        self.request = self.runtime._duration.request_id
        return self.command(c.CommandKind.DURATION_SUBMITTED, self.request, minutes=10)
    def publish(self, engine):
        getattr(engine, self.family+'_watch_status_changed' if self.family == 'mine' else 'cosine_live_status_changed').emit(self.snapshot())

def test_sine_existing_arc_and_terminal(station):
    engine, page = station
    data = dict(stage=1, phase='ACTIVE', next_deadline_seconds=600,
                stage_2_delay_seconds_applied=600, stage_2_deadline_monotonic_ns=time.monotonic_ns()+600*NS)
    engine.sine_watch_status_changed.emit(data)
    assert page._ring._progress == 0
    data['next_deadline_seconds'] = 300
    engine.sine_watch_status_changed.emit(data)
    assert page._ring._progress == .5
    data['activity_clock_paused'] = True
    engine.sine_watch_status_changed.emit(data)
    assert page._ring._progress == .5
    engine.sine_watch_status_changed.emit(dict(data, phase='RESOLVED', next_deadline_seconds=None))
    assert page._ring._progress == 0
    engine.sine_watch_status_changed.emit(dict(stage=3, phase='PROTECTED_RED', protected_red_active=True))
    assert page._ring._progress == 1
    engine.sine_watch_status_changed.emit(None)
    assert page._ring._progress == 0

@pytest.mark.parametrize('family', ['mine','cosine'])
def test_real_initial_evidence_clock_runs_and_completes(station, family):
    engine, page = station
    timeline = Timeline(family)
    timeline.observe(); timeline.publish(engine)
    timeline.observe(100); timeline.publish(engine)
    assert page._ring._progress == pytest.approx(100/(600 if family == 'mine' else 300))
    timers = len(page.findChildren(QTimer))
    timeline.observe(500 if family == 'mine' else 200); timeline.publish(engine)
    assert timeline.snapshot().timer_progress_fraction is None
    assert page._ring._progress == 0
    assert len(page.findChildren(QTimer)) == timers

@pytest.mark.parametrize('family', ['mine','cosine'])
def test_allowance_completion_pause_hold_and_identity(station, family):
    engine, page = station
    timeline = Timeline(family); timeline.allowance()
    timeline.ns += 30*NS; timeline.publish(engine)
    expected = 30/(300 if family == 'mine' else 600)
    assert page._ring._progress == pytest.approx(expected)
    initial = timeline.snapshot()
    timeline.runtime.set_global_paused(True, timeline.ns)
    timeline.ns += 20*NS; timeline.publish(engine)
    assert page._ring._progress == 0
    timeline.runtime.set_global_paused(False, timeline.ns)
    timeline.publish(engine)
    assert page._ring._progress == pytest.approx(expected)
    key = timeline.runtime.monitor_status(now_ns=timeline.ns).episode_key
    assert timeline.runtime.monitor_hold(episode_key=key, now_ns=timeline.ns)
    timeline.ns += 20*NS; timeline.publish(engine)
    assert page._ring._progress == 0
    assert timeline.runtime.monitor_resume(episode_key=key, now_ns=timeline.ns)
    timeline.publish(engine)
    assert page._ring._progress == pytest.approx(expected)
    after = timeline.snapshot()
    parent_field = 'parent_session_id' if family == 'mine' else 'session_id'
    identity_field = 'mine_episode_id' if family == 'mine' else 'cosine_session_id'
    assert getattr(initial, identity_field) == getattr(after, identity_field)
    assert initial.generation == after.generation
    assert getattr(initial, parent_field) == getattr(after, parent_field)
    timeline.ns += (300 if family == 'mine' else 600)*NS
    timeline.runtime.advance(now_ns=timeline.ns); timeline.publish(engine)
    assert timeline.snapshot().timer_progress_fraction is None
    assert page._ring._progress == 0

@pytest.mark.parametrize('family', ['mine','cosine'])
def test_return_intent_and_recovery_confirmation(station, family):
    engine, page = station
    timeline = Timeline(family); timeline.active_intervention()
    if family == 'mine':
        timeline.command(m.MineCommandKind.MINE1_ACTION, timeline.request, m.MineChoice.I_WILL_COME_BACK)
    else:
        timeline.command(c.CommandKind.INTENT_ACTION, timeline.request, c.CosineChoice.RETURN_INTENTION)
    timeline.observe(); timeline.observe(10); timeline.publish(engine)
    assert page._ring._progress == pytest.approx(10/(795 if family == 'mine' else 300))
    timeline.observe(focus=True); timeline.observe(5, focus=True); timeline.publish(engine)
    assert page._ring._progress == .5
    timeline.observe(5, focus=True); timeline.observe(30, focus=True); timeline.publish(engine)
    assert page._ring._progress == .5
    timeline.observe(30, focus=True); timeline.publish(engine)
    assert timeline.snapshot().phase.value == 'CLOSED'
    assert page._ring._progress == 0

@pytest.mark.parametrize('family', ['mine','cosine'])
@pytest.mark.parametrize('exit_kind', ['STOPPING','STOPPED','EMERGENCY','ERROR','detach','shutdown'])
def test_terminal_fences_and_late_snapshots(station, family, exit_kind):
    engine, page = station
    timeline = Timeline(family); timeline.allowance(); timeline.ns += 30*NS
    timeline.publish(engine); saved = timeline.snapshot()
    assert page._ring._progress > 0
    if exit_kind == 'detach':
        engine.sid = None; engine.current_session_id_changed.emit(None)
    elif exit_kind == 'shutdown':
        page.retire_engine_ring()
    else:
        engine.transition(EngineStatus[exit_kind], active=False)
    assert page._ring._progress == 0
    getattr(engine, 'mine_watch_status_changed' if family == 'mine' else 'cosine_live_status_changed').emit(saved)
    assert page._ring._progress == 0

@pytest.mark.parametrize('family', ['mine','cosine'])
def test_new_session_and_generation_fence(station, family):
    engine, page = station
    timeline = Timeline(family); timeline.allowance(); timeline.ns += 30*NS
    timeline.publish(engine); saved = timeline.snapshot()
    signal = engine.mine_watch_status_changed if family == 'mine' else engine.cosine_live_status_changed
    signal.emit(replace(saved, generation=saved.generation+1, timer_progress_fraction=None))
    assert page._ring._progress == 0
    signal.emit(saved)
    assert page._ring._progress == 0
    engine.transition(EngineStatus.STOPPED, active=False)
    engine.sid = 42
    engine.transition(EngineStatus.ACTIVE)
    signal.emit(saved)
    assert page._ring._progress == 0

def test_or_contract_and_excluded_organs(station):
    engine, page = station
    mine, cosine = Timeline('mine'), Timeline('cosine')
    mine.allowance(); cosine.allowance()
    mine.ns += 90*NS; cosine.ns += 120*NS
    mine.publish(engine); cosine.publish(engine)
    assert page._ring._progress == pytest.approx(.3)
    mine.runtime.close(m.MineClosureReason.STOPPED, now_ns=mine.ns); mine.publish(engine)
    assert page._ring._progress == pytest.approx(.2)
    cosine.runtime.close(c.ClosureReason.STOPPED, now_ns=cosine.ns); cosine.publish(engine)
    assert page._ring._progress == 0
    engine.secant_projection_changed.emit({'stage':'SECANT_1','escalation_remaining_ns':60*NS})
    engine.study_view_changed.emit({'state':'BREAK_ACTIVE','seconds_to_next_stage':60})
    page.render({'blacklist': None, 'secant': {'timer_running':True}, 'cosecant': {'timer_running':True},
                 'study': {'timer_running':True}, 'normal_break': {'timer_running':True}})
    assert page._ring._progress == 0

def test_no_visibility_or_episode_inference(station):
    engine, page = station
    for family in ('mine','cosine'):
        timeline = Timeline(family); timeline.active_intervention(); timeline.publish(engine)
        assert timeline.snapshot().timer_progress_fraction is None
        assert page._ring._progress == 0

def test_snapshots_are_readonly_and_no_behavioral_events_added():
    for family in ('mine','cosine'):
        timeline = Timeline(family); timeline.allowance()
        before = [event for event in timeline.sink.events]
        state = dict(timeline.runtime.__dict__)
        for _ in range(3): timeline.snapshot()
        assert timeline.sink.events == before
        assert timeline.runtime.__dict__ == state

@pytest.mark.parametrize('family', ['mine', 'cosine'])
def test_global_pause_is_stationary_and_paused_session_detach_clears(station, family):
    engine, page = station
    timeline = Timeline(family); timeline.allowance(); timeline.ns += 30*NS
    timeline.publish(engine); progress = page._ring._progress
    timeline.runtime.set_global_paused(True, timeline.ns)
    engine.transition(EngineStatus.PAUSED)
    timeline.ns += 60*NS; timeline.publish(engine)
    assert timeline.snapshot().timer_progress_fraction is None
    assert page._ring._progress == progress
    engine.sid = None; engine.current_session_id_changed.emit(None)
    assert page._ring._progress == 0

@pytest.mark.parametrize('family', ['mine', 'cosine'])
def test_unconfirmed_evidence_does_not_drive_ring(station, family):
    engine, page = station
    timeline = Timeline(family); timeline.observe(); timeline.observe(30); timeline.publish(engine)
    assert page._ring._progress > 0
    timeline.observe(1, neutral=True); timeline.publish(engine)
    assert timeline.snapshot().timer_progress_fraction is None
    assert page._ring._progress == 0

@pytest.mark.parametrize('family', ['mine', 'cosine'])
def test_final_callback_recovery_uses_existing_confirmation_counters(station, family):
    engine, page = station
    timeline = Timeline(family); timeline.allowance()
    timeline.ns += (300 if family == 'mine' else 600)*NS
    timeline.runtime.advance(now_ns=timeline.ns)
    pending = timeline.snapshot()
    if family == 'mine':
        timeline.command(m.MineCommandKind.MINE2_DISPLAYED, pending.mine2_request_id)
    else:
        timeline.command(c.CommandKind.FINAL_CALLBACK_DISPLAYED, pending.final_callback_request_id)
    timeline.publish(engine)
    assert page._ring._progress == 0  # Popup alone is not a timer.
    timeline.observe(focus=True); timeline.observe(1, focus=True); timeline.publish(engine)
    assert page._ring._progress == pytest.approx(1/(3 if family == 'mine' else 10))
    timeline.observe(2, focus=True); timeline.publish(engine)
    assert timeline.snapshot().phase.value in {'RETURN_VERIFYING', 'FINAL_CALLBACK_HIDDEN_VERIFYING'}
    timeline.observe(5, focus=True); timeline.publish(engine)
    assert page._ring._progress == pytest.approx(.5 if family == 'mine' else .8)
    timeline.runtime.shutdown(now_ns=timeline.ns); timeline.publish(engine)
    assert page._ring._progress == 0

def test_visual_existing_arc(station):
    engine, page = station
    page.resize(1450, 1100); page.show(); QTest.qWait(10)
    samples = []
    for family in ('mine','cosine'):
        timeline = Timeline(family); timeline.allowance()
        for seconds in (30, 60):
            timeline.ns += seconds*NS; timeline.publish(engine)
            assert page._ring._progress == pytest.approx(timeline.snapshot().timer_progress_fraction)
            page._ring.grab().save(str(OUT/f'{family}_{seconds}.png'))
            samples.append({'organ':family,'progress':page._ring._progress})
        timeline.runtime.close(m.MineClosureReason.STOPPED if family == 'mine' else c.ClosureReason.STOPPED,
                               now_ns=timeline.ns)
        timeline.publish(engine)
    (OUT/'ring_visual_results.json').write_text(json.dumps(samples, indent=2))
