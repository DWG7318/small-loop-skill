"""Closed consumer for saved Overwatcher authority.

Only the bound OW may consume its sealed credential, and only for the two
append-only observation writes needed by an active observation turn.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import worker_completion as wc


FIELDS = {
    "schema_version", "run_id", "overwatcher_role_instance_id", "expected_runtime_revision",
    "sealed_credential_path", "state_command", "operation", "operation_request_path",
    "operation_request_sha256", "result_path",
}
OPERATIONS = {
    "record-overwatch-cycle": {"overwatch_cycle_recorded"},
    "record-overwatcher-status": {"overwatcher_status_recorded"},
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


def execute_sealed_overwatcher_admin(
    request_path: Path | str, *, request_sha256: str,
) -> dict[str, Any]:
    request_path = Path(request_path).resolve()
    if _sha256(request_path) != request_sha256:
        raise ValueError("Overwatcher admin request hash changed")
    request = _object(request_path, "Overwatcher admin request")
    if set(request) != FIELDS or request.get("schema_version") != "slk.overwatcher-admin/v1":
        raise ValueError("Overwatcher admin request is not closed")
    operation = request.get("operation")
    if operation not in OPERATIONS:
        raise ValueError("Overwatcher admin operation is not allowed")
    run_id = request.get("run_id")
    role_instance_id = request.get("overwatcher_role_instance_id")
    revision = request.get("expected_runtime_revision")
    state_command = request.get("state_command")
    if (not isinstance(run_id, str) or not run_id.strip()
        or not isinstance(role_instance_id, str) or not role_instance_id.strip()
        or isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
        or not isinstance(state_command, list) or not state_command
        or not all(isinstance(item, str) and item for item in state_command)):
        raise ValueError("Overwatcher admin identity or state command is invalid")
    sealed = Path(request["sealed_credential_path"])
    operation_request = Path(request["operation_request_path"])
    result_path = Path(request["result_path"])
    if not all(path.is_absolute() for path in (sealed, operation_request, result_path)):
        raise ValueError("Overwatcher admin paths must be absolute")
    if not sealed.is_file() or not operation_request.is_file():
        raise ValueError("Overwatcher admin input is missing")
    if _sha256(operation_request) != request.get("operation_request_sha256"):
        raise ValueError("Overwatcher operation request hash changed")
    operation_value = _object(operation_request, "Overwatcher operation request")
    if (operation_value.get("run_id") != run_id
        or operation_value.get("role_instance_id") != role_instance_id):
        raise ValueError("Overwatcher operation changed role identity")
    if result_path.exists():
        saved = _object(result_path, "Overwatcher admin result")
        if (saved.get("request_sha256") != request_sha256
            or saved.get("operation_request_sha256") != request["operation_request_sha256"]):
            raise ValueError("Overwatcher admin result conflicts with this request")
        return saved

    secret = wc.unprotect_dpapi_hex(sealed)
    try:
        authenticated = wc._run_json_command(
            list(state_command),
            ["authenticate-role", "--run-id", run_id, "--role-instance-id", role_instance_id],
            credential=secret,
        )
        if (authenticated.get("status") != "authenticated"
            or authenticated.get("run_id") != run_id
            or authenticated.get("role") != "overwatcher"
            or authenticated.get("role_instance_id") != role_instance_id):
            raise ValueError("OVERWATCHER_AUTHENTICATION_FAILED: saved credential does not authenticate the current Overwatcher")
        if authenticated.get("runtime_revision") != revision:
            raise ValueError("OVERWATCHER_SNAPSHOT_STALE: refresh the snapshot and collect a new observation; do not replay the old cycle")
        state_result = wc._run_json_command(
            list(state_command), [operation, "--request", str(operation_request)],
            credential=secret, credential_scope="overwatcher",
        )
    finally:
        secret = ""
    if state_result.get("status") == "error":
        code, message = state_result.get("code"), state_result.get("message")
        sensitive = json.dumps({"code": code, "message": message}, ensure_ascii=False).lower()
        if (isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,95}", code)
            and isinstance(message, str) and message.strip() == message and 0 < len(message) <= 512
            and not any(term in sensitive for term in ("credential", "secret", "password", "api_key"))):
            raise ValueError(f"{code}: {message}")
    if (state_result.get("status") not in OPERATIONS[operation]
        or state_result.get("run_id") != run_id
        or any("credential" in str(key).lower() for key in state_result)):
        raise ValueError("Overwatcher administration did not produce the allowed closed result")
    receipt = {
        "schema_version": "slk.overwatcher-admin-result/v1",
        "status": "OVERWATCHER_ADMIN_COMPLETED",
        "run_id": run_id,
        "overwatcher_role_instance_id": role_instance_id,
        "operation": operation,
        "request_sha256": request_sha256,
        "operation_request_sha256": request["operation_request_sha256"],
        "state_result": state_result,
    }
    wc._write_or_reuse_stable_request(result_path, receipt)
    return receipt
