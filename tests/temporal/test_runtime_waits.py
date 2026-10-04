"""C2 regressions use an injected clock; no real 20/30-minute sleeps."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("temporalio")
from temporalio.exceptions import ApplicationError
from slk_temporal import workflows
from slk_temporal.workflows import RunSlkWorkflow

from .test_contracts import start_value, delivery_value, ack_value


@pytest.mark.parametrize("damage", ["runtime-guard", "wrong-authority", "open-delivery"])
def test_invalid_update_is_a_business_rejection_not_workflow_task_failure(damage):
    from temporalio.exceptions import ApplicationError
    from slk_temporal.contracts import StartSlkRequest
    from slk_temporal.continuity import RunContinuity
    from .test_contracts import runtime_guard_resolution_value
    run = RunSlkWorkflow()
    run._startup = StartSlkRequest.from_dict(start_value())
    run._continuity = RunContinuity(run._startup.run_id)
    if damage in {"runtime-guard", "wrong-authority"}:
        run._runtime_guard_blocker = {"event_id": "overwatcher-exit-a"}
    with pytest.raises(ApplicationError) as rejected:
        if damage == "wrong-authority":
            value = runtime_guard_resolution_value()
            value["supervisor_role_instance_id"] = "checker-a"
            run.resolve_runtime_guard(value)
        else:
            value = delivery_value()
            if damage == "open-delivery": value["undeclared"] = True
            run.request_delivery(value)
    assert rejected.value.non_retryable is True
    assert run._continuity.pending_delivery() is None


def test_empty_audit_wake_keeps_workflow_alive(monkeypatch):
    run = RunSlkWorkflow()
    clock = datetime(2026, 10, 4, tzinfo=timezone.utc)
    waits = []
    audits = []

    async def wait(predicate, *, timeout=None):
        nonlocal clock
        waits.append(timeout)
        if len(waits) == 1:
            clock += timedelta(seconds=timeout)
            raise asyncio.TimeoutError
        run.close_run("RUN_CLOSED")

    async def inspect():
        audits.append(clock)

    monkeypatch.setattr(workflows.workflow, "now", lambda: clock)
    monkeypatch.setattr(workflows.workflow, "wait_condition", wait)
    monkeypatch.setattr(run, "_inspect_overwatcher", inspect)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _: True)
    result = asyncio.run(run.run({"startup": start_value(), "startup_receipt": {}}))
    assert result["phase"] == "TERMINAL"
    assert len(audits) == 1
    assert len(waits) == 2


def test_audit_still_runs_while_waiting_for_recovery_ack(monkeypatch):
    run = RunSlkWorkflow()
    clock = datetime(2026, 10, 4, tzinfo=timezone.utc)
    waits, audits, activities = [], [], []
    start = start_value()
    start["ack_timeout_seconds"] = 2
    delivery = delivery_value()

    async def wait(predicate, *, timeout=None):
        nonlocal clock
        waits.append(timeout)
        if len(waits) == 1:
            run.request_delivery(delivery)
            return
        if len(waits) == 4:
            run.native_started(ack_value())
            run.close_run("RUN_CLOSED")
            return
        assert timeout is not None, "recovery wait must not disable the runtime clock"
        clock += timedelta(seconds=timeout)
        raise asyncio.TimeoutError

    async def activity(name, value, **kwargs):
        activities.append(name)
        return {"status": "DELIVERED" if name == "slk.deliver_message" else "RECOVERY_REQUESTED",
                "operation_id": delivery["operation_id"], "receipt_sha256": "a" * 64}

    async def inspect():
        audits.append(clock)

    monkeypatch.setattr(workflows.workflow, "now", lambda: clock)
    monkeypatch.setattr(workflows.workflow, "wait_condition", wait)
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _: True)
    monkeypatch.setattr(run, "_inspect_overwatcher", inspect)
    result = asyncio.run(run.run({"startup": start, "startup_receipt": {}}))
    assert result["phase"] == "TERMINAL"
    assert len(audits) == 1
    assert activities == ["slk.deliver_message", "slk.request_recovery"]


def test_later_runtime_alarm_does_not_crash_an_already_guarded_run():
    run = RunSlkWorkflow()
    run._startup = workflows.StartSlkRequest.from_dict(start_value())
    first = run._set_runtime_guard(event_id="first", kind="OVERWATCHER_AUDIT_FAILED", role_instance_id="ow-a")
    second = run._set_runtime_guard(event_id="second", kind="OVERWATCHER_ACTIVITY_ANOMALY", role_instance_id="ow-a")
    assert run._runtime_guard_blocker == first  # retain original repair identity
    assert second["event_id"] == "second"  # new fact remains reportable


def test_notification_string_is_not_native_supervisor_wake_proof(monkeypatch):
    run = RunSlkWorkflow()
    run._startup = workflows.StartSlkRequest.from_dict(start_value())
    run._continuity = workflows.RunContinuity(run._startup.run_id)
    async def activity(*a, **kw):
        return {"status": "NOTIFIED", "event_id": "notice-a", "receipt_sha256": "a" * 64}
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _: True)
    assert asyncio.run(run._notify_supervisor({"run_id": run._startup.run_id, "event_id": "notice-a"})) is False
    assert run._runtime_guard_blocker["kind"] == "SUPERVISOR_NOTIFICATION_UNPROVED"
    assert run._notification_failure["event_id"] == "notice-a"
    with pytest.raises(ApplicationError, match="runtime guard"):
        run.request_delivery(delivery_value())


@pytest.mark.parametrize("corruption", ["empty", "wrong_run", "wrong_cycle", "hash_only", "unknown",
                                      "invalid_hash", "boolean_cycle"])
def test_invalid_audit_is_guarded_and_reported_not_a_workflow_crash(monkeypatch, corruption):
    run = RunSlkWorkflow()
    run._startup = workflows.StartSlkRequest.from_dict(start_value())
    notices = []
    async def inspect(name, value, **kwargs):
        receipt = {"status": "CLEAR", "run_id": value["run_id"],
                   "overwatcher_role_instance_id": value["overwatcher_role_instance_id"],
                   "audit_cycle": value["audit_cycle"], "evidence_sha256": "b" * 64,
                   "receipt_sha256": "a" * 64}
        if corruption == "empty":
            return {}
        if corruption == "wrong_run":
            receipt["run_id"] = "another-run"
        if corruption == "wrong_cycle":
            receipt["audit_cycle"] = 0
        if corruption == "hash_only":
            receipt.pop("evidence_sha256")
        if corruption == "unknown":
            receipt["status"] = "UNKNOWN"
        if corruption == "invalid_hash":
            receipt["evidence_sha256"] = "not-evidence"
        if corruption == "boolean_cycle":
            receipt["audit_cycle"] = True
        return receipt
    async def notify(value):
        notices.append(value)
    monkeypatch.setattr(workflows.workflow, "execute_activity", inspect)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _: True)
    monkeypatch.setattr(run, "_notify_supervisor", notify)
    asyncio.run(run._inspect_overwatcher())
    assert run._runtime_guard_blocker is not None
    assert notices[0]["kind"] == "OVERWATCHER_AUDIT_FAILED"
