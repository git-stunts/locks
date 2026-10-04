#!/usr/bin/env python3
"""Prove the study detects publication without the expected-root comparison."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import json
import tempfile
import time

output = Path('/work/artifacts') / f'root-cas-calibration-{time.time_ns()}'
with tempfile.TemporaryDirectory(prefix='locks-mutant-') as tmp:
    mutant = Path(tmp) / 'git-locks'
    source = (ROOT / 'bin/git-locks').read_text()
    original = '''printf 'update %s %s %s\\n' "${STATE_REF}" "${next}" "${STATE_OID}"'''
    replacement = '''printf 'update %s %s\\n' "${STATE_REF}" "${next}"'''
    assert source.count(original) == 1, 'mutation target must be unambiguous'
    mutant.write_text(source.replace(original, replacement))
    mutant.chmod(0o755)
    result = subprocess.run(['python3', str(ROOT / 'test/observation/study.py'),
                             '--binary', str(mutant), '--seeds', '38', '--output', str(output)],
                            text=True, capture_output=True, timeout=120)
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    report = json.loads((output / 'report.json').read_text())
    assert report['cases'] == 6 and report['violating_cases'] == 3, report
    bad = {row['domain']: row for row in report['results'] if row['violations']}
    assert set(bad) == {'family', 'semaphore', 'prefix'}, bad
    assert all(row['mask'] == 0 for row in bad.values()), bad
    (output / 'mutant').write_text(mutant.read_text())
    (output / 'study.stdout').write_text(result.stdout)
    (output / 'study.stderr').write_text(result.stderr)
print('root CAS calibration: removing the comparison fails stale family, semaphore, and prefix cases')
