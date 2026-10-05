#!/usr/bin/env python3
"""Corrupt cross-index authority must never become a free resource or a repair."""
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
ENV = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}


def git(store, *args, data=None):
    return subprocess.check_output(['git', '--git-dir=' + str(store), *args], input=data, text=True, env=ENV).strip()


def locks(env, args, data=None):
    return subprocess.run([CLI, *args], env=env, input=data, text=True, capture_output=True, timeout=15)


def entries(store):
    return {line.split('\t')[1]: line.split()[2] for line in git(store, 'ls-tree', '-r', 'refs/locks/state').splitlines()}


def publish(store, values):
    # Independent mktree construction, never the production private-index builder.
    root = {}
    for path, oid in values.items():
        parts = path.split('/')
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = oid

    def tree(node):
        rows = [f'040000 tree {tree(value)}\t{name}\n' if isinstance(value, dict)
                else f'100644 blob {value}\t{name}\n' for name, value in sorted(node.items())]
        return git(store, 'mktree', data=''.join(rows))

    oid = tree(root)
    git(store, 'update-ref', 'refs/locks/state', oid)
    return oid


def setup(base):
    store = base / 'store.git'
    env = dict(ENV, GIT_LOCKS_STORE=str(store), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='100')
    for args in (['claim', '--job', 'a', '--holder', 'alice', '--ttl', '60', 'src/a.md'],
                 ['claim', '--job', 'b', '--holder', 'alice', '--parent', 'a', '--ttl', '60', 'src/b.md'],
                 ['sem', 'create', 'gpu', '--capacity', '2'],
                 ['sem', 'acquire', 'gpu', '--job', 's1', '--holder', 'alice', '--ttl', '60'],
                 ['sem', 'acquire', 'gpu', '--job', 's2', '--holder', 'bob', '--ttl', '60']):
        result = locks(env, args)
        assert result.returncode == 0 and not result.stderr, result
    return env, store, entries(store)


def replace_record(store, values, key, before, after):
    old = values[key]
    record = git(store, 'cat-file', 'blob', old)
    assert before in record
    new = git(store, 'hash-object', '-w', '--stdin', data=record.replace(before, after) + '\n')
    for path, oid in list(values.items()):
        if oid == old:
            values[path] = new
    return new


def corrupt(store, values, mode):
    pa = 'paths/' + git(store, 'hash-object', '--stdin', data='src/a.md')
    pb = 'paths/' + git(store, 'hash-object', '--stdin', data='src/b.md')
    if mode == 'missing-path':
        del values[pa]
    elif mode == 'wrong-path':
        values[pa] = values['jobs/b']
    elif mode == 'orphan-path':
        del values['jobs/b']
    elif mode == 'stray-path':
        values['paths/' + 'f' * 40] = values['jobs/b']
    elif mode == 'missing-parent':
        replace_record(store, values, 'jobs/b', 'parent: a', 'parent: absent')
    elif mode == 'parent-holder':
        replace_record(store, values, 'jobs/b', 'holder: alice', 'holder: bob')
    elif mode == 'family-cycle':
        replace_record(store, values, 'jobs/a', 'holder: alice', 'holder: alice\nparent: b')
    elif mode == 'missing-meta':
        del values['sem/gpu/meta']
    elif mode == 'missing-gen':
        del values['sem/gpu/gen']
    elif mode == 'over-capacity':
        replace_record(store, values, 'sem/gpu/meta', 'capacity: 2', 'capacity: 1')
    elif mode == 'prefix-overlap':
        oid = replace_record(store, values, 'jobs/a', 'src/a.md', 'src/')
        del values[pa]
        values['paths/' + git(store, 'hash-object', '--stdin', data='src/')] = oid
    elif mode == 'unknown-entry':
        values['future/authority'] = values['jobs/a']
    else:
        raise AssertionError(mode)


