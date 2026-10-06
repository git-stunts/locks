# Proposal: Git-issued generations with resource-enforced fencing

Status: design proposal, not an implemented flag or accepted wire protocol.
The current CLI remains advisory. This proposal preserves Git as the authority
that grants reservations and orders acquisitions; the protected resource enforces
which granted acquisition may mutate its data.

## Recommendation

Build fencing only with a concrete resource adapter that can reject stale writes
at the point of mutation. Do not ship an environment variable named “fencing
token” as if that alone fenced arbitrary shell commands. Keep acquisition IDs
for guarded release/renewal, and keep OIDs as optional snapshot receipts.

For a first implementation, support one explicitly configured exclusive resource
domain with one adapter. For example, an artifact-publishing service could own
the destination and accept a generation on each publish. Every competing write
must pass through that service, or the service's backing store must enforce the
token transactionally. Existing unrestricted filesystem writes cannot gain this
guarantee from an extra CLI option.

## Issuance in Git

Add a versioned store header and persistent generation counter to the immutable
state tree. A successful fenced acquisition increments the counter and records
the assigned generation, resource domain, job, and acquisition identity in the
same successor root. Publish that root with the existing expected-old-root CAS.
On failure, discard the candidate grant and replan. A losing candidate's proposed
generation is not a token that a client may use.

A conceptual token is:

```json
{
  "protocol": "git-locks-fence/1",
  "authority": "configured-store-incarnation",
  "domain": "artifact-publisher/project-a",
  "generation": "42",
  "acquisition": "opaque-acquisition-id"
}
```

The decimal string avoids loss of integer precision in JSON consumers. Use checked
integer arithmetic, fail closed at exhaustion, and never reset the counter on
release, sweep, or empty-store cleanup. Renewal preserves the acquisition's
generation. Reacquisition receives a larger generation. The authority identifier
is provisioned with the adapter; it is neither a password nor an ordered epoch.

Return the published root OID separately as evidence identifying the grant's
snapshot. Do not embed that same root OID in the state tree it hashes: that would
create a self-referential hashing requirement. An OID alone does not attest that
a candidate was ever published or that its owner is still current.

## Activation before launching protected work

The adapter exposes an activation operation and protected mutations. Its durable
state includes the accepted authority incarnation and the highest activated
generation/acquisition for each domain. The adapter validates issuance through a
trusted integration; accepting arbitrary client-supplied integers would allow a
client to invent a huge generation and block valid owners.

1. The CLI acquires in Git and receives the published grant.
2. The adapter verifies that grant against the configured authority and activates
   it only if its generation is newer, or exactly matches an already activated
   acquisition for an idempotent retry. Lower generations and conflicting tokens
   at the same generation are rejected.
3. Activation is serialized with protected mutations. It must wait for an already
   admitted older mutation to finish, or cause that mutation's eventual commit to
   fail a generation check. It must not acknowledge while an old request can still
   commit afterward without another check.
4. Only after activation acknowledgement does the wrapper start new protected work.
5. Each mutation validates the full active token and applies its effect under the
   same resource transaction or serialization boundary. Checking, unlocking, and
   then writing would recreate a time-of-check/time-of-use race.

```mermaid
sequenceDiagram
    participant A as Old worker
    participant G as Git authority
    participant B as New worker
    participant R as Resource adapter
    Note over A: Grant 41 expires; old request may still be delayed
    B->>G: Acquire domain
    G-->>B: CAS publishes grant 42
    B->>R: Activate validated grant 42
    R->>R: Drain or invalidate older mutations; durably activate 42
    R-->>B: Activation acknowledged
    B->>B: Start protected work
    A->>R: Delayed mutation with grant 41
    R-->>A: Reject stale token
    B->>R: Mutation with grant 42
    R->>R: Check active token and commit effect atomically
    R-->>B: Success
```

The ordering is numerical, not derived from OID sorting or wall-clock time.
It resembles the generation/recipient-validation boundary in
[Chubby's sequencers](https://research.google.com/archive/chubby-osdi06.pdf).

## Failure and recovery rules

| Event | Required behavior |
| --- | --- |
| CLI loses the CAS | No usable grant and no child launch; re-read and replan. |
| CLI crashes after grant but before activation | Reservation may remain until release/expiry. No protected child was started. |
| Activation response is lost | Retry the identical grant; never manufacture a new generation outside Git. |
| Adapter crashes after activation | Recover durable active state before serving any mutation; fail closed if unavailable. |
| Older activation arrives after a newer one | Reject it. A delayed handshake cannot roll back the active generation. |
| Stale writer resumes or a network request arrives late | Reject at the mutation boundary, even if the old process still runs. |
| New owner never activates | This protocol does not instantly revoke the previous active token merely because a Git lease expires. |
| Reservation expires or is administratively released | Advisory time/release semantics alone do not revoke the adapter token; explicit revocation needs its own serialized adapter operation. |
| Git store is restored or recreated | Quiesce the domain and reprovision a new accepted incarnation, rejecting the old one. A random ID alone supplies no recovery ordering. |
| Adapter state is restored from an old backup | Do not serve until its high-water mark and incarnation are reconciled; restoring Git alone is insufficient. |
| Adapter cannot validate authority or complete activation | Do not launch protected work; attempt acquisition-guarded cleanup and report failure. |

This is stale-owner fencing after successful activation, not a promise of exact
TTL cutoff at every downstream system. Immediate revocation would require the
adapter to participate in that protocol. A Git read immediately before an external
write is insufficient because another acquisition may occur between them.

## Scope and conflict domains

A global issuance counter avoids ambiguity in grant order, but enforcement is
per protected domain. Unrelated resources should not reject each other's valid
owners merely because another grant has a larger global number. A prefix grant
such as `dist/` and a child grant such as `dist/app.js` must resolve to compatible
enforcement scopes. Independent per-path high-water marks would allow stale
overlapping writes unless prefix fencing participates too.

The first adapter should use explicit domains and exclude hierarchical/subset
fencing, shared lock modes, semaphore slots, and family delegation until their
semantics are designed. Store-format migration, counter durability, role and
token authentication, retry idempotency, and multi-domain partial activation are
separate acceptance requirements. This proposal neither adds cryptographic
authentication to Git hashes nor protects against writers allowed to bypass the
resource adapter.

## Required acceptance evidence

Before advertising fenced operation, demonstrate delayed old writes, a paused old
process, delayed activation, duplicate activation, response loss, an in-flight old
mutation during activation, Git and adapter crash recovery, stale backup recovery,
counter exhaustion, and direct-write bypass refusal for the chosen resource.
Use deterministic schedules before stress testing. Test the adapter's actual
mutation boundary, not only token generation or a mock that compares numbers.

No adapter or generation counter is implemented in this change. For generic local
commands today, use cooperative reservations with bounded lifetimes. Where actual
exclusion is required, prefer the protected system's native transaction/conditional
write or an OS lock appropriate to that resource. That resource-specific mechanism
must cover the actual writes; Git remains useful for scheduling and traceability.
