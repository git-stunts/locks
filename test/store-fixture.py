#!/usr/bin/env python3
"""Inspect or deliberately corrupt logical entries in a state-tree fixture.

This is NOT on the CLI's PATH. Record-level tests use this explicit adapter
instead of treating logical entries as physical refs. It builds trees with
mktree, independently of production's private index implementation.
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import os
import sys

STATE = 'refs/locks/state'
PREFIX = 'refs/locks/'
store_arg, command, *args = sys.argv[1:]
assert store_arg.startswith('--git-dir=')


def git(*argv, data=None):
    return subprocess.check_output(['git', store_arg, *argv], input=data, text=True)


def entries():
    roots = git('for-each-ref', '--format=%(refname) %(objectname)', PREFIX).splitlines()
    if not roots:
        return {}
    assert len(roots) == 1 and roots[0].split()[0] == STATE, roots
    return {PREFIX + line.split('\t')[1]: line.split()[2]
            for line in git('ls-tree', '-r', roots[0].split()[1]).splitlines()}


def publish(values):
    tree = {}
    for ref, oid in values.items():
        assert ref.startswith(PREFIX)
        parts = ref[len(PREFIX):].split('/')
        parent = tree
        for part in parts[:-1]:
            parent = parent.setdefault(part, {})
        parent[parts[-1]] = oid

    def write(node):
        rows = []
        for name, value in sorted(node.items()):
            if isinstance(value, dict):
                rows.append(f'040000 tree {write(value)}\t{name}\n')
            else:
                rows.append(f'100644 blob {value}\t{name}\n')
        return git('mktree', data=''.join(rows)).strip()

    git('update-ref', STATE, write(tree))


def mutate(values, words):
    verb, ref, *rest = words
    if verb == 'delete':
        values.pop(ref, None)
    elif verb in ('create', 'update'):
        values[ref] = rest[0]
    elif verb != 'verify':
        raise ValueError(words)


if command == 'for-each-ref':
    values = entries()
    fmt = next((arg.split('=', 1)[1] for arg in args if arg.startswith('--format=')), '%(refname) %(objectname)')
    prefixes = [arg for arg in args if not arg.startswith('--')]
    for ref, oid in sorted(values.items()):
        if not prefixes or any(ref.startswith(prefix) for prefix in prefixes):
            print(fmt.replace('%(refname)', ref).replace('%(objectname)', oid))
elif command in ('show', 'rev-parse') and len(args) == 1 and args[0].startswith(PREFIX):
    oid = entries().get(args[0])
    if oid is None:
        sys.exit(1)
    print(git('cat-file', 'blob', oid), end='') if command == 'show' else print(oid)
elif command == 'update-ref':
    values = entries()
    if args == ['--stdin']:
        for line in sys.stdin:
            words = line.split()
            if words and words[0] not in ('start', 'prepare', 'commit'):
                mutate(values, words)
    elif args[0] == '-d':
        mutate(values, ['delete', *args[1:]])
    else:
        mutate(values, ['update', *args])
    publish(values)
else:
    os.execvp('git', ['git', store_arg, command, *args])
