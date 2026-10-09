"""Authenticated FAIL-only Checker suffix for one existing D1 terminal result."""

from __future__ import annotations

from . import SUPPORTED_METHOD_VERSIONS

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from .adapters.base import AdapterError
from .adapters.codex_desktop import validate_late_desktop_start
from .contracts import ENVELOPE_SCHEMA, IDENTIFIER, DeliveryResult, Endpoint, Envelope, canonical_json_sha256
from .evidence import Attempt
from .native_activity import NativeActivityError, validate_native_start
from .worker_completion import CompletionError, _run_json_command, resolve_authoritative_token_boundary, unprotect_dpapi_hex


REQUEST_SCHEMA = "slk.checker-post-d1-request/v1"
_NAMESPACE = uuid.UUID("4933ab7d-4b65-4a44-b3d6-ce2514d82612")
REQUEST_FIELDS = frozenset(
    {
        "schema_version",
        "method_version",
        "post_d1_invocation_id",
        "run_id",
        "go_id",
        "cell_id",
        "attempt",
        "plan_revision",
        "runtime_revision",
        "token_sequence",
        "checker_role_instance_id",
        "d1_failure_event_id",
        "runtime_projection_path",
        "native_attempt_path",
        "supervisor_endpoint_path",
        "checker_credential_path",
        "state_command",
        "transport_command",
        "escalation_attempt_root",
        "rework_round",
        "cell_goal",
        "acceptance_criteria",
        "findings",
        "reproduction_steps",
        "expected_result",
        "evidence_refs",
        "occurred_at",
    }
)


class CheckerEscalationError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


RunJsonCommand = Callable[[list[str], list[str]], Mapping[str, Any]]
UnprotectCredential = Callable[[Path | str], str]


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_EVIDENCE_INVALID", f"{label} is unreadable"
        ) from exc
    if not isinstance(value, dict):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_EVIDENCE_INVALID", f"{label} must be an object"
        )
    return value


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_EVIDENCE_INVALID", f"evidence is unreadable: {path}"
        ) from exc


def _positive(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CheckerEscalationError("CHECKER_ESCALATION_REQUEST_INVALID", f"{label} must be positive")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_REQUEST_INVALID", f"{label} must be canonical non-empty text"
        )
    return value


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item and item == item.strip() for item in value
    ):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_REQUEST_INVALID", f"{label} must be a non-empty canonical string array"
        )
    return list(value)


def _command(value: Any, label: str) -> list[str]:
    return _strings(value, label)


def _path(value: Any, label: str, *, directory: bool = False) -> Path:
    path = Path(_text(value, label))
    if not path.is_absolute() or not (path.is_dir() if directory else path.is_file()):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_REQUEST_INVALID", f"{label} must be an existing absolute path"
        )
    return path.resolve()


def _details(event: Mapping[str, Any]) -> Mapping[str, Any]:
    value = event.get("details")
    if isinstance(value, Mapping):
        return value
    serialized = event.get("details_json")
    if isinstance(serialized, str):
        try:
            decoded = json.loads(serialized)
        except json.JSONDecodeError:
            return {}
        if isinstance(decoded, Mapping):
            return decoded
    return {}


def _validate_explicit_decision(
    native: Path, endpoint: Endpoint, envelope: Envelope,
    event: Mapping[str, Any], details: Mapping[str, Any],
) -> None:
    """Check the existing role action receipt, never later report/exit files."""
    receipt = native / "native-start.received.json"
    try:
        start = validate_native_start(receipt, adapter=endpoint.adapter,
            run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
            request_sha256=envelope.payload_sha256)
        decision = _read_object(native / "role-host" / "checker-decision.json", "Checker action")
        decided_at = datetime.fromisoformat(str(decision.get("decided_at", "")).replace("Z", "+00:00"))
        occurred_at = datetime.fromisoformat(str(event.get("occurred_at", "")).replace("Z", "+00:00"))
        valid = (dict(details) == decision
            and decision.get("decision_source") == "CHECKER_EXPLICIT"
            and decision.get("source_message_id") == envelope.message_id
            and decision.get("native_message_id") == envelope.message_id
            and decision.get("role_instance_id") == endpoint.role_instance_id
            and event.get("author_role_instance_id") == endpoint.role_instance_id
            and decision.get("native_start_path") == str(receipt.resolve())
            and decision.get("native_start_sha256") == _sha256(receipt)
            and start["native_task"]["kind"] == "ocrv-review"
            and decision.get("native_task_id") == start["native_task"]["id"]
            and decided_at.tzinfo is not None and occurred_at == decided_at)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise CheckerEscalationError("CHECKER_EXPLICIT_ACTION_INVALID", "original Checker action is unproved") from exc
    if not valid:
        raise CheckerEscalationError("CHECKER_EXPLICIT_ACTION_INVALID", "original Checker action evidence changed")


