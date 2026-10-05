#!/usr/bin/env python3
"""Reject unsafe graph claims and preserve the common prompt prefix."""
from pathlib import Path
import copy
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


def rejected(name, action):
    global checks
    try:
        action()
    except ValueError:
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
rejected('cycle', lambda: module.layers_for(bad))
bad = copy.deepcopy(valid)
bad[1]['dependencies'][0]['id'] = 'missing'
rejected('unknown dependency', lambda: module.layers_for(bad))
bad = copy.deepcopy(valid)
bad[1]['dependencies'][0]['id'] = 'b'
rejected('self dependency', lambda: module.layers_for(bad))
bad = copy.deepcopy(valid)
bad[1]['dependencies'].append(dict(bad[1]['dependencies'][0]))
rejected('duplicate edge', lambda: module.layers_for(bad))
bad = copy.deepcopy(valid)
bad[1]['dependencies'][0]['reason'] = ''
rejected('unexplained edge', lambda: module.layers_for(bad))
bad = copy.deepcopy(valid)
bad[1]['dependencies'][0]['id'] = 'c'
rejected('optional work on release path', lambda: module.layers_for(bad))
rejected('duplicate task id', lambda: module.layers_for(valid + [valid[0]]))
rejected('duplicate metadata key', lambda: module.metadata('---\nid: "a"\nid: "b"\n---\n'))

tasks, inventory = module.load()
projection = module.render(tasks, inventory)
for path, expected in projection.items():
    assert (ROOT / path).read_bytes().decode('utf-8') == expected, path
    checks += 1
prefix = (ROOT / 'docs/tasks/PROMPT.txt').read_bytes().decode('utf-8')
for task in tasks:
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/roadmap.py'), '--prompt', task['id']],
                            text=True, capture_output=True, timeout=10)
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
