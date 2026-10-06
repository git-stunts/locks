# Git-backed lock evolution: assessment and follow-up

Author: Codex. Date: 2026-10-05. Project: git-stunts/locks.
Original design baseline: `566e577b9e89e191894a8ec7284540e41fdefbdb`.
This report preserves the earlier assessment and records the subsequent source
audit, bounded experiment, and proposed design. Native libraries were not executed;
the Python/Git experiment ran in the project's isolated Docker worker.

## Original assessment

The following is the substantive assessment supplied before the user's follow-up;
the later findings below qualify it. The original design document is preserved
byte-for-byte at its baseline in the Reader delivery alongside this report.

> These ideas can preserve Git as the lock authority. The quoted performance and
> fencing guarantees go much further than the evidence supports.
>
> The current implementation already publishes one immutable tree through
> `refs/locks/state`; the separate directory-ref description is outdated.

| Proposal | Original assessment |
| --- | --- |
| Native Git library | Plausible improvement. It removes subprocess launches, but storage writes, validation, contention, and retries remain. Sub-millisecond acquisition needs measurement. |
| Automatic GC | Useful maintenance, requiring retention and resource policies. Old snapshots and unpublished candidates can be unreachable while operations still need them. |
| Hierarchical intentions | Promising indexing design. A single `.intent=IX` marker needs ownership/counting and expiry bookkeeping so releasing one child preserves other children's intentions. Avoiding a descendant scan does not make the complete operation constant-time. |
| Notification daemon | Compatible with Git authority if notifications only trigger another acquisition attempt. It needs subscription-race handling, recovery from missed events, and expiry timers: leases can expire without any ref change. |
| OID fencing tokens | Incorrect as proposed. Hashes identify content; they do not increase with acquisition order. Even an unpublished candidate has an OID. |

> Real fencing can still be Git-backed: increment a persistent generation counter
> in the same CAS that grants ownership. The protected service must atomically
> enforce that generation when accepting writes. Once it accepts generation 42,
> it rejects delayed writes carrying 41. Killing a process cannot retract an
> already-sent request.

The original design note linked primary Git, gitoxide, inotify, and Chubby
references. Its three Mermaid diagrams were source-reviewed, not rendered.
At that original checkpoint only documentation changed; no runtime experiment had
yet been run. The experiment described below happened afterward.

## Follow-up 1: native libraries need an operation-by-operation gate

The [native-library audit](../native-library-audit.md) inventories all 12 production
Git command families, including initialization, subject/store configuration,
discovery, raw symbolic-ref checks, object reads/hashing/writes, private-index tree
construction, normal root CAS, and offline multi-ref migration. It maps candidate
APIs and preserves exact upstream source commits.

A concrete mismatch was found in inspected gitoxide source: `MustNotExist` permits
an existing reference if its target already equals the requested new target.
Git's strict zero-old-OID update refuses this, verified in both hash formats by
the experiment. This is a source-level mismatch plus a Git-side test; no native
library reproduction or duplicate-grant failure is claimed.

libgit2 labels SHA-256 experimental, and its inspected Rust binding gates it behind
`unstable-sha256`. gix has explicit SHA-256 support, but it must be enabled. Both
libraries document partial multi-ref commit failure. Isolated configuration,
error classification, durability, and backend parity also need adapter tests.

Recommendation: retain CLI plumbing now. A measured hybrid could move object
reads and tree construction into a native library while preserving Git CLI
publication and other unresolved operations. No evidence here establishes the
historical blockers in git-warp or git-cas, and no fully native rewrite is approved.

## Follow-up 2: empty-parent commits do not retain siblings

The [GC experiment](../studies/hierarchical-intentions/README.md#gc-experiment-an-empty-parent-is-not-a-retention-root)
created two state commits sharing an empty parent. Only the new sibling was
referenced. Immediate GC removed the older sibling and its unique tree, and also
removed an unpublished candidate. Making the old state the parent of the live
new state retained both. Both SHA-1 and SHA-256 passed these assertions.

Reachability runs from refs through object edges. A common empty parent does not
point back to its children. The production root currently points to a tree, which
has no commit parent. A linked history would retain successful snapshots, but grow
until deliberately truncated and still not retain unpublished candidates.

Recommendation: use explicit quiescence for destructive pruning for now. Online
reclamation needs a pin/retention protocol covering snapshot selection, candidate
construction, publication, and reader retirement. OIDs inside JSON strings are
not Git reachability edges. Immediate GC was used only in disposable test stores.

## Follow-up 3: hierarchical intentions were tried

The [prototype and evidence](../studies/hierarchical-intentions/README.md) implement
an immutable component trie with separate exact/prefix reservations, acquisition
membership, and maximum-expiry summaries. It persists actual Git trees, retains
unchanged subtree OIDs, and publishes by one root CAS.

Results: 400 seeded updates, 34,000 flat-oracle comparisons, and 6,800 immutable
prior-snapshot query checks passed. Both Git hash formats passed round-trip,
strict-create, stale-CAS/replan, packed-ref, structural-sharing, and forged-summary
checks. A prefix query over 128 children visited two in-memory nodes; that is not
a latency benchmark.

This is an isolated index experiment, not production integration. Loading and
validating the full tree still scans it; wide-node updates and holder reporting
need further design. Job replacement, batch/family/eviction policy, semaphores,
and migration remain the existing planner's responsibility. The next safe
integration boundary is a derived index checked against the current planner.

## Follow-up 4: notifications remain an optimization

The [updated design](../design-options.md) preserves register-before-recheck,
missed-event recovery, timers for expiry without writes, and retrying Git admission
after each notification. No daemon was implemented or benchmarked.

## Follow-up 5: concrete fencing proposal

The [fencing proposal](../fencing-proposal.md) recommends an explicit resource
adapter, a persistent Git-issued generation, and an activation handshake before
launching protected work. Activation must drain or invalidate earlier in-flight
mutations; every later write atomically validates the active token with its effect.
It must survive adapter restart, reject delayed activation, and handle authority
and adapter rollback without accepting stale owners.

Git remains the grant authority. The resource's durable high-water mark is
enforcement metadata. An OID remains a snapshot receipt, not an ordered token or
proof of current ownership. Exact TTL revocation and hierarchical fencing are
not implied. Generic shell commands cannot be fenced without control over their
actual writes. No resource adapter or generation counter was implemented here.

## Validation and resources

The second guarded experiment exited zero with no guard error. Its sampled peaks
were 3,342,336 bytes under `/work` (including copied inputs), 282,624 under `/tmp`,
and 12,288 under `/evidence`; output was 1,293 bytes. Minimum Docker backing free
space was 687,863,148,544 bytes. Host free space remained about 674 GiB. The reused
worker stopped and its shared reservation was released. No new image, worker,
volume, native dependency installation, or compiler cache was created.

The [launch contract](../studies/hierarchical-intentions/launch-contract.md) and
checked-in [result](../studies/hierarchical-intentions/evidence/result.json),
[resource](../studies/hierarchical-intentions/evidence/resources.json), and
[isolation](../studies/hierarchical-intentions/evidence/isolation.json) receipts
bound the evidence. These are focused experimental checks, not a full production
suite, a native-library parity test, a concurrent stress campaign, or a formal
proof. The Mermaid diagrams have not been rendered in this turn.
