#!/usr/bin/env python3
"""Bounded differential/index and Git reachability experiments, Docker only."""

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import json
import random
import tempfile
import argparse
from prototype import EMPTY, GitTrees, conflict, node, update


def oracle(records, wanted, now):
    def overlaps(a, b):
        return a == b or (a.endswith('/') and b.startswith(a)) or (b.endswith('/') and a.startswith(b))
    return any(expiry > now and overlaps(path, wanted)
               for (path, _acquisition), expiry in records.items())


def differential():
    paths = ['dist', 'dist/', 'dist/a', 'dist/a/', 'dist/a/b', 'dist/b', 'dist2/a',
             '.intent', '.intent/a', 'é/a', 'e\u0301/a', 'A/a', 'a/a', 'a/',
             'space here/x', 'literal*/x', 'literal?/x']
    rng, root, records, checks = random.Random(90423), EMPTY, {}, 0
    for step in range(400):
        path, acquisition = rng.choice(paths), 'owner-' + str(rng.randrange(6))
        expiry = None if rng.randrange(3) == 0 else rng.randrange(1, 100)
        previous = root
        before_queries = [conflict(previous, query, 50)[0] for query in paths]
        root = update(root, path, acquisition, expiry)
        if expiry is None:
            records.pop((path, acquisition), None)
        else:
            records[path, acquisition] = expiry
        # Keep the previous version around: immutable updates must not mutate it.
        for now in (0, 25, 50, 75, 100):
            for query in paths:
                actual, visits = conflict(root, query, now)
                assert actual == oracle(records, query, now), (step, now, query)
                assert visits <= len(query.removesuffix('/').split('/')) + 1
                checks += 1
        assert [conflict(previous, query, 50)[0] for query in paths] == before_queries
        assert root.count == len(records)
    # Explicit ownership and expiry boundaries, including a backward clock read.
    root = update(update(EMPTY, 'dist/a', 'A', 10), 'dist/b', 'B', 20)
    previous = root
    root = update(root, 'dist/a', 'A', None)
    assert conflict(root, 'dist/', 19)[0]
    assert not conflict(root, 'dist/', 20)[0]
    assert conflict(root, 'dist/', 19)[0]
    assert previous.count == 2 and root.count == 1
    root = update(root, 'dist/b', 'B', 30)
    assert conflict(root, 'dist/', 20)[0]
    assert not conflict(root, 'dist', 20)[0]
    # Structural work observation, not a timing benchmark.
    wide = EMPTY
    for i in range(128):
        wide = update(wide, f'dist/file-{i}', str(i), 100)
    assert conflict(wide, 'dist/', 0) == (True, 2)
    assert conflict(wide, 'dist/', 100) == (False, 2)
    return {'seed': 90423, 'updates': 400, 'oracle_comparisons': checks,
            'prior_snapshot_query_checks': 400 * len(paths),
            'wide_children': 128, 'wide_prefix_visited_nodes': 2}


def git_checks(directory, algorithm):
    git = GitTrees(directory, algorithm)
    initial = update(EMPTY, '.intent/a', 'one', 10)
    initial = update(initial, 'é/a', 'unicode', 30)
    base = git.tree(initial)
    assert git.publish(base)
    assert not git.publish(base)  # Strict create refuses even an identical existing target.
    restored = git.load(base)
    assert restored.count == initial.count
    assert conflict(restored, '.intent/', 9)[0]
    assert not conflict(restored, '.intent/', 10)[0]
    assert not conflict(restored, 'e\u0301/', 0)[0]
    a = update(initial, 'other/a', 'A', 100)
    b = update(initial, 'other/b', 'B', 100)
    ta, tb = git.tree(a), git.tree(b)
    assert git.publish(ta, base)
    assert not git.publish(tb, base)  # Deterministic stale publication schedule.
    combined = update(git.load(ta), 'other/b', 'B', 100)
    tc = git.tree(combined)
    assert git.publish(tc, ta)
    git.run('pack-refs', '--all')
    assert git.publish(ta, tc)
    # An unrelated immutable subtree retains its OID after another path changes.
    encoded = 'k' + 'é'.encode().hex()
    assert git.run('rev-parse', base + ':' + encoded).stdout == git.run('rev-parse', ta + ':' + encoded).stdout
    # Inject a false summary using an independent raw tree constructor.
    rows = git.run('ls-tree', '-z', ta).stdout.split(b'\0')
    bad_meta = git.blob(b'{"exact":{},"prefix":{},"count":0,"maximum":0,"below_maximum":0}')
    forged = b'\0'.join((b'100644 blob ' + bad_meta.encode() + b'\tmeta')
                       if row.endswith(b'\tmeta') else row for row in rows)
    forged_oid = git.run('mktree', '-z', data=forged).stdout.decode().strip()
    try:
        git.load(forged_oid)
    except ValueError:
        pass
    else:
        raise AssertionError('forged summary accepted')
    return {'object_format': algorithm, 'roundtrip': True, 'stale_cas_rejected': True,
            'strict_create_same_target_rejected': True,
            'replan_preserves_both': True, 'packed_ref_update': True,
            'structural_sharing': True, 'forged_summary_rejected': True}


def reachability(directory, algorithm):
    git = GitTrees(directory, algorithm)
    empty = git.run('mktree', data=b'').stdout.decode().strip()

    def commit(tree, label, parent=None):
        return git.run('commit-tree', tree, *(['-p', parent] if parent else []),
                       data=(label + '\n').encode()).stdout.decode().strip()

    ancestor = commit(empty, 'empty parent')
    old_tree = git.tree(update(EMPTY, 'old', 'old', 10))
    new_tree = git.tree(update(EMPTY, 'new', 'new', 20))
    old = commit(old_tree, 'old sibling', ancestor)
    new = commit(new_tree, 'new sibling', ancestor)
    chain = commit(new_tree, 'new child of old', old)
    # Only isolated fixtures: immediate GC is deliberately destructive here.
    git.run('update-ref', 'refs/heads/current', new)
    git.run('gc', '--prune=now')
    exists = lambda oid: git.run('cat-file', '-e', oid, check=False).returncode == 0
    assert exists(ancestor) and exists(new) and not exists(old)
    assert not exists(old_tree) and not exists(chain)
    # Reconstruct, then retain old through the new commit's parent edge.
    git.cache.clear()
    old_tree = git.tree(update(EMPTY, 'old', 'old', 10))
    old = commit(old_tree, 'old sibling', ancestor)
    chain = commit(new_tree, 'new child of old', old)
    git.run('update-ref', 'refs/heads/current', chain)
    git.run('gc', '--prune=now')
    assert exists(old) and exists(old_tree) and exists(chain)
    return {'object_format': algorithm, 'empty_parent_does_not_retain_sibling': True,
            'unpublished_candidate_pruned': True, 'reachable_parent_chain_retains_old': True}


parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True, type=Path)
out = parser.parse_args().output
if out.parent.resolve() != Path('/work/artifacts').resolve() or out.exists():
    raise ValueError('output must be a new directory directly under /work/artifacts')

result = {'scope': 'experimental index and sequential Git schedules; not production integration',
          'differential': differential(), 'git': [], 'gc': []}
with tempfile.TemporaryDirectory(prefix='hierarchical-study-') as scratch:
    for algorithm in ('sha1', 'sha256'):
        result['git'].append(git_checks(Path(scratch) / (algorithm + '-index'), algorithm))
        result['gc'].append(reachability(Path(scratch) / (algorithm + '-gc'), algorithm))
print(json.dumps(result, indent=2))
out.mkdir()
(out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
