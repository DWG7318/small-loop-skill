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
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", operation_id)
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
    started_path = native / "started.json"
    failed_path = native / "failed.json"
    deadline = time.monotonic() + 300
    while not started_path.is_file() and time.monotonic() < deadline:
        if failed_path.is_file():
            break
        time.sleep(0.05)
    try:
        validate_native_start(
            started_path,
            adapter=endpoint.adapter,
            run_id=envelope.run_id,
            cell_id=envelope.cell_id,
            message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256,
        )
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


def _missing_result_failure(attempt: Path, envelope: Envelope) -> dict[str, Any] | None:
    """Return the exact legacy DSH missing-result terminal, if present."""

    failed_path = attempt / "failed.json"
    if (
        not failed_path.is_file()
        or (attempt / "completed.json").exists()
        or (attempt / "worker-result.json").exists()
    ):
        return None
    failed = _read_object(failed_path, "Worker failed result")
    if (
        failed.get("schema_version") != "slk.transport-result/v1"
        or failed.get("message_id") != envelope.message_id
        or failed.get("run_id") != envelope.run_id
        or failed.get("adapter") != "dsh-worker"
        or failed.get("status") != "failed"
        or failed.get("error_code") != "DSH_RESULT_MISSING"
    ):
        return None
    return failed


def _native_execution_failure(
    attempt: Path, endpoint: Endpoint, envelope: Envelope
) -> dict[str, Any] | None:
    receipt_path = attempt / "native-execution.json"
    failed_path = attempt / "failed.json"
    started_path = attempt / "started.json"
    if (
        not receipt_path.is_file()
        or not failed_path.is_file()
        or not started_path.is_file()
        or (attempt / "completed.json").exists()
        or (attempt / "worker-result.json").exists()
    ):
        return None
    receipt = _read_object(receipt_path, "native execution outcome")
    failed = _read_object(failed_path, "Worker failed result")
    try:
        started = validate_native_start(
            started_path,
            adapter="dsh-worker",
            run_id=envelope.run_id,
            cell_id=envelope.cell_id,
            message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256,
        )
    except NativeActivityError:
        return None
    receipt_fields = {
        "schema_version", "adapter", "run_id", "cell_id", "message_id", "instance_id",
        "session_id", "status", "started_at", "ended_at", "duration_ms", "exit_code",
        "error_code", "stdout_sha256", "stderr_sha256",
    }
    identity_fields = {
        "instance_id", "session_id", "exit_code", "runtime_outcome", "duration_ms",
        "error_code", "execution_receipt_sha256",
    }
    expected = {
        "execution_failure": ("DSH_EXIT_NONZERO", int),
        "timed_out": ("DSH_TIMEOUT", type(None)),
    }
    outcome = receipt.get("status")
    if outcome not in expected:
        return None
    error_code, exit_type = expected[outcome]
    identity = failed.get("native_identity")
    evidence = failed.get("evidence")
    duration = receipt.get("duration_ms")
    try:
        _timestamp(str(receipt.get("started_at")))
        _timestamp(str(receipt.get("ended_at")))
    except (CompletionError, ValueError):
        return None
    if (
        set(receipt) != receipt_fields
        or receipt.get("schema_version") != "slk.native-execution-outcome/v1"
        or receipt.get("adapter") != "dsh-worker"
        or receipt.get("run_id") != envelope.run_id
        or receipt.get("cell_id") != envelope.cell_id
        or receipt.get("message_id") != envelope.message_id
        or receipt.get("instance_id") != endpoint.address.get("instance_id")
        or receipt.get("session_id") != started["native_task"]["id"]
        or receipt.get("error_code") != error_code
        or not isinstance(receipt.get("exit_code"), exit_type)
        or isinstance(duration, bool)
        or not isinstance(duration, int)
        or duration < 0
        or not all(
            isinstance(receipt.get(field), str)
            and len(str(receipt[field])) == 64
            and all(character in "0123456789abcdef" for character in str(receipt[field]))
            for field in ("stdout_sha256", "stderr_sha256")
        )
        or failed.get("schema_version") != "slk.transport-result/v1"
        or failed.get("message_id") != envelope.message_id
        or failed.get("run_id") != envelope.run_id
        or failed.get("adapter") != "dsh-worker"
        or failed.get("status") != "failed"
        or failed.get("error_code") != error_code
        or not isinstance(identity, Mapping)
        or set(identity) != identity_fields
        or identity.get("instance_id") != receipt.get("instance_id")
        or identity.get("session_id") != receipt.get("session_id")
        or identity.get("exit_code") != receipt.get("exit_code")
        or identity.get("runtime_outcome") != outcome
        or identity.get("duration_ms") != duration
        or identity.get("error_code") != error_code
        or identity.get("execution_receipt_sha256") != _sha256(receipt_path)
        or not isinstance(evidence, list)
        or "native-execution.json" not in evidence
    ):
        return None
    return receipt


def _git_text(repository: Path, *arguments: str) -> str:
    from .process import windows_no_window_kwargs

    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
        check=False,
        **windows_no_window_kwargs(),
    )
    if completed.returncode != 0:
        raise CompletionError(
            "WORKER_CONTINUATION_NOT_READY",
            f"candidate repository cannot prove git {' '.join(arguments)}",
        )
    return completed.stdout.strip()


