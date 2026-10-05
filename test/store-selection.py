#!/usr/bin/env python3
"""Store selection must agree across workers and fail closed on discovery errors."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import json
import os
import shutil
import tempfile

import jsonschema

CLI = str(ROOT / 'bin/git-locks')
GIT = shutil.which('git')
ENV = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))


def git(cwd, *args):
    result = subprocess.run([GIT, '-C', str(cwd), *args], env=ENV, text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result
    return result.stdout.strip()


def setup(base, mode='normal'):
    home = base / 'home'
    home.mkdir()
    subject = base / 'subject with spaces'
    subject.mkdir()
    args = ['init', '-q', '-b', 'main']
    if mode == 'bare':
        args.append('--bare')
    if mode == 'separate':
        args.append('--separate-git-dir=' + str(base / 'metadata.git'))
    git(subject, *args)
    env = dict(ENV, HOME=str(home), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_LOCKS_TEST_HOOKS='1', GIT_LOCKS_NOW='100')
    common = Path(git(subject, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    anchor = common.parent if common.name == '.git' else common
    return subject, common, anchor, env


def locks(cwd, env, *args):
    result = subprocess.run([CLI, *args], cwd=cwd, env=env, text=True, capture_output=True, timeout=10)
    for line in (result.stdout + result.stderr).splitlines():
        VALIDATOR.validate(json.loads(line))
    return result


def selected(cwd, env):
    result = locks(cwd, env, 'store')
    assert result.returncode == 0 and not result.stderr, result
    return Path(json.loads(result.stdout)['store'])


def consistent(base, mode, selector):
    subject, common, anchor, env = setup(base, mode)
    sub = subject / 'sub' / 'deep'
    sub.mkdir(parents=True)
    relative = '.reservations/store.git'
    if selector == 'environment':
        env['GIT_LOCKS_STORE'] = relative
    elif selector == 'config':
        git(subject, 'config', 'locks.store', relative)
    else:
        env['GIT_LOCKS_HOME'] = '.test-home'
    locations = [subject, sub]
    # Linked worktrees must share even an explicitly relative selector.
    if mode != 'bare':
        git(subject, '-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'fixture')
        linked = base / 'linked'
        git(subject, 'worktree', 'add', '-q', '-b', 'linked', str(linked))
        (linked / 'nested').mkdir()
        locations += [linked, linked / 'nested']
    expected = anchor / relative
    if selector == 'home':
        expected = anchor / '.test-home' / ('locks' + str(anchor))
    assert selected(locations[0], env) == expected, 'wrong shared anchor'
    first = locks(locations[0], env, 'claim', '--job', 'held', '--holder', 'alice', 'x.md')
    assert first.returncode == 0, first
    for location in locations[1:]:
        assert selected(location, env) == expected, (location, 'split store')
        result = locks(location, env, 'claim', '--job', 'racer', '--holder', 'bob', 'x.md')
        assert result.returncode == 1 and not result.stdout, result
        refusal = json.loads(result.stderr)
        assert refusal['event'] == 'refused' and refusal['holder'] == 'alice' and refusal['path'] == 'x.md', result
    assert not (sub / relative).exists()


def files(base):
    return {str(p.relative_to(base)): p.read_bytes() for p in base.rglob('*') if p.is_file()}


def discovery_error(base, mode):
    subject, common, anchor, env = setup(base)
    if mode == 'bad-config':
        (common / 'config').write_text('[broken\n')
    elif mode == 'unreadable-config':
        (common / 'config').chmod(0)
    elif mode == 'broken-head':
        (common / 'HEAD').write_text('not a ref\n')
    elif mode == 'broken-gitfile':
        subject = base / 'broken-worktree'
        subject.mkdir()
        (subject / '.git').write_text('gitdir: /tmp/absent-locks-gitdir\n')
    elif mode == 'bad-global-config':
        config = base / 'global-config'
        config.write_text('[broken\n')
        env['GIT_CONFIG_GLOBAL'] = str(config)
    elif mode == 'bad-explicit-git-dir':
        env['GIT_DIR'] = str(base / 'absent.git')
    elif mode in ('config-failure', 'discovery-failure'):
        shim = base / 'shim'
        shim.mkdir()
        (shim / 'git').write_text('''#!/usr/bin/python3
import os,sys
args=sys.argv[1:]
if (os.environ['FAIL_WHICH']=='config-failure' and 'config' in args and '--get' in args) or (os.environ['FAIL_WHICH']=='discovery-failure' and '--git-common-dir' in args):
    print('fatal: injected discovery failure',file=sys.stderr)
    sys.exit(128)
os.execv(os.environ['REAL_GIT'],[os.environ['REAL_GIT'],*args])
''')
        (shim / 'git').chmod(0o755)
        env.update(PATH=str(shim) + os.pathsep + env['PATH'], REAL_GIT=GIT, FAIL_WHICH=mode)
    # Permission faults cannot be byte-inspected until permissions are restored.
    before = None if mode == 'unreadable-config' else files(base)
    marker = base / 'child-ran'
    errors = []
    for args in [('store',), ('check', 'x.md'), ('claim', '--job', 'new', '--holder', 'alice', 'x.md'),
                 ('with', '--job', 'wrapped', '--holder', 'alice', 'wrapped.md', '--', 'touch', str(marker))]:
        result = locks(subject, env, *args)
        if result.returncode != 2 or result.stdout or json.loads(result.stderr).get('reason') != 'store-read':
            errors.append((args[0], result.returncode, result.stdout, result.stderr))
    try:
        assert not errors, errors
        assert not marker.exists()
        assert not (Path(env['HOME']) / '.git-stunts').exists(), 'fallback store created'
        if before is not None:
            assert files(base) == before, 'discovery failure changed fixture bytes'
    finally:
        if mode == 'unreadable-config':
            (common / 'config').chmod(0o644)


def outside(base):
    subject = base / 'outside'
    subject.mkdir()
    env = dict(ENV, HOME=str(base / 'home'), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
    assert selected(subject, env) == Path(env['HOME']) / ('.git-stunts/locks' + str(subject))
    explicit = dict(env, GIT_LOCKS_STORE='relative.git')
    assert selected(subject, explicit) == subject / 'relative.git'


def precedence(base):
    subject, common, anchor, env = setup(base)
    git(subject, 'config', 'locks.store', '.config-store.git')
    assert selected(subject, dict(env, GIT_LOCKS_STORE='self')) == common
    explicit = base / 'absolute.git'
    assert selected(subject, dict(env, GIT_LOCKS_STORE=str(explicit))) == explicit
    assert not (anchor / '.config-store.git').exists()


def newline_selector(base, selection):
    subject, common, anchor, env = setup(base)
    if selection == 'config':
        git(subject, 'config', 'locks.store', 'wrong.git\n')
    elif selection == 'home':
        env['GIT_LOCKS_HOME'] = str(base / 'wrong\n')
    else:
        env['GIT_LOCKS_STORE'] = 'wrong.git\n'
    before = files(base)
    result = locks(subject, env, 'store')
    assert result.returncode == 2 and not result.stdout, result
    assert json.loads(result.stderr)['reason'] == 'store-read', result
    assert files(base) == before


def newline_subject(base, repository):
    subject = base / 'name\n'
    subject.mkdir()
    if repository:
        git(subject, 'init', '-q')
    env = dict(ENV, HOME=str(base / 'home'), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
    before = files(base)
    result = locks(subject, env, 'store')
    assert result.returncode == 2 and not result.stdout, result
    assert json.loads(result.stderr)['reason'] == 'store-read', result
    assert files(base) == before
    assert not (base / 'name').exists()


failures = []
passed = 0


def case(name, body):
    global passed
    try:
        with tempfile.TemporaryDirectory(prefix='locks-selection-') as tmp:
            body(Path(tmp))
        passed += 1
        print('PASS', name, flush=True)
    except Exception as error:
        failures.append((name, str(error)))
        print('FAIL', name, str(error), flush=True)


for mode in ('normal', 'bare', 'separate'):
    for selector in ('environment', 'config', 'home'):
        case(f'{mode}: {selector}', lambda base, mode=mode, selector=selector: consistent(base, mode, selector))
for mode in ('bad-config', 'unreadable-config', 'broken-head', 'broken-gitfile', 'bad-global-config',
             'bad-explicit-git-dir', 'config-failure', 'discovery-failure'):
    case(mode, lambda base, mode=mode: discovery_error(base, mode))
case('outside a repository remains supported', outside)
case('explicit selection precedence', precedence)
for selector in ('environment', 'config', 'home'):
    case('newline selector: ' + selector, lambda base, selector=selector: newline_selector(base, selector))
for repository in (False, True):
    case(f'newline subject, repository={repository}', lambda base, repository=repository: newline_subject(base, repository))
print(f'store selection: {passed} cases passed; {len(failures)} failed')
assert not failures, failures
