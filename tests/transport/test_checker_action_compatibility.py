"""Explicit Checker actions against real, isolated state; no model or product Run."""
from dataclasses import asdict
import json
from pathlib import Path
import uuid

import pytest

from slk_transport import checker_escalation, checker_management, worker_completion as wc
from slk_transport.contracts import Envelope, canonical_json_sha256
from slk_transport.native_activity import make_native_start
from slk_transport.role_host import RoleHost
from test_role_host import prepared_host
from test_worker_completion import actual_state_call, actual_worker_state, write_json


def live_checker(tmp_path, monkeypatch, *, credentials=None, second_cell=False, native_kind="ocrv-review"):
    binary, config, worker_secret, checker_secret, revision = actual_worker_state(tmp_path, credentials=credentials, second_cell=second_cell)
    host, worker_source, original = prepared_host(tmp_path)
    if second_cell:
        host.binding["cells"].append({"go_id": original.go_id, "cell_id": "CELL-002", "payload": {
            "cell_id":"CELL-002", "cell_ordinal":2, "required_cell_count":2,
            "task":"next bounded implementation", "d1_criteria":["next criterion"],
            "root_record_path":str(worker_source/"envelope.json")}})
    for role in ("checker", "supervisor"):
        path = Path(host.binding["roles"][role]["endpoint_path"])
        write_json(path, {**host.endpoint(role), "endpoint_version": 1})
        host.binding["roles"][role]["endpoint_sha256"] = wc._sha256(path)
    host = RoleHost({**host.binding, "state_command": [str(binary)]}, host.digest,
                    state_config_path=str(config))
    candidate = {"kind": "commit", "commit": "b" * 40}
    message_id = wc._stable_id(original.message_id, "output-delivery")
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_PATH", str(worker_source / "native-activity.json"))
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_CONTEXT", json.dumps({"adapter": "dsh-worker",
        "run_id": original.run_id, "cell_id": original.cell_id, "message_id": original.message_id}))
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda path: worker_secret
                        if Path(path) == Path(host.credential_path("worker"))
                        else pytest.fail("Worker may only consume its own credential"))
    for event_type, details in (
        ("WORK_STARTED", {}), ("D0_COMPLETED", {"d0": "Worker explicit fixture"}),
        ("CANDIDATE_SUBMITTED", {"candidate": candidate,
            "source_message_id": original.message_id, "handoff_message_id": message_id}),
    ):
        host.record_worker_action(worker_source, event_type, details)
    from slk_transport.contracts import DeliveryResult, RESULT_SCHEMA
    from slk_transport.dispatcher import dispatch_once
    original_command = wc._run_json_command
    received = []
    class Receiver:
        def validate_address(self, endpoint):
            pass
        def deliver(self, endpoint, envelope, attempt):
            received.append(envelope)
            native = make_native_start(adapter=endpoint.adapter, run_id=envelope.run_id,
                cell_id=envelope.cell_id, message_id=envelope.message_id,
                request_sha256=envelope.payload_sha256, native_request_sha256="a" * 64,
                native_task_kind={"checker":native_kind, "supervisor":"codex-turn", "worker":"dsh-session"}[endpoint.role],
                native_task_id=("original-review:" + envelope.message_id if endpoint.role == "checker" else
                    host.endpoint("supervisor")["address"]["thread_id"] + ":fixture-turn" if endpoint.role == "supervisor" else
                    host.endpoint("worker")["address"]["session_id"] or "original-worker-session"),
                native_task_status="RUNNING", pid=__import__("os").getpid())
            native["observed_at"] = "2026-09-23T00:05:00Z"
            attempt.write_json_once("native-start.received.json", native)
            attempt.write_json_once("started.json", native)
            return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id,
                endpoint.adapter, "completed", {}, None, ("started.json",))
    def command(executable, arguments, **kwargs):
        if executable != host.transport:
            return original_command(executable, arguments, **kwargs)
        endpoint = json.loads(Path(arguments[arguments.index("--endpoint")+1]).read_text())
        envelope = json.loads(Path(arguments[arguments.index("--envelope")+1]).read_text())
        from slk_transport.evidence import AttemptStore
        attempt = AttemptStore(arguments[arguments.index("--attempt-root")+1]).create(Envelope.from_dict(envelope))
        if not (attempt.root / "started.json").is_file():
            from slk_transport.contracts import Endpoint
            attempt.write_json_once("endpoint.json", endpoint)
            attempt.write_json_once("envelope.json", envelope)
            Receiver().deliver(Endpoint.from_dict(endpoint), Envelope.from_dict(envelope), attempt)
        return {"status": "started", "ack_scope": "NATIVE_RECEIVE_START_ONLY"}
    monkeypatch.setattr(wc, "_run_json_command", command)
    raw = b"Worker D0 finished; explicit candidate submitted.\r\nNot JSON.\xff\r\n"
    (worker_source / "worker-result.json").write_bytes(raw)
    delivered = host.complete(worker_source)
    assert delivered["status"] == "OUTPUT_DELIVERED"
    assert delivered["handoff"]["status"] == "OWNED_HANDOFF_COMMITTED"
    assert len(received) == 1 and received[0].payload["candidate"] == candidate
    assert (worker_source / "worker-result.json").read_bytes() == raw
    incoming = received[0]
    source = worker_source / "role-host" / "worker-handoff" / "attempts" / incoming.run_id / message_id
    start = source / "native-start.received.json"
    native = json.loads(start.read_text())
    assert host.complete(worker_source)["handoff"]["status"] == "OWNED_HANDOFF_ALREADY_COMMITTED"
    assert len(received) == 1
    monkeypatch.setenv("SLK_NATIVE_START_RECEIPT", str(start))
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda path: checker_secret
                        if Path(path) == Path(host.credential_path("checker"))
                        else pytest.fail("no other role credential may be consumed"))
    return host, source, incoming, native