def _stable_id(request: Mapping[str, Any], suffix: str) -> str:
    source_event_id = request.get("d1_failure_event_id", request.get("d1_incomplete_event_id"))
    invocation_id = request.get("post_d1_invocation_id", request.get("management_invocation_id"))
    source = ":".join(
        str(value)
        for value in (
            request.get("run_id"), request.get("cell_id"), request.get("attempt"),
            source_event_id, invocation_id,
        )
    )
    return str(uuid.uuid5(_NAMESPACE, f"{source}:{suffix}"))


def _write_stable(path: Path, value: Mapping[str, Any]) -> Path:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if path.is_file():
        if path.read_bytes() != encoded:
            raise CheckerEscalationError(
                "CHECKER_ESCALATION_CONFLICT", f"immutable suffix evidence conflicts: {path.name}"
            )
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(path)
    return path


def _validate_request(request: Mapping[str, Any]) -> dict[str, Any]:
    if set(request) != REQUEST_FIELDS or request.get("schema_version") != REQUEST_SCHEMA:
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_REQUEST_INVALID", "post-D1 request is not closed"
        )
    if request.get("method_version") not in SUPPORTED_METHOD_VERSIONS:
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_REQUEST_INVALID", "post-D1 method version is unsupported"
        )
    for field in (
        "post_d1_invocation_id",
        "run_id",
        "go_id",
        "cell_id",
        "checker_role_instance_id",
        "d1_failure_event_id",
        "cell_goal",
    ):
        _text(request.get(field), field)
    if not IDENTIFIER.fullmatch(str(request["post_d1_invocation_id"])):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_REQUEST_INVALID",
            "post_d1_invocation_id must be one canonical identifier",
        )
    for field in (
        "attempt",
        "plan_revision",
        "runtime_revision",
        "token_sequence",
        "rework_round",
    ):
        _positive(request.get(field), field)
    for field in ("acceptance_criteria", "evidence_refs"):
        _strings(request.get(field), field)
    for field in ("findings", "reproduction_steps"):
        value = request.get(field)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise CheckerEscalationError("CHECKER_ESCALATION_REQUEST_INVALID", f"{field} must be supplied text or empty")
    if request.get("expected_result") is not None and not isinstance(request["expected_result"], str):
        raise CheckerEscalationError("CHECKER_ESCALATION_REQUEST_INVALID", "expected_result must be supplied text or null")
    for field in (
        "runtime_projection_path",
        "native_attempt_path",
        "supervisor_endpoint_path",
        "checker_credential_path",
    ):
        _path(request.get(field), field, directory=field == "native_attempt_path")
    _path(request.get("escalation_attempt_root"), "escalation_attempt_root", directory=True)
    _command(request.get("state_command"), "state_command")
    _command(request.get("transport_command"), "transport_command")
    try:
        timestamp = datetime.fromisoformat(_text(request.get("occurred_at"), "occurred_at").replace("Z", "+00:00"))
    except ValueError as exc:
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_REQUEST_INVALID", "occurred_at must be RFC3339"
        ) from exc
    if timestamp.tzinfo is None:
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_REQUEST_INVALID", "occurred_at must include a timezone"
        )
    return dict(request)


