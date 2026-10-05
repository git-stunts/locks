#!/usr/bin/env python3
"""Strict UTF-8 consumers must see valid JSON without changing reservation keys."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import json
import os
import random
import tempfile

import jsonschema

CLI = os.fsencode(ROOT / 'bin/git-locks')
BASE = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
VALIDATOR = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))
BAD = [b'\x80', b'\xbf', b'\xc0\xaf', b'\xc2', b'\xc2A', b'\xe0\x80\x80', b'\xed\xa0\x80',
       b'\xed\xbf\xbf', b'\xe2\x82', b'\xe2(\xa1', b'\xf0\x80\x80\x80', b'\xf4\x90\x80\x80',
       b'\xf5\x80\x80\x80', b'\xff', b'good-\xe2\x98\x83-bad-\x80']
failures = []
checks = 0


def run(env, *args, data=None):
    return subprocess.run([CLI, *args], env=env, input=data, capture_output=True, timeout=10)


def rows(data):
    decoded = data.decode('utf-8', errors='strict')
    result = [json.loads(line) for line in decoded.split('\n') if line]
    for item in result:
        VALIDATOR.validate(item)
    return result


def git(env, *args, data=None):
    return subprocess.check_output(['git', '--git-dir=' + env['GIT_LOCKS_STORE'], *args], input=data, timeout=10)


def setup(base):
    env = dict(BASE, GIT_LOCKS_STORE=str(base / 'store.git'))
    claim = run(env, 'claim', '--job', 'owner', '--holder', 'alice', '--ttl', '300', 'held.md')
    assert claim.returncode == 0, claim.stderr
    return env


def root(env):
    return git(env, 'rev-parse', 'refs/locks/state').strip()


def case(label, body):
    global checks
    try:
        with tempfile.TemporaryDirectory(prefix='locks-utf8-') as tmp:
            body(Path(tmp))
        checks += 1
        print('PASS', label, flush=True)
    except Exception as error:
        failures.append(label)
        print('FAIL', label, repr(error), flush=True)


def refuse_input(base, kind, bad):
    env = setup(base)
    before = root(env)
    marker = base / 'command-ran'
    data = None
    if kind in ('holder', 'note', 'path'):
        args = ['claim', '--job', 'candidate', '--holder', bad if kind == 'holder' else 'bob']
        if kind == 'note':
            args += ['--note', bad]
        args += [bad if kind == 'path' else 'free.md']
    elif kind == 'batch':
        args = ['batch']
        data = b'job: first\nholder: alice\npaths:\nfirst.md\n\njob: bad\nholder: alice\npaths:\n' + bad + b'\n'
    elif kind == 'sem':
        assert run(env, 'sem', 'create', 'gpu', '--capacity', '1').returncode == 0
        before = root(env)
        args = ['sem', 'acquire', 'gpu', '--job', 'candidate', '--holder', bad]
    elif kind == 'with':
        args = ['with', '--job', 'candidate', '--holder', bad, 'free.md', '--', 'touch', str(marker)]
    elif kind == 'check':
        args = ['check', bad]
    else:
        args = ['release', '--job', 'owner', '--acquisition', bad]
    result = run(env, *args, data=data)
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
    assert not result.stdout
    errors = rows(result.stderr)
    assert len(errors) == 1 and errors[0]['event'] == 'error' and errors[0]['reason'] == 'usage', errors
    assert root(env) == before, 'invalid text changed the reservation root'
    assert not marker.exists(), 'invalid text launched the command'


for kind in ('holder', 'note', 'path', 'batch', 'sem', 'with', 'check', 'acquisition'):
    for bad in BAD:
        case(f'refuse {kind} {bad.hex()}', lambda base, k=kind, b=bad: refuse_input(base, k, b))


def damaged_record(base, field):
    env = setup(base)
    old = root(env).decode()
    blob = git(env, 'cat-file', '-p', old + ':jobs/owner')
    if field == 'path':
        blob = blob.replace(b'held.md', b'bad-\x80.md')
    elif field == 'unknown':
        blob = b'unknown-\x80: value\n' + blob
    elif field == 'note':
        blob = b'note: bad-\xed\xa0\x80\n' + blob
    else:
        blob = blob.replace(b'holder: alice', b'holder: bad-\xf4\x90\x80\x80')
    oid = git(env, 'hash-object', '-w', '--stdin', data=blob).strip().decode()
    tree = git(env, 'ls-tree', '-r', old).splitlines()
    index_env = dict(BASE, GIT_INDEX_FILE=str(base / 'fixture.index'))
    git_args = ['git', '--git-dir=' + env['GIT_LOCKS_STORE']]
    subprocess.run([*git_args, 'read-tree', '--empty'], env=index_env, check=True, timeout=10)
    entries = b''.join(b'100644 ' + oid.encode() + b'\t' + entry.split(b'\t')[1] + b'\n' for entry in tree)
    subprocess.run([*git_args, 'update-index', '--index-info'], env=index_env, input=entries, check=True, timeout=10)
    state = subprocess.check_output([*git_args, 'write-tree'], env=index_env, timeout=10).strip().decode()
    git(env, 'update-ref', 'refs/locks/state', state, old)
    before = root(env)
    for args in (['list'], ['check', 'held.md'], ['release', '--job', 'owner'], ['sweep'],
                 ['claim', '--job', 'other', '--holder', 'bob', 'free.md'],
                 ['with', '--job', 'other', '--holder', 'bob', 'free.md', '--', 'touch', str(base / 'ran')]):
        result = run(env, *args)
        assert result.returncode == 2 and not result.stdout, result
        errors = rows(result.stderr)
        assert errors[0]['reason'] == 'store-read' and 'UTF-8' in errors[0]['detail'], errors
        assert root(env) == before and not (base / 'ran').exists()
    result = run(env, 'doctor')
    assert result.returncode == 1 and not result.stderr, result
    findings = rows(result.stdout)
    assert any(item.get('check') == 'record-decodes' and 'UTF-8' in item['detail'] for item in findings)
    assert root(env) == before


for field in ('holder', 'note', 'path', 'unknown'):
    case('corrupt stored ' + field + ' remains diagnosable and cannot authorize work',
         lambda base, f=field: damaged_record(base, f))


def diagnostics(base):
    env = setup(base)
    before = root(env)
    result = run(env, 'claim', '--job', b'bad-\x80', '--holder', 'alice', 'free.md')
    assert result.returncode == 2
    errors = rows(result.stderr)
    assert '\ufffd' in errors[0]['detail']
    # An external Git diagnostic is not guaranteed to be UTF-8 either.
    shim = base / 'shim'
    shim.mkdir()
    import shutil
    executable = shim / 'git'
    executable.write_text('#!/bin/bash\nfor arg in "$@"; do\n'
                          '  if [[ "$arg" == for-each-ref ]]; then printf "bad Git byte: \\377\\n" >&2; exit 65; fi\n'
                          'done\nexec ' + shutil.which('git') + ' "$@"\n')
    executable.chmod(0o755)
    result = run(dict(env, PATH=str(shim) + os.pathsep + env['PATH']), 'list')
    assert result.returncode == 2 and not result.stdout
    errors = rows(result.stderr)
    assert errors[0]['reason'] == 'store-read' and '\ufffd' in errors[0]['detail']
    assert root(env) == before


case('invalid input and external diagnostics still produce valid JSON', diagnostics)


def store_path(base):
    selector = os.fsdecode(os.fsencode(base) + b'/store-\x80.git')
    result = run(dict(BASE, GIT_LOCKS_STORE=selector), 'store')
    assert result.returncode == 2 and not result.stdout, result
    errors = rows(result.stderr)
    assert errors[0]['reason'] == 'usage' and 'UTF-8' in errors[0]['detail']
    assert not os.path.exists(selector)


case('invalid store pathname is refused before initialization', store_path)


def valid_text(base):
    env = setup(base)
    text = ''.join(chr(c) for c in (0x7f, 0x80, 0x7ff, 0x800, 0xd7ff, 0xe000, 0xffff, 0x10000, 0x10ffff))
    text += ' café cafe\u0301 日本語 🔐 " \\ \t \u0085 \u2028 \u2029'
    paths = ['café.md', 'cafe\u0301.md', '🔐/鍵.md']
    result = run(env, 'claim', '--job', 'unicode', '--holder', text, '--note', text, *paths)
    assert result.returncode == 0 and not result.stderr, result
    claim = rows(result.stdout)[0]
    assert claim['holder'] == text and claim['note'] == text and set(claim['paths']) == set(paths)
    result = run(env, 'show', '--job', 'unicode')
    record = rows(result.stdout)[0]
    assert record['holder'] == text and record['note'] == text and set(record['paths']) == set(paths)
    for path in paths:
        result = run(env, 'check', path)
        assert result.returncode == 1 and rows(result.stdout)[0]['path'] == path
    # The wrapped program owns its arguments and output; do not validate its payload.
    result = run(env, 'with', '--job', 'wrapped', '--holder', 'alice', 'wrapped.md', '--',
                 'python3', '-c', 'import os,sys; sys.stdout.buffer.write(os.fsencode(sys.argv[1]))', b'\x80')
    assert result.returncode == 0 and result.stdout == b'\x80'
    rows(result.stderr)


case('valid scalar boundaries round-trip without normalization; child bytes remain its own', valid_text)


def codec_oracle(base):
    rng = random.Random(6301)
    corpus = [b''] + [bytes([n]) for n in range(1, 256)] + BAD
    corpus += [bytes(rng.randrange(1, 256) for _ in range(rng.randrange(1, 12))) for _ in range(2048)]
    for _ in range(256):
        scalars = []
        while len(scalars) < 8:
            scalar = rng.randrange(1, 0x110000)
            if not 0xd800 <= scalar <= 0xdfff:
                scalars.append(chr(scalar))
        corpus.append(''.join(scalars).encode())
    corpus += [b'prefix-\xe2\x98\x83-\x80-suffix-\xf0\x9f\x94\x90', b'\xe2\x82']
    # One process avoids turning a codec comparison into thousands of Git fixtures.
    script = '''source "$1/lib/000-prelude.sh"
source "$1/lib/005-utf8.sh"
source "$1/lib/010-json.sh"
while IFS= read -r -d '' text; do
  if valid_utf8 "$text"; then valid=true; else valid=false; fi
  json_str encoded "$text"
  printf '{"valid":%s,"text":%s}\\n' "$valid" "$encoded"
done
'''
    result = subprocess.run(['bash', '-c', script, 'codec-fixture', str(ROOT)], env=BASE,
                            input=b''.join(item + b'\0' for item in corpus), capture_output=True, timeout=20)
    assert result.returncode == 0 and not result.stderr, result
    # JSON Lines uses LF, not Unicode's broader set of line separator scalars.
    output = [json.loads(line) for line in result.stdout.decode('utf-8', errors='strict').split('\n') if line]
    assert len(output) == len(corpus)
    for original, item in zip(corpus, output):
        try:
            decoded = original.decode('utf-8', errors='strict')
        except UnicodeDecodeError:
            assert item['valid'] is False and '\ufffd' in item['text'], (original, item)
        else:
            assert item == {'valid': True, 'text': decoded}, (original, item)
        assert not any(0xd800 <= ord(c) <= 0xdfff for c in item['text'])
    assert output[-2]['text'] == 'prefix-☃-\ufffd-suffix-🔐'
    assert output[-1]['text'] == '\ufffd\ufffd'
    print(f'Codec oracle: {len(corpus)} byte strings compared with Python strict UTF-8', flush=True)


case('codec agrees with independent strict decoder and preserves mixed valid diagnostic text', codec_oracle)
print(f'UTF-8 JSON: {checks} passed; {len(failures)} failed', flush=True)
raise SystemExit(bool(failures))
