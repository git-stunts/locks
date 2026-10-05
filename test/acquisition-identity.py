#!/usr/bin/env python3
"""Synthetic opaque identities survive offline migration and record rewrites."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import json
import os
import tempfile
import unicodedata

BASE = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}


def exercise(directory, kind, identity):
    store = directory / 'store.git'
    env = dict(BASE, GIT_LOCKS_STORE=str(store), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='1000000')
    git_env = dict(BASE, GIT_INDEX_FILE=str(directory / 'index'))

    def git(*args, data=None):
        return subprocess.check_output(['git', '--git-dir=' + str(store), *args],
                                       input=data, env=git_env, timeout=10)

    def locks(*args):
        result = subprocess.run([str(ROOT / 'bin/git-locks'), *args], env=env,
                                capture_output=True, text=True, timeout=10)
        assert result.returncode == 0 and not result.stderr, (args, result)
        return [json.loads(line) for line in result.stdout.splitlines()]

    def root():
        return git('rev-parse', 'refs/locks/state').decode().strip()

    if kind == 'path':
        receipt = locks('claim', '--job', 'owner', '--holder', 'alice', 'held')[0]
        release = ['release', '--job', 'owner']
    else:
        locks('sem', 'create', 'gpu', '--capacity', '1')
        receipt = locks('sem', 'acquire', 'gpu', '--job', 'owner', '--holder', 'alice')[0]
        release = ['sem', 'release', 'gpu', '--job', 'owner']
    before = root()
    original = git('cat-file', 'blob', receipt['record'])
    marker = ('acquisition: ' + receipt['acquisition']).encode()
    assert original.count(marker) == 1
    rewritten = original.replace(marker, ('acquisition: ' + identity).encode('utf-8'))
    record = git('hash-object', '-w', '--stdin', data=rewritten).decode().strip()
    git('read-tree', before)
    for entry in git('ls-tree', '-r', before).decode().splitlines():
        metadata, name = entry.split('\t')
        if metadata.split()[2] == receipt['record']:
            git('update-index', '--cacheinfo', '100644', record, name)
    synthetic = git('write-tree').decode().strip()
    git('update-ref', 'refs/locks/state', synthetic, before)
    locks('doctor')

    # Convert only this stopped, isolated fixture to the legacy ref layout.
    for entry in git('ls-tree', '-r', synthetic).decode().splitlines():
        metadata, name = entry.split('\t')
        git('update-ref', 'refs/locks/' + name, metadata.split()[2])
    git('update-ref', '-d', 'refs/locks/state', synthetic)
    locks('migrate', '--offline')
    assert root() == synthetic, 'migration changed opaque identity or any other object'
    if kind == 'path':
        locks('extend', '--job', 'owner', '--acquisition', identity, '--ttl', '600')
        current = locks('show', '--job', 'owner')[0]
    else:
        current = locks('sem', 'acquire', 'gpu', '--job', 'owner', '--holder', 'alice', '--ttl', '600')[0]
    assert current['acquisition'] == identity
    assert current['record'] != record, 'renewal fixture must change the record version'
    renewed = root()
    stale = locks(*release, '--record', record, '--acquisition', identity)[0]
    assert stale['reason'] == 'superseded' and root() == renewed
    mismatches = [identity + '-other']
    normalized = unicodedata.normalize('NFC', identity)
    if normalized != identity:
        mismatches.append(normalized)
    for mismatch in mismatches:
        stale = locks(*release, '--acquisition', mismatch)[0]
        assert stale['reason'] == 'superseded' and root() == renewed
    assert locks(*release, '--acquisition', identity)[0]['event'] == 'released'
    assert root() != renewed
    locks('doctor')


for kind in ('path', 'semaphore'):
    for identity in ('opaque-legacy-owner', 'owner-e\u0301-雪'):
        with tempfile.TemporaryDirectory(prefix='locks-opaque-identity-') as temporary:
            exercise(Path(temporary), kind, identity)
        print('PASS', kind, repr(identity), flush=True)
print('opaque acquisition identity: 4 migration/rewrite/release cases passed')
