"""Bounded Worker-completion continuation and read-only handoff inspection."""

from __future__ import annotations

from . import SUPPORTED_METHOD_VERSIONS

import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
import ctypes
from ctypes import wintypes
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .adapters.base import AdapterError
from .adapters.ocrv import OcrvAdapter, VERDICT_EXIT_CODES
from .contracts import (
    ENVELOPE_SCHEMA,
    SHA256,
    ContractError,
    DeliveryResult,
    Endpoint,
    Envelope,
    canonical_json_sha256,
    parse_delivery,
)
from .native_activity import NativeActivityError, inspect_native_activity, validate_native_start
from .task_file import TaskFileError, verify_task_file


INSPECTION_SCHEMA = "slk.worker-completion-inspection/v1"
CONTINUATION_SCHEMA = "slk.worker-continuation/v1"
CONTINUATION_SCHEMA_V2 = "slk.worker-continuation/v2"
CONTINUATION_SCHEMA_V3 = "slk.worker-continuation/v3"
CHECKER_RECOVERY_SCHEMA = "slk.ocrv-worker-recovery-request/v1"
CHECKER_RECOVERY_RESULT_SCHEMA = "slk.ocrv-worker-recovery-result/v1"
COMMITTED_TERMINAL_SCHEMA = "slk.ocrv-committed-terminal-request/v1"
COMMITTED_TERMINAL_RESULT_SCHEMA = "slk.ocrv-committed-terminal-result/v1"
INCOMPLETE_RESUME_SCHEMA = "slk.ocrv-incomplete-checker-resume-request/v1"
TERMINAL_BUDGET_RESUME_SCHEMA = "slk.ocrv-terminal-budget-resume-request/v1"
TERMINAL_BUDGET_RESUME_RESULT_SCHEMA = "slk.ocrv-terminal-budget-resume-result/v1"
TERMINAL_BUDGET_RESUME_RESULT_FIELDS = frozenset(
    {
        "schema_version", "method_version", "status", "run_id", "cell_id", "attempt",
        "candidate_message_id", "checker_role_instance_id", "checker_endpoint_version",
        "recovery_invocation_id", "request_sha256", "capacity_revision_sha256",
        "ocrv_transition_sha256", "runtime_config_binding_sha256",
        "source_d1_incomplete_event_id", "d1_verdict", "d1_event_type",
        "corrected_d1_event_id", "suffix_mode", "suffix_request_path",
        "suffix_result_path", "suffix_status", "parent_session_id", "child_session_id",
        "native_attempt_path", "native_result_path",
    }
)
TERMINAL_BUDGET_FRESH_RESULT_FIELDS = frozenset(
    {
        "schema_version", "method_version", "status", "run_id", "cell_id", "attempt",
        "candidate_message_id", "checker_role_instance_id", "checker_endpoint_version",
        "recovery_invocation_id", "request_sha256", "capacity_revision_sha256",
        "source_rejection_sha256", "compatibility_authorization_sha256",
        "source_d1_incomplete_event_id", "d1_verdict", "d1_event_type",
        "corrected_d1_event_id", "suffix_mode", "suffix_request_path",
        "suffix_result_path", "suffix_status", "parent_session_id", "child_session_id",
        "native_attempt_path", "native_result_path",
    }
)
COMMITTED_TERMINAL_RESULT_FIELDS = frozenset(
    {
        "schema_version", "method_version", "status", "run_id", "cell_id", "attempt",
        "candidate_message_id", "checker_role_instance_id", "checker_endpoint_version",
        "checker_authenticated", "authorized_existing_terminal", "recovery_invocation_id",
        "request_sha256", "runtime_revision", "token_sequence", "native_attempt_path",
        "d1_verdict", "d1_event_type", "native_result_path",
    }
)
_NAMESPACE = uuid.UUID("23c8316f-29fe-4f2f-b5c5-90ba4e7b1224")
_LEGACY_WORKER_START_FIELDS = frozenset(
    {"instance_id", "message_id", "run_id", "session_id", "status", "task_sha256"}
)
INVALID_SUPPLEMENT_RESULT_CONTRACT = {
    "worker_result_fields": [
        "schema_version",
        "message_id",
        "run_id",
        "role_instance_id",
        "status",
        "candidate",
        "next_payload",
    ],
    "next_payload_fields": [
        "attempt",
        "candidate_repository",
        "cell_id",
        "changed_paths",
        "d0",
        "suffix_blocker",
        "unproved",
    ],
    "d0_fields": [
        "baseline_commit",
        "branch",
        "candidate_commit",
        "changed_paths",
        "evidence_files",
        "focused_command",
        "frozen_command",
        "frozen_command_result",
        "green",
        "red",
        "unproved",
    ],
}
CONTINUATION_FIELDS = {
    "schema_version",
    "method_version",
    "run_id",
    "go_id",
    "cell_id",
    "attempt",
    "plan_revision",
    "runtime_revision",
    "source_message_id",
    "source_attempt_root",
    "continuation_result_path",
    "source_endpoint_sha256",
    "source_envelope_sha256",
    "source_runtime_projection_sha256",
    "source_runtime_snapshot",
    "recovery_mode",
    "worker_result_path",
    "worker_result_sha256",
    "source_terminal_sha256",
    "source_task_sha256",
    "source_started_sha256",
    "source_invalid_result_sha256",
    "source_candidate",
    "source_candidate_parent",
    "source_repository",
    "source_changed_paths",
    "supplement_result_contract",
    "worker_role_instance_id",
    "worker_instance_id",
    "worker_session_id",
    "checker_endpoint",
    "credential_path",
    "state_command",
    "transport_command",
    "token_sequence",
    "checker_token_already_committed",
    "occurred_at",
}
CONTINUATION_V2_FIELDS = CONTINUATION_FIELDS | {"temporal"}
PRE_D0_CONTINUATION_FIELDS = CONTINUATION_FIELDS | {
    "source_blocked_result_sha256",
    "source_project_id",
    "environment_adjustment_path",
    "environment_adjustment_sha256",
}
PRE_D0_ENVIRONMENT_FIELDS = frozenset(
    {
        "schema_version",
        "recovery_kind",
        "source_message_id",
        "candidate_repository",
        "candidate_commit",
        "tool_path",
        "tool_sha256",
        "state_config_path",
        "state_config_sha256",
        "d0_environment",
        "d0_command",
    }
)
TEMPORAL_BINDING_FIELDS = {
    "client_command", "workflow_identity_path", "workflow_identity_sha256", "attempt_root",
}
TEMPORAL_IDENTITY_FIELDS = {
    "schema_version", "run_id", "address", "task_queue", "start_workflow_id",
    "start_run_id", "run_workflow_id", "run_run_id", "startup_fingerprint",
}
TEMPORAL_UPDATE_RESULT_FIELDS = {
    "schema_version", "status", "operation", "run_id", "operation_id", "message_id",
}
TEMPORAL_DELIVERY_REQUEST_FIELDS = {
    "operation_id", "run_id", "cell_id", "attempt", "message_id",
    "sender_role_instance_id", "receiver_role_instance_id", "payload_sha256",
    "source_runtime_revision",
}


