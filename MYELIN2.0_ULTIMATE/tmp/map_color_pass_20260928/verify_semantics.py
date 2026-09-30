"""Task-scoped semantic and factual-invariance checks."""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from SECANT.dashboard_evidence import EvidenceSnapshot, EvidenceTable, TABLES
from SECANT.dashboard_projection import _secant_flow_tone, _cosecant_flow_tone, prepare_presentation
from SECANT import dashboard_demo as after_demo

def tone(event_name, stage=None, reason=None):
    return _secant_flow_tone(dict(event_name=event_name, stage=stage, reason=reason))

assert [tone('SECANT_DISPLAYED', i) for i in (1, 2, 3)] == ['blue', 'amber', 'red']
assert tone('SECANT_EPISODE_FOUNDED') == 'purple'
for name in ('SECANT_ACTION_INTENT', 'SECANT_RETURN_STARTED', 'SECANT_RETURN_VERIFIED', 'SECANT_RECOVERY_CLOSED'):
    assert tone(name) == 'green', name
for name in ('SECANT_RECOVERY_INTERRUPTED', 'SECANT_FROZEN'):
    assert tone(name) == 'yellow', name
assert tone('SECANT_EPISODE_CLOSED', reason='recovered') == 'green'
for reason in ('session_end', 'study_complete', 'emergency'):
    assert tone('SECANT_EPISODE_CLOSED', reason=reason) == 'neutral', reason
assert tone('SECANT_RESUMED') == 'neutral'

co_contract = {
    'BREAK_STARTED': 'purple', 'BREAK_COMPLETE': 'yellow', 'BREAK_ALREADY_OVER': 'yellow',
    'FINAL_LOCKED': 'yellow', 'RETURN_INTENT_RECORDED': 'green',
    'RETURN_CONFIRMATION_STARTED': 'green', 'RETURN_CONFIRMATION_RESTARTED': 'green',
    'RETURN_CONFIRMATION_LOST': 'yellow', 'RETURN_CONFIRMED': 'green',
    'BREAK_CANCELLED': 'yellow', 'SAFE_SHUTDOWN': 'neutral',
}
for kind, expected in co_contract.items():
    assert _cosecant_flow_tone(kind) == expected, kind

cached = ROOT.parent / 'PHASE3_COMPLETION_20260927'
raw = json.loads((cached / 'session202_study_cosecant.json').read_text(encoding='utf-8'))
snapshot = EvidenceSnapshot(202, {name: EvidenceTable(tuple(raw.get(name, ())), 'AVAILABLE') for name in TABLES})
co_flow = prepare_presentation(snapshot, 'UTC')['cosecant']['flow']
old_co_flow = json.loads((cached / 'session202_presentation.json').read_text(encoding='utf-8'))['cosecant']['flow']
assert [list(node[:3]) + [node[5]] for node in co_flow] == [node[:3] + [node[5]] for node in old_co_flow]
assert all(node[3] == 'Unavailable' for node in co_flow)  # Named timezone database absent in this Python runtime.
assert [node[4] for node in co_flow] == ['purple', 'yellow', 'green', 'green', 'green', 'neutral']

spec = importlib.util.spec_from_file_location('baseline_demo', Path(__file__).parent / 'source_backup' / 'dashboard_demo.py')
before_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(before_demo)
def without_tones(value):
    if isinstance(value, (tuple, list)):
        if len(value) == 6 and all(isinstance(x, str) for x in value):
            return tuple(value[:4]) + (value[5],)
        return tuple(without_tones(x) for x in value)
    if isinstance(value, dict):
        return {key: without_tones(item) for key, item in value.items()}
    return value
for name in ('SECANT_FLOW', 'COSECANT_FLOW', 'DEMO_SECANT_EPISODE_ARCHIVE', 'STUDY_FLOW', 'CONFIRMATION_FLOW'):
    assert without_tones(getattr(before_demo, name)) == without_tones(getattr(after_demo, name)), name
assert before_demo.STUDY_FLOW == after_demo.STUDY_FLOW
assert before_demo.CONFIRMATION_FLOW == after_demo.CONFIRMATION_FLOW

print('semantic mapping, real Session 202 COSECANT projection, and demo non-tone invariants: PASS')
