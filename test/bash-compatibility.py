#!/usr/bin/env python3
"""Exercise the actual unsupported and minimum-supported Bash interpreters."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import argparse
import json
import os
import signal
import tempfile

import jsonschema

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bash43', required=True, type=Path)
parser.add_argument('--bash44', required=True, type=Path)
parser.add_argument('--cli', type=Path, default=ROOT / 'bin/git-locks')
args = parser.parse_args()
validator = jsonschema.Draft202012Validator(json.loads((ROOT / 'schema/git-locks.schema.json').read_text()))
checks = 0


def run(binary, env, command, expected, data=None, child_output=False):
    global checks
    process = subprocess.Popen([str(binary), str(args.cli), *command], env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(data, timeout=15)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
    assert process.returncode == expected, (command, process.returncode, stdout, stderr)
    records = []
    for stream in ([stderr] if child_output else [stdout, stderr]):
        for line in stream.splitlines():
            record = json.loads(line)
            validator.validate(record)
            records.append(record)
    checks += 1
    print(f'PASS {binary.name}: {command[0]} ({expected})', flush=True)
    return records, stdout, stderr


with tempfile.TemporaryDirectory(prefix='locks-bash-floor-') as scratch:
    base = Path(scratch)
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(TMPDIR=str(base), GIT_LOCKS_STORE=str(base / 'unsupported.git'))
    for binary, version in ((args.bash43, b'4.3.'), (args.bash44, b'4.4.')):
        actual = subprocess.check_output([str(binary), '-c', 'printf "%s" "$BASH_VERSION"'], timeout=5)
        assert actual.startswith(version), (binary, actual)
    # Reject before store initialization, parsing, wrapped-child execution, or
    # Bash's empty-array expansion can turn an unsupported runtime into exit 1.
    for command in (
        ['claim', '--job', 'a', '--holder', 'alice', 'src/'], ['list'], ['check', 'src/a'],
        ['show', '--job', 'a'], ['release', '--job', 'a'], ['doctor'], ['batch'],
        ['with', '--job', 'a', '--holder', 'alice', 'src/', '--', 'touch', str(base / 'child')],
    ):
        records, stdout, stderr = run(args.bash43, env, command, 2, b'job: a\n')
        assert not stdout and len(records) == 1
        assert records[0] == {'event': 'error', 'reason': 'usage', 'detail': 'Bash 4.4 or newer is required'}
        assert not (base / 'unsupported.git').exists() and not (base / 'child').exists()
    env['GIT_LOCKS_STORE'] = str(base / 'supported.git')
    bash = args.bash44
    records, _, _ = run(bash, env, ['claim', '--job', 'a', '--holder', 'alice', 'src/'], 0)
    acquisition = records[0]['acquisition']
    run(bash, env, ['check', 'src/a'], 1)
    run(bash, env, ['claim', '--job', 'other', '--holder', 'bob', 'src/a'], 1)
    run(bash, env, ['extend', '--job', 'a', '--acquisition', acquisition, '--ttl', '60'], 0)
    run(bash, env, ['release', '--job', 'a', '--acquisition', acquisition], 0)
    run(bash, env, ['check', 'src/a'], 0)
    run(bash, env, ['batch'], 0, b'job: batch\nholder: alice\npaths:\nsrc/a\n')
    run(bash, env, ['release', '--job', 'batch'], 0)
    run(bash, env, ['sem', 'create', 'worker', '--capacity', '1'], 0)
    run(bash, env, ['sem', 'acquire', 'worker', '--job', 'slot', '--holder', 'alice'], 0)
    run(bash, env, ['sem', 'acquire', 'worker', '--job', 'blocked', '--holder', 'bob'], 1)
    run(bash, env, ['sem', 'release', 'worker', '--job', 'slot'], 0)
    run(bash, env, ['sem', 'delete', 'worker'], 0)
    records, stdout, _ = run(bash, env, ['with', '--job', 'wrapped', '--holder', 'alice', 'src/',
                                     '--', 'printf', 'child'], 0, child_output=True)
    assert stdout == b'child' and [r['event'] for r in records] == ['claimed', 'released']
    run(bash, env, ['check', 'src/a'], 0)
    records, _, _ = run(bash, env, ['doctor'], 0)
    assert records[-1]['healthy'] is True

print(f'Bash compatibility: {checks} passed', flush=True)
