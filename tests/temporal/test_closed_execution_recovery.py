"""Closed native execution is not readiness; maintenance never replays work."""

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pytest.importorskip("temporalio")
from temporalio.client import WorkflowExecutionStatus
from slk_temporal import inspector, standard_adapter, workflows
from .test_contracts import start_value, delivery_value, ack_value


def test_recovery_materialization_versions_host_and_config_without_touching_source(tmp_path):
    from slk_temporal.recovery_client import materialize_bindings
    def write(name, value):
        path = tmp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return {"path": str(path), "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest()}
    source_host = {"run_id": "RUN-A", "plan_revision": 7, "roles": {"supervisor": "unchanged"},
                   "temporal": {"attempt_root": "exact-original", "client_command": [sys.executable],
                                "workflow_identity_path": "old", "workflow_identity_sha256": "a" * 64}}
    host = write("old-host.json", source_host)
    config = write("old-config.json", {"run_id": "RUN-A", "role_host_binding": host, "unchanged": True})
    identity = {"schema_version": "slk.temporal-workflow-identity/v1", "run_id": "RUN-A",
                "start_run_id": "new-parent", "run_run_id": "new-child"}
    request = {"run_id": "RUN-A", "source_host": host, "source_config": config,
               "evidence_root": str(tmp_path / "versioned")}
    result = materialize_bindings(request, identity)
    new_host = json.loads(__import__("pathlib").Path(result["role_host"]["path"]).read_text())
    new_config = json.loads(__import__("pathlib").Path(result["adapter_config"]["path"]).read_text())
    assert {k: v for k, v in new_host.items() if k != "temporal"} == {k: v for k, v in source_host.items() if k != "temporal"}
    assert new_host["temporal"]["workflow_identity_path"] == result["identity"]["path"]
    assert new_config["role_host_binding"] == result["role_host"]
    assert json.loads(__import__("pathlib").Path(host["path"]).read_text()) == source_host
    assert materialize_bindings(request, identity) == result


def test_restore_request_rejects_unknown_field_and_wrong_supervisor_before_rpc(tmp_path):
    from slk_temporal.recovery_client import validate_request
    with pytest.raises(ValueError, match="closed"):
        validate_request({"schema_version": "slk.temporal-execution-recovery/v1", "Owner": "pretend"})


def test_recovery_start_never_reads_files_during_workflow_replay(monkeypatch):
    from slk_temporal import recovery_client
    from slk_temporal.continuity import RunContinuity
    from slk_temporal.contracts import DeliveryRequest
    source = workflows.RunSlkWorkflow()
    source._startup = workflows.StartSlkRequest.from_dict(start_value())
    source._continuity = RunContinuity(source._startup.run_id)
    source._continuity.request_delivery(DeliveryRequest.from_dict(delivery_value()))
    source._delivery_started.add(delivery_value()["operation_id"])
    source._admitted = True
    async def activity(name, value, **options):
        assert name == "slk.prepare_run"
        return {"status": "RECOVERY_READY", "checkpoint": source.recovery_checkpoint(),
                "recovery_request_sha256": "a" * 64, "source_run_id": "source-native-run"}
    class Child:
        def __await__(self):
            async def result(): return {"phase": "TERMINAL"}
            return result().__await__()
    async def start_child(function, value, **options):
        assert options["id"] == "slk-run-RUN-A-recovery-source-native-run"
        assert value["recovery_checkpoint"] == source.recovery_checkpoint()
        return Child()
    monkeypatch.setattr(recovery_client, "read_proof", lambda *args, **kwargs: pytest.fail("file IO in workflow"))
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "start_child_workflow", start_child)
    result = asyncio.run(workflows.StartSlkWorkflow().run({"recovery": {"source_identity": "not read here"}}))
    assert result["phase"] == "TERMINAL"


