"""Task-scoped offscreen capture for the SECANT map color pass."""
import json
import importlib.util
import os
import sys
from pathlib import Path

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT.parent / 'PASSIVE_RECORDER_IMPLEMENTATION_20260926' / 'test_dependencies')]

from PyQt6.QtWidgets import QApplication, QFrame, QLabel
from PyQt6.QtGui import QFontDatabase
if '--baseline-view' in sys.argv:
    import SECANT
    demo_spec = importlib.util.spec_from_file_location('SECANT.dashboard_demo', Path(__file__).parent / 'source_backup' / 'dashboard_demo.py')
    baseline_demo = importlib.util.module_from_spec(demo_spec)
    demo_spec.loader.exec_module(baseline_demo)
    sys.modules['SECANT.dashboard_demo'] = baseline_demo
    SECANT.dashboard_demo = baseline_demo
    spec = importlib.util.spec_from_file_location('baseline_dashboard_view', Path(__file__).parent / 'source_backup' / 'dashboard_view.py')
    view = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(view)
else:
    from SECANT import dashboard_view as view
SecantCosecantDashboard = view.SecantCosecantDashboard
FlowConnector = view.FlowConnector
from SECANT.dashboard_projection import _secant_flow_tone, _cosecant_flow_tone

FIXTURE = ROOT.parent / 'PHASE3_COMPLETION_20260927' / 'session202_presentation.json'
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
p = json.loads(FIXTURE.read_text(encoding='utf-8'))
if '--semantic' in sys.argv:
    # Cached Session 202 presentation predates this tone pass. Recolor only its
    # sixth-tuple tone slot, preserving all captured facts and route data.
    def color_nodes(nodes):
        colored = []
        for node in nodes:
            category, title, detail, stamp, _, gap = node
            if category == 'SECANT':
                if title == 'SECANT Displayed':
                    event = {'event_name': 'SECANT_DISPLAYED', 'stage': int(detail[-1]), 'reason': None}
                else:
                    identity = {
                        'Episode Founded': 'SECANT_EPISODE_FOUNDED',
                        'Return to Study Selected': 'SECANT_ACTION_INTENT',
                        'Return Process Started': 'SECANT_RETURN_STARTED',
                        'Return Verified': 'SECANT_RETURN_VERIFIED',
                        'Recovery Interrupted': 'SECANT_RECOVERY_INTERRUPTED',
                        'Recovery Closed': 'SECANT_RECOVERY_CLOSED',
                        'Episode Closed': 'SECANT_EPISODE_CLOSED',
                    }
                    event = {'event_name': identity[title], 'stage': None,
                             'reason': 'recovered' if title == 'Episode Closed' and detail == 'Recovered' else None}
                tone = _secant_flow_tone(event)
            elif category == 'COSECANT':
                tone = _cosecant_flow_tone(title.upper().replace(' ', '_'))
            else:
                tone = node[4]
            colored.append([category, title, detail, stamp, tone, gap])
        return colored

    for key in ('landing', 'overview'):
        p[key]['journey'] = color_nodes(p[key]['journey'])
    for key in ('episodes', 'distraction_history', 'cosecant'):
        p[key]['flow'] = color_nodes(p[key]['flow'])
    for item in p['secant_archive']:
        item['map_nodes'] = color_nodes(item['map_nodes'])
app = QApplication([])
for font in ('segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf', 'consola.ttf'):
    assert QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font) >= 0, font
w = SecantCosecantDashboard()
w.resize(1600, 850)
w.set_presentation_context(captions=p['context'])
for name in ('landing', 'overview', 'episodes', 'distraction_history', 'study_history', 'study_evidence', 'cosecant'):
    getattr(w, 'set_' + name + '_data')(**p[name])
w.set_secant_episode_archive(tuple(p['secant_archive']), preserve_state=True)
w.set_study_session_archive(tuple(p['study_archive']), preserve_state=True)
w.show()

def settle():
    for _ in range(12):
        app.processEvents()

def capture(name):
    settle()
    assert w.size().width() == 1600 and w.size().height() == 850
    w.grab().save(str(out / (name + '.png')))
    panel = {
        'landing': w.landing.recent_flow,
        'overview': w.analysis.overview_flow,
        'episodes': w.analysis.episodes_flow,
        'distraction_history': w.analysis.distraction_flow,
        'cosecant': w.analysis.cosecant_flow,
        'past_secant_episodes': w.analysis.historical_secant_flow,
        'past_study_sessions': w.analysis.historical_study_flow,
    }[name]
    host = panel.scroll.widget()
    cards = [f for f in host.findChildren(QFrame) if f.objectName() == 'flowNode']
    connectors = host.findChildren(FlowConnector)
    return {
        'cards': [{'tone': c.property('tone'), 'size': [c.width(), c.height()],
                   'labels': [l.text() for l in c.findChildren(QLabel)]} for c in cards],
        'connectors': [{'caption': c.caption, 'width': c.width(), 'height': c.height()} for c in connectors],
        'page_horizontal_overflow': w.analysis.body.horizontalScrollBar().maximum() if hasattr(w, 'analysis') and w.analysis.isVisible() else None,
    }

report = {'landing': capture('landing')}
w.open_analysis()
for route in ('overview', 'episodes', 'distraction_history', 'cosecant', 'past_secant_episodes', 'past_study_sessions'):
    w.analysis.select_route(route)
    settle()
    if route == 'past_secant_episodes':
        w.analysis._secant_date_picker.setCurrentIndex(1)
        w.analysis._secant_archive_panel.table.selectRow(0)
        w.analysis.view_secant_episode_flow()
    if route == 'past_study_sessions':
        w.analysis._study_date_picker.setCurrentIndex(1)
        w.analysis._study_archive_panel.table.selectRow(0)
        w.analysis.view_study_session_map()
    report[route] = capture(route)
(out / 'geometry_and_nodes.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
w.close()
