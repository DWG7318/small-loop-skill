"""Reload one exact local Temporal worker without starting or terminating workflows."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .process import windows_no_window_kwargs
from .worker_completion import _write_or_reuse_stable_request


FIELDS = {"schema_version", "run_id", "address", "task_queue", "python_executable",
          "worker_command", "inspection_command", "pythonpath", "adapter_source", "workflow_source",
          "old_processes", "workflow_identity", "evidence_root", "result_path"}
PROCESS_FIELDS = {"pid", "parent_pid", "creation_time", "command_sha256"}
IDENTITY_FIELDS = {"schema_version", "run_id", "address", "task_queue", "start_workflow_id",
                   "start_run_id", "run_workflow_id", "run_run_id", "startup_fingerprint"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _proof(value: Any, label: str) -> tuple[Path, dict[str, Any]]:
    if not isinstance(value, Mapping) or set(value) != {"path", "sha256"}:
        raise ValueError(f"{label} proof is not closed")
    path = Path(value["path"])
    if not path.is_absolute() or not path.is_file() or _sha256(path) != value["sha256"]:
        raise ValueError(f"{label} proof changed")
    return path, _object(path, label)


def _file_proof(value: Any, label: str) -> Path:
    if not isinstance(value, Mapping) or set(value) != {"path", "sha256"}:
        raise ValueError(f"{label} proof is not closed")
    path = Path(value["path"])
    if not path.is_absolute() or not path.is_file() or _sha256(path) != value["sha256"]:
        raise ValueError(f"{label} proof changed")
    return path


def _powershell_json(script: str) -> Any:
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", check=False,
        **windows_no_window_kwargs(),
    )
    if completed.returncode == 3:
        raise ProcessLookupError("Windows process no longer exists")
    if completed.returncode != 0 or not completed.stdout.strip():
        raise ValueError("Windows process identity is unavailable")
    return json.loads(completed.stdout)


def _process_snapshot(pid: int) -> dict[str, Any]:
    if os.name != "nt" or isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
        raise ValueError("Temporal worker process identity is invalid")
    row = _powershell_json(
        f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\"; "
        "if($null -eq $p){exit 3}; $p | Select-Object ProcessId,ParentProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress"
    )
    command = row.get("CommandLine")
    created = row.get("CreationDate")
    if not isinstance(command, str) or not command or not isinstance(created, str) or not created:
        raise ValueError("Temporal worker process metadata is incomplete")
    return {"pid": int(row["ProcessId"]), "parent_pid": int(row["ParentProcessId"]),
            "creation_time": created, "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest()}


def _child_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_pid = {row["pid"]: row for row in rows}
    roots = [row for row in rows if row["parent_pid"] not in by_pid]
    if len(roots) != 1:
        raise ValueError("old Temporal worker processes must form one exact chain")
    depth: dict[int, int] = {}
    for row in rows:
        seen: set[int] = set()
        current, distance = row, 0
        while current["parent_pid"] in by_pid:
            if current["pid"] in seen:
                raise ValueError("old Temporal worker process chain contains a cycle")
            seen.add(current["pid"])
            current = by_pid[current["parent_pid"]]
            distance += 1
        if current["pid"] != roots[0]["pid"]:
            raise ValueError("old Temporal worker process chain is disconnected")
        depth[row["pid"]] = distance
    return sorted(rows, key=lambda item: depth[item["pid"]], reverse=True)


def _stop_exact_processes(rows: list[dict[str, Any]]) -> None:
    for row in _child_first(rows):
        pid = row["pid"]
        if pid == os.getpid():
            raise ValueError("reload cannot stop its own process")
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             f"Stop-Process -Id {pid} -Force -ErrorAction Stop"],
            stdin=subprocess.DEVNULL, capture_output=True, check=False, **windows_no_window_kwargs(),
        )
        if completed.returncode != 0:
            try:
                current = _process_snapshot(pid)
            except ProcessLookupError:
                continue
            if current != row:
                raise ValueError(f"exact Temporal worker process {pid} identity changed")
            raise ValueError(f"exact Temporal worker process {pid} did not stop")


def _spawn_worker(request: Mapping[str, Any], environment: dict[str, str], root: Path) -> int:
    root.mkdir(parents=True, exist_ok=True)
    stdout = (root / "worker.stdout.log").open("ab")
    stderr = (root / "worker.stderr.log").open("ab")
    try:
        process = subprocess.Popen(
            list(request["worker_command"]), stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            close_fds=True, env=environment, **windows_no_window_kwargs(detached=True),
        )
    finally:
        stdout.close()
        stderr.close()
    return process.pid


def _inspect_workflows(request: Mapping[str, Any], environment: dict[str, str]) -> dict[str, Any]:
    identity = _object(Path(request["workflow_identity"]["path"]), "workflow identity")
    arguments = ["--address", request["address"], "--run-id", request["run_id"],
        "--task-queue", request["task_queue"], "--start-workflow-id", identity["start_workflow_id"],
        "--start-run-id", identity["start_run_id"], "--run-workflow-id", identity["run_workflow_id"],
        "--run-run-id", identity["run_run_id"], "--startup-fingerprint", identity["startup_fingerprint"]]
    completed = subprocess.run(list(request["inspection_command"]) + arguments, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", check=False, env=environment,
        **windows_no_window_kwargs())
    if completed.returncode != 0:
        raise ValueError("reloaded Temporal workflows are not queryable")
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("Temporal inspection result is not an object")
    return value


def reload_temporal_worker(request_path: Path | str, *, request_sha256: str) -> dict[str, Any]:
    request_path = Path(request_path).resolve()
    if _sha256(request_path) != request_sha256:
        raise ValueError("Temporal reload request hash changed")
    request = _object(request_path, "Temporal reload request")
    if set(request) != FIELDS or request.get("schema_version") != "slk.temporal-worker-reload/v1":
        raise ValueError("Temporal reload request is not closed")
    run_id, address, queue = request.get("run_id"), request.get("address"), request.get("task_queue")
    commands = (request.get("worker_command"), request.get("inspection_command"))
    python = Path(request.get("python_executable", ""))
    if (not all(isinstance(value, str) and value for value in (run_id, address, queue))
        or not python.is_absolute() or not python.is_file()
        or any(not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command)
               for command in commands)
        or Path(request["worker_command"][0]).resolve() != python.resolve()
        or request["worker_command"][1:3] != ["-m", "slk_temporal.worker"]
        or not isinstance(request.get("pythonpath"), list) or not request["pythonpath"]
        or not all(Path(path).is_absolute() and Path(path).exists() for path in request["pythonpath"])):
        raise ValueError("Temporal reload command or Python identity is invalid")
    for marker in (("--address", address), ("--task-queue", queue)):
        try:
            if request["worker_command"][request["worker_command"].index(marker[0]) + 1] != marker[1]:
                raise ValueError
        except (ValueError, IndexError) as exc:
            raise ValueError("Temporal worker command changed frozen routing") from exc
    for label in ("adapter_source", "workflow_source"):
        path = _file_proof(request[label], label)
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError(f"{label} exceeds the bounded source limit")
    _, identity = _proof(request["workflow_identity"], "workflow identity")
    if (set(identity) != IDENTITY_FIELDS or identity["schema_version"] != "slk.temporal-workflow-identity/v1"
        or identity["run_id"] != run_id or identity["address"] != address or identity["task_queue"] != queue
        or not isinstance(identity["startup_fingerprint"], str) or len(identity["startup_fingerprint"]) != 64):
        raise ValueError("frozen Temporal workflow identity is invalid")
    rows = request.get("old_processes")
    if not isinstance(rows, list) or not rows or any(not isinstance(row, Mapping) or set(row) != PROCESS_FIELDS for row in rows):
        raise ValueError("old Temporal worker process chain is invalid")
    pids = {row["pid"] for row in rows}
    if len(pids) != len(rows):
        raise ValueError("old Temporal worker processes must form one exact chain")
    _child_first([dict(row) for row in rows])
    result_path, evidence_root = Path(request["result_path"]), Path(request["evidence_root"])
    if not result_path.is_absolute() or not evidence_root.is_absolute():
        raise ValueError("Temporal reload output paths must be absolute")
    if result_path.exists():
        saved = _object(result_path, "Temporal reload result")
        if saved.get("request_sha256") != request_sha256:
            raise ValueError("Temporal reload result conflicts with this request")
        return saved
    for row in rows:
        if _process_snapshot(row["pid"]) != row:
            raise ValueError("old Temporal worker identity changed")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(request["pythonpath"])
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    if _inspect_workflows(request, environment) != identity:
        raise ValueError("live Temporal workflow identity differs from the frozen reload target")
    _stop_exact_processes([dict(row) for row in rows])
    new_pid = _spawn_worker(request, environment, evidence_root)
    deadline = time.monotonic() + 30
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            observed = _inspect_workflows(request, environment)
            if observed != identity:
                raise ValueError("Temporal workflow identity changed across worker reload")
            break
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.25)
    else:
        raise ValueError("reloaded worker did not recover the exact workflow pair") from last_error
    result = {"schema_version": "slk.temporal-worker-reload-result/v1",
        "status": "TEMPORAL_WORKER_RELOADED", "run_id": run_id, "task_queue": queue,
        "new_worker_pid": new_pid, "request_sha256": request_sha256,
        "adapter_source_sha256": request["adapter_source"]["sha256"],
        "workflow_source_sha256": request["workflow_source"]["sha256"],
        "workflow_identity": identity}
    result_path.parent.mkdir(parents=True, exist_ok=True)
    _write_or_reuse_stable_request(result_path, result)
    return result
