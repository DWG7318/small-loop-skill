"""Ordinary jobs must run the owned suffix, without another Agent substituting."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from dataclasses import asdict

import pytest

from slk_transport import cli
from slk_transport.contracts import DeliveryResult
from slk_transport.contracts import Envelope
from slk_transport.role_host import RoleHost
from slk_transport.native_activity import make_native_start
from slk_transport import worker_completion as wc
from test_worker_completion import completion_fixture, write_json


def test_normal_job_consumes_frozen_host_binding_after_terminal(tmp_path, monkeypatch):
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    seen = []
    host = tmp_path / "role-host.json"
    host.write_text("{}")
    monkeypatch.setenv("SLK_TRANSPORT_ROLE_HOST", str(host))
    monkeypatch.setenv("SLK_TRANSPORT_ROLE_HOST_SHA256", hashlib.sha256(host.read_bytes()).hexdigest())
    terminal = DeliveryResult.from_dict(json.loads((attempt / "completed.json").read_text()))

    class Bound:
        def complete(self, source):
            assert source == attempt
            assert (source / "completed.json").is_file()
            seen.append("suffix")
            return {"status": "CHECKER_STARTED"}

    monkeypatch.setattr(cli, "load_role_host", lambda *args: seen.append("binding") or Bound(), raising=False)
    monkeypatch.setattr(cli, "dispatch_once", lambda *args, **kwargs: seen.append("delivery") or terminal)
    args = argparse.Namespace(endpoint=attempt / "endpoint.json", envelope=attempt / "envelope.json",
                              attempt_root=attempt.parents[1])
    assert cli._job(args) == 0
    assert seen == ["binding", "delivery", "suffix"]


def test_host_binding_is_checked_before_any_native_delivery(tmp_path, monkeypatch):
    attempt, _endpoint, _checker = completion_fixture(tmp_path)
    monkeypatch.setenv("SLK_TRANSPORT_ROLE_HOST", str(tmp_path / "missing.json"))
    monkeypatch.delenv("SLK_TRANSPORT_ROLE_HOST_SHA256", raising=False)
    monkeypatch.setattr(cli, "dispatch_once", lambda *a, **k: pytest.fail("invalid host binding dispatched work"))
    args = argparse.Namespace(endpoint=attempt / "endpoint.json", envelope=attempt / "envelope.json",
                              attempt_root=attempt.parents[1])
    with pytest.raises(ValueError):
        cli._job(args)


def prepared_host(tmp_path):
    attempt, worker, checker = completion_fixture(tmp_path)
    supervisor = {**checker, "role": "supervisor", "agent_runtime": "codex",
                  "adapter": "codex-app-server", "role_instance_id": "RUN-A-supervisor-001",
                  "address": {"thread_id": "isolated-test-supervisor"}}
    roles = {}
    for endpoint in (supervisor, checker, worker):
        role = endpoint["role"]
        path = write_json(tmp_path / f"{role}.json", endpoint)
        secret = tmp_path / f"{role}.dpapi"
        secret.write_text("unit-test-placeholder", encoding="ascii")
        roles[role] = {"endpoint_path": str(path), "endpoint_sha256": wc._sha256(path),
                       "credential_path": str(secret)}
    envelope = Envelope.from_dict(wc._read_object(attempt / "envelope.json", "test source"))
    binding = {"schema_version": "slk.role-host/v1", "run_id": "RUN-A", "plan_revision": 1,
               "state_command": ["state"], "transport_command": ["transport"], "roles": roles,
               "cells": [{"go_id": envelope.go_id, "cell_id": envelope.cell_id, "payload": envelope.payload}],
               "d2_criteria": ["both accepted"]}
    host = RoleHost(binding, "a" * 64)
    return host, attempt, envelope


@pytest.mark.parametrize("damage", ["open-payload", "wrong-ordinal", "missing-record"])
def test_preparation_rejects_unusable_next_cell_before_dispatch(tmp_path, damage):
    host, source, incoming = prepared_host(tmp_path)
    payload = {"cell_id": "CELL-002", "cell_ordinal": 2, "required_cell_count": 2,
        "task": "Implement the frozen second CELL", "d1_criteria": ["Independent acceptance"],
        "root_record_path": str(source / "envelope.json")}
    if damage == "open-payload": payload = {"cell_goal": "second", "instructions": "work"}
    if damage == "wrong-ordinal": payload["cell_ordinal"] = 1
    if damage == "missing-record": payload["root_record_path"] = str(tmp_path / "absent.md")
    binding = {**host.binding, "cells": [*host.binding["cells"],
        {"go_id": incoming.go_id, "cell_id": "CELL-002", "payload": payload}]}
    with pytest.raises(ValueError):
        RoleHost(binding, "b" * 64)


@pytest.mark.parametrize("damage", ["missing-goal", "extra-key", "empty-criteria"])
def test_preparation_rejects_unusable_first_task(tmp_path, damage):
    host, source, incoming = prepared_host(tmp_path)
    payload = dict(host.binding["cells"][0]["payload"])
    if damage == "missing-goal": payload.pop("cell_goal")
    if damage == "extra-key": payload["new_unregistered_action"] = "do it"
    if damage == "empty-criteria": payload["d1_criteria"] = []
    binding = {**host.binding, "cells": [{**host.binding["cells"][0], "payload": payload}]}
    with pytest.raises(ValueError):
        RoleHost(binding, "b" * 64)


def test_role_host_schema_matches_prepared_first_and_next_contract(tmp_path):
    import jsonschema
    host, source, incoming = prepared_host(tmp_path)
    schema = json.loads((Path(__file__).parents[2] / "docs/contracts/slk-role-host.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(host.binding, schema)
    bad = {**host.binding, "new_scheduler": "not-authorized"}
    with pytest.raises(jsonschema.ValidationError): jsonschema.validate(bad, schema)


def test_owned_send_authenticates_before_external_start(tmp_path, monkeypatch):
    host, attempt, envelope = prepared_host(tmp_path)
    (attempt / "owned").mkdir()
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda p: "sealed-test-secret")
    calls = []
    def run(command, arguments, **kwargs):
        calls.append(arguments[0])
        return {"status": "rejected"}
    monkeypatch.setattr(wc, "_run_json_command", run)
    with pytest.raises(ValueError):
        host._send_owned(attempt / "owned", envelope, "2026-10-04T00:00:00Z", {})
    assert calls == ["authenticate-role"]


def test_changed_sender_is_rejected_before_credentials_or_send(tmp_path, monkeypatch):
    host, attempt, envelope = prepared_host(tmp_path)
    (attempt / "owned").mkdir()
    changed = {**asdict(envelope), "sender_role_instance_id": "another-checker"}
    def forbidden(*a, **k):
        pytest.fail("wrong role was allowed to consume credentials or send")
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", forbidden)
    monkeypatch.setattr(wc, "_run_json_command", forbidden)
    with pytest.raises(ValueError):
        host._send_owned(attempt / "owned", Envelope.from_dict(changed), "2026-10-04T00:00:00Z", {})


def host_boundary(host, envelope):
    return {"summary": {"run_id": envelope.run_id}, "events": [], "token_history": [],
            "runtime_snapshot": {"plan_revision": 1, "runtime_revision": 7,
                "token_sequence": envelope.token_sequence - 1,
                "token_holder_role_instance_id": envelope.sender_role_instance_id,
                "latest_message_id": "source-message"}}


def authenticated_commands(monkeypatch, host, envelope, calls):
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda p: "sealed-test-secret")
    def run(command, arguments, **kwargs):
        calls.append(arguments[0])
        if arguments[0] != "authenticate-role":
            pytest.fail("invalid or uncertain handoff must not start another native job")
        return {"status": "authenticated", "run_id": envelope.run_id, "role": envelope.sender_role,
                "role_instance_id": envelope.sender_role_instance_id, "runtime_revision": 7}
    monkeypatch.setattr(wc, "_run_json_command", run)


def test_wrong_token_owner_is_rejected_before_native_start(tmp_path, monkeypatch):
    host, attempt, envelope = prepared_host(tmp_path)
    projection = host_boundary(host, envelope)
    projection["runtime_snapshot"]["token_holder_role_instance_id"] = "another-owner"
    monkeypatch.setattr(host, "projection", lambda: projection)
    calls = []
    authenticated_commands(monkeypatch, host, envelope, calls)
    with pytest.raises(wc.CompletionError):
        host._send_owned(attempt / "owned", envelope, "2026-10-04T00:00:00Z", projection)
    assert calls == ["authenticate-role"]


def test_existing_unknown_attempt_is_not_started_in_a_new_call(tmp_path, monkeypatch):
    host, attempt, envelope = prepared_host(tmp_path)
    projection = host_boundary(host, envelope)
    monkeypatch.setattr(host, "projection", lambda: projection)
    calls = []
    authenticated_commands(monkeypatch, host, envelope, calls)
    native = attempt / "owned" / "attempts" / envelope.run_id / envelope.message_id
    native.mkdir(parents=True)
    write_json(native / "endpoint.json", host.endpoint(envelope.receiver_role))
    with pytest.raises(ValueError):
        host._send_owned(attempt / "owned", envelope, "2026-10-04T00:00:00Z", projection)
    assert calls == ["authenticate-role"]


def native_delivery(root, host, envelope):
    native = root / "attempts" / envelope.run_id / envelope.message_id
    target = host.endpoint(envelope.receiver_role)
    write_json(native / "endpoint.json", target)
    write_json(native / "envelope.json", asdict(envelope))
    write_json(native / "started.json", make_native_start(
        adapter=target["adapter"], run_id=envelope.run_id, cell_id=envelope.cell_id,
        message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
        native_request_sha256="b" * 64, native_task_kind="dsh-session",
        native_task_id="session-isolated", native_task_status="RUNNING", pid=os.getpid()))
    return native


def committed_projection(host, envelope, native):
    projection = host_boundary(host, envelope)
    projection["runtime_snapshot"].update(token_sequence=envelope.token_sequence + 2,
        token_holder_role_instance_id="later-owner", latest_message_id="later-message")
    projection["token_history"] = [{"event_type": "TOKEN_HANDED_OFF",
        "message_id": envelope.message_id, "token_sequence": envelope.token_sequence,
        "go_id": envelope.go_id, "cell_id": envelope.cell_id,
        "from_role_instance_id": envelope.sender_role_instance_id,
        "to_role_instance_id": envelope.receiver_role_instance_id}]
    projection["events"] = [{"event_type": "TRANSPORT_STARTED", "corrects_event_id": None,
        "go_id": envelope.go_id, "cell_id": envelope.cell_id,
        "author_role_instance_id": envelope.sender_role_instance_id,
        "details_json": json.dumps({"message_id": envelope.message_id,
            "start_evidence_sha256": wc._sha256(native / "started.json"),
            "endpoint_sha256": wc._sha256(native / "endpoint.json"),
            "envelope_sha256": wc._sha256(native / "envelope.json")})}]
    return projection


def test_confirmed_old_handoff_is_read_only_even_after_token_advanced(tmp_path, monkeypatch):
    host, attempt, envelope = prepared_host(tmp_path)
    root = attempt / "owned"
    native = native_delivery(root, host, envelope)
    projection = committed_projection(host, envelope, native)
    monkeypatch.setattr(host, "projection", lambda: projection)
    calls = []
    authenticated_commands(monkeypatch, host, envelope, calls)
    result = host._send_owned(root, envelope, "2026-10-04T00:00:00Z", host_boundary(host, envelope))
    assert result["status"] == "OWNED_HANDOFF_ALREADY_COMMITTED"
    assert result["message_id"] == envelope.message_id
    assert calls == ["authenticate-role"]


@pytest.mark.parametrize("damage", ["token", "native", "duplicate"])
def test_replay_needs_exact_unique_token_and_native_evidence(tmp_path, monkeypatch, damage):
    host, attempt, envelope = prepared_host(tmp_path)
    root = attempt / "owned"
    native = native_delivery(root, host, envelope)
    projection = committed_projection(host, envelope, native)
    if damage == "token":
        projection["token_history"][0]["to_role_instance_id"] = "other-worker"
    elif damage == "native":
        value = wc._read_object(native / "started.json", "start")
        value["native_task"]["id"] = "session-substituted"
        write_json(native / "started.json", value)
    else:
        projection["events"].append(dict(projection["events"][0]))
    monkeypatch.setattr(host, "projection", lambda: projection)
    calls = []
    authenticated_commands(monkeypatch, host, envelope, calls)
    with pytest.raises(wc.CompletionError):
        host._send_owned(root, envelope, "2026-10-04T00:00:00Z", host_boundary(host, envelope))
    assert calls == ["authenticate-role"]


def test_native_started_commit_retry_preserves_original_request_and_does_not_resend(tmp_path, monkeypatch):
    host, attempt, envelope = prepared_host(tmp_path)
    root = attempt / "owned"
    native_delivery(root, host, envelope)
    projection = host_boundary(host, envelope)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda p: "sealed-test-secret")
    revision, committed = [7], []
    def command(_command, arguments, **kwargs):
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": envelope.run_id, "role": envelope.sender_role,
                    "role_instance_id": envelope.sender_role_instance_id, "runtime_revision": revision[0]}
        assert arguments[0] == "commit-delivery-start", "must reuse the existing native start"
        request = wc._read_object(Path(arguments[-1]), "commit")
        committed.append((Path(arguments[-1]), request))
        if len(committed) == 1:
            raise wc.CompletionError("RUNTIME_REVISION_CONFLICT", "unrelated observation advanced revision")
        return {"status": "committed", "message_id": envelope.message_id,
            "runtime_revision": revision[0] + 1, "token_sequence": envelope.token_sequence,
            "run_id": envelope.run_id, "token_owner_role_instance_id": envelope.receiver_role_instance_id}
    monkeypatch.setattr(wc, "_run_json_command", command)
    with pytest.raises(wc.CompletionError):
        host._send_owned(root, envelope, "2026-10-04T00:00:00Z", projection)
    original = committed[0][0].read_bytes()
    revision[0] = 8
    projection["runtime_snapshot"]["runtime_revision"] = 8
    result = host._send_owned(root, envelope, "2026-10-04T00:00:00Z", projection)
    assert result["status"] == "OWNED_HANDOFF_COMMITTED"
    receipt = wc._read_object(Path(result["commit_path"]).with_suffix(".result.json"), "commit receipt")
    assert receipt["status"] == "committed" and receipt["message_id"] == envelope.message_id
    assert committed[0][0].read_bytes() == original
    assert committed[0][0] != committed[1][0]
    assert {**committed[0][1], "expected_runtime_revision": 8} == committed[1][1]


def test_saved_handoff_cannot_hide_changed_original_engineering_result(tmp_path):
    host, attempt, envelope = prepared_host(tmp_path)
    hashes = {name: wc._sha256(attempt / name) for name in (
        "endpoint.json", "envelope.json", "started.json", "completed.json", "failed.json",
        "worker-result.json", "checker-result.json", "ocrv-result.json") if (attempt / name).is_file()}
    saved = {"status": "OWNED_HANDOFF_COMMITTED", "binding_sha256": host.digest,
             "source_message_id": envelope.message_id, "source_sha256": wc.canonical_json_sha256(hashes)}
    write_json(attempt / "role-host" / "result.json", saved)
    assert host.complete(attempt) == saved
    result_path = attempt / "worker-result.json"
    changed = wc._read_object(result_path, "Worker result")
    changed["candidate"] = {"kind": "commit", "commit": "f" * 40}
    write_json(result_path, changed)
    with pytest.raises(wc.CompletionError):
        host.complete(attempt)


def supervisor_result_fixture(tmp_path, *, d2=False):
    host, source, old = prepared_host(tmp_path)
    failure = {"d1_failure_event_id": "D1-failed", "failed_candidate_sha256": "a" * 64,
        "rework_round": 1, "cell_goal": "same goal", "acceptance_criteria": ["same criterion"],
        "findings": ["actual defect"], "reproduction_steps": ["run focused test"],
        "expected_result": "satisfy original criterion", "evidence_refs": [str(source / "envelope.json")]}
    payload = ({"d1_event_id": "D1-passed", "required_cell_ids": [old.cell_id], "accepted_cell_ids": [old.cell_id],
        "final_candidate_message_id": old.message_id, "d2_criteria": ["accepted whole result"],
        "evidence_refs": [str(source / "envelope.json")]} if d2 else failure)
    incoming = Envelope.from_dict({**asdict(old), "receiver_role": "supervisor",
        "receiver_role_instance_id": host.endpoint("supervisor")["role_instance_id"],
        "receiver_endpoint_version": host.endpoint("supervisor")["endpoint_version"],
        "payload_type": "D2_READY" if d2 else "D1_FAILURE_ESCALATION",
        "payload": payload, "payload_sha256": wc.canonical_json_sha256(payload)})
    write_json(source / "endpoint.json", host.endpoint("supervisor"))
    write_json(source / "envelope.json", asdict(incoming))
    identity = {"thread_id": "isolated-test-supervisor", "turn_id": "native-turn", "turn_status": "completed", "turn_sha256": "b" * 64}
    write_json(source / "started.json", make_native_start(adapter="codex-app-server",
        run_id=incoming.run_id, cell_id=incoming.cell_id, message_id=incoming.message_id,
        request_sha256=incoming.payload_sha256, native_request_sha256="b" * 64,
        native_task_kind="codex-turn", native_task_id="isolated-test-supervisor:native-turn",
        native_task_status="RUNNING", pid=os.getpid()))
    terminal = wc._read_object(source / "completed.json", "terminal")
    write_json(source / "completed.json", {**terminal, "adapter": "codex-app-server", "native_identity": identity})
    decision = ({"verdict": "PASS", "summary": "independently verified whole sample", "evidence_refs": failure["evidence_refs"]}
        if d2 else {**{k: v for k, v in failure.items() if k not in {"reproduction_steps", "expected_result"}},
        "investigation_mode": "STANDARD", "root_cause_hypothesis": "one cause",
        "minimal_experiment": "one focused check", "minimal_repair_scope": "same function", "regression_target": "same criterion"})
    result = {"schema_version": "slk.supervisor-result/v1", "source_message_id": incoming.message_id,
        "operation": "d2" if d2 else "rework", "decision": decision}
    write_json(source / "supervisor-result.json", result)
    projection = host_boundary(host, incoming)
    projection["runtime_snapshot"].update(token_sequence=incoming.token_sequence,
        token_holder_role_instance_id=incoming.receiver_role_instance_id, latest_message_id=incoming.message_id)
    projection["events"] = [{"event_type": "TRANSPORT_STARTED", "cell_id": incoming.cell_id,
        "attempt": 2, "details_json": json.dumps({"message_id": incoming.message_id})}]
    return host, source, incoming, result, projection


@pytest.mark.parametrize("d2", [False, True])
def test_native_supervisor_decision_uses_own_sealed_suffix_only(tmp_path, monkeypatch, d2):
    host, source, incoming, result, projection = supervisor_result_fixture(tmp_path, d2=d2)
    monkeypatch.setattr(host, "_boundary", lambda envelope: projection)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda path: "sealed-supervisor")
    seen = []
    def run(command, args, **kwargs):
        assert kwargs["credential"] == "sealed-supervisor"
        if args[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": incoming.run_id, "role": "supervisor",
                "role_instance_id": incoming.receiver_role_instance_id, "runtime_revision": 7}
        assert args[0] == "write"
        event = wc._read_object(Path(args[-1]), "event")
        seen.append(event)
        assert event["role_instance_id"] == incoming.receiver_role_instance_id
        return {"status": "recorded", "run_id": incoming.run_id}
    monkeypatch.setattr(wc, "_run_json_command", run)
    sent = []
    def send(root, envelope, occurred, snapshot):
        sent.append(envelope)
        assert [e["event_type"] for e in seen] == ["REWORK_REQUESTED"]
        return {"status": "OWNED_HANDOFF_COMMITTED", "message_id": envelope.message_id}
    monkeypatch.setattr(host, "_send_owned", send)
    receipt = host.complete(source)
    if d2:
        assert [e["event_type"] for e in seen] == ["D2_STARTED", "D2_PASSED"]
        assert not sent and receipt["status"] == "SUPERVISOR_D2_RECORDED"
    else:
        assert receipt["status"] == "OWNED_HANDOFF_COMMITTED"
        assert sent[0].payload == result["decision"]
        assert sent[0].sender_role == "supervisor" and sent[0].receiver_role == "worker"
        assert seen[0]["attempt"] == 2
        assert seen[0]["details"]["d1_failure_event_id"] == incoming.payload["d1_failure_event_id"]
    assert host.complete(source) == receipt
    assert len(seen) == (2 if d2 else 1)


@pytest.mark.parametrize("damage", ["wrong-source", "wrong-failure", "changed-criteria", "d1-takeover", "missing"])
def test_supervisor_result_cannot_replace_d1_or_other_identity(tmp_path, monkeypatch, damage):
    host, source, incoming, result, projection = supervisor_result_fixture(tmp_path)
    if damage == "wrong-source": result["source_message_id"] = "another-message"
    if damage == "wrong-failure": result["decision"]["d1_failure_event_id"] = "older-failure"
    if damage == "changed-criteria": result["decision"]["acceptance_criteria"] = ["weaker"]
    if damage == "d1-takeover": result["operation"] = "d1"
    write_json(source / "supervisor-result.json", result)
    if damage == "missing": (source / "supervisor-result.json").unlink()
    monkeypatch.setattr(host, "_boundary", lambda envelope: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda path: pytest.fail("invalid decision consumed credential"))
    with pytest.raises(wc.CompletionError):
        host.complete(source)


@pytest.mark.parametrize("damage", ["wrong-terminal", "wrong-start", "wrong-turn", "failed-and-completed"])
def test_supervisor_suffix_requires_matching_native_completion(tmp_path, monkeypatch, damage):
    host, source, incoming, result, projection = supervisor_result_fixture(tmp_path)
    if damage == "wrong-start":
        path = source / "started.json"
        value = wc._read_object(path, "start")
        value["request_sha256"] = "c" * 64
    else:
        path = source / "completed.json"
        value = wc._read_object(path, "terminal")
        if damage == "wrong-terminal": value["run_id"] = "OTHER-RUN"
        if damage == "wrong-turn": value["native_identity"]["turn_id"] = "other-turn"
        if damage == "failed-and-completed": write_json(source / "failed.json", {**value, "status": "failed"})
    write_json(path, value)
    monkeypatch.setattr(host, "_boundary", lambda envelope: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda path: pytest.fail("unproved native completion consumed credentials"))
    with pytest.raises(wc.CompletionError): host.complete(source)


def test_rework_delivery_commits_new_attempt_not_first_attempt(tmp_path, monkeypatch):
    host, source, incoming, result, projection = supervisor_result_fixture(tmp_path)
    decision = result["decision"]
    outgoing = Envelope.from_dict({**asdict(incoming), "message_id": wc._stable_id(incoming.message_id, "supervisor-rework"),
        "token_sequence": incoming.token_sequence + 1, "sender_role": "supervisor",
        "sender_role_instance_id": incoming.receiver_role_instance_id, "receiver_role": "worker",
        "receiver_role_instance_id": host.endpoint("worker")["role_instance_id"], "receiver_endpoint_version": 1,
        "payload_type": "D1_REWORK_DIRECTIVE", "payload": decision, "payload_sha256": wc.canonical_json_sha256(decision)})
    projection["events"].append({"event_type": "REWORK_REQUESTED", "cell_id": incoming.cell_id, "go_id": incoming.go_id,
        "attempt": 2, "details_json": json.dumps({k: decision[k] for k in ("d1_failure_event_id", "failed_candidate_sha256", "rework_round", "investigation_mode")})})
    root = source / "role-host" / "rework"
    native_delivery(root, host, outgoing)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda p: "sealed-test-secret")
    def run(command, args, **kwargs):
        if args[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": incoming.run_id, "role": "supervisor",
                "role_instance_id": incoming.receiver_role_instance_id, "runtime_revision": 7}
        assert args[0] == "commit-delivery-start"
        request = wc._read_object(Path(args[-1]), "commit")
        assert request["attempt"] == 3
        return {"status": "committed", "run_id": incoming.run_id, "message_id": outgoing.message_id,
            "runtime_revision": 8, "token_sequence": outgoing.token_sequence,
            "token_owner_role_instance_id": outgoing.receiver_role_instance_id}
    monkeypatch.setattr(wc, "_run_json_command", run)
    assert host._send_owned(root, outgoing, "2026-10-05T00:00:00Z", projection)["status"] == "OWNED_HANDOFF_COMMITTED"


def test_rework_commit_survives_missing_host_receipt_without_second_write_or_send(tmp_path, monkeypatch):
    host, source, incoming, result, projection = supervisor_result_fixture(tmp_path)
    decision = result["decision"]
    outgoing = Envelope.from_dict({**asdict(incoming), "message_id": wc._stable_id(incoming.message_id, "supervisor-rework"),
        "token_sequence": incoming.token_sequence + 1, "sender_role": "supervisor",
        "sender_role_instance_id": incoming.receiver_role_instance_id, "receiver_role": "worker",
        "receiver_role_instance_id": host.endpoint("worker")["role_instance_id"], "receiver_endpoint_version": 1,
        "payload_type": "D1_REWORK_DIRECTIVE", "payload": decision, "payload_sha256": wc.canonical_json_sha256(decision)})
    root = source / "role-host"
    write_json(root / "supervisor-decision.json", result)
    native = native_delivery(root / "rework", host, outgoing)
    projection = committed_projection(host, outgoing, native)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(host, "_boundary", lambda _: pytest.fail("already committed handoff cannot wait for old TOKEN"))
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda path: "sealed-test-secret")
    monkeypatch.setattr(host, "_authenticate", lambda *a: {})
    monkeypatch.setattr(wc, "_run_json_command", lambda *a, **k: pytest.fail("committed replay must not write or resend"))
    assert host.complete(source)["status"] == "OWNED_HANDOFF_ALREADY_COMMITTED"


@pytest.mark.parametrize("field,value", [("go_id", "OTHER-GO"), ("cell_id", "OTHER-CELL"),
    ("token_sequence", 99), ("payload_type", "CANDIDATE_READY")])
def test_initial_checker_cannot_change_dispatch_scope(tmp_path, field, value):
    host, source, outgoing = prepared_host(tmp_path)
    outgoing = Envelope.from_dict({**asdict(outgoing), "token_sequence": 2})
    incoming = Envelope.from_dict({**asdict(outgoing), "message_id": "80f488e8-e35c-4587-85bc-0453a6ee30db",
        "token_sequence": outgoing.token_sequence - 1, "sender_role": "supervisor",
        "sender_role_instance_id": host.endpoint("supervisor")["role_instance_id"],
        "receiver_role": "checker", "receiver_role_instance_id": host.endpoint("checker")["role_instance_id"],
        "receiver_endpoint_version": host.endpoint("checker")["endpoint_version"], "payload_type": "CELL_DISPATCH"})
    result = {"schema_version": "slk.checker-result/v1", "operation": "dispatch", "source_message_id": incoming.message_id,
        "next_endpoint": host.endpoint("worker"), "next_envelope": {**asdict(outgoing), field: value}}
    with pytest.raises(wc.CompletionError):
        host._dispatch_envelope(incoming, result)
