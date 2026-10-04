# Isolated tests and benchmarks

Every test and benchmark runs in the Docker worker. The host needs Docker,
Python 3, and Git; Node and the test dependencies live in the toolchain image.

```sh
make test
make lint
python3 scripts/docker-run.py python3 test/capacity.py
python3 scripts/docker-run.py bash test/unicode-missing-locale.sh
make study-observation OBSERVATION_OUT=/work/artifacts/observation-red
```

`make test-docker` is an alias for `make test`. CI uses this same runner, including
the missing-locale regression. Direct test and benchmark entry points invoke
the pinned, vendored [docker-guard](../scripts/vendor/docker-guard/UPSTREAM.md)
through a local adapter. Setting `GIT_STUNTS_DOCKER=1` or `GITHUB_ACTIONS=true`
on the host does not bypass the adapter. Production `bin/git-locks` has no
Docker or Node dependency.

The runner copies current tracked files and nonignored new files, including
uncommitted changes. It excludes Git metadata and generated output and refuses
symlinks. It does not mount the host checkout, host home, Docker socket, caches,
or volumes. Inside the container it creates a new Git repository and one commit
from those copied files. This is a fixture for tests that inspect committed
evidence; it contains no source-repository history, remotes, alternates,
credentials, hooks, or linked worktrees. Its commit ID identifies the isolated
input, not a commit from the source repository.

The worker uses `--network none`, a read-only root filesystem, an unprivileged
user, dropped capabilities, and `no-new-privileges`. Only image construction
downloads toolchain packages. The image contains no source or test output.
The adapter also checks container evidence, the approved source location,
tmpfs mount boundaries, and absence of network interfaces other than loopback.
It is a guard against accidental raw execution, not a sandbox against a user
who controls Docker or edits the guard.

One stable image (`git-locks-tests:local`) and one worker (`git-locks-tests`)
are reused. An OS lock serializes runs across checkouts; an already-running
worker is never restarted automatically. Each run stops the worker after
exporting receipts, which clears its temporary filesystems. Source changes
do not rebuild the toolchain image.

Resource limits are two CPUs, 2 GiB memory including swap, 256 processes,
512 MiB each for `/work` and `/tmp`, 32 MiB for the container home, and a separate
16 MiB tmpfs for live logs and exported evidence. Private `/dev/shm` is also
explicitly capped at 16 MiB and monitored; daemon-wide defaults cannot enlarge it.
`TMPDIR` is explicitly `/tmp`.
The runner checks host and Docker VM backing-filesystem free space before work
and monitors both during execution, stopping below 50 GiB. The smaller quota
filesystems have their own limits and a 1 MiB remaining-space stop threshold. Inputs are limited to
64 MiB; individual generated files and the test log are capped at 16 MiB.
Each invocation has a 30-minute timeout. On completion, timeout, or any monitor
failure, the runner kills every process created after its container baseline,
including descendants in other sessions and groups. Container teardown is the
final boundary if process inspection or termination itself fails.
The project uses no compiler cache
or data volumes; the toolchain image and its build cache must remain within
the shared 20 GiB project budget.

`.test-results/isolation.json` records the image, copied-input archive hash,
command, and Docker configuration. `latest.log` and `result.json` record the
latest command. Write evidence that must survive teardown under
`/work/artifacts/<unique-name>`; it is exported into
`.test-results/artifacts/<unique-name>`. Existing evidence is never overwritten,
and aggregate retained evidence is limited to 80 MiB, counting allocated blocks.
A new run reserves 16 MiB of export space before it starts. The live log/evidence
filesystem, latest host log, 1 MiB receipt-metadata reserve, and bounded Docker log leave the combined log
budget below 128 MiB. A monitored conservative count also includes generated
fixture files outside Git object storage; copied inputs are excluded. The
runtime data filesystems plus host receipts total less than 1.2 GiB, below the
4 GiB project data budget. `resources.json` records sampled peaks, minimum VM
free space, output bytes, and any resource refusal. Other container files
are disposable. Exported receipts are ignored by Git and never copied back
into a later test input.

The ordinary suite checks Docker isolation and raw-entry refusal as well as
the existing behavior tests. The full observation study still reports the
known safety counterexamples until #45 is fixed. A passing container suite
does not change that production-safety verdict.
