# Store initialization

Store selection is shared across subdirectories and linked worktrees. The
anchor is Git's absolute common directory with a final `/.git` removed: the
main repository top level in the ordinary layout, and the common directory
itself for bare repositories and separate metadata layouts. This is also the
identity used by the default store. A relative `GIT_LOCKS_STORE`, `locks.store`,
or `GIT_LOCKS_HOME` resolves against that anchor. Absolute overrides retain
their location; `self` selects the common Git directory. Outside a repository,
the physical current directory is the anchor. Paths containing newlines are
refused instead of being silently shortened by shell command substitution.

Default selection uses a nonempty `GIT_LOCKS_HOME`, or `HOME/.git-stunts` when that override is absent or empty. If both variables are absent or empty, git-locks exits 2 with a structured `store-read` error before initialization. An explicit `GIT_LOCKS_STORE` or configured `locks.store` does not require `HOME`.

For example, `locks.store=.reservations/store.git` in a normal repository at
`/projects/app` selects `/projects/app/.reservations/store.git` from the root,
any subdirectory, and its linked worktrees. This changes earlier behavior that
selected a separate relative store in each invocation directory. Before
upgrading a launcher that used relative paths, stop its workers and inspect
those earlier stores. Point every worker at one existing store with an absolute
override, or resolve existing reservations before moving to the shared location.
No old stores are moved or merged automatically.

Repository discovery and configuration failures return `store-read` before
initialization or reservation output. Only Git's ordinary repository-absence
diagnostic permits directory-based operation, and even then nearby Git metadata
or an explicit Git repository environment prevents fallback. An absent
`locks.store` key is allowed; other configuration read errors are not treated as
an unset key. Subject discovery continues to honor the caller's Git environment.

A missing store is initialized automatically on first use, including `store`.
Use an absent path for a new store. An existing destination must already be a
valid bare Git repository, or the subject's common Git directory in `self` mode.
An empty directory, a directory containing unrelated files, and a file named
`HEAD` alone are not valid stores; git-locks refuses them without initializing
anything inside them.

Initialization prepares a bare repository in a unique temporary directory beside
the destination. Git templates are disabled so that a newly allocated store does
not copy template hooks, refs, or unrelated files. A completed directory is then
renamed into place on the same filesystem. A competing initializer can only
observe the absent destination or a completed store. It validates and uses the
winning repository, then normal root publication decides reservation admission.

Each initializer removes its unused preparation. On GNU and BSD systems, if a
competitor wins immediately before `mv`, the losing directory may be placed
inside the winning store; only that uniquely named preparation is removed. It
contains no reservations and is never read as authority. This handles both
portable `mv` destination forms without an external coordination service or a
persistent initialization lock.

Filesystem setup and initialization failures exit 2 with a structured
`store-write` error. Invalid existing destinations exit 2 with `store-read`.
Normal interruption cleans the preparation; a force-killed process can leave an
unreferenced `.git-locks.init.*` sibling or nested directory. Remove such a
preparation only after establishing that its initializer has stopped. Do not
move, replace, or remove the store while clients are using it.

Docker checks cover 15 rounds of four concurrent first-use claims, a forced
four-way directory-publication race, visibility while Git initialization is
paused, injected initialization failure, existing invalid destinations,
unwritable parents, exclusion of custom templates, and removal of unused
preparations. Every resulting race store is inspected through real Git-backed
commands.

The store-selection suite verifies shared authority through competing claims
from roots, subdirectories and linked worktrees, including bare and separate
metadata layouts. It also covers malformed/unreadable configuration, broken
repository metadata, injected discovery errors, outside-repository operation,
selection precedence, and newline rejection.