def _candidate_repository_snapshot(repository: Path) -> dict[str, Any]:
    repository = repository.resolve()
    if not repository.is_dir():
        raise CompletionError("WORKER_CONTINUATION_NOT_READY", "candidate repository is unavailable")
    root = Path(_git_text(repository, "rev-parse", "--show-toplevel")).resolve()
    if root != repository:
        raise CompletionError("WORKER_CONTINUATION_NOT_READY", "candidate repository root changed")
    status = _git_text(repository, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise CompletionError("WORKER_CONTINUATION_NOT_READY", "candidate repository is not clean")
    head = _git_text(repository, "rev-parse", "HEAD")
    parent = _git_text(repository, "rev-parse", "HEAD^")
    changed_paths = sorted(
        item for item in _git_text(repository, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
        if item
    )
    if (
        len(head) != 40
        or len(parent) != 40
        or any(character not in "0123456789abcdef" for character in head + parent)
        or not changed_paths
    ):
        raise CompletionError("WORKER_CONTINUATION_NOT_READY", "candidate git identity is invalid")
    return {
        "repository": str(repository),
        "head": head,
        "parent": parent,
        "changed_paths": changed_paths,
    }


def _invalid_result_contract_source(
    attempt: Path,
    endpoint: Endpoint,
    envelope: Envelope,
    started: Mapping[str, Any],
) -> dict[str, Any] | None:
    failed_path = attempt / "failed.json"
    invalid_path = attempt / "worker-result.invalid.txt"
    task_path = attempt / "transport-task.json"
    if (
        not failed_path.is_file()
        or not invalid_path.is_file()
        or not task_path.is_file()
        or (attempt / "completed.json").exists()
        or (attempt / "worker-result.json").exists()
    ):
        return None
    failed = _read_object(failed_path, "Worker failed result")
    terminal_fields = {
        "schema_version", "message_id", "run_id", "adapter", "status",
        "native_identity", "error_code", "evidence",
    }
    if (
        set(failed) != terminal_fields
        or failed.get("schema_version") != "slk.transport-result/v1"
        or failed.get("message_id") != envelope.message_id
        or failed.get("run_id") != envelope.run_id
        or failed.get("adapter") != "dsh-worker"
        or failed.get("status") != "failed"
        or failed.get("error_code") != "DSH_RESULT_INVALID"
        or not isinstance(failed.get("native_identity"), Mapping)
        or not isinstance(failed.get("evidence"), list)
        or "worker-result.invalid.txt" not in failed["evidence"]
    ):
        return None
    task_digest = started.get("native_request_sha256")
    if not isinstance(task_digest, str):
        return None
    try:
        task = verify_task_file(task_path.resolve(), task_digest)
        task_endpoint = Endpoint.from_dict(task["endpoint"])
        task_envelope = Envelope.from_dict(task["envelope"])
        from .adapters.dsh import DshAdapter

        expected_result_path = (
            Path(str(endpoint.address["cwd"]))
            / ".slk-transport"
            / envelope.message_id
            / "worker-result.json"
        ).resolve()
        task_matches = (
            task_endpoint == endpoint
            and task_envelope == envelope
            and task.get("message_id") == envelope.message_id
            and task.get("run_id") == envelope.run_id
            and task.get("go_id") == envelope.go_id
            and task.get("cell_id") == envelope.cell_id
            and task.get("result_contract") == DshAdapter.legacy_result_contract(endpoint, envelope)
            and task.get("result_path") == str(expected_result_path)
        )
    except (KeyError, TypeError, ValueError, TaskFileError, CompletionError):
        return None
    if not task_matches:
        return None
    invalid = _read_object(invalid_path, "invalid Worker result")
    identity = invalid.get("identity")
    completed = invalid.get("completed")
    if (
        set(invalid) != {"schema_version", "identity", "status", "completed"}
        or invalid.get("schema_version") != "slk.worker-result-contract/v1"
        or invalid.get("status") != "completed"
        or not isinstance(identity, Mapping)
        or set(identity) != {"schema_version", "message_id", "run_id", "role_instance_id"}
        or identity.get("schema_version") != "slk.worker-result/v1"
        or identity.get("message_id") != envelope.message_id
        or identity.get("run_id") != envelope.run_id
        or identity.get("role_instance_id") != endpoint.role_instance_id
        or not isinstance(completed, Mapping)
        or set(completed) != {"candidate", "next_payload", "blocker", "evidence"}
        or completed.get("blocker") is not None
    ):
        return None
    candidate = completed.get("candidate")
    next_payload = completed.get("next_payload")
    evidence = completed.get("evidence")
    if (
        not isinstance(candidate, Mapping)
        or set(candidate) != {"kind", "commit"}
        or candidate.get("kind") != "commit"
        or not isinstance(candidate.get("commit"), str)
        or len(str(candidate["commit"])) != 40
        or any(character not in "0123456789abcdef" for character in str(candidate["commit"]))
        or not isinstance(next_payload, Mapping)
        or set(next_payload) != {"candidate_repository"}
        or not isinstance(next_payload.get("candidate_repository"), str)
        or not isinstance(evidence, Mapping)
    ):
        return None
    repository = Path(str(next_payload["candidate_repository"])).resolve()
    if repository != Path(str(endpoint.address["cwd"])).resolve():
        return None
    snapshot = _candidate_repository_snapshot(repository)
    raw_changed_paths = evidence.get("changed_paths")
    if (
        snapshot["head"] != candidate["commit"]
        or evidence.get("candidate_commit") != candidate["commit"]
        or evidence.get("candidate_parent") != snapshot["parent"]
        or not isinstance(raw_changed_paths, list)
        or sorted(raw_changed_paths) != snapshot["changed_paths"]
    ):
        return None
    return {
        "failed": failed,
        "candidate": dict(candidate),
        **snapshot,
    }


def _pre_d0_environment(
    path: Path,
    expected_sha256: str,
    *,
    envelope: Envelope,
    attempt_number: int,
    project_id: str,
) -> dict[str, Any]:
    """Verify one closed environment adjustment for the exact blocked D0 command."""

    try:
        if not path.is_absolute() or not path.is_file() or _sha256(path) != expected_sha256:
            raise ValueError("environment adjustment hash changed")
        value = _read_object(path, "pre-D0 environment adjustment")
        if (
            set(value) != PRE_D0_ENVIRONMENT_FIELDS
            or value.get("schema_version") != "slk.pre-d0-blocked-recovery/v1"
            or value.get("recovery_kind") != "WINDOWS_CARGO_TARGET_PLAIN_PATH"
            or value.get("source_message_id") != envelope.message_id
            or not isinstance(value.get("candidate_repository"), str)
            or not isinstance(value.get("candidate_commit"), str)
            or not re.fullmatch(r"[0-9a-f]{40}", str(value["candidate_commit"]))
            or not isinstance(value.get("tool_path"), str)
            or not isinstance(value.get("tool_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", str(value["tool_sha256"]))
            or not isinstance(value.get("state_config_path"), str)
            or not isinstance(value.get("state_config_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", str(value["state_config_sha256"]))
            or not isinstance(value.get("d0_environment"), Mapping)
            or set(value["d0_environment"]) != {"PROTOC", "PROTOC_SHA256"}
            or not isinstance(value["d0_environment"].get("PROTOC"), str)
            or not value["d0_environment"]["PROTOC"]
            or not isinstance(value["d0_environment"].get("PROTOC_SHA256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", value["d0_environment"]["PROTOC_SHA256"])
            or not isinstance(value.get("d0_command"), list)
            or not value["d0_command"]
            or not all(isinstance(item, str) and item for item in value["d0_command"])
        ):
            raise ValueError("environment adjustment is not closed")
        repository = Path(str(value["candidate_repository"])).resolve()
        tool = Path(str(value["tool_path"])).resolve()
        state_config_path = Path(str(value["state_config_path"])).resolve()
        protoc = Path(str(value["d0_environment"]["PROTOC"]))
        command = list(value["d0_command"])
        if (
            Path(command[0]).resolve() != tool
            or not tool.is_file()
            or _sha256(tool) != value["tool_sha256"]
            or not state_config_path.is_file()
            or _sha256(state_config_path) != value["state_config_sha256"]
            or not protoc.is_absolute()
            or not protoc.is_file()
            or _sha256(protoc) != value["d0_environment"]["PROTOC_SHA256"]
        ):
            raise ValueError("environment adjustment tool or repository changed")
        required = {
            "--run-id": envelope.run_id,
            "--go-id": envelope.go_id,
            "--cell-id": envelope.cell_id,
            "--attempt": str(attempt_number),
        }
        if len(command) < 4 or command[1] != "run" or "--" not in command:
            raise ValueError("D0 command is not one slk-cargo run")
        separator = command.index("--")
        prefix = command[2:separator]
        for flag, expected in required.items():
            if prefix.count(flag) != 1:
                raise ValueError(f"D0 command does not bind {flag}")
            index = prefix.index(flag)
            if index + 1 >= len(prefix) or prefix[index + 1] != expected:
                raise ValueError(f"D0 command changed {flag}")
        for flag in ("--data-root", "--project-id", "--cargo-program"):
            if prefix.count(flag) != 1:
                raise ValueError(f"D0 command does not bind {flag}")
            index = prefix.index(flag)
            if index + 1 >= len(prefix) or not prefix[index + 1]:
                raise ValueError(f"D0 command changed {flag}")
        data_root = Path(prefix[prefix.index("--data-root") + 1])
        cargo_program = Path(prefix[prefix.index("--cargo-program") + 1])
        command_project_id = prefix[prefix.index("--project-id") + 1]
        config = _read_object(state_config_path, "SLK state config")
        if (
            not data_root.is_absolute()
            or not data_root.is_dir()
            or not cargo_program.is_absolute()
            or not cargo_program.is_file()
            or set(config) != {"schema_version", "data_root"}
            or config.get("schema_version") != "slk.config/v1"
            or Path(str(config.get("data_root"))).resolve() != data_root.resolve()
            or not (data_root / "slk.db").is_file()
            or command_project_id != project_id
        ):
            raise ValueError("D0 command dependencies are unavailable")
        return {
            **value,
            "candidate_repository": str(repository),
            "tool_path": str(tool),
            "state_config_path": str(state_config_path),
        }
    except (CompletionError, OSError, TypeError, ValueError) as exc:
        raise CompletionError(
            "WORKER_PRE_D0_RECOVERY_NOT_READY",
            "pre-D0 environment adjustment is absent, changed, or out of scope",
        ) from exc


def _pre_d0_blocked_source(
    attempt: Path,
    endpoint: Endpoint,
    envelope: Envelope,
    started: Mapping[str, Any],
    environment_path: Path,
    environment_sha256: str,
    *,
    attempt_number: int,
    runtime_projection: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove the one 4.4.2 Windows Cargo blocker without rewriting its evidence."""

    try:
        result_path = attempt / "worker-result.json"
        failed_path = attempt / "failed.json"
        task_path = attempt / "transport-task.json"
        if (
            not result_path.is_file()
            or not failed_path.is_file()
            or not task_path.is_file()
            or (attempt / "completed.json").exists()
        ):
            raise ValueError("blocked source evidence is incomplete")
        result = _read_object(result_path, "blocked Worker result")
        failed = _read_object(failed_path, "blocked Worker terminal")
        blocker = result.get("blocker")
        identity = failed.get("native_identity")
        if (
            set(result)
            != {
                "schema_version", "message_id", "run_id", "role_instance_id", "status",
                "candidate", "next_payload", "blocker",
            }
            or result.get("schema_version") != "slk.worker-result/v1"
            or result.get("message_id") != envelope.message_id
            or result.get("run_id") != envelope.run_id
            or result.get("role_instance_id") != endpoint.role_instance_id
            or result.get("status") != "blocked"
            or result.get("candidate") is not None
            or result.get("next_payload") is not None
            or not isinstance(blocker, Mapping)
            or set(blocker) != {"phase", "cause", "summary", "evidence"}
            or blocker.get("phase") != "D0"
            or blocker.get("cause")
            != "ENVIRONMENT_SLK_CARGO_TARGET_UNC_PREFIX_BREAKS_MSVC_INCLUDE"
            or not isinstance(blocker.get("summary"), str)
            or not blocker["summary"].strip()
            or not isinstance(blocker.get("evidence"), list)
            or not all(isinstance(item, str) and item.strip() for item in blocker["evidence"])
            or failed.get("schema_version") != "slk.transport-result/v1"
            or failed.get("message_id") != envelope.message_id
            or failed.get("run_id") != envelope.run_id
            or failed.get("adapter") != "dsh-worker"
            or failed.get("status") != "failed"
            or failed.get("error_code") != "DSH_WORKER_BLOCKED"
            or not isinstance(identity, Mapping)
            or identity.get("instance_id") != endpoint.address.get("instance_id")
            or identity.get("session_id") != endpoint.address.get("session_id")
            or identity.get("worker_outcome") != "blocked"
            or identity.get("blocker_cause") != blocker.get("cause")
        ):
            raise ValueError("blocked source identity changed")
        session_id = _native_v2_worker_session(attempt / "started.json", endpoint, envelope)
        if session_id != endpoint.address.get("session_id"):
            raise ValueError("blocked source Session changed")
        task_sha256 = started.get("native_request_sha256")
        if not isinstance(task_sha256, str):
            raise ValueError("blocked source task hash is absent")
        task = verify_task_file(task_path.resolve(), task_sha256)
        if (
            Endpoint.from_dict(task["endpoint"]) != endpoint
            or Envelope.from_dict(task["envelope"]) != envelope
            or task.get("result_path")
            != str(
                (
                    Path(str(endpoint.address["cwd"]))
                    / ".slk-transport"
                    / envelope.message_id
                    / "worker-result.json"
                ).resolve()
            )
        ):
            raise ValueError("blocked source task changed")
        summary = runtime_projection.get("summary")
        administrative = runtime_projection.get("administrative_snapshot")
        project_id = summary.get("project_id") if isinstance(summary, Mapping) else None
        if (
            not isinstance(project_id, str)
            or not project_id
            or not isinstance(administrative, Mapping)
            or administrative.get("project_id") != project_id
        ):
            raise ValueError("Run project identity is unavailable")
        environment = _pre_d0_environment(
            environment_path,
            environment_sha256,
            envelope=envelope,
            attempt_number=attempt_number,
            project_id=project_id,
        )
        repository = Path(str(environment["candidate_repository"])).resolve()
        if repository != Path(str(endpoint.address["cwd"])).resolve():
            raise ValueError("candidate repository changed")
        snapshot = _candidate_repository_snapshot(repository)
        if snapshot["head"] != environment["candidate_commit"]:
            raise ValueError("candidate commit changed")
        return {
            "result": result,
            "failed": failed,
            "session_id": session_id,
            "environment": environment,
            "environment_path": str(environment_path),
            "environment_sha256": environment_sha256,
            "project_id": project_id,
            **snapshot,
        }
    except (AdapterError, CompletionError, KeyError, OSError, TaskFileError, TypeError, ValueError) as exc:
        if isinstance(exc, CompletionError) and exc.error_code == "WORKER_PRE_D0_RECOVERY_NOT_READY":
            raise
        raise CompletionError(
            "WORKER_PRE_D0_RECOVERY_NOT_READY",
            "source is not the exact preserved pre-D0 Windows Cargo blocker",
        ) from exc


def _continuation_root(request: Mapping[str, Any]) -> Path:
    name = {
        "INVALID_RESULT_CONTRACT": "invalid-result-supplement",
        "PRE_D0_BLOCKED_RECOVERY": "pre-d0-blocked-recovery",
    }.get(str(request.get("recovery_mode")), "worker-continuation")
    return Path(str(request["source_attempt_root"])) / name


def _native_v2_worker_session(
    started_path: Path,
    endpoint: Endpoint,
    envelope: Envelope,
) -> str | None:
    try:
        started = validate_native_start(
            started_path,
            adapter=endpoint.adapter,
            run_id=envelope.run_id,
            cell_id=envelope.cell_id,
            message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256,
        )
    except NativeActivityError:
        return None
    native_task = started["native_task"]
    if native_task["kind"] != "dsh-session":
        return None
    session_id = native_task["id"]
    return session_id if isinstance(session_id, str) else None


def _legacy_completed_worker_session(
    attempt: Path,
    endpoint: Endpoint,
    envelope: Envelope,
    started: Mapping[str, Any],
    completed: Mapping[str, Any] | None,
    result: Mapping[str, Any] | None,
    runtime_projection: Mapping[str, Any],
    *,
    attempt_number: int,
    candidate_message_id: str,
    checker_token_already_committed: bool,
) -> str | None:
    """Read one closed 4.3.4 start only after its completed candidate already owns Checker TOKEN."""

    if (
        not checker_token_already_committed
        or completed is None
        or result is None
        or set(started) != _LEGACY_WORKER_START_FIELDS
        or started.get("status") != "started"
        or started.get("message_id") != envelope.message_id
        or started.get("run_id") != envelope.run_id
        or started.get("instance_id") != endpoint.address.get("instance_id")
    ):
        return None
    session_id = started.get("session_id")
    native_identity = completed.get("native_identity")
    if (
        not isinstance(session_id, str)
        or not session_id.startswith("session-")
        or set(completed)
        != {
            "schema_version",
            "message_id",
            "run_id",
            "adapter",
            "status",
            "native_identity",
            "error_code",
            "evidence",
        }
        or completed.get("schema_version") != "slk.transport-result/v1"
        or completed.get("message_id") != envelope.message_id
        or completed.get("run_id") != envelope.run_id
        or completed.get("adapter") != "dsh-worker"
        or completed.get("status") != "completed"
        or completed.get("error_code") is not None
        or completed.get("evidence")
        != ["started.json", "worker-result.json", "native.stdout.txt", "native.stderr.txt"]
        or not isinstance(native_identity, Mapping)
        or set(native_identity)
        != {"instance_id", "session_id", "exit_code", "worker_outcome", "blocker_cause"}
        or native_identity.get("instance_id") != endpoint.address.get("instance_id")
        or native_identity.get("session_id") != session_id
        or native_identity.get("exit_code") != 0
        or native_identity.get("worker_outcome") != "completed"
        or native_identity.get("blocker_cause") is not None
    ):
        return None
    task_path = attempt / "transport-task.json"
    try:
        task = verify_task_file(task_path.resolve(), str(started.get("task_sha256")))
        task_endpoint = Endpoint.from_dict(task["endpoint"])
        task_envelope = Envelope.from_dict(task["envelope"])
        from .adapters.dsh import DshAdapter

        expected_result_path = (
            Path(str(endpoint.address["cwd"]))
            / ".slk-transport"
            / envelope.message_id
            / "worker-result.json"
        ).resolve()
        task_matches = (
            task_endpoint == endpoint
            and task_envelope == envelope
            and task.get("message_id") == envelope.message_id
            and task.get("run_id") == envelope.run_id
            and task.get("go_id") == envelope.go_id
            and task.get("cell_id") == envelope.cell_id
            and json.dumps(task.get("result_contract"), sort_keys=True)
            in {
                json.dumps(DshAdapter().result_contract(endpoint, envelope), sort_keys=True),
                json.dumps(DshAdapter().legacy_result_contract(endpoint, envelope), sort_keys=True),
            }
            and task.get("result_path") == str(expected_result_path)
        )
    except (KeyError, TypeError, ValueError, TaskFileError):
        return None
    candidate = result.get("candidate")
    if not task_matches or not isinstance(candidate, Mapping):
        return None
    candidate_submitted, transport_started = _exact_worker_handoff(
        runtime_projection,
        cell_id=envelope.cell_id,
        attempt=attempt_number,
        candidate=candidate,
        source_message_id=envelope.message_id,
        handoff_message_id=candidate_message_id,
    )
    return session_id if candidate_submitted and transport_started else None


def _incomplete_handoff_evidence(attempt: Path, staged: Path, d0_path: Path) -> dict[str, Any]:
    """Verify preserved clues against files and Git, not the blocker's prose claim."""
    from .adapters.dsh import DshAdapter

    try:
        endpoint = Endpoint.from_dict(_read_object(attempt / "endpoint.json", "Worker endpoint"))
        source = Envelope.from_dict(_read_object(attempt / "envelope.json", "Worker envelope"))
        result = DshAdapter()._read_result(attempt / "worker-result.json", endpoint, source)
        terminal = DeliveryResult.from_dict(_read_object(attempt / "failed.json", "Worker terminal"))
        _native_v2_worker_session(attempt / "started.json", endpoint, source)
        if (result["status"] != "incomplete" or terminal.status != "failed"
            or terminal.run_id != source.run_id or terminal.message_id != source.message_id
            or terminal.adapter != "dsh-worker" or (attempt / "completed.json").exists()
            or result["blocker"]["phase"] != "worker-suffix-handoff"
            or result["blocker"]["cause"] != "ENVIRONMENT_SANDBOX_WRITE_DENIED"):
            raise ValueError("not a preserved handoff-only INCOMPLETE")
        references: dict[Path, str] = {}
        for clue in result["blocker"]["evidence"]:
            match = re.fullmatch(r"(.+?) sha256=([0-9a-f]{64})(?: \(.*\))?", clue)
            if match and Path(match[1]).is_absolute():
                path = Path(match[1]).resolve()
                if path in references and references[path] != match[2]:
                    raise ValueError("conflicting immutable evidence hashes")
                references[path] = match[2]

        def bound(path: Path) -> dict[str, str]:
            path = path.resolve()
            if path not in references or not path.is_file() or _sha256(path) != references[path]:
                raise ValueError("preserved evidence is absent or changed")
            return {"path": str(path), "sha256": references[path]}

        staged_ref, d0_ref = bound(staged), bound(d0_path)
        prepared = Envelope.from_dict(_read_object(staged, "preserved candidate envelope"))
        d0 = _read_object(d0_path, "preserved D0 request")
        if (prepared.run_id != source.run_id or prepared.go_id != source.go_id
            or prepared.message_id != _stable_id(source.message_id, "candidate-ready")
            or prepared.cell_id != source.cell_id or prepared.sender_role != "worker"
            or prepared.sender_role_instance_id != endpoint.role_instance_id
            or prepared.receiver_role != "checker" or prepared.payload_type != "CANDIDATE_READY"
            or prepared.token_sequence != source.token_sequence + 1
            or d0.get("event_type") != "D0_COMPLETED" or d0.get("corrects_event_id") is not None
            or any(d0.get(k) != getattr(source, k) for k in ("run_id", "go_id", "cell_id"))
            or d0.get("role_instance_id") != endpoint.role_instance_id):
            raise ValueError("preserved handoff changed scope or role")
        payload = prepared.payload
        if set(payload) != {"repository", "candidate", "cell_goal", "d1_criteria", "evidence_files"}:
            raise ValueError("candidate payload is not closed")
        repo = Path(payload["repository"]).resolve()
        snapshot = _candidate_repository_snapshot(repo)
        details = d0["details"]
        candidate = {"kind": "commit", "commit": snapshot["head"]}
        criteria = source.payload.get("d1_criteria", source.payload.get("acceptance_criteria"))
        if (repo != Path(endpoint.address["cwd"]).resolve()
            or payload["candidate"] != candidate or details.get("candidate") != candidate
            or details.get("baseline_commit") != snapshot["parent"]
            or sorted(details.get("changed_paths", [])) != snapshot["changed_paths"]
            or not details.get("d0") or not isinstance(details.get("unproved"), list)
            or payload["cell_goal"] != source.payload.get("cell_goal")
            or not criteria or payload["d1_criteria"] != criteria):
            raise ValueError("candidate, parent, changed paths or frozen criteria differ")
        proofs = []
        for item in payload["evidence_files"]:
            path = Path(item).resolve()
            # The Worker's copied terminal can also be an original evidence file.
            if path.is_file() and path.read_bytes() == (attempt / "worker-result.json").read_bytes():
                proofs.append({"path": str(path), "sha256": _sha256(path)})
            else:
                proofs.append(bound(path))
        if not proofs:
            raise ValueError("D0 evidence is missing")
        return {
            "schema_version": "slk.worker-handoff-evidence/v1", "status": "HANDOFF_EVIDENCE_VERIFIED",
            "run_id": source.run_id, "go_id": source.go_id, "cell_id": source.cell_id,
            "source_message_id": source.message_id, "role_instance_id": endpoint.role_instance_id,
            "source_result_sha256": _sha256(attempt / "worker-result.json"),
            "source_terminal_sha256": _sha256(attempt / "failed.json"),
            "staged_envelope": staged_ref, "d0_request": d0_ref, "evidence": proofs,
            "candidate": candidate, "parent_commit": snapshot["parent"],
            "candidate_repository": str(repo), "changed_paths": snapshot["changed_paths"],
            "d0": details["d0"], "unproved": details["unproved"],
            "attempt": d0["attempt"], "plan_revision": d0["plan_revision"],
            "checker_role_instance_id": prepared.receiver_role_instance_id,
            "checker_endpoint_version": prepared.receiver_endpoint_version,
        }
    except (OSError, KeyError, TypeError, ValueError, AdapterError) as exc:
        raise CompletionError("WORKER_INCOMPLETE_EVIDENCE_INVALID", "preserved handoff evidence failed verification") from exc


def prepare_incomplete_worker_handoff(
    source_attempt_root: Path | str, *, staged_envelope_path: Path | str, d0_request_path: Path | str,
) -> dict[str, Any]:
    """Prepare a new host supplement; original INCOMPLETE and failed attempt stay untouched."""
    attempt = Path(source_attempt_root).resolve()
    evidence = _incomplete_handoff_evidence(attempt, Path(staged_envelope_path), Path(d0_request_path))
    destination = attempt / "incomplete-handoff" / "evidence.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_or_reuse_stable_request(destination, evidence)
    return evidence


def _load_incomplete_handoff(attempt: Path) -> dict[str, Any]:
    evidence = _read_object(attempt / "incomplete-handoff" / "evidence.json", "incomplete handoff supplement")
    try:
        verified = _incomplete_handoff_evidence(
            attempt, Path(evidence["staged_envelope"]["path"]), Path(evidence["d0_request"]["path"]),
        )
    except (KeyError, TypeError) as exc:
        raise CompletionError("WORKER_INCOMPLETE_EVIDENCE_INVALID", "incomplete handoff supplement is not closed") from exc
    if verified != evidence:
        raise CompletionError("WORKER_INCOMPLETE_EVIDENCE_INVALID", "incomplete handoff supplement changed")
    return evidence


def build_continuation_request(
    attempt_root: Path | str,
    checker_endpoint_raw: Mapping[str, Any],
    runtime_projection: Mapping[str, Any],
    *,
    plan_revision: int,
    runtime_revision: int,
    token_sequence: int,
    credential_path: Path | str,
    state_command: list[str],
    transport_command: list[str],
    occurred_at: str,
    temporal: Mapping[str, Any] | None = None,
    environment_adjustment_path: Path | str | None = None,
    environment_adjustment_sha256: str | None = None,
) -> dict[str, Any]:
    """Build one immutable request for the already-started DSH Worker Session."""

    attempt = Path(attempt_root).resolve()
    endpoint_path = attempt / "endpoint.json"
    envelope_path = attempt / "envelope.json"
    started_path = attempt / "started.json"
    result_path = attempt / "worker-result.json"
    completed_path = attempt / "completed.json"
    endpoint = Endpoint.from_dict(_read_object(endpoint_path, "Worker endpoint"))
    envelope = Envelope.from_dict(_read_object(envelope_path, "Worker envelope"))
    checker = Endpoint.from_dict(checker_endpoint_raw)
    started = _read_object(started_path, "Worker started evidence")
    attempt_number = _source_attempt(runtime_projection, envelope)
    missing_result_failure = _missing_result_failure(attempt, envelope)
    invalid_result_source = _invalid_result_contract_source(attempt, endpoint, envelope, started)
    pre_d0_source = None
    if environment_adjustment_path is not None or environment_adjustment_sha256 is not None:
        if (
            environment_adjustment_path is None
            or not isinstance(environment_adjustment_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", environment_adjustment_sha256)
        ):
            raise CompletionError(
                "WORKER_PRE_D0_RECOVERY_NOT_READY",
                "environment adjustment path and SHA-256 must be supplied together",
            )
        pre_d0_source = _pre_d0_blocked_source(
            attempt,
            endpoint,
            envelope,
            started,
            Path(environment_adjustment_path).resolve(),
            environment_adjustment_sha256,
            attempt_number=attempt_number,
            runtime_projection=runtime_projection,
        )
    source_task_sha256: str | None = None
    source_started_sha256: str | None = None
    source_invalid_result_sha256: str | None = None
    source_candidate: dict[str, Any] | None = None
    source_candidate_parent: str | None = None
    source_repository: str | None = None
    source_changed_paths: list[str] | None = None
    supplement_result_contract: dict[str, Any] | None = None
    source_blocked_result_sha256: str | None = None
    bound_environment_path: str | None = None
    bound_environment_sha256: str | None = None
    source_project_id: str | None = None
    incomplete_evidence = None
    if pre_d0_source is not None:
        recovery_mode = "PRE_D0_BLOCKED_RECOVERY"
        result = completed = None
        continuation_result_path = (
            attempt / "pre-d0-blocked-recovery" / "recovered-worker-result.json"
        )
        worker_result_sha256 = None
        source_terminal_path = attempt / "failed.json"
        source_task_sha256 = _sha256(attempt / "transport-task.json")
        source_started_sha256 = _sha256(started_path)
        source_candidate = {"kind": "commit", "commit": pre_d0_source["head"]}
        source_candidate_parent = str(pre_d0_source["parent"])
        source_repository = str(pre_d0_source["repository"])
        source_changed_paths = list(pre_d0_source["changed_paths"])
        supplement_result_contract = dict(INVALID_SUPPLEMENT_RESULT_CONTRACT)
        source_blocked_result_sha256 = _sha256(result_path)
        bound_environment_path = str(pre_d0_source["environment_path"])
        bound_environment_sha256 = str(pre_d0_source["environment_sha256"])
        source_project_id = str(pre_d0_source["project_id"])
    elif result_path.is_file() and completed_path.is_file():
        recovery_mode = "COMPLETED_RESULT"
        result = _read_object(result_path, "Worker result")
        completed = _read_object(completed_path, "Worker terminal result")
        continuation_result_path = result_path
        worker_result_sha256: str | None = _sha256(result_path)
        source_terminal_path = completed_path
    elif result_path.is_file() and (attempt / "incomplete-handoff" / "evidence.json").is_file():
        incomplete_evidence = _load_incomplete_handoff(attempt)
        recovery_mode = "INCOMPLETE_HANDOFF"
        result = completed = None
        continuation_result_path = attempt / "incomplete-handoff" / "evidence.json"
        worker_result_sha256 = _sha256(continuation_result_path)
        source_terminal_path = attempt / "failed.json"
    elif missing_result_failure is not None:
        recovery_mode = "MISSING_RESULT"
        result = None
        completed = None
        continuation_result_path = attempt / "worker-continuation" / "recovered-worker-result.json"
        worker_result_sha256 = None
        source_terminal_path = attempt / "failed.json"
    elif invalid_result_source is not None:
        recovery_mode = "INVALID_RESULT_CONTRACT"
        result = None
        completed = None
        continuation_result_path = (
            attempt / "invalid-result-supplement" / "recovered-worker-result.json"
        )
        worker_result_sha256 = None
        source_terminal_path = attempt / "failed.json"
        source_task_sha256 = _sha256(attempt / "transport-task.json")
        source_started_sha256 = _sha256(started_path)
        source_invalid_result_sha256 = _sha256(attempt / "worker-result.invalid.txt")
        source_candidate = dict(invalid_result_source["candidate"])
        source_candidate_parent = str(invalid_result_source["parent"])
        source_repository = str(invalid_result_source["repository"])
        source_changed_paths = list(invalid_result_source["changed_paths"])
        supplement_result_contract = dict(INVALID_SUPPLEMENT_RESULT_CONTRACT)
    else:
        raise CompletionError(
            "WORKER_CONTINUATION_NOT_READY",
            "Worker attempt has no exact recoverable completed, missing, or invalid-result source",
        )
    if incomplete_evidence is not None and (
        incomplete_evidence["attempt"] != attempt_number or incomplete_evidence["plan_revision"] != plan_revision
        or incomplete_evidence["checker_role_instance_id"] != checker.role_instance_id
        or incomplete_evidence["checker_endpoint_version"] != checker.endpoint_version
    ):
        raise CompletionError("WORKER_INCOMPLETE_EVIDENCE_INVALID", "supplement does not bind the frozen plan or Checker")
    snapshot = runtime_projection.get("runtime_snapshot")
    try:
        token_boundary = resolve_authoritative_token_boundary(
            runtime_projection, run_id=envelope.run_id, plan_revision=plan_revision,
        )
    except CompletionError as exc:
        raise CompletionError("WORKER_CONTINUATION_NOT_READY",
                              "current Worker TOKEN boundary is not authoritative") from exc
    boundary_message_id = token_boundary["message_id"]
    candidate_message_id = _stable_id(envelope.message_id, "candidate-ready")
    checker_token_already_committed = (
        isinstance(snapshot, Mapping)
        and snapshot.get("token_holder_role_instance_id") == checker.role_instance_id
        and boundary_message_id == candidate_message_id
    )
    worker_holds_source_token = (
        isinstance(snapshot, Mapping)
        and snapshot.get("token_holder_role_instance_id") == endpoint.role_instance_id
        and boundary_message_id == envelope.message_id
    )
    if recovery_mode in {"INVALID_RESULT_CONTRACT", "PRE_D0_BLOCKED_RECOVERY"}:
        source_event_types = _event_types(
            runtime_projection,
            cell_id=envelope.cell_id,
            attempt=attempt_number,
        )
        if (
            not worker_holds_source_token
            or checker_token_already_committed
            or source_event_types & {"WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED"}
        ):
            raise CompletionError(
                "WORKER_CONTINUATION_NOT_READY",
                "recovery requires the original Worker TOKEN and no Worker engineering facts",
            )
    session_id = (
        _native_v2_worker_session(started_path, endpoint, envelope)
        if started.get("schema_version") == "slk.native-start/v2"
        else _legacy_completed_worker_session(
            attempt,
            endpoint,
            envelope,
            started,
            completed,
            result,
            runtime_projection,
            attempt_number=attempt_number,
            candidate_message_id=candidate_message_id,
            checker_token_already_committed=checker_token_already_committed,
        )
        if recovery_mode == "COMPLETED_RESULT"
        else None
    )
    configured_session_id = endpoint.address.get("session_id")
    if (
        endpoint.role != "worker"
        or envelope.receiver_role != "worker"
        or endpoint.role_instance_id != envelope.receiver_role_instance_id
        or checker.role != "checker"
        or checker.run_id != envelope.run_id
        or not isinstance(session_id, str)
        or not session_id.startswith("session-")
        or (configured_session_id is not None and session_id != configured_session_id)
        or (
            recovery_mode == "COMPLETED_RESULT"
            and (
                completed is None
                or result is None
                or completed.get("status") != "completed"
                or result.get("status") != "completed"
                or result.get("message_id") != envelope.message_id
                or result.get("role_instance_id") != endpoint.role_instance_id
            )
        )
        or not isinstance(snapshot, Mapping)
        or snapshot.get("method_version") not in SUPPORTED_METHOD_VERSIONS
        or runtime_projection.get("summary", {}).get("slk_version") != snapshot.get("method_version")
        or snapshot.get("plan_revision") != plan_revision
        or snapshot.get("runtime_revision") != runtime_revision
        or snapshot.get("token_sequence") != token_sequence
        or not (worker_holds_source_token or checker_token_already_committed)
    ):
        raise CompletionError(
            "WORKER_CONTINUATION_NOT_READY",
            "terminal Worker evidence, exact Session, Run, or Checker binding does not match",
        )
    if (
        isinstance(plan_revision, bool)
        or plan_revision < 1
        or isinstance(runtime_revision, bool)
        or runtime_revision < 1
        or isinstance(token_sequence, bool)
        or token_sequence < 1
        or not state_command
        or not transport_command
        or not all(isinstance(item, str) and item for item in state_command + transport_command)
    ):
        raise CompletionError("WORKER_CONTINUATION_NOT_READY", "closed commands and positive revisions are required")
    _timestamp(occurred_at)
    credential = Path(credential_path).resolve()
    temporal_binding = validate_temporal_binding(temporal, envelope.run_id) if temporal is not None else None
    result = {
        "schema_version": (
            CONTINUATION_SCHEMA_V3
            if recovery_mode == "PRE_D0_BLOCKED_RECOVERY"
            else CONTINUATION_SCHEMA_V2
            if temporal_binding is not None
            else CONTINUATION_SCHEMA
        ),
        "method_version": snapshot["method_version"],
        "run_id": envelope.run_id,
        "go_id": envelope.go_id,
        "cell_id": envelope.cell_id,
        "attempt": attempt_number,
        "plan_revision": plan_revision,
        "runtime_revision": runtime_revision,
        "source_message_id": envelope.message_id,
        "source_attempt_root": str(attempt),
        "continuation_result_path": str(
            attempt
            / {
                "INVALID_RESULT_CONTRACT": "invalid-result-supplement",
                "PRE_D0_BLOCKED_RECOVERY": "pre-d0-blocked-recovery",
            }.get(recovery_mode, "worker-continuation")
            / "result.json"
        ),
        "source_endpoint_sha256": _sha256(endpoint_path),
        "source_envelope_sha256": _sha256(envelope_path),
        "source_runtime_projection_sha256": canonical_json_sha256(runtime_projection),
        "source_runtime_snapshot": {
            field: (boundary_message_id if field == "latest_message_id" else snapshot.get(field))
            for field in (
                "method_version",
                "plan_revision",
                "runtime_revision",
                "token_sequence",
                "token_holder_role_instance_id",
                "latest_message_id",
            )
        },
        "recovery_mode": recovery_mode,
        "worker_result_path": str(continuation_result_path.resolve()),
        "worker_result_sha256": worker_result_sha256,
        "source_terminal_sha256": _sha256(source_terminal_path),
        "source_task_sha256": source_task_sha256,
        "source_started_sha256": source_started_sha256,
        "source_invalid_result_sha256": source_invalid_result_sha256,
        "source_candidate": source_candidate,
        "source_candidate_parent": source_candidate_parent,
        "source_repository": source_repository,
        "source_changed_paths": source_changed_paths,
        "supplement_result_contract": supplement_result_contract,
        "worker_role_instance_id": endpoint.role_instance_id,
        "worker_instance_id": str(endpoint.address["instance_id"]),
        "worker_session_id": session_id,
        "checker_endpoint": dict(checker_endpoint_raw),
        "credential_path": str(credential),
        "state_command": list(state_command),
        "transport_command": list(transport_command),
        "token_sequence": token_sequence,
        "checker_token_already_committed": checker_token_already_committed,
        "occurred_at": occurred_at,
    }
    if recovery_mode == "PRE_D0_BLOCKED_RECOVERY":
        result.update(
            {
                "source_blocked_result_sha256": source_blocked_result_sha256,
                "source_project_id": source_project_id,
                "environment_adjustment_path": bound_environment_path,
                "environment_adjustment_sha256": bound_environment_sha256,
            }
        )
    if temporal_binding is not None:
        result["temporal"] = temporal_binding
    return result


def continuation_request_bytes(request: Mapping[str, Any]) -> bytes:
    return (json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _validate_continuation_request(request: Mapping[str, Any]) -> None:
    version = request.get("schema_version")
    fields = (
        CONTINUATION_V2_FIELDS
        if version == CONTINUATION_SCHEMA_V2
        else PRE_D0_CONTINUATION_FIELDS
        if version == CONTINUATION_SCHEMA_V3
        else CONTINUATION_FIELDS
    )
    if (
        set(request) != fields
        or version not in {CONTINUATION_SCHEMA, CONTINUATION_SCHEMA_V2, CONTINUATION_SCHEMA_V3}
        or request.get("method_version") not in SUPPORTED_METHOD_VERSIONS
    ):
        raise CompletionError("WORKER_CONTINUATION_INVALID", "continuation request is not closed")
    if version == CONTINUATION_SCHEMA_V2:
        validate_temporal_binding(request.get("temporal"), str(request.get("run_id")))
    snapshot = request.get("source_runtime_snapshot")
    snapshot_fields = {
        "method_version",
        "plan_revision",
        "runtime_revision",
        "token_sequence",
        "token_holder_role_instance_id",
        "latest_message_id",
    }
    if (
        not isinstance(snapshot, Mapping)
        or set(snapshot) != snapshot_fields
        or snapshot.get("method_version") != request["method_version"]
        or snapshot.get("plan_revision") != request.get("plan_revision")
        or snapshot.get("runtime_revision") != request.get("runtime_revision")
        or snapshot.get("token_sequence") != request.get("token_sequence")
    ):
        raise CompletionError("WORKER_CONTINUATION_INVALID", "frozen runtime snapshot is inconsistent")
    if request.get("recovery_mode") in {"INVALID_RESULT_CONTRACT", "PRE_D0_BLOCKED_RECOVERY"}:
        pre_d0 = request.get("recovery_mode") == "PRE_D0_BLOCKED_RECOVERY"
        if (
            snapshot.get("token_holder_role_instance_id") != request.get("worker_role_instance_id")
            or snapshot.get("latest_message_id") != request.get("source_message_id")
            or request.get("checker_token_already_committed") is not False
            or request.get("supplement_result_contract") != INVALID_SUPPLEMENT_RESULT_CONTRACT
            or not all(
                request.get(field) is not None
                for field in (
                    "source_task_sha256",
                    "source_started_sha256",
                    "source_candidate",
                    "source_candidate_parent",
                    "source_repository",
                    "source_changed_paths",
                )
            )
            or (
                not pre_d0
                and request.get("source_invalid_result_sha256") is None
            )
            or (pre_d0 and version != CONTINUATION_SCHEMA_V3)
            or (
                pre_d0
                and (
                    not isinstance(request.get("source_blocked_result_sha256"), str)
                    or not SHA256.fullmatch(str(request["source_blocked_result_sha256"]))
                    or not isinstance(request.get("environment_adjustment_path"), str)
                    or not Path(str(request["environment_adjustment_path"])).is_absolute()
                    or not isinstance(request.get("environment_adjustment_sha256"), str)
                    or not SHA256.fullmatch(str(request["environment_adjustment_sha256"]))
                    or not isinstance(request.get("source_project_id"), str)
                    or not str(request["source_project_id"]).strip()
                )
            )
            or (not pre_d0 and version == CONTINUATION_SCHEMA_V3)
        ):
            raise CompletionError(
                "WORKER_CONTINUATION_INVALID",
                "recovery does not bind the original Worker snapshot",
            )
    elif request.get("recovery_mode") in {"COMPLETED_RESULT", "MISSING_RESULT", "INCOMPLETE_HANDOFF"}:
        if request.get("supplement_result_contract") is not None:
            raise CompletionError("WORKER_CONTINUATION_INVALID", "ordinary continuation has supplement fields")
    else:
        raise CompletionError("WORKER_CONTINUATION_INVALID", "continuation recovery mode is invalid")


def prepare_invalid_result_recovery_envelope(
    source_attempt_root: Path | str,
    checker_endpoint_raw: Mapping[str, Any],
    runtime_projection_path: Path | str,
    *,
    supervisor_role_instance_id: str,
    plan_revision: int,
    runtime_revision: int,
    token_sequence: int,
    worker_credential_path: Path | str,
    checker_credential_path: Path | str,
    state_command: list[str],
    transport_command: list[str],
    occurred_at: str,
    output_path: Path | str,
) -> dict[str, Any]:
    """Read-only preflight that materializes one authenticated Checker recovery envelope."""

    projection_path = Path(runtime_projection_path).resolve()
    projection = _read_object(projection_path, "runtime projection")
    checker = Endpoint.from_dict(checker_endpoint_raw)
    worker_credential = Path(worker_credential_path).resolve()
    checker_credential = Path(checker_credential_path).resolve()
    if (
        checker.role != "checker"
        or not worker_credential.is_file()
        or not checker_credential.is_file()
        or not projection_path.is_file()
    ):
        raise CompletionError(
            "WORKER_CONTINUATION_NOT_READY",
            "active Checker, runtime projection, and sealed role credentials are required",
        )
    continuation = build_continuation_request(
        source_attempt_root,
        checker_endpoint_raw,
        projection,
        plan_revision=plan_revision,
        runtime_revision=runtime_revision,
        token_sequence=token_sequence,
        credential_path=worker_credential,
        state_command=state_command,
        transport_command=transport_command,
        occurred_at=occurred_at,
    )
    if continuation.get("recovery_mode") != "INVALID_RESULT_CONTRACT":
        raise CompletionError(
            "WORKER_CONTINUATION_NOT_READY",
            "prepare entry accepts only an exact invalid-result contract source",
        )
    source_message_id = str(continuation["source_message_id"])
    payload = {
        "source_attempt_root": str(Path(source_attempt_root).resolve()),
        "runtime_projection_path": str(projection_path),
        "plan_revision": plan_revision,
        "runtime_revision": runtime_revision,
        "token_sequence": token_sequence,
        "worker_credential_path": str(worker_credential),
        "checker_credential_path": str(checker_credential),
        "state_command": list(state_command),
        "transport_command": list(transport_command),
        "occurred_at": occurred_at,
    }
    envelope = {
        "schema_version": ENVELOPE_SCHEMA,
        "message_id": _stable_id(source_message_id, "invalid-result-contract-recovery"),
        "token_sequence": token_sequence,
        "run_id": continuation["run_id"],
        "go_id": continuation["go_id"],
        "cell_id": continuation["cell_id"],
        "sender_role": "supervisor",
        "sender_role_instance_id": supervisor_role_instance_id,
        "receiver_role": "checker",
        "receiver_role_instance_id": checker.role_instance_id,
        "receiver_endpoint_version": checker.endpoint_version,
        "payload_type": "WORKER_COMPLETION_RECOVERY",
        "payload_sha256": canonical_json_sha256(payload),
        "payload": payload,
    }
    Envelope.from_dict(envelope)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_or_reuse_stable_request(destination, envelope)
    return {
        "schema_version": "slk.invalid-result-recovery-readiness/v1",
        "method_version": continuation["method_version"],
        "status": "INVALID_RESULT_RECOVERY_READY",
        "run_id": continuation["run_id"],
        "cell_id": continuation["cell_id"],
        "source_message_id": source_message_id,
        "recovery_message_id": envelope["message_id"],
        "recovery_mode": continuation["recovery_mode"],
        "candidate": continuation["source_candidate"],
        "worker_session_id": continuation["worker_session_id"],
        "runtime_revision": runtime_revision,
        "token_sequence": token_sequence,
        "envelope_path": str(destination),
        "envelope_sha256": _sha256(destination),
    }


def prepare_pre_d0_blocked_recovery_envelope(
    source_attempt_root: Path | str,
    checker_endpoint_raw: Mapping[str, Any],
    runtime_projection_path: Path | str,
    *,
    supervisor_role_instance_id: str,
    plan_revision: int,
    runtime_revision: int,
    token_sequence: int,
    worker_credential_path: Path | str,
    checker_credential_path: Path | str,
    state_command: list[str],
    transport_command: list[str],
    environment_adjustment_path: Path | str,
    environment_adjustment_sha256: str,
    occurred_at: str,
    output_path: Path | str,
) -> dict[str, Any]:
    """Prepare one read-only Supervisor→original-Checker pre-D0 recovery envelope."""

    try:
        projection_path = Path(runtime_projection_path).resolve()
        projection = _read_object(projection_path, "runtime projection")
        checker = Endpoint.from_dict(checker_endpoint_raw)
        worker_credential = Path(worker_credential_path).resolve()
        checker_credential = Path(checker_credential_path).resolve()
        environment_path = Path(environment_adjustment_path).resolve()
        if (
            checker.role != "checker"
            or not worker_credential.is_file()
            or not checker_credential.is_file()
            or not projection_path.is_file()
            or not environment_path.is_file()
            or not isinstance(supervisor_role_instance_id, str)
            or not supervisor_role_instance_id.strip()
        ):
            raise ValueError("required recovery identity or evidence is absent")
        continuation = build_continuation_request(
            source_attempt_root,
            checker_endpoint_raw,
            projection,
            plan_revision=plan_revision,
            runtime_revision=runtime_revision,
            token_sequence=token_sequence,
            credential_path=worker_credential,
            state_command=state_command,
            transport_command=transport_command,
            occurred_at=occurred_at,
            environment_adjustment_path=environment_path,
            environment_adjustment_sha256=environment_adjustment_sha256,
        )
        if continuation.get("recovery_mode") != "PRE_D0_BLOCKED_RECOVERY":
            raise ValueError("source is not the exact pre-D0 blocked recovery")
        source_message_id = str(continuation["source_message_id"])
        payload = {
            "source_attempt_root": str(Path(source_attempt_root).resolve()),
            "runtime_projection_path": str(projection_path),
            "plan_revision": plan_revision,
            "runtime_revision": runtime_revision,
            "token_sequence": token_sequence,
            "worker_credential_path": str(worker_credential),
            "checker_credential_path": str(checker_credential),
            "state_command": list(state_command),
            "transport_command": list(transport_command),
            "environment_adjustment_path": str(environment_path),
            "environment_adjustment_sha256": environment_adjustment_sha256,
            "occurred_at": occurred_at,
        }
        envelope = {
            "schema_version": ENVELOPE_SCHEMA,
            "message_id": _stable_id(source_message_id, "pre-d0-blocked-recovery"),
            "token_sequence": token_sequence,
            "run_id": continuation["run_id"],
            "go_id": continuation["go_id"],
            "cell_id": continuation["cell_id"],
            "sender_role": "supervisor",
            "sender_role_instance_id": supervisor_role_instance_id,
            "receiver_role": "checker",
            "receiver_role_instance_id": checker.role_instance_id,
            "receiver_endpoint_version": checker.endpoint_version,
            "payload_type": "PRE_D0_BLOCKED_RECOVERY",
            "payload_sha256": canonical_json_sha256(payload),
            "payload": payload,
        }
        Envelope.from_dict(envelope)
        destination = Path(output_path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_or_reuse_stable_request(destination, envelope)
        return {
            "schema_version": "slk.pre-d0-blocked-recovery-readiness/v1",
            "method_version": continuation["method_version"],
            "status": "PRE_D0_BLOCKED_RECOVERY_READY",
            "run_id": continuation["run_id"],
            "cell_id": continuation["cell_id"],
            "source_message_id": source_message_id,
            "recovery_message_id": envelope["message_id"],
            "recovery_mode": continuation["recovery_mode"],
            "candidate": continuation["source_candidate"],
            "worker_session_id": continuation["worker_session_id"],
            "runtime_revision": runtime_revision,
            "token_sequence": token_sequence,
            "envelope_path": str(destination),
            "envelope_sha256": _sha256(destination),
        }
    except (AdapterError, CompletionError, ContractError, KeyError, OSError, TypeError, ValueError) as exc:
        if isinstance(exc, CompletionError) and exc.error_code == "WORKER_CONTINUATION_CONFLICT":
            raise
        raise CompletionError(
            "WORKER_PRE_D0_RECOVERY_NOT_READY",
            "pre-D0 blocked recovery identity, evidence, runtime, or environment is not exact",
        ) from exc


def resume_worker_continuation(request: Mapping[str, Any]) -> dict[str, Any]:
    """Resume exactly the recorded DSH Session and let it execute one bounded suffix."""

    _validate_continuation_request(request)
    from .adapters.dsh import DshAdapter, _positive_seconds
    from .process import windows_no_window_kwargs
    from .subprocess_watch import finish, spawn

    attempt = Path(str(request["source_attempt_root"]))
    endpoint_path = attempt / "endpoint.json"
    envelope_path = attempt / "envelope.json"
    endpoint = Endpoint.from_dict(_read_object(endpoint_path, "Worker endpoint"))
    if (
        _sha256(endpoint_path) != request.get("source_endpoint_sha256")
        or _sha256(envelope_path) != request.get("source_envelope_sha256")
        or endpoint.role_instance_id != request.get("worker_role_instance_id")
        or endpoint.address.get("instance_id") != request.get("worker_instance_id")
    ):
        raise CompletionError(
            "WORKER_CONTINUATION_SOURCE_CHANGED",
            "immutable Worker endpoint or envelope changed before continuation",
        )
    recovery_mode = request.get("recovery_mode")
    terminal_path = attempt / (
        "failed.json"
        if recovery_mode in {"MISSING_RESULT", "INVALID_RESULT_CONTRACT", "PRE_D0_BLOCKED_RECOVERY"}
        else "completed.json"
    )
    if recovery_mode not in {
        "COMPLETED_RESULT", "MISSING_RESULT", "INVALID_RESULT_CONTRACT", "PRE_D0_BLOCKED_RECOVERY",
    } or (
        _sha256(terminal_path) != request.get("source_terminal_sha256")
    ):
        raise CompletionError(
            "WORKER_CONTINUATION_SOURCE_CHANGED",
            "immutable Worker terminal evidence changed before continuation",
        )
    adapter = DshAdapter()
    adapter.validate_address(endpoint)
    configured_session_id = endpoint.address.get("session_id")
    worker_session_id = request.get("worker_session_id")
    if not isinstance(worker_session_id, str) or (
        configured_session_id is not None and configured_session_id != worker_session_id
    ):
        raise CompletionError("WORKER_CONTINUATION_SESSION_MISMATCH", "Worker endpoint does not name the recorded Session")
    resumed_endpoint = Endpoint(
        **{
            **endpoint.__dict__,
            "address": {**endpoint.address, "session_id": worker_session_id},
        }
    )
    adapter.validate_address(resumed_endpoint)
    continuation_root = _continuation_root(request)
    recovery_process_environment: dict[str, str] = {}
    if recovery_mode not in {"INVALID_RESULT_CONTRACT", "PRE_D0_BLOCKED_RECOVERY"} and any(
        (continuation_root / name).exists()
        for name in ("launch-attempt.json", "started.json", "native.stdout.txt", "native.stderr.txt")
    ):
        raise CompletionError(
            "WORKER_CONTINUATION_ALREADY_ATTEMPTED",
            "the one allowed same-Session continuation already has execution evidence",
        )
    if recovery_mode in {"INVALID_RESULT_CONTRACT", "PRE_D0_BLOCKED_RECOVERY"}:
        if continuation_root.exists():
            raise CompletionError(
                (
                    "WORKER_PRE_D0_RECOVERY_ALREADY_ATTEMPTED"
                    if recovery_mode == "PRE_D0_BLOCKED_RECOVERY"
                    else "WORKER_INVALID_RESULT_SUPPLEMENT_ALREADY_ATTEMPTED"
                ),
                "the one allowed same-Session recovery already has evidence",
            )
        if (
            _sha256(attempt / "transport-task.json") != request.get("source_task_sha256")
            or _sha256(attempt / "started.json") != request.get("source_started_sha256")
            or (
                recovery_mode == "INVALID_RESULT_CONTRACT"
                and _sha256(attempt / "worker-result.invalid.txt")
                != request.get("source_invalid_result_sha256")
            )
            or (
                recovery_mode == "PRE_D0_BLOCKED_RECOVERY"
                and _sha256(attempt / "worker-result.json")
                != request.get("source_blocked_result_sha256")
            )
        ):
            raise CompletionError(
                "WORKER_CONTINUATION_SOURCE_CHANGED",
                "invalid-result source evidence changed before supplement",
            )
        snapshot = _candidate_repository_snapshot(Path(str(request["source_repository"])))
        if (
            snapshot["head"] != request.get("source_candidate", {}).get("commit")
            or snapshot["parent"] != request.get("source_candidate_parent")
            or snapshot["changed_paths"] != request.get("source_changed_paths")
        ):
            raise CompletionError(
                "WORKER_CONTINUATION_SOURCE_CHANGED",
                "candidate repository changed before result-only supplement",
            )
        if recovery_mode == "PRE_D0_BLOCKED_RECOVERY":
            source_envelope = Envelope.from_dict(_read_object(envelope_path, "Worker envelope"))
            environment = _pre_d0_environment(
                Path(str(request["environment_adjustment_path"])),
                str(request["environment_adjustment_sha256"]),
                envelope=source_envelope,
                attempt_number=int(request["attempt"]),
                project_id=str(request["source_project_id"]),
            )
            if (
                environment["candidate_repository"] != request.get("source_repository")
                or environment["candidate_commit"]
                != request.get("source_candidate", {}).get("commit")
            ):
                raise CompletionError(
                    "WORKER_CONTINUATION_SOURCE_CHANGED",
                    "pre-D0 environment no longer binds the frozen candidate",
                )
            recovery_process_environment = {"PROTOC": str(environment["d0_environment"]["PROTOC"])}
    continuation_root.mkdir(parents=True, exist_ok=True)
    request_path = continuation_root / "request.json"
    data = continuation_request_bytes(request)
    if request_path.exists() and request_path.read_bytes() != data:
        raise CompletionError("WORKER_CONTINUATION_CONFLICT", "immutable continuation request conflicts")
    if not request_path.exists():
        temporary = request_path.with_suffix(".json.tmp")
        temporary.write_bytes(data)
        temporary.replace(request_path)
    digest = hashlib.sha256(data).hexdigest()
    if recovery_mode == "MISSING_RESULT":
        instruction = (
            "Resume this exact SLK Worker Session only to recover its missing closed result contract and finish "
            "the existing CELL handoff. Do not redo or expand the implementation. Verify the immutable request "
            "SHA-256, inspect the frozen source envelope and current repository candidate, then write one closed "
            "slk.worker-result/v1 JSON object to the request's worker_result_path. It must contain exactly "
            "schema_version, message_id, run_id, role_instance_id, status, candidate, and next_payload; "
            "status must be completed and the identity must match the source attempt. "
            "After writing it, execute the request's transport_command with "
            f"`continue-worker --request {json.dumps(str(request_path))} --sha256 {digest}`. "
            "Do not read, print, copy, or return credential plaintext. "
            f"<slk-worker-continuation-task path={json.dumps(str(request_path))} sha256={json.dumps(digest)} />"
        )
    elif recovery_mode == "INVALID_RESULT_CONTRACT":
        instruction = (
            "Resume this exact SLK Worker Session for one result-only contract correction. Do not edit product "
            "files, change commits, rerun construction, or create a rework round. Verify the immutable request "
            "SHA-256, inspect the frozen invalid result and unchanged candidate, then author one flat completed "
            "slk.worker-result/v1 object at worker_result_path using exactly the worker_result_fields, "
            "next_payload_fields, and d0_fields frozen in supplement_result_contract. Reuse the Worker's real rich "
            "D0 and evidence; the Tool must not transform the old nested object or invent a new schema. Then execute "
            f"the request's transport_command with `continue-worker --request {json.dumps(str(request_path))} "
            f"--sha256 {digest}`. Do not read, print, copy, or return credential plaintext. "
            f"<slk-worker-continuation-task path={json.dumps(str(request_path))} sha256={json.dumps(digest)} />"
        )
    elif recovery_mode == "PRE_D0_BLOCKED_RECOVERY":
        instruction = (
            "Resume this exact SLK Worker Session for the one sealed pre-D0 environment recovery. Do not edit "
            "product files, change commits, create a rework round, or repeat construction. Verify the immutable "
            "request SHA-256 and unchanged blocked evidence, execute only environment_adjustment.d0_command, then "
            "write one flat completed slk.worker-result/v1 object at worker_result_path using exactly the "
            "worker_result_fields, next_payload_fields, and d0_fields frozen in supplement_result_contract. "
            "The result must bind the existing source_candidate, source_candidate_parent, source_changed_paths, "
            "source_repository, original message, role and Session. Then execute the request's transport_command "
            f"with `continue-worker --request {json.dumps(str(request_path))} --sha256 {digest}`. Do not read, "
            "print, copy, or return credential plaintext. "
            f"<slk-worker-continuation-task path={json.dumps(str(request_path))} sha256={json.dumps(digest)} />"
        )
    else:
        instruction = (
            "Resume this exact SLK Worker Session only to finish its already-completed CELL handoff. "
            "Verify the immutable request SHA-256, then execute its transport_command with "
            f"`continue-worker --request {json.dumps(str(request_path))} --sha256 {digest}`. "
            "Do not read, print, copy, or return credential plaintext. "
            f"<slk-worker-continuation-task path={json.dumps(str(request_path))} sha256={json.dumps(digest)} />"
        )
    command = adapter.command(resumed_endpoint, instruction)
    environment = os.environ.copy()
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    environment.pop("SLK_OVERWATCHER_CREDENTIAL", None)
    environment["DSH_RUNTIME_ROOT"] = str(resumed_endpoint.address["runtime_root"])
    environment["SLK_DSH_INSTANCE_ID"] = str(request["worker_instance_id"])
    environment["SLK_DSH_SESSION_ID"] = str(request["worker_session_id"])
    environment.update(recovery_process_environment)
    timeout = _positive_seconds(resumed_endpoint.address["timeout_seconds"])
    launch_attempt_path = continuation_root / "launch-attempt.json"
    launch_attempt_path.write_bytes(
        continuation_request_bytes(
            {
                "schema_version": "slk.worker-continuation-launch/v1",
                "run_id": request["run_id"],
                "source_message_id": request["source_message_id"],
                "instance_id": request["worker_instance_id"],
                "session_id": request["worker_session_id"],
                "request_sha256": digest,
                "status": "launch_attempted",
            }
        )
    )
    started_at = time.monotonic()
    process = spawn(
        command,
        cwd=str(resumed_endpoint.address["cwd"]),
        env=environment,
        process_kwargs=windows_no_window_kwargs(),
    )
    session_path = adapter._session_root(resumed_endpoint) / f"{worker_session_id}.json"
    while time.monotonic() - started_at < timeout:
        if session_path.is_file() and process.poll() is None:
            break
        if process.poll() is not None:
            break
        time.sleep(0.01)
    if process.poll() is not None or not session_path.is_file():
        process.kill()
        process.communicate()
        raise CompletionError("WORKER_CONTINUATION_START_UNPROVED", "exact resumed DSH Session did not start")
    started_path = continuation_root / "started.json"
    started = {
        "schema_version": "slk.worker-continuation-start/v1",
        "run_id": request["run_id"],
        "source_message_id": request["source_message_id"],
        "instance_id": request["worker_instance_id"],
        "session_id": request["worker_session_id"],
        "request_sha256": digest,
        "status": "started",
    }
    started_bytes = continuation_request_bytes(started)
    if started_path.exists() and started_path.read_bytes() != started_bytes:
        process.kill()
        process.communicate()
        raise CompletionError("WORKER_CONTINUATION_CONFLICT", "continuation start evidence conflicts")
    if not started_path.exists():
        started_path.write_bytes(started_bytes)
    try:
        completed = finish(process, None)
    except subprocess.TimeoutExpired as exc:
        raise CompletionError("WORKER_CONTINUATION_TIMEOUT", "resumed Worker did not finish the handoff") from exc
    (continuation_root / "native.stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (continuation_root / "native.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise CompletionError("WORKER_CONTINUATION_FAILED", f"resumed Worker exited with {completed.returncode}")
    if recovery_mode in {"INVALID_RESULT_CONTRACT", "PRE_D0_BLOCKED_RECOVERY"}:
        snapshot = _candidate_repository_snapshot(Path(str(request["source_repository"])))
        if (
            snapshot["head"] != request.get("source_candidate", {}).get("commit")
            or snapshot["parent"] != request.get("source_candidate_parent")
            or snapshot["changed_paths"] != request.get("source_changed_paths")
        ):
            raise CompletionError(
                "WORKER_CONTINUATION_SOURCE_CHANGED",
                "candidate repository changed during result-only supplement",
            )
    result = _read_object(Path(str(request["continuation_result_path"])), "continuation result")
    if result.get("status") != "CHECKER_DELIVERY_READY" or result.get("source_message_id") != request.get(
        "source_message_id"
    ):
        raise CompletionError(
            "WORKER_CONTINUATION_RESULT_INVALID",
            "continuation result does not prove one staged Checker delivery",
        )
    return result


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
    """Classify one Worker terminal/handoff boundary without changing Run state."""

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
    if completed:
        worker_result = _read_object(attempt / "worker-result.json", "Worker result")
        raw_candidate = worker_result.get("candidate")
        if (
            worker_result.get("message_id") != envelope.message_id
            or worker_result.get("run_id") != envelope.run_id
            or worker_result.get("role_instance_id") != endpoint.role_instance_id
            or worker_result.get("status") != "completed"
            or not isinstance(raw_candidate, Mapping)
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "terminal Worker result does not match the exact dispatch identity",
            )
        candidate = raw_candidate
        exact_candidate, exact_transport = _exact_worker_handoff(
            runtime_projection,
            cell_id=envelope.cell_id,
            attempt=attempt_number,
            candidate=candidate,
            source_message_id=envelope.message_id,
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
        "worker_outcome": "completed" if completed else None,
        "blocker": None,
        "handoff_message_id": handoff_message_id,
        "observed_at": observed_at,
        "cadence_seconds": cadence_seconds,
        "anomaly_codes": [],
        "notification_already_sent": False,
        "missing_worker_events": [],
    }
    if not completed:
        result_path = attempt / "worker-result.json"
        if failed_path.is_file() and result_path.is_file():
            failed = _read_object(failed_path, "Worker failed result")
            worker_result = _read_object(result_path, "Worker result")
            outcome = worker_result.get("status")
            status_map = {
                "incomplete": "WORKER_INCOMPLETE",
                "blocked": "WORKER_BLOCKED",
                "execution_failure": "WORKER_EXECUTION_FAILURE",
                "timed_out": "WORKER_TIMED_OUT",
            }
            error_map = {key: f"DSH_WORKER_{value.removeprefix('WORKER_')}" for key, value in status_map.items()}
            blocker = worker_result.get("blocker")
            if (
                outcome not in status_map
                or set(worker_result)
                != {
                    "schema_version",
                    "message_id",
                    "run_id",
                    "role_instance_id",
                    "status",
                    "candidate",
                    "next_payload",
                    "blocker",
                }
                or worker_result.get("schema_version") != "slk.worker-result/v1"
                or worker_result.get("message_id") != envelope.message_id
                or worker_result.get("run_id") != envelope.run_id
                or worker_result.get("role_instance_id") != endpoint.role_instance_id
                or worker_result.get("candidate") is not None
                or worker_result.get("next_payload") is not None
                or not isinstance(blocker, Mapping)
                or set(blocker) != {"phase", "cause", "summary", "evidence"}
                or not all(
                    isinstance(blocker.get(field), str) and str(blocker[field]).strip()
                    for field in ("phase", "cause", "summary")
                )
                or not isinstance(blocker.get("evidence"), list)
                or not all(
                    isinstance(item, str) and item.strip()
                    for item in blocker.get("evidence", [])
                )
                or failed.get("schema_version") != "slk.transport-result/v1"
                or failed.get("message_id") != envelope.message_id
                or failed.get("run_id") != envelope.run_id
                or failed.get("adapter") != "dsh-worker"
                or failed.get("status") != "failed"
                or failed.get("error_code") != error_map[outcome]
            ):
                raise CompletionError(
                    "WORKER_COMPLETION_EVIDENCE_INVALID",
                    "non-completed Worker result does not match the exact failed dispatch",
                )
            return {
                **base,
                "status": status_map[outcome],
                "worker_outcome": outcome,
                "blocker": dict(blocker),
                "grace_started_at": None,
            }
        missing_result_failure = _missing_result_failure(attempt, envelope)
        if missing_result_failure is not None:
            return {
                **base,
                "status": "WORKER_INCOMPLETE",
                "worker_outcome": "incomplete",
                "blocker": {
                    "phase": "result_contract",
                    "cause": "RESULT_CONTRACT_MISSING",
                    "summary": "the exact started DSH Worker terminated without its closed result contract",
                    "evidence": ["failed.json", "native.stdout.txt", "native.stderr.txt"],
                },
                "grace_started_at": None,
            }
        native_failure = _native_execution_failure(attempt, endpoint, envelope)
        if native_failure is not None:
            outcome = str(native_failure["status"])
            return {
                **base,
                "status": {
                    "execution_failure": "WORKER_EXECUTION_FAILURE",
                    "timed_out": "WORKER_TIMED_OUT",
                }[outcome],
                "worker_outcome": outcome,
                "blocker": {
                    "phase": "native_execution",
                    "cause": native_failure["error_code"],
                    "summary": "the exact DSH runtime did not produce a Worker engineering result",
                    "evidence": ["native-execution.json", "failed.json"],
                },
                "grace_started_at": None,
            }
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
            "status": "WORKER_INCOMPLETE",
            "worker_outcome": "incomplete",
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


def run_worker_continuation(
    request: Mapping[str, Any],
    *,
    authenticate: Authenticate,
    write_event: WriteEvent,
    start_checker: StartChecker,
    commit_start: CommitStart,
    defer_checker_start: bool = False,
) -> dict[str, Any]:
    """Execute the bounded Worker-owned D0/candidate/checker handoff suffix."""

    _validate_continuation_request(request)
    run_id = str(request["run_id"])
    role_instance_id = str(request["worker_role_instance_id"])
    fresh_runtime_revision = authenticate(run_id, role_instance_id)
    if isinstance(fresh_runtime_revision, bool) or not isinstance(fresh_runtime_revision, int) or fresh_runtime_revision < 1:
        raise CompletionError("WORKER_RUNTIME_REVISION_INVALID", "fresh runtime revision is unavailable")
    attempt = Path(str(request["source_attempt_root"]))
    recovery_mode = request.get("recovery_mode")
    if recovery_mode not in {
        "COMPLETED_RESULT", "MISSING_RESULT", "INVALID_RESULT_CONTRACT",
        "INCOMPLETE_HANDOFF", "PRE_D0_BLOCKED_RECOVERY",
    }:
        raise CompletionError("WORKER_CONTINUATION_INVALID", "continuation recovery mode is invalid")
    if recovery_mode in {"INVALID_RESULT_CONTRACT", "PRE_D0_BLOCKED_RECOVERY"} and fresh_runtime_revision != request.get("runtime_revision"):
        raise CompletionError(
            "WORKER_RUNTIME_REVISION_INVALID",
            "same-Session recovery requires the frozen Worker runtime revision",
        )
    result_path = Path(str(request.get("worker_result_path", ""))).resolve()
    if recovery_mode == "MISSING_RESULT":
        expected_result_path = attempt / "worker-continuation" / "recovered-worker-result.json"
    elif recovery_mode == "INVALID_RESULT_CONTRACT":
        expected_result_path = attempt / "invalid-result-supplement" / "recovered-worker-result.json"
    elif recovery_mode == "PRE_D0_BLOCKED_RECOVERY":
        expected_result_path = attempt / "pre-d0-blocked-recovery" / "recovered-worker-result.json"
    elif recovery_mode == "INCOMPLETE_HANDOFF":
        expected_result_path = attempt / "incomplete-handoff" / "evidence.json"
    else:
        expected_result_path = attempt / "worker-result.json"
    expected_result_path = expected_result_path.resolve()
    if result_path != expected_result_path:
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "Worker result path is not exact")
    if recovery_mode == "COMPLETED_RESULT":
        if (
            request.get("worker_result_sha256") is None
            or _sha256(result_path) != request.get("worker_result_sha256")
            or _sha256(attempt / "completed.json") != request.get("source_terminal_sha256")
        ):
            raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "Worker result hash changed")
    elif recovery_mode == "MISSING_RESULT":
        if (
            request.get("worker_result_sha256") is not None
            or _missing_result_failure(
                attempt,
                Envelope.from_dict(_read_object(attempt / "envelope.json", "Worker envelope")),
            )
            is None
            or _sha256(attempt / "failed.json") != request.get("source_terminal_sha256")
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "missing-result recovery source is not exact",
            )
    elif recovery_mode == "INCOMPLETE_HANDOFF":
        if (_sha256(result_path) != request.get("worker_result_sha256")
            or _sha256(attempt / "failed.json") != request.get("source_terminal_sha256")):
            raise CompletionError("WORKER_INCOMPLETE_EVIDENCE_INVALID", "incomplete handoff source changed")
        _load_incomplete_handoff(attempt)
    elif recovery_mode == "PRE_D0_BLOCKED_RECOVERY":
        source_envelope = Envelope.from_dict(_read_object(attempt / "envelope.json", "Worker envelope"))
        if (
            request.get("worker_result_sha256") is not None
            or _sha256(attempt / "failed.json") != request.get("source_terminal_sha256")
            or _sha256(attempt / "transport-task.json") != request.get("source_task_sha256")
            or _sha256(attempt / "started.json") != request.get("source_started_sha256")
            or _sha256(attempt / "worker-result.json")
            != request.get("source_blocked_result_sha256")
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "pre-D0 blocked recovery source is not exact",
            )
        environment = _pre_d0_environment(
            Path(str(request["environment_adjustment_path"])),
            str(request["environment_adjustment_sha256"]),
            envelope=source_envelope,
            attempt_number=int(request["attempt"]),
            project_id=str(request["source_project_id"]),
        )
        snapshot = _candidate_repository_snapshot(Path(str(request["source_repository"])))
        if (
            environment["candidate_repository"] != request.get("source_repository")
            or environment["candidate_commit"]
            != request.get("source_candidate", {}).get("commit")
            or snapshot["head"] != request.get("source_candidate", {}).get("commit")
            or snapshot["parent"] != request.get("source_candidate_parent")
            or snapshot["changed_paths"] != request.get("source_changed_paths")
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "pre-D0 environment or candidate changed",
            )
    elif (
        request.get("worker_result_sha256") is not None
        or _sha256(attempt / "failed.json") != request.get("source_terminal_sha256")
        or _sha256(attempt / "transport-task.json") != request.get("source_task_sha256")
        or _sha256(attempt / "started.json") != request.get("source_started_sha256")
        or _sha256(attempt / "worker-result.invalid.txt")
        != request.get("source_invalid_result_sha256")
    ):
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "invalid-result supplement source is not exact",
        )
    worker_result = _read_object(result_path, "Worker result")
    endpoint_path = attempt / "endpoint.json"
    source_endpoint = Endpoint.from_dict(_read_object(endpoint_path, "Worker endpoint"))
    if (
        _sha256(endpoint_path) != request.get("source_endpoint_sha256")
        or _sha256(attempt / "envelope.json") != request.get("source_envelope_sha256")
        or source_endpoint.role != "worker"
        or source_endpoint.run_id != run_id
        or source_endpoint.role_instance_id != role_instance_id
    ):
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "authenticated immutable Worker endpoint does not match the continuation",
        )
    source_envelope = Envelope.from_dict(_read_object(attempt / "envelope.json", "Worker envelope"))
    next_payload = worker_result.get("next_payload")
    if recovery_mode == "INCOMPLETE_HANDOFF":
        if (worker_result["attempt"] != request["attempt"] or worker_result["plan_revision"] != request["plan_revision"]
            or worker_result["checker_role_instance_id"] != request["checker_endpoint"]["role_instance_id"]
            or worker_result["checker_endpoint_version"] != request["checker_endpoint"]["endpoint_version"]):
            raise CompletionError("WORKER_INCOMPLETE_EVIDENCE_INVALID", "incomplete handoff scope changed")
        next_payload = {key: worker_result[key] for key in ("candidate_repository", "changed_paths", "d0", "unproved")}
    completed_result_fields = {
        "schema_version",
        "message_id",
        "run_id",
        "role_instance_id",
        "status",
        "candidate",
        "next_payload",
    }
    if recovery_mode != "INCOMPLETE_HANDOFF" and (
        frozenset(worker_result) != frozenset(completed_result_fields)
        or worker_result.get("schema_version") != "slk.worker-result/v1"
        or worker_result.get("message_id") != request.get("source_message_id")
        or worker_result.get("run_id") != run_id
        or worker_result.get("role_instance_id") != role_instance_id
        or worker_result.get("status") != "completed"
        or not isinstance(worker_result.get("candidate"), Mapping)
        or set(worker_result["candidate"]) != {"kind", "commit"}
        or worker_result["candidate"].get("kind") != "commit"
        or not isinstance(worker_result["candidate"].get("commit"), str)
        or len(str(worker_result["candidate"]["commit"])) != 40
        or not isinstance(next_payload, Mapping)
    ):
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "Worker next_payload is invalid")
    d0 = next_payload.get("d0")
    changed_paths = next_payload.get("changed_paths", [])
    unproved = next_payload.get("unproved", [])
    repository_value = next_payload.get("candidate_repository", source_endpoint.address.get("cwd"))
    repository = Path(str(repository_value)).resolve()
    if not repository.is_dir():
        raise CompletionError("WORKER_COMPLETION_EVIDENCE_INVALID", "candidate repository is unavailable")
    if recovery_mode in {"INVALID_RESULT_CONTRACT", "PRE_D0_BLOCKED_RECOVERY"}:
        required_payload_fields = set(INVALID_SUPPLEMENT_RESULT_CONTRACT["next_payload_fields"])
        required_d0_fields = set(INVALID_SUPPLEMENT_RESULT_CONTRACT["d0_fields"])
        suffix_blocker = next_payload.get("suffix_blocker")
        if (
            request.get("supplement_result_contract") != INVALID_SUPPLEMENT_RESULT_CONTRACT
            or set(next_payload) != required_payload_fields
            or next_payload.get("attempt") != request.get("attempt")
            or next_payload.get("cell_id") != request.get("cell_id")
            or not isinstance(next_payload.get("candidate_repository"), str)
            or not isinstance(changed_paths, list)
            or not changed_paths
            or not all(isinstance(item, str) and item.strip() for item in changed_paths)
            or not isinstance(unproved, list)
            or not all(isinstance(item, str) and item.strip() for item in unproved)
            or not isinstance(d0, Mapping)
            or set(d0) != required_d0_fields
            or not isinstance(d0.get("baseline_commit"), str)
            or len(str(d0["baseline_commit"])) != 40
            or not isinstance(d0.get("branch"), str)
            or not str(d0["branch"]).strip()
            or d0.get("candidate_commit") != worker_result["candidate"]["commit"]
            or sorted(d0.get("changed_paths", [])) != request.get("source_changed_paths")
            or not isinstance(d0.get("evidence_files"), list)
            or not d0["evidence_files"]
            or not all(isinstance(item, str) and item.strip() for item in d0["evidence_files"])
            or not isinstance(d0.get("focused_command"), str)
            or not str(d0["focused_command"]).strip()
            or not isinstance(d0.get("frozen_command"), str)
            or not str(d0["frozen_command"]).strip()
            or not isinstance(d0.get("frozen_command_result"), Mapping)
            or not isinstance(d0.get("green"), Mapping)
            or not isinstance(d0.get("red"), Mapping)
            or d0.get("unproved") != unproved
            or (
                suffix_blocker is not None
                and (
                    not isinstance(suffix_blocker, Mapping)
                    or set(suffix_blocker) != {"phase", "cause", "summary", "evidence"}
                )
            )
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "recovery result lacks the closed D0, changed-path, or evidence fields",
            )
        if recovery_mode == "PRE_D0_BLOCKED_RECOVERY" and (
            suffix_blocker is not None
            or d0.get("frozen_command")
            != json.dumps(
                environment["d0_command"],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            or not isinstance(d0.get("frozen_command_result"), Mapping)
            or d0["frozen_command_result"].get("exit_code") != 0
            or isinstance(d0["frozen_command_result"].get("exit_code"), bool)
            or d0.get("green", {}).get("status") != "PASS"
            or not all(Path(item).is_absolute() and Path(item).is_file() for item in d0["evidence_files"])
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "pre-D0 result does not prove the one bound successful command",
            )
        snapshot = _candidate_repository_snapshot(repository)
        if (
            worker_result["candidate"] != request.get("source_candidate")
            or str(repository) != request.get("source_repository")
            or snapshot["head"] != worker_result["candidate"]["commit"]
            or snapshot["parent"] != request.get("source_candidate_parent")
            or snapshot["changed_paths"] != sorted(changed_paths)
            or snapshot["changed_paths"] != request.get("source_changed_paths")
        ):
            raise CompletionError(
                "WORKER_COMPLETION_EVIDENCE_INVALID",
                "recovered Worker result does not bind the frozen candidate",
            )
    source_message_id = str(request["source_message_id"])
    handoff_message_id = _stable_id(source_message_id, "candidate-ready")
    checker_token_already_committed = request.get("checker_token_already_committed") is True
    common = {
        "run_id": run_id,
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "plan_revision": request["plan_revision"],
        "role_instance_id": role_instance_id,
        "corrects_event_id": None,
        "occurred_at": request["occurred_at"],
    }
    cell_goal = source_envelope.payload.get("cell_goal", source_envelope.payload.get("task", next_payload.get("cell_goal")))
    d1_criteria = source_envelope.payload.get("d1_criteria")
    acceptance_criteria = source_envelope.payload.get("acceptance_criteria")
    if d1_criteria is None:
        d1_criteria = acceptance_criteria
    elif acceptance_criteria is not None and acceptance_criteria != d1_criteria:
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "d1_criteria and acceptance_criteria conflict",
        )
    source_terminal_path = attempt / (
        "failed.json"
        if recovery_mode in {
            "MISSING_RESULT", "INVALID_RESULT_CONTRACT", "INCOMPLETE_HANDOFF",
            "PRE_D0_BLOCKED_RECOVERY",
        }
        else "completed.json"
    )
    raw_evidence = [
        path
        for path in (
            result_path,
            attempt / "worker-result.json",
            source_terminal_path,
            attempt / "native.stdout.txt",
            attempt / "native.stderr.txt",
        )
        if path.is_file()
    ]
    evidence_index_path = _continuation_root(request) / "checker-evidence-index.json"
    evidence_index_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_index = {
        "schema_version": "slk.checker-evidence-index/v1",
        "run_id": run_id,
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "candidate_message_id": handoff_message_id,
        "entries": [
            {
                "name": path.name,
                "path": str(path.resolve()),
                "byte_length": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in raw_evidence
        ],
    }
    _write_or_reuse_stable_request(evidence_index_path, evidence_index)
    evidence_files = [
        str(path.resolve())
        for path in (result_path, source_terminal_path, evidence_index_path)
        if path.is_file()
    ]
    if (
        not isinstance(cell_goal, str)
        or not cell_goal.strip()
        or not isinstance(d1_criteria, list)
        or not d1_criteria
        or not all(isinstance(item, str) and item.strip() for item in d1_criteria)
        or not evidence_files
    ):
        raise CompletionError(
            "WORKER_COMPLETION_EVIDENCE_INVALID",
            "frozen repository, CELL goal, D1 criteria, and immutable evidence are required",
        )
    candidate_payload = {
        "repository": str(repository),
        "candidate": worker_result["candidate"],
        "cell_goal": cell_goal.strip(),
        "d1_criteria": [item.strip() for item in d1_criteria],
        "evidence_files": evidence_files,
    }
    if recovery_mode == "INCOMPLETE_HANDOFF":
        # Preserve the original logical delivery byte contract. Supplementary
        # verification is separate evidence, never a new payload under an old ID.
        prepared = _read_object(Path(worker_result["staged_envelope"]["path"]), "preserved candidate envelope")
        candidate_payload = dict(prepared["payload"])
    checker = Endpoint.from_dict(request["checker_endpoint"])
    envelope = {
        "schema_version": ENVELOPE_SCHEMA,
        "message_id": handoff_message_id,
        "token_sequence": int(request["token_sequence"])
        if checker_token_already_committed
        else int(request["token_sequence"]) + 1,
        "run_id": run_id,
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "sender_role": "worker",
        "sender_role_instance_id": role_instance_id,
        "receiver_role": "checker",
        "receiver_role_instance_id": checker.role_instance_id,
        "receiver_endpoint_version": checker.endpoint_version,
        "payload_type": "CANDIDATE_READY",
        "payload_sha256": canonical_json_sha256(candidate_payload),
        "payload": candidate_payload,
    }
    Envelope.from_dict(envelope)
    for suffix, event_type, details in (
        ("work-started", "WORK_STARTED", {"source_message_id": source_message_id, "resumed_session_id": request["worker_session_id"]}),
        (
            "d0-completed",
            "D0_COMPLETED",
            {
                "candidate": worker_result["candidate"],
                "d0": d0,
                "changed_paths": changed_paths,
                "unproved": unproved,
            },
        ),
        (
            "candidate-submitted",
            "CANDIDATE_SUBMITTED",
            {
                "candidate": worker_result["candidate"],
                "checker_endpoint_version": request["checker_endpoint"]["endpoint_version"],
                "source_message_id": source_message_id,
                "handoff_message_id": handoff_message_id,
            },
        ),
    ):
        write_event(
            {
                **common,
                "event_id": _stable_id(source_message_id, suffix),
                "event_type": event_type,
                "details": details,
            }
        )
    handoff_runtime_revision = authenticate(run_id, role_instance_id)
    if (
        isinstance(handoff_runtime_revision, bool)
        or not isinstance(handoff_runtime_revision, int)
        or handoff_runtime_revision < fresh_runtime_revision
    ):
        raise CompletionError(
            "WORKER_RUNTIME_REVISION_INVALID",
            "post-event runtime revision is unavailable or moved backwards",
        )
    start = dict(start_checker(dict(request["checker_endpoint"]), envelope))
    if defer_checker_start:
        if start.get("status") != "delivery_ready":
            raise CompletionError(
                "CHECKER_DELIVERY_STAGE_INVALID",
                "Worker must stage one immutable Checker delivery package",
            )
        try:
            endpoint_path = Path(str(start["endpoint_path"])).resolve()
            envelope_path = Path(str(start["envelope_path"])).resolve()
            checker_attempt_root = Path(str(start["attempt_root"])).resolve()
        except KeyError as exc:
            raise CompletionError(
                "CHECKER_DELIVERY_STAGE_INVALID", "staged Checker paths are incomplete"
            ) from exc
        if (
            _read_object(endpoint_path, "staged Checker endpoint")
            != dict(request["checker_endpoint"])
            or _read_object(envelope_path, "staged Checker envelope") != envelope
            or not checker_attempt_root.is_absolute()
        ):
            raise CompletionError(
                "CHECKER_DELIVERY_STAGE_INVALID",
                "staged Checker delivery does not bind the exact candidate",
            )
        return {
            "status": "CHECKER_DELIVERY_READY",
            "run_id": run_id,
            "source_message_id": source_message_id,
            "candidate_message_id": envelope["message_id"],
            "runtime_revision": handoff_runtime_revision,
            "checker_token_already_committed": checker_token_already_committed,
            "endpoint_path": str(endpoint_path),
            "envelope_path": str(envelope_path),
            "attempt_root": str(checker_attempt_root),
        }
    if start.get("status") not in {"started", "completed", "already_started", "ALREADY_STARTED"}:
        raise CompletionError("CHECKER_START_UNPROVED", "Checker native start is not proven")
    try:
        started_path = Path(str(start["started_path"])).resolve()
        endpoint_path = Path(str(start["endpoint_path"])).resolve()
        envelope_path = Path(str(start["envelope_path"])).resolve()
    except KeyError as exc:
        raise CompletionError("CHECKER_START_UNPROVED", "exact native start evidence paths are missing") from exc
    started = _read_object(started_path, "Checker started evidence")
    persisted_endpoint = _read_object(endpoint_path, "Checker delivery endpoint")
    persisted_envelope = _read_object(envelope_path, "Checker delivery envelope")
    if (
        started.get("status") != "started"
        or started.get("run_id") != run_id
        or started.get("message_id") != envelope["message_id"]
        or persisted_endpoint != dict(request["checker_endpoint"])
        or persisted_envelope != envelope
    ):
        raise CompletionError("CHECKER_START_UNPROVED", "exact native start evidence does not match delivery")
    commit_request = {
        "event_id": _stable_id(source_message_id, "checker-transport-started"),
        "transport_receipt_id": _stable_id(source_message_id, "checker-start-receipt"),
        "run_id": run_id,
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "plan_revision": request["plan_revision"],
        "expected_runtime_revision": handoff_runtime_revision,
        "message_id": envelope["message_id"],
        "token_sequence": envelope["token_sequence"],
        "from_role_instance_id": role_instance_id,
        "to_role_instance_id": checker.role_instance_id,
        "endpoint_version": checker.endpoint_version,
        "payload_type": "CANDIDATE_READY",
        "payload_sha256": envelope["payload_sha256"],
        "start_evidence": {
            "evidence_id": _stable_id(source_message_id, "checker-start-evidence"),
            "stored_path": str(started_path),
            "sha256": _sha256(started_path),
            "message_id": envelope["message_id"],
            "endpoint_sha256": _sha256(endpoint_path),
            "envelope_sha256": _sha256(envelope_path),
            "native_status": "STARTED",
        },
        "occurred_at": request["occurred_at"],
    }
    committed = commit_start(commit_request)
    committed_revision = committed.get("runtime_revision")
    if (
        committed.get("status") not in {"committed", "idempotent_replay"}
        or isinstance(committed_revision, bool)
        or not isinstance(committed_revision, int)
        or committed_revision <= handoff_runtime_revision
        or committed.get("token_sequence") != envelope["token_sequence"]
        or committed.get("message_id") != envelope["message_id"]
    ):
        raise CompletionError(
            "WORKER_RUNTIME_REVISION_INVALID",
            "delivery commit did not return the exact resulting runtime revision",
        )
    return {
        "status": "CHECKER_STARTED",
        "run_id": run_id,
        "source_message_id": source_message_id,
        "candidate_message_id": envelope["message_id"],
        "runtime_revision": committed_revision,
    }


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


def _activate_staged_checker(
    outcome: Mapping[str, Any],
    continuation: Mapping[str, Any],
    *,
    failed_commit_request_path: Path | None = None,
) -> Mapping[str, Any]:
    """Start OCRV outside DSH, validate native v2 evidence, then commit the handoff."""

    expected_outcome_fields = {
        "status",
        "run_id",
        "source_message_id",
        "candidate_message_id",
        "runtime_revision",
        "endpoint_path",
        "envelope_path",
        "attempt_root",
        "checker_token_already_committed",
    }
    if set(outcome) != expected_outcome_fields or outcome.get("status") != "CHECKER_DELIVERY_READY":
        raise CompletionError("CHECKER_DELIVERY_STAGE_INVALID", "staged Checker delivery result is not closed")
    endpoint_path = Path(str(outcome["endpoint_path"])).resolve()
    envelope_path = Path(str(outcome["envelope_path"])).resolve()
    attempt_root = Path(str(outcome["attempt_root"])).resolve()
    try:
        endpoint = Endpoint.from_dict(_read_object(endpoint_path, "staged Checker endpoint"))
        envelope = Envelope.from_dict(_read_object(envelope_path, "staged Checker envelope"))
    except (TypeError, ValueError) as exc:
        raise CompletionError("CHECKER_DELIVERY_STAGE_INVALID", "staged Checker delivery is invalid") from exc
    if (
        endpoint != Endpoint.from_dict(continuation["checker_endpoint"])
        or endpoint.role != "checker"
        or envelope.run_id != continuation.get("run_id")
        or envelope.cell_id != continuation.get("cell_id")
        or envelope.message_id != outcome.get("candidate_message_id")
        or envelope.message_id != _stable_id(str(continuation["source_message_id"]), "candidate-ready")
        or envelope.sender_role != "worker"
        or envelope.sender_role_instance_id != continuation.get("worker_role_instance_id")
        or envelope.receiver_role_instance_id != endpoint.role_instance_id
        or outcome.get("run_id") != continuation.get("run_id")
        or outcome.get("source_message_id") != continuation.get("source_message_id")
    ):
        raise CompletionError(
            "CHECKER_DELIVERY_STAGE_INVALID", "staged Checker delivery identity does not match the continuation"
        )
    staged_revision = outcome.get("runtime_revision")
    if isinstance(staged_revision, bool) or not isinstance(staged_revision, int) or staged_revision < 1:
        raise CompletionError("WORKER_RUNTIME_REVISION_INVALID", "staged runtime revision is invalid")
    checker_token_already_committed = outcome.get("checker_token_already_committed") is True
    if checker_token_already_committed != (continuation.get("checker_token_already_committed") is True):
        raise CompletionError("CHECKER_DELIVERY_STAGE_INVALID", "Checker TOKEN recovery state changed")
    native_attempt_root = (
        attempt_root / ".native-recovery-v2" / str(continuation["source_message_id"])
        if checker_token_already_committed
        else attempt_root
    )
    attempt = native_attempt_root / envelope.run_id / envelope.message_id
    started_path = attempt / "started.json"
    persisted_endpoint_path = attempt / "endpoint.json"
    persisted_envelope_path = attempt / "envelope.json"
    temporal = continuation.get("temporal") if not checker_token_already_committed else None
    if temporal is not None and failed_commit_request_path is None:
        attempt = start_temporal_delivery(
            temporal,
            _continuation_root(continuation),
            asdict(endpoint),
            asdict(envelope),
            attempt=int(continuation["attempt"]),
            source_runtime_revision=staged_revision,
            required_attempt_root=native_attempt_root,
        )
        started_path = attempt / "started.json"
        persisted_endpoint_path = attempt / "endpoint.json"
        persisted_envelope_path = attempt / "envelope.json"
    elif attempt.exists():
        if not all(path.is_file() for path in (started_path, persisted_endpoint_path, persisted_envelope_path)):
            raise CompletionError("CHECKER_START_UNPROVED", "Checker attempt has incomplete immutable evidence")
    else:
        if failed_commit_request_path is not None:
            raise CompletionError(
                "CHECKER_START_UNPROVED",
                "commit-only recovery requires the already proven Checker native start",
            )
        transport_command = continuation.get("transport_command")
        if not isinstance(transport_command, list) or not transport_command:
            raise CompletionError("WORKER_CONTINUATION_INVALID", "transport command is unavailable")
        sent = _run_json_command(
            list(transport_command),
            [
                "send",
                "--endpoint",
                str(endpoint_path),
                "--envelope",
                str(envelope_path),
                "--attempt-root",
                str(native_attempt_root),
            ],
            credential=None,
        )
        command = sent.get("_slk_command")
        if (
            sent.get("status") not in {"started", "completed"}
            or sent.get("run_id") != envelope.run_id
            or sent.get("message_id") != envelope.message_id
            or not isinstance(command, Mapping)
            or command.get("process_exit") != 0
        ):
            raise CompletionError("CHECKER_START_UNPROVED", "OCRV transport did not prove the exact native start")
    if (
        _read_object(persisted_endpoint_path, "Checker delivery endpoint") != _read_object(endpoint_path, "staged Checker endpoint")
        or _read_object(persisted_envelope_path, "Checker delivery envelope") != _read_object(envelope_path, "staged Checker envelope")
    ):
        raise CompletionError("CHECKER_START_UNPROVED", "OCRV immutable delivery evidence conflicts")
    try:
        validate_native_start(
            started_path,
            adapter=endpoint.adapter,
            run_id=envelope.run_id,
            cell_id=envelope.cell_id,
            message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256,
        )
    except NativeActivityError as exc:
        raise CompletionError("CHECKER_START_UNPROVED", "OCRV native-start v2 evidence is invalid") from exc
    if checker_token_already_committed:
        if failed_commit_request_path is not None:
            raise CompletionError(
                "WORKER_COMMIT_RECOVERY_NOT_REQUIRED",
                "Checker TOKEN was already committed before commit-only recovery",
            )
        return {
            "status": "CHECKER_STARTED",
            "runtime_revision": staged_revision,
            "token_sequence": envelope.token_sequence,
            "candidate_message_id": envelope.message_id,
            "checker_token_already_committed": True,
            "native_attempt_path": str(attempt),
        }
    commit_request = {
        "event_id": _stable_id(str(continuation["source_message_id"]), "checker-transport-started"),
        "transport_receipt_id": _stable_id(str(continuation["source_message_id"]), "checker-start-receipt"),
        "run_id": envelope.run_id,
        "go_id": continuation["go_id"],
        "cell_id": envelope.cell_id,
        "attempt": continuation["attempt"],
        "plan_revision": continuation["plan_revision"],
        "expected_runtime_revision": staged_revision,
        "message_id": envelope.message_id,
        "token_sequence": envelope.token_sequence,
        "from_role_instance_id": continuation["worker_role_instance_id"],
        "to_role_instance_id": endpoint.role_instance_id,
        "endpoint_version": endpoint.endpoint_version,
        "payload_type": envelope.payload_type,
        "payload_sha256": envelope.payload_sha256,
        "start_evidence": {
            "evidence_id": _stable_id(str(continuation["source_message_id"]), "checker-start-evidence"),
            "stored_path": str(started_path),
            "sha256": _sha256(started_path),
            "message_id": envelope.message_id,
            "endpoint_sha256": _sha256(persisted_endpoint_path),
            "envelope_sha256": _sha256(persisted_envelope_path),
            "native_status": "STARTED",
        },
        "occurred_at": continuation["occurred_at"],
    }
    worker_credential = unprotect_dpapi_hex(str(continuation["credential_path"]))
    try:
        commit_request_path = (
            _continuation_root(continuation)
            / f"commit-delivery-start-{commit_request['transport_receipt_id']}.json"
        )
        failed_request_sha256: str | None = None
        if failed_commit_request_path is not None:
            failed_path = failed_commit_request_path.resolve()
            if failed_path != commit_request_path.resolve() or not failed_path.is_file():
                raise CompletionError(
                    "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
                    "commit-only recovery requires the exact preserved failed request",
                )
            failed_request = _read_object(failed_path, "failed Checker start commit request")
            if failed_request != commit_request:
                raise CompletionError(
                    "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
                    "failed commit request changed the staged delivery identity",
                )
            authentication = _run_json_command(
                list(continuation["state_command"]),
                [
                    "authenticate-role",
                    "--run-id",
                    str(continuation["run_id"]),
                    "--role-instance-id",
                    str(continuation["worker_role_instance_id"]),
                ],
                credential=worker_credential,
            )
            current_revision = authentication.get("runtime_revision")
            if (
                authentication.get("status") != "authenticated"
                or authentication.get("role") != "worker"
                or authentication.get("role_instance_id")
                != continuation.get("worker_role_instance_id")
                or isinstance(current_revision, bool)
                or not isinstance(current_revision, int)
                or current_revision <= staged_revision
            ):
                raise CompletionError(
                    "WORKER_COMMIT_RECOVERY_AUTHENTICATION_FAILED",
                    "original Worker does not prove a newer current runtime revision",
                )
            failed_request_sha256 = _sha256(failed_path)
            commit_request = {
                **commit_request,
                "expected_runtime_revision": current_revision,
            }
            commit_request_path = (
                _continuation_root(continuation)
                / "commit-only-recovery"
                / f"commit-delivery-start-{commit_request['transport_receipt_id']}.json"
            )
            commit_request_path.parent.mkdir(parents=True, exist_ok=True)
        commit_request_path = _write_or_reuse_stable_request(
            commit_request_path,
            commit_request,
        )
        committed = _run_json_command(
            list(continuation["state_command"]),
            ["commit-delivery-start", "--request", str(commit_request_path)],
            credential=worker_credential,
        )
    finally:
        worker_credential = ""
    committed_revision = committed.get("runtime_revision")
    if (
        committed.get("status") not in {"committed", "idempotent_replay"}
        or isinstance(committed_revision, bool)
        or not isinstance(committed_revision, int)
        or committed_revision <= commit_request["expected_runtime_revision"]
        or committed.get("token_sequence") != envelope.token_sequence
        or committed.get("message_id") != envelope.message_id
    ):
        raise CompletionError("WORKER_RUNTIME_REVISION_INVALID", "Checker start commit is not exact")
    _write_or_reuse_stable_request(commit_request_path.with_suffix(".result.json"), committed)
    activation = {
        "status": "CHECKER_STARTED",
        "runtime_revision": committed_revision,
        "token_sequence": envelope.token_sequence,
        "candidate_message_id": envelope.message_id,
        "checker_token_already_committed": False,
        "native_attempt_path": str(attempt),
    }
    if failed_commit_request_path is None:
        return activation
    recovery_result_path = _continuation_root(continuation) / "commit-only-recovery" / "result.json"
    recovery_result = {
        "schema_version": "slk.worker-checker-commit-recovery/v1",
        "method_version": continuation["method_version"],
        **activation,
        "status": "CHECKER_START_COMMITTED",
        "run_id": continuation["run_id"],
        "cell_id": continuation["cell_id"],
        "source_message_id": continuation["source_message_id"],
        "worker_role_instance_id": continuation["worker_role_instance_id"],
        "checker_role_instance_id": endpoint.role_instance_id,
        "transport_receipt_id": commit_request["transport_receipt_id"],
        "failed_request_path": str(failed_commit_request_path.resolve()),
        "failed_request_sha256": failed_request_sha256,
        "recovery_request_path": str(commit_request_path.resolve()),
        "recovery_request_sha256": _sha256(commit_request_path),
    }
    _write_or_reuse_stable_request(recovery_result_path, recovery_result)
    return {**recovery_result, "result_path": str(recovery_result_path.resolve())}


def recover_staged_checker_commit(
    continuation: Mapping[str, Any],
    outcome: Mapping[str, Any],
    *,
    failed_request_path: Path,
) -> Mapping[str, Any]:
    """Commit one already-started Checker delivery after a proven revision-only conflict."""

    return _activate_staged_checker(
        outcome,
        continuation,
        failed_commit_request_path=failed_request_path,
    )


def _load_commit_only_checker_activation(
    continuation: Mapping[str, Any],
    current_runtime_revision: int,
) -> Mapping[str, Any]:
    """Validate a completed commit-only recovery for the original Checker path."""

    root = _continuation_root(continuation)
    result_path = root / "commit-only-recovery" / "result.json"
    result = _read_object(result_path, "commit-only recovery result")
    fields = {
        "schema_version",
        "method_version",
        "status",
        "runtime_revision",
        "token_sequence",
        "candidate_message_id",
        "checker_token_already_committed",
        "native_attempt_path",
        "run_id",
        "cell_id",
        "source_message_id",
        "worker_role_instance_id",
        "checker_role_instance_id",
        "transport_receipt_id",
        "failed_request_path",
        "failed_request_sha256",
        "recovery_request_path",
        "recovery_request_sha256",
    }
    if (
        set(result) != fields
        or result.get("schema_version") != "slk.worker-checker-commit-recovery/v1"
        or result.get("method_version") != continuation["method_version"]
        or result.get("status") != "CHECKER_START_COMMITTED"
        or result.get("runtime_revision") != current_runtime_revision
        or result.get("run_id") != continuation.get("run_id")
        or result.get("cell_id") != continuation.get("cell_id")
        or result.get("source_message_id") != continuation.get("source_message_id")
        or result.get("worker_role_instance_id") != continuation.get("worker_role_instance_id")
        or result.get("checker_role_instance_id")
        != continuation["checker_endpoint"].get("role_instance_id")
        or result.get("candidate_message_id")
        != _stable_id(str(continuation["source_message_id"]), "candidate-ready")
        or result.get("token_sequence") != int(continuation["token_sequence"]) + 1
        or result.get("checker_token_already_committed") is not False
    ):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "commit-only recovery result does not bind the original Checker delivery",
        )
    failed_path = Path(str(result["failed_request_path"])).resolve()
    recovery_path = Path(str(result["recovery_request_path"])).resolve()
    if (
        failed_path
        != (
            root
            / f"commit-delivery-start-{result['transport_receipt_id']}.json"
        ).resolve()
        or recovery_path
        != (
            root
            / "commit-only-recovery"
            / f"commit-delivery-start-{result['transport_receipt_id']}.json"
        ).resolve()
        or not failed_path.is_file()
        or not recovery_path.is_file()
        or result.get("failed_request_sha256") != _sha256(failed_path)
        or result.get("recovery_request_sha256") != _sha256(recovery_path)
    ):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "commit-only request evidence is missing or changed",
        )
    failed_request = _read_object(failed_path, "failed Checker start commit request")
    recovery_request = _read_object(recovery_path, "recovered Checker start commit request")
    failed_without_revision = dict(failed_request)
    recovery_without_revision = dict(recovery_request)
    failed_revision = failed_without_revision.pop("expected_runtime_revision", None)
    recovery_revision = recovery_without_revision.pop("expected_runtime_revision", None)
    if (
        failed_without_revision != recovery_without_revision
        or failed_request.get("transport_receipt_id") != result.get("transport_receipt_id")
        or isinstance(failed_revision, bool)
        or not isinstance(failed_revision, int)
        or isinstance(recovery_revision, bool)
        or not isinstance(recovery_revision, int)
        or recovery_revision <= failed_revision
        or current_runtime_revision != recovery_revision + 1
    ):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "commit-only recovery changed more than the authenticated runtime revision",
        )
    outcome_path = Path(str(continuation["continuation_result_path"])).resolve()
    outcome = _read_object(outcome_path, "staged Checker delivery result")
    if (
        outcome.get("status") != "CHECKER_DELIVERY_READY"
        or outcome.get("candidate_message_id") != result.get("candidate_message_id")
        or outcome.get("run_id") != continuation.get("run_id")
        or outcome.get("source_message_id") != continuation.get("source_message_id")
    ):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "staged Checker delivery no longer matches the recovered commit",
        )
    endpoint_path = Path(str(outcome["endpoint_path"])).resolve()
    envelope_path = Path(str(outcome["envelope_path"])).resolve()
    endpoint = Endpoint.from_dict(_read_object(endpoint_path, "staged Checker endpoint"))
    envelope = Envelope.from_dict(_read_object(envelope_path, "staged Checker envelope"))
    native_attempt = Path(str(result["native_attempt_path"])).resolve()
    expected_attempt = (
        Path(str(outcome["attempt_root"])).resolve()
        / envelope.run_id
        / envelope.message_id
    )
    if (
        endpoint != Endpoint.from_dict(continuation["checker_endpoint"])
        or envelope.message_id != result.get("candidate_message_id")
        or native_attempt != expected_attempt
        or _read_object(native_attempt / "endpoint.json", "Checker delivery endpoint")
        != _read_object(endpoint_path, "staged Checker endpoint")
        or _read_object(native_attempt / "envelope.json", "Checker delivery envelope")
        != _read_object(envelope_path, "staged Checker envelope")
    ):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "existing Checker native attempt does not match the staged delivery",
        )
    try:
        validate_native_start(
            native_attempt / "started.json",
            adapter=endpoint.adapter,
            run_id=envelope.run_id,
            cell_id=envelope.cell_id,
            message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256,
        )
    except NativeActivityError as exc:
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "existing Checker native start is invalid",
        ) from exc
    return {
        "status": "CHECKER_STARTED",
        "runtime_revision": current_runtime_revision,
        "token_sequence": result["token_sequence"],
        "candidate_message_id": result["candidate_message_id"],
        "checker_token_already_committed": False,
        "native_attempt_path": str(native_attempt),
    }


