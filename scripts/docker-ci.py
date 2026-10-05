#!/usr/bin/env python3
"""Private Docker provisioning for disposable hosted Linux runners.

This provider is not enabled in CI until its fault tests and real setup receipt
pass. The ordinary runner remains fail-closed when its image is unavailable.
"""
from pathlib import Path
import fcntl
import hashlib
import json
import math
import os
import platform
import select
import shutil
import signal
import stat
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


class LifetimeGuard:
    """A separate process stops owned work when monitor heartbeats disappear."""
    def __init__(self, stop, timeout=10):
        incoming, outgoing = os.pipe()
        acknowledged, acknowledge = os.pipe()
        self.pid = os.fork()
        if self.pid == 0:
            os.close(outgoing)
            os.close(acknowledged)
            os.setsid()
            code = 0
            try:
                while select.select([incoming], [], [], timeout)[0]:
                    if os.read(incoming, 1) != b'.':
                        break
                    os.write(acknowledge, b'.')
            except BaseException:
                code = 2
            finally:
                try:
                    stop()
                except BaseException:
                    code = 2
                os._exit(code)
        os.close(incoming)
        os.close(acknowledge)
        self.outgoing, self.acknowledged = outgoing, acknowledged

    def pulse(self):
        try:
            os.write(self.outgoing, b'.')
            if not select.select([self.acknowledged], [], [], 2)[0]:
                raise RuntimeError('bootstrap watchdog stopped acknowledging the monitor')
            if os.read(self.acknowledged, 1) != b'.':
                raise RuntimeError('bootstrap watchdog exited')
        except OSError as error:
            raise RuntimeError('bootstrap watchdog pipe failed') from error

    def close(self):
        os.close(self.outgoing)
        os.close(self.acknowledged)
        deadline = time.monotonic() + 5
        while True:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                if status:
                    raise RuntimeError('bootstrap watchdog could not stop owned work')
                return
            if time.monotonic() >= deadline:
                os.kill(self.pid, signal.SIGKILL)
                os.waitpid(self.pid, 0)
                raise RuntimeError('bootstrap watchdog cleanup timed out')
            time.sleep(.01)


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


def quota_filesystem(data, image):
    """Verify the owned loop filesystem; never infer a quota from free bytes."""
    for path, directory in ((image.parent, True), (data, True), (image, False)):
        metadata = os.lstat(path)
        correct_type = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
        if not correct_type or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise RuntimeError('quota path is not a root-owned protected ' + ('directory: ' if directory else 'file: ') + str(path))
        if not directory and (metadata.st_size != BUILD_BYTES or metadata.st_nlink != 1):
            raise RuntimeError('quota backing image size or link count changed')
    if not os.path.ismount(data):
        raise RuntimeError('quota filesystem disappeared')
    device = os.stat(data).st_dev
    if device == os.stat(image).st_dev:
        raise RuntimeError('quota filesystem shares its backing device')
    backing = Path('/sys/dev/block') / f'{os.major(device)}:{os.minor(device)}' / 'loop/backing_file'
    if backing.read_text().rstrip('\n') != str(image):
        raise RuntimeError('quota loop device does not use the owned backing image')
    fs = os.statvfs(data)
    if fs.f_frsize <= 0 or fs.f_blocks <= 0 or fs.f_blocks * fs.f_frsize > BUILD_BYTES:
        raise RuntimeError('build filesystem exceeds quota or has invalid geometry')
    available = fs.f_bavail * fs.f_frsize
    if available < 64 * 1024**2:
        raise RuntimeError('build filesystem reserve exhausted')
    return {'device': device, 'capacity_bytes': fs.f_blocks * fs.f_frsize, 'free_bytes': available}


def process_identity(pid, require_root=True):
    if type(pid) is not int or pid < 2:
        raise RuntimeError('invalid bootstrap monitor PID')
    directory = Path('/proc') / str(pid)
    fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
    identities = [line.split()[1:] for line in (directory / 'status').read_text().splitlines()
                  if line.startswith('Uid:')]
    if (require_root and identities != [['0', '0', '0', '0']]) or fields[0] in ('Z', 'X', 'x'):
        raise RuntimeError('bootstrap monitoring process is dead or not root-owned')
    return {'pid': pid, 'parent': int(fields[1]), 'started': int(fields[19])}


