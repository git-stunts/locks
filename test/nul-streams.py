#!/usr/bin/env python3
"""NUL bytes must not change reservation identity or escape as shell warnings."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import json
import os
import shlex
import shutil
import signal
import tempfile
import time

import jsonschema

CLI = str(ROOT / 'bin/git-locks')
GIT = shutil.which('git')
BASE = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))
checks = 0
failures = []


def run(env, *args, data=None, input_file=None):
    process = subprocess.Popen([CLI, *args], env=env, stdin=input_file if input_file is not None else subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = process.communicate(data, timeout=10)
    except BaseException:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
        raise
    return subprocess.CompletedProcess(args, process.returncode, out, err)


def git(env, *args, data=None):
    return subprocess.check_output([GIT, '--git-dir=' + env['GIT_LOCKS_STORE'], *args],
                                   input=data, env=env, timeout=10)


def rows(data):
    result = [json.loads(line) for line in data.decode('utf-8').split('\n') if line]
    for item in result:
        VALIDATOR.validate(item)
    return result


def root(env):
    return git(env, 'rev-parse', 'refs/locks/state').strip()


def objects(env):
    return sorted(git(env, 'cat-file', '--batch-all-objects', '--batch-check=%(objectname)').splitlines())


def setup(base):
    scratch = base / 'tmp'
    scratch.mkdir()
    env = dict(BASE, GIT_LOCKS_STORE=str(base / 'store.git'), TMPDIR=str(scratch))
    result = run(env, 'claim', '--job', 'owner', '--holder', 'alice', 'held.md')
    assert result.returncode == 0 and not result.stderr, result
    return env


def clean_capture(env):
    assert not list(Path(env['TMPDIR']).glob('git-locks-read.*')), 'snapshot capture file leaked'


def error(result, reason):
    assert result.returncode == 2 and not result.stdout, result
    parsed = rows(result.stderr)
    assert len(parsed) == 1 and parsed[0]['event'] == 'error' and parsed[0]['reason'] == reason, parsed
    return parsed[0]


def case(label, body):
    global checks
    try:
        with tempfile.TemporaryDirectory(prefix='locks-nul-') as tmp:
            body(Path(tmp))
        checks += 1
        print('PASS', label, flush=True)
    except Exception as exc:
        failures.append(label)
        print('FAIL', label, repr(exc), flush=True)


RECORD = b'job: candidate\nholder: alice\nnote: review\npaths:\nfree.md\n'
BATCHES = {
    'before first record': b'\0' + RECORD,
    'job': RECORD.replace(b'candidate', b'can\0didate'),
    'holder': RECORD.replace(b'alice', b'ali\0ce'),
    'note': RECORD.replace(b'review', b're\0view'),
    'path': RECORD.replace(b'free.md', b'free\0.md'),
    'after final record': RECORD + b'\0',
    'after valid first record': RECORD + b'\njob: second\nholder: bob\npaths:\nsec\0ond.md\n',
}


def batch_refusal(base, data):
    env = setup(base)
    before, before_objects = root(env), objects(env)
    error(run(env, 'batch', data=data), 'usage')
    assert root(env) == before and objects(env) == before_objects, 'bad batch published or wrote objects'
    clean_capture(env)


for label, data in BATCHES.items():
    case('batch refuses NUL ' + label, lambda base, d=data: batch_refusal(base, d))


def corrupt(base, field, args):
    env = setup(base)
    old = root(env).decode()
    original = git(env, 'cat-file', '-p', old + ':jobs/owner')
    if field == 'holder':
        damaged = original.replace(b'alice', b'ali\0ce')
    elif field == 'path':
        damaged = original.replace(b'held.md', b'he\0ld.md')
    elif field == 'note':
        damaged = b'note: re\0view\n' + original
    elif field == 'unknown':
        damaged = b'unknown: nu\0l\n' + original
    else:
        damaged = original + b'\0'
    oid = git(env, 'hash-object', '-w', '--stdin', data=damaged).strip()
    entries = git(env, 'ls-tree', '-r', old).splitlines()
    index_env = dict(env, GIT_INDEX_FILE=str(base / 'fixture.index'))
    git(index_env, 'read-tree', '--empty')
    listing = b''.join(b'100644 ' + oid + b'\t' + entry.split(b'\t')[1] + b'\n' for entry in entries)
    git(index_env, 'update-index', '--index-info', data=listing)
    new = git(index_env, 'write-tree').strip().decode()
    git(env, 'update-ref', 'refs/locks/state', new, old)
    before_objects = objects(env)
    marker = base / 'child-ran'
    command = [str(marker) if arg == 'MARKER' else arg for arg in args]
    error(run(env, *command), 'store-read')
    assert root(env).decode() == new and objects(env) == before_objects
    assert not marker.exists(), 'corrupt authority admitted child execution'
    clean_capture(env)


COMMANDS = [
    ['list'], ['check', 'held.md'], ['show', '--job', 'owner'], ['release', '--job', 'owner'],
    ['sweep'], ['claim', '--job', 'new', '--holder', 'bob', 'free.md'],
    ['with', '--job', 'new', '--holder', 'bob', 'free.md', '--', 'touch', 'MARKER'], ['doctor'],
]
for field in ('holder', 'path', 'note', 'unknown', 'after record'):
    for args in COMMANDS:
        case('stored NUL ' + field + ': ' + args[0], lambda base, f=field, a=args: corrupt(base, f, a))


def accepted_batch(base, suffix):
    env = setup(base)
    data = RECORD.rstrip(b'\n') + suffix
    result = run(env, 'batch', data=data)
    assert result.returncode == 0 and not result.stderr, result
    claimed = rows(result.stdout)[0]
    assert claimed['holder'] == 'alice' and claimed['note'] == 'review' and claimed['paths'] == ['free.md']
    clean_capture(env)


for suffix in (b'', b'\n', b'\n\n\n'):
    case('valid batch ending ' + repr(suffix), lambda base, s=suffix: accepted_batch(base, s))


def child_bytes(base):
    env = setup(base)
    payload = b'\0\xff\ntext\0\n\n'
    result = run(env, 'with', '--job', 'child', '--holder', 'alice', 'free.md', '--',
                 'python3', '-c', 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())', data=payload)
    assert result.returncode == 0 and result.stdout == payload, result
    assert [row['event'] for row in rows(result.stderr)] == ['claimed', 'released']
    clean_capture(env)


case('wrapped child retains NUL and arbitrary byte streams', child_bytes)


def transport_failure(base, mode):
    env = setup(base)
    before = root(env)
    shim = base / 'shim'
    shim.mkdir()
    script = '#!/bin/bash\nfor arg in "$@"; do\n  if [[ "$arg" == --batch ]]; then\n'
    if mode == 'nul':
        script += "    printf 'diagnostic with NUL: \\000tail\\n' >&2; exit 65\n"
    elif mode == 'exit':
        script += "    printf 'injected batch failure\\n' >&2; exit 65\n"
    else:
        script += "    printf 'invalid header\\n'; exit 0\n"
    script += '  fi\ndone\nexec ' + shlex.quote(GIT) + ' "$@"\n'
    executable = shim / 'git'
    executable.write_text(script)
    executable.chmod(0o755)
    result = run(dict(env, PATH=str(shim) + os.pathsep + env['PATH']), 'list')
    error(result, 'store-read')
    assert root(env) == before
    clean_capture(env)


for mode in ('nul', 'exit', 'header'):
    case('failed snapshot transport remains structured: ' + mode,
         lambda base, m=mode: transport_failure(base, m))


def capture_failure(base, command):
    env = setup(base)
    if command == 'batch':
        # An empty snapshot reaches batch's own capture allocation. A populated
        # snapshot fails earlier while loading the store, with store-read.
        assert run(env, 'release', '--job', 'owner').returncode == 0
    before, before_objects = root(env), objects(env)
    # No writable capture directory: fail before command input can be trusted.
    result = run(dict(env, TMPDIR=str(base / 'missing')), command, data=RECORD)
    error(result, 'usage' if command == 'batch' else 'store-read')
    assert root(env) == before and objects(env) == before_objects
    clean_capture(env)


for command in ('list', 'batch'):
    case('capture allocation failure: ' + command, lambda base, c=command: capture_failure(base, c))


def batch_io_failure(base):
    env = setup(base)
    before, before_objects = root(env), objects(env)
    descriptor = os.open(base, os.O_RDONLY)  # A real read error (EISDIR), not EOF.
    try:
        error(run(env, 'batch', input_file=descriptor), 'usage')
    finally:
        os.close(descriptor)
    assert root(env) == before and objects(env) == before_objects, 'partial failed input was published'
    clean_capture(env)


case('batch input read errors remain structured and do not publish', batch_io_failure)


def parent_cancel(base, sig):
    env = setup(base)
    before, before_objects = root(env), objects(env)
    ready, cat_pid = base / 'read-ready', base / 'cat-pid'
    # A test-only handshake proves that cmd_batch entered its input reader.
    # The cat shim also observes the old command-substitution implementation.
    startup = base / 'startup.sh'
    startup.write_text('read() {\n'
                       '  if [[ "${FUNCNAME[1]:-}" == cmd_batch ]]; then printf ready >"$READ_READY"; fi\n'
                       '  builtin read "$@"\n}\n')
    shim = base / 'shim'
    shim.mkdir()
    cat = shim / 'cat'
    cat.write_text('#!/bin/bash\nprintf "%s\\n" "${BASHPID}" >"$CAT_PID"\nexec /usr/bin/cat\n')
    cat.chmod(0o755)
    env.update(PATH=str(shim) + os.pathsep + env['PATH'], BASH_ENV=str(startup),
               READ_READY=str(ready), CAT_PID=str(cat_pid))
    process = subprocess.Popen([CLI, 'batch'], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        process.stdin.write(b'job: partial\nholder: alice\npaths:\n')
        process.stdin.flush()
        deadline = time.monotonic() + 3
        while not ready.exists() and not cat_pid.exists():
            assert process.poll() is None and time.monotonic() < deadline, 'input reader never became ready'
            time.sleep(.01)
        process.send_signal(sig)  # Signal only the CLI PID. Keep the input pipe open.
        assert process.wait(timeout=2) in (-sig, 128 + sig)
        time.sleep(.1)
        if cat_pid.exists():
            status = Path('/proc') / cat_pid.read_text().strip() / 'status'
            assert not status.exists() or '\nState:\tZ' in status.read_text(), 'input reader survived CLI cancellation'
        clean_capture(env)
        assert root(env) == before and objects(env) == before_objects
    finally:
        process.stdin.close()
        process.stdin = None
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate(timeout=3)


for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    case('parent-only cancellation leaves no input reader or capture: ' + sig.name,
         lambda base, s=sig: parent_cancel(base, s))

print(f'NUL streams: {checks} passed; {len(failures)} failed', flush=True)
raise SystemExit(bool(failures))
