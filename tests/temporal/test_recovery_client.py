"""Closed recovery client boundaries; all files belong to isolated test storage."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
pytest.importorskip("temporalio")
from slk_temporal import recovery_client as recovery
from slk_temporal import workflows
from slk_temporal.continuity import RunContinuity
from slk_temporal.contracts import DeliveryRequest, NativeStartAck, StartSlkRequest
from .test_contracts import start_value, delivery_value, ack_value
from .test_delivery_client import identity


def packet():
    run = workflows.RunSlkWorkflow()
    run._startup = StartSlkRequest.from_dict({**start_value(), "method_version": "4.4.2"})
    run._continuity = RunContinuity("RUN-A")
    run._continuity.request_delivery(DeliveryRequest.from_dict(delivery_value()))
    run._continuity.acknowledge(NativeStartAck.from_dict(ack_value()))
    second = {**delivery_value(), "operation_id": "second", "message_id": "message-second"}
    run._continuity.request_delivery(DeliveryRequest.from_dict(second))
    run._continuity.mark_timeout("second")
    run._admitted = True
    run._delivery_started.update((delivery_value()["operation_id"], "second"))
    run._recovery_started.add("second")
    return run.recovery_checkpoint()


def request_fixture(root):
    def write(name, value):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")
        return recovery.proof(path)
    checkpoint = packet()
    source = {**identity(), "task_queue": checkpoint["startup"]["task_queue"],
              "startup_fingerprint": StartSlkRequest.from_dict(checkpoint["startup"]).startup_fingerprint}
    source_proof = write("identity.json", source)
    host = write("host.json", {"schema_version": "slk.role-host/v2", "run_id": "RUN-A", "plan_revision": 7,
        "roles": {"unchanged": True}, "temporal": {"workflow_identity_path": source_proof["path"],
                                                 "workflow_identity_sha256": source_proof["sha256"]}})
    config = write("config/RUN-A.json", {"run_id": "RUN-A", "role_host_binding": host})
    return {"schema_version": "slk.temporal-execution-recovery/v1", "run_id": "RUN-A",
        "source_identity": source_proof, "source_executions": {name: {"status": "FAILED", "close_time": "2026-10-08T19:28:41Z"}
            for name in ("start", "run")}, "checkpoint": write("checkpoint.json", checkpoint),
        "histories": {name: write(name + "-history.json", {"events": []}) for name in ("start", "run")},
        "source_host": host, "source_config": config, "central_projection": write("central.json", {"runtime_revision": 339}),
        "decision": {"supervisor_role_instance_id": "supervisor-a", "reason": "same-scope reversible repair", "evidence_ref": "existing-authority"},
        "evidence_root": str(root / "versioned")}


@pytest.mark.parametrize("damage", ["unknown", "run", "source-state", "supervisor", "reason", "hash"])
def test_request_fails_closed_on_scope_authority_or_source_drift(tmp_path, damage):
    request = request_fixture(tmp_path)
    if damage == "unknown": request["invented"] = True
    if damage == "run": request["run_id"] = "OTHER"
    if damage == "source-state": request["source_executions"]["run"]["status"] = "RUNNING"
    if damage == "supervisor": request["decision"]["supervisor_role_instance_id"] = "checker-a"
    if damage == "reason": request["decision"]["reason"] = " "
    if damage == "hash": request["checkpoint"]["sha256"] = "0" * 64
    with pytest.raises(ValueError): recovery.validate_request(request)


def test_existing_supervisor_disposition_needs_no_new_human_item(tmp_path):
    request = request_fixture(tmp_path)
    assert recovery.validate_request(request)[0] == request


def test_source_business_queue_is_bound_to_checkpoint_before_rpc(tmp_path):
    request = request_fixture(tmp_path)
    path = Path(request["source_identity"]["path"])
    value = json.loads(path.read_text())
    value["task_queue"] = "wrong-source-queue"
    path.write_text(json.dumps(value), encoding="utf-8")
    request["source_identity"] = recovery.proof(path)
    with pytest.raises(ValueError, match="queue"):
        recovery.validate_request(request)


def test_target_business_queue_cannot_change_even_if_sdk_execution_queue_differs(monkeypatch):
    source = identity()
    target = {**source, "start_workflow_id": "slk-start-RUN-A-recovery-" + source["run_run_id"],
        "run_workflow_id": "slk-run-RUN-A-recovery-" + source["run_run_id"], "task_queue": "wrong-target-queue"}
    monkeypatch.setattr(recovery, "read_proof", lambda *_a, **_k: source)
    async def inspect(**_k): pytest.fail("invalid queue must reject before RPC")
    monkeypatch.setattr(recovery, "inspect_pair", inspect)
    with pytest.raises(ValueError, match="lineage"):
        asyncio.run(recovery.verify_target({"run_id": "RUN-A", "source_identity": {}}, target, packet(), initial=True))


def test_frozen_forward_slash_refs_match_resolved_absolute_proofs(tmp_path):
    request = request_fixture(tmp_path)
    host_path = Path(request["source_host"]["path"])
    host = json.loads(host_path.read_text())
    host["temporal"]["workflow_identity_path"] = Path(request["source_identity"]["path"]).as_posix()
    host_path.write_text(json.dumps(host), encoding="utf-8")
    request["source_host"] = recovery.proof(host_path)
    config_path = Path(request["source_config"]["path"])
    config = json.loads(config_path.read_text())
    config["role_host_binding"] = {**request["source_host"], "path": host_path.as_posix()}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    request["source_config"] = recovery.proof(config_path)
    assert recovery.read_proof(config["role_host_binding"], "host") == host
    assert recovery.validate_request(request)[0] == request


@pytest.mark.parametrize("damage", ["other-file", "hash"])
def test_equivalent_path_comparison_still_requires_same_file_and_sha(tmp_path, damage):
    request = request_fixture(tmp_path)
    path = Path(request["source_host"]["path"])
    host = json.loads(path.read_text())
    if damage == "other-file":
        other = tmp_path / "copied-identity.json"
        other.write_bytes(Path(request["source_identity"]["path"]).read_bytes())
        host["temporal"]["workflow_identity_path"] = other.as_posix()
    else:
        host["temporal"]["workflow_identity_sha256"] = "0" * 64
    path.write_text(json.dumps(host), encoding="utf-8")
    request["source_host"] = recovery.proof(path)
    config_path = Path(request["source_config"]["path"])
    config = json.loads(config_path.read_text())
    config["role_host_binding"] = request["source_host"]
    config_path.write_text(json.dumps(config), encoding="utf-8")
    request["source_config"] = recovery.proof(config_path)
    with pytest.raises(ValueError): recovery.validate_request(request)


def test_actual_restored_checkpoint_cannot_drop_or_change_completed_history():
    source = packet()
    target = copy.deepcopy(source)
    recovery.verify_restored_checkpoint(source, target, initial=True)
    target["continuity"]["seen"][0]["payload_sha256"] = "f" * 64
    with pytest.raises(ValueError): recovery.verify_restored_checkpoint(source, target, initial=True)


@pytest.mark.parametrize("notified", [True, False])
def test_initial_recovery_accepts_only_exact_overdue_member_notice(notified):
    source = packet()
    state = source["status"]
    state.update(responsible_role_instance_id="checker-a", responsibility_operation_id=delivery_value()["operation_id"],
        member_residency_since="2026-10-09T03:20:41.854459+08:00", member_residency_notice_sent=False,
        notification_failure={"event_id": "RUN-A-ow-audit-189", "reason": "SUPERVISOR_NOTIFICATION_UNPROVED"})
    target = copy.deepcopy(source)
    event = "RUN-A-member-residency-" + state["responsibility_operation_id"]
    target["status"].update(member_residency_notice_sent=True, notification_failure=None)
    if not notified:
        target["status"]["notification_failure"] = {"event_id": event, "reason": "SUPERVISOR_NOTIFICATION_UNPROVED"}
        target["status"]["runtime_guard_blocker"] = {"event_id": event, "kind": "SUPERVISOR_NOTIFICATION_UNPROVED",
            "run_id": "RUN-A", "responsible_role_instance_id": "supervisor-a",
            "source_operation_id": "runtime-guard-" + event, "threshold_seconds": 0}
    recovery.verify_restored_checkpoint(source, target, initial=True)
    assert target["status"]["member_residency_since"] == state["member_residency_since"]
    assert source["status"]["notification_failure"]["event_id"] == "RUN-A-ow-audit-189"


@pytest.mark.parametrize("damage", ["future-time", "wrong-notice", "changed-responsibility", "cleared-guard"])
def test_initial_recovery_does_not_accept_arbitrary_guard_drift(damage):
    source = packet()
    state = source["status"]
    state.update(responsible_role_instance_id="checker-a", responsibility_operation_id=delivery_value()["operation_id"],
                 member_residency_since="2026-10-09T03:20:41.854459+08:00")
    target = copy.deepcopy(source)
    target["status"].update(member_residency_notice_sent=True, notification_failure=None)
    if damage == "future-time":
        state["member_residency_since"] = target["status"]["member_residency_since"] = "2999-01-01T00:00:00+00:00"
    if damage == "wrong-notice":
        target["status"]["notification_failure"] = {"event_id": "other", "reason": "SUPERVISOR_NOTIFICATION_UNPROVED"}
    if damage == "changed-responsibility": target["status"]["responsible_role_instance_id"] = "worker-a"
    if damage == "cleared-guard":
        state["runtime_guard_blocker"] = {"event_id": "old", "kind": "OVERWATCHER_EXIT",
            "run_id": "RUN-A", "responsible_role_instance_id": "overwatcher-a",
            "source_operation_id": "runtime-guard-old", "threshold_seconds": 0}
    with pytest.raises(ValueError): recovery.verify_restored_checkpoint(source, target, initial=True)


def test_verified_result_retry_does_not_repeat_source_boundary_admission(tmp_path, monkeypatch):
    request = request_fixture(tmp_path)
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request), encoding="utf-8")
    value, source, checkpoint = recovery.validate_request(request)
    suffix = "-recovery-" + source["run_run_id"]
    target = {**source, "start_workflow_id": "slk-start-RUN-A" + suffix,
              "run_workflow_id": "slk-run-RUN-A" + suffix, "start_run_id": "new-start", "run_run_id": "new-run"}
    bindings = recovery.materialize_bindings(request, target)
    result = {"schema_version": "slk.temporal-execution-recovery-result/v1", "status": "ACK_ONLY_PAIR_RUNNING",
              "run_id": "RUN-A", "source_identity": source, "target_identity": target,
              "request_sha256": recovery.proof(path)["sha256"], **bindings}
    (Path(request["evidence_root"]) / "result.json").write_text(json.dumps(result), encoding="utf-8")
    async def verify(*args, **kwargs): return None
    async def source_changed(*args, **kwargs): pytest.fail("completed recovery retry must not re-admit old339 boundary")
    monkeypatch.setattr(recovery, "verify_target", verify, raising=False)
    monkeypatch.setattr(recovery, "validate_source", source_changed)
    assert asyncio.run(recovery.restore(request_path=path, request_sha256=result["request_sha256"],
        config_root=tmp_path / "config")) == result


@pytest.mark.parametrize("damage", [None, "runtime", "plan", "role", "event", "old-observation"])
def test_source_validation_allows_only_append_only_ow_observations(tmp_path, monkeypatch, damage):
    request = request_fixture(tmp_path)
    saved = {"runtime_snapshot": {"runtime_revision": 339, "plan_revision": 7, "token_sequence": 110},
             "roles": [{"role_instance_id": "checker-a"}], "events": [{"event_id": "accepted-fail-247"}],
             "overwatch_cycles": [{"cycle_id": "cycle-1"}],
             "operational_observations": [{"observation_id": "observation-1"}],
             "overwatcher_native_status_receipts": [{"status_id": "status-1"}]}
    path = Path(request["central_projection"]["path"])
    path.write_text(json.dumps(saved), encoding="utf-8")
    request["central_projection"] = recovery.proof(path)
    actual = copy.deepcopy(saved)
    for key, identifier in (("overwatch_cycles", "cycle_id"), ("operational_observations", "observation_id"),
                            ("overwatcher_native_status_receipts", "status_id")):
        actual[key].append({identifier: "new"})
    if damage == "runtime": actual["runtime_snapshot"]["runtime_revision"] = 340
    if damage == "plan": actual["runtime_snapshot"]["plan_revision"] = 8
    if damage == "role": actual["roles"][0]["role_instance_id"] = "other"
    if damage == "event": actual["events"][0]["event_id"] = "other"
    if damage == "old-observation": actual["overwatch_cycles"][0]["changed"] = True
    _, source, checkpoint = recovery.validate_request(request)
    histories = {key: recovery.read_proof(value, "history") for key, value in request["histories"].items()}
    async def snapshot(_): return request["source_executions"], checkpoint, histories
    monkeypatch.setattr(recovery, "source_snapshot", snapshot)
    monkeypatch.setattr(recovery.adapter, "_load_config", lambda _: recovery.read_proof(request["source_config"], "config"))
    monkeypatch.setattr(recovery, "_central", lambda *args: actual)
    if damage is not None:
        with pytest.raises(ValueError): asyncio.run(recovery.validate_source(request, config_root=tmp_path / "config"))
    else:
        assert asyncio.run(recovery.validate_source(request, config_root=tmp_path / "config"))["status"] == "RECOVERY_READY"