class CompletionError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def resolve_authoritative_token_boundary(
    projection: Mapping[str, Any], *, run_id: str, plan_revision: int,
) -> dict[str, Any]:
    """Resolve one current TOKEN boundary without rewriting a historical NULL snapshot."""
    try:
        summary = projection["summary"]
        snapshot = projection["runtime_snapshot"]
        if not isinstance(summary, Mapping) or not isinstance(snapshot, Mapping):
            raise ValueError("projection is incomplete")
        summary_revision = summary.get("current_plan_revision", summary.get("plan_revision"))
        sequence = snapshot.get("token_sequence")
        holder = snapshot.get("token_holder_role_instance_id")
        message_id = snapshot.get("latest_message_id")
        method_version = snapshot.get("method_version")
        if (
            summary.get("run_id") != run_id
            or projection.get("run_id", run_id) != run_id
            or method_version not in SUPPORTED_METHOD_VERSIONS
            or summary.get("slk_version") != method_version
            or summary_revision != plan_revision
            or snapshot.get("run_id", run_id) != run_id
            or snapshot.get("plan_revision") != plan_revision
            or isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1
            or not isinstance(holder, str) or not holder
        ):
            raise ValueError("projection scope changed")
        history = projection.get("token_history")
        if isinstance(message_id, str) and message_id:
            if isinstance(history, list):
                token_rows = [row for row in history if isinstance(row, Mapping)
                    and row.get("event_type") == "TOKEN_HANDED_OFF"]
                same_sequence = [row for row in token_rows if row.get("token_sequence") == sequence]
                if token_rows and (len(same_sequence) != 1 or token_rows[-1] is not same_sequence[0]
                    or same_sequence[0].get("message_id") != message_id
                    or same_sequence[0].get("to_role_instance_id") != holder):
                    raise ValueError("snapshot conflicts with TOKEN history")
            return {"message_id": message_id, "token_sequence": sequence, "holder_role_instance_id": holder,
                    "source": "RUNTIME_SNAPSHOT", "go_id": None, "cell_id": None}
        if message_id is not None or sequence < 1 or not isinstance(history, list):
            raise ValueError("snapshot message identity is invalid")
        token_rows = [row for row in history if isinstance(row, Mapping)
            and row.get("event_type") == "TOKEN_HANDED_OFF"]
        created_rows = [row for row in history if isinstance(row, Mapping)
            and row.get("event_type") == "TOKEN_CREATED"]
        if not token_rows and sequence == 1 and len(created_rows) == 1:
            created = created_rows[0]
            supervisors = [row for row in projection.get("roles", []) if isinstance(row, Mapping)
                and row.get("role") == "supervisor" and row.get("lifecycle", "active") == "active"]
            if (len(supervisors) != 1 or supervisors[0].get("role_instance_id") != holder
                or created.get("token_sequence") != 1
                or created.get("to_role_instance_id") != holder
                or created.get("message_id") is not None or created.get("from_role_instance_id") is not None
                or created.get("go_id") is not None or created.get("cell_id") is not None
                or created.get("run_id", run_id) != run_id
                or created.get("plan_revision", plan_revision) != plan_revision):
                raise ValueError("initial TOKEN identity conflicts with snapshot")
            return {"message_id": None, "token_sequence": 1, "holder_role_instance_id": holder,
                    "source": "TOKEN_CREATED", "go_id": None, "cell_id": None}
        matches = [row for row in token_rows if row.get("token_sequence") == sequence]
        if len(matches) != 1 or not token_rows or token_rows[-1] is not matches[0]:
            raise ValueError("current TOKEN is missing or ambiguous")
        token = matches[0]
        for field in ("message_id", "go_id", "cell_id", "from_role_instance_id", "to_role_instance_id"):
            if not isinstance(token.get(field), str) or not token[field]:
                raise ValueError("TOKEN identity is incomplete")
        if (token["to_role_instance_id"] != holder
            or token.get("run_id", run_id) != run_id
            or token.get("plan_revision", plan_revision) != plan_revision):
            raise ValueError("TOKEN scope conflicts with snapshot")
        starts = []
        for event in projection.get("events", []):
            if not isinstance(event, Mapping) or event.get("event_type") != "TRANSPORT_STARTED":
                continue
            try:
                details = json.loads(event.get("details_json", ""))
            except (TypeError, json.JSONDecodeError):
                continue
            if (isinstance(details, Mapping) and details.get("message_id") == token["message_id"]
                and event.get("go_id") == token["go_id"] and event.get("cell_id") == token["cell_id"]):
                starts.append((event, details))
        if len(starts) != 1:
            raise ValueError("TOKEN native start is missing or ambiguous")
        event, details = starts[0]
        if (event.get("corrects_event_id") is not None
            or event.get("author_role_instance_id") != token["from_role_instance_id"]
            or event.get("plan_revision", plan_revision) != plan_revision
            or any(not isinstance(details.get(field), str) or not SHA256.fullmatch(details[field])
                   for field in ("endpoint_sha256", "envelope_sha256", "start_evidence_sha256"))):
            raise ValueError("TOKEN native start conflicts with authoritative identity")
        return {"message_id": token["message_id"], "token_sequence": sequence,
                "holder_role_instance_id": holder, "source": "TOKEN_HISTORY",
                "go_id": token["go_id"], "cell_id": token["cell_id"]}
    except (KeyError, TypeError, ValueError) as exc:
        raise CompletionError("AUTHORITATIVE_TOKEN_BOUNDARY_INVALID",
                              "current TOKEN boundary is missing, ambiguous, or contradictory") from exc


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", f"{label} must be an object")
    return value

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise CompletionError("WORKER_COMPLETION_TIME_INVALID", "observed_at must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise CompletionError("WORKER_COMPLETION_TIME_INVALID", "observed_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def _file_timestamp(path: Path) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError as exc:
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "Worker terminal evidence timestamp is unavailable",
        ) from exc


