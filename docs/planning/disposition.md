# Prior-task disposition

Graph `2026-10-05.2` to `2026-10-05.3`. The original 41 cards are preserved in published Git history at `2c35dc160f9355b7d571ba576e51b69b5690cb4f` and the existing Reader archive. No removed outcome is claimed complete by this rewrite.

Only the cards in the current [roadmap](../../ROADMAP.md) are active. Deferred ideas have no active task file; reintroducing one requires a new scoped card and graph update.

| Prior ID and outcome | Disposition | Current ownership or reason |
| --- | --- | --- |
| GL-001 — Publish a truthful Bash support floor | retained | [GL-001](../tasks/GL-001.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-002 — Verify the minimum Git version | retained | [GL-002](../tasks/GL-002.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-003 — Guard toolchain bootstrap from start to cleanup | retained | [GL-003](../tasks/GL-003.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-004 — Resolve job and semaphore name findings | replaced | [GL-007](../tasks/GL-007.md), [GL-044](../tasks/GL-044.md); Current key behavior is defined once in the public contract and implemented in the Rust preview; obsolete per-ref failures are not presumed current. |
| GL-005 — Return precise argument diagnostics | replaced | [GL-007](../tasks/GL-007.md), [GL-044](../tasks/GL-044.md); Precise diagnostics are specified in the shared command contract and implemented once in Rust instead of expanding Bash argument handlers. |
| GL-006 — Choose the acquisition identifier contract | retained | [GL-006](../tasks/GL-006.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-007 — Align output events, schema, and reference tables | retained | [GL-007](../tasks/GL-007.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-008 — Report operational store problems accurately | retained | [GL-008](../tasks/GL-008.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-009 — Choose a safe recovery contract | retained | [GL-009](../tasks/GL-009.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-010 — Implement and rehearse offline recovery | retained | [GL-010](../tasks/GL-010.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-011 — Choose store retention and history boundaries | retained | [GL-011](../tasks/GL-011.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-012 — Provide safe bounded store maintenance | retained | [GL-012](../tasks/GL-012.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-013 — Separate stored fields from decoded numbers | replaced | [GL-043](../tasks/GL-043.md); Typed Rust records preserve raw stored fields separately from checked arithmetic values. |
| GL-014 — Guard deliberate plan redirects | replaced | [GL-043](../tasks/GL-043.md); The Rust plan type enforces expected values and deliberate redirects instead of directly mutating T_AFTER. |
| GL-015 — Expose a safe planner test interface | replaced | [GL-043](../tasks/GL-043.md); The Rust core exposes pure planners to independent fixtures; no sourced production Bash test interface is needed. |
| GL-016 — Separate planner decisions from command output | replaced | [GL-043](../tasks/GL-043.md), [GL-044](../tasks/GL-044.md); Rust planners return typed decisions; command adapters own JSONL, streams, and exits. |
| GL-017 — Share validated liveness and invariant rules | replaced | [GL-043](../tasks/GL-043.md); The Rust core owns shared liveness/relationship rules with distinct diagnostic behavior. |
| GL-018 — Resolve remaining admission-loop duplication | replaced | [GL-044](../tasks/GL-044.md); The obsolete duplicated-loop report is reconciled as part of complete Rust admission commands, not a speculative Bash cleanup. |
| GL-019 — Bind retained evidence to source and bytes | retained | [GL-019](../tasks/GL-019.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-020 — Make Python tooling checks explicit | replaced | [GL-021](../tasks/GL-021.md); Python lint, format, exclusions, and tooling policy join the same fast/full validation-tier result. |
| GL-021 — Define a fast local gate and complete merge gate | retained | [GL-021](../tasks/GL-021.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-022 — Report development prerequisites in one command | deferred | A doctor-dev convenience command is not required for a reliable Rust cutover. Supported tool requirements remain owned by GL-001, GL-002, GL-003, and GL-043. |
| GL-023 — Record the exact merge review policy | retained | [GL-023](../tasks/GL-023.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-024 — Align merge automation with the review policy | retained | [GL-024](../tasks/GL-024.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-025 — Pin workflow actions to reviewed commits | retained | [GL-025](../tasks/GL-025.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-026 — Produce verifiable release artifacts | retained | [GL-026](../tasks/GL-026.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-027 — Measure current contention and object growth | retained | [GL-027](../tasks/GL-027.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-028 — Choose whether state layout needs optimization | retained | [GL-028](../tasks/GL-028.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-029 — Run an actual cooperating-worker adoption trial | retained | [GL-029](../tasks/GL-029.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-030 — Audit hardening completion and select the release | retained | [GL-030](../tasks/GL-030.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-031 — Investigate the native supervisor warning | retained | [GL-031](../tasks/GL-031.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-032 — Close the supported-contract evidence matrix | retained | [GL-032](../tasks/GL-032.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-033 — Decide automatic wrapper renewal semantics | retained | [GL-033](../tasks/GL-033.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-034 — Decide durable history semantics | deferred | Queryable history is a separate product. Required retention and durability are owned by GL-011 and GL-012; no unbounded history chain is adopted. |
| GL-035 — Explain store selection provenance | replaced | [GL-007](../tasks/GL-007.md), [GL-044](../tasks/GL-044.md); Store selection and its provenance are part of command compatibility and operator-visible runtime behavior. |
| GL-036 — Explain decisions from a pinned root and time | deferred | A new explain command is useful but not required for the migration. Structural and operational diagnosis remains owned by GL-008. |
| GL-037 — Decide wait and watch observation guarantees | deferred | Wait/watch and a notification daemon require their own observation contract and demonstrated need after the basic lifecycle is complete. |
| GL-038 — Evaluate remote coordination safety | deferred | Remote coordination changes the authority and failure model. Local shared Git authority remains the supported scope. |
| GL-039 — Evaluate enforceable resource fencing | retained | [GL-039](../tasks/GL-039.md); Outcome retained with refreshed scope, baseline, dependencies, and evidence requirements. |
| GL-040 — Test the proposed rate-limit semantics | deferred | Rate limiting has a separate temporal contract; semaphore capacity alone does not supply it. |
| GL-041 — Decide whether lock families need a general graph | deferred | Current single-parent family behavior must survive the port. No demonstrated need justifies general graph-family semantics now. |

## New outcomes

- [GL-042 — Apply the admission deadline throughout reference retries](../tasks/GL-042.md): Make the Bash reference honor the selected finite admission/plumbing contract under contention and stalls.
- [GL-043 — Introduce a typed Rust core with a Git CLI backend](../tasks/GL-043.md): Add a non-default Rust core that reads, validates, plans, and conditionally publishes through Git CLI plumbing.
- [GL-044 — Port advisory commands into the non-default Rust preview](../tasks/GL-044.md): Provide a non-default Rust executable covering the complete current advisory command set through the Git CLI backend.
- [GL-045 — Implement bounded Rust supervision and guarded renewal](../tasks/GL-045.md): Run child commands under a bounded Rust supervisor with identity-guarded renewal/loss response and complete cleanup.
- [GL-046 — Establish cross-implementation and platform parity](../tasks/GL-046.md): Run one current parity/independent-oracle matrix against Bash and the complete Rust preview on declared configurations.
- [GL-047 — Measure and cut over the installed CLI with rollback](../tasks/GL-047.md): Select and implement an independently usable default Rust CLI cutover with a verified Bash fallback and rollback procedure.
- [GL-048 — Integrate an opt-in verified hierarchical index](../tasks/GL-048.md): Implement the accepted hierarchical-index mode without changing the stable default contract or weakening validation.
- [GL-049 — Evaluate native Git plumbing with executable semantic checks](../tasks/GL-049.md): Determine which native backend operations can replace CLI plumbing with demonstrated semantic parity and measured benefit.

Issue links are local planning traceability only. This rewrite does not close, create, edit, or publish tracker issues, PRs, settings, or releases. Split issue ownership is intentional only when one card specifies a contract and another implements it, or one supplies typed core behavior and another command rendering.
