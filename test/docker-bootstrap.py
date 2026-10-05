#!/usr/bin/env python3
"""Missing/stale toolchains must not start unaccounted Docker work."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import hashlib
import importlib.util
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('docker_runner', ROOT / 'scripts/docker-run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class ReachedRuntime(Exception):
    pass


with tempfile.TemporaryDirectory(prefix='locks-bootstrap-') as scratch:
    root = Path(scratch)
    recipe = root / 'scripts/docker/Dockerfile'
    recipe.parent.mkdir(parents=True)
    recipe.write_text('FROM existing-test-input\n')
    fingerprint = hashlib.sha256(recipe.read_bytes()).hexdigest()
    for label, create in ((None, False), ('old-recipe', False), (fingerprint, False), (fingerprint, True)):
        calls = []

        def inspect(kind, name):
            calls.append(('inspect', kind, name))
            if kind == 'container':
                if create:
                    return None
                raise ReachedRuntime
            if label is None:
                return None
            return {'Id': 'sha256:verified', 'Config': {'Labels': {runner.OWNER: label}}}

        def unexpected(*command, **kwargs):
            if create:
                assert command[:4] == ('docker', 'create', '--pull', 'never'), command
                assert command[-1] == 'sha256:verified', command
                calls.append(('create',))
                raise ReachedRuntime
            raise AssertionError(('unaccounted Docker command', command))

        # This is an orchestration fault test, not a resource measurement. The
        # real guarded worker enforces the test's limits; no Docker socket or
        # host mount is present. Stop at runtime inspection on the reuse path.
        with patch.object(runner, 'ROOT', root), patch.object(runner, 'inspect', inspect), \
             patch.object(runner, 'run', unexpected), patch.object(runner, 'source_archive', lambda: b''), \
             patch.object(runner.shutil, 'disk_usage', return_value=SimpleNamespace(free=70 << 30)):
            try:
                runner.main()
            except RuntimeError as error:
                assert label != fingerprint and 'refusing unguarded Docker bootstrap' in str(error), error
            except ReachedRuntime:
                assert label == fingerprint
            else:
                raise AssertionError('bootstrap boundary did not stop the fixture')
        assert calls[0] == ('inspect', 'image', runner.IMAGE)
        assert len(calls) == (3 if create else 2 if label == fingerprint else 1), calls
        print(f'PASS bootstrap boundary: {label or "missing"}; create={create}', flush=True)
