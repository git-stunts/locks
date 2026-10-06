# Native Git library audit: 2026-10-05

**Decision: retain Git CLI plumbing for now. Neither inspected library is a
verified drop-in replacement.** This source audit maps every Git command family
used by the production fragments, including store setup and offline migration.
Finding an API is not evidence that all of its edge cases match the existing
protocol. No native library was compiled, benchmarked, or run in this audit.

Project baseline: `566e577b9e89e191894a8ec7284540e41fdefbdb`.
Upstream source snapshots were resolved and inspected on 2026-10-05:

| Component | Exact upstream commit | Version declared in inspected source |
| --- | --- | --- |
| gitoxide / gix | `9272d45a1b08ca6f26779389954bd718f8308a80` | gix 0.88.0 |
| libgit2 C API | `0551dfd4ad989b6a3d5683c0d4cf326c6efef929` | header reports 1.9.0; this is a source snapshot, not a release certification |
| Rust git2 bindings | `f6f11169dee36b6eec224416350bc3f6238b6a83` | git2 0.21.0 |

The pinned source links below are the evidence. Conclusions do not establish why
git-warp or git-cas previously rejected a library; their operation sets and the
versions evaluated then may differ.
The [source manifest](studies/hierarchical-intentions/evidence/upstream-manifest.json)
records the fetched upstream file URLs and SHA-256 checksums.

## Concrete mismatch: strict creation

The current first publication uses `create refs/locks/state <new>` inside
`git update-ref --no-deref --stdin`. Creating an existing ref must fail even when
it already has the proposed OID. The isolated [Git experiment](studies/hierarchical-intentions/README.md)
checks the equivalent zero-old-OID update in both SHA-1 and SHA-256 stores.

