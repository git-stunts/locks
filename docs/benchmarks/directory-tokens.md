# Historical directory-token benchmark

This study asks how directory tokens retained after release affect command cost when no job or path refs remain. It compares ref count and distinct reachable records, since a deep path leaves several tokens pointing to the same record. Repeated reuse also leaves unreachable historical blobs on disk.

The runner measures `check`, an exact claim, a prefix claim, `list`, and `doctor`. The live control measures the same successful commands against unrelated reservations. Large fixture setup uses Git directly and is excluded from operation timing. The current fixture generator creates blobs and a state tree, including distinct historical records, with the same post-release semantics as the CLI. Inventory ref counts mean logical tree entries; reachable-record counts exclude tree objects. The retained 2026-09-22 run used the old loose-ref layout and is historical. Its deterministic acquisition IDs differ from real generated IDs.

`test/directory-token-churn.sh` calibrates shallow, deep, and reused shapes against actual CLI claim/release sequences. It compares every retained logical entry and every record field except the acquisition ID, checks independent counts, and runs the real doctor. It deliberately contaminates a released fixture to verify rejection. Empty stores, live controls, invalid counts, missing stores, and existing output protection are also covered. Twelve seed-39 shape samples use hand-counted count/record oracles. A quick matrix exercises the timing/cleanup path without a latency assertion.

## Workloads

| Scenario | Requested scale | Retained directory tokens | Distinct reachable records | Live jobs |
|---|---:|---:|---:|---:|
| Empty, before and after the matrix | 0 | 0 | 0 | 0 |
| Shallow/wide | 1,000 / 10,000 paths | 1,000 / 10,000 | 1,000 / 10,000 | 0 |
| Deep, ten levels per path | 1,000 / 10,000 prefixes | 1,000 / 10,000 | 100 / 1,000 | 0 |
| Repeated reuse of ten directories | 1,000 / 10,000 acquisitions | 10 | 1 | 0 |
| Synthetic live control, shallow/wide | 1,000 paths | 1,000 | 1,000 | 1,000 |

Each scenario has three repetitions of each operation. Claim cleanup runs outside the timer. Prefix claims create a retained probe token, so the runner removes that exclusively owned token with its expected object ID after release. A fingerprint verifies that all refs exactly match their starting state after every observation. The before/after inventories expose unreachable probe records left by those operations.

## Reproduction

The host needs Docker, Python 3, and Git. Bash 5, Git, standard Unix utilities, and GNU time are supplied by the isolated Linux toolchain image. Small calibration is part of `make test`. No production runtime dependency is added to git-locks. See [test isolation and resource limits](../testing.md); historical native measurements retain their original provenance.

```bash
python3 scripts/docker-run.py bash test/directory-token-churn.sh
python3 scripts/docker-run.py bash scripts/benchmark-directory-tokens.sh run /work/artifacts/locks-churn-quick quick
python3 scripts/docker-run.py bash scripts/benchmark-directory-tokens.sh run /work/artifacts/locks-churn-results
```

Output directories must not exist. The fixture command refuses existing stores and bounds its input to 10,000 work units. The large matrix processes one store at a time in a private temporary directory, then removes that store. The planned peak footprint is below 200 MiB, including temporary input files, loose objects, and refs. The runner checks the working footprint after the setup transaction, before deleting setup inputs, and reports an excess above 200 MiB. This check happens after allocation; it is not a preventive disk quota. A failed run retains raw command output, metrics, partial CSVs, and its current temporary store for diagnosis.

`environment.txt` identifies the measured revision, binary and generator blob IDs, Bash/Git/platform versions, and repetition count. `fixtures.csv` records setup time separately, ref/record/object counts, and allocated store KiB before and after operations, plus the observed setup working footprint. `observations.csv` retains every raw duration, native maximum RSS report, exit code, and stdout line count. Native resource reports are retained under `raw/`; `summary.csv` contains minimum, median, and maximum durations.

## Interpretation limits

Filesystem caches are not cleared. Setup and ref verification warm filesystem metadata, so these are repeated local observations on a shared host, not cold-storage measurements. `elapsed_us` uses Bash's wall clock around native time and the CLI; it includes the time wrapper. Native maximum RSS is a per-command resource report, not total concurrent process memory. Three repetitions support bounded descriptive comparisons, not a latency SLA or confidence interval.

The fixture equivalence check covers reachable record semantics at small scale. Synthetic setup does not measure the cost of thousands of actual CLI claim/release invocations, historical transaction interleavings, or token reclamation. The benchmark adds no timing threshold and proposes no retention-policy change.

The first native macOS run and its retained observations are in the [2026-09-22 results](directory-tokens-results.md). That run was resource-confounded by host memory and disk exhaustion, so its latencies are not a representative baseline.
