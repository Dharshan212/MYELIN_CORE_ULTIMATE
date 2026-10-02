"""Phase 2 source and authority integrity, using only the standard library."""
import ast
import copy
import difflib
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
PAIRS = {'CONTROL_STATION/application.py': 'application.before.py',
         'MINE/mine.py': 'mine.before.py', 'COSINE/cosine.py': 'cosine.before.py'}
def tree(text): return ast.parse(text)
def same(left, right): return ast.dump(left) == ast.dump(right)
def classes(module): return {node.name: node for node in module.body if isinstance(node, ast.ClassDef)}
def methods(cls): return {node.name: node for node in cls.body if isinstance(node, ast.FunctionDef)}

patches, result = [], {}
for relative, backup in PAIRS.items():
    before = (OUT/backup).read_text(encoding='utf-8-sig')
    after = (ROOT/relative).read_text(encoding='utf-8-sig')
    patches.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                      fromfile=relative+' (before Phase 2)', tofile=relative))
    original, current = tree(before), tree(after)
    if relative.startswith(('MINE/', 'COSINE/')):
        restored = copy.deepcopy(current)
        for cls in classes(restored).values():
            cls.body = [node for node in cls.body if not
                        (isinstance(node, ast.FunctionDef) and node.name == '_timer_progress_fraction')
                        and not (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                                 and node.target.id == 'timer_progress_fraction')]
            if cls.name.endswith('Runtime'):
                for call in ast.walk(methods(cls)['snapshot']):
                    if isinstance(call, ast.Call):
                        call.keywords = [kw for kw in call.keywords if kw.arg != 'timer_progress_fraction']
        assert same(original, restored), relative+' changed beyond the read-only snapshot projection'
        result[relative] = 'PASS: every pre-existing authority function, constant, event and schema unchanged'
    else:
        old_classes, new_classes = classes(original), classes(current)
        assert old_classes.keys() == new_classes.keys()
        changed = []
        for name, old in old_classes.items():
            new = new_classes[name]
            if same(old, new): continue
            assert name in {'ControlPage', 'ControlStationWindow'}, name
            old_methods, new_methods = methods(old), methods(new)
            for method in old_methods:
                if not same(old_methods[method], new_methods[method]): changed.append(name+'.'+method)
            added = new_methods.keys()-old_methods.keys()
            assert added == ({'_receive_engine_ring_progress', '_set_sine_ring_progress',
                              'retire_engine_ring', '_render_engine_organ_ring'} if name == 'ControlPage' else set())
        expected = {'ControlPage.__init__', 'ControlPage._engine_status_changed',
                    'ControlPage._clear_current_resource_presentation', 'ControlPage.reset_runtime_presentation',
                    'ControlPage.render_cosine', 'ControlPage.render_mine',
                    'ControlPage._render_current_authority_interval', 'ControlStationWindow._finish_shutdown'}
        assert set(changed) == expected, changed
        # SINE's original progress calculations and all unrelated interval UI are identical.
        interval = copy.deepcopy(methods(new_classes['ControlPage'])['_render_current_authority_interval'])
        clear = copy.deepcopy(methods(new_classes['ControlPage'])['_clear_current_resource_presentation'])
        for method in (interval, clear):
            for call in ast.walk(method):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == '_set_sine_ring_progress':
                    call.func = ast.Attribute(ast.Attribute(ast.Name('self', ast.Load()), '_ring', ast.Load()), 'set_progress', ast.Load())
        assert same(interval, methods(old_classes['ControlPage'])['_render_current_authority_interval'])
        assert same(clear, methods(old_classes['ControlPage'])['_clear_current_resource_presentation'])
        shutdown = copy.deepcopy(methods(new_classes['ControlStationWindow'])['_finish_shutdown'])
        shutdown.body = [node for node in shutdown.body if not (isinstance(node, ast.Expr)
                         and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute)
                         and node.value.func.attr == 'retire_engine_ring')]
        assert same(shutdown, methods(old_classes['ControlStationWindow'])['_finish_shutdown'])
        def timers(module):
            return sorted(ast.dump(node) for node in ast.walk(module) if isinstance(node, ast.Call)
                          and any(word in ast.unparse(node.func) for word in ('QTimer', 'Animation', '.singleShot')))
        assert timers(original) == timers(current), 'New/modified timer or animation construction'
        result[relative] = {'changed_methods': changed, 'existing_timer_and_animation_calls_unchanged': True,
                            'existing_sine_progress_calculations_unchanged': True,
                            'all_other_classes_unchanged': True}

manifest = json.loads((OUT/'manifest.before.json').read_text(encoding='utf-8-sig'))
changed = []
for entry in manifest:
    path = Path(entry['Path'])
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest().upper() != entry['Hash']:
        changed.append(path.relative_to(ROOT).as_posix())
assert set(changed) == set(PAIRS), changed
result.update(manifest_checked_files=len(manifest), changed_runtime_files=changed,
              engine_ring_renderer_unchanged=True, secant_phase1_unchanged=True,
              database_and_schema_sources_unchanged=True, result='PASS')
(OUT/'changes.patch').write_text(''.join(patches), encoding='utf-8')
(OUT/'integrity_results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
