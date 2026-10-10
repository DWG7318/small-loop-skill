"""The reusable 启动 SLK and 进行 SLK Temporal workflow templates."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Mapping

from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ActivityError, ApplicationError

with workflow.unsafe.imports_passed_through():
    from .continuity import RunContinuity
    from .checkpoint import validate_checkpoint
    from .contracts import (
        DeliveryRequest,
        NativeStartAck,
        PreStartRejection,
        OverwatcherExitNotice,
        RuntimeGuardResolution,
        StartSlkRequest,
        IDENTIFIER,
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
        if isinstance(value, Mapping) and set(value) == {"recovery"}:
            # One validation Activity reads native source history and sealed
            # Supervisor authority. No admission, delivery or recovery replay.
            receipt = await workflow.execute_activity(
                "slk.prepare_run", value, result_type=dict,
                start_to_close_timeout=timedelta(seconds=60), retry_policy=ONE_ATTEMPT)
            if not isinstance(receipt, Mapping) or set(receipt) != {
                "status", "checkpoint", "recovery_request_sha256", "source_run_id"} or receipt["status"] != "RECOVERY_READY":
                raise ValueError("closed execution recovery validation failed")
            checkpoint = validate_checkpoint(receipt["checkpoint"])
            request = StartSlkRequest.from_dict(checkpoint["startup"])
            # Native lineage is verified by the Activity, never file IO during replay.
            child_id = f"slk-run-{request.run_id}-recovery-{receipt['source_run_id']}"
            self._identity = {"phase": "PREPARING", "run_id": request.run_id,
                              "startup_fingerprint": request.startup_fingerprint,
                              "child_workflow_id": child_id,
                              "recovery_request_sha256": receipt["recovery_request_sha256"]}
            child = await workflow.start_child_workflow(RunSlkWorkflow.run,
                {"startup": request.to_dict(), "recovery_checkpoint": checkpoint}, id=child_id,
                task_queue=request.task_queue, id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                retry_policy=ONE_ATTEMPT)
            self._identity["phase"] = "PAIR_CREATED"
            result = await child
            self._identity["phase"] = "TERMINAL"
            return {**result, "startup_fingerprint": request.startup_fingerprint, "child_workflow_id": child_id}
        request = StartSlkRequest.from_dict(value)
        fingerprint = request.startup_fingerprint
        child_id = f"slk-run-{request.run_id}"
        self._identity = {
            "phase": "PREPARING",
            "run_id": request.run_id,
            "startup_fingerprint": fingerprint,
            "child_workflow_id": child_id,
        }
        two_stage = workflow.patched("slk-4.4.2-two-stage-admission")
        if two_stage:
            child_input = {"startup": request.to_dict(), "admission_required": True}
        else:
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
                {"status", "run_id", "runtime_revision", "startup_fingerprint", "receipt_sha256"},
                status={"READY"},
            )
            expected = (request.run_id, request.runtime_revision, fingerprint)
            actual = (receipt.get("run_id"), receipt.get("runtime_revision"),
                      receipt.get("startup_fingerprint"))
            if actual != expected:
                raise ValueError("startup readiness receipt does not match the request")
            child_input = {"startup": request.to_dict(), "startup_receipt": dict(receipt)}
        child = await workflow.start_child_workflow(
            RunSlkWorkflow.run,
            child_input,
            id=child_id,
            task_queue=request.task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
            retry_policy=ONE_ATTEMPT,
        )
        self._identity["phase"] = "PAIR_CREATED" if two_stage else "RUNNING"
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
        self._admitted = False
        self._admission_requested = False
        self._admission_request_sha256: str | None = None
        self._admission_attempt = 0
        self._admission_failure: str | None = None
        self._recovery_failure: dict[str, Any] | None = None
        self._restored_pending_operation: str | None = None
        self._run_pause: dict[str, Any] | None = None

    @workflow.run
    async def run(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise ValueError("SLK Run input must be an object")
        restoring = "recovery_checkpoint" in value
        two_stage = not restoring and workflow.patched("slk-4.4.2-two-stage-admission")
        expected_fields = ({"startup", "recovery_checkpoint"} if restoring else
                           {"startup", "admission_required"} if two_stage else {"startup", "startup_receipt"})
        if set(value) != expected_fields or (two_stage and value.get("admission_required") is not True):
            raise ValueError("SLK Run input must use the exact field set")
        self._startup = StartSlkRequest.from_dict(value["startup"])
        self._continuity = RunContinuity(self._startup.run_id)
        self._admitted = not two_stage
        if restoring:
            info = workflow.info()
            prefix = f"slk-run-{self._startup.run_id}-recovery-"
            if (info.parent is None or not info.workflow_id.startswith(prefix)
                or info.workflow_id == prefix
                or info.parent.workflow_id != info.workflow_id.replace("slk-run-", "slk-start-", 1)):
                raise ApplicationError("checkpoint requires the exact recovery parent", non_retryable=True)
            self._restore_checkpoint(value["recovery_checkpoint"])
            # Closed executions did not monitor the gap. Do not replay missed
            # audit cycles as new external actions; source times remain in lineage.
            self._next_overwatcher_audit_at = workflow.now() + OVERWATCHER_AUDIT_INTERVAL
        if two_stage:
            while not self._admitted and not self._continuity.is_terminal():
                await workflow.wait_condition(
                    lambda: self._admission_requested or (
                        self._continuity is not None and self._continuity.is_terminal()
                    )
                )
                if self._continuity.is_terminal():
                    break
                self._admission_attempt += 1
                try:
                    receipt = await workflow.execute_activity(
                        "slk.prepare_run",
                        {"request": self._startup.to_dict(),
                         "startup_fingerprint": self._startup.startup_fingerprint},
                        result_type=dict,
                        start_to_close_timeout=timedelta(seconds=60),
                        retry_policy=ONE_ATTEMPT,
                        activity_id=(f"prepare-{self._startup.startup_idempotency_key}-"
                                     f"{self._admission_attempt}"),
                    )
                    receipt = _closed_receipt(
                        receipt,
                        {"status", "run_id", "runtime_revision", "startup_fingerprint",
                         "receipt_sha256"},
                        status={"READY"},
                    )
                    expected = (self._startup.run_id, self._startup.runtime_revision,
                                self._startup.startup_fingerprint)
                    actual = (receipt.get("run_id"), receipt.get("runtime_revision"),
                              receipt.get("startup_fingerprint"))
                    if actual != expected:
                        raise ValueError("startup readiness receipt does not match the request")
                    self._admitted = True
                    self._admission_failure = None
                except Exception as error:
                    self._admission_failure = type(error).__name__
                    self._admission_requested = False
        if self._continuity.is_terminal():
            return self._continuity.snapshot()
        if self._next_overwatcher_audit_at is None:
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
            if self._run_pause is None and self._continuity.pending_delivery_result() == "PAUSED":
                # The central gate may precede its original Temporal update.
                # Retain the receipt, not a fabricated lifecycle phase or ACK.
                try:
                    await workflow.wait_condition(lambda: self._run_pause is not None
                        or self._continuity.is_terminal() or self._continuity.is_resolved(operation_id),
                        timeout=self._runtime_check_timeout())
                except asyncio.TimeoutError:
                    await self._perform_runtime_checks()
                continue
            if self._run_pause is not None:
                workflow.patched("slk-4.4.3-run-pause")
                sender = next(role.role for role in self._startup.roles if role.role_instance_id == delivery.sender_role_instance_id)
                receiver = next(role.role for role in self._startup.roles if role.role_instance_id == delivery.receiver_role_instance_id)
                blocked = self._run_pause["phase"] == "PAUSED" or (self._run_pause["phase"] == "REQUESTED"
                    and (sender, receiver) not in {("WORKER", "CHECKER"), ("CHECKER", "SUPERVISOR")})
                generation = self._run_pause["delivery_generation"]
                deferred = self._run_pause["deferred_operation_id"] == operation_id
                if blocked or deferred:
                    try:
                        await workflow.wait_condition(lambda: self._continuity.is_terminal()
                            or self._continuity.is_resolved(operation_id)
                            or self._run_pause["delivery_generation"] != generation,
                            timeout=self._runtime_check_timeout())
                    except asyncio.TimeoutError:
                        await self._perform_runtime_checks()
                    continue
            if operation_id == self._restored_pending_operation:
                # The source history already attempted delivery/recovery. Only its
                # original, independently proven native-start ACK may release it.
                await self._wait_for_completion(operation_id)
                self._restored_pending_operation = None
                continue
            if (operation_id not in self._delivery_started
                or (self._run_pause is not None and self._run_pause["deferred_operation_id"] == "RETRY:" + operation_id)):
                self._delivery_started.add(operation_id)
                try:
                    receipt = await workflow.execute_activity(
                        "slk.deliver_message",
                        delivery.to_dict(),
                        result_type=dict,
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=ONE_ATTEMPT,
                        activity_id=(f"deliver-{operation_id}-pause-{self._run_pause['delivery_generation']}"
                            if self._run_pause is not None else f"deliver-{operation_id}"),
                    )
                    early_pause = (self._run_pause is None and isinstance(receipt, Mapping) and receipt.get("status") == "PAUSED"
                        and workflow.patched("slk-4.4.3-central-pause-receipt"))
                    _closed_receipt(
                        receipt,
                        {"status", "operation_id", "receipt_sha256"},
                        status={"DELIVERED", "FAILED", "PAUSED"} if self._run_pause is not None or early_pause else {"DELIVERED", "FAILED"},
                        operation_id=operation_id,
                    )
                    if receipt["status"] == "PAUSED":
                        if self._continuity.is_resolved(operation_id): continue
                        if self._run_pause is None:
                            self._continuity.record_delivery_result(operation_id, "PAUSED")
                        else:
                            self._run_pause["deferred_operation_id"] = operation_id
                        continue
                    if self._run_pause is not None:
                        self._run_pause["deferred_operation_id"] = None
                    if not self._continuity.is_completed(operation_id):
                        self._continuity.record_delivery_result(
                            operation_id, str(receipt["status"])
                        )
                except Exception as error:
                    if not self._continuity.is_completed(operation_id):
                        self._continuity.record_delivery_result(
                            operation_id, f"TOOL_ERROR:{type(error).__name__}"
                        )
            if self._continuity.is_resolved(operation_id):
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
                if self._continuity.is_resolved(operation_id):
                    continue
                self._continuity.mark_timeout(operation_id)
                if operation_id not in self._recovery_started:
                    self._recovery_started.add(operation_id)
                    recovery_input = {
                        "delivery": delivery.to_dict(),
                        "recovery_target_role_instance_id": delivery.sender_role_instance_id,
                    }
                    try:
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
                    except Exception as error:
                        if not workflow.patched("slk-4.4.2-recovery-failure-is-guard"):
                            raise  # preserve the recorded outcome of pre-fix histories
                        cause = error
                        while cause.__cause__ is not None:
                            cause = cause.__cause__
                        details = getattr(cause, "details", ())
                        self._recovery_failure = {"reason": str(cause), "type": type(cause).__name__,
                            "operation_id": operation_id,
                            "evidence": details[0] if details and isinstance(details[0], dict) else None}
                        self._continuity.mark_blocked(
                            operation_id, "recovery activity failed; Supervisor repair required"
                        )
                        blocker = self._set_runtime_guard(
                            event_id=f"{self._startup.run_id}-recovery-failed-{operation_id}",
                            kind="RECOVERY_ACTIVITY_FAILED",
                            role_instance_id=delivery.sender_role_instance_id,
                        )
                        await self._notify_supervisor(blocker)
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
        if (self._member_residency_since is not None and not self._member_residency_notice_sent
            and not self._pause_confirmed()):
            deadlines.append(self._member_residency_since + MEMBER_RESIDENCY_LIMIT)
        due = min(item for item in deadlines if item is not None)
        return max(0.001, (due - now).total_seconds())

    async def _wait_for_completion(self, operation_id: str, seconds: int | None = None) -> None:
        deadline = workflow.now() + timedelta(seconds=seconds) if seconds is not None else None
        while self._continuity is not None and not (
            self._continuity.is_resolved(operation_id) or self._continuity.is_terminal()
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
                        self._continuity.is_resolved(operation_id) or self._continuity.is_terminal()
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
            and not self._pause_confirmed()
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
    def request_admission(self, value: dict[str, Any]) -> str:
        if self._startup is None or self._continuity is None:
            raise ApplicationError("SLK Run has not initialized", non_retryable=True)
        if not isinstance(value, Mapping) or set(value) != {
            "run_id", "startup_fingerprint", "workflow_identity_sha256",
        }:
            raise ApplicationError("admission request is not closed", non_retryable=True)
        digest = value.get("workflow_identity_sha256")
        if (value.get("run_id") != self._startup.run_id
            or value.get("startup_fingerprint") != self._startup.startup_fingerprint
            or not isinstance(digest, str) or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)):
            raise ApplicationError("admission request changed workflow identity", non_retryable=True)
        if self._admission_request_sha256 not in (None, digest):
            raise ApplicationError("admission request changed its identity evidence", non_retryable=True)
        if self._admitted:
            return "READY"
        if self._continuity.is_terminal():
            raise ApplicationError("terminal Run cannot be admitted", non_retryable=True)
        self._admission_request_sha256 = digest
        self._admission_requested = True
        self._admission_failure = None
        return "ADMISSION_REQUESTED"

    @workflow.update
    def set_run_pause(self, value: dict[str, Any]) -> str:
        if self._startup is None or self._continuity is None:
            raise ApplicationError("SLK Run has not initialized", non_retryable=True)
        fields = {"run_id", "supervisor_role_instance_id", "pause_id", "event_id", "phase"}
        if isinstance(value, Mapping) and "confirmed_at" in value: fields.add("confirmed_at")
        if (not isinstance(value, Mapping) or set(value) != fields
            or value["run_id"] != self._startup.run_id
            or value["supervisor_role_instance_id"] != self._startup.supervisor.role_instance_id):
            raise ApplicationError("pause requires the exact frozen Supervisor", non_retryable=True)
        if (value["phase"] not in {"REQUESTED", "PAUSED", "RESUMED"}
            or any(not isinstance(value[key], str) or not IDENTIFIER.fullmatch(value[key]) for key in ("pause_id", "event_id"))
            or self._continuity.is_terminal()):
            raise ApplicationError("pause lifecycle identity or phase is invalid", non_retryable=True)
        old = self._run_pause
        if old is not None and value["event_id"] in old["events"]:
            if old["events"][value["event_id"]] != dict(value):
                raise ApplicationError("pause event identity changed", non_retryable=True)
            if value["phase"] == "RESUMED" and old["deferred_operation_id"] is not None:
                operation = old["deferred_operation_id"].removeprefix("RETRY:")
                old["delivery_generation"] += 1
                old["deferred_operation_id"] = "RETRY:" + operation
            return value["phase"]
        prior = old["phase"] if old is not None else None
        if (value["phase"] == "REQUESTED" and old is not None
            and any(event["pause_id"] == value["pause_id"] for event in old["events"].values())):
            raise ApplicationError("pause cycle identity was already used", non_retryable=True)
        required = {"REQUESTED": {None, "RESUMED"}, "PAUSED": {"REQUESTED"}, "RESUMED": {"PAUSED"}}
        if prior not in required[value["phase"]] or (value["phase"] != "REQUESTED" and value["pause_id"] != old["pause_id"]):
            raise ApplicationError("pause lifecycle transition is invalid", non_retryable=True)
        pending = self._continuity.pending_delivery()
        deferred = (old["deferred_operation_id"] if old is not None else
            pending.operation_id if pending is not None and self._continuity.pending_delivery_result() == "PAUSED" else None)
        if (value["phase"] == "PAUSED" and pending is not None
            and pending.operation_id in self._delivery_started and deferred != pending.operation_id):
            raise ApplicationError("pause cannot confirm an unresolved native delivery", non_retryable=True)
        paused_at = old["paused_at"] if old is not None else None
        if value["phase"] == "PAUSED":
            confirmed = workflow.now()
            if "confirmed_at" in value:
                try:
                    confirmed = datetime.fromisoformat(value["confirmed_at"].replace("Z", "+00:00"))
                    if confirmed.tzinfo is None or confirmed > workflow.now(): raise ValueError("timestamp")
                except (AttributeError, TypeError, ValueError) as exc:
                    raise ApplicationError("pause confirmation timestamp is invalid", non_retryable=True) from exc
            paused_at = confirmed.isoformat()
        elif "confirmed_at" in value:
            raise ApplicationError("only PAUSED may contain its central confirmation time", non_retryable=True)
        if value["phase"] == "RESUMED" and self._member_residency_since is not None:
            # A role whose responsibility began inside a pause only loses its
            # own overlap, never the time before it took responsibility.
            start = max(datetime.fromisoformat(paused_at), self._member_residency_since)
            self._member_residency_since += max(timedelta(), workflow.now() - start)
        events = dict(old["events"]) if old is not None else {}
        events[value["event_id"]] = dict(value)
        self._run_pause = {"phase": value["phase"], "pause_id": value["pause_id"],
                           "paused_at": paused_at, "events": events,
                           "deferred_operation_id": deferred,
                           "delivery_generation": old["delivery_generation"] + (value["phase"] == "RESUMED") if old else 0}
        if value["phase"] == "RESUMED" and deferred is not None:
            self._run_pause["deferred_operation_id"] = "RETRY:" + deferred
        return value["phase"]

    def _pause_confirmed(self) -> bool:
        return self._run_pause is not None and self._run_pause["phase"] == "PAUSED"

    @workflow.update
    def request_delivery(self, value: dict[str, Any]) -> str:
        if self._continuity is None:
            raise ApplicationError("SLK Run has not initialized", non_retryable=True)
        if not self._admitted:
            raise ApplicationError("full new-Run admission must pass before delivery", non_retryable=True)
        if self._runtime_guard_blocker is not None:
            raise ApplicationError("runtime guard must be repaired before the next CELL delivery", non_retryable=True)
        request = self._update_value(DeliveryRequest.from_dict, value)
        if (self._run_pause is not None and self._run_pause["phase"] != "RESUMED"
            and not self._continuity.knows_delivery(request.operation_id)):
            sender = next((role.role for role in self._startup.roles if role.role_instance_id == request.sender_role_instance_id), None)
            receiver = next((role.role for role in self._startup.roles if role.role_instance_id == request.receiver_role_instance_id), None)
            if self._pause_confirmed() or (sender, receiver) not in {("WORKER", "CHECKER"), ("CHECKER", "SUPERVISOR")}:
                raise ApplicationError("Run pause blocks new engineering delivery", non_retryable=True)
        result = self._update_value(self._continuity.request_delivery, request)
        if (self._run_pause is not None and self._run_pause["phase"] == "RESUMED"
            and self._run_pause["deferred_operation_id"] == request.operation_id):
            self._run_pause["delivery_generation"] += 1
            self._run_pause["deferred_operation_id"] = "RETRY:" + request.operation_id
        return result

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
    def abandon_pre_start_rejection(self, value: dict[str, Any]) -> str:
        if self._startup is None or self._continuity is None:
            raise ApplicationError("SLK Run has not initialized", non_retryable=True)
        rejection = self._update_value(PreStartRejection.from_dict, value)
        supervisor = self._startup.supervisor.role_instance_id
        if (
            rejection.run_id != self._startup.run_id
            or rejection.supervisor_role_instance_id != supervisor
            or rejection.central_token_holder_role_instance_id != supervisor
        ):
            raise ApplicationError(
                "pre-start rejection changed the frozen Supervisor authority",
                non_retryable=True,
            )
        return self._update_value(self._continuity.abandon_pre_start, rejection)

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
    def recovery_checkpoint(self) -> dict[str, Any]:
        if self._startup is None or self._continuity is None:
            raise ValueError("SLK Run has not initialized")
        return {"schema_version": "slk.temporal-execution-checkpoint/v2" if self._run_pause is not None else "slk.temporal-execution-checkpoint/v1",
                "startup": self._startup.to_dict(), "continuity": self._continuity.checkpoint(),
                "delivery_started": sorted(self._delivery_started),
                "recovery_started": sorted(self._recovery_started), "status": self.status(),
                "admission_requested": self._admission_requested,
                "admission_request_sha256": self._admission_request_sha256}

    def _restore_checkpoint(self, value: object) -> None:
        packet = validate_checkpoint(value)
        if packet["startup"] != self._startup.to_dict():
            raise ValueError("restoration changed immutable startup")
        self._continuity = RunContinuity.from_checkpoint(packet["continuity"])
        self._delivery_started, self._recovery_started = (
            set(packet["delivery_started"]), set(packet["recovery_started"]))
        state = packet["status"]
        for field in ("admitted", "admission_attempt", "admission_failure",
                      "responsible_role_instance_id", "responsibility_operation_id",
                      "member_residency_notice_sent", "overwatcher_audit_cycle",
                      "runtime_guard_blocker", "notification_failure", "recovery_failure"):
            setattr(self, "_" + field, state[field])
        for field in ("member_residency_since", "next_overwatcher_audit_at"):
            setattr(self, "_" + field, datetime.fromisoformat(state[field]) if state[field] else None)
        self._admission_requested = packet["admission_requested"]
        self._admission_request_sha256 = packet["admission_request_sha256"]
        self._run_pause = state.get("run_pause")
        pending = self._continuity.pending_delivery()
        self._restored_pending_operation = (pending.operation_id if pending is not None
            and pending.operation_id in self._delivery_started
            and self._continuity.pending_delivery_result() != "PAUSED"
            and (self._run_pause is None or self._run_pause["deferred_operation_id"] not in {pending.operation_id, "RETRY:" + pending.operation_id}) else None)

    @workflow.query
    def status(self) -> dict[str, Any]:
        if self._continuity is None:
            return {"phase": "NOT_STARTED"}
        snapshot = self._continuity.snapshot()
        if not self._admitted and not self._continuity.is_terminal():
            snapshot["phase"] = "ADMISSION_FAILED" if self._admission_failure else "AWAITING_ADMISSION"
        return {
            **snapshot,
            **({"run_pause": self._run_pause} if self._run_pause is not None else {}),
            "admitted": self._admitted,
            "admission_attempt": self._admission_attempt,
            "admission_failure": self._admission_failure,
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
            "recovery_failure": dict(self._recovery_failure) if self._recovery_failure else None,
        }
