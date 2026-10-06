# Bounded experiment launch: 2026-10-05

The only executable experiment is `check.py`, through
`python3 scripts/docker-run.py python3 docs/studies/hierarchical-intentions/check.py`.
It is limited to 400 seeded in-memory updates, 34,000 flat-oracle comparisons,
6,800 prior-snapshot query checks, a 128-child query example, and four small
disposable Git repositories. Expected generated data is below 16 MiB and output
below 64 KiB; tmpfs quotas and the existing monitor enforce the larger bounds.

- Reuse `git-locks-tests:local`, image
  `sha256:9f145953f6e79a59749a683d11a476133cb7cef0588b79256dc195b1d0c87ad7`,
  and stopped worker `git-locks-tests`, profile 5. Recipe fingerprint matches;
  no image build is needed or authorized by this experiment.
- Workstation authority: `/Users/Shared/git-locks/workstation.git`; exclusive keys
  `host/heavy-work` and `host/docker/git-locks-tests/`; acquisition
  `1791254454-68436-1492915293`, job
  `agent-4F3B665D-4DD5-45E6-B471-0D6A5F287472`, TTL 3,600 seconds.
  Keep the runner's `/tmp/git-locks-docker-tests.lock` as well.
- Preflight: host free 723,832,217,600 bytes; Docker backing filesystem free
  687,930,257,408 bytes; worker writable layer 233,472 bytes; no mounts/volumes.
  Retained project evidence occupies 42,349,600 allocated bytes. No compiler
  target/cache is used. Docker reports 2.548 GB of build cache across all projects,
  conservatively below the 20 GiB project ceiling even if all were attributed here.
- Owned runtime outputs: copied inputs and scratch under `/work` (512 MiB tmpfs),
  fixture stores under `TMPDIR=/tmp` (512 MiB), home `/home/node` (32 MiB),
  logs/evidence `/evidence` (16 MiB), and private `/dev/shm` (16 MiB).
  Container root is read-only, with no bind mounts or volumes; network is disabled.
- Host outputs: bounded `.test-results/latest.log`, result/isolation/resource
  receipts, and the unique exported
  `.test-results/artifacts/hierarchical-intentions-20261005/` directory. Existing
  artifact directories are preserved. Export cap is 80 MiB aggregate; project
  log accounting is 128 MiB, with a 16 MiB live output cap and Docker log rotation
  at one 1 MiB file. The independent upstream-source review scratch directory is
  `/private/tmp/git-locks-design-followup-20261005/`, with individually bounded
  downloads and no generated builds.
- Existing `scripts/docker-exec.py` enforces a 1,800-second workload deadline,
  16 MiB individual-file limit, quota reserves, VM free-space floor, and generated
  log accounting. The outer runner monitors host free space. Both free-space
  floors are 50 GiB. The container has two CPUs, 2 GiB RAM including swap, and
  256-process limit. Inner monitoring failure kills owned processes, including
  detached groups; outer teardown stops `git-locks-tests`.
- Run only on the matching existing worker/image. The runner's unguarded image
  bootstrap remains outside this launch: a missing/mismatched image is a stop,
  not permission to rebuild. Sampling can overshoot a log/free-space threshold;
  runtime tmpfs capacities are hard bounds. This run creates no build caches.

Export the result and resource receipt, stop the worker, and release the exact
workstation acquisition. These measurements authorize this bounded run only.

## Follow-up run

The first run passed. A second bounded run adds the strict-create same-target
assertion and an explicit `--output` argument. It uses the same worker, image,
limits, and lock keys, with a fresh wrapper-owned acquisition and output
`/work/artifacts/hierarchical-intentions-20261005-strict-create`. The first export
is retained unchanged. The checked-in result/isolation/resource receipts describe
the second run. Recheck image identity and host/VM space before launch; no rebuild
is permitted. The wrapper's 3,600-second TTL exceeds the runner's 1,800-second
timeout and cleanup allowance.
