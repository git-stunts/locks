#!/usr/bin/env python3
"""Nonprivileged fault tests for bootstrap ownership and monitor lifetime."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import importlib.util
import os
import select
import signal
import sys
import tempfile
import time
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bootstrap_provider', ROOT / 'scripts/docker-ci.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)


def terminate(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def workload():
    return subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                            start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


for stalled in (False, True):
    process = workload()
    guard = provider.LifetimeGuard(lambda: terminate(process.pid), timeout=.25)
    try:
        guard.pulse()
        assert process.poll() is None
        if stalled:
            assert process.wait(timeout=3) == -signal.SIGKILL
        guard.close()
        guard = None
        assert process.wait(timeout=3) == -signal.SIGKILL
        print(f'PASS watchdog stops owned process group: stalled={stalled}', flush=True)
    finally:
        terminate(process.pid)
        process.wait()
        if guard is not None:
            guard.close()

guard = provider.LifetimeGuard(lambda: None)
os.kill(guard.pid, signal.SIGKILL)
try:
    guard.pulse()
except RuntimeError:
    print('PASS monitor detects watchdog death', flush=True)
else:
    raise AssertionError('dead watchdog acknowledged monitor')
try:
    guard.close()
except RuntimeError:
    pass  # Its observed SIGKILL is the injected failure.

process = workload()
ready_read, ready_write = os.pipe()
monitor = os.fork()
if monitor == 0:
    os.close(ready_read)
    os.setsid()
    try:
        guard = provider.LifetimeGuard(lambda: terminate(process.pid), timeout=2)
        guard.pulse()
        os.write(ready_write, str(guard.pid).encode())
        os.close(ready_write)
        while True:
            guard.pulse()
            time.sleep(.05)
    finally:
        os._exit(2)
os.close(ready_write)
watchdog = None
try:
    assert select.select([ready_read], [], [], 3)[0], 'monitor did not start'
    watchdog = int(os.read(ready_read, 64))
    os.kill(monitor, signal.SIGKILL)
    os.waitpid(monitor, 0)
    monitor = None
    assert process.wait(timeout=3) == -signal.SIGKILL
    print('PASS abrupt monitor death stops owned process group', flush=True)
finally:
    os.close(ready_read)
    terminate(process.pid)
    process.wait()
    if monitor is not None:
        terminate(monitor)
        os.waitpid(monitor, 0)
    if watchdog is not None:
        terminate(watchdog)

with tempfile.TemporaryDirectory(prefix='locks-bootstrap-ownership-') as scratch:
    base = Path(scratch)
    control = base / 'control'
    control.mkdir()
    old = control / 'daemon.log'
    old.write_text('unrelated prior evidence')
    with patch.object(provider, 'CONTROL', control), patch.object(provider, 'ROOT', base):
        instance = provider.Provider(os.getuid(), os.getgid())
        with patch.object(provider, 'run', side_effect=AssertionError('touched unowned setup')), \
             patch.object(provider.subprocess, 'run', side_effect=AssertionError('touched unowned setup')):
            instance.cleanup()
        assert old.read_text() == 'unrelated prior evidence'
        assert not (base / '.test-results').exists()
    print('PASS refusal cleanup preserves unowned resources and evidence', flush=True)

    # A failed systemd start can leave a slice and unit behind. Use ordinary
    # files to model that ownership state; never call the host's systemd.
    control = base / 'owned'
    control.mkdir()
    cgroup = base / 'cgroup'
    cgroup.mkdir()
    (cgroup / 'cgroup.kill').touch()
    (cgroup / 'cgroup.events').write_text('populated 0\n')
    unit = base / 'owned.slice'
    unit.write_text('owned unit')
    with patch.object(provider, 'CONTROL', control), patch.object(provider, 'CGROUP', cgroup), \
         patch.object(provider, 'ROOT', base):
        instance = provider.Provider(os.getuid(), os.getgid())
        instance.control_owned = instance.unit_owned = instance.slice_owned = True
        instance.unit_file = unit
        calls = []
        with patch.object(provider, 'run', side_effect=lambda command, **kw: calls.append(command)), \
             patch.object(provider.subprocess, 'run', side_effect=lambda command, **kw: calls.append(command)):
            instance.cleanup()
        assert (cgroup / 'cgroup.kill').read_text() == '1\n'
        assert not unit.exists() and not control.exists()
        assert ['systemctl', 'stop', provider.SLICE] in calls
    print('PASS partial activation cleans only owned unit and control paths', flush=True)

print('Bootstrap lifetime: 6 cases passed', flush=True)