def _run_sealed_checker_terminal(
    request_path: Path,
    request: Mapping[str, Any],
    endpoint: Endpoint,
    *,
    request_sha256: str,
    mode: str,
    result_schema: str,
    error_code: str,
    extra_args: tuple[str, ...] = (),
    result_statuses: tuple[str, ...] = ("CHECKER_D1_RECORDED",),
    identity_source: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Use the one registered headless OCRV host for an existing terminal."""

    identity = identity_source or request
    command = endpoint.address.get("command")
    runtime_root = Path(str(endpoint.address.get("runtime_root", ""))).resolve()
    if not _nonempty_strings(command) or not runtime_root.is_dir():
        raise CompletionError(error_code, "registered OCRV host command or runtime root is unavailable")
    environment = os.environ.copy()
    for name in (
        "SLK_ROLE_CREDENTIAL",
        "SLK_OVERWATCHER_CREDENTIAL",
        "SLK_NATIVE_START_RECEIPT",
        "SLK_NATIVE_START_CONTEXT",
    ):
        environment.pop(name, None)
    environment.update({
        "SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID": endpoint.role_instance_id,
        "SLK_OCRV_RECOVERY_INVOCATION_ID": str(request["recovery_invocation_id"]),
        "SLK_OCRV_RECOVERY_ENDPOINT_VERSION": str(endpoint.endpoint_version),
    })
    from .process import windows_no_window_kwargs

    completed = subprocess.run(
        [*command, mode, "--request", str(request_path.resolve()), "--output",
         str(Path(str(request["result_path"])).resolve()), *extra_args],
        cwd=str(runtime_root),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        **windows_no_window_kwargs(detached=False),
    )
    try:
        stdout = (completed.stdout or b"").decode("utf-8", errors="strict")
        stderr = (completed.stderr or b"").decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CompletionError(error_code, "original Checker terminal consumer returned invalid UTF-8") from exc
    if completed.returncode != 0:
        raise CompletionError(error_code, stderr.strip() or stdout.strip() or "original Checker terminal consumer failed")
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CompletionError(error_code, "original Checker terminal consumer returned no valid JSON") from exc
    if (
        not _matches(value, {
            "schema_version": result_schema,
            "run_id": identity["run_id"],
            "checker_role_instance_id": endpoint.role_instance_id,
            "request_sha256": request_sha256,
        })
        or value.get("status") not in result_statuses
    ):
        raise CompletionError(error_code, stderr.strip() or "original Checker terminal consumer failed")
    return value


def consume_staged_checker_terminal(
    request_path: Path,
    *,
    request_sha256: str,
) -> Mapping[str, Any]:
    """Re-enter the original sealed OCRV host only to consume an existing terminal."""

    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError(
            "CHECKER_RECOVERY_REQUEST_MISMATCH",
            "Checker recovery request hash mismatch",
        )
    request = _read_object(request_path, "Checker recovery request")
    if (
        request.get("schema_version") != CHECKER_RECOVERY_SCHEMA
        or request.get("method_version") not in SUPPORTED_METHOD_VERSIONS
    ):
        raise CompletionError(
            "CHECKER_RECOVERY_REQUEST_INVALID",
            "existing-terminal consumption requires the original supported Checker request",
        )
    try:
        endpoint = Endpoint.from_dict(request["checker_endpoint"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CompletionError(
            "CHECKER_RECOVERY_REQUEST_INVALID",
            "original Checker endpoint is invalid",
        ) from exc
    if (
        endpoint.role != "checker"
        or endpoint.role_instance_id != request.get("checker_role_instance_id")
        or endpoint.endpoint_version != request.get("checker_endpoint_version")
        or endpoint.run_id != request.get("run_id")
    ):
        raise CompletionError(
            "CHECKER_RECOVERY_IDENTITY_MISMATCH",
            "original Checker endpoint identity is not exact",
        )
    projection = _read_object(Path(str(request["runtime_projection_path"])), "runtime projection")
    continuation = build_continuation_request(
        str(request["source_attempt_root"]),
        request["checker_endpoint"],
        projection,
        plan_revision=int(request["plan_revision"]),
        runtime_revision=int(request["runtime_revision"]),
        token_sequence=int(request["token_sequence"]),
        credential_path=str(request["worker_credential_path"]),
        state_command=list(request["state_command"]),
        transport_command=list(request["transport_command"]),
        occurred_at=str(request["occurred_at"]),
    )
    commit_result = _read_object(
        _continuation_root(continuation) / "commit-only-recovery" / "result.json",
        "commit-only recovery result",
    )
    current_revision = commit_result.get("runtime_revision")
    if isinstance(current_revision, bool) or not isinstance(current_revision, int):
        raise CompletionError(
            "WORKER_COMMIT_RECOVERY_EVIDENCE_INVALID",
            "commit-only recovery runtime revision is invalid",
        )
    _load_commit_only_checker_activation(continuation, current_revision)
    return _run_sealed_checker_terminal(
        request_path,
        request,
        endpoint,
        request_sha256=request_sha256,
        mode="--slk-existing-terminal",
        result_schema=CHECKER_RECOVERY_RESULT_SCHEMA,
        error_code="CHECKER_RECOVERY_COMMAND_FAILED",
    )


def _reuse_committed_checker_delivery(continuation: Mapping[str, Any]) -> Mapping[str, Any]:
    """Locate the immutable candidate package after a legacy false start already moved TOKEN."""

    source_message_id = str(continuation["source_message_id"])
    candidate_message_id = _stable_id(source_message_id, "candidate-ready")
    attempt_root = (
        Path(str(continuation["source_attempt_root"])).resolve()
        / "worker-continuation"
        / "checker-attempts"
    )
    attempt = attempt_root / str(continuation["run_id"]) / candidate_message_id
    endpoint_path = attempt / "endpoint.json"
    envelope_path = attempt / "envelope.json"
    if not endpoint_path.is_file() or not envelope_path.is_file():
        raise CompletionError(
            "CHECKER_COMMITTED_DELIVERY_MISSING",
            "Checker holds TOKEN but the immutable candidate package is unavailable",
        )
    return {
        "status": "CHECKER_DELIVERY_READY",
        "run_id": continuation["run_id"],
        "source_message_id": source_message_id,
        "candidate_message_id": candidate_message_id,
        "runtime_revision": continuation["runtime_revision"],
        "checker_token_already_committed": True,
        "endpoint_path": str(endpoint_path),
        "envelope_path": str(envelope_path),
        "attempt_root": str(attempt_root),
    }


def _record_checker_d1(
    activation: Mapping[str, Any],
    continuation: Mapping[str, Any],
    *,
    checker_credential_path: Path | str,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    """Bind the actual OCRV terminal result to Checker-owned D1 events."""

    if 'independent_fail' in continuation:
        from .independent_checker_fail import record
        return record(continuation, checker_credential_path)

    native_attempt = Path(str(activation.get("native_attempt_path", ""))).resolve()
    started_path = native_attempt / "started.json"
    checker = Endpoint.from_dict(continuation["checker_endpoint"])
    candidate_message_id = str(activation.get("candidate_message_id", ""))
    native_message_id = str(continuation.get("native_message_id", candidate_message_id))
    try:
        started = validate_native_start(
            started_path,
            adapter=checker.adapter,
            run_id=str(continuation["run_id"]),
            cell_id=str(continuation["cell_id"]),
            message_id=native_message_id,
        )
    except NativeActivityError as exc:
        raise CompletionError("CHECKER_D1_EVIDENCE_INVALID", "D1 native start evidence is invalid") from exc
    if started["native_task"]["kind"] != "ocrv-review":
        raise CompletionError(
            "CHECKER_D1_EVIDENCE_INVALID",
            "recovery wrapper start is not actual OCRV D1 evidence",
        )
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise CompletionError("CHECKER_D1_EVIDENCE_INVALID", "D1 terminal timeout is invalid")
    credential = unprotect_dpapi_hex(checker_credential_path)
    event_root = native_attempt / "slk-state"
    event_root.mkdir(parents=True, exist_ok=True)

    def write_checker_event(event_type: str, suffix: str, details: Mapping[str, Any], occurred_at: str) -> None:
        request = {
            "event_id": _stable_id(candidate_message_id, suffix),
            "run_id": continuation["run_id"],
            "go_id": continuation["go_id"],
            "cell_id": continuation["cell_id"],
            "attempt": continuation["attempt"],
            "plan_revision": continuation["plan_revision"],
            "role_instance_id": checker.role_instance_id,
            "event_type": event_type,
            "details": dict(details),
            "corrects_event_id": (
                continuation.get('d1_correction_event_id')
                or continuation.get('partial_correction_event_id')
            ) if event_type != 'D1_STARTED' else None,
            "occurred_at": occurred_at,
        }
        request_path = _write_or_reuse_stable_request(event_root / f"{suffix}.json", request)
        recorded = _run_json_command(
            list(continuation["state_command"]),
            ["write", "--request", str(request_path)],
            credential=credential,
        )
        if recorded.get("status") != "recorded" or recorded.get("run_id") != continuation["run_id"]:
            raise CompletionError("CHECKER_D1_STATE_WRITE_FAILED", f"{event_type} was not recorded")

    try:
        if not (continuation.get('d1_correction_event_id') or continuation.get('partial_correction_event_id')): write_checker_event(
            "D1_STARTED",
            "d1-started-v2",
            {
                "candidate_message_id": candidate_message_id,
                "native_start_path": str(started_path),
                "native_start_sha256": _sha256(started_path),
                "native_task": started["native_task"],
            },
            str(started["observed_at"]),
        )
        deadline = time.monotonic() + float(timeout_seconds)
        completed_path = native_attempt / "completed.json"
        failed_path = native_attempt / "failed.json"
        while time.monotonic() < deadline and not completed_path.is_file() and not failed_path.is_file():
            time.sleep(0.02)
        if completed_path.is_file() == failed_path.is_file():
            raise CompletionError("CHECKER_D1_TERMINAL_UNPROVEN", "OCRV D1 has no unique terminal result")
        terminal_path = completed_path if completed_path.is_file() else failed_path
        terminal = _read_object(terminal_path, "OCRV terminal result")
        terminal_fields = {
            "schema_version",
            "message_id",
            "run_id",
            "adapter",
            "status",
            "native_identity",
            "error_code",
            "evidence",
        }
        expected_terminal_status = "completed" if completed_path.is_file() else "failed"
        if (
            set(terminal) != terminal_fields
            or terminal.get("schema_version") != "slk.transport-result/v1"
            or terminal.get("message_id") != native_message_id
            or terminal.get("run_id") != continuation["run_id"]
            or terminal.get("adapter") != checker.adapter
            or terminal.get("status") != expected_terminal_status
            or not isinstance(terminal.get("native_identity"), Mapping)
            or not isinstance(terminal.get("evidence"), list)
        ):
            raise CompletionError(
                "CHECKER_D1_EVIDENCE_INVALID",
                "OCRV D1 terminal does not bind the exact candidate delivery",
            )
        result_path = native_attempt / "ocrv-result.json"
        verdict = "INCOMPLETE"
        result: Mapping[str, Any] | None = None
        aggregate_path: Path | None = None
        if completed_path.is_file():
            result = _read_object(result_path, "OCRV D1 result")
            required_result_fields = {
                "schema_version",
                "run_id",
                "cell_id",
                "review_invocation_id",
                "verdict",
                "reason_codes",
                "findings",
                "review",
                "evidence",
                "request_sha256",
                "artifacts",
            }
            if (
                set(result) != required_result_fields
                or result.get("schema_version") != "slk.ocrv-d1-result/v1"
                or result.get("run_id") != continuation["run_id"]
                or result.get("cell_id") != continuation["cell_id"]
                or result.get("verdict") not in {"PASS", "FAIL", "INCOMPLETE"}
                or not isinstance(result.get("review"), Mapping)
                or not isinstance(result.get("artifacts"), Mapping)
                or not isinstance(result.get("evidence"), list)
            ):
                raise CompletionError("CHECKER_D1_EVIDENCE_INVALID", "OCRV D1 result is not closed")
            verdict = str(result["verdict"])
            identity = terminal["native_identity"]
            identity_fields = {
                "run_id",
                "cell_id",
                "review_invocation_id",
                "session_id",
                "provider",
                "model",
                "verdict",
                "exit_code",
                "review_segment_count",
            }
            review = result["review"]
            segment_count = identity.get("review_segment_count")
            expected_exit_code = {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}[verdict]
            if (
                set(identity) != identity_fields
                or identity.get("run_id") != continuation["run_id"]
                or identity.get("cell_id") != continuation["cell_id"]
                or identity.get("review_invocation_id") != result.get("review_invocation_id")
                or identity.get("session_id") != review.get("session_id")
                or identity.get("provider") != review.get("provider")
                or identity.get("model") != review.get("model")
                or identity.get("verdict") != verdict
                or identity.get("exit_code") != expected_exit_code
                or isinstance(review.get("exit_code"), bool)
                or not isinstance(review.get("exit_code"), int)
                or not isinstance(segment_count, int)
                or isinstance(segment_count, bool)
                or segment_count < 0
                or "started.json" not in terminal["evidence"]
                or "ocrv-result.json" not in terminal["evidence"]
            ):
                raise CompletionError(
                    "CHECKER_D1_EVIDENCE_INVALID",
                    "OCRV D1 terminal native identity does not bind the actual result",
                )
            if segment_count == 0:
                if (
                    result.get("review_invocation_id") != started["native_task"]["id"]
                    or result.get("request_sha256") != started["native_request_sha256"]
                ):
                    raise CompletionError(
                        "CHECKER_D1_EVIDENCE_INVALID",
                        "OCRV D1 result does not bind the native request",
                    )
            else:
                aggregate_path = native_attempt / "ocrv-aggregate.json"
                aggregate = _read_object(aggregate_path, "OCRV D1 aggregate")
                aggregate_hash = _sha256(aggregate_path)
                segments = aggregate.get("segments")
                if (
                    result["artifacts"].get("aggregate") != "ocrv-aggregate.json"
                    or result["evidence"] != [aggregate_hash]
                    or "ocrv-aggregate.json" not in terminal["evidence"]
                    or aggregate.get("schema_version") != "slk.ocrv-d1-aggregate/v1"
                    or aggregate.get("run_id") != continuation["run_id"]
                    or aggregate.get("cell_id") != continuation["cell_id"]
                    or aggregate.get("verdict") != verdict
                    or aggregate.get("completed_segment_count") != segment_count
                    or not isinstance(segments, list)
                    or len(segments) != segment_count
                ):
                    raise CompletionError(
                        "CHECKER_D1_EVIDENCE_INVALID",
                        "OCRV D1 aggregate evidence does not bind the terminal result",
                    )
                for ordinal, segment in enumerate(segments, start=1):
                    segment_root = native_attempt / "review-segments" / f"segment-{ordinal:03d}"
                    correction_root = native_attempt / "review-corrections" / f"segment-{ordinal:03d}"
                    segment_result_path = (
                        correction_root if correction_root.is_dir() else segment_root
                    ) / "result.json"
                    if (
                        not isinstance(segment, Mapping)
                        or segment.get("ordinal") != ordinal
                        or not segment_result_path.is_file()
                        or segment.get("result_sha256") != _sha256(segment_result_path)
                    ):
                        raise CompletionError(
                            "CHECKER_D1_EVIDENCE_INVALID",
                            "OCRV D1 aggregate segment evidence is invalid",
                        )
        event_type = {
            "PASS": "D1_PASSED",
            "FAIL": "D1_FAILED",
            "INCOMPLETE": "D1_INCOMPLETE",
        }[verdict]
        details = {
            "candidate_message_id": candidate_message_id,
            "verdict": verdict,
            "native_start_sha256": _sha256(started_path),
            "native_terminal_path": str(terminal_path),
            "native_terminal_sha256": _sha256(terminal_path),
            "native_result_path": str(result_path) if result is not None else None,
            "native_result_sha256": _sha256(result_path) if result is not None else None,
            "native_aggregate_path": str(aggregate_path) if aggregate_path is not None else None,
            "native_aggregate_sha256": _sha256(aggregate_path) if aggregate_path is not None else None,
            "review_invocation_id": result.get("review_invocation_id") if result is not None else None,
            "session_id": result["review"].get("session_id") if result is not None else None,
            "reason_codes": result.get("reason_codes") if result is not None else [terminal.get("error_code")],
        }
        if native_message_id != candidate_message_id:
            details["native_message_id"] = native_message_id
        occurred_at = datetime.fromtimestamp(terminal_path.stat().st_mtime, tz=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        suffix = (
            'd1-' + str(continuation.get('d1_correction_kind', 'budget')) + '-'
            + str(continuation['d1_correction_id'])
            if continuation.get('d1_correction_event_id')
            else 'd1-partial-' + str(continuation['partial_recovery_invocation_id'])
            if continuation.get('partial_correction_event_id')
            else 'd1-result-v2'
        )
        write_checker_event(event_type, suffix, details, occurred_at)
    finally:
        credential = ""
    return {
        "status": "CHECKER_D1_RECORDED",
        "d1_verdict": verdict,
        "d1_event_type": event_type,
        "native_attempt_path": str(native_attempt),
        "native_result_path": str(result_path) if result is not None else None,
    }


def _default_record_checker_d1(
    activation: Mapping[str, Any],
    continuation: Mapping[str, Any],
    credential_path: Path,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    return _record_checker_d1(
        activation,
        continuation,
        checker_credential_path=credential_path,
        timeout_seconds=timeout_seconds,
    )


def execute_checker_recovery(
    request: Mapping[str, Any],
    *,
    request_sha256: str,
    authenticate_checker: CheckerAuthenticate = _default_checker_authenticate,
    resume_continuation: ResumeContinuation = resume_worker_continuation,
    activate_checker: ActivateChecker = _activate_staged_checker,
    record_checker_d1: RecordCheckerD1 = _default_record_checker_d1,
    load_committed_activation: LoadCommittedActivation = _load_commit_only_checker_activation,
) -> dict[str, Any]:
    """Authenticate the exact OCRV Checker before resuming one Worker completion suffix."""

    fields = {
        "schema_version",
        "method_version",
        "recovery_invocation_id",
        "recovery_envelope_message_id",
        "run_id",
        "go_id",
        "cell_id",
        "checker_role_instance_id",
        "checker_endpoint_version",
        "checker_endpoint",
        "source_attempt_root",
        "runtime_projection_path",
        "plan_revision",
        "runtime_revision",
        "token_sequence",
        "worker_credential_path",
        "checker_credential_path",
        "state_command",
        "transport_command",
        "occurred_at",
        "result_path",
    }
    pre_d0_fields = {"environment_adjustment_path", "environment_adjustment_sha256"}
    pre_d0 = bool(set(request) & pre_d0_fields)
    expected_fields = fields | pre_d0_fields if pre_d0 else fields
    if set(request) != expected_fields or request.get("schema_version") != CHECKER_RECOVERY_SCHEMA:
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "Checker recovery request is not closed")
    if request.get("method_version") not in SUPPORTED_METHOD_VERSIONS:
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "Checker recovery requires a supported SLK patch")
    role_instance_id = request.get("checker_role_instance_id")
    invocation_id = request.get("recovery_invocation_id")
    endpoint_version = request.get("checker_endpoint_version")
    if (
        os.environ.get("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID") != role_instance_id
        or os.environ.get("SLK_OCRV_RECOVERY_INVOCATION_ID") != invocation_id
        or os.environ.get("SLK_OCRV_RECOVERY_ENDPOINT_VERSION") != str(endpoint_version)
    ):
        raise CompletionError(
            "CHECKER_RECOVERY_NATIVE_IDENTITY_UNPROVEN",
            "recovery is not running inside the exact OCRV Checker invocation",
        )
    try:
        checker = Endpoint.from_dict(request["checker_endpoint"])
    except (TypeError, ValueError) as exc:
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "Checker endpoint is invalid") from exc
    if (
        checker.role != "checker"
        or checker.role_instance_id != role_instance_id
        or checker.endpoint_version != endpoint_version
        or checker.run_id != request.get("run_id")
    ):
        raise CompletionError("CHECKER_RECOVERY_IDENTITY_MISMATCH", "Checker endpoint identity is not exact")
    state_command = request.get("state_command")
    transport_command = request.get("transport_command")
    if (
        not isinstance(state_command, list)
        or not state_command
        or not all(isinstance(item, str) and item for item in state_command)
        or not isinstance(transport_command, list)
        or not transport_command
        or not all(isinstance(item, str) and item for item in transport_command)
    ):
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "closed commands are required")
    authentication = authenticate_checker(
        str(request["run_id"]),
        str(role_instance_id),
        Path(str(request["checker_credential_path"])),
        list(state_command),
    )
    authenticated_revision = authentication.get("runtime_revision")
    if (
        authentication.get("status") != "authenticated"
        or authentication.get("role") != "checker"
        or authentication.get("role_instance_id") != role_instance_id
        or isinstance(authenticated_revision, bool)
        or not isinstance(authenticated_revision, int)
    ):
        raise CompletionError(
            "CHECKER_RECOVERY_AUTHENTICATION_FAILED",
            "credential does not prove the current Checker",
        )
    projection = _read_object(Path(str(request["runtime_projection_path"])), "runtime projection")
    continuation = build_continuation_request(
        str(request["source_attempt_root"]),
        request["checker_endpoint"],
        projection,
        plan_revision=int(request["plan_revision"]),
        runtime_revision=int(request["runtime_revision"]),
        token_sequence=int(request["token_sequence"]),
        credential_path=str(request["worker_credential_path"]),
        state_command=list(state_command),
        transport_command=list(transport_command),
        occurred_at=str(request["occurred_at"]),
        environment_adjustment_path=(
            str(request["environment_adjustment_path"]) if pre_d0 else None
        ),
        environment_adjustment_sha256=(
            str(request["environment_adjustment_sha256"]) if pre_d0 else None
        ),
    )
    if continuation["method_version"] != request["method_version"]:
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "Checker request and Run versions differ")
    if authenticated_revision == request.get("runtime_revision"):
        outcome = (
            _reuse_committed_checker_delivery(continuation)
            if continuation.get("checker_token_already_committed") is True
            else resume_continuation(continuation)
        )
        if outcome.get("status") != "CHECKER_DELIVERY_READY":
            raise CompletionError("CHECKER_RECOVERY_FAILED", "Worker continuation did not stage Checker D1")
        activated = activate_checker(outcome, continuation)
        if (
            activated.get("status") != "CHECKER_STARTED"
            or activated.get("candidate_message_id") != outcome.get("candidate_message_id")
        ):
            raise CompletionError("CHECKER_RECOVERY_FAILED", "external OCRV host did not start Checker D1")
    else:
        activated = load_committed_activation(continuation, authenticated_revision)
        if activated.get("status") != "CHECKER_STARTED":
            raise CompletionError(
                "CHECKER_RECOVERY_AUTHENTICATION_FAILED",
                "newer Checker revision lacks an exact commit-only recovery",
            )
    timeout_seconds = checker.address.get("timeout_seconds")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise CompletionError("CHECKER_RECOVERY_REQUEST_INVALID", "Checker timeout is invalid")
    d1 = record_checker_d1(
        activated,
        continuation,
        Path(str(request["checker_credential_path"])),
        float(timeout_seconds),
    )
    if d1.get("status") != "CHECKER_D1_RECORDED" or d1.get("d1_verdict") not in {
        "PASS",
        "FAIL",
        "INCOMPLETE",
    }:
        raise CompletionError("CHECKER_RECOVERY_FAILED", "actual OCRV D1 result was not recorded")
    return {
        "schema_version": CHECKER_RECOVERY_RESULT_SCHEMA,
        "method_version": request["method_version"],
        "status": "CHECKER_D1_RECORDED",
        "run_id": request["run_id"],
        "cell_id": request["cell_id"],
        "source_message_id": continuation["source_message_id"],
        "worker_session_id": continuation["worker_session_id"],
        "checker_role_instance_id": role_instance_id,
        "checker_endpoint_version": endpoint_version,
        "checker_authenticated": True,
        "authorized_recovery": True,
        "recovery_invocation_id": invocation_id,
        "request_sha256": request_sha256,
        "runtime_revision": activated["runtime_revision"],
        "token_sequence": activated["token_sequence"],
        "checker_token_already_committed": activated["checker_token_already_committed"],
        "native_attempt_path": activated["native_attempt_path"],
        "d1_verdict": d1["d1_verdict"],
        "d1_event_type": d1["d1_event_type"],
        "native_result_path": d1["native_result_path"],
    }


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


def _validate_committed_terminal_request(request: Mapping[str, Any], *, source_only: bool = False,
                                         partial_review: Mapping[str, Any] | None = None,
                                         d1_correction: Mapping[str, Any] | None = None,
                                         audit_lineage: frozenset[str] | None = None,
                                         audit_management_return: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if 'independent_fail' in request:
        from .independent_checker_fail import validate
        try:
            return validate(request)
        except (OSError, ValueError, KeyError, TypeError, AdapterError, ContractError) as exc:
            raise CompletionError('CHECKER_INDEPENDENT_FAIL_EVIDENCE_INVALID', str(exc)) from exc
    if 'partial_terminal' in request and not source_only:
        from .partial_review import validate_partial_terminal
        try:
            return validate_partial_terminal(request)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CompletionError('CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID', str(exc)) from exc
    fields = {
        "schema_version",
        "method_version",
        "recovery_invocation_id",
        "run_id",
        "go_id",
        "cell_id",
        "attempt",
        "plan_revision",
        "runtime_revision",
        "token_sequence",
        "worker_role_instance_id",
        "checker_role_instance_id",
        "checker_endpoint_version",
        "checker_endpoint",
        "runtime_projection_path",
        "runtime_projection_sha256",
        "candidate_repository",
        "candidate_commit",
        "candidate_parent",
        "candidate_message_id",
        "payload_sha256",
        "candidate_submitted_event_id",
        "transport_started_event_id",
        "commit_request_path",
        "commit_request_sha256",
        "native_attempt_path",
        "raw_review_path",
        "immutable_sha256",
        "checker_credential_path",
        "state_command",
        "transport_command",
        "result_path",
    }
    recovery_terminal = request.get("recovery_terminal")
    if d1_correction is None and isinstance(recovery_terminal, Mapping):
        candidate_correction = recovery_terminal.get("d1_correction")
        d1_correction = candidate_correction if isinstance(candidate_correction, Mapping) else None
    if d1_correction is not None and partial_review is None and (
        set(d1_correction) != {
            "correction_id", "d1_started_event_id", "d1_incomplete_event_id",
            "native_terminal_sha256", "native_result_sha256",
        }
        or not all(
            isinstance(d1_correction.get(name), str) and bool(d1_correction[name])
            for name in ("correction_id", "d1_started_event_id", "d1_incomplete_event_id")
        )
        or not _exact_digest(d1_correction.get("native_terminal_sha256"))
        or not _exact_digest(d1_correction.get("native_result_sha256"))
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID", "D1 correction identity is not closed"
        )
    correction = d1_correction or partial_review
    if recovery_terminal is not None:
        fields.add("recovery_terminal")
    if (
        set(request) != fields
        or request.get("schema_version") != COMMITTED_TERMINAL_SCHEMA
        or request.get("method_version") not in SUPPORTED_METHOD_VERSIONS
        or not all(
            _positive_integer(request.get(name))
            for name in (
                "attempt", "plan_revision", "runtime_revision", "token_sequence",
                "checker_endpoint_version",
            )
        )
        or not all(
            isinstance(request.get(name), str) and bool(request.get(name))
            for name in (
                "recovery_invocation_id",
                "run_id",
                "go_id",
                "cell_id",
                "worker_role_instance_id",
                "checker_role_instance_id",
                "candidate_repository",
                "candidate_message_id",
                "candidate_submitted_event_id",
                "transport_started_event_id",
                "checker_credential_path",
                "result_path",
            )
        )
        or not all(_nonempty_strings(request.get(name)) for name in ("state_command", "transport_command"))
        or not all(_exact_commit(request.get(name)) for name in ("candidate_commit", "candidate_parent"))
        or not all(
            _exact_digest(request.get(name))
            for name in (
                "runtime_projection_sha256",
                "payload_sha256",
                "commit_request_sha256",
            )
        )
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID",
            "committed-terminal request is not closed",
        )
    try:
        checker = Endpoint.from_dict(request["checker_endpoint"])
    except (TypeError, ValueError) as exc:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID",
            "Checker endpoint is invalid",
        ) from exc
    if (
        checker.role != "checker"
        or checker.agent_runtime != "ocrv"
        or checker.adapter != "ocrv-checker"
        or checker.state != "active"
        or checker.run_id != request["run_id"]
        or checker.role_instance_id != request["checker_role_instance_id"]
        or checker.endpoint_version != request["checker_endpoint_version"]
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_IDENTITY_MISMATCH",
            "registered Checker identity is not exact",
        )
    if not Path(str(request["checker_credential_path"])).resolve().is_file():
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID",
            "sealed Checker credential is unavailable",
        )
    state_command = request["state_command"]
    transport_command = request["transport_command"]
    state_path = Path(state_command[0]).resolve()
    direct_transport = False
    launcher_transport = False
    if len(transport_command) == 2:
        python_path = Path(transport_command[0]).resolve()
        transport_path = Path(transport_command[1]).resolve()
        direct_transport = (
            python_path == Path(sys.executable).resolve()
            and transport_path.name.lower() == "slk-transport.pyz"
            and transport_path.is_file()
            and state_path.parent == transport_path.parent
        )
    elif len(transport_command) == 1:
        launcher_path = Path(transport_command[0]).resolve()
        zipapp_path = launcher_path.with_name("slk-transport.pyz")
        try:
            launcher_text = launcher_path.read_text(encoding="utf-8-sig").replace(
                "\r\n", "\n"
            )
        except (OSError, UnicodeError):
            launcher_text = ""
        launcher_transport = (
            launcher_path.name.lower() == "slk-transport.cmd"
            and launcher_path.is_file()
            and zipapp_path.is_file()
            and state_path.parent == launcher_path.parent
            and launcher_text
            == '@echo off\npython "%~dp0slk-transport.pyz" %*\nexit /b %ERRORLEVEL%\n'
        )
    if (
        len(state_command) != 1
        or state_path.name.lower() != "slk-state.exe"
        or not state_path.is_file()
        or not (direct_transport or launcher_transport)
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID",
            "state or transport command is not the installed closed runtime",
        )

    projection_path = Path(str(request["runtime_projection_path"])).resolve()
    if not projection_path.is_file() or _sha256(projection_path) != request["runtime_projection_sha256"]:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "runtime projection is missing or changed",
        )
    projection = _read_object(projection_path, "committed-terminal runtime projection")
    if audit_management_return is not None and not (source_only and correction is not None and audit_lineage):
        raise CompletionError('CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID', 'management lineage is internal to a proven correction')
    candidate_token_sequence = (audit_management_return['candidate_token_sequence']
        if audit_management_return else request['token_sequence'])
    current_message_id = (audit_management_return['message_id']
        if audit_management_return else request['candidate_message_id'])
    summary = projection.get("summary")
    administrative = projection.get("administrative_snapshot")
    runtime = projection.get("runtime_snapshot")
    events = projection.get("events")
    roles = projection.get("roles")
    token_history = projection.get("token_history")
    shared_state = {"run_id": request["run_id"], "state": "active", "closure_state": "open"}
    try:
        token_boundary = resolve_authoritative_token_boundary(
            projection, run_id=request["run_id"], plan_revision=request["plan_revision"])
    except CompletionError as exc:
        raise CompletionError("CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
                              "current Checker TOKEN boundary is not authoritative") from exc
    if (
        not _matches(projection, {"schema_version": "slk.bi.run/v1", "run_id": request["run_id"]})
        or not _matches(summary, {
            **shared_state, "slk_version": request["method_version"],
            "current_plan_revision": request["plan_revision"],
        })
        or not _matches(administrative, {
            **shared_state, "latest_event_id": (correction['d1_incomplete_event_id']
                if correction is not None else request["transport_started_event_id"]),
        })
        or not _matches(runtime, {
            "run_id": request["run_id"], "method_version": request["method_version"],
            "plan_revision": request["plan_revision"],
            "runtime_revision": request["runtime_revision"],
            "token_sequence": request["token_sequence"],
            "token_holder_role_instance_id": request["checker_role_instance_id"],
        })
        or token_boundary["message_id"] != current_message_id
        or not all(isinstance(value, list) for value in (events, roles, token_history))
        or not token_history
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
            "current Run no longer exposes the exact committed Checker boundary",
        )
    checker_roles = [
        role
        for role in roles
        if isinstance(role, Mapping)
        and role.get("role") == "checker"
        and role.get("role_instance_id") == request["checker_role_instance_id"]
    ]
    worker_roles = [
        role
        for role in roles
        if isinstance(role, Mapping)
        and role.get("role") == "worker"
        and role.get("role_instance_id") == request["worker_role_instance_id"]
    ]
    if len(checker_roles) != 1 or len(worker_roles) != 1:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_IDENTITY_MISMATCH",
            "current Worker or Checker role identity is missing or duplicated",
        )
    checker_role = checker_roles[0]
    worker_role = worker_roles[0]
    endpoint_rows = checker_role.get("endpoints")
    matching_endpoint = [
        row
        for row in endpoint_rows
        if isinstance(row, Mapping)
        and row.get("endpoint_version") == checker.endpoint_version
        and row.get("transport_adapter") == checker.adapter
        and row.get("state") == "active"
        and row.get("retired_at") is None
    ] if isinstance(endpoint_rows, list) else []
    if (
        checker_role.get("agent_runtime") != "ocrv"
        or checker_role.get("lifecycle") != "active"
        or len(matching_endpoint) != 1
        or worker_role.get("agent_runtime") != "dsh"
        or worker_role.get("lifecycle") != "active"
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_IDENTITY_MISMATCH",
            "current Worker or Checker role is not active and exact",
        )

    candidate_matches = []
    transport_matches = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if (
            event.get("cell_id") == request["cell_id"]
            and event.get("attempt") == request["attempt"]
            and event.get("event_type") in {"D1_STARTED", "D1_PASSED", "D1_FAILED", "D1_INCOMPLETE"}
        ):
            if source_only and correction is not None and audit_lineage is not None and (
                event.get('event_id') in audit_lineage
                and event.get('event_type') in {'D1_STARTED', 'D1_INCOMPLETE'}
                and event.get('author_role_instance_id') == request['checker_role_instance_id']
                and _committed_event_details(event).get('candidate_message_id') == request['candidate_message_id']
            ):
                continue  # independently checked complete correction chain, never a general D1 bypass
            if correction is not None and event.get('event_id') == correction.get(
                {'D1_STARTED': 'd1_started_event_id', 'D1_INCOMPLETE': 'd1_incomplete_event_id'}.get(event.get('event_type'), '')
            ) and event.get('author_role_instance_id') == request['checker_role_instance_id'] and (
                _committed_event_details(event).get('candidate_message_id') == request['candidate_message_id']
            ):
                details = _committed_event_details(event)
                if event.get('event_type') == 'D1_INCOMPLETE' and (
                    correction.get('native_terminal_sha256') is not None
                    and (
                        details.get('verdict') != 'INCOMPLETE'
                        or details.get('native_terminal_sha256') != correction.get('native_terminal_sha256')
                        or details.get('native_result_sha256') != correction.get('native_result_sha256')
                    )
                ):
                    raise CompletionError(
                        "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
                        "source D1 INCOMPLETE does not bind the terminal-budget evidence",
                    )
                continue
            raise CompletionError(
                "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
                "the target attempt already has a D1 event",
            )
        event_type = event.get("event_type")
        if event_type not in {"CANDIDATE_SUBMITTED", "TRANSPORT_STARTED"}:
            continue
        details = _committed_event_details(event)
        if (
            event_type == "CANDIDATE_SUBMITTED"
            and details.get("handoff_message_id") == request["candidate_message_id"]
        ):
            candidate_matches.append((event, details))
        if (
            event_type == "TRANSPORT_STARTED"
            and details.get("message_id") == request["candidate_message_id"]
        ):
            transport_matches.append((event, details))
    if len(candidate_matches) != 1 or len(transport_matches) != 1:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "candidate submission or committed transport event is missing or duplicated",
        )
    candidate_event, candidate_details = candidate_matches[0]
    transport_event, transport_details = transport_matches[0]
    expected_scope = (
        request["go_id"],
        request["cell_id"],
        request["attempt"],
        request["worker_role_instance_id"],
    )
    if (
        candidate_event.get("event_id") != request["candidate_submitted_event_id"]
        or transport_event.get("event_id") != request["transport_started_event_id"]
        or tuple(candidate_event.get(name) for name in ("go_id", "cell_id", "attempt", "author_role_instance_id"))
        != expected_scope
        or tuple(transport_event.get(name) for name in ("go_id", "cell_id", "attempt", "author_role_instance_id"))
        != expected_scope
        or candidate_details.get("candidate")
        != {"kind": "commit", "commit": request["candidate_commit"]}
        or candidate_details.get("checker_endpoint_version") != checker.endpoint_version
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "central candidate or handoff identity does not match the request",
        )
    last_token = token_history[-1]
    if (
        not isinstance(last_token, Mapping)
        or last_token.get("event_type") != "TOKEN_HANDED_OFF"
        or last_token.get("from_role_instance_id") != (audit_management_return['supervisor_role_instance_id']
            if audit_management_return else request["worker_role_instance_id"])
        or last_token.get("to_role_instance_id") != request["checker_role_instance_id"]
        or last_token.get("go_id") != request["go_id"]
        or last_token.get("cell_id") != request["cell_id"]
        or last_token.get("message_id") != current_message_id
        or last_token.get("token_sequence") != request["token_sequence"]
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
            "TOKEN history no longer ends at the exact Checker handoff",
        )

    commit_path = Path(str(request["commit_request_path"])).resolve()
    if not commit_path.is_file() or _sha256(commit_path) != request["commit_request_sha256"]:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "commit-delivery-start request is missing or changed",
        )
    commit = _read_object(commit_path, "commit-delivery-start request")
    commit_fields = {
        "event_id",
        "transport_receipt_id",
        "run_id",
        "go_id",
        "cell_id",
        "attempt",
        "plan_revision",
        "expected_runtime_revision",
        "message_id",
        "token_sequence",
        "from_role_instance_id",
        "to_role_instance_id",
        "endpoint_version",
        "payload_type",
        "payload_sha256",
        "start_evidence",
        "occurred_at",
    }
    start_evidence = commit.get("start_evidence")
    native_attempt = Path(str(request["native_attempt_path"])).resolve()
    started_path = native_attempt / "started.json"
    if (
        set(commit) != commit_fields
        or commit.get("event_id") != request["transport_started_event_id"]
        or commit.get("run_id") != request["run_id"]
        or commit.get("go_id") != request["go_id"]
        or commit.get("cell_id") != request["cell_id"]
        or commit.get("attempt") != request["attempt"]
        or commit.get("plan_revision") != request["plan_revision"]
        or isinstance(commit.get("expected_runtime_revision"), bool)
        or not isinstance(commit.get("expected_runtime_revision"), int)
        or commit.get("expected_runtime_revision") >= request["runtime_revision"]
        or commit.get("message_id") != request["candidate_message_id"]
        or commit.get("token_sequence") != candidate_token_sequence
        or commit.get("from_role_instance_id") != request["worker_role_instance_id"]
        or commit.get("to_role_instance_id") != request["checker_role_instance_id"]
        or commit.get("endpoint_version") != checker.endpoint_version
        or commit.get("payload_type") != "CANDIDATE_READY"
        or commit.get("payload_sha256") != request["payload_sha256"]
        or not isinstance(start_evidence, Mapping)
        or Path(str(start_evidence.get("stored_path", ""))).resolve() != started_path
        or start_evidence.get("message_id") != request["candidate_message_id"]
        or start_evidence.get("native_status") != "STARTED"
        or transport_details.get("transport_receipt_id") != commit.get("transport_receipt_id")
        or transport_details.get("start_evidence_id") != start_evidence.get("evidence_id")
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "commit-delivery-start does not bind the current candidate handoff",
        )

    immutable = request.get("immutable_sha256")
    expected_names = (
        {"endpoint.json", "envelope.json", "started.json", "ocrv-request.json"}
        if recovery_terminal is not None or source_only
        else {
            "endpoint.json", "envelope.json", "started.json", "ocrv-request.json",
            "completed.json", "ocrv-result.json", "raw_review",
        }
    )
    if (
        not isinstance(immutable, Mapping)
        or set(immutable) != expected_names
        or not all(_exact_digest(value) for value in immutable.values())
        or native_attempt.name != request["candidate_message_id"]
        or native_attempt.parent.name != request["run_id"]
        or (partial_review is None and (native_attempt / "failed.json").exists())
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "immutable OCRV evidence index is invalid",
        )
    evidence_paths = {
        name: native_attempt / name
        for name in expected_names
        if name != "raw_review"
    }
    if partial_review is not None:
        evidence_paths['ocrv-request.json'] = native_attempt / 'review-segments/segment-001/request.json'
    raw_review_path = Path(str(request["raw_review_path"])).resolve()
    if recovery_terminal is None and not source_only:
        evidence_paths["raw_review"] = raw_review_path
    if any(
        not path.is_file() or _sha256(path) != immutable[name]
        for name, path in evidence_paths.items()
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "immutable OCRV evidence is missing or changed",
        )
    if (
        start_evidence.get("sha256") != immutable["started.json"]
        or start_evidence.get("endpoint_sha256") != immutable["endpoint.json"]
        or start_evidence.get("envelope_sha256") != immutable["envelope.json"]
        or transport_details.get("start_evidence_sha256") != immutable["started.json"]
        or transport_details.get("endpoint_sha256") != immutable["endpoint.json"]
        or transport_details.get("envelope_sha256") != immutable["envelope.json"]
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "central commit hashes do not match immutable OCRV evidence",
        )
    adapter = OcrvAdapter()
    try:
        delivery = parse_delivery(
            _read_object(evidence_paths["endpoint.json"], "OCRV endpoint"),
            _read_object(evidence_paths["envelope.json"], "OCRV envelope"),
        )
        adapter.validate_address(delivery.endpoint)
        started = validate_native_start(
            evidence_paths["started.json"],
            adapter=checker.adapter,
            run_id=str(request["run_id"]),
            cell_id=str(request["cell_id"]),
            message_id=str(request["candidate_message_id"]),
            request_sha256=str(request["payload_sha256"]),
        )
    except (AdapterError, ContractError, NativeActivityError, TypeError, ValueError) as exc:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV endpoint, envelope or native start is invalid",
        ) from exc
    persisted_endpoint = delivery.endpoint
    envelope = delivery.envelope
    payload = envelope.payload
    if (
        persisted_endpoint != checker
        or envelope.run_id != request["run_id"]
        or envelope.go_id != request["go_id"]
        or envelope.cell_id != request["cell_id"]
        or envelope.message_id != request["candidate_message_id"]
        or envelope.sender_role != "worker"
        or envelope.sender_role_instance_id != request["worker_role_instance_id"]
        or envelope.receiver_role != "checker"
        or envelope.receiver_role_instance_id != request["checker_role_instance_id"]
        or envelope.receiver_endpoint_version != checker.endpoint_version
        or envelope.token_sequence != candidate_token_sequence
        or envelope.payload_type != "CANDIDATE_READY"
        or envelope.payload_sha256 != request["payload_sha256"]
        or not isinstance(payload, Mapping)
        or payload.get("candidate") != {"kind": "commit", "commit": request["candidate_commit"]}
        or Path(str(payload.get("repository", ""))).resolve()
        != Path(str(request["candidate_repository"])).resolve()
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV delivery identity does not match the committed candidate",
        )
    ocrv_request = _read_object(evidence_paths["ocrv-request.json"], "OCRV request")
    if (
        ocrv_request.get("schema_version") != "slk.ocrv-d1-request/v2"
        or ocrv_request.get("run_id") != request["run_id"]
        or ocrv_request.get("cell_id") != request["cell_id"]
        or ocrv_request.get("candidate")
        != {"kind": "commit", "commit": request["candidate_commit"]}
        or Path(str(ocrv_request.get("repository", ""))).resolve()
        != Path(str(request["candidate_repository"])).resolve()
        or started.get("native_task", {}).get("kind") != "ocrv-review"
        or started.get("native_request_sha256") != immutable["ocrv-request.json"]
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV native request does not bind the committed candidate",
        )
    if source_only: return {"checker": checker, 'frozen_projection': projection}
    terminal_attempt = native_attempt
    result_request_path = evidence_paths["ocrv-request.json"]
    terminal_request_name = "ocrv-request.json"
    if recovery_terminal is not None:
        if not isinstance(recovery_terminal, Mapping):
            raise CompletionError(
                "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID", "recovery terminal is not an object"
            )
        recovery_fields = {
            "native_attempt_path", "started_sha256", "completed_sha256",
            "ocrv_result_sha256", "raw_review_sha256",
        }
        ordinary_fields = recovery_fields | {"resume_request_sha256"}
        budget_fields = {
            "source_request_path", "source_request_sha256", "capacity_request_sha256",
            "resume_lineage_sha256", "native_session_sha256", "d1_correction",
        }
        fresh_budget_fields = {
            "compatibility_request_path", "compatibility_request_sha256",
            "capacity_request_sha256", "compatibility_lineage_sha256",
            "native_session_sha256", "d1_correction",
        }
        fresh_partial_budget_fields = {
            "fresh_partial_request_path", "fresh_partial_request_sha256",
            "capacity_request_sha256", "resume_lineage_sha256",
            "native_session_sha256", "d1_correction",
        }
        is_budget_resume = d1_correction is not None
        is_fresh_budget = is_budget_resume and "compatibility_request_path" in recovery_terminal
        is_fresh_partial_budget = (
            is_budget_resume and "fresh_partial_request_path" in recovery_terminal
        )
        expected_recovery_fields = (
            recovery_fields | fresh_budget_fields
            if is_fresh_budget
            else recovery_fields | fresh_partial_budget_fields
            if is_fresh_partial_budget
            else ordinary_fields | budget_fields
            if is_budget_resume
            else ordinary_fields
        )
        terminal_attempt = Path(str(recovery_terminal.get("native_attempt_path", ""))).resolve()
        native_request_name = "ocrv-capacity-request.json" if is_budget_resume else "ocrv-resume-request.json"
        recovered = {
            "started.json": recovery_terminal.get("started_sha256"),
            "completed.json": recovery_terminal.get("completed_sha256"),
            "ocrv-result.json": recovery_terminal.get("ocrv_result_sha256"),
            native_request_name: (
                recovery_terminal.get("capacity_request_sha256")
                if is_budget_resume else recovery_terminal.get("resume_request_sha256")
            ),
            "raw_review": recovery_terminal.get("raw_review_sha256"),
        }
        recovered_paths = {
            "started.json": terminal_attempt / "started.json",
            "completed.json": terminal_attempt / "completed.json",
            "ocrv-result.json": terminal_attempt / "ocrv-result.json",
            native_request_name: terminal_attempt / native_request_name,
            "raw_review": raw_review_path,
        }
        if (
            set(recovery_terminal) != expected_recovery_fields
            or (
                not is_fresh_budget and not is_fresh_partial_budget
                and terminal_attempt.parent.parent != native_attempt / (
                    "resume-terminal-budget-checker" if is_budget_resume else "resume-incomplete-checker"
                )
            )
            or any(not _exact_digest(value) for value in recovered.values())
            or any(not path.is_file() or _sha256(path) != recovered[name]
                   for name, path in recovered_paths.items())
        ):
            raise CompletionError(
                "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID", "recovery terminal evidence is invalid"
            )
        if is_budget_resume:
            from .terminal_budget import (
                read_session_records,
                validate as validate_terminal_budget,
                validate_resumed_child,
            )

            if is_fresh_budget:
                from .terminal_budget_fresh import (
                    validate_fresh_child,
                    validate_fresh_review_request,
                )

                source_path = Path(str(recovery_terminal["compatibility_request_path"])).resolve()
                source_digest = recovery_terminal["compatibility_request_sha256"]
                lineage_path = terminal_attempt / "compatibility-lineage.json"
                lineage_digest = recovery_terminal["compatibility_lineage_sha256"]
                compatibility = _read_object(source_path, "terminal-budget fresh-review request")
                budget_validated = validate_fresh_review_request(compatibility, consumed=True)
                source_request = budget_validated["source_request"]
                budget_basis = budget_validated
            elif is_fresh_partial_budget:
                from .terminal_budget_fresh_partial import (
                    validate_fresh_partial_child,
                    validate_fresh_partial_request,
                )

                source_path = Path(
                    str(recovery_terminal["fresh_partial_request_path"])
                ).resolve()
                source_digest = recovery_terminal["fresh_partial_request_sha256"]
                lineage_path = terminal_attempt / "resume-lineage.json"
                lineage_digest = recovery_terminal["resume_lineage_sha256"]
                partial_request = _read_object(
                    source_path, "terminal-budget fresh-partial request"
                )
                budget_validated = validate_fresh_partial_request(
                    partial_request, consumed=True
                )
                source_request = budget_validated["source_request"]
                budget_basis = budget_validated["source_validated"]
            else:
                source_path = Path(str(recovery_terminal["source_request_path"])).resolve()
                source_digest = recovery_terminal["source_request_sha256"]
                lineage_path = terminal_attempt / "resume-lineage.json"
                lineage_digest = recovery_terminal["resume_lineage_sha256"]
                source_request = _read_object(source_path, "terminal-budget source request")
                budget_validated = validate_terminal_budget(source_request, consumed=True)
                budget_basis = budget_validated
            if (
                not source_path.is_file() or _sha256(source_path) != source_digest
                or not lineage_path.is_file() or _sha256(lineage_path) != lineage_digest
                or (
                    not is_fresh_budget and not is_fresh_partial_budget
                    and recovery_terminal["resume_request_sha256"] != lineage_digest
                )
            ):
                raise CompletionError(
                    "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
                    "terminal-budget request or lineage changed",
                )
            original = _read_object(native_attempt / "ocrv-request.json", "original OCRV request")
            revised = _read_object(recovered_paths[native_request_name], "revised OCRV request")
            expected = dict(original)
            expected["capacity"] = {
                **dict(original["capacity"]), **source_request["capacity_revision"]["new"]
            }
            native_session_path = terminal_attempt / "native-session.jsonl"
            lineage = _read_object(lineage_path, "terminal-budget lineage")
            child_raw = _read_object(raw_review_path, "terminal-budget OCRV review")
            parent_raw = _read_object(
                Path(str(source_request["raw_review_path"])).resolve(), "parent OCRV review"
            )
            try:
                records = read_session_records(native_session_path)
            except (OSError, ValueError) as exc:
                raise CompletionError(
                    "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
                    "terminal-budget native child Session is invalid",
                ) from exc
            if (
                budget_basis["d1_correction"] != d1_correction
                or revised != expected
                or _sha256(native_session_path) != recovery_terminal["native_session_sha256"]
                or lineage.get("parent_session_id") != parent_raw.get("session_id")
                or lineage.get("child_session_id") != child_raw.get("session_id")
                or lineage.get("native_session_sha256") != recovery_terminal["native_session_sha256"]
            ):
                raise CompletionError(
                    "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
                    "terminal-budget revision, Session, or D1 correction changed",
                )
            try:
                target = {
                    "target_ocrv_version": budget_basis["target_ocrv_version"],
                    "target_rule_config_sha256": budget_basis["target_rule_config_sha256"],
                    "target_runtime_config_sha256": budget_basis["target_runtime_config_sha256"],
                }
                if is_fresh_budget:
                    validate_fresh_child(parent_raw, child_raw, child_records=records, **target)
                    if (
                        terminal_attempt != budget_validated["recovery_root"] / "native-attempt"
                        or lineage.get("schema_version")
                        != "slk.ocrv-terminal-budget-fresh-compatibility-lineage/v1"
                        or lineage.get("strategy") != compatibility["strategy"]
                        or lineage.get("source_request_sha256")
                        != compatibility["source_request_sha256"]
                        or lineage.get("source_rejection_sha256")
                        != compatibility["source_rejection_sha256"]
                        or lineage.get("compatibility_request_sha256") != source_digest
                        or lineage.get("candidate_commit") != request["candidate_commit"]
                        or lineage.get("candidate_message_id") != request["candidate_message_id"]
                        or lineage.get("d1_incomplete_event_id")
                        != d1_correction["d1_incomplete_event_id"]
                        or lineage.get("checkpoint_reuse") is not False
                    ):
                        raise ValueError("fresh compatibility identity changed")
                else:
                    resumes = [row for row in records if row.get("type") == "resume_lineage"]
                    ends = [row for row in records if row.get("type") == "session_end"]
                    if len(resumes) != 1 or len(ends) != 1 or ends[0].get(
                        "run_manifest"
                    ) != child_raw.get("manifest"):
                        raise ValueError("resume lineage is incomplete")
                    validate_resumed_child(parent_raw, child_raw, resumes[0], **target)
                    if is_fresh_partial_budget:
                        validate_fresh_partial_child(parent_raw, child_raw)
                        if (
                            terminal_attempt
                            != Path(str(partial_request["recovery_root"])).resolve()
                            / "native-attempt"
                            or lineage.get("source_request_path") != str(source_path)
                            or lineage.get("source_request_sha256") != source_digest
                        ):
                            raise ValueError("fresh-partial continuation identity changed")
            except ValueError as exc:
                raise CompletionError(
                    "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
                    "terminal-budget parent/child lineage is invalid",
                ) from exc
        try:
            started = validate_native_start(
                recovered_paths["started.json"], adapter=checker.adapter,
                run_id=str(request["run_id"]), cell_id=str(request["cell_id"]),
                message_id=str(request["candidate_message_id"]),
                request_sha256=str(request["payload_sha256"]),
                native_request_sha256=str(recovered[native_request_name]),
            )
        except NativeActivityError as exc:
            raise CompletionError(
                "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID", "recovery OCRV start is invalid"
            ) from exc
        evidence_paths.update(recovered_paths)
        result_request_path = recovered_paths[native_request_name]
        terminal_request_name = native_request_name
    try:
        terminal = DeliveryResult.from_dict(
            _read_object(evidence_paths["completed.json"], "OCRV terminal")
        )
        raw_result = _read_object(evidence_paths["ocrv-result.json"], "OCRV result")
        verdict = raw_result.get("verdict")
        if verdict not in VERDICT_EXIT_CODES:
            raise AdapterError("OCRV_RESULT_INVALID", "OCRV verdict is invalid")
        result = adapter.validate_existing_result(
            evidence_paths["ocrv-result.json"],
            result_request_path,
            envelope,
            VERDICT_EXIT_CODES[str(verdict)],
        )
    except (AdapterError, ContractError) as exc:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV terminal or result is invalid",
        ) from exc
    identity = terminal.native_identity
    review = result["review"]
    identity_fields = {
        "run_id", "cell_id", "review_invocation_id", "session_id", "provider",
        "model", "verdict", "exit_code", "review_segment_count",
    }
    if (
        terminal.status != "completed"
        or terminal.adapter != checker.adapter
        or terminal.run_id != request["run_id"]
        or terminal.message_id != request["candidate_message_id"]
        or terminal.error_code is not None
        or not {"started.json", terminal_request_name, "ocrv-result.json"}.issubset(terminal.evidence)
        or set(identity) != identity_fields
        or identity.get("review_segment_count") != 0
        or review.get("status") != "complete"
        or identity.get("run_id") != request["run_id"]
        or identity.get("cell_id") != request["cell_id"]
        or identity.get("review_invocation_id") != started["native_task"]["id"]
        or identity.get("review_invocation_id") != result["review_invocation_id"]
        or identity.get("session_id") != review["session_id"]
        or identity.get("provider") != review["provider"]
        or identity.get("model") != review["model"]
        or identity.get("verdict") != result["verdict"]
        or identity.get("exit_code") != VERDICT_EXIT_CODES[str(result["verdict"])]
        or Path(str(result["artifacts"].get("raw_review", ""))).resolve() != raw_review_path
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV terminal and result do not form one completed review",
        )
    raw_review = _read_object(raw_review_path, "OCRV raw review")
    manifest = raw_review.get("manifest")
    coverage = manifest.get("coverage") if isinstance(manifest, Mapping) else None
    manifest_input = manifest.get("input") if isinstance(manifest, Mapping) else None
    execution = manifest.get("execution") if isinstance(manifest, Mapping) else None
    selected = coverage.get("selected") if isinstance(coverage, Mapping) else None
    completed = coverage.get("completed") if isinstance(coverage, Mapping) else None
    reused = coverage.get("reused") if isinstance(coverage, Mapping) else None
    failed = coverage.get("failed") if isinstance(coverage, Mapping) else None
    waived = coverage.get("waived") if isinstance(coverage, Mapping) else None
    if (
        raw_review.get("status") != "complete"
        or raw_review.get("session_id") != review.get("session_id")
        or not isinstance(manifest, Mapping)
        or manifest.get("schema_version") != "ocr.run-manifest/v1"
        or manifest.get("run_id") != review.get("session_id")
        or manifest.get("operation") != "review"
        or manifest.get("terminal_state") != "complete"
        or not isinstance(manifest_input, Mapping)
        or manifest_input.get("requested_head") != request["candidate_commit"]
        or manifest_input.get("resolved_head") != request["candidate_commit"]
        or manifest_input.get("resolved_base") != request["candidate_parent"]
        or manifest_input.get("exact_range")
        != f"{request['candidate_parent']}..{request['candidate_commit']}"
        or not isinstance(execution, Mapping)
        or execution.get("provider") != review.get("provider")
        or execution.get("model") != review.get("model")
        or not isinstance(selected, list)
        or not selected
        or not isinstance(completed, list)
        or not isinstance(reused, list)
        or failed != []
        or waived != []
        or {json.dumps(item, sort_keys=True) for item in selected}
        != {json.dumps(item, sort_keys=True) for item in [*completed, *reused]}
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_EVIDENCE_INVALID",
            "OCRV raw review manifest does not prove complete candidate coverage",
        )
    continuation = {
        "run_id": request["run_id"],
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "plan_revision": request["plan_revision"],
        "source_message_id": request["candidate_message_id"],
        "checker_endpoint": request["checker_endpoint"],
        "state_command": request["state_command"],
        "occurred_at": str(started["observed_at"]),
    }
    if d1_correction is not None:
        continuation.update(
            d1_correction_event_id=d1_correction["d1_incomplete_event_id"],
            d1_correction_id=d1_correction["correction_id"],
        )
    activation = {
        "status": "CHECKER_STARTED",
        "runtime_revision": request["runtime_revision"],
        "token_sequence": request["token_sequence"],
        "candidate_message_id": request["candidate_message_id"],
        "checker_token_already_committed": True,
        "native_attempt_path": str(terminal_attempt),
    }
    return {
        "checker": checker,
        "continuation": continuation,
        "activation": activation,
        "frozen_projection": projection,
    }


def _committed_terminal_drift_invalid() -> None:
    raise CompletionError(
        "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED",
        "current runtime drift is not authenticated Overwatcher-only observation history",
    )


def _projection_additions(
    frozen: Mapping[str, Any], current: Mapping[str, Any], name: str, identity: str
) -> list[Mapping[str, Any]]:
    before, after = frozen.get(name), current.get(name)
    if not isinstance(before, list) or not isinstance(after, list):
        _committed_terminal_drift_invalid()
    before_by_id = {row.get(identity): row for row in before if isinstance(row, Mapping)}
    after_by_id = {row.get(identity): row for row in after if isinstance(row, Mapping)}
    if (
        len(before_by_id) != len(before)
        or len(after_by_id) != len(after)
        or any(not isinstance(item, str) or not item for item in after_by_id)
        or any(after_by_id.get(item) != row for item, row in before_by_id.items())
    ):
        _committed_terminal_drift_invalid()
    return [row for item, row in after_by_id.items() if item not in before_by_id]


def _rebind_overwatcher_only_committed_boundary(
    request: Mapping[str, Any], frozen: Mapping[str, Any], current: Mapping[str, Any],
    authenticated_revision: int,
) -> int:
    """Accept authenticated projection drift only when engineering truth is unchanged."""

    old_runtime, now_runtime = frozen.get("runtime_snapshot"), current.get("runtime_snapshot")
    if not isinstance(old_runtime, Mapping) or not isinstance(now_runtime, Mapping):
        _committed_terminal_drift_invalid()
    revision = old_runtime.get("runtime_revision")
    runtime_ow_fields = {"runtime_revision", "latest_event_id", "overwatcher_status", "committed_at"}
    mutable_top = {
        "administrative_snapshot", "runtime_snapshot", "events", "overwatch_cycles",
        "overwatcher_native_status_receipts", "overwatcher_incident_transitions",
        "overwatcher_binding_transitions", "operational_observations",
    }
    if (
        isinstance(revision, bool) or not isinstance(revision, int)
        or isinstance(authenticated_revision, bool) or not isinstance(authenticated_revision, int)
        or authenticated_revision <= revision
        or now_runtime.get("runtime_revision") != authenticated_revision
        or set(current) != set(frozen)
        or {key: value for key, value in old_runtime.items() if key not in runtime_ow_fields}
        != {key: value for key, value in now_runtime.items() if key not in runtime_ow_fields}
        or any(current.get(name) != frozen.get(name) for name in frozen if name not in mutable_top)
    ):
        _committed_terminal_drift_invalid()

    roles = current.get("roles")
    watchers = [row for row in roles if isinstance(row, Mapping) and row.get("role") == "overwatcher"
                and row.get("lifecycle") == "active"] if isinstance(roles, list) else []
    supervisors = [row for row in roles if isinstance(row, Mapping) and row.get("role") == "supervisor"
                   and row.get("lifecycle") == "active"] if isinstance(roles, list) else []
    additions = {
        "event": _projection_additions(frozen, current, "events", "event_id"),
        "status": _projection_additions(
            frozen, current, "overwatcher_native_status_receipts", "status_id"
        ),
        "incident": _projection_additions(
            frozen, current, "overwatcher_incident_transitions", "transition_id"
        ),
        "observation": _projection_additions(
            frozen, current, "operational_observations", "observation_id"
        ),
        "cycle": _projection_additions(frozen, current, "overwatch_cycles", "cycle_id"),
        "binding": _projection_additions(
            frozen, current, "overwatcher_binding_transitions", "transition_id"
        ),
    }
    if (
        len(watchers) != 1 or additions["binding"]
        or authenticated_revision - revision
        != len(additions["status"]) + len(additions["event"])
    ):
        _committed_terminal_drift_invalid()
    watcher = watchers[0]
    watcher_id, watcher_session = watcher.get("role_instance_id"), watcher.get("session_id")
    binding_revision = now_runtime.get("overwatcher_binding_revision")
    if not all((watcher_id, watcher_session, binding_revision)):
        _committed_terminal_drift_invalid()

    all_statuses = current.get("overwatcher_native_status_receipts")
    statuses = {row.get("status_id"): row for row in all_statuses if isinstance(row, Mapping)} \
        if isinstance(all_statuses, list) else {}
    all_cycles = current.get("overwatch_cycles")
    cycles = {row.get("cycle_id"): row for row in all_cycles if isinstance(row, Mapping)} \
        if isinstance(all_cycles, list) else {}
    expected_incidents: dict[str, Mapping[str, Any]] = {}
    revision_items: dict[str, tuple[Any, str]] = {}
    for status in additions["status"]:
        status_id, liveness = status.get("status_id"), status.get("native_liveness")
        if (
            not isinstance(status_id, str) or not status_id
            or status.get("role_instance_id") != watcher_id
            or status.get("session_id") != watcher_session
            or status.get("binding_revision") != binding_revision
            or liveness not in {"IN_PROGRESS", "COMPLETED", "MISSING", "MISMATCHED"}
            or not _exact_digest(status.get("evidence_sha256"))
            or not isinstance(status.get("observed_at"), str)
        ):
            _committed_terminal_drift_invalid()
        revision_items[status_id] = (
            status.get("observed_at"), "ACTIVE" if liveness == "IN_PROGRESS" else "VIOLATION"
        )
        if liveness != "IN_PROGRESS":
            expected_incidents[f"incident-open-{status_id}"] = {
                "transition_id": f"incident-open-{status_id}",
                "incident_id": f"continuity-{request['run_id']}-{binding_revision}-{status_id}",
                "binding_revision": binding_revision,
                "incident_code": "OVERWATCHER_CONTINUITY_VIOLATION", "state": "OPEN",
                "evidence_path": status.get("evidence_path"),
                "evidence_sha256": status.get("evidence_sha256"),
                "occurred_at": status.get("observed_at"),
            }

    if additions["event"] and len(supervisors) != 1:
        _committed_terminal_drift_invalid()
    supervisor_id = supervisors[0].get("role_instance_id") if supervisors else None
    for event in additions["event"]:
        try:
            details = json.loads(str(event.get("details_json")))
        except json.JSONDecodeError:
            _committed_terminal_drift_invalid()
        evidence = details.get("native_active_session_evidence") if isinstance(details, Mapping) else None
        event_id = event.get("event_id")
        if (
            event.get("event_type") != "OVERWATCHER_TURN_RESUMED"
            or event.get("author_role_instance_id") != supervisor_id
            or any(event.get(name) is not None for name in ("go_id", "cell_id", "attempt"))
            or not isinstance(event_id, str) or not isinstance(details, Mapping)
            or details.get("role_instance_id") != watcher_id
            or details.get("session_id") != watcher_session
            or details.get("binding_revision") != binding_revision
            or not isinstance(evidence, Mapping) or not _exact_digest(evidence.get("sha256"))
            or not isinstance(event.get("occurred_at"), str)
        ):
            _committed_terminal_drift_invalid()
        last_status, last_cycle = details.get("last_native_status_id"), details.get("last_anomaly_cycle_id")
        if details.get("resume_basis") == "NATIVE_STATUS" and last_cycle is None:
            basis = statuses.get(last_status)
            if (
                not isinstance(basis, Mapping) or basis.get("role_instance_id") != watcher_id
                or basis.get("session_id") != watcher_session
                or basis.get("binding_revision") != binding_revision
                or basis.get("native_liveness") == "IN_PROGRESS"
            ):
                _committed_terminal_drift_invalid()
            expected_incidents[f"incident-resolved-{event_id}"] = {
                "transition_id": f"incident-resolved-{event_id}",
                "incident_id": f"continuity-{request['run_id']}-{binding_revision}-{last_status}",
                "binding_revision": binding_revision,
                "incident_code": "OVERWATCHER_CONTINUITY_VIOLATION", "state": "RESOLVED",
                "evidence_path": evidence.get("path"), "evidence_sha256": evidence.get("sha256"),
                "occurred_at": event.get("occurred_at"),
            }
        elif details.get("resume_basis") == "ANOMALY_CYCLE" and last_status is None:
            basis = cycles.get(last_cycle)
            if (
                not isinstance(basis, Mapping)
                or basis.get("overwatcher_role_instance_id") != watcher_id
                or basis.get("session_id") != watcher_session
                or basis.get("binding_revision") != binding_revision
                or basis.get("anomaly_codes_json") in {None, "[]"}
            ):
                _committed_terminal_drift_invalid()
        else:
            _committed_terminal_drift_invalid()
        revision_items[event_id] = (event.get("occurred_at"), "ACTIVE")

    if any(
        row.get("overwatcher_role_instance_id") != watcher_id
        or row.get("session_id") != watcher_session
        or row.get("binding_revision") != binding_revision
        or row.get("plan_revision") != request.get("plan_revision")
        or row.get("token_sequence") != request.get("token_sequence")
        or row.get("latest_message_id") != request.get("candidate_message_id")
        or row.get("native_liveness") != "IN_PROGRESS"
        or isinstance(row.get("runtime_revision"), bool)
        or not isinstance(row.get("runtime_revision"), int)
        or not revision <= row.get("runtime_revision") <= authenticated_revision
        for row in additions["cycle"]
    ):
        _committed_terminal_drift_invalid()
    if (
        len(additions["incident"]) != len(expected_incidents)
        or any(
            str(row.get("transition_id")) not in expected_incidents
            or not _matches(row, expected_incidents[str(row.get("transition_id"))])
            for row in additions["incident"]
        )
    ):
        _committed_terminal_drift_invalid()

    old_admin, now_admin = frozen.get("administrative_snapshot"), current.get("administrative_snapshot")
    if not isinstance(old_admin, Mapping) or not isinstance(now_admin, Mapping):
        _committed_terminal_drift_invalid()
    dynamic_admin = {"event_count", "latest_event_id"}
    if (
        {key: value for key, value in old_admin.items() if key not in dynamic_admin}
        != {key: value for key, value in now_admin.items() if key not in dynamic_admin}
    ):
        _committed_terminal_drift_invalid()
    if additions["event"]:
        if (
            isinstance(old_admin.get("event_count"), bool)
            or not isinstance(old_admin.get("event_count"), int)
            or now_admin.get("event_count") != old_admin.get("event_count") + len(additions["event"])
            or now_admin.get("latest_event_id") != additions["event"][-1].get("event_id")
        ):
            _committed_terminal_drift_invalid()
    elif now_admin != old_admin:
        _committed_terminal_drift_invalid()

    latest = revision_items.get(str(now_runtime.get("latest_event_id")))
    if (
        latest is None or latest[0] != now_runtime.get("committed_at")
        or latest[1] != now_runtime.get("overwatcher_status")
    ):
        _committed_terminal_drift_invalid()
    allowed_kinds = {
        "DELIVERY_UNCONFIRMED", "DELIVERY_RETRYING", "ACTIVITY_UNPROVEN", "RECORD_CONFLICT",
        "RECOVERY_ESCALATED", "PROJECTION_REFRESH_REQUESTED", "WORKER_COMPLETION_HANDOFF_MISSING",
    }
    if any(
        row.get("overwatcher_role_instance_id") != watcher_id
        or row.get("kind") not in allowed_kinds
        or row.get("plan_revision") != request.get("plan_revision")
        for row in additions["observation"]
    ):
        _committed_terminal_drift_invalid()
    return authenticated_revision


def execute_committed_checker_terminal(
    request: Mapping[str, Any],
    *,
    request_sha256: str,
    authenticate_checker: CheckerAuthenticate = _default_checker_authenticate,
    record_checker_d1: RecordCheckerD1 = _default_record_checker_d1,
    load_current_projection: LoadCurrentProjection = _default_load_current_projection,
) -> dict[str, Any]:
    """Authenticate the original Checker and record one already-complete native D1."""

    if not _exact_digest(request_sha256):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID", "request SHA-256 is invalid"
        )
    validated = _validate_committed_terminal_request(request)
    checker: Endpoint = validated["checker"]
    if (
        os.environ.get("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID") != checker.role_instance_id
        or os.environ.get("SLK_OCRV_RECOVERY_INVOCATION_ID")
        != request["recovery_invocation_id"]
        or os.environ.get("SLK_OCRV_RECOVERY_ENDPOINT_VERSION")
        != str(checker.endpoint_version)
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_NATIVE_IDENTITY_UNPROVEN",
            "terminal consumption is not running inside the exact OCRV Checker host",
        )
    authentication = authenticate_checker(
        str(request["run_id"]),
        checker.role_instance_id,
        Path(str(request["checker_credential_path"])),
        list(request["state_command"]),
    )
    authenticated_revision = authentication.get("runtime_revision")
    if (
        authentication.get("status") != "authenticated"
        or authentication.get("role") != "checker"
        or authentication.get("role_instance_id") != checker.role_instance_id
        or isinstance(authenticated_revision, bool)
        or not isinstance(authenticated_revision, int)
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_AUTHENTICATION_FAILED",
            "sealed credential does not prove the current Checker",
        )
    activation = dict(validated["activation"])
    replay_d1 = None
    if authenticated_revision != request["runtime_revision"]:
        current_projection = load_current_projection(
            str(request["run_id"]), list(request["state_command"])
        )
        if 'independent_fail' in request:
            from .independent_checker_fail import recorded, result as independent_result
            if recorded(validated['continuation'], current_projection):
                replay_d1 = independent_result(validated['continuation'])
        if replay_d1 is None:
            activation["runtime_revision"] = _rebind_overwatcher_only_committed_boundary(
                request, validated["frozen_projection"], current_projection, authenticated_revision)
    timeout_seconds = checker.address.get("timeout_seconds")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or timeout_seconds <= 0
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_INVALID", "Checker timeout is invalid"
        )
    d1 = replay_d1 if replay_d1 is not None else record_checker_d1(
        activation,
        validated["continuation"],
        Path(str(request["checker_credential_path"])),
        float(timeout_seconds),
    )
    verdict = d1.get("d1_verdict")
    if (
        d1.get("status") != "CHECKER_D1_RECORDED"
        or verdict not in {"PASS", "FAIL", "INCOMPLETE"}
        or d1.get("d1_event_type") != {
            "PASS": "D1_PASSED", "FAIL": "D1_FAILED", "INCOMPLETE": "D1_INCOMPLETE",
        }[str(verdict)]
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_RECORD_FAILED", "existing OCRV D1 was not recorded"
        )
    return {
        "schema_version": COMMITTED_TERMINAL_RESULT_SCHEMA,
        "method_version": request["method_version"],
        "status": "CHECKER_D1_RECORDED",
        "run_id": request["run_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "candidate_message_id": request["candidate_message_id"],
        "checker_role_instance_id": checker.role_instance_id,
        "checker_endpoint_version": checker.endpoint_version,
        "checker_authenticated": True,
        "authorized_existing_terminal": True,
        "recovery_invocation_id": request["recovery_invocation_id"],
        "request_sha256": request_sha256,
        "runtime_revision": authenticated_revision,
        "token_sequence": request["token_sequence"],
        "native_attempt_path": validated["activation"]["native_attempt_path"],
        "d1_verdict": d1["d1_verdict"],
        "d1_event_type": d1["d1_event_type"],
        "native_result_path": d1["native_result_path"],
    }


def consume_committed_checker_terminal(
    request_path: Path,
    *,
    request_sha256: str,
) -> Mapping[str, Any]:
    """Launch the sealed Checker host only after the committed terminal chain is complete."""

    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_REQUEST_MISMATCH",
            "committed-terminal request hash mismatch",
        )
    request = _read_object(request_path, "committed-terminal request")
    validated = _validate_committed_terminal_request(request)
    checker: Endpoint = validated["checker"]
    value = _run_sealed_checker_terminal(
        request_path,
        request,
        checker,
        request_sha256=request_sha256,
        mode="--slk-committed-terminal",
        result_schema=COMMITTED_TERMINAL_RESULT_SCHEMA,
        error_code="CHECKER_COMMITTED_TERMINAL_COMMAND_FAILED",
    )
    if (
        set(value) != COMMITTED_TERMINAL_RESULT_FIELDS
        or value.get("method_version") != request["method_version"]
        or value.get("d1_verdict") not in {"PASS", "FAIL", "INCOMPLETE"}
    ):
        raise CompletionError(
            "CHECKER_COMMITTED_TERMINAL_COMMAND_FAILED",
            "original Checker terminal consumer returned an invalid result",
        )
    return value


def _validate_incomplete_resume(request: Mapping[str, Any], *, consumed: bool = False) -> dict[str, Any]:
    required = {
        "schema_version", "method_version", "recovery_invocation_id", "run_id", "go_id", "cell_id",
        "attempt", "plan_revision", "runtime_revision", "token_sequence", "worker_role_instance_id",
        "checker_role_instance_id", "checker_endpoint_version", "checker_endpoint",
        "runtime_projection_path", "runtime_projection_sha256", "candidate_repository",
        "candidate_commit", "candidate_parent", "candidate_message_id", "payload_sha256",
        "candidate_submitted_event_id", "transport_started_event_id", "commit_request_path",
        "commit_request_sha256", "native_attempt_path", "checker_credential_path", "state_command",
        "transport_command", "immutable_sha256", "result_path", "background_path", "ocrv_session",
        "recovery_root",
    }
    partial = request.get('partial_review')
    if partial is not None:
        required.add('partial_review')
        from .partial_review import validate_partial_source
        try:
            validate_partial_source(request, consumed=consumed)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CompletionError('CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID', str(exc)) from exc
    try:
        checker = Endpoint.from_dict(request["checker_endpoint"])
        session = request["ocrv_session"]
        attempt = Path(str(request["native_attempt_path"])).resolve()
        recovery = Path(str(request["recovery_root"])).resolve()
        started_path = attempt / "started.json"
    except (KeyError, TypeError, ValueError) as exc:
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_REQUEST_INVALID", "resume request is invalid") from exc
    if (
        set(request) != required or request.get("schema_version") != INCOMPLETE_RESUME_SCHEMA
        or request.get("method_version") not in SUPPORTED_METHOD_VERSIONS or not isinstance(session, Mapping)
        or recovery != attempt / "resume-incomplete-checker" / str(request["recovery_invocation_id"])
        or Path(str(request["result_path"])).resolve() != recovery / "result.json"
        or (partial is None and any((attempt / name).exists() for name in ("completed.json", "failed.json", "ocrv-result.json")))
        or ((recovery / "resume-consumed.json").exists() != consumed)
        or session.get("diff_commit") != request.get("candidate_commit")
        or session.get("model") != "qwen3.8-max" or session.get("review_mode") != "commit"
        or (partial is None and (session.get("aborted") is not True or session.get("selected_files") != 0
        or session.get("completed_files") != 0))
    ):
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_REQUEST_INVALID", "resume identity is invalid or already consumed")
    try:
        started = validate_native_start(
            started_path, adapter=checker.adapter, run_id=str(request["run_id"]),
            cell_id=str(request["cell_id"]), message_id=str(request["candidate_message_id"]),
            request_sha256=str(request["payload_sha256"]),
        )
    except NativeActivityError as exc:
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID", "original OCRV start is invalid") from exc
    if inspect_native_activity(
        started_path, terminal_paths=() if partial is not None else (attempt / "completed.json", attempt / "failed.json"),
        **({'native_probe': lambda _start: {'status':'UNKNOWN'}} if partial is not None else {}),
    ).get("status") != "DEAD_WITHOUT_TERMINAL":
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID", "original OCRV process is not dead")
    names = {"endpoint.json", "envelope.json", "started.json", "ocrv-request.json", "ocrv-preflight.json",
             "d1-background.md", "native-activity.json", "session-record"}
    paths = {name: attempt / name for name in names}
    paths["d1-background.md"] = Path(str(request["background_path"])).resolve()
    paths["session-record"] = Path(str(session.get("session_record_path", ""))).resolve()
    if partial is not None:
        paths['ocrv-request.json'] = attempt / 'review-segments/segment-001/request.json'
        paths['ocrv-preflight.json'] = attempt / 'review-segments/segment-001/preflight.json'
    immutable = request["immutable_sha256"]
    if not isinstance(immutable, Mapping) or set(immutable) != names or any(
        not path.is_file() or _sha256(path) != immutable.get(name) for name, path in paths.items()
    ) or session.get("session_record_sha256") != immutable.get("session-record"):
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID", "resume input is missing")
    preflight = _read_object(paths["ocrv-preflight.json"], "OCRV preflight")
    if (preflight.get("status") != "READY" or preflight.get("request_sha256") != immutable["ocrv-request.json"]
        or not _matches(preflight.get("background"), {"sha256": immutable["d1-background.md"]})):
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_EVIDENCE_INVALID", "OCRV preflight is not exact")
    source = {key: value for key, value in request.items() if key not in {"background_path", "ocrv_session", "recovery_root", 'partial_review'}}
    source.update({"schema_version": COMMITTED_TERMINAL_SCHEMA, "raw_review_path": "unused", "immutable_sha256": {name: immutable[name] for name in ("endpoint.json", "envelope.json", "started.json", "ocrv-request.json")}})
    return {**_validate_committed_terminal_request(source, source_only=True, partial_review=partial), "paths": paths, "session": dict(session), "recovery_root": recovery}
def resume_incomplete_checker(request_path: Path, *, request_sha256: str, prepare_only: bool = False) -> Mapping[str, Any]:
    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError("CHECKER_INCOMPLETE_RESUME_REQUEST_MISMATCH", "resume request hash mismatch")
    request = _read_object(request_path, "incomplete Checker resume request")
    validated = _validate_incomplete_resume(request)
    if prepare_only:
        return {'schema_version':'slk.ocrv-incomplete-checker-resume-preflight/v1',
                'status':'READY_FOR_SEALED_CHECKER_PREFLIGHT', 'request_sha256':request_sha256,
                **{key:request[key] for key in ('run_id','go_id','cell_id','attempt','candidate_message_id',
                    'runtime_revision','token_sequence','checker_role_instance_id','checker_endpoint_version')}}
    return _run_sealed_checker_terminal(
        request_path, request, validated["checker"], request_sha256=request_sha256,
        mode="--slk-resume-incomplete-checker", result_schema=COMMITTED_TERMINAL_RESULT_SCHEMA,
        error_code="CHECKER_INCOMPLETE_RESUME_COMMAND_FAILED",
    )


def resume_terminal_budget_checker(
    request_path: Path, *, request_sha256: str, prepare_only: bool = False
) -> Mapping[str, Any]:
    """Resume one terminal budget-only OCRV D1 inside the original sealed Checker."""

    from .terminal_budget import RESULT_SCHEMA, validate

    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError(
            "CHECKER_TERMINAL_BUDGET_REQUEST_MISMATCH", "terminal-budget request hash mismatch"
        )
    request = _read_object(request_path, "terminal-budget Checker resume request")
    validated = validate(request)
    if prepare_only:
        return {
            "schema_version": "slk.ocrv-terminal-budget-resume-preflight/v1",
            "status": "READY_FOR_SEALED_CHECKER_PREFLIGHT",
            "request_sha256": request_sha256,
            **{
                key: request[key]
                for key in (
                    "run_id", "go_id", "cell_id", "attempt", "candidate_message_id",
                    "runtime_revision", "token_sequence", "checker_role_instance_id",
                    "checker_endpoint_version", "d1_incomplete_event_id",
                )
            },
            "capacity_revision_sha256": canonical_json_sha256(request["capacity_revision"]),
            "ocrv_transition_sha256": canonical_json_sha256(request["ocrv_transition"]),
            "runtime_config_binding_sha256": canonical_json_sha256(
                request["runtime_config_binding"]
            ),
        }
    value = _run_sealed_checker_terminal(
        request_path,
        request,
        validated["checker"],
        request_sha256=request_sha256,
        mode="--slk-resume-terminal-budget",
        result_schema=RESULT_SCHEMA,
        error_code="CHECKER_TERMINAL_BUDGET_COMMAND_FAILED",
        result_statuses=("CHECKER_D1_RECORDED", "CHECKER_D1_STILL_INCOMPLETE"),
    )
    if (
        set(value) != TERMINAL_BUDGET_RESUME_RESULT_FIELDS
        or value.get("status") not in {"CHECKER_D1_RECORDED", "CHECKER_D1_STILL_INCOMPLETE"}
        or value.get("d1_verdict") not in {"PASS", "FAIL", "INCOMPLETE"}
        or value.get("d1_event_type")
        != {"PASS": "D1_PASSED", "FAIL": "D1_FAILED", "INCOMPLETE": "D1_INCOMPLETE"}.get(
            value.get("d1_verdict")
        )
    ):
        raise CompletionError(
            "CHECKER_TERMINAL_BUDGET_COMMAND_FAILED", "sealed Checker returned an invalid continuation result"
        )
    return value


def resume_terminal_budget_fresh_review(
    request_path: Path, *, request_sha256: str, prepare_only: bool = False
) -> Mapping[str, Any]:
    """Run one Owner-authorized fresh full review after a native rule-identity rejection."""

    from .terminal_budget_fresh import (
        RESULT_SCHEMA,
        validate_fresh_review_request,
    )

    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_REQUEST_MISMATCH",
            "fresh-review compatibility request hash mismatch",
        )
    request = _read_object(request_path, "terminal-budget fresh-review request")
    validated = validate_fresh_review_request(request)
    source = validated["source_request"]
    if prepare_only:
        return {
            "schema_version": "slk.ocrv-terminal-budget-fresh-review-preflight/v1",
            "status": "READY_FOR_SEALED_CHECKER_FRESH_REVIEW",
            "request_sha256": request_sha256,
            **{
                key: source[key]
                for key in (
                    "run_id", "cell_id", "attempt", "candidate_commit",
                    "candidate_message_id", "checker_role_instance_id",
                    "checker_endpoint_version",
                )
            },
            "recovery_invocation_id": request["recovery_invocation_id"],
            "source_rejection_sha256": request["source_rejection_sha256"],
            "capacity_revision_sha256": canonical_json_sha256(source["capacity_revision"]),
        }
    value = _run_sealed_checker_terminal(
        request_path,
        request,
        validated["source_validated"]["checker"],
        request_sha256=request_sha256,
        mode="--slk-fresh-terminal-budget-review",
        result_schema=RESULT_SCHEMA,
        error_code="CHECKER_TERMINAL_BUDGET_FRESH_COMMAND_FAILED",
        result_statuses=("CHECKER_D1_RECORDED", "CHECKER_D1_STILL_INCOMPLETE"),
        identity_source=source,
    )
    if (
        set(value) != TERMINAL_BUDGET_FRESH_RESULT_FIELDS
        or value.get("status") not in {"CHECKER_D1_RECORDED", "CHECKER_D1_STILL_INCOMPLETE"}
        or value.get("d1_verdict") not in {"PASS", "FAIL", "INCOMPLETE"}
        or value.get("d1_event_type")
        != {"PASS": "D1_PASSED", "FAIL": "D1_FAILED", "INCOMPLETE": "D1_INCOMPLETE"}.get(
            value.get("d1_verdict")
        )
    ):
        raise CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_COMMAND_FAILED",
            "sealed Checker returned an invalid fresh-review result",
        )
    return value


def resume_terminal_budget_fresh_partial(
    request_path: Path, *, request_sha256: str, prepare_only: bool = False
) -> Mapping[str, Any]:
    """Resume only the remaining item(s) of one consumed fresh budget-partial review."""

    from .terminal_budget_fresh_partial import RESULT_SCHEMA, validate_fresh_partial_request

    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_REQUEST_MISMATCH",
            "fresh-partial continuation request hash mismatch",
        )
    request = _read_object(request_path, "terminal-budget fresh-partial request")
    validated = validate_fresh_partial_request(request)
    source = validated["source_request"]
    current = _default_load_current_projection(str(source["run_id"]), list(source["state_command"]))
    runtime = current.get("runtime_snapshot")
    current_revision = runtime.get("runtime_revision") if isinstance(runtime, Mapping) else None
    if isinstance(current_revision, bool) or not isinstance(current_revision, int):
        _committed_terminal_drift_invalid()
    if current_revision != source["runtime_revision"]:
        current_revision = _rebind_overwatcher_only_committed_boundary(
            source, validated["source_validated"]["frozen_projection"], current, current_revision
        )
    if prepare_only:
        return {
            "schema_version": "slk.ocrv-terminal-budget-fresh-partial-preflight/v1",
            "status": "READY_FOR_SEALED_CHECKER_FRESH_PARTIAL_RESUME",
            "request_sha256": request_sha256,
            **{
                key: source[key]
                for key in (
                    "run_id", "cell_id", "attempt", "candidate_commit",
                    "candidate_message_id", "checker_role_instance_id", "checker_endpoint_version",
                    "runtime_revision", "token_sequence",
                )
            },
            "current_runtime_revision": current_revision,
            "recovery_invocation_id": request["recovery_invocation_id"],
            "parent_session_id": request["parent_session_id"],
            "capacity_revision_sha256": canonical_json_sha256(request["capacity_revision"]),
            "completed_paths": sorted(validated["parent_completed_paths"]),
            "remaining_paths": sorted(validated["remaining_paths"]),
        }
    value = _run_sealed_checker_terminal(
        request_path,
        request,
        validated["source_validated"]["checker"],
        request_sha256=request_sha256,
        mode="--slk-resume-terminal-budget-fresh-partial",
        result_schema=RESULT_SCHEMA,
        error_code="CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_COMMAND_FAILED",
        result_statuses=("CHECKER_D1_RECORDED", "CHECKER_D1_STILL_INCOMPLETE"),
        identity_source=source,
    )
    if (
        set(value) != TERMINAL_BUDGET_RESUME_RESULT_FIELDS
        or value.get("status") not in {"CHECKER_D1_RECORDED", "CHECKER_D1_STILL_INCOMPLETE"}
        or value.get("d1_verdict") not in {"PASS", "FAIL", "INCOMPLETE"}
        or value.get("d1_event_type")
        != {"PASS": "D1_PASSED", "FAIL": "D1_FAILED", "INCOMPLETE": "D1_INCOMPLETE"}.get(
            value.get("d1_verdict")
        )
    ):
        raise CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_COMMAND_FAILED",
            "sealed Checker returned an invalid fresh-partial continuation result",
        )
    return value


def resume_terminal_budget_fresh_partial_suffix(
    request_path: Path, *, request_sha256: str, prepare_only: bool = False,
) -> Mapping[str, Any]:
    """Continue only the missing suffix after the exact fresh-partial D1 was recorded."""

    from .terminal_budget_fresh_partial import (
        RESULT_SCHEMA,
        validate_fresh_partial_suffix_source,
    )

    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_SUFFIX_REQUEST_MISMATCH",
            "fresh-partial suffix request hash mismatch",
        )
    request = _read_object(request_path, "terminal-budget fresh-partial suffix request")
    basis = validate_fresh_partial_suffix_source(request_path, request)
    source = basis["source"]
    if prepare_only:
        return {
            "schema_version": "slk.ocrv-terminal-budget-fresh-partial-suffix-preflight/v1",
            "status": "READY_FOR_SEALED_CHECKER_FRESH_PARTIAL_SUFFIX",
            "request_sha256": request_sha256,
            **{
                key: source[key]
                for key in (
                    "run_id", "cell_id", "attempt", "candidate_commit",
                    "candidate_message_id", "checker_role_instance_id",
                    "checker_endpoint_version", "token_sequence",
                )
            },
            "current_runtime_revision": basis["current_runtime_revision"],
            "recovery_invocation_id": request["recovery_invocation_id"],
            "d1_verdict": basis["native_result"]["verdict"],
            "corrected_d1_event_id": basis["corrected_d1_event_id"],
        }
    value = _run_sealed_checker_terminal(
        request_path,
        request,
        basis["committed_validated"]["checker"],
        request_sha256=request_sha256,
        mode="--slk-resume-terminal-budget-fresh-partial-suffix",
        result_schema=RESULT_SCHEMA,
        error_code="CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_SUFFIX_COMMAND_FAILED",
        result_statuses=("CHECKER_D1_RECORDED",),
        identity_source=source,
    )
    if (
        set(value) != TERMINAL_BUDGET_RESUME_RESULT_FIELDS
        or value.get("d1_verdict") not in {"PASS", "FAIL"}
        or value.get("d1_event_type")
        != {"PASS": "D1_PASSED", "FAIL": "D1_FAILED"}.get(value.get("d1_verdict"))
        or value.get("corrected_d1_event_id") != basis["corrected_d1_event_id"]
        or value.get("suffix_status") == "NOT_APPLICABLE"
    ):
        raise CompletionError(
            "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_SUFFIX_COMMAND_FAILED",
            "sealed Checker returned an invalid post-D1 suffix result",
        )
    return value


def continue_consumed_partial_checker(
    request_path: Path, *, request_sha256: str, prepare_only: bool = False
) -> Mapping[str, Any]:
    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError("CHECKER_PARTIAL_CONTINUE_REQUEST_MISMATCH", "resume request hash mismatch")
    request = _read_object(request_path, "consumed partial Checker request")
    validated = _validate_incomplete_resume(request, consumed=True)
    try:
        from .partial_review import validate_consumed_partial_attempt
        consumed = validate_consumed_partial_attempt(request, request_sha256)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CompletionError("CHECKER_PARTIAL_CONTINUE_EVIDENCE_INVALID", str(exc)) from exc
    current_projection = _default_load_current_projection(
        str(request["run_id"]), list(request["state_command"])
    )
    current_runtime = current_projection.get("runtime_snapshot")
    current_revision = current_runtime.get("runtime_revision") if isinstance(current_runtime, Mapping) else None
    if isinstance(current_revision, bool) or not isinstance(current_revision, int):
        _committed_terminal_drift_invalid()
    if current_revision != request["runtime_revision"]:
        current_revision = _rebind_overwatcher_only_committed_boundary(
            request, validated["frozen_projection"], current_projection, current_revision
        )
    if prepare_only:
        return {'schema_version': 'slk.ocrv-consumed-partial-preflight/v1',
                'status': 'READY_TO_CONSUME_COMPLETED_SEGMENT_1', 'request_sha256': request_sha256,
                'completed_segment_count': 1,
                **{key: request[key] for key in ('run_id', 'go_id', 'cell_id', 'attempt',
                    'candidate_message_id', 'runtime_revision', 'token_sequence',
                    'checker_role_instance_id', 'checker_endpoint_version')},
                'current_runtime_revision': current_revision,
                'native_child_session_id': consumed['raw']['session_id']}
    return _run_sealed_checker_terminal(
        request_path, request, validated['checker'], request_sha256=request_sha256,
        mode='--slk-continue-consumed-partial', result_schema=COMMITTED_TERMINAL_RESULT_SCHEMA,
        error_code='CHECKER_PARTIAL_CONTINUE_COMMAND_FAILED')


def resume_consumed_partial_checker(
    request_path: Path, *, request_sha256: str, prepare_only: bool = False
) -> Mapping[str, Any]:
    """Resume only the failed item of the already-started second frozen segment."""
    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError('CHECKER_PARTIAL_SEGMENT_RESUME_REQUEST_MISMATCH', 'resume request hash mismatch')
    request = _read_object(request_path, 'later partial Checker request')
    validated = _validate_incomplete_resume(request, consumed=True)
    try:
        from .partial_review import validate_consumed_partial_resume_attempt
        partial = validate_consumed_partial_resume_attempt(request, request_sha256)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CompletionError('CHECKER_PARTIAL_SEGMENT_RESUME_EVIDENCE_INVALID', str(exc)) from exc
    current_projection = _default_load_current_projection(str(request['run_id']), list(request['state_command']))
    current_runtime = current_projection.get('runtime_snapshot')
    current_revision = current_runtime.get('runtime_revision') if isinstance(current_runtime, Mapping) else None
    if isinstance(current_revision, bool) or not isinstance(current_revision, int):
        _committed_terminal_drift_invalid()
    if current_revision != request['runtime_revision']:
        current_revision = _rebind_overwatcher_only_committed_boundary(
            request, validated['frozen_projection'], current_projection, current_revision)
    coverage = partial['partial_manifest']['coverage']
    if prepare_only:
        return {'schema_version':'slk.ocrv-partial-segment-resume-preflight/v1',
                'status':'READY_TO_RESUME_PARTIAL_SEGMENT_2', 'request_sha256':request_sha256,
                'partial_session_id':partial['partial_raw']['session_id'],
                'failed_paths':[item['path'] for item in coverage['failed']],
                'reused_paths':[item['path'] for item in coverage['completed']],
                **{key:request[key] for key in ('run_id','go_id','cell_id','attempt','candidate_message_id',
                    'runtime_revision','token_sequence','checker_role_instance_id','checker_endpoint_version')},
                'current_runtime_revision':current_revision}
    return _run_sealed_checker_terminal(
        request_path, request, validated['checker'], request_sha256=request_sha256,
        mode='--slk-resume-consumed-partial', result_schema=COMMITTED_TERMINAL_RESULT_SCHEMA,
        error_code='CHECKER_PARTIAL_SEGMENT_RESUME_COMMAND_FAILED')


def refine_consumed_partial_checker(
    request_path: Path, *, request_sha256: str, prepare_only: bool = False,
) -> Mapping[str, Any]:
    """Refine a zero-complete multi-path budget boundary into single-path reviews."""
    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError('CHECKER_PARTIAL_REFINEMENT_REQUEST_MISMATCH',
                              'partial refinement request hash mismatch')
    request = _read_object(request_path, 'zero-complete partial Checker request')
    validated = _validate_incomplete_resume(request, consumed=True)
    try:
        from .partial_review import validate_zero_complete_refinement_attempt
        attempt = Path(str(request['recovery_root'])) / 'native-attempt'
        final_partial = (attempt / 'review-segments/segment-003/result.json').is_file()
        partial = validate_zero_complete_refinement_attempt(
            request, request_sha256, final_partial=final_partial)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CompletionError('CHECKER_PARTIAL_REFINEMENT_EVIDENCE_INVALID', str(exc)) from exc
    current_projection = _default_load_current_projection(
        str(request['run_id']), list(request['state_command']))
    current_runtime = current_projection.get('runtime_snapshot')
    current_revision = current_runtime.get('runtime_revision') if isinstance(current_runtime, Mapping) else None
    if isinstance(current_revision, bool) or not isinstance(current_revision, int):
        _committed_terminal_drift_invalid()
    if current_revision != request['runtime_revision']:
        current_revision = _rebind_overwatcher_only_committed_boundary(
            request, validated['frozen_projection'], current_projection, current_revision)
    failed_paths = [item['path'] for item in partial['second']['coverage']['failed']]
    if prepare_only:
        if final_partial:
            return {'schema_version':'slk.ocrv-partial-blocking-failure-preflight/v1',
                    'status':'READY_TO_FAIL_FROM_REFINED_FINAL_PARTIAL',
                    'request_sha256':request_sha256, 'segment_ordinal':3,
                    'blocking_paths':partial['blocking_paths'],
                    **{key:request[key] for key in ('run_id','go_id','cell_id','attempt',
                        'candidate_message_id','runtime_revision','token_sequence',
                        'checker_role_instance_id','checker_endpoint_version')},
                    'current_runtime_revision':current_revision}
        return {'schema_version':'slk.ocrv-zero-complete-refinement-preflight/v1',
                'status':'READY_TO_REFINE_ZERO_COMPLETE_SEGMENT_2',
                'request_sha256':request_sha256, 'segment_ordinal':2,
                'failed_paths':failed_paths, 'refined_review_count':len(failed_paths),
                **{key:request[key] for key in ('run_id','go_id','cell_id','attempt',
                    'candidate_message_id','runtime_revision','token_sequence',
                    'checker_role_instance_id','checker_endpoint_version')},
                'current_runtime_revision':current_revision}
    return _run_sealed_checker_terminal(
        request_path, request, validated['checker'], request_sha256=request_sha256,
        mode='--slk-refine-consumed-partial', result_schema=COMMITTED_TERMINAL_RESULT_SCHEMA,
        error_code='CHECKER_PARTIAL_REFINEMENT_COMMAND_FAILED')


def consume_existing_partial_checker(
    request_path: Path, *, request_sha256: str, evidence_root: Path,
    prepare_only: bool = False,
) -> Mapping[str, Any]:
    """Consume a fully terminal legacy partial chain without another model call."""
    data = request_path.read_bytes()
    if hashlib.sha256(data).hexdigest() != request_sha256:
        raise CompletionError('CHECKER_EXISTING_PARTIAL_REQUEST_MISMATCH',
                              'existing partial request hash mismatch')
    request = _read_object(request_path, 'existing partial Checker request')
    validated = _validate_incomplete_resume(request, consumed=True)
    try:
        from .partial_review import validate_existing_partial_completion
        existing = validate_existing_partial_completion(
            request, request_sha256, Path(evidence_root))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CompletionError('CHECKER_EXISTING_PARTIAL_EVIDENCE_INVALID', str(exc)) from exc
    current_projection = _default_load_current_projection(
        str(request['run_id']), list(request['state_command']))
    current_runtime = current_projection.get('runtime_snapshot')
    current_revision = current_runtime.get('runtime_revision') if isinstance(current_runtime, Mapping) else None
    if isinstance(current_revision, bool) or not isinstance(current_revision, int):
        _committed_terminal_drift_invalid()
    if current_revision != request['runtime_revision']:
        current_revision = _rebind_overwatcher_only_committed_boundary(
            request, validated['frozen_projection'], current_projection, current_revision)
    if prepare_only:
        return {'schema_version': 'slk.ocrv-existing-partial-consumption-preflight/v1',
                'status': 'READY_TO_CONSUME_EXISTING_PARTIAL_EVIDENCE',
                'request_sha256': request_sha256, 'verdict': existing['verdict'],
                'completed_segment_count': len(existing['segment_results']),
                **{key: request[key] for key in ('run_id', 'go_id', 'cell_id', 'attempt',
                    'candidate_message_id', 'runtime_revision', 'token_sequence',
                    'checker_role_instance_id', 'checker_endpoint_version')},
                'current_runtime_revision': current_revision,
                'evidence_root': str(Path(evidence_root).resolve())}
    return _run_sealed_checker_terminal(
        request_path, request, validated['checker'], request_sha256=request_sha256,
        mode='--slk-consume-existing-partial', result_schema=COMMITTED_TERMINAL_RESULT_SCHEMA,
        error_code='CHECKER_EXISTING_PARTIAL_CONSUMPTION_FAILED',
        extra_args=('--evidence-root', str(Path(evidence_root).resolve())))


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


def execute_worker_continuation(request: Mapping[str, Any]) -> dict[str, Any]:
    """Run the continuation inside the resumed DSH process using its own DPAPI credential."""

    if os.environ.get("SLK_DSH_INSTANCE_ID") != request.get("worker_instance_id") or os.environ.get(
        "SLK_DSH_SESSION_ID"
    ) != request.get("worker_session_id"):
        raise CompletionError(
            "WORKER_CONTINUATION_SESSION_MISMATCH",
            "continuation is not running inside the exact resumed DSH Worker Session",
        )
    return _execute_worker_suffix(request)


def execute_worker_host_continuation(request: Mapping[str, Any]) -> dict[str, Any]:
    """Owning adapter executes the existing suffix outside the model sandbox.

    Authority remains the sealed Worker credential. Identity comes from the
    immutable native start, never environment variables invented by the caller.
    """
    _validate_continuation_request(request)
    attempt = Path(str(request["source_attempt_root"]))
    endpoint = Endpoint.from_dict(_read_object(attempt / "endpoint.json", "Worker endpoint"))
    envelope = Envelope.from_dict(_read_object(attempt / "envelope.json", "Worker envelope"))
    session = _native_v2_worker_session(attempt / "started.json", endpoint, envelope)
    if (session != request["worker_session_id"] or endpoint.address.get("instance_id") != request["worker_instance_id"]
        or endpoint.role_instance_id != request["worker_role_instance_id"]
        or _sha256(attempt / "endpoint.json") != request["source_endpoint_sha256"]
        or _sha256(attempt / "envelope.json") != request["source_envelope_sha256"]):
        raise CompletionError("WORKER_CONTINUATION_SESSION_MISMATCH", "owning host source identity changed")
    root = _continuation_root(request)
    root.mkdir(parents=True, exist_ok=True)
    result_path = root / "host-handoff.json"
    digest = canonical_json_sha256(request)
    if result_path.exists():
        saved = _read_object(result_path, "host handoff receipt")
        if set(saved) != {"request_sha256", "activation"} or saved["request_sha256"] != digest:
            raise CompletionError("WORKER_CONTINUATION_CONFLICT", "host handoff identity changed")
        return saved["activation"]
    stage_path = Path(str(request["continuation_result_path"]))
    if stage_path.exists():
        stage = _read_object(stage_path, "staged host handoff")
    else:
        stage = _execute_worker_suffix(request)
        _write_or_reuse_stable_request(stage_path, stage)
    activation = dict(_activate_staged_checker(stage, request))
    _write_or_reuse_stable_request(result_path, {"request_sha256": digest, "activation": activation})
    return activation


def _execute_worker_suffix(request: Mapping[str, Any]) -> dict[str, Any]:
    """Shared deterministic suffix; caller establishes the native ownership boundary."""
    state_command = list(request["state_command"])
    credential = unprotect_dpapi_hex(str(request["credential_path"]))
    request_root = _continuation_root(request)
    request_root.mkdir(parents=True, exist_ok=True)

    def state_request(command_name: str, value: Mapping[str, Any]) -> dict[str, Any]:
        path = request_root / f"{command_name}-{value.get('event_id', value.get('transport_receipt_id', 'request'))}.json"
        _write_or_reuse_stable_request(path, value)
        return _run_json_command(state_command, [command_name, "--request", str(path)], credential=credential)

    def authenticate(run_id: str, role_instance_id: str) -> int:
        value = _run_json_command(
            state_command,
            ["authenticate-role", "--run-id", run_id, "--role-instance-id", role_instance_id],
            credential=credential,
        )
        if value.get("role_instance_id") != role_instance_id or value.get("role") != "worker":
            raise CompletionError("WORKER_CREDENTIAL_MISMATCH", "credential is not the active Worker")
        revision = value.get("runtime_revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise CompletionError("WORKER_RUNTIME_REVISION_INVALID", "fresh runtime revision is unavailable")
        return revision

    def write_event(value: dict[str, Any]) -> str:
        return str(state_request("write", value).get("status"))

    checker_attempt_root = request_root / "checker-attempts"
    temporal = request.get("temporal")
    if isinstance(temporal, Mapping):
        checker_attempt_root = Path(str(temporal["attempt_root"])).resolve()
    elif request.get("recovery_mode") == "INCOMPLETE_HANDOFF":
        # The preserved candidate was addressed through the original transport
        # root. Query/reuse that exact attempt instead of starting it in a new root.
        checker_attempt_root = Path(str(request["source_attempt_root"])).parents[1]

    def start_checker(endpoint_raw: dict[str, Any], envelope_raw: dict[str, Any]) -> Mapping[str, Any]:
        endpoint_path = request_root / "checker-endpoint.json"
        envelope_path = request_root / "candidate-envelope.json"
        for path, value in ((endpoint_path, endpoint_raw), (envelope_path, envelope_raw)):
            encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            if path.exists() and path.read_bytes() != encoded:
                raise CompletionError("WORKER_CONTINUATION_CONFLICT", f"immutable delivery conflicts: {path.name}")
            if not path.exists():
                path.write_bytes(encoded)
        return {
            "status": "delivery_ready",
            "endpoint_path": str(endpoint_path),
            "envelope_path": str(envelope_path),
            "attempt_root": str(checker_attempt_root),
        }

    def commit_start(_value: dict[str, Any]) -> Mapping[str, Any]:
        raise CompletionError(
            "CHECKER_START_HOST_INVALID",
            "a DSH Worker process cannot host or commit the OCRV Checker start",
        )

    try:
        return run_worker_continuation(
            request,
            authenticate=authenticate,
            write_event=write_event,
            start_checker=start_checker,
            commit_start=commit_start,
            defer_checker_start=True,
        )
    finally:
        credential = ""
