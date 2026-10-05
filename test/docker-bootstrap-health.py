#!/usr/bin/env python3
"""Exercise health-record admission using synthetic process and file facts."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import copy
import importlib.util
import json
import stat
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bootstrap_provider', ROOT / 'scripts/docker-ci.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
valid = {'protocol': 1, 'monotonic': 100.0,
         'monitor': {'pid': 20, 'parent': 1, 'started': 30},
         'watchdog': {'pid': 21, 'parent': 20, 'started': 40}}
metadata = dict(st_mode=stat.S_IFREG | 0o644, st_uid=0, st_nlink=1, st_size=256)


def check(proof, file_changes=None, processes=None):
    facts = dict(metadata, **(file_changes or {}))
    identities = processes or {row['pid']: row for row in (valid['monitor'], valid['watchdog'])}
    with patch.object(provider.os, 'lstat', return_value=SimpleNamespace(**facts)), \
         patch.object(provider.Path, 'read_text', return_value=json.dumps(proof)), \
         patch.object(provider.time, 'monotonic', return_value=101.0), \
         patch.object(provider, 'process_identity', side_effect=lambda pid: identities[pid]):
        return provider.monitor_health()


assert check(valid) == valid
checks = 1
cases = [('stale', {'monotonic': 90.0}), ('future', {'monotonic': 102.0}),
         ('nonfinite', {'monotonic': float('nan')}), ('wrong protocol', {'protocol': 2}), ('boolean protocol', {'protocol': True}),
         ('malformed identity', {'monitor': {'pid': True}}),
         ('reused PID', {'monitor': dict(valid['monitor'], started=31)}),
         ('missing watchdog', {'watchdog': dict(valid['watchdog'], pid=22)})]
for label, change in cases:
    try:
        check(dict(valid, **change))
    except (RuntimeError, KeyError):
        checks += 1
        print('PASS health refuses ' + label, flush=True)
    else:
        raise AssertionError('accepted ' + label)
for key, value in [('st_uid', 1000), ('st_mode', stat.S_IFREG | 0o666),
                   ('st_mode', stat.S_IFLNK | 0o777), ('st_nlink', 2), ('st_size', 4097)]:
    try:
        check(valid, {key: value})
    except RuntimeError:
        checks += 1
    else:
        raise AssertionError(('accepted unsafe record', key, value))
proof = copy.deepcopy(valid)
proof['watchdog']['parent'] = 99
try:
    check(proof, processes={row['pid']: row for row in (proof['monitor'], proof['watchdog'])})
except RuntimeError:
    checks += 1
else:
    raise AssertionError('accepted unrelated watchdog')
# Parse proc stat independently of the admission mocks, including parentheses in comm.
fields = ['S', '1', *(['0'] * 17), '12345']
for uid, state, allowed in [('0', 'S', True), ('1000', 'S', False), ('0', 'Z', False)]:
    fields[0] = state
    def content(path):
        return ('20 (name with ) parentheses) ' + ' '.join(fields) if path.name == 'stat'
                else 'Uid:\t' + '\t'.join([uid] * 4) + '\n')
    with patch.object(provider.Path, 'read_text', content):
        try:
            identity = provider.process_identity(20)
        except RuntimeError:
            assert not allowed
        else:
            assert allowed and identity == {'pid': 20, 'parent': 1, 'started': 12345}
    checks += 1
# Worker identity must preserve the configured unprivileged UID in all four fields.
for uids, allowed in [(['1000'] * 4, True), (['0'] * 4, False),
                      (['1001'] * 4, False), (['1000', '0', '1000', '1000'], False),
                      ([], False)]:
    fields[0] = 'S'
    def content(path):
        return ('20 (worker) ' + ' '.join(fields) if path.name == 'stat'
                else 'Uid:\t' + '\t'.join(uids) + '\n')
    with patch.object(provider.Path, 'read_text', content):
        try:
            identity = provider.process_identity(20, require_root=False)
        except RuntimeError:
            assert not allowed, uids
        else:
            assert allowed and identity == {'pid': 20, 'parent': 1, 'started': 12345}, uids
    checks += 1
print(f'Bootstrap health: {checks} synthetic cases passed', flush=True)
