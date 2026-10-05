#!/usr/bin/env python3
"""Private Docker provisioning for disposable hosted Linux runners.

This provider is not enabled in CI until its fault tests and real setup receipt
pass. The ordinary runner remains fail-closed when its image is unavailable.
"""
from pathlib import Path
import fcntl
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
CONTROL = Path('/tmp/git-locks-ci')
DATA = CONTROL / 'data'
SLICE = 'gitlocksci.slice'
CGROUP = Path('/sys/fs/cgroup') / SLICE
DAEMON = 'gitlockscidaemon.service'
COMMAND = 'gitlockscicommand.service'
BUILD_BYTES = 19 * 1024**3  # Leave headroom within the aggregate 20 GiB budget.
MEMORY_BYTES = 4 * 1024**3
LOG_BYTES = 128 * 1024**2
FREE_BYTES = 50 * 1024**3
DEADLINE_SECONDS = 1800


def run(command, **kwargs):
    return subprocess.run(command, check=True, timeout=30, **kwargs)


def daemon_config():
    # data-root does not contain a system containerd image store. Explicitly
    # use classic overlay2 and let this daemon manage its own containerd.
    return {
        'data-root': str(DATA / 'docker'), 'exec-root': str(DATA / 'run'),
        'pidfile': str(DATA / 'dockerd.pid'), 'hosts': ['unix://' + str(CONTROL / 'docker.sock')],
        'storage-driver': 'overlay2', 'features': {'containerd-snapshotter': False},
        'exec-opts': ['native.cgroupdriver=cgroupfs'], 'cgroup-parent': '/' + SLICE,
        'live-restore': False, 'shutdown-timeout': 5,
        'iptables': False, 'ip6tables': False, 'bridge': 'none',
        'ip-forward': False, 'ip-masq': False, 'userland-proxy': False,
        'log-driver': 'json-file', 'log-opts': {'max-size': '1m', 'max-file': '1'},
        'max-concurrent-downloads': 1,
    }


def allocated(directory):
    total = 0
    if directory.exists():
        for path in directory.rglob('*'):
            if path.is_file() and not path.is_symlink():
                stat = path.stat()
                total += max(stat.st_size, stat.st_blocks * 512)
    return total