def _stable_id(source_message_id: str, suffix: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{source_message_id}:{suffix}"))


def validate_temporal_binding(value: object, run_id: str) -> dict[str, Any]:
    """Validate one hash-bound client for the already-running Workflow pair."""

    try:
        if not isinstance(value, Mapping) or set(value) != TEMPORAL_BINDING_FIELDS:
            raise ValueError("field set")
        command = value["client_command"]
        if (not isinstance(command, list) or len(command) != 3
            or not all(isinstance(item, str) and item for item in command)
            or not Path(command[0]).is_absolute() or not Path(command[0]).is_file()
            or command[1:] != ["-m", "slk_temporal.delivery_client"]):
            raise ValueError("client command")
        identity_path = Path(str(value["workflow_identity_path"]))
        identity_sha256 = str(value["workflow_identity_sha256"])
        if (not identity_path.is_absolute() or not identity_path.is_file()
            or not re.fullmatch(r"[0-9a-f]{64}", identity_sha256)
            or _sha256(identity_path) != identity_sha256):
            raise ValueError("identity proof")
        identity = _read_object(identity_path, "Temporal workflow identity")
        if (set(identity) != TEMPORAL_IDENTITY_FIELDS
            or identity.get("schema_version") != "slk.temporal-workflow-identity/v1"
            or identity.get("run_id") != run_id
            or not all(isinstance(identity.get(field), str) and identity[field].strip() == identity[field]
                       for field in TEMPORAL_IDENTITY_FIELDS - {"schema_version"})
            or not re.fullmatch(r"[0-9a-f]{64}", str(identity.get("startup_fingerprint", "")))):
            raise ValueError("workflow identity")
        attempt_root = Path(str(value["attempt_root"]))
        if not attempt_root.is_absolute() or not attempt_root.is_dir():
            raise ValueError("attempt root")
        return {
            "client_command": list(command),
            "workflow_identity_path": str(identity_path.resolve()),
            "workflow_identity_sha256": identity_sha256,
            "attempt_root": str(attempt_root.resolve()),
        }
    except (OSError, TypeError, KeyError, ValueError, CompletionError) as exc:
        raise CompletionError(
            "TEMPORAL_BINDING_INVALID",
            "Temporal delivery requires the exact existing Workflow identity, SDK client, and canonical ATTEMPT_ROOT",
        ) from exc


def _validate_temporal_result(value: Mapping[str, Any], *, operation: str, run_id: str,
                              operation_id: str, message_id: str) -> None:
    command = value.get("_slk_command")
    core = {key: item for key, item in value.items() if key != "_slk_command"}
    expected_operation = "request_delivery" if operation == "request-delivery" else "native_started"
    allowed = ({"DELIVERY_REQUESTED", "RECOVERY_REQUIRED", "BLOCKED", "DELIVERY_ACKNOWLEDGED"}
               if operation == "request-delivery" else {"DELIVERY_ACKNOWLEDGED"})
    if (set(core) != TEMPORAL_UPDATE_RESULT_FIELDS
        or core.get("schema_version") != "slk.temporal-delivery-update-result/v1"
        or core.get("status") not in allowed or core.get("operation") != expected_operation
        or core.get("run_id") != run_id or core.get("operation_id") != operation_id
        or core.get("message_id") != message_id
        or (command is not None and (not isinstance(command, Mapping) or command.get("process_exit") != 0))):
        raise CompletionError("TEMPORAL_DELIVERY_UPDATE_INVALID", "Temporal update did not bind the exact handoff")


def _temporal_result_path(request_path: Path, status: str) -> Path:
    suffix = status.lower().replace("_", "-")
    return request_path.with_name(f"{request_path.stem}.{suffix}.result.json")


def _temporal_ack_recorded(
    evidence_root: Path, *, operation_id: str, run_id: str, message_id: str,
) -> bool:
    candidates = (
        (evidence_root / f"temporal-native-started-{operation_id}.delivery-acknowledged.result.json", "native-started"),
        (evidence_root / f"temporal-request-{operation_id}.delivery-acknowledged.result.json", "request-delivery"),
    )
    found = False
    for path, operation in candidates:
        if not path.is_file():
            continue
        value = _read_object(path, "Temporal acknowledgement result")
        _validate_temporal_result(
            value, operation=operation, run_id=run_id,
            operation_id=operation_id, message_id=message_id,
        )
        if value.get("status") != "DELIVERY_ACKNOWLEDGED":
            raise CompletionError(
                "TEMPORAL_DELIVERY_UPDATE_INVALID",
                "saved Temporal result is not an acknowledgement",
            )
        found = True
    return found


def acknowledge_temporal_delivery(
    temporal_raw: object,
    evidence_root: Path,
    endpoint_raw: Mapping[str, Any],
    envelope_raw: Mapping[str, Any],
    *,
    request_path: Path,
    request_sha256: str,
    attempt: int,
    required_attempt_root: Path | None = None,
) -> Path:
    """ACK one previously requested exact operation without requesting delivery again."""

    endpoint = Endpoint.from_dict(endpoint_raw)
    envelope = Envelope.from_dict(envelope_raw)
    temporal = validate_temporal_binding(temporal_raw, envelope.run_id)
    attempt_root = Path(temporal["attempt_root"])
    if required_attempt_root is not None and attempt_root.resolve() != required_attempt_root.resolve():
        raise CompletionError("TEMPORAL_ATTEMPT_ROOT_MISMATCH", "handoff changed the adapter's canonical ATTEMPT_ROOT")
    request_path = request_path.resolve()
    if (not request_path.is_file() or not SHA256.fullmatch(request_sha256)
        or _sha256(request_path) != request_sha256):
        raise CompletionError("TEMPORAL_DELIVERY_REQUEST_INVALID", "original Temporal request hash changed")
    request = _read_object(request_path, "original Temporal delivery request")
    operation_id = request.get("operation_id")
    if (set(request) != TEMPORAL_DELIVERY_REQUEST_FIELDS
        or not isinstance(operation_id, str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", operation_id)
        or request.get("run_id") != envelope.run_id
        or request.get("cell_id") != envelope.cell_id
        or request.get("attempt") != attempt
        or request.get("message_id") != envelope.message_id
        or request.get("sender_role_instance_id") != envelope.sender_role_instance_id
        or request.get("receiver_role_instance_id") != envelope.receiver_role_instance_id
        or request.get("payload_sha256") != envelope.payload_sha256
        or isinstance(request.get("source_runtime_revision"), bool)
        or not isinstance(request.get("source_runtime_revision"), int)
        or request["source_runtime_revision"] < 1):
        raise CompletionError("TEMPORAL_DELIVERY_REQUEST_INVALID", "original Temporal request changed handoff identity")
    native = attempt_root / envelope.run_id / envelope.message_id
    from .desktop_current_turn import resolve_delivery_start
    started_path, _ = resolve_delivery_start(native, endpoint_raw, envelope_raw)
    if (_read_object(native / "endpoint.json", "target endpoint") != dict(endpoint_raw)
        or _read_object(native / "envelope.json", "target envelope") != dict(envelope_raw)):
        raise CompletionError("TEMPORAL_NATIVE_START_UNPROVED", "native start changed the exact delivery")
    evidence_root.mkdir(parents=True, exist_ok=True)
    if _temporal_ack_recorded(
        evidence_root, operation_id=operation_id,
        run_id=envelope.run_id, message_id=envelope.message_id,
    ):
        return native
    acknowledgement = {
        "operation_id": operation_id,
        "message_id": envelope.message_id,
        "receiver_role_instance_id": envelope.receiver_role_instance_id,
        "payload_sha256": envelope.payload_sha256,
        "started_receipt_sha256": _sha256(started_path),
    }
    acknowledgement_path = _write_or_reuse_stable_request(
        evidence_root / f"temporal-native-started-{operation_id}.json", acknowledgement)
    common = [
        "--identity", temporal["workflow_identity_path"],
        "--identity-sha256", temporal["workflow_identity_sha256"],
    ]
    acknowledged = _run_json_command(
        temporal["client_command"],
        ["native-started", *common, "--request", str(acknowledgement_path),
         "--request-sha256", _sha256(acknowledgement_path)],
        credential=None,
    )
    _validate_temporal_result(
        acknowledged, operation="native-started", run_id=envelope.run_id,
        operation_id=operation_id, message_id=envelope.message_id,
    )
    _write_or_reuse_stable_request(
        _temporal_result_path(acknowledgement_path, str(acknowledged["status"])),
        {key: value for key, value in acknowledged.items() if key != "_slk_command"},
    )
    return native


def start_temporal_delivery(
    temporal_raw: object,
    evidence_root: Path,
    endpoint_raw: Mapping[str, Any],
    envelope_raw: Mapping[str, Any],
    *,
    attempt: int,
    source_runtime_revision: int,
    required_attempt_root: Path | None = None,
) -> Path:
    """Let the original role request one Temporal-owned native start and ACK it."""

    endpoint = Endpoint.from_dict(endpoint_raw)
    envelope = Envelope.from_dict(envelope_raw)
    temporal = validate_temporal_binding(temporal_raw, envelope.run_id)
    attempt_root = Path(temporal["attempt_root"])
    if required_attempt_root is not None and attempt_root.resolve() != required_attempt_root.resolve():
        raise CompletionError("TEMPORAL_ATTEMPT_ROOT_MISMATCH", "handoff changed the adapter's canonical ATTEMPT_ROOT")
    if (isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1
        or isinstance(source_runtime_revision, bool) or not isinstance(source_runtime_revision, int)
        or source_runtime_revision < 1):
        raise CompletionError("TEMPORAL_DELIVERY_REQUEST_INVALID", "attempt and runtime revision must be positive")
    native = attempt_root / envelope.run_id / envelope.message_id
    native.mkdir(parents=True, exist_ok=True)
    _write_or_reuse_stable_request(native / "endpoint.json", endpoint_raw)
    _write_or_reuse_stable_request(native / "envelope.json", envelope_raw)
    evidence_root.mkdir(parents=True, exist_ok=True)
    operation_id = _stable_id(envelope.message_id, "temporal-delivery")
    request = {
        "operation_id": operation_id,
        "run_id": envelope.run_id,
        "cell_id": envelope.cell_id,
        "attempt": attempt,
        "message_id": envelope.message_id,
        "sender_role_instance_id": envelope.sender_role_instance_id,
        "receiver_role_instance_id": envelope.receiver_role_instance_id,
        "payload_sha256": envelope.payload_sha256,
        "source_runtime_revision": source_runtime_revision,
    }
    request_path = _write_or_reuse_stable_request(
        evidence_root / f"temporal-request-{operation_id}.json", request)
    common = [
        "--identity", temporal["workflow_identity_path"],
        "--identity-sha256", temporal["workflow_identity_sha256"],
    ]
    requested = _run_json_command(
        temporal["client_command"],
        ["request-delivery", *common, "--request", str(request_path),
         "--request-sha256", _sha256(request_path)],
        credential=None,
    )
    _validate_temporal_result(requested, operation="request-delivery", run_id=envelope.run_id,
                              operation_id=operation_id, message_id=envelope.message_id)
    _write_or_reuse_stable_request(
        _temporal_result_path(request_path, str(requested["status"])),
        {key: value for key, value in requested.items() if key != "_slk_command"},
    )
    if requested["status"] in {"BLOCKED", "RECOVERY_REQUIRED"}:
        raise CompletionError(
            f"TEMPORAL_DELIVERY_{requested['status']}",
            f"Temporal request returned {requested['status']}",
        )
    from .desktop_current_turn import resolve_delivery_start
    started_path, started = resolve_delivery_start(native, endpoint_raw, envelope_raw, missing_ok=True)
    failed_path = native / "failed.json"
    deadline = time.monotonic() + 300
    while started is None and time.monotonic() < deadline:
        if failed_path.is_file():
            break
        time.sleep(0.05)
        started_path, started = resolve_delivery_start(native, endpoint_raw, envelope_raw, missing_ok=True)
    try:
        started_path, _ = resolve_delivery_start(native, endpoint_raw, envelope_raw)
    except NativeActivityError as exc:
        raise CompletionError("TEMPORAL_NATIVE_START_UNPROVED", "Temporal delivery produced no exact native v2 start") from exc
    if requested["status"] == "DELIVERY_ACKNOWLEDGED":
        return native
    acknowledgement = {
        "operation_id": operation_id,
        "message_id": envelope.message_id,
        "receiver_role_instance_id": envelope.receiver_role_instance_id,
        "payload_sha256": envelope.payload_sha256,
        "started_receipt_sha256": _sha256(started_path),
    }
    acknowledgement_path = _write_or_reuse_stable_request(
        evidence_root / f"temporal-native-started-{operation_id}.json", acknowledgement)
    acknowledged = _run_json_command(
        temporal["client_command"],
        ["native-started", *common, "--request", str(acknowledgement_path),
         "--request-sha256", _sha256(acknowledgement_path)],
        credential=None,
    )
    _validate_temporal_result(acknowledged, operation="native-started", run_id=envelope.run_id,
                              operation_id=operation_id, message_id=envelope.message_id)
    _write_or_reuse_stable_request(
        _temporal_result_path(acknowledgement_path, str(acknowledged["status"])),
        {key: value for key, value in acknowledged.items() if key != "_slk_command"},
    )
    return native


def _write_or_reuse_stable_request(path: Path, value: Mapping[str, Any]) -> Path:
    """Keep the first immutable request bytes when an exact retry has a later clock value."""

    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if path.exists():
        existing_bytes = path.read_bytes()
        try:
            existing = json.loads(existing_bytes)
        except json.JSONDecodeError as exc:
            raise CompletionError("WORKER_CONTINUATION_CONFLICT", f"immutable request is invalid: {path.name}") from exc
        comparable = dict(value)
        if isinstance(existing, dict) and "occurred_at" in comparable:
            comparable["occurred_at"] = existing.get("occurred_at")
        if existing != comparable:
            raise CompletionError("WORKER_CONTINUATION_CONFLICT", f"immutable request conflicts: {path.name}")
        return path
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)
    return path


def _event_details(value: Mapping[str, Any]) -> Mapping[str, Any] | None:
    details = value.get("details")
    if isinstance(details, Mapping):
        return details
    serialized = value.get("details_json")
    if isinstance(serialized, str):
        try:
            parsed = json.loads(serialized)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def _source_attempt(runtime_projection: Mapping[str, Any], envelope: Envelope) -> int:
    events = runtime_projection.get("events")
    if not isinstance(events, list):
        raise CompletionError("WORKER_COMPLETION_ATTEMPT_UNPROVEN", "runtime events are unavailable")
    attempts: set[int] = set()
    for item in events:
        if (
            not isinstance(item, Mapping)
            or item.get("event_type") != "TRANSPORT_STARTED"
            or item.get("cell_id") != envelope.cell_id
        ):
            continue
        details = _event_details(item)
        attempt = item.get("attempt")
        if (
            details is not None
            and details.get("message_id") == envelope.message_id
            and isinstance(attempt, int)
            and not isinstance(attempt, bool)
            and attempt >= 1
        ):
            attempts.add(attempt)
    if len(attempts) != 1:
        raise CompletionError(
            "WORKER_COMPLETION_ATTEMPT_UNPROVEN",
            "source message must bind exactly one current TRANSPORT_STARTED attempt",
        )
    return attempts.pop()


def _event_types(projection: Mapping[str, Any], *, cell_id: str, attempt: int) -> set[str]:
    events = projection.get("events")
    if not isinstance(events, list):
        return set()
    return {
        str(item.get("event_type"))
        for item in events
        if isinstance(item, Mapping)
        and isinstance(item.get("event_type"), str)
        and item.get("cell_id") == cell_id
        and item.get("attempt") == attempt
    }


def _event_details(value: Mapping[str, Any]) -> Mapping[str, Any]:
    details = value.get("details")
    if isinstance(details, Mapping):
        return details
    serialized = value.get("details_json")
    if isinstance(serialized, str):
        try:
            decoded = json.loads(serialized)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, Mapping):
            return decoded
    return {}


