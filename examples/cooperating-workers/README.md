# Two cooperating workers

This example puts reservation acquisition in the code that launches a mutation. Alice reserves two generated files before her worker starts. Bob receives a refusal naming Alice and her note, then completes unrelated work while Alice remains active. The same run demonstrates renewal, acquisition-aware cleanup, a failed worker, and the TTL boundary.

The example exercises controlled local flows. It does not resolve the mixed-observation failures in [#45](https://github.com/git-stunts/locks/issues/45). Evaluate an external runner integration after the hardening work and that correctness gate; the adoption experiment below has not been run.

## Run it

From this checkout, with Bash 4+ and Git available:

```bash
./examples/cooperating-workers/demo.sh /tmp/locks-workers-review
```

Choose a fresh output path. An existing directory is refused before any file is overwritten. With no argument, the launcher creates a fresh temporary directory and prints its location. It uses this checkout's `bin/git-locks`; no installation, service, or package download is required.

The launcher selects an explicit bare store at `<output>/store.git`, uses `<output>/work` as the workers' common artifact directory, and writes command receipts under `<output>/receipts`. It retains those files when it finishes. The demonstration does not modify this checkout's source files or project refs.

The expected transcript is:

```text
Path set acquired before mutation; overlap refused; unrelated work completed; renewed acquisition released.
Superseded cleanup preserved the replacement acquisition.
Worker exit 17 propagated; its reservation was released.
TTL expired while the command remained active; automatic renewal is not provided.
Artifacts and JSONL receipts: <absolute output directory>
```

Inspect the evidence directly:

```bash
cat /tmp/locks-workers-review/receipts/worker-b-refusal.jsonl
cat /tmp/locks-workers-review/receipts/before-renewal.jsonl
cat /tmp/locks-workers-review/receipts/after-renewal.jsonl
cat /tmp/locks-workers-review/receipts/replacement-survives.jsonl
cat /tmp/locks-workers-review/receipts/expired-while-running.jsonl
cat /tmp/locks-workers-review/receipts/final-doctor.jsonl
```

Each run records CLI `version`, selected store and checkout revision. The [recorded example](recorded-run.json) retains one observed run's CLI records and results against its named source revision. Object IDs and acquisition IDs change on later runs; compare their relationships and the actual outcomes.

## What the launcher does

The admission boundary is the `with` invocation in [demo.sh](demo.sh):

```bash
"${DEMO_BIN}" with --job build --holder alice \
  --note 'regenerating API and types' --ttl 60 \
  generated/api.txt generated/types.txt -- \
  bash "${HERE}/worker.sh" worker-a build "${gate}" build
```

`with` obtains the whole path set before it invokes the mutation command. The worker records its admitted acquisition, writes both artifacts, and signals readiness through a gate file. Bob's launcher also uses `with`; a failed acquisition prevents Bob's mutation command from running. A prior `check` is not the admission mechanism.

The gates control order without guessing how long a worker will take. Alice remains inside her command while Bob's conflicting launch is refused and Bob's independent launch writes `independent.txt`. The independent worker records Alice's live acquisition during its own execution. It then exits and releases its separate reservation.

The launcher renews Alice's reservation with `extend`. The before/after records have different `record` object IDs and the same `acquisition` ID. When Alice's gate opens, her wrapper releases that original acquisition despite the renewal. Both generated paths become free.

A separate case starts a wrapper with job name `reused`, then creates a replacement acquisition under that name. The old wrapper's cleanup reports `nothing` with `reason: superseded`; the replacement stays live and is released explicitly by its own acquisition ID.

The failed-worker case returns status 17 after writing partial output. `with` propagates 17 and releases the reservation. Cleanup does not roll back the worker's file changes: `failed.txt` intentionally remains as partial output.

Finally, a worker with TTL 1 waits at a gate. An observation at a simulated later clock reports the reservation expired while the command is still active. The launcher then opens the gate and lets cleanup complete. The example fixes `GIT_LOCKS_NOW=1000000` and explicitly advances one observation to `1000002`; this is a deterministic TTL demonstration, not a two-second benchmark. Real integrations should use the normal clock. `with` neither renews automatically nor terminates a command when its reservation expires. Choose a TTL appropriate to the workload and put any renewal policy in the runner.

## Store and worktree meaning

This example coordinates two workers accessing the same physical artifact directory. Its explicit store isolates the exercise and makes the sharing policy visible.

In a project integration, the default separate store keeps coordination refs out of the project and is shared by linked worktrees. Reserving the same relative path across linked worktrees coordinates logical ownership; the files may be physically different. A runner must choose whether that shared logical ownership is the intended policy. Using distinct explicit stores intentionally creates independent coordination domains. Workers that should coordinate must select the same store and agree on relative path meaning.

The reservations are cooperative. Other programs can write the files without using the launcher. These controlled runs do not prove the reader coherence or arbitrary interleaving properties tracked by #45.

## Repeatable verification

```bash
python3 test/cooperating-workers.py
make lint
```

The Python test requires the same `jsonschema` dependency as the existing suite; the example itself uses Bash and Git. `make test` runs the example test as part of the normal suite.

The oracle parses the real command receipts and validates lifecycle JSON against the public schema. It checks acquisition before mutation, both reserved paths, refusal holder/note, absence of Bob's blocked mutation marker, unrelated progress during Alice's acquisition, renewal identity, release after renewal, superseded cleanup, status-17 cleanup, simulated expiry, and final store health.

The golden run uses an output path containing spaces. An existing-directory case checks preservation of a sentinel file. Two complete demonstrations then run concurrently with separate stores and both must satisfy the same behavioral assertions. That is bounded stress of this example and its isolation, not arbitrary-schedule fuzzing or evidence of external adoption.

## Adoption experiment, not yet run

After the hardening gates, recruit one actual runner maintainer or integration user and agree on one existing generator or coding-worker task that mutates a known path set. Run it through the launch boundary above in a shared checkout or deliberately chosen artifact directory. Keep the experiment to that task and its existing workflow.

Record the following before deciding whether to add features:

| Question | Evidence to retain |
| --- | --- |
| Can the maintainer install and wire the launcher? | Setup minutes, commands changed, platform/runtime versions, and each obstacle. |
| Is it useful beyond the first demonstration? | Number of runs on at least three workdays and whether the maintainer chose to keep using it. |
| Is contention understandable? | The refusal shown to the user and their explanation of who held the paths, why, and what they did next. |
| Does unrelated work keep moving? | A concrete blocked path set and an unrelated task that completed during it. |
| Is lifecycle handling dependable for the task? | Renewal/expiry decisions, worker failures, interrupted runs, cleanup receipts and any unexpected artifacts. |
| Does the sharing policy fit? | Shared checkout or linked-worktree layout, selected store, and any mismatch between logical paths and physical files. |

Ask the maintainer: "What did this refusal tell you?", "Where would you place acquisition in your launcher?", "What happened when the worker exceeded its TTL?", and "Would you keep this in the workflow next week, and why?" Record their words rather than substituting an inferred adoption score.

A useful result would be a maintainer who completes integration, uses it repeatedly, explains contention correctly, and wants to keep it. A passing local demo alone does not supply that evidence. No external maintainer has been recruited or contacted as part of this change, and no standalone-business conclusion follows from it.
