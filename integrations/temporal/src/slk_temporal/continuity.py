"""Small communication-only state used by the Temporal workflow and unit tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .contracts import ContractError, DeliveryRequest, NativeStartAck, PreStartRejection


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
        self._abandoned: dict[str, PreStartRejection] = {}
        self._pending: _Pending | None = None
        self._last_completed_operation_id: str | None = None
        self._last_abandoned_operation_id: str | None = None
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
            if delivery.operation_id in self._abandoned:
                return "PRE_START_REJECTION_ABANDONED"
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

    def abandon_pre_start(self, rejection: PreStartRejection) -> str:
        abandoned = self._abandoned.get(rejection.operation_id)
        if abandoned is not None:
            if abandoned != rejection:
                raise ContinuityError("changed duplicate pre-start rejection is forbidden")
            return "PRE_START_REJECTION_ABANDONED"
        pending = self._require_pending(rejection.operation_id)
        if pending.delivery_result not in {"FAILED", "TOOL_ERROR:ActivityError"}:
            raise ContinuityError("delivery lacks a proven pre-start FAILED result")
        try:
            rejection.require_match(pending.delivery)
        except ContractError as error:
            raise ContinuityError(str(error)) from error
        self._abandoned[rejection.operation_id] = rejection
        self._last_abandoned_operation_id = rejection.operation_id
        self._pending = None
        return "PRE_START_REJECTION_ABANDONED"

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
            "last_abandoned_operation_id": self._last_abandoned_operation_id,
            "recovery_request_count": self._recovery_request_count,
            "blocked_reason": pending.blocked_reason if pending else None,
            "terminal_reason": self._terminal_reason,
        }

    def checkpoint(self) -> dict[str, object]:
        """Lossless communication state; never an engineering-state snapshot."""
        pending = self._pending
        return {
            "schema_version": "slk.temporal-continuity-checkpoint/v1",
            "run_id": self.run_id,
            "seen": [item.to_dict() for item in self._seen.values()],
            "completed": [item.to_dict() for item in self._completed.values()],
            "abandoned": [item.to_dict() for item in self._abandoned.values()],
            "pending": ({"delivery": pending.delivery.to_dict(), "phase": pending.phase,
                         "delivery_result": pending.delivery_result,
                         "recovery_requested": pending.recovery_requested,
                         "blocked_reason": pending.blocked_reason} if pending else None),
            "last_completed_operation_id": self._last_completed_operation_id,
            "last_abandoned_operation_id": self._last_abandoned_operation_id,
            "recovery_request_count": self._recovery_request_count,
            "terminal_reason": self._terminal_reason,
        }

    @classmethod
    def from_checkpoint(cls, value: object) -> "RunContinuity":
        fields = {"schema_version", "run_id", "seen", "completed", "abandoned", "pending",
                  "last_completed_operation_id", "last_abandoned_operation_id",
                  "recovery_request_count", "terminal_reason"}
        if (not isinstance(value, Mapping) or set(value) != fields
            or value["schema_version"] != "slk.temporal-continuity-checkpoint/v1"
            or not isinstance(value["run_id"], str) or not value["run_id"]):
            raise ContinuityError("continuity checkpoint is not closed")
        result = cls(value["run_id"])
        for field, parser, target in (("seen", DeliveryRequest.from_dict, result._seen),
                                     ("completed", NativeStartAck.from_dict, result._completed),
                                     ("abandoned", PreStartRejection.from_dict, result._abandoned)):
            if not isinstance(value[field], list):
                raise ContinuityError("checkpoint operations must be arrays")
            for raw in value[field]:
                item = parser(raw)
                if getattr(item, "run_id", result.run_id) != result.run_id or item.operation_id in target:
                    raise ContinuityError("checkpoint operation scope or duplicate changed")
                target[item.operation_id] = item
        pending = value["pending"]
        if pending is not None:
            if (not isinstance(pending, Mapping) or set(pending) != {
                    "delivery", "phase", "delivery_result", "recovery_requested", "blocked_reason"}
                or pending["phase"] not in {"DELIVERY_REQUESTED", "RECOVERY_REQUIRED", "BLOCKED"}
                or type(pending["recovery_requested"]) is not bool
                or pending["delivery_result"] is not None and not isinstance(pending["delivery_result"], str)
                or pending["blocked_reason"] is not None and (
                    not isinstance(pending["blocked_reason"], str) or not pending["blocked_reason"].strip())):
                raise ContinuityError("checkpoint pending state is not closed")
            delivery = DeliveryRequest.from_dict(pending["delivery"])
            if result._seen.get(delivery.operation_id) != delivery:
                raise ContinuityError("checkpoint pending delivery is not an exact seen operation")
            if ((pending["phase"] == "RECOVERY_REQUIRED" and not pending["recovery_requested"])
                or (pending["phase"] == "BLOCKED") != (pending["blocked_reason"] is not None)):
                raise ContinuityError("checkpoint pending phase contradicts evidence")
            result._pending = _Pending(delivery, pending["phase"], pending["delivery_result"],
                                       pending["recovery_requested"], pending["blocked_reason"])
        resolved = set(result._completed) | set(result._abandoned)
        pending_ids = {result._pending.delivery.operation_id} if result._pending else set()
        if (set(result._completed) & set(result._abandoned) or resolved & pending_ids
            or set(result._seen) != resolved | pending_ids):
            raise ContinuityError("checkpoint loses or duplicates operation state")
        for item in (*result._completed.values(), *result._abandoned.values()):
            item.require_match(result._seen[item.operation_id])
        for field, items in (("last_completed_operation_id", result._completed),
                             ("last_abandoned_operation_id", result._abandoned)):
            if value[field] != next(reversed(items), None):
                raise ContinuityError("checkpoint last operation changed")
            setattr(result, "_" + field, value[field])
        count, terminal = value["recovery_request_count"], value["terminal_reason"]
        if (type(count) is not int or count < 0
            or result._pending and result._pending.recovery_requested and count < 1
            or terminal is not None and (not isinstance(terminal, str) or not terminal.strip() or pending_ids)):
            raise ContinuityError("checkpoint counter or terminal evidence changed")
        result._recovery_request_count, result._terminal_reason = count, terminal
        return result

    def pending_delivery(self) -> DeliveryRequest | None:
        return self._pending.delivery if self._pending else None

    def pending_delivery_result(self) -> str | None:
        return self._pending.delivery_result if self._pending else None

    def knows_delivery(self, operation_id: str) -> bool:
        return operation_id in self._seen

    def is_completed(self, operation_id: str) -> bool:
        return operation_id in self._completed

    def is_resolved(self, operation_id: str) -> bool:
        return operation_id in self._completed or operation_id in self._abandoned

    def is_terminal(self) -> bool:
        return self._terminal_reason is not None

    def _require_pending(self, operation_id: str) -> _Pending:
        if self._pending is None or self._pending.delivery.operation_id != operation_id:
            raise ContinuityError("delivery operation is not pending")
        return self._pending
