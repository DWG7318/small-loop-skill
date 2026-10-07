import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

from slk_transport import runtime_binding_migration as migration


RUN_ID = "RUN-A"


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path.resolve()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def endpoint(version: int, *, aggregate: int, timeout: int) -> dict[str, object]:
    return {
        "schema_version": "slk.transport-endpoint/v1",
        "run_id": RUN_ID,
        "role": "checker",
        "role_instance_id": "checker-a",
        "agent_runtime": "ocrv",
        "adapter": "ocrv-checker",
        "host_id": "win-a",
        "endpoint_version": version,
        "state": "active",
        "address": {
            "command": ["D:/OCRV/slk-checker.cmd"],
            "runtime_root": "D:/OCRV",
            "timeout_seconds": 1800,
            "review_capacity": {
                "max_tokens": 32000,
                "max_tokens_budget": aggregate,
                "timeout_minutes": timeout,
            },
        },
    }


def projection(*, runtime: int, plan: int, endpoint_version: int) -> dict[str, object]:
    return {
        "summary": {"run_id": RUN_ID, "state": "active", "closure_state": "open"},
        "runtime_snapshot": {
            "run_id": RUN_ID,
            "runtime_revision": runtime,
            "plan_revision": plan,
            "token_sequence": 53,
            "token_holder_role_instance_id": "supervisor-a",
        },
        "roles": [
            {
                "role": "supervisor",
                "role_instance_id": "supervisor-a",
                "lifecycle": "active",
                "session_id": "supervisor-session",
                "model": "gpt-sol",
                "reasoning": "xhigh",
                "endpoints": [{"endpoint_version": 1, "state": "active"}],
            },
            {
                "role": "checker",
                "role_instance_id": "checker-a",
                "lifecycle": "active",
                "session_id": "D:\\OCRV",
                "model": "qwen-max",
                "reasoning": "provider-default",
                "endpoints": [{
                    "endpoint_version": endpoint_version,
                    "state": "active",
                    "transport_adapter": "ocrv-checker",
                    "host_identity": "win-a",
                    "session_id": "D:\\OCRV",
                }],
            },
        ],
    }


