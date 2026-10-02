---
report_id: "AUD-2026-10-02-V01"
title: "Day 0 DX & Purity Audit — git-locks"
status: "Final"
audit:
  date_started: 2026-10-02
  date_completed: 2026-10-02
  type: "Full"
  scope: "README.md, CONTRIBUTING.md, CHANGELOG.md, Makefile, .gitignore, .github/workflows/ci.yml, scripts/build.sh, scripts/hooks/*, scripts/benchmark-directory-tokens.sh, bin/git-locks, lib/*.sh (all 22 fragments; read in full: 000, 020, 040, 090 arg parser and prefix planner, 110, 120, 140, 160, 990; grep-audited: the rest), test/*.sh, test/*.py, test/observation/*, examples/cooperating-workers/*, docs/**/*.md, schema/git-locks.schema.json"
  compliance_frameworks: ["System-Style", "OWASP ASVS"]
target:
  repository: "git-stunts/locks"
  branch: "main"
  commit_hash: "a5c0acd1f96515b02106707bc2e42e82ce4463a7"
  language_stack: ["Bash", "Git", "Python (test tooling)"]
  environment: "Local"
methodology:
  manual_review_hours: 0.3
  false_positive_rate: "15 of 35 candidates discarded (43%)"
summary:
  total_findings: 20
  severity_count:
    critical: 0
    high: 3
    medium: 8
    low: 9
  remediation_status: "Pending"
related_reports:
  previous_audit: "N/A"
  tracking_ticket: "TBD"
---

# Day 0 DX & Purity Audit

## Scope and method

This is Phase 1 of the Internal Repository Survey of `git-stunts/locks` at `a5c0acd1f96515b02106707bc2e42e82ce4463a7` (`origin/main`). Everything below was reproduced on this machine: macOS (Darwin 25.6.0), bash 5.3.9, git 2.54.0 (Apple Git-157), shellcheck 0.11.0, shfmt 3.13.1, python3 3.12.13 with jsonschema 4.26.0, markdownlint-cli2 on PATH, no ruff/flake8/pyflakes/yamllint, Docker client 29.5.2 with the daemon stopped. A second bash, 4.3.30, was available at a scratch path and used for the version-floor probe. All probing used a fresh `git clone` of the checkout under the Phase 1 scratch directory, isolated stores via `GIT_LOCKS_STORE`, and `GIT_LOCKS_NOW=1757980800` unless a probe says otherwise. No tracked file other than this report was modified; `make build` was not run.

Citations use `path#line@a5c0acd`. Every finding carries an Action Prompt that a developer can paste into an LLM; each prompt names the failing test to write first, because `CONTRIBUTING.md#3@a5c0acd` declares tests the spec.

### Finding index

| ID | Severity | Section | Title |
|---|---|---|---|
| DX-01 | High | Q1 | `make test` costs 5 min 55 s and the pre-push hook runs all of it |
| DX-02 | Medium | Q1 | Install says nothing about `~/.local/bin` being on PATH |
| DX-03 | Medium | Q1 | Develop omits the toolchain: python3 for `make build`, shellcheck and shfmt for `make lint`, `/usr/bin/time` for the benchmark |
| DX-04 | Low | Q1 | `make test-docker` has no CI job and no evidence of ever having run |
| DX-05 | Medium | Q2 | "No Python" is the written rule; 671 lines of Python, including the build step, have no linter, formatter or ignore rule |
| DX-06 | Low | Q2 | Executable bits are inconsistent across the script set |
| DX-07 | Low | Q2 | Three error helpers with three contracts: `usage` dumps 4.4 KB, `fail` labels non-usage failures `usage`, `store_error` is the only one with a precise reason |
| DX-08 | Low | Q2 | 107 uppercase globals act as return registers across modules |
| DX-09 | Low | Q2 | Markdown has no lint configuration or CI step; the house rule (no MD013) is unenforced |
| DX-10 | High | Q3 | "bash 4 or newer" is false: bash 4.3.30 crashes `claim`, `release`, `with` and `doctor` |
| DX-11 | Medium | Q3 | `git locks help` and `<cmd> --help` disagree with the README and the code on `with --parent` and `release` conditions |
| DX-12 | Medium | Q3 | README says an expired lock "is free the moment its time is up", but `extend` revives it |
| DX-13 | Low | Q3 | README `sem release` row omits `--record` and `--acquisition`, which the parser accepts |
| DX-14 | Low | Q3 | Commands table exit column says `0` for `release`, `list`, `sweep`; the code exits 1 and 2 on documented paths |
| DX-15 | High | Q4 | A large `--ttl` is accepted, written as a negative `expires`, and poisons the store for every command including `sweep` |
| DX-16 | Medium | Q4 | `GIT_LOCKS_NOW=abc` leaks a raw bash `unbound variable` error and exits 1, the "refused" code |
| DX-17 | Medium | Q4 | Any argument mistake prints the entire usage manual as one JSON line and never says what was wrong |
| DX-18 | Medium | Q4 | `resolve_store` runs `git init --bare` inside any existing directory, `git locks store` included, and reports failures as `usage` |
| DX-19 | Low | Q4 | A relative `GIT_LOCKS_STORE` resolves against the current directory, not the repository |
| DX-20 | Low | Q4 | `with` leaks `bin/git-locks: line 1952: …: command not found` for a missing command |

## Q1. First Boot Friction and Time to Value

### What a new developer actually experiences

The walk followed `README.md#450-469@a5c0acd` (Install, Develop) and `CONTRIBUTING.md#8@a5c0acd` (hooks) literally, in a fresh clone under scratch, then ran the README's own transcript (`README.md#27-55@a5c0acd`), the `with` transcript (`README.md#337-342`), the semaphore transcript (`README.md#282-292`) and the runnable example (`README.md#348-350`).

| Step | Command | Wall time | Result | Surprise |
|---|---|---|---|---|
| 1 | `git clone … clone` | 0.27 s | ok | none |
| 2 | `make install PREFIX=<scratch>/prefix` | 0.14 s | ok, `prefix/bin/git-locks` 0755 | README never says `~/.local/bin` must be on PATH; macOS default PATH lacks it (DX-02) |
| 3 | `PATH=<prefix>/bin:$PATH git locks version` | <0.1 s | `{"name":"git-locks","version":"0.7.0"}` | none |
| 4 | `make lint` | 6.7 s | zero output, rc 0 | README does not say how to get shellcheck or shfmt; CI installs shfmt through `go install` (DX-03) |
| 5 | `make test` | 355.35 s (5 min 55 s), 33.7 MB RSS | `1085 passed` (test.sh), `760 checks passed` (capacity.py), `240 passed` (literal-paths.sh), `20 passed, 0 skipped` (unicode-locale.sh), `6 passed` (calibration), churn suite all `ok`; exit 0 | nearly six minutes, and this is also the pre-push hook (DX-01); negative-path fixtures print `directory-token benchmark: count must be 0..10000` eight times on stderr during a green run |
| 6 | `git config --local core.hooksPath scripts/hooks` | instant | ok | none |
| 7 | README transcript, fresh store, `GIT_LOCKS_NOW=1757980800` | <1 s | every line matched the README in shape and exit code; IDs differ as the README says they will | `for-each-ref` shows a third ref, `refs/locks/dirs/<hash>`, which the README flags as omitted from the sketch at `README.md#76` |
| 8 | `with` transcript | <0.5 s | matched; `building` on stdout, two JSON lines on stderr, rc 0 | none |
| 9 | Semaphore transcript | <1 s | matched through the `capacity` refusal, rc 1 | real `acquired` lines carry `record` and `acquisition`; the README lines at `README.md#286-288` omit them, covered by the abbreviation note at `README.md#65` |
| 10 | `./examples/cooperating-workers/demo.sh <scratch>/demo-out` | 3.72 s | rc 0, four narrative lines, receipts written | none; this is the best onboarding artefact in the repository |
| 11 | `make test-docker` | n/a | `Cannot connect to the Docker daemon` | not verifiable here (DX-04) |
| 12 | `make build` | not run | by instruction | would require python3 (`scripts/build.sh#9@a5c0acd`); README does not say so (DX-03) |

Time to first successful `claim` from a cold clone: under five seconds. Time to a verified development loop (lint plus test plus hooks): about six and a half minutes, almost all of it the suite.

### TTV rubric

| Criterion | Weight | Score (0–10) | Evidence |
|---|---|---|---|
| Install is one command and works | 20% | 9 | Steps 1–3; one point off for the unstated PATH requirement |
| Documented transcript reproduces | 20% | 10 | Steps 7–9 match byte-shape and exit codes |
| Dependencies are named where they are needed | 15% | 4 | python3 for build, shellcheck/shfmt for lint, `/usr/bin/time` for the benchmark are all unstated in README; jsonschema is stated |
| Dev loop latency (lint + test) | 20% | 3 | 6.7 s lint is fine; 355 s test as the pre-push hook is not |
| Runnable example and first error experience | 15% | 7 | Demo is excellent; first argument mistake prints a 4.4 KB usage blob (DX-17) |
| Portability matches the claim | 10% | 2 | "bash 4 or newer" fails on 4.3 (DX-10) |
| **Weighted TTV** | | **6.3 / 10** | |

