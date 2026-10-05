#!/usr/bin/env python3
"""Renewal preserves live acquisition identity and rechecks after root contention."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import json
import os
import signal
import tempfile
import time

import jsonschema

CLI = str(ROOT / 'bin/git-locks')
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))


def run(env, *args):
    result = subprocess.run([CLI, *args], env=env, text=True, capture_output=True, timeout=10)
    for line in (result.stdout + result.stderr).splitlines():
        VALIDATOR.validate(json.loads(line))
    return result


def setup(base):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_LOCKS_STORE=str(base / 'store.git'), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='100')
    result = run(env, 'claim', '--job', 'j', '--holder', 'alice', '--ttl', '5', 'x.md')
    assert result.returncode == 0, result
    return env, json.loads(result.stdout)['acquisition']


def state(env):
    return subprocess.check_output(['git', '--git-dir=' + env['GIT_LOCKS_STORE'], 'rev-parse', 'refs/locks/state'], text=True)


def record(env):
    result = run(env, 'show', '--job', 'j')
    assert result.returncode == 0, result
    return json.loads(result.stdout)


def refusal(result, reason):
    assert result.returncode == 1 and not result.stdout, result
    row = json.loads(result.stderr)
    assert row == {'event': 'refused', 'reason': reason, 'job': 'j'}, row


def expired(base, guarded):
    env, acquisition = setup(base)
    for clock in ('105', '106'):
        env['GIT_LOCKS_NOW'] = clock
        before = state(env)
        args = ['--acquisition', acquisition] if guarded else []
        refusal(run(env, 'extend', '--job', 'j', '--ttl', '20', *args), 'expired')
        assert state(env) == before
        checked = run(env, 'check', 'x.md')
        assert checked.returncode == 0 and json.loads(checked.stdout)['state'] == 'expired', checked


def guard(base):
    env, acquisition = setup(base)
    env['GIT_LOCKS_NOW'] = '104'
    before = state(env)
    refusal(run(env, 'extend', '--job', 'j', '--ttl', '20', '--acquisition', 'another-acquisition'), 'superseded')
    assert state(env) == before
    for ttl in ('20', '30'):
        old_record = record(env)['record']
        result = run(env, 'extend', '--job', 'j', '--ttl', ttl, '--acquisition', acquisition)
        assert result.returncode == 0 and not result.stderr, result
        current = record(env)
        assert current['acquisition'] == acquisition and current['record'] != old_record
        assert current['expires'] == 104 + int(ttl)


def invalid_guard(base, value):
    env, _ = setup(base)
    before = state(env)
    result = run(env, 'extend', '--job', 'j', '--ttl', '20', '--acquisition', value)
    assert result.returncode == 2 and not result.stdout, result
    assert state(env) == before


def race(base, mode):
    env, acquisition = setup(base)
    gate = base / 'gate'
    shim = base / 'shim'
    shim.mkdir()
    clock = base / 'clock'
    clock.write_text('100')
    date = shim / 'date'
    date.write_text('#!/bin/sh\ncat "$CLOCK_SAMPLE"\n')
    date.chmod(0o755)
    env.pop('GIT_LOCKS_NOW')
    env.update(PATH=str(shim) + os.pathsep + env['PATH'], CLOCK_SAMPLE=str(clock))
    paused = dict(env, GIT_LOCKS_PAUSE_BEFORE_COMMIT=str(gate))
    child = subprocess.Popen([CLI, 'extend', '--job', 'j', '--ttl', '20', '--acquisition', acquisition],
                             env=paused, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not Path(str(gate) + '.ready').exists():
            assert child.poll() is None and time.monotonic() < deadline, 'renewal did not reach publication'
            time.sleep(0.01)
        if mode == 'expired':
            clock.write_text('106')
            winner = run(env, 'claim', '--job', 'other', '--holder', 'bob', 'other.md')
        else:
            winner = run(env, 'claim', '--job', 'j', '--holder', 'bob', 'x.md')
        assert winner.returncode == 0, winner
        before = state(env)
        gate.touch()
        out, err = child.communicate(timeout=10)
        result = subprocess.CompletedProcess([], child.returncode, out, err)
        VALIDATOR.validate(json.loads(err))
        refusal(result, mode)
        assert state(env) == before, 'a stale renewal modified the winner'
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()


failures = []
checks = 0

def case(label, body):
    global checks
    try:
        with tempfile.TemporaryDirectory(prefix='locks-renew-') as tmp:
            body(Path(tmp))
        checks += 1
    except Exception as error:
        failures.append((label, str(error)))
        print(f'FAIL renewal ({label}): {error}', flush=True)


case('expired unguarded', lambda base: expired(base, False))
case('expired guarded', lambda base: expired(base, True))
case('live acquisition guard', guard)
for value in ('', 'bad\nacquisition', 'bad\racquisition'):
    case(f'invalid guard {value!r}', lambda base, v=value: invalid_guard(base, v))
for mode in ('expired', 'superseded'):
    case(f'retry rechecks {mode}', lambda base, m=mode: race(base, m))
print(f'renewal: {checks} cases passed; {len(failures)} failed')
assert not failures, failures
