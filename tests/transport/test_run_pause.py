"""Lifecycle uses the original Host and scans all calls, not just TOKEN holder."""

from pathlib import Path
import hashlib
import json
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
    host.binding["temporal"] = {"attempt_root": str(roots[0]), "client_command": ["python"],
        "workflow_identity_path": "identity", "workflow_identity_sha256": "a" * 64}
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


def test_original_lifecycle_request_retries_partial_central_and_temporal_without_new_events(tmp_path, monkeypatch):
    host, op, projection = lifecycle_host(tmp_path, monkeypatch)
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
    proof = host.inspect_run_quiescence("pause-1", [source.parents[1]])
    assert proof["status"] == ("QUIESCENT" if damage is None else "NOT_QUIESCENT"), json.dumps(proof)
