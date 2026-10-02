"""Confirm the one-file presentation boundary and preserve a reviewable diff."""
from pathlib import Path
import ast
import difflib
import hashlib
import json

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
source = ROOT/'SECANT/dashboard_view.py'
old = (OUT/'dashboard_view.before.py').read_text(encoding='utf-8')
new = source.read_text(encoding='utf-8')
compile(new, str(source), 'exec')
before, after = ast.parse(old), ast.parse(new)
def classes(tree):
    return {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
bc, ac = classes(before), classes(after)
for name in bc.keys() - {'SecantLandingPage', 'SecantCosecantDashboard', 'FlowConnector'}:
    assert ast.dump(bc[name]) == ast.dump(ac[name]), name
def methods(cls):
    return {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}
assert ast.dump(methods(bc['FlowConnector'])['__init__']) == ast.dump(methods(ac['FlowConnector'])['__init__'])
bm, am = methods(bc['SecantCosecantDashboard']), methods(ac['SecantCosecantDashboard'])
for name in bm.keys() - {'_style', '_retheme'}:
    assert ast.dump(bm[name]) == ast.dump(am[name]), name

class WithoutPresentation(ast.NodeTransformer):
    def visit_Expr(self, node):
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
            if call.func.attr in ('setStyleSheet', '_retheme'):
                return None
            if call.func.attr == 'setProperty' and call.args and isinstance(call.args[0], ast.Constant):
                if call.args[0].value == 'secantColor':
                    return None
        return self.generic_visit(node)
    def visit_If(self, node):
        # Only the optional cached-theme style pass was added to the setter.
        if ast.unparse(node.test) == "hasattr(self, '_theme')":
            return None
        return self.generic_visit(node)

bl, al = methods(bc['SecantLandingPage']), methods(ac['SecantLandingPage'])
for name in ('_request_refresh', 'set_landing_data'):
    normalize = WithoutPresentation()
    assert ast.dump(normalize.visit(bl[name])) == ast.dump(normalize.visit(al[name])), name
manifest = json.loads((OUT/'manifest.before.json').read_text())
changed = [entry['Path'] for entry in manifest
           if hashlib.sha256(Path(entry['Path']).read_bytes()).hexdigest().upper() != entry['Hash']]
assert changed == [str(source)], changed
diff = ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                  fromfile='SECANT/dashboard_view.py (before)',
                                  tofile='SECANT/dashboard_view.py (after)'))
(OUT/'changes.patch').write_text(diff, encoding='utf-8')
report = {'runtime_files_changed': changed, 'deep_analysis_ast_unchanged': True,
          'dashboard_navigation_and_data_api_ast_unchanged': True,
          'landing_refresh_and_data_logic_unchanged': True,
          'other_runtime_sources_and_configuration_unchanged': True,
          'syntax': 'PASS'}
(OUT/'integrity_results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
