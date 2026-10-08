"""Fail-closed PASS suffix for one Checker-owned D1 terminal."""

from __future__ import annotations

from . import SUPPORTED_METHOD_VERSIONS
from . import worker_completion as wc

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .adapters.base import AdapterError
from .adapters.codex_desktop import validate_late_desktop_start
from .contracts import ENVELOPE_SCHEMA, IDENTIFIER, Endpoint, Envelope, canonical_json_sha256
from .evidence import Attempt
from .native_activity import NativeActivityError, validate_native_start
from .worker_completion import CompletionError, _run_json_command, resolve_authoritative_token_boundary, unprotect_dpapi_hex


REQUEST_SCHEMA = "slk.checker-completion-request/v1"
_NAMESPACE = uuid.UUID("50f725a6-7aa8-45b1-999d-f0bf867810a0")
REQUEST_FIELDS = frozenset(
    {
        "schema_version", "method_version", "completion_invocation_id", "run_id",
        "go_id", "cell_id", "target_cell_id", "attempt", "plan_revision",
        "runtime_revision", "token_sequence", "checker_role_instance_id",
        "d1_event_id", "route", "runtime_projection_path", "target_endpoint_path",
        "checker_credential_path", "state_command", "transport_command",
        "handoff_attempt_root", "payload", "occurred_at",
    }
)
NEXT_PAYLOAD_FIELDS = frozenset(
    {"cell_id", "cell_ordinal", "required_cell_count", "task", "d1_criteria", "root_record_path"}
)
D2_PAYLOAD_FIELDS = frozenset(
    {
        "d1_event_id", "required_cell_ids", "accepted_cell_ids",
        "final_candidate_message_id", "d2_criteria", "evidence_refs",
    }
)


class CheckerCompletionError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


