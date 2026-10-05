#!/usr/bin/env python3
"""Compare public help with generated headers and the command reference."""
from pathlib import Path
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)
CLI = str(ROOT / 'bin/git-locks')
failures = []
checks = 0


def check(label, condition):
    global checks
    checks += 1
    print(('PASS ' if condition else 'FAIL ') + label)
    if not condition:
        failures.append(label)


def help_text(*args):
    result = subprocess.run([CLI, *args], text=True, capture_output=True, timeout=10)
    assert result.returncode == 0 and not result.stderr, result
    return json.loads(result.stdout)['usage']


def normalize(text):
    return ' '.join(text.replace('<seconds>', '<s>').split())


commands = ['claim', 'batch', 'release', 'check', 'list', 'sweep', 'store',
            'show', 'ttl', 'extend', 'with', 'sem', 'doctor', 'migrate']
full = help_text('help')
full_lines = [normalize(line.removeprefix('usage: ')) for line in full.split('\n\n', 1)[0].splitlines()]
header_lines = [normalize(line[4:]) for line in (ROOT / 'bin/git-locks').read_text().splitlines()
                if line.startswith('#   git locks ')]
synopses = {}
for command in commands:
    short = normalize(help_text(command, '--help').removeprefix('usage: '))
    synopses[command] = short
    check(command + ' full help equals command help', short in full_lines)
    check(command + ' header equals command help', short in header_lines)
check('with documents parent', '[--parent <id>]' in synopses['with'])
check('release permits both guards', '[--record <oid>] [--acquisition <id>]' in synopses['release'])
check('semaphore release permits both guards', '[--record <oid>] [--acquisition <id>]' in synopses['sem'])
for command in ['version', 'schema', 'help']:
    check(command + ' full help', 'git locks ' + command in full_lines)
    check(command + ' header', 'git locks ' + command in header_lines)
check('no extra header synopsis', len(header_lines) == len(commands) + 3)
check('no extra full synopsis', len(full_lines) == len(commands) + 3)

# Compare complete documented syntax, including all six semaphore operations.
reference = (ROOT / 'docs/usage.md').read_text().split('## Command reference\n', 1)[1].split('## Output and errors', 1)[0]
documented = []
for line in reference.splitlines():
    if line.startswith('| `'):
        documented.extend(re.findall(r'`([^`]+)`', line.split(' | ', 1)[0]))
expected = [s.removeprefix('git locks ') for c, s in synopses.items() if c != 'sem']
expected += ['sem ' + s for s in re.split(r' \| (?=[a-z])', synopses['sem'].removeprefix('git locks sem '))]
expected += ['version', 'schema', 'help']
for syntax in expected:
    check('reference: ' + syntax, normalize(syntax) in [normalize(s) for s in documented])
check('reference has no extra syntax', len(documented) == len(expected))
print(f'{checks - len(failures)} passed; {len(failures)} failed')
raise SystemExit(bool(failures))
