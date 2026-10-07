"""Ordinary jobs must run the owned suffix, without another Agent substituting."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from dataclasses import asdict

import pytest

from slk_transport import cli
from slk_transport import role_host as role_host_module
from slk_transport.contracts import DeliveryResult
from slk_transport.contracts import Envelope
from slk_transport.role_host import RoleHost, normalized_checker_findings
from slk_transport.native_activity import make_native_start
from slk_transport import worker_completion as wc
from slk_transport import checker_management
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


def test_continue_staged_handoff_cli_uses_hash_bound_original_sender_host(
    tmp_path, monkeypatch, capsys,
):
    binding = write_json(tmp_path / "role-host.json", {"binding": "test"})
    digest = hashlib.sha256(binding.read_bytes()).hexdigest()
    source = tmp_path / "canonical" / "RUN-A" / "message-a"
    source.mkdir(parents=True)
    seen = []

    class Bound:
        def continue_staged_handoff(self, staged, **options):
            seen.append((staged, options))
            return {"status": "OWNED_HANDOFF_COMMITTED", "message_id": "message-a"}

    monkeypatch.setattr(
        cli, "RoleHost",
        lambda value, actual: Bound() if value == {"binding": "test"} and actual == digest
        else pytest.fail("binding identity changed"),
    )
    args = argparse.Namespace(binding=binding, sha256=digest, source_attempt=source,
                              temporal_request=None, temporal_request_sha256=None)

    assert cli._continue_staged_handoff(args) == 0
    assert seen == [(source.resolve(), {
        "temporal_request_path": None,
        "temporal_request_sha256": None,
    })]
    assert json.loads(capsys.readouterr().out)["status"] == "OWNED_HANDOFF_COMMITTED"


def test_reclassify_checker_cli_uses_hash_bound_role_host(tmp_path, monkeypatch, capsys):
    binding = write_json(tmp_path / "role-host.json", {"binding": "test"})
    digest = hashlib.sha256(binding.read_bytes()).hexdigest()
    source = tmp_path / "attempt"
    source.mkdir()
    seen = []

    class Bound:
        def reclassify_completed_checker(self, attempt):
            seen.append(attempt)
            return {"status": "CHECKER_ESCALATION_COMMITTED"}

    monkeypatch.setattr(
        cli, "RoleHost",
        lambda value, actual: Bound() if value == {"binding": "test"} and actual == digest
        else pytest.fail("binding identity changed"),
    )
    args = argparse.Namespace(binding=binding, sha256=digest, source_attempt=source)

    assert cli._reclassify_completed_checker(args) == 0
    assert seen == [source.resolve()]
    assert json.loads(capsys.readouterr().out)["status"] == "CHECKER_ESCALATION_COMMITTED"


def test_checker_findings_strip_provider_thinking_before_supervisor_escalation():
    findings = normalized_checker_findings([
        {"severity": "HIGH", "message": "real defect", "thinking": "private chain",
         "evidence": {"path": "proof.txt", "analysis": "provider scratchpad"}}
    ])

    assert findings == [json.dumps(
        {"evidence": {"path": "proof.txt"}, "message": "real defect", "severity": "HIGH"},
        ensure_ascii=False, sort_keys=True,
    )]


def test_checker_incomplete_hands_control_to_supervisor_without_a_fail_or_rework(
    tmp_path, monkeypatch
):
    host, source, envelope = prepared_host(tmp_path)
    root = tmp_path / "checker-host"
    root.mkdir()
    current = host_boundary(host, envelope)
    event_id = wc._stable_id(envelope.message_id, "d1-result-v2")
    current["events"] = [{
        "event_id": event_id,
        "event_type": "D1_INCOMPLETE",
        "author_role_instance_id": envelope.receiver_role_instance_id,
        "go_id": envelope.go_id,
        "cell_id": envelope.cell_id,
        "attempt": 1,
        "corrects_event_id": None,
        "details_json": json.dumps({
            "candidate_message_id": envelope.message_id,
            "verdict": "INCOMPLETE",
            "reason_codes": ["OCR_STATUS_NOT_COMPLETE"],
        }),
    }]
    current["runtime_snapshot"].update({
        "latest_event_id": event_id,
        "runtime_revision": 8,
        "token_sequence": envelope.token_sequence,
        "token_holder_role_instance_id": envelope.receiver_role_instance_id,
        "latest_message_id": envelope.message_id,
    })
    monkeypatch.setattr(wc, "_source_attempt", lambda *_args: 1)
    monkeypatch.setattr(
        wc,
        "_record_checker_d1",
        lambda *_args, **_kwargs: {
            "status": "CHECKER_D1_RECORDED",
            "d1_verdict": "INCOMPLETE",
            "d1_event_type": "D1_INCOMPLETE",
        },
    )
    monkeypatch.setattr(host, "projection", lambda: current)
    def manage(request, **_kwargs):
        assert request["d1_incomplete_event_id"] == event_id
        assert request["reason_codes"] == ["OCR_STATUS_NOT_COMPLETE"]
        return {"status": "CHECKER_INCOMPLETE_ESCALATION_COMMITTED",
                "d1_incomplete_event_id": event_id}
    monkeypatch.setattr(checker_management, "execute_checker_management", manage)

    result = host._checker_result(
        source, envelope, root, "2026-10-06T08:00:00Z", host_boundary(host, envelope)
    )

    assert result["status"] == "CHECKER_INCOMPLETE_ESCALATION_COMMITTED"
    assert result["d1_incomplete_event_id"] == event_id
    assert wc._read_object(root / "d1-projection.json", "D1 projection") == current


def test_completed_tool_failure_with_blocker_is_corrected_without_rerunning_ocrv(
    tmp_path, monkeypatch,
):
    from slk_transport import checker_escalation

    host, source, old = prepared_host(tmp_path)
    checker = host.endpoint("checker")
    worker = host.endpoint("worker")
    payload = {
        "repository": str((tmp_path / "repository").resolve()),
        "candidate": {"kind": "commit", "commit": "b" * 40},
        "cell_goal": "preserve first-use credential freshness",
        "d1_criteria": ["freshness is fail-closed"],
        "evidence_files": [str((source / "completed.json").resolve())],
    }
    incoming = Envelope.from_dict({
        **asdict(old),
        "sender_role": "worker",
        "sender_role_instance_id": worker["role_instance_id"],
        "receiver_role": "checker",
        "receiver_role_instance_id": checker["role_instance_id"],
        "receiver_endpoint_version": checker["endpoint_version"],
        "payload_type": "CANDIDATE_READY",
        "payload": payload,
        "payload_sha256": wc.canonical_json_sha256(payload),
    })
    write_json(source / "endpoint.json", checker)
    write_json(source / "envelope.json", asdict(incoming))
    write_json(source / "started.json", make_native_start(
        adapter="ocrv-checker", run_id=incoming.run_id, cell_id=incoming.cell_id,
        message_id=incoming.message_id, request_sha256=incoming.payload_sha256,
        native_request_sha256="d" * 64, native_task_kind="ocrv-review",
        native_task_id="review-1", native_task_status="RUNNING", pid=os.getpid(),
    ))
    raw_path = write_json(tmp_path / "ocrv" / "review-1" / "ocrv-review.json", {
        "status": "complete", "provider": "dashscope-tokenplan", "model": "qwen3.8-max",
        "session_id": "session-review-1", "tool_calls": {"failure": 1},
        "comments": [{"severity": "medium", "message": "real blocker"}],
        "manifest": {"terminal_state": "complete", "coverage": {
            "selected": [{"item_id": "criterion-1"}],
            "completed": [{"item_id": "criterion-1"}], "reused": [],
            "failed": [], "waived": [],
        }},
    })
    result = {
        "schema_version": "slk.ocrv-d1-result/v1", "run_id": incoming.run_id,
        "cell_id": incoming.cell_id, "review_invocation_id": "review-1",
        "verdict": "INCOMPLETE", "reason_codes": ["OCR_TOOL_FAILURE"],
        "findings": [{"severity": "medium", "message": "real blocker"}],
        "review": {"status": "complete", "provider": "dashscope-tokenplan",
                   "model": "qwen3.8-max", "session_id": "session-review-1", "exit_code": 0},
        "evidence": [], "request_sha256": "d" * 64,
        "artifacts": {"raw_review": str(raw_path)},
    }
    write_json(source / "ocrv-result.json", result)
    terminal = {
        "schema_version": "slk.transport-result/v1", "message_id": incoming.message_id,
        "run_id": incoming.run_id, "adapter": "ocrv-checker", "status": "completed",
        "native_identity": {"run_id": incoming.run_id, "cell_id": incoming.cell_id,
            "review_invocation_id": "review-1", "session_id": "session-review-1",
            "provider": "dashscope-tokenplan", "model": "qwen3.8-max",
            "verdict": "INCOMPLETE", "exit_code": 3, "review_segment_count": 0},
        "error_code": None, "evidence": ["started.json", "ocrv-result.json"],
    }
    write_json(source / "completed.json", terminal)
    source_event_id = "d1-incomplete"
    event = {"event_id": source_event_id, "event_type": "D1_INCOMPLETE",
        "author_role_instance_id": checker["role_instance_id"], "go_id": incoming.go_id,
        "cell_id": incoming.cell_id, "attempt": 1, "corrects_event_id": None,
        "details_json": json.dumps({"candidate_message_id": incoming.message_id,
            "verdict": "INCOMPLETE", "native_terminal_sha256": wc._sha256(source / "completed.json"),
            "native_result_sha256": wc._sha256(source / "ocrv-result.json")})}
    projection = {"summary": {"run_id": incoming.run_id, "slk_version": "4.4.2",
        "current_plan_revision": 1}, "events": [event], "token_history": [],
        "runtime_snapshot": {"method_version": "4.4.2", "plan_revision": 1,
            "runtime_revision": 8, "token_sequence": incoming.token_sequence,
            "token_holder_role_instance_id": checker["role_instance_id"],
            "latest_message_id": incoming.message_id, "latest_event_id": source_event_id}}
    root = source / "role-host"
    root.mkdir(exist_ok=True)
    write_json(root / "result.json", {"binding_sha256": host.digest,
        "source_message_id": incoming.message_id,
        "source_sha256": host._source_sha256(source, "checker"),
        "status": "CHECKER_D1_RECORDED", "d1_verdict": "INCOMPLETE",
        "d1_event_type": "D1_INCOMPLETE"})

    def record(activation, continuation, **_kwargs):
        correction = Path(activation["native_attempt_path"])
        assert wc._read_object(correction / "ocrv-result.json", "corrected")["verdict"] == "FAIL"
        assert continuation["d1_correction_kind"] == "classification"
        corrected_id = wc._stable_id(
            incoming.message_id, "d1-classification-" + continuation["d1_correction_id"]
        )
        projection["events"].append({"event_id": corrected_id, "event_type": "D1_FAILED",
            "author_role_instance_id": checker["role_instance_id"], "go_id": incoming.go_id,
            "cell_id": incoming.cell_id, "attempt": 1,
            "corrects_event_id": source_event_id,
            "details_json": json.dumps({"candidate_message_id": incoming.message_id,
                                         "verdict": "FAIL"})})
        projection["runtime_snapshot"]["latest_event_id"] = corrected_id
        projection["runtime_snapshot"]["runtime_revision"] = 9
        return {"d1_verdict": "FAIL", "d1_event_type": "D1_FAILED"}

    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "_record_checker_d1", record)
    def escalate(request, *_args, **_kwargs):
        assert Path(request["escalation_attempt_root"]).is_dir()
        return {"status": "CHECKER_ESCALATION_COMMITTED"}

    monkeypatch.setattr(checker_escalation, "execute_checker_escalation", escalate)

    value = host.reclassify_completed_checker(source)

    assert value["status"] == "CHECKER_ESCALATION_COMMITTED"
    receipt = wc._read_object(
        root / "classification-correction" / "normalization-correction.json", "receipt"
    )
    assert receipt["source_incomplete_event_id"] == source_event_id
    assert receipt["reason_codes"] == ["OCR_BLOCKING_FINDINGS_PRESENT", "OCR_TOOL_FAILURE"]


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
    envelope_raw = wc._read_object(attempt / "envelope.json", "test source")
    envelope_raw["token_sequence"] = 3
    write_json(attempt / "envelope.json", envelope_raw)
    envelope = Envelope.from_dict(envelope_raw)
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
    return {"summary": {"run_id": envelope.run_id, "slk_version": "4.4.2", "current_plan_revision": 1},
            "events": [], "token_history": [],
            "runtime_snapshot": {"method_version": "4.4.2", "plan_revision": 1, "runtime_revision": 7,
                "token_sequence": envelope.token_sequence - 1,
                "token_holder_role_instance_id": envelope.sender_role_instance_id,
                "latest_message_id": "source-message"}}


def run06_historical_null_boundary(envelope):
    message_id = "c13ee3db-524e-4011-a7f3-ba02386e5599"
    projection = {
        "summary": {"run_id": envelope.run_id, "slk_version": "4.4.2", "current_plan_revision": 1},
        "runtime_snapshot": {"run_id": envelope.run_id, "method_version": "4.4.2", "plan_revision": 1,
            "runtime_revision": 15, "token_sequence": 3,
            "token_holder_role_instance_id": envelope.receiver_role_instance_id,
            "latest_message_id": None},
        "token_history": [{"event_type": "TOKEN_HANDED_OFF", "message_id": message_id,
            "token_sequence": 3, "go_id": envelope.go_id, "cell_id": envelope.cell_id,
            "from_role_instance_id": envelope.sender_role_instance_id,
            "to_role_instance_id": envelope.receiver_role_instance_id}],
        "events": [{"event_id": "transport-start-cell01-t003-mcp-startup-20261004t081141z",
            "event_type": "TRANSPORT_STARTED", "corrects_event_id": None,
            "go_id": envelope.go_id, "cell_id": envelope.cell_id,
            "author_role_instance_id": envelope.sender_role_instance_id, "plan_revision": 1,
            "details_json": json.dumps({"message_id": message_id,
                "endpoint_sha256": "348444cc80aef5a5e330dd576b57c542364db0191d8d44ec79fad17e6b2bbaa2",
                "envelope_sha256": "19a436c76c220e91d1c9efca89bc14650b6cefcac849d1c7d596e19bfb77765d",
                "start_evidence_sha256": "521542adc90d5fd07ea14ebf34d47f559613423b01b820e6d89357ac47b2111c"})}],
    }
    return projection


def test_role_host_boundary_uses_exact_authoritative_token_when_snapshot_message_is_historical_null(
    tmp_path, monkeypatch,
):
    host, _attempt, original = prepared_host(tmp_path)
    incoming = Envelope.from_dict({**asdict(original),
        "message_id": "c13ee3db-524e-4011-a7f3-ba02386e5599", "token_sequence": 3})
    projection = run06_historical_null_boundary(incoming)
    monkeypatch.setattr(host, "projection", lambda: projection)
    ticks = iter((0.0, 11.0))
    monkeypatch.setattr(role_host_module.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(role_host_module.time, "sleep", lambda _seconds: None)

    assert host._boundary(incoming) is projection


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


def test_owned_handoff_preserves_safe_central_commit_rejection(tmp_path, monkeypatch):
    host, attempt, envelope = prepared_host(tmp_path)
    root = attempt / "owned"
    native_delivery(root, host, envelope)
    projection = host_boundary(host, envelope)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _p: "sealed-test-secret")

    def command(_command, arguments, **_kwargs):
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": envelope.run_id,
                    "role": envelope.sender_role,
                    "role_instance_id": envelope.sender_role_instance_id,
                    "runtime_revision": 7}
        if arguments[0] == "commit-delivery-start":
            return {"status": "error", "code": "SLK_OVERWATCHER_INACTIVE",
                    "message": "foreground turn continuity violation blocks new dispatch"}
        pytest.fail(f"unexpected command: {arguments[0]}")

    monkeypatch.setattr(wc, "_run_json_command", command)
    with pytest.raises(wc.CompletionError) as rejected:
        host._send_owned(root, envelope, "2026-10-04T00:00:00Z", projection)

    assert rejected.value.error_code == "SLK_OVERWATCHER_INACTIVE"
    assert str(rejected.value) == "foreground turn continuity violation blocks new dispatch"


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


def test_native_supervisor_can_record_incomplete_management_without_fabricating_fail_or_rework(
    tmp_path, monkeypatch,
):
    host, source, incoming, _result, projection = supervisor_result_fixture(tmp_path)
    payload = {
        "d1_incomplete_event_id": "D1-incomplete",
        "candidate_message_id": incoming.message_id,
        "reason_codes": ["OCR_STATUS_NOT_COMPLETE"],
        "evidence": [{"path": str(source / "envelope.json"), "sha256": "a" * 64}],
        "native_terminal_sha256": "b" * 64,
        "native_result_sha256": "c" * 64,
        "decision_required": "CAPACITY_OR_ENVIRONMENT_MANAGEMENT",
    }
    incoming = Envelope.from_dict({
        **asdict(incoming),
        "payload_type": "D1_INCOMPLETE_ESCALATION",
        "payload": payload,
        "payload_sha256": wc.canonical_json_sha256(payload),
    })
    write_json(source / "envelope.json", asdict(incoming))
    decision = {
        "action": "MECHANICAL_RECOVERY",
        "summary": "Retry only after the capacity cause is corrected.",
        "evidence_refs": [str(source / "envelope.json")],
    }
    write_json(source / "supervisor-result.json", {
        "schema_version": "slk.supervisor-result/v1",
        "source_message_id": incoming.message_id,
        "operation": "management",
        "decision": decision,
    })
    monkeypatch.setattr(host, "_completion_proof", lambda *_args: None)
    monkeypatch.setattr(host, "_boundary", lambda _envelope: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _path: "sealed-supervisor")
    monkeypatch.setattr(host, "_authenticate", lambda role, credential: {
        "status": "authenticated", "run_id": incoming.run_id, "role": role,
        "role_instance_id": incoming.receiver_role_instance_id, "runtime_revision": 7,
    })
    monkeypatch.setattr(wc, "_run_json_command", lambda *_args, **_kwargs: pytest.fail(
        "management decision must not invent a D1 event or rework delivery"
    ))
    monkeypatch.setattr(host, "_send_owned", lambda *_args, **_kwargs: pytest.fail(
        "management decision must not dispatch ordinary rework"
    ))

    receipt = host.complete(source)

    assert receipt["status"] == "SUPERVISOR_MANAGEMENT_RECORDED"
    assert receipt["action"] == "MECHANICAL_RECOVERY"


@pytest.mark.parametrize("rework_round", [2, 3])
def test_second_or_later_d1_failure_cannot_use_old_host_as_ordinary_rework(
    tmp_path, monkeypatch, rework_round,
):
    host, source, incoming, result, projection = supervisor_result_fixture(tmp_path)
    payload = {**incoming.payload, "rework_round": rework_round}
    incoming = Envelope.from_dict({**asdict(incoming), "payload": payload,
        "payload_sha256": wc.canonical_json_sha256(payload)})
    write_json(source / "envelope.json", asdict(incoming))
    result["decision"]["rework_round"] = rework_round
    result["decision"]["investigation_mode"] = "AGGRESSIVE"
    write_json(source / "supervisor-result.json", result)
    monkeypatch.setattr(host, "_completion_proof", lambda *_args: None)
    monkeypatch.setattr(host, "_boundary", lambda envelope: projection)
    monkeypatch.setattr(host, "_send_owned", lambda *_args, **_kwargs: pytest.fail(
        "second D1 failure must not be sent as ordinary rework"))

    with pytest.raises(wc.CompletionError) as error:
        host.complete(source)

    assert error.value.error_code == "ROLE_HOST_CELL_SPLIT_REQUIRED"


def test_revised_host_dispatches_first_split_successor_and_old_host_rejects_revision(tmp_path, monkeypatch):
    old_host, source, original = prepared_host(tmp_path)
    first_payload = {"cell_goal": "Implement bounded half A", "d1_criteria": ["A is independently accepted"]}
    second_payload = {"cell_id": "CELL-001-B", "cell_ordinal": 2, "required_cell_count": 2,
        "task": "Implement bounded half B", "d1_criteria": ["B is independently accepted"],
        "root_record_path": str(source / "envelope.json")}
    revised_binding = {**old_host.binding, "plan_revision": 2, "cells": [
        {"go_id": original.go_id, "cell_id": "CELL-001-A", "payload": first_payload},
        {"go_id": original.go_id, "cell_id": "CELL-001-B", "payload": second_payload},
    ]}
    revised = RoleHost(revised_binding, "b" * 64)
    checker = revised.endpoint("checker")
    dispatch_payload = {"worker_endpoint": revised.endpoint("worker"), "worker_payload": first_payload}
    incoming = Envelope.from_dict({**asdict(original), "cell_id": "CELL-001-A",
        "sender_role": "supervisor",
        "sender_role_instance_id": revised.endpoint("supervisor")["role_instance_id"],
        "receiver_role": "checker", "receiver_role_instance_id": checker["role_instance_id"],
        "receiver_endpoint_version": checker["endpoint_version"], "payload_type": "CELL_DISPATCH",
        "payload": dispatch_payload, "payload_sha256": wc.canonical_json_sha256(dispatch_payload)})
    write_json(source / "endpoint.json", checker)
    write_json(source / "envelope.json", asdict(incoming))
    write_json(source / "started.json", make_native_start(
        adapter=checker["adapter"], run_id=incoming.run_id, cell_id=incoming.cell_id,
        message_id=incoming.message_id, request_sha256=incoming.payload_sha256,
        native_request_sha256="c" * 64, native_task_kind="ocrv-review",
        native_task_id="checker-dispatch-review", native_task_status="RUNNING", pid=os.getpid()))
    write_json(source / "completed.json", DeliveryResult(
        schema_version="slk.transport-result/v1", message_id=incoming.message_id,
        run_id=incoming.run_id, adapter=checker["adapter"], status="completed",
        native_identity={}, error_code=None, evidence=()).to_dict())
    outgoing = Envelope.from_dict({**asdict(incoming),
        "message_id": "33333333-3333-4333-8333-333333333333",
        "token_sequence": incoming.token_sequence + 1, "sender_role": "checker",
        "sender_role_instance_id": checker["role_instance_id"], "receiver_role": "worker",
        "receiver_role_instance_id": revised.endpoint("worker")["role_instance_id"],
        "receiver_endpoint_version": revised.endpoint("worker")["endpoint_version"],
        "payload_type": "WORKER_TASK", "payload": first_payload,
        "payload_sha256": wc.canonical_json_sha256(first_payload)})
    write_json(source / "checker-result.json", {"schema_version": "slk.checker-result/v1",
        "operation": "dispatch", "source_message_id": incoming.message_id,
        "next_endpoint": revised.endpoint("worker"), "next_envelope": asdict(outgoing)})
    revised_projection = host_boundary(revised, incoming)
    revised_projection["summary"]["current_plan_revision"] = 2
    revised_projection["runtime_snapshot"]["plan_revision"] = 2
    monkeypatch.setattr(revised, "_boundary", lambda _envelope: revised_projection)
    monkeypatch.setattr(revised, "_send_owned", lambda _root, envelope, *_args: {
        "status": "OWNED_HANDOFF_COMMITTED", "message_id": envelope.message_id})

    assert revised.complete(source)["status"] == "OWNED_HANDOFF_COMMITTED"
    monkeypatch.setattr(old_host, "projection", lambda: revised_projection)
    with pytest.raises(wc.CompletionError) as error:
        old_host._boundary(incoming)
    assert error.value.error_code == "ROLE_HOST_PLAN_CHANGED"


def test_supervisor_can_submit_decision_from_exact_session_before_turn_terminal(tmp_path, monkeypatch):
    host, source, incoming, result, projection = supervisor_result_fixture(tmp_path)
    (source / "completed.json").unlink()
    monkeypatch.setenv("CODEX_THREAD_ID", host.endpoint("supervisor")["address"]["thread_id"])
    monkeypatch.setattr(host, "_boundary", lambda envelope: projection)
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda path: "sealed-supervisor")
    events = []

    def run(command, args, **kwargs):
        if args[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": incoming.run_id, "role": "supervisor",
                    "role_instance_id": incoming.receiver_role_instance_id, "runtime_revision": 7}
        events.append(wc._read_object(Path(args[-1]), "event"))
        return {"status": "recorded", "run_id": incoming.run_id}

    monkeypatch.setattr(wc, "_run_json_command", run)
    monkeypatch.setattr(host, "_send_owned", lambda *args: {
        "status": "OWNED_HANDOFF_COMMITTED", "message_id": "rework-message"})

    receipt = host.submit_supervisor_decision(source)

    assert receipt["status"] == "OWNED_HANDOFF_COMMITTED"
    assert [event["event_type"] for event in events] == ["REWORK_REQUESTED"]
    assert host.complete(source) == receipt


def test_supervisor_active_submit_rejects_wrong_session_before_credentials(tmp_path, monkeypatch):
    host, source, _incoming, _result, _projection = supervisor_result_fixture(tmp_path)
    (source / "completed.json").unlink()
    monkeypatch.setenv("CODEX_THREAD_ID", "another-supervisor-session")
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda path: pytest.fail("wrong session used credential"))

    with pytest.raises(wc.CompletionError) as error:
        host.submit_supervisor_decision(source)

    assert error.value.error_code == "ROLE_HOST_SESSION_MISMATCH"


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
