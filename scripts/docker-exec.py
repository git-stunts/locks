#!/usr/bin/env python3
"""Bound one copied workload and measure its temporary filesystems."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import json
import os
import resource
import selectors
import signal
import sys
import time

MIN_FREE = 50 * 1024**3
LOG_LIMIT = 16 * 1024**2
MOUNTS = ('/work', '/tmp', '/home/node', '/evidence')
peaks = {mount: 0 for mount in MOUNTS}
minimum_vm_free = None
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
    if free < MIN_FREE:
        raise RuntimeError('Docker VM backing filesystem has less than 50 GiB free')
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


def main():
    for path in ROOT.rglob('*'):
        if path.is_file():
            stat = path.stat()
            input_sizes[str(path)] = max(stat.st_size, stat.st_blocks * 512)
    measure()
    Path('/evidence/runner.pid').write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, interrupted_signal)
    signal.signal(signal.SIGINT, interrupted_signal)
    resource.setrlimit(resource.RLIMIT_FSIZE, (LOG_LIMIT, LOG_LIMIT))
    process = subprocess.Popen(sys.argv[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + 1800
    error = None
    written = 0
    try:
        with Path('/evidence/test.log').open('wb') as log:
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
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        error = str(exc)
        print(f'Docker resource guard: {error}', file=sys.stderr, flush=True)
        return 2
    finally:
        selector.close()
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        # Quota reserve above leaves room for this receipt even on a refused run.
        Path('/evidence/resources.json').write_text(json.dumps({
            'peak_tmpfs_bytes': peaks, 'minimum_vm_free_bytes': minimum_vm_free,
            'stdout_bytes': written, 'guard_error': error,
            'peak_generated_nonobject_bytes': peak_generated_log_bytes, 'runtime_log_budget_bytes': log_budget,
        }, indent=2) + '\n')


if __name__ == '__main__':
    sys.exit(main())
