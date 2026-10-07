"""Closed Checker-to-Supervisor management exit for one current D1 INCOMPLETE."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from . import SUPPORTED_METHOD_VERSIONS
from .checker_escalation import (
    CheckerEscalationError,
    _authenticate,
    _command,
    _complete,
    _details,
    _path,
    _positive,
    _prepare,
    _read_object,
    _sha256,
    _stable_id,
    _strings,
    _text,
    _write_stable,
)
from .contracts import ENVELOPE_SCHEMA, IDENTIFIER, Endpoint, Envelope, canonical_json_sha256
from .worker_completion import _run_json_command, resolve_authoritative_token_boundary, unprotect_dpapi_hex


REQUEST_SCHEMA = "slk.checker-management-request/v1"
REQUEST_FIELDS = frozenset({
    "schema_version", "method_version", "management_invocation_id", "run_id", "go_id",
    "cell_id", "attempt", "plan_revision", "runtime_revision", "token_sequence",
    "checker_role_instance_id", "d1_incomplete_event_id", "runtime_projection_path",
    "native_attempt_path", "supervisor_endpoint_path", "checker_credential_path",
    "state_command", "transport_command", "escalation_attempt_root", "reason_codes",
    "evidence_refs", "occurred_at",
})


def _validate_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if set(request) != REQUEST_FIELDS or request.get("schema_version") != REQUEST_SCHEMA:
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_REQUEST_INVALID", "Checker management request is not closed"
        )
    if request.get("method_version") not in SUPPORTED_METHOD_VERSIONS:
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_REQUEST_INVALID", "method version is unsupported"
        )
    for field in (
        "management_invocation_id", "run_id", "go_id", "cell_id",
        "checker_role_instance_id", "d1_incomplete_event_id",
    ):
        _text(request.get(field), field)
    if not IDENTIFIER.fullmatch(str(request["management_invocation_id"])):
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_REQUEST_INVALID", "management_invocation_id is invalid"
        )
    for field in ("attempt", "plan_revision", "runtime_revision", "token_sequence"):
        _positive(request.get(field), field)
    for field in ("reason_codes", "evidence_refs"):
        _strings(request.get(field), field)
    for field in (
        "runtime_projection_path", "native_attempt_path", "supervisor_endpoint_path",
        "checker_credential_path",
    ):
        _path(request.get(field), field, directory=field == "native_attempt_path")
    _path(request.get("escalation_attempt_root"), "escalation_attempt_root", directory=True)
    _command(request.get("state_command"), "state_command")
    _command(request.get("transport_command"), "transport_command")
    try:
        timestamp = datetime.fromisoformat(
            _text(request.get("occurred_at"), "occurred_at").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_REQUEST_INVALID", "occurred_at must be RFC3339"
        ) from exc
    if timestamp.tzinfo is None:
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_REQUEST_INVALID", "occurred_at must include a timezone"
        )
    return dict(request)


def _validate_incomplete(request: Mapping[str, Any]) -> dict[str, Any]:
    projection = _read_object(Path(str(request["runtime_projection_path"])), "runtime projection")
    summary = projection.get("summary")
    snapshot = projection.get("runtime_snapshot")
    events = projection.get("events")
    if (
        not isinstance(summary, Mapping)
        or summary.get("run_id") != request["run_id"]
        or summary.get("slk_version") != request["method_version"]
        or summary.get("current_plan_revision") != request["plan_revision"]
        or not isinstance(snapshot, Mapping)
        or snapshot.get("method_version") != request["method_version"]
        or snapshot.get("plan_revision") != request["plan_revision"]
        or snapshot.get("runtime_revision") != request["runtime_revision"]
        or snapshot.get("token_sequence") != request["token_sequence"]
        or snapshot.get("token_holder_role_instance_id") != request["checker_role_instance_id"]
        or not isinstance(events, list)
    ):
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_RUNTIME_MISMATCH",
            "runtime projection is not the exact Checker-owned D1 INCOMPLETE boundary",
        )
    boundary = resolve_authoritative_token_boundary(
        projection, run_id=str(request["run_id"]), plan_revision=int(request["plan_revision"])
    )
    terminals = [
        event for event in events
        if isinstance(event, Mapping)
        and event.get("event_type") in {"D1_FAILED", "D1_PASSED", "D1_INCOMPLETE"}
        and event.get("go_id") == request["go_id"]
        and event.get("cell_id") == request["cell_id"]
        and event.get("attempt") == request["attempt"]
    ]
    matches = [
        event for event in terminals
        if event.get("event_id") == request["d1_incomplete_event_id"]
    ]
    if len(matches) != 1 or not terminals or terminals[-1] is not matches[0]:
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_D1_MISMATCH", "D1 INCOMPLETE is not the current terminal"
        )
    event = matches[0]
    details = _details(event)
    candidate_message_id = details.get("candidate_message_id")
    if (
        event.get("event_type") != "D1_INCOMPLETE"
        or event.get("author_role_instance_id") != request["checker_role_instance_id"]
        or details.get("verdict") != "INCOMPLETE"
        or boundary["message_id"] != candidate_message_id
    ):
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_D1_MISMATCH", "request does not bind the current INCOMPLETE"
        )

    native = Path(str(request["native_attempt_path"])).resolve()
    endpoint = Endpoint.from_dict(_read_object(native / "endpoint.json", "OCRV endpoint"))
    envelope = Envelope.from_dict(_read_object(native / "envelope.json", "OCRV envelope"))
    started = native / "started.json"
    terminal_path = Path(str(details.get("native_terminal_path", ""))).resolve()
    result_path_value = details.get("native_result_path")
    result_path = Path(result_path_value).resolve() if isinstance(result_path_value, str) else None
    if (
        endpoint.run_id != request["run_id"]
        or endpoint.role != "checker"
        or endpoint.role_instance_id != request["checker_role_instance_id"]
        or envelope.run_id != request["run_id"]
        or envelope.go_id != request["go_id"]
        or envelope.cell_id != request["cell_id"]
        or envelope.receiver_role_instance_id != request["checker_role_instance_id"]
        or envelope.payload_type != "CANDIDATE_READY"
        or envelope.message_id != candidate_message_id
        or not started.is_file()
        or details.get("native_start_sha256") != _sha256(started)
        or terminal_path.parent != native
        or terminal_path.name not in {"completed.json", "failed.json"}
        or not terminal_path.is_file()
        or details.get("native_terminal_sha256") != _sha256(terminal_path)
    ):
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_EVIDENCE_INVALID", "native Checker evidence changed"
        )
    terminal = _read_object(terminal_path, "OCRV terminal")
    if terminal.get("message_id") != candidate_message_id or terminal.get("run_id") != request["run_id"]:
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_EVIDENCE_INVALID", "native terminal identity changed"
        )
    if result_path is not None:
        if (
            result_path.parent != native
            or result_path.name != "ocrv-result.json"
            or not result_path.is_file()
            or details.get("native_result_sha256") != _sha256(result_path)
            or _read_object(result_path, "OCRV result").get("verdict") != "INCOMPLETE"
        ):
            raise CheckerEscalationError(
                "CHECKER_MANAGEMENT_EVIDENCE_INVALID", "native INCOMPLETE result changed"
            )
    supervisor = Endpoint.from_dict(
        _read_object(Path(str(request["supervisor_endpoint_path"])), "Supervisor endpoint")
    )
    if supervisor.run_id != request["run_id"] or supervisor.role != "supervisor":
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_SUPERVISOR_INVALID", "Supervisor endpoint does not match the Run"
        )
    evidence = []
    reason_bound = False
    for value in request["evidence_refs"]:
        path = Path(str(value)).resolve()
        if not path.is_file():
            raise CheckerEscalationError(
                "CHECKER_MANAGEMENT_EVIDENCE_INVALID", "supplemental evidence is unavailable"
            )
        evidence.append({"path": str(path), "sha256": _sha256(path)})
        try:
            observed = _read_object(path, "supplemental evidence")
        except CheckerEscalationError:
            observed = {}
        if (
            observed.get("verdict") == "INCOMPLETE"
            and observed.get("reason_codes") == request["reason_codes"]
        ):
            reason_bound = True
    if not reason_bound and details.get("reason_codes") != request["reason_codes"]:
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_EVIDENCE_INVALID", "management reason codes are unbound"
        )
    return {
        "candidate_message_id": str(candidate_message_id),
        "native_terminal_sha256": _sha256(terminal_path),
        "native_result_sha256": _sha256(result_path) if result_path is not None else None,
        "evidence": evidence,
        "supervisor": supervisor,
    }


def materialize_management_escalation(request: Mapping[str, Any]) -> dict[str, Any]:
    validated_request = _validate_request(request)
    validated = _validate_incomplete(validated_request)
    supervisor: Endpoint = validated["supervisor"]
    payload = {
        "d1_incomplete_event_id": request["d1_incomplete_event_id"],
        "candidate_message_id": validated["candidate_message_id"],
        "reason_codes": list(request["reason_codes"]),
        "evidence": validated["evidence"],
        "native_terminal_sha256": validated["native_terminal_sha256"],
        "native_result_sha256": validated["native_result_sha256"],
        "decision_required": "CAPACITY_OR_ENVIRONMENT_MANAGEMENT",
    }
    envelope = {
        "schema_version": ENVELOPE_SCHEMA,
        "message_id": _stable_id(request, "d1-incomplete-escalation"),
        "token_sequence": int(request["token_sequence"]) + 1,
        "run_id": request["run_id"], "go_id": request["go_id"], "cell_id": request["cell_id"],
        "sender_role": "checker", "sender_role_instance_id": request["checker_role_instance_id"],
        "receiver_role": "supervisor", "receiver_role_instance_id": supervisor.role_instance_id,
        "receiver_endpoint_version": supervisor.endpoint_version,
        "payload_type": "D1_INCOMPLETE_ESCALATION",
        "payload_sha256": canonical_json_sha256(payload), "payload": payload,
    }
    Envelope.from_dict(envelope)
    endpoint = _read_object(Path(str(request["supervisor_endpoint_path"])), "Supervisor endpoint")
    root = (
        Path(str(request["escalation_attempt_root"])) / ".checker-management"
        / str(request["management_invocation_id"])
    ).resolve()
    endpoint_path = _write_stable(root / "endpoint.json", endpoint)
    envelope_path = _write_stable(root / "envelope.json", envelope)
    delivery = Path(str(request["escalation_attempt_root"])).resolve() / str(request["run_id"]) / str(envelope["message_id"])
    bridge = delivery / "recovery" / "desktop-current-turn"
    return {
        "endpoint": endpoint, "envelope": envelope,
        "endpoint_path": str(endpoint_path), "envelope_path": str(envelope_path),
        "attempt_root": str(Path(str(request["escalation_attempt_root"])).resolve()),
        "delivery_path": str(delivery), "desktop_request_path": str(bridge / "request.json"),
        "desktop_started_path": str(bridge / "started.json"),
    }


def execute_checker_management(
    request: Mapping[str, Any], *, request_sha256: str, request_path: Path | str,
    host_receipt_path: Path | str | None = None,
    run_json_command: Callable[..., Mapping[str, Any]] = _run_json_command,
    unprotect_credential: Callable[[Path | str], str] = unprotect_dpapi_hex,
) -> dict[str, Any]:
    path = Path(request_path).resolve()
    if _sha256(path) != request_sha256 or _read_object(path, "management request") != dict(request):
        raise CheckerEscalationError(
            "CHECKER_MANAGEMENT_REQUEST_MISMATCH", "management request bytes changed"
        )
    validated = _validate_request(request)
    _validate_incomplete(validated)
    prepared = materialize_management_escalation(validated)
    credential = unprotect_credential(Path(str(validated["checker_credential_path"])))
    try:
        _authenticate(validated, credential, run_json_command)
        if host_receipt_path is None:
            return _prepare(validated, prepared, run_json_command, credential)
        receipt = _path(str(host_receipt_path), "host_receipt_path")
        return _complete(validated, prepared, receipt, credential, run_json_command)
    finally:
        credential = ""
