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
from .native_activity import inspect_native_activity, utc_now


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


def _verify_cycle(cycle: dict[str, Any], run_id: str, state_command: list[str]) -> None:
    """Recheck original native evidence; an OW-written inspection is not execution proof."""
    try:
        now = utc_now()
        start, end = wc._timestamp(cycle["started_at"]), wc._timestamp(cycle["completed_at"])
        age = (wc._timestamp(now) - end).total_seconds()
        if end <= start or not -1 <= age <= cycle["cadence_seconds"]:
            raise ValueError("cycle must have real, current start and completion times")
        projection = wc._default_load_current_projection(run_id, state_command)
        snapshot = projection["runtime_snapshot"]
        for field in ("runtime_revision", "token_sequence", "token_holder_role_instance_id", "latest_message_id"):
            if cycle.get(field) != snapshot.get(field):
                raise ValueError("cycle differs from the current authoritative scope")
        references = cycle["evidence_refs"]
        objects = []
        for ref in references:
            path = Path(ref["path"])
            if not path.is_absolute() or _sha256(path) != ref["sha256"]:
                raise ValueError("cycle evidence is missing or changed")
            if path.stat().st_size <= 131072:
                try:
                    value = _object(path, "cycle evidence")
                except ValueError:
                    continue
                objects.append((path, value))
        inspections = [(p, v) for p, v in objects if v.get("schema_version") == wc.INSPECTION_SCHEMA]
        worker = any(r.get("role") == "worker" and r.get("role_instance_id") == snapshot.get("token_holder_role_instance_id")
                     for r in projection.get("roles", []))
        if not worker:
            return
        if len(inspections) != 1:
            raise ValueError("Worker-held TOKEN needs exactly one original completion inspection")
        reported = inspections[0][1]
        if not start <= wc._timestamp(reported["observed_at"]) <= end:
            raise ValueError("inspection time is outside the real cycle")
        events = [e for e in projection["events"] if e.get("event_type") == "TRANSPORT_STARTED"
                  and wc._event_details(e).get("message_id") == snapshot["latest_message_id"]]
        if len(events) != 1:
            raise ValueError("original Worker native start is not uniquely bound")
        proof = wc._event_details(events[0])
        starts = [p for p, v in objects if v.get("schema_version") == "slk.native-start/v2"
                  and _sha256(p) == proof.get("start_evidence_sha256")]
        if len(starts) != 1:
            raise ValueError("cycle must reference the exact authoritative Worker started.json")
        source = starts[0].parent
        for name in ("endpoint", "envelope"):
            if _sha256(source / (name + ".json")) != proof.get(name + "_sha256"):
                raise ValueError("Worker source identity changed")
        def current_native(path, **kwargs):
            kwargs.pop("observed_at", None)
            return inspect_native_activity(path, **kwargs)
        actual = wc.inspect_worker_completion(source, projection, observed_at=utc_now(),
                                              cadence_seconds=cycle["cadence_seconds"], native_inspector=current_native)
        if {k: v for k, v in actual.items() if k != "observed_at"} != {k: v for k, v in reported.items() if k != "observed_at"}:
            raise ValueError("reported Worker inspection differs from recollected native facts")
    except (KeyError, TypeError, OSError, ValueError) as exc:
        raise ValueError("OVERWATCHER_CYCLE_EVIDENCE_INVALID: recollect current scope, time and original native evidence") from exc


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
        if operation == "record-overwatch-cycle":
            _verify_cycle(operation_value, run_id, list(state_command))
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