def _validate_failure(request: Mapping[str, Any]) -> dict[str, Any]:
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
            "CHECKER_ESCALATION_RUNTIME_MISMATCH",
            "runtime projection does not end at the exact Checker-owned D1 failure",
        )
    try:
        token_boundary = resolve_authoritative_token_boundary(
            projection, run_id=request["run_id"], plan_revision=request["plan_revision"])
    except CompletionError as exc:
        raise CheckerEscalationError("CHECKER_ESCALATION_RUNTIME_MISMATCH",
                                    "runtime TOKEN boundary is not authoritative") from exc
    scope_d1_terminals = [
        event
        for event in events
        if isinstance(event, Mapping)
        and event.get("event_type") in {"D1_FAILED", "D1_PASSED", "D1_INCOMPLETE"}
        and event.get("go_id") == request["go_id"]
        and event.get("cell_id") == request["cell_id"]
    ]
    d1_terminals = [
        event for event in scope_d1_terminals
        if event.get("attempt") == request["attempt"]
    ]
    matches = [
        event
        for event in scope_d1_terminals
        if event.get("event_id") == request["d1_failure_event_id"]
    ]
    if (
        len(matches) != 1
        or not d1_terminals
        or not scope_d1_terminals
        or scope_d1_terminals[-1] is not matches[0]
    ):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_D1_MISMATCH",
            "bound D1 failure is not the unique current terminal for this scope",
        )
    event = matches[0]
    event_index = events.index(event)
    details = _details(event)
    if (
        event.get("event_type") != "D1_FAILED"
        or event.get("author_role_instance_id") != request["checker_role_instance_id"]
        or event.get("go_id") != request["go_id"]
        or event.get("cell_id") != request["cell_id"]
        or event.get("attempt") != request["attempt"]
        or details.get("verdict") != "FAIL"
        or token_boundary["message_id"]
        != details.get("native_message_id", details.get("candidate_message_id"))
    ):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_D1_MISMATCH", "post-D1 suffix is limited to the exact current FAIL"
        )
    prior_rounds = sum(
        1
        for item in events
        if isinstance(item, Mapping)
        and item.get("event_type") == "REWORK_REQUESTED"
        and item.get("cell_id") == request["cell_id"]
    )
    if request["rework_round"] != prior_rounds + 1:
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_D1_MISMATCH", "rework round does not follow the frozen history"
        )

    native = Path(str(request["native_attempt_path"])).resolve()
    endpoint_path = native / "endpoint.json"
    envelope_path = native / "envelope.json"
    if not endpoint_path.is_file() or not envelope_path.is_file():
        raise CheckerEscalationError(
            "CHECKER_LEGACY_ACTION_RETIRED",
            "historical synthesized terminals cannot invoke a new Checker action; original reports remain deliverable",
        )
    started_path = native / "started.json"
    result_path = native / "ocrv-result.json"
    terminal_path = native / "completed.json"
    endpoint = Endpoint.from_dict(_read_object(endpoint_path, "OCRV endpoint"))
    envelope = Envelope.from_dict(_read_object(envelope_path, "OCRV envelope"))
    explicit = details.get("decision_source") == "CHECKER_EXPLICIT"
    if explicit:
        _validate_explicit_decision(native, endpoint, envelope, event, details)
    terminal = {} if explicit else _read_object(terminal_path, "OCRV terminal")
    candidate_message_id = details.get("candidate_message_id")
    native_message_id = details.get("native_message_id", candidate_message_id)
    management_return = envelope.payload_type == "D1_MANAGEMENT_RETURN"
    candidate_payload = (
        envelope.payload.get("candidate_payload")
        if management_return
        else envelope.payload
    )
    candidate = (
        candidate_payload.get("candidate")
        if isinstance(candidate_payload, Mapping)
        else None
    )
    ordinary_candidate = (
        envelope.payload_type == "CANDIDATE_READY"
        and envelope.message_id == candidate_message_id
        and native_message_id == candidate_message_id
    )
    management_source = None
    management_source_index = None
    candidate_start = None
    candidate_start_index = None
    management_start = None
    management_start_index = None
    preceding_candidate_terminal = None
    if management_return:
        sources = [
            (index, item)
            for index, item in enumerate(events)
            if isinstance(item, Mapping)
            and item.get("event_id") == event.get("corrects_event_id")
        ]
        if len(sources) == 1:
            management_source_index, management_source = sources[0]
        candidate_starts = [
            (index, item)
            for index, item in enumerate(events)
            if isinstance(item, Mapping)
            and item.get("event_type") == "TRANSPORT_STARTED"
            and item.get("go_id") == request["go_id"]
            and item.get("cell_id") == request["cell_id"]
            and _details(item).get("message_id") == candidate_message_id
        ]
        if len(candidate_starts) == 1:
            candidate_start_index, candidate_start = candidate_starts[0]
        management_starts = [
            (index, item)
            for index, item in enumerate(events)
            if isinstance(item, Mapping)
            and item.get("event_type") == "TRANSPORT_STARTED"
            and item.get("go_id") == request["go_id"]
            and item.get("cell_id") == request["cell_id"]
            and _details(item).get("message_id") == native_message_id
        ]
        if len(management_starts) == 1:
            management_start_index, management_start = management_starts[0]
        preceding = [
            item
            for index, item in enumerate(events)
            if isinstance(item, Mapping)
            and index < event_index
            and item.get("event_type") in {"D1_FAILED", "D1_PASSED", "D1_INCOMPLETE"}
            and item.get("go_id") == request["go_id"]
            and item.get("cell_id") == request["cell_id"]
            and _details(item).get("candidate_message_id") == candidate_message_id
        ]
        preceding_candidate_terminal = preceding[-1] if preceding else None
    management_source_details = (
        _details(management_source) if isinstance(management_source, Mapping) else {}
    )
    management_lineage_valid = (
        management_return
        and envelope.message_id == native_message_id
        and envelope.payload.get("candidate_message_id") == candidate_message_id
        and envelope.payload.get("source_d1_incomplete_event_id")
        == event.get("corrects_event_id")
        and envelope.payload.get("candidate_payload_sha256")
        == canonical_json_sha256(candidate_payload)
        and isinstance(management_source, Mapping)
        and isinstance(candidate_start, Mapping)
        and isinstance(management_start, Mapping)
        and management_source.get("event_type") == "D1_INCOMPLETE"
        and management_source.get("author_role_instance_id")
        == request["checker_role_instance_id"]
        and management_source.get("go_id") == request["go_id"]
        and management_source.get("cell_id") == request["cell_id"]
        and candidate_start.get("attempt") == management_source.get("attempt")
        and management_start.get("attempt") == request["attempt"]
        and management_start.get("author_role_instance_id")
        == envelope.sender_role_instance_id
        and candidate_start_index is not None
        and management_source_index is not None
        and management_start_index is not None
        and candidate_start_index < management_source_index < management_start_index
        and management_start_index < event_index
        and preceding_candidate_terminal is management_source
        and management_source_details.get("candidate_message_id") == candidate_message_id
        and management_source_details.get("verdict") == "INCOMPLETE"
    )
    if (
        endpoint.run_id != request["run_id"]
        or endpoint.role != "checker"
        or endpoint.role_instance_id != request["checker_role_instance_id"]
        or envelope.run_id != request["run_id"]
        or envelope.go_id != request["go_id"]
        or envelope.cell_id != request["cell_id"]
        or envelope.receiver_role != "checker"
        or envelope.receiver_role_instance_id != request["checker_role_instance_id"]
        or not (ordinary_candidate or management_lineage_valid)
        or not isinstance(candidate, Mapping)
        or (not explicit and (terminal.get("message_id") != native_message_id
        or terminal.get("run_id") != request["run_id"]
        or terminal.get("status") not in {"completed", "failed"}
        or not isinstance(terminal.get("native_identity"), Mapping)
        or details.get("native_start_sha256") != _sha256(started_path)
        or details.get("native_result_path") != str(result_path)
        or details.get("native_result_sha256") != _sha256(result_path)
        or details.get("native_terminal_path") != str(terminal_path)
        or details.get("native_terminal_sha256") != _sha256(terminal_path)))
    ):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_D1_MISMATCH",
            "D1 failure does not bind the immutable OCRV candidate and terminal evidence",
        )
    if event.get("corrects_event_id") is not None and not management_lineage_valid:
        raise CheckerEscalationError(
            "CHECKER_LEGACY_ACTION_RETIRED", "automatic classification corrections are historical facts, not new role actions"
        )
    supervisor = Endpoint.from_dict(
        _read_object(Path(str(request["supervisor_endpoint_path"])), "Supervisor endpoint")
    )
    if supervisor.run_id != request["run_id"] or supervisor.role != "supervisor":
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_SUPERVISOR_INVALID", "Supervisor endpoint does not match the Run"
        )
    return {
        "projection": projection,
        "event": dict(event),
        "details": dict(details),
        "candidate": dict(candidate),
        "candidate_sha256": canonical_json_sha256(candidate),
        "supervisor": supervisor,
    }


