"""Lifecycle uses the original Host and scans all calls, not just TOKEN holder."""

from pathlib import Path
import hashlib
import json
import sys
import pytest

from test_role_host import prepared_host
from test_worker_completion import write_json
from slk_transport import native_activity as native
from slk_transport import worker_completion as wc


def test_pause_census_checks_old_nonholder_and_does_not_trust_terminal_label(tmp_path, monkeypatch):
    host, source, incoming = prepared_host(tmp_path)
    host.binding["temporal"] = {"attempt_root": str(source.parents[1])}
    projection = {"summary": {"run_id": "RUN-A"}, "runtime_snapshot": {"runtime_revision": 7},
                  "native_invocations": []}
    monkeypatch.setattr(host, "projection", lambda: projection)
    # Even a completed transport label cannot prove a DSH Session is quiescent.
    def activity(_path, start, status="RUNNING"):
        now = native.utc_now()
        return {"schema_version": native.TASK_ACTIVITY_SCHEMA, **{key: start[key] for key in ("adapter", "run_id", "cell_id", "message_id")},
            "native_task_id": start["native_task"]["id"], "status": status, "sequence": 1, "observed_at": now,
            "last_event": {"kind": "REGISTRY_SAMPLE", "sequence": 1}, "waiting_on": None,
            "sample": {"source": "DSH_LIVE_AGENT_REGISTRY", "native_task_id": start["native_task"]["id"], "observed_at": now}}
    monkeypatch.setattr(native, "_file_native_probe", activity)
    monkeypatch.setattr(native, "process_probe", lambda *_a: {"exists": False, "identity_matches": False})
    proof = host.inspect_run_quiescence("pause-1", [source.parents[1]])
    assert proof["status"] == "NOT_QUIESCENT"
    assert proof["inspections"] and proof["inspections"][0]["message_id"] == incoming.message_id
    monkeypatch.setattr(native, "_file_native_probe", lambda path, start: activity(path, start, "COMPLETED"))
    assert host.inspect_run_quiescence("pause-1", [source.parents[1]])["status"] == "QUIESCENT"


def test_pause_census_rejects_omitted_old_central_native_call(tmp_path, monkeypatch):
    host, source, incoming = prepared_host(tmp_path)
    missing = tmp_path / "old-root" / "RUN-A" / "old-message" / "started.json"
    monkeypatch.setattr(host, "projection", lambda: {"summary": {"run_id": "RUN-A"},
        "runtime_snapshot": {"runtime_revision": 7}, "native_invocations": [{"message_id": "old-message",
            "role_instance_id": "old-checker", "start_evidence_path": str(missing), "start_evidence_sha256": "a" * 64}]})
    proof = host.inspect_run_quiescence("pause-1", [source.parents[1]])
    assert proof["status"] == "NOT_QUIESCENT"
    assert any(row["status"] == "UNKNOWN" and row["message_id"] == "old-message" for row in proof["inspections"])


def test_ow_observer_can_recheck_exact_coordinator_without_authoring_as_supervisor(tmp_path, monkeypatch):
    from test_role_host import current_d2_fixture
    host, source, incoming, _result, _projection, _seen = current_d2_fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("CODEX_THREAD_ID", "the-independent-ow-thread")
    with pytest.raises(wc.CompletionError, match="registered Session"):
        host._supervisor_start_proof(source, incoming)  # author identity never bypassed
    host._supervisor_start_proof(source, incoming, observer=True)
    path = source / "started.json"
    proof = json.loads(path.read_text())
    proof["native_task"]["id"] = "different-supervisor:turn"
    write_json(path, proof)
    with pytest.raises(wc.CompletionError, match="exact native start"):
        host._supervisor_start_proof(source, incoming, observer=True)


