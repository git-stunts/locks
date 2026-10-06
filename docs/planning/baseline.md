# Planning baseline and traceability

Graph version: `2026-10-05.3`. Source baseline: `fdf35f559270bc34d401ff5555566822ce4cc9bc`, captured on 2026-10-05 after synchronizing published planning with the local design work.

## Source and observed state

- Published origin/main was `da14251`, the merge of roadmap PR #121, when fetched for this revision. The prior planning head was `2c35dc1`; its graph was `2026-10-05.2`.
- The source baseline combines that published plan with local design commits `566e577` and `188aade`. These local commits are not described as publicly available commits.
- PR #124 merged a proposed opaque-identity decision and compatibility tests. Its document still says proposed; GL-006 owns recorded acceptance.
- Current source uses the single immutable tree root and conditional publication, guarded renewal APIs, fail-closed state validation, atomic wrapper admission, and cancellation cleanup. It has no automatic wrapper renewal, TTL termination, native Git backend, daemon, or resource fence.
- The hierarchical prototype passed the scoped 34,000 flat-oracle comparisons and controlled SHA-1/SHA-256 Git checks recorded in its committed evidence. No production index integration or performance gain was established.
- The native audit is source inspection of pinned upstream snapshots. It found a strict-create mismatch; no native library was built or run.
- This revision does not revalidate hosted CI, installed binaries, prior independent reviews, or historical native probes. Those claims must be checked at execution/candidate time.

See [state protocol](../state-protocol.md), [wrapper lifetime](../wrapper-lifetime.md),
[native audit](../native-library-audit.md), [index/GC experiment](../studies/hierarchical-intentions/README.md),
and [fencing proposal](../fencing-proposal.md). Finite tests do not prove every
schedule, supported platform, or physical power-loss outcome.

## Foundation and existing work to reuse

HOME selection, canonical help, explicit test-hook opt-in, input/time/identity
validation, coherent root publication, environment/hook isolation, and major
wrapper cleanup improvements are existing foundation. Do not recreate those
tasks or treat every open historical issue as a current reproduced defect.

Existing `fix/bash-minimum` at `705178562982caaf0c5c24126fa9ccea72ec966e` and
`fix/guard-bootstrap` at `050ba2c186d1afbdbf1d5bc46f8030f4724bc4e5` contain relevant
prior work. The old baseline reports interpreter/review evidence and a disabled
bootstrap provider; those older receipts are not certification of this integrated
candidate. Inspect and reuse the branches, then validate the actual result.

The prior plan also reported an installed baseline at `7ba2c09`. That is historical
provenance, not a verified statement about today's installation. No installation
or global settings change is performed by this roadmap rewrite.

## External gates

Before-action gates block only their named action, not independent preparation.
Completion gates block closure of the named result. Existing active-session
authorization takes precedence; do not request it again because a card mentions
a gate. No gate is marked satisfied solely by editing these documents.

### workflow_permission

Phase: `before-action`. Blocked action: Publish changes to GitHub workflow files.

Before publishing workflow changes, verify active publication authorization and credential workflow scope. The prior scope refusal is historical; do not assume it persists or switch identities to bypass a new refusal.

### privileged_linux

Phase: `before-action`. Blocked action: Run the privileged Linux bootstrap experiment.

Provide an explicitly authorized disposable Linux environment with the required kernel features, resource limits, and at least 50 GiB free. Mocked calls do not satisfy this gate.

### repository_policy_approval

Phase: `before-action`. Blocked action: Apply repository protection settings.

James approves the concrete protection changes from GL-023 before an executor applies them. A task card alone does not authorize remote settings changes.

### release_signing_setup

Phase: `before-action`. Blocked action: Use the release signing identity.

The repository owner enables the selected release identity and required permissions. Do not export private keys or improvise signing identities.

### consenting_trial_maintainer

Phase: `before-action`. Blocked action: Start the real maintainer trial.

A real runner maintainer agrees to the named trial and its observations. Do not send recruitment messages without authorization.

### elapsed_trial_observations

Phase: `completion`. Blocked action: Declare the real trial complete.

This is a completion gate, not a gate on trial setup. The agreed repeated workday observations must exist. Simulated runs cannot satisfy elapsed real use.

### release_publication_approval

Phase: `completion`. Blocked action: Record final release approval or publish the release.

James approves the exact version, verified artifacts, and public release after reviewing the completion matrix.

### native_probe_approval

Phase: `before-action`. Blocked action: Run the bounded native terminal probe.

James authorizes the specific bounded native terminal probe. The standing installation check exception does not authorize an arbitrary host campaign.

### installed_cutover_approval

Phase: `before-action`. Blocked action: Replace the workstation installed default CLI.

Apply an installed default-CLI change only within active deployment authorization for the concrete reviewed candidate. Prior authorization persists; the task does not authorize installation by itself.

### fencing_target

Phase: `before-action`. Blocked action: Run mutation-boundary experiments against the selected resource.

Identify and agree on one real enforceable resource domain, access boundary, permitted mutations, and bounded target environment. No target is selected by the generic proposal.

## Issue coverage

This is planning traceability, not a tracker mutation or correctness verdict. Issue #41 is a container; GL-030 owns the delivery decision, not duplicate implementation.

