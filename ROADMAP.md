---
schema: "git-locks-roadmap/1"
graph_version: "2026-10-05.2"
status: "proposed"
created: "2026-10-05"
baseline_commit: "7ba2c09b9a09e86a8d811f391d6632b995df1450"
---

# Hardening roadmap

## Executive summary

Make git-locks reliable within its stated contract: cooperative reservations for agents and workers on one machine.
One immutable Git root holds the complete authority. A conditional update prevents publication from a stale root.
Every participant must use the same store, keys, and lease rules. The tool cannot stop an expired worker from writing.

The core already rejects many invalid states and unsafe inputs. Current main includes the HOME fix and consistent command help.
Compatibility, bounded fresh setup, recovery, retention, evidence quality, and release verification remain unfinished.
These tasks close the gap between a passing test suite and a tool that operators can install, diagnose, maintain, and recover.

This plan has **41 task cards: 32 required hardening tasks and 9 optional product tasks**.
Required tasks include decisions and research. They can expose more required work; they do not prove that the backlog is complete forever.
[GL-030](docs/tasks/GL-030.md) must add any required follow-up task before it can declare completion.
Optional product tasks do not block the hardening release.

## Horizons and exit conditions

| Horizon | Result | Exit condition |
| --- | --- | --- |
| Short | A truthful support contract and bounded setup, with explicit decisions for unresolved policies. | Each relevant task has current evidence or a named external blocker. |
| Medium | Recovery, maintenance, independent validation, measured limits, and a release decision. | Every required task and the completion matrix pass at the release candidate. |
| Long | Extensions selected from actual use. | Each accepted design receives its own implementation tasks and a revised graph. |

Horizons express order and scope. They are not calendar estimates. A medium-term task can start when its prerequisites permit it.
The long-term cards cover decisions or bounded features. They do not invent implementation plans for unresolved semantics.

## How to execute a task

1. Select a task from the graph's dependency-ready candidates.
2. Recheck its source, prerequisites, and external gates.
3. Extract its prompt with `python3 scripts/roadmap.py --prompt GL-019` inside the guarded worker.
4. Send the extracted prompt first. Append volatile session details after it.
5. Complete one coherent result and record its evidence.
6. Update task status, issue links, and generated graph files in the same change.

Every extracted prompt begins with the exact bytes in [PROMPT.txt](docs/tasks/PROMPT.txt).
Task identity and context follow that prefix. Do not prepend changing timestamps, file metadata, or conversation summaries.
This layout supports prefix reuse. It does not guarantee that a model provider uses a cache.
The extractor includes the complete card after the prompt, so its criteria travel with it.

## Dependency model and workstreams

Task frontmatter is the source of truth. [graph.json](docs/tasks/graph.json) is its generated machine-readable projection.
[DAG.md](docs/tasks/DAG.md) contains the full Mermaid graph, topological layers, and dependency-ready candidates.
Each layer is an antichain. These layers are not a maximum-width antichain calculation or a runtime schedule.

Edges mean correctness prerequisites. Their reasons appear in both frontmatter and task sections.
The edges are evidence-backed proposals in this graph version, not a claim that GitHub already records or the owner individually approved them.
A shared file, worker, API limit, or subject does not create a dependency.
External approvals and environments are gates; the graph does not treat them as completed tasks.
Each gate states its phase and blocked action. Completion gates permit preparation before the final evidence exists.

| Workstream | Exclusive ownership | Boundary |
| --- | --- | --- |
| contract | Public input, output, identity, support, and native wrapper behavior. | No store maintenance or optional product extension. |
| operations | Diagnosis, recovery, retention, and maintenance. | No new history product or planner refactor. |
| state | Internal field, plan, predicate, and admission interfaces. | Preserve the public contract; do not add commands. |
| assurance | Setup guards, tools, evidence, review, supply chain, and final completion audit. | No benchmark conclusions or product priorities. |
| performance | Current measurements, optimization choices, and real adoption evidence. | No unmeasured redesign or invented users. |
| product | Optional extensions selected from demonstrated needs. | Excluded from the required hardening exit set. |

Each task belongs to exactly one workstream. Together, the streams cover the known tasks in this graph version.
That partition is MECE for this inventory. It does not prove that unknown defects or future requests do not exist.
Cross-stream dependencies remain in the graph. Shared resources still require admission and resource guards.

## Safe concurrency

Use the workstation's canonical authority and resource registry when they exist.
Acquire `host/heavy-work` and the applicable worker key before an expensive campaign.
Use the repository's shared authority for `.git/` and changed file keys.
Independent task cards do not permit duplicate builds, conflicting writes, or review-service contention.
Do not hold a parent reservation while a delegated worker waits to acquire the same key.

Maintain the existing 20 GiB build, 4 GiB runtime, and 128 MiB log budgets.
Stop heavy work below 50 GiB free on the host or Docker backing filesystem.
A quota or verified monitor must cover every generated output and stop child work on failure.
Reuse workers and caches. Preserve unique evidence before removing owned disposable data.

## Task sequence

The checklist below uses a deterministic topological order. It is a valid sequence, not the only sequence.
An unchecked task is unfinished. Follow its card for approval, evidence, and scope; do not infer readiness from its position.