def lifecycle_host(tmp_path, monkeypatch):
    host, source, _ = prepared_host(tmp_path)
    roots = [source.parents[1], tmp_path / "notices"]
    roots[1].mkdir()
    identity = write_json(tmp_path / "workflow-identity.json", {"schema_version": "slk.temporal-workflow-identity/v1",
        "run_id": "RUN-A", "address": "test-only", "task_queue": "test-queue", "start_workflow_id": "start-a",
        "start_run_id": "start-execution", "run_workflow_id": "run-a", "run_run_id": "run-execution",
        "startup_fingerprint": "a" * 64})
    host.binding["schema_version"] = "slk.role-host/v2"
    host.binding["temporal"] = {"attempt_root": str(roots[0]),
        "client_command": [sys.executable, "-m", "slk_temporal.delivery_client"],
        "workflow_identity_path": str(identity), "workflow_identity_sha256": wc._sha256(identity)}
    binding = write_json(tmp_path / "host.json", host.binding)
    host.digest = wc._sha256(binding)
    config = write_json(tmp_path / "adapter.json", {"run_id": "RUN-A", "attempt_root": str(roots[0]),
        "notification_attempt_root": str(roots[1]), "role_host_binding": {"path": str(binding), "sha256": host.digest}})
    op = {"schema_version": "slk.run-lifecycle/v1", "run_id": "RUN-A", "role_instance_id": "RUN-A-supervisor-001",
        "pause_id": "pause-1", "binding_path": str(binding), "binding_sha256": host.digest,
        "adapter_config_path": str(config), "adapter_config_sha256": wc._sha256(config),
        "evidence_root": str(tmp_path / "lifecycle"), "coordinator_started_path": None}
    projection = {"summary": {"run_id": "RUN-A"}, "runtime_snapshot": {"runtime_revision": 7, "plan_revision": 1}, "events": []}
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(host, "_authenticate", lambda *_a: {})
    monkeypatch.setattr(host, "_resume_preflight", lambda *_a: None)
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda *_a: "secret")
    def state(arguments, **_k):
        event = json.loads(Path(arguments[-1]).read_text())
        projection["events"].append({"event_id": event["event_id"], "event_type": event["event_type"],
            "author_role_instance_id": event["role_instance_id"], "details_json": json.dumps(event["details"]),
            "occurred_at": event["occurred_at"]})
        projection["runtime_snapshot"]["runtime_revision"] += 1
        return {"status": "recorded", "run_id": "RUN-A"}
    monkeypatch.setattr(host, "_state_json", state)
    monkeypatch.setattr(host, "inspect_run_quiescence", lambda *_a: {"status": "QUIESCENT",
        "runtime_revision": projection["runtime_snapshot"]["runtime_revision"]})
    return host, op, projection


@pytest.mark.parametrize("pause_id", ["pause-1", "pause-" + "a" * 512])
def test_original_lifecycle_request_retries_partial_central_and_temporal_without_new_events(tmp_path, monkeypatch, pause_id):
    host, op, projection = lifecycle_host(tmp_path, monkeypatch)
    op["pause_id"] = pause_id
    calls = []
    fail = ["REQUESTED", "RESUMED"]
    def temporal(_command, arguments, **_k):
        value = json.loads(Path(arguments[arguments.index("--request") + 1]).read_text())
        calls.append(value)
        if fail and value["phase"] == fail[0]:
            fail.pop(0)
            raise ValueError("RPC unavailable")
        return {"schema_version": "slk.temporal-lifecycle-update-result/v1", "run_id": "RUN-A",
                "status": value["phase"], "event_id": value["event_id"]}
    monkeypatch.setattr(wc, "_run_json_command", temporal)
    digest = "b" * 64
    with pytest.raises(ValueError, match="RPC"):
        host.run_lifecycle("pause-run", op, operation_sha256=digest, expected_revision=7)
    assert projection["events"][0]["event_type"] == "RUN_PAUSE_REQUESTED"
    assert host.lifecycle_retry_matches(projection, "pause-run", op, digest, 7, op["role_instance_id"])
    assert not host.lifecycle_retry_matches(projection, "pause-run", op, "d" * 64, 7, op["role_instance_id"])
    assert host.run_lifecycle("pause-run", op, operation_sha256=digest, expected_revision=7)["status"] == "paused"
    assert len(projection["events"]) == 2
    saved = write_json(tmp_path / "pause.json", op)
    resume = {**op, "pause_request_path": str(saved), "pause_request_sha256": wc._sha256(saved)}
    with pytest.raises(ValueError, match="RPC"):
        host.run_lifecycle("resume-run", resume, operation_sha256="c" * 64, expected_revision=9)
    assert len(projection["events"]) == 2
    assert host.run_lifecycle("resume-run", resume, operation_sha256="c" * 64, expected_revision=9)["status"] == "resumed"
    assert [row["event_type"] for row in projection["events"]] == ["RUN_PAUSE_REQUESTED", "RUN_PAUSED", "RUN_RESUMED"]
    monkeypatch.setattr(host, "inspect_run_quiescence", lambda *_a: pytest.fail("already released"))
    assert host.run_lifecycle("resume-run", resume, operation_sha256="c" * 64, expected_revision=9)["status"] == "resumed"


