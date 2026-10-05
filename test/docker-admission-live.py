#!/usr/bin/env python3
"""Live root/worker receipt boundary; run only through test-admission-live.py."""
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)
import importlib.util
import os
import sys
import time

if len(sys.argv) != 3:
    raise SystemExit('host coordinator must supply run identity and capacity')
run_id, capacity = sys.argv[1], int(sys.argv[2])
spec = importlib.util.spec_from_file_location('proof', ROOT / 'scripts/docker-admission.py')
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)
assert os.geteuid() == 1000
receipt = proof.DIRECTORY / proof.NAME
ready = Path('/evidence/admission-ready')
ready.touch()
def await_valid():
    deadline = time.monotonic() + 10
    while True:
        try:
            assert proof.read(run_id, capacity) == capacity
            return
        except (FileNotFoundError, RuntimeError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(.05)
await_valid()
assert receipt.stat().st_uid == 0 and receipt.stat().st_nlink == 1
original = receipt.read_bytes()
def denied(operation):
    try:
        operation()
    except PermissionError:
        return
    raise AssertionError('worker modified root-owned admission')
denied(lambda: receipt.write_text('forged'))
denied(receipt.unlink)
denied(lambda: receipt.chmod(0o666))
attack = proof.DIRECTORY / ('attacker-' + run_id)
try:
    attack.write_text('forged replacement')
    denied(lambda: os.replace(attack, receipt))
finally:
    attack.unlink(missing_ok=True)
assert receipt.read_bytes() == original
for identity, size in [('0'*32, capacity), (run_id, capacity-1)]:
    try:
        proof.read(identity, size)
    except RuntimeError:
        pass
    else:
        raise AssertionError('accepted wrong run or capacity')
print('PASS actual root publication; worker cannot write, unlink, chmod, or replace proof', flush=True)
deadline = time.monotonic() + proof.MAX_AGE + 2
while True:
    try:
        proof.read(run_id, capacity)
    except RuntimeError as error:
        assert 'stale' in str(error)
        break
    assert time.monotonic() < deadline, 'receipt did not expire'
    time.sleep(.05)
print('PASS actual proof expires when root supervisor stops refreshing', flush=True)
Path('/evidence/admission-refresh').touch()
await_valid()
assert receipt.read_bytes() != original
print('PASS actual root refresh restores matching admission', flush=True)
