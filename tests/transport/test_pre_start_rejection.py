from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from slk_transport import worker_completion as wc
from slk_transport.pre_start_rejection import execute_pre_start_rejection

from test_contracts import endpoint_value, payload_hash


RUN_ID = "RUN-A"
MESSAGE_ID = "11111111-1111-4111-8111-111111111111"
OPERATION_ID = "22222222-2222-4222-8222-222222222222"


def write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path: Path) -> tuple[Path, str, dict[str, object]]:
    attempts = tmp_path / "attempts"
    source = attempts / RUN_ID / MESSAGE_ID
    endpoint = endpoint_value(role="checker", run_id=RUN_ID)
    endpoint["address"] = {"command": ["D:/OCRV/slk-checker.cmd"], "runtime_root": str(tmp_path), "timeout_seconds": 5}
    worker = endpoint_value(role="worker", run_id=RUN_ID, version=1)
    worker["address"] = {"command": ["D:/DSH/dsh-slk.cmd"]}
    malformed_payload = {"task": "direct Worker payload"}
    envelope = {
        "schema_version": "slk.transport-envelope/v1", "message_id": MESSAGE_ID,
        "token_sequence": 54, "run_id": RUN_ID, "go_id": "GO-1", "cell_id": "CELL-1",
        "sender_role": "supervisor", "sender_role_instance_id": "supervisor-a",
        "receiver_role": "checker", "receiver_role_instance_id": endpoint["role_instance_id"],
        "receiver_endpoint_version": endpoint["endpoint_version"], "payload_type": "CELL_DISPATCH",
        "payload_sha256": payload_hash(malformed_payload), "payload": malformed_payload,
    }
    write(source / "endpoint.json", endpoint)
    write(source / "envelope.json", envelope)
    write(source / "accepted.json", {"status": "accepted", "run_id": RUN_ID, "message_id": MESSAGE_ID})
    write(source / "failed.json", {
        "schema_version": "slk.transport-result/v1", "message_id": MESSAGE_ID, "run_id": RUN_ID,
        "adapter": "ocrv-checker", "status": "failed", "native_identity": {},
        "error_code": "OCRV_PAYLOAD_INVALID", "evidence": ["accepted.json", "endpoint.json", "envelope.json"],
    })
    handoff = source / "role-host" / "sender-handoff"
    handoff.mkdir(parents=True, exist_ok=True)
    # RoleHost writes the immutable handoff as compact JSON.  The adapter writes
    # the canonical attempt as pretty JSON; equality is semantic, not bytewise.
    (handoff / "endpoint.json").write_text(
        json.dumps(endpoint, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (handoff / "envelope.json").write_text(
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporal_request = write(handoff / f"temporal-request-{OPERATION_ID}.json", {
        "operation_id": OPERATION_ID, "run_id": RUN_ID, "cell_id": "CELL-1", "attempt": 1,
        "message_id": MESSAGE_ID, "sender_role_instance_id": "supervisor-a",
        "receiver_role_instance_id": endpoint["role_instance_id"],
        "payload_sha256": envelope["payload_sha256"], "source_runtime_revision": 168,
    })
    write(handoff / f"temporal-request-{OPERATION_ID}.delivery-requested.result.json", {
        "schema_version": "slk.temporal-delivery-update-result/v1", "status": "DELIVERY_REQUESTED",
        "operation": "request_delivery", "run_id": RUN_ID, "operation_id": OPERATION_ID,
        "message_id": MESSAGE_ID,
    })
    identity = write(tmp_path / "identity.json", {
        "schema_version": "slk.temporal-workflow-identity/v1", "run_id": RUN_ID,
        "address": "127.0.0.1:7233", "task_queue": "slk", "start_workflow_id": "start",
        "start_run_id": "start-run", "run_workflow_id": "run", "run_run_id": "run-run",
        "startup_fingerprint": "a" * 64,
    })
    roles = {}
    supervisor = endpoint_value(role="supervisor", run_id=RUN_ID)
    supervisor["role_instance_id"] = "supervisor-a"
    for role, raw in (("supervisor", supervisor),
                      ("checker", endpoint), ("worker", worker)):
        path = write(tmp_path / f"{role}.json", raw)
        credential = tmp_path / f"{role}.credential"
        credential.write_text("sealed", encoding="ascii")
        roles[role] = {"endpoint_path": str(path.resolve()), "endpoint_sha256": digest(path),
                       "credential_path": str(credential.resolve())}
    binding = write(tmp_path / "host.json", {
        "schema_version": "slk.role-host/v2", "run_id": RUN_ID, "plan_revision": 5,
        "state_command": [str((tmp_path / "state.exe").resolve())],
        "transport_command": [str((tmp_path / "transport.cmd").resolve())],
        "roles": roles, "cells": [{"go_id": "GO-1", "cell_id": "CELL-1", "payload": {"cell_goal": "x", "d1_criteria": ["y"]}}],
        "d2_criteria": ["done"],
        "temporal": {"client_command": [str((tmp_path / "python.exe").resolve()), "-m", "slk_temporal.delivery_client"],
                     "workflow_identity_path": str(identity.resolve()), "workflow_identity_sha256": digest(identity),
                     "attempt_root": str(attempts.resolve())},
    })
    for name in ("state.exe", "transport.cmd", "python.exe"):
        (tmp_path / name).write_text("fixture", encoding="ascii")
    result = tmp_path / "abandonment" / "result.json"
    request = write(tmp_path / "abandon.json", {
        "schema_version": "slk.pre-start-rejection-abandonment/v1",
        "role_host_binding_path": str(binding.resolve()), "role_host_binding_sha256": digest(binding),
        "source_attempt_path": str(source.resolve()),
        "temporal_request_path": str(temporal_request.resolve()), "temporal_request_sha256": digest(temporal_request),
        "expected_runtime_revision": 168, "expected_plan_revision": 5,
        "expected_token_sequence": 53, "expected_supervisor_role_instance_id": "supervisor-a",
        "result_path": str(result.resolve()),
    })
    projection = {"summary": {"run_id": RUN_ID, "slk_version": "4.4.2", "current_plan_revision": 5},
                  "runtime_snapshot": {"run_id": RUN_ID, "method_version": "4.4.2", "runtime_revision": 168,
                                       "plan_revision": 5, "token_sequence": 53,
                                       "token_holder_role_instance_id": "supervisor-a", "latest_message_id": None},
                  "token_history": [], "roles": []}
    return request, digest(request), projection


def test_pre_start_rejection_command_binds_exact_failure_and_current_supervisor(
    tmp_path: Path, monkeypatch,
) -> None:
    request, request_sha, projection = fixture(tmp_path)
    calls = []
    def temporal(command, arguments, **kwargs):
        calls.append((command, arguments, kwargs))
        return {
            "schema_version": "slk.temporal-delivery-update-result/v1",
            "status": "PRE_START_REJECTION_ABANDONED", "operation": "abandon_pre_start_rejection",
            "run_id": RUN_ID, "operation_id": OPERATION_ID, "message_id": MESSAGE_ID,
        }
    monkeypatch.setattr(wc, "_run_json_command", temporal)
    result = execute_pre_start_rejection(
        request, request_sha256=request_sha,
        authenticate=lambda _host: {"status": "authenticated", "run_id": RUN_ID, "role": "supervisor",
                                    "role_instance_id": "supervisor-a", "runtime_revision": 168},
        load_projection=lambda _host: projection,
    )
    assert result["status"] == "PRE_START_REJECTION_ABANDONED"
    assert calls[0][1][0] == "abandon-pre-start-rejection"
    temporal_source = Path(calls[0][2]["pythonpath"])
    assert (temporal_source / "slk_temporal" / "delivery_client.py").is_file()
    assert Path(json.loads(request.read_text())["result_path"]).is_file()


@pytest.mark.parametrize("damage", ["started", "unknown", "boundary", "attempt_hash"])
def test_pre_start_rejection_rejects_any_native_start_unknown_or_scope_drift(tmp_path: Path, damage: str) -> None:
    request, request_sha, projection = fixture(tmp_path)
    request_value = json.loads(request.read_text())
    source = Path(request_value["source_attempt_path"])
    if damage == "started":
        write(source / "started.json", {"status": "STARTED"})
    elif damage == "unknown":
        failed = json.loads((source / "failed.json").read_text())
        failed["error_code"] = "UNKNOWN"
        write(source / "failed.json", failed)
    elif damage == "boundary":
        projection = copy.deepcopy(projection)
        projection["runtime_snapshot"]["token_sequence"] = 54
    else:
        request_value["temporal_request_sha256"] = "0" * 64
        write(request, request_value)
        request_sha = digest(request)
    with pytest.raises(ValueError):
        execute_pre_start_rejection(
            request, request_sha256=request_sha,
            authenticate=lambda _host: {"status": "authenticated", "run_id": RUN_ID, "role": "supervisor",
                                        "role_instance_id": "supervisor-a", "runtime_revision": 168},
            load_projection=lambda _host: projection,
            run_temporal=lambda *_: pytest.fail("Temporal must not be called"),
        )
