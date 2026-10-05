#!/usr/bin/env python3
"""Fault-inject runner integration without a privileged Docker socket."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import copy
import hashlib
import importlib.util
import json
import runpy
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('docker_runner', ROOT / 'scripts/docker-run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
initial = {'capacity_bytes': 19 << 30, 'device': 7,
           'monitor': {'pid': 20, 'parent': 1, 'started': 30},
           'watchdog': {'pid': 21, 'parent': 20, 'started': 40},
           'daemon': {'pid': 22, 'parent': 1, 'started': 50},
           'worker': {'pid': 23, 'parent': 22, 'started': 60},
           'backing_free_bytes': 70 << 30}
checks = 0
for fault in ('changed identity', 'expired health', 'unreadable kernel state'):
    with tempfile.TemporaryDirectory(prefix='locks-quota-runner-') as scratch:
        root = Path(scratch)
        recipe = root / 'scripts/docker/Dockerfile'
        recipe.parent.mkdir(parents=True)
        recipe.write_text('FROM existing-toolchain\n')
        fingerprint = hashlib.sha256(recipe.read_bytes()).hexdigest()
        config = {'Binds': [], 'NetworkMode': 'none', 'ReadonlyRootfs': True,
                  'Privileged': False, 'Init': True, 'Memory': 2 << 30,
                  'NanoCpus': 2*10**9, 'PidsLimit': 256, 'ShmSize': 16 << 20,
                  'IpcMode': 'private', 'PidMode': '',
                  'Tmpfs': {name: 'bounded' for name in ('/work', '/tmp', '/home/node', '/evidence')}}
        worker = {'Config': {'Labels': {runner.OWNER: '1', runner.OWNER+'.profile': runner.PROFILE}},
                  'State': {'Running': False, 'Pid': 23}, 'Image': 'verified', 'HostConfig': config, 'Mounts': []}
        def inspect(kind, name):
            return ({'Id': 'verified', 'Config': {'Labels': {runner.OWNER: fingerprint}}}
                    if kind == 'image' else worker)
        snapshots = []
        def admission(info, pid):
            assert pid == 23 and info == {'private': True}
            snapshots.append(pid)
            if len(snapshots) == 1:
                return copy.deepcopy(initial)
            if fault == 'expired health':
                raise RuntimeError('health expired')
            if fault == 'unreadable kernel state':
                raise OSError('kernel state unreadable')
            changed = copy.deepcopy(initial)
            changed['watchdog']['started'] += 1
            return changed
        calls = []
        class Process:
            returncode = None
            def poll(self): return self.returncode
            def wait(self, timeout=None):
                assert self.returncode is not None, 'wait before cancellation'
                return self.returncode
        process = Process()
        def run(*command, **kwargs):
            calls.append(command)
            if command[:5] == ('docker', 'exec', runner.WORKER, 'kill', '-TERM'):
                process.returncode = 143
            if kwargs.get('stdout') is not None and hasattr(kwargs['stdout'], 'write'):
                kwargs['stdout'].write(b'{}\n')
            return SimpleNamespace(returncode=0)
        def output(command, **kwargs):
            if 'df' in command: return 'Filesystem blocks used available percent mount\nroot 1 0 131072 0% /\n'
            if command[1] == 'info': return '{"private": true}'
            if command[-1] == '/evidence/runner.pid': return '100\n'
            raise AssertionError(command)
        def launch(command):
            at = command.index('--verified-bootstrap-quota')
            assert command[at+1:at+3] == [str(19 << 30), '--']
            return process
        with patch.object(runner, 'ROOT', root), patch.object(runner, 'source_archive', return_value=b''), \
             patch.object(runner, 'inspect', inspect), patch.object(runner, 'run', run), \
             patch.object(runner, 'export_artifacts', lambda path: None), \
             patch.object(runner, 'load_bootstrap', return_value=SimpleNamespace(quota_admission=admission)), \
             patch.object(runner.shutil, 'disk_usage', return_value=SimpleNamespace(free=70 << 30)), \
             patch.object(runner.subprocess, 'check_output', side_effect=output), \
             patch.object(runner.subprocess, 'Popen', side_effect=launch):
            assert runner.main() == 2
        result = json.loads((root / '.test-results/result.json').read_text())
        assert result['host_guard'] and result['host_guard_detail']
        assert len(snapshots) == 2
        assert ('docker', 'exec', runner.WORKER, 'kill', '-TERM', '100') in calls
        assert ('docker', 'stop', '--time', '5', runner.WORKER) in calls
        checks += 1
        print('PASS running host guard cancels on ' + fault, flush=True)

inner = runpy.run_path(str(ROOT / 'scripts/docker-exec.py'))
measure = inner['measure']
globals_ = measure.__globals__
for label, capacity, root_bytes, free, allowed in [
    ('ordinary large backing', None, 100 << 30, 70 << 30, True),
    ('unverified small backing', None, 19 << 30, 128 << 20, False),
    ('admitted quota', 19 << 30, 19 << 30, 128 << 20, True),
    ('changed capacity', 19 << 30, 18 << 30, 128 << 20, False),
    ('oversized admission', 20 << 30, 20 << 30, 128 << 20, False),
    ('exhausted quota', 19 << 30, 19 << 30, 63 << 20, False),
]:
    def filesystem(path):
        total, remaining = (root_bytes, free) if path == '/' else (512 << 20, 256 << 20)
        return SimpleNamespace(f_frsize=4096, f_blocks=total//4096,
                               f_bavail=remaining//4096, f_bfree=remaining//4096)
    with patch.dict(globals_, quota_capacity=capacity, generated_logs=lambda: 0), \
         patch.object(globals_['os'], 'statvfs', side_effect=filesystem):
        try:
            measure()
        except RuntimeError:
            assert not allowed, label
        else:
            assert allowed, label
    checks += 1
    print('PASS inner capacity guard: ' + label, flush=True)
print(f'Quota runner integration: {checks} synthetic cases passed', flush=True)
