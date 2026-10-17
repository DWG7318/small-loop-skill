"""Real SDK histories prove the dedup patch changes only new executions."""
import inspect
import sys
import types
import uuid
import pytest

pytest.importorskip("temporalio")
from temporalio import activity
from temporalio.worker import Worker, Replayer, UnsandboxedWorkflowRunner
from slk_temporal import workflows
from .test_contracts import start_value, notification_value
from .test_workflows import _environment, _admit, prepare_run, deliver_message, request_recovery


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [True, False])
async def test_audit_history_replay_and_new_cause_dedup(tmp_path, legacy):
    name = "slk_temporal._pre455_replay_fixture"
    module = types.ModuleType(name)
    module.__package__ = "slk_temporal"
    sys.modules[name] = module
    source = inspect.getsource(workflows).replace(
        'workflow.patched("slk-4.5.5-audit-cause-dedup")', "False")
    exec(compile(source, "pre455-workflow-fixture", "exec"), module.__dict__)
    implementation = module.RunSlkWorkflow if legacy else workflows.RunSlkWorkflow
    audits, notices = [], []
    @activity.defn(name="slk.inspect_overwatcher")
    async def audit(value):
        audits.append(value)
        return {"status": "EXITED",
                **{k: value[k] for k in ("run_id", "overwatcher_role_instance_id", "audit_cycle")},
                **({} if legacy else {"alarm_key": "c" * 64}),
                "evidence_sha256": "a" * 64, "receipt_sha256": "b" * 64}
    @activity.defn(name="slk.notify_supervisor")
    async def notify(value):
        notices.append(value)
        return notification_value(value["event_id"], value["run_id"])
    try:
        async with await _environment(tmp_path) as env:
            queue = "slk455-replay-" + uuid.uuid4().hex
            async with Worker(env.client, task_queue=queue, workflows=[implementation],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                    activities=[prepare_run, deliver_message, request_recovery, audit, notify]):
                start = {**start_value(), "method_version": "4.5.4" if legacy else "4.5.5", "task_queue": queue}
                handle = await env.client.start_workflow(implementation.run,
                    {"startup": start, "admission_required": True}, id=queue, task_queue=queue)
                await _admit(handle, env, start)
                for _ in range(3):
                    await env.sleep(1201)
                assert len(audits) == 3
                assert len(notices) == (3 if legacy else 1)
                await handle.execute_update("close_run", "isolated audit test complete")
                await handle.result()
                history = await handle.fetch_history()
            await Replayer(workflows=[workflows.RunSlkWorkflow],
                workflow_runner=UnsandboxedWorkflowRunner()).replay_workflow(history)
    finally:
        sys.modules.pop(name, None)

