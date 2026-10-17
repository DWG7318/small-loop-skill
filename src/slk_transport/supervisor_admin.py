"""Closed consumer for Supervisor-orchestrated administrative authority.

The caller supplies only paths and hashes.  DPAPI plaintext exists in this process
and is never returned or persisted.  Worker registration consumes the exact saved
Checker authority after independently authenticating the current Supervisor.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
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
    "replace-overwatcher": {"overwatcher_replaced"},
    "close-overwatcher": {"overwatcher_closed"},
    "close-run": {"recorded"},
    "abandon-run": {"recorded"},
    "close-role": {"closed", "already_closed"},
    "record-closeout-summary": {"summary_recorded", "summary_replayed"},
}
PROVISION_OPERATIONS = {"register-role", "bind-overwatcher", "replace-overwatcher"}
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


def _recover_overwatcher_replacement(
    request: Mapping[str, Any], operation: Mapping[str, Any], *,
    supervisor_secret: str, current_revision: int,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Continue only the centrally committed original replacement, never rebind."""
    run_id, role_id = request["run_id"], request["issued_role_instance_id"]
    command = list(request["state_command"])
    projection = wc._default_load_current_projection(run_id, command)
    snapshot = projection.get("runtime_snapshot") or {}
    events = [event for event in projection.get("events", [])
              if event.get("event_id") == operation["event_id"]]
    roles = [role for role in projection.get("roles", [])
             if role.get("role") == "overwatcher" and role.get("lifecycle") == "active"]
    binding_revision = operation["expected_binding_revision"] + 1
    if (len(events) != 1 or len(roles) != 1
        or projection.get("summary", {}).get("run_id") != run_id
        or projection.get("summary", {}).get("closure_state") != "open"
        or snapshot.get("runtime_revision") != current_revision
        or snapshot.get("overwatcher_binding_revision") != binding_revision
        or snapshot.get("overwatcher_status") != "ACTIVE"
        or events[0].get("event_type") != "OVERWATCHER_REPLACED"
        or events[0].get("author_role_instance_id") != request["supervisor_role_instance_id"]
        or wc._event_details(events[0]) != {
            "request_sha256": request["operation_request_sha256"],
            "overwatcher_role_instance_id": role_id, "binding_revision": binding_revision,
        }
        or any(roles[0].get(key) != value for key, value in operation["replacement"].items())
        or roles[0].get("foreground_turn_id") != operation["foreground_turn_id"]
        or not any(endpoint.get("state") == "active" and all(
            endpoint.get(key) == operation["endpoint"].get(key)
            for key in ("endpoint_version", "transport_adapter", "host_identity", "session_id")
        ) for endpoint in roles[0].get("endpoints", []))):
        raise ValueError("stale replacement lacks the exact committed request and current new OW binding")
    result = {"status": "overwatcher_replaced", "run_id": run_id,
        "binding_revision": binding_revision, "overwatcher_role_instance_id": role_id}
    destination = Path(request["credential_destination_path"])
    if destination.exists():
        saved_secret = wc.unprotect_dpapi_hex(destination)
        try:
            authenticated = wc._run_json_command(command,
                ["authenticate-role", "--run-id", run_id, "--role-instance-id", role_id],
                credential=saved_secret)
        finally:
            saved_secret = ""
        if (authenticated.get("status") != "authenticated"
            or authenticated.get("run_id") != run_id or authenticated.get("role") != "overwatcher"
            or authenticated.get("role_instance_id") != role_id
            or authenticated.get("runtime_revision") != current_revision):
            raise ValueError("existing sealed credential does not authenticate the exact new OW")
        return result, {"status": "SEALED_ROLE_VERIFIED", "run_id": run_id,
            "role": "overwatcher", "role_instance_id": role_id, "sealed_path": str(destination),
            "sealed_sha256": _sha256(destination), "runtime_revision": current_revision}
    credential_id = roles[0].get("credential_id")
    if not isinstance(credential_id, str) or not credential_id.startswith("credential-"):
        raise ValueError("replacement recovery requires the current non-secret OW credential ID projection")
    # Reuse the exact-binding rotation command. Its CAS also protects a race with
    # another rotation; a lost rotation response can retry from the new current ID.
    rotation_id = "replacement-seal-" + hashlib.sha256(
        (request["operation_request_sha256"] + credential_id + ":" + str(current_revision)).encode("utf-8")).hexdigest()
    rotation_path = Path(request["result_path"]).with_name(rotation_id + ".json")
    wc._write_or_reuse_stable_request(rotation_path, {
        "rotation_id": rotation_id, "run_id": run_id, "expected_binding_revision": binding_revision,
        "expected_runtime_revision": current_revision, "role_instance_id": role_id,
        "session_id": operation["replacement"]["session_id"],
        "foreground_turn_id": operation["foreground_turn_id"],
        "expected_overwatcher_credential_id": credential_id,
        "evidence": {"path": request["operation_request_path"],
                     "sha256": request["operation_request_sha256"]},
        "reason": "recover one-time credential delivery for the exact committed replacement",
        "occurred_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
    rotated = wc._run_json_command(command,
        ["rotate-overwatcher-credential", "--request", str(rotation_path)], credential=supervisor_secret)
    if (rotated.get("status") != "overwatcher_credential_rotated" or rotated.get("run_id") != run_id
        or rotated.get("overwatcher_role_instance_id") != role_id
        or rotated.get("binding_revision") != binding_revision
        or rotated.get("_slk_command", {}).get("process_exit", 0) != 0):
        raise ValueError("exact replacement credential recovery did not succeed")
    return {**rotated, **result}, None


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
    replacing_overwatcher = operation == "replace-overwatcher"
    worker_provisioning = (
        operation == "register-role" and request.get("issued_role") == "worker"
    )
    overwatcher_closing = operation == "close-overwatcher"
    overwatcher_authority = overwatcher_closing and "sealed_overwatcher_credential_path" in request
    expected_fields = (
        WORKER_PROVISION_FIELDS if worker_provisioning
        else PROVISION_FIELDS if provisioning
        else OVERWATCHER_CLOSE_FIELDS if overwatcher_authority
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
        if overwatcher_authority else None
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
    if overwatcher_closing and bool(operation_value.get("final_cycle_id")) != overwatcher_authority:
        raise ValueError("final cycle close uses OW authority; ended-child close uses Supervisor authority")
    if operation == "close-run" and operation_value.get("event_type") != "RUN_CLOSED":
        raise ValueError("close-run requires the exact RUN_CLOSED event")
    if operation == "abandon-run" and operation_value.get("event_type") != "RUN_ABANDONED":
        raise ValueError("abandon-run requires the exact RUN_ABANDONED event")
    if operation == "close-role" and operation_value.get("role") not in {"checker", "worker"}:
        raise ValueError("close-role may retire only the exact Checker or Worker")
    if provisioning:
        issued_role = request.get("issued_role")
        issued_role_instance_id = request.get("issued_role_instance_id")
        destination = Path(request["credential_destination_path"])
        identity = operation_value.get("replacement" if replacing_overwatcher else "identity")
        expected_role = "overwatcher" if operation in {"bind-overwatcher", "replace-overwatcher"} else issued_role
        if (issued_role != expected_role or issued_role not in {"checker", "worker", "overwatcher"}
            or not isinstance(issued_role_instance_id, str) or not issued_role_instance_id
            or not destination.is_absolute()
            or not isinstance(identity, Mapping) or identity.get("role") != issued_role
            or identity.get("role_instance_id") != issued_role_instance_id):
            raise ValueError("issued role identity or sealed destination is invalid")
        if replacing_overwatcher and (
            operation_value.get("expected_runtime_revision") != revision
            or not wc._positive_integer(operation_value.get("expected_binding_revision"))
        ):
            raise ValueError("replacement must name the exact original runtime and binding revision")
        if worker_provisioning:
            checker_role_instance_id = request.get("checker_role_instance_id")
            if not isinstance(checker_role_instance_id, str) or not checker_role_instance_id.strip():
                raise ValueError("exact Checker authority is required for Worker registration")
    if result_path.exists():
        saved = _object(result_path, "Supervisor admin result")
        return _validated_saved_result(
            saved, request, request_sha256=request_sha256, provisioning=provisioning,
        )
    if provisioning and not replacing_overwatcher and Path(request["credential_destination_path"]).exists():
        raise ValueError("issued role sealed destination exists without a matching result")

    secret = wc.unprotect_dpapi_hex(sealed)
    checker_secret = ""
    overwatcher_secret = ""
    recovered_result = None
    recovered_sealed_result = None
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
            if replacing_overwatcher:
                recovered_result, recovered_sealed_result = _recover_overwatcher_replacement(
                    request, operation_value, supervisor_secret=secret,
                    current_revision=authenticated.get("runtime_revision"))
            elif operation not in {"pause-run", "resume-run", "close-run", "abandon-run"}:
                raise ValueError("saved credential does not authenticate the exact current Supervisor revision")
        if authenticated.get("runtime_revision") != revision and not replacing_overwatcher:
            from .role_host import RoleHost
            projection = wc._default_load_current_projection(run_id, list(state_command))
            saved_terminal = next((event for event in projection.get("events", [])
                                if event.get("event_id") == operation_value.get("event_id")), None)
            terminal_kind = {"close-run": "RUN_CLOSED", "abandon-run": "RUN_ABANDONED"}.get(operation)
            same_terminal = (terminal_kind is not None and saved_terminal is not None
                and saved_terminal.get("event_type") == terminal_kind
                and saved_terminal.get("author_role_instance_id") == role_instance_id
                and saved_terminal.get("occurred_at") == operation_value.get("occurred_at")
                and wc._event_details(saved_terminal) == operation_value.get("details")
                and all(saved_terminal.get(key) == operation_value.get(key) for key in ("go_id", "cell_id", "attempt", "corrects_event_id")))
            if not same_terminal and not RoleHost.lifecycle_retry_matches(projection, operation, operation_value,
                    request["operation_request_sha256"], revision, role_instance_id):
                raise ValueError("stale lifecycle revision does not belong to this exact operation")
        if replacing_overwatcher and recovered_result is None and destination.exists():
            raise ValueError("issued role sealed destination exists without a matching replacement")
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
        elif overwatcher_authority:
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
        state_operation = "write" if operation in {"close-run", "abandon-run"} else operation
        state_arguments = [state_operation, "--request", str(operation_request)]
        if recovered_result is not None:
            state_result = recovered_result
        elif operation in {"start-d2", "pause-run", "resume-run"}:
            pass  # Original RoleHost wrote the single existing D2_STARTED event.
        elif overwatcher_authority:
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
        error_code = state_result.get("error_code", state_result.get("code"))
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
    sealed_result = recovered_sealed_result
    if provisioning:
        secret_field = "overwatcher_write_credential" if operation in {"bind-overwatcher", "replace-overwatcher"} else "role_credential"
        issued_secret = state_result.pop(secret_field, None)
        if sealed_result is None and not isinstance(issued_secret, str):
            raise ValueError("role registration did not return its one-time credential")
        try:
            if replacing_overwatcher and (
                state_result.get("overwatcher_role_instance_id") != request["issued_role_instance_id"]
                or state_result.get("binding_revision") != operation_value["expected_binding_revision"] + 1
            ):
                raise ValueError("replacement returned a different new OW identity")
            if sealed_result is None:
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
