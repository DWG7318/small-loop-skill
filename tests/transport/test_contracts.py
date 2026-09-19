from __future__ import annotations

import copy
import hashlib
import json
import uuid

import pytest

from slk_transport.contracts import ContractError, Endpoint, Envelope, parse_delivery


MESSAGE_ID = str(uuid.UUID("11111111-1111-4111-8111-111111111111"))


def payload_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def endpoint_value(
    *,
    role: str = "checker",
    run_id: str = "RUN-A",
    version: int = 2,
    state: str = "active",
) -> dict[str, object]:
    return {
        "schema_version": "slk.transport-endpoint/v1",
        "run_id": run_id,
        "role": role,
        "role_instance_id": f"{run_id}-{role}-001",
        "agent_runtime": "ocrv" if role == "checker" else "codex",
        "adapter": "ocrv-checker" if role == "checker" else "codex-app-server",
        "host_id": "local",
        "endpoint_version": version,
        "state": state,
        "address": {"launcher": "D:/OCRV/slk-checker.cmd"},
    }


def envelope_value(
    *,
    run_id: str = "RUN-A",
    sender_role: str = "supervisor",
    receiver_role: str = "checker",
    receiver_endpoint_version: int = 2,
) -> dict[str, object]:
    payload: dict[str, object] = {"probe_nonce": "A-001"}
    return {
        "schema_version": "slk.transport-envelope/v1",
        "message_id": MESSAGE_ID,
        "token_sequence": 1,
        "run_id": run_id,
        "go_id": "GO-001",
        "cell_id": "CELL-001",
        "sender_role": sender_role,
        "sender_role_instance_id": f"{run_id}-{sender_role}-001",
        "receiver_role": receiver_role,
        "receiver_role_instance_id": f"{run_id}-{receiver_role}-001",
        "receiver_endpoint_version": receiver_endpoint_version,
        "payload_type": "TRANSPORT_PROBE",
        "payload_sha256": payload_hash(payload),
        "payload": payload,
    }


def test_envelope_requires_exact_role_edge_and_payload_hash() -> None:
    endpoint = endpoint_value()
    envelope = envelope_value()

    parsed = parse_delivery(endpoint, envelope)

    assert parsed.endpoint.role_instance_id == "RUN-A-checker-001"
    assert parsed.envelope.receiver_role_instance_id == "RUN-A-checker-001"

    drifted = copy.deepcopy(envelope)
    drifted["payload_sha256"] = "0" * 64
    with pytest.raises(ContractError, match="payload_sha256"):
        parse_delivery(endpoint, drifted)


def test_endpoint_rejects_title_matching_and_unknown_fields() -> None:
    value = endpoint_value()
    value["conversation_title"] = "SLK Checker"

    with pytest.raises(ContractError, match="unknown endpoint field"):
        Endpoint.from_dict(value)


@pytest.mark.parametrize(
    ("mutate_endpoint", "mutate_envelope", "message"),
    [
        (lambda value: value.update(run_id="RUN-B"), lambda value: None, "run_id"),
        (lambda value: value.update(state="retired"), lambda value: None, "retired"),
        (lambda value: None, lambda value: value.update(receiver_endpoint_version=3), "endpoint_version"),
        (lambda value: None, lambda value: value.update(receiver_role_instance_id="RUN-A-checker-999"), "role_instance_id"),
        (lambda value: None, lambda value: value.update(sender_role="checker"), "role edge"),
    ],
)
def test_delivery_rejects_identity_and_route_mismatch(
    mutate_endpoint,
    mutate_envelope,
    message: str,
) -> None:
    endpoint = endpoint_value()
    envelope = envelope_value()
    mutate_endpoint(endpoint)
    mutate_envelope(envelope)

    with pytest.raises(ContractError, match=message):
        parse_delivery(endpoint, envelope)


def test_envelope_rejects_unknown_fields_and_invalid_json_values() -> None:
    unknown = envelope_value()
    unknown["delivery_hint"] = "title-search"
    with pytest.raises(ContractError, match="unknown envelope field"):
        Envelope.from_dict(unknown)

    invalid_json = envelope_value()
    invalid_json["payload"] = {"bad": object()}
    invalid_json["payload_sha256"] = "0" * 64
    with pytest.raises(ContractError, match="JSON"):
        Envelope.from_dict(invalid_json)


@pytest.mark.parametrize("sequence", [0, -1, True])
def test_token_sequence_is_a_positive_integer(sequence: object) -> None:
    envelope = envelope_value()
    envelope["token_sequence"] = sequence

    with pytest.raises(ContractError, match="token_sequence"):
        Envelope.from_dict(envelope)


def test_message_id_must_be_a_canonical_uuid() -> None:
    envelope = envelope_value()
    envelope["message_id"] = "message-one"

    with pytest.raises(ContractError, match="message_id"):
        Envelope.from_dict(envelope)
