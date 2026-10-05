#!/usr/bin/env python3
"""Bound a root-receipt probe inside the existing guarded worker.

Invoke under the workstation heavy/worker keys. Optional arguments after --
replace the launcher prefix, for example an existing project-budget runner.
This does not create a private daemon or prove a small backing filesystem.
"""
from pathlib import Path
import importlib.util
import os
import signal
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('host_runner', ROOT / 'scripts/docker-run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

def main():
    if sys.argv[1:] and (sys.argv[1] != '--' or len(sys.argv) < 3):
        raise RuntimeError('expected -- followed by guarded launcher prefix')
    launcher = sys.argv[2:] or [sys.executable, str(ROOT / 'scripts/docker-run.py')]
    run_id, capacity = uuid.uuid4().hex, 19 << 30
    program = (ROOT / 'scripts/docker-admission.py').read_text()
    def interrupted(signum, frame):
        raise RuntimeError('admission probe interrupted')
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, interrupted)
    child = subprocess.Popen([*launcher, 'python3', 'test/docker-admission-live.py', run_id, str(capacity)],
                             cwd=ROOT, start_new_session=True)
    deadline = time.monotonic() + 60
    published = set()
    try:
        while child.poll() is None:
            if time.monotonic() >= deadline:
                raise RuntimeError('live admission probe exceeded 60 seconds')
            for marker in ('admission-ready', 'admission-refresh'):
                if marker in published:
                    continue
                result = subprocess.run(['docker', 'exec', runner.WORKER, 'test', '-f', '/evidence/' + marker],
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                if result.returncode == 0:
                    # Exercise the production publication call with a synthetic
                    # capacity admission. No quota or cgroup proof is claimed.
                    class Boundary:
                        initial = {'capacity_bytes': capacity}
                        def check(self): return self.initial
                    runner.publish_admission(Boundary(), run_id, program)
                    published.add(marker)
            time.sleep(.05)
        if child.returncode or len(published) != 2:
            raise RuntimeError('live admission probe did not complete both publications')
        return 0
    finally:
        if child.poll() is None:
            # Stop remote work first; killing docker exec alone is insufficient.
            try:
                subprocess.run(['docker', 'stop', '--time', '5', runner.WORKER],
                               timeout=15, check=True, stdout=subprocess.DEVNULL)
            finally:
                try: os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError: pass
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try: os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    child.wait(timeout=5)

if __name__ == '__main__':
    sys.exit(main())