def _payload(request: Mapping[str, Any]) -> dict[str, Any]:
    validated = _validate_failure(request)
    return {
        "d1_failure_event_id": request["d1_failure_event_id"],
        "failed_candidate_sha256": validated["candidate_sha256"],
        "rework_round": request["rework_round"],
        "cell_goal": request["cell_goal"],
        "acceptance_criteria": list(request["acceptance_criteria"]),
        "findings": list(request["findings"]),
        "reproduction_steps": list(request["reproduction_steps"]),
        "expected_result": request["expected_result"],
        "evidence_refs": list(request["evidence_refs"]),
    }


def escalation_message_id(request: Mapping[str, Any]) -> str:
    return _stable_id(request, "d1-failure-escalation")


def escalation_payload_sha256(request: Mapping[str, Any]) -> str:
    return canonical_json_sha256(_payload(request))


def materialize_escalation(request: Mapping[str, Any]) -> dict[str, Any]:
    _validate_request(request)
    validated = _validate_failure(request)
    supervisor: Endpoint = validated["supervisor"]
    payload = {
        "d1_failure_event_id": request["d1_failure_event_id"],
        "failed_candidate_sha256": validated["candidate_sha256"],
        "rework_round": request["rework_round"],
        "cell_goal": request["cell_goal"],
        "acceptance_criteria": list(request["acceptance_criteria"]),
        "findings": list(request["findings"]),
        "reproduction_steps": list(request["reproduction_steps"]),
        "expected_result": request["expected_result"],
        "evidence_refs": list(request["evidence_refs"]),
    }
    envelope = {
        "schema_version": ENVELOPE_SCHEMA,
        "message_id": escalation_message_id(request),
        "token_sequence": int(request["token_sequence"]) + 1,
        "run_id": request["run_id"],
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "sender_role": "checker",
        "sender_role_instance_id": request["checker_role_instance_id"],
        "receiver_role": "supervisor",
        "receiver_role_instance_id": supervisor.role_instance_id,
        "receiver_endpoint_version": supervisor.endpoint_version,
        "payload_type": "D1_FAILURE_ESCALATION",
        "payload_sha256": canonical_json_sha256(payload),
        "payload": payload,
    }
    Envelope.from_dict(envelope)
    endpoint = _read_object(Path(str(request["supervisor_endpoint_path"])), "Supervisor endpoint")
    root = (
        Path(str(request["escalation_attempt_root"]))
        / ".checker-post-d1"
        / str(request["post_d1_invocation_id"])
    ).resolve()
    endpoint_path = _write_stable(root / "endpoint.json", endpoint)
    envelope_path = _write_stable(root / "envelope.json", envelope)
    delivery = (
        Path(str(request["escalation_attempt_root"])).resolve()
        / str(request["run_id"])
        / str(envelope["message_id"])
    )
    bridge = delivery / "recovery" / "desktop-current-turn"
    return {
        "endpoint": endpoint,
        "envelope": envelope,
        "endpoint_path": str(endpoint_path),
        "envelope_path": str(envelope_path),
        "attempt_root": str(Path(str(request["escalation_attempt_root"])).resolve()),
        "delivery_path": str(delivery),
        "desktop_request_path": str(bridge / "request.json"),
        "desktop_started_path": str(bridge / "started.json"),
        "failed_candidate": validated["candidate"],
    }


