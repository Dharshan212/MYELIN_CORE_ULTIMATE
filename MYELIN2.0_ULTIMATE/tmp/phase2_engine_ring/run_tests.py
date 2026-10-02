from pathlib import Path
import os
import sys
OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
BASE = ROOT.parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(BASE/'PREPACKAGING_PHASE1_20261001/test_dependencies'),
               str(BASE/'TIMER_IMPLEMENTATION_20261001/dependencies'),
               str(BASE/'PREPACKAGING_PHASE5_CORRECTION_20261001')]
os.environ.update(QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1',
                  PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', APPDATA=str(OUT/'isolated_appdata'),
                  LOCALAPPDATA=str(OUT/'isolated_localappdata'))
def deny_database(event, args):
    if event == 'sqlite3.connect':
        raise AssertionError('Phase 2 validation never opens/creates a database')
sys.addaudithook(deny_database)
import pytest
class AuditOutputs:
    def pytest_collection_modifyitems(self, items):
        for item in items:
            if hasattr(item.module, 'OUT'):
                item.module.OUT = OUT
            if hasattr(item.module, 'ROOT'):
                item.module.ROOT = ROOT
paths = sys.argv[1:] or [str(OUT/'test_engine_ring.py')]
raise SystemExit(pytest.main([*paths, '-q', '-p', 'no:cacheprovider', '--rootdir', str(OUT),
                             '--basetemp', str(OUT/'pytest_temp')], plugins=[AuditOutputs()]))