def requested_cancel_host(tmp_path, monkeypatch):
    host, pause, projection = lifecycle_host(tmp_path, monkeypatch)
    saved = write_json(tmp_path / "pause.json", pause)
    projection["events"].append({"event_id": wc._stable_id(wc._sha256(saved), "run_pause_requested"),
        "event_type": "RUN_PAUSE_REQUESTED", "author_role_instance_id": pause["role_instance_id"],
        "details_json": json.dumps({"pause_id": pause["pause_id"], "expected_runtime_revision": 6})})
    resume = {**pause, "pause_request_path": str(saved), "pause_request_sha256": wc._sha256(saved),
              "cancel_requested": True, "reason": "Cancel the unconfirmed request; preserve the active call"}
    monkeypatch.setattr(host, "inspect_run_quiescence", lambda *_a: pytest.fail("cancellation must not claim quiescence"))
    monkeypatch.setattr(host, "_resume_preflight", lambda *_a: pytest.fail("cancellation must not require stopped members"))
    return host, resume, projection


def temporal_result(arguments):
    value = json.loads(Path(arguments[arguments.index("--request") + 1]).read_text())
    return {"schema_version": "slk.temporal-lifecycle-update-result/v1", "run_id": value["run_id"],
            "status": value["phase"], "event_id": value["event_id"]}


def sealed_lifecycle(tmp_path, monkeypatch, host, op, projection, revision=7):
    from slk_transport import supervisor_admin as admin
    from slk_transport.role_host import RoleHost
    operation = write_json(tmp_path / "cancel.json", op)
    request = write_json(tmp_path / "admin.json", {"schema_version": "slk.supervisor-admin/v1",
        "run_id": host.binding["run_id"], "supervisor_role_instance_id": host.endpoint("supervisor")["role_instance_id"],
        "expected_runtime_revision": revision, "sealed_credential_path": host.credential_path("supervisor"),
        "state_command": host.state, "operation": "resume-run", "operation_request_path": str(operation),
        "operation_request_sha256": wc._sha256(operation), "result_path": str(tmp_path / "admin-result.json")})
    command = wc._run_json_command
    def run(command_args, arguments, *, credential, credential_scope="role", state_config_path=None, pythonpath=None):
        if arguments[0] == "authenticate-role":
            assert credential == "secret"
            return {"status": "authenticated", "run_id": "RUN-A", "role": "supervisor",
                "role_instance_id": "RUN-A-supervisor-001", "runtime_revision": projection["runtime_snapshot"]["runtime_revision"]}
        return command(command_args, arguments, credential=credential, credential_scope=credential_scope,
                       state_config_path=state_config_path, pythonpath=pythonpath)
    monkeypatch.setattr(wc, "_run_json_command", run)
    monkeypatch.setattr(wc, "_default_load_current_projection", lambda *_a, **_k: projection)
    # Substitute only process/DPAPI/native boundaries; keep the sealed consumer,
    # binding validation, lifecycle implementation and retry matcher real.
    for name in ("projection", "_authenticate", "_state_json", "inspect_run_quiescence", "_resume_preflight"):
        original = getattr(host, name)
        monkeypatch.setattr(RoleHost, name, lambda _self, *args, _method=original, **kwargs: _method(*args, **kwargs))
    return lambda: admin.execute_sealed_supervisor_admin(request, request_sha256=wc._sha256(request))


