#!/usr/bin/env python3
"""Check cleanup ownership and evidence retention with synthetic mount operations."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import importlib.util
import os
import tempfile
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
            if command[0] == 'umount' and (fault == 'unmount failure' or
                    (fault == 'nested mounts' and '--recursive' not in command)):
                raise subprocess.CalledProcessError(32, command)
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
             patch.object(provider, 'run', side_effect=run), \
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
