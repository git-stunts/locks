#!/usr/bin/env python3
"""Exercise artifact export using real child pipes, without nested Docker."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import importlib.util
import io
import tarfile
import tempfile
import time
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('export_runner', ROOT / 'scripts/docker-run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
archive = io.BytesIO()
payload = b'evidence' * 4096
with tarfile.open(fileobj=archive, mode='w') as tar:
    member = tarfile.TarInfo('artifacts/receipt.bin')
    member.size = len(payload)
    tar.addfile(member, io.BytesIO(payload))
original_popen = subprocess.Popen
physical_usage = runner.shutil.disk_usage
for mode in ('success', 'header stall', 'body stall', 'exit stall'):
    with tempfile.TemporaryDirectory(prefix='locks-export-') as scratch:
        root = Path(scratch)
        source = root / 'input.tar'
        source.write_bytes(archive.getvalue())
        children = []
        def launch(command, **kwargs):
            assert command[:2] == ['docker', 'exec']
            child = original_popen(['python3', '-c', """import os,signal,subprocess,sys,time
from pathlib import Path
mode = sys.argv[2]
data = Path(sys.argv[1]).read_bytes()
if mode == 'exit stall':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = subprocess.Popen(['sleep', '10'])
    Path(sys.argv[1]+'.child').write_text(str(child.pid))
if mode == 'header stall': time.sleep(2)
if mode == 'body stall':
    os.write(1, data[:10240])
    time.sleep(2)
    data = data[10240:]
while data:
    data = data[os.write(1, data):]
os.close(1)
if mode == 'exit stall': time.sleep(10)
""", str(source), mode], **kwargs)
            children.append(child)
            return child
        # Receipts live in the capped fixture tmpfs. The host-space input is
        # the worker's actual VM backing filesystem; the outer guard stays on.
        started = time.monotonic()
        try:
            with patch.object(runner.subprocess, 'Popen', side_effect=launch), \
                 patch.object(runner, 'EXPORT_TIMEOUT', .2, create=True), \
                 patch.object(runner.shutil, 'disk_usage', side_effect=lambda path: physical_usage('/')):
                try:
                    runner.export_artifacts(root)
                except subprocess.TimeoutExpired:
                    assert mode != 'success'
                else:
                    assert mode == 'success', 'stalled artifact export had no enforced deadline: ' + mode
                    assert (root / 'artifacts/receipt.bin').read_bytes() == payload
            assert time.monotonic() - started < 5, mode
            assert all(child.poll() is not None for child in children), 'export client survived cleanup'
            if mode == 'exit stall':
                child_pid = int(Path(str(source)+'.child').read_text())
                state = Path(f'/proc/{child_pid}/stat')
                assert not state.exists() or state.read_text().rsplit(')', 1)[1].split()[0] == 'Z', 'export descendant survived'
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=2)
        print('PASS artifact export: ' + mode, flush=True)
print('Artifact export: real successful stream and three deadline/cancellation cases passed')
