# Bash compatibility check

The CLI requires Bash 4.4 or newer. Earlier Bash versions treat empty arrays as unset under `set -u`. The startup guard returns a JSON usage error and exit code 2 before store access.

CI downloads the GNU Bash 4.3 and 4.4 release archives with exact byte limits and SHA-256 checks. It builds each interpreter in the existing Docker test worker, then tests the unsupported-version refusal and the supported reservation lifecycle. It does not simulate `BASH_VERSINFO` or use the worker's default Bash as evidence for the minimum version.

Run the same check with:

```sh
python3 scripts/bash-compatibility.py fetch
python3 scripts/docker-run.py python3 scripts/bash-compatibility.py test --full
```

The fetch step reuses verified archives in `bash-compat-input/`. Keep these local inputs untracked so the Docker source copier can include them. Each archive is at most 10 MiB; the two archives total less than 20 MiB. Fetching has a 120-second deadline plus a 10-second socket timeout. Compilation runs offline with the worker's existing CPU, memory, temporary-storage, log, and process-time limits. Source and object trees are removed after each interpreter build. No compiler output is added to an image.

For repeated local checks, `test --interpreters PATH` reuses explicitly supplied binaries named `bash-4.3` and `bash-4.4`. Use binaries from a verified local build. The test checks their actual version strings; this option does not authenticate their provenance. CI always builds from pinned source archives.

Focused coverage includes refusal before store creation or child execution, claims, conflicts, renewal, release, batch input, semaphore capacity, wrapped-command output and cleanup, and doctor. With `--full`, a PATH selector also routes the normal `bin/git-locks` entry to Bash 4.4 for the full suite and counts those invocations. Test and build scripts retain the worker's normal Bash because the benchmark harness requires Bash 5. Tests that explicitly select another interpreter or construct another CLI copy retain that behavior. The selector does not change production source or its assembled bytes.

This Linux check does not establish native macOS compatibility or support for older Git versions. Full-suite checks on the normal toolchain remain separate release gates.
