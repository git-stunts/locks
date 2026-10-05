# Development and releases

Source files are in `lib/`, with modules in numeric order.
The build combines these fragments with `schema/git-locks.schema.json` into `bin/git-locks`.
The repository commits this script so installation needs no runtime assembly.

## Change and verify

1. Edit the relevant modules in `lib/`.
2. Run `make build`.
3. Run the relevant checks through the [isolated Docker runner](testing.md).
4. Commit the source and generated script together.

```sh
make build
make lint
make test
```

The host needs Docker, Python 3, and Git for tests and lint.
Production git-locks does not need Docker or Node.
The guarded runner reuses one worker and toolchain image, limits resources, and exports receipts.
Read [test isolation and resource limits](testing.md) before a broad test or benchmark run.

The suite checks that the committed script matches the build output.
Lint examines the assembled script because individual source fragments do not parse independently.
The build generates the schema module from the schema file.
Tests compare `git locks schema` with that file and validate their observed output.

The Unicode integration test selects an installed UTF-8 locale.
Without `locale`, it probes `C.UTF-8` and `en_US.UTF-8`.
It checks JSON stdout separately from shell diagnostics.
If no suitable locale exists, it reports a skip with the prerequisite.
`GIT_LOCKS_TEST_REQUIRE_UTF8=1` makes that skip a failure; CI requires it.

Optional repository hooks run lint before commit and tests before push:

```sh
git config --local core.hooksPath scripts/hooks
```

The hooks remove inherited Git repository variables before they invoke checks.
The Docker runner copies inputs without host Git metadata or host mounts.

## State and concurrency checks

The [state protocol](state-protocol.md#bounds-and-evidence) lists the current publication checks and their limits.
The ordinary suite includes the observation study and its calibration against deliberately broken publication.
A separate study run preserves its receipts under a new output directory:

```sh
make study-observation OBSERVATION_OUT=/work/artifacts/fresh-study
```

The study returns failure when its oracle detects a violated invariant.
Historical [per-ref counterexamples](studies/membership-observation/README.md) remain as evidence of the old design's defects.
They do not describe the current implementation.
Passing tests establish the covered cases, not a proof for every possible execution.

## Releases and installation

`VERSION` in `lib/000-prelude.sh` supplies the version in the built script.
For a release:

1. Update `VERSION`.
2. Run `make build`.
3. Add that version's section to `CHANGELOG.md`.
4. Pass the required checks and merge the change.

After successful checks on `main`, the [release job](../.github/workflows/ci.yml) checks for an existing tag or release.
For a new version, it creates an annotated `v<version>` tag and a GitHub release.
The release uses the changelog section and attaches the script and schema.
An existing version causes no new release.

`make install` copies the committed script to `$(PREFIX)/bin/git-locks`; the default prefix is `~/.local`.
It does not build or install a symlink.
Install a reviewed checkout or release, then repeat installation when you intend to upgrade.
A development symlink exposes every uncommitted edit to all consumers.

## Lessons from earlier versions

These incidents explain several current constraints:

- A linked worktree exported `GIT_DIR` to a pre-push hook. Test repository initialization then targeted the real repository.
  The hooks now remove inherited Git variables; the current runner also isolates Git metadata.
- Early snapshot code loaded state inside command substitutions. Subshells discarded cached data and increased Git process counts.
  Helpers now preserve snapshot state in their caller.
- Review of 0.2.1 found failed reads reported as free, conflicting transaction plans, incomplete family checks, unsafe release identity, and invalid JSON.
  Regression cases informed the identity, error, and family contracts in [usage](usage.md).
- A development symlink exposed an incomplete refactor to another project's hook in 2026.
  Installation now copies a snapshot.
- The old per-ref protocol could combine a new generation with incomplete membership.
  The current protocol reads one immutable tree and conditionally publishes its successor through one ref.

See [CHANGELOG](../CHANGELOG.md), the [observation study](studies/membership-observation/README.md), and the [audit reports](audit/) for historical context.
