"""Pause is an execution gate, not a new engineering state machine."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("temporalio")
from slk_temporal import workflows
from slk_temporal.checkpoint import validate_checkpoint
from .test_contracts import start_value, delivery_value, ack_value


def prepared(monkeypatch):
    run = workflows.RunSlkWorkflow()
    run._startup = workflows.StartSlkRequest.from_dict(start_value())
    run._continuity = workflows.RunContinuity("RUN-A")
    run._admitted = True
    monkeypatch.setattr(workflows.workflow, "now", lambda: datetime(2026, 10, 10, tzinfo=timezone.utc))
    return run


def change(phase, event_id=None):
    return {"run_id": "RUN-A", "supervisor_role_instance_id": "supervisor-a",
            "pause_id": "pause-1", "event_id": event_id or phase.lower(), "phase": phase}


def test_requested_fences_new_work_but_keeps_original_delivery_and_ack(monkeypatch):
    run = prepared(monkeypatch)
    run.request_delivery(delivery_value())
    assert run.set_run_pause(change("REQUESTED")) == "REQUESTED"
    assert run.request_delivery(delivery_value()) == "DELIVERY_REQUESTED"
    with pytest.raises(Exception, match="pause"):
        run.request_delivery({**delivery_value(), "operation_id": "new", "message_id": "new",
                              "sender_role_instance_id": "supervisor-a"})
    run.native_started(ack_value())
    assert run.request_delivery(delivery_value()) == "DELIVERY_ACKNOWLEDGED"
    assert run.status()["pending_operation_id"] is None
    with pytest.raises(Exception, match="Supervisor"):
        run.set_run_pause({**change("PAUSED"), "supervisor_role_instance_id": "worker-a"})


def test_pause_clock_preserves_twenty_plus_ten_and_keeps_ow_audits(monkeypatch):
    run = prepared(monkeypatch)
    base = datetime(2026, 10, 10, tzinfo=timezone.utc)
    clock = base
    monkeypatch.setattr(workflows.workflow, "now", lambda: clock)
    run.request_delivery(delivery_value()); run.native_started(ack_value())
    clock += timedelta(minutes=20)
    run.set_run_pause(change("REQUESTED")); run.set_run_pause(change("PAUSED"))
    run._next_overwatcher_audit_at = clock + timedelta(minutes=20)
    notices, audits = [], []
    async def notify(value): notices.append(value)
    async def inspect(): audits.append(clock)
    monkeypatch.setattr(run, "_notify_supervisor", notify)
    monkeypatch.setattr(run, "_inspect_overwatcher", inspect)
    clock += timedelta(minutes=60)
    asyncio.run(run._perform_runtime_checks())
    assert len(audits) == 1 and notices == []
    run.set_run_pause(change("RESUMED"))
    assert run._member_residency_since == base + timedelta(minutes=60)
    clock += timedelta(minutes=10)
    asyncio.run(run._perform_runtime_checks())
    assert len(notices) == 1 and notices[0]["kind"] == "MEMBER_RESIDENCY_EXCEEDED"
    assert run.set_run_pause(change("RESUMED")) == "RESUMED"


def test_paused_idle_checkpoint_roundtrips_without_fake_pending_or_reset_guard(monkeypatch):
    run = prepared(monkeypatch)
    run.set_run_pause(change("REQUESTED")); run.set_run_pause(change("PAUSED"))
    run._runtime_guard_blocker = {"event_id": "guard", "kind": "OW_EXIT", "run_id": "RUN-A",
        "responsible_role_instance_id": "supervisor-a", "source_operation_id": "guard-source", "threshold_seconds": 0}
    packet = run.recovery_checkpoint()
    assert packet["schema_version"] == "slk.temporal-execution-checkpoint/v2"
    validate_checkpoint(packet)
    restored = prepared(monkeypatch)
    restored._restore_checkpoint(packet)
    assert restored.recovery_checkpoint() == packet
    assert restored._restored_pending_operation is None
    restored.set_run_pause(change("RESUMED"))
    assert restored._runtime_guard_blocker == run._runtime_guard_blocker
    with pytest.raises(Exception, match="guard"):
        restored.request_delivery(delivery_value())


def test_requested_time_is_not_deducted_and_role_change_never_deducts_before_start(monkeypatch):
    run = prepared(monkeypatch)
    base = datetime(2026, 10, 10, tzinfo=timezone.utc)
    clock = base
    monkeypatch.setattr(workflows.workflow, "now", lambda: clock)
    run.set_run_pause(change("REQUESTED"))
    clock += timedelta(minutes=20)
    run.set_run_pause(change("PAUSED"))
    clock += timedelta(minutes=40)
    run._responsible_role_instance_id = "checker-a"
    run._responsibility_operation_id = "new-responsibility"
    run._member_residency_since = clock
    clock += timedelta(minutes=20)
    run.set_run_pause(change("RESUMED"))
    assert run._member_residency_since == clock


def test_central_confirmed_time_survives_late_temporal_retry(monkeypatch):
    run = prepared(monkeypatch)
    base = workflows.workflow.now()
    run.request_delivery(delivery_value()); run.native_started(ack_value())
    monkeypatch.setattr(workflows.workflow, "now", lambda: base + timedelta(minutes=20))
    run.set_run_pause(change("REQUESTED"))
    monkeypatch.setattr(workflows.workflow, "now", lambda: base + timedelta(minutes=25))
    run.set_run_pause({**change("PAUSED"), "confirmed_at": (base + timedelta(minutes=20)).isoformat()})
    validate_checkpoint(run.recovery_checkpoint())
    monkeypatch.setattr(workflows.workflow, "now", lambda: base + timedelta(minutes=80))
    run.set_run_pause(change("RESUMED"))
    assert run._member_residency_since == base + timedelta(minutes=60)


def test_pause_cycle_ids_are_checkpoint_safe_and_never_reused(monkeypatch):
    run = prepared(monkeypatch)
    with pytest.raises(Exception, match="identity"):
        run.set_run_pause({**change("REQUESTED"), "pause_id": "invalid/id"})
    run.set_run_pause(change("REQUESTED")); run.set_run_pause(change("PAUSED")); run.set_run_pause(change("RESUMED"))
    with pytest.raises(Exception, match="identity"):
        run.set_run_pause(change("REQUESTED", "requested-again"))
    run.set_run_pause({**change("REQUESTED", "requested-2"), "pause_id": "pause-2"})
    validate_checkpoint(run.recovery_checkpoint())


def test_original_paused_receipt_roundtrips_without_inventing_lifecycle_or_ack(monkeypatch):
    run = prepared(monkeypatch)
    delivery = delivery_value()
    run.request_delivery(delivery)
    run._delivery_started.add(delivery["operation_id"])
    run._continuity.record_delivery_result(delivery["operation_id"], "PAUSED")
    packet = run.recovery_checkpoint()
    validate_checkpoint(packet)
    assert "run_pause" not in packet["status"]
    restored = prepared(monkeypatch)
    restored._restore_checkpoint(packet)
    assert restored._restored_pending_operation is None  # Not a physically started call awaiting ACK.
    restored.set_run_pause(change("REQUESTED"))
    assert restored.status()["run_pause"]["deferred_operation_id"] == delivery["operation_id"]
    restored.set_run_pause(change("PAUSED"))
    validate_checkpoint(restored.recovery_checkpoint())


@pytest.mark.parametrize("mode", ["deferred", "delivered-unacked", "central-before-temporal"])
def test_real_sdk_resume_partial_commit_keeps_original_queued_operation_and_replays(mode):
    from temporalio import activity
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker, Replayer
    import uuid

    async def scenario():
        central_paused = mode != "delivered-unacked"
        entered, release = asyncio.Event(), asyncio.Event()
        calls = {"delivery": 0, "native_starts": 0, "recovery": 0, "audits": 0}
        notices = []
        delivery = {**delivery_value(), **({"sender_role_instance_id": "supervisor-a"}
            if mode == "central-before-temporal" else {})}
        @activity.defn(name="slk.prepare_run")
        async def prepare(value):
            return {"status": "READY", "run_id": "RUN-A", "runtime_revision": start_value()["runtime_revision"],
                    "startup_fingerprint": value["startup_fingerprint"], "receipt_sha256": "a" * 64}
        @activity.defn(name="slk.deliver_message")
        async def deliver(value):
            if value["operation_id"] == "warmup":
                return {"status": "DELIVERED", "operation_id": "warmup", "receipt_sha256": "b" * 64}
            calls["delivery"] += 1
            entered.set()
            await release.wait()
            if central_paused:
                return {"status": "PAUSED", "operation_id": value["operation_id"], "receipt_sha256": "b" * 64}
            calls["native_starts"] += 1
            return {"status": "DELIVERED", "operation_id": value["operation_id"], "receipt_sha256": "b" * 64}
        @activity.defn(name="slk.request_recovery")
        async def recover(value):
            calls["recovery"] += 1
            raise AssertionError("authorized pause must not mechanically recover")
        @activity.defn(name="slk.inspect_overwatcher")
        async def audit(value):
            calls["audits"] += 1
            return {"status": "CLEAR", **{key: value[key] for key in ("run_id", "overwatcher_role_instance_id", "audit_cycle")},
                "evidence_sha256": "c" * 64, "receipt_sha256": "d" * 64}
        @activity.defn(name="slk.notify_supervisor")
        async def notify(value):
            notices.append(value)
            return {"status": "NOTIFIED", "event_id": value["event_id"], "receipt_sha256": "e" * 64}
        async with await WorkflowEnvironment.start_time_skipping() as env:
            queue = "pause-test-" + uuid.uuid4().hex
            async with Worker(env.client, task_queue=queue, workflows=[workflows.RunSlkWorkflow],
                              activities=[prepare, deliver, recover, audit, notify]):
                handle = await env.client.start_workflow(workflows.RunSlkWorkflow.run,
                    {"startup": start_value(), "admission_required": True}, id="pause-" + uuid.uuid4().hex, task_queue=queue)
                async def until(predicate):
                    for _ in range(100):
                        state = await handle.query("status")
                        if predicate(state): return state
                        await asyncio.sleep(.02)
                    raise AssertionError("pause state not reached")
                await until(lambda state: state["phase"] == "AWAITING_ADMISSION")
                await handle.execute_update("request_admission", {"run_id": "RUN-A",
                    "startup_fingerprint": workflows.StartSlkRequest.from_dict(start_value()).startup_fingerprint,
                    "workflow_identity_sha256": "9" * 64})
                await until(lambda state: state["admitted"])
                if mode == "central-before-temporal":
                    # Establish an existing member timer before the raced op.
                    await handle.execute_update("request_delivery", {**delivery_value(), "operation_id": "warmup", "message_id": "warmup-message"})
                    await handle.execute_update("native_started", {**ack_value(), "operation_id": "warmup", "message_id": "warmup-message"})
                await handle.execute_update("request_delivery", delivery)
                await asyncio.wait_for(entered.wait(), 10)
                if mode != "central-before-temporal":
                    await handle.execute_update("set_run_pause", change("REQUESTED"))
                release.set()
                if mode == "central-before-temporal":
                    for _ in range(100):
                        checkpoint = await handle.query("recovery_checkpoint")
                        if checkpoint["continuity"]["pending"]["delivery_result"] is not None: break
                        await asyncio.sleep(.02)
                    else: raise AssertionError("original central PAUSED receipt was not retained")
                    assert checkpoint["continuity"]["pending"]["delivery_result"] == "PAUSED"
                    assert "run_pause" not in checkpoint["status"]  # Never invent a Temporal pause update.
                    validate_checkpoint(checkpoint)
                    since = checkpoint["status"]["member_residency_since"]
                    await env.sleep(1801)  # Exceed ACK deadline, OW audit and original member notice threshold.
                    state = await until(lambda state: state["member_residency_notice_sent"])
                    assert state["member_residency_since"] == since
                    assert calls["audits"] >= 1 and len(notices) == 1
                    assert notices[0]["kind"] == "MEMBER_RESIDENCY_EXCEEDED"
                    assert calls["native_starts"] == calls["recovery"] == 0 and calls["delivery"] == 1
                    await handle.execute_update("set_run_pause", change("REQUESTED"))
                if mode == "delivered-unacked":
                    from temporalio.client import WorkflowUpdateFailedError
                    for _ in range(100):
                        checkpoint = await handle.query("recovery_checkpoint")
                        if checkpoint["continuity"]["pending"]["delivery_result"] == "DELIVERED": break
                        await asyncio.sleep(.02)
                    else: raise AssertionError("original native delivery did not complete")
                    central_paused = True  # Central confirmation can precede the native-start ACK suffix.
                    with pytest.raises(WorkflowUpdateFailedError) as rejected:
                        await handle.execute_update("set_run_pause", change("PAUSED"))
                    assert "unresolved native delivery" in str(rejected.value.cause)
                    state = await handle.query("status")
                    assert state["run_pause"]["phase"] == "REQUESTED"
                    assert state["pending_operation_id"] == delivery_value()["operation_id"]
                    assert await handle.execute_update("native_started", ack_value()) == "DELIVERY_ACKNOWLEDGED"
                    assert await handle.execute_update("set_run_pause", change("PAUSED")) == "PAUSED"
                    assert await handle.execute_update("set_run_pause", change("PAUSED")) == "PAUSED"
                    assert await handle.execute_update("request_delivery", delivery) == "DELIVERY_ACKNOWLEDGED"
                    assert calls["delivery"] == 1
                else:
                    await until(lambda state: state.get("run_pause", {}).get("deferred_operation_id") == delivery_value()["operation_id"])
                    await handle.execute_update("set_run_pause", change("PAUSED"))
                    await handle.execute_update("set_run_pause", change("RESUMED"))
                    await until(lambda state: state["run_pause"]["deferred_operation_id"] == delivery_value()["operation_id"])
                    assert calls["native_starts"] == 0 and calls["recovery"] == 0
                    central_paused = False
                    await handle.execute_update("set_run_pause", change("RESUMED"))
                    await until(lambda state: state["run_pause"]["deferred_operation_id"] is None)
                    await handle.execute_update("native_started", ack_value())
                assert calls["native_starts"] == 1 and calls["recovery"] == 0
                await handle.execute_update("close_run", "RUN_CLOSED")
                await handle.result()
                history = await handle.fetch_history()
            await Replayer(workflows=[workflows.RunSlkWorkflow]).replay_workflow(history)
    asyncio.run(scenario())
