#!/usr/bin/env python3
"""Container cleanup reaches detached descendants even after their leader exits."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import os
import runpy
import tempfile
import time

runner = runpy.run_path(str(ROOT / 'scripts/docker-exec.py'))
for leader_exits in (False, True):
    with tempfile.TemporaryDirectory(prefix='locks-resource-stop-') as tmp:
        receipt = Path(tmp) / 'child'
        existing = runner['process_ids']()
        leader = subprocess.Popen(['python3', '-c', '''import os, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen(['sleep', '30'], start_new_session=True)
Path(sys.argv[1]).write_text(str(child.pid))
if sys.argv[2] == 'False':
    time.sleep(30)
''', str(receipt), str(leader_exits)], start_new_session=True)
        try:
            deadline = time.monotonic() + 5
            while not receipt.exists():
                assert time.monotonic() < deadline and leader.poll() is None
                time.sleep(.01)
            child = int(receipt.read_text())
            assert os.getpgid(child) != leader.pid, 'fixture did not escape its leader group'
            if leader_exits:
                assert leader.wait(timeout=5) == 0
            runner['stop_workload'](existing)
            leader.wait(timeout=5)
            state = Path(f'/proc/{child}/stat')
            assert not state.exists() or state.read_text().rsplit(')', 1)[1].split()[0] == 'Z', 'detached child survived'
        finally:
            runner['stop_workload'](existing)
            leader.wait(timeout=5)
print('Docker resource cleanup: live and exited leaders with detached descendants stopped')

# A counter failure is an enforcement failure even when it is not one of the
# runner's expected quota exceptions. Exercise main's actual cleanup path.
import json

with tempfile.TemporaryDirectory(prefix='locks-monitor-failure-') as tmp:
    evidence = Path(tmp)
    identity = evidence / 'identity'
    main = runner['main']
    globals_ = main.__globals__
    real_measure = globals_['measure']

    def failed_counter():
        real_measure()
        if identity.exists():
            parent, child = map(int, identity.read_text().split())
            state = Path(f'/proc/{parent}/stat')
            if not state.exists() or state.read_text().rsplit(')', 1)[1].split()[0] == 'Z':
                raise ValueError('injected disk-counter decoding failure')

    globals_['measure'] = failed_counter
    result = main(['python3', '-c', '''import os, subprocess, sys
from pathlib import Path
child = subprocess.Popen(['sleep', '30'], start_new_session=True)
Path(sys.argv[1]).write_text(f'{os.getpid()} {child.pid}')
''', str(identity)], evidence)
    assert result == 2
    receipt = json.loads((evidence / 'resources.json').read_text())
    assert receipt['guard_error'] == 'injected disk-counter decoding failure', receipt
    child = int(identity.read_text().split()[1])
    state = Path(f'/proc/{child}/stat')
    assert not state.exists() or state.read_text().rsplit(')', 1)[1].split()[0] == 'Z'
print('Docker resource cleanup: unexpected monitor failure stopped an orphan in another session')
