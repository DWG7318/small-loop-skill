"""Replay pre-fix notification histories with the real SDK, no product service."""
import asyncio
import inspect
import sys
import types
import uuid

import pytest
pytest.importorskip("temporalio")
from temporalio import activity
from temporalio.worker import Worker, Replayer, UnsandboxedWorkflowRunner
from slk_temporal import workflows
from slk_temporal.contracts import StartSlkRequest
from .test_contracts import start_value, delivery_value, ack_value
from .test_workflows import _environment, prepare_run, deliver_message, request_recovery, inspect_overwatcher


@pytest.mark.asyncio
async def test_pre451_failed_notice_history_replays_without_new_retry_or_timer(tmp_path):
    name = "slk_temporal._pre451_replay_fixture"
    legacy = types.ModuleType(name)
    legacy.__package__ = "slk_temporal"
    sys.modules[name] = legacy
    source = inspect.getsource(workflows).replace('workflow.patched("slk-4.5.1-notification-truth")', 'False')
    source = source.replace('workflow.patched("slk-4.5.1-late-is-not-dead")', 'False')
    exec(compile(source, "pre451-workflow-fixture", "exec"), legacy.__dict__)
    notices = []
    @activity.defn(name="slk.notify_supervisor")
    async def failed_notice(value):
        notices.append(value)
        return {"status": "NOTIFIED"}  # accepted-only is deliberately unproved
    try:
        async with await _environment(tmp_path) as env:
            queue = "slk451-replay-" + uuid.uuid4().hex
            async with Worker(env.client, task_queue=queue, workflows=[legacy.RunSlkWorkflow],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activities=[prepare_run, deliver_message, request_recovery, inspect_overwatcher, failed_notice]):
                start = {**start_value(), "task_queue": queue}
                handle = await env.client.start_workflow(legacy.RunSlkWorkflow.run,
                    {"startup": start, "admission_required": True}, id=queue, task_queue=queue)
                await handle.execute_update("request_admission", {"run_id": start["run_id"],
                    "startup_fingerprint": StartSlkRequest.from_dict(start).startup_fingerprint,
                    "workflow_identity_sha256": "9" * 64})
                for _ in range(100):
                    if (await handle.query("status"))["admitted"]: break
                    await asyncio.sleep(.02)
                await handle.execute_update("request_delivery", delivery_value())
                for _ in range(100):
                    if (await handle.query("status"))["phase"] == "WAITING_NATIVE_STARTED": break
                    await asyncio.sleep(.02)
                await handle.execute_update("native_started", ack_value())
                await env.sleep(1801)
                for _ in range(100):
                    state = await handle.query("status")
                    if state["member_residency_notice_sent"]: break
                    await asyncio.sleep(.02)
                assert state["member_residency_notice_sent"] is True
                assert state["notification_failure"] is not None
                assert len(notices) == 1
                await handle.execute_update("close_run", "Owner accepted isolated replay evidence")
                await handle.result()
                history = await handle.fetch_history()
            await Replayer(workflows=[workflows.RunSlkWorkflow],
                workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(history)
    finally:
        sys.modules.pop(name, None)
