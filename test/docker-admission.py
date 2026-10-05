#!/usr/bin/env python3
"""Admission proof tests; root ownership is synthetic except explicit refusals."""
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import importlib.util
import json
import os
import stat
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('admission', ROOT / 'scripts/docker-admission.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
run_id = 'a' * 32
capacity = 19 << 30
valid = {'protocol': 1, 'run': run_id, 'capacity': capacity, 'monotonic': 100.0}
checks = 0

def refused(command):
    try:
        command()
    except (OSError, RuntimeError, ValueError):
        return
    raise AssertionError('accepted invalid admission proof')

# Read real kernel ownership on the existing worker; no root operations.
assert os.geteuid() == 1000
fd = module.directory_fd()
os.close(fd)
refused(lambda: module.publish(run_id, capacity))
checks += 2

# Parent ownership/permissions and the sticky shared-memory directory are required.
for mode, uid in [(stat.S_IFDIR | 0o777, 0), (stat.S_IFDIR | 0o755, 1000),
                  (stat.S_IFLNK | 0o777, 0)]:
    with patch.object(module.os, 'lstat', return_value=SimpleNamespace(st_mode=mode, st_uid=uid)):
        refused(module.directory_fd)
    checks += 1
for mode, uid in [(stat.S_IFDIR | 0o777, 0), (stat.S_IFDIR | 0o1777, 1000),
                  (stat.S_IFREG | 0o1777, 0)]:
    with patch.object(module.os, 'fstat', return_value=SimpleNamespace(st_mode=mode, st_uid=uid)):
        refused(module.directory_fd)
    checks += 1

with tempfile.TemporaryDirectory(prefix='locks-admission-') as scratch:
    directory = Path(scratch)
    receipt = directory / module.NAME
    receipt.write_text(json.dumps(valid))
    open_directory = lambda: os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    real_fstat = os.fstat
    metadata_changes = {}
    def metadata(fd):
        row = real_fstat(fd)
        return SimpleNamespace(**dict({'st_mode': row.st_mode, 'st_uid': 0,
                                      'st_nlink': row.st_nlink, 'st_size': row.st_size},
                                     **metadata_changes))
    with patch.object(module, 'directory_fd', open_directory):
        # This actual UID1000 file cannot authenticate itself.
        refused(lambda: module.read(run_id, capacity))
        checks += 1
        with patch.object(module.os, 'fstat', side_effect=metadata), \
             patch.object(module.time, 'monotonic', return_value=101.0):
            assert module.read(run_id, capacity) == capacity
            checks += 1
            for changes in [{'protocol': True}, {'protocol': 2}, {'run': 'b'*32},
                            {'capacity': True}, {'capacity': capacity-1},
                            {'monotonic': 90.0}, {'monotonic': 102.0},
                            {'monotonic': float('nan')}, {'monotonic': float('inf')},
                            {'monotonic': True}, {'extra': 1}]:
                receipt.write_text(json.dumps(dict(valid, **changes)))
                refused(lambda: module.read(run_id, capacity))
                checks += 1
            for raw in ('[]', '{', 'x' * 4097):
                receipt.write_text(raw)
                refused(lambda: module.read(run_id, capacity))
                checks += 1
            receipt.write_text(json.dumps(valid))
            for changes in [{'st_uid': 1000}, {'st_mode': stat.S_IFREG | 0o666},
                            {'st_nlink': 2}, {'st_size': 0}, {'st_size': 4097}]:
                metadata_changes.clear()
                metadata_changes.update(changes)
                refused(lambda: module.read(run_id, capacity))
                checks += 1
            metadata_changes.clear()
            receipt.unlink()
            refused(lambda: module.read(run_id, capacity))
            target = directory / 'target'
            target.write_text(json.dumps(valid))
            receipt.symlink_to(target)
            refused(lambda: module.read(run_id, capacity))
            receipt.unlink()
            os.mkfifo(receipt)
            refused(lambda: module.read(run_id, capacity))
            receipt.unlink()
            checks += 3
        # Simulate privileged publication using actual exclusive/atomic file I/O.
        # geteuid is mocked; resulting file is still really owned by UID1000.
        with patch.object(module.os, 'geteuid', return_value=0), \
             patch.object(module.time, 'monotonic', return_value=100.0):
            module.publish(run_id, capacity)
            assert json.loads(receipt.read_text()) == valid
            assert not (directory / module.PENDING).exists()
            checks += 1
            previous = receipt.read_bytes()
            refused(lambda: module.publish(run_id, capacity))  # existing nonroot target
            assert receipt.read_bytes() == previous
            checks += 1
            receipt.unlink()
            with patch.object(module.os, 'replace', side_effect=OSError('injected publication failure')):
                refused(lambda: module.publish(run_id, capacity))
            assert not receipt.exists() and not (directory / module.PENDING).exists()
            checks += 1
            pending = directory / module.PENDING
            pending.write_text('unowned pending file')
            refused(lambda: module.publish(run_id, capacity))
            assert pending.read_text() == 'unowned pending file'
            checks += 1

for bad_run, bad_capacity in [('x', capacity), (run_id, True), (run_id, 0), (run_id, 20 << 30)]:
    refused(lambda: module.read(bad_run, bad_capacity))
    checks += 1
print(f'Admission proof: {checks} cases passed; privileged writer ownership remains unverified', flush=True)
