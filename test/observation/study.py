#!/usr/bin/env python3
"""Synthetic observation-phase safety study; no live Git race is claimed.

The default command exits 1 when production leaves an invariant violation.
Experiment calibration failures exit 2. Output retains the actual failure,
not an expected-failure test result.
"""

import argparse
import copy
import itertools
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys

NOW = 1000000
ROOT = Path(__file__).resolve().parents[2]
GIT = shutil.which("git")


def execute(args, cwd, env=None, data=None):
    return subprocess.run(args, cwd=cwd, env=env, input=data, text=True, capture_output=True, timeout=30)


def git(store, *args, data=None):
    result = execute([GIT, f"--git-dir={store}", *args], store.parent, data=data)
    if result.returncode:
        raise RuntimeError((args, result.stderr))
    return result.stdout


def refmap(store):
    return dict(line.split() for line in git(store, "for-each-ref", "--format=%(refname) %(objectname)", "refs/locks/").splitlines())


def fields(body):
    header, sep, paths = body.partition("\npaths:\n")
    record = dict(line.split(": ", 1) for line in header.splitlines() if ": " in line)
    record["paths"] = paths.splitlines() if sep else []
    return record


def read_state(store):
    refs = refmap(store)
    objects = {oid: git(store, "cat-file", "blob", oid) for oid in set(refs.values())}
    return {"refs": refs, "objects": objects}


def violations(state):
    records = {ref: fields(state["objects"][oid]) for ref, oid in state["refs"].items()}
    jobs = {ref.removeprefix("refs/locks/jobs/"): r for ref, r in records.items() if ref.startswith("refs/locks/jobs/")}
    failures = []
    for name, record in jobs.items():
        parent = record.get("parent")
        if parent and (parent not in jobs or jobs[parent].get("holder") != record.get("holder") or int(jobs[parent]["expires"]) <= NOW):
            failures.append({"invariant": "family-parent", "job": name, "parent": parent})
        seen, ancestor = {name}, parent
        while ancestor in jobs:
            if ancestor in seen:
                failures.append({"invariant": "family-cycle", "job": name})
                break
            seen.add(ancestor)
            ancestor = jobs[ancestor].get("parent")
    for ref, record in records.items():
        if ref.startswith("refs/locks/sem/") and ref.endswith("/meta"):
            prefix = ref[:-4] + "slots/"
            live = sum(int(r["expires"]) > NOW for key, r in records.items() if key.startswith(prefix))
            if live > int(record["capacity"]):
                failures.append({"invariant": "semaphore-capacity", "semaphore": ref.split("/")[3], "live": live, "capacity": int(record["capacity"])})
    for (left, a), (right, b) in itertools.combinations(jobs.items(), 2):
        if min(int(a["expires"]), int(b["expires"])) <= NOW:
            continue
        for p, q in itertools.product(a["paths"], b["paths"]):
            if p == q or (p.endswith("/") and q.startswith(p)) or (q.endswith("/") and p.startswith(q)):
                failures.append({"invariant": "prefix-exclusivity", "jobs": [left, right], "paths": [p, q]})
    return failures


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")


def write_refs(path, refs):
    path.write_text("".join(f"{ref} {oid}\n" for ref, oid in sorted(refs.items())))


def scenario(case, domain, seed, binary):
    case.mkdir(parents=True)
    store = case / "store.git"
    env = dict(os.environ, HOME=str(case / "home"), GIT_LOCKS_STORE=str(store), GIT_LOCKS_NOW=str(NOW))
    env.pop("GIT_LOCKS_HOME", None)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX", "GIT_OBJECT_DIRECTORY", "GIT_NAMESPACE"):
        env.pop(key, None)
    Path(env["HOME"]).mkdir()
    rng = random.Random(seed)
    suffix = str(rng.randrange(10000))
    parent, child, contender = "p" + suffix, "c" + suffix, "z" + suffix
    directory = "d" + suffix + "/"

    def locks(*args):
        result = execute([binary, *args], case, env)
        if result.returncode:
            raise RuntimeError((args, result.stdout, result.stderr))
        return result

    if domain == "family":
        locks("claim", "--job", parent, "--holder", "alice", "parent.md")
        before = read_state(store)
        locks("claim", "--job", child, "--holder", "alice", "--parent", parent, "child.md")
        action = ["release", "--job", parent]
    elif domain == "semaphore":
        locks("sem", "create", "gpu", "--capacity", "1")
        before = read_state(store)
        locks("sem", "acquire", "gpu", "--job", child, "--holder", "alice")
        action = ["sem", "acquire", "gpu", "--job", contender, "--holder", "bob"]
    else:
        locks("claim", "--job", "unrelated", "--holder", "alice", "outside.md")
        before = read_state(store)
        locks("claim", "--job", child, "--holder", "alice", directory + "child.md")
        action = ["claim", "--job", contender, "--holder", "bob", directory]
    after = read_state(store)
    if violations(before) or violations(after):
        raise RuntimeError("unhealthy setup")
    return store, env, before, after, action


