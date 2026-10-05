#!/usr/bin/env python3
"""Missing HOME must not crash or select a root-level default authority."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import hashlib
import json
import os
import tempfile

import jsonschema

CLI = str(ROOT / 'bin/git-locks')
BASE = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
BASE.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))


def git(cwd, *args):
    return subprocess.check_output(['git', '-C', str(cwd), *args], env=BASE,
                                   stderr=subprocess.PIPE, text=True, timeout=10).strip()


def inventory(base):
    return {str(p.relative_to(base)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in base.rglob('*') if p.is_file()}


def run(cwd, env, *args):
    return subprocess.run([CLI, *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=10)


def exercise(base, layout, home, selector):
    subject = base / 'subject'
    subject.mkdir()
    cwd = subject
    if layout != 'outside':
        git(subject, 'init', '-q', '-b', 'main')
        if layout == 'linked':
            git(subject, '-c', 'user.name=test', '-c', 'user.email=test@example.invalid',
                'commit', '--allow-empty', '-qm', 'fixture')
            cwd = base / 'linked'
            git(subject, 'worktree', 'add', '-q', '-b', 'linked', str(cwd))
    # Enter a nested directory to also test the linked-worktree shared anchor.
    cwd = cwd / 'nested'
    cwd.mkdir()
    anchor = cwd if layout == 'outside' else subject
    env = dict(BASE)
    if home == 'unset':
        env.pop('HOME', None)
    elif home == 'empty':
        env['HOME'] = ''
    else:
        env['HOME'] = str(base / 'home')
        (base / 'home').mkdir()
    if selector == 'absolute':
        expected = base / 'explicit.git'
        env['GIT_LOCKS_STORE'] = str(expected)
    elif selector in ('relative', 'config'):
        expected = anchor / '.reservations/store.git'
        if selector == 'config':
            git(subject, 'config', 'locks.store', '.reservations/store.git')
        else:
            env['GIT_LOCKS_STORE'] = '.reservations/store.git'
    elif selector == 'self':
        env['GIT_LOCKS_STORE'] = 'self'
        expected = subject / '.git'
    elif selector == 'override':
        env['GIT_LOCKS_HOME'] = str(base / 'override')
        expected = base / 'override' / ('locks' + str(anchor))
    else:
        if selector == 'empty-override':
            env['GIT_LOCKS_HOME'] = ''
        expected = base / 'home/.git-stunts' / ('locks' + str(anchor))
    if home != 'valid' and selector in ('default', 'empty-override'):
        before = inventory(base)
        marker = base / 'command-ran'
        for args in (['store'], ['with', '--job', 'held', '--holder', 'alice',
                                'x.md', '--', 'touch', str(marker)]):
            result = run(cwd, env, *args)
            assert result.returncode == 2 and not result.stdout, result
            row = json.loads(result.stderr)
            VALIDATOR.validate(row)
            assert row['event'] == 'error' and row['reason'] == 'store-read', row
            assert 'HOME' in row['detail'], row
            assert inventory(base) == before, 'missing home modified the fixture'
            assert not marker.exists(), 'missing home launched a child'
        return
    selected = run(cwd, env, 'store')
    assert selected.returncode == 0 and not selected.stderr, selected
    row = json.loads(selected.stdout)
    VALIDATOR.validate(row)
    assert row['store'] == str(expected), (row, expected)
    claimed = run(cwd, env, 'claim', '--job', 'held', '--holder', 'alice', '--ttl', '300', 'x.md')
    assert claimed.returncode == 0 and not claimed.stderr, claimed
    VALIDATOR.validate(json.loads(claimed.stdout))
    # Read the state from a second working directory with an explicit authority.
    second_cwd = subject if selector == 'self' else base
    second = run(second_cwd, dict(env, GIT_LOCKS_STORE=str(expected)), 'show', '--job', 'held')
    assert second.returncode == 0 and not second.stderr, second
    row = json.loads(second.stdout)
    VALIDATOR.validate(row)
    assert row['job'] == 'held' and row['paths'] == ['x.md'], row


failures = []
checks = 0
for layout in ('outside', 'normal', 'linked'):
    selectors = ('default', 'empty-override', 'override', 'absolute', 'relative')
    if layout != 'outside':
        selectors += ('config', 'self')
    cases = [(home, selector) for home in ('unset', 'empty') for selector in selectors]
    cases += [('valid', 'default')]
    for home, selector in cases:
        with tempfile.TemporaryDirectory(prefix='locks-home-') as tmp:
            try:
                exercise(Path(tmp), layout, home, selector)
                checks += 1
                print('PASS', layout, home, selector, flush=True)
            except Exception as error:
                failures.append((layout, home, selector, repr(error)))
                print('FAIL', *failures[-1], flush=True)
print(f'home selection: {checks} passed; {len(failures)} failed')
raise SystemExit(bool(failures))