def _authenticate(
    request: Mapping[str, Any],
    credential: str,
    run_json_command: Callable[..., Mapping[str, Any]],
) -> None:
    result = run_json_command(
        list(request["state_command"]),
        [
            "authenticate-role",
            "--run-id",
            str(request["run_id"]),
            "--role-instance-id",
            str(request["checker_role_instance_id"]),
        ],
        credential=credential,
    )
    if (
        result.get("status") != "authenticated"
        or result.get("run_id") != request["run_id"]
        or result.get("role") != "checker"
        or result.get("role_instance_id") != request["checker_role_instance_id"]
        or result.get("runtime_revision") != request["runtime_revision"]
    ):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_AUTHORITY_INVALID",
            "sealed credential does not authenticate the exact current Checker",
        )


def _prepare(
    request: Mapping[str, Any],
    prepared: Mapping[str, Any],
    run_json_command: Callable[..., Mapping[str, Any]],
    credential: str,
    temporal: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if temporal is not None:
        from . import worker_completion as wc
        native = wc.start_temporal_delivery(
            temporal, Path(str(prepared["endpoint_path"])).parent, prepared["endpoint"], prepared["envelope"],
            attempt=int(request["attempt"]), source_runtime_revision=int(request["runtime_revision"]),
            required_attempt_root=Path(str(prepared["attempt_root"])),
        )
        return _commit_started(request, prepared, native / "started.json", str(prepared["envelope"]["message_id"]),
                               _sha256(native / "endpoint.json"), _sha256(native / "envelope.json"),
                               credential, run_json_command, recovered=False)
    common = [
        "--endpoint",
        str(prepared["endpoint_path"]),
        "--envelope",
        str(prepared["envelope_path"]),
        "--attempt-root",
        str(prepared["attempt_root"]),
    ]
    native = Path(str(prepared["delivery_path"]))
    try:
        late = validate_late_desktop_start(
            Endpoint.from_dict(prepared["endpoint"]),
            Envelope.from_dict(prepared["envelope"]),
            Attempt(native),
        )
    except AdapterError as exc:
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_START_UNPROVEN", "late Desktop start is invalid"
        ) from exc
    if late is not None:
        started_path = native / "started.json"
        return _commit_started(
            request, prepared, started_path, str(prepared["envelope"]["message_id"]),
            _sha256(native / "endpoint.json"), _sha256(native / "envelope.json"),
            credential, run_json_command, recovered=False,
        )
    sent = (_read_object(native / "failed.json", "preserved delivery failure")
            if (native / "failed.json").is_file() else run_json_command(
                list(request["transport_command"]), ["send", *common], credential=None))
    if sent.get("status") == "failed" and sent.get("error_code") == "CODEX_DESKTOP_HOST_UNAVAILABLE":
        failure = DeliveryResult.from_dict(_read_object(native / "failed.json", "preserved delivery failure"))
        if ("desktop" not in prepared["endpoint"]["address"]
            or failure.run_id != request["run_id"] or failure.message_id != prepared["envelope"]["message_id"]
            or failure.adapter != prepared["endpoint"]["adapter"] or failure.native_identity
            or failure.evidence != ("accepted.json", "endpoint.json", "envelope.json")
            or {p.name for p in native.iterdir() if p.is_file()} != {"accepted.json", "endpoint.json", "envelope.json", "failed.json"}
            or _read_object(native / "endpoint.json", "native endpoint") != prepared["endpoint"]
            or _read_object(native / "envelope.json", "native envelope") != prepared["envelope"]):
            raise CheckerEscalationError("CHECKER_ESCALATION_START_UNPROVEN", "host failure does not prove the exact unsent boundary")
        retry_root = native / "recovery" / "exact-1"
        native = retry_root / str(request["run_id"]) / str(prepared["envelope"]["message_id"])
        if (native / "started.json").is_file():
            sent = {"status": "started", "run_id": request["run_id"], "message_id": prepared["envelope"]["message_id"]}
        else:
            sent = run_json_command(list(request["transport_command"]),
                ["send", "--endpoint", str(prepared["endpoint_path"]), "--envelope", str(prepared["envelope_path"]),
                 "--attempt-root", str(retry_root)], credential=None)
    if sent.get("status") in {"started", "completed"}:
        started_path = native / "started.json"
        message_id = str(prepared["envelope"]["message_id"])
        if (sent.get("run_id") != request["run_id"] or sent.get("message_id") != message_id
            or _read_object(native / "endpoint.json", "native endpoint") != prepared["endpoint"]
            or _read_object(native / "envelope.json", "native envelope") != prepared["envelope"]):
            raise CheckerEscalationError("CHECKER_ESCALATION_START_UNPROVEN", "direct Supervisor identity differs")
        try:
            validate_native_start(started_path, adapter=str(prepared["endpoint"]["adapter"]),
                                  run_id=str(request["run_id"]), cell_id=str(request["cell_id"]),
                                  message_id=message_id, request_sha256=prepared["envelope"]["payload_sha256"])
        except NativeActivityError as exc:
            raise CheckerEscalationError("CHECKER_ESCALATION_START_UNPROVEN", "direct Supervisor start is unproven") from exc
        return _commit_started(request, prepared, started_path, message_id,
                               _sha256(native / "endpoint.json"), _sha256(native / "envelope.json"),
                               credential, run_json_command, recovered=False)
    failure_kind = sent.get("error_code")
    if sent.get("status") != "failed" or failure_kind not in {
        "CODEX_ACTIVE_WRITER_UNRESOLVED",
        "CODEX_RPC_TIMEOUT",
    }:
        raise CheckerEscalationError(
            str(failure_kind) if isinstance(failure_kind, str) and failure_kind.startswith("CODEX_") else "CHECKER_ESCALATION_DELIVERY_INVALID",
            "Supervisor delivery failed: " + str(failure_kind),
        )
    retried = run_json_command(
        list(request["transport_command"]),
        ["retry-exact", *common],
        credential=None,
    )
    retry_result = retried.get("result")
    if (
        retried.get("status") != "SUPERVISOR_DECISION_REQUIRED"
        or retried.get("reason") != "EXACT_RETRY_EXHAUSTED"
        or not isinstance(retry_result, Mapping)
        or retry_result.get("error_code") != failure_kind
    ):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_DELIVERY_INVALID", "exact Desktop writer retry is not exhausted"
        )
    desktop = dict(
        run_json_command(
            list(request["transport_command"]),
            ["prepare-desktop-current-turn", *common],
            credential=None,
        )
    )
    if (
        desktop.get("schema_version") != "slk.transport-desktop-current-turn-request/v1"
        or desktop.get("status") != "PREPARED"
        or desktop.get("run_id") != request["run_id"]
        or desktop.get("go_id") != request["go_id"]
        or desktop.get("cell_id") != request["cell_id"]
        or desktop.get("original_message_id") != prepared["envelope"]["message_id"]
        or desktop.get("target_thread_id") != prepared["endpoint"]["address"]["thread_id"]
        or desktop.get("payload_type") != prepared["envelope"]["payload_type"]
        or desktop.get("payload_sha256") != prepared["envelope"]["payload_sha256"]
        or not isinstance(desktop.get("recovery_message_id"), str)
        or not isinstance(desktop.get("prompt"), str)
        or not isinstance(desktop.get("prompt_sha256"), str)
    ):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_DESKTOP_INVALID", "Desktop bridge request changed escalation identity"
        )
    desktop.pop("_slk_command", None)
    if prepared["envelope"]["payload_type"] == "D1_INCOMPLETE_ESCALATION":
        return {
            "schema_version": "slk.checker-management-result/v1",
            "status": "DESKTOP_BRIDGE_REQUIRED",
            "run_id": request["run_id"],
            "go_id": request["go_id"],
            "cell_id": request["cell_id"],
            "attempt": request["attempt"],
            "checker_role_instance_id": request["checker_role_instance_id"],
            "supervisor_role_instance_id": prepared["endpoint"]["role_instance_id"],
            "d1_incomplete_event_id": request["d1_incomplete_event_id"],
            "candidate_message_id": prepared["envelope"]["payload"]["candidate_message_id"],
            "escalation_message_id": prepared["envelope"]["message_id"],
            "desktop_request_path": prepared["desktop_request_path"],
            "desktop_request": desktop,
        }
    return {
        "schema_version": "slk.checker-post-d1-result/v1",
        "status": "DESKTOP_BRIDGE_REQUIRED",
        "run_id": request["run_id"],
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "checker_role_instance_id": request["checker_role_instance_id"],
        "supervisor_role_instance_id": prepared["endpoint"]["role_instance_id"],
        "d1_failure_event_id": request["d1_failure_event_id"],
        "failed_candidate": prepared["failed_candidate"],
        "failed_candidate_sha256": prepared["envelope"]["payload"]["failed_candidate_sha256"],
        "escalation_message_id": prepared["envelope"]["message_id"],
        "desktop_request_path": prepared["desktop_request_path"],
        "desktop_request": desktop,
    }


