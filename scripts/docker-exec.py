#!/usr/bin/env python3
"""Bound one copied workload and measure its temporary filesystems."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import importlib.util
import json
import os
import resource
import selectors
import signal
import sys
import time

MIN_FREE = 50 * 1024**3
LOG_LIMIT = 16 * 1024**2
MOUNTS = ('/work', '/tmp', '/home/node', '/evidence', '/dev/shm')
peaks = {mount: 0 for mount in MOUNTS}
minimum_vm_free = None
quota_capacity = None
quota_run = None
admission = None
interrupted = False
input_sizes = {}
peak_generated_log_bytes = 0
log_budget = int(os.environ['TEST_LOG_BUDGET_BYTES'])


def generated_logs():
    # Count all generated non-object files conservatively, including fixture
    # traces with arbitrary names. Immutable copied inputs and Git object data
    # are data, not logs. Symlinks are not followed or counted a second time.
    total = 0
    for root in MOUNTS:
        for directory, children, files in os.walk(root):
            base = Path(directory)
            if (base / 'HEAD').is_file() and (base / 'objects').is_dir():
                children[:] = [child for child in children if child != 'objects']
            for name in files:
                path = base / name
                try:
                    stat = path.lstat()
                    if path.is_symlink():
                        continue
                    allocated = max(stat.st_size, stat.st_blocks * 512)
                    total += max(0, allocated - input_sizes.get(str(path), 0))
                except FileNotFoundError:
                    pass  # a fixture cleaned up between enumeration and stat
    return total


def measure():
    global minimum_vm_free, peak_generated_log_bytes
    backing = os.statvfs('/')
    free = backing.f_bavail * backing.f_frsize
    minimum_vm_free = free if minimum_vm_free is None else min(minimum_vm_free, free)
    if quota_capacity is None:
        if free < MIN_FREE:
            raise RuntimeError('Docker VM backing filesystem has less than 50 GiB free')
    else:
        if admission is None:
            raise RuntimeError('quota exception requires protected host admission proof')
        try:
            admission.read(quota_run, quota_capacity)
        except Exception as error:
            raise RuntimeError('protected host admission failed: ' + str(error)) from None
        # Host admission verified the loop backing, physical disk, guardian,
        # daemon and worker identities. It rechecks these while this runs.
        # This inner check verifies the actual root capacity and free reserve.
        if (type(quota_capacity) is not int or not 0 < quota_capacity <= 19 * 1024**3
                or backing.f_frsize <= 0 or backing.f_blocks * backing.f_frsize != quota_capacity):
            raise RuntimeError('root filesystem differs from the admitted bootstrap quota')
        if free < 64 * 1024**2:
            raise RuntimeError('bootstrap root filesystem reserve exhausted')
    for mount in MOUNTS:
        fs = os.statvfs(mount)
        used = (fs.f_blocks - fs.f_bfree) * fs.f_frsize
        peaks[mount] = max(peaks[mount], used)
        if fs.f_bavail * fs.f_frsize < 1024**2:
            raise RuntimeError(f'{mount} reached its bounded filesystem reserve')
    generated = generated_logs()
    peak_generated_log_bytes = max(peak_generated_log_bytes, generated)
    if generated > log_budget:
        raise RuntimeError('aggregate generated logs and retained evidence reached the 128 MiB project budget')


def interrupted_signal(_signum, _frame):
    global interrupted
    interrupted = True


def process_ids():
    return {int(name) for name in os.listdir('/proc') if name.isdecimal()}


def stop_workload(existing):
    """This serialized container owns every process started after the baseline.

    Sessions and process groups do not escape this boundary. Kill immediately:
    after a guard failure no grace period may keep producing unmonitored data.
    Re-scan to catch a child forked while its parent was being stopped.
    """
    deadline = time.monotonic() + 5
    while True:
        active = []
        for pid in process_ids() - existing:
            try:
                state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
                if state != 'Z':
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except PermissionError:
                        # The host may still be completing its bounded root
                        # receipt publisher. We cannot signal it; keep it in
                        # the active set until it exits or the deadline fails.
                        uids = [line.split()[1:] for line in Path(f'/proc/{pid}/status').read_text().splitlines()
                                if line.startswith('Uid:')]
                        if os.geteuid() != 1000 or uids != [['0'] * 4]:
                            raise
                    active.append(pid)
            except ProcessLookupError:
                pass
            except FileNotFoundError:
                pass
        if not active:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError('owned workload did not stop; container teardown required')
        time.sleep(.01)


def main(command=None, evidence=Path('/evidence'), admitted_capacity=None, admitted_run=None):
    global quota_capacity, quota_run, admission
    quota_capacity, quota_run = admitted_capacity, admitted_run
    admission = None
    if quota_capacity is not None:
        spec = importlib.util.spec_from_file_location('protected_admission', ROOT / 'scripts/docker-admission.py')
        admission = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(admission)
    for path in ROOT.rglob('*'):
        if path.is_file():
            stat = path.stat()
            input_sizes[str(path)] = max(stat.st_size, stat.st_blocks * 512)
    measure()
    (evidence / 'runner.pid').write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, interrupted_signal)
    signal.signal(signal.SIGINT, interrupted_signal)
    resource.setrlimit(resource.RLIMIT_FSIZE, (LOG_LIMIT, LOG_LIMIT))
    existing = process_ids()
    process = subprocess.Popen(sys.argv[1:] if command is None else command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + 1800
    error = None
    written = 0
    try:
        with (evidence / 'test.log').open('wb') as log:
            while selector.get_map() or process.poll() is None:
                measure()
                if interrupted or time.monotonic() >= deadline:
                    raise RuntimeError('workload interrupted by the host guard' if interrupted else 'workload exceeded 1800 seconds')
                for key, _ in selector.select(timeout=0.25):
                    data = os.read(key.fileobj.fileno(), 65536)
                    if not data:
                        selector.unregister(key.fileobj)
                        continue
                    written += len(data)
                    if written > LOG_LIMIT:
                        raise RuntimeError('workload output exceeded 16 MiB')
                    log.write(data)
                    log.flush()
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
        return process.wait()
    except Exception as exc:
        error = str(exc)
        print(f'Docker resource guard: {error}', file=sys.stderr, flush=True)
        return 2
    finally:
        selector.close()
        stop_workload(existing)
        process.wait(timeout=5)
        # Quota reserve above leaves room for this receipt even on a refused run.
        (evidence / 'resources.json').write_text(json.dumps({
            'peak_tmpfs_bytes': peaks, 'minimum_vm_free_bytes': minimum_vm_free,
            'stdout_bytes': written, 'guard_error': error, 'bootstrap_quota_bytes': quota_capacity,
            'peak_generated_nonobject_bytes': peak_generated_log_bytes, 'runtime_log_budget_bytes': log_budget,
        }, indent=2) + '\n')


if __name__ == '__main__':
    arguments = sys.argv[1:]
    admitted = None
    admitted_run = None
    if arguments[:1] == ['--verified-bootstrap-quota']:
        if len(arguments) < 5 or arguments[3] != '--':
            raise RuntimeError('invalid internal bootstrap admission arguments')
        admitted = int(arguments[1])
        admitted_run = arguments[2]
        arguments = arguments[4:]
    sys.exit(main(arguments, admitted_capacity=admitted, admitted_run=admitted_run))
