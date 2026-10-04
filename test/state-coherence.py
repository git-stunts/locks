#!/usr/bin/env python3
"""Black-box checks for the immutable state witness and fail-closed reads."""
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

VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))

with tempfile.TemporaryDirectory(prefix='locks-state-') as tmp:
    store = Path(tmp) / 'store.git'
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_LOCKS_STORE=str(store), GIT_LOCKS_NOW='1000000')

    def locks(*args, expected=0):
        result = subprocess.run([str(ROOT / 'bin/git-locks'), *args], cwd=tmp, env=env, text=True, capture_output=True, timeout=20)
        assert result.returncode == expected, (args, result.returncode, result.stdout, result.stderr)
        for line in (result.stdout + result.stderr).splitlines():
            VALIDATOR.validate(json.loads(line))
        if expected == 0:
            assert not result.stderr, (args, result.stderr)
        return result

    def git(*args, data=None):
        return subprocess.check_output(['git', f'--git-dir={store}', *args], input=data, text=True)

    def refs():
        return dict(line.split() for line in git('for-each-ref', '--format=%(refname) %(objectname)', 'refs/locks/').splitlines())

    def state():
        current = refs()
        assert len(current) == 1 and 'refs/locks/state' in current, current
        oid = current['refs/locks/state']
        assert git('cat-file', '-t', oid).strip() == 'tree'
        observed = {}
        for line in git('ls-tree', '-r', oid).splitlines():
            metadata, path = line.split('\t')
            mode, kind, value = metadata.split()
            assert (mode, kind) == ('100644', 'blob')
            observed[path] = value
        return oid, observed

    def witness():
        return state()[0]

    locks('claim', '--job', 'parent', '--holder', 'alice', 'src/a.md')
    first = witness()
    locks('claim', '--job', 'child', '--holder', 'alice', '--parent', 'parent', 'src/b.md')
    assert witness() != first
    locks('extend', '--job', 'parent', '--ttl', '500')
    witness()
    locks('sem', 'create', 'gpu', '--capacity', '1')
    witness()
    locks('sem', 'acquire', 'gpu', '--job', 'slot', '--holder', 'bob')
    witness()
    locks('sem', 'release', 'gpu', '--job', 'slot')
    witness()
    locks('sem', 'delete', 'gpu')
    witness()
    locks('release', '--job', 'parent')
    witness()
    assert not any(key.startswith(('jobs/', 'paths/', 'sem/')) for key in state()[1])

    # Git shares an unchanged semaphore subtree while path reservations change.
    locks('sem', 'create', 'gpu', '--capacity', '1')
    subtree = git('rev-parse', 'refs/locks/state:sem').strip()
    locks('claim', '--job', 'held', '--holder', 'alice', 'folder/child.md')
    assert git('rev-parse', 'refs/locks/state:sem').strip() == subtree
    assert git('ls-tree', '-r', first), 'an older root still identifies its entire immutable state'

    # Two plans from one root: conflicting claims cannot both win; independent
    # ones must replan and preserve both updates. No timing-based race guesses.
    for index, mode in enumerate(('conflict', 'disjoint', 'sem-create')):
        conflict = mode == 'conflict'
        gate = Path(tmp) / f'gate-{index}'
        racer_env = dict(env, GIT_LOCKS_PAUSE_BEFORE_COMMIT=str(gate))
        path = f'race-{index}.md'
        action = ['sem', 'create', 'new-sem', '--capacity', '1'] if mode == 'sem-create' else ['claim', '--job', f'a{index}', '--holder', 'alice', path]
        racer = subprocess.Popen([str(ROOT / 'bin/git-locks'), *action],
                                 cwd=tmp, env=racer_env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while not Path(str(gate) + '.ready').exists():
                assert racer.poll() is None, racer.communicate()
                assert time.monotonic() < deadline, 'publication gate not reached'
                time.sleep(0.02)
            locks('claim', '--job', f'b{index}', '--holder', 'bob', path if conflict else f'other-{index}.md')
            gate.touch()
            stdout, stderr = racer.communicate(timeout=20)
            assert racer.returncode == (1 if conflict else 0), (stdout, stderr)
            jobs = {row['job'] for row in map(json.loads, locks('list').stdout.splitlines())}
            assert f'b{index}' in jobs
            if mode == 'sem-create':
                locks('sem', 'show', 'new-sem')
            else:
                assert (f'a{index}' in jobs) == (not conflict)
        finally:
            if racer.poll() is None:
                racer.kill()
                racer.wait()

    # A legacy store cannot be silently imported from a potentially torn scan.
    root, current = state()
    git('update-ref', 'refs/locks/jobs/legacy', current['jobs/b0'])
    for command in (('check', 'elsewhere'), ('claim', '--job', 'x', '--holder', 'x', 'elsewhere'), ('doctor',)):
        result = locks(*command, expected=2)
        assert not result.stdout and json.loads(result.stderr)['reason'] == 'store-read'
    assert git('rev-parse', 'refs/locks/state').strip() == root
    git('update-ref', '-d', 'refs/locks/jobs/legacy')
    git('update-ref', 'refs/locks/state', current['jobs/b0'])
    result = locks('check', 'elsewhere', expected=2)
    assert json.loads(result.stderr)['reason'] == 'store-read'
    git('update-ref', 'refs/locks/state', root)
    locks('doctor')
    # Downgrade a stopped isolated fixture to the historical per-ref layout,
    # then migrate explicitly. The import must preserve every object identity.
    old_root, old_entries = state()
    for name, oid in old_entries.items():
        git('update-ref', 'refs/locks/' + name, oid)
    git('update-ref', '-d', 'refs/locks/state')
    locks('migrate', expected=2)
    assert 'refs/locks/state' not in refs()
    imported = json.loads(locks('migrate', '--offline').stdout)
    assert imported['entries'] == len(old_entries)
    assert state() == (old_root, old_entries)
    assert json.loads(locks('migrate', '--offline').stdout) == imported
    locks('doctor')
    # A symbolic authority must never redirect writes into an unrelated ref.
    git('update-ref', 'refs/private/other', old_root)
    git('symbolic-ref', 'refs/locks/state', 'refs/private/other')
    result = locks('claim', '--job', 'redirected', '--holder', 'alice', 'bad.md', expected=2)
    assert json.loads(result.stderr)['reason'] == 'store-read'
    assert git('rev-parse', 'refs/private/other').strip() == old_root
    git('update-ref', '--no-deref', 'refs/locks/state', old_root)
    git('update-ref', '-d', 'refs/private/other')

    # An unavailable scratch directory now prevents validating path identity
    # before planning. It must emit a structured read error and preserve authority.
    result = subprocess.run([str(ROOT / 'bin/git-locks'), 'claim', '--job', 'failed', '--holder', 'alice', 'failed.md'],
                            cwd=tmp, env=dict(env, TMPDIR=str(Path(tmp) / 'missing-dir')),
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 2 and not result.stdout, result
    error = json.loads(result.stderr)
    VALIDATOR.validate(error)
    assert error['reason'] == 'store-read'
    assert state() == (old_root, old_entries)

    # Make scratch unwritable after snapshot validation, so the private index
    # still has an independent, real-filesystem write-failure regression.
    scratch = Path(tmp) / 'index-scratch'
    scratch.mkdir()
    gate = Path(tmp) / 'index-gate'
    racer = subprocess.Popen([str(ROOT / 'bin/git-locks'), 'claim', '--job', 'failed-index', '--holder', 'alice', 'failed.md'],
                             cwd=tmp, env=dict(env, TMPDIR=str(scratch), GIT_LOCKS_PAUSE_AFTER_READ=str(gate)),
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while not Path(str(gate) + '.ready').exists():
            assert racer.poll() is None, racer.communicate()
            assert time.monotonic() < deadline, 'snapshot gate not reached'
            time.sleep(.02)
        scratch.chmod(0o555)
        gate.touch()
        out, err = racer.communicate(timeout=10)
        assert racer.returncode == 2 and not out, (out, err)
        error = json.loads(err)
        VALIDATOR.validate(error)
        assert error['reason'] == 'store-write', error
        assert state() == (old_root, old_entries)
    finally:
        scratch.chmod(0o755)
        if racer.poll() is None:
            os.killpg(racer.pid, signal.SIGKILL)
            racer.wait()

    # Tree reachability, not loose-object grace, retains current records.
    git('gc', '--prune=now')
    locks('doctor')
    assert state() == (old_root, old_entries)

    # Git's other supported object format needs the same publication/deletion
    # behavior; a hard-coded forty-zero index deletion is not sufficient.
    store = Path(tmp) / 'sha256.git'
    subprocess.run(['git', 'init', '-q', '--bare', '--object-format=sha256', str(store)], check=True)
    env['GIT_LOCKS_STORE'] = str(store)
    locks('claim', '--job', 'sha', '--holder', 'alice', 'x.md')
    assert len(state()[0]) == 64
    locks('release', '--job', 'sha')
    assert not state()[1]

    # Tree keys preserve distinct job names even on a case-insensitive host.
    git('config', 'core.ignorecase', 'true')
    locks('claim', '--job', 'Case', '--holder', 'alice', 'one.md')
    locks('claim', '--job', 'case', '--holder', 'bob', 'two.md')
    assert set(state()[1]) >= {'jobs/Case', 'jobs/case'}
    locks('doctor')
print('state root: writers, structural sharing, conflicting/disjoint races, legacy and type refusal passed')
