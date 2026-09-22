---
title: "git-locks: path locks made of git refs"
date: 2026-09-15
author: James Ross
description: "How git-locks turns a claim on a file path into a git ref, why that makes locking atomic without a daemon, and what happens when two writers want the same path."
tags: [git, locking, bash, concurrency, jsonl]
draft: false
status: published
project: git-stunts/locks
version: 0.2.0
---

# git-locks: path locks made of git refs

Pure bash and git. No daemon, no lock files in your worktree, no refs in your project. JSON Lines out. This document teaches how it works by following one example from the first claim to a full semaphore. If you only want the commands, jump to [Commands](#commands).

## In sixty seconds

git-locks lets a writer say "I am about to write these paths" and lets everyone else find that out, atomically, using nothing but a git repository as the ledger. A lock is one small text record stored as a git blob; git refs point at it, one ref per locked path and one per job. Claiming is a single `git update-ref` transaction, so a claim on several paths lands whole or not at all, and two claimants racing for one path produce exactly one winner. The loser is told who won. Locks expire, children die with their parents, and a semaphore variant lets up to N holders share a resource. The ledger lives in a separate bare repository under `~/.git-stunts/locks/`, so your project's own refs stay clean.

That is the whole arc. The rest of this document shows each piece with a real transcript.

## The example we will follow

Everything below refers back to this transcript. Two people, alice and bob, work on one repository. Both want to edit `notes/report.md`. Alice claims first. The clock is fixed at `1757980800` (2026-09-15T23:20:00Z) so the numbers stay stable; every line is real output from `git-locks 0.2.0`.

```text
$ git locks claim --job alice-report --holder alice notes/report.md
{"event":"claimed","job":"alice-report","holder":"alice","claimed":1757980800,"expires":1757995200,"paths":["notes/report.md"]}

$ git locks claim --job bob-report --holder bob notes/report.md
{"event":"refused","path":"notes/report.md","holder":"alice","job":"alice-report","expires":1757995200}
(exit 1)

$ git locks check notes/report.md notes/other.md
{"path":"notes/report.md","state":"held","holder":"alice","job":"alice-report","expires":1757995200,"remaining":14400}
{"path":"notes/other.md","state":"free"}
(exit 1)

$ git locks release --job alice-report
{"event":"released","job":"alice-report","paths":1}

$ git locks claim --job bob-report --holder bob notes/report.md
{"event":"claimed","job":"bob-report","holder":"bob","claimed":1757980800,"expires":1757995200,"paths":["notes/report.md"]}
```

Read it once as a story: alice claims, bob is refused and told it is alice who holds the path, `check` says the same thing and adds that fourteen thousand four hundred seconds remain, alice releases, bob claims. Hold onto the refusal line especially. It is the reason the tool exists.

Two foils draw the edges. `notes/other.md` in the `check` call is a path nobody claimed: it reports `free` and does not affect the exit code, which is 1 only because `notes/report.md` is held. And bob's second claim, after the release, is not a retry of the first: the first was refused and left nothing behind, which the next section makes visible.

## The cast: a store, a record, and two kinds of ref

A lock is made of exactly three things, and once you can name them the rest of the tool is arithmetic on them. The store is a git repository that holds nothing but locks. The record is a blob in that repository, a few lines of text. The refs are pointers from stable names to that blob: one named after the job, one named after each locked path. This section introduces each, using alice's claim.

The store is not your project's repository. By default it is a bare repository at `~/.git-stunts/locks/<absolute path of your repository>`, created the first time you claim, so `refs/locks/` never appears in your project and linked worktrees of one repository share one store. `git locks store` tells you where it resolved:

```text
$ git locks store
{"store":"/Users/alice/.git-stunts/locks/Users/alice/work/reports"}
```

Inside that store, alice's claim wrote one blob and two refs. Plain git can show them, which is the point of building on git:

```text
$ git --git-dir "$(git locks store | sed -E 's/.*"store":"([^"]*)".*/\1/')" for-each-ref
75f0c1fb62f9e0b728caf81652be9b5c0693dc04 blob	refs/locks/jobs/alice-report
75f0c1fb62f9e0b728caf81652be9b5c0693dc04 blob	refs/locks/paths/57982dcddc1bb1c76ac1e00f4ff74d76706eecad
```

Both refs point at the same object, `75f0c1f`. The first is named after the job. The second is named after the path, hashed: `57982dc…` is `git hash-object` of the string `notes/report.md`, so a path with spaces or slashes becomes a valid ref name without any escaping. The object they point at is the record:

```text
$ git --git-dir "$(git locks store | sed -E 's/.*"store":"([^"]*)".*/\1/')" cat-file -p refs/locks/jobs/alice-report
schema: git-locks/1
job: alice-report
holder: alice
claimed: 1757980800
expires: 1757995200
paths:
notes/report.md
```

The load-bearing lines are `holder` and `expires`. `holder` is what a refusal reports, and `expires` is what turns a dead session's lock into a free path four hours later. There is no separate index or counter to keep in sync: the set of live locks is the set of refs, and a path is held exactly when a ref named after it exists and points at an unexpired record.

The diagram below shows the store as a git graph. Read each node as a blob, not a commit, and each branch as a ref: git-locks never makes commits, it moves refs between blobs. After alice's claim, two refs share one blob.

```mermaid
gitGraph
  commit id: "empty store"
  branch refs/locks/jobs/alice-report
  checkout refs/locks/jobs/alice-report
  commit id: "75f0c1f alice: notes/report.md" type: HIGHLIGHT
  checkout main
  branch refs/locks/paths/57982dc
  checkout refs/locks/paths/57982dc
  commit id: "same blob 75f0c1f"
```

<details>
<summary>Figure 1 - The store after alice's claim</summary>

Two refs, one blob. `refs/locks/jobs/alice-report` and `refs/locks/paths/57982dc…` both point at blob `75f0c1f`, the record shown above. The `main` line is only the empty store; nothing is ever committed to it.

</details>

| Piece | Where | What it is for |
|---|---|---|
| store | `~/.git-stunts/locks/<repo path>`, a bare repository | holds every lock for one project, outside the project |
| record | a blob in the store | job, holder, claimed, expires, paths |
| job ref | `refs/locks/jobs/<job>` | find a lock by the job that owns it: release, extend, show |
| path ref | `refs/locks/paths/<hash of path>` | find who holds a path: check, refuse |

In summary, a lock is a blob plus the refs that name it, and everything git-locks reports is read straight off those refs. Nothing else is stored, so nothing else can drift.

> **Intuition to carry forward:** a path is held exactly when a ref named after it exists. Claiming is creating that ref. Everything about atomicity follows from how git creates refs.

## What git already guarantees about refs

Before the tool can refuse bob, git has to make refusing possible, and it does so with one command most people never use directly: `git update-ref --stdin`. This section explains the two properties git-locks leans on, because the refusal in the example is nothing more than git enforcing them.

The first property is that a ref update can be conditional. `update-ref` takes an old value alongside the new one, and if the ref does not currently hold that old value, the update fails. A `create` is the special case where the expected old value is "nothing": it fails if the ref already exists. That is a compare-and-swap, and git takes a lock file on the ref while it checks, so two processes cannot both pass.

The second property is that several ref updates can be one transaction. On stdin, `start`, then any number of `create`, `update`, `delete` and `verify` lines, then `prepare` and `commit`. Every line is checked before any is applied, and if one fails, none are applied. This is the exact stanza alice's claim sent, reconstructed from the code path in `bin/git-locks`:

```text
start
create refs/locks/paths/57982dc… 75f0c1f…
create refs/locks/jobs/alice-report 75f0c1f…
prepare
commit
```

The `create` on the path ref is the whole lock. If bob's process had sent its own stanza at the same instant, git would have accepted one `create` on that ref and failed the other, and the failed transaction would have created nothing, including its job ref. A claim on three paths is three `create` lines in one stanza; if one path is taken, the other two are not, either.

```mermaid
sequenceDiagram
  participant A as alice's claim
  participant G as git update-ref
  participant B as bob's claim
  A->>G: start / create paths/57982dc / create jobs/alice-report / commit
  B->>G: start / create paths/57982dc / create jobs/bob-report / commit
  G-->>A: ok, both refs written
  G-->>B: fatal, paths/57982dc already exists, nothing written
  B->>G: read paths/57982dc
  G-->>B: blob 75f0c1f, holder alice
  B-->>B: print refused line, exit 1
```

<details>
<summary>Figure 2 - Two claims race for one ref</summary>

Both claimants send a transaction. Git serialises them at the ref: one `create` succeeds, the other fails and its transaction applies nothing. The loser then reads the ref that beat it to name the holder.

</details>

| Turn | What happened | Why it is safe |
|---|---|---|
| alice sends her stanza | both refs are created | no ref named after the path existed |
| bob sends his stanza | `create` on the path ref fails | git checked the ref under its own lock file |
| bob's job ref | never created | the failed transaction applied nothing |
| bob reads the path ref | finds alice's blob | that is where the holder's name lives |

In summary, git-locks does not implement locking; git does. The tool decides what refs to ask for and turns git's yes or no into a line that names the holder.

> **Intuition to carry forward:** every change git-locks makes is one `update-ref` transaction, and every replacement of an existing ref carries the old value it expects. That is what makes expiry and semaphores safe later on.

## The refusal, traced through the model

With the model in place, bob's refused claim in the example is fully explained, and this section walks it through step by step so nothing is left to trust. The claim reads before it writes; the read is what lets it name alice, and the transaction is what protects the read from going stale.

When bob runs `claim`, the tool first hashes `notes/report.md`, finds `refs/locks/paths/57982dc…` already exists, and reads its blob. The blob says `holder: alice`, `job: alice-report`, and `expires: 1757995200`, which is in the future. So the tool does not even send a transaction: it prints the refusal line on stderr and exits 1. That is the line from the example:

```text
{"event":"refused","path":"notes/report.md","holder":"alice","job":"alice-report","expires":1757995200}
```

Had the ref not existed when bob read, but been created by alice a millisecond later, bob's transaction would have failed instead, and the tool would then read the ref and print the same refusal line. Two different code paths, one contract: a refusal names the holder. The store afterwards is unchanged by bob, which is why the git graph after bob's attempt is Figure 1 again with nothing added.

The other outcome in the example is `release`. Alice's release is also one transaction, this time `delete` lines, each carrying the blob it expects the ref to hold. If some other process had replaced the path ref in the meantime, alice's delete of that ref would fail rather than remove someone else's lock. After the release the store is empty, and bob's second claim is a fresh Figure 1 with his names in it.

```mermaid
gitGraph
  commit id: "empty store"
  branch refs/locks/jobs/alice-report
  checkout refs/locks/jobs/alice-report
  commit id: "75f0c1f alice claims"
  checkout main
  commit id: "alice releases: both refs deleted"
  branch refs/locks/jobs/bob-report
  checkout refs/locks/jobs/bob-report
  commit id: "new blob: bob, notes/report.md" type: HIGHLIGHT
```

<details>
<summary>Figure 3 - Release, then bob's claim</summary>

Alice's release deletes both of her refs in one transaction. Bob's claim then creates his own two refs pointing at a new blob. Nodes are blobs and branches are refs; the `main` line only marks time.

</details>

In summary, a refusal is a read of the winning blob, a release is a guarded delete, and neither leaves anything behind that the next reader could mistake for a live lock.

## Expiry, and why nothing has to clean up

A lock held by a process that died would block its path forever unless something ended it, and git-locks ends it with time rather than with a cleaner. This section shows how `expires` in the record does that job, and what the tool does when it finds an expired lock in its way.

Every record carries `expires`, four hours after `claimed` unless `--ttl` said otherwise. Every read compares it to the clock. `check` reports an expired lock as `expired`, with `remaining: 0`, and exits 0 for that path because it is free to take. `list` and `show` report `state: expired`. Nothing deletes anything until a writer needs the path.

When a claim finds an expired lock on a path it wants, it evicts the whole expired lock inside its own transaction: an `update` on the path ref carrying the expired blob as the expected old value, plus `delete` lines for the expired lock's job ref and its other path refs. If a racing claimant evicted first, the old value no longer matches and this transaction fails cleanly. `sweep` does the same eviction for every expired lock, on demand, and `extend --job` moves a live lock's expiry forward by rewriting its blob and `update`-ing every ref that pointed at the old one.

| Situation | What `check` says | What a claim does |
|---|---|---|
| ref exists, `expires` in the future | `held`, names the holder, exit 1 | refuses, names the holder |
| ref exists, `expires` in the past | `expired`, names the last holder, exit 0 | evicts the old lock and takes the path, one transaction |
| no ref | `free`, exit 0 | creates the ref |

In summary, expiry is a field, not a process. A dead holder's lock is free the moment its time is up, and the next writer removes it as part of taking the path.

## Families and batches: all or nothing across locks

One transaction per claim already makes a multi-path claim atomic; this section extends that to several locks at once, in two forms that share one mechanism. A child lock is tied to a parent so that the family lives and dies together, and a batch claims several independent locks in one stanza.

A child is a claim with `--parent <job>`. Its record gains a `parent:` line, and its transaction gains a `verify` on the parent's job ref, carrying the parent's current blob. The parent must be live and held by the same holder at planning time, and the `verify` makes that true at commit time too: if the parent was released in between, the child's transaction fails. Releasing or sweeping a parent collects every descendant, transitively, and deletes them all in the same transaction, so a child never outlives its parent. The release line lists them as `cascaded`.

A batch is `git locks batch` reading records on stdin, each record in the same blank-line-separated form as the blob itself. Every record is planned into one stanza, and a child may name a parent that appears earlier in the same batch. If any path in any record is held, or any parent check fails, the stanza is never sent and nothing is claimed.

```mermaid
flowchart TD
  P["parent: build (alice)"]
  C1["child: build-docs (alice)"]
  C2["child: build-site (alice)"]
  G["grandchild: build-site-assets (alice)"]
  P --> C1
  P --> C2
  C2 --> G
  R["release --job build"] --> P
  style R fill:#f8d7da,stroke:#c0392b
  style P fill:#f8d7da,stroke:#c0392b
  style C1 fill:#f8d7da,stroke:#c0392b
  style C2 fill:#f8d7da,stroke:#c0392b
  style G fill:#f8d7da,stroke:#c0392b
```

<details>
<summary>Figure 4 - A family released whole</summary>

Releasing `build` deletes the refs of every lock whose parent chain reaches it, in one transaction. The release line reports `"cascaded":["build-docs","build-site","build-site-assets"]`.

</details>

| Form | Guarantee | Verified by |
|---|---|---|
| `claim --parent` | parent live and same holder at commit time | a `verify` line on the parent's ref |
| `release`, `sweep` of a parent | every descendant goes with it | one transaction of `delete` lines |
| `batch` | all records claimed or none | one stanza for every record |
| `release --job a --job b` | both families released or neither | one stanza |

In summary, "all or nothing" is never a loop with a rollback. It is one stanza, and git either applies the whole stanza or none of it.

## Semaphores: capacity instead of exclusivity

A path lock says one holder. Some resources are better described by a number: two GPUs, five build agents. This section shows how git-locks gives a named resource a capacity while keeping the same atomicity, and it needs one new idea, a generation token, that the reader has all the pieces for.

A semaphore is three kinds of ref under `refs/locks/sem/<name>/`. `meta` points at a blob holding the capacity. `slots/<job>` is one ref per holder, pointing at a slot record with the holder and an expiry, exactly like a lock record. And `gen` points at a blob whose only purpose is to change: every transaction on the semaphore writes a fresh generation blob and `update`s `gen` from the generation it read. Two acquirers that both read "2 of 3 live" both try to move `gen` from the same old value; git lets exactly one through, and the other re-reads and finds the semaphore full. Here is the example's semaphore, capacity 2, filled by alice and bob, then refused to carol:

```text
$ git locks sem create gpu --capacity 2
{"event":"created","semaphore":"gpu","capacity":2}
$ git locks sem acquire gpu --job train-1 --holder alice
{"event":"acquired","semaphore":"gpu","job":"train-1","holder":"alice","claimed":1757980800,"expires":1757995200,"live":1,"capacity":2}
$ git locks sem acquire gpu --job train-2 --holder bob
{"event":"acquired","semaphore":"gpu","job":"train-2","holder":"bob","claimed":1757980800,"expires":1757995200,"live":2,"capacity":2}
$ git locks sem acquire gpu --job train-3 --holder carol
{"event":"refused","reason":"capacity","semaphore":"gpu","capacity":2,"live":2}
(exit 1)
```

And the store afterwards, again in plain git:

```text
$ git --git-dir "$(git locks store | sed -E 's/.*"store":"([^"]*)".*/\1/')" for-each-ref refs/locks/sem/
5cd95224… blob	refs/locks/sem/gpu/gen
cc04fb6d… blob	refs/locks/sem/gpu/meta
60ebcc0f… blob	refs/locks/sem/gpu/slots/train-1
cc694fe0… blob	refs/locks/sem/gpu/slots/train-2
```

The `gen` ref is the part that makes capacity a hard limit rather than a hope. Without it, two acquirers could each count two live slots below a capacity of three and each create a slot, giving four. With it, each acquire is `create slots/<job>` plus `update gen <new> <old-I-read>` in one stanza, and only one stanza per generation can commit.

```mermaid
gitGraph
  commit id: "create: meta cap 2"
  branch refs/locks/sem/gpu/gen
  checkout refs/locks/sem/gpu/gen
  commit id: "gen g0"
  commit id: "gen g1 (alice takes train-1)"
  commit id: "gen g2 (bob takes train-2)" type: HIGHLIGHT
```

<details>
<summary>Figure 5 - The generation ref moves once per successful transaction</summary>

Each successful acquire moves `gen` to a fresh blob; a refusal moves nothing, which is why carol does not appear on the line. She read generation `g2`, counted two live slots against capacity two, and was refused before sending anything. Had she raced bob and read `g1`, her `update gen g3 g1` would have failed because `gen` was already at `g2`, and she would have re-read and been refused the same way.

</details>

| Ref | Points at | Changes when |
|---|---|---|
| `sem/gpu/meta` | the capacity | never, after `create` |
| `sem/gpu/slots/<job>` | one holder's slot record, with expiry | acquire, release, eviction of an expired slot |
| `sem/gpu/gen` | a fresh token | every transaction on the semaphore |

In summary, a semaphore is a set of slot refs plus one ref that every writer must move, and the compare-and-swap on that one ref is what keeps the count honest under contention. Twenty racers on capacity three winning exactly three times is a test in `test/test.sh`, not a promise.

## Wrapping a command: claim, run, release

Most callers want the lock only for the duration of one command, and forgetting the release is the common failure. This section shows `with`, which does the three steps and cannot forget the third.

`git locks with --job <id> --holder <name> [--wait <s>] [--sem <name>] <path>... -- <command>...` claims the paths (and a semaphore slot if asked), runs the command, and releases on exit, on failure, and on Ctrl-C or a termination signal, then exits with the command's own status. The command owns stdout; git-locks reports its claim and release on stderr, so a pipeline reading the command's output sees only that output:

```text
$ git locks with --job build --holder alice dist/bundle.js -- sh -c 'echo building'
{"event":"claimed","job":"build","holder":"alice","claimed":1757980800,"expires":1757995200,"paths":["dist/bundle.js"],"record":"3f1c…"}   (stderr)
building                                                                                                          (stdout)
{"event":"released","job":"build","paths":1}                                                                     (stderr)
```

`--wait <seconds>` turns a refusal into a retry once a second until the paths are free or the wait runs out; without it, a held path exits 1 immediately and the command never runs.

In summary, `with` is the shape most scripts should use: the lock's lifetime is the command's lifetime, by construction.

## Output: JSON Lines, always

Every example above showed one JSON object per line, and this section states the contract behind that so a consumer can rely on it. There is no plain-text mode. Stdout carries one object per result, written as each result is known; stderr carries refusals and errors as objects; `git locks help` is a `usage` object; `git locks schema` prints the schema as one line. The single exception is a command wrapped by `with`, which owns stdout while git-locks reports around it on stderr.

Each line matches exactly one definition in [`schema/git-locks.schema.json`](schema/git-locks.schema.json), JSON Schema 2020-12. The pretty file is for people; the test suite parses `git locks schema` and asserts it is the same document, and validates every line it provokes against it. Strings are escaped completely: a control character in a holder or a git diagnostic inside a refusal cannot break the consumer's parser, and that is a test. Exit codes: 0 for done or free, 1 for refused or held, 2 for usage or a store that could not be read.

In summary, the output is the API, the schema is its contract, and the tests are what keep the two the same.

## The contract, in the terms a reviewer asked for

An outside review of 0.2.1 found the guarantees running ahead of the implementation in five places and asked three questions. The fixes shipped in 0.3.0; the answers are the contract.

**What a successful acquisition authorises, and how it is identified.** A claim admits one *acquisition*, and three names apply to it, kept distinct on purpose. The **job id** is a label a person or an orchestrator chooses; it can be reused, and a later claim under the same job is a new acquisition that replaces the old one. The **acquisition id** (`acquisition` on the claim line) is minted by the claim and kept by every rewrite of the record: `extend`, and the family bump a child admission performs on a parent. The **record** (`record`) is the object id of the current version of that record, and changes on every rewrite. `release --job X --acquisition <id>` releases that acquisition and only that one, across any number of renewals; `--record <oid>` releases only if the record is exactly that version. If the job now holds a different acquisition, the answer is `{"event":"nothing","reason":"superseded"}` and nothing moves. `with` remembers the acquisition it made and releases by it, so an invocation that outlives a re-claim of its job name cannot release someone else's lock, and one whose command renewed the lock still releases it. Semaphore slots carry the same two ids.

**What binds the membership you observed to the decision you commit.** Every write is compiled into one transition per ref with the old value it expects, and sent as one transaction; a stale expectation fails the whole transaction and the command re-reads and re-plans a bounded number of times. Family membership is bound through the parent's own record: admitting a child rewrites the parent's blob with a bumped `family` generation and moves the parent's refs to it, so a release or sweep that planned against the old parent fails when a child was admitted meanwhile, and re-plans with the child in view. Semaphore capacity is bound through the semaphore's generation ref the same way. A snapshot is a cached read taken under one `for-each-ref`; it is never treated as a consistent cut, which is why every write carries expectations.

**What `parent` means.** Ownership plus lifetime, not dependency ordering. A child is admitted only under a live parent held by the same holder. Liveness and holder are checked at planning time; what the generation bump adds at commit time is that the parent's record is unchanged since that check, so a release, a renewal or another child cannot have slipped in between. The bump does not re-check the clock: a parent that expires during the microseconds between planning and commit is still bumped, and its family ends at the next sweep or claim over it. The child is released or swept whenever the parent is, by any command, including a claim that evicts an expired parent. Expiry is not inherited: a child keeps its own `expires`, and a parent's expiry ends the family. Renewing a parent (`extend`) keeps its family. Recreating a job name after its release makes a new record with a fresh family, unrelated to the old one.

**What a path identifies.** The lexical form after normalisation: leading `./`, empty segments and `.` segments are removed; absolute paths and `..` are refused. `dir//file` and `dir/./file` are one key. Case, symlinks and hard links are not resolved. A trailing `/` is kept and means a prefix: `dir/` covers every path under it, and is covered by any live lock under it, in both directions and inside the transaction (a directory token ref per level, compared-and-swapped by every claim, is what makes a stale scan fail rather than land); `dir` without the slash is the directory entry itself, a different key, and a prefix does not cover it. Before 0.7.0 the slash was stripped; that is the one normalisation rule that changed.

**What a lock does not do.** It is a cooperative, time-bounded reservation. `with` claims once, runs, and releases; it does not renew, so the reservation can expire under a long command and another claimant may take the path. Give `--ttl` the command's worst case, or renew with `extend` from inside it. A `check` that says free is an observation, not an admission; the protected write needs a claim.

**What a failed read is.** An error, never a free path. If `for-each-ref` or `cat-file` fails, or an object does not parse, the command exits 2 with `{"event":"error","reason":"store-read"}` and reports nothing as free or held.

**What the invariants are, and how to see them hold.** `git locks doctor` reads one snapshot and checks it, writing nothing: every job record decodes and names its own job; every path a record lists has a path ref pointing at that record; every path ref points at a record some job ref points at, and that record lists the path; every child's parent exists, is live and has the same holder, and no parent chain cycles; every semaphore has its meta and gen refs, its records decode, and its live slots fit its capacity. Each broken invariant is one `finding` line as it is found, and the last line states the basis it was checked against, the refs and records of that one snapshot and the clock, so a clean report says what was clean. An unreadable store is an error, never healthy. Repair is not a mode of this command; when a finding needs a hand, the fix is a `release`, a `sweep`, or an explicit `update-ref` on the store by someone who has read the finding.

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
- `git --git-dir "$(git locks store | sed -E 's/.*"store":"([^"]*)".*/\1/')" for-each-ref` shows every lock, and your project's `git for-each-ref refs/locks/` shows nothing.
- `git locks with … -- cmd` exits with `cmd`'s status and releases the acquisition it made, even after Ctrl-C, even if its job name was re-claimed meanwhile.
- `git locks sem show <name>` never reports `live` above `capacity`, under any number of racers.
- Every line you receive, on either stream, parses as JSON and validates against `git locks schema`.

The reference sections below are the map; the story above is why the map looks the way it does.

## Commands

Output is JSON Lines on every command; there is no text mode.

| Command | Does | Stdout line(s) | Exit |
|---|---|---|---|
| `claim --job <id> --holder <name> [--ttl <s>] [--note <text>] <path>...` | atomically lock the paths for the job; re-claiming with the same job replaces its record; `--note` is one line saying why, carried on every line that names the lock | one `claimed` object with `record`; refusals on stderr | 0 claimed, 1 refused, 2 usage |
| `check <path>...` | who holds each path, in argument order; a path under a live prefix, or a prefix with a live lock under it, is held `via` that other path | one object per path as it is examined | 0 all free, 1 any held |
| `list` | every lock, live or expired, with its paths | one object per lock; nothing when empty | 0 |
| `sweep` | delete expired locks | one `swept` object per lock, as it goes | 0 |
| `store` | the resolved store path | one `store` object | 0 |
| `show --job <id>` | one lock in full, with `remaining` seconds | one object, same shape as a `list` line | 0, 1 if no such lock |
| `ttl --job <id>` | the seconds a lock has left | one `{job, expires, remaining}` object | 0, 1 if no such lock |
| `extend --job <id> --ttl <s>` | move the expiry to now + ttl, paths unchanged, atomically | one `extended` object | 0, 1 if no such lock |
| `claim … --parent <id>` | make the lock a child: the parent must be live and held by the same holder (verified inside the transaction); the child is released or swept with it | as `claim`, with `parent` | 0, 1 if refused |
| `batch < records` | claim several locks in one transaction, or none; records are blank-line separated `job:`, `holder:`, `ttl:`, `parent:`, then `paths:` with one path per line | one `claimed` object per record | 0, 1 if any is refused, 2 on a malformed record |
| `release --job <id> [--record <oid>] [--job <id>...]` | release the jobs and all their descendants in one transaction; `--record` releases only that acquisition | one object per job, `cascaded` lists descendants, `nothing` with `reason: superseded` when the record no longer matches | 0 |
| `with --job <id> --holder <name> [--ttl <s>] [--wait <s>] [--parent <id>] <path>... -- <cmd>...` | claim, run the command, release; `--wait` retries once a second until the paths are free or the wait runs out | the command's own stdout; git-locks' `claimed`, `released` and refusals go to **stderr** | the command's exit status; 1 if never acquired; 130/143 on INT/TERM after releasing |
| `version` | tool name and version | one object | 0 |
| `schema` | the JSON Schema every line above conforms to | the schema document | 0 |
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

`GIT_LOCKS_NOW=<epoch seconds>` fixes the clock, for tests; `GIT_LOCKS_PAUSE_BEFORE_COMMIT=<file>` makes every transaction wait for that file, so tests can force interleavings. Timestamps are epoch seconds.

## Versioning and releases

`VERSION` in `lib/000-prelude.sh` is the version (it lands in `bin/git-locks` at build time). A push to `main` whose version has no tag yet gets an annotated tag `v<version>` and a GitHub release whose notes are that version's section of `CHANGELOG.md`, with the script and the schema attached, from the `release` job in `.github/workflows/ci.yml`. So a release is: bump `VERSION`, `make build`, write the changelog section, merge.

## Install

```sh
make install            # copies bin/git-locks into ~/.local/bin (a snapshot of this checkout, on purpose)
git locks list          # git dispatches `git locks` to git-locks on PATH
```

`make install` copies rather than symlinks. A symlink into a development checkout makes every uncommitted edit live for every consumer on the machine at once; on 2026-09-15 that turned a half-finished refactor into a transient lock failure in another project's pre-commit hook. Install from a tagged checkout and re-run `make install` when you mean to upgrade.

## Develop

```sh
make build              # assemble bin/git-locks from lib/*.sh and schema/git-locks.schema.json
make lint               # shellcheck with every optional check on, shfmt
make test               # pure bash, temporary repositories; needs python3 with jsonschema for the schema checks
git config --local core.hooksPath scripts/hooks   # pre-commit lints, pre-push tests
```

The source is `lib/`, one module per section in numeric order (`000-prelude.sh` through `990-main.sh`); `bin/git-locks` is the build product and is committed, because it is what `make install`, the release asset and a `curl` of the raw file all want: one file, no runtime assembly. Edit under `lib/`, run `make build`, commit both. The suite checks that the committed script is exactly what `lib/` builds, so a `lib/` change without a rebuild fails the pre-push hook and CI. The schema module is generated at build time from `schema/git-locks.schema.json`, so there is one copy of the schema in the repository. Lint runs over the built script rather than the fragments, which do not parse on their own. The Unicode integration test selects an installed UTF-8 locale and checks JSON stdout separately from shell diagnostics; when no UTF-8 locale exists, it reports the skipped integration with the installation prerequisite.

## Limits, stated

- The lock is advisory and time-bounded. Nothing stops a writer that never claimed, and nothing renews a reservation under a long command. The consumer that lands writes (a commit script, a CI step) is where refusal belongs; `check` exits 1 for exactly that use, and a `check` is an observation, not an admission.
- One machine. The store is local; a shared remote would need a fetch before every claim and is out of scope.
- `git rev-parse --path-format=absolute` and `update-ref --stdin` transactions need git 2.31 or newer.
- bash 4 or newer: the store snapshot uses associative arrays. macOS's `/bin/bash` is 3.2; the script's shebang finds a newer bash on `PATH` (Homebrew's, for instance).
- Each command reads the store once (`for-each-ref` plus one `cat-file --batch`) and every transaction invalidates that snapshot, so an invocation is a handful of git processes however many locks exist; the test suite pins the counts with a shim that counts spawns. Process count is not time: the snapshot is parsed in bash, so work grows linearly with the store, and `list` renders every record without forking. Measured on 500 locks (macOS, bash 5.3, 0.4.0): `check` 0.28 s, `show` 0.25 s, `claim` 0.33 s, `list` 0.58 s; the same store under 0.3.2 took 0.87 s, 0.85 s, 1.0 s and 6.75 s. A store of hundreds of live locks is fine; one of many thousands will feel the snapshot.
- Every command reads the store once, plans, then commits with expectations. A racer can win in between; the transaction then fails and the command re-plans or reports who won. That is the designed outcome, not a gap.
- The tests are bounded conformance evidence. Twenty racers and one forced interleaving are what the suite shows; they are not a proof over every schedule.

## License

Apache 2.0. See `LICENSE` and `NOTICE`.
