"""Closed consumer for Supervisor-orchestrated administrative authority.

The caller supplies only paths and hashes.  DPAPI plaintext exists in this process
and is never returned or persisted.  Worker registration consumes the exact saved
Checker authority after independently authenticating the current Supervisor.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import worker_completion as wc


FIELDS = {
    "schema_version", "run_id", "supervisor_role_instance_id", "expected_runtime_revision",
    "sealed_credential_path", "state_command", "operation", "operation_request_path",
    "operation_request_sha256", "result_path",
}
PROVISION_FIELDS = FIELDS | {
    "issued_role", "issued_role_instance_id", "credential_destination_path",
}
WORKER_PROVISION_FIELDS = PROVISION_FIELDS | {
    "checker_role_instance_id", "sealed_checker_credential_path",
}
OPERATIONS = {
    "adopt-method-contract": {"applied", "idempotent_replay"},
    "revise-role-model": {"model_revised", "already_applied"},
    "resume-overwatcher-turn": {"overwatcher_turn_resumed"},
    "rebind-session": {"rebound"},
    "revise-plan": {"revised"},
    "register-role": {"registered"},
    "bind-overwatcher": {"overwatcher_bound"},
}
PROVISION_OPERATIONS = {"register-role", "bind-overwatcher"}
RESULT_FIELDS = {
    "schema_version", "status", "run_id", "supervisor_role_instance_id", "operation",
    "request_sha256", "operation_request_sha256", "state_result",
}
PROVISION_RESULT_FIELDS = RESULT_FIELDS | {
    "issued_role", "issued_role_instance_id", "sealed_credential",
}
SEALED_RESULT_FIELDS = {
    "status", "run_id", "role", "role_instance_id", "sealed_path", "sealed_sha256",
    "runtime_revision",
}


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


def _validated_saved_result(
    saved: dict[str, Any], request: Mapping[str, Any], *, request_sha256: str,
    provisioning: bool,
) -> dict[str, Any]:
    expected_fields = PROVISION_RESULT_FIELDS if provisioning else RESULT_FIELDS
    if (set(saved) != expected_fields
        or saved.get("schema_version") != "slk.supervisor-admin-result/v1"
        or saved.get("status") != "SUPERVISOR_ADMIN_COMPLETED"
        or saved.get("run_id") != request["run_id"]
        or saved.get("supervisor_role_instance_id") != request["supervisor_role_instance_id"]
        or saved.get("operation") != request["operation"]
        or saved.get("request_sha256") != request_sha256
        or saved.get("operation_request_sha256") != request["operation_request_sha256"]
        or not isinstance(saved.get("state_result"), Mapping)):
        raise ValueError("Supervisor admin result conflicts with this request")
    if not provisioning:
        return saved
    sealed_result = saved.get("sealed_credential")
    destination = Path(str(request["credential_destination_path"]))
    if (saved.get("issued_role") != request["issued_role"]
        or saved.get("issued_role_instance_id") != request["issued_role_instance_id"]
        or not isinstance(sealed_result, Mapping) or set(sealed_result) != SEALED_RESULT_FIELDS
        or sealed_result.get("status") != "SEALED_ROLE_VERIFIED"
        or sealed_result.get("run_id") != request["run_id"]
        or sealed_result.get("role") != request["issued_role"]
        or sealed_result.get("role_instance_id") != request["issued_role_instance_id"]
        or Path(str(sealed_result.get("sealed_path"))).resolve() != destination.resolve()
        or not destination.is_file()
        or sealed_result.get("sealed_sha256") != _sha256(destination)):
        raise ValueError("saved issued sealed credential is missing or changed")
    return saved


def execute_sealed_supervisor_admin(
    request_path: Path | str, *, request_sha256: str,
) -> dict[str, Any]:
    request_path = Path(request_path).resolve()
    if _sha256(request_path) != request_sha256:
        raise ValueError("Supervisor admin request hash changed")
    request = _object(request_path, "Supervisor admin request")
    operation = request.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("Supervisor admin operation is not allowed")
    provisioning = operation in PROVISION_OPERATIONS
    worker_provisioning = (
        operation == "register-role" and request.get("issued_role") == "worker"
    )
    expected_fields = (
        WORKER_PROVISION_FIELDS if worker_provisioning
        else PROVISION_FIELDS if provisioning
        else FIELDS
    )
    if (set(request) != expected_fields
        or request.get("schema_version") != "slk.supervisor-admin/v1"):
        raise ValueError("Supervisor admin request is not closed")
    run_id = request.get("run_id")
    role_instance_id = request.get("supervisor_role_instance_id")
    revision = request.get("expected_runtime_revision")
    state_command = request.get("state_command")
    if (not isinstance(run_id, str) or not run_id.strip()
        or not isinstance(role_instance_id, str) or not role_instance_id.strip()
        or isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
        or not isinstance(state_command, list) or not state_command
        or not all(isinstance(item, str) and item for item in state_command)):
        raise ValueError("Supervisor admin identity or state command is invalid")
    sealed = Path(request["sealed_credential_path"])
    checker_sealed = (
        Path(request["sealed_checker_credential_path"])
        if worker_provisioning else None
    )
    operation_request = Path(request["operation_request_path"])
    result_path = Path(request["result_path"])
    input_paths = [sealed, operation_request, result_path]
    if checker_sealed is not None:
        input_paths.append(checker_sealed)
    if not all(path.is_absolute() for path in input_paths):
        raise ValueError("Supervisor admin paths must be absolute")
    if (not sealed.is_file() or not operation_request.is_file()
        or (checker_sealed is not None and not checker_sealed.is_file())):
        raise ValueError("Supervisor admin input is missing")
    if _sha256(operation_request) != request.get("operation_request_sha256"):
        raise ValueError("Supervisor operation request hash changed")
    operation_value = _object(operation_request, "Supervisor operation request")
    if operation_value.get("run_id") != run_id:
        raise ValueError("Supervisor operation changed Run identity")
    if provisioning:
        issued_role = request.get("issued_role")
        issued_role_instance_id = request.get("issued_role_instance_id")
        destination = Path(request["credential_destination_path"])
        identity = operation_value.get("identity")
        expected_role = "overwatcher" if operation == "bind-overwatcher" else issued_role
        if (issued_role != expected_role or issued_role not in {"checker", "worker", "overwatcher"}
            or not isinstance(issued_role_instance_id, str) or not issued_role_instance_id
            or not destination.is_absolute()
            or not isinstance(identity, Mapping) or identity.get("role") != issued_role
            or identity.get("role_instance_id") != issued_role_instance_id):
            raise ValueError("issued role identity or sealed destination is invalid")
        if worker_provisioning:
            checker_role_instance_id = request.get("checker_role_instance_id")
            if not isinstance(checker_role_instance_id, str) or not checker_role_instance_id.strip():
                raise ValueError("exact Checker authority is required for Worker registration")
    if result_path.exists():
        saved = _object(result_path, "Supervisor admin result")
        return _validated_saved_result(
            saved, request, request_sha256=request_sha256, provisioning=provisioning,
        )
    if provisioning and Path(request["credential_destination_path"]).exists():
        raise ValueError("issued role sealed destination exists without a matching result")

    secret = wc.unprotect_dpapi_hex(sealed)
    checker_secret = ""
    try:
        authenticated = wc._run_json_command(
            list(state_command),
            ["authenticate-role", "--run-id", run_id, "--role-instance-id", role_instance_id],
            credential=secret,
        )
        if (authenticated.get("status") != "authenticated"
            or authenticated.get("run_id") != run_id
            or authenticated.get("role") != "supervisor"
            or authenticated.get("role_instance_id") != role_instance_id
            or authenticated.get("runtime_revision") != revision):
            raise ValueError("saved credential does not authenticate the exact current Supervisor revision")
        operation_secret = secret
        if worker_provisioning:
            checker_secret = wc.unprotect_dpapi_hex(checker_sealed)
            checker_role_instance_id = request["checker_role_instance_id"]
            checker_authenticated = wc._run_json_command(
                list(state_command),
                ["authenticate-role", "--run-id", run_id,
                 "--role-instance-id", checker_role_instance_id],
                credential=checker_secret,
            )
            if (checker_authenticated.get("status") != "authenticated"
                or checker_authenticated.get("run_id") != run_id
                or checker_authenticated.get("role") != "checker"
                or checker_authenticated.get("role_instance_id") != checker_role_instance_id
                or checker_authenticated.get("runtime_revision") != revision):
                raise ValueError(
                    "saved credential does not authenticate the exact current Checker revision"
                )
            operation_secret = checker_secret
        state_result = wc._run_json_command(
            list(state_command), [operation, "--request", str(operation_request)],
            credential=operation_secret,
        )
    finally:
        checker_secret = ""
        secret = ""
    if state_result.get("status") not in OPERATIONS[operation] or state_result.get("run_id") != run_id:
        raise ValueError("Supervisor administration did not produce the allowed closed result")
    sealed_result = None
    if provisioning:
        secret_field = "overwatcher_write_credential" if operation == "bind-overwatcher" else "role_credential"
        issued_secret = state_result.get(secret_field)
        if not isinstance(issued_secret, str):
            raise ValueError("role registration did not return its one-time credential")
        try:
            sealed_result = wc.seal_role_credential(
                issued_secret, Path(request["credential_destination_path"]),
                run_id=run_id, role=request["issued_role"],
                role_instance_id=request["issued_role_instance_id"],
                state_command=list(state_command),
            )
        finally:
            issued_secret = ""
        state_result = {
            key: value for key, value in state_result.items()
            if "credential" not in str(key).lower()
        }
    elif any("credential" in str(key).lower() for key in state_result):
        raise ValueError("Supervisor administration returned credential material unexpectedly")
    receipt = {
        "schema_version": "slk.supervisor-admin-result/v1",
        "status": "SUPERVISOR_ADMIN_COMPLETED",
        "run_id": run_id,
        "supervisor_role_instance_id": role_instance_id,
        "operation": operation,
        "request_sha256": request_sha256,
        "operation_request_sha256": request["operation_request_sha256"],
        "state_result": state_result,
    }
    if sealed_result is not None:
        receipt.update({
            "issued_role": request["issued_role"],
            "issued_role_instance_id": request["issued_role_instance_id"],
            "sealed_credential": sealed_result,
        })
    wc._write_or_reuse_stable_request(result_path, receipt)
    return receipt
