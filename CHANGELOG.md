# Changelog

All notable changes to this project are recorded here. The format follows Keep a Changelog; versions follow SemVer.

## [Unreleased]

## [0.2.0] - 2026-09-15

### Added

- Capacity semaphores: `sem create <name> --capacity <n>`, `sem acquire` (with `--ttl` and `--wait`; re-acquire refreshes the job's own slot), `sem release`, `sem show`, `sem list`, `sem delete`. A slot is a ref under `refs/locks/sem/<name>/slots/`; every transaction on a semaphore compare-and-swaps its `gen` ref, so racers beyond capacity fail and re-read; a lost swap is retried, a full semaphore is refused with `capacity` and `live`. Expired slots free their capacity and are evicted by the next transaction.
- `with --sem <name>`: take a slot around a command, with or without paths; released on exit, failure, or a signal.
- Schema: `sem_line`, `sem_event_line`, and the `capacity`, `exists` and `live` refusals. 238 checks.

## [0.1.0] - 2026-09-15

### Added

- Parent/child locks: `claim --parent <id>` (parent live, same holder, verified inside the transaction); `release` and `sweep` take every descendant with the parent in one transaction and report them as `cascaded`; `list`, `show` and `claim` lines carry `parent`.
- All or nothing across several locks: `batch` claims every record on stdin in one transaction or none; `release --job a --job b` releases several jobs, with their families, in one transaction.
- `show --job`, `ttl --job`, `extend --job --ttl`: one lock in full with the seconds it has left, just the seconds, and an atomic expiry move. `list` and `check` lines carry `remaining` too.
- `with --job --holder [--ttl] [--wait] <path>... -- <command>...`: claim, run the command, release (on failure and on INT/TERM too), exit with the command's status; `--wait` retries once a second. The wrapped command owns stdout; git-locks reports on stderr.
- Works outside a git repository: the default store is keyed on the directory when there is no repo.
- A `release` job on push to `main`: when `VERSION` has no tag, tag `v<version>`, publish a GitHub release with that CHANGELOG section as notes and the script plus schema attached.
- JSON Lines by default on every command, one object per result written as each result is known, refusals as objects on stderr; `--text` for the human form. `git locks help` and `<cmd> --help` exit 0; `git locks version`.
- The public output schema, `schema/git-locks.schema.json` (JSON Schema 2020-12), printed byte-for-byte by `git locks schema`; the test suite validates every emitted line against it.
- The store: locks live in a bare repository at `~/.git-stunts/locks/<absolute path of the main repo>` by default, created on first use, shared by a repo's linked worktrees, so the project's own refs stay clean; `GIT_LOCKS_STORE=<path|self>`, `git config locks.store`, and `GIT_LOCKS_HOME` override it; `git locks store` prints what resolved.
- `git locks claim | release | check | list | sweep`: path locks stored as git refs (`refs/locks/jobs/<job>`, `refs/locks/paths/<hash>`) pointing at a plain-text record blob; a claim is one `git update-ref --stdin` transaction, atomic across its paths and across racing claimants; a refused claim names the holder; expiry with a default four-hour TTL; re-claim by the same job replaces its path set; expired locks are claimable over and swept on demand.
- `test/test.sh`: 194 checks in pure bash, including twenty concurrent claimants producing exactly one winner.
- `make lint` (shellcheck with every optional check, shfmt) and `make test`; git hooks under `scripts/hooks/`; GitHub Actions running both.