def fixture(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    source_endpoint = write_json(tmp_path / "checker-endpoint-v1.json", endpoint(1, aggregate=64000, timeout=15))
    target_endpoint = write_json(tmp_path / "checker-endpoint-v2.json", endpoint(2, aggregate=0, timeout=0))
    credentials = {}
    roles = {}
    for role in ("supervisor", "checker", "worker"):
        credential = tmp_path / f"{role}.dpapi"
        credential.write_text("sealed", encoding="ascii")
        credentials[role] = credential.resolve()
        if role == "checker":
            path = source_endpoint
        else:
            value = {
                "schema_version": "slk.transport-endpoint/v1", "run_id": RUN_ID,
                "role": role, "role_instance_id": f"{role}-a",
                "agent_runtime": "codex" if role == "supervisor" else "dsh",
                "adapter": "codex-app-server" if role == "supervisor" else "dsh-worker",
                "host_id": "win-a", "endpoint_version": 1, "state": "active",
                "address": {"thread_id": "thread-a"} if role == "supervisor" else {
                    "command": ["D:/DSH/slk-worker.cmd"], "runtime_root": "D:/DSH",
                    "session_id": "worker-session", "timeout_seconds": 1800,
                },
            }
            path = write_json(tmp_path / f"{role}-endpoint.json", value)
        roles[role] = {
            "endpoint_path": str(path), "endpoint_sha256": sha256(path),
            "credential_path": str(credentials[role]),
        }
    record = tmp_path / "run.md"
    record.write_text("run", encoding="utf-8")
    cells4 = [
        {"go_id": "GO-1", "cell_id": "CELL-1", "payload": {
            "cell_id": "CELL-1", "cell_ordinal": 1, "required_cell_count": 2,
            "task": "first task", "d1_criteria": ["first criterion"],
            "root_record_path": str(record.resolve()),
        }},
        {"go_id": "GO-1", "cell_id": "CELL-2", "payload": {
            "cell_id": "CELL-2", "cell_ordinal": 2, "required_cell_count": 2,
            "task": "second task", "d1_criteria": ["second criterion"],
            "root_record_path": str(record.resolve()),
        }},
    ]
    workflow_path = write_json(tmp_path / "workflow.json", {
        "schema_version": "slk.temporal-workflow-identity/v1", "run_id": RUN_ID,
        "address": "127.0.0.1:7233", "task_queue": "slk",
        "start_workflow_id": "slk-start-RUN-A", "start_run_id": "start-native",
        "run_workflow_id": "slk-run-RUN-A", "run_run_id": "run-native",
        "startup_fingerprint": "f" * 64,
    })
    source_host_value = {
        "schema_version": "slk.role-host/v2", "run_id": RUN_ID, "plan_revision": 4,
        "state_command": ["C:/tools/slk-state.exe"],
        "transport_command": ["C:/tools/slk-transport.cmd"], "roles": roles,
        "cells": cells4, "d2_criteria": ["combined acceptance"],
        "temporal": {
            "client_command": [str(Path(sys.executable).resolve()), "-m", "slk_temporal.delivery_client"],
            "workflow_identity_path": str(workflow_path),
            "workflow_identity_sha256": sha256(workflow_path),
            "attempt_root": str(tmp_path / "attempts"),
        },
    }
    Path(source_host_value["temporal"]["attempt_root"]).mkdir()
    source_host = write_json(tmp_path / "role-host-plan4.json", source_host_value)

    target_roles = copy.deepcopy(roles)
    target_roles["checker"] = {
        **target_roles["checker"], "endpoint_path": str(target_endpoint),
        "endpoint_sha256": sha256(target_endpoint),
    }
    cells5 = [copy.deepcopy(cells4[0])]
    for index, cell_id in enumerate(("CELL-2A", "CELL-2B"), start=2):
        cells5.append({"go_id": "GO-1", "cell_id": cell_id, "payload": {
            "cell_id": cell_id, "cell_ordinal": index, "required_cell_count": 3,
            "task": f"successor {cell_id}", "d1_criteria": [f"criterion {cell_id}"],
            "root_record_path": str(record.resolve()),
        }})
    for index, cell in enumerate(cells5, start=1):
        cell["payload"]["cell_ordinal"] = index
        cell["payload"]["required_cell_count"] = len(cells5)
    target_host_value = {
        **copy.deepcopy(source_host_value), "plan_revision": 5,
        "roles": target_roles, "cells": cells5,
    }
    target_host = write_json(tmp_path / "role-host-plan5.json", target_host_value)

    admission = write_json(tmp_path / "admission.json", {"status": "READY"})
    supervisor_endpoint = Path(roles["supervisor"]["endpoint_path"])
    notifications = tmp_path / "notifications"
    notifications.mkdir()
    common_config = {
        "schema_version": "slk.temporal-standard-adapter/v2", "method_version": "4.4.2",
        "run_id": RUN_ID, "transport_command": ["C:/tools/slk-transport.cmd"],
        "query_command": ["C:/tools/slk-bi-query.exe"],
        "state_config_path": str(write_json(tmp_path / "state-config.json", {
            "schema_version": "slk.config/v1", "data_root": str(tmp_path / "data")
        })),
        "admission_kind": "PRODUCT", "admission_path": str(admission),
        "attempt_root": str(tmp_path / "attempts"),
        "notification_attempt_root": str(notifications),
        "supervisor_endpoint_path": str(supervisor_endpoint),
        "overwatcher_activity": {
            "endpoint_ref": "ow-v1", "role_instance_id": "ow-a",
            "started_path": str(write_json(tmp_path / "ow-started.json", {"status": "STARTED"})),
            "completed_path": None, "failed_path": None,
            "attestation_path": str(write_json(tmp_path / "ow-attestation.json", {"status": "ACTIVE"})),
            "attestation_sha256": "a" * 64,
        },
    }
    Path(tmp_path / "data").mkdir()
    source_config_value = {
        **common_config, "role_host_binding": {"path": str(source_host), "sha256": sha256(source_host)}
    }
    target_config_value = {
        **common_config, "role_host_binding": {"path": str(target_host), "sha256": sha256(target_host)}
    }
    live_config = write_json(tmp_path / f"{RUN_ID}.json", source_config_value)
    target_config = write_json(tmp_path / f"{RUN_ID}.plan5.json", target_config_value)

    rebind_operation = write_json(tmp_path / "rebind-operation.json", {
        "event_id": "rebind-checker-v2", "run_id": RUN_ID, "role_instance_id": "checker-a",
        "endpoint": {
            "endpoint_version": 2, "transport_adapter": "ocrv-checker",
            "host_identity": "win-a", "session_id": "D:\\OCRV",
            "native_address": endpoint(2, aggregate=0, timeout=0)["address"],
        },
        "reason": "remove finite aggregate review ceiling", "occurred_at": "2026-10-07T00:00:00Z",
    })
    revise_operation = write_json(tmp_path / "revise-operation.json", {
        "event_id": "split-cell-2", "run_id": RUN_ID,
        "snapshot": {"expected_plan_revision": 4, "cell_split": {
            "source_go_id": "GO-1", "source_cell_id": "CELL-2",
            "failure_event_ids": ["fail-1", "fail-2"],
            "successor_cells": [
                {"cell_id": "CELL-2A", "title": "A", "objective": "successor CELL-2A"},
                {"cell_id": "CELL-2B", "title": "B", "objective": "successor CELL-2B"},
            ],
        }},
        "reason": "second D1 failure requires a smaller engineering split",
        "occurred_at": "2026-10-07T00:00:01Z",
    })
    sealed = tmp_path / "supervisor.dpapi"
    sealed.write_text("sealed", encoding="ascii")

    def admin(path: Path, operation: str, operation_path: Path, revision: int) -> Path:
        return write_json(path, {
            "schema_version": "slk.supervisor-admin/v1", "run_id": RUN_ID,
            "supervisor_role_instance_id": "supervisor-a", "expected_runtime_revision": revision,
            "sealed_credential_path": str(sealed.resolve()),
            "state_command": ["C:/tools/slk-state.exe"], "operation": operation,
            "operation_request_path": str(operation_path),
            "operation_request_sha256": sha256(operation_path),
            "result_path": str((tmp_path / f"{operation}-result.json").resolve()),
        })

    rebind_admin = admin(tmp_path / "rebind-admin.json", "rebind-session", rebind_operation, 10)
    revise_admin = admin(tmp_path / "revise-admin.json", "revise-plan", revise_operation, 11)
    request_value = {
        "schema_version": "slk.runtime-binding-migration/v1", "run_id": RUN_ID,
        "role": "checker", "role_instance_id": "checker-a",
        "supervisor_role_instance_id": "supervisor-a",
        "expected_runtime_revision": 10, "expected_source_plan_revision": 4,
        "target_plan_revision": 5, "expected_token_sequence": 53,
        "source_endpoint_path": str(source_endpoint), "source_endpoint_sha256": sha256(source_endpoint),
        "target_endpoint_path": str(target_endpoint), "target_endpoint_sha256": sha256(target_endpoint),
        "source_role_host_path": str(source_host), "source_role_host_sha256": sha256(source_host),
        "target_role_host_path": str(target_host), "target_role_host_sha256": sha256(target_host),
        "live_temporal_config_path": str(live_config),
        "source_temporal_config_sha256": sha256(live_config),
        "target_temporal_config_path": str(target_config),
        "target_temporal_config_sha256": sha256(target_config),
        "rebind_admin_request_path": str(rebind_admin), "rebind_admin_request_sha256": sha256(rebind_admin),
        "revise_plan_admin_request_path": str(revise_admin), "revise_plan_admin_request_sha256": sha256(revise_admin),
        "query_command": ["C:/tools/slk-bi-query.exe"],
        "state_config_path": str(tmp_path / "state-config.json"),
        "result_path": str((tmp_path / "migration-result.json").resolve()),
    }
    request = write_json(tmp_path / "migration.json", request_value)
    return request, request_value


def test_migration_quarantines_dispatch_then_waits_for_external_plan_revision_and_publishes(tmp_path, monkeypatch):
    request, value = fixture(tmp_path)
    phase = {"value": 0}
    projections = [
        projection(runtime=10, plan=4, endpoint_version=1),
        projection(runtime=11, plan=4, endpoint_version=2),
        projection(runtime=12, plan=5, endpoint_version=2),
    ]
    monkeypatch.setattr(migration, "_query_projection", lambda _request: projections[phase["value"]])
    calls = []

    def execute(path, *, request_sha256):
        live = json.loads(Path(value["live_temporal_config_path"]).read_text())
        assert live["schema_version"] == "slk.temporal-binding-migration-guard/v1"
        calls.append(Path(path).name)
        phase["value"] += 1
        return {"status": "SUPERVISOR_ADMIN_COMPLETED", "request_sha256": request_sha256}

    monkeypatch.setattr(migration, "execute_sealed_supervisor_admin", execute)
    staged = migration.execute_runtime_binding_migration(request, request_sha256=sha256(request))
    assert staged["status"] == "RUNTIME_BINDING_REBOUND_AWAITING_PLAN_REVISION"
    assert staged["required_operation"]["request_path"] == value["revise_plan_admin_request_path"]
    assert calls == ["rebind-admin.json"]
    assert json.loads(Path(value["live_temporal_config_path"]).read_text())["dispatch_allowed"] is False

    # Supervisor owns plan authority and executes the existing revise-plan consumer.
    revise_admin = json.loads(Path(value["revise_plan_admin_request_path"]).read_text())
    write_json(Path(revise_admin["result_path"]), {
        "schema_version": "slk.supervisor-admin-result/v1",
        "status": "SUPERVISOR_ADMIN_COMPLETED", "run_id": RUN_ID,
        "supervisor_role_instance_id": "supervisor-a", "operation": "revise-plan",
        "request_sha256": value["revise_plan_admin_request_sha256"],
        "operation_request_sha256": revise_admin["operation_request_sha256"],
        "state_result": {"status": "revised", "run_id": RUN_ID, "revision": 5},
    })
    phase["value"] = 2
    result = migration.execute_runtime_binding_migration(request, request_sha256=sha256(request))

    assert result["status"] == "RUNTIME_BINDING_MIGRATED"
    assert result["runtime_revision"] == 12
    assert calls == ["rebind-admin.json"]
    assert sha256(Path(value["live_temporal_config_path"])) == value["target_temporal_config_sha256"]
    assert sha256(Path(value["source_endpoint_path"])) == value["source_endpoint_sha256"]
    assert sha256(Path(value["source_role_host_path"])) == value["source_role_host_sha256"]
    assert Path(result["source_temporal_config_backup_path"]).is_file()


def test_migration_rebind_failure_leaves_a_dispatch_blocking_guard_and_replays(tmp_path, monkeypatch):
    request, value = fixture(tmp_path)
    phase = {"value": 0}
    projections = [
        projection(runtime=10, plan=4, endpoint_version=1),
        projection(runtime=11, plan=4, endpoint_version=2),
        projection(runtime=12, plan=5, endpoint_version=2),
    ]
    monkeypatch.setattr(migration, "_query_projection", lambda _request: projections[phase["value"]])
    failed_once = {"value": False}

    def execute(path, *, request_sha256):
        assert Path(path).name == "rebind-admin.json"
        if not failed_once["value"]:
            failed_once["value"] = True
            raise ValueError("synthetic rebind failure")
        phase["value"] = 1
        return {"status": "SUPERVISOR_ADMIN_COMPLETED", "request_sha256": request_sha256}

    monkeypatch.setattr(migration, "execute_sealed_supervisor_admin", execute)
    with pytest.raises(ValueError, match="synthetic rebind failure"):
        migration.execute_runtime_binding_migration(request, request_sha256=sha256(request))
    guard = json.loads(Path(value["live_temporal_config_path"]).read_text())
    assert guard["schema_version"] == "slk.temporal-binding-migration-guard/v1"
    assert guard["dispatch_allowed"] is False

    result = migration.execute_runtime_binding_migration(request, request_sha256=sha256(request))
    assert result["status"] == "RUNTIME_BINDING_REBOUND_AWAITING_PLAN_REVISION"
    assert json.loads(Path(value["live_temporal_config_path"]).read_text())["dispatch_allowed"] is False


@pytest.mark.parametrize("damage", ["capacity", "worker-binding", "temporal-field", "token-owner"])
def test_migration_rejects_scope_drift_before_admin_or_quarantine(tmp_path, monkeypatch, damage):
    request, value = fixture(tmp_path)
    if damage == "capacity":
        target = Path(value["target_endpoint_path"])
        changed = json.loads(target.read_text())
        changed["address"]["command"] = ["D:/OCRV/other.cmd"]
        write_json(target, changed)
        value["target_endpoint_sha256"] = sha256(target)
    elif damage == "worker-binding":
        target = Path(value["target_role_host_path"])
        changed = json.loads(target.read_text())
        changed["roles"]["worker"]["credential_path"] = "D:/changed.dpapi"
        write_json(target, changed)
        value["target_role_host_sha256"] = sha256(target)
        config = Path(value["target_temporal_config_path"])
        config_value = json.loads(config.read_text())
        config_value["role_host_binding"]["sha256"] = value["target_role_host_sha256"]
        write_json(config, config_value)
        value["target_temporal_config_sha256"] = sha256(config)
    elif damage == "temporal-field":
        target = Path(value["target_temporal_config_path"])
        changed = json.loads(target.read_text())
        changed["attempt_root"] = "D:/changed-attempts"
        write_json(target, changed)
        value["target_temporal_config_sha256"] = sha256(target)
    write_json(request, value)

    current = projection(runtime=10, plan=4, endpoint_version=1)
    if damage == "token-owner":
        current["runtime_snapshot"]["token_holder_role_instance_id"] = "checker-a"
    monkeypatch.setattr(migration, "_query_projection", lambda _request: current)
    monkeypatch.setattr(
        migration, "execute_sealed_supervisor_admin",
        lambda *_args, **_kwargs: pytest.fail("invalid migration must not consume authority"),
    )
    with pytest.raises(ValueError):
        migration.execute_runtime_binding_migration(request, request_sha256=sha256(request))
    assert sha256(Path(value["live_temporal_config_path"])) == value["source_temporal_config_sha256"]


def test_preparer_materializes_v2_endpoint_host_config_and_closed_two_stage_request(tmp_path, monkeypatch):
    _request, value = fixture(tmp_path)
    final_host_path = Path(value["target_role_host_path"])
    draft_value = json.loads(final_host_path.read_text())
    draft_value["roles"]["checker"]["endpoint_sha256"] = "PENDING"
    output_root = tmp_path / "prepared-output"
    output_root.mkdir()
    expected_endpoint_path = output_root / "checker-endpoint-v2.json"
    draft_value["roles"]["checker"]["endpoint_path"] = str(expected_endpoint_path.resolve())
    draft = write_json(tmp_path / "role-host-plan5.draft.json", draft_value)
    revise_admin = json.loads(Path(value["revise_plan_admin_request_path"]).read_text())
    revise_operation = Path(revise_admin["operation_request_path"])
    prep_value = {
        "schema_version": "slk.runtime-binding-migration-preparation/v1",
        "run_id": RUN_ID,
        "source_endpoint_path": value["source_endpoint_path"],
        "source_endpoint_sha256": value["source_endpoint_sha256"],
        "source_role_host_path": value["source_role_host_path"],
        "source_role_host_sha256": value["source_role_host_sha256"],
        "target_role_host_draft_path": str(draft),
        "target_role_host_draft_sha256": sha256(draft),
        "live_temporal_config_path": value["live_temporal_config_path"],
        "source_temporal_config_sha256": value["source_temporal_config_sha256"],
        "revise_plan_operation_path": str(revise_operation),
        "revise_plan_operation_sha256": sha256(revise_operation),
        "occurred_at": "2026-10-07T00:00:00Z",
        "output_root": str(output_root.resolve()),
    }
    prep = write_json(tmp_path / "prepare-migration.json", prep_value)
    monkeypatch.setattr(
        migration, "_query_projection",
        lambda _request: projection(runtime=10, plan=4, endpoint_version=1),
    )

    result = migration.prepare_runtime_binding_migration(prep, request_sha256=sha256(prep))

    assert result["status"] == "RUNTIME_BINDING_MIGRATION_PREPARED"
    target_endpoint = json.loads(Path(result["target_endpoint_path"]).read_text())
    assert target_endpoint["endpoint_version"] == 2
    assert target_endpoint["address"]["review_capacity"] == {
        "max_tokens": 32000, "max_tokens_budget": 0, "timeout_minutes": 0,
    }
    target_host = json.loads(Path(result["target_role_host_path"]).read_text())
    assert target_host["roles"]["checker"] == {
        "endpoint_path": result["target_endpoint_path"],
        "endpoint_sha256": result["target_endpoint_sha256"],
        "credential_path": draft_value["roles"]["checker"]["credential_path"],
    }
    migration_request = json.loads(Path(result["migration_request_path"]).read_text())
    assert migration_request["target_plan_revision"] == 5
    assert migration_request["expected_runtime_revision"] == 10
    assert migration_request["expected_token_sequence"] == 53
    assert result["first_stage_command"][-2:] == ["--sha256", result["migration_request_sha256"]]