### DX-01 (High): `make test` costs 5 min 55 s and the pre-push hook runs all of it

**Evidence.** `/usr/bin/time -l make test` in the scratch clone: `355.35 real 172.26 user 158.49 sys`, exit 0. `scripts/hooks/pre-push#8@a5c0acd` runs `make --no-print-directory test` unconditionally. `Makefile#15-21@a5c0acd` lists six suites; `test/test.sh` alone reports `1085 passed`. The pre-sweep figure the lead quoted was 2 min 23 s on main; the suite has grown by roughly 2.5x since and now exceeds the 120 s pre-push budget the project is held to by almost three times.

**Why it matters.** Every push is a six-minute wait. Developers either stop pushing often or run `git push --no-verify`, and the hook becomes theatre. The suite is also the only thing standing between a stale `bin/git-locks` and `main`, so weakening it informally is the worst outcome.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. The pre-push hook (scripts/hooks/pre-push) runs `make test`, which takes 355 s wall on an M-series Mac (6 suites; test/test.sh alone is 1085 cases). The project budget for pre-push is 120 s.

Task: split the suite into a fast pre-push tier and a full CI tier without deleting or weakening any test.

1. Measure first: add `GIT_LOCKS_TEST_TIMING=1` support to test/test.sh so each `ok` line can carry elapsed milliseconds, and produce a one-off ranking of the slowest 30 cases (the race, fuzz, 500-lock performance and forced-interleaving cases are the likely heavy hitters). Record the ranking in the PR description.
2. Add a Makefile target `test-fast` that runs: test/test.sh with `GIT_LOCKS_TEST_TIER=fast` (skipping cases tagged slow via a `slow` helper you add, with a printed `SKIP <name> (slow tier)` line so the skip is visible), plus test/literal-paths.sh. Keep `test` as the full suite; CI keeps running `make test`.
3. Write the failing test first: a new case in test/test.sh named "fast tier finishes under 120 s" that runs `make test-fast` in a subshell with `time` and asserts the elapsed seconds are below 120. Show it red (it will be red while test-fast still equals test), then make it green.
4. Point scripts/hooks/pre-push at `make test-fast`, and add a comment naming the budget and that CI runs the full suite.
5. Update README.md (Develop section) and CONTRIBUTING.md to describe the two tiers in the same commit.

Acceptance: `make test-fast` under 120 s on the machine where you measured; `make test` unchanged in case count (1085 in test.sh); `make lint` clean; CHANGELOG Unreleased entry under Changed.
```

### DX-02 (Medium): Install says nothing about `~/.local/bin` being on PATH

**Evidence.** `README.md#452-455@a5c0acd` shows `make install` then `git locks list` with the comment "git dispatches `git locks` to git-locks on PATH". `Makefile#38-41@a5c0acd` installs into `$(PREFIX)/bin` with `PREFIX ?= $(HOME)/.local`. `/usr/libexec/path_helper -s` on this Mac shows the default PATH does not contain `~/.local/bin`. The walk's step 3 only worked because the probe prepended the prefix to PATH explicitly (and the host already had a `~/.local/bin/git-locks` from a prior install, which masked the problem in the "without PATH" control).

**Why it matters.** The first README command after install, `git locks list`, prints `git: 'locks' is not a git command` for a developer on a default macOS shell, and nothing in the README or the `make install` output tells them why.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. README.md Install (lines 450-457) tells a new user to run `make install` then `git locks list`, but never says that $(PREFIX)/bin (default ~/.local/bin) must be on PATH; macOS's default PATH does not include it.

Task:
1. Add a test first in test/test.sh: "install target reports when PREFIX/bin is not on PATH". Run `make install PREFIX=<tmpdir>` with PATH set so <tmpdir>/bin is absent, capture stdout, and assert it contains the string `not on PATH` and the exact path. Show it red.
2. Make the Makefile `install` recipe end with a one-line shell check: if `:$PATH:` does not contain `:$(PREFIX)/bin:`, print `git-locks installed to $(PREFIX)/bin, which is not on PATH; add it or `git locks` will not dispatch` to stdout. Keep the recipe POSIX sh-compatible.
3. In README.md Install, add one sentence after the code block stating the PATH requirement and that `make install` reports it, and mention `PREFIX=` for a different location.

Acceptance: the new test is green; `make lint` clean (the Makefile is not in SCRIPTS, but keep the recipe simple); README and CHANGELOG updated in the same commit.
```

### DX-03 (Medium): Develop omits the toolchain

**Evidence.** `README.md#462-466@a5c0acd` lists `make build`, `make lint`, `make test`, `make study-observation`. Only `make test` names a dependency ("needs python3 with jsonschema"). But `scripts/build.sh#9@a5c0acd` calls `python3 -c 'import json,…'` to minify the schema, so `make build` needs python3 too; `Makefile#11-12@a5c0acd` needs `shellcheck` and `shfmt`, which CI installs with `apt-get install shellcheck` and `go install mvdan.cc/sh/v3/cmd/shfmt@latest` (`.github/workflows/ci.yml#68-73@a5c0acd`); `scripts/benchmark-directory-tokens.sh#180-183@a5c0acd` calls `/usr/bin/time -l` on macOS or GNU `time -f` on Linux, stated only in `docs/benchmarks/directory-tokens.md#23@a5c0acd`; `make test-docker` needs a Docker daemon. `CONTRIBUTING.md#5@a5c0acd` says "No jq, no Python" and so actively misleads about the build.

**Why it matters.** A contributor on a minimal Linux box gets `python3: command not found` from the first `make build`, in a project whose contributing guide says Python is not used.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. The README Develop section (lines 459-469) and CONTRIBUTING.md do not name the developer toolchain. Facts: scripts/build.sh line 9 requires python3 (schema minification); make lint requires shellcheck and shfmt (CI: apt shellcheck, `go install mvdan.cc/sh/v3/cmd/shfmt@latest`); make test requires python3 + jsonschema; scripts/benchmark-directory-tokens.sh requires /usr/bin/time (macOS) or GNU time; make test-docker requires Docker. CONTRIBUTING.md line 5 says "No Python", which is true of the runtime (bin/git-locks) but not of the toolchain.