def test_explicit_pass_delivers_only_next_required_cell_with_its_own_first_attempt(tmp_path, monkeypatch):
    host, source, _, _ = live_checker(tmp_path, monkeypatch, second_cell=True)
    result = host.submit_checker_decision(source, "PASS", "original first CELL acceptance")
    assert result["handoff"]["status"] == "OWNED_HANDOFF_COMMITTED"
    request = json.loads(Path(result["handoff"]["commit_path"]).read_text())
    assert request["cell_id"] == "CELL-002" and request["attempt"] == 1
    assert request["payload_type"] == "WORKER_TASK"
    assert host.projection()["runtime_snapshot"]["token_holder_role_instance_id"] == host.endpoint("worker")["role_instance_id"]


def test_actual_second_attempt_incomplete_return_keeps_original_candidate_and_attempt(tmp_path, monkeypatch):
    import os
    credentials = {}
    host, checker_source, incoming, _ = live_checker(tmp_path, monkeypatch, credentials=credentials)
    def own(role):
        monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda path: credentials[role]
            if Path(path) == Path(host.credential_path(role)) else pytest.fail("cross-role credential"))
    def receiver(result):
        request = json.loads(Path(result["commit_path"]).read_text())
        return Path(request["start_evidence"]["stored_path"]).parent
    own("checker")
    failed = host.submit_checker_decision(checker_source, "FAIL", "original defect, not host classification")
    supervisor_source = receiver(failed["handoff"])
    failure = json.loads((supervisor_source/"envelope.json").read_text())
    write_json(supervisor_source/"supervisor-result.json", {"operation": "rework",
        "source_message_id": failure["message_id"], "decision": {**failure["payload"],
            "investigation_mode": "OWNER_APPROVED_BOUNDED_INVESTIGATION", "guidance": "repair exact defect"}})
    monkeypatch.setenv("CODEX_THREAD_ID", host.endpoint("supervisor")["address"]["thread_id"])
    own("supervisor")
    rework = host.submit_supervisor_decision(supervisor_source)
    worker_source = receiver(rework)
    worker_input = Envelope.from_dict(json.loads((worker_source/"envelope.json").read_text()))
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_PATH", str(worker_source/"native-activity.json"))
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_CONTEXT", json.dumps({"adapter":"dsh-worker",
        "run_id":worker_input.run_id, "cell_id":worker_input.cell_id, "message_id":worker_input.message_id}))
    own("worker")
    candidate = {"kind":"commit", "commit":"c"*40}
    for event, details in [("WORK_STARTED", {}), ("D0_COMPLETED", {"original":"D0"}),
                           ("CANDIDATE_SUBMITTED", {"candidate":candidate})]:
        host.record_worker_action(worker_source, event, details)
    (worker_source/"worker-result.json").write_bytes(b"Second Worker report is free text.\xff\r\n")
    delivered = host.complete(worker_source)
    assert delivered["handoff"]["status"] == "OWNED_HANDOFF_COMMITTED"
    second_checker = receiver(delivered["handoff"])
    monkeypatch.setenv("SLK_NATIVE_START_RECEIPT", str(second_checker/"native-start.received.json"))
    own("checker")
    incomplete = host.submit_checker_decision(second_checker, "INCOMPLETE", "original unchecked item")
    second_supervisor = receiver(incomplete["handoff"])
    management = json.loads((second_supervisor/"envelope.json").read_text())
    write_json(second_supervisor/"supervisor-result.json", {"operation":"management",
        "source_message_id":management["message_id"],
        "decision":{"action":"OWNER_CHOSEN_REPAIR", "summary":"resume original candidate"}})
    own("supervisor")
    returned = host.submit_supervisor_decision(second_supervisor)
    final_checker = receiver(returned)
    returned_input = json.loads((final_checker/"envelope.json").read_text())
    assert returned_input["payload"]["candidate_payload"]["candidate"] == candidate
    monkeypatch.setenv("SLK_NATIVE_START_RECEIPT", str(final_checker/"native-start.received.json"))
    own("checker")
    passed = host.submit_checker_decision(final_checker, "PASS", "original Checker final decision")
    assert passed["handoff"]["status"] == "OWNED_HANDOFF_COMMITTED"
    events = host.projection()["events"]
    second_events = [e for e in events if e["event_type"] in {"D1_INCOMPLETE", "D1_PASSED"}]
    assert [e["attempt"] for e in second_events] == [2, 2]
    assert second_events[-1]["corrects_event_id"] == second_events[0]["event_id"]
    for role_handoff in (incomplete["handoff"], returned, passed["handoff"]):
        assert json.loads(Path(role_handoff["commit_path"]).read_text())["attempt"] == 2


