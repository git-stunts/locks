#!/usr/bin/env python3
"""Exercise raw-entry refusals and the copied Git/runtime boundary inside Docker."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(["node", str(ROOT / "scripts/require-docker.mjs")], check=True)

import os
import shutil
import tempfile

assert ROOT == Path('/work/source')
assert subprocess.check_output(['git', 'remote'], cwd=ROOT) == b''
assert not (ROOT / '.git/objects/info/alternates').exists()
assert not (ROOT / '.git/commondir').exists()
assert subprocess.check_output(['git', 'rev-parse', '--absolute-git-dir'], cwd=ROOT).strip() == b'/work/source/.git'
assert sorted(p.name for p in Path('/sys/class/net').iterdir()) == ['lo']
assert not Path('/var/run/docker.sock').exists()
assert os.getuid() != 0
assert os.environ['TMPDIR'] == '/tmp'
for mount, limit in (('/work', 512), ('/tmp', 512), ('/home/node', 32), ('/evidence', 16)):
    fs = os.statvfs(mount)
    assert fs.f_blocks * fs.f_frsize <= limit * 1024**2, (mount, fs)
assert (ROOT.parent / 'artifacts').resolve() == Path('/evidence/artifacts')

# Moving the scripts outside the approved copied tree represents a raw entry.
# Environment-only bypasses must not admit even an otherwise real container.
with tempfile.TemporaryDirectory(prefix='git-locks-guard-') as tmp:
    candidate = Path(tmp)
    for directory in ('scripts', 'test', 'examples'):
        shutil.copytree(ROOT / directory, candidate / directory)
    entries = [('bash', p.relative_to(ROOT)) for p in (ROOT / 'test').rglob('*.sh')]
    entries += [('python3', p.relative_to(ROOT)) for p in (ROOT / 'test').rglob('*.py') if p.name != 'docker-boundary.py']
    entries += [('bash', Path(p)) for p in ('scripts/benchmark-directory-tokens.sh', 'examples/cooperating-workers/demo.sh', 'examples/cooperating-workers/worker.sh')]
    entries.append(('python3', Path('scripts/docker-exec.py')))
    for interpreter, entry in entries:
        if entry == Path('test/observation/git-shim.sh'):
            continue  # copied shim is guarded through its fixed container source path
        env = dict(os.environ, GIT_STUNTS_DOCKER='1', GITHUB_ACTIONS='true')
        result = subprocess.run([interpreter, str(candidate / entry)], cwd=candidate, env=env, text=True, capture_output=True, timeout=10)
        assert result.returncode != 0, (entry, result.stdout, result.stderr)
        assert 'HOST EXECUTION PROHIBITED' in result.stderr, (entry, result.stderr)
    assert not list(candidate.rglob('store.git'))
print(f'Docker boundary: isolated Git, offline unprivileged runtime, and {len(entries) - 1} raw-entry refusals passed')