def test_checkpoint_retains_completed_operation_and_pending_without_replaying():
    from slk_temporal.continuity import RunContinuity
    from slk_temporal.contracts import DeliveryRequest, NativeStartAck
    state = RunContinuity("RUN-A")
    first = DeliveryRequest.from_dict(delivery_value())
    state.request_delivery(first)
    state.acknowledge(NativeStartAck.from_dict(ack_value()))
    second = {**delivery_value(), "operation_id": "second", "message_id": "message-second"}
    state.request_delivery(DeliveryRequest.from_dict(second))
    state.record_delivery_result("second", "TOOL_ERROR:ActivityError")
    state.mark_timeout("second")
    packet = state.checkpoint()
    restored = RunContinuity.from_checkpoint(packet)
    assert restored.checkpoint() == packet
    assert restored.request_delivery(first) == "DELIVERY_ACKNOWLEDGED"
    assert restored.pending_delivery().to_dict() == second
    with pytest.raises(ValueError, match="duplicate"):
        restored.request_delivery(DeliveryRequest.from_dict({**first.to_dict(), "payload_sha256": "9" * 64}))
    with pytest.raises(ValueError):
        RunContinuity.from_checkpoint({**packet, "extra": True})


def test_restored_workflow_only_waits_for_original_ack_not_an_activity(monkeypatch):
    from slk_temporal.continuity import RunContinuity
    from slk_temporal.contracts import DeliveryRequest
    run = workflows.RunSlkWorkflow()
    run._startup = workflows.StartSlkRequest.from_dict(start_value())
    run._continuity = RunContinuity(run._startup.run_id)
    run._continuity.request_delivery(DeliveryRequest.from_dict(delivery_value()))
    run._continuity.mark_timeout(delivery_value()["operation_id"])
    run._delivery_started.add(delivery_value()["operation_id"])
    run._recovery_started.add(delivery_value()["operation_id"])
    run._admitted = True
    checkpoint = run.recovery_checkpoint()
    restored = workflows.RunSlkWorkflow()
    monkeypatch.setattr(workflows.workflow, "info", lambda: SimpleNamespace(
        workflow_id="slk-run-RUN-A-recovery-source", task_queue=run._startup.task_queue,
        parent=SimpleNamespace(workflow_id="slk-start-RUN-A-recovery-source")))
    monkeypatch.setattr(workflows.workflow, "now", lambda: datetime(2026, 10, 9, tzinfo=timezone.utc))
    monkeypatch.setattr(workflows.workflow, "patched", lambda _name: True)
    async def activity(*_args, **_kwargs): pytest.fail("restore must not replay an activity")
    async def wait(predicate, *, timeout=None):
        assert restored.status()["phase"] == "RECOVERY_REQUIRED"
        restored.native_started(ack_value())
        restored.close_run("RUN_CLOSED")
        assert predicate()
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "wait_condition", wait)
    result = asyncio.run(restored.run({"startup": start_value(), "recovery_checkpoint": checkpoint}))
    assert result["phase"] == "TERMINAL"


def test_restored_ack_wait_keeps_existing_runtime_guard_checks(monkeypatch):
    from slk_temporal.continuity import RunContinuity
    from slk_temporal.contracts import DeliveryRequest
    source = workflows.RunSlkWorkflow()
    source._startup = workflows.StartSlkRequest.from_dict(start_value())
    source._continuity = RunContinuity(source._startup.run_id)
    source._continuity.request_delivery(DeliveryRequest.from_dict(delivery_value()))
    source._delivery_started.add(delivery_value()["operation_id"])
    source._admitted = True
    restored = workflows.RunSlkWorkflow()
    clock = datetime(2026, 10, 9, tzinfo=timezone.utc)
    monkeypatch.setattr(workflows.workflow, "now", lambda: clock)
    monkeypatch.setattr(workflows.workflow, "info", lambda: SimpleNamespace(
        workflow_id="slk-run-RUN-A-recovery-source", task_queue=source._startup.task_queue,
        parent=SimpleNamespace(workflow_id="slk-start-RUN-A-recovery-source")))
    checks = []
    async def runtime_checks():
        checks.append(True)
        restored._set_runtime_guard(event_id="ow-failed", kind="OVERWATCHER_AUDIT_FAILED",
                                    role_instance_id="overwatcher-a")
        restored.native_started(ack_value())
        restored.close_run("RUN_CLOSED")
    async def wait(predicate, *, timeout=None):
        assert timeout is not None, "restored ACK wait must not disable runtime timers"
        raise asyncio.TimeoutError
    monkeypatch.setattr(restored, "_perform_runtime_checks", runtime_checks)
    monkeypatch.setattr(workflows.workflow, "wait_condition", wait)
    result = asyncio.run(restored.run({"startup": start_value(), "recovery_checkpoint": source.recovery_checkpoint()}))
    assert result["phase"] == "TERMINAL" and checks == [True]


