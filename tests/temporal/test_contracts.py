from __future__ import annotations

import copy
import hashlib
import json

import pytest

from slk_temporal.contracts import (
    ContractError,
    DeliveryRequest,
    NativeStartAck,
    OverwatcherExitNotice,
    RuntimeGuardResolution,
    StartSlkRequest,
    notification_native_id,
    validate_supervisor_notification,
)


def notification_value(event_id="notice-a", run_id="RUN-A"):
    value = {"status": "NOTIFIED", "event_id": event_id, "supervisor_role_instance_id": "supervisor-a",
        "native_start": {"schema_version": "slk.native-start/v2", "status": "STARTED", "adapter": "codex-app-server",
            "run_id": run_id, "cell_id": "PREPARATION", "message_id": notification_native_id(run_id, event_id),
            "request_sha256": "a" * 64, "native_request_sha256": "b" * 64, "observed_at": "2026-10-05T00:00:00Z",
            "process": {"pid": 1, "creation_time": "fixture-only:1"},
            "native_task": {"kind": "codex-desktop-turn", "id": "fixture-thread:turn:item", "status": "RUNNING"}}}
    value["receipt_sha256"] = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return value


def test_native_supervisor_notification_contract():
    validate_supervisor_notification(notification_value(), run_id="RUN-A", event_id="notice-a", supervisor_role_instance_id="supervisor-a")


@pytest.mark.parametrize("damage", ["other-run", "other-supervisor", "other-message", "hash-only", "legacy-native", "boolean-pid", "changed-receipt"])
def test_native_supervisor_notification_rejects_wrong_or_missing_proof(damage):
    value = notification_value()
    if damage == "other-run": value["native_start"]["run_id"] = "OTHER-RUN"
    if damage == "other-supervisor": value["supervisor_role_instance_id"] = "ow-a"
    if damage == "other-message": value["native_start"]["message_id"] = "another-message"
    if damage == "hash-only": value.pop("native_start")
    if damage == "legacy-native": value["native_start"]["schema_version"] = "slk.native-start/v1"
    if damage == "boolean-pid": value["native_start"]["process"]["pid"] = True
    if damage == "changed-receipt": value["receipt_sha256"] = "c" * 64
    with pytest.raises(ContractError):
        validate_supervisor_notification(value, run_id="RUN-A", event_id="notice-a", supervisor_role_instance_id="supervisor-a")


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
        "method_version": "4.4.0",
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


def overwatcher_exit_value() -> dict[str, object]:
    return {
        "event_id": "overwatcher-exit-a",
        "run_id": "RUN-A",
        "overwatcher_role_instance_id": "overwatcher-a",
        "requested_by_role_instance_id": "supervisor-a",
        "evidence_sha256": "c" * 64,
    }


def runtime_guard_resolution_value() -> dict[str, object]:
    return {
        "event_id": "runtime-guard-resolution-a",
        "run_id": "RUN-A",
        "supervisor_role_instance_id": "supervisor-a",
        "blocker_event_id": "overwatcher-exit-a",
        "resolution": "OVERWATCHER_RESTORED",
        "evidence_sha256": "d" * 64,
    }


@pytest.mark.parametrize("version", ["4.4.0", "4.4.1"])
def test_compatible_start_preserves_original_method_version(version):
    value = start_value()
    value["method_version"] = version
    parsed = StartSlkRequest.from_dict(value)
    assert parsed.method_version == version
    assert parsed.to_dict()["method_version"] == version


def test_start_contract_is_closed_and_has_exact_role_topology() -> None:
    request = StartSlkRequest.from_dict(start_value())
    assert request.run_id == "RUN-A"
    assert request.overwatcher is not None
    assert len(request.startup_fingerprint) == 64
    assert StartSlkRequest.from_dict(request.to_dict()) == request

    with pytest.raises(ContractError, match="exactly one SUPERVISOR, CHECKER, WORKER and OVERWATCHER"):
        StartSlkRequest.from_dict(start_value(overwatcher=False))

    extra = start_value()
    extra["unexpected"] = True
    with pytest.raises(ContractError, match="exact field set"):
        StartSlkRequest.from_dict(extra)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (lambda value: value["roles"].pop(2), "exactly one SUPERVISOR, CHECKER, WORKER and OVERWATCHER"),
        (
            lambda value: value["roles"].append(copy.deepcopy(value["roles"][2])),
            "exactly one SUPERVISOR, CHECKER, WORKER and OVERWATCHER",
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


def test_overwatcher_exit_and_supervisor_repair_contracts_are_closed() -> None:
    exit_notice = OverwatcherExitNotice.from_dict(overwatcher_exit_value())
    resolution = RuntimeGuardResolution.from_dict(runtime_guard_resolution_value())
    assert exit_notice.overwatcher_role_instance_id == "overwatcher-a"
    assert resolution.supervisor_role_instance_id == "supervisor-a"

    missing = overwatcher_exit_value()
    missing.pop("evidence_sha256")
    with pytest.raises(ContractError, match="exact field set"):
        OverwatcherExitNotice.from_dict(missing)

    wrong = runtime_guard_resolution_value()
    wrong["resolution"] = "SUPERVISOR_APPROVED_STOP"
    with pytest.raises(ContractError, match="OVERWATCHER_RESTORED"):
        RuntimeGuardResolution.from_dict(wrong)