In the inspected gix source, `PreviousValue::MustNotExist` reaches a branch that
rejects an existing ref **only when its target differs from the requested new
target**. An identical target passes. This is a source-level semantic mismatch,
not a reproduced native-library execution or a demonstrated duplicate-grant bug.
See the [prepare implementation, lines 118–133](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix-ref/src/store/file/transaction/prepare.rs#L118-L133)
and [the expectation type](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix-ref/src/transaction/mod.rs).

An unlocked precheck does not repair this race. A port would need a supported
way to enforce strict absence while holding the ref transaction lock, or retain
CLI publication, or explicitly justify and test a changed contract. Merely
mapping `create` to an API named `MustNotExist` is insufficient.

## Complete production command inventory

The inventory covers the 12 Git command families invoked by `lib/` at the
baseline. The `g` and `store_git` wrappers and the `capture_text g cat-file`
pipeline are included. Shell filesystem publication of a new store is a separate
application operation. The private-index steps may be replaced by direct tree
editing; their observable tree semantics must still match.

“API present” below means inspected source exposes relevant primitives. It does
not mean an adapter passed the project's tests. Source groups link the pinned
implementations after the table.

| Git operation and production use | gix candidate | libgit2 candidate | Remaining obligation |
| --- | --- | --- | --- |
| `rev-parse --path-format=absolute --git-common-dir`: subject discovery | Discovery and repository paths [G1] | `git_repository_discover`, open APIs, `git_repository_commondir` [L1] | Linked worktrees, bare/separate metadata, caller environment, damaged `.git`, and absence versus read failure. |
| `config --get locks.store`: store selector | `config_snapshot` [G2] | Config getters/snapshots [L2] | Exact precedence, missing versus invalid values, relative anchors, and newline preservation. |
| `init --bare --object-format=sha1 --template=`: private store bootstrap | `create::into`, bare kind, explicit object hash [G1] | `git_repository_init_ext`, bare/no-reinit options [L1] | No unwanted template files/hooks, concurrent directory publication, and losing-initializer cleanup. |
| `rev-parse --is-bare-repository`: validate selected store | Repository kind/open options [G1] | Repository open/is-bare APIs [L1] | Never silently initialize or select another store on error; preserve `self` exception. |
| `for-each-ref` with name/OID/symref fields: inventory and legacy refusal | Reference iteration/raw targets [G3] | Reference iterators/type/target APIs [L3] | Namespace boundaries, packed refs, malformed records, and symbolic-root detection. |
| `symbolic-ref --quiet --no-recurse`: dangling/cyclic direct-root check | Raw `Target::Symbolic`, without peeling [G3] | Raw symbolic target/type, without resolve [L3] | An iterator may omit a dangling ref; explicit lookup and cyclic/dangling fixtures remain necessary. |
| `cat-file -t` and `--batch`: validate and read immutable objects | `find_header`, `find_object`, raw data [G4] | ODB read/header APIs [L4] | Exact byte lengths, missing objects, corrupt objects, wrong kinds, no replacement/lazy-fetch behavior. |
| `hash-object --stdin`, `--no-filters --stdin-paths`, `-w --stdin`: path hashes and record writes | `gix_object::compute_hash`, `write_blob` [G4] | ODB hashing and raw writes [L4] | Git blob framing, selected hash format, no filters/normalization, write failures. Batching is an implementation choice. |
| `ls-tree -r`: logical state enumeration | Tree decoding/traversal [G4] | Tree entries/walk [L5] | Preserve raw names, modes, tree/blob type checks, and UTF-8 validation policy. |
| `read-tree <root>` / `--empty`: candidate basis | `edit_tree` / empty tree [G4] | Tree builder initialized from existing/empty tree [L5] | Preserve unchanged subtrees and case-distinct keys without consulting the worktree index. |
| `update-index --index-info`: apply candidate edits | Tree editor upsert/remove [G4] | Tree builder insert/remove, recursively [L5] | Exact deletes, file/tree conflicts, entry modes, and literal path bytes. |
| `write-tree`: emit candidate root | Tree editor write [G4] | Tree builder write [L5] | New objects exist before ref publication; all errors fail closed. |
| `update-ref --no-deref --stdin`: normal publication | `RefEdit`, expected target, `deref=false` [G3] | `git_reference_create_matching`; strict create via non-force creation [L3] | gix strict-create mismatch above; validate symbolic races, packed refs, lock timeout and failure classification. |
| The same `update-ref` with create plus conditional deletes: offline migration | Multi-edit transaction [G3] | Lock refs, validate expected values under lock, queue updates/deletes [L6] | Partial-commit recovery, stale/deleted refs, and no mixed-format operation. Multi-ref API availability is not crash atomicity. |

There are more rows than command families because discovery/validation and
ordinary publication/migration have different contracts.

## Cross-cutting requirements that API names do not settle

- **Both hash formats.** gix exposes `sha1` and `sha256` features; its inspected
  default feature set includes SHA-1. Enable and test both explicitly. libgit2's
  README still calls SHA-256 experimental; the inspected Rust binding gates it
  behind `unstable-sha256`. This is not evidence that SHA-256 is wholly absent,
  but a normal/default build cannot be assumed equivalent. [G5, L7]
- **Ref backends.** gix's inspected ref-store modules expose loose/packed files;
  reftable compatibility was not established. The inspected libgit2 source does
  dispatch to a reftable backend, so an old claim that libgit2 universally lacks
  it would be inaccurate. Build availability and transaction parity for that
  backend are untested here. The current project's explicit packed-ref tests do
  not establish a general reftable support promise. [G6, L8]
- **Isolation.** Subject discovery intentionally sees caller Git configuration;
  store plumbing strips inherited Git variables and disables global/system
  configuration, replacement objects, lazy fetching, hooks, and fsmonitor.
  gix offers isolated permissions, but exact policy parity needs tests. Its
  isolated-config mode also disables includes; blindly enabling it can change
  repository-local configuration behavior. A libgit2 adapter likewise needs an
  explicit configuration/environment policy. [G7, L2]
- **Transactions.** Both inspected implementations document possible partial
  multi-ref commit failure. This is not a claim that Git CLI transactions provide
  crash-atomic multi-file replacement; it is a reason to preserve the single-root
  design and review migration separately. [G8, L6]
- **Durability.** The inspected gix loose-object writer flushes and persists its
  temporary file; this inspection does not establish parity with Git's complete
  fsync policy for objects, refs, and directories. libgit2 exposes an fsync option,
  but option existence is not a durability test. Specify the promised crash model
  before claiming ACID equivalence. [G9, L9]
- **Failures.** Root mismatch, ref-lock contention, permission failure, missing
  objects, and other operational errors must retain their distinct retry/exit
  behavior. Test wrapper cleanup after uncertain publication, not just successful
  ref updates. These are application requirements, not supplied by a Git library.

GC, repacking, and commit construction are not production operations of the
current tree-root engine. A future native-only maintenance or commit-history
design would add them to this inventory and require another capability check.
They cannot be silently counted as supported by this audit.

## Recommended implementation boundary

Keep the Git CLI as the compatibility baseline. If profiling justifies a native
experiment, start with object reads and candidate-tree construction while retaining
CLI publication, store discovery, migration, and maintenance. This can remove
many process launches without claiming complete subprocess elimination.

Before selecting a fully native backend, run an adapter against the existing
root-ref, state-coherence, bootstrap, environment, hook, corruption, Unicode,
release/renewal, family, and wrapper suites in both object formats. Add the strict
create same-target case, native lock-error classification, and a declared backend
matrix. Preserve a CLI path for unsupported configurations. No library migration
or dependency installation is authorized or performed by this document.

## Pinned upstream evidence

- [G1: discovery](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix/src/discover.rs), [creation](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix/src/create.rs), and [open options](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix/src/open/options.rs).
- [G2: configuration](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix/src/repository/config/mod.rs).
- [G3: repository refs](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix/src/repository/reference.rs), [transaction types](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix-ref/src/transaction/mod.rs), and [prepare](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix-ref/src/store/file/transaction/prepare.rs).
- [G4: repository objects](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix/src/repository/object.rs), [tree editor](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix/src/object/tree/editor.rs), and [object hashing](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix-object/src/lib.rs).
- [G5: gix feature flags](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix/Cargo.toml).
- [G6: ref-store modules](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix-ref/src/store/mod.rs).
- [G7: isolated permissions](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix/src/open/permissions.rs).
- [G8: partial-commit behavior](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix-ref/src/store/file/transaction/commit.rs).
- [G9: loose-object writer](https://github.com/GitoxideLabs/gitoxide/blob/9272d45a1b08ca6f26779389954bd718f8308a80/gix-odb/src/store_impls/loose/write.rs).
- [L1: repository API](https://github.com/libgit2/libgit2/blob/0551dfd4ad989b6a3d5683c0d4cf326c6efef929/include/git2/repository.h).
- [L2: configuration API](https://github.com/libgit2/libgit2/blob/0551dfd4ad989b6a3d5683c0d4cf326c6efef929/include/git2/config.h).
- [L3: reference API](https://github.com/libgit2/libgit2/blob/0551dfd4ad989b6a3d5683c0d4cf326c6efef929/include/git2/refs.h).
- [L4: object database API](https://github.com/libgit2/libgit2/blob/0551dfd4ad989b6a3d5683c0d4cf326c6efef929/include/git2/odb.h).
- [L5: tree API](https://github.com/libgit2/libgit2/blob/0551dfd4ad989b6a3d5683c0d4cf326c6efef929/include/git2/tree.h).
- [L6: transaction API](https://github.com/libgit2/libgit2/blob/0551dfd4ad989b6a3d5683c0d4cf326c6efef929/include/git2/transaction.h) and [Rust binding's non-atomicity documentation](https://github.com/rust-lang/git2-rs/blob/f6f11169dee36b6eec224416350bc3f6238b6a83/src/transaction.rs).
- [L7: SHA-256 status](https://github.com/libgit2/libgit2/blob/0551dfd4ad989b6a3d5683c0d4cf326c6efef929/README.md) and [Rust feature gate](https://github.com/rust-lang/git2-rs/blob/f6f11169dee36b6eec224416350bc3f6238b6a83/Cargo.toml).
- [L8: ref-backend dispatch](https://github.com/libgit2/libgit2/blob/0551dfd4ad989b6a3d5683c0d4cf326c6efef929/src/libgit2/refdb.c).
- [L9: fsync option](https://github.com/libgit2/libgit2/blob/0551dfd4ad989b6a3d5683c0d4cf326c6efef929/include/git2/common.h).
