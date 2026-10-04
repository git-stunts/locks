# Wrapper lifetime

`with` is a synchronous command launcher. Its reservation authority is Git;
there is no daemon, external mutex, heartbeat service, or filesystem fence.

## Admission and cleanup

The wrapper generates one acquisition identity and plans every requested path
and optional semaphore slot against one state root. They publish together.
Waiting holds no partial slot, and one `--wait` deadline covers the whole
admission. A live job or slot with the same name is refused with `reason: active`;
a second wrapper cannot take over the first wrapper's running command.

After publication, the wrapper reads another snapshot and checks that every
requested acquisition remains present, matches its identity, and is live. A
failed check prevents command launch. Once the command ends, cleanup reads the
state again and conditionally publishes all still-owned releases together.
Root contention causes both ownership checks and release planning to run again.
A replacement acquisition is preserved, including one published during cleanup.
Renewal and family updates may change record OIDs without changing ownership.

The wrapper reports `lost` for each missing, superseded, or expired acquisition.
An expired acquisition still owned by the wrapper is removed during cleanup.
`command_status` records the wrapped command's exit status, or null when it did
not launch. An operational failure to verify ownership, launch the command, or release ownership produces the
underlying error and a `with-failed` line. Failed cleanup cannot become success.

| Situation | Exit |
| --- | ---: |
| Admission refused, including an active job | 1 |
| Invalid input or operational admission failure | 2 |
| Ownership lost or verification/cleanup failed | 125 |
| INT or TERM received | 130 or 143 |
| Healthy lifecycle | Wrapped command's status |

Cancellation keeps its signal status even if cleanup also fails; the failure is
reported on stderr. A wrapped command can itself return 125; the `lost` or
`with-failed` diagnostic distinguishes a wrapper failure. Lifecycle JSON uses
stderr; the command retains its own stdin, stdout, and stderr.

## Cancellation

Bash job control puts the command in a separate process group. A short-lived
Bash supervisor preserves terminal input, foreground/background ownership, and
Ctrl-Z/resume behavior. The system `ps` utility supplies the caller's process
and terminal group IDs (the `pgid` and `tpgid` fields on Linux and macOS). A
private start gate delays execution until the wrapper knows the command group's
PID. Failure to establish this launch boundary prevents command execution.

INT and TERM received by the wrapper are forwarded to the command group. After
a two-second grace period, the wrapper sends KILL to that group and waits for
its supervisor before cleaning up reservations. Remaining ordinary descendants
are also stopped when the command finishes; background work must not outlive
its wrapped command. A small exit receipt preserves command status even when
Bash's foreground-job handling aborts on an interrupt. These Bash processes
exist only for the invocation, with no persistent service or external authority.

If a signal arrives during a Git admission publication, cleanup waits for that
operation to finish so it can release the acquisition it may have published.
A signal sent to the whole caller group can destroy the publication receipt;
cleanup still checks the identity allocated before admission.
A pending signal prevents command launch even when publication succeeded before
the parent received the receipt. Filesystem delays can delay Git operations.
SIGKILL cannot be trapped. Commands that detach into other process groups are
outside this cancellation mechanism and must manage their own lifetime.

## TTL remains a cooperative obligation

There is no automatic renewal or termination at TTL expiry. A command that keeps
writing after expiry may overlap a later owner; reporting that loss cannot undo
its writes. Choose a suitable TTL and use acquisition-guarded renewal when the
runner needs it. Clock changes, scheduling pauses, and the gap between verifying
ownership and executing code cannot be made atomic with a Git ref publication.
External writes require a resource that can enforce fencing if that guarantee is
needed. An administrative release or replacement can also revoke ownership while
the command runs. `check` is an observation, never launch authorization.

## Evidence

The guarded Docker suite checks path and semaphore loss, exact expiry, combined
admission, active-job refusal, three forced stale-admission races, a replacement
during cleanup, expiry/replacement before launch, cancellation after publication
but before its receipt, forwarding to child processes, forced termination of a
stubborn group, cleanup and launch failures, background terminal ownership, terminal restoration,
Ctrl-Z/resume, group cancellation across publication, and stdin/status preservation. The
cooperating-worker example verifies the updated supersession exit and leaves
its replacement acquisition intact.
