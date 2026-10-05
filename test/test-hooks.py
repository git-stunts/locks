#!/usr/bin/env python3
"""Ambient instrumentation cannot change production authority or write files."""
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
BASE = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))
failures = []
checks = 0


def finish(process):
    try:
        stdout, stderr = process.communicate(timeout=8)
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise
    return subprocess.CompletedProcess(process.args, process.returncode, stdout, stderr)


def start(env, *args):
    return subprocess.Popen([CLI, *args], env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)


def run(env, *args):
    return finish(start(env, *args))


def reject(result):
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert not result.stdout, result.stdout
    lines = [json.loads(line) for line in result.stderr.splitlines()]
    assert len(lines) == 1 and lines[0]['event'] == 'error' and lines[0]['reason'] == 'usage', lines
    VALIDATOR.validate(lines[0])
    assert 'GIT_LOCKS_TEST_HOOKS=1' in result.stderr, result.stderr


def environment(base):
    return dict(BASE, GIT_LOCKS_STORE=str(base / 'store.git'))


def case(label, body):
    global checks
    try:
        with tempfile.TemporaryDirectory(prefix='locks-test-hooks-') as tmp:
            body(Path(tmp))
        checks += 1
        print('PASS', label, flush=True)
    except Exception as error:
        failures.append(label)
        print('FAIL', label, repr(error), flush=True)


def disabled(base, name, selector):
    env = environment(base)
    gate = base / 'gate'
    gate.write_text('ready')  # A broken baseline must not spend 30 seconds waiting.
    trace = base / 'trace'
    trace.write_text('preserve\n')
    env[name] = '100' if name == 'GIT_LOCKS_NOW' else str(trace if name == 'GIT_LOCKS_TRACE' else gate)
    if selector is not None:
        env['GIT_LOCKS_TEST_HOOKS'] = selector
    marker = base / 'command-ran'
    result = run(env, 'with', '--job', 'probe', '--holder', 'test', '--ttl', '10',
                 'report.md', '--', 'touch', str(marker))
    reject(result)
    assert not Path(env['GIT_LOCKS_STORE']).exists(), 'refused input initialized a store'
    assert trace.read_text() == 'preserve\n', 'trace was written without test opt-in'
    assert not gate.with_suffix('.ready').exists(), 'pause gate wrote its ready marker'
    assert not marker.exists(), 'protected command ran despite invalid test configuration'


for hook in ('GIT_LOCKS_NOW', 'GIT_LOCKS_TRACE', 'GIT_LOCKS_PAUSE_AFTER_READ', 'GIT_LOCKS_PAUSE_BEFORE_COMMIT'):
    for selector in (None, '', '0', 'true', '01'):
        case(f'{hook} refuses selector {selector!r} before all side effects',
             lambda base, h=hook, s=selector: disabled(base, h, s))


def preserve_live(base):
    env = environment(base)
    assert run(env, 'claim', '--job', 'owner', '--holder', 'alice', '--ttl', '300', 'held.md').returncode == 0
    git = ['git', '--git-dir=' + env['GIT_LOCKS_STORE'], 'rev-parse', 'refs/locks/state']
    before = subprocess.check_output(git)
    contaminated = dict(env, GIT_LOCKS_NOW=str(int(time.time()) + 3600))
    reject(run(contaminated, 'claim', '--job', 'contender', '--holder', 'bob', 'held.md'))
    assert subprocess.check_output(git) == before, 'test clock replaced a live production reservation'
    assert run(env, 'check', 'held.md').returncode == 1


case('ambient future clock cannot expire a live production reservation', preserve_live)


def empty_controls(base):
    for name in ('GIT_LOCKS_NOW', 'GIT_LOCKS_TRACE', 'GIT_LOCKS_PAUSE_AFTER_READ', 'GIT_LOCKS_PAUSE_BEFORE_COMMIT'):
        env = environment(base / name)
        env[name] = ''
        reject(run(env, 'list'))
        assert not Path(env['GIT_LOCKS_STORE']).exists()


case('empty controls still require explicit opt-in', empty_controls)


def static_output(base):
    env = dict(environment(base), GIT_LOCKS_NOW='invalid', GIT_LOCKS_TRACE=str(base / 'trace'))
    for args in (('help',), ('version',), ('schema',), ('claim', '--help')):
        result = run(env, *args)
        assert result.returncode == 0 and not result.stderr, result
        json.loads(result.stdout)
    assert not Path(env['GIT_LOCKS_STORE']).exists() and not (base / 'trace').exists()


case('static output remains available without enabling ambient controls', static_output)


def enabled_clock(base):
    env = dict(environment(base), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='00100')
    result = run(env, 'claim', '--job', 'clock', '--holder', 'test', '--ttl', '10', 'clock.md')
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout)
    VALIDATOR.validate(record)
    assert record['claimed'] == 100 and record['expires'] == 110, record
    assert run(dict(env, GIT_LOCKS_NOW='110'), 'check', 'clock.md').returncode == 0
    invalid = dict(environment(base / 'invalid'), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='')
    bad = run(invalid, 'store')
    assert bad.returncode == 2 and not Path(invalid['GIT_LOCKS_STORE']).exists()
    VALIDATOR.validate(json.loads(bad.stderr))


case('explicit test mode retains normalized clock and expiry behavior', enabled_clock)


def enabled_gate(base, name):
    gate = base / 'gate'
    trace = base / 'trace'
    env = dict(environment(base), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='100', GIT_LOCKS_TRACE=str(trace))
    env[name] = str(gate)
    process = start(env, 'claim', '--job', 'gated', '--holder', 'test', 'gated.md')
    try:
        deadline = time.monotonic() + 5
        while not gate.with_suffix('.ready').exists():
            assert process.poll() is None and time.monotonic() < deadline, 'enabled gate was not reached'
            time.sleep(.01)
        assert process.poll() is None, 'enabled gate did not wait'
        gate.touch()
        result = finish(process)
        assert result.returncode == 0, result.stderr
        VALIDATOR.validate(json.loads(result.stdout))
        assert 'snapshot ' in trace.read_text()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


for hook in ('GIT_LOCKS_PAUSE_AFTER_READ', 'GIT_LOCKS_PAUSE_BEFORE_COMMIT'):
    case(f'explicit test mode enables {hook} and tracing', lambda base, h=hook: enabled_gate(base, h))


def ordinary(base):
    env = dict(environment(base), GIT_LOCKS_TEST_HOOKS='0')
    result = run(env, 'with', '--job', 'normal', '--holder', 'test', '--ttl', '60', 'normal.md',
                 '--', 'python3', '-c', 'import os; print(os.environ["GIT_LOCKS_TEST_HOOKS"])')
    assert result.returncode == 0 and result.stdout == '0\n', result
    for line in result.stderr.splitlines():
        VALIDATOR.validate(json.loads(line))
    assert run(env, 'check', 'normal.md').returncode == 0


case('ordinary wrapper keeps the caller environment and releases its reservation', ordinary)
print(f'Test hooks: {checks} passed; {len(failures)} failed', flush=True)
raise SystemExit(bool(failures))
