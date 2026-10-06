"""Closed data contracts for exact SLK Agent delivery."""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping, TypeAlias


Role: TypeAlias = Literal["supervisor", "checker", "worker"]
AdapterName: TypeAlias = Literal["codex-app-server", "ocrv-checker", "dsh-worker"]
JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

ENDPOINT_SCHEMA = "slk.transport-endpoint/v1"
ENVELOPE_SCHEMA = "slk.transport-envelope/v1"
RESULT_SCHEMA = "slk.transport-result/v1"

ROLES = frozenset({"supervisor", "checker", "worker"})
ADAPTERS = frozenset({"codex-app-server", "ocrv-checker", "dsh-worker"})
ROLE_RUNTIME_ADAPTER = {
    "supervisor": ("codex", "codex-app-server"),
    "checker": ("ocrv", "ocrv-checker"),
    "worker": ("dsh", "dsh-worker"),
}
ENDPOINT_STATES = frozenset({"active", "retired"})
DELIVERY_STATUSES = frozenset({"accepted", "started", "completed", "failed"})
ROLE_EDGES = frozenset(
    {
        ("supervisor", "checker"),
        ("supervisor", "worker"),
        ("checker", "worker"),
        ("worker", "checker"),
        ("checker", "supervisor"),
    }
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ContractError(ValueError):
    """Raised when a transport value violates a closed contract."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ContractError(f"{label} must be a JSON object")
    return value


def _closed(value: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    unknown = set(value) - fields
    missing = fields - set(value)
    if unknown:
        raise ContractError(f"unknown {label} field(s): {', '.join(sorted(unknown))}")
    if missing:
        raise ContractError(f"missing {label} field(s): {', '.join(sorted(missing))}")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a non-empty string")
    return value.strip()


def _identifier(value: Any, label: str) -> str:
    text = _text(value, label)
    if not IDENTIFIER.fullmatch(text):
        raise ContractError(f"{label} has an unsupported identifier shape")
    return text


def _choice(value: Any, choices: frozenset[str], label: str) -> str:
    text = _text(value, label)
    if text not in choices:
        raise ContractError(f"{label} is unsupported: {text}")
    return text


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContractError(f"{label} must be a positive integer")
    return value


def _text_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ContractError(f"{label} must be a non-empty array")
    return [_text(item, f"{label} item") for item in value]


def _d1_rework_directive(value: Mapping[str, Any]) -> None:
    fields = frozenset(
        {
            "d1_failure_event_id",
            "failed_candidate_sha256",
            "rework_round",
            "investigation_mode",
            "cell_goal",
            "acceptance_criteria",
            "findings",
            "evidence_refs",
            "root_cause_hypothesis",
            "minimal_experiment",
            "minimal_repair_scope",
            "regression_target",
        }
    )
    _closed(value, fields, "rework directive")
    _identifier(value["d1_failure_event_id"], "d1_failure_event_id")
    failed_candidate = _text(value["failed_candidate_sha256"], "failed_candidate_sha256")
    if not SHA256.fullmatch(failed_candidate):
        raise ContractError("failed_candidate_sha256 must be 64 lowercase hexadecimal characters")
    rework_round = _positive_int(value["rework_round"], "rework_round")
    investigation_mode = _choice(
        value["investigation_mode"],
        frozenset({"STANDARD", "AGGRESSIVE"}),
        "investigation_mode",
    )
    expected_mode = "STANDARD" if rework_round == 1 else "AGGRESSIVE"
    if investigation_mode != expected_mode:
        raise ContractError(
            f"rework round {rework_round} requires investigation_mode={expected_mode}"
        )
    _text(value["cell_goal"], "cell_goal")
    for field in ("acceptance_criteria", "findings", "evidence_refs"):
        _text_list(value[field], field)
    for field in (
        "root_cause_hypothesis",
        "minimal_experiment",
        "minimal_repair_scope",
        "regression_target",
    ):
        _text(value[field], field)


def _d1_failure_escalation(value: Mapping[str, Any]) -> None:
    fields = frozenset(
        {
            "d1_failure_event_id",
            "failed_candidate_sha256",
            "rework_round",
            "cell_goal",
            "acceptance_criteria",
            "findings",
            "reproduction_steps",
            "expected_result",
            "evidence_refs",
        }
    )
    _closed(value, fields, "D1 failure escalation")
    _identifier(value["d1_failure_event_id"], "d1_failure_event_id")
    failed_candidate = _text(value["failed_candidate_sha256"], "failed_candidate_sha256")
    if not SHA256.fullmatch(failed_candidate):
        raise ContractError("failed_candidate_sha256 must be 64 lowercase hexadecimal characters")
    _positive_int(value["rework_round"], "rework_round")
    _text(value["cell_goal"], "cell_goal")
    _text(value["expected_result"], "expected_result")
    for field in ("acceptance_criteria", "findings", "reproduction_steps", "evidence_refs"):
        _text_list(value[field], field)


def _d2_ready(value: Mapping[str, Any]) -> None:
    fields = frozenset(
        {
            "d1_event_id", "required_cell_ids", "accepted_cell_ids",
            "final_candidate_message_id", "d2_criteria", "evidence_refs",
        }
    )
    _closed(value, fields, "D2_READY")
    _identifier(value["d1_event_id"], "d1_event_id")
    _text(value["final_candidate_message_id"], "final_candidate_message_id")
    required = _text_list(value["required_cell_ids"], "required_cell_ids")
    accepted = _text_list(value["accepted_cell_ids"], "accepted_cell_ids")
    if required != accepted or len(required) != len(set(required)):
        raise ContractError("D2_READY accepted_cell_ids must exactly match unique required_cell_ids")
    _text_list(value["d2_criteria"], "d2_criteria")
    _text_list(value["evidence_refs"], "evidence_refs")


def _worker_completion_recovery(value: Mapping[str, Any]) -> None:
    fields = frozenset(
        {
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
        }
    )
    _closed(value, fields, "Worker completion recovery")
    for field in (
        "source_attempt_root",
        "runtime_projection_path",
        "worker_credential_path",
        "checker_credential_path",
        "occurred_at",
    ):
        _text(value[field], field)
    for field in ("plan_revision", "runtime_revision", "token_sequence"):
        _positive_int(value[field], field)
    for field in ("state_command", "transport_command"):
        _text_list(value[field], field)


def _pre_d0_blocked_recovery(value: Mapping[str, Any]) -> None:
    fields = frozenset(
        {
            "source_attempt_root",
            "runtime_projection_path",
            "plan_revision",
            "runtime_revision",
            "token_sequence",
            "worker_credential_path",
            "checker_credential_path",
            "state_command",
            "transport_command",
            "environment_adjustment_path",
            "environment_adjustment_sha256",
            "occurred_at",
        }
    )
    _closed(value, fields, "pre-D0 blocked recovery")
    for field in (
        "source_attempt_root",
        "runtime_projection_path",
        "worker_credential_path",
        "checker_credential_path",
        "environment_adjustment_path",
        "occurred_at",
    ):
        _text(value[field], field)
    digest = _text(value["environment_adjustment_sha256"], "environment_adjustment_sha256")
    if not SHA256.fullmatch(digest):
        raise ContractError("environment_adjustment_sha256 must be 64 lowercase hexadecimal characters")
    for field in ("plan_revision", "runtime_revision", "token_sequence"):
        _positive_int(value[field], field)
    for field in ("state_command", "transport_command"):
        _text_list(value[field], field)


def _json(value: Any, label: str) -> JsonValue:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError(f"{label} must contain finite JSON numbers")
        return value
    if isinstance(value, list):
        return [_json(item, f"{label} item") for item in value]
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        return {key: _json(item, f"{label}.{key}") for key, item in value.items()}
    raise ContractError(f"{label} must contain only JSON values")


def canonical_json_sha256(value: Mapping[str, JsonValue]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class Endpoint:
    schema_version: str
    run_id: str
    role: Role
    role_instance_id: str
    agent_runtime: str
    adapter: AdapterName
    host_id: str
    endpoint_version: int
    state: Literal["active", "retired"]
    address: Mapping[str, JsonValue]

    FIELDS = frozenset(
        {
            "schema_version",
            "run_id",
            "role",
            "role_instance_id",
            "agent_runtime",
            "adapter",
            "host_id",
            "endpoint_version",
            "state",
            "address",
        }
    )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Endpoint":
        value = _mapping(raw, "endpoint")
        _closed(value, cls.FIELDS, "endpoint")
        if value["schema_version"] != ENDPOINT_SCHEMA:
            raise ContractError(f"schema_version must be {ENDPOINT_SCHEMA}")
        address = _json(_mapping(value["address"], "address"), "address")
        if not address:
            raise ContractError("address must not be empty")
        role = _choice(value["role"], ROLES, "role")
        agent_runtime = _identifier(value["agent_runtime"], "agent_runtime")
        adapter = _choice(value["adapter"], ADAPTERS, "adapter")
        if (agent_runtime, adapter) != ROLE_RUNTIME_ADAPTER[role]:
            raise ContractError(
                f"fixed SLK role binding mismatch for {role}: {agent_runtime}/{adapter}"
            )
        return cls(
            schema_version=ENDPOINT_SCHEMA,
            run_id=_identifier(value["run_id"], "run_id"),
            role=role,  # type: ignore[arg-type]
            role_instance_id=_identifier(value["role_instance_id"], "role_instance_id"),
            agent_runtime=agent_runtime,
            adapter=adapter,  # type: ignore[arg-type]
            host_id=_identifier(value["host_id"], "host_id"),
            endpoint_version=_positive_int(value["endpoint_version"], "endpoint_version"),
            state=_choice(value["state"], ENDPOINT_STATES, "state"),  # type: ignore[arg-type]
            address=address,
        )


@dataclass(frozen=True)
class Envelope:
    schema_version: str
    message_id: str
    token_sequence: int
    run_id: str
    go_id: str
    cell_id: str
    sender_role: Role
    sender_role_instance_id: str
    receiver_role: Role
    receiver_role_instance_id: str
    receiver_endpoint_version: int
    payload_type: str
    payload_sha256: str
    payload: Mapping[str, JsonValue]

    FIELDS = frozenset(
        {
            "schema_version",
            "message_id",
            "token_sequence",
            "run_id",
            "go_id",
            "cell_id",
            "sender_role",
            "sender_role_instance_id",
            "receiver_role",
            "receiver_role_instance_id",
            "receiver_endpoint_version",
            "payload_type",
            "payload_sha256",
            "payload",
        }
    )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Envelope":
        value = _mapping(raw, "envelope")
        _closed(value, cls.FIELDS, "envelope")
        if value["schema_version"] != ENVELOPE_SCHEMA:
            raise ContractError(f"schema_version must be {ENVELOPE_SCHEMA}")
        message_id = _text(value["message_id"], "message_id")
        try:
            parsed_message_id = uuid.UUID(message_id)
        except (ValueError, AttributeError) as exc:
            raise ContractError("message_id must be a canonical UUID") from exc
        if str(parsed_message_id) != message_id:
            raise ContractError("message_id must be a canonical UUID")
        sender_role = _choice(value["sender_role"], ROLES, "sender_role")
        receiver_role = _choice(value["receiver_role"], ROLES, "receiver_role")
        if (sender_role, receiver_role) not in ROLE_EDGES:
            raise ContractError(f"unsupported role edge: {sender_role}->{receiver_role}")
        payload_type = _identifier(value["payload_type"], "payload_type")
        payload = _json(_mapping(value["payload"], "payload"), "payload")
        if payload_type == "D1_FAILURE_ESCALATION":
            if (sender_role, receiver_role) != ("checker", "supervisor"):
                raise ContractError("D1_FAILURE_ESCALATION requires checker->supervisor")
            _d1_failure_escalation(payload)
        if payload_type == "D1_REWORK_DIRECTIVE":
            if (sender_role, receiver_role) != ("supervisor", "worker"):
                raise ContractError("D1_REWORK_DIRECTIVE requires supervisor->worker")
            _d1_rework_directive(payload)
        elif payload_type == "WORKER_COMPLETION_RECOVERY":
            if (sender_role, receiver_role) != ("supervisor", "checker"):
                raise ContractError("WORKER_COMPLETION_RECOVERY requires supervisor->checker")
            _worker_completion_recovery(payload)
        elif payload_type == "PRE_D0_BLOCKED_RECOVERY":
            if (sender_role, receiver_role) != ("supervisor", "checker"):
                raise ContractError("PRE_D0_BLOCKED_RECOVERY requires supervisor->checker")
            _pre_d0_blocked_recovery(payload)
        elif payload_type == "D2_READY":
            if (sender_role, receiver_role) != ("checker", "supervisor"):
                raise ContractError("D2_READY requires checker->supervisor")
            _d2_ready(payload)
        elif (sender_role, receiver_role) == ("supervisor", "worker"):
            raise ContractError("supervisor->worker is limited to D1_REWORK_DIRECTIVE")
        payload_sha256 = _text(value["payload_sha256"], "payload_sha256")
        if not SHA256.fullmatch(payload_sha256):
            raise ContractError("payload_sha256 must be 64 lowercase hexadecimal characters")
        if canonical_json_sha256(payload) != payload_sha256:
            raise ContractError("payload_sha256 does not match payload")
        return cls(
            schema_version=ENVELOPE_SCHEMA,
            message_id=message_id,
            token_sequence=_positive_int(value["token_sequence"], "token_sequence"),
            run_id=_identifier(value["run_id"], "run_id"),
            go_id=_identifier(value["go_id"], "go_id"),
            cell_id=_identifier(value["cell_id"], "cell_id"),
            sender_role=sender_role,  # type: ignore[arg-type]
            sender_role_instance_id=_identifier(
                value["sender_role_instance_id"], "sender_role_instance_id"
            ),
            receiver_role=receiver_role,  # type: ignore[arg-type]
            receiver_role_instance_id=_identifier(
                value["receiver_role_instance_id"], "receiver_role_instance_id"
            ),
            receiver_endpoint_version=_positive_int(
                value["receiver_endpoint_version"], "receiver_endpoint_version"
            ),
            payload_type=payload_type,
            payload_sha256=payload_sha256,
            payload=payload,
        )


@dataclass(frozen=True)
class ParsedDelivery:
    endpoint: Endpoint
    envelope: Envelope


@dataclass(frozen=True)
class DeliveryResult:
    schema_version: str
    message_id: str
    run_id: str
    adapter: str
    status: Literal["accepted", "started", "completed", "failed"]
    native_identity: Mapping[str, JsonValue]
    error_code: str | None
    evidence: tuple[str, ...]

    FIELDS = frozenset(
        {
            "schema_version",
            "message_id",
            "run_id",
            "adapter",
            "status",
            "native_identity",
            "error_code",
            "evidence",
        }
    )

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DeliveryResult":
        value = _mapping(raw, "delivery result")
        _closed(value, cls.FIELDS, "delivery result")
        if value["schema_version"] != RESULT_SCHEMA:
            raise ContractError(f"schema_version must be {RESULT_SCHEMA}")
        message_id = _text(value["message_id"], "message_id")
        try:
            parsed_message_id = uuid.UUID(message_id)
        except (ValueError, AttributeError) as exc:
            raise ContractError("message_id must be a canonical UUID") from exc
        if str(parsed_message_id) != message_id:
            raise ContractError("message_id must be a canonical UUID")
        error_code = value["error_code"]
        if error_code is not None:
            error_code = _identifier(error_code, "error_code")
        evidence = value["evidence"]
        if not isinstance(evidence, list) or not all(isinstance(item, str) and item for item in evidence):
            raise ContractError("evidence must be an array of non-empty strings")
        native_identity = _json(
            _mapping(value["native_identity"], "native_identity"),
            "native_identity",
        )
        return cls(
            schema_version=RESULT_SCHEMA,
            message_id=message_id,
            run_id=_identifier(value["run_id"], "run_id"),
            adapter=_choice(value["adapter"], ADAPTERS, "adapter"),
            status=_choice(value["status"], DELIVERY_STATUSES, "status"),  # type: ignore[arg-type]
            native_identity=native_identity,
            error_code=error_code,
            evidence=tuple(evidence),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["evidence"] = list(self.evidence)
        return value


def parse_delivery(endpoint_raw: Mapping[str, Any], envelope_raw: Mapping[str, Any]) -> ParsedDelivery:
    endpoint = Endpoint.from_dict(endpoint_raw)
    envelope = Envelope.from_dict(envelope_raw)
    if endpoint.state != "active":
        raise ContractError("receiver endpoint is retired")
    if endpoint.run_id != envelope.run_id:
        raise ContractError("endpoint run_id does not match envelope run_id")
    if endpoint.role != envelope.receiver_role:
        raise ContractError("endpoint role does not match receiver_role")
    if endpoint.role_instance_id != envelope.receiver_role_instance_id:
        raise ContractError("endpoint role_instance_id does not match receiver_role_instance_id")
    if endpoint.endpoint_version != envelope.receiver_endpoint_version:
        raise ContractError("endpoint_version does not match receiver_endpoint_version")
    return ParsedDelivery(endpoint=endpoint, envelope=envelope)
