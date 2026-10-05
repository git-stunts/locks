#!/usr/bin/env python3
"""CLI time boundaries, checked against Python integers and controlled clocks."""
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
LIMIT = 2**63 - 1
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))
checks = 0
failures = []


def invoke(env, *args, data=None):
    process = subprocess.Popen([CLI, *args], env=env, stdin=subprocess.PIPE, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(data, timeout=15)
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise
    result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    for line in (result.stdout + result.stderr).splitlines():
        VALIDATOR.validate(json.loads(line))
    return result


def refs(env):
    return subprocess.check_output(['git', '--git-dir=' + env['GIT_LOCKS_STORE'], 'for-each-ref',
                                    '--format=%(refname) %(objectname)'], text=True)


def environment(base, clock='1000000'):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_LOCKS_STORE=str(base / 'store.git'), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW=clock)
    assert invoke(env, 'sem', 'create', 'gpu', '--capacity', '2').returncode == 0
    assert invoke(env, 'claim', '--job', 'held', '--holder', 'alice', '--ttl', '1', 'held.md').returncode == 0
    return env


def action(kind, value, marker):
    if kind == 'claim':
        return ['claim', '--job', 'new', '--holder', 'bob', '--ttl', value, 'new.md'], None
    if kind == 'extend':
        return ['extend', '--job', 'held', '--ttl', value], None
    if kind == 'batch':
        return ['batch'], f'job: first\nholder: bob\nttl: 1\npaths:\nfirst.md\n\njob: new\nholder: bob\nttl: {value}\npaths:\nnew.md\n'
    if kind == 'sem':
        return ['sem', 'acquire', 'gpu', '--job', 'new', '--holder', 'bob', '--ttl', value], None
    args = ['with', '--job', 'new', '--holder', 'bob', '--ttl', value]
    if kind == 'with-sem':
        args += ['--sem', 'gpu']
    return [*args, 'new.md', '--', 'touch', str(marker)], None


def case(label, body):
    global checks
    try:
        with tempfile.TemporaryDirectory(prefix='locks-time-') as tmp:
            body(Path(tmp))
        checks += 1
    except Exception as error:
        detail = error.message if isinstance(error, jsonschema.ValidationError) else str(error)
        failures.append((label, detail))
        print(f'FAIL {label}: {detail}', flush=True)


def invalid_ttl(base, kind, value):
    env = environment(base)
    before = refs(env)
    marker = base / 'ran'
    args, data = action(kind, value, marker)
    result = invoke(env, *args, data=data)
    assert result.returncode == 2 and not result.stdout, (result.returncode, result.stdout, result.stderr)
    assert json.loads(result.stderr)['reason'] == 'usage', result.stderr
    assert refs(env) == before and not marker.exists(), 'rejected time changed authority or ran command'


bad_ttls = ['0', '-1', '+1', '1+1', str(LIMIT), str(LIMIT - 1000000 + 1),
            str(LIMIT + 1), str(2**64 + 1), '9' * 128]
for kind in ('claim', 'extend', 'batch', 'sem', 'with', 'with-sem'):
    for value in bad_ttls:
        case(f'{kind} rejects ttl {value}', lambda base, k=kind, v=value: invalid_ttl(base, k, v))


def valid_time(base, kind, clock, ttl):
    env = environment(base, clock)
    args, data = action(kind, ttl, base / 'ran')
    result = invoke(env, *args, data=data)
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    lines = [json.loads(line) for line in (result.stdout + result.stderr).splitlines()]
    timed = [row for row in lines if row.get('job') in ('new', 'held') and 'expires' in row]
    assert timed and all(row['expires'] == int(clock) + int(ttl) for row in timed), lines
    assert invoke(env, 'doctor').returncode == 0


