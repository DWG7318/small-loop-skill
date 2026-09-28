"""Small communication-only state used by the Temporal workflow and unit tests."""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import ContractError, DeliveryRequest, NativeStartAck


class ContinuityError(ValueError):
    """Raised when a continuity event conflicts with durable identity."""


@dataclass
class _Pending:
    delivery: DeliveryRequest
    phase: str = "DELIVERY_REQUESTED"
    delivery_result: str | None = None
    recovery_requested: bool = False
    blocked_reason: str | None = None


class RunContinuity:
    """Track only delivery, native-start acknowledgement and recovery facts."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._seen: dict[str, DeliveryRequest] = {}
        self._completed: dict[str, NativeStartAck] = {}
        self._pending: _Pending | None = None
        self._last_completed_operation_id: str | None = None
        self._recovery_request_count = 0
        self._terminal_reason: str | None = None

    def request_delivery(self, delivery: DeliveryRequest) -> str:
        if self._terminal_reason is not None:
            raise ContinuityError("Run continuity is terminal")
        if delivery.run_id != self.run_id:
            raise ContinuityError("delivery run_id does not match this Run")
        existing = self._seen.get(delivery.operation_id)
        if existing is not None:
            if existing != delivery:
                raise ContinuityError("changed duplicate delivery is forbidden")
            if delivery.operation_id in self._completed:
                return "DELIVERY_ACKNOWLEDGED"
            if self._pending is None:
                raise ContinuityError("known delivery has no pending or completed state")
            return self._pending.phase
        if self._pending is not None:
            raise ContinuityError("another delivery is unresolved")
        self._seen[delivery.operation_id] = delivery
        self._pending = _Pending(delivery)
        return self._pending.phase

    def record_delivery_result(self, operation_id: str, result: str) -> str:
        pending = self._require_pending(operation_id)
        pending.delivery_result = result
        return pending.phase

    def acknowledge(self, acknowledgement: NativeStartAck) -> str:
        completed = self._completed.get(acknowledgement.operation_id)
        if completed is not None:
            if completed != acknowledgement:
                raise ContinuityError("changed duplicate acknowledgement is forbidden")
            return "DELIVERY_ACKNOWLEDGED"
        pending = self._require_pending(acknowledgement.operation_id)
        try:
            acknowledgement.require_match(pending.delivery)
        except ContractError as error:
            raise ContinuityError(str(error)) from error
        self._completed[acknowledgement.operation_id] = acknowledgement
        self._last_completed_operation_id = acknowledgement.operation_id
        self._pending = None
        return "DELIVERY_ACKNOWLEDGED"

    def mark_timeout(self, operation_id: str) -> str:
        pending = self._require_pending(operation_id)
        if not pending.recovery_requested:
            pending.recovery_requested = True
            pending.phase = "RECOVERY_REQUIRED"
            self._recovery_request_count += 1
        return pending.phase

    def mark_blocked(self, operation_id: str, reason: str) -> str:
        pending = self._require_pending(operation_id)
        if not reason.strip():
            raise ContinuityError("blocked reason must not be blank")
        pending.blocked_reason = reason
        pending.phase = "BLOCKED"
        return pending.phase

    def terminate(self, reason: str) -> str:
        if self._pending is not None:
            raise ContinuityError("cannot terminate with an unresolved delivery")
        if not reason.strip():
            raise ContinuityError("terminal reason must not be blank")
        self._terminal_reason = reason
        return "TERMINAL"

    def snapshot(self) -> dict[str, object]:
        pending = self._pending
        return {
            "run_id": self.run_id,
            "phase": "TERMINAL" if self._terminal_reason is not None else pending.phase if pending else "IDLE",
            "pending_operation_id": pending.delivery.operation_id if pending else None,
            "last_completed_operation_id": self._last_completed_operation_id,
            "recovery_request_count": self._recovery_request_count,
            "blocked_reason": pending.blocked_reason if pending else None,
            "terminal_reason": self._terminal_reason,
        }

    def pending_delivery(self) -> DeliveryRequest | None:
        return self._pending.delivery if self._pending else None

    def is_completed(self, operation_id: str) -> bool:
        return operation_id in self._completed

    def is_terminal(self) -> bool:
        return self._terminal_reason is not None

    def _require_pending(self, operation_id: str) -> _Pending:
        if self._pending is None or self._pending.delivery.operation_id != operation_id:
            raise ContinuityError("delivery operation is not pending")
        return self._pending
