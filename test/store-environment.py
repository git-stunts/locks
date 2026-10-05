#!/usr/bin/env python3
"""Inherited Git plumbing cannot redirect the selected reservation store."""
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
BASE_ENV = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))


def git(*args, data=None):
    return subprocess.check_output(['git', *map(str, args)], input=data, text=True, env=BASE_ENV).strip()


def snapshot(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in path.rglob('*') if p.is_file()}


def locks(env, *args, status=0, cwd=None):
    result = subprocess.run([CLI, *args], env=env, cwd=cwd, text=True, capture_output=True, timeout=15)
    assert result.returncode == status, (args, result.returncode, result.stdout, result.stderr)
    rows = [json.loads(line) for line in (result.stdout + result.stderr).splitlines()]
    for row in rows:
        VALIDATOR.validate(row)
    if status == 0:
        assert not result.stderr, result.stderr
    return rows


def setup(base, existing=True):
    subject, foreign, store = (base / name for name in ('subject', 'foreign.git', 'store.git'))
    git('init', '-q', subject)
    git('init', '-q', '--bare', foreign)
    (subject / '.git/index').write_bytes(b'caller-owned index; must never be read or changed')
    if existing:
        git('init', '-q', '--bare', store)
    config = base / 'foreign.config'
    config.write_text('[core]\n\tbare = false\n[init]\n\tdefaultObjectFormat = sha256\n')
    env = dict(BASE_ENV, GIT_LOCKS_STORE=str(store), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='1000000')
    return env, subject, foreign, store, config


