#!/usr/bin/env python3
"""Store initialization is private until ready, including concurrent first use."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

from concurrent.futures import ThreadPoolExecutor
import json
import os
import shutil
import signal
import tempfile
import time

import jsonschema

CLI = str(ROOT / 'bin/git-locks')
GIT = shutil.which('git')
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))
checks = 0
failures = []


def environment(base):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_LOCKS_STORE=str(base / 'store.git'), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='1000000')
    return env


def locks(env, *args):
    process = subprocess.Popen([CLI, *args], env=env, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    for line in (out + err).splitlines():
        try:
            VALIDATOR.validate(json.loads(line))
        except (ValueError, jsonschema.ValidationError) as error:
            raise AssertionError((args, process.returncode, out, err)) from error
    return subprocess.CompletedProcess(args, process.returncode, out, err)


def assert_clean(base):
    assert not list(base.rglob('*.init.*')), 'an initialization directory was left behind'


def races(base):
    results = []
    for round_id in range(15):
        target = base / str(round_id)
        env = environment(target)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(locks, env, 'claim', '--job', f'j{i}', '--holder', 'worker', f'{i}.md') for i in range(4)]
            results.extend(f.result() for f in futures)
        current = locks(env, 'list')
        assert current.returncode == 0, current
        assert {json.loads(row)['job'] for row in current.stdout.splitlines()} == {'j0', 'j1', 'j2', 'j3'}, current
        assert locks(env, 'doctor').returncode == 0
        assert_clean(target)
    assert all(result.returncode == 0 and not result.stderr for result in results), results
    print('concurrent first use: 60/60 independent claims succeeded in 15 fresh stores')


def gated_init(base, fail=False):
    env = environment(base)
    shim = base / 'shim'
    shim.mkdir()
    gate = base / 'gate'
    log = base / 'ready'
    script = '''#!/usr/bin/python3
import os, subprocess, sys, time
from pathlib import Path
args = sys.argv[1:]
if 'init' not in args:
    os.execv(os.environ['REAL_GIT'], [os.environ['REAL_GIT'], *args])
result = subprocess.run([os.environ['REAL_GIT'], *args])
Path(os.environ['INIT_READY']).write_text(args[-1])
while not Path(os.environ['INIT_GATE']).exists():
    time.sleep(0.01)
if os.environ.get('INIT_FAIL'):
    print('fatal: injected initialization failure', file=sys.stderr)
    sys.exit(128)
sys.exit(result.returncode)
'''
    (shim / 'git').write_text(script)
    (shim / 'git').chmod(0o755)
    env.update(PATH=str(shim) + os.pathsep + env['PATH'], REAL_GIT=GIT,
               INIT_READY=str(log), INIT_GATE=str(gate), INIT_FAIL='1' if fail else '')
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(locks, env, 'claim', '--job', 'j', '--holder', 'worker', 'x.md')
        try:
            deadline = time.monotonic() + 5
            while not log.exists():
                assert time.monotonic() < deadline and not result.done()
                time.sleep(0.01)
            assert not Path(env['GIT_LOCKS_STORE']).exists(), 'the store was exposed before git init completed'
        finally:
            gate.touch()
        completed = result.result()
    if fail:
        assert completed.returncode == 2 and not completed.stdout, completed
        assert json.loads(completed.stderr)['reason'] == 'store-write'
        assert not Path(env['GIT_LOCKS_STORE']).exists(), 'a failed initialization exposed a usable store'
    else:
        assert completed.returncode == 0 and not completed.stderr, completed
        assert locks(env, 'doctor').returncode == 0
    assert_clean(base)


def occupied(base, kind):
    env = environment(base)
    target = Path(env['GIT_LOCKS_STORE'])
    if kind == 'file':
        target.write_text('preserve file\n')
    else:
        target.mkdir()
        if kind == 'nonempty':
            (target / 'keep').write_text('preserve directory\n')
        elif kind == 'fake':
            (target / 'HEAD').write_text('ref: refs/heads/main\n')
    before = {str(p.relative_to(base)): p.read_bytes() for p in base.rglob('*') if p.is_file()}
    result = locks(env, 'claim', '--job', 'j', '--holder', 'worker', 'x.md')
    assert result.returncode == 2 and not result.stdout, result
    assert json.loads(result.stderr)['reason'] == 'store-read'
    after = {str(p.relative_to(base)): p.read_bytes() for p in base.rglob('*') if p.is_file()}
    assert before == after, (before, after)
    assert_clean(base)


def parent_failure(base):
    env = environment(base)
    parent = base / 'readonly'
    parent.mkdir()
    env['GIT_LOCKS_STORE'] = str(parent / 'nested/store.git')
    try:
        parent.chmod(0o555)
        result = locks(env, 'claim', '--job', 'j', '--holder', 'worker', 'x.md')
        assert result.returncode == 2 and not result.stdout, result
        assert json.loads(result.stderr)['reason'] == 'store-write'
        assert not list(parent.iterdir())
    finally:
        parent.chmod(0o755)



def publish_race(base):
    env = environment(base)
    shim = base / 'shim'
    shim.mkdir()
    markers = base / 'markers'
    markers.mkdir()
    script = '''#!/usr/bin/python3
import os, sys, time
from pathlib import Path
markers = Path(os.environ['MV_MARKERS'])
(markers / str(os.getpid())).touch()
deadline = time.monotonic() + 5
while len(list(markers.iterdir())) != 4:
    if time.monotonic() >= deadline:
        sys.exit(77)
    time.sleep(0.01)
os.execv(os.environ['REAL_MV'], [os.environ['REAL_MV'], *sys.argv[1:]])
'''
    (shim / 'mv').write_text(script)
    (shim / 'mv').chmod(0o755)
    env.update(PATH=str(shim) + os.pathsep + env['PATH'], REAL_MV=shutil.which('mv'), MV_MARKERS=str(markers))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: locks(env, 'claim', '--job', f'j{i}', '--holder', 'worker', f'{i}.md'), range(4)))
    assert all(result.returncode == 0 and not result.stderr for result in results), results
    assert len(list(markers.iterdir())) == 4, 'did not force four concurrent directory publications'
    assert len(locks(env, 'list').stdout.splitlines()) == 4
    assert_clean(base)


def no_templates(base):
    env = environment(base)
    template = base / 'template'
    template.mkdir()
    (template / 'foreign-data').write_text('this does not belong in the lock store')
    env['GIT_TEMPLATE_DIR'] = str(template)
    result = locks(env, 'claim', '--job', 'j', '--holder', 'worker', 'x.md')
    assert result.returncode == 0 and not result.stderr, result
    assert not (Path(env['GIT_LOCKS_STORE']) / 'foreign-data').exists()
    assert_clean(base)


def case(label, body):
    global checks
    try:
        with tempfile.TemporaryDirectory(prefix='locks-init-') as tmp:
            body(Path(tmp))
        checks += 1
    except Exception as error:
        detail = error.message if isinstance(error, jsonschema.ValidationError) else str(error)
        failures.append((label, detail))
        print(f'FAIL {label}: {detail}', flush=True)


case('concurrent initialization', races)
case('simultaneous directory publication', publish_race)
case('private preparation', gated_init)
case('failed private preparation', lambda base: gated_init(base, True))
for kind in ('empty', 'nonempty', 'fake', 'file'):
    case(f'occupied destination: {kind}', lambda base, k=kind: occupied(base, k))
case('unwritable parent', parent_failure)
case('foreign templates are excluded', no_templates)
print(f'store bootstrap: {checks} cases passed; {len(failures)} failed')
assert not failures, failures
