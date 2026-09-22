# Directory-token churn results, 2026-09-22

A released store with 10,000 distinct directory tokens and 10,000 reachable records had a median `check` latency of **3.641 seconds** in this run. Empty-store controls measured **0.140 seconds before** the matrix and **0.094 seconds after** it. The store had no job or path refs. Historical directory state belongs in performance measurements alongside live-lock count.

These are 135 native macOS observations: nine scenarios, five operations, three repetitions each. Every measured command exited 0, expected output-line counts matched, and every post-operation ref fingerprint matched its starting state. The raw check range for wide 10k was **3.070–6.811 seconds**; its median should not be read as a stable latency guarantee.

## Median operation latency

Values below are rounded milliseconds. Full minimum/median/maximum distributions are in [summary.csv](results/2026-09-22/summary.csv), with every sample in [observations.csv](results/2026-09-22/observations.csv).

| Scenario | Check | Exact claim | Prefix claim | List | Doctor |
|---|---:|---:|---:|---:|---:|
| Empty, before | 140 | 205 | 268 | 105 | 162 |
| Wide 1k | 348 | 474 | 436 | 299 | 334 |
| Wide 10k | 3641 | 2753 | 2433 | 2110 | 2462 |
| Deep 1k prefixes | 201 | 260 | 296 | 193 | 261 |
| Deep 10k prefixes | 1031 | 1144 | 1209 | 1158 | 1372 |
| Reuse 1k acquisitions | 139 | 180 | 197 | 107 | 107 |
| Reuse 10k acquisitions | 212 | 203 | 193 | 95 | 89 |
| Live 1k control | 460 | 539 | 806 | 1160 | 3017 |
| Empty, after | 94 | 165 | 163 | 71 | 71 |

## What the comparisons show

- **Released records still cost reads.** Wide 10k retained 10,000 refs and 10,000 distinct records, with zero jobs or paths. Median `list` was 2.110 seconds even though it emitted no lines; median `doctor` was 2.462 seconds.
- **Keep ref count and reachable-record count separate.** Deep 10k retained the same 10,000 refs but only 1,000 distinct records. Its median `check` was 1.031 seconds. The fixed scenario order and host variation prevent attributing the entire difference to object count.
- **Unreachable objects and retained authority have different costs.** Reuse 10k left 10 tokens pointing to one record, plus 10,000 loose historical objects on disk. Median `check` was 0.212 seconds, `list` 0.095 seconds, and `doctor` 0.089 seconds. This workload did not reproduce wide 10k's multi-second observations; it does not establish that unreachable-object growth is free under every storage layout.
- **Live-lock work adds a separate cost.** The synthetic live 1k control had 3,000 refs and 1,000 records. Its median `list` was 1.160 seconds and `doctor` 3.017 seconds, compared with 0.299 and 0.334 seconds in the released wide 1k store.

The [before/after inventories](results/2026-09-22/fixtures.csv) retain all ref, reachable-record, loose-object, and allocated-store counts. Wide 10k occupied 78.2 MiB after setup; deep 10k occupied 43.0 MiB; reuse 10k occupied 39.2 MiB. Each scenario accumulated six unreachable probe records during measured claim/release repetitions; the inventories expose those additions while ref fingerprints remained identical.

## Provenance and limits

The measured revision was `fe7cdb588ee16f0d90350865344e0b007bf4ffa0`, with binary blob `ff0444627cb9239b1a582ecfc9645fe22b68e611` and generator blob `2d934e9942ecd7aa2f080d93b7cb4e36b95688d8`. The git-locks executable is unchanged from the study's `01e39c3` main baseline. The final results commit adds data and this report without changing that measured code.

The host was macOS 26.6.2, Darwin 25.6.0 arm64, MacBookPro18,3, 10 logical CPUs, and 16 GiB RAM. Bash was 5.3.9 and Git reported 2.54.0, Apple Git-157. Exact captured metadata is in [environment.txt](results/2026-09-22/environment.txt) and [hardware.txt](results/2026-09-22/hardware.txt). Hardware metadata came from `sw_vers` and `sysctl hw.model hw.ncpu hw.memsize` on the same host.

Setup used synthetic loose Git objects and refs. Small wide/deep/reuse fixtures matched actual CLI claim/release records and refs after excluding acquisition IDs. The large history was not produced by thousands of CLI invocations. Setup, inventory, ref restoration, and release cleanup were excluded from operation timing. Native resource reports are concatenated, unchanged except for filename headers, in [native-time.txt](results/2026-09-22/native-time.txt). The largest native maximum-RSS report was 46.3 MiB during wide 10k `doctor`; it is not aggregate concurrent memory.

The largest observed setup working footprint was **157.3 MiB**, measured with `du -sk` before setup inputs were removed. The 200 MiB check detects an excess after allocation; it is a planned workload budget and an observed check, not a preventive disk quota. The completed matrix removed every scenario store. Retained data is compact text.

Caches were not cleared, and the host was shared with other development work. Empty controls changed from 140 to 94 milliseconds for `check`, and from 162 to 71 milliseconds for `doctor`. That drift, fixed operation order, wall-clock instrumentation, and three repetitions limit causal and statistical claims. There was no failed timing observation or partial large-matrix run. Earlier host disk pressure delayed the study before its full matrix started.

These results support profiling snapshot reads at large retained-token counts and repeating the experiment after the hardening changes land. They do not justify deleting generation tokens or changing the concurrency protocol. Packed stores, garbage collection, cold caches, other machines, and long-running CLI history setup remain unmeasured. No timing threshold or retention-policy change is introduced.

See the [protocol and reproduction commands](directory-tokens.md) for the calibrated generator, quick checks, and full matrix.