def inherited(base, mode, existing):
    env, subject, foreign, store, config = setup(base, existing)
    overrides = {
        'directory': {'GIT_DIR': str(subject / '.git')},
        'common': {'GIT_COMMON_DIR': str(foreign)},
        'objects': {'GIT_OBJECT_DIRECTORY': str(foreign / 'objects')},
        'worktree': {'GIT_WORK_TREE': str(subject)},
        'index': {'GIT_INDEX_FILE': str(subject / '.git/index')},
        'namespace': {'GIT_NAMESPACE': 'foreign'},
        'count-config': {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.bare', 'GIT_CONFIG_VALUE_0': 'false'},
        'parameters-config': {'GIT_CONFIG_PARAMETERS': "'core.bare=false'"},
        'global-config': {'GIT_CONFIG_GLOBAL': str(config)},
        'system-config': {'GIT_CONFIG_SYSTEM': str(config)},
        'default-hash': {'GIT_DEFAULT_HASH': 'sha256'},
        'combined': {'GIT_DIR': str(subject / '.git'), 'GIT_COMMON_DIR': str(foreign),
                     'GIT_OBJECT_DIRECTORY': str(foreign / 'objects'),
                     'GIT_INDEX_FILE': str(subject / '.git/index'), 'GIT_NAMESPACE': 'foreign'},
    }[mode]
    before = snapshot(subject), snapshot(foreign), config.read_bytes()
    clean = dict(env)
    env.update(overrides)
    claimed = locks(env, 'claim', '--job', 'held', '--holder', 'alice', '--ttl', '60', 'x.md', cwd=subject)[0]
    assert claimed['event'] == 'claimed'
    shown = locks(clean, 'show', '--job', 'held')[0]
    assert shown['holder'] == 'alice' and shown['record'] == claimed['record'], shown
    assert len(claimed['record']) == 40, 'inherited defaults changed the new store format'
    locks(clean, 'claim', '--job', 'rival', '--holder', 'bob', 'x.md', status=1)
    locks(env, 'extend', '--job', 'held', '--ttl', '120')
    locks(clean, 'check', 'x.md', status=1)
    locks(env, 'release', '--job', 'held')
    locks(clean, 'check', 'x.md')
    assert locks(env, 'doctor')[-1]['hooks']['directory'] == str(store / 'hooks')
    assert before == (snapshot(subject), snapshot(foreign), config.read_bytes()), 'inherited repository was modified'
    assert not list(store.glob('.git-locks.init.*')), 'nested bootstrap debris'


def subject_discovery(base, selection):
    env, subject, foreign, store, _ = setup(base)
    env.pop('GIT_LOCKS_STORE')
    env.update(GIT_DIR=str(subject / '.git'), GIT_WORK_TREE=str(subject),
               GIT_OBJECT_DIRECTORY=str(foreign / 'objects'), GIT_INDEX_FILE=str(subject / '.git/index'))
    selected = subject / '.git' if selection == 'self' else store
    if selection == 'self':
        env['GIT_LOCKS_STORE'] = 'self'
    else:
        env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='locks.store', GIT_CONFIG_VALUE_0=str(store))
    before = snapshot(foreign), (subject / '.git/index').read_bytes()
    assert locks(env, 'store', cwd=base)[0]['store'] == str(selected)
    locks(env, 'claim', '--job', 'held', '--holder', 'alice', 'x.md', cwd=base)
    clean = dict(BASE_ENV, GIT_LOCKS_STORE=str(selected), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='1000000')
    if selection == 'self':
        clean['GIT_LOCKS_STORE'] = 'self'
    assert locks(clean, 'show', '--job', 'held', cwd=subject)[0]['holder'] == 'alice'
    assert before == (snapshot(foreign), (subject / '.git/index').read_bytes())
    # The command receives the caller's Git environment, even though store Git does not.
    output = base / 'environment.json'
    program = 'import json,os,sys;json.dump({k:v for k,v in os.environ.items() if k.startswith("GIT_")},open(sys.argv[1],"w"))'
    result = subprocess.run([CLI, 'with', '--job', 'wrapped', '--holder', 'alice', 'y.md', '--',
                             'python3', '-c', program, str(output)], cwd=base, env=env, text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result
    assert json.loads(output.read_text()) == {k: v for k, v in env.items() if k.startswith('GIT_')}


def replacement(base, kind):
    env, _, _, store, _ = setup(base)
    claimed = locks(env, 'claim', '--job', 'held', '--holder', 'alice', 'x.md')[0]
    if kind == 'tree':
        original = git('--git-dir=' + str(store), 'rev-parse', 'refs/locks/state')
        substitute = git('--git-dir=' + str(store), 'mktree', data='')
    else:
        original = claimed['record']
        record = git('--git-dir=' + str(store), 'cat-file', 'blob', original)
        substitute = git('--git-dir=' + str(store), 'hash-object', '-w', '--stdin', data=record.replace('holder: alice', 'holder: impostor') + '\n')
    git('--git-dir=' + str(store), 'replace', original, substitute)
    # Positive control: ordinary Git really sees the substitution.
    assert git('--git-dir=' + str(store), 'cat-file', '-p', original) == git('--git-dir=' + str(store), 'cat-file', '-p', substitute)
    assert locks(env, 'show', '--job', 'held')[0]['holder'] == 'alice'
    locks(env, 'claim', '--job', 'rival', '--holder', 'bob', 'x.md', status=1)


def alternate_objects(base):
    env, _, foreign, store, _ = setup(base)
    oid = locks(env, 'claim', '--job', 'held', '--holder', 'alice', 'x.md')[0]['record']
    source = store / 'objects' / oid[:2] / oid[2:]
    target = foreign / 'objects' / oid[:2] / oid[2:]
    target.parent.mkdir(exist_ok=True)
    source.rename(target)
    env['GIT_ALTERNATE_OBJECT_DIRECTORIES'] = str(foreign / 'objects')
    # Calibrate that the inherited alternate supplies the missing object to plain Git.
    assert subprocess.run(['git', '--git-dir=' + str(store), 'cat-file', '-e', oid], env=env).returncode == 0
    rows = locks(env, 'check', 'x.md', status=2)
    assert rows[-1]['event'] == 'error' and rows[-1]['reason'] == 'store-read', rows


def sha256_store(base):
    store = base / 'sha256.git'
    git('init', '-q', '--bare', '--object-format=sha256', store)
    env = dict(BASE_ENV, GIT_LOCKS_STORE=str(store), GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='1000000', GIT_DEFAULT_HASH='sha1')
    row = locks(env, 'claim', '--job', 'held', '--holder', 'alice', 'x.md')[0]
    assert len(row['record']) == 64
    locks(env, 'check', 'x.md', status=1)
    locks(env, 'release', '--job', 'held')
    locks(env, 'check', 'x.md')


failures = []
checks = 0


def case(label, body):
    global checks
    try:
        with tempfile.TemporaryDirectory(prefix='locks-env-') as tmp:
            body(Path(tmp))
        checks += 1
        print('PASS', label, flush=True)
    except Exception as error:
        failures.append((label, str(error)))
        print('FAIL', label, str(error), flush=True)


for existing in (False, True):
    for mode in ('directory', 'common', 'objects', 'worktree', 'index', 'namespace', 'count-config',
                 'parameters-config', 'global-config', 'system-config', 'default-hash', 'combined'):
        case(f'{mode}, existing={existing}', lambda base, mode=mode, existing=existing: inherited(base, mode, existing))
for selection in ('self', 'config'):
    case(f'subject discovery and child environment: {selection}', lambda base, selection=selection: subject_discovery(base, selection))
for kind in ('tree', 'blob'):
    case(f'immutable identity ignores {kind} replacement', lambda base, kind=kind: replacement(base, kind))
case('environment alternates cannot repair a corrupt store', alternate_objects)
case('existing SHA-256 stores retain their format', sha256_store)
print(f'store environment: {checks} passed; {len(failures)} failed')
assert not failures, failures
