#!/usr/bin/env python3
"""Real Git permission/lock faults and publication retry classification."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import argparse
from collections import Counter
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
failures = []
checks = 0


def run(env, *args, data=None, timeout=5):
    process = subprocess.Popen([CLI, *args], env=env, text=True, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = process.communicate(data, timeout=timeout)
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise
    return subprocess.CompletedProcess(args, process.returncode, out, err)


def git(env, *args):
    return subprocess.check_output([GIT, '--git-dir=' + env['GIT_LOCKS_STORE'], *args], text=True)


def roots(env):
    return git(env, 'for-each-ref', '--format=%(refname) %(objectname)')


def blobs(env):
    return Counter(git(env, 'cat-file', '--batch-all-objects', '--batch-check=%(objecttype)').splitlines())['blob']


def setup(base):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_LOCKS_STORE=str(base / 'store.git'), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='1000000')
    for args in [('claim', '--job', 'held', '--holder', 'alice', '--ttl', '1', 'held.md'),
                 ('sem', 'create', 'gpu', '--capacity', '2'),
                 ('sem', 'acquire', 'gpu', '--job', 'held', '--holder', 'alice', '--ttl', '1')]:
        result = run(env, *args)
        assert result.returncode == 0, result.stderr
    shim = base / 'shim'
    shim.mkdir()
    script = '''#!/usr/bin/python3
import json, os, subprocess, sys
from pathlib import Path
args = sys.argv[1:]
if 'hash-object' in args and '-w' not in args and os.environ.get('INJECT_HASH_FAILURE'):
    print('fatal: injected hash failure', file=sys.stderr)
    sys.exit(128)
if 'update-ref' not in args:
    os.execv(os.environ['REAL_GIT'], [os.environ['REAL_GIT'], *args])
data = sys.stdin.read()
if os.environ.get('INJECT_WRITE_FAILURE'):
    result = subprocess.CompletedProcess(args, 128, '', 'fatal: injected permission failure\\nwith "quotes"\\n')
else:
    result = subprocess.run([os.environ['REAL_GIT'], *args], input=data, text=True, capture_output=True)
with open(os.environ['WRITES_LOG'], 'a') as log:
    log.write(json.dumps({'input': data, 'exit': result.returncode, 'stderr': result.stderr}) + '\\n')
print(result.stdout, end='')
print(result.stderr, end='', file=sys.stderr)
sys.exit(result.returncode)
'''
    (shim / 'git').write_text(script)
    (shim / 'git').chmod(0o755)
    env.update(PATH=str(shim) + os.pathsep + env['PATH'], REAL_GIT=GIT, WRITES_LOG=str(base / 'writes.jsonl'))
    return env


def writes(env):
    path = Path(env['WRITES_LOG'])
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def command(kind):
    if kind == 'claim':
        return ['claim', '--job', 'new', '--holder', 'bob', 'new.md'], None
    if kind == 'batch':
        return ['batch'], 'job: new\nholder: bob\npaths:\nnew.md\n'
    if kind == 'extend':
        return ['extend', '--job', 'held', '--ttl', '10'], None
    if kind == 'release':
        return ['release', '--job', 'held'], None
    if kind == 'sweep':
        return ['sweep'], None
    if kind == 'with':
        return ['with', '--job', 'new', '--holder', 'bob', '--wait', '10', 'new.md', '--', 'echo', 'MUST-NOT-RUN'], None
    return {'sem-create': ['sem', 'create', 'new', '--capacity', '1'],
            'sem-acquire': ['sem', 'acquire', 'gpu', '--job', 'new', '--holder', 'bob'],
            'sem-release': ['sem', 'release', 'gpu', '--job', 'held'],
            'sem-delete': ['sem', 'delete', 'gpu']}[kind], None


def assert_error(result):
    assert result.returncode == 2 and not result.stdout, (result.returncode, result.stdout, result.stderr)
    row = json.loads(result.stderr)
    VALIDATOR.validate(row)
    assert row['reason'] == 'store-write', row


def permanent(base, kind):
    env = setup(base)
    if kind in ('sweep', 'sem-delete'):
        env['GIT_LOCKS_NOW'] = '1000002'
    env['INJECT_WRITE_FAILURE'] = '1'
    before = roots(env)
    count = blobs(env)
    args, data = command(kind)
    result = run(env, *args, data=data)
    assert_error(result)
    assert roots(env) == before
    assert len(writes(env)) == 1, writes(env)
    assert blobs(env) - count <= (2 if kind.startswith('sem-') else 1), 'failure replanned and rewrote records'


def lockfile(base, transient=False):
    env = setup(base)
    git(env, 'config', 'core.filesRefLockTimeout', '-1') # repository config must not turn bounded retries into an infinite wait
    lock = Path(env['GIT_LOCKS_STORE']) / 'refs/locks/state.lock'
    lock.write_text('owned by another writer\n')
    count = blobs(env)
    before = roots(env)
    started = time.monotonic()
    process = subprocess.Popen([CLI, 'claim', '--job', 'new', '--holder', 'bob', 'new.md'],
                               env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True)
    try:
        if transient:
            deadline = time.monotonic() + 2
            while not writes(env):
                assert time.monotonic() < deadline and process.poll() is None
                time.sleep(0.01)
            # Only the test, acting as the other writer, removes its lock file.
            lock.unlink()
        out, err = process.communicate(timeout=5)
        result = subprocess.CompletedProcess([], process.returncode, out, err)
        assert blobs(env) - count == 1, 'lock contention rebuilt the candidate record'
        assert 1 <= len(writes(env)) <= 6, writes(env)
        assert len({row['input'] for row in writes(env)}) == 1, 'lock retry changed the publication candidate'
        if transient:
            assert result.returncode == 0 and not result.stderr, result
        else:
            assert_error(result)
            assert roots(env) == before
            assert lock.read_text() == 'owned by another writer\n'
            assert time.monotonic() - started < 2, 'abandoned lock was retried as stale state'
        print(f'root lock: transient={transient}, attempts={len(writes(env))}, elapsed={time.monotonic() - started:.3f}s, new_blobs=1')
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def readonly(base, target):
    env = setup(base)
    store = Path(env['GIT_LOCKS_STORE'])
    before = roots(env)
    if target == 'objects':
        directories = [path for path in (store / 'objects').rglob('*') if path.is_dir()]
        directories.append(store / 'objects')
    else:
        directories = [store / 'refs/locks']
    try:
        for path in directories:
            path.chmod(0o555)
        result = run(env, 'claim', '--job', 'new', '--holder', 'bob', 'new.md')
        assert_error(result)
        assert roots(env) == before
        assert len(writes(env)) == (0 if target == 'objects' else 1)
    finally:
        for path in directories:
            path.chmod(0o755)


def case(label, body):
    global checks
    try:
        with tempfile.TemporaryDirectory(prefix='locks-write-') as tmp:
            body(Path(tmp))
        checks += 1
    except Exception as error:
        detail = error.message if isinstance(error, jsonschema.ValidationError) else str(error)
        failures.append((label, detail))
        print(f'FAIL {label}: {detail}', flush=True)


def migration_failure(base):
    env = setup(base)
    entries = git(env, 'ls-tree', '-r', 'refs/locks/state').splitlines()
    for row in entries:
        metadata, name = row.split('\t')
        git(env, 'update-ref', 'refs/locks/' + name, metadata.split()[2])
    git(env, 'update-ref', '-d', 'refs/locks/state')
    env['INJECT_WRITE_FAILURE'] = '1'
    before = roots(env)
    result = run(env, 'migrate', '--offline')
    assert_error(result)
    assert roots(env) == before and len(writes(env)) == 1


def read_hash_failure(base):
    env = setup(base)
    env['INJECT_HASH_FAILURE'] = '1'
    before = roots(env)
    result = run(env, 'check', 'free.md')
    assert result.returncode == 2 and not result.stdout
    row = json.loads(result.stderr)
    VALIDATOR.validate(row)
    assert row['reason'] == 'store-read'
    assert roots(env) == before and not writes(env)


def packed_lock(base):
    env = setup(base)
    entries = git(env, 'ls-tree', '-r', 'refs/locks/state').splitlines()
    for row in entries:
        metadata, name = row.split('\t')
        git(env, 'update-ref', 'refs/locks/' + name, metadata.split()[2])
    git(env, 'update-ref', '-d', 'refs/locks/state')
    git(env, 'pack-refs', '--all', '--prune')
    git(env, 'config', 'core.packedRefsTimeout', '-1')
    lock = Path(env['GIT_LOCKS_STORE']) / 'packed-refs.lock'
    lock.write_text('owned packed refs lock\n')
    before = roots(env)
    result = run(env, 'migrate', '--offline')
    assert_error(result)
    assert roots(env) == before and len(writes(env)) == 1
    assert lock.read_text() == 'owned packed refs lock\n'


parser = argparse.ArgumentParser()
parser.add_argument('--red', action='store_true', help='only the initial permanent-error and abandoned-lock reproductions')
args = parser.parse_args()
kinds = ('claim',) if args.red else ('claim', 'batch', 'extend', 'release', 'sweep', 'with', 'sem-create', 'sem-acquire', 'sem-release', 'sem-delete')
for kind in kinds:
    case(f'{kind}: permanent publication failure', lambda base, k=kind: permanent(base, k))
case('abandoned root lock', lockfile)
if not args.red:
    case('transient root lock', lambda base: lockfile(base, True))
    case('read-only refs', lambda base: readonly(base, 'refs'))
    case('read-only objects', lambda base: readonly(base, 'objects'))
    case('failed offline migration', migration_failure)
    case('path hash read failure', read_hash_failure)
    case('packed-refs lock during migration', packed_lock)
print(f'store write failures: {checks} cases passed; {len(failures)} failed')
assert not failures, failures