def test_recovery_child_cannot_bypass_admission_without_recovery_parent(monkeypatch):
    from slk_temporal.continuity import RunContinuity
    from slk_temporal.contracts import DeliveryRequest
    source = workflows.RunSlkWorkflow()
    source._startup = workflows.StartSlkRequest.from_dict(start_value())
    source._continuity = RunContinuity(source._startup.run_id)
    source._continuity.request_delivery(DeliveryRequest.from_dict(delivery_value()))
    source._delivery_started.add(delivery_value()["operation_id"])
    source._admitted = True
    monkeypatch.setattr(workflows.workflow, "info", lambda: SimpleNamespace(parent=None))
    monkeypatch.setattr(workflows.workflow, "now", lambda: datetime(2026, 10, 9, tzinfo=timezone.utc))
    async def activity(*args, **kwargs): pytest.fail("unbound restore cannot run activities")
    async def wait(*args, **kwargs): pytest.fail("unbound restore cannot wait as admitted")
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "wait_condition", wait)
    with pytest.raises(Exception, match="recovery parent"):
        asyncio.run(workflows.RunSlkWorkflow().run({"startup": start_value(),
                                                   "recovery_checkpoint": source.recovery_checkpoint()}))


def test_central_recovery_rejects_actual_closed_projection_before_auth(monkeypatch):
    from slk_temporal import recovery_client
    startup = workflows.StartSlkRequest.from_dict(start_value())
    projection = {"summary": {"run_id": startup.run_id, "state": "closed", "closure_state": "closed",
                               "closed_at": "2026-10-09T00:00:00Z"},
        "runtime_snapshot": {"method_version": "4.4.2", "plan_revision": 7, "runtime_revision": 339,
                             "token_holder_role_instance_id": "worker-a"},
        "roles": [{"role": role.role, "role_instance_id": role.role_instance_id, "lifecycle": "active"}
                  for role in startup.roles]}
    monkeypatch.setattr(standard_adapter, "_query", lambda config: projection)
    monkeypatch.setattr(standard_adapter, "_run_json", lambda *a, **k: pytest.fail("closed Run must reject before auth"))
    with pytest.raises(ValueError, match="central"):
        recovery_client._central({"transport_command": ["test"], "role_host_binding": {"path": "x", "sha256": "a" * 64},
                                  "state_config_path": "x"}, startup, {"continuity": {"pending": {"delivery": delivery_value()}}},
                                 {"plan_revision": 7})


@pytest.mark.parametrize("status", [WorkflowExecutionStatus.FAILED,
    WorkflowExecutionStatus.COMPLETED, WorkflowExecutionStatus.CANCELED,
    WorkflowExecutionStatus.TERMINATED, WorkflowExecutionStatus.TIMED_OUT, None])
