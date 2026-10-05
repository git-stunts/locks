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
export_faults = ('missing test log', 'missing resource receipt', 'artifact export failure', 'early child refusal')
emergency_faults = ('missing runner PID', 'invalid runner PID', 'failed TERM', 'TERM timeout', 'failed worker stop', 'stuck Docker client')
for fault in ('changed identity', 'expired health', 'unreadable kernel state', 'final health expired', 'initial publication failure', 'refresh publication failure', 'successful refresh', *emergency_faults, *export_faults):
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
            if fault in export_faults or len(snapshots) <= 2 or fault in ('initial publication failure', 'refresh publication failure', 'successful refresh'):
                return copy.deepcopy(initial)
            if fault in ('expired health', 'final health expired'):
                raise RuntimeError('health expired')
            if fault == 'unreadable kernel state':
                raise OSError('kernel state unreadable')
            changed = copy.deepcopy(initial)
            changed['watchdog']['started'] += 1
            return changed
        calls = []
        publications = []
        launches = []
        class Process:
            returncode = 1 if fault == 'early child refusal' else (0 if fault == 'final health expired' or fault in export_faults else None)
            def poll(self): return self.returncode
            def wait(self, timeout=None):
                if fault == 'successful refresh' and self.returncode is None:
                    self.returncode = 0
                if fault in ('TERM timeout', 'stuck Docker client') and self.returncode is None:
                    raise subprocess.TimeoutExpired('docker exec', timeout)
                assert self.returncode is not None, 'wait before cancellation'
                return self.returncode
            def kill(self):
                assert ('docker', 'stop', '--time', '5', runner.WORKER) in calls
                assert fault == 'stuck Docker client'
                self.returncode = -9
        process = Process()
        def run(*command, **kwargs):
            calls.append(command)
            if ((fault == 'early child refusal' and command[-1] in ('/evidence/test.log', '/evidence/resources.json')) or
                    (fault == 'missing test log' and command[-1] == '/evidence/test.log') or
                    (fault == 'missing resource receipt' and command[-1] == '/evidence/resources.json')):
                raise subprocess.CalledProcessError(1, command)
            if command[:4] == ('docker', 'exec', '--user', '0:0'):
                assert command[4:8] == (runner.WORKER, '/usr/bin/python3', '-I', '-c')
                assert command[8] == (ROOT / 'scripts/docker-admission.py').read_text()
                assert command[9] == 'publish' and kwargs['timeout'] == 5
                assert len(snapshots) == len(publications) + 2
                publications.append(command[10:12])
                if fault == 'initial publication failure' or (fault == 'refresh publication failure' and len(publications) > 1):
                    raise subprocess.CalledProcessError(1, command[:8])
            if command[:5] == ('docker', 'exec', runner.WORKER, 'kill', '-TERM'):
                if fault == 'failed TERM':
                    raise subprocess.CalledProcessError(1, command)
                if fault not in ('TERM timeout', 'stuck Docker client'):
                    process.returncode = 143
            if command[:2] == ('docker', 'stop'):
                if fault == 'failed worker stop':
                    raise subprocess.CalledProcessError(1, command)
                if fault != 'stuck Docker client':
                    process.returncode = 137
            if kwargs.get('stdout') is not None and hasattr(kwargs['stdout'], 'write'):
                kwargs['stdout'].write(b'{}\n')
            return SimpleNamespace(returncode=0)
        def output(command, **kwargs):
            if 'df' in command: return 'Filesystem blocks used available percent mount\nroot 1 0 131072 0% /\n'
            if command[1] == 'info': return '{"private": true}'
            if command[-1] == '/evidence/runner.pid':
                if fault in ('missing runner PID', 'failed worker stop'):
                    raise subprocess.CalledProcessError(1, command)
                if fault == 'invalid runner PID': return '1\n'
                return '100\n'
            raise AssertionError(command)
        def launch(command):
            at = command.index('--verified-bootstrap-quota')
            assert fault != 'initial publication failure'
            assert command[at+1] == str(19 << 30) and command[at+3] == '--'
            assert publications == [(command[at+2], str(19 << 30))]
            launches.append(command)
            return process
        exports = []
        def export(path):
            exports.append(path)
            if fault == 'artifact export failure':
                raise RuntimeError('injected artifact export failure')
        with patch.object(runner, 'ROOT', root), patch.object(runner, 'source_archive', return_value=b''), \
             patch.object(runner, 'inspect', inspect), patch.object(runner, 'run', run), \
             patch.object(runner, 'export_artifacts', export), \
             patch.object(runner, 'load_bootstrap', return_value=SimpleNamespace(quota_admission=admission)), \
             patch.object(runner.shutil, 'disk_usage', return_value=SimpleNamespace(free=70 << 30)), \
             patch.object(runner.subprocess, 'check_output', side_effect=output), \
             patch.object(runner.subprocess, 'Popen', side_effect=launch):
            if fault == 'failed worker stop':
                try:
                    runner.main()
                except (RuntimeError, subprocess.CalledProcessError):
                    pass
                else:
                    raise AssertionError('failed worker stop must not report success')
            else:
                assert runner.main() == (0 if fault == 'successful refresh' else 2)
        result = json.loads((root / '.test-results/result.json').read_text())
        if fault in export_faults:
            assert result['exit_code'] == 2 and result['workload_exit_code'] == (1 if fault == 'early child refusal' else 0), result
            assert result['evidence_errors'] and not result['host_guard'], result
            if fault == 'early child refusal':
                assert set(result['evidence_errors']) == {'latest.log', 'resources.json'}, result
                assert not (root / '.test-results/latest.log').exists()
                assert not (root / '.test-results/resources.json').exists()
            assert len(exports) == 1, 'one failed file export skipped retained artifacts'
            for name in ('test.log', 'resources.json'):
                assert ('docker', 'exec', runner.WORKER, 'cat', '/evidence/' + name) in calls
            assert ('docker', 'stop', '--time', '5', runner.WORKER) in calls
            checks += 1
            print('PASS host evidence: ' + fault, flush=True)
            continue
        if fault in ('initial publication failure', 'successful refresh'):
            if fault == 'initial publication failure':
                assert not launches and result['state'] == 'admission-publication-failed'
                assert result['host_guard'] and result['host_guard_detail'] and len(publications) == 1
            else:
                assert len(launches) == 1 and len(publications) == 2 and publications[0] == publications[1]
                assert not result['host_guard'] and result['exit_code'] == 0
            assert ('docker', 'stop', '--time', '5', runner.WORKER) in calls
            checks += 1
            print('PASS host proof: ' + fault, flush=True)
            continue
        assert result['host_guard'] and result['host_guard_detail']
        assert len(publications) == (2 if fault == 'refresh publication failure' else 1)
        assert len(snapshots) == 3
        if fault in ('final health expired', 'missing runner PID', 'invalid runner PID', 'failed worker stop'):
            assert not any('kill' in command for command in calls)
        else:
            assert ('docker', 'exec', runner.WORKER, 'kill', '-TERM', '100') in calls
        if fault in emergency_faults:
            assert result['exit_code'] == 2 and result['cancellation_error']
            assert result['evidence_unavailable']
            if fault == 'failed worker stop':
                assert result['worker_stop'] == 'failed' and result['stop_error']
                assert process.returncode is None
            else:
                assert result['worker_stop'] == 'confirmed'
                assert process.returncode is not None
            assert not (root / '.test-results/latest.log').exists()
            assert not (root / '.test-results/resources.json').exists()
        else:
            assert (root / '.test-results/latest.log').read_bytes() == b'{}\n'
            assert (root / '.test-results/resources.json').read_bytes() == b'{}\n'
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
    with patch.dict(globals_, quota_capacity=capacity, admission=SimpleNamespace(read=lambda run, size: size), generated_logs=lambda: 0), \
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
