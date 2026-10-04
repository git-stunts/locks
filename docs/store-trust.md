# Store trust and Git hooks

All cooperating callers must trust the store's owner and everyone who can write
to its directory. Git's conditional root update coordinates cooperating writers;
it does not authenticate a worker or prevent a principal with filesystem access
from replacing refs, objects, configuration, or the store itself. Select the
store through a trusted launcher configuration and environment.

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
- `configured_path` is the configured `core.hooksPath`, or null for Git's default.
- `directory` is Git's resolved hook directory in the command's invocation context.
- `executables` lists executable `reference-transaction` and `post-index-change`
  files in that directory. They are inspected, never executed by diagnosis.

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