def _complete(
    request: Mapping[str, Any],
    prepared: Mapping[str, Any],
    host_receipt_path: Path,
    credential: str,
    run_json_command: Callable[..., Mapping[str, Any]],
) -> dict[str, Any]:
    desktop_request_path = Path(str(prepared["desktop_request_path"]))
    desktop = _read_object(desktop_request_path, "Desktop bridge request")
    common = [
        "--endpoint",
        str(prepared["endpoint_path"]),
        "--envelope",
        str(prepared["envelope_path"]),
        "--attempt-root",
        str(prepared["attempt_root"]),
    ]
    recovered = run_json_command(
        list(request["transport_command"]),
        ["complete-desktop-current-turn", *common, "--host-receipt", str(host_receipt_path)],
        credential=None,
    )
    recovery_message_id = recovered.get("recovery_message_id")
    if (
        recovered.get("status") != "started"
        or recovered.get("recovery_of_message_id") != prepared["envelope"]["message_id"]
        or recovered.get("run_id") != request["run_id"]
        or recovered.get("payload_sha256") != prepared["envelope"]["payload_sha256"]
        or recovery_message_id != desktop.get("recovery_message_id")
        or not isinstance(recovered.get("endpoint_sha256"), str)
        or not isinstance(recovered.get("envelope_sha256"), str)
    ):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_DESKTOP_INVALID", "Desktop recovery does not prove the exact escalation"
        )
    started_path = Path(str(prepared["desktop_started_path"]))
    try:
        validate_native_start(
            started_path,
            adapter=str(prepared["endpoint"]["adapter"]),
            run_id=str(request["run_id"]),
            cell_id=str(request["cell_id"]),
            message_id=str(recovery_message_id),
            request_sha256=str(prepared["envelope"]["payload_sha256"]),
            native_request_sha256=str(desktop.get("prompt_sha256")),
        )
    except NativeActivityError as exc:
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_START_UNPROVEN", "Desktop start evidence is missing or invalid"
        ) from exc
    return _commit_started(request, prepared, started_path, str(recovery_message_id),
                           recovered["endpoint_sha256"], recovered["envelope_sha256"],
                           credential, run_json_command, recovered=True)


