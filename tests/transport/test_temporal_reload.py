"""Controlled worker reload preserves one existing Temporal workflow pair."""

import hashlib
import json
from pathlib import Path

import pytest

from slk_transport import temporal_reload as reload


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def reload_request(tmp_path: Path) -> Path:
    adapter = tmp_path / "adapter.py"
    adapter.write_text("# adapter\n", encoding="utf-8")
    source = tmp_path / "workflows.py"
    source.write_text("# patched workflow\n", encoding="utf-8")
    identity = write_json(tmp_path / "workflow-identity.json", {
        "schema_version": "slk.temporal-workflow-identity/v1", "run_id": "RUN-A",
        "address": "127.0.0.1:7233", "task_queue": "slk-run-a",
        "start_workflow_id": "slk-start-RUN-A", "start_run_id": "native-start-a",
        "run_workflow_id": "slk-run-RUN-A", "run_run_id": "native-run-a",
        "startup_fingerprint": "a" * 64,
    })
    proof = lambda path: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return write_json(tmp_path / "reload.json", {
        "schema_version": "slk.temporal-worker-reload/v1", "run_id": "RUN-A",
        "address": "127.0.0.1:7233", "task_queue": "slk-run-a",
        "python_executable": str(Path(__import__("sys").executable).resolve()),
        "worker_command": [str(Path(__import__("sys").executable).resolve()), "-m", "slk_temporal.worker",
            "--address", "127.0.0.1:7233", "--task-queue", "slk-run-a", "--adapter-module", "adapter"],
        "inspection_command": [str(Path(__import__("sys").executable).resolve()), "-m", "slk_temporal.inspector"],
        "pythonpath": [str(tmp_path)], "adapter_source": proof(adapter), "workflow_source": proof(source),
        "old_processes": [{"pid": 101, "parent_pid": 100, "creation_time": "2026-10-05T00:00:00Z",
                            "command_sha256": "b" * 64}],
        "workflow_identity": proof(identity), "evidence_root": str(tmp_path / "evidence"),
        "result_path": str(tmp_path / "reload-result.json"),
    })


def test_reload_stops_only_exact_worker_and_preserves_workflow_identity(tmp_path, monkeypatch):
    request = reload_request(tmp_path)
    snapshots = {101: {"pid": 101, "parent_pid": 100, "creation_time": "2026-10-05T00:00:00Z",
                       "command_sha256": "b" * 64}}
    calls = []
    monkeypatch.setattr(reload, "_process_snapshot", lambda pid: snapshots[pid])
    monkeypatch.setattr(reload, "_stop_exact_processes", lambda rows: calls.append(("stop", rows)))
    monkeypatch.setattr(reload, "_spawn_worker", lambda request, env, root: calls.append(("spawn", request["worker_command"])) or 202)
    identity = json.loads(Path(json.loads(request.read_text())["workflow_identity"]["path"]).read_text())
    monkeypatch.setattr(reload, "_inspect_workflows", lambda request, env: identity)

    result = reload.reload_temporal_worker(request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())

    assert result["status"] == "TEMPORAL_WORKER_RELOADED"
    assert result["new_worker_pid"] == 202
    assert result["workflow_identity"] == identity
    assert [call[0] for call in calls] == ["stop", "spawn"]


def test_process_chain_is_stopped_child_first_not_by_pid_number():
    rows = [
        {"pid": 900, "parent_pid": 10, "creation_time": "root", "command_sha256": "a" * 64},
        {"pid": 20, "parent_pid": 900, "creation_time": "child", "command_sha256": "b" * 64},
        {"pid": 5, "parent_pid": 20, "creation_time": "grandchild", "command_sha256": "c" * 64},
    ]
    assert [row["pid"] for row in reload._child_first(rows)] == [5, 20, 900]


def test_exact_reload_result_is_idempotent_after_old_parent_exits(tmp_path, monkeypatch):
    request = reload_request(tmp_path)
    value = json.loads(request.read_text())
    identity = json.loads(Path(value["workflow_identity"]["path"]).read_text())
    result = {"schema_version": "slk.temporal-worker-reload-result/v1",
              "status": "TEMPORAL_WORKER_RELOADED", "run_id": "RUN-A", "task_queue": "slk-run-a",
              "new_worker_pid": 202, "request_sha256": hashlib.sha256(request.read_bytes()).hexdigest(),
              "adapter_source_sha256": value["adapter_source"]["sha256"],
              "workflow_source_sha256": value["workflow_source"]["sha256"],
              "workflow_identity": identity}
    Path(value["result_path"]).write_text(json.dumps(result), encoding="utf-8")
    monkeypatch.setattr(reload, "_process_snapshot", lambda pid: pytest.fail("completed retry must not inspect exited old parent"))

    assert reload.reload_temporal_worker(
        request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest()) == result


def test_post_identity_process_exit_is_idempotent_but_pid_reuse_is_rejected(monkeypatch):
    row = {"pid": 101, "parent_pid": 100, "creation_time": "original", "command_sha256": "b" * 64}
    completed = type("Completed", (), {"returncode": 1})()
    monkeypatch.setattr(reload.subprocess, "run", lambda *args, **kwargs: completed)
    monkeypatch.setattr(reload, "_process_snapshot", lambda pid: (_ for _ in ()).throw(ProcessLookupError(pid)))
    reload._stop_exact_processes([row])

    monkeypatch.setattr(reload, "_process_snapshot", lambda pid: {**row, "creation_time": "reused"})
    with pytest.raises(ValueError, match="identity changed"):
        reload._stop_exact_processes([row])


@pytest.mark.parametrize("damage", ["old-process", "workflow", "source"])
def test_reload_fails_closed_on_process_history_or_source_drift(tmp_path, monkeypatch, damage):
    request = reload_request(tmp_path)
    value = json.loads(request.read_text())
    identity = json.loads(Path(value["workflow_identity"]["path"]).read_text())
    snapshot = dict(value["old_processes"][0])
    if damage == "old-process": snapshot["creation_time"] = "different"
    if damage == "workflow": identity["run_run_id"] = "different-native-run"
    if damage == "source": Path(value["workflow_source"]["path"]).write_text("changed", encoding="utf-8")
    monkeypatch.setattr(reload, "_process_snapshot", lambda pid: snapshot)
    monkeypatch.setattr(reload, "_stop_exact_processes", lambda rows: pytest.fail("drift must not stop a process"))
    monkeypatch.setattr(reload, "_spawn_worker", lambda *args: pytest.fail("drift must not spawn"))
    monkeypatch.setattr(reload, "_inspect_workflows", lambda request, env: identity)
    with pytest.raises(ValueError):
        reload.reload_temporal_worker(request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
