#!/usr/bin/env python3
"""Check cleanup ownership and evidence retention with synthetic mount operations."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import importlib.util
import os
import tempfile
import json
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cleanup_provider', ROOT / 'scripts/docker-ci.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
cases = ('nested mounts', 'remaining child mount', 'remaining root mount', 'unreadable mount table', 'malformed mount table', 'receipt collision', 'log collision', 'copy failure', 'success', 'unmount failure')
for fault in cases:
    with tempfile.TemporaryDirectory(prefix='locks-bootstrap-cleanup-') as scratch:
        root = Path(scratch)
        control = root / 'control'
        data = control / 'data'
        data.mkdir(parents=True)
        (control / 'daemon.log').write_text('unique daemon evidence')
        unit = root / 'owned.slice'
        unit.write_text('owned unit')
        cgroup = root / 'cgroup'
        cgroup.mkdir()
        (cgroup / 'cgroup.kill').touch()
        (cgroup / 'cgroup.events').write_text('populated 0\n')
        receipts = root / '.test-results'
        receipts.mkdir()
        if fault == 'receipt collision':
            (receipts / 'bootstrap.json').write_text('prior receipt')
        if fault == 'log collision':
            (receipts / 'bootstrap-daemon.log').write_text('prior log')
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            if command[0] in ('umount', 'systemctl') and command[1] != 'stop':
                assert kwargs['timeout'] == 30 and kwargs['check'] is True, kwargs
            if command[0] == 'umount' and (fault == 'unmount failure' or
                    (fault == 'nested mounts' and '--recursive' not in command)):
                raise subprocess.CalledProcessError(32, command)
            return SimpleNamespace(returncode=0)
        real_read = Path.read_bytes
        def mount_table(path):
            if path != Path('/proc/self/mountinfo'):
                return real_read(path)
            if fault == 'unreadable mount table':
                raise OSError('injected unreadable mount table')
            if fault == 'malformed mount table':
                return b'invalid mount record\n'
            target = str(data / 'child') if fault == 'remaining child mount' else str(data)
            if fault in ('remaining child mount', 'remaining root mount'):
                return ('20 1 0:2 / ' + target + ' rw - tmpfs tmpfs rw\n').encode()
            return b'1 0 0:1 / / rw - rootfs rootfs rw\n'
        real_copy = provider.shutil.copyfile
        def copy(source, target):
            if fault == 'copy failure':
                raise OSError('injected evidence export failure')
            return real_copy(source, target)
        with patch.object(provider, 'ROOT', root), patch.object(provider, 'CONTROL', control), \
             patch.object(provider, 'DATA', data), patch.object(provider, 'CGROUP', cgroup), \
             patch.object(provider.subprocess, 'run', side_effect=run), \
             patch.object(provider.shutil, 'copyfile', side_effect=copy), \
             patch.object(Path, 'read_bytes', mount_table):
            instance = provider.Provider(os.getuid(), os.getgid())
            instance.control_owned = instance.unit_owned = instance.slice_owned = instance.mounted = True
            instance.unit_file = unit
            error = None
            try:
                instance.cleanup()
            except (OSError, RuntimeError, subprocess.CalledProcessError) as caught:
                error = caught
            assert (error is None) == (fault in ('success', 'nested mounts')), (fault, error)
        assert (cgroup / 'cgroup.kill').read_text() == '1\n'
        assert ['umount', '--recursive', '--', str(data)] in calls, (fault, calls)
        if fault in ('unmount failure', 'remaining child mount', 'remaining root mount', 'unreadable mount table', 'malformed mount table'):
            assert instance.mounted and unit.exists() and control.exists()
            assert ['systemctl', 'daemon-reload'] not in calls
        else:
            assert not instance.mounted and not unit.exists()
            assert ['systemctl', 'daemon-reload'] in calls
        if fault not in ('success', 'nested mounts'):
            assert (control / 'daemon.log').read_text() == 'unique daemon evidence'
        else:
            assert not control.exists()
        if fault == 'receipt collision':
            assert (receipts / 'bootstrap.json').read_text() == 'prior receipt'
        if fault == 'log collision':
            assert (receipts / 'bootstrap-daemon.log').read_text() == 'prior log'
        print('PASS bootstrap cleanup: ' + fault, flush=True)
print(f'Bootstrap cleanup: {len(cases)} synthetic cases passed', flush=True)

# Exercise the verifier against this unprivileged worker's actual mount table.
with tempfile.TemporaryDirectory(prefix='locks-unmounted-') as scratch:
    provider.verify_unmounted(Path(scratch))
try:
    provider.verify_unmounted(Path('/tmp'))
except RuntimeError as error:
    assert 'owned mounts remain' in str(error)
else:
    raise AssertionError('the worker tmpfs mount was not detected')
print('PASS live mount table: mounted tmpfs and unmounted directory distinguished', flush=True)
# Kernel octal escaping and a lexical sibling must not defeat the boundary.
for directory, encoded, mounted in [('/owned space', b'/owned\\040space', True),
                                    ('/owned', b'/owned-other', False)]:
    row = b'20 1 0:2 / ' + encoded + b' rw - tmpfs tmpfs rw\n'
    with patch.object(Path, 'read_bytes', return_value=row):
        try:
            provider.verify_unmounted(Path(directory))
        except RuntimeError:
            assert mounted
        else:
            assert not mounted
print('PASS mount table escaping and subtree boundary', flush=True)

# Stop failures must not skip other units, watchdog shutdown or evidence export.
# Mount and systemd operations remain synthetic; data is tiny local fixtures.
unit_cases = ('timeout empty', 'timeout populated', 'timeout unreadable', 'timeout malformed', 'nonzero empty', 'collected command', 'collected daemon', 'not-found active', 'not-found job', 'show failure', 'show timeout', 'show malformed', 'show duplicate')
for fault in unit_cases:
    with tempfile.TemporaryDirectory(prefix='locks-unit-stop-') as scratch:
        root = Path(scratch)
        control = root / 'control'
        data = control / 'data'
        data.mkdir(parents=True)
        (control / 'daemon.log').write_text('preserve this evidence')
        cgroup = root / 'cgroup'
        cgroup.mkdir()
        (cgroup / 'cgroup.kill').touch()
        if fault != 'timeout unreadable':
            (cgroup / 'cgroup.events').write_text('populated ' + ('1' if fault == 'timeout populated' else 'invalid' if fault == 'timeout malformed' else '0') + '\n')
        unit = root / 'owned.slice'
        unit.touch()
        calls = []
        closed = []
        def command(args, **kwargs):
            calls.append(args)
            if args[:2] == ['systemctl', 'show']:
                assert kwargs['timeout'] == 5 and kwargs['check'] is False
                if fault == 'show timeout':
                    raise subprocess.TimeoutExpired(args, 5)
                body = 'LoadState=not-found\nActiveState=inactive\nJob=\n'
                if fault == 'not-found active': body = body.replace('inactive', 'active')
                if fault == 'not-found job': body = body.replace('Job=\n', 'Job=123\n')
                if fault == 'show malformed': body = 'LoadState=not-found\n'
                if fault == 'show duplicate': body += 'LoadState=not-found\n'
                if fault == 'nonzero empty': body = body.replace('not-found', 'loaded')
                return SimpleNamespace(returncode=1 if fault == 'show failure' else 0, stdout=body)
            failed_unit = provider.DAEMON if fault == 'collected daemon' else provider.COMMAND
            if args == ['systemctl', 'stop', failed_unit]:
                if fault.startswith('timeout'):
                    raise subprocess.TimeoutExpired(args, 20)
                return SimpleNamespace(returncode=1)
            return SimpleNamespace(returncode=0)
        with patch.object(provider, 'ROOT', root), patch.object(provider, 'CONTROL', control), \
             patch.object(provider, 'DATA', data), patch.object(provider, 'CGROUP', cgroup), \
             patch.object(provider.subprocess, 'run', side_effect=command):
            instance = provider.Provider(os.getuid(), os.getgid())
            instance.control_owned = instance.unit_owned = instance.slice_owned = instance.mounted = True
            instance.unit_file = unit
            instance.watchdog = SimpleNamespace(close=lambda: closed.append(True))
            instance.status = 'passed'
            collected = fault.startswith('collected')
            try:
                instance.cleanup()
            except (RuntimeError, subprocess.SubprocessError):
                assert not collected, 'a proven collected unit caused cleanup failure'
            else:
                assert collected, 'unit stop failure was reported as success'
        assert all(['systemctl', 'stop', name] in calls for name in (provider.COMMAND, provider.DAEMON, provider.SLICE)), calls
        assert closed == [True], 'watchdog cleanup was skipped'
        receipt = json.loads((root / '.test-results/bootstrap.json').read_text())
        assert receipt['status'] == ('passed' if collected else 'cleanup-failed'), receipt
        assert bool(receipt['cleanup_errors']) != collected, receipt
        expected_collected = [provider.DAEMON if fault == 'collected daemon' else provider.COMMAND] if collected else []
        assert receipt['collected_units'] == expected_collected, receipt
        assert (root / '.test-results/bootstrap-daemon.log').read_text() == 'preserve this evidence'
        safe = fault not in ('timeout populated', 'timeout unreadable', 'timeout malformed')
        assert (['umount', '--recursive', '--', str(data)] in calls) == safe, calls
        assert instance.mounted != safe and unit.exists() != safe
        assert control.exists() != safe, 'uncertain mounted data must survive'
        print('PASS unit stop recovery: ' + fault, flush=True)
print(f'Bootstrap unit stop recovery: {len(unit_cases)} synthetic cases passed')
