# Store trust, environment, and Git hooks

All cooperating callers must trust the store's owner and everyone who can write
to its directory. Git's conditional root update coordinates cooperating writers;
it does not authenticate a worker or prevent a principal with filesystem access
from replacing refs, objects, configuration, or the store itself. Select the
store through a trusted launcher configuration and environment.

Subject discovery honors the caller's Git environment: `GIT_DIR`, linked
worktrees, and `git -c locks.store=... locks ...` still select the subject and
store. Once selected, store operations run in a separate subshell that removes
inherited `GIT_*` variables except the tool's own `GIT_LOCKS_*` settings. Store
Git ignores system and global configuration and uses the selected repository's
local format and configuration. The private index is supplied internally;
the caller's index, common directory, object directory, namespace, and alternate
object environment cannot redirect store operations. Git documents these
overrides in its [environment reference](https://git-scm.com/docs/git#_environment_variables).

New stores use SHA-1 independently of inherited initialization defaults. Existing
SHA-1 and SHA-256 stores retain their format. Replacement refs are disabled:
an object ID must identify its original bytes when reading reservation authority.
Lazy fetching and all transport protocols are disabled for store operations;
missing local objects fail closed. These settings also apply to initialization
and diagnosis. They do not mutate the caller's environment or configuration;
`with` passes the original environment to its command.

For its object, index, and ref operations, git-locks passes
`-c core.hooksPath=/dev/null -c core.fsmonitor=false` to Git. The overrides apply
to each invocation and do not modify repository or global configuration. This
prevents the reservation operations from running `reference-transaction` and
`post-index-change`, and disables filesystem-monitor integration. Git documents
the per-command hook override in its
[configuration reference](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corehooksPath).
New stores also exclude Git templates during initialization.

`doctor` reports a `hooks` object in its summary:

- `disabled` and `fsmonitor_disabled` state the runtime policy.
- `configured_path` is the store-local `core.hooksPath`, or null for Git's default.
- `directory` is Git's resolved hook directory in the command's invocation context.
- `executables` lists executable `reference-transaction` and `post-index-change`
  files in that directory. They are inspected, never executed by diagnosis.

Global, system, and environment configuration are excluded from this report,
matching the configuration boundary of store operations.

The hook report does not change the reservation-data health verdict. An ignored
hook can exist in a healthy store, particularly in `self` mode where the subject
repository still uses hooks for its own Git commands. git-locks neither removes
those files nor changes their configuration. This policy does not sandbox the
wrapped command, Git itself, the caller's environment, or a hostile store owner.

The Docker regression first proves that plain Git executes the fixture hooks,
then verifies that git-locks does not execute them during claim, renewal, release,
and semaphore operations. It covers default hooks, absolute and relative custom
paths, local and global configuration, Git environment configuration, `self`
mode, and an executable filesystem-monitor command. Doctor's report and every
produced JSON line are checked against the schema.

The environment regression covers first-use and existing stores, inherited Git
paths and configuration, hook-style subject discovery, preservation of the
wrapped command's environment and caller's index, replacement trees and blobs,
missing objects supplied through an inherited alternate, and an existing SHA-256
store. All fixtures and intentionally unrelated repositories live inside the
isolated Docker worker.
