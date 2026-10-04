# Store failures and contention

A refused reservation and a failed store operation have different meanings:

| Result | Exit | Meaning |
| --- | ---: | --- |
| Held path, full semaphore, or conflicting family policy | 1 | Admission was refused |
| Exhausted stale-publication retries | 1 | Other writers kept invalidating the plan |
| `store-read` | 2 | The state or a required path hash could not be read reliably |
| `store-write` | 2 | A record, successor tree, or publication could not be written |

Errors are JSON Lines on stderr. Git diagnostics, including newlines and quotes,
are escaped inside the `detail` string. The command never reports an acquisition
as successful after a publication error. A wrapped command is not launched when
its admission fails operationally.

## Publication failures

The runtime forces Git's C locale. Only an expected-root mismatch, or creation
losing to an existing root, requests a fresh snapshot and plan. Permission errors,
invalid ref updates, hook rejections, and unrecognized failures return a
`store-write` error immediately. They do not consume the 200 stale-plan retries.

Git's files backend uses a short-lived `refs/locks/state.lock` during publication.
The file itself cannot tell git-locks whether its owner is active or has crashed.
For this one condition, git-locks retries the same candidate at most six times,
with five 20 ms pauses. It does not rebuild records between those attempts. If
another writer publishes in the meantime, the root comparison detects the
change and the caller replans normally. If the lock persists, the command exits
2 and leaves the lock file untouched. These bounds limit attempts and deliberate
sleep time; filesystem delays and scheduling remain outside the timer.

Publication and migration override Git's `core.filesRefLockTimeout` and
`core.packedRefsTimeout` to zero for that command only, so repository settings
cannot add hidden or infinite retry loops. Git documents zero as disabling its
internal retry in the [configuration reference](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corefilesRefLockTimeout).

Never remove another writer's lock as part of ordinary acquisition. Recovery of
an abandoned lock requires establishing that its writer has stopped. `doctor`
currently diagnoses reservation data, not whether a publisher is active or the
store is writable.

## Failure coverage

The Docker suite runs as an unprivileged user and exercises real read-only object
and ref directories, a planted persistent ref lock, and a transient lock released
by its owning test process. A logging Git adapter injects permanent publication
failures across claim, batch, extend, release, sweep, wrapper admission, every
semaphore writer, and offline migration. It records the real Git transaction
inputs for lock cases.

Assertions cover structured exit status, unchanged authority in these fault
cases, bounded publication attempts, identical candidates during lock retries,
and the number of new record blobs. Existing forced races and the observation
study continue to check successful replanning and exclusion.
