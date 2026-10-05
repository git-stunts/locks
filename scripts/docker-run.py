#!/usr/bin/env python3
"""Copy inputs into one bounded, offline Docker worker; never mount the checkout."""

import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import select
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "git-locks-tests:local"
WORKER = "git-locks-tests"
OWNER = "git-stunts.locks.tests"
PROFILE = "5"
SOURCE_LIMIT = 64 * 1024 * 1024
ARTIFACT_LIMIT = 80 * 1024 * 1024
EXPORT_TIMEOUT = 30


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
    command = ["docker", "exec", WORKER, "tar", "cf", "-", "-C", "/evidence", "artifacts"]
    deadline = time.monotonic() + EXPORT_TIMEOUT
    process = subprocess.Popen(command, stdout=subprocess.PIPE, bufsize=0, start_new_session=True)

    def remaining():
        seconds = deadline - time.monotonic()
        if seconds <= 0:
            raise subprocess.TimeoutExpired(command, EXPORT_TIMEOUT)
        if shutil.disk_usage(receipts).free < 50 * 1024**3:
            raise RuntimeError("host backing free space below 50 GiB during artifact export")
        return seconds

    class Stream:
        def read(self, size):
            while True:
                ready, _, _ = select.select([process.stdout], [], [], min(.25, remaining()))
                if ready:
                    return os.read(process.stdout.fileno(), min(size, 65536))

    try:
        with tarfile.open(fileobj=Stream(), mode="r|") as tar:
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
        while True:
            try:
                status = process.wait(timeout=min(.25, remaining()))
                break
            except subprocess.TimeoutExpired:
                remaining()
        if status:
            raise RuntimeError("could not export container evidence")
    finally:
        # Kill only this export client's group, including children that retain
        # its pipe. main() separately stops remote processes via container stop.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)
            process.stdout.close()


