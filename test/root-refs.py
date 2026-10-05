#!/usr/bin/env python3
"""Root absence and publication must not follow hidden symbolic authority."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import json
import os
import shutil
import signal
import tempfile
import time

import jsonschema

CLI = str(ROOT / 'bin/git-locks')
GIT = shutil.which('git')
ENV = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))
STATE = 'refs/locks/state'
TARGET = 'refs/private/target'


def git(store, *args, data=None, status=0):
    result = subprocess.run([GIT, '--git-dir=' + str(store), *args], env=ENV, input=data,
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == status, result
    return result.stdout.strip()


def setup(base):
    store = base / 'store.git'
    git(store, 'init', '-q', '--bare', str(store))
    return store, dict(ENV, GIT_LOCKS_STORE=str(store), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='100')


def locks(env, args):
    result = subprocess.run([CLI, *args], env=env, text=True, capture_output=True, timeout=15)
    for line in (result.stdout + result.stderr).splitlines():
        VALIDATOR.validate(json.loads(line))
    return result


def files(store):
    return {str(path.relative_to(store)): path.read_bytes() for path in store.rglob('*') if path.is_file()}


def damaged(base, mode):
    store, env = setup(base)
    root = store / STATE
    root.parent.mkdir(exist_ok=True)
    if mode in ('dangling', 'chain', 'cycle', 'resolved'):
        if mode == 'resolved':
            git(store, 'update-ref', TARGET, git(store, 'mktree', data=''))
        elif mode == 'chain':
            git(store, 'symbolic-ref', TARGET, 'refs/private/missing')
        elif mode == 'cycle':
            git(store, 'symbolic-ref', TARGET, STATE)
        git(store, 'symbolic-ref', STATE, TARGET)
    else:
        root.write_text({'empty': '', 'malformed': 'not a ref\n', 'missing-object': 'f' * 40 + '\n'}[mode])
    before = files(store)
    marker = base / 'must-not-run'
    actions = [('check', 'x.md'), ('list',), ('doctor',), ('claim', '--job', 'new', '--holder', 'alice', 'x.md'),
               ('sem', 'create', 'gpu', '--capacity', '1'), ('migrate', '--offline'),
               ('with', '--job', 'new', '--holder', 'alice', 'x.md', '--', 'touch', str(marker))]
    errors = []
    for args in actions:
        # Each command starts from the original damaged fixture, even during RED.
        shutil.rmtree(store)
        for name, data in before.items():
            path = store / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (store / 'objects/info').mkdir(parents=True, exist_ok=True)
        (store / 'objects/pack').mkdir(parents=True, exist_ok=True)
        marker.unlink(missing_ok=True)
        result = locks(env, args)
        try:
            assert result.returncode == 2 and not result.stdout, result
            assert json.loads(result.stderr)['reason'] == 'store-read', result.stderr
            assert files(store) == before, 'damaged store or target was modified'
            assert not marker.exists(), 'wrapped command executed'
        except Exception as error:
            errors.append((args[0], str(error)))
    assert not errors, errors


def publication_race(base, mode):
    store, env = setup(base)
    old = ''
    if mode in ('existing-same', 'existing-different', 'migration'):
        result = locks(env, ['claim', '--job', 'held', '--holder', 'alice', 'held.md'])
        assert result.returncode == 0, result
        old = git(store, 'rev-parse', STATE)
    action = ['claim', '--job', 'new', '--holder', 'bob', 'new.md']
    if mode == 'migration':
        for line in git(store, 'ls-tree', '-r', STATE).splitlines():
            metadata, name = line.split('\t')
            git(store, 'update-ref', 'refs/locks/' + name, metadata.split()[2])
        git(store, 'update-ref', '-d', STATE)
        action = ['migrate', '--offline']
    target_oid = old if mode == 'existing-same' else git(store, 'mktree', data='') if mode == 'existing-different' else ''
    if target_oid:
        git(store, 'update-ref', TARGET, target_oid)
    shim = base / 'shim'
    shim.mkdir()
    (shim / 'git').write_text('''#!/usr/bin/python3
import os,subprocess,sys,time
from pathlib import Path
if 'update-ref' not in sys.argv[1:]:
    os.execv(os.environ['REAL_GIT'], [os.environ['REAL_GIT'], *sys.argv[1:]])
data=sys.stdin.read()
gate=Path(os.environ['ROOT_GATE'])
Path(str(gate)+'.ready').touch()
deadline=time.monotonic()+10
while not gate.exists():
    if time.monotonic()>deadline: sys.exit(77)
    time.sleep(.01)
sys.exit(subprocess.run([os.environ['REAL_GIT'], *sys.argv[1:]], input=data, text=True).returncode)
''')
    (shim / 'git').chmod(0o755)
    gate = base / 'gate'
    racer = subprocess.Popen([CLI, *action], env=dict(env, PATH=str(shim) + os.pathsep + env['PATH'],
                              REAL_GIT=GIT, ROOT_GATE=str(gate)), text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while not Path(str(gate) + '.ready').exists():
            assert racer.poll() is None, racer.communicate()
            assert time.monotonic() < deadline, 'publication gate not reached'
            time.sleep(.01)
        git(store, 'symbolic-ref', STATE, TARGET)
        gate.touch()
        out, err = racer.communicate(timeout=15)
        assert racer.returncode in (0, 2), (racer.returncode, out, err)
        for line in (out + err).splitlines():
            VALIDATOR.validate(json.loads(line))
        actual_target = git(store, 'for-each-ref', '--format=%(objectname)', TARGET)
        assert actual_target == target_oid, ('publication followed the symbolic target', target_oid, actual_target)
        if racer.returncode == 0:
            git(store, 'symbolic-ref', '--quiet', '--no-recurse', STATE, status=1)
            assert locks(env, ['doctor']).returncode == 0
            assert locks(env, ['show', '--job', 'held' if mode == 'migration' else 'new']).returncode == 0
        else:
            assert not out
    finally:
        if racer.poll() is None:
            os.killpg(racer.pid, signal.SIGKILL)
            racer.wait()


def packed(base):
    store, env = setup(base)
    assert locks(env, ['claim', '--job', 'a', '--holder', 'alice', 'a.md']).returncode == 0
    git(store, 'pack-refs', '--all', '--prune')
    assert not (store / STATE).exists()
    assert locks(env, ['check', 'a.md']).returncode == 1
    assert locks(env, ['claim', '--job', 'b', '--holder', 'bob', 'b.md']).returncode == 0
    assert locks(env, ['doctor']).returncode == 0


failures = []
checks = 0


def case(label, body):
    global checks
    try:
        with tempfile.TemporaryDirectory(prefix='locks-root-') as tmp:
            body(Path(tmp))
        checks += 1
        print('PASS', label, flush=True)
    except Exception as error:
        failures.append((label, str(error)))
        print('FAIL', label, str(error), flush=True)


for mode in ('dangling', 'chain', 'cycle', 'resolved', 'empty', 'malformed', 'missing-object'):
    case('damaged root: ' + mode, lambda base, mode=mode: damaged(base, mode))
for mode in ('first', 'existing-same', 'existing-different', 'migration'):
    case('symbol introduced at publication: ' + mode, lambda base, mode=mode: publication_race(base, mode))
case('packed root remains valid authority', packed)
print(f'root refs: {checks} cases passed; {len(failures)} failed')
assert not failures, f'{len(failures)} root-reference cases failed; see above'
