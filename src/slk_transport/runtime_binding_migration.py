"""Fail-closed publication of one same-identity Checker endpoint revision.

The consumer owns no product-plan authority.  It first installs a Temporal
dispatch guard and consumes the existing sealed ``rebind-session`` operation.
The Supervisor must then execute the separately frozen ``revise-plan`` request.
A replay verifies that result and publishes the new RoleHost/config atomically.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from . import worker_completion as wc
from .contracts import Endpoint
from .role_host import RoleHost
from .supervisor_admin import execute_sealed_supervisor_admin


FIELDS = {
    "schema_version", "run_id", "role", "role_instance_id",
    "supervisor_role_instance_id", "expected_runtime_revision",
    "expected_source_plan_revision", "target_plan_revision",
    "expected_token_sequence", "source_endpoint_path", "source_endpoint_sha256",
    "target_endpoint_path", "target_endpoint_sha256", "source_role_host_path",
    "source_role_host_sha256", "target_role_host_path", "target_role_host_sha256",
    "live_temporal_config_path", "source_temporal_config_sha256",
    "target_temporal_config_path", "target_temporal_config_sha256",
    "rebind_admin_request_path", "rebind_admin_request_sha256",
    "revise_plan_admin_request_path", "revise_plan_admin_request_sha256",
    "query_command", "state_config_path", "result_path",
}
ENDPOINT_FIELDS = {
    "schema_version", "run_id", "role", "role_instance_id", "agent_runtime",
    "adapter", "host_id", "endpoint_version", "state", "address",
}
ADMIN_FIELDS = {
    "schema_version", "run_id", "supervisor_role_instance_id",
    "expected_runtime_revision", "sealed_credential_path", "state_command",
    "operation", "operation_request_path", "operation_request_sha256", "result_path",
}
CONFIG_FIELDS = {
    "schema_version", "method_version", "run_id", "transport_command",
    "query_command", "state_config_path", "admission_kind", "admission_path",
    "attempt_root", "notification_attempt_root", "supervisor_endpoint_path",
    "role_host_binding", "overwatcher_activity",
}
RESULT_FIELDS = {
    "schema_version", "status", "run_id", "role", "role_instance_id",
    "supervisor_role_instance_id", "request_sha256", "source_endpoint_sha256",
    "target_endpoint_sha256", "source_role_host_sha256", "target_role_host_sha256",
    "source_temporal_config_sha256", "target_temporal_config_sha256",
    "source_temporal_config_backup_path", "runtime_revision", "plan_revision",
    "token_sequence",
}
SHA256 = set("0123456789abcdef")
PREPARATION_FIELDS = {
    "schema_version", "run_id", "source_endpoint_path", "source_endpoint_sha256",
    "source_role_host_path", "source_role_host_sha256", "target_role_host_draft_path",
    "target_role_host_draft_sha256", "live_temporal_config_path",
    "source_temporal_config_sha256", "revise_plan_operation_path",
    "revise_plan_operation_sha256", "occurred_at", "output_root",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - SHA256:
        raise ValueError(f"{label} is not a SHA-256 digest")
    return value


def _absolute(value: object, label: str, *, existing: bool = True) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute() or (existing and not path.is_file()):
        raise ValueError(f"{label} path is unavailable")
    return path.resolve()


def _object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _hashed(request: Mapping[str, Any], path_field: str, hash_field: str, label: str) -> tuple[Path, dict[str, Any]]:
    path = _absolute(request[path_field], label)
    expected = _digest(request[hash_field], f"{label} hash")
    if _sha256(path) != expected:
        raise ValueError(f"{label} hash changed")
    return path, _object(path, label)


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _validate_endpoint_pair(
    request: Mapping[str, Any], source: Mapping[str, Any], target: Mapping[str, Any],
) -> None:
    if (set(source) != ENDPOINT_FIELDS or set(target) != ENDPOINT_FIELDS
        or source.get("schema_version") != "slk.transport-endpoint/v1"
        or target.get("schema_version") != "slk.transport-endpoint/v1"):
        raise ValueError("endpoint revision is not closed")
    if request["source_endpoint_path"] == request["target_endpoint_path"]:
        raise ValueError("endpoint revision must preserve the old file at a new path")
    stable = ENDPOINT_FIELDS - {"endpoint_version", "address"}
    if any(source.get(field) != target.get(field) for field in stable):
        raise ValueError("endpoint revision changed Checker identity")
    if (source.get("run_id") != request["run_id"] or source.get("role") != "checker"
        or source.get("role_instance_id") != request["role_instance_id"]
        or source.get("state") != "active"
        or type(source.get("endpoint_version")) is not int
        or target.get("endpoint_version") != source["endpoint_version"] + 1):
        raise ValueError("endpoint revision does not target the exact current Checker")
    source_address, target_address = source.get("address"), target.get("address")
    if not isinstance(source_address, Mapping) or not isinstance(target_address, Mapping):
        raise ValueError("Checker endpoint address is invalid")
    if set(source_address) != set(target_address) or set(source_address) != {
        "command", "runtime_root", "timeout_seconds", "review_capacity",
    }:
        raise ValueError("Checker endpoint address shape changed")
    for field in ("command", "runtime_root", "timeout_seconds"):
        if source_address[field] != target_address[field]:
            raise ValueError("endpoint migration may change only review capacity")
    old_capacity, new_capacity = source_address["review_capacity"], target_address["review_capacity"]
    capacity_fields = {"max_tokens", "max_tokens_budget", "timeout_minutes"}
    if (not isinstance(old_capacity, Mapping) or not isinstance(new_capacity, Mapping)
        or set(old_capacity) != capacity_fields or set(new_capacity) != capacity_fields
        or type(old_capacity["max_tokens"]) is not int or old_capacity["max_tokens"] < 1
        or new_capacity["max_tokens"] != old_capacity["max_tokens"]
        or type(old_capacity["max_tokens_budget"]) is not int
        or old_capacity["max_tokens_budget"] < 1
        or type(old_capacity["timeout_minutes"]) is not int
        or old_capacity["timeout_minutes"] < 1
        or new_capacity["max_tokens_budget"] != 0
        or new_capacity["timeout_minutes"] != 0):
        raise ValueError("Checker review capacity is not the finite-to-unbounded migration")
    Endpoint.from_dict(source)
    Endpoint.from_dict(target)


def _normalized_cell(cell: Mapping[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(cell))
    payload = value.get("payload")
    if isinstance(payload, dict):
        payload.pop("cell_ordinal", None)
        payload.pop("required_cell_count", None)
    return value


def _validate_host_pair(
    request: Mapping[str, Any], source_path: Path, source: Mapping[str, Any],
    target_path: Path, target: Mapping[str, Any], source_endpoint: Path,
    target_endpoint: Path, split: Mapping[str, Any],
) -> None:
    RoleHost(source, request["source_role_host_sha256"])
    RoleHost(target, request["target_role_host_sha256"])
    if (source.get("run_id") != request["run_id"] or target.get("run_id") != request["run_id"]
        or source.get("plan_revision") != request["expected_source_plan_revision"]
        or target.get("plan_revision") != request["target_plan_revision"]):
        raise ValueError("RoleHost plan identity changed")
    if request["target_plan_revision"] != request["expected_source_plan_revision"] + 1:
        raise ValueError("binding migration supports one adjacent plan revision")
    for field in ("schema_version", "state_command", "transport_command", "d2_criteria", "temporal"):
        if source.get(field) != target.get(field):
            raise ValueError("RoleHost changed outside plan cells and Checker endpoint")
    source_roles, target_roles = source.get("roles"), target.get("roles")
    if not isinstance(source_roles, Mapping) or not isinstance(target_roles, Mapping):
        raise ValueError("RoleHost roles are invalid")
    for role in ("supervisor", "worker"):
        if source_roles.get(role) != target_roles.get(role):
            raise ValueError("non-Checker RoleHost binding changed")
    old_checker, new_checker = source_roles.get("checker"), target_roles.get("checker")
    if (not isinstance(old_checker, Mapping) or not isinstance(new_checker, Mapping)
        or Path(str(old_checker.get("endpoint_path"))).resolve() != source_endpoint
        or Path(str(new_checker.get("endpoint_path"))).resolve() != target_endpoint
        or old_checker.get("endpoint_sha256") != request["source_endpoint_sha256"]
        or new_checker.get("endpoint_sha256") != request["target_endpoint_sha256"]
        or old_checker.get("credential_path") != new_checker.get("credential_path")):
        raise ValueError("RoleHost does not preserve the same Checker credential")
    source_cells, target_cells = source.get("cells"), target.get("cells")
    successors = split.get("successor_cells")
    if not isinstance(source_cells, list) or not isinstance(target_cells, list) or not isinstance(successors, list):
        raise ValueError("RoleHost CELL revision is invalid")
    source_id = split.get("source_cell_id")
    source_go = split.get("source_go_id")
    indices = [i for i, cell in enumerate(source_cells)
               if isinstance(cell, Mapping) and cell.get("cell_id") == source_id and cell.get("go_id") == source_go]
    successor_ids = [item.get("cell_id") for item in successors if isinstance(item, Mapping)]
    if len(indices) != 1 or len(successor_ids) != len(successors) or len(successor_ids) < 2:
        raise ValueError("revised RoleHost split identity is invalid")
    index = indices[0]
    expected_ids = [cell.get("cell_id") for cell in source_cells[:index]] + successor_ids + [
        cell.get("cell_id") for cell in source_cells[index + 1:]
    ]
    if [cell.get("cell_id") if isinstance(cell, Mapping) else None for cell in target_cells] != expected_ids:
        raise ValueError("target RoleHost does not freeze the exact split order")
    unaffected = list(zip(source_cells[:index], target_cells[:index])) + list(
        zip(source_cells[index + 1:], target_cells[index + len(successor_ids):])
    )
    if any(_normalized_cell(old) != _normalized_cell(new) for old, new in unaffected):
        raise ValueError("target RoleHost changed an unaffected CELL")


def _validate_admin(
    request: Mapping[str, Any], path_field: str, hash_field: str, operation: str,
    expected_revision: int,
) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    path, value = _hashed(request, path_field, hash_field, f"{operation} admin request")
    if (set(value) != ADMIN_FIELDS or value.get("schema_version") != "slk.supervisor-admin/v1"
        or value.get("run_id") != request["run_id"]
        or value.get("supervisor_role_instance_id") != request["supervisor_role_instance_id"]
        or value.get("expected_runtime_revision") != expected_revision
        or value.get("operation") != operation):
        raise ValueError(f"{operation} admin request changed the frozen authority")
    operation_path = _absolute(value.get("operation_request_path"), f"{operation} operation")
    if (_sha256(operation_path) != _digest(value.get("operation_request_sha256"), f"{operation} operation hash")):
        raise ValueError(f"{operation} operation request hash changed")
    operation_value = _object(operation_path, f"{operation} operation")
    if operation_value.get("run_id") != request["run_id"]:
        raise ValueError(f"{operation} operation changed Run identity")
    return path, value, operation_path, operation_value


def _validate_config_pair(
    request: Mapping[str, Any], source: Mapping[str, Any], target: Mapping[str, Any],
    source_host: Path, target_host: Path,
) -> None:
    if (set(source) != CONFIG_FIELDS or set(target) != CONFIG_FIELDS
        or source.get("run_id") != request["run_id"] or target.get("run_id") != request["run_id"]):
        raise ValueError("Temporal config is not closed")
    for field in CONFIG_FIELDS - {"role_host_binding"}:
        if source.get(field) != target.get(field):
            raise ValueError("Temporal migration may change only the RoleHost binding")
    source_binding, target_binding = source.get("role_host_binding"), target.get("role_host_binding")
    if (not isinstance(source_binding, Mapping) or not isinstance(target_binding, Mapping)
        or set(source_binding) != {"path", "sha256"} or set(target_binding) != {"path", "sha256"}
        or Path(str(source_binding.get("path"))).resolve() != source_host
        or Path(str(target_binding.get("path"))).resolve() != target_host
        or source_binding.get("sha256") != request["source_role_host_sha256"]
        or target_binding.get("sha256") != request["target_role_host_sha256"]):
        raise ValueError("Temporal config does not bind the exact old and new RoleHosts")


def _query_projection(request: Mapping[str, Any]) -> dict[str, Any]:
    result = wc._run_json_command(
        list(request["query_command"]), ["run", "--run-id", request["run_id"]],
        credential=None, state_config_path=request["state_config_path"],
    )
    meta = result.pop("_slk_command", None)
    if isinstance(meta, Mapping) and meta.get("process_exit") != 0:
        raise ValueError("Run query failed")
    return result


def _phase(
    request: Mapping[str, Any], projection: Mapping[str, Any],
    source_endpoint: Mapping[str, Any], target_endpoint: Mapping[str, Any], session_id: str,
) -> str:
    summary, snapshot, roles = projection.get("summary"), projection.get("runtime_snapshot"), projection.get("roles")
    if (not isinstance(summary, Mapping) or not isinstance(snapshot, Mapping) or not isinstance(roles, list)
        or summary.get("run_id") != request["run_id"] or summary.get("state") != "active"
        or summary.get("closure_state") != "open"
        or snapshot.get("run_id") != request["run_id"]
        or snapshot.get("token_sequence") != request["expected_token_sequence"]
        or snapshot.get("token_holder_role_instance_id") != request["supervisor_role_instance_id"]):
        raise ValueError("runtime binding migration requires the exact active Supervisor TOKEN boundary")
    checker = [row for row in roles if isinstance(row, Mapping) and row.get("role") == "checker"
               and row.get("lifecycle") == "active"]
    supervisor = [row for row in roles if isinstance(row, Mapping) and row.get("role") == "supervisor"
                  and row.get("lifecycle") == "active"]
    if (len(checker) != 1 or len(supervisor) != 1
        or checker[0].get("role_instance_id") != request["role_instance_id"]
        or supervisor[0].get("role_instance_id") != request["supervisor_role_instance_id"]):
        raise ValueError("runtime role identity is not unique and current")
    active = [item for item in checker[0].get("endpoints", [])
              if isinstance(item, Mapping) and item.get("state") == "active"]
    if len(active) != 1:
        raise ValueError("current Checker endpoint is ambiguous")
    if (checker[0].get("session_id") != session_id
        or active[0].get("transport_adapter") != target_endpoint.get("adapter")
        or active[0].get("host_identity") != target_endpoint.get("host_id")
        or active[0].get("session_id") != session_id):
        raise ValueError("current Checker endpoint binding changed")
    source_version = source_endpoint["endpoint_version"]
    target_version = target_endpoint["endpoint_version"]
    state = (snapshot.get("runtime_revision"), snapshot.get("plan_revision"), active[0].get("endpoint_version"))
    allowed = {
        (request["expected_runtime_revision"], request["expected_source_plan_revision"], source_version): "SOURCE",
        (request["expected_runtime_revision"] + 1, request["expected_source_plan_revision"], target_version): "REBOUND",
        (request["expected_runtime_revision"] + 2, request["target_plan_revision"], target_version): "REVISED",
    }
    try:
        return allowed[state]
    except KeyError as exc:
        raise ValueError("runtime changed outside the frozen binding migration") from exc


def _atomic_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(f".{path.name}.slk-migration.tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def _guard(request: Mapping[str, Any], request_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": "slk.temporal-binding-migration-guard/v1",
        "run_id": request["run_id"], "request_sha256": request_sha256,
        "source_temporal_config_sha256": request["source_temporal_config_sha256"],
        "target_temporal_config_sha256": request["target_temporal_config_sha256"],
        "dispatch_allowed": False,
    }


def _install_guard(
    request: Mapping[str, Any], request_sha256: str, live: Path, source_bytes: bytes,
) -> Path:
    backup = live.with_name(f"{live.name}.pre-migration-{request['source_temporal_config_sha256']}")
    if backup.exists():
        if _sha256(backup) != request["source_temporal_config_sha256"]:
            raise ValueError("source Temporal config backup conflicts")
    else:
        _atomic_bytes(backup, source_bytes)
    encoded = (json.dumps(_guard(request, request_sha256), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")) + "\n").encode("utf-8")
    _atomic_bytes(live, encoded)
    return backup


def _validate_revise_result(
    request: Mapping[str, Any], admin: Mapping[str, Any], admin_path: Path,
) -> None:
    result = _absolute(admin.get("result_path"), "revise-plan result")
    value = _object(result, "revise-plan result")
    if (set(value) != {
            "schema_version", "status", "run_id", "supervisor_role_instance_id",
            "operation", "request_sha256", "operation_request_sha256", "state_result",
        }
        or value.get("schema_version") != "slk.supervisor-admin-result/v1"
        or value.get("status") != "SUPERVISOR_ADMIN_COMPLETED"
        or value.get("run_id") != request["run_id"]
        or value.get("supervisor_role_instance_id") != request["supervisor_role_instance_id"]
        or value.get("operation") != "revise-plan"
        or value.get("request_sha256") != _sha256(admin_path)
        or value.get("operation_request_sha256") != admin["operation_request_sha256"]
        or not isinstance(value.get("state_result"), Mapping)
        or value["state_result"].get("status") != "revised"
        or value["state_result"].get("run_id") != request["run_id"]
        or value["state_result"].get("revision") != request["target_plan_revision"]):
        raise ValueError("Supervisor revise-plan result is missing or changed")


def _saved_result(path: Path, request: Mapping[str, Any], request_sha256: str) -> dict[str, Any]:
    value = _object(path, "runtime binding migration result")
    live = _absolute(request["live_temporal_config_path"], "live Temporal config")
    if (set(value) != RESULT_FIELDS or value.get("schema_version") != "slk.runtime-binding-migration-result/v1"
        or value.get("status") != "RUNTIME_BINDING_MIGRATED"
        or value.get("run_id") != request["run_id"] or value.get("request_sha256") != request_sha256
        or _sha256(live) != request["target_temporal_config_sha256"]):
        raise ValueError("saved runtime binding migration result conflicts")
    return value


def _stable_write(path: Path, value: Mapping[str, Any]) -> Path:
    return wc._write_or_reuse_stable_request(path, dict(value)).resolve()


def prepare_runtime_binding_migration(
    request_path: Path | str, *, request_sha256: str,
) -> dict[str, Any]:
    """Materialize immutable v2/Host/config/admin artifacts without mutating the Run."""

    request_path = Path(request_path).resolve()
    if _sha256(request_path) != _digest(request_sha256, "preparation request hash"):
        raise ValueError("runtime binding preparation request hash changed")
    request = _object(request_path, "runtime binding preparation request")
    if (set(request) != PREPARATION_FIELDS
        or request.get("schema_version") != "slk.runtime-binding-migration-preparation/v1"
        or not isinstance(request.get("run_id"), str) or not request["run_id"]):
        raise ValueError("runtime binding preparation request is not closed")
    try:
        datetime.fromisoformat(str(request["occurred_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("migration preparation timestamp is invalid") from exc
    output_root = Path(str(request["output_root"]))
    if not output_root.is_absolute() or not output_root.is_dir():
        raise ValueError("migration preparation output root is unavailable")
    output_root = output_root.resolve()
    source_endpoint_path, source_endpoint = _hashed(
        request, "source_endpoint_path", "source_endpoint_sha256", "source endpoint")
    source_host_path, source_host = _hashed(
        request, "source_role_host_path", "source_role_host_sha256", "source RoleHost")
    _draft_path, draft = _hashed(
        request, "target_role_host_draft_path", "target_role_host_draft_sha256", "target RoleHost draft")
    live_config = _absolute(request["live_temporal_config_path"], "live Temporal config")
    if _sha256(live_config) != _digest(
        request["source_temporal_config_sha256"], "source Temporal config hash"):
        raise ValueError("source Temporal config changed")
    source_config = _object(live_config, "source Temporal config")
    revise_path, revise = _hashed(
        request, "revise_plan_operation_path", "revise_plan_operation_sha256",
        "revise-plan operation",
    )
    if (revise.get("run_id") != request["run_id"]
        or not isinstance(revise.get("snapshot"), Mapping)
        or not isinstance(revise["snapshot"].get("cell_split"), Mapping)):
        raise ValueError("revise-plan operation is not the exact CELL split")
    source_plan = source_host.get("plan_revision")
    if (source_host.get("run_id") != request["run_id"] or type(source_plan) is not int
        or revise["snapshot"].get("expected_plan_revision") != source_plan
        or draft.get("run_id") != request["run_id"]
        or draft.get("plan_revision") != source_plan + 1):
        raise ValueError("RoleHost draft and revise-plan operation are not adjacent")
    if (set(source_config) != CONFIG_FIELDS or source_config.get("run_id") != request["run_id"]
        or source_config.get("role_host_binding") != {
            "path": str(source_host_path).replace("\\", "/"),
            "sha256": request["source_role_host_sha256"],
        } and not (
            isinstance(source_config.get("role_host_binding"), Mapping)
            and Path(str(source_config["role_host_binding"].get("path"))).resolve() == source_host_path
            and source_config["role_host_binding"].get("sha256") == request["source_role_host_sha256"]
        )):
        raise ValueError("source Temporal config does not bind the source RoleHost")
    query_request = {
        "run_id": request["run_id"], "query_command": source_config["query_command"],
        "state_config_path": source_config["state_config_path"],
    }
    projection = _query_projection(query_request)
    snapshot = projection.get("runtime_snapshot")
    roles = projection.get("roles")
    if not isinstance(snapshot, Mapping) or not isinstance(roles, list):
        raise ValueError("current Run projection is incomplete")
    checker_rows = [row for row in roles if isinstance(row, Mapping) and row.get("role") == "checker"
                    and row.get("lifecycle") == "active"]
    supervisor_rows = [row for row in roles if isinstance(row, Mapping) and row.get("role") == "supervisor"
                       and row.get("lifecycle") == "active"]
    if len(checker_rows) != 1 or len(supervisor_rows) != 1:
        raise ValueError("current Run role registry is ambiguous")
    checker, supervisor = checker_rows[0], supervisor_rows[0]
    if (snapshot.get("run_id") != request["run_id"] or snapshot.get("plan_revision") != source_plan
        or snapshot.get("token_holder_role_instance_id") != supervisor.get("role_instance_id")
        or type(snapshot.get("runtime_revision")) is not int
        or type(snapshot.get("token_sequence")) is not int):
        raise ValueError("preparation requires the exact current Supervisor TOKEN boundary")
    active_endpoints = [item for item in checker.get("endpoints", [])
                        if isinstance(item, Mapping) and item.get("state") == "active"]
    if (len(active_endpoints) != 1
        or active_endpoints[0].get("endpoint_version") != source_endpoint.get("endpoint_version")
        or active_endpoints[0].get("transport_adapter") != source_endpoint.get("adapter")
        or active_endpoints[0].get("host_identity") != source_endpoint.get("host_id")
        or active_endpoints[0].get("session_id") != checker.get("session_id")):
        raise ValueError("source endpoint is not the current Checker binding")

    target_endpoint = json.loads(json.dumps(source_endpoint))
    target_endpoint["endpoint_version"] = source_endpoint["endpoint_version"] + 1
    capacity = target_endpoint.get("address", {}).get("review_capacity")
    if not isinstance(capacity, dict) or type(capacity.get("max_tokens")) is not int:
        raise ValueError("source Checker review capacity is invalid")
    capacity["max_tokens_budget"] = 0
    capacity["timeout_minutes"] = 0
    target_endpoint_path = output_root / "checker-endpoint-v2.json"
    _stable_write(target_endpoint_path, target_endpoint)
    target_endpoint_sha256 = _sha256(target_endpoint_path)

    target_host = json.loads(json.dumps(draft))
    checker_binding = target_host.get("roles", {}).get("checker")
    source_checker_binding = source_host.get("roles", {}).get("checker")
    if (not isinstance(checker_binding, dict) or not isinstance(source_checker_binding, Mapping)
        or checker_binding.get("credential_path") != source_checker_binding.get("credential_path")
        or checker_binding.get("endpoint_sha256") != "PENDING_STANDARD_MIGRATION_ENDPOINT_HASH"
        or Path(str(checker_binding.get("endpoint_path"))).resolve() != target_endpoint_path.resolve()):
        raise ValueError("RoleHost draft Checker placeholder is not exact")
    checker_binding["endpoint_path"] = str(target_endpoint_path.resolve()).replace("\\", "/")
    checker_binding["endpoint_sha256"] = target_endpoint_sha256
    target_host_path = output_root / f"role-host-plan{source_plan + 1}.json"
    target_host_sha256 = _sha256(_stable_write(target_host_path, target_host))

    target_config = json.loads(json.dumps(source_config))
    target_config["role_host_binding"] = {
        "path": str(target_host_path.resolve()).replace("\\", "/"),
        "sha256": target_host_sha256,
    }
    temporal_root = output_root / "temporal-config"
    temporal_root.mkdir(exist_ok=True)
    target_config_path = _stable_write(
        temporal_root / f"{request['run_id']}.plan{source_plan + 1}.json", target_config)
    target_config_sha256 = _sha256(target_config_path)

    rebind_operation = {
        "event_id": wc._stable_id(request["run_id"], "checker-endpoint-v2-rebind"),
        "run_id": request["run_id"], "role_instance_id": checker["role_instance_id"],
        "endpoint": {
            "endpoint_version": target_endpoint["endpoint_version"],
            "transport_adapter": target_endpoint["adapter"],
            "host_identity": target_endpoint["host_id"],
            "session_id": checker["session_id"], "native_address": target_endpoint["address"],
        },
        "reason": "preserve the same Checker while replacing finite aggregate review capacity",
        "occurred_at": request["occurred_at"],
    }
    rebind_operation_path = _stable_write(output_root / "checker-endpoint-v2-rebind.json", rebind_operation)
    supervisor_credential = source_host["roles"]["supervisor"]["credential_path"]
    runtime_revision = snapshot["runtime_revision"]
    rebind_admin = {
        "schema_version": "slk.supervisor-admin/v1", "run_id": request["run_id"],
        "supervisor_role_instance_id": supervisor["role_instance_id"],
        "expected_runtime_revision": runtime_revision,
        "sealed_credential_path": supervisor_credential,
        "state_command": source_host["state_command"], "operation": "rebind-session",
        "operation_request_path": str(rebind_operation_path).replace("\\", "/"),
        "operation_request_sha256": _sha256(rebind_operation_path),
        "result_path": str((output_root / "checker-endpoint-v2-rebind-admin-result.json").resolve()).replace("\\", "/"),
    }
    rebind_admin_path = _stable_write(output_root / "checker-endpoint-v2-rebind-admin.json", rebind_admin)
    revise_admin = {
        "schema_version": "slk.supervisor-admin/v1", "run_id": request["run_id"],
        "supervisor_role_instance_id": supervisor["role_instance_id"],
        "expected_runtime_revision": runtime_revision + 1,
        "sealed_credential_path": supervisor_credential,
        "state_command": source_host["state_command"], "operation": "revise-plan",
        "operation_request_path": str(revise_path).replace("\\", "/"),
        "operation_request_sha256": request["revise_plan_operation_sha256"],
        "result_path": str((output_root / f"plan{source_plan + 1}-revise-admin-result.json").resolve()).replace("\\", "/"),
    }
    revise_admin_path = _stable_write(output_root / f"plan{source_plan + 1}-revise-admin.json", revise_admin)
    migration_request = {
        "schema_version": "slk.runtime-binding-migration/v1", "run_id": request["run_id"],
        "role": "checker", "role_instance_id": checker["role_instance_id"],
        "supervisor_role_instance_id": supervisor["role_instance_id"],
        "expected_runtime_revision": runtime_revision,
        "expected_source_plan_revision": source_plan, "target_plan_revision": source_plan + 1,
        "expected_token_sequence": snapshot["token_sequence"],
        "source_endpoint_path": str(source_endpoint_path).replace("\\", "/"),
        "source_endpoint_sha256": request["source_endpoint_sha256"],
        "target_endpoint_path": str(target_endpoint_path.resolve()).replace("\\", "/"),
        "target_endpoint_sha256": target_endpoint_sha256,
        "source_role_host_path": str(source_host_path).replace("\\", "/"),
        "source_role_host_sha256": request["source_role_host_sha256"],
        "target_role_host_path": str(target_host_path.resolve()).replace("\\", "/"),
        "target_role_host_sha256": target_host_sha256,
        "live_temporal_config_path": str(live_config).replace("\\", "/"),
        "source_temporal_config_sha256": request["source_temporal_config_sha256"],
        "target_temporal_config_path": str(target_config_path).replace("\\", "/"),
        "target_temporal_config_sha256": target_config_sha256,
        "rebind_admin_request_path": str(rebind_admin_path).replace("\\", "/"),
        "rebind_admin_request_sha256": _sha256(rebind_admin_path),
        "revise_plan_admin_request_path": str(revise_admin_path).replace("\\", "/"),
        "revise_plan_admin_request_sha256": _sha256(revise_admin_path),
        "query_command": source_config["query_command"],
        "state_config_path": source_config["state_config_path"],
        "result_path": str((output_root / "runtime-binding-migration-result.json").resolve()).replace("\\", "/"),
    }
    _validate_endpoint_pair(migration_request, source_endpoint, target_endpoint)
    _validate_host_pair(
        migration_request, source_host_path, source_host, target_host_path, target_host,
        target_endpoint=target_endpoint_path, source_endpoint=source_endpoint_path,
        split=revise["snapshot"]["cell_split"],
    )
    _validate_config_pair(
        migration_request, source_config, target_config, source_host_path, target_host_path)
    migration_path = _stable_write(output_root / "runtime-binding-migration.json", migration_request)
    command = [
        *source_config["transport_command"], "migrate-runtime-binding",
        "--request", str(migration_path).replace("\\", "/"),
        "--sha256", _sha256(migration_path),
    ]
    result = {
        "schema_version": "slk.runtime-binding-migration-prepared/v1",
        "status": "RUNTIME_BINDING_MIGRATION_PREPARED", "run_id": request["run_id"],
        "request_sha256": request_sha256,
        "target_endpoint_path": str(target_endpoint_path.resolve()).replace("\\", "/"),
        "target_endpoint_sha256": target_endpoint_sha256,
        "target_role_host_path": str(target_host_path.resolve()).replace("\\", "/"),
        "target_role_host_sha256": target_host_sha256,
        "target_temporal_config_path": str(target_config_path).replace("\\", "/"),
        "target_temporal_config_sha256": target_config_sha256,
        "migration_request_path": str(migration_path).replace("\\", "/"),
        "migration_request_sha256": _sha256(migration_path),
        "first_stage_command": command,
    }
    _stable_write(output_root / "runtime-binding-migration-prepared.json", result)
    # Preparation is not publication: all source/live bytes remain exact.
    if (_sha256(source_endpoint_path) != request["source_endpoint_sha256"]
        or _sha256(source_host_path) != request["source_role_host_sha256"]
        or _sha256(live_config) != request["source_temporal_config_sha256"]):
        raise ValueError("preparation changed a live source artifact")
    return result


def execute_runtime_binding_migration(
    request_path: Path | str, *, request_sha256: str,
) -> dict[str, Any]:
    request_path = Path(request_path).resolve()
    if _sha256(request_path) != _digest(request_sha256, "migration request hash"):
        raise ValueError("runtime binding migration request hash changed")
    request = _object(request_path, "runtime binding migration request")
    if (set(request) != FIELDS or request.get("schema_version") != "slk.runtime-binding-migration/v1"
        or request.get("role") != "checker"
        or not all(isinstance(request.get(field), str) and request[field] for field in (
            "run_id", "role_instance_id", "supervisor_role_instance_id"))):
        raise ValueError("runtime binding migration request is not closed")
    for field in ("expected_runtime_revision", "expected_source_plan_revision",
                  "target_plan_revision", "expected_token_sequence"):
        _positive(request[field], field)
    if (not isinstance(request.get("query_command"), list) or not request["query_command"]
        or not all(isinstance(item, str) and item for item in request["query_command"])):
        raise ValueError("Run query command is invalid")
    state_config = _absolute(request["state_config_path"], "state config")
    result_path = _absolute(request["result_path"], "migration result", existing=False)
    if result_path.exists():
        return _saved_result(result_path, request, request_sha256)

    source_endpoint_path, source_endpoint = _hashed(
        request, "source_endpoint_path", "source_endpoint_sha256", "source endpoint")
    target_endpoint_path, target_endpoint = _hashed(
        request, "target_endpoint_path", "target_endpoint_sha256", "target endpoint")
    _validate_endpoint_pair(request, source_endpoint, target_endpoint)
    source_host_path, source_host = _hashed(
        request, "source_role_host_path", "source_role_host_sha256", "source RoleHost")
    target_host_path, target_host = _hashed(
        request, "target_role_host_path", "target_role_host_sha256", "target RoleHost")
    rebind_admin_path, rebind_admin, _, rebind = _validate_admin(
        request, "rebind_admin_request_path", "rebind_admin_request_sha256",
        "rebind-session", request["expected_runtime_revision"],
    )
    revise_admin_path, revise_admin, _, revise = _validate_admin(
        request, "revise_plan_admin_request_path", "revise_plan_admin_request_sha256",
        "revise-plan", request["expected_runtime_revision"] + 1,
    )
    target_state_endpoint = {
        "endpoint_version": target_endpoint["endpoint_version"],
        "transport_adapter": target_endpoint["adapter"],
        "host_identity": target_endpoint["host_id"],
        "session_id": rebind.get("endpoint", {}).get("session_id")
            if isinstance(rebind.get("endpoint"), Mapping) else None,
        "native_address": target_endpoint["address"],
    }
    if (rebind.get("role_instance_id") != request["role_instance_id"]
        or rebind.get("endpoint") != target_state_endpoint
        or revise.get("snapshot", {}).get("expected_plan_revision") != request["expected_source_plan_revision"]
        or not isinstance(revise.get("snapshot", {}).get("cell_split"), Mapping)):
        raise ValueError("administrative operations do not match the endpoint/plan migration")
    split = revise["snapshot"]["cell_split"]
    _validate_host_pair(
        request, source_host_path, source_host, target_host_path, target_host,
        source_endpoint_path, target_endpoint_path, split,
    )
    live_config = _absolute(request["live_temporal_config_path"], "live Temporal config")
    target_config_path, target_config = _hashed(
        request, "target_temporal_config_path", "target_temporal_config_sha256", "target Temporal config")
    source_config_path = live_config
    current_bytes = live_config.read_bytes()
    current_hash = hashlib.sha256(current_bytes).hexdigest()
    guard = _guard(request, request_sha256)
    current_value = _object(live_config, "live Temporal config")
    if current_hash == request["source_temporal_config_sha256"]:
        source_config = current_value
        source_bytes = current_bytes
    elif current_value == guard:
        backup = live_config.with_name(
            f"{live_config.name}.pre-migration-{request['source_temporal_config_sha256']}")
        if not backup.is_file() or _sha256(backup) != request["source_temporal_config_sha256"]:
            raise ValueError("guarded migration lost the source Temporal config backup")
        source_config = _object(backup, "source Temporal config backup")
        source_bytes = backup.read_bytes()
    elif current_hash == request["target_temporal_config_sha256"]:
        backup = live_config.with_name(
            f"{live_config.name}.pre-migration-{request['source_temporal_config_sha256']}")
        if not backup.is_file() or _sha256(backup) != request["source_temporal_config_sha256"]:
            raise ValueError("published migration lost the source Temporal config backup")
        source_config = _object(backup, "source Temporal config backup")
        source_bytes = backup.read_bytes()
    else:
        raise ValueError("live Temporal config changed outside the migration")
    if source_config is not None:
        _validate_config_pair(
            request, source_config, target_config, source_host_path, target_host_path)
    if (rebind_admin.get("state_command") != source_host.get("state_command")
        or revise_admin.get("state_command") != source_host.get("state_command")
        or rebind_admin.get("sealed_credential_path") != revise_admin.get("sealed_credential_path")
        or list(request["query_command"]) != list(source_config["query_command"])
        or Path(str(source_config["state_config_path"])).resolve() != state_config):
        raise ValueError("migration commands do not match the frozen Run configuration")

    session_id = str(target_state_endpoint["session_id"])
    phase = _phase(request, _query_projection(request), source_endpoint, target_endpoint, session_id)
    if phase == "SOURCE":
        if current_hash != request["source_temporal_config_sha256"] and current_value != guard:
            raise ValueError("source runtime is not paired with its source config or guard")
        backup = _install_guard(request, request_sha256, live_config, source_bytes)
        old_config = os.environ.get("SLK_CONFIG_PATH")
        os.environ["SLK_CONFIG_PATH"] = str(state_config)
        try:
            execute_sealed_supervisor_admin(
                rebind_admin_path, request_sha256=request["rebind_admin_request_sha256"])
        finally:
            if old_config is None:
                os.environ.pop("SLK_CONFIG_PATH", None)
            else:
                os.environ["SLK_CONFIG_PATH"] = old_config
        phase = _phase(request, _query_projection(request), source_endpoint, target_endpoint, session_id)
        if phase != "REBOUND":
            raise ValueError("endpoint rebind did not reach the frozen intermediate state")
    else:
        backup = live_config.with_name(
            f"{live_config.name}.pre-migration-{request['source_temporal_config_sha256']}")
    if phase == "REBOUND":
        if _object(live_config, "live Temporal migration guard") != guard:
            raise ValueError("endpoint was rebound without the Temporal dispatch guard")
        return {
            "schema_version": "slk.runtime-binding-migration-progress/v1",
            "status": "RUNTIME_BINDING_REBOUND_AWAITING_PLAN_REVISION",
            "run_id": request["run_id"], "runtime_revision": request["expected_runtime_revision"] + 1,
            "plan_revision": request["expected_source_plan_revision"],
            "dispatch_allowed": False,
            "required_operation": {
                "command": "supervisor-admin",
                "request_path": str(revise_admin_path),
                "request_sha256": request["revise_plan_admin_request_sha256"],
            },
        }

    _validate_revise_result(request, revise_admin, revise_admin_path)
    if _object(live_config, "live Temporal migration guard") != guard:
        if _sha256(live_config) != request["target_temporal_config_sha256"]:
            raise ValueError("revised plan is not protected by the migration guard")
    else:
        _atomic_bytes(live_config, target_config_path.read_bytes())
    final = _phase(request, _query_projection(request), source_endpoint, target_endpoint, session_id)
    if final != "REVISED" or _sha256(live_config) != request["target_temporal_config_sha256"]:
        raise ValueError("runtime binding publication did not reach the exact target")
    for path, digest in (
        (source_endpoint_path, request["source_endpoint_sha256"]),
        (source_host_path, request["source_role_host_sha256"]),
        (target_endpoint_path, request["target_endpoint_sha256"]),
        (target_host_path, request["target_role_host_sha256"]),
        (target_config_path, request["target_temporal_config_sha256"]),
        (backup, request["source_temporal_config_sha256"]),
    ):
        if not path.is_file() or _sha256(path) != digest:
            raise ValueError("runtime binding artifact changed during publication")
    result = {
        "schema_version": "slk.runtime-binding-migration-result/v1",
        "status": "RUNTIME_BINDING_MIGRATED", "run_id": request["run_id"],
        "role": "checker", "role_instance_id": request["role_instance_id"],
        "supervisor_role_instance_id": request["supervisor_role_instance_id"],
        "request_sha256": request_sha256,
        "source_endpoint_sha256": request["source_endpoint_sha256"],
        "target_endpoint_sha256": request["target_endpoint_sha256"],
        "source_role_host_sha256": request["source_role_host_sha256"],
        "target_role_host_sha256": request["target_role_host_sha256"],
        "source_temporal_config_sha256": request["source_temporal_config_sha256"],
        "target_temporal_config_sha256": request["target_temporal_config_sha256"],
        "source_temporal_config_backup_path": str(backup),
        "runtime_revision": request["expected_runtime_revision"] + 2,
        "plan_revision": request["target_plan_revision"],
        "token_sequence": request["expected_token_sequence"],
    }
    wc._write_or_reuse_stable_request(result_path, result)
    return result
