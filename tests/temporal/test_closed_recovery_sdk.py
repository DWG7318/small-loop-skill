"""Real existing-server SDK recovery. No product, native Agent or D1 dispatch."""
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import types
import uuid

import pytest
pytest.importorskip("temporalio")
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker, UnsandboxedWorkflowRunner
from slk_temporal import recovery_client as recovery, standard_adapter as adapter, workflows
from slk_temporal.contracts import StartSlkRequest
from .test_contracts import start_value, delivery_value, ack_value


async def scenario(tmp_path, monkeypatch, *, overdue=False):
    address = os.environ.get("SLK_TEMPORAL_TEST_ADDRESS")
    if not address: pytest.skip("existing Temporal server required; never provision a service")
    client = await Client.connect(address)
    run_id = "RUN-CLOSED-RECOVERY-TEST-" + uuid.uuid4().hex[:8]
    queue = "slk-closed-recovery-test-" + uuid.uuid4().hex[:10]
    start = {**start_value(), "run_id": run_id, "method_version": "4.4.2", "task_queue": queue,
             "ack_timeout_seconds": 1, "startup_idempotency_key": "start-" + run_id}
    calls = {"deliver": 0, "recover": 0, "prepare_recovery": 0}
    notices = []

    @activity.defn(name="slk.prepare_run")
    async def prepare(value):
        if "recovery" in value:
            calls["prepare_recovery"] += 1
            return await adapter.prepare_run(value)
        return {"status": "READY", "run_id": run_id, "runtime_revision": start["runtime_revision"],
                "startup_fingerprint": value["startup_fingerprint"], "receipt_sha256": "a" * 64}
    @activity.defn(name="slk.deliver_message")
    async def deliver(value):
        calls["deliver"] += 1
        return {"status": "DELIVERED", "operation_id": value["operation_id"], "receipt_sha256": "b" * 64}
    @activity.defn(name="slk.request_recovery")
    async def recover(value):
        calls["recover"] += 1
        raise ApplicationError("isolated legacy recovery inspection failed", non_retryable=True)
    @activity.defn(name="slk.inspect_overwatcher")
    async def audit(value):
        return {"status": "CLEAR", **value, "evidence_sha256": "c" * 64, "receipt_sha256": "d" * 64}
    @activity.defn(name="slk.notify_supervisor")
    async def notify(value):
        if not overdue: pytest.fail("short isolated recovery must not notify product or call a model")
        notices.append(value)
        raise ApplicationError("isolated overdue notice is unproved", non_retryable=True)
    activities = [prepare, deliver, recover, audit, notify]
    # Reproduce the exact old code path without its new patch marker. The source
    # pair is genuinely FAILED; the replacement uses production sandboxed code.
    legacy = types.ModuleType("slk_temporal._isolated_legacy_recovery")
    legacy.__file__ = workflows.__file__
    monkeypatch.setitem(sys.modules, legacy.__name__, legacy)
    source_code = Path(workflows.__file__).read_text(encoding="utf-8").replace(
        'workflow.patched("slk-4.4.2-recovery-failure-is-guard")', 'False')
    exec(compile(source_code, workflows.__file__, "exec"), legacy.__dict__)
    async def phase(handle, name):
        for _ in range(200):
            try:
                value = await handle.query("status")
                if value["phase"] == name: return value
            except Exception: pass
            await asyncio.sleep(.03)
        raise AssertionError("isolated workflow phase missing: " + name)
    async with Worker(client, task_queue=queue, workflows=[legacy.StartSlkWorkflow, legacy.RunSlkWorkflow],
                      activities=activities, workflow_runner=UnsandboxedWorkflowRunner()):
        parent = await client.start_workflow(legacy.StartSlkWorkflow.run, start,
                                            id="slk-start-" + run_id, task_queue=queue)
        child = client.get_workflow_handle("slk-run-" + run_id)
        await phase(child, "AWAITING_ADMISSION")
        await child.execute_update("request_admission", {"run_id": run_id,
            "startup_fingerprint": StartSlkRequest.from_dict(start).startup_fingerprint,
            "workflow_identity_sha256": "9" * 64})
        await phase(child, "IDLE")
        for index in range(11):
            delivery = {**delivery_value(), "run_id": run_id, "operation_id": f"prior-{index}", "message_id": f"prior-message-{index}"}
            await child.execute_update("request_delivery", delivery)
            await child.execute_update("native_started", {**ack_value(), "operation_id": delivery["operation_id"], "message_id": delivery["message_id"]})
            await phase(child, "IDLE")
        pending = {**delivery_value(), "run_id": run_id, "cell_id": "CELL-005", "source_runtime_revision": 338,
            "operation_id": "5f2d75da-2eb5-575b-a80b-bd3616765c00", "message_id": "4860108c-34e0-50b1-a1ec-51c33d04c88a",
            "sender_role_instance_id": "checker-a", "receiver_role_instance_id": "supervisor-a"}
        await child.execute_update("request_delivery", pending)
        try: await asyncio.wait_for(parent.result(), 10)
        except Exception: pass
        descriptions = await asyncio.gather(parent.describe(), child.describe())
        assert all(row.status == WorkflowExecutionStatus.FAILED and row.close_time is not None for row in descriptions)
        source = {"schema_version": "slk.temporal-workflow-identity/v1", "run_id": run_id, "address": address,
            "task_queue": queue, "start_workflow_id": descriptions[0].id, "start_run_id": descriptions[0].run_id,
            "run_workflow_id": descriptions[1].id, "run_run_id": descriptions[1].run_id,
            "startup_fingerprint": StartSlkRequest.from_dict(start).startup_fingerprint}
    def write(name, value):
        path = tmp_path / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8"); return path
    identity_path = write("identity.json", source)
    host = {"schema_version": "slk.role-host/v2", "run_id": run_id, "plan_revision": 7,
            "roles": {"same-test-roles": True}, "temporal": {
                "workflow_identity_path": str(identity_path), "workflow_identity_sha256": recovery.proof(identity_path)["sha256"]}}
    host_path = write("host.json", host)
    config = {"run_id": run_id, "role_host_binding": recovery.proof(host_path), "transport_command": ["isolated-authority-consumer"],
              "state_config_path": str(tmp_path / "isolated-state.json")}
    write("config/" + run_id + ".json", config)
    projection = {"summary": {"run_id": run_id, "state": "active", "closure_state": "open", "closed_at": None},
        "runtime_snapshot": {"method_version": "4.4.2", "plan_revision": 7, "runtime_revision": 339,
            "token_sequence": 110, "token_holder_role_instance_id": "checker-a"},
        "roles": [{"role": row["role"], "role_instance_id": row["role_instance_id"], "lifecycle": "active"} for row in start["roles"]],
        "preserved_d1": {"prior_pass": 11, "event": "247c0be8-a626-5447-a8fc-10ceb5d8ebcc", "verdict": "FAIL", "candidate_attempt": 2}}
    monkeypatch.setattr(adapter, "_load_config", lambda _: config)
    monkeypatch.setattr(adapter, "_query", lambda _: projection)
    monkeypatch.setattr(adapter, "_run_json", lambda *a, **k: {"status": "SUPERVISOR_RECOVERY_AUTHENTICATED", "run_id": run_id,
        "supervisor_role_instance_id": "supervisor-a", "runtime_revision": 339})
    if overdue:
        original_snapshot = recovery.source_snapshot
        old_since = (datetime.now(timezone.utc) - timedelta(hours=8)).isoformat()
        async def long_gap_source(identity):
            executions, checkpoint, histories = await original_snapshot(identity)
            # Only the isolated source clock boundary is a fixture: the SDK
            # server is not time-skipped and we do not wait eight real hours.
            # Both FAILED histories and the restored timers/notice are native.
            checkpoint = copy.deepcopy(checkpoint)
            checkpoint["status"].update(member_residency_since=old_since, notification_failure={
                "event_id": run_id + "-ow-audit-189", "reason": "SUPERVISOR_NOTIFICATION_UNPROVED"})
            return executions, checkpoint, histories
        monkeypatch.setattr(recovery, "source_snapshot", long_gap_source)
    async with Worker(client, task_queue=queue, workflows=[workflows.StartSlkWorkflow, workflows.RunSlkWorkflow], activities=activities):
        original_verify = recovery.verify_target
        async def verify_after_overdue_notice(request, identity, checkpoint, *, initial):
            if overdue and initial:
                live = client.get_workflow_handle(identity["run_workflow_id"], run_id=identity["run_run_id"])
                for _ in range(200):
                    if (await live.query("status"))["member_residency_notice_sent"]: break
                    await asyncio.sleep(.03)
                else: raise AssertionError("expired restored timer did not produce a notice")
            await original_verify(request, identity, checkpoint, initial=initial)
        monkeypatch.setattr(recovery, "verify_target", verify_after_overdue_notice)
        proof = await recovery.prepare(identity_path=identity_path, identity_sha256=recovery.proof(identity_path)["sha256"],
            config_root=tmp_path / "config", evidence_root=tmp_path / "versioned", reason="isolated approved repair", evidence_ref="isolated-Supervisor")
        result = await recovery.restore(request_path=Path(proof["path"]), request_sha256=proof["sha256"], config_root=tmp_path / "config")
        target = result["target_identity"]
        restored = client.get_workflow_handle(target["run_workflow_id"], run_id=target["run_run_id"])
        try:
            snapshot = await restored.query("recovery_checkpoint")
            assert snapshot["continuity"]["pending"]["delivery"] == pending
            assert len(snapshot["continuity"]["completed"]) == 11
            if overdue:
                old = json.loads(Path(json.loads(Path(proof["path"]).read_text())["checkpoint"]["path"]).read_text())
                assert snapshot["status"]["member_residency_since"] == old["status"]["member_residency_since"]
                assert snapshot["status"]["runtime_guard_blocker"]["kind"] == "SUPERVISOR_NOTIFICATION_UNPROVED"
                assert len(notices) == 1 and notices[0]["kind"] == "MEMBER_RESIDENCY_EXCEEDED"
                assert old["status"]["notification_failure"]["event_id"].endswith("-ow-audit-189")
            assert calls == {"deliver": 12, "recover": 1, "prepare_recovery": 1}
            assert await restored.execute_update("native_started", {**ack_value(), "operation_id": pending["operation_id"],
                "message_id": pending["message_id"], "receiver_role_instance_id": pending["receiver_role_instance_id"]}) == "DELIVERY_ACKNOWLEDGED"
            await phase(restored, "IDLE")
            projection["runtime_snapshot"].update(runtime_revision=340, token_sequence=111, token_holder_role_instance_id="supervisor-a")
            assert await recovery.restore(request_path=Path(proof["path"]), request_sha256=proof["sha256"], config_root=tmp_path / "config") == result
            assert projection["preserved_d1"]["prior_pass"] == 11 and projection["preserved_d1"]["verdict"] == "FAIL"
            assert calls == {"deliver": 12, "recover": 1, "prepare_recovery": 1}
        finally:
            await restored.execute_update("close_run", "ISOLATED_TEST_CLOSED")
            await client.get_workflow_handle(target["start_workflow_id"], run_id=target["start_run_id"]).result()


def test_real_sdk_closed_pair_recovers_checkpoint_and_acks_without_replay(tmp_path, monkeypatch):
    asyncio.run(asyncio.wait_for(scenario(tmp_path, monkeypatch), 60))


def test_real_sdk_long_closed_gap_preserves_time_and_accepts_new_notice(tmp_path, monkeypatch):
    asyncio.run(asyncio.wait_for(scenario(tmp_path, monkeypatch, overdue=True), 60))
