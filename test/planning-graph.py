#!/usr/bin/env python3
"""Reject unsafe graph claims and preserve the common prompt prefix."""
from pathlib import Path
import copy
import json
import os
import shutil
import tempfile
import re
import importlib.util
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)
spec = importlib.util.spec_from_file_location('roadmap', ROOT / 'scripts/roadmap.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
checks = 0


def rejected(name, action, expected):
    global checks
    try:
        action()
    except ValueError as error:
        assert expected in str(error), (name, expected, str(error))
        checks += 1
        print('PASS rejects ' + name)
    else:
        raise AssertionError('accepted ' + name)


valid = [{'id': 'a', 'dependencies': [], 'release_required': True},
         {'id': 'b', 'dependencies': [{'id': 'a', 'reason': 'needs result'}], 'release_required': True},
         {'id': 'c', 'dependencies': [], 'release_required': False}]
assert module.layers_for(valid) == [['a', 'c'], ['b']]
checks += 1
bad = copy.deepcopy(valid)
bad[0]['dependencies'] = [{'id': 'b', 'reason': 'cycle'}]
rejected('cycle', lambda: module.layers_for(bad), 'dependency cycle')
bad = copy.deepcopy(valid)
bad[1]['dependencies'][0]['id'] = 'missing'
rejected('unknown dependency', lambda: module.layers_for(bad), 'unknown dependency')
bad = copy.deepcopy(valid)
bad[1]['dependencies'][0]['id'] = 'b'
rejected('self dependency', lambda: module.layers_for(bad), 'self dependency')
bad = copy.deepcopy(valid)
bad[1]['dependencies'].append(dict(bad[1]['dependencies'][0]))
rejected('duplicate edge', lambda: module.layers_for(bad), 'duplicate dependency')
bad = copy.deepcopy(valid)
bad[1]['dependencies'][0]['reason'] = ''
rejected('unexplained edge', lambda: module.layers_for(bad), 'missing dependency reason')
bad = copy.deepcopy(valid)
bad[1]['dependencies'][0]['id'] = 'c'
rejected('optional work on release path', lambda: module.layers_for(bad), 'required task depends on optional work')
rejected('duplicate task id', lambda: module.layers_for(valid + [valid[0]]), 'duplicate task id')
rejected('duplicate metadata key', lambda: module.metadata('---\nid: "a"\nid: "b"\n---\n'), 'invalid or duplicate frontmatter key')

tasks, inventory = module.load()
projection = module.render(tasks, inventory)
for path, expected in projection.items():
    assert (ROOT / path).read_bytes().decode('utf-8') == expected, path
    checks += 1
# Each mutation uses a fresh, bounded fixture. Source paths are empty placeholders.
with tempfile.TemporaryDirectory(prefix='roadmap-fixture-') as temporary:
    fixture = Path(temporary)
    shutil.copytree(ROOT / 'docs/tasks', fixture / 'docs/tasks')
    shutil.copytree(ROOT / 'docs/planning', fixture / 'docs/planning')
    shutil.copyfile(ROOT / 'ROADMAP.md', fixture / 'ROADMAP.md')
    (fixture / 'scripts').mkdir(exist_ok=True)
    shutil.copyfile(ROOT / 'scripts/roadmap.py', fixture / 'scripts/roadmap.py')
    for task in tasks:
        for source in task['sources']:
            target = fixture / source
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                if (ROOT / source).is_dir():
                    target.mkdir()
                else:
                    target.touch()
    def mutation(name, path, transform, expected):
        original = path.read_bytes()
        try:
            path.write_bytes(transform(original.decode('utf-8')).encode('utf-8'))
            module.ROOT = fixture
            rejected(name, module.load, expected)
        finally:
            module.ROOT = ROOT
            path.write_bytes(original)
    card = fixture / 'docs/tasks/GL-001.md'
    dependency = tasks[0]['dependencies'][0]
    reason_line = '[' + dependency['id'] + '](' + dependency['id'] + '.md): ' + dependency['reason']
    mutation('reason copied outside Prerequisites', card,
             lambda text: text.replace(reason_line, reason_line.split(': ')[0] + ': stale reason')
             .replace('## 4. Scope', '## 4. Scope\n\n' + reason_line), 'frontmatter and prerequisite text disagree')
    mutation('prefix hash drift', card, lambda text: text.replace(tasks[0]['prompt_prefix_sha256'], '0' * 64, 1), 'wrong prompt prefix hash')
    mutation('prompt text drift', card, lambda text: text.replace('```text\n', '```text\nChanged prefix.\n', 1), 'prompt prefix or task id drift')
    mutation('issue coverage drift', fixture / 'docs/planning/inventory.json',
             lambda text: json.dumps(dict(json.loads(text), issue_coverage={})), 'task missing from issue map')
    mutation('missing source', card, lambda text: re.sub(r'^sources: .*$', 'sources: ["absent-source"]', text, flags=re.M), 'source path missing')
    mutation('missing prerequisite prose', card, lambda text: text.replace(reason_line, 'omitted'), 'extra or missing prerequisite in prose')
    mutation('unknown gate phase', fixture / 'docs/planning/inventory.json',
             lambda text: text.replace('"before-action"', '"unknown"', 1), 'unknown gate phase')
    mutation('gate phase prose drift', card,
             lambda text: text.replace('`workflow_permission` (before-action)', '`workflow_permission` (completion)'), 'gate phase prose drift')
    completion_task = copy.deepcopy(next(task for task in tasks if task['id'] == 'GL-030'))
    completion_task['dependencies'] = []
    candidate_graph = json.loads(module.render([completion_task] + [task for task in tasks if task['id'] != 'GL-030'], inventory)['docs/tasks/graph.json'])
    assert 'GL-030' in candidate_graph['candidates_without_action_gates']
    assert 'GL-003' not in candidate_graph['candidates_without_action_gates']
    checks += 2
    locale = dict(os.environ, LC_ALL='C', PYTHONUTF8='0', PYTHONCOERCECLOCALE='0', PYTHONIOENCODING='ascii')
    for arguments in (['--write'], ['--prompt', 'GL-001']):
        result = subprocess.run([sys.executable, str(fixture / 'scripts/roadmap.py'), *arguments],
                                env=locale, capture_output=True, timeout=10)
        assert result.returncode == 0, (arguments, result.stderr)
        if arguments[0] == '--write':
            for path, expected in projection.items():
                assert (fixture / path).read_bytes() == expected.encode('utf-8'), path
        else:
            assert ' — '.encode('utf-8') in result.stdout
        checks += 1
    with (fixture / 'docs/tasks/DAG.md').open('ab') as stream:
        stream.write(b'stale projection\n')
    result = subprocess.run([sys.executable, str(fixture / 'scripts/roadmap.py'), '--check'],
                            capture_output=True, timeout=10)
    assert result.returncode != 0 and b'stale graph projection' in result.stderr
    checks += 1
prefix = (ROOT / 'docs/tasks/PROMPT.txt').read_bytes().decode('utf-8')
for task in tasks:
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/roadmap.py'), '--prompt', task['id']],
                            text=True, encoding="utf-8", capture_output=True, timeout=10)
    assert result.returncode == 0 and not result.stderr, result
    assert result.stdout.startswith(prefix + '\nTask: ' + task['id'] + ' — '), task['id']
    assert '## 7. Definition of Done' in result.stdout and '## 9. Related Issues' in result.stdout, task['id']
    checks += 1
for path in [ROOT / 'ROADMAP.md', ROOT / 'README.md',
             *(ROOT / 'docs/tasks').glob('*.md'), *(ROOT / 'docs/planning').glob('*.md')]:
    for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', path.read_bytes().decode('utf-8')):
        if target.startswith(('https://', 'http://', '#')):
            continue
        destination = (path.parent / target.split('#', 1)[0]).resolve()
        assert destination.is_relative_to(ROOT) and destination.exists(), (path, target)
    checks += 1
print(f'{checks} graph and prompt checks passed')
