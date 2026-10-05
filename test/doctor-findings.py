#!/usr/bin/env python3
"""Doctor must distinguish an unreadable record from a proven index defect."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import json
import os
import tempfile
from collections import Counter

import jsonschema

CLI = str(ROOT / 'bin/git-locks')
BASE = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))


def git(store, *args, data=None):
    return subprocess.check_output(['git', '--git-dir=' + str(store), *args], input=data,
                                   env=BASE, timeout=10).strip()


def publish(store, entries):
    # Build the fixture independently of the CLI's private-index publisher.
    root = {}
    for path, oid in entries.items():
        node = root
        parts = path.split('/')
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = oid

    def tree(node):
        rows = []
        for name, value in sorted(node.items()):
            if isinstance(value, dict):
                rows.append(b'040000 tree ' + tree(value) + b'\t' + name.encode() + b'\n')
            else:
                rows.append(b'100644 blob ' + value + b'\t' + name.encode() + b'\n')
        return git(store, 'mktree', data=b''.join(rows))

    oid = tree(root)
    git(store, 'update-ref', 'refs/locks/state', oid.decode())
    return oid


def exercise(base, mode):
    store = base / 'store.git'
    env = dict(BASE, GIT_LOCKS_STORE=str(store))
    for job in ('a', 'b'):
        result = subprocess.run([CLI, 'claim', '--job', job, '--holder', 'alice',
                                 '--ttl', '300', job + '.md'], env=env, capture_output=True, timeout=10)
        assert result.returncode == 0, result
    entries = {line.split(b'\t')[1].decode(): line.split()[2]
               for line in git(store, 'ls-tree', '-r', 'refs/locks/state').splitlines()}
    a_oid = entries['jobs/a']
    a_record = git(store, 'cat-file', 'blob', a_oid.decode()) + b'\n'
    expected = []
    if mode in ('malformed', 'utf8', 'no-paths', 'bad-time', 'bad-alias', 'mixed'):
        if mode == 'utf8':
            damaged = a_record.replace(b'holder: alice', b'holder: \xff')
        elif mode == 'no-paths':
            damaged = a_record[:a_record.index(b'paths:\n')] + b'paths:\n'
        elif mode == 'bad-time':
            damaged = a_record.replace(b'expires: ', b'expires: invalid')
        else:
            damaged = b'not a lock record\n'
        bad_oid = git(store, 'hash-object', '-w', '--stdin', data=damaged)
        entries = {key: bad_oid if value == a_oid else value for key, value in entries.items()}
        expected.append(('record-decodes', 'a'))
        if mode == 'bad-alias':
            entries['jobs/alias'] = bad_oid
            expected.append(('record-decodes', 'alias'))
    if mode in ('stray', 'mixed'):
        key = 'paths/' + git(store, 'hash-object', '--stdin', data=b'unlisted.md').decode()
        entries[key] = entries['jobs/b']
        expected.append(('path-ref-stray', 'refs/locks/' + key))
    if mode in ('orphan', 'mixed'):
        if mode == 'orphan':
            orphan_oid = entries.pop('jobs/a')
            key = 'paths/' + git(store, 'hash-object', '--stdin', data=b'a.md').decode()
        else:
            orphan_oid = git(store, 'hash-object', '-w', '--stdin', data=a_record.replace(b'job: a', b'job: gone'))
            key = 'paths/' + git(store, 'hash-object', '--stdin', data=b'orphan.md').decode()
            entries[key] = orphan_oid
        expected.append(('path-ref-orphan', 'refs/locks/' + key))
    if mode == 'valid-alias':
        entries['jobs/alias'] = a_oid
        expected.append(('job-ref-name', 'alias'))
    before = publish(store, entries)
    objects = git(store, 'cat-file', '--batch-all-objects', '--batch-check=%(objectname)')
    result = subprocess.run([CLI, 'doctor'], env=env, capture_output=True, timeout=10)
    assert result.returncode == int(bool(expected)) and not result.stderr, result
    rows = [json.loads(line) for line in result.stdout.decode('utf-8', errors='strict').splitlines()]
    for row in rows:
        VALIDATOR.validate(row)
    findings = rows[:-1]
    actual = Counter((row['check'], row['subject']) for row in findings)
    assert actual == Counter(expected), (mode, actual, expected)
    assert rows[-1]['findings'] == len(expected) and rows[-1]['healthy'] == (not expected), rows[-1]
    assert git(store, 'rev-parse', 'refs/locks/state') == before, 'doctor changed the root'
    assert git(store, 'cat-file', '--batch-all-objects', '--batch-check=%(objectname)') == objects, 'doctor wrote objects'


failures = []
modes = ('healthy', 'malformed', 'utf8', 'no-paths', 'bad-time', 'bad-alias',
         'stray', 'orphan', 'mixed', 'valid-alias')
for mode in modes:
    with tempfile.TemporaryDirectory(prefix='locks-doctor-') as tmp:
        try:
            exercise(Path(tmp), mode)
            print('PASS', mode, flush=True)
        except Exception as error:
            failures.append((mode, repr(error)))
            print('FAIL', mode, repr(error), flush=True)
print(f'doctor findings: {len(modes) - len(failures)} passed; {len(failures)} failed')
raise SystemExit(bool(failures))
