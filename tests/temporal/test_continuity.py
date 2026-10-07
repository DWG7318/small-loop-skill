from __future__ import annotations

import pytest

from slk_temporal.continuity import ContinuityError, RunContinuity
from slk_temporal.contracts import DeliveryRequest, NativeStartAck, PreStartRejection

from .test_contracts import ack_value, delivery_value, pre_start_rejection_value


def request() -> DeliveryRequest:
    return DeliveryRequest.from_dict(delivery_value())


def ack() -> NativeStartAck:
    return NativeStartAck.from_dict(ack_value())


def test_delivery_needs_matching_native_start_ack() -> None:
    state = RunContinuity("RUN-A")
    assert state.request_delivery(request()) == "DELIVERY_REQUESTED"
    assert state.record_delivery_result(request().operation_id, "COMPLETED") == "DELIVERY_REQUESTED"
    assert state.snapshot()["phase"] == "DELIVERY_REQUESTED"

    assert state.acknowledge(ack()) == "DELIVERY_ACKNOWLEDGED"
    assert state.snapshot()["phase"] == "IDLE"
    assert state.snapshot()["last_completed_operation_id"] == request().operation_id


def test_duplicate_is_idempotent_but_changed_duplicate_is_rejected() -> None:
    state = RunContinuity("RUN-A")
    assert state.request_delivery(request()) == "DELIVERY_REQUESTED"
    assert state.request_delivery(request()) == "DELIVERY_REQUESTED"
    changed = delivery_value()
    changed["payload_sha256"] = "c" * 64
    with pytest.raises(ContinuityError, match="changed duplicate"):
        state.request_delivery(DeliveryRequest.from_dict(changed))

    state.acknowledge(ack())
    assert state.acknowledge(ack()) == "DELIVERY_ACKNOWLEDGED"


def test_timeout_requests_one_recovery_and_ack_stops_escalation() -> None:
    state = RunContinuity("RUN-A")
    state.request_delivery(request())
    assert state.mark_timeout(request().operation_id) == "RECOVERY_REQUIRED"
    assert state.mark_timeout(request().operation_id) == "RECOVERY_REQUIRED"
    assert state.snapshot()["recovery_request_count"] == 1

    assert state.acknowledge(ack()) == "DELIVERY_ACKNOWLEDGED"
    with pytest.raises(ContinuityError, match="not pending"):
        state.mark_blocked(request().operation_id, "late failure")


def test_unrecoverable_delivery_remains_truthfully_blocked() -> None:
    state = RunContinuity("RUN-A")
    state.request_delivery(request())
    state.mark_timeout(request().operation_id)
    assert state.mark_blocked(request().operation_id, "no verified continuation route") == "BLOCKED"
    snapshot = state.snapshot()
    assert snapshot["phase"] == "BLOCKED"
    assert snapshot["blocked_reason"] == "no verified continuation route"
    with pytest.raises(ContinuityError, match="unresolved delivery"):
        state.terminate("RUN_CLOSED")


def test_exact_failed_pre_start_rejection_is_abandoned_without_forging_ack() -> None:
    state = RunContinuity("RUN-A")
    state.request_delivery(request())
    state.record_delivery_result(request().operation_id, "FAILED")
    rejection = PreStartRejection.from_dict(pre_start_rejection_value())

    assert state.abandon_pre_start(rejection) == "PRE_START_REJECTION_ABANDONED"
    snapshot = state.snapshot()
    assert snapshot["phase"] == "IDLE"
    assert snapshot["last_completed_operation_id"] is None
    assert snapshot["last_abandoned_operation_id"] == request().operation_id
    assert state.request_delivery(request()) == "PRE_START_REJECTION_ABANDONED"

    replacement = delivery_value()
    replacement["operation_id"] = "delivery-RUN-A-CELL-001-a2"
    replacement["message_id"] = "message-b"
    assert state.request_delivery(DeliveryRequest.from_dict(replacement)) == "DELIVERY_REQUESTED"


def test_exact_historical_activity_error_can_use_same_proven_pre_start_rejection() -> None:
    state = RunContinuity("RUN-A")
    state.request_delivery(request())
    state.record_delivery_result(request().operation_id, "TOOL_ERROR:ActivityError")
    assert state.abandon_pre_start(
        PreStartRejection.from_dict(pre_start_rejection_value())
    ) == "PRE_START_REJECTION_ABANDONED"


@pytest.mark.parametrize("delivery_result", [None, "DELIVERED", "TOOL_ERROR:RuntimeError"])
def test_pre_start_abandonment_rejects_unproved_or_ambiguous_native_state(delivery_result) -> None:
    state = RunContinuity("RUN-A")
    state.request_delivery(request())
    if delivery_result is not None:
        state.record_delivery_result(request().operation_id, delivery_result)
    with pytest.raises(ContinuityError, match="proven pre-start"):
        state.abandon_pre_start(PreStartRejection.from_dict(pre_start_rejection_value()))


def test_scope_and_run_identity_cannot_change() -> None:
    state = RunContinuity("RUN-A")
    wrong_run = delivery_value()
    wrong_run["run_id"] = "RUN-B"
    with pytest.raises(ContinuityError, match="run_id"):
        state.request_delivery(DeliveryRequest.from_dict(wrong_run))

    state.request_delivery(request())
    changed_ack = ack_value()
    changed_ack["receiver_role_instance_id"] = "supervisor-a"
    with pytest.raises(ContinuityError, match="does not match"):
        state.acknowledge(NativeStartAck.from_dict(changed_ack))


def test_terminal_close_requires_no_pending_delivery() -> None:
    state = RunContinuity("RUN-A")
    state.request_delivery(request())
    with pytest.raises(ContinuityError, match="unresolved delivery"):
        state.terminate("RUN_CLOSED")
    state.acknowledge(ack())
    assert state.terminate("RUN_CLOSED") == "TERMINAL"
    with pytest.raises(ContinuityError, match="terminal"):
        state.request_delivery(request())
