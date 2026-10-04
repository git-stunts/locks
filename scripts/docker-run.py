#!/usr/bin/env python3
"""Copy inputs into one bounded, offline Docker worker; never mount the checkout."""

import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "git-locks-tests:local"
WORKER = "git-locks-tests"
OWNER = "git-stunts.locks.tests"
PROFILE = "4"
SOURCE_LIMIT = 64 * 1024 * 1024
ARTIFACT_LIMIT = 80 * 1024 * 1024


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def inspect(kind, name):
    result = subprocess.run(["docker", kind, "inspect", name], capture_output=True, text=True)
    if result.returncode:
        return None
    return json.loads(result.stdout)[0]


def source_archive():
    # Current tracked and nonignored new files, including uncommitted edits.
    # Never copy .git, symlinks, caches, special files, or host configuration.
    git_env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    git_env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT, env=git_env
    ).decode().split("\0")
    archive = io.BytesIO()
    total = 0
    with tarfile.open(fileobj=archive, mode="w") as tar:
        for name in sorted(set(names) - {""}):
            relative = Path(name)
            if relative.is_absolute() or any(part in {"..", ".git", "node_modules", "__pycache__", ".test-results"} for part in relative.parts):
                raise RuntimeError(f"unsafe source entry: {name}")
            source = ROOT / relative
            if source.is_symlink() or any(parent.is_symlink() for parent in source.parents if parent != ROOT):
                raise RuntimeError(f"source symlinks are not allowed: {name}")
            if not source.exists():
                continue  # tracked deletion in the candidate
            if not source.is_file():
                raise RuntimeError(f"source entry is not a regular file: {name}")
            total += source.stat().st_size
            if total > SOURCE_LIMIT:
                raise RuntimeError("source snapshot exceeds 64 MiB")
            info = tar.gettarinfo(str(source), arcname="source/" + name)
            info.uid = info.gid = 1000
            info.uname = info.gname = "node"
            with source.open("rb") as stream:
                tar.addfile(info, stream)
    return archive.getvalue()


def retained_usage(receipts):
    target = receipts / "artifacts"
    return sum(max(p.stat().st_size, p.stat().st_blocks * 512) for p in target.rglob('*')) if target.exists() else 0


