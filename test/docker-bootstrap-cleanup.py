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
cases = ('receipt collision', 'log collision', 'copy failure', 'success', 'unmount failure')
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
            if command[0] == 'umount' and fault == 'unmount failure':
                raise subprocess.CalledProcessError(32, command)
        real_copy = provider.shutil.copyfile
        def copy(source, target):
            if fault == 'copy failure':
                raise OSError('injected evidence export failure')
            return real_copy(source, target)
        with patch.object(provider, 'ROOT', root), patch.object(provider, 'CONTROL', control), \
             patch.object(provider, 'DATA', data), patch.object(provider, 'CGROUP', cgroup), \
             patch.object(provider, 'run', side_effect=run), \
             patch.object(provider.subprocess, 'run', side_effect=run), \
             patch.object(provider.shutil, 'copyfile', side_effect=copy):
            instance = provider.Provider(os.getuid(), os.getgid())
            instance.control_owned = instance.unit_owned = instance.slice_owned = instance.mounted = True
            instance.unit_file = unit
            error = None
            try:
                instance.cleanup()
            except (OSError, RuntimeError, subprocess.CalledProcessError) as caught:
                error = caught
            assert (error is None) == (fault == 'success'), (fault, error)
        assert (cgroup / 'cgroup.kill').read_text() == '1\n'
        assert ['umount', str(data)] in calls, (fault, calls)
        if fault == 'unmount failure':
            assert instance.mounted and unit.exists() and control.exists()
            assert ['systemctl', 'daemon-reload'] not in calls
        else:
            assert not instance.mounted and not unit.exists()
            assert ['systemctl', 'daemon-reload'] in calls
        if fault != 'success':
            assert (control / 'daemon.log').read_text() == 'unique daemon evidence'
        else:
            assert not control.exists()
        if fault == 'receipt collision':
            assert (receipts / 'bootstrap.json').read_text() == 'prior receipt'
        if fault == 'log collision':
            assert (receipts / 'bootstrap-daemon.log').read_text() == 'prior log'
        print('PASS bootstrap cleanup: ' + fault, flush=True)
print(f'Bootstrap cleanup: {len(cases)} synthetic cases passed', flush=True)
