"""Use existing local dependencies; keep fixtures and logs within this trial."""
from pathlib import Path
import os
import sys

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
BASE = ROOT.parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(BASE/'PREPACKAGING_PHASE1_20261001/test_dependencies'),
               str(BASE/'TIMER_IMPLEMENTATION_20261001/dependencies'),
               str(BASE/'PREPACKAGING_PHASE3_20261001')]
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
os.environ['APPDATA'] = str(OUT/'isolated_appdata')
os.environ['LOCALAPPDATA'] = str(OUT/'isolated_localappdata')
import pytest
mode = sys.argv[1]
if mode == 'secant':
    paths = [str(ROOT/'SECANT/test_dashboard_corrections.py'), str(ROOT/'SECANT/test_pdf_export.py')]
else:
    def deny_database(event, args):
        if event == 'sqlite3.connect':
            raise RuntimeError('UI regressions must never open/create databases')
    sys.addaudithook(deny_database)
    paths = [str(BASE/'PREPACKAGING_PHASE5_CORRECTION_20261001/test_contextual_lock.py'), '-k', 'secant']
raise SystemExit(pytest.main([*paths, '-q', '-p', 'no:cacheprovider', '--rootdir', str(OUT),
                             '--basetemp', str(OUT/f'pytest_{mode}'), *sys.argv[2:]]))
