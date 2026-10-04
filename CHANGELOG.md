# Changelog

All notable changes to this project are recorded here. The format follows Keep a Changelog; versions follow SemVer.

## [Unreleased]

### Added

- Three audit reports under `docs/audit/` from the 2026-10-02 Internal Repository Survey: Day 0 DX and purity (20 findings, TTV 6.3/10), architecture and provenance (16), and ship readiness (15, one Critical: `transact()` retries permanent failures 200 times). Every finding carries an action prompt; the consolidated backlog is filed as #52–#86.
- A calibrated historical directory-token benchmark (#39), comparing released prefix churn, repeated reuse, and live-lock controls. Small real-CLI calibration runs in the suite; large timing runs are informational. The retained macOS run contains 135 observations, including multi-second reads of a released wide-10k store, but it coincided with host memory and disk exhaustion and is kept as a record, not a baseline. The runner ignores inherited `GIT_LOCKS_TRACE`, `GIT_LOCKS_PAUSE_*`, and `GIT_LOCKS_HOME` so test hooks cannot reach timed commands.
- A runnable cooperating-worker example (#40) acquires a path set in the mutation launcher, shows holder/note contention, allows unrelated work, and demonstrates renewal, superseded cleanup, failure cleanup and non-renewing TTL expiry. JSON receipts and behavior tests cover the golden path, agreement with the retained recorded run, an existing-output edge, a stopped run leaving no worker processes, and two concurrent isolated runs. The runbook distinguishes these controlled flows from unresolved #45 coherence work and defines external adoption validation as an unrun experiment.

### Changed

- **Breaking storage format (#45):** reservations now live in one immutable Git tree, published through a conditional update of `refs/locks/state`. Every membership and absence decision uses that root. Disjoint writers replan after contention; semaphore creation no longer mistakes unrelated publication for an existing semaphore. Stop all old clients and use `git locks migrate --offline` to import a healthy legacy store. No daemon or new production dependency is introduced.

- Tests, benchmarks, lint, and CI use one reusable offline Docker worker with copied source, a fresh unrelated Git fixture, no host mounts, and bounded temporary storage. A pinned git-stunts/docker-guard adapter rejects raw test entry points even with Docker/CI environment flags set. Isolation configuration, logs, and explicitly selected evidence are exported before teardown; production dependencies are unchanged.
- **Breaking:** re-claiming a parent's acquisition while any of its descendants remain stored, expired ones included, now exits 1 with a `parent` refusal whose detail is `descendants`. Before, a same-holder re-claim replaced the parent and left its children pointing at a superseded acquisition. Scripts that renew a parent by claiming it again must switch to `extend`, or release or sweep the descendants first (#34).
- The README leads with cooperative path reservations, explains TTL and launcher admission before the first example, and refreshes introductory and wrapper transcripts with acquisition IDs. It clarifies linked-worktree logical ownership, release conditions, and Git concurrent-reader visibility (#37).

### Fixed

- Publication distinguishes stale roots from operational failures (#52). Permission and unknown Git errors return `store-write` (exit 2) immediately. A busy root lock gets at most six attempts with one unchanged candidate; it is never deleted by acquisition. Blob-write and path-hash diagnostics are structured too. Real permission and lock-file tests verify bounded retries, preserved authority, and bounded record creation across writer commands.
- Time inputs share one decimal parser with signed 64-bit bounds (#55, #56). TTL and wait additions check for overflow before arithmetic; leading zeros are decimal, and malformed clock overrides are rejected before store initialization. System-clock failures and backward steps during waits report structured errors. Publication retries refresh their lease clock and recheck expiry bounds. Tests cover all TTL writers and confirm refused inputs cannot publish or launch a command.
- The full membership observation study is an ordinary test/CI gate (#88). Current-root and stale-root cases cover families, semaphores, and prefixes. Original per-ref counterexample receipts remain historical evidence.

- The README no longer overstates child admission: the parent's liveness and holder are checked at planning time, and the transaction compares the parent's record rather than sending a `verify` line. The claim stanza is marked as simplified (it omits the ancestor-prefix verify and the directory token), directory token refs are noted to outlive a release, and `with` lists `--note` and `--parent` (#37).
- The README states that `with --wait` also waits for a semaphore slot when `--sem` is given, and the `with` command-table row lists `--sem` and the optional paths (#37).
- The README's `with` synopses now list every option the command accepts, including `--note` and `--ttl`, which the example uses.
- A controlled membership-observation study (#38) enumerates mixed before/after refs for families, semaphore slots and prefix descendants. Real Git transactions leave independent invariant violations in 21 of 84 synthetic cases. The fixture retains exact observations and transaction receipts, calibrates its independent oracle, and returns exit 1 when it exposes a safety failure; any harness fault, anticipated or not, exits 2. The ordinary test suite runs the oracle calibration and verifies the committed receipt hashes. No live Git race is claimed and no production fix is included; #45 tracks the unresolved correctness work.
- Parent acquisition replacement (#34) now refuses while any descendants remain stored, including expired descendants. This applies to the same holder, changed holders, reparenting and batches. Renew parents with `extend`, or release/sweep descendants before replacing them. Leaf replacement followed by new child admission remains supported. Admission rejects self-parenting and indirect cycles, verifies observed ancestor records in its transaction, and reports schema-valid `parent` refusals with `cycle` or `descendants` detail. The `claim` help text and the README command table state both rules. Regression tests cover unchanged refs and the reported `detail` on refusal, renewal/recreation, both child-admission race directions with their final records, and 192 seeded operations whose outcomes and refusal reasons are checked against an independent family model.
- Semaphore capacity is validated as a bounded positive decimal and normalized before storage, arithmetic, and JSON serialization. Leading-zero values such as `01`, `08`, and `010` keep their decimal meaning, including when reading metadata written by older versions. Invalid stored capacities fail with `store-read` (#35).
- `doctor` reads a stored semaphore capacity with the same decimal rule. Before, a legacy `08` printed a bash arithmetic error, `010` was compared as octal eight (so nine live slots were a false `sem-capacity` finding), and a capacity past 2^64 wrapped around to a small number instead of being a `sem-record` finding.
- Validate authoritative lock and semaphore records before normal reads or planning (#33). Corrupt records now produce a structured `store-read` error with exit 2 before any success output or mutation. Doctor shares the decoder and safely reports malformed numeric fields; generation tokens remain opaque. Stored decimal fields normalize leading zeros and reject values outside the nonnegative signed 64-bit range. Child admission refuses a parent whose family generation cannot advance without overflow.
- `sem list` no longer reads the slot of a job named `meta` as a second semaphore. It matched any ref ending in `/meta`, so `refs/locks/sem/gpu/slots/meta` printed a `gpu/slots` line with an empty capacity, which is not valid JSON. Snapshot validation splits semaphore refs the same way, so such a slot is validated as a slot rather than as metadata.
- Path normalisation preserves literal `*`, `?` and bracket characters instead of expanding them against files in the working tree.
- Unicode integration tests select an installed UTF-8 locale (probing for one where there is no `locale` command, as on musl), keep JSON stdout separate from shell diagnostics, and report an explicit skip when no UTF-8 locale is available; `GIT_LOCKS_TEST_REQUIRE_UTF8=1`, set in CI, turns that skip into a failure.

## [0.7.0] - 2026-09-16

### Added

- Prefix locks (#6). A path ending in `/` is a prefix: `claim --job build dist/` covers every path under `dist/`, so `with --job build dist/ -- make` now protects what it names. A claim on a path under a live prefix held by another job is refused `via` the prefix; a claim on a prefix over a live lock under it is refused `via` that path; `check` reports the same `via`. Expired locks in the way are evicted as before. The same job may claim under its own prefix. `dist` without the slash is the directory entry itself, a different key, and is not covered.
- Overlap inside one `batch` is decided while planning, before any transaction: two records of different jobs may not claim a prefix and a path under it (the records are not in each other's snapshot, so neither the ancestor verify nor the descendant scan can see the other). The loser is a `duplicate` refusal naming the path and the record that covers it, and the batch lands nothing. One job may still hold a prefix and a path under it.
- How the race closes: prefixes above a wanted path are verified inside the transaction (absent, or unchanged), and every claim moves a directory token ref (`refs/locks/dirs/<hash of the prefix>`) for each directory above its paths by compare-and-swap from the value its snapshot saw. A prefix claim's scan of what is under it and a path claim's check of what is above it therefore cannot both be stale: one of the two transactions fails and re-plans with the other in view. Both orders are forced in the suite with the before-commit gate. The cost is one extra ref transition per directory level on every claim, and two claims under one directory can now collide once and re-plan; `doctor` knows the token refs.

### Changed

- A trailing slash is no longer stripped by normalisation; it is the prefix marker. Before 0.7.0, `dir/file/` named the same key as `dir/file`; now it asks about, or claims, everything under `dir/file`. Every other normalisation rule is unchanged (`dir//` and `./dir/./` are the prefix `dir/`).

## [0.6.0] - 2026-09-16

### Added

- `--note <text>` on `claim` and `with`, and `note:` in a batch record: one line saying why the lock is held (#8). It is stored in the record and carried on every line that names the lock: the claim line, `show`, `list`, `check` on a held or expired path, and the refusal another claimant gets, which can now read "held by alice: building the release bundle" rather than just "held by alice". `extend` and a child admission keep it. Optional in the schema; absent when none was given.

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
