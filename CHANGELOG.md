# Changelog

All notable changes to this project are recorded here. The format follows Keep a Changelog; versions follow SemVer.

## [Unreleased]

## [0.5.0] - 2026-09-16

### Added

- `git locks doctor`: a read-only invariant check of the store (#19). One `finding` line per broken invariant as it is found, then one `doctor` line with the store, the reading basis (refs and records in the one snapshot it read, and the clock), the checks run, the count and the verdict. The invariants: every job record decodes and names its own job; every path a record lists has a path ref pointing at that record; every path ref points at a record some job ref points at, and that record lists the path; every child's parent exists, is live and has the same holder, and no parent chain cycles; every semaphore has meta and gen, its records decode, and its live slots fit its capacity. Exit 0 healthy, 1 with findings, 2 when the store cannot be read, which is never reported healthy. Paths are hashed in one `hash-object` process, so the process count does not grow with the store. Nothing is repaired: diagnosis is the whole command.

## [0.4.0] - 2026-09-16

### Changed

- The script is built. `bin/git-locks` is assembled by `scripts/build.sh` from `lib/*.sh` in numeric order, with the schema module generated from `schema/git-locks.schema.json`; `make build` writes it, and the test suite refuses a committed `bin/git-locks` that is not byte-for-byte what `lib/` builds (#11). The installed artifact, the release asset and `make install` are unchanged: one file.
- `list` renders without forking. Record fields, paths, the clock and JSON arrays have `printf -v` forms (`field_v`, `record_paths_v`, `now_v`, `json_paths_v`) and the render path uses only those, so each record is parsed once and a list of n locks is O(n) bash with no processes per line; `GIT_LOCKS_TRACE` writes one `parse <oid>` line per record and the suite counts them (#24).
- The snapshot reads `cat-file --batch` output with `read -N` instead of slicing the captured text, which was quadratic in the store size. Measured on 500 locks (macOS, bash 5.3, same store, before and after): `list` 6.75 s to 0.58 s; `check` 0.87 s to 0.28 s; `show` 0.85 s to 0.25 s; `claim` about 1.0 s to 0.33 s. The 0.07 s figures the README carried for 0.3.x were not reproducible on that store and are withdrawn.
- One clock reading per invocation (`now_v` caches it), so every `remaining` in one `list` is computed against the same instant.

### Fixed

- A `--ttl` with a leading zero was octal in arithmetic (`010` gave eight seconds; `08` failed); ttl values are decimal everywhere (`claim`, `batch`, `extend`, `sem acquire`, `with`).
- Parsed record fields are stored whole, keyed by record and field name, so no byte in a holder can read as a field delimiter (the first cut of 0.4.0 joined them with control bytes). A holder is one line; `sem acquire` and `with` now refuse a newline in it as `claim` already did.
- A `batch` record with only `parent:` or `ttl:` was skipped as empty and its parent leaked into the next record; it is malformed now.
- `sweep` deletes only the record it saw expire: a lock renewed between its read and its transaction is left alone.
- `with --sem` validates its arguments before acquiring anything, and arms its release traps before the first acquisition, so a signal during the wait for the path lock gives back the slot already taken.
- `check` reads the clock in the parent shell, so `remaining` and `state` on one line agree.
- `version` refuses extra arguments like every other command.

## [0.3.2] - 2026-09-16

### Fixed

- Every read phase loads the snapshot in the parent shell first (#23's trace found five reads per retry: after an invalidation each `$(…)` took its own). A waiter now takes exactly two reads across a release it could not see at first, the stale one and one fresh one; that is a forced, traced test for both `sem acquire --wait` and `with --wait`.

### Changed

- Tests assert on parsed fields (`jfields key=value…`) instead of exact JSON substrings, so key order is not part of the contract (#15); schema validation remains the structural guard.
- Two more test hooks: `GIT_LOCKS_PAUSE_AFTER_READ=<file>` pauses after every store read, `GIT_LOCKS_TRACE=<file>` appends one line per read.

## [0.3.1] - 2026-09-15

### Fixed

- Acquisition identity survives renewal. 0.3.0 used the record oid as the acquisition's identity, so an `extend` inside a `with` changed the oid and the wrapper's own release then reported "superseded", leaving the lock until expiry. Records now carry an `acquisition` id, minted by a claim and kept by `extend` and by a child admission's rewrite of the parent; `release --acquisition <id>`, `sem release --acquisition <id>` and `with` release by it. `record` stays as the oid of the current record version. Reproduced first: `with` running `extend` inside its command, then a check that the path is free.

### Added

- A second forced interleaving in the suite: a renewal committed between a release's read and its commit; the release re-plans and the renewed lock is gone.
- README carries measured timings on 500 locks and says plainly that process count is not time.

## [0.3.0] - 2026-09-15

The correctness release. An outside review of 0.2.1 found five defects under the guarantees and asked three questions; each defect was reproduced as a failing test before it was fixed, and README's "The contract" section carries the answers.

### Changed (breaking)

- JSON Lines everywhere: `--text` is gone. `help` and `<cmd> --help` print a `usage` object (also on a usage error, to stderr); `schema` prints the schema as one line; every error is `{"event":"error","reason":…,"detail":…}`.
- `claim`, `list`, `show` and `sem acquire`/`sem show` lines carry `record`, the object id of the acquisition. `release --record <oid>` and `sem release --record <oid>` release only that acquisition, else `nothing` with `reason: superseded`. `with` releases by record.
- A child admission rewrites the parent's record (a `family` generation) and moves the parent's refs to it, so a release or sweep planned against the old parent fails and re-plans when a child arrived meanwhile. A batch child under a same-batch parent with a different holder is refused; it used to be accepted.
- Claim-time eviction of an expired lock terminates its whole family, the same operation release and sweep use.
- Path normalisation removes empty and `.` segments and a trailing `/`, so `dir//file`, `dir/./file` and `dir/file/` are one key.

### Fixed

- A failed store read (`for-each-ref`, `cat-file --batch`, a missing or malformed object) is `{"event":"error","reason":"store-read"}` with exit 2; it was reported as free.
- Every write is compiled into one transition per ref; transactions no longer contradict themselves (two-path eviction of one expired job, two children of one parent in a batch, re-acquiring an expired slot under the same job id all failed with "multiple updates for ref").
- `sem acquire --wait` refreshes its read on every attempt; it could time out after another process released.
- JSON escaping covers every control character and git's multi-line diagnostics (#13).
- `with` releases the acquisition it made, never whatever wears the job name.

### Added

- `GIT_LOCKS_PAUSE_BEFORE_COMMIT=<file>`: a test-only gate on every transaction, used to force the child-under-release interleaving deterministically.
- The test suite refuses to run with `HOME` or `GIT_LOCKS_HOME` under the real home; `make test-docker` runs it in the official bash image.

## [0.2.2] - 2026-09-15

### Changed

- `make install` copies `bin/git-locks` into `$(PREFIX)/bin` instead of symlinking it. The symlink made the development checkout live for every consumer on the machine: while the v0.2.1 refactor was in progress on a branch, a downstream project's pre-commit hook ran the half-fixed script and its lock step failed once. An installed binary is now a snapshot of the checkout it was installed from; upgrade by re-running `make install`.

## [0.2.1] - 2026-09-15

### Changed

- One git process per protocol per command, not per object (#12). Every invocation takes one snapshot of the store, `for-each-ref` over `refs/locks/` plus one `cat-file --batch` for every blob, parsed in bash; reads come from that snapshot and every transaction invalidates it. The store lookup went from four processes to two. Measured on 50 locks: `list` 305 processes to 4, `check` on three paths 19 to 7, a three-path `claim` 13 to at most 10. The bounds are tests, run with a git shim that counts spawns. The pattern is @git-stunts/plumbing's persistent cat-file session, in bash.
- Requires bash 4 or newer (associative arrays); the script refuses older shells with a message. `LC_ALL=C` inside the script, so string offsets are byte offsets.

### Changed

- README rewritten as a guided explainer: one running example (alice, bob, one path) followed from claim to semaphore, with real transcripts and five Mermaid figures (rendered and checked) showing the store's refs and blobs as claims, refusals, releases and slots happen. The command reference and install, develop and limits sections stay at the end.

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