def test_lifecycle_temporal_uses_strict_command_signature_without_role_credential(tmp_path, monkeypatch):
    host, op, _projection = lifecycle_host(tmp_path, monkeypatch)
    def temporal(command, arguments, *, credential, credential_scope="role", state_config_path=None, pythonpath=None):
        assert credential is None
        return temporal_result(arguments)
    monkeypatch.setattr(wc, "_run_json_command", temporal)
    assert host.run_lifecycle("pause-run", op, operation_sha256="b" * 64, expected_revision=7)["status"] == "paused"


@pytest.mark.parametrize("boundary", ["first-temporal", "central", "final-temporal", None])
def test_requested_cancel_retries_exact_event_across_commit_boundaries(tmp_path, monkeypatch, boundary):
    host, op, projection = requested_cancel_host(tmp_path, monkeypatch)
    projection["current_token"] = {"token_id": "T014", "holder": "worker"}
    before_token = dict(projection["current_token"])
    saved = write_json(tmp_path / "cancel.json", op)
    digest = wc._sha256(saved)
    calls, writes, failed = [], [], False
    original_state = host._state_json
    def temporal(command, arguments, *, credential, credential_scope="role", state_config_path=None, pythonpath=None):
        nonlocal failed
        assert credential is None
        result = temporal_result(arguments)
        calls.append(result["event_id"])
        if not failed and ((boundary == "first-temporal" and len(calls) == 1)
                           or (boundary == "final-temporal" and len(calls) == 2)):
            failed = True
            raise ValueError("boundary unavailable")
        return result
    def state(arguments, **kwargs):
        nonlocal failed
        event = json.loads(Path(arguments[-1]).read_text())
        writes.append(event)
        if boundary == "central" and not failed:
            failed = True
            raise ValueError("boundary unavailable")
        return original_state(arguments, **kwargs)
    monkeypatch.setattr(wc, "_run_json_command", temporal)
    monkeypatch.setattr(host, "_state_json", state)
    execute = sealed_lifecycle(tmp_path, monkeypatch, host, op, projection)
    if boundary:
        with pytest.raises(ValueError, match="boundary unavailable"):
            execute()
        assert not (tmp_path / "admin-result.json").exists()
    assert execute()["status"] == "SUPERVISOR_ADMIN_COMPLETED"
    assert host.lifecycle_retry_matches(projection, "resume-run", op, digest, 7, op["role_instance_id"])
    assert host.run_lifecycle("resume-run", op, operation_sha256=digest, expected_revision=7)["status"] == "resumed"
    assert [event["event_type"] for event in projection["events"]] == ["RUN_PAUSE_REQUESTED", "RUN_RESUMED"]
    details = wc._event_details(projection["events"][-1])
    assert details == {"pause_id": op["pause_id"], "expected_runtime_revision": 7,
                       "cancel_requested": True, "reason": op["reason"]}
    assert len(set(calls)) == 1 and all(event == writes[0] for event in writes)
    assert projection["current_token"] == before_token


@pytest.mark.parametrize("damage", ["role", "run", "pause", "revision", "marker", "reason", "extra",
    "no-request", "already-paused", "original-author", "original-request", "central-author", "central-request"])
def test_requested_cancel_rejects_changed_authority_before_any_temporal_write(tmp_path, monkeypatch, damage):
    host, op, projection = requested_cancel_host(tmp_path, monkeypatch)
    revision = 7
    if damage == "role": op["role_instance_id"] = "RUN-A-worker-001"
    elif damage == "run": op["run_id"] = "RUN-B"
    elif damage == "pause": op["pause_id"] = "another-pause"
    elif damage == "revision": revision = 6
    elif damage == "marker": op["cancel_requested"] = False
    elif damage == "reason": op["reason"] = "  "
    elif damage == "extra": op["unrelated"] = True
    elif damage == "no-request": projection["events"].clear()
    elif damage == "already-paused": projection["events"][-1]["event_type"] = "RUN_PAUSED"
    elif damage == "central-author": projection["events"][-1]["author_role_instance_id"] = "another-supervisor"
    elif damage == "central-request": projection["events"][-1]["event_id"] = "another-request"
    else:
        old_path = Path(op["pause_request_path"])
        old = json.loads(old_path.read_text())
        if damage == "original-author": old["role_instance_id"] = "another-supervisor"
        else: old["unexpected"] = "changed"
        write_json(old_path, old)
        op["pause_request_sha256"] = wc._sha256(old_path)
        projection["events"][-1]["event_id"] = wc._stable_id(op["pause_request_sha256"], "run_pause_requested")
    monkeypatch.setattr(wc, "_run_json_command", lambda *_a, **_k: pytest.fail("invalid cancel reached Temporal"))
    monkeypatch.setattr(host, "_state_json", lambda *_a, **_k: pytest.fail("invalid cancel reached central"))
    execute = sealed_lifecycle(tmp_path, monkeypatch, host, op, projection, revision)
    with pytest.raises(ValueError):
        execute()


