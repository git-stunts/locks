# State integrity and recovery

A coherent root can still contain inconsistent records after a bad import,
manual edit, or an older implementation's bug. A single root comparison does
not establish that its contents satisfy the reservation rules.

Before rendering reservations or planning a mutation, git-locks checks:

- Every job's path has an index entry pointing at that exact job record.
- Every path index is accounted for by an existing job and one of its paths.
- Parents exist, have the same holder as their children, and form no cycle.
- Each semaphore has capacity metadata and a generation token; its live slots
  do not exceed that capacity.
- Live paths owned by different jobs do not overlap through a prefix.
- The root contains only recognized logical entry types and decodable authority.

All checks use one immutable snapshot and one lease-clock sample. Path hashes
are computed with one Git invocation per uncached batch, using private temporary
files and numeric filenames streamed on stdin. This avoids one Git subprocess
per record and command-line limits; checked hashes are reused by the planner.
Family traversal visits each parent edge once. Prefix checks look up path
ancestors rather than comparing every pair of paths.

An inconsistency produces a structured `store-read` error and exit 2, before
reservation output, new objects, publication, or wrapped-command launch. This
applies to queries and to ordinary release and sweep commands as well as
acquisition. They do not infer which damaged index should win or silently repair
the store. `store`, help, version, and schema do not interpret reservations.

Expiry alone is allowed. A parent can expire while its child remains stored;
ordinary sweep must still be able to remove that family. Expired semaphore slots
do not consume capacity. A single job may claim both a prefix and paths beneath
it. Historical directory tokens and semaphore generation contents remain opaque.
Clock changes can affect which reservations count as live; a resulting live
conflict is refused at the observed clock.

## Diagnosis and recovery

`doctor` reads the same immutable state but continues to report findings for a
damaged store. Its `path-overlap` finding names conflicting live prefixes.
Diagnosis never repairs state. An expired parent is a diagnostic finding even
though it is not structural damage and normal sweep remains permitted.

Stop all users of the store before repairing it and preserve a backup. Use
doctor's findings to identify the affected records and indexes. Restoring an
earlier root requires determining that it does not erase reservations still in
use; a root rollback is not an automatic safe repair. Any deliberate replacement
must rebuild a mutually consistent set of entries and pass `doctor` before
clients resume. There is no automatic repair command or background service.

The Docker regression constructs damaged trees independently with `mktree`.
Twelve corruption modes are checked against sixteen query/mutation entry points,
with unchanged root/object storage and no command launch as the oracle. Doctor
must diagnose each fixture. Positive controls cover ordinary expiry, sweep,
capacity after slot expiry, and overlap owned by a single job.
