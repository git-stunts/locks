# Time and integer boundaries

All integer inputs use one decimal grammar: ASCII digits only, with leading
zeros allowed. Signs, expressions, whitespace, and values above
`9223372036854775807` are refused before arithmetic. Stored numeric fields use
the same parser. Output and newly written records use canonical decimal.

| Input | Minimum | Additional condition |
| --- | ---: | --- |
| TTL | 1 | `now + ttl` must fit the signed 64-bit range |
| Wait duration | 0 | `system clock + wait` must fit that range |
| Semaphore capacity | 1 | Fits that range |
| Test clock override | 0 | Fits that range; an explicitly empty value is invalid |

The program checks the remaining range before adding a duration. It never tries
an overflowing addition and then checks the wrapped result. The largest valid
TTL therefore depends on the clock: at epoch 8, the largest expiry is obtained
with TTL `9223372036854775799`.

Invalid arguments and `GIT_LOCKS_NOW` values return a structured `usage` error,
exit 2. An invalid override is rejected before resolving or creating a store.
An overflowing claim, renewal, batch, or slot acquisition publishes nothing;
`with` never starts its command for rejected time input. A failed batch may
leave unreferenced candidate blobs from earlier records, but never a partial
reservation.

## Lease time

Ordinary commands obtain Unix seconds from `date +%s`. The system clock must
produce a nonnegative integer in the same range. A failed command or malformed
sample produces a structured `clock` error, exit 2, instead of raw Bash output
or an invalid reservation record.

One sample is cached for a snapshot's decisions. Reading a new snapshot clears
the cached time: a writer that loses publication, or a waiter taking another
attempt, checks liveness and calculates expiry again. An expiry that would
overflow after a retry is refused even if it fitted during the first attempt.

`GIT_LOCKS_NOW` is a test override, normalized with the same parser. It fixes
lease time but does not change the wait clock. Omit it to use the system clock;
setting it to an empty string is an error.

## Waiting

`--wait 08` means eight seconds; `--wait 010` means ten. Zero allows one attempt.
Each acquisition's wait window uses the system wall clock. Invalid samples,
failed clock reads, and a detected backward step while retrying return a
`clock` error. A forward step reaching the deadline ends the wait. A wrapper
that already obtained a semaphore slot attempts to release it if its later
path wait fails.

This does not make lease time monotonic across processes, recheck the clock
atomically with a Git ref update, renew a running command, or fence filesystem
writes. Those are separate lifetime obligations. The clock can advance while
planning, Git is publishing, or the scheduler has paused a process.

## Regression evidence

`test/time-arithmetic.py` compares emitted values with Python's integer
arithmetic. It covers every TTL writer, safe and overflowing boundaries,
leading zeros, hostile numeric expressions, malformed system clocks, wait
deadlines, and wrapper cleanup after a clock failure. Controlled publication
races prove that both path and semaphore retries use fresh lease time and
recheck overflow. Every test runs through the hermetic Docker worker.