class Provider:
    def __init__(self, uid, gid):
        self.uid, self.gid = uid, gid
        self.started = time.monotonic()
        self.mounted = False
        self.slice_owned = False
        self.control_owned = False
        self.minimum_free = shutil.disk_usage(ROOT).free
        self.peak_logs = 0
        self.unit_file = Path('/run/systemd/system') / SLICE
        self.receipt = ROOT / '.test-results/bootstrap.json'
        self.docker = [shutil.which('docker'), '--host', 'unix://' + str(CONTROL / 'docker.sock'),
                       '--config', str(DATA / 'client')]

    def guard(self):
        free = min(shutil.disk_usage(ROOT).free, shutil.disk_usage(CONTROL).free)
        self.minimum_free = min(self.minimum_free, free)
        if free < FREE_BYTES:
            raise RuntimeError('host/Docker backing free space below 50 GiB')
        if time.monotonic() - self.started >= DEADLINE_SECONDS:
            raise RuntimeError('bootstrap and test deadline exceeded')
        if self.slice_owned:
            quota, period = (CGROUP / 'cpu.max').read_text().split()
            if quota == 'max' or int(quota) > 2 * int(period):
                raise RuntimeError('CPU enforcement missing')
            if (CGROUP / 'memory.max').read_text().strip() != str(MEMORY_BYTES):
                raise RuntimeError('memory enforcement changed')
            if (CGROUP / 'memory.swap.max').read_text().strip() != '0':
                raise RuntimeError('swap enforcement changed')
            if not (CGROUP / 'cgroup.kill').is_file():
                raise RuntimeError('owned process-tree cancellation unavailable')
        if self.mounted:
            if not os.path.ismount(DATA):
                raise RuntimeError('quota filesystem disappeared')
            fs = os.statvfs(DATA)
            if fs.f_blocks * fs.f_frsize > BUILD_BYTES:
                raise RuntimeError('build filesystem exceeds quota')
            if fs.f_bavail * fs.f_frsize < 64 * 1024**2:
                raise RuntimeError('build filesystem reserve exhausted')
        logs = allocated(ROOT / '.test-results')
        for path in (CONTROL / 'daemon.log', CONTROL / 'command.log'):
            if path.exists():
                size = path.stat().st_size
                if size > 16 * 1024**2:
                    raise RuntimeError('bootstrap log exceeded 16 MiB')
                logs += size
        for path in (DATA / 'docker/containers').glob('*/*-json.log'):
            logs += path.stat().st_size
        self.peak_logs = max(self.peak_logs, logs)
        # Reserve space for the ordinary worker's 16 MiB live log/evidence tmpfs.
        if logs > LOG_BYTES - 20 * 1024**2:
            raise RuntimeError('aggregate log reserve exhausted')

    def command(self, command, user=False):
        self.guard()
        invocation = ['systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                      '--unit', COMMAND, '--slice', SLICE,
                      '--property=KillMode=control-group', '--property=TimeoutStopSec=5',
                      '--property=RuntimeMaxSec=1800', '--working-directory', str(ROOT)]
        if user:
            invocation += ['--uid', str(self.uid), '--gid', str(self.gid)]
        environment = {'PATH': os.environ['PATH'], 'HOME': str(DATA / 'client'),
                       'TMPDIR': str(DATA / 'tmp'), 'DOCKER_TMPDIR': str(DATA / 'tmp'),
                       'DOCKER_HOST': 'unix://' + str(CONTROL / 'docker.sock'),
                       'DOCKER_CONFIG': str(DATA / 'client')}
        invocation += ['--setenv=' + key + '=' + value for key, value in environment.items()]
        invocation += ['--', *command]
        with (CONTROL / 'command.log').open('ab') as output:
            process = subprocess.Popen(invocation, stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                while process.poll() is None:
                    self.guard()
                    time.sleep(.25)
                self.guard()
                if process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, command)
            finally:
                if process.poll() is None:
                    self.kill_owned()
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()

    def kill_owned(self):
        if self.slice_owned and (CGROUP / 'cgroup.kill').exists():
            (CGROUP / 'cgroup.kill').write_text('1\n')

    def setup(self):
        if CONTROL.exists() or self.unit_file.exists() or CGROUP.exists():
            raise RuntimeError('prior bootstrap resources exist; inspect their owner before reuse or cleanup')
        CONTROL.mkdir(mode=0o711)
        self.control_owned = True
        self.guard()
        image = CONTROL / 'storage.ext4'
        with image.open('xb') as output:
            output.truncate(BUILD_BYTES)
        run(['mkfs.ext4', '-q', '-F', '-m', '0', str(image)], stdout=subprocess.DEVNULL)
        DATA.mkdir()
        run(['mount', '-o', 'loop,nosuid,nodev', str(image), str(DATA)])
        self.mounted = True
        self.unit_file.write_text('[Unit]\nDescription=Owned git-locks CI resources\n'
                                  '[Slice]\nCPUQuota=200%\nCPUQuotaPeriodSec=100ms\n'
                                  'MemoryMax=4G\nMemorySwapMax=0\nTasksMax=2048\n')
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'start', SLICE])
        self.slice_owned = True
        self.guard()
        for name in ('client', 'tmp', 'home'):
            path = DATA / name
            path.mkdir(mode=0o700)
            os.chown(path, self.uid, self.gid)
        config = CONTROL / 'daemon.json'
        config.write_text(json.dumps(daemon_config()) + '\n')
        run(['systemd-run', '--quiet', '--unit', DAEMON, '--slice', SLICE,
             '--property=Delegate=yes', '--property=KillMode=control-group',
             '--property=TimeoutStopSec=5', '--property=RuntimeMaxSec=1800',
             '--property=StandardOutput=append:' + str(CONTROL / 'daemon.log'),
             '--property=StandardError=append:' + str(CONTROL / 'daemon.log'),
             '--setenv=DOCKER_TMPDIR=' + str(DATA / 'tmp'),
             '--setenv=TMPDIR=' + str(DATA / 'tmp'), '--setenv=HOME=' + str(DATA / 'home'),
             '--', shutil.which('dockerd'), '--config-file', str(config)])
        ready_deadline = time.monotonic() + 45
        while True:
            self.guard()
            result = subprocess.run([*self.docker, 'info', '--format', '{{json .}}'],
                                    capture_output=True, timeout=5)
            if result.returncode == 0:
                info = json.loads(result.stdout)
                if info['DockerRootDir'] != str(DATA / 'docker') or info['Driver'] != 'overlay2':
                    raise RuntimeError('Docker storage escaped the owned quota boundary')
                if info['CgroupDriver'] != 'cgroupfs' or info['CgroupVersion'] != '2':
                    raise RuntimeError('Docker cgroup boundary differs')
                break
            if time.monotonic() >= ready_deadline:
                raise RuntimeError('private Docker daemon did not become ready')
            time.sleep(.25)
        os.chown(CONTROL / 'docker.sock', self.uid, self.gid)
        (CONTROL / 'docker.sock').chmod(0o600)

    def cleanup(self):
        self.kill_owned()
        if self.slice_owned:
            for unit in (COMMAND, DAEMON, SLICE):
                subprocess.run(['systemctl', 'stop', unit], timeout=20, check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if CGROUP.exists() and 'populated 1' in (CGROUP / 'cgroup.events').read_text():
                raise RuntimeError('owned processes remain; preserving mounted recovery data')
        self.receipt.parent.mkdir(exist_ok=True)
        self.receipt.write_text(json.dumps({
            'build_filesystem_bytes': BUILD_BYTES, 'memory_bytes': MEMORY_BYTES,
            'cpus': 2, 'timeout_seconds': DEADLINE_SECONDS,
            'minimum_backing_free_bytes': self.minimum_free, 'peak_counted_log_bytes': self.peak_logs,
            'command': sys.argv[1:], 'status': getattr(self, 'status', 'incomplete'),
        }, indent=2) + '\n')
        os.chown(self.receipt, self.uid, self.gid)
        for name in ('daemon.log', 'command.log'):
            source = CONTROL / name
            if source.exists():
                target = self.receipt.parent / ('bootstrap-' + name)
                if target.exists():
                    raise RuntimeError('refusing to overwrite earlier bootstrap evidence')
                shutil.copyfile(source, target)
                os.chown(target, self.uid, self.gid)
        if self.mounted:
            run(['umount', str(DATA)])
            self.mounted = False
        if self.slice_owned:
            self.unit_file.unlink()
            run(['systemctl', 'daemon-reload'])
        if self.control_owned:
            shutil.rmtree(CONTROL)


def main():
    # Deliberately fail closed while the provider is being completed. In
    # particular, the ordinary worker's backing-space check must distinguish a
    # verified quota filesystem, and monitor death must terminate daemon work.
    raise RuntimeError('provisioning prototype disabled: monitor-death cleanup and quota integration are unverified')


def provision():
    if platform.system() != 'Linux' or os.geteuid() != 0:
        raise RuntimeError('private provisioning requires root on a disposable hosted Linux runner')
    if os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted':
        raise RuntimeError('this provider is restricted to disposable GitHub-hosted runners')
    uid, gid = int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID'])
    if uid == 0 or not (Path('/sys/fs/cgroup') / 'cgroup.controllers').is_file():
        raise RuntimeError('non-root command owner and cgroup v2 required')
    for tool in ('systemd-run', 'systemctl', 'docker', 'dockerd', 'mkfs.ext4', 'mount', 'umount'):
        if not shutil.which(tool):
            raise RuntimeError('missing bootstrap tool: ' + tool)
    if shutil.disk_usage(ROOT).free < FREE_BYTES or shutil.disk_usage('/tmp').free < FREE_BYTES:
        raise RuntimeError('less than 50 GiB backing free space')
    descriptor = os.open('/run/lock/git-locks-ci.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        provider = Provider(uid, gid)
        try:
            provider.setup()
            recipe = ROOT / 'scripts/docker/Dockerfile'
            fingerprint = hashlib.sha256(recipe.read_bytes()).hexdigest()
            provider.command([*provider.docker, 'build', '--network', 'host',
                              '--cgroup-parent', '/' + SLICE, '--label', 'git-stunts.locks.tests=' + fingerprint,
                              '--tag', 'git-locks-tests:local', str(recipe.parent)], user=True)
            provider.command([sys.executable, str(ROOT / 'scripts/docker-run.py'), *sys.argv[1:]], user=True)
            provider.status = 'passed'
        finally:
            provider.cleanup()


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print('Docker CI provisioning: ' + str(error), file=sys.stderr)
        sys.exit(2)