def run_case(case, domain, seed, mask, binary, shim, inject_read=None):
    store, env, before, after, action = scenario(case, domain, seed, binary)
    changed = sorted(ref for ref in before["refs"].keys() | after["refs"].keys() if before["refs"].get(ref) != after["refs"].get(ref))
    expected_count = {"family": 4, "semaphore": 2, "prefix": 3}[domain]
    if len(changed) != expected_count:
        raise RuntimeError(("fixture transition shape changed", domain, changed))
    observed = dict(before["refs"])
    selection = {}
    for index, ref in enumerate(changed):
        source = after if mask & (1 << index) else before
        selection[ref] = "after" if source is after else "before"
        if ref in source["refs"]:
            observed[ref] = source["refs"][ref]
        else:
            observed.pop(ref, None)
    write_refs(case / "observed.refs", observed)
    write_json(case / "before.json", before)
    write_json(case / "committed-after.json", after)
    env.update(PATH=str(shim) + os.pathsep + env["PATH"], OBS_CASE=str(case), OBS_REAL_GIT=GIT, OBS_INJECT_READ=str(inject_read or (1 if domain == "prefix" else 2)))
    result = execute([binary, *action], case, env)
    (case / "stdout.txt").write_text(result.stdout)
    (case / "stderr.txt").write_text(result.stderr)
    if result.returncode not in (0, 1):
        raise RuntimeError(("unexpected command failure", action, result.returncode, result.stderr))
    if not (case / "injected").exists():
        raise RuntimeError(("planner injection did not run", domain, action))
    final = read_state(store)
    bad = violations(final)
    write_json(case / "final.json", final)
    record = {"domain": domain, "seed": seed, "mask": mask, "changed": selection, "observation": "synthetic-per-ref-before-after", "command": action, "exit": result.returncode, "violations": bad, "reads": (case / "reads.log").read_text().splitlines(), "injected_read": inject_read or (1 if domain == "prefix" else 2), "transactions": int((case / "transaction-count").read_text()) if (case / "transaction-count").exists() else 0}
    write_json(case / "result.json", record)
    return record


def calibrate(output, binary, shim):
    evidence = []
    for domain in ("family", "semaphore", "prefix"):
        case = output / ("calibration-" + domain)
        _, _, _, healthy, _ = scenario(case, domain, 38, binary)
        bad = copy.deepcopy(healthy)
        if domain == "family":
            del bad["refs"]["refs/locks/jobs/p6899"]
            expected = "family-parent"
        elif domain == "semaphore":
            slot = "refs/locks/sem/gpu/slots/c6899"
            bad["refs"]["refs/locks/sem/gpu/slots/second"] = bad["refs"][slot]
            expected = "semaphore-capacity"
        else:
            child_ref = "refs/locks/jobs/c6899"
            body = bad["objects"][bad["refs"][child_ref]]
            body = body.replace("job: c6899\n", "job: covering\n").replace("d6899/child.md\n", "d6899/\n")
            bad["objects"]["calibration-object"] = body
            bad["refs"]["refs/locks/jobs/covering"] = "calibration-object"
            expected = "prefix-exclusivity"
        if violations(healthy) or [v["invariant"] for v in violations(bad)] != [expected]:
            raise RuntimeError(("oracle calibration failed", domain, violations(healthy), violations(bad)))
        write_json(case / "healthy.json", healthy)
        write_json(case / "deliberately-bad.json", bad)
        evidence.append({"domain": domain, "healthy_violations": [], "deliberately_bad_violations": violations(bad), "kind": "hand-constructed-oracle-input"})
    # release/sem discard the dispatcher's initial snapshot before planning.
    # Injecting there is a negative instrumentation control, not a safe planner.
    for domain, mask in (("family", 14), ("semaphore", 1)):
        result = run_case(output / ("discarded-bootstrap-" + domain), domain, 38, mask, binary, shim, inject_read=1)
        if result["violations"] or result["reads"][:2] != ["injected", "real"]:
            raise RuntimeError(("discarded-read control failed", result))
        evidence.append(result)
    write_json(output / "calibration.json", evidence)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--binary", default=str(ROOT / "bin/git-locks"))
    parser.add_argument("--seeds", nargs="+", type=int, default=[38, 1701, 20260922])
    parser.add_argument("--domains", nargs="+", choices=["family", "semaphore", "prefix"], default=["family", "semaphore", "prefix"])
    parser.add_argument("--calibrate-only", action="store_true", help="check the oracle and discarded-read controls, not production safety")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    shim = output / "shim"
    shim.mkdir()
    shutil.copy(ROOT / "test/observation/git-shim.sh", shim / "git")
    (shim / "git").chmod(0o755)
    calibration = calibrate(output, str(Path(args.binary).resolve()), shim)
    if args.calibrate_only:
        print(json.dumps({"calibration": "PASS", "oracle_cases": 6, "discarded_read_controls": 2, "production_safety": "NOT_EVALUATED"}))
        return 0
    provenance = {
        "binary_sha256": hashlib.sha256(Path(args.binary).read_bytes()).hexdigest(),
        "fixture_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "shim_sha256": hashlib.sha256((ROOT / "test/observation/git-shim.sh").read_bytes()).hexdigest(),
        "git": execute([GIT, "--version"], ROOT).stdout.strip(),
        "bash": execute(["bash", "--version"], ROOT).stdout.splitlines()[0],
        "python": sys.version.splitlines()[0],
    }
    write_json(output / "provenance.json", provenance)
    results = []
    for seed in args.seeds:
        for domain in args.domains:
            size = {"family": 16, "semaphore": 4, "prefix": 8}[domain]
            for mask in range(size):
                result = run_case(output / f"{domain}-{seed}-{mask:02d}", domain, seed, mask, str(Path(args.binary).resolve()), shim)
                results.append(result)
                print(json.dumps(result), flush=True)
    report = {"observation": "synthetic-per-ref-before-after", "live_git_race_reproduced": False, "cases": len(results), "violating_cases": sum(bool(r["violations"]) for r in results), "results": results, "calibration": calibration}
    report["production_safety"] = "FAIL" if report["violating_cases"] else "PASS_WITHIN_TESTED_SYNTHETIC_CASES"
    write_json(output / "report.json", report)
    print(json.dumps({key: value for key, value in report.items() if key not in ("results", "calibration")}), flush=True)
    return 1 if report["violating_cases"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, RuntimeError, subprocess.TimeoutExpired, OSError, ValueError, KeyError) as exc:
        print(f"STUDY ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
