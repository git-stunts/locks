#!/usr/bin/env python3
"""Quota measurements must consult protected proof, not just numeric capacity."""
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)
import runpy
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

inner = runpy.run_path(str(ROOT / 'scripts/docker-exec.py'))
measure = inner['measure']
state = measure.__globals__
capacity = 19 << 30
run_id = 'a' * 32
checks = 0
for fault in ('missing proof', 'stale proof', 'proof expires', 'valid proof'):
    calls = []
    def read(identity, size):
        calls.append((identity, size))
        assert (identity, size) == (run_id, capacity)
        if fault == 'stale proof' or (fault == 'proof expires' and len(calls) == 2):
            raise RuntimeError('admission receipt expired')
        return size
    def filesystem(path):
        total, free = (capacity, 128 << 20) if path == '/' else (512 << 20, 256 << 20)
        return SimpleNamespace(f_frsize=4096, f_blocks=total//4096,
                               f_bavail=free//4096, f_bfree=free//4096)
    proof = None if fault == 'missing proof' else SimpleNamespace(read=read)
    with patch.dict(state, quota_capacity=capacity, quota_run=run_id, admission=proof, generated_logs=lambda: 0), \
         patch.object(state['os'], 'statvfs', side_effect=filesystem):
        error = None
        try:
            measure()
            measure()  # Every measurement must revalidate freshness.
        except RuntimeError as caught:
            error = caught
        if fault == 'valid proof':
            assert error is None and len(calls) == 2
        else:
            assert error is not None, 'numeric quota bypassed ' + fault
        if fault == 'stale proof':
            assert len(calls) == 1
    checks += 1
    print('PASS inner admission: ' + fault, flush=True)
with tempfile.TemporaryDirectory(prefix='locks-admission-cli-') as scratch:
    marker = Path(scratch) / 'child-ran'
    child = [sys.executable, '-c', 'from pathlib import Path; Path(' + repr(str(marker)) + ').touch()']
    for options, diagnostic in [(['--verified-bootstrap-quota', str(capacity), '--'],
                                 'invalid internal bootstrap admission arguments'),
                                (['--verified-bootstrap-quota', str(capacity), '0'*32, '--'],
                                 'protected host admission failed')]:
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/docker-exec.py'), *options, *child],
                                capture_output=True, text=True, timeout=10)
        assert result.returncode != 0 and diagnostic in result.stderr, result
        assert not marker.exists(), 'unproved quota launched the child'
        checks += 1
print('PASS actual inner CLI refuses numeric-only and unproved run identities before launch', flush=True)
print(f'Inner admission: {checks} cases passed (four synthetic measurements, two actual CLI refusals)', flush=True)
