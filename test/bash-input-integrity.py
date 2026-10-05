#!/usr/bin/env python3
"""Reject corrupt cached Bash archives even when Python assertions are disabled."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import os
import sys
import tempfile

checks = 0
for optimized in (False, True):
    for kind in ('size', 'digest', 'symlink', 'directory'):
        with tempfile.TemporaryDirectory(prefix='locks-bash-input-') as scratch:
            base = Path(scratch)
            target = base / 'bash-4.3.tar.gz'
            # Both names exist, so the defective parent returns success without
            # network access when -O removes its integrity assertions.
            (base / 'bash-4.4.tar.gz').write_bytes(b'invalid second archive')
            if kind == 'directory':
                target.mkdir()
            elif kind == 'symlink':
                payload = base / 'unrelated'
                payload.write_bytes(b'preserve me')
                target.symlink_to(payload)
            else:
                with target.open('wb') as output:
                    output.truncate(7955839 if kind == 'digest' else 1)
            env = dict(os.environ)
            env.pop('PYTHONOPTIMIZE', None)
            command = [sys.executable, *(['-O'] if optimized else []),
                       str(ROOT / 'scripts/bash-compatibility.py'), 'fetch', '--sources', str(base)]
            result = subprocess.run(command, env=env, capture_output=True, timeout=10)
            assert result.returncode == 1, (optimized, kind, 'corrupt cache was accepted', result)
            detail = b'archive SHA-256 mismatch' if kind == 'digest' else b'invalid archive type or size'
            assert detail in result.stderr, (optimized, kind, result.stderr)
            assert not list(base.glob('download-*')), 'invalid cache triggered a download'
            assert (base / 'bash-4.4.tar.gz').read_bytes() == b'invalid second archive'
            if kind == 'symlink':
                assert payload.read_bytes() == b'preserve me' and target.is_symlink()
            checks += 1
            print(f'PASS cached archive refusal: optimized={optimized}, kind={kind}', flush=True)
print(f'Bash input integrity: {checks} cases passed', flush=True)