def export_artifacts(receipts):
    """Retain explicitly named evidence, never overwrite an earlier receipt."""
    used = retained_usage(receipts)
    process = subprocess.Popen(["docker", "exec", WORKER, "tar", "cf", "-", "-C", "/evidence", "artifacts"], stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as tar:
            for member in tar:
                relative = Path(member.name)
                if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != 'artifacts':
                    raise RuntimeError("unsafe evidence archive path")
                destination = receipts / relative
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    used += 4096
                    if used > ARTIFACT_LIMIT:
                        raise RuntimeError("retained evidence exceeds the 80 MiB project limit")
                    continue
                if not member.isfile() or destination.exists():
                    raise RuntimeError(f"evidence is not new regular data: {relative}")
                used += max(4096, (member.size + 4095) // 4096 * 4096)
                if used > ARTIFACT_LIMIT:
                    raise RuntimeError("retained evidence exceeds the 80 MiB project limit")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open('xb') as output:
                    shutil.copyfileobj(tar.extractfile(member), output)
        if process.wait():
            raise RuntimeError("could not export container evidence")
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait()


def main():
    if shutil.disk_usage(ROOT).free < 50 * 1024**3:
        raise RuntimeError("less than 50 GiB host free space; refusing new test work")
    # flock serializes all checkouts using this one project worker. It is held
    # through setup, execution, receipt export, and teardown.
    lock_path = Path(tempfile.gettempdir()) / "git-locks-docker-tests.lock"
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("git-locks Docker worker is busy; wait for its current run") from exc
        receipts = ROOT / ".test-results"
        receipts.mkdir(exist_ok=True)
        retained = retained_usage(receipts)
        if retained > ARTIFACT_LIMIT - 16 * 1024**2:
            raise RuntimeError("retained evidence leaves less than 16 MiB export reserve; archive owned evidence before running")
        (receipts / "result.json").write_text(json.dumps({"exit_code": None, "state": "preparing"}) + "\n")
        payload = source_archive()
        recipe = ROOT / "scripts/docker/Dockerfile"
        fingerprint = hashlib.sha256(recipe.read_bytes()).hexdigest()
        image = inspect("image", IMAGE)
        if not image or (image["Config"].get("Labels") or {}).get(OWNER) != fingerprint:
            run("docker", "build", "--label", f"{OWNER}={fingerprint}", "--tag", IMAGE, str(recipe.parent))
            image = inspect("image", IMAGE)
        worker = inspect("container", WORKER)
        if worker:
            if (worker["Config"].get("Labels") or {}).get(OWNER) != "1":
                raise RuntimeError(f"refusing to replace unowned container {WORKER}")
            if worker["State"]["Running"]:
                raise RuntimeError(f"{WORKER} is already running; inspect it before restarting")
            if worker["Image"] != image["Id"] or worker["Config"]["Labels"].get(OWNER + ".profile") != PROFILE:
                run("docker", "rm", WORKER)
                worker = None
        if worker is None:
            run("docker", "create", "--name", WORKER, "--label", f"{OWNER}=1", "--label", f"{OWNER}.profile={PROFILE}",
                "--init", "--network", "none", "--read-only", "--cpus", "2", "--memory", "2g",
                "--memory-swap", "2g", "--pids-limit", "256", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--user", "1000:1000",
                "--tmpfs", "/work:rw,exec,nosuid,nodev,size=512m,uid=1000,gid=1000",
                "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=512m,uid=1000,gid=1000",
                "--tmpfs", "/home/node:rw,nosuid,nodev,size=32m,uid=1000,gid=1000",
                "--tmpfs", "/evidence:rw,nosuid,nodev,size=16m,uid=1000,gid=1000",
                "--env", "TMPDIR=/tmp",
                "--log-opt", "max-size=1m", "--log-opt", "max-file=1",
                "--env", "GIT_AUTHOR_NAME=git-locks tests", "--env", "GIT_AUTHOR_EMAIL=tests@example.invalid",
                "--env", "GIT_COMMITTER_NAME=git-locks tests", "--env", "GIT_COMMITTER_EMAIL=tests@example.invalid",
                "--env", "GIT_LOCKS_TEST_REQUIRE_UTF8=1", IMAGE, stdout=subprocess.DEVNULL)
        worker = inspect("container", WORKER)
        config = worker["HostConfig"]
        if (worker["Mounts"] or config["Binds"] or config["NetworkMode"] != "none"
                or not config["ReadonlyRootfs"] or config["Privileged"] or not config["Init"]
                or config["Memory"] != 2 * 1024**3 or config["NanoCpus"] != 2 * 10**9
                or config["PidsLimit"] != 256
                or set(config["Tmpfs"]) != {"/work", "/tmp", "/home/node", "/evidence"}):
            raise RuntimeError("worker isolation or resource configuration differs from the required boundary")
        receipts = ROOT / ".test-results"
        receipts.mkdir(exist_ok=True)
        (receipts / "isolation.json").write_text(json.dumps({
            "image": image["Id"], "source_archive_sha256": hashlib.sha256(payload).hexdigest(),
            "source_archive_bytes": len(payload), "host_config": config,
            "mounts": worker["Mounts"], "command": sys.argv[1:] or ["make", "test-container"],
        }, indent=2) + "\n")
        run("docker", "start", WORKER, stdout=subprocess.DEVNULL)
        try:
            vm_df = subprocess.check_output(["docker", "exec", WORKER, "df", "-Pk", "/"], text=True)
            vm_free = int(vm_df.splitlines()[-1].split()[3]) * 1024
            if vm_free < 50 * 1024**3:
                raise RuntimeError("less than 50 GiB Docker VM free space; refusing test work")
            run("docker", "exec", "-i", WORKER, "tar", "xf", "-", "-C", "/work", input=payload)
            run("docker", "exec", "-w", "/work/source", WORKER,
                "bash", "scripts/docker-entry.sh")
            run("docker", "exec", WORKER, "mkdir", "/evidence/artifacts")
            run("docker", "exec", WORKER, "ln", "-s", "/evidence/artifacts", "/work/artifacts")
            command = sys.argv[1:] or ["make", "test-container"]
            # The inner runner monitors the VM and quota filesystems. The host
            # separately checks its own filesystem; no host path is mounted.
            process = subprocess.Popen(["docker", "exec", "-e", f"TEST_LOG_BUDGET_BYTES={128 * 1024**2 - retained - 17 * 1024**2}", "-w", "/work/source", WORKER,
                                        "python3", "scripts/docker-exec.py", *command])
            host_guard = False
            while process.poll() is None:
                if shutil.disk_usage(ROOT).free < 50 * 1024**3:
                    host_guard = True
                    pid = subprocess.check_output(["docker", "exec", WORKER, "cat", "/evidence/runner.pid"], text=True).strip()
                    if not pid.isdecimal() or int(pid) < 2:
                        raise RuntimeError("invalid owned workload PID")
                    run("docker", "exec", WORKER, "kill", "-TERM", pid)
                    process.wait(timeout=20)
                    break
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            result_code = 2 if host_guard else process.returncode
            with (receipts / "latest.log").open("wb") as log:
                run("docker", "exec", WORKER, "cat", "/evidence/test.log", stdout=log)
            (receipts / "result.json").write_text(json.dumps({"exit_code": result_code, "host_guard": host_guard}) + "\n")
            with (receipts / "resources.json").open("wb") as receipt:
                run("docker", "exec", WORKER, "cat", "/evidence/resources.json", stdout=receipt)
            export_artifacts(receipts)
            return result_code
        finally:
            run("docker", "stop", "--time", "5", WORKER, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Docker test runner: {error}", file=sys.stderr)
        sys.exit(2)