<!-- TASK CHECKLIST BEGIN -->
- [ ] [GL-003 — Guard toolchain bootstrap from start to cleanup](docs/tasks/GL-003.md) · assurance · short
- [ ] [GL-004 — Resolve job and semaphore name findings](docs/tasks/GL-004.md) · contract · short
- [ ] [GL-005 — Return precise argument diagnostics](docs/tasks/GL-005.md) · contract · short
- [ ] [GL-006 — Choose the acquisition identifier contract](docs/tasks/GL-006.md) · contract · short
- [ ] [GL-008 — Report operational store problems accurately](docs/tasks/GL-008.md) · operations · short
- [ ] [GL-009 — Choose a safe recovery contract](docs/tasks/GL-009.md) · operations · short
- [ ] [GL-011 — Choose store retention and history boundaries](docs/tasks/GL-011.md) · operations · short
- [ ] [GL-013 — Separate stored fields from decoded numbers](docs/tasks/GL-013.md) · state · medium
- [ ] [GL-014 — Guard deliberate plan redirects](docs/tasks/GL-014.md) · state · medium
- [ ] [GL-015 — Expose a safe planner test interface](docs/tasks/GL-015.md) · state · medium
- [ ] [GL-018 — Resolve remaining admission-loop duplication](docs/tasks/GL-018.md) · state · medium
- [ ] [GL-019 — Bind retained evidence to source and bytes](docs/tasks/GL-019.md) · assurance · short
- [ ] [GL-023 — Record the exact merge review policy](docs/tasks/GL-023.md) · assurance · short
- [ ] [GL-025 — Pin workflow actions to reviewed commits](docs/tasks/GL-025.md) · assurance · medium
- [ ] [GL-031 — Investigate the native supervisor warning](docs/tasks/GL-031.md) · contract · short
- [ ] [GL-001 — Publish a truthful Bash support floor](docs/tasks/GL-001.md) · contract · short
- [ ] [GL-002 — Verify the minimum Git version](docs/tasks/GL-002.md) · contract · short
- [ ] [GL-007 — Align output events, schema, and reference tables](docs/tasks/GL-007.md) · contract · medium
- [ ] [GL-010 — Implement and rehearse offline recovery](docs/tasks/GL-010.md) · operations · medium
- [ ] [GL-012 — Provide safe bounded store maintenance](docs/tasks/GL-012.md) · operations · medium
- [ ] [GL-016 — Separate planner decisions from command output](docs/tasks/GL-016.md) · state · medium
- [ ] [GL-017 — Share validated liveness and invariant rules](docs/tasks/GL-017.md) · state · medium
- [ ] [GL-020 — Make Python tooling checks explicit](docs/tasks/GL-020.md) · assurance · medium
- [ ] [GL-024 — Align merge automation with the review policy](docs/tasks/GL-024.md) · assurance · medium
- [ ] [GL-026 — Produce verifiable release artifacts](docs/tasks/GL-026.md) · assurance · medium
- [ ] [GL-027 — Measure current contention and object growth](docs/tasks/GL-027.md) · performance · medium
- [ ] [GL-021 — Define a fast local gate and complete merge gate](docs/tasks/GL-021.md) · assurance · medium
- [ ] [GL-022 — Report development prerequisites in one command](docs/tasks/GL-022.md) · assurance · medium
- [ ] [GL-028 — Choose whether state layout needs optimization](docs/tasks/GL-028.md) · performance · medium
- [ ] [GL-029 — Run an actual cooperating-worker adoption trial](docs/tasks/GL-029.md) · performance · medium
- [ ] [GL-032 — Close the supported-contract evidence matrix](docs/tasks/GL-032.md) · assurance · medium
- [ ] [GL-030 — Audit hardening completion and select the release](docs/tasks/GL-030.md) · assurance · medium
- [ ] [GL-033 — Decide automatic wrapper renewal semantics](docs/tasks/GL-033.md) · product · long · optional
- [ ] [GL-034 — Decide durable history semantics](docs/tasks/GL-034.md) · product · long · optional
- [ ] [GL-035 — Explain store selection provenance](docs/tasks/GL-035.md) · product · long · optional
- [ ] [GL-036 — Explain decisions from a pinned root and time](docs/tasks/GL-036.md) · product · long · optional
- [ ] [GL-037 — Decide wait and watch observation guarantees](docs/tasks/GL-037.md) · product · long · optional
- [ ] [GL-038 — Evaluate remote coordination safety](docs/tasks/GL-038.md) · product · long · optional
- [ ] [GL-039 — Evaluate enforceable resource fencing](docs/tasks/GL-039.md) · product · long · optional
- [ ] [GL-040 — Test the proposed rate-limit semantics](docs/tasks/GL-040.md) · product · long · optional
- [ ] [GL-041 — Decide whether lock families need a general graph](docs/tasks/GL-041.md) · product · long · optional
<!-- TASK CHECKLIST END -->

## Coverage and baseline

[baseline.md](docs/planning/baseline.md) records the source revision, completed foundation, external gates, and issue mapping.
[Task templates](docs/planning/task-templates.md) preserve the supplied card structures.
[Planning terms](docs/planning/terms.md) define the technical vocabulary and writing-status limits.

Run the graph check through the guarded Docker runner:

```sh
python3 scripts/docker-run.py python3 scripts/roadmap.py --check
```

After a task edit, generate the projections inside the guarded worker with `--write`.
Export `ROADMAP.md`, `docs/tasks/graph.json`, and `docs/tasks/DAG.md`, then commit them with the task change.
Follow the current host and repository lock protocol around the runner.
Never run an unguarded fresh image build to validate this plan.
