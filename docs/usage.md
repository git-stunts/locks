# Commands and usage

git-locks provides advisory reservations. Every worker must use the same store, acquire before work, and stop or renew before expiry.
Start with the [README](../README.md) for installation and a command wrapper.

## Paths and stores

Run commands from the subject repository's root. Path keys are lexical, repo-relative names; they do not identify filesystem objects.

| Input | Meaning |
| --- | --- |
| `src/main.sh` | One path. |
| `src/` | Every path below `src/`. A live child path also blocks this prefix. |
| `src` | The directory entry itself; distinct from `src/`. |
| `./src//./main.sh` | Normalizes to `src/main.sh`. |
| Absolute paths or `..` segments | Refused. |
| Literal `*`, `?`, or brackets | Ordinary characters, not patterns. Quote them to prevent shell expansion. |

Paths must be valid UTF-8. They can contain spaces but cannot contain newlines. Case, Unicode composition, symlinks, and hard links do not normalize to one key.
All workers must agree on names, even when two names address the same file.

Holder names, notes, acquisition guards, batch input, and the selected store pathname must also be valid UTF-8. Malformed text is refused with exit 2 before any reservation is published. Existing authority records with malformed UTF-8 block ordinary operations; `doctor` reports the invalid records without changing them. Error output replaces each invalid diagnostic byte with U+FFFD, so external errors still form valid JSON. Reservation keys are never repaired or replaced. A wrapped program keeps control of its own arguments and output.

Batch input must not contain NUL bytes. A bad batch fails with exit 2 before any reservation is written. Stored records with NUL bytes block all state reads, including `doctor`, with a structured `store-read` error. The CLI never removes NUL bytes to make a record valid. Wrapped programs retain control of their binary input and output.

The default store is a separate bare repository under `~/.git-stunts/locks`.
The subject repository's common directory determines its store; linked worktrees share it.
Project refs remain separate from lock state.

```sh
git locks store
```

`GIT_LOCKS_STORE` or Git configuration `locks.store` can select another store.
An explicit shared store lets different repositories coordinate named resources.
Relative overrides use a shared repository anchor. See [store selection and initialization](store-initialization.md) before changing an existing configuration.

## Identity, renewal, and release

A reservation has three identifiers:

| Identifier | Meaning |
| --- | --- |
| `job` | A caller-selected name. A later claim can reuse it. |
| `acquisition` | One reservation lifetime. Renewal preserves it. |
| `record` | The stored version. It changes when record contents change. |

Use a unique job name for each concurrent operation. Capture the `acquisition` from its successful claim receipt.
Use that identifier for renewal and release, so an old worker cannot change a replacement reservation.

```sh
git locks claim --job report-1 --holder alice --ttl 300 \
  --note 'update the report' notes/report.md notes/index.md
# Save the acquisition value from the claimed JSON object.
git locks extend --job report-1 --ttl 600 --acquisition '<saved-acquisition>'
git locks release --job report-1 --acquisition '<saved-acquisition>'
```

A claim acquires all requested paths together, or none.
A refusal names the conflicting holder, job, expiry, and note when present.
`check` reports an observation; another worker can claim immediately afterward.

An acquisition expires when the current time reaches `expires`.
`extend` refuses an expired or replaced acquisition. It sets expiry to the current time plus TTL, which can shorten an existing deadline.
Without `--acquisition`, renewal addresses whichever live reservation currently has that job name.
`release --record` requires one exact version and can become stale after renewal.
An explicit `--acquisition` must be a nonempty UTF-8 line. Empty or multiline guards return exit 2 without releasing any jobs or semaphore slots.
An unguarded release addresses the current job. Holder names do not authenticate callers.
See [time and integer boundaries](time.md).

## Command wrappers

```text
git locks with --job <id> --holder <name> [--ttl <s>] [--wait <s>]
  [--sem <name>] [--parent <id>] [--note <text>] [<path>...] -- <command>...
```

Put the actual command on one shell line, or use shell continuation characters.
`with` acquires all paths and the optional semaphore slot in one publication.
A live job or slot with the same name causes refusal. The wrapper checks ownership before it starts the command.

`--wait` retries contention once a second within one deadline. A failed attempt holds no partial reservation.
Without it, refusal exits immediately and the command does not start.

The command retains stdin, stdout, and stderr. git-locks sends its lifecycle JSON to stderr.
After the command exits, the wrapper attempts release using its acquisition identity.
Healthy cleanup preserves the command's status. Lost ownership or failed lifecycle checks return 125 with a diagnostic.

INT and TERM reach the command's process group. After two seconds, the wrapper kills any remaining group members and attempts cleanup.
Cancellation returns 130 or 143, including when cleanup also fails.
Ordinary background descendants must not outlive the command. Detached process groups require separate supervision.
SIGKILL or store failures can prevent cleanup.

**The wrapper neither renews automatically nor terminates work at TTL expiry.**
Another worker can acquire after expiry while the first command still runs.
Use a deadline below TTL or guarded renewal with a supervisor that stops work when renewal fails.
No reservation can undo writes after ownership loss. See [wrapper lifetime](wrapper-lifetime.md) for the complete boundary.

## Families and batches

`claim --parent <job>` creates a child reservation under a live parent with the same holder.
A parent's release or removal through expiry also removes its descendants in the same publication.
Children keep their own expiry; they do not inherit the parent's expiry.
A parent's expiry ends the family's authority.
The state comparison detects data changes, but does not recheck the clock at publication.

`claim` and `batch` refuse replacement of a job that has stored descendants, including expired descendants.
Use `extend` to renew a parent without changing its acquisition.
Release or sweep descendants before replacement, or release the parent to end the entire family.
A leaf can be replaced or moved under another live parent with the same holder.
Self-parenting and cycles cause refusal.

