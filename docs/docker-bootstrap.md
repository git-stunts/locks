# Docker bootstrap implementation status

Issue #93 is incomplete. The ordinary runner now refuses a missing or stale image instead of starting an unguarded build. It creates workers from the verified image ID with `--pull never`. A matching existing image remains the supported local path. The refusal change and its orchestration tests still need Docker execution evidence before merge.

`scripts/docker-ci.py` is a disabled provisioning prototype for disposable GitHub-hosted Linux runners. Its entry point refuses execution before any privileged operation. It is not wired into CI and is not an approved setup command. Do not remove the refusal until the requirements below have executable evidence.

The proposed boundary is a private Docker daemon, a private socket and runtime directory, a 19 GiB loop filesystem, and a cgroup v2 slice with two CPUs, 4 GiB memory, no swap, and a process limit. The existing offline test worker would run in that daemon. The provider must retain bounded receipts, stop all owned processes, unmount its own filesystem, and remove only its own resources. It must preserve every unrelated daemon, container, volume, and cache.

Docker's `data-root` alone is insufficient with the containerd image store: images and snapshots can be stored outside that directory. The draft selects classic `overlay2`, disables the containerd snapshotter, omits any shared containerd endpoint, and checks the private daemon's reported storage driver and root. These are configuration requirements, not proof that all writes stay inside the quota. See [Docker daemon storage](https://docs.docker.com/engine/daemon/) and [daemon options](https://docs.docker.com/reference/cli/dockerd/).

The build's RUN processes also need explicit membership in the owned cgroup. Docker documents `--cgroup-parent` for [build commands](https://docs.docker.com/reference/cli/docker/buildx/build/). Membership must be observed during a real build; a command-line option or configured memory limit alone is not evidence that descendants obey it.

Work required before enabling the prototype:

- Put filesystem formatting and every other heavy setup phase under verified resource controls before execution. Check and clean partial setup when systemd activation or mounting fails.
- Make monitor death stop the actual daemon, build processes, and test processes. The draft's `finally` cleanup and systemd timeouts do not cover abrupt monitor death. Add independent liveness enforcement and fault tests; killing only a client is insufficient.
- Integrate the intentionally small quota filesystem with both host and in-container free-space guards. They currently require 50 GiB free on the Docker backing filesystem and will correctly refuse the proposed 19 GiB volume. Any exception must verify a real quota and keep continuous checks on the physical backing disk; an environment-only bypass is not acceptable.
- Audit every containerd, BuildKit, daemon, temporary, client, runtime, and log path. Include host-side receipts and setup logs in aggregate limits. Preserve earlier evidence and stop before a log reserve is consumed.
- Prove cleanup after cancellation, timeout, exhausted quota, low physical space, malformed monitoring data, daemon failure, and failed export. Preserve mounted recovery data if process death or unmounting cannot be verified.
- Run a real guarded fresh setup and cached-image reuse. Record resource peaks, image identity, process/cgroup membership, quota identity, cancellation results, and retained usage. Only then update CI to use the provider and verify a fresh hosted run.

The implementation must keep one coherent issue/PR boundary: a cached-only refusal is useful preparation, but it does not complete fresh provisioning or justify merging a change that breaks fresh CI.