RunJsonCommand = Callable[..., Mapping[str, Any]]
UnprotectCredential = Callable[[Path | str], str]


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckerCompletionError("CHECKER_COMPLETION_EVIDENCE_INVALID", f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise CheckerCompletionError("CHECKER_COMPLETION_EVIDENCE_INVALID", f"{label} must be an object")
    return value


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise CheckerCompletionError("CHECKER_COMPLETION_EVIDENCE_INVALID", f"evidence is unreadable: {path}") from exc


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", f"{label} must be canonical text")
    return value


def _positive(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", f"{label} must be positive")
    return value


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item and item == item.strip() for item in value
    ):
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", f"{label} must be canonical strings")
    if len(value) != len(set(value)):
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", f"{label} must be unique")
    return list(value)


def _existing_path(value: Any, label: str, *, directory: bool = False) -> Path:
    path = Path(_text(value, label))
    if not path.is_absolute() or not (path.is_dir() if directory else path.is_file()):
        raise CheckerCompletionError(
            "CHECKER_COMPLETION_REQUEST_INVALID", f"{label} must be an existing absolute path"
        )
    return path.resolve()


def _write_stable(path: Path, value: Mapping[str, Any]) -> Path:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if path.is_file():
        if path.read_bytes() != encoded:
            raise CheckerCompletionError("CHECKER_COMPLETION_CONFLICT", f"immutable evidence conflicts: {path.name}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)
    return path


def _details(event: Mapping[str, Any]) -> Mapping[str, Any]:
    details = event.get("details")
    if isinstance(details, Mapping):
        return details
    serialized = event.get("details_json")
    if isinstance(serialized, str):
        try:
            decoded = json.loads(serialized)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, Mapping):
            return decoded
    return {}


def _stable_id(request: Mapping[str, Any], suffix: str) -> str:
    source = ":".join(
        str(request[field])
        for field in ("run_id", "cell_id", "attempt", "d1_event_id", "completion_invocation_id")
    )
    return str(uuid.uuid5(_NAMESPACE, f"{source}:{suffix}"))


def _ordered_cells(projection: Mapping[str, Any]) -> list[dict[str, Any]]:
    go_nodes = projection.get("go_nodes")
    if not isinstance(go_nodes, list) or not go_nodes:
        raise CheckerCompletionError("CHECKER_COMPLETION_PLAN_INVALID", "current plan has no required CELL set")
    ordered: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for go in sorted(go_nodes, key=lambda item: item.get("ordinal", 0) if isinstance(item, Mapping) else 0):
        if not isinstance(go, Mapping) or not isinstance(go.get("cell_nodes"), list):
            raise CheckerCompletionError("CHECKER_COMPLETION_PLAN_INVALID", "current plan CELL set is malformed")
        for cell in sorted(
            go["cell_nodes"],
            key=lambda item: item.get("ordinal", 0) if isinstance(item, Mapping) else 0,
        ):
            if not isinstance(cell, Mapping):
                raise CheckerCompletionError("CHECKER_COMPLETION_PLAN_INVALID", "current plan CELL is malformed")
            if cell.get("state") == "split":
                continue
            cell_id = cell.get("cell_id")
            ordinal = cell.get("ordinal")
            if (
                not isinstance(cell_id, str) or not cell_id or cell_id in seen_ids
                or isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 1
            ):
                raise CheckerCompletionError("CHECKER_COMPLETION_PLAN_INVALID", "current plan CELL identity is invalid")
            seen_ids.add(cell_id)
            ordered.append(dict(cell))
    return ordered


def _validate_payload(
    request: Mapping[str, Any], cells: list[dict[str, Any]], details: Mapping[str, Any]
) -> None:
    payload = request.get("payload")
    if not isinstance(payload, Mapping):
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", "payload must be an object")
    ids = [str(cell["cell_id"]) for cell in cells]
    route = request["route"]
    if route == "NEXT_CELL":
        if set(payload) != NEXT_PAYLOAD_FIELDS:
            raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", "next CELL payload is not closed")
        if (
            payload.get("cell_id") != request["target_cell_id"]
            or payload.get("cell_ordinal") != ids.index(str(request["target_cell_id"])) + 1
            or payload.get("required_cell_count") != len(cells)
        ):
            raise CheckerCompletionError("CHECKER_COMPLETION_PLAN_INVALID", "payload does not bind the next required CELL")
        _text(payload.get("task"), "payload.task")
        _strings(payload.get("d1_criteria"), "payload.d1_criteria")
        _existing_path(payload.get("root_record_path"), "payload.root_record_path")
        return
    if set(payload) != D2_PAYLOAD_FIELDS:
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", "D2_READY payload is not closed")
    required = _strings(payload.get("required_cell_ids"), "payload.required_cell_ids")
    accepted = _strings(payload.get("accepted_cell_ids"), "payload.accepted_cell_ids")
    if required != ids or accepted != ids or payload.get("d1_event_id") != request["d1_event_id"]:
        raise CheckerCompletionError("CHECKER_COMPLETION_PLAN_INVALID", "D2_READY does not bind every required CELL")
    if payload.get("final_candidate_message_id") != details.get("candidate_message_id"):
        raise CheckerCompletionError("CHECKER_COMPLETION_D1_MISMATCH", "D2_READY candidate is not the final D1 candidate")
    _strings(payload.get("d2_criteria"), "payload.d2_criteria")
    for item in _strings(payload.get("evidence_refs"), "payload.evidence_refs"):
        _existing_path(item, "payload.evidence_ref")


def _validate_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if set(request) != REQUEST_FIELDS or request.get("schema_version") != REQUEST_SCHEMA:
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", "request is not closed")
    if request.get("method_version") not in SUPPORTED_METHOD_VERSIONS or request.get("route") not in {"NEXT_CELL", "D2_READY"}:
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", "method version or route is invalid")
    for field in (
        "completion_invocation_id", "run_id", "go_id", "cell_id", "target_cell_id",
        "checker_role_instance_id", "d1_event_id",
    ):
        _text(request.get(field), field)
    if not IDENTIFIER.fullmatch(str(request["completion_invocation_id"])):
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", "completion_invocation_id is invalid")
    for field in ("attempt", "plan_revision", "runtime_revision", "token_sequence"):
        _positive(request.get(field), field)
    for field in ("runtime_projection_path", "target_endpoint_path", "checker_credential_path"):
        _existing_path(request.get(field), field)
    _existing_path(request.get("handoff_attempt_root"), "handoff_attempt_root", directory=True)
    for field in ("state_command", "transport_command"):
        _strings(request.get(field), field)
    try:
        timestamp = datetime.fromisoformat(_text(request.get("occurred_at"), "occurred_at").replace("Z", "+00:00"))
    except ValueError as exc:
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", "occurred_at must be RFC3339") from exc
    if timestamp.tzinfo is None:
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_INVALID", "occurred_at must include timezone")
    return dict(request)


def _validate_boundary(request: Mapping[str, Any]) -> dict[str, Any]:
    projection = _read_object(Path(str(request["runtime_projection_path"])), "runtime projection")
    summary = projection.get("summary")
    snapshot = projection.get("runtime_snapshot")
    events = projection.get("events")
    if (
        not isinstance(summary, Mapping) or summary.get("run_id") != request["run_id"]
        or summary.get("slk_version") != request["method_version"]
        or summary.get("current_plan_revision") != request["plan_revision"]
        or not isinstance(snapshot, Mapping) or snapshot.get("method_version") != request["method_version"]
        or snapshot.get("plan_revision") != request["plan_revision"]
        or snapshot.get("runtime_revision") != request["runtime_revision"]
        or snapshot.get("token_sequence") != request["token_sequence"]
        or snapshot.get("token_holder_role_instance_id") != request["checker_role_instance_id"]
        or not isinstance(events, list)
    ):
        raise CheckerCompletionError("CHECKER_COMPLETION_RUNTIME_MISMATCH", "runtime is not the exact Checker boundary")
    try:
        token_boundary = resolve_authoritative_token_boundary(
            projection, run_id=request["run_id"], plan_revision=request["plan_revision"])
    except CompletionError as exc:
        raise CheckerCompletionError("CHECKER_COMPLETION_RUNTIME_MISMATCH",
                                     "runtime TOKEN boundary is not authoritative") from exc
    terminals = [
        event for event in events
        if isinstance(event, Mapping)
        and event.get("event_type") in {"D1_PASSED", "D1_FAILED", "D1_INCOMPLETE"}
        and event.get("go_id") == request["go_id"]
        and event.get("cell_id") == request["cell_id"]
        and event.get("attempt") == request["attempt"]
    ]
    matches = [event for event in terminals if event.get("event_id") == request["d1_event_id"]]
    if len(matches) != 1 or not terminals or terminals[-1] is not matches[0]:
        raise CheckerCompletionError("CHECKER_COMPLETION_D1_MISMATCH", "bound D1 is not the current terminal")
    event = matches[0]
    details = _details(event)
    if (
        event.get("event_type") != "D1_PASSED"
        or event.get("author_role_instance_id") != request["checker_role_instance_id"]
        or details.get("verdict") != "PASS"
        or token_boundary["message_id"]
        != details.get("native_message_id", details.get("candidate_message_id"))
    ):
        raise CheckerCompletionError("CHECKER_COMPLETION_D1_MISMATCH", "Checker completion requires exact D1 PASS")
    cells = _ordered_cells(projection)
    ids = [str(cell["cell_id"]) for cell in cells]
    try:
        current_index = ids.index(str(request["cell_id"]))
    except ValueError as exc:
        raise CheckerCompletionError("CHECKER_COMPLETION_PLAN_INVALID", "D1 CELL is not required by the current plan") from exc
    if cells[current_index].get("state") != "d1_passed":
        raise CheckerCompletionError("CHECKER_COMPLETION_PLAN_INVALID", "current CELL is not D1 accepted")
    endpoint = Endpoint.from_dict(_read_object(Path(str(request["target_endpoint_path"])), "target endpoint"))
    route = request["route"]
    if route == "NEXT_CELL":
        if current_index + 1 >= len(cells) or request["target_cell_id"] != ids[current_index + 1]:
            raise CheckerCompletionError("CHECKER_COMPLETION_PLAN_INVALID", "target is not the next required CELL")
        if endpoint.run_id != request["run_id"] or endpoint.role != "worker":
            raise CheckerCompletionError("CHECKER_COMPLETION_TARGET_INVALID", "NEXT_CELL requires the current Worker endpoint")
    else:
        if current_index != len(cells) - 1 or request["target_cell_id"] != request["cell_id"]:
            raise CheckerCompletionError("CHECKER_COMPLETION_PLAN_INVALID", "D2_READY requires the final required CELL")
        if any(cell.get("state") != "d1_passed" for cell in cells):
            raise CheckerCompletionError("CHECKER_COMPLETION_PLAN_INVALID", "D2_READY requires every required CELL D1 PASS")
        if endpoint.run_id != request["run_id"] or endpoint.role != "supervisor":
            raise CheckerCompletionError("CHECKER_COMPLETION_TARGET_INVALID", "D2_READY requires the current Supervisor endpoint")
    _validate_payload(request, cells, details)
    return {"projection": projection, "event": dict(event), "details": dict(details), "cells": cells, "endpoint": endpoint}


def _materialize(request: Mapping[str, Any], boundary: Mapping[str, Any]) -> dict[str, Any]:
    endpoint: Endpoint = boundary["endpoint"]
    payload = dict(request["payload"])
    message_id = _stable_id(request, str(request["route"]).lower())
    envelope = {
        "schema_version": ENVELOPE_SCHEMA,
        "message_id": message_id,
        "token_sequence": int(request["token_sequence"]) + 1,
        "run_id": request["run_id"],
        "go_id": request["go_id"],
        "cell_id": request["target_cell_id"],
        "sender_role": "checker",
        "sender_role_instance_id": request["checker_role_instance_id"],
        "receiver_role": endpoint.role,
        "receiver_role_instance_id": endpoint.role_instance_id,
        "receiver_endpoint_version": endpoint.endpoint_version,
        "payload_type": "WORKER_TASK" if request["route"] == "NEXT_CELL" else "D2_READY",
        "payload_sha256": canonical_json_sha256(payload),
        "payload": payload,
    }
    Envelope.from_dict(envelope)
    root = (
        Path(str(request["handoff_attempt_root"])) / ".checker-completion"
        / str(request["completion_invocation_id"])
    ).resolve()
    endpoint_path = _write_stable(root / "endpoint.json", _read_object(Path(str(request["target_endpoint_path"])), "target endpoint"))
    envelope_path = _write_stable(root / "envelope.json", envelope)
    delivery = (
        Path(str(request["handoff_attempt_root"])) / str(request["run_id"])
        / str(envelope["message_id"])
    ).resolve()
    bridge = delivery / "recovery" / "desktop-current-turn"
    return {
        "endpoint": endpoint,
        "envelope": envelope,
        "endpoint_path": endpoint_path,
        "envelope_path": envelope_path,
        "request_root": root,
        "desktop_request_path": bridge / "request.json",
        "desktop_started_path": bridge / "started.json",
    }


def _authenticate(request: Mapping[str, Any], credential: str, run_json_command: RunJsonCommand) -> None:
    result = run_json_command(
        list(request["state_command"]),
        ["authenticate-role", "--run-id", str(request["run_id"]), "--role-instance-id", str(request["checker_role_instance_id"])],
        credential=credential,
    )
    if (
        result.get("status") != "authenticated" or result.get("run_id") != request["run_id"]
        or result.get("role") != "checker"
        or result.get("role_instance_id") != request["checker_role_instance_id"]
        or result.get("runtime_revision") != request["runtime_revision"]
    ):
        raise CheckerCompletionError("CHECKER_COMPLETION_AUTHORITY_INVALID", "credential is not the current Checker")


def _direct_start(
    request: Mapping[str, Any], prepared: Mapping[str, Any], run_json_command: RunJsonCommand
) -> tuple[str, Path] | dict[str, Any]:
    common = [
        "--endpoint", str(prepared["endpoint_path"]), "--envelope", str(prepared["envelope_path"]),
        "--attempt-root", str(Path(str(request["handoff_attempt_root"])).resolve()),
    ]
    envelope = prepared["envelope"]
    attempt = (
        Path(str(request["handoff_attempt_root"])) / str(request["run_id"])
        / str(envelope["message_id"])
    ).resolve()
    if request["route"] == "D2_READY":
        try:
            late = validate_late_desktop_start(
                prepared["endpoint"], Envelope.from_dict(envelope), Attempt(attempt)
            )
        except AdapterError as exc:
            raise CheckerCompletionError(
                "CHECKER_COMPLETION_START_UNPROVEN", "late Desktop start is invalid"
            ) from exc
        if late is not None:
            return str(envelope["message_id"]), attempt / "started.json"
    sent = run_json_command(list(request["transport_command"]), ["send", *common], credential=None)
    failure_kind = sent.get("error_code")
    if request["route"] == "D2_READY" and sent.get("status") == "failed" and failure_kind in {
        "CODEX_ACTIVE_WRITER_UNRESOLVED", "CODEX_RPC_TIMEOUT",
    }:
        retried = run_json_command(
            list(request["transport_command"]), ["retry-exact", *common], credential=None
        )
        retry_result = retried.get("result")
        if (
            retried.get("status") != "SUPERVISOR_DECISION_REQUIRED"
            or retried.get("reason") != "EXACT_RETRY_EXHAUSTED"
            or not isinstance(retry_result, Mapping)
            or retry_result.get("error_code") != failure_kind
        ):
            raise CheckerCompletionError(
                "CHECKER_COMPLETION_DELIVERY_FAILED", "exact Desktop writer retry is not exhausted"
            )
        desktop = dict(
            run_json_command(
                list(request["transport_command"]),
                ["prepare-desktop-current-turn", *common],
                credential=None,
            )
        )
        endpoint: Endpoint = prepared["endpoint"]
        if (
            desktop.get("schema_version") != "slk.transport-desktop-current-turn-request/v1"
            or desktop.get("status") != "PREPARED"
            or desktop.get("run_id") != request["run_id"]
            or desktop.get("go_id") != request["go_id"]
            or desktop.get("cell_id") != request["target_cell_id"]
            or desktop.get("original_message_id") != envelope["message_id"]
            or desktop.get("target_thread_id") != endpoint.address["thread_id"]
            or desktop.get("payload_type") != "D2_READY"
            or desktop.get("payload_sha256") != envelope["payload_sha256"]
            or not isinstance(desktop.get("recovery_message_id"), str)
            or not isinstance(desktop.get("prompt"), str)
            or not isinstance(desktop.get("prompt_sha256"), str)
        ):
            raise CheckerCompletionError(
                "CHECKER_COMPLETION_DESKTOP_INVALID", "Desktop bridge changed D2_READY identity"
            )
        desktop.pop("_slk_command", None)
        return {
            "schema_version": "slk.checker-completion-result/v1",
            "status": "DESKTOP_BRIDGE_REQUIRED",
            "route": "D2_READY",
            "run_id": request["run_id"],
            "go_id": request["go_id"],
            "cell_id": request["cell_id"],
            "target_cell_id": request["target_cell_id"],
            "d1_event_id": request["d1_event_id"],
            "message_id": envelope["message_id"],
            "desktop_request_path": str(prepared["desktop_request_path"]),
            "desktop_request": desktop,
        }
    if (
        sent.get("status") not in {"started", "completed"}
        or sent.get("run_id") != request["run_id"]
        or sent.get("message_id") != envelope["message_id"]
    ):
        raise CheckerCompletionError("CHECKER_COMPLETION_DELIVERY_FAILED", "target native start was not proven")
    started_path = attempt / "started.json"
    try:
        validate_native_start(
            started_path,
            adapter=prepared["endpoint"].adapter,
            run_id=str(request["run_id"]),
            cell_id=str(request["target_cell_id"]),
            message_id=str(envelope["message_id"]),
            request_sha256=str(envelope["payload_sha256"]),
        )
    except NativeActivityError as exc:
        raise CheckerCompletionError("CHECKER_COMPLETION_START_UNPROVEN", "target native start evidence is invalid") from exc
    return str(envelope["message_id"]), started_path


def _commit(
    request: Mapping[str, Any], prepared: Mapping[str, Any], message_id: str,
    started_path: Path, credential: str, run_json_command: RunJsonCommand,
    *, endpoint_sha256: str | None = None, envelope_sha256: str | None = None,
) -> dict[str, Any]:
    attempt = started_path.parent
    if endpoint_sha256 is None or envelope_sha256 is None:
        endpoint_evidence = attempt / "endpoint.json"
        envelope_evidence = attempt / "envelope.json"
        if not endpoint_evidence.is_file() or not envelope_evidence.is_file():
            raise CheckerCompletionError(
                "CHECKER_COMPLETION_START_UNPROVEN", "transport identity evidence is missing"
            )
        endpoint_sha256 = _sha256(endpoint_evidence)
        envelope_sha256 = _sha256(envelope_evidence)
    endpoint: Endpoint = prepared["endpoint"]
    envelope = prepared["envelope"]
    start = validate_native_start(
        started_path, adapter=endpoint.adapter, run_id=str(request["run_id"]),
        cell_id=str(request["target_cell_id"]), message_id=message_id,
        request_sha256=str(envelope["payload_sha256"]),
    )
    commit = {
        "event_id": _stable_id(request, "target-transport-started"),
        "transport_receipt_id": _stable_id(request, "target-transport-receipt"),
        "run_id": request["run_id"],
        "go_id": request["go_id"],
        "cell_id": request["target_cell_id"],
        "attempt": request["attempt"] if request["route"] == "D2_READY" else 1,
        "plan_revision": request["plan_revision"],
        "expected_runtime_revision": request["runtime_revision"],
        "message_id": message_id,
        "token_sequence": int(request["token_sequence"]) + 1,
        "from_role_instance_id": request["checker_role_instance_id"],
        "to_role_instance_id": endpoint.role_instance_id,
        "endpoint_version": endpoint.endpoint_version,
        "payload_type": envelope["payload_type"],
        "payload_sha256": envelope["payload_sha256"],
        "start_evidence": {
            "evidence_id": _stable_id(request, "target-native-start"),
            "stored_path": str(started_path),
            "sha256": _sha256(started_path),
            "message_id": message_id,
            "endpoint_sha256": endpoint_sha256,
            "envelope_sha256": envelope_sha256,
            "native_status": "STARTED",
        },
        "occurred_at": start["observed_at"],
    }
    commit_path = _write_stable(Path(str(prepared["request_root"])) / "commit-delivery-start.json", commit)
    recorded = run_json_command(
        list(request["state_command"]),
        ["commit-delivery-start", "--request", str(commit_path)],
        credential=credential,
    )
    if (
        recorded.get("status") not in {"committed", "idempotent_replay"}
        or recorded.get("run_id") != request["run_id"]
        or recorded.get("runtime_revision") != int(request["runtime_revision"]) + 1
        or recorded.get("token_sequence") != int(request["token_sequence"]) + 1
        or recorded.get("token_owner_role_instance_id") != endpoint.role_instance_id
        or recorded.get("message_id") != message_id
    ):
        raise CheckerCompletionError("CHECKER_COMPLETION_COMMIT_FAILED", "atomic TOKEN commit did not match")
    _write_stable(commit_path.with_suffix(".result.json"), recorded)
    return {
        "schema_version": "slk.checker-completion-result/v1",
        "status": "CHECKER_COMPLETION_COMMITTED",
        "route": request["route"],
        "run_id": request["run_id"],
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "target_cell_id": request["target_cell_id"],
        "d1_event_id": request["d1_event_id"],
        "message_id": message_id,
        "runtime_revision": recorded["runtime_revision"],
        "token_sequence": recorded["token_sequence"],
        "token_owner_role_instance_id": recorded["token_owner_role_instance_id"],
        "commit_request_path": str(commit_path),
        "started_path": str(started_path),
    }


def _complete_desktop(
    request: Mapping[str, Any], prepared: Mapping[str, Any], host_receipt_path: Path,
    credential: str, run_json_command: RunJsonCommand,
) -> dict[str, Any]:
    if request["route"] != "D2_READY":
        raise CheckerCompletionError(
            "CHECKER_COMPLETION_DESKTOP_INVALID", "Desktop bridge is only valid for D2_READY"
        )
    desktop = _read_object(Path(str(prepared["desktop_request_path"])), "Desktop bridge request")
    common = [
        "--endpoint", str(prepared["endpoint_path"]), "--envelope", str(prepared["envelope_path"]),
        "--attempt-root", str(Path(str(request["handoff_attempt_root"])).resolve()),
    ]
    recovered = run_json_command(
        list(request["transport_command"]),
        ["complete-desktop-current-turn", *common, "--host-receipt", str(host_receipt_path)],
        credential=None,
    )
    recovery_message_id = recovered.get("recovery_message_id")
    envelope = prepared["envelope"]
    if (
        recovered.get("status") != "started"
        or recovered.get("recovery_of_message_id") != envelope["message_id"]
        or recovered.get("run_id") != request["run_id"]
        or recovered.get("payload_sha256") != envelope["payload_sha256"]
        or recovery_message_id != desktop.get("recovery_message_id")
        or not isinstance(recovered.get("endpoint_sha256"), str)
        or not isinstance(recovered.get("envelope_sha256"), str)
    ):
        raise CheckerCompletionError(
            "CHECKER_COMPLETION_DESKTOP_INVALID", "Desktop recovery does not prove exact D2_READY"
        )
    started_path = Path(str(prepared["desktop_started_path"]))
    try:
        validate_native_start(
            started_path,
            adapter=prepared["endpoint"].adapter,
            run_id=str(request["run_id"]),
            cell_id=str(request["target_cell_id"]),
            message_id=str(recovery_message_id),
            request_sha256=str(envelope["payload_sha256"]),
            native_request_sha256=str(desktop.get("prompt_sha256")),
        )
    except NativeActivityError as exc:
        raise CheckerCompletionError(
            "CHECKER_COMPLETION_START_UNPROVEN", "Desktop start evidence is missing or invalid"
        ) from exc
    return _commit(
        request,
        prepared,
        str(recovery_message_id),
        started_path,
        credential,
        run_json_command,
        endpoint_sha256=str(recovered["endpoint_sha256"]),
        envelope_sha256=str(recovered["envelope_sha256"]),
    )


def execute_checker_completion(
    request: Mapping[str, Any], *, request_sha256: str, request_path: Path | str,
    host_receipt_path: Path | str | None = None,
    temporal: Mapping[str, Any] | None = None,
    run_json_command: RunJsonCommand = _run_json_command,
    unprotect_credential: UnprotectCredential = unprotect_dpapi_hex,
) -> dict[str, Any]:
    """Complete one PASS route only after target start and atomic TOKEN commit."""

    path = Path(request_path).resolve()
    if _sha256(path) != request_sha256 or _read_object(path, "request") != dict(request):
        raise CheckerCompletionError("CHECKER_COMPLETION_REQUEST_MISMATCH", "request bytes or SHA-256 changed")
    validated = _validate_request(request)
    boundary = _validate_boundary(validated)
    prepared = _materialize(validated, boundary)
    credential = unprotect_credential(Path(str(validated["checker_credential_path"])))
    try:
        _authenticate(validated, credential, run_json_command)
        if host_receipt_path is not None:
            if temporal is not None:
                raise CheckerCompletionError("CHECKER_COMPLETION_TEMPORAL_REQUIRED", "Temporal-bound completion cannot bypass its native ACK")
            receipt = _existing_path(str(host_receipt_path), "host_receipt_path")
            return _complete_desktop(
                validated, prepared, receipt, credential, run_json_command
            )
        if temporal is not None:
            envelope = prepared["envelope"]
            native = wc.start_temporal_delivery(
                temporal, Path(prepared["request_root"]),
                _read_object(Path(prepared["endpoint_path"]), "target endpoint"), envelope,
                attempt=int(validated["attempt"]) if validated["route"] == "D2_READY" else 1,
                source_runtime_revision=int(validated["runtime_revision"]),
                required_attempt_root=Path(str(validated["handoff_attempt_root"])),
            )
            return _commit(validated, prepared, str(envelope["message_id"]), native / "started.json", credential, run_json_command)
        direct = _direct_start(validated, prepared, run_json_command)
        if isinstance(direct, dict):
            return direct
        message_id, started_path = direct
        return _commit(validated, prepared, message_id, started_path, credential, run_json_command)
    finally:
        credential = ""