def load_bootstrap():
    spec = importlib.util.spec_from_file_location('git_locks_bootstrap', ROOT / 'scripts/docker-ci.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BootstrapBoundary:
    """A small filesystem is admitted only with live host-side kernel proof."""
    def __init__(self, info, worker_pid):
        self.provider = load_bootstrap()
        self.info, self.worker_pid = info, worker_pid
        self.initial = self.snapshot()

    def snapshot(self):
        try:
            return self.provider.quota_admission(self.info, self.worker_pid)
        except Exception as error:
            raise RuntimeError('bootstrap quota admission failed: ' + str(error)) from None

    def check(self):
        current = self.snapshot()
        # Free bytes can change. Quota and process identities must not.
        for key, value in self.initial.items():
            if key != 'backing_free_bytes' and current.get(key) != value:
                raise RuntimeError('bootstrap quota or process identity changed: ' + key)
        return current


def publish_admission(boundary, run_id, program):
    boundary.check()
    # Execute the supervisor's trusted copy, never a worker-writable script or
    # module. Isolated Python ignores the worker's cwd and PYTHONPATH.
    run('docker', 'exec', '--user', '0:0', WORKER, '/usr/bin/python3', '-I', '-c',
        program, 'publish', run_id, str(boundary.initial['capacity_bytes']), timeout=5)


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
            raise RuntimeError("toolchain image is missing or stale; refusing unguarded Docker bootstrap. "
                               "Provision a matching image with resource-enforced setup before retrying")
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
            run("docker", "create", "--pull", "never", "--name", WORKER, "--label", f"{OWNER}=1", "--label", f"{OWNER}.profile={PROFILE}",
                "--init", "--network", "none", "--read-only", "--ipc", "private", "--shm-size", "16m", "--cpus", "2", "--memory", "2g",
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
                "--env", "GIT_LOCKS_TEST_REQUIRE_UTF8=1", image["Id"], stdout=subprocess.DEVNULL)
        worker = inspect("container", WORKER)
        config = worker["HostConfig"]
        if (worker["Mounts"] or config["Binds"] or config["NetworkMode"] != "none"
                or not config["ReadonlyRootfs"] or config["Privileged"] or not config["Init"]
                or config["Memory"] != 2 * 1024**3 or config["NanoCpus"] != 2 * 10**9
                or config["PidsLimit"] != 256 or config["ShmSize"] != 16 * 1024**2
                or config["IpcMode"] != "private" or config["PidMode"]
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
        worker_stopped = False
        try:
            vm_df = subprocess.check_output(["docker", "exec", WORKER, "df", "-Pk", "/"], text=True)
            vm_free = int(vm_df.splitlines()[-1].split()[3]) * 1024
            boundary = None
            inner_options = []
            run_id = None
            admission_program = None
            if vm_free < 50 * 1024**3:
                info = json.loads(subprocess.check_output(
                    ["docker", "info", "--format", "{{json .}}"], text=True, timeout=5))
                running = inspect("container", WORKER)
                boundary = BootstrapBoundary(info, running["State"]["Pid"])
                run_id = uuid.uuid4().hex
                admission_program = Path(__file__).with_name("docker-admission.py").read_text()
                inner_options = ["--verified-bootstrap-quota", str(boundary.initial["capacity_bytes"]), run_id, "--"]
                (receipts / "quota-admission.json").write_text(json.dumps(boundary.initial, indent=2) + "\n")
            run("docker", "exec", "-i", WORKER, "tar", "xf", "-", "-C", "/work", input=payload)
            run("docker", "exec", "-w", "/work/source", WORKER,
                "bash", "scripts/docker-entry.sh")
            run("docker", "exec", WORKER, "mkdir", "/evidence/artifacts")
            run("docker", "exec", WORKER, "ln", "-s", "/evidence/artifacts", "/work/artifacts")
            if boundary is not None:
                try:
                    publish_admission(boundary, run_id, admission_program)
                except Exception as error:
                    (receipts / "result.json").write_text(json.dumps({
                        "exit_code": 2, "host_guard": True, "host_guard_detail": str(error),
                        "state": "admission-publication-failed"}) + "\n")
                    return 2
            command = sys.argv[1:] or ["make", "test-container"]
            # The inner runner monitors the VM and quota filesystems. The host
            # separately checks its own filesystem; no host path is mounted.
            process = subprocess.Popen(["docker", "exec", "-e", f"TEST_LOG_BUDGET_BYTES={128 * 1024**2 - retained - 18 * 1024**2}", "-w", "/work/source", WORKER,
                                        "python3", "scripts/docker-exec.py", *inner_options, *command])
            host_guard = False
            host_guard_detail = None
            while process.poll() is None:
                try:
                    if shutil.disk_usage(ROOT).free < 50 * 1024**3:
                        raise RuntimeError("host free space below 50 GiB")
                    if boundary is not None:
                        publish_admission(boundary, run_id, admission_program)
                except Exception as error:
                    host_guard = True
                    host_guard_detail = str(error)
                    try:
                        pid = subprocess.check_output(["docker", "exec", WORKER, "cat", "/evidence/runner.pid"],
                                                      text=True, timeout=5).strip()
                        if not pid.isdecimal() or int(pid) < 2:
                            raise RuntimeError("invalid owned workload PID")
                        run("docker", "exec", WORKER, "kill", "-TERM", pid, timeout=5)
                        process.wait(timeout=20)
                    except Exception as cancellation_error:
                        # Killing the local Docker client does not stop its remote
                        # workload. Stop the owned container before reaping it.
                        failure = {"exit_code": 2, "host_guard": True,
                                   "host_guard_detail": host_guard_detail,
                                   "cancellation_error": str(cancellation_error),
                                   "worker_stop": "requested",
                                   "evidence_unavailable": "Emergency worker stop discards tmpfs evidence before export"}
                        result_path = receipts / "result.json"
                        result_path.write_text(json.dumps(failure) + "\n")
                        try:
                            run("docker", "stop", "--time", "5", WORKER,
                                stdout=subprocess.DEVNULL, timeout=15)
                        except Exception as stop_error:
                            failure.update(worker_stop="failed", stop_error=str(stop_error))
                            result_path.write_text(json.dumps(failure) + "\n")
                            raise RuntimeError("emergency worker stop failed: " + str(stop_error)) from None
                        worker_stopped = True
                        failure["worker_stop"] = "confirmed"
                        result_path.write_text(json.dumps(failure) + "\n")
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                        return 2
                    break
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            if boundary is not None and not host_guard:
                try:
                    boundary.check()
                except Exception as error:
                    host_guard = True
                    host_guard_detail = str(error)
            result_code = 2 if host_guard else process.returncode
            result = {"exit_code": None, "pending_exit_code": result_code, "worker_stop": "pending",
                      "workload_exit_code": process.returncode,
                      "host_guard": host_guard, "host_guard_detail": host_guard_detail,
                      "evidence_errors": {}}
            result_path = receipts / "result.json"
            result_path.write_text(json.dumps(result) + "\n")
            for local, remote in (("latest.log", "test.log"), ("resources.json", "resources.json")):
                target = receipts / local
                try:
                    with target.open("wb") as output:
                        run("docker", "exec", WORKER, "cat", "/evidence/" + remote,
                            stdout=output, timeout=15)
                except Exception as error:
                    result["evidence_errors"][local] = str(error)
                    # A failed transfer must not leave an apparently complete
                    # receipt or reuse a previous run's evidence.
                    try:
                        target.unlink(missing_ok=True)
                    except OSError as cleanup_error:
                        result["evidence_errors"][local] += "; partial file removal failed: " + str(cleanup_error)
            try:
                export_artifacts(receipts)
            except Exception as error:
                result["evidence_errors"]["artifacts"] = str(error)
            if result["evidence_errors"]:
                result["pending_exit_code"] = 2
            result_path.write_text(json.dumps(result) + "\n")
            return result["pending_exit_code"]
        finally:
            if not worker_stopped:
                result_path = receipts / "result.json"
                receipt_error = None
                try:
                    final_result = json.loads(result_path.read_text())
                    if not isinstance(final_result, dict):
                        raise ValueError("runner result is not an object")
                except (OSError, ValueError) as error:
                    receipt_error = str(error)
                    final_result = {"exit_code": 2, "result_error": receipt_error}
                planned_exit = final_result.pop("pending_exit_code", final_result.get("exit_code"))
                try:
                    run("docker", "stop", "--time", "5", WORKER, stdout=subprocess.DEVNULL, timeout=15)
                except Exception as error:
                    final_result.update(exit_code=2, worker_stop="failed", stop_error=str(error))
                    raise
                else:
                    final_result.update(exit_code=planned_exit, worker_stop="confirmed")
                finally:
                    result_path.write_text(json.dumps(final_result) + "\n")
                if receipt_error is not None:
                    raise RuntimeError("could not read runner result before container stop: " + receipt_error)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, subprocess.SubprocessError) as error:
        print(f"Docker test runner: {error}", file=sys.stderr)
        sys.exit(2)
