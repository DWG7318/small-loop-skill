"""The reusable 启动 SLK and 进行 SLK Temporal workflow templates."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Mapping

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy

with workflow.unsafe.imports_passed_through():
    from .continuity import RunContinuity
    from .contracts import DeliveryRequest, NativeStartAck, StartSlkRequest


ONE_ATTEMPT = RetryPolicy(maximum_attempts=1)


def _closed_receipt(
    value: object,
    fields: set[str],
    *,
    status: set[str],
    operation_id: str | None = None,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError("Temporal adapter receipt must use the exact field set")
    if value.get("status") not in status:
        raise ValueError("Temporal adapter receipt has an invalid status")
    digest = value.get("receipt_sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("Temporal adapter receipt must contain a lowercase SHA-256")
    if operation_id is not None and value.get("operation_id") != operation_id:
        raise ValueError("Temporal adapter receipt changed operation_id")
    return value


@workflow.defn(name="SLK.Start")
class StartSlkWorkflow:
    """Validate one startup request and own one child SLK Run workflow."""

    def __init__(self) -> None:
        self._identity: dict[str, Any] = {"phase": "NOT_STARTED"}

    @workflow.run
    async def run(self, value: dict[str, Any]) -> dict[str, Any]:
        request = StartSlkRequest.from_dict(value)
        fingerprint = request.startup_fingerprint
        child_id = f"slk-run-{request.run_id}"
        self._identity = {
            "phase": "PREPARING",
            "run_id": request.run_id,
            "startup_fingerprint": fingerprint,
            "child_workflow_id": child_id,
        }
        receipt = await workflow.execute_activity(
            "slk.prepare_run",
            {"request": request.to_dict(), "startup_fingerprint": fingerprint},
            result_type=dict,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=ONE_ATTEMPT,
            activity_id=f"prepare-{request.startup_idempotency_key}",
        )
        receipt = _closed_receipt(
            receipt,
            {
                "status",
                "run_id",
                "runtime_revision",
                "startup_fingerprint",
                "receipt_sha256",
            },
            status={"READY"},
        )
        expected = (request.run_id, request.runtime_revision, fingerprint)
        actual = (
            receipt.get("run_id"),
            receipt.get("runtime_revision"),
            receipt.get("startup_fingerprint"),
        )
        if actual != expected:
            raise ValueError("startup readiness receipt does not match the request")
        self._identity["phase"] = "RUNNING"
        child = await workflow.start_child_workflow(
            RunSlkWorkflow.run,
            {"startup": request.to_dict(), "startup_receipt": dict(receipt)},
            id=child_id,
            task_queue=request.task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            retry_policy=ONE_ATTEMPT,
        )
        result = await child
        self._identity["phase"] = "TERMINAL"
        return {**result, "startup_fingerprint": fingerprint, "child_workflow_id": child_id}

    @workflow.query
    def status(self) -> dict[str, Any]:
        return dict(self._identity)


@workflow.defn(name="SLK.Run")
class RunSlkWorkflow:
    """Durably track exact cross-Agent delivery and recovery, not engineering judgment."""

    def __init__(self) -> None:
        self._continuity: RunContinuity | None = None
        self._startup: StartSlkRequest | None = None
        self._delivery_started: set[str] = set()
        self._recovery_started: set[str] = set()

    @workflow.run
    async def run(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != {"startup", "startup_receipt"}:
            raise ValueError("SLK Run input must use the exact field set")
        self._startup = StartSlkRequest.from_dict(value["startup"])
        self._continuity = RunContinuity(self._startup.run_id)
        while not self._continuity.is_terminal():
            await workflow.wait_condition(
                lambda: self._continuity is not None
                and (
                    self._continuity.pending_delivery() is not None
                    or self._continuity.is_terminal()
                )
            )
            if self._continuity.is_terminal():
                break
            delivery = self._continuity.pending_delivery()
            if delivery is None:
                raise RuntimeError("pending delivery disappeared after the wait condition")
            operation_id = delivery.operation_id
            if operation_id not in self._delivery_started:
                self._delivery_started.add(operation_id)
                try:
                    receipt = await workflow.execute_activity(
                        "slk.deliver_message",
                        delivery.to_dict(),
                        result_type=dict,
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=ONE_ATTEMPT,
                        activity_id=f"deliver-{operation_id}",
                    )
                    _closed_receipt(
                        receipt,
                        {"status", "operation_id", "receipt_sha256"},
                        status={"DELIVERED", "FAILED"},
                        operation_id=operation_id,
                    )
                    if not self._continuity.is_completed(operation_id):
                        self._continuity.record_delivery_result(
                            operation_id, str(receipt["status"])
                        )
                except Exception as error:
                    if not self._continuity.is_completed(operation_id):
                        self._continuity.record_delivery_result(
                            operation_id, f"TOOL_ERROR:{type(error).__name__}"
                        )
            if self._continuity.is_completed(operation_id):
                continue
            try:
                await workflow.wait_condition(
                    lambda: self._continuity is not None
                    and self._continuity.is_completed(operation_id),
                    timeout=self._startup.ack_timeout_seconds,
                )
            except asyncio.TimeoutError:
                if self._continuity.is_completed(operation_id):
                    continue
                self._continuity.mark_timeout(operation_id)
                if operation_id not in self._recovery_started:
                    self._recovery_started.add(operation_id)
                    overwatcher = self._startup.overwatcher
                    recovery_input = {
                        "delivery": delivery.to_dict(),
                        "recovery_target_role_instance_id": (
                            overwatcher.role_instance_id if overwatcher else "SENDER"
                        ),
                    }
                    recovery = await workflow.execute_activity(
                        "slk.request_recovery",
                        recovery_input,
                        result_type=dict,
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=ONE_ATTEMPT,
                        activity_id=f"recover-{operation_id}",
                    )
                    recovery = _closed_receipt(
                        recovery,
                        {"status", "operation_id", "receipt_sha256"},
                        status={"RECOVERY_REQUESTED", "BLOCKED"},
                        operation_id=operation_id,
                    )
                    if recovery["status"] == "BLOCKED":
                        self._continuity.mark_blocked(
                            operation_id, "adapter reported no verified continuation route"
                        )
            await workflow.wait_condition(
                lambda: self._continuity is not None
                and (
                    self._continuity.is_completed(operation_id)
                    or self._continuity.is_terminal()
                )
            )
        return self._continuity.snapshot()

    @workflow.update
    def request_delivery(self, value: dict[str, Any]) -> str:
        if self._continuity is None:
            raise ValueError("SLK Run has not initialized")
        return self._continuity.request_delivery(DeliveryRequest.from_dict(value))

    @workflow.update
    def native_started(self, value: dict[str, Any]) -> str:
        if self._continuity is None:
            raise ValueError("SLK Run has not initialized")
        return self._continuity.acknowledge(NativeStartAck.from_dict(value))

    @workflow.update
    def close_run(self, reason: str) -> str:
        if self._continuity is None:
            raise ValueError("SLK Run has not initialized")
        return self._continuity.terminate(reason)

    @workflow.query
    def status(self) -> dict[str, Any]:
        if self._continuity is None:
            return {"phase": "NOT_STARTED"}
        return self._continuity.snapshot()