def downstream_request(host, source, incoming, verdict):
    projection = host.projection()
    snapshot = projection["runtime_snapshot"]
    terminal = next(event for event in projection["events"]
                    if event["event_type"] == {"FAIL": "D1_FAILED", "INCOMPLETE": "D1_INCOMPLETE"}[verdict])
    runtime = write_json(source / "runtime-projection.json", projection)
    return {"method_version": projection["summary"]["slk_version"],
        "run_id": incoming.run_id, "go_id": incoming.go_id, "cell_id": incoming.cell_id,
        "attempt": 1, "plan_revision": host.binding["plan_revision"],
        "runtime_revision": snapshot["runtime_revision"], "token_sequence": snapshot["token_sequence"],
        "checker_role_instance_id": incoming.receiver_role_instance_id,
        "d1_failure_event_id" if verdict == "FAIL" else "d1_incomplete_event_id": terminal["event_id"],
        "runtime_projection_path": str(runtime), "native_attempt_path": str(source),
        "supervisor_endpoint_path": host.binding["roles"]["supervisor"]["endpoint_path"],
        "rework_round": 1, "evidence_refs": []}


@pytest.mark.parametrize("verdict", ["FAIL", "INCOMPLETE"])
@pytest.mark.parametrize("report", ["absent", "partial", "native-failed"])
@pytest.mark.parametrize("native_kind", ["ocrv-review", "ocrv-invocation"])
def test_actual_checker_action_reaches_downstream_without_future_output(
    tmp_path, monkeypatch, verdict, report, native_kind,
):
    host, source, incoming, native = live_checker(tmp_path, monkeypatch, native_kind=native_kind)
    result = host.record_checker_decision(source, verdict)
    assert result["status"] == "CHECKER_D1_RECORDED"
    assert not (source / "ocrv-result.json").exists()
    assert not (source / "completed.json").exists()
    if report != "absent":
        (source / "ocrv-result.json").write_bytes(b"partial report\r\nnot JSON\xff")
    if report == "native-failed":
        write_json(source / "failed.json", {"status": "failed", "exit_code": 42})
    request = downstream_request(host, source, incoming, verdict)
    validate = (checker_escalation._validate_failure if verdict == "FAIL"
                else checker_management._validate_incomplete)
    assert validate(request)
    terminal_path = source / "role-host" / f"d1_{'failed' if verdict == 'FAIL' else 'incomplete'}.json"
    terminal = json.loads(terminal_path.read_text())
    assert terminal["occurred_at"] != native["observed_at"]
    original = terminal_path.read_bytes()
    host.record_checker_decision(source, verdict)
    assert terminal_path.read_bytes() == original
    assert len([event for event in host.projection()["events"]
                if event["event_type"] in {"D1_STARTED", "D1_FAILED", "D1_INCOMPLETE"}]) == 2


