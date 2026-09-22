#!/usr/bin/env python3
"""Verify the committed receipt manifest, without trusting untracked files."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
prefix = "docs/studies/membership-observation/evidence/"


def git(*args):
    return subprocess.check_output(["git", *args], cwd=root)


manifest = json.loads(git("show", "HEAD:" + prefix + "sha256.json"))
tracked = set(git("ls-files", "-z", "--", prefix).decode().split("\0"))
failures = []
for name, expected in manifest.items():
    path = prefix + name
    if path not in tracked:
        failures.append(f"not tracked: {path}")
        continue
    actual = hashlib.sha256(git("show", "HEAD:" + path)).hexdigest()
    if actual != expected:
        failures.append(f"committed checksum differs: {path}")
if failures:
    print("\n".join(failures), file=sys.stderr)
    sys.exit(1)
print(f"Verified {len(manifest)} committed receipt paths and SHA-256 hashes at " + git("rev-parse", "HEAD").decode().strip())