for kind in ('claim', 'extend', 'batch', 'sem', 'with', 'with-sem'):
    for clock, ttl in [('0008', '010'), ('0', str(LIMIT)), (str(LIMIT - 1), '1'),
                       ('000000', '0' * 256 + '10')]:
        case(f'{kind} decimal clock={clock} ttl={ttl}', lambda base, k=kind, c=clock, t=ttl: valid_time(base, k, c, t))


def bad_clock(base, value):
    env = environment(base)
    before = refs(env)
    marker = base / 'ran'
    value = value.replace('MARKER', str(marker))
    env['GIT_LOCKS_NOW'] = value
    for args in [('check', 'free.md'), ('claim', '--job', 'new', '--holder', 'bob', 'new.md'),
                 ('sem', 'create', 'bad', '--capacity', '1'), ('extend', '--job', 'held', '--ttl', '1'),
                 ('with', '--job', 'new', '--holder', 'bob', 'new.md', '--', 'touch', str(marker))]:
        result = invoke(env, *args)
        assert result.returncode == 2 and not result.stdout, (args, result.returncode, result.stdout, result.stderr)
        assert json.loads(result.stderr)['reason'] == 'usage'
        assert refs(env) == before and not marker.exists()


for value in ('', '+5', '-1', 'abc', '08x', '1+1', str(LIMIT + 1), '9' * 128, 'arr[$(touch MARKER)]'):
    case(f'invalid clock {value}', lambda base, v=value: bad_clock(base, v))


def fake_clock(base, env, values):
    shim = base / 'shim'
    shim.mkdir()
    samples = base / 'samples'
    samples.write_text('\n'.join(values) + '\n')
    script = '''#!/usr/bin/python3
import os
import sys
from pathlib import Path
p = Path(os.environ['TIME_SAMPLES'])
values = p.read_text().splitlines()
value = values[0]
if len(values) > 1:
    p.write_text('\\n'.join(values[1:]) + '\\n')
with open(os.environ['TIME_LOG'], 'a') as log:
    log.write(value + '\\n')
if value == '!failure':
    print('date unavailable', file=sys.stderr)
    sys.exit(1)
print(value)
'''
    (shim / 'date').write_text(script)
    (shim / 'date').chmod(0o755)
    (shim / 'sleep').write_text('#!/bin/sh\nexit 0\n')
    (shim / 'sleep').chmod(0o755)
    return dict(env, PATH=str(shim) + os.pathsep + env['PATH'], TIME_SAMPLES=str(samples), TIME_LOG=str(base / 'clock.log'))


def invalid_wait(base, value):
    env = fake_clock(base, environment(base), ['100'])
    before = refs(env)
    marker = base / 'ran'
    result = invoke(env, 'with', '--job', 'new', '--holder', 'bob', '--wait', value,
                    '--sem', 'gpu', 'free.md', '--', 'touch', str(marker))
    assert result.returncode == 2 and not result.stdout, (result.returncode, result.stdout, result.stderr)
    assert json.loads(result.stderr)['reason'] == 'usage'
    assert refs(env) == before and not marker.exists()
    result = invoke(env, 'sem', 'acquire', 'gpu', '--job', 'new', '--holder', 'bob', '--wait', value)
    assert result.returncode == 2 and not result.stdout
    assert refs(env) == before


for value in ('-1', '+1', '1+1', str(LIMIT), str(LIMIT + 1), str(2**64 + 1), '9' * 128):
    case(f'invalid wait {value}', lambda base, v=value: invalid_wait(base, v))


def decimal_wait(base, value, samples, code=1):
    env = fake_clock(base, environment(base), samples)
    before = refs(env)
    result = invoke(env, 'with', '--job', 'new', '--holder', 'bob', '--wait', value,
                    'held.md', '--', 'touch', str(base / 'ran'))
    assert result.returncode == code, (result.returncode, result.stdout, result.stderr)
    assert (base / 'clock.log').read_text().splitlines() == samples
    assert refs(env) == before and not (base / 'ran').exists()
    if code == 2:
        assert json.loads(result.stderr)['reason'] == 'clock'