def _exact_worker_handoff(
    projection: Mapping[str, Any],
    *,
    cell_id: str,
    attempt: int,
    candidate: Mapping[str, Any],
    source_message_id: str,
    handoff_message_id: str,
) -> tuple[bool, bool]:
    events = projection.get("events")
    if not isinstance(events, list):
        return False, False
    candidate_submitted = False
    transport_started = False
    for item in events:
        if (
            not isinstance(item, Mapping)
            or item.get("cell_id") != cell_id
            or item.get("attempt") != attempt
        ):
            continue
        details = _event_details(item)
        if item.get("event_type") == "CANDIDATE_SUBMITTED":
            candidate_submitted = candidate_submitted or (
                details.get("candidate") == candidate
                and details.get("source_message_id") == source_message_id
                and details.get("handoff_message_id") == handoff_message_id
            )
        if item.get("event_type") == "TRANSPORT_STARTED":
            transport_started = transport_started or details.get("message_id") == handoff_message_id
    return candidate_submitted, transport_started


def _observation_mentions_message(value: Any, message_id: str) -> bool:
    if not isinstance(value, Mapping):
        return False
    if value.get("message_id") == message_id:
        return True
    details: Any = value.get("details")
    if not isinstance(details, Mapping):
        serialized = value.get("details_json")
        if isinstance(serialized, str):
            try:
                details = json.loads(serialized)
            except json.JSONDecodeError:
                details = None
    return isinstance(details, Mapping) and details.get("message_id") == message_id


