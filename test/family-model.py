"""Seeded CLI histories with an independent public-state oracle.

The model stores only holder, parent and acquisition identity. Ref bytes must
remain identical after refusal; successful commands must match the model's
whole job set. Removing replacement/cycle checks breaks the fixed seeds.
"""

import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile


binary = str(Path(sys.argv[1]).resolve())
for seed in (34, 1701, 20260922):
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory(prefix="git-locks-family-model-") as tmp:
        env = dict(os.environ, GIT_LOCKS_STORE=f"{tmp}/store.git", GIT_LOCKS_NOW="1000000")
        jobs = {}
        acquisitions = {}

        def call(*args):
            return subprocess.run([binary, *args], cwd=tmp, env=env, text=True, capture_output=True, timeout=15)

        def refs():
            store = Path(tmp, "store.git")
            if not store.exists():
                return ""
            return subprocess.check_output(
                ["git", f"--git-dir={store}", "for-each-ref", "--format=%(refname) %(objectname)"], text=True
            )

        for step in range(64):
            job = f"j{rng.randrange(6)}"
            holder = rng.choice(("alice", "bob"))
            parent = rng.choice(("", "j0", "j1", "j2", "j3", "j4", "j5"))
            op = rng.randrange(8)
            before = refs()
            if op < 6:
                # A child is never transferable to a replacement acquisition.
                allowed = not any(p == job for _, p in jobs.values())
                if parent:
                    allowed &= parent in jobs and jobs.get(parent, (None,))[0] == holder
                ancestor, seen = parent, {job}
                while ancestor:
                    if ancestor in seen:
                        allowed = False
                        break
                    seen.add(ancestor)
                    ancestor = jobs.get(ancestor, ("", ""))[1]
                args = ["claim", "--job", job, "--holder", holder]
                if parent:
                    args += ["--parent", parent]
                result = call(*args, f"{job}.md")
                expected = 0 if allowed else 1
                if allowed:
                    jobs[job] = (holder, parent)
                    claimed = json.loads(result.stdout)
                    assert claimed["acquisition"] != acquisitions.get(job), (seed, step, "replacement identity")
                    acquisitions[job] = claimed["acquisition"]
            elif op == 6:
                result = call("extend", "--job", job, "--ttl", "16000")
                expected = 0 if job in jobs else 1
            else:
                result = call("release", "--job", job)
                expected = 0
                removed = {job}
                while True:
                    expanded = removed | {j for j, (_, p) in jobs.items() if p in removed}
                    if expanded == removed:
                        break
                    removed = expanded
                jobs = {j: state for j, state in jobs.items() if j not in removed}
                acquisitions = {j: acq for j, acq in acquisitions.items() if j not in removed}
            assert result.returncode == expected, (seed, step, job, parent, holder, expected, result.returncode, result.stdout, result.stderr)
            if expected == 1:
                assert refs() == before, (seed, step, "refused plan changed refs")
            listing = call("list")
            assert listing.returncode == 0, (seed, step, listing.stderr)
            records = [json.loads(line) for line in listing.stdout.splitlines()]
            actual = {r["job"]: (r["holder"], r.get("parent", "")) for r in records}
            assert actual == jobs, (seed, step, "family differs from model", actual, jobs)
            assert {r["job"]: r["acquisition"] for r in records} == acquisitions, (seed, step, "acquisition changed")
            assert all(r["state"] == "live" and r["paths"] == [f'{r["job"]}.md'] for r in records), (seed, step, "path or liveness")
    print(f"seed {seed}: 64 operations matched public state, acquisition identity and refusal ref immutability")
