#!/usr/bin/env python3
"""Fetch pinned Bash inputs, then build and test only in the guarded worker."""
from pathlib import Path
import argparse
import hashlib
import os
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    '4.3': ('afc687a28e0e24dc21b988fa159ff9dbcf6b7caa92ade8645cc6d5605cd024d4', 7955839),
    '4.4': ('d86b3392c1202e8ff5a423b302e6284db7f8f435ea9f39b5b1b20fd3ac36dfcb', 9377313),
}
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('operation', choices=['fetch', 'test'])
parser.add_argument('--sources', type=Path, default=ROOT / 'bash-compat-input')
parser.add_argument('--interpreters', type=Path, help='reuse explicitly supplied, locally built interpreters for a test run')
parser.add_argument('--full', action='store_true', help='also run the full production suite through Bash 4.4')
args = parser.parse_args()


def bounded(command, timeout, **kwargs):
    process = subprocess.Popen(command, start_new_session=True, **kwargs)
    try:
        code = process.wait(timeout=timeout)
        if code:
            raise subprocess.CalledProcessError(code, command)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def verify(path, digest, size):
    assert path.is_file() and not path.is_symlink() and path.stat().st_size == size, path
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, path


def fetch():
    # At most two pinned archives (~17 MiB), plus one bounded partial download.
    args.sources.mkdir(exist_ok=True)
    deadline = time.monotonic() + 120
    for version, (digest, size) in SOURCES.items():
        target = args.sources / f'bash-{version}.tar.gz'
        if target.exists():
            verify(target, digest, size)
            continue
        assert shutil.disk_usage(args.sources).free >= 50 * 1024**3, 'less than 50 GiB free'
        with tempfile.NamedTemporaryFile(dir=args.sources, prefix='download-') as output:
            url = f'https://ftp.gnu.org/gnu/bash/bash-{version}.tar.gz'
            with urllib.request.urlopen(url, timeout=10) as response:
                while True:
                    assert time.monotonic() < deadline, 'download deadline exceeded'
                    block = response.read(65536)
                    if not block:
                        break
                    assert output.tell() + len(block) <= size, 'archive exceeds pinned size'
                    output.write(block)
            output.flush()
            verify(Path(output.name), digest, size)
            # Do not replace a concurrently created or unrelated input.
            os.link(output.name, target)


def extract(archive, destination, version):
    prefix = f'bash-{version}'
    with tarfile.open(archive) as stream:
        members = stream.getmembers()
        assert len(members) < 2000 and sum(m.size for m in members) < 32 * 1024**2
        links = []
        for member in members:
            relative = Path(member.name)
            assert not relative.is_absolute() and '..' not in relative.parts
            assert relative.parts and relative.parts[0] == prefix
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                target.parent.mkdir(parents=True, exist_ok=True)
                with stream.extractfile(member) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)
            else:
                assert member.issym() and member.name == prefix + '/ChangeLog'
                assert member.linkname == 'CWRU/changelog'
                links.append((target, member.linkname))
        for target, link in links:
            target.symlink_to(link)


def test():
    subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)
    # The runner supplies CPU/memory limits, tmpfs quotas, a process-tree
    # deadline, and continuous data/log guards. Never compile on the host.
    with tempfile.TemporaryDirectory(prefix='locks-bash-compat-') as scratch:
        base = Path(scratch)
        binaries = []
        for version, (digest, size) in SOURCES.items():
            binary = base / f'bash-{version}'
            if args.interpreters:
                shutil.copyfile(args.interpreters / binary.name, binary)
            else:
                archive = args.sources / f'bash-{version}.tar.gz'
                verify(archive, digest, size)
                work = base / 'build'
                work.mkdir()
                try:
                    extract(archive, work, version)
                    source = work / f'bash-{version}'
                    env = dict(os.environ, CFLAGS='-O2')
                    # Compiler output is bounded by the guarded runner's log
                    # cap; no source, objects, or binaries enter an image layer.
                    bounded(['./configure', '--without-bash-malloc', '--disable-nls'],
                            cwd=source, env=env, timeout=240)
                    bounded(['make', '-j2', 'bash'], cwd=source, env=env, timeout=480)
                    shutil.copyfile(source / 'bash', binary)
                    subprocess.run(['strip', str(binary)], check=True, timeout=15)
                finally:
                    shutil.rmtree(work)
            binary.chmod(0o700)
            binaries.append(str(binary))
        bounded(['python3', str(ROOT / 'test/bash-compatibility.py'),
                 '--bash43', binaries[0], '--bash44', binaries[1]], timeout=480)
        if args.full:
            bounded(['python3', str(ROOT / 'test/bash-floor-suite.py'),
                     '--bash44', binaries[1]], timeout=1550)


if args.operation == 'fetch':
    assert args.interpreters is None and not args.full, 'test options do not apply to fetch'
    fetch()
else:
    test()