def inspect_worker_completion(
    attempt_root: Path | str,
    runtime_projection: Mapping[str, Any],
    *,
    observed_at: str,
    cadence_seconds: int,
    previous_inspection: Mapping[str, Any] | None = None,
    native_inspector: Callable[..., Mapping[str, Any]] = inspect_native_activity,
) -> dict[str, Any]:
    """Inspect native and delivery facts without reviewing the Worker report or deciding D0."""

    if isinstance(cadence_seconds, bool) or cadence_seconds < 1:
        raise CompletionError("WORKER_COMPLETION_CADENCE_INVALID", "cadence_seconds must be positive")
    now = _timestamp(observed_at)
    attempt = Path(attempt_root).resolve()
    envelope = Envelope.from_dict(_read_object(attempt / "envelope.json", "Worker envelope"))
    endpoint = Endpoint.from_dict(_read_object(attempt / "endpoint.json", "Worker endpoint"))
    snapshot = runtime_projection.get("runtime_snapshot")
    if not isinstance(snapshot, Mapping):
        raise CompletionError("WORKER_COMPLETION_PROJECTION_INVALID", "runtime snapshot is required")
    token_owner = snapshot.get("token_holder_role_instance_id")
    attempt_number = _source_attempt(runtime_projection, envelope)
    event_types = _event_types(runtime_projection, cell_id=envelope.cell_id, attempt=attempt_number)
    completed_path = attempt / "completed.json"
    completed = completed_path.is_file()
    failed_path = attempt / "failed.json"
    candidate: Mapping[str, Any] | None = None
    handoff_message_id = _stable_id(envelope.message_id, "candidate-ready")
    exact_candidate = False
    exact_transport = False
    try:
        worker_result = json.loads((attempt / "worker-result.json").read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        worker_result = None
    if isinstance(worker_result, Mapping) and isinstance(worker_result.get("candidate"), Mapping):
        candidate = worker_result["candidate"]
        exact_candidate, exact_transport = _exact_worker_handoff(
            runtime_projection, cell_id=envelope.cell_id, attempt=attempt_number,
            candidate=candidate, source_message_id=envelope.message_id,
            handoff_message_id=handoff_message_id,
        )
    base = {
        "schema_version": INSPECTION_SCHEMA,
        "run_id": envelope.run_id,
        "go_id": envelope.go_id,
        "cell_id": envelope.cell_id,
        "attempt": attempt_number,
        "source_message_id": envelope.message_id,
        "worker_role_instance_id": endpoint.role_instance_id,
        "candidate": candidate,
        "worker_outcome": None,
        "native_status": "completed" if completed else "failed" if failed_path.is_file() else None,
        "blocker": None,
        "handoff_message_id": handoff_message_id,
        "observed_at": observed_at,
        "cadence_seconds": cadence_seconds,
        "anomaly_codes": [],
        "notification_already_sent": False,
        "missing_worker_events": [],
    }
    if not completed:
        if failed_path.is_file():
            failed = DeliveryResult.from_dict(_read_object(failed_path, "native Worker failure"))
            if (failed.message_id != envelope.message_id or failed.run_id != envelope.run_id
                or failed.adapter != endpoint.adapter or failed.status != "failed"):
                raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "native failure changed dispatch identity")
            return {**base, "status": "WORKER_TIMED_OUT" if failed.error_code == "DSH_TIMEOUT"
                    else "WORKER_EXECUTION_FAILURE", "grace_started_at": None,
                    "native_identity": dict(failed.native_identity),
                    "blocker": {"phase": "native_execution", "cause": failed.error_code,
                                "summary": "native execution failed; the Worker engineering outcome is not inferred",
                                "evidence": [str(failed_path)]}}
        try:
            native = native_inspector(
                attempt / "started.json", terminal_paths=(completed_path, failed_path),
                observed_at=observed_at,
            )
            native_status = str(native.get("status"))
            native_error = native.get("error")
        except (NativeActivityError, OSError, TypeError, ValueError) as exc:
            native_status, native_error = "UNKNOWN", str(exc) or type(exc).__name__
        if native_status in {"ACTIVE", "PENDING", "IDLE"}:
            return {**base, "status": "IN_PROGRESS", "grace_started_at": None}
        cause = {
            "DEAD_WITHOUT_TERMINAL": "NATIVE_TURN_ORPHANED",
            "COMPLETED_WITHOUT_TERMINAL": "NATIVE_TASK_COMPLETED_WITHOUT_TERMINAL",
            "FAILED_WITHOUT_TERMINAL": "NATIVE_TASK_FAILED_WITHOUT_TERMINAL",
        }.get(native_status, "NATIVE_ACTIVITY_UNPROVED")
        evidence = ["started.json"]
        if (attempt / "native-activity.json").is_file():
            evidence.append("native-activity.json")
        if cause == "NATIVE_ACTIVITY_UNPROVED":
            return {
                **base, "status": "UNKNOWN", "worker_outcome": None,
                "blocker": {"phase": "native_observation", "cause": str(native_error or cause)[:512],
                            "summary": f"native observation status={native_status[:64]}; Worker execution outcome is unproved",
                            "evidence": evidence},
                "grace_started_at": None,
            }
        return {
            **base,
            "status": cause,
            "worker_outcome": None,
            "blocker": {
                "phase": "native_execution",
                "cause": cause,
                "summary": "the exact Worker native turn is not active and has no terminal engineering result",
                "evidence": evidence,
            },
            "grace_started_at": None,
        }
    if token_owner != endpoint.role_instance_id and exact_candidate and exact_transport:
        return {**base, "status": "HANDED_OFF_OR_D1", "grace_started_at": None}
    output_root = attempt / "role-host"
    if (output_root / "output-envelope.json").is_file():
        from .contracts import parse_delivery
        from .desktop_current_turn import resolve_delivery_start
        target = _read_object(output_root / "output-endpoint.json", "report endpoint")
        raw = _read_object(output_root / "output-envelope.json", "report envelope")
        outgoing = parse_delivery(target, raw).envelope
        if ((outgoing.run_id, outgoing.go_id, outgoing.cell_id) != (envelope.run_id, envelope.go_id, envelope.cell_id)
            or outgoing.sender_role_instance_id != endpoint.role_instance_id
            or outgoing.receiver_role != "checker"
            or outgoing.payload.get("source_message_id") != envelope.message_id):
            raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "output report changed dispatch identity")
        native = output_root / "output-attempts" / outgoing.run_id / outgoing.message_id
        try:
            started_path, _ = resolve_delivery_start(native, target, raw)
        except (ValueError, OSError) as exc:
            base["output_delivery"] = {"status": "UNCONFIRMED", "error": str(exc)}
        else:
            return {**base, "status": "OUTPUT_DELIVERED_AWAITING_ROLE_ACTION", "grace_started_at": None,
                    "output_delivery": {"status": "started", "message_id": outgoing.message_id,
                                        "evidence": str(started_path)}}
    handoff_failures = sorted((attempt / "role-host").glob("failure-*.json"))
    if len(handoff_failures) > 1:
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "multiple explicit Worker handoff failures conflict",
        )
    if handoff_failures:
        failure = _read_object(handoff_failures[0], "Worker host handoff failure")
        error_code = failure.get("error_code")
        if (
            set(failure)
            != {"status", "run_id", "source_message_id", "error_code"}
            or failure.get("status") != "HOST_HANDOFF_FAILED"
            or failure.get("run_id") != envelope.run_id
            or failure.get("source_message_id") != envelope.message_id
            or not isinstance(error_code, str)
            or not error_code
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "explicit Worker handoff failure does not match this dispatch",
            )
        return {
            **base,
            "status": "WORKER_COMPLETION_HANDOFF_MISSING",
            "blocker": {
                "phase": "checker_handoff",
                "cause": error_code,
                "summary": "the owning host recorded an explicit Checker handoff failure",
                "evidence": [str(handoff_failures[0].resolve())],
            },
            "grace_started_at": None,
            "anomaly_codes": [
                "WORKER_COMPLETION_HANDOFF_MISSING",
                "COMMUNICATION_RECOVERY_REQUIRED",
            ],
        }
    observations = runtime_projection.get("operational_observations")
    notification_already_sent = isinstance(observations, list) and any(
        _observation_mentions_message(item, envelope.message_id) for item in observations
    )
    terminal_time = _file_timestamp(completed_path)
    grace_started = terminal_time if terminal_time <= now else now
    grace_started_at = grace_started.isoformat().replace("+00:00", "Z")
    if previous_inspection is not None:
        if (
            previous_inspection.get("schema_version") != INSPECTION_SCHEMA
            or previous_inspection.get("run_id") != envelope.run_id
            or previous_inspection.get("source_message_id") != envelope.message_id
            or previous_inspection.get("status")
            not in {"COMPLETION_GRACE", "WORKER_COMPLETION_HANDOFF_MISSING"}
        ):
            raise CompletionError("WORKER_COMPLETION_PREVIOUS_INVALID", "previous inspection identity is not exact")
        grace_started_at = str(previous_inspection.get("grace_started_at"))
    elapsed = (now - _timestamp(grace_started_at)).total_seconds()
    if elapsed < cadence_seconds:
        return {**base, "status": "COMPLETION_GRACE", "grace_started_at": grace_started_at}
    return {
        **base,
        "status": "WORKER_COMPLETION_HANDOFF_MISSING",
        "grace_started_at": grace_started_at,
        "anomaly_codes": [
            "WORKER_COMPLETION_HANDOFF_MISSING",
            "COMMUNICATION_RECOVERY_REQUIRED",
        ],
        "notification_already_sent": notification_already_sent,
        "missing_worker_events": sorted(
            {"WORK_STARTED", "D0_COMPLETED"} - event_types
            | ({"CANDIDATE_SUBMITTED"} if not exact_candidate else set())
            | ({"TRANSPORT_STARTED"} if not exact_transport else set())
        ),
    }