def test_cancel_retry_requires_same_closed_details_and_latest_lifecycle(tmp_path, monkeypatch):
    host, op, projection = requested_cancel_host(tmp_path, monkeypatch)
    digest = wc.canonical_json_sha256(op)
    monkeypatch.setattr(wc, "_run_json_command", lambda _c, args, **_k: temporal_result(args))
    host.run_lifecycle("resume-run", op, operation_sha256=digest, expected_revision=7)
    event = projection["events"][-1]
    original = event["details_json"]
    for details in ({**json.loads(original), "reason": "other"},
                    {**json.loads(original), "cancel_requested": False},
                    {**json.loads(original), "extra": True}):
        event["details_json"] = json.dumps(details)
        assert not host.lifecycle_retry_matches(projection, "resume-run", op, digest, 7, op["role_instance_id"])
        with pytest.raises(ValueError):
            host.run_lifecycle("resume-run", op, operation_sha256=digest, expected_revision=7)
    event["details_json"] = original
    projection["events"].append({"event_id": "later", "event_type": "RUN_PAUSE_REQUESTED",
        "author_role_instance_id": op["role_instance_id"], "details_json": json.dumps({"pause_id": "pause-2"})})
    assert not host.lifecycle_retry_matches(projection, "resume-run", op, digest, 7, op["role_instance_id"])
    with pytest.raises(ValueError):
        host.run_lifecycle("resume-run", op, operation_sha256=digest, expected_revision=7)


def test_physical_entry_fences_construction_but_retains_original_started_closure(tmp_path, monkeypatch):
    host, source, incoming = prepared_host(tmp_path)
    monkeypatch.setattr(host, "projection", lambda: {"summary": {"state": "pause_requested"}})
    # Existing started calls are read/replayed, never another native invocation.
    host.validate_native_dispatch(host.endpoint("worker"), incoming, source.parents[1])
    new = incoming.to_dict() if hasattr(incoming, "to_dict") else __import__("dataclasses").asdict(incoming)
    new["message_id"] = wc._stable_id(incoming.message_id, "new-worker")
    from slk_transport.contracts import Envelope
    with pytest.raises(wc.CompletionError, match="pause"):
        host.validate_native_dispatch(host.endpoint("worker"), Envelope.from_dict(new), source.parents[1])


@pytest.mark.parametrize("state", ["paused", "closed"])
@pytest.mark.parametrize("kind", ["WORKER_REPORT", "CANDIDATE_READY"])
def test_paused_and_closed_never_start_new_checker_even_for_report_with_candidate(tmp_path, monkeypatch, state, kind):
    from dataclasses import asdict
    from slk_transport.contracts import Envelope
    host, source, incoming = prepared_host(tmp_path)
    monkeypatch.setattr(host, "projection", lambda: {"summary": {"state": state}})
    raw = {**asdict(incoming), "message_id": wc._stable_id(incoming.message_id, kind), "payload_type": kind,
        "sender_role": "worker", "sender_role_instance_id": host.endpoint("worker")["role_instance_id"],
        "receiver_role": "checker", "receiver_role_instance_id": host.endpoint("checker")["role_instance_id"],
        "receiver_endpoint_version": host.endpoint("checker")["endpoint_version"],
        "payload": {"candidate": {"kind": "commit", "commit": "b" * 40}}}
    raw["payload_sha256"] = wc.canonical_json_sha256(raw["payload"])
    with pytest.raises(wc.CompletionError):
        host.validate_native_dispatch(host.endpoint("checker"), Envelope.from_dict(raw), source.parents[1])


