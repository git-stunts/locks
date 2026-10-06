"""Experimental immutable path index; not used by the production CLI.

Inputs are normalized relative paths and already-validated reservation records.
This indexes conflict existence, not acquisition permission or family policy.
"""

from dataclasses import dataclass
from types import MappingProxyType
import json
import os
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class Node:
    exact: object
    prefix: object
    children: object
    count: int
    maximum: int
    below_maximum: int


def node(exact=None, prefix=None, children=None):
    exact, prefix, children = dict(exact or {}), dict(prefix or {}), dict(children or {})
    below = max([0, *prefix.values(), *(c.maximum for c in children.values())])
    return Node(MappingProxyType(exact), MappingProxyType(prefix), MappingProxyType(children),
                len(exact) + len(prefix) + sum(c.count for c in children.values()),
                max([below, *exact.values()]), below)


EMPTY = node()


def split(path):
    prefix = path.endswith('/')
    parts = path.removesuffix('/').split('/')
    if any(p in ('', '.', '..') or any(c in p for c in '\0\r\n') for p in parts):
        raise ValueError('prototype requires a normalized relative path')
    return parts, prefix


def update(root, path, acquisition, expires):
    """Copy the affected ancestors; None removes only this acquisition."""
    if not acquisition or (expires is not None and (type(expires) is not int or expires <= 0)):
        raise ValueError('invalid acquisition or expiry')
    parts, prefix = split(path)

    def visit(current, depth):
        if depth == len(parts):
            entries = dict(current.prefix if prefix else current.exact)
            if expires is None:
                entries.pop(acquisition, None)
            else:
                entries[acquisition] = expires
            return node(current.exact if prefix else entries,
                        entries if prefix else current.prefix, current.children)
        children = dict(current.children)
        child = visit(children.get(parts[depth], EMPTY), depth + 1)
        if child.count:
            children[parts[depth]] = child
        else:
            children.pop(parts[depth], None)
        return node(current.exact, current.prefix, children)

    return visit(root, 0)


def conflict(root, path, now):
    """Return (any live conflict, visited nodes), without walking descendants."""
    parts, prefix = split(path)
    current, visited = root, 1
    for part in parts:
        if max(current.prefix.values(), default=0) > now:
            return True, visited
        current = current.children.get(part)
        if current is None:
            return False, visited
        visited += 1
    maximum = current.below_maximum if prefix else max(current.exact.values(), default=0)
    return maximum > now, visited


class GitTrees:
    """Persist the experimental index as real Git trees and publish one root."""

    def __init__(self, directory, object_format):
        self.directory = Path(directory)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
                        GIT_AUTHOR_NAME='Index experiment', GIT_AUTHOR_EMAIL='test@example.invalid',
                        GIT_COMMITTER_NAME='Index experiment', GIT_COMMITTER_EMAIL='test@example.invalid')
        self.run('init', '--bare', '--template=', '--object-format=' + object_format, str(directory))
        self.zero = '0' * (40 if object_format == 'sha1' else 64)
        self.cache = {}  # Retain node identity as well as OID; never rely on recycled id().

    def run(self, *args, data=None, check=True):
        return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null',
                               '--git-dir=' + str(self.directory), *args],
                              input=data, capture_output=True, env=self.env,
                              check=check, timeout=10)

    def blob(self, content):
        return self.run('hash-object', '-w', '--stdin', data=content).stdout.decode().strip()

    def tree(self, root):
        cached = self.cache.get(id(root))
        if cached is not None and cached[0] is root:
            return cached[1]
        metadata = json.dumps({'exact': dict(root.exact), 'prefix': dict(root.prefix),
                               'count': root.count, 'maximum': root.maximum,
                               'below_maximum': root.below_maximum},
                              sort_keys=True, separators=(',', ':')).encode()
        entries = [f'100644 blob {self.blob(metadata)}\tmeta\0']
        for name, child in sorted(root.children.items()):
            encoded = 'k' + name.encode('utf-8').hex()
            entries.append(f'040000 tree {self.tree(child)}\t{encoded}\0')
        oid = self.run('mktree', '-z', data=''.join(entries).encode()).stdout.decode().strip()
        self.cache[id(root)] = (root, oid)
        return oid

    def load(self, oid):
        entries = self.run('ls-tree', '-z', oid).stdout.split(b'\0')
        children, metadata = {}, None
        for entry in filter(None, entries):
            header, name = entry.split(b'\t', 1)
            mode, kind, child_oid = header.decode().split()
            if name == b'meta' and mode == '100644' and kind == 'blob':
                metadata = json.loads(self.run('cat-file', 'blob', child_oid).stdout)
            elif name.startswith(b'k') and mode == '040000' and kind == 'tree':
                decoded = bytes.fromhex(name[1:].decode()).decode('utf-8')
                children[decoded] = self.load(child_oid)
            else:
                raise ValueError('invalid experimental tree entry')
        if metadata is None:
            raise ValueError('missing summary')
        root = node(metadata['exact'], metadata['prefix'], children)
        for field in ('count', 'maximum', 'below_maximum'):
            if metadata[field] != getattr(root, field):
                raise ValueError('summary disagrees with descendants')
        return root

    def publish(self, new, observed=None):
        return self.run('update-ref', '--no-deref', 'refs/locks/state',
                        new, observed or self.zero, check=False).returncode == 0
