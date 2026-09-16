# Contributing

- Tests are the spec. Write the failing case in `test/test.sh` first, show it red, then change the module under `lib/` and run `make build`; `bin/git-locks` is the build product and is committed beside the `lib/` change (the suite refuses a stale one).
- `make lint` must pass with zero output: shellcheck with every optional check enabled, and shfmt with the repository's settings (`-i 2 -ci -bn`). Do not add a `# shellcheck disable` without a comment saying why.
- Pure bash and git only. No jq, no Python, no external daemons. Anything that would need one belongs in a different project.
- Keep `README.md` and `CHANGELOG.md` current in the same commit as the change they describe.
- Commits use conventional-commit subjects (`feat:`, `fix:`, `test:`, `docs:`, `chore:`). No history rewriting on `main`.
- Configure the hooks once: `git config --local core.hooksPath scripts/hooks`. Pre-commit lints, pre-push runs the tests.
- Bash rules learned the hard way, each with a commit behind it:
  - `$(…)` and the tail of a pipeline run in subshells. Nothing set there survives: a memoised cache, an invalidation flag, an array. Helpers that must remember something write into a named variable with `printf -v VAR` and are never called inside `$(…)`; `path_ref VAR path` and `json_str VAR value` are the pattern.
  - A helper that writes into the caller's variable must not declare a local of the same name, or `printf -v` fills the local and the caller sees nothing (`write_blob` and the test helper `lines` both did this once).
  - Load the store snapshot once in the parent shell before dispatch; a subshell inherits it, a subshell cannot refresh it for the parent. Invalidate explicitly after any `$(transact …)`.
  - Never install this tool as a symlink into a checkout you edit. `make install` copies for that reason: a half-fixed branch went live under another project's pre-commit hook on 2026-09-15.
  - Every git spawn is a test: `test/test.sh` counts them with a shim. Keep one process per protocol per command.
  - A fork per record is a fork per record. `$(field …)` inside a render loop costs a process each time and forgets the parse; the `_v` helpers (`field_v`, `record_paths_v`, `now_v`, `json_paths_v`) exist so hot paths never fork. `list` on 500 locks went from 6.75 s to 0.58 s by using them.
  - `${text:pos:len}` on a large string copies from `pos` every call; a loop over it is quadratic. Read structured output with `read -N` instead (the snapshot's `cat-file --batch` parse).
