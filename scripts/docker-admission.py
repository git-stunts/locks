#!/usr/bin/env python3
"""Root-published, short-lived admission evidence for one private worker run.

This is host-supervisor provenance, not isolation against malicious test code.
The provider remains disabled until the complete privileged path is verified.
"""
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

DIRECTORY = Path('/dev/shm')
NAME = 'git-locks-bootstrap-admission.json'
PENDING = NAME + '.pending'
MAX_BYTES = 4096
MAX_AGE = 5.0
MAX_CAPACITY = 19 * 1024**3


def directory_fd():
    for path in (Path('/'), Path('/dev')):
        metadata = os.lstat(path)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise RuntimeError('admission ancestor is not protected')
    descriptor = os.open(DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        metadata = os.fstat(descriptor)
        if (metadata.st_uid != 0 or not stat.S_ISDIR(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o1777):
            raise RuntimeError('admission directory must be root-owned and sticky')
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def validate_file(metadata):
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
            or metadata.st_mode & 0o022 or metadata.st_nlink != 1
            or not 0 < metadata.st_size <= MAX_BYTES):
        raise RuntimeError('admission receipt is not protected regular data')


def validate_request(run_id, capacity):
    if not isinstance(run_id, str) or re.fullmatch(r'[0-9a-f]{32}', run_id) is None:
        raise RuntimeError('invalid admission run identity')
    if type(capacity) is not int or not 0 < capacity <= MAX_CAPACITY:
        raise RuntimeError('invalid admission capacity')


def read(run_id, capacity):
    validate_request(run_id, capacity)
    directory = directory_fd()
    try:
        descriptor = os.open(NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, 'rb') as source:
            validate_file(os.fstat(source.fileno()))
            raw = source.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise RuntimeError('admission receipt exceeds size limit')
    finally:
        os.close(directory)
    proof = json.loads(raw)
    if (not isinstance(proof, dict) or set(proof) != {'protocol', 'run', 'capacity', 'monotonic'}
            or type(proof['protocol']) is not int or proof['protocol'] != 1
            or proof['run'] != run_id or type(proof['capacity']) is not int
            or proof['capacity'] != capacity or type(proof['monotonic']) not in (int, float)):
        raise RuntimeError('admission receipt does not match this run')
    age = time.monotonic() - proof['monotonic']
    if not math.isfinite(age) or not 0 <= age <= MAX_AGE:
        raise RuntimeError('admission receipt is stale or from the future')
    return proof['capacity']


def publish(run_id, capacity):
    validate_request(run_id, capacity)
    if os.geteuid() != 0:
        raise RuntimeError('only the host root supervisor may publish admission')
    directory = directory_fd()
    pending_owned = False
    try:
        try:
            validate_file(os.stat(NAME, dir_fd=directory, follow_symlinks=False))
        except FileNotFoundError:
            pass
        descriptor = os.open(PENDING, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o644, dir_fd=directory)
        pending_owned = True
        with os.fdopen(descriptor, 'w') as output:
            # Root ownership plus the sticky parent prevents worker replacement.
            os.fchmod(output.fileno(), 0o644)
            json.dump({'protocol': 1, 'run': run_id, 'capacity': capacity,
                       'monotonic': time.monotonic()}, output)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(PENDING, NAME, src_dir_fd=directory, dst_dir_fd=directory)
        pending_owned = False
    finally:
        try:
            if pending_owned:
                os.unlink(PENDING, dir_fd=directory)
        finally:
            os.close(directory)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != 'publish':
        raise SystemExit('usage: docker-admission.py publish RUN CAPACITY')
    publish(sys.argv[2], int(sys.argv[3]))