Task:
1. Failing test first: add to test/test.sh a case "build.sh fails with a named prerequisite when python3 is absent" that runs scripts/build.sh with PATH pointing at a temp dir containing only bash, git, cat, chmod, mv, mktemp, dirname, and asserts stderr contains `python3` and `make build`, exit 2. Show it red (today it dies with bash's `command not found`).
2. Make scripts/build.sh check `command -v python3` first and fail with that message.
3. Add a `make doctor-dev` (or `make deps`) target that prints each tool's presence and version (bash, git >= 2.31, shellcheck, shfmt, python3, jsonschema import, /usr/bin/time or GNU time, docker) as one line each, never failing the build; mention it in README Develop.
4. Rewrite README Develop to state, per target, what it needs. Rewrite CONTRIBUTING.md line 5 to distinguish the runtime rule (bin/git-locks: bash and git only) from the toolchain (python3 for build and tests).

Acceptance: new test green; `make lint` clean; README, CONTRIBUTING and CHANGELOG updated in one commit.
```

### DX-04 (Low): `make test-docker` has no CI job and no evidence of ever having run

**Evidence.** `Makefile#33-34@a5c0acd` defines `test-docker`. `.github/workflows/ci.yml@a5c0acd` never references it (`grep -c test-docker` is 0). Running it here: `Cannot connect to the Docker daemon at unix:///Users/james/.docker/run/docker.sock`. The recipe installs `time` in the Alpine image, which suggests someone anticipated the benchmark calibration, but nothing in the repository records a successful run.

**Why it matters.** An unrun recipe rots silently. Its `apk add` line is the only place the Linux prerequisite list is written down, so if it is wrong nobody knows.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. Makefile has a `test-docker` target (bash:5.2 image, apk add git python3 py3-jsonschema time, then the six suites) that no CI job runs and that has no recorded successful run.

Task:
1. Add a CI job `docker-suite` to .github/workflows/ci.yml that runs `make test-docker` on ubuntu-latest (Docker is preinstalled there), with the same `GIT_LOCKS_TEST_REQUIRE_UTF8: "1"` env as lint-and-test. Make `release` depend on it.
2. While it is red, fix whatever the recipe needs (likely candidates: `git config --global --add safe.directory /src` ordering, the `time` package name, locale availability for test/unicode-locale.sh in Alpine; the suite already probes for C.UTF-8 on musl).
3. Record the first green run's URL in CHANGELOG Unreleased and in the Makefile comment above the target.

Acceptance: the new job is green on the PR; the Makefile target is unchanged in intent; README Develop mentions `make test-docker` with its Docker requirement.
```

## Q2. System-Style and Purity

### What is clean (verified, no finding)

- Every non-fragment shell file in the repository is in `SCRIPTS` (`Makefile#3@a5c0acd`): the diff between `git ls-files '*.sh' + hooks + bin` and `SCRIPTS` is exactly the 22 `lib/*.sh` fragments, which are documented as linting only through the built script (`Makefile#2@a5c0acd`). `shfmt -d -i 2 -ci -bn lib/*.sh` nonetheless passes on the fragments themselves.
- `make lint` passes with zero output on a fresh clone (shellcheck 0.11.0 `-S style -o all`, shfmt 3.13.1).
- Exactly one `# shellcheck disable` exists, `test/unicode-locale.sh#65@a5c0acd`, and it carries a justification comment as `CONTRIBUTING.md#4` requires.
- No single-bracket `[ … ]` tests in `lib/` (the only grep hit is a comment at `lib/030-time-refs-records.sh#73`); `[[ ]]` appears 254 times and `(( ))` 106 times, used for strings and arithmetic respectively, which is the consistent style.
- Every function name in `lib/` is `snake_case`; the six `_v` helpers (`json_paths_v`, `now_v`, `ancestors_v`, `field_v`, `record_paths_v`, `covering_v`) follow the documented convention; `_j1`…`_j5` are the uniform JSON-escape temporaries (76 uses, heaviest in `lib/170-semaphores.sh`).
- Markdown: no fenced block without a language across all nine `.md` files; no hard-wrapped prose (the heuristic's only hits were README front-matter lines 3–5); no ASCII art or box-drawing characters (grep for U+2500–U+257F is empty; all `|---|` hits are table separators); all diagrams are Mermaid (`README.md#101,#149,#195,#241,#306`); the six tab characters in `README.md` are inside code blocks reproducing `for-each-ref` output, where tabs are the literal format.
- YAML: `.github/workflows/ci.yml` has no odd-indented lines; two-space throughout.
- `git locks schema` is byte-identical to the minified `schema/git-locks.schema.json` (diff empty), as `README.md#440` claims.

### DX-05 (Medium): "No Python" is the rule; 671 lines of Python have no linter, formatter or ignore rule

**Evidence.** `CONTRIBUTING.md#5@a5c0acd`: "Pure bash and git only. No jq, no Python, no external daemons." Reality at HEAD: `test/capacity.py`, `test/cooperating-workers.py`, `test/family-model.py`, `test/observation/study.py`, `test/observation/verify-evidence.py`, 671 lines total (`wc -l`), plus `scripts/build.sh#9` which means the shipped artefact cannot be built without Python. No `pyproject.toml`, `setup.cfg`, `ruff.toml`, `.flake8`, or `mypy.ini` exists; `Makefile#lint` does not touch `.py`; CI does not either. `python3 -m py_compile` passes, 47 lines exceed 100 columns, no tabs. `.gitignore@a5c0acd` has no `__pycache__/` rule: running `py_compile` during this audit left two untracked `__pycache__/` directories in the checkout (removed afterwards).

**Why it matters.** The runtime rule is honoured and valuable (`bin/git-locks` is bash and git only). But the written rule is now false for the repository, and the Python that enforces correctness (the independent family model, the capacity oracle, the observation study's oracle) is the only code in the repository held to no standard at all. "Zero lint output" means nothing for a third of the test logic.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. CONTRIBUTING.md line 5 says "No Python", yet test/*.py and test/observation/*.py total 671 lines and scripts/build.sh requires python3. These files have no linter, formatter, type checker or config, and .gitignore lacks __pycache__/.

Task:
1. Rewrite CONTRIBUTING.md line 5 as two rules: (a) bin/git-locks is bash and git only, no runtime dependency ever; (b) test tooling and the build may use python3 (standard library plus jsonschema only), held to the same "zero lint output" bar as the shell.
2. Add a `pyproject.toml` with a [tool.ruff] section at maximum strictness consistent with the repo's linter policy (select ALL, line-length 100, target py310), and a [tool.ruff.format] section; add `__pycache__/` and `*.pyc` to .gitignore.
3. Extend the Makefile: `lint` runs `ruff check` and `ruff format --check` over test/*.py test/observation/*.py after shfmt; add `PY_SCRIPTS :=` beside SCRIPTS. Install ruff in CI's lint-and-test job (`pipx install ruff` or `pip install ruff`), and document it in README Develop.
4. Failing test first: add a case to test/test.sh "make lint covers every tracked .py" that lists `git ls-files '*.py'` and asserts each appears in the Makefile's PY_SCRIPTS. Show it red, then green.
5. Fix every ruff finding in the five files (expect long lines, missing type hints, broad excepts). Do not change behaviour; the shell suites that call these files (test/test.sh, test/family-replacement.sh) must stay green.

Acceptance: `make lint` zero output including Python; `make test` unchanged in pass counts; CHANGELOG Unreleased entry.
```

### DX-06 (Low): Executable bits are inconsistent

**Evidence.** `git ls-files -s`: `test/literal-paths.sh`, `test/unicode-locale.sh`, `test/unicode-locale-calibration.sh`, `examples/cooperating-workers/*.sh`, `scripts/build.sh`, hooks are `100755`; `test/test.sh`, `test/family-replacement.sh`, `test/directory-token-churn.sh`, `test/observation/git-shim.sh`, `scripts/benchmark-directory-tokens.sh` and every `.py` are `100644`. All of them carry a shebang.

**Why it matters.** `./test/literal-paths.sh` works and `./test/test.sh` says `Permission denied`. The Makefile hides this by prefixing `bash`, so the inconsistency only bites someone running a suite directly, which is exactly what a developer does when one suite fails.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. Executable bits are inconsistent: test/test.sh, test/family-replacement.sh, test/directory-token-churn.sh, test/observation/git-shim.sh, scripts/benchmark-directory-tokens.sh and all .py files are 100644 while sibling scripts with shebangs are 100755.

Task:
1. Failing test first: add a case to test/test.sh "every tracked file with a shebang is executable" that iterates `git ls-files`, reads the first two bytes, and asserts mode 100755 via `git ls-files -s` for each `#!` file. Show it red.
2. `git update-index --chmod=+x` on each offending file (list them in the commit body). Do not change content.
3. Add the same check to scripts/hooks/pre-commit so it cannot regress.

Acceptance: new test green; `make lint` clean; CHANGELOG Unreleased under Fixed.
```

### DX-07 (Low): Three error helpers with three contracts

**Evidence.** `lib/020-errors.sh#3-16@a5c0acd` defines `fail` (exit 1 → `reason:"failed"`, exit 2 → `reason:"usage"`) and `store_error` (exit 2, `reason:"store-read"`). `lib/000-prelude.sh#136-141@a5c0acd` defines `usage`, which prints the whole `usage_text` as one object and exits 2 with no `detail`. Call counts in `lib/`: `|| usage` 46, `fail ` 63, `store_error` 17, `|| missing` 3. The same condition class is routed differently: `--wait abc` → `fail '--wait is a number of seconds' 2` (`lib/160-with.sh#102`) with a precise detail; a missing path list → bare `usage` (`lib/090-claim-planning.sh#393`) with none. Non-usage failures are labelled `usage`: `mkdir -p "${STORE}" || fail "cannot create the lock store at …" 2` (`lib/040-the-store.sh#23`) is a permissions failure reported as `{"reason":"usage"}`.

**Why it matters.** A consumer of the JSON contract cannot tell "you typed it wrong" from "the disk said no" from "argument missing", because all three arrive as exit 2 and two of them say `usage`. The user-facing consequence is DX-17 and DX-18 below; this entry records the structural cause.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. lib/020-errors.sh and lib/000-prelude.sh give three error helpers with divergent contracts: `usage` (no detail, prints the full manual), `fail msg 2` (reason "usage" even for I/O failures like `cannot create the lock store`), `store_error` (precise). 46 call sites use bare `usage`.

Task:
1. Define the reason vocabulary in schema/git-locks.schema.json first: extend the error object's `reason` enum to {"usage","failed","store-read","store-create"} and make `detail` required for every reason. Write the failing tests in test/test.sh: (a) `claim --job x --holder y` (no paths) emits `reason:"usage"` with `detail` matching /path/ and exit 2, and the object validates; (b) a store under a read-only parent emits `reason:"store-create"`, exit 2, and the raw `mkdir:` line is absent from stderr. Show both red.
2. Give `usage` a required message argument: `usage 'claim needs at least one path'`. Emit `{"event":"error","reason":"usage","detail":<msg>,"usage":<the one-line synopsis for that subcommand from sub_usage_text>}`. Keep the full manual for `git locks help` only.
3. Route store creation through a new `store_create_error` (reason "store-create") and redirect mkdir/git init stderr into the detail.
4. Update all 46 `|| usage` sites with a specific message. Update README "Output: JSON Lines" to document the four reasons.

Acceptance: both tests green, schema validation of every provoked line still passes (the suite does this), `make lint` clean, README and CHANGELOG updated.
```

### DX-08 (Low): 107 uppercase globals act as return registers

**Evidence.** `grep` over `lib/*.sh` counts 49 uppercase names assigned at column 0 (`B_*`, `BATCH_*`, `D_*`, `R_*`, `T_*`, `PLAN_*`, `TERMINATED_*`, `CLAIM_LINE`, `BUMPED`, …) and 58 distinct uppercase names assigned inside functions (`W_*` in `lib/160-with.sh#37-43`, `CA_*` in `lib/090-claim-planning.sh#343-348`, `SEM_CAP`, `ACQUIRED_LINE`, …). `CONTRIBUTING.md#9-11@a5c0acd` documents why: `printf -v` into named variables survives where `$(…)` would fork and forget.

**Why it matters.** The idiom is deliberate and defensible in bash, and issue #11 (closed) already addressed the worst of it. It is recorded here as the one systemic style cost the repository carries: any function may read or clobber `D_HOLDER` or `W_TTL`, and nothing but discipline prevents a `with` invocation's `W_PATHS` from being read by a planner. No new issue is proposed; the item is a tracked trade-off.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. lib/ uses ~107 uppercase globals as cross-function return registers (D_*, B_*, R_*, W_*, CA_*, PLAN_*, …) because printf -v into named variables is the fork-free idiom (CONTRIBUTING.md). This is a documented trade-off, not a bug.

Task (documentation only, no behaviour change):
1. Add a "Register conventions" subsection to CONTRIBUTING.md listing each prefix, the module that owns it (D_ = describe in 050-the-snapshot.sh, R_ = record validation in 055, T_/PLAN_ = 060-the-transition-plan.sh, B_/BATCH_ = 100-batch.sh, CA_ = claim_args, W_ = cmd_with, SEM_ = 170-semaphores.sh), and the rule: only the owning module writes them; everyone else reads.
2. Add a test to test/test.sh "register prefixes are written only by their owning module" that greps lib/*.sh for `^\s*<PREFIX>_[A-Z_]*=` and asserts the file list per prefix equals the documented owner. Show it red if any cross-writes exist today and either fix them or document the exception inline with a comment.

Acceptance: test green; CONTRIBUTING updated; no change to bin/git-locks behaviour (make build output byte-identical except where a comment was added).
```

### DX-09 (Low): Markdown has no lint configuration or CI step

**Evidence.** No `.markdownlint*` file exists. `markdownlint-cli2` with default rules reports only MD013 line-length across README and SECURITY, which is the house rule's intended state (one physical line per paragraph). With MD013 disabled (temp config in scratch) the remaining hits are `README.md#317,#324,#414` and similar: MD033 inline HTML for the deliberate `<details><summary>` figure captions, and MD060 table-column style for the compact `|---|---|` separators. Nothing in CI runs any Markdown check.

**Why it matters.** The repository's Markdown is currently clean by hand. The house rule that makes it clean (no MD013, compact tables allowed, `<details>` allowed) exists only in people's heads.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. Markdown style is clean by convention but unenforced: no .markdownlint config, no CI step. House rules: one physical line per paragraph (MD013 off), compact table separators (MD060 off or style "compact"), <details>/<summary> allowed (MD033 allowed_elements), fenced blocks must have a language (MD040 on), Mermaid not ASCII art.

Task:
1. Add `.markdownlint-cli2.jsonc` encoding exactly those rules, with a comment per rule saying why.
2. Add `make lint-md` running `markdownlint-cli2 $(git ls-files '*.md')` and call it from `lint`; install markdownlint-cli2 in CI's lint-and-test job via `npm install -g markdownlint-cli2`.
3. Failing test first: in test/test.sh add "every fenced block in tracked Markdown names a language" implemented in bash (awk over ``` openers), show it red by temporarily adding a bare fence in a scratch copy, then green against the real tree.

Acceptance: `make lint` zero output; CI green; CONTRIBUTING gains one bullet on Markdown style and the wide-md convention.
```

### Policy decision: tabs versus spaces

The audit brief prefers tabs; the repository enforces two-space indentation through `shfmt -i 2 -ci -bn` in `Makefile#12@a5c0acd`, CI (`ci.yml#75`), and the pre-commit hook. The code is 100% consistent with the enforced standard: `shfmt -d` is silent on every file including the fragments, and the only tabs in the repository are the literal `for-each-ref` output in README code blocks and the Makefile's recipe lines, where make requires them. This is recorded as a decision, not a defect.

| Option | For | Against |
|---|---|---|
| Keep two spaces (current) | Zero migration cost; shfmt, shellcheck, CONTRIBUTING, hooks and CI already agree; heredocs in `usage_text` are column-aligned for a 2-space world | Diverges from the audit brief's preference |
| Switch to tabs (`shfmt -i 0`) | Reader-configurable width; matches the brief | Touches every line of 2 611 lib lines plus tests in one commit, destroying `git blame`; `-ci` (indent case labels) interacts with tabs in heredoc continuation lines in `usage_text`; the committed `bin/git-locks` must be rebuilt and byte-compared; no functional gain |

Recommendation: keep two spaces and write the choice into `CONTRIBUTING.md#4` as explicit policy ("two-space indentation, enforced by shfmt; tabs only where make requires them").

## Q3. README Reality Check

### Ranking

| Rank | Finding | Why it ranks here |
|---|---|---|
| 1 | DX-10 "bash 4 or newer" | A documented support floor that crashes four core commands with raw bash text; verified on a real 4.3.30 |
| 2 | DX-03 / DX-02 Develop and Install omit the toolchain and PATH | The first two things a new developer runs can fail with no documented cause |
| 3 | DX-11 help text disagrees with README and code | The tool's own `--help`, which the README calls a usage object, is the stale copy |
| 4 | DX-12 "free the moment its time is up" versus `extend` reviving an expired lock | A liveness statement in the model section that one command contradicts |
| 5 | DX-13 / DX-14 Commands table omissions and exit codes | Reference-table drift, low blast radius |

### DX-10 (High, crowned): "bash 4 or newer" is false

**Evidence.** `README.md#476@a5c0acd`: "bash 4 or newer: the store snapshot uses associative arrays." `lib/000-prelude.sh#52-55@a5c0acd` refuses only `BASH_VERSINFO[0] < 4`, and `lib/000-prelude.sh#51` sets `set -uo pipefail`. Under bash 4.3.30 (scratch build, `GNU bash, version 4.3.30(1)-release (arm-apple-darwin25.6.0)`), against a fresh store with `GIT_LOCKS_NOW=1757980800`:

```text
$ bash-4.3.30 bin/git-locks claim --job a --holder alice notes/report.md
bin/git-locks: line 1252: evict[@]: unbound variable          (exit 1)
$ bash-4.3.30 bin/git-locks claim --job b --holder bob file.md
bin/git-locks: line 1164: ancs: unbound variable              (exit 1)
$ bash-4.3.30 bin/git-locks release --job a
bin/git-locks: line 1548: superseded[@]: unbound variable     (exit 1)
$ bash-4.3.30 bin/git-locks with --job w --holder alice x.md -- true
bin/git-locks: line 1164: ancs: unbound variable              (exit 1)
$ bash-4.3.30 bin/git-locks doctor
bin/git-locks: line 2452: jobs[@]: unbound variable           (exit 1)
```

`check`, `list` and `store` happen to work. The built lines map to `lib/090-claim-planning.sh#271` (`for ej in "${evict[@]}"`), `lib/090-claim-planning.sh#183` (`while [[ -n "${ancs}" ]]`, a `local ancs` declared without a value at `#180`), `lib/110-release.sh#84` (`for j in "${superseded[@]}"`) and `lib/175-doctor.sh#121` (`for job in "${jobs[@]}"`). Bash 4.4 changed `set -u` to tolerate `"${empty[@]}"`; 4.0–4.3 do not. `docs/benchmarks/directory-tokens.md#23@a5c0acd` already says "Requirements are Bash 5", contradicting the README. bash 3.2 is refused cleanly as designed. The PR-sweep journal flagged this; it is confirmed here with a reproduction.

**Why it matters.** The exit code is 1, which the contract (`README.md#356`) defines as "refused or held". A wrapper that treats 1 as "someone else holds it" will wait or retry forever on a bash 4.3 host, and the stderr is not JSON, violating "JSON Lines, always" (`README.md#352`). Debian 8, RHEL 7 and several embedded images shipped 4.3 as `/bin/bash`.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. README.md line 476 and lib/000-prelude.sh lines 52-55 promise "bash 4 or newer", but bash 4.0-4.3 crash under `set -u` on empty-array expansions: claim (lib/090-claim-planning.sh:271 `"${evict[@]}"`, :183 `${ancs}` declared with `local ancs` and no value), release (lib/110-release.sh:84 `"${superseded[@]}"`), doctor (lib/175-doctor.sh:121 `"${jobs[@]}"`). Verified on bash 4.3.30: raw `unbound variable` text on stderr, exit 1.

Decide and implement ONE of:
(A) Raise the floor to 4.4: change the prelude check to `((BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 4)))`, keep the JSON-free one-line refusal but mention 4.4, update README line 476 and the Limits list, docs/benchmarks/directory-tokens.md line 23, CHANGELOG.
(B) Support 4.0+: initialise every `local` array/scalar that is expanded before assignment (`local ancs=''`, `local -a evict=()` plus `${evict[@]+"${evict[@]}"}` at expansion sites), and add a CI job that runs the suite under a bash 4.3 build (e.g. compile 4.3.30 from gnu.org in a cached step).

Either way, test first: add to test/test.sh a case "startup refuses bash below the documented floor with exit 2" using a stub bash that fakes BASH_VERSINFO=(4 3 30) — or, if option B, a case that runs claim/release/doctor under the real 4.3 binary when `GIT_LOCKS_TEST_BASH43=<path>` is set and skips visibly otherwise. Show it red.

Acceptance: the README sentence, the prelude check, docs/benchmarks and CHANGELOG all state the same floor; make build run and bin/git-locks committed with the lib change; make lint clean; the suite green.
```

### DX-11 (Medium): help text disagrees with the README and the code

**Evidence.** `with` accepts `--parent` (`lib/160-with.sh#73-77@a5c0acd`) and the README lists it (`README.md#335,#426`), but `usage_text` at `lib/000-prelude.sh#79` and `sub_usage_text with` at `lib/000-prelude.sh#162` omit it; verified: `git locks with --help` prints `[--sem <name>] [--note <text>] [<path>...]` with no `--parent`. `release` usage reads `[--record <oid> | --acquisition <id>]` (`lib/000-prelude.sh#71,#154`), but `cmd_release` accepts both on one job and requires both to match (`lib/110-release.sh#14-26,#51-61`); verified with both flags on a live job: `{"event":"released","job":"h","paths":1}`, exit 0. The README row at `README.md#425` is correct ("if both are given, both must match"), so the README is right and the tool's own help is the stale copy. The header comment at `lib/000-prelude.sh#4-16` has a third, older synopsis set (no `--note` on `with`, no `doctor`).

**Why it matters.** `README.md#354` says `git locks help` is a usage object that is part of the output contract. Three synopsis sources (header comment, `usage_text`, `sub_usage_text`) are hand-maintained and have already drifted from each other and from the parsers.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. Three hand-written synopsis sources in lib/000-prelude.sh (header comment lines 4-16, usage_text lines 69-84, sub_usage_text lines 150-167) disagree with the parsers: `with --parent` (lib/160-with.sh:73) is missing from both help texts; `release` help says `--record | --acquisition` but lib/110-release.sh accepts both and requires both to match (README.md:425 documents the latter correctly).

Task:
1. Failing tests first in test/test.sh: (a) "with --help lists every flag the parser accepts": extract `--[a-z]+)` case labels from the cmd_with parser in bin/git-locks and assert each appears in `git locks with --help`; (b) same for claim, release, extend, sem acquire/release; (c) "release help states both conditions may be combined". Show them red.
2. Make sub_usage_text the single source: have usage_text's synopsis block be generated by calling sub_usage_text for each command (so there is one string per command), and delete the header-comment synopsis in favour of a one-line pointer to `git locks help`.
3. Add `--parent <id>` to the with synopsis; change release to `[--record <oid>] [--acquisition <id>]` with the description "give one or both; each must match".
4. Rebuild bin/git-locks, update README Commands rows if wording changes, CHANGELOG under Fixed.

Acceptance: tests green; `git locks help` and every `<cmd> --help` agree with the README table; make lint clean.
```

### DX-12 (Medium): "free the moment its time is up", except for `extend`

**Evidence.** `README.md#231@a5c0acd`: "A dead holder's lock is free the moment its time is up." `README.md#221`: `check` reports an expired lock as `expired` and "exits 0 for that path because it is free to take." `cmd_extend` at `lib/140-extend.sh#8-22@a5c0acd` reads the record, computes `expires=$((at + ttl))` and rewrites it with no liveness check. Reproduced with a 10 s TTL and the clock advanced by 9 200 s:

```text
$ GIT_LOCKS_NOW=1757990000 git locks check e.md
{"path":"e.md","state":"expired","holder":"a","job":"e","expires":1757980810,"remaining":0}   (exit 0)
$ GIT_LOCKS_NOW=1757990000 git locks extend --job e --ttl 100
{"event":"extended","job":"e","expires":1757990100}                                            (exit 0)
$ GIT_LOCKS_NOW=1757990000 git locks check e.md
{"path":"e.md","state":"held","holder":"a","job":"e","expires":1757990100,"remaining":100}     (exit 1)
```

A path that `check` called free and that any claimant could have taken is held again by the old holder, with the old acquisition id, no new `claimed`, and no transaction with anyone who observed it free.

**Why it matters.** The README's expiry model has one rule: expiry is a field, and after it a writer may evict. `extend` lets the expired holder win against an eviction without going through a claim. A worker that stalled past its TTL and then renewed would believe it had held the path continuously.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. cmd_extend (lib/140-extend.sh:8-22) rewrites a record's expires without checking liveness, so an expired lock that `check` reported as free (exit 0) can be revived by its old holder. README.md:231 says an expired lock "is free the moment its time is up".

Task:
1. Failing test first in test/test.sh: "extend refuses an expired lock": claim with --ttl 10 at GIT_LOCKS_NOW=T, then at T+100 run extend --ttl 100 and assert exit 1, stderr is one object `{"event":"refused","reason":"expired","job":"e","expires":<T+10>}` that validates against the schema, and `check` still reports `expired`. Add a second case "extend of a live lock still succeeds" guarding the existing behaviour. Show the first red.
2. In cmd_extend, after `describe "${oid}"`, call `record_live "${oid}" "${at}"` (lib/120-check.sh:43) and on failure emit the refusal via lib/070-refusals.sh conventions and exit 1. Add `"expired"` to the refusal `reason` enum in schema/git-locks.schema.json.
3. Decide and document the same for `sem acquire` re-acquiring an expired slot of the same job (lib/170-semaphores.sh): either a fresh acquisition id or a refusal; add the test.
4. README: add one sentence to the Expiry section and the extend row of the Commands table ("exit 1 if expired"); CHANGELOG under Changed with a Breaking marker, since scripts renewing late will now fail.

Acceptance: tests green; make build; bin/git-locks committed; make lint clean.
```

### DX-13 (Low): README `sem release` row omits `--record` and `--acquisition`

**Evidence.** `README.md#432@a5c0acd` row: `sem release <name> --job <id>`. The parser accepts `--record` and `--acquisition` (`lib/170-semaphores.sh#272-278@a5c0acd`), `usage_text` lists them (`lib/000-prelude.sh#81`), and `README.md#364` says "Semaphore slots carry the same two ids." The reference table is the one place that forgot.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. README.md line 432, the `sem release` row of the Commands table, omits `[--record <oid>] [--acquisition <id>]`, which lib/170-semaphores.sh:272-278 accepts and the usage text lists.

Task: failing test first in test/test.sh "README command rows list every flag the parser accepts" (parse the Commands table rows for claim, release, extend, with, sem acquire, sem release; extract `--[a-z]+)` labels from the corresponding parser in bin/git-locks; assert containment). Show it red on sem release, fix the row, keep the test. CHANGELOG under Fixed.
```

### DX-14 (Low): Commands table exit column is incomplete for `release`, `list`, `sweep`

**Evidence.** `README.md#417,#418,#425@a5c0acd` give exit `0` only. `cmd_release` exits 1 when 200 re-plans fail (`lib/110-release.sh#72-75`) and every command that reads the store exits 2 on `store_error` (`lib/020-errors.sh#11-16`), which `README.md#380` documents in prose but the table does not reflect. `with`'s row (`#426`) does not mention exit 2 either, though a store-read failure before acquisition exits 2.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. The README Commands table (lines 413-436) lists exit `0` alone for list, sweep and release, and omits exit 2 everywhere, while lib/110-release.sh:72-75 exits 1 after exhausting RETRIES and every store-reading command exits 2 on store-read (lib/020-errors.sh:11-16).

Task: add a one-line note above the table ("every command exits 2 when the store cannot be read; see 'What a failed read is'") and add "1 if the transaction kept failing" to the release, extend, sweep and sem rows that can exhaust RETRIES. Test first: extend the existing store-read tests in test/test.sh to assert exit 2 for list, sweep and release on a store whose refs/ directory was removed (the probe for this audit got `for-each-ref exited 128: fatal: not a git repository`), if any is missing. CHANGELOG under Fixed (docs).
```

## Q4. Error Usability and POLA

### Collected runtime errors, as seen

| Provocation | Exact stderr (first line) | Exit | Verdict |
|---|---|---|---|
| `claim --job x --holder y` (no paths) | `{"event":"usage","usage":"usage: git locks claim   --job <id> …` (4 414 bytes, the whole manual) | 2 | DX-17 |
| `sem` (no subcommand), `with … p.md echo hi` (no `--`) | same 4 414-byte object | 2 | DX-17 |
| `claim … $'a\nb'` | `{"event":"error","reason":"usage","detail":"a path with a newline is not supported"}` | 2 | good |
| `claim … --ttl abc`, `--ttl 0`, `--ttl -5` | `{"event":"error","reason":"usage","detail":"--ttl is a positive number of seconds"}` | 2 | good |
| `claim … --ttl 9223372036854775807 o.md` | `{"event":"claimed",…,"expires":-9223372035096795009,…}` on stdout | 0 | DX-15 |
| then any command on that store | `{"event":"error","reason":"store-read","detail":"refs/locks/paths/fbd9…: record 0351…: invalid expires"}` | 2 | DX-15 |
| `claim … --ttl 99999999999999999999 o.md` | `{"event":"claimed",…,"expires":7766279633210222719,…}` | 0 | DX-15 (silent 64-bit wrap) |
| `GIT_LOCKS_NOW=abc git locks list` | `bin/git-locks: line 569: abc: unbound variable` | 1 | DX-16 |
| `GIT_LOCKS_STORE=<read-only parent>/store git locks list` | `mkdir: …: Permission denied` then `{"event":"error","reason":"usage","detail":"cannot create the lock store at …"}` | 2 | DX-18 |
| `GIT_LOCKS_STORE=<plain file>` | `mkdir: …: File exists` then the same `usage` object | 2 | DX-18 |
| `GIT_LOCKS_STORE=<existing dir with files>` | nothing; the directory is now a bare git repository | 0 | DX-18 |
| `git locks store` with no store yet | nothing; the store is created as a side effect of asking where it is | 0 | DX-18 |
| `GIT_LOCKS_STORE=relstore` from repo root and from `sub/` | two different stores | 0 | DX-19 |
| `with … -- definitely-not-a-command` | `bin/git-locks: line 1952: definitely-not-a-command: command not found` | 127 | DX-20 |
| corrupt record (garbage blob) | `{"event":"error","reason":"store-read","detail":"refs/locks/jobs/good: record 9ce7…: invalid header line"}` | 2 | good: names ref and oid |
| store `refs/` removed mid-life | `{"event":"error","reason":"store-read","detail":"for-each-ref exited 128: fatal: not a git repository: '…'"}` | 2 | good |
| `GIT_LOCKS_STORE=self` outside a repo | `{"event":"error","reason":"usage","detail":"GIT_LOCKS_STORE=self needs a git repository; this directory is not in one"}` | 2 | good message, wrong reason (DX-07) |
| `check` on a held path | one `held` object on stdout | 1 | documented and intended (`README.md#473`); not a defect |
| `with --wait 2` on a held path | `refused` after 2.4 s | 1 | matches `README.md#344` |
| `with -- bash -c 'trap … INT; kill -INT $$'` | command's own trap ran, `released` | 0 | matches the command's status; not a defect |
| `batch` with no records / unknown line / missing fields | `{"event":"error","reason":"usage","detail":"batch: no records on stdin"}` etc. | 2 | good |
| `sem create s --capacity 0` / `abc` | `{"event":"error","reason":"usage","detail":"--capacity is a decimal integer from 1 through 9223372036854775807"}` | 2 | good |

### DX-15 (High, POLA winner): a large `--ttl` is accepted and poisons the store for everyone

**Evidence.** `valid_ttl` at `lib/030-time-refs-records.sh#39-44@a5c0acd` accepts any digit string whose `$((10#…))` is positive; `plan_claim` computes `expires=$((at + ttl))` at `lib/090-claim-planning.sh#73`, `cmd_extend` at `lib/140-extend.sh#15`, and the semaphore path at `lib/170-semaphores.sh#313` likewise, with no bound. Record validation on read (`lib/055-record-validation.sh`, CHANGELOG Unreleased "Reject malformed stored records", #33) then refuses what the writer just wrote. Reproduced on three fresh stores:

```text
$ git locks claim --job o --holder a --ttl 9223372036854775807 o.md
{"event":"claimed","job":"o","holder":"a","claimed":1757980800,"expires":-9223372035096795009,"paths":["o.md"],…}   (exit 0)
$ git locks list
{"event":"error","reason":"store-read","detail":"refs/locks/paths/fbd9c3fd…: record 03513b86…: invalid expires"}   (exit 2)
$ git locks sweep                     # same error, exit 2
$ git locks release --job o           # same error, exit 2
$ git locks claim --job unrelated --holder a other.md   # same error, exit 2
$ git locks doctor                    # finding record-decodes + a spurious path-ref-stray, exit 1

$ git locks extend --job e --ttl 9223372036854775807
{"event":"extended","job":"e","expires":-9223372035096795009}      (exit 0) ; list → store-read, exit 2
$ git locks sem acquire s --job j --holder h --ttl 9223372036854775807
{"event":"acquired",…,"expires":-9223372035096795009,…}            (exit 0) ; sem list → store-read, exit 2

$ git locks claim --job o --holder a --ttl 99999999999999999999 o.md
{"event":"claimed",…,"expires":7766279633210222719,…}              (exit 0)  # silent wrap past 2^64, a lock until year ~2.4e11
```

**Why it matters.** This is the ASVS V5 input-validation class with a persistence twist: one cooperating worker, with one mistyped or computed-overflowed `--ttl`, takes every other worker's store from working to exit 2 on every command. The tool's own repair paths (`sweep`, `release`) fail on the same read. The only recovery is `git --git-dir <store> update-ref -d` by someone who reads the doctor output. The "fail closed on corrupt records" hardening from #33 is correct; what is missing is refusing to write what the reader will refuse. The 2^64 wrap case is worse in a different way: it is silent and the lock is effectively permanent.

**Replacement behaviour.** Refuse at the parser: `--ttl` must satisfy `ttl <= 9223372036854775807 - now` (and, more usefully, a sane ceiling such as 10 years) with `{"event":"error","reason":"usage","detail":"--ttl 9223372036854775807 overflows expires; the maximum is <N> seconds"}`, exit 2, before any write.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. valid_ttl (lib/030-time-refs-records.sh:39-44) accepts any positive digit string. `expires=$((at + ttl))` in lib/090-claim-planning.sh:73, lib/140-extend.sh:15 and lib/170-semaphores.sh (acquire) overflows signed 64-bit: `--ttl 9223372036854775807` writes `expires: -9223372035096795009`, the record validator (#33) then rejects it on every read, and the whole store answers exit 2 to every command including sweep and release. `--ttl 99999999999999999999` wraps past 2^64 to a positive value silently.

Task:
1. Failing tests first in test/test.sh: (a) "claim refuses a ttl that would overflow expires": `--ttl 9223372036854775807` → exit 2, stderr one object reason "usage", detail matches /overflow|maximum/, and `list` on the store afterwards is still exit 0 with no records; (b) same for extend and sem acquire; (c) "claim refuses a ttl beyond 64 bits": `--ttl 99999999999999999999` → exit 2, no record written; (d) "ttl at the maximum accepted value round-trips": pick MAX_TTL and assert claim then list succeed. Show (a)-(c) red.
2. Implement in valid_ttl: reject strings longer than 19 digits; compute the bound against the clock (`now_v`) so `at + ttl <= 9223372036854775807`; introduce `MAX_TTL=315360000` (ten years) in the prelude as the documented ceiling and use it as the effective bound (the 64-bit check then becomes defence in depth). Make the error detail state the number given and the maximum.
3. README: "A ttl is a decimal number of seconds" (line 442) gains "at most MAX_TTL (ten years)"; the Limits list gets one bullet. schema: if `ttl` or `expires` have numeric definitions, add maximum. CHANGELOG under Fixed with a note on recovery for stores already poisoned (`git --git-dir <store> update-ref -d refs/locks/jobs/<job>` plus its path refs, as doctor lists them).
4. Separately note in doctor: the `path-ref-stray` finding emitted for a record that failed to decode is spurious (the paths could not be read); suppress stray/missing checks for records already reported under record-decodes, with a test.

Acceptance: tests green; make build; bin/git-locks committed; make lint clean.
```

### DX-16 (Medium): `GIT_LOCKS_NOW=abc` leaks a raw bash error and exits 1

**Evidence.** `now_v` at `lib/030-time-refs-records.sh#3-12@a5c0acd` copies `GIT_LOCKS_NOW` unvalidated into `NOW_CACHED`. Arithmetic then explodes wherever it is first used: `list` → `bin/git-locks: line 569: abc: unbound variable` (`lib/050-the-snapshot.sh#169`, `D_REMAINING=$((D_EXPIRES - at))`), `check` → line 1603 (`lib/120-check.sh#46`), `claim` → line 1054 (`lib/090-claim-planning.sh#73`), all exit 1. The README documents the variable as "for tests" (`README.md#444`), but it is read in production and has no guard.

**Why it matters.** Exit 1 means "refused or held" in this contract; a retry loop will spin. The stderr is not JSON. And because `now()` is also an arithmetic sink for `expires - now`, a value like `GIT_LOCKS_NOW=1e9` or an injected `GIT_LOCKS_NOW='a[$(touch /tmp/x)]'` enters `$(( ))`, which in bash evaluates array subscripts and therefore command substitutions; a CI environment that lets users set env vars for the job but not run arbitrary code would be surprised. Validate it or ignore it.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. now_v (lib/030-time-refs-records.sh:3-12) uses GIT_LOCKS_NOW verbatim; `GIT_LOCKS_NOW=abc git locks list` dies with `bin/git-locks: line 569: abc: unbound variable`, exit 1 (the "refused/held" code). Values reach `$(( ))`, which evaluates subscripts and so command substitutions.

Task:
1. Failing tests first in test/test.sh: (a) `GIT_LOCKS_NOW=abc git locks list` → exit 2, stderr one object `{"event":"error","reason":"usage","detail":"GIT_LOCKS_NOW must be epoch seconds (digits only); got 'abc'"}`; (b) `GIT_LOCKS_NOW='x[$(touch '"$tmp"'/pwned)]'` → exit 2 and the file does not exist; (c) `GIT_LOCKS_NOW=0017` is accepted as 17 (decimal, matching the ttl rule). Show (a) and (b) red.
2. In now_v, validate with `[[ "${GIT_LOCKS_NOW}" =~ ^[0-9]{1,18}$ ]]` and normalise with `$((10#…))`; on failure call `fail … 2`. Do the same for GIT_LOCKS_PAUSE_* and GIT_LOCKS_TRACE only insofar as they are used in arithmetic (they are paths; just ensure they never reach `$(( ))`).
3. README line 444: state the accepted format. CHANGELOG under Fixed.

Acceptance: tests green; make build; make lint clean.
```

### DX-17 (Medium): any argument mistake prints the entire manual and never says what was wrong

**Evidence.** `usage()` (`lib/000-prelude.sh#136-141@a5c0acd`) prints `usage_json`, the full 58-line manual, as one 4 414-byte JSON line on stderr and exits 2, with no `detail`. It is the handler at 46 sites: `claim` with no paths (`lib/090-claim-planning.sh#393`), `claim` with no arguments, unknown command (`lib/990-main.sh#30`), `sem` with no subcommand, `with` without `--` (`lib/160-with.sh#100`), `release` with `--record` before any `--job` (`lib/110-release.sh#16`). The same tool answers `--ttl abc` with a one-line `detail` (`lib/090-claim-planning.sh#390`). A consumer sees `{"event":"usage"…}` with no indication whether a flag was misspelled, a value was missing, or `--` was forgotten.

**Why it matters.** The first error a new user meets is the worst one in the tool: 4.4 KB of escaped text in a terminal, the relevant line buried as `claim    lock the paths for the job…`. Machine consumers get the same blob and cannot distinguish causes. It also contradicts the README's own claim that errors are objects with a `reason` (`README.md#354`): the `usage` event has none.

**Replacement behaviour.** `{"event":"error","reason":"usage","detail":"claim needs at least one path","usage":"usage: git locks claim --job <id> --holder <name> [--ttl <seconds>] [--parent <id>] [--note <text>] <path>..."}`: the specific complaint, plus the one-line synopsis for that subcommand only. The manual stays behind `git locks help`.

**Action Prompt.** See DX-07; the prompt there covers this change end to end (schema, tests for the no-paths case, `usage` taking a message, per-subcommand synopsis, 46 call sites).

### DX-18 (Medium): `resolve_store` initialises a bare repository inside any existing directory, and misreports failures

**Evidence.** `lib/040-the-store.sh#22-25@a5c0acd`: if `${STORE}/HEAD` is not a file, `mkdir -p` then `git init -q --bare "${STORE}"`. Reproduced: `GIT_LOCKS_STORE=<dir containing file>` followed by `git locks list` printed nothing, exit 0, and the directory now contains `HEAD config description hooks/ info/ objects/ refs/` beside the original file. `git locks store`, a command whose only job is to say where the store resolves (`lib/990-main.sh#41` skips the snapshot but not `resolve_store` at `#40`), created a bare repository under `GIT_LOCKS_HOME` as a side effect. When creation fails, `mkdir`'s own stderr leaks (`mkdir: …: Permission denied`, `mkdir: …: File exists`) before a JSON object whose `reason` is `usage`.

**Why it matters.** `GIT_LOCKS_STORE=.` or `GIT_LOCKS_STORE=$HOME` turns the current project or the home directory into a bare git repository with no prompt and no message. The leaked `mkdir:` line breaks "JSON Lines, always" on stderr, and `reason:"usage"` sends the user to re-read the manual for a filesystem problem.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. resolve_store (lib/040-the-store.sh:22-25) runs `mkdir -p` + `git init --bare` into any path lacking HEAD, including a non-empty existing directory and including when the command is merely `git locks store`. Failures leak mkdir's stderr and are labelled reason "usage".

Task:
1. Failing tests first in test/test.sh: (a) "a non-empty non-repository directory is refused as a store": create a dir with a file, set GIT_LOCKS_STORE to it, run `git locks list`, assert exit 2, stderr is one object reason "store-create" (add to the schema enum) with detail naming the path and "is not empty and not a git repository", and the directory is unchanged (`ls` equals before); (b) "store does not create the store": with GIT_LOCKS_HOME under tmp, `git locks store` exits 0, prints the path, and the path does not exist afterwards; (c) "mkdir failure emits exactly one stderr line, JSON": read-only parent, assert `wc -l` of stderr is 1 and it parses. Show all red.
2. Implement: create only when the target is absent or an empty directory; otherwise refuse. Capture `mkdir`/`git init` stderr into the detail (`2>&1` into a variable). Use reason "store-create". Make cmd_store skip creation (resolve the path, do not materialise it; document that the first claim creates it).
3. README "The cast" (line 67) and the usage text `store:` line: state that the store is created on first write, never inside an existing non-empty directory. CHANGELOG under Fixed.

Acceptance: tests green; make build; make lint clean; existing store-creation tests still pass.
```

### DX-19 (Low): a relative `GIT_LOCKS_STORE` resolves against the current directory

**Evidence.** `lib/040-the-store.sh#20@a5c0acd`: `*) STORE="${PWD}/${sel}"`. From the repository root, `GIT_LOCKS_STORE=relstore git locks store` → `…/work/relstore`; from `work/sub/`, the same command → `…/work/sub/relstore`. The same is true for `git config locks.store relstore`, which the README calls persistent (`README.md#74`).

**Why it matters.** Two workers in the same repository with the same configuration can lock against different stores depending on their cwd, which is the one failure mode a lock tool must not have. Paths are repo-relative; the store should be too.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. lib/040-the-store.sh:20 resolves a relative GIT_LOCKS_STORE (or `locks.store`) against $PWD, so cwd decides the store.

Task: failing test first in test/test.sh "relative store resolves against the repository top level": set `git config locks.store relstore`, run `git locks store` from the root and from a subdirectory, assert identical output ending in `/relstore` at the top level; outside a repository, assert the fallback is $PWD and that stderr carries no warning (or decide to warn, and test that). Show it red. Implement with `git rev-parse --show-toplevel` (fall back to `${common%/.git}` for bare/worktree cases already computed as `key`). Update the usage text `store:` line and README line 74. CHANGELOG under Fixed.
```

### DX-20 (Low): `with` leaks the script's internal line number for a missing command

**Evidence.** `lib/160-with.sh#153@a5c0acd` runs `"${command[@]}" || status=$?`. With a nonexistent command: stderr shows `bin/git-locks: line 1952: definitely-not-a-command-xyz: command not found` between the `claimed` and `released` objects; exit 127 is correctly propagated and the lock is released.

**Why it matters.** The message names a line in a 2 618-line built script that the user did not write, and it is the one non-JSON line git-locks itself (not the wrapped command) puts on stderr in the normal flow. A pre-flight `command -v` makes the failure cheap and avoids taking and releasing a lock for nothing.

**Action Prompt.**

```text
Repository: git-stunts/locks at a5c0acd. cmd_with (lib/160-with.sh:153) executes the wrapped command without checking it exists; bash prints `bin/git-locks: line N: <cmd>: command not found` and the lock is claimed and released around nothing.

Task: failing test first in test/test.sh "with refuses a command that cannot be found before claiming": run `with --job w --holder h p.md -- no-such-cmd-xyz`, assert exit 127, stderr is one object `{"event":"error","reason":"failed","detail":"command not found: no-such-cmd-xyz"}` that validates, and `check p.md` is free with no claim ever written (use GIT_LOCKS_TRACE or `git --git-dir <store> reflog`/`for-each-ref` to assert no ref was created). Show it red. Implement with `command -v -- "${command[0]}" >/dev/null 2>&1 || fail "command not found: ${command[0]}" 127` after argument validation and before acquire_with_wait; let `fail` accept 127 and map it to reason "failed". README `with` section: one sentence. CHANGELOG under Fixed.
```

## Verification notes and what could not be verified

- **Could not verify:** `make test-docker`. The Docker daemon was not running (`Cannot connect to the Docker daemon at unix:///Users/james/.docker/run/docker.sock`). The recipe therefore remains unexecuted as far as this audit can establish (DX-04).
- **Could not verify:** the `git 2.31 or newer` floor at `README.md#475`; only git 2.54.0 was available. Cited, not tested.
- **Verified the brief's prior claims:** `release` accepting both conditions (yes), `with` usage omitting `--parent` (yes), `extend` reviving an expired lock (yes), the suite exceeding the budget (355 s here, exit 0), bash 4.3 crashing (yes, on four commands, not only `claim`). The lib line count is 2 611 at HEAD (`wc -l lib/*.sh`), not 2 428 as the brief stated; the built script is 2 618 lines.
- **Discarded after verification (15 of 35 candidates):** store-read errors "with no hint of which ref" (they name ref and oid: `refs/locks/jobs/good: record 9ce7…: invalid header line`); `# shellcheck disable` without justification (the single instance is justified); `*.sh` files missing from `SCRIPTS` (none outside `lib/`); mixed `[ ]`/`[[ ]]` (no `[ ]` in `lib/`); hard-wrapped Markdown prose (none); fenced blocks without a language (none); ASCII art (none); a dangling job ref as corruption (git refuses to write one with `update-ref`, so not reproducible through supported paths); a fully deleted store being silently recreated (consistent with the documented design that the store is created on first use); `with` masking the wrapped command's status on INT (the command's own trap status was preserved); schema drift between `git locks schema` and the file (byte-identical); the README transcript commit `01e39c3` (exists: "Merge pull request #31 from git-stunts/feat/prefix-locks"); YAML indentation (clean); `check` exiting 1 for held (documented, intended for scripting at `README.md#473`); tabs in README (literal git output inside code blocks).

## Sources

Files read at `a5c0acd1f96515b02106707bc2e42e82ce4463a7`: `README.md`, `CONTRIBUTING.md`, `CHANGELOG.md` (head), `Makefile`, `.gitignore`, `.github/workflows/ci.yml`, `scripts/build.sh`, `scripts/hooks/pre-commit`, `scripts/hooks/pre-push`, `scripts/benchmark-directory-tokens.sh` (lines 180-183), `lib/000-prelude.sh`, `lib/020-errors.sh`, `lib/030-time-refs-records.sh` (lines 1-47), `lib/040-the-store.sh`, `lib/050-the-snapshot.sh` (error sites, line 169), `lib/055-record-validation.sh` (error sites), `lib/090-claim-planning.sh` (lines 180-185, 240-275, 340-400), `lib/110-release.sh`, `lib/120-check.sh`, `lib/140-extend.sh`, `lib/160-with.sh`, `lib/170-semaphores.sh` (lines 8, 50, 272-313), `lib/175-doctor.sh` (line 121), `lib/990-main.sh`, `bin/git-locks` (line mapping), `test/test.sh` (grep), `test/unicode-locale.sh` (line 65), `examples/cooperating-workers/README.md`, `docs/benchmarks/directory-tokens.md` (line 23), `schema/git-locks.schema.json` (via `git locks schema` diff), `.claude/bad_code.md` and `.claude/cool_ideas.md` (untracked sweep journals, read to avoid duplicates).

Commands run (all in the Phase 1 scratch directory unless noted): `git clone`, `make install PREFIX=…`, `make lint`, `/usr/bin/time -l make test`, `make test-docker` (failed: no daemon), `git config --local core.hooksPath scripts/hooks`, `./examples/cooperating-workers/demo.sh <scratch>/demo-out`, the README transcript with `GIT_LOCKS_STORE=<scratch>/store GIT_LOCKS_NOW=1757980800`, the `with` and semaphore transcripts, `bash-4.3.30 bin/git-locks {claim,check,list,release,with,doctor}`, `/bin/bash bin/git-locks list`, the error provocations tabulated in Q4 (store permission, plain-file store, non-empty directory store, corrupt blob, bad `expires`, half-deleted store, `GIT_LOCKS_STORE=self` in and out of a repository, relative store from two directories, `--wait abc|0|2`, INT via the wrapped command, `extend` after expiry, malformed `batch` input, `sem` errors, `GIT_LOCKS_NOW=abc`, `--ttl` overflow on `claim`, `extend`, `sem acquire`), `shellcheck`/`shfmt` version checks, `shfmt -d -i 2 -ci -bn lib/*.sh`, `markdownlint-cli2` with and without MD013, `python3 -m py_compile test/*.py test/observation/*.py`, `git ls-files -s`, `gh issue list --state all --limit 60`, `docker info`, `/usr/libexec/path_helper -s`, `diff <(bin/git-locks schema) <(python3 -c … schema/git-locks.schema.json)`.

## Backlog candidates

Checked against `gh issue list --state all --limit 60`: open issues are #45, #41, #20, #14, #10, #9, #7, #2. Nothing below duplicates them. The PR-sweep journal (`.claude/bad_code.md`, untracked) already notes the bash floor, the usage drift and the `extend` revival; they are proposed here because no GitHub issue exists for them.

**BAD CODE**

- **A --ttl at or near INT64_MAX writes a negative expires and bricks the store for every command** — `valid_ttl` has no upper bound, `expires=$((at + ttl))` overflows, and the #33 record validator then refuses the store on every read, `sweep` and `release` included (DX-15) — bad-code
- **"bash 4 or newer" is false: 4.0–4.3 crash claim, release, with and doctor under set -u** — empty-array and declared-unset expansions at lib/090:183,271, lib/110:84, lib/175:121 die with raw `unbound variable`, exit 1; raise the floor to 4.4 or initialise and add a 4.3 CI job (DX-10) — bad-code
- **GIT_LOCKS_NOW is used unvalidated in arithmetic** — `GIT_LOCKS_NOW=abc` leaks `unbound variable` with exit 1, and the value reaches `$(( ))` where subscripts evaluate (DX-16) — bad-code
- **usage() prints the whole 4.4 KB manual with no detail for 46 argument errors** — a `claim` with no paths, `sem` with no subcommand or `with` without `--` all get the same blob; `fail` elsewhere gives one-line details; store-creation failures are labelled reason `usage` (DX-07, DX-17) — bad-code
- **resolve_store runs git init --bare inside any existing directory, and git locks store creates the store as a side effect** — `GIT_LOCKS_STORE=.` silently turns the project into a bare repo; `mkdir:` stderr leaks before the JSON error (DX-18) — bad-code
- **extend revives an expired lock without a liveness check** — a path `check` called free at exit 0 becomes held again by the old acquisition (DX-12) — bad-code
- **Three hand-maintained synopsis sources disagree with the parsers** — header comment, `usage_text` and `sub_usage_text` omit `with --parent` and misstate `release` conditions; derive one from the other (DX-11) — bad-code
- **make test takes 355 s and is the pre-push hook** — split a fast tier under 120 s from the full CI suite without dropping cases (DX-01) — bad-code
- **Python test tooling has no linter, formatter or ignore rule while CONTRIBUTING says "No Python"** — 671 lines across five files plus the build step's python3 call; add ruff and rewrite the rule as runtime-versus-toolchain (DX-05) — bad-code
- **A relative GIT_LOCKS_STORE resolves against $PWD, so cwd chooses the store** — resolve against the repository top level (DX-19) — bad-code
- **doctor reports path-ref-stray for a record that failed to decode** — the finding is spurious because the paths could not be read; suppress dependent checks after record-decodes fails (seen in DX-15's reproduction) — bad-code
- **Executable bits inconsistent across scripts with shebangs** — `./test/test.sh` is `Permission denied` while `./test/literal-paths.sh` runs (DX-06) — bad-code

**COOL IDEAS™**

- **`make doctor-dev`: print every toolchain prerequisite and its version in one screen** — bash, git ≥ 2.31, shellcheck, shfmt, python3 + jsonschema, GNU or BSD time, Docker; the README's Develop section links to it instead of listing versions (DX-03) — idea
- **Derive the README Commands table from sub_usage_text at build time** — `scripts/build.sh` already generates the schema module; a generated `docs/commands.md` or a checked-in table with a drift test closes DX-11, DX-13 and DX-14 permanently — idea
- **A `MAX_TTL` with a human unit in refusals** — "--ttl 9223372036854775807 exceeds the ten-year maximum (315360000 s)" reads better than a 64-bit boundary and gives DX-15 a product rule rather than an arithmetic one — idea
- **Test tiers with visible SKIP lines and a timing ranking** — `GIT_LOCKS_TEST_TIER=fast` plus per-case elapsed ms in `ok` lines makes the suite's cost legible and keeps pre-push honest (DX-01) — idea
- **`git locks store --create` versus a read-only `store`** — make creation explicit and let `store` answer the question it is asked (DX-18) — idea
- **A bash 4.3 compatibility job in CI, built once and cached** — whichever floor is chosen, the claim should be executed, not asserted (DX-10) — idea

Filed on 2026-10-02 as GitHub issues #52–#76 (`bad-code`) and #77–#86 (`idea`), consolidated across the three reports; findings that extend open issues were added as comments on #9 and #20 rather than filed again.
