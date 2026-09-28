from __future__ import annotations

import copy

import pytest

from slk_temporal.contracts import ContractError, DeliveryRequest, NativeStartAck, StartSlkRequest


def start_value(*, overwatcher: bool = True) -> dict[str, object]:
    roles: list[dict[str, str]] = [
        {
            "role": "SUPERVISOR",
            "role_instance_id": "supervisor-a",
            "endpoint_ref": "endpoint-supervisor-a-v1",
        },
        {
            "role": "CHECKER",
            "role_instance_id": "checker-a",
            "endpoint_ref": "endpoint-checker-a-v1",
        },
        {
            "role": "WORKER",
            "role_instance_id": "worker-a",
            "endpoint_ref": "endpoint-worker-a-v1",
        },
    ]
    if overwatcher:
        roles.append(
            {
                "role": "OVERWATCHER",
                "role_instance_id": "overwatcher-a",
                "endpoint_ref": "endpoint-overwatcher-a-v1",
            }
        )
    return {
        "run_id": "RUN-A",
        "method_version": "4.3.0",
        "runtime_revision": 7,
        "task_queue": "slk-local",
        "ack_timeout_seconds": 120,
        "startup_idempotency_key": "start-RUN-A-v7",
        "roles": roles,
    }


def delivery_value() -> dict[str, object]:
    return {
        "operation_id": "delivery-RUN-A-CELL-001-a1",
        "run_id": "RUN-A",
        "cell_id": "CELL-001",
        "attempt": 1,
        "message_id": "message-a",
        "sender_role_instance_id": "worker-a",
        "receiver_role_instance_id": "checker-a",
        "payload_sha256": "a" * 64,
        "source_runtime_revision": 8,
    }


def ack_value() -> dict[str, object]:
    return {
        "operation_id": "delivery-RUN-A-CELL-001-a1",
        "message_id": "message-a",
        "receiver_role_instance_id": "checker-a",
        "payload_sha256": "a" * 64,
        "started_receipt_sha256": "b" * 64,
    }


def test_start_contract_is_closed_and_has_exact_role_topology() -> None:
    request = StartSlkRequest.from_dict(start_value())
    assert request.run_id == "RUN-A"
    assert request.overwatcher is not None
    assert len(request.startup_fingerprint) == 64
    assert StartSlkRequest.from_dict(request.to_dict()) == request

    without_overwatcher = StartSlkRequest.from_dict(start_value(overwatcher=False))
    assert without_overwatcher.overwatcher is None

    extra = start_value()
    extra["unexpected"] = True
    with pytest.raises(ContractError, match="exact field set"):
        StartSlkRequest.from_dict(extra)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda value: value["roles"].pop(2), "exactly one SUPERVISOR, CHECKER and WORKER"),
        (
            lambda value: value["roles"].append(copy.deepcopy(value["roles"][2])),
            "exactly one SUPERVISOR, CHECKER and WORKER",
        ),
        (
            lambda value: value["roles"][1].update(
                {"role_instance_id": value["roles"][0]["role_instance_id"]}
            ),
            "role_instance_id must be unique",
        ),
        (lambda value: value.update({"run_id": " RUN-A"}), "canonical identifier"),
        (lambda value: value.update({"runtime_revision": True}), "runtime_revision"),
        (lambda value: value.update({"ack_timeout_seconds": 0}), "ack_timeout_seconds"),
        (lambda value: value.update({"method_version": "4.2.11"}), "method_version"),
    ],
)
def test_start_contract_fails_closed(mutate, match: str) -> None:
    value = start_value()
    mutate(value)
    with pytest.raises(ContractError, match=match):
        StartSlkRequest.from_dict(value)


def test_delivery_and_ack_contracts_bind_exact_identity() -> None:
    delivery = DeliveryRequest.from_dict(delivery_value())
    ack = NativeStartAck.from_dict(ack_value())
    ack.require_match(delivery)
    assert DeliveryRequest.from_dict(delivery.to_dict()) == delivery
    assert NativeStartAck.from_dict(ack.to_dict()) == ack

    changed = ack_value()
    changed["payload_sha256"] = "c" * 64
    with pytest.raises(ContractError, match="does not match"):
        NativeStartAck.from_dict(changed).require_match(delivery)


@pytest.mark.parametrize(
    "factory,value,match",
    [
        (DeliveryRequest.from_dict, {**delivery_value(), "attempt": False}, "attempt"),
        (DeliveryRequest.from_dict, {**delivery_value(), "payload_sha256": "abc"}, "SHA-256"),
        (
            NativeStartAck.from_dict,
            {**ack_value(), "started_receipt_sha256": "z" * 64},
            "SHA-256",
        ),
    ],
)
def test_runtime_contract_numbers_and_hashes_fail_closed(factory, value, match: str) -> None:
    with pytest.raises(ContractError, match=match):
        factory(value)
