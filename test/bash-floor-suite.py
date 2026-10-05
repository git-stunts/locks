#!/usr/bin/env python3
"""Run the full suite with the production CLI selected through real Bash 4.4."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['node', str(ROOT / 'scripts/require-docker.mjs')], check=True)

import argparse
import os
import shutil
import shlex
import signal
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--bash44', required=True, type=Path)
args = parser.parse_args()
interpreter = args.bash44.resolve()
version = subprocess.check_output([str(interpreter), '-c', 'printf "%s" "$BASH_VERSION"'], timeout=5)
assert version.startswith(b'4.4.'), version
native = shutil.which('bash')
assert native, 'test-tool Bash missing'

with tempfile.TemporaryDirectory(prefix='locks-bash-selector-') as scratch:
    directory = Path(scratch)
    trace = directory / 'invocations'
    selector = directory / 'bash'
    # The benchmark harness needs Bash 5's EPOCHREALTIME. Select the old
    # interpreter only for the real CLI entry; leave test/build tools intact.
    # A Python launcher initializes sys.stdin and crashes on a directory fd
    # before the CLI can report its own read error. This shell wrapper leaves
    # stdin untouched, including deliberately invalid descriptors in tests.
    selector.write_text('#!/bin/sh\n'
                        f'target={shlex.quote(str(ROOT / "bin/git-locks"))}\n'
                        f'old={shlex.quote(str(interpreter))}\n'
                        f'native={shlex.quote(native)}\n'
                        'selected=$native\n'
                        'if [ "$#" -gt 0 ] && [ "$(realpath -- "$1" 2>/dev/null)" = "$target" ]; then\n'
                        f'    printf 1 >> {shlex.quote(str(trace))} || exit 2\n'
                        '    selected=$old\n'
                        'fi\n'
                        'exec "$selected" "$@"\n')
    selector.chmod(0o700)
    env = dict(os.environ, PATH=str(directory) + os.pathsep + os.environ['PATH'])
    process = subprocess.Popen(['make', 'test-container'], cwd=ROOT, env=env, start_new_session=True)
    try:
        code = process.wait(timeout=1500)
        assert code == 0, f'full suite exited {code}'
        count = trace.stat().st_size
        assert count > 0, 'full suite never selected the minimum-version CLI'
        print(f'Bash 4.4 production CLI invocations: {count}', flush=True)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
