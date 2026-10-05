#!/usr/bin/env python3
"""A malformed synopsis must fail the build without replacing the executable."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)
source = (ROOT / 'lib/000-prelude.sh').read_text()
case = "    list) printf 'usage: git locks list\\n' ;;"
fixtures = {
    'missing header marker': source.replace('# @GIT_LOCKS_SYNOPSES@', ''),
    'duplicate usage marker': source.replace('@GIT_LOCKS_USAGE@', '@GIT_LOCKS_USAGE@\n@GIT_LOCKS_USAGE@'),
    'duplicate command': source.replace(case, case + '\n' + case),
    'printf format directive': source.replace(case, case.replace('locks list', 'locks list %s')),
    'wrong command name': source.replace(case, case.replace('locks list', 'locks claim')),
    'nonliteral synopsis': source.replace(case, '    list) printf "$UNTRUSTED" ;;'),
}
for name, malformed in fixtures.items():
    assert malformed != source, name
    with tempfile.TemporaryDirectory(prefix='help-build-') as temporary:
        root = Path(temporary)
        shutil.copytree(ROOT / 'lib', root / 'lib')
        shutil.copytree(ROOT / 'schema', root / 'schema')
        (root / 'scripts').mkdir()
        for script in ['build.sh', 'generate-help.py']:
            shutil.copyfile(ROOT / 'scripts' / script, root / 'scripts' / script)
        (root / 'lib/000-prelude.sh').write_text(malformed)
        output = root / 'installed'
        output.write_bytes(b'keep the previously generated executable\n')
        result = subprocess.run(['bash', str(root / 'scripts/build.sh'), str(output)],
                                env=dict(os.environ, TMPDIR=str(root)),
                                text=True, capture_output=True, timeout=10)
        assert result.returncode != 0 and 'help generation:' in result.stderr, (name, result)
        assert output.read_bytes() == b'keep the previously generated executable\n', name
        assert not list(root.glob('git-locks-build.*')), name
        print('PASS ' + name + ': refuses, preserves executable, removes temporary output')
print(f'{len(fixtures)} build refusal cases passed')