def rejected_commands(marker):
    return [(['check', 'src/a.md'], None), (['list'], None), (['show', '--job', 'a'], None),
            (['ttl', '--job', 'a'], None), (['sem', 'show', 'gpu'], None), (['sem', 'list'], None),
            (['claim', '--job', 'new', '--holder', 'new', 'unrelated.md'], None),
            (['batch'], 'job: new\nholder: new\npaths:\nunrelated.md\n'),
            (['extend', '--job', 'a', '--ttl', '120'], None), (['release', '--job', 'a'], None),
            (['sweep'], None),
            (['with', '--job', 'new', '--holder', 'new', 'unrelated.md', '--', 'touch', str(marker)], None),
            (['sem', 'create', 'other', '--capacity', '1'], None),
            (['sem', 'acquire', 'gpu', '--job', 's3', '--holder', 'new'], None),
            (['sem', 'release', 'gpu', '--job', 's1'], None), (['sem', 'delete', 'gpu'], None)]


failures = []
checks = 0
for mode in ('missing-path', 'wrong-path', 'orphan-path', 'stray-path', 'missing-parent', 'parent-holder',
             'family-cycle', 'missing-meta', 'missing-gen', 'over-capacity', 'prefix-overlap', 'unknown-entry'):
    with tempfile.TemporaryDirectory(prefix='locks-integrity-') as tmp:
        base = Path(tmp)
        env, store, values = setup(base)
        corrupt(store, values, mode)
        bad_root = publish(store, values)
        marker = base / 'must-not-run'
        for args, data in rejected_commands(marker):
            # Restore the intentionally damaged fixture after a RED command mutates it.
            git(store, 'update-ref', 'refs/locks/state', bad_root)
            marker.unlink(missing_ok=True)
            before_objects = git(store, 'cat-file', '--batch-all-objects', '--batch-check=%(objectname)')
            result = locks(env, args, data)
            try:
                assert result.returncode == 2 and not result.stdout, (result.returncode, result.stdout, result.stderr)
                row = json.loads(result.stderr)
                VALIDATOR.validate(row)
                assert row['event'] == 'error' and row['reason'] == 'store-read', row
                assert git(store, 'rev-parse', 'refs/locks/state') == bad_root, 'root changed'
                assert git(store, 'cat-file', '--batch-all-objects', '--batch-check=%(objectname)') == before_objects, 'objects were written before refusing damaged authority'
                assert not marker.exists(), 'wrapped command ran'
                checks += 1
            except Exception as error:
                failures.append((mode, args[0], str(error)))
                print('FAIL', mode, args, str(error), flush=True)
        git(store, 'update-ref', 'refs/locks/state', bad_root)
        diagnosis = locks(env, ['doctor'])
        try:
            assert diagnosis.returncode == 1 and not diagnosis.stderr, diagnosis
            rows = [json.loads(line) for line in diagnosis.stdout.splitlines()]
            for row in rows:
                VALIDATOR.validate(row)
            assert rows[-1]['healthy'] is False and rows[-1]['findings'] > 0
            assert git(store, 'rev-parse', 'refs/locks/state') == bad_root
            checks += 1
        except Exception as error:
            failures.append((mode, 'doctor', str(error)))
            print('FAIL', mode, 'doctor', str(error), flush=True)
        print('checked', mode, flush=True)

# Passing time is not structural damage. Expired parents can be swept, expired
# slots do not count against capacity, and a job may overlap its own paths.
with tempfile.TemporaryDirectory(prefix='locks-integrity-valid-') as tmp:
    base = Path(tmp)
    env, store, values = setup(base)
    replace_record(store, values, 'jobs/a', 'expires: 160', 'expires: 100')
    replace_record(store, values, 'sem/gpu/meta', 'capacity: 2', 'capacity: 1')
    replace_record(store, values, 'sem/gpu/slots/s1', 'expires: 160', 'expires: 100')
    publish(store, values)
    for args in (['check', 'unrelated.md'], ['sem', 'show', 'gpu'], ['sweep'],
                 ['claim', '--job', 'overlap', '--holder', 'alice', 'own/', 'own/a.md', 'own/deep/', 'own/deep/b.md']):
        result = locks(env, args)
        assert result.returncode == 0 and not result.stderr, result
        checks += 1
    result = locks(env, ['doctor'])
    assert result.returncode == 0 and json.loads(result.stdout.splitlines()[-1])['healthy'] is True, result
    checks += 1
print(f'store integrity: {checks} passed; {len(failures)} failed')
assert not failures, f'{len(failures)} integrity checks failed; see above'
