#!/usr/bin/env python3
"""An explicit invalid release guard must never become an unguarded release."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import json
import os
import tempfile

import jsonschema

CLI = str(ROOT / 'bin/git-locks')
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))
BASE = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}


def run(env, *args):
    result = subprocess.run([CLI, *args], env=env, capture_output=True, text=True, timeout=10)
    for line in (result.stdout + result.stderr).splitlines():
        VALIDATOR.validate(json.loads(line))
    return result


def state(env):
    return subprocess.check_output(['git', '--git-dir=' + env['GIT_LOCKS_STORE'],
                                    'rev-parse', 'refs/locks/state'], timeout=10)


def exercise(base, kind, value):
    env = dict(BASE, GIT_LOCKS_STORE=str(base / 'store.git'))
    if kind == 'semaphore':
        assert run(env, 'sem', 'create', 'gpu', '--capacity', '1').returncode == 0
        claim = run(env, 'sem', 'acquire', 'gpu', '--job', 'owner', '--holder', 'alice', '--ttl', '300')
        args = ['sem', 'release', 'gpu', '--job', 'owner']
    else:
        claim = run(env, 'claim', '--job', 'owner', '--holder', 'alice', '--ttl', '300', 'held.md')
        args = ['release', '--job', 'owner']
        if kind == 'multi-job':
            assert run(env, 'claim', '--job', 'first', '--holder', 'alice', '--ttl', '300',
                       'first.md').returncode == 0
            args = ['release', '--job', 'first', '--job', 'owner']
    assert claim.returncode == 0, claim
    before = state(env)
    if value == 'matching':
        guard = ['--acquisition', json.loads(claim.stdout)['acquisition']]
    elif value == 'omitted':
        guard = []
    else:
        guard = ['--acquisition', value]
    result = run(env, *args, *guard)
    if value in ('matching', 'omitted'):
        assert result.returncode == 0 and not result.stderr, result
        assert all(json.loads(line)['event'] == 'released' for line in result.stdout.splitlines()), result
        assert state(env) != before
    elif value == 'stale-acquisition':
        assert result.returncode == 0 and not result.stderr, result
        assert json.loads(result.stdout)['reason'] == 'superseded', result
        assert state(env) == before
    else:
        assert result.returncode == 2 and not result.stdout, (kind, repr(value), result)
        error = json.loads(result.stderr)
        assert error['event'] == 'error' and error['reason'] == 'usage', result
        assert state(env) == before, 'invalid guard changed authority'


failures = []
checks = 0
for kind in ('path', 'semaphore', 'multi-job'):
    values = ('', '\n', '\r', 'two\nlines', 'two\rlines', 'matching', 'omitted')
    if kind != 'multi-job':
        values += ('stale-acquisition',)
    for value in values:
        with tempfile.TemporaryDirectory(prefix='locks-release-guard-') as tmp:
            try:
                exercise(Path(tmp), kind, value)
                checks += 1
                print('PASS', kind, repr(value), flush=True)
            except Exception as error:
                failures.append((kind, repr(value), repr(error)))
                print('FAIL', *failures[-1], flush=True)
print(f'{checks} passed; {len(failures)} failed')
raise SystemExit(bool(failures))
