# Membership observation study

The controlled reader exposed unsafe commits in all three studied domains. Across 84 synthetic per-ref observations, 21 commands returned success and left a family, semaphore-capacity or prefix-exclusivity violation. Production code is unchanged. The corrective work is tracked by [#45](https://github.com/git-stunts/locks/issues/45), an unresolved release correctness gate in [#41](https://github.com/git-stunts/locks/issues/41).

These are synthetic observation counterexamples executed against real objects and real Git transactions. This study did **not** reproduce a live Git reader/writer schedule. It establishes how the planner behaves when given these mixed observations, and challenges the claim that generation compare-and-swap alone makes any cached observation safe.

## Question and assumptions

A generation check can detect a change that happens after a coherent membership scan. Does it also reject a scan that already contains the current generation and incomplete membership?

Git's [update-ref documentation](https://git-scm.com/docs/git-update-ref), checked on 2026-09-22, says that "a concurrent reader may still see a subset of the modifications." The documentation does not promise a consistent snapshot across refs. That permits concern about mixed observations; it does not prove that every synthetic combination in this study occurs under a particular Git backend or ref-enumeration order.

The subject is the unchanged executable at `01e39c306362d7de26cec08f149d7f286e3733ce`, with `GIT_LOCKS_NOW=1000000`. Each case creates its own store. A normal command first creates state A. Another normal command adds one family child, one semaphore slot, or one path below a directory, creating state B. Both initial states pass the independent checks. State B is fully committed before the candidate command begins.

The candidate receives one synthetic `for-each-ref` response. Each changed ref independently takes its value from A or B; absence is also a value. Unchanged refs remain present. Immutable objects are fetched from the actual store. The shim never rewrites object contents or substitutes an `update-ref` result. The candidate's transaction runs against the real, fully committed B. Any retry receives the real current refs.

This deliberately separates two questions:

1. Can the planner commit unsafely from this observation? The controlled fixture answers this.
2. Can a live Git reader produce this observation during a supported backend's transaction? This remains unverified.

## Results

The complete ref-mix space was enumerated for three deterministic name variants, seeds `38`, `1701` and `20260922`. These seeds change job and directory names; they do not represent random samples of arbitrary family shapes or process schedules.

| Domain | Changed refs per transition | Cases | Cases with a studied violation | Representative case |
| --- | ---: | ---: | ---: | --- |
| Family child admission | 4 | 48 | 12 | [`family-38-14`](evidence/family-38-14/result.json) |
| Semaphore slot admission | 2 | 12 | 3 | [`semaphore-38-01`](evidence/semaphore-38-01/result.json) |
| Descendant path admission | 3 | 24 | 6 | [`prefix-38-01`](evidence/prefix-38-01/result.json) |
| Total | | 84 | 21 | [Complete result ledger](evidence/report.json) |

All 21 violating cases returned exit 0 and completed a real transaction. The other 63 cases had no violation of the three studied invariants. That is a bounded result, not a declaration that every ref in those stores is valid.

### Family

The mixed observation includes the new parent job record and parent path record, but omits the child job. The reader can also include the child's path ref; family membership is discovered through job refs.

`release --job p6899` plans only the parent deletions. The transaction expects the current parent record, so its compare-and-swap succeeds. Child job `c6899` and its path ref remain after parent `p6899` is deleted. The independent oracle reports `family-parent` because the child's named parent no longer exists.

The retained [observed refs](evidence/family-38-14/observed.refs), [transaction input](evidence/family-38-14/transaction-1.stdin), and [final raw state](evidence/family-38-14/final.json) show the missing membership, successful current-generation expectation, and resulting orphan.

A possible reader-order explanation would read the absent child job before the writer commits and the updated parent job afterward. This is a hypothesis requiring live backend instrumentation, not a reproduced schedule.

### Semaphore

The observation retains the new `refs/locks/sem/gpu/gen`, the unchanged capacity of 1, and no slot. In the real store, one live slot is already committed.

`sem acquire gpu --job z6899 --holder bob` counts zero visible slots and plans a new one. The current generation expectation matches. Its successful transaction leaves two live slots with capacity 1. The [raw final state](evidence/semaphore-38-01/final.json) supplies both slot records and the capacity record to the independent oracle.

### Prefix

The observation retains the new directory token but omits the descendant job. A path ref may be omitted or retained; the prefix membership scan enumerates job records.

The candidate successfully claims `d6899/` while the real store still contains another job's `d6899/child.md`. The [transaction](evidence/prefix-38-01/transaction-1.stdin) compares against the actual current token, and the [final state](evidence/prefix-38-01/final.json) contains both live reservations. The independent oracle compares path strings and reports their overlap across different jobs.

## Controls and oracle

The oracle reads raw refs and blob contents through the real Git executable. It does not call production parsing helpers, `doctor`, or `check`. It checks parent existence, holder equality, parent liveness and cycles; live slot count against capacity; and overlapping live paths across different jobs.

Six hand-checked inputs calibrate it: a healthy state and a deliberately broken state for each domain. The broken family input removes the parent job; the broken semaphore input adds a second slot reference; the broken prefix input adds a covering reservation. These are oracle inputs, not claims about how normal admission creates those states. The [calibration receipt](evidence/calibration.json) retains their exact verdicts.

Two further controls explain where observation injection belongs. The dispatcher loads a snapshot, but release and semaphore acquisition reload before planning. Injecting only their first read was initially harmless because the planner discarded it. The final fixture retains these discarded-read controls, then injects planner read 2 for release/semaphore and read 1 for prefix claims. Every case records read order, the injected ordinal, and transaction count. If the injection does not execute or the transition's ref shape changes, the study exits 2 as an instrumentation error.

Coherent A and coherent B observations are included for every domain and seed. Coherent old observations with stale generations retry against real B. For semaphore and prefix admission, old-generation/new-membership observations refuse on visible contention. Current-generation/incomplete-membership observations are the damaging case.

The small ref-mix spaces are exhausted for these transitions. This is stronger than hoping a repeated concurrent launch encounters a particular mix, but it is not stress evidence about the operating system, Git's actual publication order, or arbitrary histories. The study does not examine ref-backend internals, crashes, network filesystems, semaphore deletion, expiry boundaries, deeper families, or complete job/path-ref consistency. It cannot establish the rate or reachability of a live race.

## Reproduction and exit status

Python is used only by this test fixture, alongside the repository's existing Python test dependency. The installed `bin/git-locks` and every `lib/` module are unchanged.

Run the full study with a fresh retained output directory:

```bash
make study-observation OBSERVATION_OUT=/tmp/locks-observation-review-run
```

The current result is **exit 1**, `production_safety: FAIL`, with 21 violating cases. This is an exposed production safety failure under the injected observations, not an expected-failure assertion converted to a passing test. Exit 0 means the studied invariants held within the tested synthetic cases. Exit 2 means the experiment could not execute reliably. Existing evidence is never overwritten.

Run only the six oracle cases and two discarded-read controls:

```bash
make test-observation-calibration OBSERVATION_OUT=/tmp/locks-observation-review-run
```

Calibration exits 0 when the fixture is working and explicitly reports `production_safety: NOT_EVALUATED`. `make test` also runs this calibration after the ordinary suite. A green ordinary suite or calibration does not mean the observation study is green.

Every full run retains before/committed-after/final raw refs and objects, the injected refs, command stdout/stderr, read order, transaction stdin, and a result ledger. The committed evidence includes the complete 84-case ledger and representative violating/coherent cases, with [runtime and executable hashes](evidence/provenance.json). Dynamic object IDs and acquisition IDs vary between executions; the invariant failures and ref-selection categories are the comparison points.

## Follow-up boundary

[#45](https://github.com/git-stunts/locks/issues/45) requires a justified relationship between membership and the witness checked at commit, plus observation-phase regressions in all three domains. The fix should preserve ordinary paths, stale-generation retries, and independent post-run invariants. It must state supported backend and read-order assumptions and distinguish synthetic evidence from any reproduced live schedule.

An immutable per-semaphore state object in [#20](https://github.com/git-stunts/locks/issues/20) is one comparison, not a selected design. This study does not choose a broad concurrency rewrite, introduce a service, or claim production safety has been restored.
