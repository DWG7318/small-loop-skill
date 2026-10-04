"""The reusable 启动 SLK and 进行 SLK Temporal workflow templates."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, Mapping

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from .continuity import RunContinuity
    from .contracts import (
        DeliveryRequest,
        NativeStartAck,
        OverwatcherExitNotice,
        RuntimeGuardResolution,
        StartSlkRequest,
        validate_supervisor_notification,
    )


ONE_ATTEMPT = RetryPolicy(maximum_attempts=1)
MEMBER_RESIDENCY_LIMIT = timedelta(minutes=30)
OVERWATCHER_AUDIT_INTERVAL = timedelta(minutes=20)


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
        self._responsible_role_instance_id: str | None = None
        self._responsibility_operation_id: str | None = None
        self._member_residency_since = None
        self._member_residency_notice_sent = False
        self._overwatcher_audit_cycle = 0
        self._next_overwatcher_audit_at = None
        self._runtime_guard_blocker: dict[str, Any] | None = None
        self._notification_failure: dict[str, Any] | None = None

    @workflow.run
    async def run(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping) or set(value) != {"startup", "startup_receipt"}:
            raise ValueError("SLK Run input must use the exact field set")
        self._startup = StartSlkRequest.from_dict(value["startup"])
        self._continuity = RunContinuity(self._startup.run_id)
        self._next_overwatcher_audit_at = workflow.now() + OVERWATCHER_AUDIT_INTERVAL
        while not self._continuity.is_terminal():
            if self._continuity.pending_delivery() is None:
                await self._wait_for_delivery_or_runtime_check()
            if self._continuity.is_terminal():
                break
            delivery = self._continuity.pending_delivery()
            if delivery is None:
                # An audit/residency timer can wake an otherwise idle Run.
                continue
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
            guarded_wait = workflow.patched("slk-4.4.1-runtime-checks-during-ack")
            try:
                if guarded_wait:
                    await self._wait_for_completion(operation_id, self._startup.ack_timeout_seconds)
                else:
                    # Preserve the command sequence of histories created before the patch.
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
                    recovery_input = {
                        "delivery": delivery.to_dict(),
                        "recovery_target_role_instance_id": delivery.sender_role_instance_id,
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
            if guarded_wait:
                await self._wait_for_completion(operation_id)
            else:
                await workflow.wait_condition(
                    lambda: self._continuity is not None
                    and (
                        self._continuity.is_completed(operation_id)
                        or self._continuity.is_terminal()
                    )
                )
        return self._continuity.snapshot()

    def _runtime_check_timeout(self) -> float:
        if self._continuity is None or self._startup is None:
            raise ValueError("SLK Run has not initialized")
        now = workflow.now()
        deadlines = [self._next_overwatcher_audit_at]
        if self._member_residency_since is not None and not self._member_residency_notice_sent:
            deadlines.append(self._member_residency_since + MEMBER_RESIDENCY_LIMIT)
        due = min(item for item in deadlines if item is not None)
        return max(0.001, (due - now).total_seconds())

    async def _wait_for_completion(self, operation_id: str, seconds: int | None = None) -> None:
        deadline = workflow.now() + timedelta(seconds=seconds) if seconds is not None else None
        while self._continuity is not None and not (
            self._continuity.is_completed(operation_id) or self._continuity.is_terminal()
        ):
            timeout = self._runtime_check_timeout()
            if deadline is not None:
                remaining = (deadline - workflow.now()).total_seconds()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                timeout = min(timeout, remaining)
            try:
                await workflow.wait_condition(
                    lambda: self._continuity is not None and (
                        self._continuity.is_completed(operation_id) or self._continuity.is_terminal()
                    ), timeout=timeout,
                )
            except asyncio.TimeoutError:
                await self._perform_runtime_checks()

    async def _wait_for_delivery_or_runtime_check(self) -> None:
        timeout = self._runtime_check_timeout()
        try:
            await workflow.wait_condition(
                lambda: self._continuity is not None
                and (
                    self._continuity.pending_delivery() is not None
                    or self._continuity.is_terminal()
                ),
                timeout=timeout,
            )
            return
        except asyncio.TimeoutError:
            pass
        await self._perform_runtime_checks()

    async def _perform_runtime_checks(self) -> None:
        now = workflow.now()
        if self._next_overwatcher_audit_at is not None and now >= self._next_overwatcher_audit_at:
            await self._inspect_overwatcher()
            self._next_overwatcher_audit_at = (
                self._next_overwatcher_audit_at + OVERWATCHER_AUDIT_INTERVAL
            )
        member_deadline = (
            self._member_residency_since + MEMBER_RESIDENCY_LIMIT
            if self._member_residency_since is not None
            else None
        )
        if (
            member_deadline is not None
            and now >= member_deadline
            and not self._member_residency_notice_sent
        ):
            operation_id = self._responsibility_operation_id
            role_instance_id = self._responsible_role_instance_id
            if operation_id is None or role_instance_id is None:
                raise RuntimeError("member residency identity is incomplete")
            await self._notify_supervisor(
                {
                    "event_id": f"{self._startup.run_id}-member-residency-{operation_id}",
                    "kind": "MEMBER_RESIDENCY_EXCEEDED",
                    "run_id": self._startup.run_id,
                    "responsible_role_instance_id": role_instance_id,
                    "source_operation_id": operation_id,
                    "threshold_seconds": int(MEMBER_RESIDENCY_LIMIT.total_seconds()),
                }
            )
            self._member_residency_notice_sent = True

    async def _inspect_overwatcher(self) -> None:
        if self._startup is None:
            raise ValueError("SLK Run has not initialized")
        overwatcher = self._startup.overwatcher
        if overwatcher is None:
            raise RuntimeError("mandatory Overwatcher binding is missing")
        self._overwatcher_audit_cycle += 1
        audit_input = {
            "run_id": self._startup.run_id,
            "overwatcher_role_instance_id": overwatcher.role_instance_id,
            "endpoint_ref": overwatcher.endpoint_ref,
            "audit_cycle": self._overwatcher_audit_cycle,
        }
        try:
            receipt = await workflow.execute_activity(
                "slk.inspect_overwatcher",
                audit_input,
                result_type=dict,
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=ONE_ATTEMPT,
                activity_id=f"audit-{overwatcher.role_instance_id}-{self._overwatcher_audit_cycle}",
            )
            receipt = _closed_receipt(
                receipt,
                {
                    "status", "run_id", "overwatcher_role_instance_id", "audit_cycle",
                    "evidence_sha256", "receipt_sha256",
                },
                status={"CLEAR", "ANOMALY"},
            )
            if (
                receipt.get("run_id") != self._startup.run_id
                or receipt.get("overwatcher_role_instance_id") != overwatcher.role_instance_id
                or receipt.get("audit_cycle") != self._overwatcher_audit_cycle
            ):
                raise ValueError("Overwatcher audit receipt changed identity")
            if workflow.patched("slk-4.4.1-closed-audit-evidence"):
                digest = receipt["evidence_sha256"]
                if (type(receipt["audit_cycle"]) is not int or not isinstance(digest, str)
                    or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
                    raise ValueError("Overwatcher audit evidence identity is invalid")
        except Exception:
            blocker = self._set_runtime_guard(
                event_id=f"{self._startup.run_id}-overwatcher-audit-{self._overwatcher_audit_cycle}",
                kind="OVERWATCHER_AUDIT_FAILED",
                role_instance_id=overwatcher.role_instance_id,
            )
            await self._notify_supervisor(blocker)
            return
        if receipt["status"] == "ANOMALY":
            blocker = self._set_runtime_guard(
                event_id=f"{self._startup.run_id}-overwatcher-audit-{self._overwatcher_audit_cycle}",
                kind="OVERWATCHER_ACTIVITY_ANOMALY",
                role_instance_id=overwatcher.role_instance_id,
            )
            await self._notify_supervisor(blocker)

    def _set_runtime_guard(
        self, *, event_id: str, kind: str, role_instance_id: str
    ) -> dict[str, Any]:
        if self._startup is None:
            raise ValueError("SLK Run has not initialized")
        blocker = {
            "event_id": event_id,
            "kind": kind,
            "run_id": self._startup.run_id,
            "responsible_role_instance_id": role_instance_id,
            "source_operation_id": f"runtime-guard-{event_id}",
            "threshold_seconds": 0,
        }
        if self._runtime_guard_blocker is None:
            self._runtime_guard_blocker = dict(blocker)
        # A later alarm must remain reportable without replacing the unresolved
        # repair identity or crashing monitoring of this Run.
        return blocker

    async def _notify_supervisor(self, value: dict[str, Any]) -> bool:
        strict = workflow.patched("slk-441-native-supervisor-notice")
        try:
            receipt = await workflow.execute_activity(
                "slk.notify_supervisor", value, result_type=dict,
                start_to_close_timeout=timedelta(minutes=5), retry_policy=ONE_ATTEMPT,
                activity_id=f"notify-{value['event_id']}",
            )
            if strict:
                if self._startup is None:
                    raise ValueError("notification requires the frozen Run team")
                validate_supervisor_notification(receipt, run_id=self._startup.run_id, event_id=value["event_id"],
                                                 supervisor_role_instance_id=self._startup.supervisor.role_instance_id)
            else:
                _closed_receipt(receipt, {"status", "event_id", "receipt_sha256"}, status={"NOTIFIED"})
                if receipt.get("event_id") != value["event_id"]:
                    raise ValueError("Supervisor notification receipt changed event_id")
        except (ActivityError, ValueError, KeyError, TypeError):
            if not strict or self._startup is None:
                raise
            self._notification_failure = {"event_id": value["event_id"], "reason": "SUPERVISOR_NOTIFICATION_UNPROVED"}
            self._set_runtime_guard(event_id=value["event_id"], kind="SUPERVISOR_NOTIFICATION_UNPROVED",
                                    role_instance_id=self._startup.supervisor.role_instance_id)
            return False  # retain bounded monitoring; never claim takeover or permit another CELL
        self._notification_failure = None
        return True

    @staticmethod
    def _update_value(function, value):
        """Reject only this invalid update; never poison the whole Workflow task."""
        try:
            return function(value)
        except ValueError as exc:
            raise ApplicationError(str(exc), type="SLK_UPDATE_REJECTED", non_retryable=True) from exc

    @workflow.update
    def request_delivery(self, value: dict[str, Any]) -> str:
        if self._continuity is None:
            raise ApplicationError("SLK Run has not initialized", non_retryable=True)
        if self._runtime_guard_blocker is not None:
            raise ApplicationError("runtime guard must be repaired before the next CELL delivery", non_retryable=True)
        request = self._update_value(DeliveryRequest.from_dict, value)
        return self._update_value(self._continuity.request_delivery, request)

    @workflow.update
    def native_started(self, value: dict[str, Any]) -> str:
        if self._continuity is None:
            raise ApplicationError("SLK Run has not initialized", non_retryable=True)
        acknowledgement = self._update_value(NativeStartAck.from_dict, value)
        pending = self._continuity.pending_delivery()
        if pending is None:
            return self._update_value(self._continuity.acknowledge, acknowledgement)
        result = self._update_value(self._continuity.acknowledge, acknowledgement)
        self._responsible_role_instance_id = pending.receiver_role_instance_id
        self._responsibility_operation_id = pending.operation_id
        self._member_residency_since = workflow.now()
        self._member_residency_notice_sent = False
        return result

    @workflow.update
    async def overwatcher_exited(self, value: dict[str, Any]) -> str:
        if self._startup is None:
            raise ApplicationError("SLK Run has not initialized", non_retryable=True)
        notice = self._update_value(OverwatcherExitNotice.from_dict, value)
        overwatcher = self._startup.overwatcher
        if (
            overwatcher is None
            or notice.run_id != self._startup.run_id
            or notice.overwatcher_role_instance_id != overwatcher.role_instance_id
        ):
            raise ApplicationError("Overwatcher exit notice changed the frozen Run identity", non_retryable=True)
        blocker = self._set_runtime_guard(
            event_id=notice.event_id,
            kind="OVERWATCHER_EXIT_REQUIRES_SUPERVISOR_CONFIRMATION",
            role_instance_id=notice.overwatcher_role_instance_id,
        )
        await self._notify_supervisor(blocker)
        return "SUPERVISOR_CONFIRMATION_REQUIRED"

    @workflow.update
    def resolve_runtime_guard(self, value: dict[str, Any]) -> str:
        if self._startup is None or self._runtime_guard_blocker is None:
            raise ApplicationError("no runtime guard is awaiting repair", non_retryable=True)
        resolution = self._update_value(RuntimeGuardResolution.from_dict, value)
        if (
            resolution.run_id != self._startup.run_id
            or resolution.supervisor_role_instance_id
            != self._startup.supervisor.role_instance_id
            or resolution.blocker_event_id != self._runtime_guard_blocker["event_id"]
        ):
            raise ApplicationError("runtime guard resolution changed the frozen authority or blocker", non_retryable=True)
        self._runtime_guard_blocker = None
        return "RUNTIME_GUARD_REPAIRED"

    @workflow.update
    def close_run(self, reason: str) -> str:
        if self._continuity is None:
            raise ApplicationError("SLK Run has not initialized", non_retryable=True)
        return self._update_value(self._continuity.terminate, reason)

    @workflow.query
    def status(self) -> dict[str, Any]:
        if self._continuity is None:
            return {"phase": "NOT_STARTED"}
        return {
            **self._continuity.snapshot(),
            "responsible_role_instance_id": self._responsible_role_instance_id,
            "responsibility_operation_id": self._responsibility_operation_id,
            "member_residency_since": (
                self._member_residency_since.isoformat()
                if self._member_residency_since is not None else None
            ),
            "member_residency_notice_sent": self._member_residency_notice_sent,
            "overwatcher_audit_cycle": self._overwatcher_audit_cycle,
            "next_overwatcher_audit_at": (
                self._next_overwatcher_audit_at.isoformat()
                if self._next_overwatcher_audit_at is not None else None
            ),
            "runtime_guard_blocker": (
                dict(self._runtime_guard_blocker)
                if self._runtime_guard_blocker is not None else None
            ),
            "notification_failure": dict(self._notification_failure) if self._notification_failure else None,
        }
