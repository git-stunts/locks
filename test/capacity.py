#!/usr/bin/env python3
"""Exercise decimal capacity through the CLI with an independent integer oracle."""
import concurrent.futures
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'bin/git-locks'
SCHEMA = json.loads((ROOT / 'schema/git-locks.schema.json').read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
SEED = 3507
LIMIT = 9223372036854775807
checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


with tempfile.TemporaryDirectory(prefix='git-locks-capacity-') as tmp:
    base = Path(tmp)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('GIT_')}
    env.update(HOME=tmp, GIT_LOCKS_STORE=str(base / 'store.git'),
               GIT_LOCKS_NOW='1000000', LC_ALL='C')

    def run(*args, expected=0):
        result = subprocess.run([str(CLI), *args], cwd=tmp, env=env,
                                text=True, capture_output=True, timeout=45)
        check(result.returncode == expected,
              f'{args}: exit {result.returncode}, expected {expected}: {result.stderr}')
        data = []
        for output in (result.stdout, result.stderr):
            for line in output.splitlines():
                value = json.loads(line)
                VALIDATOR.validate(value)
                data.append(value)
        check(bool(data), f'{args}: missing structured output')
        return data

    def git(*args, input=None):
        return subprocess.run(['git', '--git-dir=' + env['GIT_LOCKS_STORE'], *args],
                              cwd=tmp, env=env, text=True, input=input,
                              capture_output=True, check=True).stdout.strip()

    rng = random.Random(SEED)
    values = ['1', '01', '08', '010', str(LIMIT), '000' + str(LIMIT), '0' * 256 + '8']
    values += ['0' * rng.randrange(1, 25) + str(rng.randrange(1, 1000000)) for _ in range(32)]
    for index, value in enumerate(values):
        name = f'valid-{index}'
        want = int(value, 10)
        check(run('sem', 'create', name, '--capacity', value)[0]['capacity'] == want,
              f'create did not normalize {value!r}')
        check(run('sem', 'show', name)[0]['capacity'] == want, 'show capacity mismatch')
        meta = git('show', f'refs/locks/sem/{name}/meta')
        check(f'capacity: {want}' in meta.splitlines(), 'stored capacity is not canonical')
        check(run('sem', 'acquire', name, '--job', 'a', '--holder', 'alice')[0]['capacity'] == want,
              'acquire capacity mismatch')
        check(run('sem', 'release', name, '--job', 'a')[0]['capacity'] == want,
              'release capacity mismatch')
        run('sem', 'delete', name)

    invalid = ['', '0', '00', '-1', '+1', '1.0', '1e2', ' 1', '1 ', '08x', '１２',
               str(LIMIT + 1), str(2**64 + 1), '9' * 100, '0' * 100 + str(LIMIT + 1)]
    invalid += [str(rng.randrange(LIMIT + 1, 2**100)) for _ in range(16)]
    before = git('for-each-ref', '--format=%(refname) %(objectname)', 'refs/locks/')
    for index, value in enumerate(invalid):
        result = run('sem', 'create', f'invalid-{index}', '--capacity', value, expected=2)
        check(result[0]['reason'] == 'usage', 'invalid capacity is not a usage error')
        check(git('for-each-ref', '--format=%(refname) %(objectname)', 'refs/locks/') == before,
              'invalid input changed authoritative refs')

    # Stores written by 0.7.0 may have leading zeros; reads normalize without rewriting.
    run('sem', 'create', 'legacy', '--capacity', '1')
    meta = git('show', 'refs/locks/sem/legacy/meta')
    oid = git('hash-object', '-w', '--stdin', input=meta.replace('capacity: 1', 'capacity: 01') + '\n')
    git('update-ref', 'refs/locks/sem/legacy/meta', oid)
    check(run('sem', 'show', 'legacy')[0]['capacity'] == 1, 'legacy show is not normalized')
    check(run('sem', 'list')[0]['capacity'] == 1, 'legacy list is not normalized')
    check(git('rev-parse', 'refs/locks/sem/legacy/meta') == oid, 'read rewrote legacy metadata')
    run('sem', 'acquire', 'legacy', '--job', 'first', '--holder', 'alice')
    refused = run('sem', 'acquire', 'legacy', '--job', 'second', '--holder', 'bob', expected=1)[0]
    check(refused['reason'] == 'capacity' and refused['capacity'] == 1, 'legacy capacity not enforced')
    run('sem', 'release', 'legacy', '--job', 'first')
    run('sem', 'delete', 'legacy')

    # A fresh metadata record can be corrupt independently of its JSON serialization.
    for value in ('0', '08x', str(LIMIT + 1)):
        run('sem', 'create', 'bad-meta', '--capacity', '1')
        meta = git('show', 'refs/locks/sem/bad-meta/meta')
        original = git('rev-parse', 'refs/locks/sem/bad-meta/meta')
        oid = git('hash-object', '-w', '--stdin', input=meta.replace('capacity: 1', 'capacity: ' + value) + '\n')
        git('update-ref', 'refs/locks/sem/bad-meta/meta', oid)
        result = run('sem', 'show', 'bad-meta', expected=2)
        check(result[0]['reason'] == 'store-read', 'bad stored capacity did not fail closed')
        check(git('rev-parse', 'refs/locks/sem/bad-meta/meta') == oid, 'bad read changed metadata')
        git('update-ref', 'refs/locks/sem/bad-meta/meta', original)
        run('sem', 'delete', 'bad-meta')

    run('sem', 'create', 'race', '--capacity', '03')

    def contender(index):
        result = subprocess.run([str(CLI), 'sem', 'acquire', 'race', '--job', f'r{index}',
                                 '--holder', f'h{index}'], cwd=tmp, env=env, text=True,
                                capture_output=True, timeout=45)
        assert result.returncode in (0, 1), result
        for line in (result.stdout + result.stderr).splitlines():
            VALIDATOR.validate(json.loads(line))
        return result.returncode

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        statuses = list(pool.map(contender, range(12)))
    check(statuses.count(0) == 3, f'12 racers on capacity 03 had {statuses.count(0)} winners')
    observed = run('sem', 'show', 'race')[0]
    check(observed['capacity'] == 3 and observed['live'] == 3 and len(observed['slots']) == 3,
          'post-race slot state violates capacity')
    check(run('doctor')[0]['healthy'], 'post-race doctor unhealthy')

print(f'capacity: {checks} checks passed; seed {SEED}; {len(values)} valid and {len(invalid)} invalid inputs; 12 racers / 3 winners')