def monitor_health():
    """Reject stale proof, dead processes, PID reuse, or a different guardian."""
    path = CONTROL / 'health.json'
    metadata = os.lstat(path)
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
            or metadata.st_mode & 0o022 or metadata.st_nlink != 1 or metadata.st_size > 4096):
        raise RuntimeError('bootstrap health record is not protected')
    proof = json.loads(path.read_text())
    if not isinstance(proof, dict):
        raise RuntimeError('invalid bootstrap health record')
    stamp = proof.get('monotonic')
    if type(stamp) is not float or not math.isfinite(stamp):
        raise RuntimeError('invalid bootstrap health timestamp')
    age = time.monotonic() - stamp
    if type(proof.get('protocol')) is not int or proof['protocol'] != 1 or not 0 <= age <= 5:
        raise RuntimeError('bootstrap health record is stale or unsupported')
    for role in ('monitor', 'watchdog'):
        identity = proof.get(role)
        if (not isinstance(identity, dict) or set(identity) != {'pid', 'parent', 'started'}
                or any(type(value) is not int for value in identity.values())
                or identity['pid'] < 2 or identity['parent'] < 0 or identity['started'] < 1):
            raise RuntimeError('invalid bootstrap process identity')
        if process_identity(identity['pid']) != identity:
            raise RuntimeError('bootstrap monitoring process identity changed')
    if proof['watchdog']['parent'] != proof['monitor']['pid']:
        raise RuntimeError('bootstrap watchdog does not belong to this monitor')
    return proof


def cgroup_limits():
    quota, period = (CGROUP / 'cpu.max').read_text().split()
    if quota == 'max' or not 0 < int(quota) <= 2 * int(period) or int(period) <= 0:
        raise RuntimeError('CPU enforcement missing')
    if (CGROUP / 'memory.max').read_text().strip() != str(MEMORY_BYTES):
        raise RuntimeError('memory enforcement changed')
    if (CGROUP / 'memory.swap.max').read_text().strip() != '0':
        raise RuntimeError('swap enforcement changed')
    processes = (CGROUP / 'pids.max').read_text().strip()
    if processes == 'max' or not 0 < int(processes) <= 2048:
        raise RuntimeError('process-count enforcement missing')
    if not (CGROUP / 'cgroup.kill').is_file():
        raise RuntimeError('owned process-tree cancellation unavailable')


def quota_admission(info, worker_pid):
    """Collect a verified boundary; callers must recheck it while work runs.

    Not yet used to relax either runner's ordinary free-space floor.
    """
    if platform.system() != 'Linux':
        raise RuntimeError('bootstrap quota admission requires native Linux')
    if (info.get('DockerRootDir') != str(DATA / 'docker') or info.get('Driver') != 'overlay2'
            or info.get('CgroupDriver') != 'cgroupfs' or info.get('CgroupVersion') != '2'):
        raise RuntimeError('daemon is outside the private bootstrap boundary')
    quota = quota_filesystem(DATA, CONTROL / 'storage.ext4')
    health = monitor_health()
    cgroup_limits()
    free = min(shutil.disk_usage(ROOT).free, shutil.disk_usage(CONTROL).free)
    if free < FREE_BYTES:
        raise RuntimeError('physical backing free space below 50 GiB')
    pidfile = DATA / 'dockerd.pid'
    metadata = os.lstat(pidfile)
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0
            or metadata.st_mode & 0o022 or metadata.st_nlink != 1 or not 0 < metadata.st_size <= 32):
        raise RuntimeError('private daemon PID file is not protected')
    daemon = process_identity(int(pidfile.read_text().strip()))
    worker = process_identity(worker_pid, require_root=False)
    for identity in (daemon, worker):
        groups = (Path('/proc') / str(identity['pid']) / 'cgroup').read_text().splitlines()
        if len(groups) != 1 or not groups[0].startswith('0::'):
            raise RuntimeError('expected unified process cgroup membership')
        membership = groups[0][3:]
        if membership != '/' + SLICE and not membership.startswith('/' + SLICE + '/'):
            raise RuntimeError('daemon or worker escaped the owned cgroup')
    return {'capacity_bytes': quota['capacity_bytes'], 'device': quota['device'],
            'monitor': health['monitor'], 'watchdog': health['watchdog'],
            'daemon': daemon, 'worker': worker, 'backing_free_bytes': free}