Authenticate = Callable[[str, str], int]
WriteEvent = Callable[[dict[str, Any]], str]
StartChecker = Callable[[dict[str, Any], dict[str, Any]], Mapping[str, Any]]
CommitStart = Callable[[dict[str, Any]], Mapping[str, Any]]


def _decode_dpapi_plaintext(plain: bytes) -> str:
    """Decode only the two credential encodings produced by supported SLK provisioners."""

    try:
        if plain.startswith(b"\xff\xfe"):
            encoded = plain[2:]
            if not encoded or len(encoded) % 2:
                raise CompletionError(
                    "WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential UTF-16LE bytes are invalid"
                )
            secret = encoded.decode("utf-16-le")
        elif plain.startswith(b"s\x00l\x00k\x00_\x00"):
            if len(plain) % 2:
                raise CompletionError(
                    "WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential UTF-16LE bytes are invalid"
                )
            secret = plain.decode("utf-16-le")
        elif plain.startswith(b"slk_"):
            secret = plain.decode("utf-8", errors="strict")
        else:
            raise CompletionError(
                "WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential plaintext is invalid"
            )
    except UnicodeDecodeError as exc:
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential plaintext is invalid") from exc
    if secret.endswith("\0"):
        secret = secret[:-1]
    if "\0" in secret:
        raise CompletionError(
            "WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential contains an embedded NUL"
        )
    suffix = secret[4:]
    if (
        not secret.startswith("slk_")
        or len(suffix) != 64
        or any(character not in "0123456789abcdef" for character in suffix)
    ):
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential shape is invalid")
    return secret