def test_inspector_rejects_closed_or_unknown_description_before_historical_query(monkeypatch, status):
    calls = []
    class Handle:
        def __init__(self, run_id): self.run_id = run_id
        async def describe(self):
            return SimpleNamespace(run_id=self.run_id, task_queue="slk-test", status=status,
                close_time=datetime(2026, 10, 8, tzinfo=timezone.utc))
        async def query(self, _query):
            calls.append("query")
            return {"run_id": "RUN-A", "child_workflow_id": "slk-run-RUN-A",
                    "startup_fingerprint": "a" * 64}
    class Client:
        @staticmethod
        async def connect(_address): return Client()
        def get_workflow_handle(self, _id, *, run_id): return Handle(run_id)
    monkeypatch.setattr(inspector, "Client", Client)
    with pytest.raises(RuntimeError, match="not running"):
        asyncio.run(inspector.inspect_pair(address="localhost:7233", run_id="RUN-A",
            task_queue="slk-test", start_workflow_id="slk-start-RUN-A", start_run_id="start-a",
            run_workflow_id="slk-run-RUN-A", run_run_id="run-a", startup_fingerprint="a" * 64))
    assert calls == []


def test_command_failure_keeps_real_exit_stdout_stderr():
    stdout = json.dumps({"status": "failed", "error": {"code": "EXACT_FAILURE"}})
    with pytest.raises(RuntimeError) as rejected:
        standard_adapter._run_json([sys.executable], ["-c",
            f"import sys; print({stdout!r}); print('exact stderr', file=sys.stderr); sys.exit(2)"])
    evidence = rejected.value.evidence
    assert evidence["exit_code"] == 2
    assert json.loads(evidence["stdout"])["error"]["code"] == "EXACT_FAILURE"
    assert evidence["stderr"].strip() == "exact stderr"
    assert evidence["responsibility"] == "STANDARD_ADAPTER_COMMAND"


def test_worker_binding_reports_actual_imported_sources_without_starting():
    from slk_temporal import worker
    binding = worker.binding_metadata("127.0.0.1:7233", "isolated", "slk_temporal.standard_adapter")
    assert binding["task_queue"] == "isolated"
    assert binding["pid"] == __import__("os").getpid()
    assert binding["workflow_source"]["path"].endswith("workflows.py")
    assert binding["adapter_source"]["path"].endswith("standard_adapter.py")
    assert len(binding["workflow_source"]["sha256"]) == 64


def test_failed_recovery_activity_blocks_and_reports_without_killing_workflow(monkeypatch):
    run = workflows.RunSlkWorkflow()
    start = start_value()
    notices = []
    waits = []
    clock = datetime(2026, 10, 9, tzinfo=timezone.utc)
    monkeypatch.setattr(workflows.workflow, "now", lambda: clock)
    monkeypatch.setattr(workflows.workflow, "patched",
        lambda name: name != "slk-4.4.2-two-stage-admission")
    async def execute(name, value, **_kwargs):
        if name == "slk.deliver_message":
            return {"status": "FAILED", "operation_id": value["operation_id"],
                    "receipt_sha256": "d" * 64}
        if name == "slk.request_recovery":
            raise RuntimeError("real recovery inspection failed")
        pytest.fail(name)
    async def notify(value):
        notices.append(value)
        return True
    async def wait(predicate, *, timeout=None):
        nonlocal clock
        waits.append(timeout)
        if len(waits) == 1:
            run.request_delivery(delivery_value())
        elif len(waits) == 2:
            clock += timedelta(seconds=start["ack_timeout_seconds"])
            raise asyncio.TimeoutError
        else:
            assert run.status()["phase"] == "BLOCKED"
            assert run.status()["runtime_guard_blocker"] is not None
            run.native_started(ack_value())
            run.close_run("RUN_CLOSED")
        assert predicate()
    monkeypatch.setattr(workflows.workflow, "execute_activity", execute)
    monkeypatch.setattr(workflows.workflow, "wait_condition", wait)
    monkeypatch.setattr(run, "_notify_supervisor", notify)
    result = asyncio.run(run.run({"startup": start, "startup_receipt": {}}))
    assert result["phase"] == "TERMINAL"
    assert len(notices) == 1
    assert notices[0]["kind"] == "RECOVERY_ACTIVITY_FAILED"
    assert run.status()["recovery_failure"]["reason"] == "real recovery inspection failed"