class Provider:
    def __init__(self, uid, gid):
        self.uid, self.gid = uid, gid
        self.started = time.monotonic()
        self.mounted = False
        self.slice_owned = False
        self.unit_owned = False
        self.control_owned = False
        self.watchdog = None
        self.minimum_free = shutil.disk_usage(ROOT).free
        self.peak_logs = 0
        self.unit_file = Path('/run/systemd/system') / SLICE
        self.receipt = ROOT / '.test-results/bootstrap.json'
        self.docker = [shutil.which('docker'), '--host', 'unix://' + str(CONTROL / 'docker.sock'),
                       '--config', str(DATA / 'client')]

    def guard(self):
        if self.watchdog is not None:
            self.watchdog.pulse()
        free = min(shutil.disk_usage(ROOT).free, shutil.disk_usage(CONTROL).free)
        self.minimum_free = min(self.minimum_free, free)
        if free < FREE_BYTES:
            raise RuntimeError('host/Docker backing free space below 50 GiB')
        if time.monotonic() - self.started >= DEADLINE_SECONDS:
            raise RuntimeError('bootstrap and test deadline exceeded')
        image = CONTROL / 'storage.ext4'
        if image.exists() and image.stat().st_size != BUILD_BYTES:
            raise RuntimeError('bootstrap image size changed')
        control_bytes = 0
        if CONTROL.exists():
            for path in CONTROL.iterdir():
                if path.name in ('data', 'storage.ext4'):
                    continue
                if path.is_dir():
                    control_bytes += allocated(path)
                elif path.is_file():
                    control_bytes += max(path.stat().st_size, path.stat().st_blocks * 512)
        if control_bytes > 64 * 1024**2:
            raise RuntimeError('bootstrap control/output reserve exhausted')
        if self.slice_owned:
            cgroup_limits()
        if self.mounted:
            quota_filesystem(DATA, CONTROL / 'storage.ext4')
        logs = allocated(ROOT / '.test-results')
        for path in (CONTROL / 'daemon.log', CONTROL / 'command.log'):
            if path.exists():
                size = path.stat().st_size
                if size > 16 * 1024**2:
                    raise RuntimeError('bootstrap log exceeded 16 MiB')
                logs += 2 * size  # Reserve the receipt copy before exporting it.
        for path in (DATA / 'docker/containers').glob('*/*-json.log'):
            logs += path.stat().st_size
        self.peak_logs = max(self.peak_logs, logs)
        # Reserve space for the ordinary worker's 16 MiB live log/evidence tmpfs.
        if logs > LOG_BYTES - 20 * 1024**2:
            raise RuntimeError('aggregate log reserve exhausted')
        if self.mounted and self.watchdog is not None:
            # Publish only after every resource check and watchdog acknowledgement.
            # Readers must still verify quota identity and physical backing space.
            proof = {'protocol': 1, 'monotonic': time.monotonic(),
                     'monitor': process_identity(os.getpid()),
                     'watchdog': process_identity(self.watchdog.pid)}
            temporary = CONTROL / 'health.pending'
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(descriptor, 'w') as output:
                output.write(json.dumps(proof) + '\n')
            os.replace(temporary, CONTROL / 'health.json')

    def command(self, command, user=False):
        self.guard()
        invocation = ['systemd-run', '--quiet', '--wait', '--pipe', '--collect',
                      '--unit', COMMAND, '--slice', SLICE,
                      '--property=KillMode=control-group', '--property=TimeoutStopSec=5',
                      '--property=RuntimeMaxSec=1800', '--working-directory', str(ROOT)]
        if user:
            invocation += ['--uid', str(self.uid), '--gid', str(self.gid)]
        temporary = DATA / 'tmp' if self.mounted else CONTROL / 'tmp'
        environment = {'PATH': os.environ['PATH'], 'HOME': str(DATA / 'client'),
                       'TMPDIR': str(temporary), 'DOCKER_TMPDIR': str(temporary),
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
        (CONTROL / 'tmp').mkdir(mode=0o700)
        with self.unit_file.open('x') as unit:
            self.unit_owned = True
            unit.write('[Unit]\nDescription=Owned git-locks CI resources\n'
                       '[Slice]\nCPUQuota=200%\nCPUQuotaPeriodSec=100ms\n'
                       'MemoryMax=4G\nMemorySwapMax=0\nTasksMax=2048\n')
        run(['systemctl', 'daemon-reload'])
        # Activation can create a cgroup even if systemctl later reports an
        # error. From this point cleanup owns that newly declared slice.
        self.slice_owned = True
        run(['systemctl', 'start', SLICE])
        self.guard()
        (CONTROL / 'launch.json').write_text(json.dumps({
            'phase': 'before filesystem formatting',
            'control': str(CONTROL), 'filesystem_image': str(CONTROL / 'storage.ext4'),
            'quota_mount': str(DATA), 'daemon_config': daemon_config(),
            'slice': str(CGROUP), 'memory_bytes': MEMORY_BYTES, 'cpus': 2,
            'build_filesystem_bytes': BUILD_BYTES, 'control_bytes_limit': 64 * 1024**2,
            'runtime_bytes_limit': 4 * 1024**3, 'logs_bytes_limit': LOG_BYTES,
            'timeout_seconds': DEADLINE_SECONDS, 'backing_free_bytes': self.minimum_free,
            'cancellation': 'independent pipe watchdog, then cgroup.kill for all owned descendants',
            'status': 'prototype disabled; this contract is not execution evidence',
        }, indent=2) + '\n')
        self.watchdog = LifetimeGuard(self.kill_owned)
        self.guard()
        image = CONTROL / 'storage.ext4'
        with image.open('xb') as output:
            output.truncate(BUILD_BYTES)
        self.command(['mkfs.ext4', '-q', '-F', '-m', '0', str(image)])
        DATA.mkdir()
        try:
            self.command(['mount', '-o', 'loop,nosuid,nodev', str(image), str(DATA)])
        finally:
            # A mount can complete before a later command/monitor failure.
            self.mounted = os.path.ismount(DATA)
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
        if not self.control_owned:
            return  # Setup refused pre-existing resources; none belong to us.
        self.kill_owned()
        if self.slice_owned:
            for unit in (COMMAND, DAEMON, SLICE):
                subprocess.run(['systemctl', 'stop', unit], timeout=20, check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if CGROUP.exists() and 'populated 1' in (CGROUP / 'cgroup.events').read_text():
                raise RuntimeError('owned processes remain; preserving mounted recovery data')
        if self.watchdog is not None:
            self.watchdog.close()
            self.watchdog = None
        self.receipt.parent.mkdir(exist_ok=True)
        with self.receipt.open('x') as output:
            output.write(json.dumps({
            'build_filesystem_bytes': BUILD_BYTES, 'memory_bytes': MEMORY_BYTES,
            'cpus': 2, 'timeout_seconds': DEADLINE_SECONDS,
            'minimum_backing_free_bytes': self.minimum_free, 'peak_counted_log_bytes': self.peak_logs,
            'command': sys.argv[1:], 'status': getattr(self, 'status', 'incomplete'),
            }, indent=2) + '\n')
        os.chown(self.receipt, self.uid, self.gid)
        for name in ('daemon.log', 'command.log', 'launch.json'):
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
        if self.unit_owned:
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
