# Planning baseline

## Source and observed state

Graph version: `2026-10-05.1`. Source baseline: `7ba2c09b9a09e86a8d811f391d6632b995df1450`, observed on 2026-10-05.
These are historical coordinates. Recheck live state before execution.

- [PR #118](https://github.com/git-stunts/locks/pull/118) rejects missing default HOME before store initialization.
- [PR #119](https://github.com/git-stunts/locks/pull/119) derives consistent command help and checks the reference table.
- [Main CI](https://github.com/git-stunts/locks/actions/runs/37286777280) passed at this baseline.
- The workstation installed this baseline. Eight native installation checks passed, including contention, cancellation, semaphore capacity, renewal, and policy checks.
- Global Codex, Claude, and Gemini instructions require shared resource coordination. Gemini application adoption is not verified.

The installed executable SHA-256 is `b23dd9a83bf7a2b4f59b411469ef1b8ed881f00f93a1fa08b1dd5b90788e724d`.
Local installation receipts remain outside tracked source. This statement is an observed snapshot, not an instruction to trust an old install.

The earlier hardening work introduced the immutable authority root and stronger input, lifecycle, and state validation.
See [state protocol](https://github.com/git-stunts/locks/blob/7ba2c09b9a09e86a8d811f391d6632b995df1450/docs/state-protocol.md), [wrapper lifetime](https://github.com/git-stunts/locks/blob/7ba2c09b9a09e86a8d811f391d6632b995df1450/docs/wrapper-lifetime.md), and [changelog](https://github.com/git-stunts/locks/blob/7ba2c09b9a09e86a8d811f391d6632b995df1450/CHANGELOG.md).
Finite synthetic observations and process tests do not establish all schedules or physical power-loss durability.

## Existing work to reuse

- `fix/bash-minimum` at `705178562982caaf0c5c24126fa9ccea72ec966e` has local actual-interpreter evidence and an independent review. Publication failed for missing workflow permission.
- `fix/guard-bootstrap` at `050ba2c186d1afbdbf1d5bc46f8030f4724bc4e5` has a disabled provider and cached-worker tests. Real privileged setup and fresh-CI proof remain missing.

These local branches predate the baseline. Their results do not authorize a merge of a newly integrated candidate.
Locate the retained receipts, inspect the current branches, and rerun affected gates after integration.
Do not rebuild toolchains or duplicate stores merely because a task has a new identifier.

## External gates

The inventory gives each gate a phase, condition, and blocked action.
`before-action` gates apply to the named action. They permit prior preparation.
`completion` gates apply to the task outcome. They do not block preparation.
The release approval gate applies only to a release outcome, not a no-release decision.

### workflow_permission

Phase: `before-action`. Blocked action: Publish changes to GitHub workflow files.

The current publishing credential lacks workflow scope. James or the repository owner supplies an authorized credential path. Do not switch identities to bypass refusal.

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

## Issue coverage

This table maps the captured open backlog to owned outcomes. It does not create or close tracker issues.
An issue can map to several tasks when each task owns a different result.
Issue #41 remains the tracking container. GL-030 owns the final completion decision, not every implementation.

| Issue | Task or disposition |
| --- | --- |
| [#2](https://github.com/git-stunts/locks/issues/2) | [GL-041](../tasks/GL-041.md) |
| [#7](https://github.com/git-stunts/locks/issues/7) | [GL-037](../tasks/GL-037.md) |
| [#9](https://github.com/git-stunts/locks/issues/9) | [GL-034](../tasks/GL-034.md) |
| [#10](https://github.com/git-stunts/locks/issues/10) | [GL-038](../tasks/GL-038.md) |
| [#14](https://github.com/git-stunts/locks/issues/14) | [GL-018](../tasks/GL-018.md) |
| [#20](https://github.com/git-stunts/locks/issues/20) | [GL-028](../tasks/GL-028.md) |
| [#41](https://github.com/git-stunts/locks/issues/41) | [GL-030](../tasks/GL-030.md) |
| [#57](https://github.com/git-stunts/locks/issues/57) | [GL-004](../tasks/GL-004.md) |
| [#61](https://github.com/git-stunts/locks/issues/61) | [GL-009](../tasks/GL-009.md), [GL-010](../tasks/GL-010.md) |
| [#62](https://github.com/git-stunts/locks/issues/62) | [GL-028](../tasks/GL-028.md) |
| [#66](https://github.com/git-stunts/locks/issues/66) | [GL-001](../tasks/GL-001.md) |
| [#67](https://github.com/git-stunts/locks/issues/67) | [PR #119](https://github.com/git-stunts/locks/pull/119), complete |
| [#68](https://github.com/git-stunts/locks/issues/68) | [GL-005](../tasks/GL-005.md) |
| [#69](https://github.com/git-stunts/locks/issues/69) | [GL-011](../tasks/GL-011.md) |
| [#70](https://github.com/git-stunts/locks/issues/70) | [GL-019](../tasks/GL-019.md) |
| [#71](https://github.com/git-stunts/locks/issues/71) | [GL-016](../tasks/GL-016.md) |
| [#72](https://github.com/git-stunts/locks/issues/72) | [GL-016](../tasks/GL-016.md), [GL-017](../tasks/GL-017.md) |
| [#73](https://github.com/git-stunts/locks/issues/73) | [GL-013](../tasks/GL-013.md), [GL-014](../tasks/GL-014.md) |
| [#74](https://github.com/git-stunts/locks/issues/74) | [GL-006](../tasks/GL-006.md), [GL-007](../tasks/GL-007.md) |
| [#75](https://github.com/git-stunts/locks/issues/75) | [GL-008](../tasks/GL-008.md) |
| [#76](https://github.com/git-stunts/locks/issues/76) | [GL-020](../tasks/GL-020.md), [GL-021](../tasks/GL-021.md) |
| [#77](https://github.com/git-stunts/locks/issues/77) | [GL-040](../tasks/GL-040.md) |
| [#78](https://github.com/git-stunts/locks/issues/78) | [GL-033](../tasks/GL-033.md) |
| [#79](https://github.com/git-stunts/locks/issues/79) | [GL-034](../tasks/GL-034.md) |
| [#80](https://github.com/git-stunts/locks/issues/80) | [GL-012](../tasks/GL-012.md) |
| [#81](https://github.com/git-stunts/locks/issues/81) | [GL-015](../tasks/GL-015.md) |
| [#82](https://github.com/git-stunts/locks/issues/82) | [GL-007](../tasks/GL-007.md) |
| [#83](https://github.com/git-stunts/locks/issues/83) | [GL-022](../tasks/GL-022.md) |
| [#84](https://github.com/git-stunts/locks/issues/84) | [GL-035](../tasks/GL-035.md) |
| [#85](https://github.com/git-stunts/locks/issues/85) | [GL-039](../tasks/GL-039.md) |
| [#86](https://github.com/git-stunts/locks/issues/86) | [GL-025](../tasks/GL-025.md), [GL-026](../tasks/GL-026.md) |
| [#90](https://github.com/git-stunts/locks/issues/90) | [GL-029](../tasks/GL-029.md) |
| [#91](https://github.com/git-stunts/locks/issues/91) | [GL-027](../tasks/GL-027.md) |
| [#92](https://github.com/git-stunts/locks/issues/92) | [GL-023](../tasks/GL-023.md), [GL-024](../tasks/GL-024.md) |
| [#93](https://github.com/git-stunts/locks/issues/93) | [GL-003](../tasks/GL-003.md) |
| [#94](https://github.com/git-stunts/locks/issues/94) | [GL-036](../tasks/GL-036.md) |

Split ownership is explicit: #73 has raw-field preservation and plan redirects; #72 has planner reporting and shared invariant rules.
Issue #76 has Python tooling and the fast gate. Issue #86 has action pins and verifiable release artifacts.
Issue #92 has an owner policy decision and its enforcement. Issue #74 has an identifier decision and its schema implementation.
The remaining #82 scope belongs to event metadata and reference checks; PR #119 already handles canonical command help.

## Graph limits and change rules

Dependency reasons are author proposals grounded in the named source and task contract. They are not imported GitHub dependency records.
Review an edge by asking whether its predecessor must be complete for the successor to be correct.
Reject edges based only on topic, shared files, or resource contention.

A decision or research task can discover required implementation work. Add typed cards and edges before it releases dependent tasks.
Bump the graph version after a scope or edge change. Recompute the DAG and antichains from frontmatter.
Preserve the old evidence coordinates. Do not rewrite historical measurements as current results.
Do not count unresolved optional decisions as implemented features.