These rules also apply within a batch.
Replacing a leaf before adding its child is allowed. Adding a child before replacing its parent is refused.
A batch cannot replace a parent with existing descendants, even if it also replaces those descendants.

`batch` reads records from stdin. Separate records with a blank line:

```text
job: chapter-1
holder: alice
ttl: 300
paths:
notes/chapter-1.md

job: chapter-2
holder: alice
ttl: 300
paths:
notes/chapter-2.md
```

Pass this input to `git locks batch`. Optional `parent:` and `note:` fields precede `paths:`.
All claims publish together, or none.
Refusals for cycles or stored descendants use `reason: parent` and `detail: cycle` or `detail: descendants`.

## Semaphores

A semaphore limits concurrent reservations with a fixed number of slots.
All workers must use the same store and semaphore name.

```sh
git locks sem create gpu --capacity 2
git locks with --sem gpu --job "gpu-$$" --holder "${USER:-worker}" \
  --ttl 60 --wait 10 -- sh -c 'printf "%s\n" "slot acquired"'
git locks sem show gpu
```

This example holds one slot for its command.
A capacity-two semaphore admits at most two live slots in its state.
It does not limit CPU, memory, disk, or request rate, and it cannot stop work after expiry.

A semaphore and a path with the same name are separate resources.
Workers must agree on one admission method for a shared resource.
`with` can acquire both a slot and paths together when the command needs both.

## Command reference

Each command supports `--help`. Help also uses JSON Lines.
The tables summarize syntax; the sections above explain lifetime and identity conditions.

| Command | Result |
| --- | --- |
| `claim --job <id> --holder <name> [--ttl <s>] [--parent <id>] [--note <text>] <path>...` | Acquire every path, or none. Reuse can replace the job unless it has stored descendants. |
| `check <path>...` | Report each path as free or held. |
| `list` | Report all reservations, including expired ones. |
| `show --job <id>` | Report one reservation and its remaining lifetime. |
| `ttl --job <id>` | Report expiry and remaining seconds. |
| `extend --job <id> --ttl <s> [--acquisition <id>]` | Renew a live reservation. |
| `release --job <id> [--record <oid>] [--acquisition <id>] [--job <id>...]` | Release jobs and descendants. Conditions apply to the preceding job; both must match if both are supplied. |
| `batch < records` | Acquire the input records together, or none. |
| `with … -- <command>...` | Acquire, run, and attempt release. See the wrapper syntax above. |
| `sweep` | Remove expired reservations. |
| `store` | Report the resolved store location. |
| `doctor` | Check one snapshot without repair. Report findings and the inspected basis. |
| `migrate --offline` | Import legacy state after all old clients stop. See the [upgrade procedure](state-protocol.md#upgrade). |
| `version`, `schema`, `help` | Report version, output schema, or usage. |

| Semaphore command | Result |
| --- | --- |
| `sem create <name> --capacity <n>` | Create a semaphore. Refuse an existing name. |
| `sem acquire <name> --job <id> --holder <name> [--ttl <s>] [--wait <s>]` | Acquire a slot. Reuse refreshes that job's slot. |
| `sem release <name> --job <id> [--record <oid>] [--acquisition <id>]` | Release a slot, subject to the supplied identity conditions. |
| `sem show <name>`, `sem list` | Report capacity and live slots. |
| `sem delete <name>` | Delete a semaphore with no live slots. |

## Output and errors

git-locks writes one JSON object per line. Ordinary results use stdout; refusals and errors use stderr.
For `with`, lifecycle output uses stderr and the command owns stdout.
There is no plain-text mode.

[`schema/git-locks.schema.json`](../schema/git-locks.schema.json) defines the output with JSON Schema 2020-12.
`git locks schema` prints the same document on one line.
The tests compare both documents and validate the output cases they exercise.
A consumer can pin the schema at a tagged commit.

| Exit | Meaning |
| --- | --- |
| 0 | Success; `check` found every requested path free. |
| 1 | Refusal, a held path, a missing requested item, or doctor findings, depending on the command. |
| 2 | Invalid input or a store/clock operation failure. |
| 125 | Wrapper ownership loss or a failed lifecycle check. |
| 130 / 143 | Wrapper cancellation through INT / TERM. |

After healthy cleanup, `with` returns its command's status, which can have any of these values.
Inspect JSON diagnostics to distinguish wrapper failures from command failures.
A guarded release of a superseded acquisition reports `event: nothing`, `reason: superseded`, and exits 0.

Read failures never mean a free path. Permanent write failures return errors instead of indefinite retries.
A persistent Git ref lock causes an error; git-locks does not delete it.
See [store errors](store-errors.md) and [state integrity and recovery](state-integrity.md).

Job IDs match `[A-Za-z0-9][A-Za-z0-9._-]*`.
Holder names and notes contain one line; JSON output escapes control characters.
TTL is a positive decimal integer; wait duration can be zero. Leading zeros do not mean octal.
Expiry, wait deadlines, capacity, and clock values must fit `0..9223372036854775807`; capacity must be positive.
See [numeric boundaries](time.md) for overflow checks and test-only clock controls.

## More examples and design

The [cooperating-worker example](../examples/cooperating-workers/README.md) exercises conflict, unrelated work, renewal, failure, and expiry in an isolated store.
Its controlled results do not establish external adoption or correctness for every execution.

The [state protocol](state-protocol.md) explains atomic publication through one Git ref.
The [trust boundary](store-trust.md) explains Git configuration isolation and disabled store hooks.
Historical performance measurements describe the old per-ref layout; they do not measure the current state-tree implementation.
See the [benchmark protocol](benchmarks/directory-tokens.md) before interpreting those results.
