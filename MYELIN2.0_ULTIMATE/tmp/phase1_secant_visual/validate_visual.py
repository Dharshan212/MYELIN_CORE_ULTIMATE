"""Phase 1: real Qt shell/theme/router, inert engine, read-only evidence."""
from pathlib import Path
from types import SimpleNamespace
import hashlib
import importlib.util
import json
import os
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
BASE = ROOT.parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(BASE/'PREPACKAGING_PHASE1_20261001/test_dependencies'),
               str(BASE/'TIMER_IMPLEMENTATION_20261001/dependencies'),
               str(BASE/'PREPACKAGING_PHASE5_CORRECTION_20261001')]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

reads = []
def readonly_database(event, args):
    if event == 'sqlite3.connect':
        uri = str(args[0])
        assert uri.startswith('file:') and 'mode=ro' in uri, uri
        reads.append(uri)
sys.addaudithook(readonly_database)

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontDatabase, QPalette
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QStackedWidget, QWidget
from CONTROL_STATION import application as ui, navigation as routing
from SECANT.dashboard_integration import DashboardIntegration
from SECANT import dashboard_demo as demo
from SECANT.dashboard_view import FlowConnector
from PERSISTENCE.database import database_path
from UI_THEMES.theme import BASE_THEMES, ATMOSPHERE_THEMES, ThemeController, BaseTheme, Atmosphere
import test_contextual_lock as harness

app = QApplication([])
for name in ('segoeui.ttf', 'seguisb.ttf', 'segoeuib.ttf', 'consola.ttf'):
    QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/name))
app.setFont(ui.make_font(13, 400))
app.setStyleSheet(ui.build_application_stylesheet())
errors = []
def record_error(*error):
    errors.append(str(error[1]))
    sys.__excepthook__(*error)
sys.excepthook = record_error

class VisualEngine(harness.Engine):
    pause_eligibility_changed = pyqtSignal(object)
    def pause_control_allowed(self):
        return False
harness.Engine = VisualEngine
host = harness.Host('secant')
profiles = SimpleNamespace(all_profiles=lambda: [SimpleNamespace(label='General', key='general')],
                           set_active=lambda _key: False)
control = ui.ControlPage(engine=host.engine, lifecycle=host.lifecycle, profiles=profiles)
host.stack.addWidget(control)
host.page_map[routing.PAGE_CONTROL] = control
host.pages.control = control
host.pages.study = host.page_map[routing.PAGE_STUDY]
host.pages.study.apply_theme = lambda theme: None
science = host.pages.science_lab
science.workspace = SimpleNamespace(_drawer=QWidget(science), _chapter_index={}, _stack=QStackedWidget(science))
host.pages.by_name = lambda: host.page_map
sidebar = ui.ControlStationSidebar()
host.sidebar = sidebar
host.navigation.sidebar = sidebar
sidebar.page_requested.connect(host.navigation.open_page)
clock = QLabel('SYSTEM CLOCK\nISOLATED UI VALIDATION')
clock.setMinimumSize(240, 110)
clock.setAlignment(Qt.AlignmentFlag.AlignCenter)
host.shell = ui.ControlStationShell(clock=clock, brand=ui.BrandConsole(), sidebar=sidebar,
    page_stack=host.takeCentralWidget(), loading_overlay=host.navigation.loading_overlay, parent=host)
host.setCentralWidget(host.shell)
host.page_stack = host.stack
host.theme = ThemeController(host)
host._application_theme_stylesheet_initialized = False
host.theme.theme_changed.connect(host._apply_theme)
host._apply_theme(host.theme.current_theme)
host.resize(1536, 950)
host.show()
host.stack.setCurrentWidget(control)
QTest.qWait(50)
assert host.isVisible() and control.isVisible()

db = database_path(create_parent=False)
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
db_before = digest(db)
model, error = DashboardIntegration._prepare_model(db, None, 'Asia/Kolkata')
assert not error, error
page = host.real_page
integration = DashboardIntegration(page, db, lambda: None, lambda: 'Asia/Kolkata')
integration.apply(model)
integration.last_model = model
spec = importlib.util.spec_from_file_location('secant_visual_before', OUT/'dashboard_view.before.py')
before = importlib.util.module_from_spec(spec)
spec.loader.exec_module(before)
baseline = before.SecantCosecantDashboard()
baseline_integration = DashboardIntegration(baseline, db, lambda: None, lambda: 'Asia/Kolkata')
baseline_integration.apply(model)

def text_state(view):
    return [label.text() for label in view.findChildren(QLabel)]
assert text_state(page) == text_state(baseline)
metric_values = [labels[1].text() for labels in page.landing.metric_labels]
assert metric_values[:3] == ['5', '6', '3'], metric_values
assert integration.last_model['landing']['metrics'][3] == model['landing']['metrics'][3]
host.navigation.register_preparation(routing.PAGE_SECANT_DASHBOARD, integration.prepare_for_navigation)
host.navigation.open_page(routing.PAGE_SECANT_DASHBOARD)
harness.wait_for(lambda: not host.navigation.is_transitioning)
assert page.isVisible() and page.landing.isVisible()