def _commit_started(
    request: Mapping[str, Any], prepared: Mapping[str, Any], started_path: Path, message_id: str,
    endpoint_sha256: str, envelope_sha256: str, credential: str,
    run_json_command: Callable[..., Mapping[str, Any]], *, recovered: bool,
) -> dict[str, Any]:
    try:
        native_start = validate_native_start(
            started_path, adapter=str(prepared["endpoint"]["adapter"]),
            run_id=str(request["run_id"]), cell_id=str(request["cell_id"]),
            message_id=message_id, request_sha256=str(prepared["envelope"]["payload_sha256"]),
        )
    except NativeActivityError as exc:
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_START_UNPROVEN", "Supervisor start is missing or unbound"
        ) from exc
    commit = {
        "event_id": _stable_id(request, "supervisor-transport-started"),
        "transport_receipt_id": _stable_id(request, "supervisor-transport-receipt"),
        "run_id": request["run_id"],
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "plan_revision": request["plan_revision"],
        "expected_runtime_revision": request["runtime_revision"],
        "message_id": message_id,
        "token_sequence": int(request["token_sequence"]) + 1,
        "from_role_instance_id": request["checker_role_instance_id"],
        "to_role_instance_id": prepared["endpoint"]["role_instance_id"],
        "endpoint_version": prepared["endpoint"]["endpoint_version"],
        "payload_type": prepared["envelope"]["payload_type"],
        "payload_sha256": prepared["envelope"]["payload_sha256"],
        "start_evidence": {
            "evidence_id": _stable_id(request, "supervisor-native-start"),
            "stored_path": str(started_path.resolve()),
            "sha256": _sha256(started_path),
            "message_id": message_id,
            "endpoint_sha256": endpoint_sha256,
            "envelope_sha256": envelope_sha256,
            "native_status": "STARTED",
        },
        "occurred_at": native_start["observed_at"],
    }
    commit_path = _write_stable(
        Path(str(prepared["endpoint_path"])).parent / "commit-delivery-start.json", commit
    )
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
        or recorded.get("token_owner_role_instance_id") != prepared["endpoint"]["role_instance_id"]
        or recorded.get("message_id") != message_id
    ):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_COMMIT_FAILED", "atomic TOKEN commit did not match the escalation"
        )
    _write_stable(commit_path.with_suffix(".result.json"), recorded)
    if prepared["envelope"]["payload_type"] == "D1_INCOMPLETE_ESCALATION":
        return {
            "schema_version": "slk.checker-management-result/v1",
            "status": "CHECKER_INCOMPLETE_ESCALATION_COMMITTED",
            "run_id": request["run_id"],
            "go_id": request["go_id"],
            "cell_id": request["cell_id"],
            "attempt": request["attempt"],
            "d1_incomplete_event_id": request["d1_incomplete_event_id"],
            "candidate_message_id": prepared["envelope"]["payload"]["candidate_message_id"],
            "escalation_message_id": prepared["envelope"]["message_id"],
            "recovery_message_id": message_id if recovered else None,
            "runtime_revision": recorded["runtime_revision"],
            "token_sequence": recorded["token_sequence"],
            "token_owner_role_instance_id": recorded["token_owner_role_instance_id"],
            "commit_request_path": str(commit_path),
            ("desktop_started_path" if recovered else "started_path"): str(started_path),
        }
    return {
        "schema_version": "slk.checker-post-d1-result/v1",
        "status": "CHECKER_ESCALATION_COMMITTED",
        "run_id": request["run_id"],
        "go_id": request["go_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "d1_failure_event_id": request["d1_failure_event_id"],
        "failed_candidate_sha256": prepared["envelope"]["payload"]["failed_candidate_sha256"],
        "escalation_message_id": prepared["envelope"]["message_id"],
        "recovery_message_id": message_id if recovered else None,
        "runtime_revision": recorded["runtime_revision"],
        "token_sequence": recorded["token_sequence"],
        "token_owner_role_instance_id": recorded["token_owner_role_instance_id"],
        "commit_request_path": str(commit_path),
        ("desktop_started_path" if recovered else "started_path"): str(started_path),
    }


def execute_checker_escalation(
    request: Mapping[str, Any],
    *,
    request_sha256: str,
    request_path: Path | str,
    host_receipt_path: Path | str | None = None,
    temporal: Mapping[str, Any] | None = None,
    run_json_command: Callable[..., Mapping[str, Any]] = _run_json_command,
    unprotect_credential: UnprotectCredential = unprotect_dpapi_hex,
) -> dict[str, Any]:
    """Prepare or complete one exact Checker-owned D1 failure escalation."""

    path = Path(request_path).resolve()
    if _sha256(path) != request_sha256 or _read_object(path, "post-D1 request") != dict(request):
        raise CheckerEscalationError(
            "CHECKER_ESCALATION_REQUEST_MISMATCH", "post-D1 request bytes or SHA-256 changed"
        )
    validated = _validate_request(request)
    _validate_failure(validated)
    prepared = materialize_escalation(validated)
    credential = unprotect_credential(Path(str(validated["checker_credential_path"])))
    try:
        _authenticate(validated, credential, run_json_command)
        if host_receipt_path is None:
            return _prepare(validated, prepared, run_json_command, credential, temporal)
        if temporal is not None:
            raise CheckerEscalationError("CHECKER_ESCALATION_TEMPORAL_REQUIRED", "Temporal-bound escalation cannot bypass its native ACK")
        receipt = _path(str(host_receipt_path), "host_receipt_path")
        return _complete(validated, prepared, receipt, credential, run_json_command)
    finally:
        credential = ""
