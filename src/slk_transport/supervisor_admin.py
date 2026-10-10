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
OVERWATCHER_CLOSE_FIELDS = FIELDS | {"sealed_overwatcher_credential_path"}
OPERATIONS = {
    "pause-run": {"pause_requested", "paused"},
    "resume-run": {"resumed", "pause_requested"},
    "start-d2": {"recorded"},
    "adopt-method-contract": {"applied", "idempotent_replay"},
    "revise-role-model": {"model_revised", "already_applied"},
    "resume-overwatcher-turn": {"overwatcher_turn_resumed"},
    "rebind-session": {"rebound"},
    "revise-plan": {"revised"},
    "register-role": {"registered"},
    "bind-overwatcher": {"overwatcher_bound"},
    "close-overwatcher": {"overwatcher_closed"},
    "close-run": {"recorded"},
    "close-role": {"closed", "already_closed"},
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
    overwatcher_closing = operation == "close-overwatcher"
    expected_fields = (
        WORKER_PROVISION_FIELDS if worker_provisioning
        else PROVISION_FIELDS if provisioning
        else OVERWATCHER_CLOSE_FIELDS if overwatcher_closing
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
    overwatcher_sealed = (
        Path(request["sealed_overwatcher_credential_path"])
        if overwatcher_closing else None
    )
    operation_request = Path(request["operation_request_path"])
    result_path = Path(request["result_path"])
    input_paths = [sealed, operation_request, result_path]
    if checker_sealed is not None:
        input_paths.append(checker_sealed)
    if overwatcher_sealed is not None:
        input_paths.append(overwatcher_sealed)
    if not all(path.is_absolute() for path in input_paths):
        raise ValueError("Supervisor admin paths must be absolute")
    if (not sealed.is_file() or not operation_request.is_file()
        or (checker_sealed is not None and not checker_sealed.is_file())
        or (overwatcher_sealed is not None and not overwatcher_sealed.is_file())):
        raise ValueError("Supervisor admin input is missing")
    if _sha256(operation_request) != request.get("operation_request_sha256"):
        raise ValueError("Supervisor operation request hash changed")
    operation_value = _object(operation_request, "Supervisor operation request")
    if operation_value.get("run_id") != run_id:
        raise ValueError("Supervisor operation changed Run identity")
    if operation == "close-run" and operation_value.get("event_type") != "RUN_CLOSED":
        raise ValueError("close-run requires the exact RUN_CLOSED event")
    if operation == "close-role" and operation_value.get("role") not in {"checker", "worker"}:
        raise ValueError("close-role may retire only the exact Checker or Worker")
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
    overwatcher_secret = ""
    try:
        authenticated = wc._run_json_command(
            list(state_command),
            ["authenticate-role", "--run-id", run_id, "--role-instance-id", role_instance_id],
            credential=secret,
        )
        if (authenticated.get("status") != "authenticated"
            or authenticated.get("run_id") != run_id
            or authenticated.get("role") != "supervisor"
            or authenticated.get("role_instance_id") != role_instance_id):
            raise ValueError("saved credential does not authenticate the exact current Supervisor revision")
        if authenticated.get("runtime_revision") != revision:
            if operation not in {"pause-run", "resume-run", "close-run"}:
                raise ValueError("saved credential does not authenticate the exact current Supervisor revision")
            from .role_host import RoleHost
            projection = wc._default_load_current_projection(run_id, list(state_command))
            saved_close = next((event for event in projection.get("events", [])
                                if event.get("event_id") == operation_value.get("event_id")), None)
            same_close = (operation == "close-run" and saved_close is not None
                and saved_close.get("event_type") == "RUN_CLOSED"
                and saved_close.get("author_role_instance_id") == role_instance_id
                and saved_close.get("occurred_at") == operation_value.get("occurred_at")
                and wc._event_details(saved_close) == operation_value.get("details")
                and all(saved_close.get(key) == operation_value.get(key) for key in ("go_id", "cell_id", "attempt", "corrects_event_id")))
            if not same_close and not RoleHost.lifecycle_retry_matches(projection, operation, operation_value,
                    request["operation_request_sha256"], revision, role_instance_id):
                raise ValueError("stale lifecycle revision does not belong to this exact operation")
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
        elif overwatcher_closing:
            overwatcher_secret = wc.unprotect_dpapi_hex(overwatcher_sealed)
            operation_secret = overwatcher_secret
        if operation in {"start-d2", "pause-run", "resume-run"}:
            from .role_host import RoleHost
            if operation == "start-d2" and set(operation_value) != {"run_id", "role_instance_id", "binding_path", "binding_sha256", "source_attempt_path"}:
                raise ValueError("D2 start request is not closed")
            binding_path = Path(operation_value["binding_path"])
            if (not binding_path.is_absolute()
                or _sha256(binding_path) != operation_value["binding_sha256"]):
                raise ValueError("D2 start binding is missing or changed")
            host = RoleHost(_object(binding_path, "D2 host binding"), operation_value["binding_sha256"])
            if (host.binding["run_id"] != run_id or host.state != state_command
                or operation_value["role_instance_id"] != role_instance_id
                or host.endpoint("supervisor")["role_instance_id"] != role_instance_id
                or Path(host.credential_path("supervisor")).resolve() != sealed.resolve()):
                raise ValueError("D2 start differs from the authenticated Supervisor host")
            if operation == "start-d2":
                source = Path(operation_value["source_attempt_path"])
                if not source.is_absolute(): raise ValueError("D2 source must be absolute")
                state_result = host.start_d2(source)
            else:
                state_result = host.run_lifecycle(operation, operation_value,
                    operation_sha256=request["operation_request_sha256"], expected_revision=revision)
        close_host = None
        close_binding = operation_value.get("details", {}).get("close_binding_path") if operation == "close-run" else None
        if close_binding is not None:
            from .role_host import RoleHost
            digest = operation_value["details"]["close_binding_sha256"]
            path = Path(close_binding)
            if not path.is_absolute() or _sha256(path) != digest: raise ValueError("close binding changed")
            close_host = RoleHost(_object(path, "close host binding"), digest)
            if (close_host.binding["run_id"] != run_id or close_host.state != state_command
                or close_host.endpoint("supervisor")["role_instance_id"] != role_instance_id
                or Path(close_host.credential_path("supervisor")).resolve() != sealed.resolve()
                or "temporal" not in close_host.binding):
                raise ValueError("close binding differs from the sealed Supervisor and original pair")
        state_operation = "write" if operation == "close-run" else operation
        state_arguments = [state_operation, "--request", str(operation_request)]
        if operation in {"start-d2", "pause-run", "resume-run"}:
            pass  # Original RoleHost wrote the single existing D2_STARTED event.
        elif overwatcher_closing:
            state_result = wc._run_json_command(
                list(state_command), state_arguments, credential=operation_secret,
                credential_scope="overwatcher",
            )
        else:
            state_result = wc._run_json_command(
                list(state_command), state_arguments, credential=operation_secret,
            )
        if close_host is not None and state_result.get("status") == "recorded":
            close_host.close_run_pair(operation_value, operation_request.parent)
    finally:
        overwatcher_secret = ""
        checker_secret = ""
        secret = ""
    command_meta = state_result.get("_slk_command")
    if isinstance(command_meta, Mapping) and command_meta.get("process_exit") != 0:
        error_code = state_result.get("error_code")
        message = state_result.get("message")
        safe_code = (
            isinstance(error_code, str) and 0 < len(error_code) <= 128
            and all(character.isupper() or character.isdigit() or character == "_" for character in error_code)
        )
        safe_message = (
            isinstance(message, str) and 0 < len(message) <= 512 and "slk_" not in message
        )
        if safe_code and safe_message:
            raise ValueError(f"Supervisor state command rejected: {error_code}: {message}")
        raise ValueError("Supervisor state command rejected without safe structured details")
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
        "status": "SUPERVISOR_ADMIN_PENDING" if state_result.get("status") == "pause_requested" else "SUPERVISOR_ADMIN_COMPLETED",
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
    if receipt["status"] == "SUPERVISOR_ADMIN_COMPLETED":
        wc._write_or_reuse_stable_request(result_path, receipt)
    return receipt