def prepare_sealed_role_credential(
    source: Path | str, destination: Path | str, *, run_id: str, role: str,
    role_instance_id: str, state_command: list[str],
) -> dict[str, Any]:
    """Trusted preparation host: authenticate, seal, then verify the saved consumer.

    Input is the existing one-time credential-out file, never a CLI secret value.
    Neither source nor an existing destination is rewritten or removed.
    """
    source, destination = Path(source), Path(destination)
    if not source.is_absolute():
        raise CompletionError("ROLE_CREDENTIAL_PREPARATION_INVALID", "use an absolute credential source")
    try:
        raw = source.read_bytes()
        if len(raw) > 512:
            raise ValueError("credential source exceeds the supported encoding size")
        secret = _decode_dpapi_plaintext(raw.rstrip(b"\r\n"))
    except (OSError, ValueError) as exc:
        raise CompletionError("ROLE_CREDENTIAL_PREPARATION_INVALID", "credential source is unreadable or invalid") from exc
    try:
        return seal_role_credential(
            secret, destination, run_id=run_id, role=role,
            role_instance_id=role_instance_id, state_command=state_command,
        )
    finally:
        secret = ""


def seal_role_credential(
    secret: str, destination: Path | str, *, run_id: str, role: str,
    role_instance_id: str, state_command: list[str],
) -> dict[str, Any]:
    """Authenticate and DPAPI-seal an in-memory one-time role credential."""
    if os.name != "nt" or role not in {"supervisor", "checker", "worker", "overwatcher"}:
        raise CompletionError("ROLE_CREDENTIAL_PREPARATION_INVALID", "Windows and an exact role are required")
    destination = Path(destination)
    if not destination.is_absolute() or destination.exists():
        raise CompletionError("ROLE_CREDENTIAL_PREPARATION_INVALID", "use a new absolute sealed destination")
    if not all(isinstance(item, str) and item.strip() for item in (run_id, role_instance_id)) or not isinstance(state_command, list) or not state_command or not all(
        isinstance(part, str) and part for part in state_command
    ):
        raise CompletionError("ROLE_CREDENTIAL_PREPARATION_INVALID", "frozen identity and state command are required")
    try:
        secret = _decode_dpapi_plaintext(secret.encode("utf-8"))
    except (AttributeError, UnicodeError, ValueError) as exc:
        raise CompletionError("ROLE_CREDENTIAL_PREPARATION_INVALID", "issued credential is invalid") from exc

    def authenticate(credential: str) -> Mapping[str, Any]:
        result = _run_json_command(
            state_command,
            ["authenticate-role", "--run-id", run_id, "--role-instance-id", role_instance_id],
            credential=credential,
        )
        revision = result.get("runtime_revision")
        if (
            result.get("status") != "authenticated" or result.get("run_id") != run_id
            or result.get("role") != role or result.get("role_instance_id") != role_instance_id
            or isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
        ):
            raise CompletionError("ROLE_CREDENTIAL_MISMATCH", "credential does not authenticate the frozen role")
        return result

    authenticate(secret)

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    buffer = ctypes.create_string_buffer(secret.encode("utf-8"))
    incoming = DataBlob(len(secret), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    outgoing = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        if not crypt32.CryptProtectData(
            ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)
        ):
            raise CompletionError("ROLE_CREDENTIAL_SEAL_FAILED", "CurrentUser DPAPI sealing failed")
        encoded = ctypes.string_at(outgoing.pbData, outgoing.cbData).hex()
        with destination.open("x", encoding="ascii") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        saved = unprotect_dpapi_hex(destination)
        if saved != secret:
            raise CompletionError("ROLE_CREDENTIAL_SEAL_FAILED", "saved consumer roundtrip failed")
        result = authenticate(saved)
        return {
            "status": "SEALED_ROLE_VERIFIED", "run_id": run_id, "role": role,
            "role_instance_id": role_instance_id, "sealed_path": str(destination),
            "sealed_sha256": _sha256(destination), "runtime_revision": result.get("runtime_revision"),
        }
    finally:
        ctypes.memset(buffer, 0, len(buffer))
        if outgoing.pbData:
            kernel32.LocalFree(outgoing.pbData)
        secret = ""


def unprotect_dpapi_hex(path: Path | str) -> str:
    """Decrypt one CurrentUser DPAPI hex blob without emitting its plaintext."""

    if os.name != "nt":
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "DPAPI is available only on Windows")
    try:
        encoded = Path(path).read_text(encoding="ascii").strip()
        protected = bytes.fromhex(encoded)
    except (OSError, UnicodeError, ValueError) as exc:
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential blob is invalid") from exc
    if not protected:
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential blob is empty")

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    buffer = ctypes.create_string_buffer(protected)
    incoming = DataBlob(len(protected), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    outgoing = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if not crypt32.CryptUnprotectData(
        ctypes.byref(incoming), None, None, None, None, 0, ctypes.byref(outgoing)
    ):
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "DPAPI rejected the Worker credential")
    try:
        plain = ctypes.string_at(outgoing.pbData, outgoing.cbData)
        secret = _decode_dpapi_plaintext(plain)
    except CompletionError:
        raise
    except ValueError as exc:
        raise CompletionError("WORKER_CREDENTIAL_UNAVAILABLE", "Worker credential plaintext is invalid") from exc
    finally:
        if outgoing.pbData:
            ctypes.memset(outgoing.pbData, 0, outgoing.cbData)
            kernel32.LocalFree(outgoing.pbData)
        ctypes.memset(buffer, 0, len(protected))
    return secret


