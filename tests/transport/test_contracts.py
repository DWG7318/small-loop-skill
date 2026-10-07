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
    runtime_adapter = {
        "supervisor": ("codex", "codex-app-server"),
        "checker": ("ocrv", "ocrv-checker"),
        "worker": ("dsh", "dsh-worker"),
    }
    agent_runtime, adapter = runtime_adapter[role]
    return {
        "schema_version": "slk.transport-endpoint/v1",
        "run_id": run_id,
        "role": role,
        "role_instance_id": f"{run_id}-{role}-001",
        "agent_runtime": agent_runtime,
        "adapter": adapter,
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


@pytest.mark.parametrize(
    ("sender_role", "receiver_role"),
    [
        ("supervisor", "checker"),
        ("checker", "worker"),
        ("worker", "checker"),
        ("checker", "supervisor"),
    ],
)
def test_existing_roles_keep_their_direct_transport_edges(
    sender_role: str, receiver_role: str
) -> None:
    endpoint = endpoint_value(role=receiver_role)
    envelope = envelope_value(
        sender_role=sender_role,
        receiver_role=receiver_role,
    )

    parsed = parse_delivery(endpoint, envelope)
    assert parsed.envelope.sender_role == sender_role
    assert parsed.endpoint.role == receiver_role


def test_supervisor_to_worker_requires_closed_d1_rework_directive() -> None:
    endpoint = endpoint_value(role="worker")
    envelope = envelope_value(sender_role="supervisor", receiver_role="worker")

    with pytest.raises(ContractError, match="D1_REWORK_DIRECTIVE"):
        parse_delivery(endpoint, envelope)

    payload = {
        "d1_failure_event_id": "d1-failed-001",
        "failed_candidate_sha256": "a" * 64,
        "rework_round": 1,
        "investigation_mode": "STANDARD",
        "cell_goal": "Repair the current CELL without changing its acceptance target.",
        "acceptance_criteria": ["The failed behavior is corrected."],
        "findings": ["The current candidate violates criterion one."],
        "evidence_refs": ["evidence/d1-failed-001.json"],
        "root_cause_hypothesis": "The candidate updates the wrong state boundary.",
        "minimal_experiment": "Reproduce the boundary mismatch with one focused test.",
        "minimal_repair_scope": "Correct only the current CELL state transition.",
        "regression_target": "The focused test fails before and passes after the repair.",
    }
    envelope["payload_type"] = "D1_REWORK_DIRECTIVE"
    envelope["payload"] = payload
    envelope["payload_sha256"] = payload_hash(payload)

    parsed = parse_delivery(endpoint, envelope)
    assert parsed.envelope.payload_type == "D1_REWORK_DIRECTIVE"


@pytest.mark.parametrize(
    "missing",
    [
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
    ],
)
def test_d1_rework_directive_rejects_missing_fields(missing: str) -> None:
    endpoint = endpoint_value(role="worker")
    payload = {
        "d1_failure_event_id": "d1-failed-001",
        "failed_candidate_sha256": "a" * 64,
        "rework_round": 1,
        "investigation_mode": "STANDARD",
        "cell_goal": "Repair the current CELL.",
        "acceptance_criteria": ["The failed behavior is corrected."],
        "findings": ["The candidate violates criterion one."],
        "evidence_refs": ["evidence/d1-failed-001.json"],
        "root_cause_hypothesis": "The candidate updates the wrong state boundary.",
        "minimal_experiment": "Reproduce the boundary mismatch with one focused test.",
        "minimal_repair_scope": "Correct only the current CELL state transition.",
        "regression_target": "The focused test fails before and passes after the repair.",
    }
    payload.pop(missing)
    envelope = envelope_value(sender_role="supervisor", receiver_role="worker")
    envelope["payload_type"] = "D1_REWORK_DIRECTIVE"
    envelope["payload"] = payload
    envelope["payload_sha256"] = payload_hash(payload)

    with pytest.raises(ContractError, match="rework directive"):
        parse_delivery(endpoint, envelope)


@pytest.mark.parametrize(
    "rework_round,investigation_mode",
    [(1, "AGGRESSIVE"), (2, "STANDARD"), (3, "STANDARD")],
)
def test_d1_rework_directive_requires_aggressive_investigation_after_second_failure(
    rework_round: int, investigation_mode: str
) -> None:
    endpoint = endpoint_value(role="worker")
    payload = {
        "d1_failure_event_id": "d1-failed-001",
        "failed_candidate_sha256": "a" * 64,
        "rework_round": rework_round,
        "investigation_mode": investigation_mode,
        "cell_goal": "Repair the current CELL.",
        "acceptance_criteria": ["The failed behavior is corrected."],
        "findings": ["The candidate violates criterion one."],
        "evidence_refs": ["evidence/d1-failed-001.json"],
        "root_cause_hypothesis": "The candidate updates the wrong state boundary.",
        "minimal_experiment": "Reproduce the boundary mismatch with one focused test.",
        "minimal_repair_scope": "Correct only the current CELL state transition.",
        "regression_target": "The focused regression fails before and passes after.",
    }
    envelope = envelope_value(sender_role="supervisor", receiver_role="worker")
    envelope["payload_type"] = "D1_REWORK_DIRECTIVE"
    envelope["payload"] = payload
    envelope["payload_sha256"] = payload_hash(payload)

    with pytest.raises(ContractError, match="investigation_mode"):
        parse_delivery(endpoint, envelope)


def test_d1_failure_escalation_is_closed_and_checker_owned() -> None:
    endpoint = endpoint_value(role="supervisor")
    payload = {
        "d1_failure_event_id": "d1-failed-001",
        "failed_candidate_sha256": "a" * 64,
        "rework_round": 1,
        "cell_goal": "Repair the current CELL.",
        "acceptance_criteria": ["The failed behavior is corrected."],
        "findings": ["The candidate violates criterion one."],
        "reproduction_steps": ["Run the focused regression test."],
        "expected_result": "The focused regression test passes.",
        "evidence_refs": ["evidence/d1-failed-001.json"],
    }
    envelope = envelope_value(sender_role="checker", receiver_role="supervisor")
    envelope["payload_type"] = "D1_FAILURE_ESCALATION"
    envelope["payload"] = payload
    envelope["payload_sha256"] = payload_hash(payload)
    assert parse_delivery(endpoint, envelope).envelope.payload_type == "D1_FAILURE_ESCALATION"

    wrong_owner = copy.deepcopy(envelope)
    wrong_owner["sender_role"] = "supervisor"
    wrong_owner["receiver_role"] = "worker"
    with pytest.raises(ContractError, match="checker->supervisor"):
        Envelope.from_dict(wrong_owner)

    wrong_directive_route = copy.deepcopy(envelope)
    wrong_directive_route["sender_role"] = "checker"
    wrong_directive_route["receiver_role"] = "worker"
    wrong_directive_route["payload_type"] = "D1_REWORK_DIRECTIVE"
    with pytest.raises(ContractError, match="supervisor->worker"):
        Envelope.from_dict(wrong_directive_route)

    missing = copy.deepcopy(envelope)
    del missing["payload"]["reproduction_steps"]
    missing["payload_sha256"] = payload_hash(missing["payload"])
    with pytest.raises(ContractError, match="D1 failure escalation"):
        parse_delivery(endpoint, missing)


def test_d1_incomplete_escalation_is_closed_and_checker_owned() -> None:
    endpoint = endpoint_value(role="supervisor")
    payload = {
        "d1_incomplete_event_id": "d1-incomplete-001",
        "candidate_message_id": MESSAGE_ID,
        "reason_codes": ["OCR_STATUS_NOT_COMPLETE"],
        "evidence": [{"path": "D:/run/ocrv-result.json", "sha256": "a" * 64}],
        "native_terminal_sha256": "b" * 64,
        "native_result_sha256": "c" * 64,
        "decision_required": "CAPACITY_OR_ENVIRONMENT_MANAGEMENT",
    }
    envelope = envelope_value(sender_role="checker", receiver_role="supervisor")
    envelope["payload_type"] = "D1_INCOMPLETE_ESCALATION"
    envelope["payload"] = payload
    envelope["payload_sha256"] = payload_hash(payload)
    assert parse_delivery(endpoint, envelope).envelope.payload_type == "D1_INCOMPLETE_ESCALATION"

    wrong_owner = copy.deepcopy(envelope)
    wrong_owner["sender_role"] = "supervisor"
    wrong_owner["receiver_role"] = "worker"
    with pytest.raises(ContractError, match="checker->supervisor"):
        Envelope.from_dict(wrong_owner)

    missing = copy.deepcopy(envelope)
    del missing["payload"]["decision_required"]
    missing["payload_sha256"] = payload_hash(missing["payload"])
    with pytest.raises(ContractError, match="D1 incomplete escalation"):
        parse_delivery(endpoint, missing)


def test_d2_ready_payload_is_closed_and_role_bound() -> None:
    d2_ready = {
        "d1_event_id": "d1-pass-cell-002",
        "required_cell_ids": ["CELL-001", "CELL-002"],
        "accepted_cell_ids": ["CELL-001", "CELL-002"],
        "final_candidate_message_id": MESSAGE_ID,
        "d2_criteria": ["Verify the bounded Run."],
        "evidence_refs": ["D:/run/evidence.json"],
    }
    to_supervisor = envelope_value(sender_role="checker", receiver_role="supervisor")
    to_supervisor["cell_id"] = "CELL-002"
    to_supervisor["payload_type"] = "D2_READY"
    to_supervisor["payload"] = d2_ready
    to_supervisor["payload_sha256"] = payload_hash(d2_ready)
    assert parse_delivery(endpoint_value(role="supervisor"), to_supervisor).envelope.payload_type == "D2_READY"

    missing = copy.deepcopy(to_supervisor)
    del missing["payload"]["accepted_cell_ids"]
    missing["payload_sha256"] = payload_hash(missing["payload"])
    with pytest.raises(ContractError, match="D2_READY"):
        parse_delivery(endpoint_value(role="supervisor"), missing)

    wrong_edge = copy.deepcopy(to_supervisor)
    wrong_edge["receiver_role"] = "worker"
    wrong_edge["receiver_role_instance_id"] = "RUN-A-worker-001"
    with pytest.raises(ContractError, match="checker->supervisor"):
        Envelope.from_dict(wrong_edge)


def test_worker_completion_recovery_is_closed_and_supervisor_to_checker_only() -> None:
    endpoint = endpoint_value(role="checker")
    payload = {
        "source_attempt_root": "D:/run/attempt",
        "runtime_projection_path": "D:/run/projection.json",
        "plan_revision": 1,
        "runtime_revision": 7,
        "token_sequence": 14,
        "worker_credential_path": "D:/run/worker.dpapi",
        "checker_credential_path": "D:/run/checker.dpapi",
        "state_command": ["D:/SLK/slk-state.exe"],
        "transport_command": ["python", "D:/SLK/slk-transport.pyz"],
        "occurred_at": "2026-09-23T00:00:00Z",
    }
    envelope = envelope_value(sender_role="supervisor", receiver_role="checker")
    envelope["payload_type"] = "WORKER_COMPLETION_RECOVERY"
    envelope["payload"] = payload
    envelope["payload_sha256"] = payload_hash(payload)
    assert parse_delivery(endpoint, envelope).envelope.payload_type == "WORKER_COMPLETION_RECOVERY"

    wrong_owner = copy.deepcopy(envelope)
    wrong_owner["sender_role"] = "worker"
    with pytest.raises(ContractError, match="supervisor->checker"):
        Envelope.from_dict(wrong_owner)

    extra = copy.deepcopy(envelope)
    extra["payload"]["supervisor_may_resume"] = True
    extra["payload_sha256"] = payload_hash(extra["payload"])
    with pytest.raises(ContractError, match="Worker completion recovery"):
        Envelope.from_dict(extra)


@pytest.mark.parametrize("extra_role", ["router", "overwatcher"])
def test_observation_roles_are_not_transport_relays(extra_role: str) -> None:
    endpoint = endpoint_value(role="checker")
    envelope = envelope_value(sender_role=extra_role, receiver_role="checker")

    with pytest.raises(ContractError, match="sender_role"):
        parse_delivery(endpoint, envelope)


def test_endpoint_rejects_title_matching_and_unknown_fields() -> None:
    value = endpoint_value()
    value["conversation_title"] = "SLK Checker"

    with pytest.raises(ContractError, match="unknown endpoint field"):
        Endpoint.from_dict(value)


@pytest.mark.parametrize(
    ("role", "agent_runtime", "adapter"),
    [
        ("checker", "codex", "codex-app-server"),
        ("worker", "codex", "codex-app-server"),
        ("supervisor", "ocrv", "ocrv-checker"),
        ("checker", "dsh", "dsh-worker"),
        ("worker", "ocrv", "ocrv-checker"),
    ],
)
def test_endpoint_rejects_role_runtime_adapter_substitution(
    role: str, agent_runtime: str, adapter: str
) -> None:
    value = endpoint_value(role=role)
    value["agent_runtime"] = agent_runtime
    value["adapter"] = adapter

    with pytest.raises(ContractError, match="fixed SLK role binding"):
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
