#!/usr/bin/env python3
"""Store Git hooks remain inert; doctor discloses their configured presence."""
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


def exercise(base, mode):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    store = base / 'store.git'
    repo = base / 'subject'
    repo.mkdir()
    if mode in ('self', 'fsmonitor'):
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        store = repo / '.git'
    else:
        subprocess.run(['git', 'init', '-q', '--bare', str(store)], check=True)
    env.update(GIT_LOCKS_STORE='self' if mode in ('self', 'fsmonitor') else str(store), GIT_LOCKS_NOW='1000000', HOOK_LOG=str(base / 'hook.log'))
    directory = repo / 'relative hooks' if mode == 'relative' else store / 'hooks' if mode in ('default', 'self', 'fsmonitor') else base / 'custom hooks'
    directory.mkdir(exist_ok=True)
    for name in ('reference-transaction', 'post-index-change'):
        hook = directory / name
        hook.write_text('#!/bin/sh\nprintf "%s\\n" "$0 $*" >> "$HOOK_LOG"\n')
        hook.chmod(0o755)
    if mode == 'relative':
        subprocess.run(['git', '--git-dir=' + str(store), 'config', 'core.hooksPath', 'relative hooks'], check=True)
    elif mode == 'fsmonitor':
        monitor = base / 'monitor'
        monitor.write_text('#!/bin/sh\nprintf "fsmonitor\\n" >> "$HOOK_LOG"\nexit 1\n')
        monitor.chmod(0o755)
        subprocess.run(['git', '--git-dir=' + str(store), 'config', 'core.fsmonitor', str(monitor)], check=True)
    elif mode == 'local':
        subprocess.run(['git', '--git-dir=' + str(store), 'config', 'core.hooksPath', str(directory)], check=True)
    elif mode == 'global':
        env['GIT_CONFIG_GLOBAL'] = str(base / 'global.config')
        subprocess.run(['git', 'config', '--global', 'core.hooksPath', str(directory)], env=env, check=True)
    elif mode == 'environment':
        env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='core.hooksPath', GIT_CONFIG_VALUE_0=str(directory))
    # Positive calibration: plain Git really executes this fixture's hook.
    blob = subprocess.check_output(['git', '--git-dir=' + str(store), 'hash-object', '-w', '--stdin'], input='calibration', text=True, env=env).strip()
    subprocess.run(['git', '--git-dir=' + str(store), 'update-ref', 'refs/private/calibration', blob], env=env, cwd=repo, check=True)
    log = Path(env['HOOK_LOG'])
    assert 'reference-transaction' in log.read_text()
    if mode == 'fsmonitor':
        (repo / 'tracked.txt').write_text('monitor calibration')
        subprocess.run(['git', 'add', 'tracked.txt'], env=env, cwd=repo, check=True, capture_output=True)
        assert 'fsmonitor' in log.read_text(), 'monitor control did not execute'
    log.unlink()

    def locks(*args):
        result = subprocess.run([CLI, *args], cwd=repo, env=env, text=True, capture_output=True, timeout=10)
        assert result.returncode == 0 and not result.stderr, (args, result)
        assert not log.exists(), (args, 'a Git hook executed', log.read_text() if log.exists() else '')
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        for row in rows:
            VALIDATOR.validate(row)
        return rows

    locks('claim', '--job', 'j', '--holder', 'worker', 'x.md')
    locks('extend', '--job', 'j', '--ttl', '5')
    locks('sem', 'create', 'gpu', '--capacity', '1')
    locks('sem', 'acquire', 'gpu', '--job', 'j', '--holder', 'worker')
    locks('sem', 'release', 'gpu', '--job', 'j')
    locks('sem', 'delete', 'gpu')
    locks('release', '--job', 'j')
    policy = locks('doctor')[-1]['hooks']
    assert policy['disabled'] is True and policy['fsmonitor_disabled'] is True
    assert policy['configured_path'] == (None if mode in ('default', 'self', 'fsmonitor') else 'relative hooks' if mode == 'relative' else str(directory)), policy
    assert policy['directory'] == str(directory), policy
    assert policy['executables'] == ['reference-transaction', 'post-index-change'], policy
    # Report configured hooks without changing their files or Git configuration.
    assert all((directory / name).is_file() for name in policy['executables'])


failures = []
modes = ('default', 'local', 'global', 'environment', 'self', 'relative', 'fsmonitor')
for mode in modes:
    try:
        with tempfile.TemporaryDirectory(prefix='locks-hooks-') as tmp:
            exercise(Path(tmp), mode)
    except Exception as error:
        failures.append((mode, str(error)))
        print(f'FAIL store hooks ({mode}): {error}', flush=True)
print(f'store hooks: {len(modes) - len(failures)} modes passed; {len(failures)} failed')
assert not failures, failures