@pytest.mark.parametrize("damage", ["start", "decision", "event-time", "task", "author"])
def test_explicit_action_evidence_drift_still_rejected(tmp_path, monkeypatch, damage):
    host, source, incoming, native = live_checker(tmp_path, monkeypatch)
    host.record_checker_decision(source, "FAIL")
    request = downstream_request(host, source, incoming, "FAIL")
    if damage == "start":
        native["native_task"]["id"] = "different-review"
        write_json(source / "native-start.received.json", native)
    elif damage == "decision":
        path = source / "role-host" / "checker-decision.json"
        decision = json.loads(path.read_text())
        decision["verdict"] = "PASS"
        write_json(path, decision)
    else:
        runtime = Path(request["runtime_projection_path"])
        projection = json.loads(runtime.read_text())
        terminal = next(event for event in projection["events"] if event["event_type"] == "D1_FAILED")
        if damage == "event-time":
            terminal["occurred_at"] = native["observed_at"]
        elif damage == "author":
            terminal["author_role_instance_id"] = "different-checker"
        else:
            details = json.loads(terminal["details_json"])
            details["native_task_id"] = "different-review"
            terminal["details_json"] = json.dumps(details)
        write_json(runtime, projection)
    with pytest.raises(ValueError):
        checker_escalation._validate_failure(request)


@pytest.mark.parametrize("verdict,kind", [("FAIL", "D1_FAILURE_ESCALATION"),
    ("INCOMPLETE", "D1_INCOMPLETE_ESCALATION"), ("PASS", "D2_READY")])
def test_explicit_checker_submission_really_hands_off_once(tmp_path, monkeypatch, verdict, kind):
    from slk_transport.contracts import DeliveryResult, RESULT_SCHEMA
    from slk_transport.dispatcher import dispatch_once
    host, source, incoming, native = live_checker(tmp_path, monkeypatch)
    original_command = wc._run_json_command
    received = []
    class Receiver:
        def validate_address(self, endpoint):
            pass
        def deliver(self, endpoint, envelope, attempt):
            received.append(envelope)
            attempt.write_json_once("started.json", make_native_start(adapter=endpoint.adapter,
                run_id=envelope.run_id, cell_id=envelope.cell_id, message_id=envelope.message_id,
                request_sha256=envelope.payload_sha256, native_request_sha256=envelope.payload_sha256,
                native_task_kind="codex-turn", native_task_id="isolated-test-supervisor:turn-1",
                native_task_status="RUNNING", pid=__import__("os").getpid()))
            return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id,
                endpoint.adapter, "completed", {}, None, ("started.json",))
    def command(executable, arguments, **kwargs):
        if executable != host.transport:
            return original_command(executable, arguments, **kwargs)
        assert executable == host.transport and arguments[0] == "send"
        endpoint = json.loads(Path(arguments[arguments.index("--endpoint")+1]).read_text())
        envelope = json.loads(Path(arguments[arguments.index("--envelope")+1]).read_text())
        return dispatch_once(endpoint, envelope, arguments[arguments.index("--attempt-root")+1],
                             adapters={endpoint["adapter"]: Receiver()}).to_dict()
    monkeypatch.setattr(wc, "_run_json_command", command)
    result = host.submit_checker_decision(source, verdict)
    assert result["handoff"]["status"] == "OWNED_HANDOFF_COMMITTED"
    assert len(received) == 1 and received[0].payload_type == kind
    projection = host.projection()
    assert projection["runtime_snapshot"]["token_holder_role_instance_id"] == host.endpoint("supervisor")["role_instance_id"]
    assert projection["token_history"][-1]["message_id"] == received[0].message_id
    again = host.submit_checker_decision(source, verdict)
    assert again["handoff"]["status"] == "OWNED_HANDOFF_ALREADY_COMMITTED"
    assert len(received) == 1
    assert not (source / "ocrv-result.json").exists()