@pytest.mark.parametrize("damage", [None, "alive", "completion", "decision", "central-start"])
def test_explicit_ocrv_completion_and_exact_executor_stop_without_session_end(tmp_path, monkeypatch, damage):
    from test_checker_action_compatibility import live_checker
    host, source, incoming, start = live_checker(tmp_path, monkeypatch, native_kind="ocrv-invocation")
    host.record_checker_decision(source, "FAIL", "original explicit decision")
    # Focus the census on this genuine, byte-bound central Checker start.
    # Prior test setup uses synthetic stage envelopes, not native stop proof
    # for an entire real Run; they must not be silently accepted by production.
    projection = dict(host.projection())
    projection["native_invocations"] = [row for row in projection["native_invocations"]
        if row["message_id"] == incoming.message_id]
    assert len(projection["native_invocations"]) == 1
    monkeypatch.setattr(host, "projection", lambda: projection)
    receipt = source / "native-start.received.json"
    identity = {"pid": 123456, "creation_time": "win-filetime:123456"}
    index = write_json(tmp_path / "review" / "evidence-index.json", {
        **{key: start[key] for key in ("run_id", "cell_id", "message_id", "native_request_sha256")},
        "native_task_id": start["native_task"]["id"]})
    write_json(source / "ocrv-native-process.json", {"schema_version": "slk.ocrv-native-process/v1",
        **{key: start[key] for key in ("run_id", "cell_id", "message_id", "native_request_sha256")},
        "native_task_id": start["native_task"]["id"], "native_start_sha256": wc._sha256(receipt),
        "launcher_process": start["process"], "process": identity,
        "index_path": str(index), "index_sha256": wc._sha256(index)})
    decision = source / "role-host" / "checker-decision.json"
    completion = write_json(index.with_name("review-completed.json"), {"schema_version": "slk.ocrv-completion/v1",
        **{key: start[key] for key in ("run_id", "cell_id", "message_id", "native_request_sha256")},
        "native_task_id": start["native_task"]["id"], "native_start_sha256": wc._sha256(receipt),
        "review_process": identity, "decision_path": str(decision), "decision_sha256": wc._sha256(decision), "verdict": "FAIL"})
    if damage == "completion": completion.unlink()
    if damage == "decision": write_json(decision, {**json.loads(decision.read_text()), "message": "changed"})
    if damage == "central-start":
        projection["native_invocations"] = [{**row, "start_evidence_sha256": "0" * 64}
            if row["message_id"] == incoming.message_id else row for row in projection["native_invocations"]]
    def activity(_path, native_start):
        now = native.utc_now()
        value = {"schema_version": native.TASK_ACTIVITY_SCHEMA,
            **{key: native_start[key] for key in ("adapter", "run_id", "cell_id", "message_id")},
            "native_task_id": native_start["native_task"]["id"], "status": "COMPLETED", "sequence": 1,
            "observed_at": now, "last_event": {"kind": "NATIVE_EVENT", "sequence": 1}, "waiting_on": None}
        if native_start["adapter"] == "dsh-worker":
            value["sample"] = {"source": "DSH_LIVE_AGENT_REGISTRY", "native_task_id": value["native_task_id"], "observed_at": now}
        else:
            value.update(status="UNKNOWN", error="OCRV_SESSION_STATUS_UNAVAILABLE")
        return value
    monkeypatch.setattr(native, "_file_native_probe", activity)
    monkeypatch.setattr(native, "process_probe", lambda pid, _created: {
        "exists": damage == "alive" and pid == identity["pid"], "identity_matches": damage == "alive" and pid == identity["pid"]})
    monkeypatch.setattr("slk_transport.native_ocrv.process_probe", native.process_probe)
    proof = host.inspect_run_quiescence("pause-1", [source.parents[1]])
    assert proof["status"] == ("QUIESCENT" if damage is None else "NOT_QUIESCENT"), json.dumps(proof)
