#!/usr/bin/env python3
"""Deleted accounting entries are harmless; unreadable entries fail closed."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import importlib.util
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('accounting_provider', ROOT / 'scripts/docker-ci.py')
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
checks = 0
for scope in ('receipt', 'control', 'daemon log', 'container log'):
    for fault in (FileNotFoundError, PermissionError, OSError):
        with tempfile.TemporaryDirectory(prefix='locks-accounting-') as scratch:
            root = Path(scratch)
            control = root / 'control'
            data = control / 'data'
            control.mkdir()
            paths = {'receipt': root / '.test-results/vanished',
                     'control': control / 'tmp/vanished',
                     'daemon log': control / 'daemon.log',
                     'container log': data / 'docker/containers/one/one-json.log'}
            target = paths[scope]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('gone between discovery and measurement')
            keep = root / '.test-results/keep'
            keep.parent.mkdir(exist_ok=True)
            keep.write_text('preserved evidence')
            original_stat, original_file = Path.stat, Path.is_file
            original_exists, original_dir = Path.exists, Path.is_dir
            observed = []
            def metadata(path, **kwargs):
                if path == target and kwargs.get('follow_symlinks', True):
                    observed.append(path)
                    raise fault('injected accounting race or unreadable entry')
                return original_stat(path, **kwargs)
            with patch.object(provider, 'ROOT', root), patch.object(provider, 'CONTROL', control), \
                 patch.object(provider, 'DATA', data), \
                 patch.object(provider.shutil, 'disk_usage', return_value=SimpleNamespace(free=70 << 30)):
                instance = provider.Provider(os.getuid(), os.getgid())
                with patch.object(Path, 'stat', metadata), \
                     patch.object(Path, 'is_file', lambda p: True if p == target else original_file(p)), \
                     patch.object(Path, 'exists', lambda p: True if p == target else original_exists(p)), \
                     patch.object(Path, 'is_dir', lambda p: False if p == target else original_dir(p)):
                    error = None
                    try:
                        instance.guard()
                    except OSError as caught:
                        error = caught
                assert observed, scope
                if fault is FileNotFoundError:
                    assert error is None, (scope, error)
                    assert instance.peak_logs >= keep.stat().st_size
                else:
                    assert type(error) is fault, (scope, error)
            checks += 1
            print(f'PASS accounting {scope}: {fault.__name__}', flush=True)
# Use tiny files with synthetic size metadata in this process only.
# The outer resource monitor sees actual bytes and retains its normal limits.
for kind in ('file symlinks', 'directory symlink', 'dangling symlink', 'owned files'):
    with tempfile.TemporaryDirectory(prefix='locks-accounting-links-') as scratch:
        root = Path(scratch)
        control = root / 'control'
        control.mkdir()
        outside = root / 'unrelated'
        outside.mkdir()
        sized_paths = set()
        for index in range(9):
            target = (control if kind == 'owned files' else outside) / str(index)
            target.write_bytes(b'x')
            sized_paths.add(target)
            if kind == 'file symlinks':
                (control / str(index)).symlink_to(target)
                sized_paths.add(control / str(index))
        if kind == 'directory symlink':
            (control / 'alias').symlink_to(outside, target_is_directory=True)
            sized_paths.update(control / 'alias' / str(i) for i in range(9))
        if kind == 'dangling symlink':
            (control / 'alias').symlink_to(root / 'absent')
        actual_stat = Path.stat
        def sized_stat(path, **kwargs):
            result = actual_stat(path, **kwargs)
            if path in sized_paths and kwargs.get('follow_symlinks', True):
                return SimpleNamespace(st_mode=result.st_mode, st_blocks=result.st_blocks,
                                       st_size=8 * 1024**2)
            return result
        with patch.object(Path, 'stat', sized_stat), \
             patch.object(provider, 'ROOT', root), patch.object(provider, 'CONTROL', control), \
             patch.object(provider, 'DATA', control / 'data'), \
             patch.object(provider.shutil, 'disk_usage', return_value=SimpleNamespace(free=70 << 30)):
            instance = provider.Provider(os.getuid(), os.getgid())
            error = None
            try:
                instance.guard()
            except RuntimeError as caught:
                error = caught
            if kind == 'owned files':
                assert error is not None and 'control/output reserve' in str(error)
            else:
                assert error is None, (kind, error)
        if kind != 'owned files':
            assert all((outside / str(i)).stat().st_size == 1 for i in range(9))
        checks += 1
        print('PASS control accounting: ' + kind, flush=True)
print(f'Bootstrap accounting: {checks} synthetic cases passed', flush=True)