case('08 waits eight decimal seconds', lambda base: decimal_wait(base, '08', ['100', '107', '108']))
case('010 waits ten decimal seconds', lambda base: decimal_wait(base, '010', ['100', '109', '110']))
case('long leading-zero wait', lambda base: decimal_wait(base, '0' * 256 + '10', ['100', '109', '110']))
case('zero wait', lambda base: decimal_wait(base, '0000', ['100', '100']))
case('wall clock reversal fails explicitly', lambda base: decimal_wait(base, '10', ['100', '99'], code=2))


def invalid_system_clock(base, value):
    env = fake_clock(base, environment(base), [value])
    env.pop('GIT_LOCKS_NOW')
    before = refs(env)
    result = invoke(env, 'claim', '--job', 'new', '--holder', 'bob', 'new.md')
    assert result.returncode == 2 and not result.stdout
    assert json.loads(result.stderr)['reason'] == 'clock'
    assert refs(env) == before


for value in ('-1', '+5', 'abc', str(LIMIT + 1), '!failure'):
    case(f'invalid system clock {value}', lambda base, v=value: invalid_system_clock(base, v))


def fresh_retry(base, kind, overflow=False):
    env = fake_clock(base, environment(base, '100'), ['100'])
    env.pop('GIT_LOCKS_NOW')
    gate = base / 'gate'
    env['GIT_LOCKS_PAUSE_BEFORE_COMMIT'] = str(gate)
    args, data = action(kind, str(LIMIT - 100) if overflow else '10', base / 'ran')
    racer = subprocess.Popen([CLI, *args], env=env, text=True, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while not Path(str(gate) + '.ready').exists():
            assert racer.poll() is None, racer.communicate()
            assert time.monotonic() < deadline, 'racer did not reach commit gate'
            time.sleep(0.02)
        other = dict(env, GIT_LOCKS_NOW='100')
        other.pop('GIT_LOCKS_PAUSE_BEFORE_COMMIT')
        assert invoke(other, 'claim', '--job', 'other', '--holder', 'other', 'other.md').returncode == 0
        Path(env['TIME_SAMPLES']).write_text('200\n')
        gate.touch()
        stdout, stderr = racer.communicate(timeout=10)
        if overflow:
            assert racer.returncode == 2 and not stdout, (stdout, stderr)
            assert json.loads(stderr)['reason'] == 'usage'
            if kind == 'claim':
                assert invoke(other, 'show', '--job', 'new').returncode == 1
            else:
                assert json.loads(invoke(other, 'sem', 'show', 'gpu').stdout)['live'] == 0
        else:
            assert racer.returncode == 0 and not stderr, (stdout, stderr)
            row = json.loads(stdout)
            assert row['claimed'] == 200 and row['expires'] == 210, row
    finally:
        if racer.poll() is None:
            os.killpg(racer.pid, signal.SIGKILL)
            racer.wait()


for kind in ('claim', 'sem'):
    case(f'{kind} refreshes time after a lost publication', lambda base, k=kind: fresh_retry(base, k))
    case(f'{kind} rechecks expiry overflow after a lost publication', lambda base, k=kind: fresh_retry(base, k, True))

def clock_failure_cleanup(base):
    env = fake_clock(base, environment(base), ['100', '100', '!failure'])
    result = invoke(env, 'with', '--job', 'new', '--holder', 'bob', '--wait', '10',
                    '--sem', 'gpu', 'held.md', '--', 'touch', str(base / 'ran'))
    assert result.returncode == 2 and not result.stdout
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert [row.get('event') for row in events] == ['error'], events
    assert events[0]['reason'] == 'clock'
    assert not (base / 'ran').exists()
    assert json.loads(invoke(env, 'sem', 'show', 'gpu').stdout)['live'] == 0


case('clock failure in an atomic path/slot wait publishes neither resource', clock_failure_cleanup)

print(f'time arithmetic: {checks} cases passed; {len(failures)} failed')
assert not failures, failures
