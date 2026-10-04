---
title: "git-locks: cooperative path reservations"
date: 2026-09-15
author: James Ross
description: "Cooperative path reservations for parallel workers, backed by Git without a daemon. Understand contention, acquisition identity, and time-bounded ownership."
tags: [git, locking, bash, concurrency, jsonl]
draft: false
status: published
project: git-stunts/locks
version: 0.7.0
---

# git-locks: cooperative path reservations

Cooperative path reservations for parallel workers, backed by Git without a daemon. A worker reserves the paths it will change; a competing worker gets a refusal naming the holder, job, and reason. Pure Bash and Git, with JSON Lines output and a separate store by default. For a command reference, jump to [Commands](#commands).

## In sixty seconds

git-locks coordinates workers that agree to acquire before changing a path. A claim can reserve several paths together, a trailing slash reserves a prefix, and `--note` explains the work to a competing worker. The default store is a separate bare repository, so the project's own refs stay clean.

Reservations are cooperative and time-bounded. They do not prevent writes by other programs. `with` acquires, starts a command, and attempts release on exit, but does not renew automatically. Its TTL can expire while the command is still running. Choose a sufficient TTL or arrange explicit renewal; cleanup on exit does not extend the reservation.

Acquire in the launcher that starts the mutation. `check` reports an observation and does not authorize a later write: another worker can claim between the check and the write. `with` supplies that acquire-before-launch ordering for shell commands.

Every command reads an immutable state tree through one Git ref. Writers publish a successor tree only if that ref still holds the root they read; competing writers reread and replan. See the [state protocol](docs/state-protocol.md) for the argument, tradeoffs, and offline upgrade from the old per-ref format.

## The example we will follow

Alice and Bob want to edit `notes/report.md`. Alice reserves it with a note. Bob's two-path claim is refused, leaving his unrelated path free. Alice then renews and releases the acquisition she originally made. This transcript was run against git-locks 0.7.0 at `01e39c3` in an isolated store, with `GIT_LOCKS_NOW=1757980800` fixing the clock at 2025-09-16T00:00:00Z. Record and acquisition IDs are captured values; a rerun generates new ones. Successful results are on stdout, refusals on stderr.

```text
$ git locks claim --job alice-report --holder alice --note 'updating the report' notes/report.md
{"event":"claimed","job":"alice-report","holder":"alice","note":"updating the report","claimed":1757980800,"expires":1757995200,"paths":["notes/report.md"],"record":"8f61ae62870d65e38b6b822b4c71186f4d5cbc81","acquisition":"1757980800-95407-2444308745"}

$ git locks claim --job bob-report --holder bob notes/report.md notes/other.md
{"event":"refused","path":"notes/report.md","holder":"alice","note":"updating the report","job":"alice-report","expires":1757995200}
(exit 1)

$ git locks check notes/report.md notes/other.md
{"path":"notes/report.md","state":"held","holder":"alice","note":"updating the report","job":"alice-report","expires":1757995200,"remaining":14400}
{"path":"notes/other.md","state":"free"}
(exit 1)

$ git locks extend --job alice-report --ttl 18000
{"event":"extended","job":"alice-report","expires":1757998800}

$ git locks show --job alice-report
{"job":"alice-report","holder":"alice","note":"updating the report","state":"live","claimed":1757980800,"expires":1757998800,"remaining":18000,"paths":["notes/report.md"],"record":"13bcecae65ff6128d118ec1c25a9c3ed0ccefee7","acquisition":"1757980800-95407-2444308745"}

$ git locks release --job alice-report --acquisition 1757980800-95407-2444308745
{"event":"released","job":"alice-report","paths":1}

$ git locks claim --job bob-report --holder bob notes/report.md
{"event":"claimed","job":"bob-report","holder":"bob","claimed":1757980800,"expires":1757995200,"paths":["notes/report.md"],"record":"a549af55e7c64fea41f66ca9c0390e9e37f2b792","acquisition":"1757980800-95785-1651320319"}
```

The job ID is a reusable name. The acquisition ID identifies this reservation's lifetime, while the record ID identifies its current stored version. `show` after renewal confirms Alice's record changed while her acquisition stayed the same. Her `release --acquisition` therefore still released the reservation she made. If another claim had replaced that job's acquisition, her release would have left the replacement alone. `release --record` instead conditions release on one exact version and becomes stale after renewal.

Local agent runners, generators, and build processes are candidate integrations for this workflow. The runnable behavior establishes what the tool does; adoption and business demand still need evidence from actual users.

## The cast: a store, records, and one root

The default store is a separate bare repository under `~/.git-stunts/locks`, keyed by the subject repository's common directory. Linked worktrees share that store and the same logical path namespace. `git locks store` reports the resolved location; `GIT_LOCKS_STORE` or `locks.store` can select another store.

Records are immutable blobs containing a job, holder, acquisition identity, expiry, and paths. A Git tree maps jobs and path hashes to those records, alongside family and semaphore bookkeeping. One ref, `refs/locks/state`, points to the whole tree.

```text
refs/locks/state -> tree
                   jobs/alice-report -> reservation blob
                   paths/<path-hash> -> the same blob
                   sem/gpu/...      -> capacity and slot records
```

A writer reads that root, checks its complete state, builds a successor tree, and asks Git to replace the root only if it has not changed. That last comparison decides who wins. Failed publication grants nothing; the caller must read again. Unchanged subtrees are shared between versions. Bash and Git do all of this, without a daemon.

To inspect the current state with Git, resolve the store and run `git --git-dir="$store" ls-tree -r refs/locks/state`. Read one record with `git --git-dir="$store" show refs/locks/state:jobs/alice-report`.

## Expiry, families, batches, and capacity

A reservation is live until its expiry. An expired record can remain stored; a later claim can evict it, and `sweep` removes expired reservations. No background process is needed.

A child names a live parent held by the same holder. Releasing or sweeping the parent removes its descendants in the same publication. Re-claiming a parent with stored descendants is refused; `extend` renews it while preserving acquisition identity. `batch` plans several claims and publishes all of them together, or none.

A semaphore has a capacity and time-bounded slots. `sem acquire` checks all slots in the same immutable tree as the capacity, then conditionally publishes the result. Concurrent acquisition cannot bypass the root comparison by observing a generation without its membership.

Existing per-ref stores require an [offline migration](docs/state-protocol.md#upgrade). Stop every old client before running `git locks migrate --offline`; ordinary commands refuse the old layout.

## Wrapping a command: claim, run, release

`with` places acquisition in the command launcher and attempts cleanup when the command exits. Its reservation remains subject to the TTL, process termination, and store errors.

`git locks with --job <id> --holder <name> [--ttl <s>] [--wait <s>] [--sem <name>] [--parent <id>] [--note <text>] [<path>...] -- <command>...` claims the paths (and a semaphore slot if asked), runs the command, and releases on exit, on failure, and on Ctrl-C or a termination signal, then exits with the command's own status. The command owns stdout; git-locks reports its claim and release on stderr, so a pipeline reading the command's output sees only that output:

```text
$ git locks with --job build --holder alice --ttl 60 dist/bundle.js -- sh -c 'echo building'
{"event":"claimed","job":"build","holder":"alice","claimed":1757980800,"expires":1757980860,"paths":["dist/bundle.js"],"record":"41072aa71c762bc6c37d8765ccbc1ff592006039","acquisition":"1757980800-95867-1195225591"}
building
{"event":"released","job":"build","paths":1}
```

`--wait <seconds>` turns a refusal into a retry once a second until the requested paths and, if `--sem` is given, a semaphore slot are available or the wait runs out; without it, a held path or a full semaphore exits 1 immediately and the command never runs.

In this transcript, `building` is the command's stdout; both lifecycle JSON lines are on stderr. `with` remembers its acquisition and releases by that identity, including after renewal. A command running longer than `--ttl 60` would outlive this reservation unless it explicitly renewed. An uncatchable kill or a store failure can prevent cleanup; expiry still bounds the reservation.

## A runnable cooperating-worker example

The [two-worker example](examples/cooperating-workers/README.md) reserves a path set before launching mutation, shows a competing worker who holds it and why, and lets unrelated work finish. It also demonstrates renewal, acquisition-aware cleanup, worker failure and the TTL boundary in an isolated store. The runbook defines an external adoption experiment as unrun. Its controlled flows do not resolve the observation-coherence failures tracked by [#45](https://github.com/git-stunts/locks/issues/45).

## Output: JSON Lines, always

The introductory transcript shows complete JSON objects; later mechanism sketches abbreviate fields and IDs. This section states the CLI output contract. There is no plain-text mode. Stdout carries one object per result, written as each result is known; stderr carries refusals and errors as objects; `git locks help` is a `usage` object; `git locks schema` prints the schema as one line. The single exception is a command wrapped by `with`, which owns stdout while git-locks reports around it on stderr.

Each line matches exactly one definition in [`schema/git-locks.schema.json`](schema/git-locks.schema.json), JSON Schema 2020-12. The pretty file is for people; the test suite parses `git locks schema` and asserts it is the same document, and validates every line it provokes against it. Strings are escaped completely: a control character in a holder or a git diagnostic inside a refusal cannot break the consumer's parser, and that is a test. Exit codes: 0 for done or free, 1 for refused or held, 2 for usage or a store that could not be read.

In summary, the output is the API, the schema is its contract, and the tests are what keep the two the same.

## The contract, in the terms a reviewer asked for

An outside review of 0.2.1 found the guarantees running ahead of the implementation in five places and asked three questions. The fixes shipped in 0.3.0; the answers are the contract.

**What a successful acquisition authorises, and how it is identified.** A claim admits one *acquisition*, and three names apply to it, kept distinct on purpose. The **job id** is a label a person or an orchestrator chooses; it can be reused, and a later claim under the same job is a new acquisition that replaces the old one, unless the old one still has stored descendants (see what `parent` means, below). The **acquisition id** (`acquisition` on the claim line) is minted by the claim and kept by every rewrite of the record: `extend`, and the family bump a child admission performs on a parent. The **record** (`record`) is the object id of the current version of that record, and changes on every rewrite. `release --job X --acquisition <id>` releases that acquisition and only that one, across any number of renewals; `--record <oid>` releases only if the record is exactly that version. If the job now holds a different acquisition, the answer is `{"event":"nothing","reason":"superseded"}` and nothing moves. `with` remembers the acquisition it made and releases by it, so an invocation that outlives a re-claim of its job name cannot release someone else's lock, and one whose command renewed the lock still releases it. Semaphore slots carry the same two ids.

**What binds the membership you observed to the decision you commit.** A single root identifies all immutable entries used in planning. Publication compares that root, so a competing membership change invalidates the entire plan. This replaces the old per-ref generation protocol whose synthetic failures are retained in the [membership observation study](docs/studies/membership-observation/README.md). The [state protocol](docs/state-protocol.md) describes the proof obligation and its limits.

**What `parent` means.** Ownership plus lifetime, not dependency ordering. A child is admitted only under a live parent held by the same holder. Liveness and holder are checked at planning time; the root comparison ensures that the complete state is unchanged since that check, so a release, a renewal or another child cannot have slipped in between. The comparison does not re-check the clock: a parent that expires during the microseconds between planning and commit is still bumped, and its family ends at the next sweep or claim over it. The child is released or swept whenever the parent is, by any command, including a claim that evicts an expired parent. Expiry is not inherited: a child keeps its own `expires`, and a parent's expiry ends the family. Renewing a parent (`extend`) keeps its family and acquisition identity.

A child stores its parent's **job name**, but belongs to the **acquisition** that admitted it. To preserve that binding without adding an acquisition field to each child, `claim` and `batch` refuse to replace any job with stored descendants, even for the same holder. This includes reparenting that job and descendants that have expired but have not yet been released or swept. Use `extend` to renew a parent; release or sweep its descendants before replacing it, or release the parent to end the whole family. Recreating the name after release starts a fresh acquisition with no old descendants. A leaf can still be replaced or reparented under a live parent with the same holder. Self-parenting and indirect cycles are refused.

These rules also apply inside a batch. Replacing a leaf and then admitting a new child under it is allowed. Admitting a child and then replacing its parent is refused, as is replacing a parent with children already stored, even if the batch also replaces those children. Refusals use `reason: "parent"` with `detail: "cycle"` or `detail: "descendants"`, exit 1 and leave all refs unchanged. For `descendants`, both `job` and `parent` name the job whose acquisition would be replaced.

Replacement and ancestry decisions use the same immutable root as the rest of the operation. The tests force child admission and replacement in both orders and compare seeded command histories with an independent family model.

**What a path identifies.** The lexical form after normalisation: leading `./`, empty segments and `.` segments are removed; absolute paths and `..` are refused. `dir//file` and `dir/./file` are one key. Literal `*`, `?` and bracket characters stay unchanged; files in the working tree never expand or otherwise rewrite a requested path. Case, symlinks and hard links are not resolved. A trailing `/` is kept and means a prefix: `dir/` covers every path under it, and is covered by any live lock under it, in both directions and inside the transaction (the root comparison invalidates a plan after any intervening state change); `dir` without the slash is the directory entry itself, a different key, and a prefix does not cover it. Before 0.7.0 the slash was stripped; that is the one normalisation rule that changed.

**What a lock does not do.** It is a cooperative, time-bounded reservation. `with` claims once, runs, and releases; it does not renew, so the reservation can expire under a long command and another claimant may take the path. Give `--ttl` the command's worst case, or renew with `extend` from inside it. A `check` that says free is an observation, not an admission; the protected write needs a claim.

**What a failed read is.** An error, never a free path. If `for-each-ref` or `cat-file` fails, or an object does not parse, the command exits 2 with `{"event":"error","reason":"store-read"}` and reports nothing as free or held. Each refreshed snapshot validates authoritative job/path records, semaphore metadata, and semaphore slots before normal commands use them. Missing required fields, duplicate headers, invalid identities, and unsafe numeric fields are store-read errors. Decimal fields accept leading zeros on disk and normalize them before arithmetic or JSON output; values must fit a nonnegative signed 64-bit integer, and capacity must be positive. A parent at the maximum family generation can still be read or released; child admission fails before its generation would overflow. Directory and semaphore generation tokens remain opaque. `doctor` uses the same record validation to report findings instead of refusing a decodable snapshot.

**What the invariants are, and how to see them hold.** `git locks doctor` reads one snapshot and checks it, writing nothing: every job record decodes and names its own job; every path a record lists has a path ref pointing at that record; every path ref points at a record some job ref points at, and that record lists the path; every child's parent exists, is live and has the same holder, and no parent chain cycles; every semaphore has its meta and gen refs, its records decode, and its live slots fit its capacity. Each broken invariant is one `finding` line as it is found, and the last line states the basis it was checked against, the refs and records of that one snapshot and the clock, so a clean report says what was clean. An unreadable store is an error, never healthy. Repair is not a mode of this command; when a finding needs a hand, the fix is a `release`, a `sweep`, or an explicit offline reconstruction of the state tree by someone who has read the finding.

**What the tests are.** A contract with bounded conformance evidence, not a proof. The race tests show one winner among twenty racers and three among twenty on capacity three, in those runs. The interleaving that let a child survive its parent's release is forced deterministically with `GIT_LOCKS_PAUSE_BEFORE_COMMIT`, a test-only gate that makes a transaction wait for a file before committing, and the invariant is asserted on the resulting store.

## How it was built, including the missteps worth keeping

The design was tested before it was written, and the failures on the way are recorded because each says something true. The tests are pure bash, in `test/test.sh`, and every feature above began as a red case there.

The race is the case that matters most: twenty background claims on one path, then a count of how many exited 0, asserting exactly one. It was red against an allow-everything stub before the script existed. The semaphore version is twenty racers on capacity three, asserting three.

Two missteps. The first push of the semaphore branch came from a linked git worktree, and git exports `GIT_DIR` to hooks; the pre-push hook ran the suite, the suite inherited it, and every `git init` inside its temporary repositories re-initialised the real repository, once as bare. Nothing was lost, and the tests and both hooks now unset `GIT_DIR` and its relatives first. The second was the 0.2.1 performance work: the first cut made `list` cost 604 processes instead of 305, because `$(…)` runs in a subshell and every field read loaded its own snapshot and threw it away. Snapshots are now loaded once in the parent, and helpers write into named variables so their memoisation survives.

An outside review of 0.2.1 then found five defects under the guarantees: a failed read reported as free, transactions that contradicted themselves, family membership outside the conflict boundary, release by job name instead of by acquisition, and JSON that a git diagnostic could break. Each was reproduced as a failing test before it was fixed; the section above is the contract that came out of it.

## What done looks like

For a consumer, done is a checklist you can run:

- `git locks claim` on a free path exits 0 and prints one `claimed` line with a `record`; on a held path it exits 1 and the stderr line names the holder.
- `git locks check <path>` exits 1 exactly while the path is held by an unexpired lock, and exits 2, saying so, when the store cannot be read.
- `git --git-dir "$(git locks store | sed -E 's/.*"store":"([^"]*)".*/\1/')" ls-tree -r refs/locks/state` shows every entry, and your project's `git for-each-ref refs/locks/` shows nothing.
- `git locks with … -- cmd` exits with `cmd`'s status and releases the acquisition it made, even after Ctrl-C, even if its job name was re-claimed meanwhile.
- `git locks sem show <name>` never reports `live` above `capacity`, under any number of racers.
- Every line you receive, on either stream, parses as JSON and validates against `git locks schema`.

The reference sections below are the map; the story above is why the map looks the way it does.

## Commands

Output is JSON Lines on every command; there is no text mode.

| Command | Does | Stdout line(s) | Exit |
|---|---|---|---|
| `claim --job <id> --holder <name> [--ttl <s>] [--note <text>] <path>...` | atomically lock the paths for the job; re-claiming with the same job replaces its record, and is refused while the job has stored descendants; `--note` is one line saying why, carried on every line that names the lock | one `claimed` object with `record` and `acquisition`; refusals on stderr | 0 claimed, 1 refused, 2 usage |
| `check <path>...` | who holds each path, in argument order; a path under a live prefix, or a prefix with a live lock under it, is held `via` that other path | one object per path as it is examined | 0 all free, 1 any held |
| `list` | every lock, live or expired, with its paths | one object per lock; nothing when empty | 0 |
| `sweep` | delete expired locks | one `swept` object per lock, as it goes | 0 |
| `store` | the resolved store path | one `store` object | 0 |
| `show --job <id>` | one lock in full, with `remaining` seconds | one object, same shape as a `list` line | 0, 1 if no such lock |
| `ttl --job <id>` | the seconds a lock has left | one `{job, expires, remaining}` object | 0, 1 if no such lock |
| `extend --job <id> --ttl <s>` | move the expiry to now + ttl, paths unchanged, atomically | one `extended` object | 0, 1 if no such lock |
| `claim … --parent <id>` | make the lock a child: the parent must be live and held by the same holder when planned, and its record unchanged at commit (the clock is not rechecked), and must not be the job itself or one of its descendants; the child is released or swept with it | as `claim`, with `parent` | 0, 1 if refused |
| `batch < records` | claim several locks in one transaction, or none; records are blank-line separated `job:`, `holder:`, `ttl:`, `parent:`, then `paths:` with one path per line | one `claimed` object per record | 0, 1 if any is refused, 2 on a malformed record |
| `release --job <id> [--record <oid> OR --acquisition <id>] [--job <id>...]` | release the jobs and descendants; `--acquisition` survives renewal, while `--record` requires the exact stored version; give one condition per job (if both are given, both must match) | one object per job, `cascaded` lists descendants, `nothing` with `reason: superseded` when the record no longer matches | 0 |
| `with --job <id> --holder <name> [--ttl <s>] [--wait <s>] [--sem <name>] [--parent <id>] [--note <text>] [<path>...] -- <cmd>...` | claim, run the command, release by the acquisition it made; `--wait` retries once a second until the requested paths and, if `--sem` is given, a semaphore slot are available or the wait runs out | the command's own stdout; git-locks' `claimed`, `released` and refusals go to **stderr** | the command's exit status; 1 if never acquired; 130/143 on INT/TERM after releasing |
| `version` | tool name and version | one object | 0 |
| `schema` | the JSON Schema every line above conforms to | the schema document | 0 |
| `migrate --offline` | import legacy state after stopping all old clients | one `migrated` object with root and entry count | 0 migrated/already current, 2 on error |
| `doctor` | read-only invariant check of the store; nothing is repaired | one `finding` object per broken invariant as it is found, then one `doctor` object with the basis (refs, records, clock), the checks run and the verdict | 0 healthy, 1 with findings, 2 if the store cannot be read |
| `sem create <name> --capacity <n>` | a semaphore with n slots | one `created` object | 0, 1 if it exists |
| `sem acquire <name> --job <id> --holder <name> [--ttl <s>] [--wait <s>]` | take a slot; re-acquiring refreshes the job's own slot; `--wait` retries once a second | one `acquired` object with `live` and `capacity` | 0, 1 when full |
| `sem release <name> --job <id>` | give the slot back | one `released` or `nothing` object | 0 |
| `sem show <name>`, `sem list` | capacity, live count, live slots with `remaining` | one object per semaphore | 0, 1 if missing |
| `sem delete <name>` | remove an empty semaphore | one `deleted` object | 0, 1 while slots are live |
| `with --sem <name> …` | take a slot around the command, with or without paths | as `with` | as `with` |
| `help`, `--help`, `<cmd> --help` | usage | one `usage` object | 0 |

## Output schema

Every JSON line git-locks writes, on stdout or stderr, matches exactly one definition in [`schema/git-locks.schema.json`](schema/git-locks.schema.json) (JSON Schema 2020-12). `git locks schema` prints that document byte-for-byte, and the test suite validates every line it provokes against it, so the contract cannot drift from the code. Consumers can pin the `$id` URL or the file at a tagged commit.

Paths are repo-relative, `./` prefixes are stripped, and absolute or `..` paths are refused. A path ending in `/` is a prefix and covers everything under it. A path may contain spaces; it may not contain a newline. Job ids match `[A-Za-z0-9][A-Za-z0-9._-]*`. A holder is one line of text; any byte but a newline is stored whole and escaped on output. A note, given with `--note`, is one line saying why the lock is held; it rides on the claim, `show`, `list`, `check` and refusal lines, so the claimant who loses reads the reason and not only the name. A ttl is a decimal number of seconds; a leading zero is not octal.

TTL, wait, capacity, and clock values use the same bounded decimal parser: `08` is eight and `010` is ten. TTLs must be positive; waits may be zero. Expiries and wait deadlines must fit `0..9223372036854775807`, with overflow rejected before publication. See [time boundaries](docs/time.md).

`GIT_LOCKS_NOW=<epoch seconds>` fixes lease time for tests; it must be a nonnegative decimal epoch, and an explicitly empty value is an error. System-clock failures are structured `clock` errors. A new snapshot refreshes lease time, so publication retries do not reuse an old expiry. `GIT_LOCKS_PAUSE_BEFORE_COMMIT=<file>` lets tests force interleavings.

## Versioning and releases

`VERSION` in `lib/000-prelude.sh` is the version (it lands in `bin/git-locks` at build time). A push to `main` whose version has no tag yet gets an annotated tag `v<version>` and a GitHub release whose notes are that version's section of `CHANGELOG.md`, with the script and the schema attached, from the `release` job in `.github/workflows/ci.yml`. So a release is: bump `VERSION`, `make build`, write the changelog section, merge.

## Install

```sh
make install            # copies bin/git-locks into ~/.local/bin (a snapshot of this checkout, on purpose)
git locks list          # git dispatches `git locks` to git-locks on PATH
```

`make install` copies rather than symlinks. A symlink into a development checkout makes every uncommitted edit live for every consumer on the machine at once; on 2026-09-15 that turned a half-finished refactor into a transient lock failure in another project's pre-commit hook. Install from a tagged checkout and re-run `make install` when you mean to upgrade.

## Develop

Tests and lint use the [isolated Docker runner](docs/testing.md); no host checkout or Git metadata is mounted into tests.

```sh
make build              # assemble bin/git-locks from lib/*.sh and schema/git-locks.schema.json
make lint               # shellcheck with every optional check on, shfmt
make test               # copied inputs in an offline Docker worker; host needs Docker, Python 3, and Git
make study-observation OBSERVATION_OUT=/work/artifacts/fresh-study   # exits 1 while it exposes #45; exports evidence
git config --local core.hooksPath scripts/hooks   # pre-commit lints, pre-push tests
```

The source is `lib/`, one module per section in numeric order (`000-prelude.sh` through `990-main.sh`); `bin/git-locks` is the build product and is committed, because it is what `make install`, the release asset and a `curl` of the raw file all want: one file, no runtime assembly. Edit under `lib/`, run `make build`, commit both. The suite checks that the committed script is exactly what `lib/` builds, so a `lib/` change without a rebuild fails the pre-push hook and CI. The schema module is generated at build time from `schema/git-locks.schema.json`, so there is one copy of the schema in the repository. Lint runs over the built script rather than the fragments, which do not parse on their own. The Unicode integration test (`test/unicode-locale.sh`) selects an installed UTF-8 locale from `locale -a`, or probes for `C.UTF-8` and `en_US.UTF-8` where there is no `locale` command (musl), and checks JSON stdout separately from shell diagnostics. When no UTF-8 locale exists it reports the skipped integration with the installation prerequisite; with `GIT_LOCKS_TEST_REQUIRE_UTF8=1`, as CI sets it, that skip is a failure instead.

## Limits, stated

- The lock is advisory and time-bounded. Nothing stops a writer that never claimed, and nothing renews a reservation under a long command. The consumer that lands writes (a commit script, a CI step) is where refusal belongs; `check` exits 1 for exactly that use, and a `check` is an observation, not an admission.
- One machine. The store is local; a shared remote would need a fetch before every claim and is out of scope.
- `git rev-parse --path-format=absolute` and `update-ref --stdin` transactions need git 2.31 or newer.
- bash 4 or newer: the store snapshot uses associative arrays. macOS's `/bin/bash` is 3.2; the script's shebang finds a newer bash on `PATH` (Homebrew's, for instance).
- Commands load one immutable root, its tree entries, and record blobs. Git process counts stay bounded, but scanning and index construction grow with the store. All writers contend on the root. Previous per-ref benchmark results are historical, not measurements of this layout.
- Released history is part of the store too: directory tokens outlive their claims, so a store with no live locks can still be slow to read. Historical directory-token measurements have a calibrated generator and an informational runner in [`scripts/benchmark-directory-tokens.sh`](scripts/benchmark-directory-tokens.sh). See the [benchmark protocol](docs/benchmarks/directory-tokens.md) for fixture semantics, resource bounds, and reproducible commands. Timings are not CI gates, and the first retained run is resource-confounded rather than a baseline.
- Every command reads the store once, plans, then commits with expectations. A racer can win in between; the transaction then fails and the command re-plans or reports who won. That is the designed outcome, not a gap.
- The tests are bounded conformance evidence. Twenty racers and one forced interleaving are what the suite shows; they are not a proof over every schedule.

## License

Apache 2.0. See `LICENSE` and `NOTICE`.