CheckerAuthenticate = Callable[[str, str, Path, list[str]], Mapping[str, Any]]
ResumeContinuation = Callable[[Mapping[str, Any]], Mapping[str, Any]]
ActivateChecker = Callable[[Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]]
RecordCheckerD1 = Callable[[Mapping[str, Any], Mapping[str, Any], Path, float], Mapping[str, Any]]
LoadCommittedActivation = Callable[[Mapping[str, Any], int], Mapping[str, Any]]
LoadCurrentProjection = Callable[[str, list[str]], Mapping[str, Any]]


def _default_checker_authenticate(
    run_id: str,
    role_instance_id: str,
    credential_path: Path,
    state_command: list[str],
) -> Mapping[str, Any]:
    try:
        credential = unprotect_dpapi_hex(credential_path)
    except CompletionError as exc:
        raise CompletionError(
            "CHECKER_CREDENTIAL_UNAVAILABLE",
            "Checker sealed credential cannot be consumed; verify preparation format and CurrentUser identity",
        ) from exc
    return _run_json_command(
        state_command,
        ["authenticate-role", "--run-id", run_id, "--role-instance-id", role_instance_id],
        credential=credential,
    )


def _default_load_current_projection(
    run_id: str, state_command: list[str], *, state_config_path: str | None = None,
) -> Mapping[str, Any]:
    query_path = Path(state_command[0]).resolve().with_name("slk-bi-query.exe")
    if not query_path.is_file():
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
            "current Run projection cannot be authenticated",
        )
    try:
        value = _run_json_command(
            [str(query_path)], ["run", "--run-id", run_id], credential=None,
            state_config_path=state_config_path,
        )
    except CompletionError as exc:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
            "current Run projection cannot be authenticated",
        ) from exc
    command = value.pop("_slk_command", None)
    if not isinstance(command, Mapping) or command.get("process_exit") != 0:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
            "current Run projection cannot be authenticated",
        )
    return value


def _record_checker_d1(
    activation: Mapping[str, Any],
    continuation: Mapping[str, Any],
    *,
    checker_credential_path: Path | str,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    """Retired automatic suffix: terminal files never make an engineering decision."""
    raise CompletionError(
        "CHECKER_EXPLICIT_DECISION_REQUIRED",
        "D1 requires the original Checker explicit action; preserved reports are not verdicts",
    )


def _exact_digest(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _positive_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _exact_commit(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _nonempty_strings(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and bool(item) for item in value
    )


def _matches(value: Any, expected: Mapping[str, Any]) -> bool:
    return isinstance(value, Mapping) and all(value.get(name) == item for name, item in expected.items())


def _committed_event_details(event: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        value = json.loads(str(event.get("details_json", "")))
    except json.JSONDecodeError as exc:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "central event details are invalid",
        ) from exc
    if not isinstance(value, Mapping):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "central event details are not an object",
        )
    return value


def _run_json_command(
    command: list[str],
    arguments: list[str],
    *,
    credential: str | None,
    credential_scope: str = "role",
    state_config_path: str | None = None,
    pythonpath: str | None = None,
) -> dict[str, Any]:
    from .process import windows_no_window_kwargs

    if credential_scope not in {"role", "overwatcher"}:
        raise CompletionError(
            "WORKER_CONTINUATION_CREDENTIAL_SCOPE_INVALID",
            "continuation command credential scope is not allowed",
        )
    environment = os.environ.copy()
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
    if credential is not None:
        environment[
            "SLK_ROLE_CREDENTIAL"
            if credential_scope == "role"
            else "SLK_OVERWATCHER_CREDENTIAL"
        ] = credential
    if state_config_path is not None:
        config = Path(state_config_path)
        if not config.is_absolute() or not config.is_file():
            raise CompletionError(
                "WORKER_CONTINUATION_STATE_CONFIG_INVALID",
                "state command config path is unavailable",
            )
        environment["SLK_CONFIG_PATH"] = str(config.resolve())
    if pythonpath is not None:
        roots = [Path(item) for item in pythonpath.split(os.pathsep)]
        if not roots or any(not root.is_absolute() or not root.is_dir() for root in roots):
            raise CompletionError(
                "WORKER_CONTINUATION_PYTHONPATH_INVALID",
                "continuation command Python source path is unavailable",
            )
        environment["PYTHONPATH"] = pythonpath
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    completed = subprocess.run(
        command + arguments,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        env=environment,
        **windows_no_window_kwargs(),
    )
    decoded: dict[str, str] = {}
    for label, raw in (("stdout", completed.stdout), ("stderr", completed.stderr)):
        data = raw if isinstance(raw, bytes) else b"" if raw is None else None
        if data is None:
            raise CompletionError(
                "WORKER_CONTINUATION_COMMAND_ENCODING_INVALID",
                f"continuation command {label} did not return bytes",
            )
        try:
            decoded[label] = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            digest = hashlib.sha256(data).hexdigest()
            raise CompletionError(
                "WORKER_CONTINUATION_COMMAND_ENCODING_INVALID",
                f"continuation command {label} is not UTF-8; sha256={digest}",
            ) from exc
    parsed: tuple[dict[str, Any], str] | None = None
    last_error: json.JSONDecodeError | None = None
    for raw, parse_status in (
        (decoded["stdout"], "PARSED_STDOUT"),
        (decoded["stderr"], "PARSED_STDERR"),
    ):
        if not raw.strip():
            continue
        try:
            candidate = json.loads(raw.strip())
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(candidate, dict):
            raise CompletionError(
                "WORKER_CONTINUATION_COMMAND_FAILED", "continuation command JSON must be an object"
            )
        parsed = (dict(candidate), parse_status)
        break
    if parsed is None:
        raise CompletionError(
            "WORKER_CONTINUATION_COMMAND_FAILED", "continuation command returned no parseable JSON"
        ) from last_error
    value, parse_status = parsed
    if "_slk_command" in value:
        raise CompletionError(
            "WORKER_CONTINUATION_COMMAND_FAILED", "continuation command used a reserved result field"
        )
    business_status = value.get("verdict", value.get("status"))
    value["_slk_command"] = {
        "process_exit": completed.returncode,
        "json_parse": parse_status,
        "business_status": business_status if isinstance(business_status, str) else None,
    }
    return value