results = []
for name, theme in [('NEON', BASE_THEMES[BaseTheme.NEON]), ('PURPLE', BASE_THEMES[BaseTheme.PURPLE]),
                    ('BLACK', BASE_THEMES[BaseTheme.BLACK]), ('WHITE', BASE_THEMES[BaseTheme.WHITE]),
                    *[(a.name, t) for a, t in ATMOSPHERE_THEMES.items()]]:
    if name in ('NEON', 'PURPLE', 'BLACK', 'WHITE'):
        host.theme.set_base_theme(BaseTheme(name.lower()))
    else:
        atmosphere = Atmosphere[name]
        host.theme.claim_atmosphere('visual-test', atmosphere)
    QTest.qWait(30)
    assert host.theme.current_theme is theme
    assert page.landing._theme is theme
    assert text_state(page) == text_state(baseline), name
    assert page.landing.palette().color(QPalette.ColorRole.Window) == QColor(theme.window_background)
    assert page.landing.recent_source.palette().color(QPalette.ColorRole.WindowText) == QColor(theme.text_primary)
    cards = page.landing.findChildren(QFrame, 'secantLandingMetric')
    assert all(card.palette().color(QPalette.ColorRole.Window) == QColor(theme.surface) for card in cards)
    assert len({labels[1].palette().color(QPalette.ColorRole.WindowText).name()
                for labels in page.landing.metric_labels}) == 4
    assert page.landing._refresh_button.palette().color(QPalette.ColorRole.ButtonText) == QColor(theme.cyan)
    host.grab().save(str(OUT/f'{name}.png'))
    # Refresh rebuilds flow widgets; theme must survive that data application.
    integration.apply(model)
    assert page.landing._theme is theme
    assert text_state(page) == text_state(baseline)
    for labels in page.landing.recent_flow.node_labels:
        assert labels[1].palette().color(QPalette.ColorRole.WindowText) == QColor(theme.text_primary)
    # Also exercise a populated synthetic landing, since the latest real
    # session currently has no recent episode, events or flow nodes.
    populated = dict(status=demo.LANDING_STATUS, recent_episode=demo.RECENT_EPISODE,
                     recent_badges=demo.LANDING_RECENT_BADGES, metrics=model['landing']['metrics'],
                     behaviour=demo.LANDING_BEHAVIOUR, latest_events=demo.LATEST_SECANT_EVENTS,
                     journey=demo.SECANT_FLOW)
    page.set_landing_data(**populated)
    baseline.set_landing_data(**populated)
    assert text_state(page) == text_state(baseline)
    assert page.landing.recent_flow.node_labels
    for labels in page.landing.recent_flow.node_labels:
        assert labels[1].palette().color(QPalette.ColorRole.WindowText) == QColor(theme.text_primary)
        assert labels[2].palette().color(QPalette.ColorRole.WindowText) == QColor(theme.muted)
    assert all(connector._landing_theme is theme
               for connector in page.landing.recent_flow.findChildren(FlowConnector))
    assert all(not hasattr(connector, '_landing_theme')
               for connector in page.analysis.findChildren(FlowConnector))
    if name in ('WHITE', 'PURPLE'):
        host.grab().save(str(OUT/f'{name}_populated.png'))
        page.landing.recent_flow.grab().save(str(OUT/f'{name}_flow.png'))
    integration.apply(model)
    baseline_integration.apply(model)
    results.append({'theme': name, 'result': 'PASS'})
    if name not in ('NEON', 'PURPLE', 'BLACK', 'WHITE'):
        host.theme.release_atmosphere('visual-test')

previous = integration.last_model
page.landing._refresh_button.click()
assert not integration.last_error
assert integration.last_model == previous
assert page.landing._refresh_button.isEnabled()
assert text_state(page) == text_state(baseline)
page.findChild(QPushButton, 'openSecantDeepAnalysis').click()
harness.wait_for(lambda: not host.navigation.is_transitioning)
assert page.analysis.isVisible() and page.analysis.route == 'overview'
page.analysis.select_route('episodes')
assert page.analysis.route == 'episodes'
page.analysis.select_face('cosecant')
assert page.analysis.face == 'cosecant'
page.analysis.close_requested.emit()
assert not page.analysis.isVisible()
assert not errors, errors
assert digest(db) == db_before, 'Runtime database changed during validation'
assert reads
integration.shutdown(timeout=0)
baseline_integration.shutdown(timeout=0)
report = {'control_station': 'PASS (real shell and ControlPage; inert engine)',
          'secant': 'PASS', 'themes': results, 'metrics': metric_values, 'refresh': 'PASS',
          'deep_analysis': 'PASS', 'baseline_text_equal': True, 'database_hash_unchanged': True,
          'database_connections': 'read-only', 'qt_errors': errors}
(OUT/'visual_results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
host.hide()
