"""450 wiring simulations; no real native Session or Temporal service is touched."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path

import pytest

pytest.importorskip("temporalio")

from slk_temporal import standard_adapter, delivery_client
from slk_temporal.contracts import StartSlkRequest
from slk_temporal.workflows import RunSlkWorkflow
from .test_standard_adapter import config_root, write_json, RUN_ID
from .test_contracts import start_value, overwatcher_exit_value, runtime_guard_resolution_value
from .test_delivery_client import identity


def native_config(tmp_path, method_version="4.5.0"):
    root, config = config_root(tmp_path, method_version)
    config["schema_version"] = "slk.temporal-standard-adapter/v2"
    ow = config["overwatcher_activity"]
    # Static config loading deliberately does not parse private native originals.
    proof = write_json(tmp_path / "proof.json", {"schema_version": "slk.subagent-overwatcher-proof/v1",
        "method_version": method_version, "run_id": RUN_ID, "role_instance_id": ow["role_instance_id"],
        "endpoint_ref": ow["endpoint_ref"], "started_sha256": standard_adapter._sha256(Path(ow["started_path"]))})
    ow.update(attestation_path=str(proof), attestation_sha256=standard_adapter._sha256(proof))
    write_json(root / f"{RUN_ID}.json", config)
    standard_adapter.configure(root)
    return root, config


@pytest.mark.parametrize("method_version", ["4.5.0", "4.5.1", "4.5.2", "4.5.3", "4.5.4", "4.5.5"])
def test_450_config_load_is_static_and_requires_native_v2(tmp_path, monkeypatch, method_version):
    root, config = native_config(tmp_path, method_version)
    monkeypatch.setattr(standard_adapter, "_run_json", lambda *_a, **_k: pytest.fail("config load must be static"))
    assert standard_adapter._load_config(RUN_ID)["method_version"] == method_version
    assert standard_adapter._load_bootstrap_config(RUN_ID)["method_version"] == method_version
    config["schema_version"] = "slk.temporal-standard-adapter/v1"
    config["overwatcher_activity"].pop("attestation_path")
    config["overwatcher_activity"].pop("attestation_sha256")
    write_json(root / f"{RUN_ID}.json", config)
    with pytest.raises(ValueError): standard_adapter._load_config(RUN_ID)


def test_config_and_bootstrap_reject_unpublished_method(tmp_path):
    native_config(tmp_path, "4.5.6")
    with pytest.raises(ValueError, match="not closed"):
        standard_adapter._load_config(RUN_ID)
    with pytest.raises(ValueError, match="not closed"):
        standard_adapter._load_bootstrap_config(RUN_ID)


@pytest.mark.parametrize("field,value", [("schema_version", "slk.desktop-overwatcher-attestation/v1"),
    ("method_version", "4.4.5"), ("run_id", "other"), ("role_instance_id", "other"),
    ("endpoint_ref", "other"), ("started_sha256", "1" * 64)])
def test_450_static_proof_correlation_rejects_drift(tmp_path, field, value):
    root, config = native_config(tmp_path)
    ow = config["overwatcher_activity"]
    proof = Path(ow["attestation_path"])
    write_json(proof, {**json.loads(proof.read_text()), field: value})
    ow["attestation_sha256"] = standard_adapter._sha256(proof)
    write_json(root / f"{RUN_ID}.json", config)
    with pytest.raises(ValueError): standard_adapter._load_config(RUN_ID)


@pytest.mark.parametrize("native,cadence,expected", [("ACTIVE", "CURRENT", "CLEAR"),
    ("ACTIVE", "CONTINUITY_UNPROVEN", "ANOMALY"), ("UNKNOWN", "CURRENT", "ANOMALY"),
    ("COMPLETED_WITHOUT_TERMINAL", "CONTINUITY_UNPROVEN", "EXITED"),
    ("FAILED_WITHOUT_TERMINAL", "CURRENT", "EXITED")])
@pytest.mark.parametrize("method_version", ["4.5.0", "4.5.1", "4.5.2", "4.5.3", "4.5.4", "4.5.5"])
def test_450_audit_uses_one_projection_native_proof_and_retains_small_hashed_evidence(tmp_path, monkeypatch, native, cadence, expected, method_version):
    _, config = native_config(tmp_path, method_version)
    ow = config["overwatcher_activity"]
    calls, queries = [], []
    projection = {"summary": {"run_id": RUN_ID}, "marker": "fresh"}
    monkeypatch.setattr(standard_adapter, "_query", lambda _c: queries.append(1) or projection)
    def run(_command, arguments, **_kwargs):
        calls.append(arguments)
        source = Path(arguments[arguments.index("--runtime-projection") + 1])
        assert json.loads(source.read_text()) == projection
        if arguments[0] == "inspect-native-activity":
            assert "--desktop-overwatcher-attestation" not in arguments
            assert arguments[arguments.index("--subagent-overwatcher-proof") + 1] == ow["attestation_path"]
            return {"status": native, "error": "NATIVE_ACTIVITY_STALE" if native == "UNKNOWN" else None,
                "observation_sequence": len(calls)}
        return {"schema_version": "slk.overwatcher-cadence-inspection/v1", "status": cadence,
            "run_id": RUN_ID, "overwatcher_role_instance_id": "ow-a", "latest_cycle_id": "cycle-a",
            "cadence_seconds": 600, "elapsed_seconds": 20}
    monkeypatch.setattr(standard_adapter, "_run_json", run)
    request = {"run_id": RUN_ID, "overwatcher_role_instance_id": "ow-a", "endpoint_ref": "ow-endpoint-a", "audit_cycle": 1}
    result = asyncio.run(standard_adapter.inspect_overwatcher(request))
    assert result["status"] == expected and len(queries) == 1
    expected_fields = {"status", "run_id", "overwatcher_role_instance_id", "audit_cycle", "evidence_sha256", "receipt_sha256"}
    if method_version == "4.5.5":
        expected_fields.add("alarm_key")
        assert len(result["alarm_key"]) == 64
        int(result["alarm_key"], 16)
    assert set(result) == expected_fields
    evidence = Path(config["notification_attempt_root"]) / RUN_ID / "overwatcher-audits" / (result["evidence_sha256"] + ".json")
    assert standard_adapter._receipt(json.loads(evidence.read_text())) == result["evidence_sha256"]
    # Another observation in the same audit cycle may retain different evidence.
    repeated = asyncio.run(standard_adapter.inspect_overwatcher(request))
    assert repeated["status"] == expected and repeated["evidence_sha256"] != result["evidence_sha256"]
    assert evidence.is_file()
    assert (evidence.parent / (repeated["evidence_sha256"] + ".json")).is_file()
    if method_version == "4.5.5":
        assert repeated["alarm_key"] == result["alarm_key"]


@pytest.mark.parametrize("method,expected", [(version, "OVERWATCHER_EXIT_REQUIRES_SUPERVISOR_CONFIRMATION") for version in ("4.5.0", "4.5.1", "4.5.2", "4.5.3", "4.5.4", "4.5.5")] + [("4.4.5", "OVERWATCHER_AUDIT_FAILED")])
def test_workflow_accepts_exited_only_from_immutable_450_startup(monkeypatch, method, expected):
    from slk_temporal import workflows
    instance = RunSlkWorkflow()
    instance._startup = StartSlkRequest.from_dict({**start_value(), "method_version": method})
    notices = []
    async def activity(_name, value, **_kwargs):
        return {"status": "EXITED", **{key: value[key] for key in ("run_id", "overwatcher_role_instance_id", "audit_cycle")},
            "evidence_sha256": "a" * 64, "receipt_sha256": "b" * 64}
    async def notify(value): notices.append(value); return False
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _name: True)
    monkeypatch.setattr(instance, "_notify_supervisor", notify)
    asyncio.run(instance._inspect_overwatcher())
    assert instance._runtime_guard_blocker["kind"] == expected
    assert notices[-1]["kind"] == expected


@pytest.mark.parametrize("operation,packet,status", [
    ("overwatcher-exited", overwatcher_exit_value(), "SUPERVISOR_CONFIRMATION_REQUIRED"),
    ("resolve-runtime-guard", runtime_guard_resolution_value(), "RUNTIME_GUARD_REPAIRED")])
@pytest.mark.parametrize("damage", [None, "run", "event", "extra", "status"])
def test_existing_guard_updates_have_exact_hashed_cli_identity_and_closed_reply(tmp_path, monkeypatch, operation, packet, status, damage):
    identity_path = write_json(tmp_path / "identity.json", identity())
    request_path = write_json(tmp_path / "request.json", packet)
    result = {"schema_version": "slk.temporal-runtime-guard-update-result/v1", "status": status,
        "operation": operation.replace("-", "_"), "run_id": packet["run_id"], "event_id": packet["event_id"]}
    if damage == "run": result["run_id"] = "other"
    elif damage == "event": result["event_id"] = "other"
    elif damage == "extra": result["extra"] = True
    elif damage == "status": result["status"] = "NOTIFIED"
    monkeypatch.setattr(delivery_client, "submit", lambda **_k: result)
    call = lambda: delivery_client.run_update(operation=operation, identity_path=identity_path,
        identity_sha256=standard_adapter._sha256(identity_path), request_path=request_path,
        request_sha256=standard_adapter._sha256(request_path))
    if damage:
        with pytest.raises(ValueError, match="result identity"): call()
    else: assert call() == result


@pytest.mark.parametrize("same_cell", [True, False])
@pytest.mark.parametrize("method", ["4.5.0", "4.5.1", "4.5.2", "4.5.3", "4.5.4", "4.5.5", "4.4.5"])
@pytest.mark.parametrize("handoff", [("worker-a", "checker-a"), ("checker-a", "supervisor-a")])
def test_450_guard_does_not_stop_current_cell_but_blocks_the_next(monkeypatch, same_cell, method, handoff):
    from slk_temporal.continuity import RunContinuity
    from slk_temporal.contracts import DeliveryRequest, NativeStartAck
    from .test_contracts import delivery_value, ack_value
    from temporalio.exceptions import ApplicationError
    instance = RunSlkWorkflow()
    instance._startup = StartSlkRequest.from_dict({**start_value(), "method_version": method})
    instance._continuity = RunContinuity("RUN-A")
    instance._admitted = True
    previous = DeliveryRequest.from_dict(delivery_value())
    instance._continuity.request_delivery(previous)
    instance._continuity.acknowledge(NativeStartAck.from_dict(ack_value()))
    instance._responsibility_operation_id = previous.operation_id
    instance._runtime_guard_blocker = {"event_id": "audit-a"}
    following = {**delivery_value(), "operation_id": "next", "message_id": "next-message",
        "cell_id": previous.cell_id if same_cell else "CELL-002",
        "sender_role_instance_id": handoff[0], "receiver_role_instance_id": handoff[1]}
    if same_cell and method in {"4.5.0", "4.5.1", "4.5.2", "4.5.3", "4.5.4", "4.5.5"}:
        assert instance.request_delivery(following) == "DELIVERY_REQUESTED"
        assert instance._runtime_guard_blocker is not None and instance._run_pause is None
    else:
        with pytest.raises(ApplicationError, match="runtime guard"): instance.request_delivery(following)


def test_450_guard_cannot_guess_current_scope_or_accept_another_run():
    from slk_temporal.continuity import RunContinuity
    from slk_temporal.contracts import DeliveryRequest
    from .test_contracts import delivery_value
    from temporalio.exceptions import ApplicationError
    instance = RunSlkWorkflow()
    instance._startup = StartSlkRequest.from_dict({**start_value(), "method_version": "4.5.0"})
    instance._continuity = RunContinuity("RUN-A")
    instance._admitted = True
    instance._runtime_guard_blocker = {"event_id": "audit-a"}
    with pytest.raises(ApplicationError, match="runtime guard"):
        instance.request_delivery(delivery_value())
    instance._responsibility_operation_id = delivery_value()["operation_id"]
    # Even a matching operation/CELL from another Run remains invalid.
    instance._continuity.request_delivery(DeliveryRequest.from_dict(delivery_value()))
    with pytest.raises(ApplicationError, match="run_id"):
        instance.request_delivery({**delivery_value(), "run_id": "RUN-B"})


@pytest.mark.parametrize("method", ["4.5.0", "4.5.1", "4.5.2", "4.5.3", "4.5.4", "4.5.5", "4.4.5"])
def test_450_schema_and_bootstrap_compatibility(tmp_path, method):
    from jsonschema import Draft202012Validator
    root, config = native_config(tmp_path, method) if method != "4.4.5" else config_root(tmp_path, method)
    contracts = Path(__file__).resolve().parents[2] / "docs/contracts"
    for name, value in (("slk-temporal-standard-adapter.schema.json", config),
        ("slk-temporal-standard-bootstrap.schema.json", json.loads((root / f"{RUN_ID}.bootstrap.json").read_text()))):
        Draft202012Validator(json.loads((contracts / name).read_text())).validate(value)
    if method != "4.4.5":
        config["schema_version"] = "slk.temporal-standard-adapter/v1"
        config["overwatcher_activity"].pop("attestation_path")
        config["overwatcher_activity"].pop("attestation_sha256")
        assert list(Draft202012Validator(json.loads((contracts / "slk-temporal-standard-adapter.schema.json").read_text())).iter_errors(config))


@pytest.mark.parametrize("operation", ["overwatcher-exited", "resolve-runtime-guard"])
@pytest.mark.parametrize("fault", [None, "supervisor", "fingerprint", "ow"])
def test_guard_client_sdk_rejoins_frozen_authority_before_exact_existing_update(monkeypatch, operation, fault):
    startup = StartSlkRequest.from_dict({**start_value(), "method_version": "4.5.0"})
    frozen_identity = {**identity(), "startup_fingerprint": startup.startup_fingerprint}
    packet = overwatcher_exit_value() if operation == "overwatcher-exited" else runtime_guard_resolution_value()
    if fault == "supervisor": packet["requested_by_role_instance_id" if operation == "overwatcher-exited" else "supervisor_role_instance_id"] = "checker-a"
    elif fault == "fingerprint": frozen_identity["startup_fingerprint"] = "1" * 64
    elif fault == "ow" and operation == "overwatcher-exited": packet["overwatcher_role_instance_id"] = "other-ow"
    calls = []
    class Handle:
        async def query(self, query):
            assert query == RunSlkWorkflow.recovery_checkpoint
            return {"startup": startup.to_dict()}
        async def execute_update(self, update, value):
            calls.append((update, value))
            return delivery_client.GUARD_OPERATIONS[operation]
    class Client:
        @staticmethod
        async def connect(address):
            assert address == frozen_identity["address"]
            return Client()
        def get_workflow_handle(self, workflow_id, *, run_id):
            assert (workflow_id, run_id) == (frozen_identity["run_workflow_id"], frozen_identity["run_run_id"])
            return Handle()
    async def inspect(**values):
        assert values["start_run_id"] == frozen_identity["start_run_id"]
    monkeypatch.setattr(delivery_client, "inspect_pair", inspect)
    monkeypatch.setattr(delivery_client, "Client", Client)
    invalid = fault in {"supervisor", "fingerprint"} or fault == "ow" and operation == "overwatcher-exited"
    if invalid:
        with pytest.raises(ValueError, match="authority"):
            asyncio.run(delivery_client._submit_once(operation=operation, identity=frozen_identity, request=packet))
        assert not calls
    else:
        result = asyncio.run(delivery_client._submit_once(operation=operation, identity=frozen_identity, request=packet))
        assert result["status"] == delivery_client.GUARD_OPERATIONS[operation]
        assert calls == [(RunSlkWorkflow.overwatcher_exited if operation == "overwatcher-exited" else RunSlkWorkflow.resolve_runtime_guard, packet)]


@pytest.mark.asyncio
async def test_450_isolated_sdk_exit_guard_failure_recovery_and_two_run_monitoring(tmp_path):
    """Actual SDK/update paths on a disposable time-skipping server, not host proof."""
    import uuid
    from temporalio import activity
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker
    from slk_temporal.workflows import StartSlkWorkflow
    from .test_workflows import prepare_run, deliver_message, request_recovery, _admit
    from .test_contracts import notification_value
    queue = "ow450-isolated-" + uuid.uuid4().hex
    audits, notices = [], []
    restored = False
    run_a, run_b = "RUN-OW450-A-" + uuid.uuid4().hex, "RUN-OW450-B-" + uuid.uuid4().hex
    @activity.defn(name="slk.inspect_overwatcher")
    async def inspect(value):
        audits.append(dict(value))
        return {"status": "EXITED" if value["run_id"] == run_a and not restored else "CLEAR",
            **{key: value[key] for key in ("run_id", "overwatcher_role_instance_id", "audit_cycle")},
            "evidence_sha256": "a" * 64, "receipt_sha256": "b" * 64}
    @activity.defn(name="slk.notify_supervisor")
    async def notify(value):
        notices.append(dict(value))
        if value["run_id"] == run_a: return {"status": "NOTIFIED"}  # accepted-only is not native proof
        return notification_value(value["event_id"], value["run_id"])
    server = tmp_path / "isolated-server"
    server.mkdir()
    async with await WorkflowEnvironment.start_time_skipping(download_dest_dir=str(server),
        test_server_existing_path=os.environ.get("SLK_TEMPORAL_TEST_SERVER_PATH")) as env:
        async with Worker(env.client, task_queue=queue, workflows=[StartSlkWorkflow, RunSlkWorkflow],
            activities=[prepare_run, deliver_message, request_recovery, inspect, notify]):
            pairs = []
            for run_id in (run_a, run_b):
                startup = {**start_value(), "run_id": run_id, "method_version": "4.5.0", "task_queue": queue}
                parent = await env.client.start_workflow(StartSlkWorkflow.run, startup,
                    id="slk-start-" + run_id, task_queue=queue)
                child = env.client.get_workflow_handle("slk-run-" + run_id)
                await _admit(child, env, startup)
                pairs.append((startup, parent, child))
            a, b = pairs
            await env.sleep(1201)
            snapshot = await a[2].query(RunSlkWorkflow.status)
            assert snapshot["runtime_guard_blocker"]["kind"] == "OVERWATCHER_EXIT_REQUIRES_SUPERVISOR_CONFIRMATION"
            assert snapshot["notification_failure"]["reason"] == "SUPERVISOR_NOTIFICATION_UNPROVED"
            assert (await b[2].query(RunSlkWorkflow.status))["runtime_guard_blocker"] is None
            assert notices[-1]["run_id"] == run_a and notices[-1]["responsible_role_instance_id"] == "overwatcher-a"
            # Close only B's pair. The same worker and A's 1200-second audit continue.
            await b[2].execute_update(RunSlkWorkflow.close_run, "RUN_CLOSED_B")
            await b[1].result()
            b_audits_at_close = len([row for row in audits if row["run_id"] == run_b])
            start_desc, run_desc = await asyncio.gather(a[1].describe(), a[2].describe())
            exact = {**identity(), "run_id": run_a, "address": env.client.service_client.config.target_host,
                "task_queue": queue, "start_workflow_id": a[1].id, "start_run_id": start_desc.run_id,
                "run_workflow_id": a[2].id, "run_run_id": run_desc.run_id,
                "startup_fingerprint": StartSlkRequest.from_dict(a[0]).startup_fingerprint}
            callback_notice = {**overwatcher_exit_value(), "run_id": run_a}
            receipt = await delivery_client._submit_once(operation="overwatcher-exited", identity=exact, request=callback_notice)
            assert receipt["status"] == "SUPERVISOR_CONFIRMATION_REQUIRED"
            snapshot = await a[2].query(RunSlkWorkflow.status)
            resolution = {**runtime_guard_resolution_value(), "run_id": run_a,
                "blocker_event_id": snapshot["runtime_guard_blocker"]["event_id"]}
            restored = True  # Supervisor has obtained fresh trustworthy evidence, not a new child.
            unresolved = set(snapshot["pending_supervisor_notifications"]) - {resolution["blocker_event_id"]}
            receipt = await delivery_client._submit_once(operation="resolve-runtime-guard", identity=exact, request=resolution)
            assert receipt["status"] == "RUNTIME_GUARD_REPAIRED"
            a_audits_before_wait = len([row for row in audits if row["run_id"] == run_a])
            for index in range(len(unresolved)):
                await env.sleep(1201)
                # Later audit/callback notices remain independent obligations.
                later = (await a[2].query(RunSlkWorkflow.status))["runtime_guard_blocker"]
                assert later is not None and later["event_id"] in unresolved
                unresolved.remove(later["event_id"])
                resolution = {**resolution, "event_id": f"resolve-later-{index}", "blocker_event_id": later["event_id"]}
                await delivery_client._submit_once(operation="resolve-runtime-guard", identity=exact, request=resolution)
            await env.sleep(1201)
            assert (await a[2].query(RunSlkWorkflow.status))["runtime_guard_blocker"] is None
            a_audits = [row["audit_cycle"] for row in audits if row["run_id"] == run_a]
            assert len(a_audits) > a_audits_before_wait
            assert a_audits == list(range(1, len(a_audits) + 1))
            assert len([row for row in audits if row["run_id"] == run_b]) == b_audits_at_close
            await a[2].execute_update(RunSlkWorkflow.close_run, "RUN_CLOSED_A")
            await a[1].result()