| Issue | Current task or disposition |
| --- | --- |
| [#2](https://github.com/git-stunts/locks/issues/2) | Deferred; Current single-parent family behavior must survive the port. No demonstrated need justifies general graph-family semantics now. |
| [#7](https://github.com/git-stunts/locks/issues/7) | Deferred; Wait/watch and a notification daemon require their own observation contract and demonstrated need after the basic lifecycle is complete. |
| [#9](https://github.com/git-stunts/locks/issues/9) | Deferred; Queryable history is a separate product. Required retention and durability are owned by GL-011 and GL-012; no unbounded history chain is adopted. |
| [#10](https://github.com/git-stunts/locks/issues/10) | Deferred; Remote coordination changes the authority and failure model. Local shared Git authority remains the supported scope. |
| [#14](https://github.com/git-stunts/locks/issues/14) | [GL-044](../tasks/GL-044.md) |
| [#20](https://github.com/git-stunts/locks/issues/20) | [GL-028](../tasks/GL-028.md) |
| [#41](https://github.com/git-stunts/locks/issues/41) | [GL-030](../tasks/GL-030.md) |
| [#57](https://github.com/git-stunts/locks/issues/57) | [GL-007](../tasks/GL-007.md), [GL-044](../tasks/GL-044.md) |
| [#61](https://github.com/git-stunts/locks/issues/61) | [GL-009](../tasks/GL-009.md), [GL-010](../tasks/GL-010.md) |
| [#62](https://github.com/git-stunts/locks/issues/62) | [GL-028](../tasks/GL-028.md) |
| [#66](https://github.com/git-stunts/locks/issues/66) | [GL-001](../tasks/GL-001.md) |
| [#67](https://github.com/git-stunts/locks/issues/67) | Historical completed foundation: PR119 |
| [#68](https://github.com/git-stunts/locks/issues/68) | [GL-007](../tasks/GL-007.md), [GL-044](../tasks/GL-044.md) |
| [#69](https://github.com/git-stunts/locks/issues/69) | [GL-011](../tasks/GL-011.md) |
| [#70](https://github.com/git-stunts/locks/issues/70) | [GL-019](../tasks/GL-019.md) |
| [#71](https://github.com/git-stunts/locks/issues/71) | [GL-044](../tasks/GL-044.md) |
| [#72](https://github.com/git-stunts/locks/issues/72) | [GL-044](../tasks/GL-044.md) |
| [#73](https://github.com/git-stunts/locks/issues/73) | [GL-043](../tasks/GL-043.md) |
| [#74](https://github.com/git-stunts/locks/issues/74) | [GL-006](../tasks/GL-006.md), [GL-007](../tasks/GL-007.md) |
| [#75](https://github.com/git-stunts/locks/issues/75) | [GL-008](../tasks/GL-008.md) |
| [#76](https://github.com/git-stunts/locks/issues/76) | [GL-021](../tasks/GL-021.md) |
| [#77](https://github.com/git-stunts/locks/issues/77) | Deferred; Rate limiting has a separate temporal contract; semaphore capacity alone does not supply it. |
| [#78](https://github.com/git-stunts/locks/issues/78) | [GL-033](../tasks/GL-033.md), [GL-045](../tasks/GL-045.md) |
| [#79](https://github.com/git-stunts/locks/issues/79) | Deferred; Queryable history is a separate product. Required retention and durability are owned by GL-011 and GL-012; no unbounded history chain is adopted. |
| [#80](https://github.com/git-stunts/locks/issues/80) | [GL-012](../tasks/GL-012.md) |
| [#81](https://github.com/git-stunts/locks/issues/81) | [GL-043](../tasks/GL-043.md) |
| [#82](https://github.com/git-stunts/locks/issues/82) | [GL-007](../tasks/GL-007.md) |
| [#83](https://github.com/git-stunts/locks/issues/83) | Deferred; A doctor-dev convenience command is not required for a reliable Rust cutover. Supported tool requirements remain owned by GL-001, GL-002, GL-003, and GL-043. |
| [#84](https://github.com/git-stunts/locks/issues/84) | [GL-044](../tasks/GL-044.md) |
| [#85](https://github.com/git-stunts/locks/issues/85) | [GL-039](../tasks/GL-039.md) |
| [#86](https://github.com/git-stunts/locks/issues/86) | [GL-025](../tasks/GL-025.md), [GL-026](../tasks/GL-026.md) |
| [#90](https://github.com/git-stunts/locks/issues/90) | [GL-029](../tasks/GL-029.md) |
| [#91](https://github.com/git-stunts/locks/issues/91) | [GL-027](../tasks/GL-027.md) |
| [#92](https://github.com/git-stunts/locks/issues/92) | [GL-023](../tasks/GL-023.md), [GL-024](../tasks/GL-024.md) |
| [#93](https://github.com/git-stunts/locks/issues/93) | [GL-003](../tasks/GL-003.md) |
| [#94](https://github.com/git-stunts/locks/issues/94) | Deferred; A new explain command is useful but not required for the migration. Structural and operational diagnosis remains owned by GL-008. |

## Change and completion rules

Every task card must be listed in ROADMAP.md and inventory.active_tasks. Every original card has one disposition. No deferred or replaced card remains in docs/tasks. Read the [full disposition](disposition.md) for the ownership rationale.

Dependencies are proposed correctness prerequisites with reasons, not shared-file conflicts. Bump the graph version for scope/edge changes and regenerate projections inside the guarded worker. New required findings must acquire their own card and release edge before the audit can declare delivery complete. Native Git, index, and fencing experiments are gated extensions; their incomplete results do not block the required compatible Rust delivery.
