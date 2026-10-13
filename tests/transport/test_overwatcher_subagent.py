"""Simulated Codex rollout fixtures, never host-native proof."""
from __future__ import annotations

import json
import hashlib
import importlib
import os
import weakref
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from slk_transport.cli import main
from slk_transport.native_activity import inspect_native_activity, make_native_start, write_native_start


def test_subagent_without_original_proof_never_accepts_self_written_activity(tmp_path: Path) -> None:
    started = make_native_start(
        adapter="codex-overwatcher", run_id="run-a", cell_id="RUN-OVERWATCH",
        message_id="codex-subagent-spawn-call_a", request_sha256="a" * 64,
        native_request_sha256="b" * 64, native_task_kind="codex-subagent",
        native_task_id="parent:call_a:/root/ow", native_task_status="RUNNING", pid=os.getpid(),
    )
    write_native_start(tmp_path / "started.json", started)
    activity = {
        "schema_version": "slk.native-task-activity/v1", "adapter": started["adapter"],
        "run_id": started["run_id"], "cell_id": started["cell_id"], "message_id": started["message_id"],
        "native_task_id": started["native_task"]["id"], "status": "RUNNING", "sequence": 1,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "last_event": {"kind": "HANDWRITTEN", "sequence": 1}, "waiting_on": None,
    }
    (tmp_path / "native-activity.json").write_text(json.dumps(activity), encoding="utf-8")

    actual = inspect_native_activity(
        tmp_path / "started.json", process_probe=lambda *_: {"exists": True, "identity_matches": True},
    )

    assert actual["status"] == "UNKNOWN"
    assert actual["error"] == "NATIVE_SUBAGENT_PROOF_REQUIRED"
    assert actual["process"] is None

    malformed_probe = inspect_native_activity(tmp_path / "started.json", native_probe=lambda _: activity)
    assert malformed_probe["status"] == "UNKNOWN"
    assert malformed_probe["error"] == "NATIVE_QUERY_FAILED"


PARENT = "11111111-1111-4111-8111-111111111111"
CHILD = "/root/ow"
SECRET = "PRIVATE BUSINESS AND FINAL CONTENT"


def stamp(offset: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).isoformat().replace("+00:00", "Z")


def record(kind: str, timestamp: str, **payload) -> dict:
    return {"timestamp": timestamp, "type": "response_item", "payload": {"type": kind, **payload}}


def sample(timestamp: str, status="running", call_id="call_list", arguments=None) -> list[dict]:
    return [
        record("function_call", timestamp, namespace="collaboration", name="list_agents",
               call_id=call_id, arguments=json.dumps(arguments or {})),
        record("function_call_output", timestamp, call_id=call_id,
               output=json.dumps({"agents": [{"agent_name": CHILD, "agent_status": status},
                                             {"agent_name": "/root/other", "agent_status": {"completed": SECRET}}]})),
    ]


@pytest.fixture
def simulated(tmp_path, monkeypatch):
    """Explicitly isolated simulation root, not the user's native sessions directory."""
    reader = importlib.import_module("slk_transport.overwatcher_subagent")
    root = tmp_path / "simulated-codex" / "sessions"
    monkeypatch.setattr(reader, "CODEX_SESSIONS_ROOT", root)
    source = root / "2026" / "10" / "11" / f"rollout-2026-10-11T01-02-03-{PARENT}.jsonl"
    source.parent.mkdir(parents=True)
    now = stamp(-10)
    records = [
        {"timestamp": now, "type": "session_meta", "payload": {"id": PARENT, "originator": "Codex Desktop"}},
        record("function_call", now, namespace="collaboration", name="spawn_agent", call_id="call_spawn",
               arguments=json.dumps({"task_name": "ow", "message": SECRET})),
        record("function_call_output", now, call_id="call_spawn", output=json.dumps({"task_name": CHILD})),
        *sample(now),
    ]
    request = {
        "schema_version": "slk.subagent-overwatcher-request/v1", "method_version": "4.5.0",
        "run_id": "run-a", "role_instance_id": "ow-a", "endpoint_ref": "endpoint-a",
        "native_address": {"kind": "supervisor_subagent", "parent": {
            "agent_runtime": "codex", "host_identity": "host-a", "session_id": PARENT}, "agent_id": CHILD},
        "native_execution_id": "codex-subagent-spawn:call_spawn", "native_source_path": str(source),
    }
    request_path = tmp_path / "request.json"
    evidence = tmp_path / "proof"

    def save():
        source.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        request_path.write_text(json.dumps(request), encoding="utf-8")
        return hashlib.sha256(request_path.read_bytes()).hexdigest()

    def attest():
        return reader.attest_subagent_overwatcher(request_path, request_sha256=save(), evidence_root=evidence)

    def inspect(result, **kwargs):
        return inspect_native_activity(
            evidence / "started.json", native_probe=lambda start: reader.subagent_overwatcher_probe(
                evidence / "subagent-overwatcher-proof.json", proof_sha256=result["proof_sha256"],
                started_path=evidence / "started.json", start=start), **kwargs,
        )

    return reader, source, records, request, request_path, evidence, save, attest, inspect


def test_native_running_attestation_is_closed_small_and_reused(simulated) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    started = json.loads((evidence / "started.json").read_text())
    proof = json.loads((evidence / "subagent-overwatcher-proof.json").read_text())
    assert result["status"] == "ATTESTED"
    assert started["native_task"]["kind"] == "codex-subagent"
    assert PARENT in started["native_task"]["id"] and CHILD in started["native_task"]["id"]
    assert "call_spawn" in started["native_task"]["id"]
    assert proof["native_execution_id"] == "codex-subagent-spawn:call_spawn"
    assert proof["canonical_task_id"] == "codex-subagent-spawn-call_spawn"
    assert proof["sample_query_timestamp"] == records[3]["timestamp"]
    assert proof["sample_output_timestamp"] == records[4]["timestamp"]
    assert not (evidence / "native-activity.json").exists()
    assert SECRET not in json.dumps(proof)
    assert inspect(result, process_probe=lambda *_: pytest.fail("reader PID is not child liveness"))["status"] == "ACTIVE"
    assert attest() == result


def linked_child(simulated):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    child_id = "22222222-2222-4222-8222-222222222222"
    child_source = source.with_name("rollout-2026-10-11T01-02-04-" + child_id + ".jsonl")
    request["child_source_path"] = str(child_source)
    link = {"timestamp": records[2]["timestamp"], "type": "event_msg", "payload": {
        "type": "item_completed", "thread_id": PARENT, "item": {"type": "SubAgentActivity",
        "id": "call_spawn", "kind": "started", "agent_thread_id": child_id, "agent_path": CHILD}}}
    records.insert(3, link)
    meta = {"timestamp": records[0]["timestamp"], "type": "session_meta", "payload": {
        "id": child_id, "parent_thread_id": PARENT, "agent_path": CHILD,
        "source": {"subagent": {"thread_spawn": {"parent_thread_id": PARENT, "depth": 1, "agent_path": CHILD}}}}}
    child_records = [meta, *sample(stamp(-5), call_id="call_child_list")]
    def save_child(): child_source.write_text("".join(json.dumps(r) + "\n" for r in child_records))
    save_child()
    return child_records, link, save_child


@pytest.mark.parametrize("damage", [None, "wrong-parent", "wrong-child", "wrong-spawn", "changed-meta", "bad-source", "missing-output", "ambiguous-followup", "native-exit", "native-exit-child-query-failed"])
def test_exact_child_original_list_can_outlive_parent_sample_without_refreshing_time(simulated, damage):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    child_records, link, save_child = linked_child(simulated)
    meta = child_records[0]
    result = attest()
    child_records.extend(sample(stamp(599), call_id="call_child_latest"))
    if damage == "wrong-parent": meta["payload"]["parent_thread_id"] = "other"
    if damage == "wrong-child": meta["payload"]["id"] = "other"
    if damage == "wrong-spawn": link["payload"]["item"]["id"] = "call_other"
    if damage == "changed-meta": meta["payload"]["changed"] = True
    if damage == "bad-source": meta["payload"]["source"] = "unsupported"
    if damage in {"missing-output", "native-exit-child-query-failed"}: child_records.pop()
    if damage == "ambiguous-followup":
        records.extend([record("function_call", stamp(595), namespace="collaboration", name="followup_task",
            call_id="call_ambiguous", arguments=json.dumps({"target": CHILD, "message": SECRET}))])
    if damage in {"native-exit", "native-exit-child-query-failed"}: records.extend(sample(stamp(600), {"completed": SECRET}, "call_parent_exit"))
    save_child(); save()
    actual = inspect(result, observed_at=stamp(601))
    expected = "ACTIVE" if damage is None else "COMPLETED_WITHOUT_TERMINAL" if damage in {"native-exit", "native-exit-child-query-failed"} else "UNKNOWN"
    assert actual["status"] == expected
    assert SECRET not in json.dumps(actual)
    if damage is None:
        assert actual["last_event"]["observed_at"] == child_records[-1]["timestamp"]
        assert actual["last_event"]["detail_sha256"] == hashlib.sha256(json.dumps(child_records[-1]).encode()).hexdigest()


def native_projection(request):
    parent = request["native_address"]["parent"]
    child = request["native_address"]["agent_id"]
    def role(name, identity, session):
        return {"role": name, "role_instance_id": identity, "lifecycle": "active",
                "agent_runtime": "codex", "session_id": session,
                "endpoints": [{"state": "active", "host_identity": parent["host_identity"],
                               "session_id": session, "transport_adapter": "codex-overwatcher"}]}
    supervisor = role("supervisor", "supervisor-a", parent["session_id"])
    supervisor["endpoints"][0]["transport_adapter"] = "codex-app-server"
    ow = role("overwatcher", request["role_instance_id"], child)
    ow["foreground_turn_id"] = request["native_execution_id"]
    return {"summary": {"run_id": request["run_id"], "slk_version": "4.5.0"},
            "runtime_snapshot": {"method_version": "4.5.0"}, "roles": [supervisor, ow]}


@pytest.mark.parametrize("fault", [None, "run", "method", "parent", "runtime", "host", "duplicate-parent",
    "duplicate-endpoint", "child", "ow-role", "ow-host", "ow-endpoint-session", "execution"])
def test_native_proof_requires_exact_current_parent_child_endpoint_and_execution(simulated, fault):
    reader, _, _, request, _, _, _, attest, _ = simulated
    result = attest()
    projection = native_projection(request)
    supervisor, ow = projection["roles"]
    if fault == "run": projection["summary"]["run_id"] = "other"
    elif fault == "method": projection["runtime_snapshot"]["method_version"] = "4.4.5"
    elif fault == "parent": supervisor["session_id"] = "other"
    elif fault == "runtime": supervisor["agent_runtime"] = "other"
    elif fault == "host": supervisor["endpoints"][0]["host_identity"] = "other"
    elif fault == "duplicate-parent": projection["roles"].append(dict(supervisor))
    elif fault == "duplicate-endpoint": supervisor["endpoints"].append(dict(supervisor["endpoints"][0]))
    elif fault == "child": ow["session_id"] = "/root/other"
    elif fault == "ow-role": ow["role_instance_id"] = "other"
    elif fault == "ow-host": ow["endpoints"][0]["host_identity"] = "other"
    elif fault == "ow-endpoint-session": ow["endpoints"][0]["session_id"] = "/root/other"
    elif fault == "execution": ow["foreground_turn_id"] = "codex-subagent-followup:call_new"
    check = lambda: reader.validate_subagent_overwatcher_binding(Path(result["proof_path"]),
        proof_sha256=result["proof_sha256"], started_path=Path(result["started_path"]), projection=projection)
    if fault:
        with pytest.raises(ValueError): check()
    else:
        assert check()["native_execution_id"] == request["native_execution_id"]


def test_native_exit_cli_rereads_originals_not_caller_status(simulated, tmp_path, capsys):
    _, _, records, request, _, _, save, attest, _ = simulated
    result = attest()
    projection = tmp_path / "projection.json"
    projection.write_text(json.dumps(native_projection(request)))
    arguments = ["observe-overwatcher-exit", "--started", result["started_path"],
        "--subagent-overwatcher-proof", result["proof_path"],
        "--subagent-overwatcher-proof-sha256", result["proof_sha256"],
        "--runtime-projection", str(projection), "--requested-by-role-instance-id", "supervisor-a"]
    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out) == {"status": "NO_CONFIRMED_EXIT"}
    records.extend(sample(stamp(), {"completed": SECRET}, "call_exit"))
    save()
    assert main(arguments) == 0
    notice = json.loads(capsys.readouterr().out)
    assert set(notice) == {"event_id", "run_id", "overwatcher_role_instance_id", "requested_by_role_instance_id", "evidence_sha256"}
    assert notice["run_id"] == "run-a" and notice["requested_by_role_instance_id"] == "supervisor-a"
    assert SECRET not in json.dumps(notice)
    # A previously saved exit is not current proof after a new native activation.
    records.extend([record("function_call", stamp(), namespace="collaboration", name="followup_task",
        call_id="call_next", arguments=json.dumps({"target": CHILD, "message": SECRET}))])
    save()
    assert main(arguments) != 0
    assert json.loads(capsys.readouterr().out)["status"] == "rejected"


@pytest.mark.parametrize("case,expected", [("active", "CLEAR"), ("old-cycle", "ANOMALY"),
    ("completed", "EXITED"), ("301-second-sample", "ANOMALY"), ("unsupported-failed-shape", "ANOMALY"),
    ("child-401", "CLEAR"), ("child-661", "LATE"), ("child-1200", "LATE"),
    ("child-1201", "ANOMALY"), ("child-2904", "ANOMALY")])
def test_450_audit_traverses_real_transport_entry_and_reader_in_simulation(simulated, tmp_path, monkeypatch, case, expected):
    pytest.importorskip("temporalio")
    import asyncio
    import contextlib
    import io
    import sys
    from slk_temporal import standard_adapter
    from slk_transport import native_activity
    _, _, records, request, _, _, save, attest, _ = simulated
    child_records = linked_child(simulated)[0] if case.startswith("child-") else None
    result = attest()
    now = stamp()
    if child_records is not None:
        now = child_records[-1]["timestamp"]
        audit_now = datetime.fromisoformat(now.replace("Z", "+00:00")) + timedelta(seconds=int(case.split("-")[1]))
        class AuditClock(datetime):
            @classmethod
            def now(cls, tz=None): return audit_now
        monkeypatch.setattr(native_activity, "utc_now", lambda: audit_now.isoformat())
        monkeypatch.setattr(standard_adapter, "datetime", AuditClock)
    if case in {"completed", "301-second-sample", "unsupported-failed-shape"}:
        status = {"failed": SECRET} if case == "unsupported-failed-shape" else {"completed": SECRET}
        records.extend(sample(now, status, "call_latest"))
        save()
    if case == "301-second-sample":
        monkeypatch.setattr(native_activity, "utc_now", lambda: (datetime.fromisoformat(now.replace("Z", "+00:00")) + timedelta(seconds=301)).isoformat())
    projection = native_projection(request)
    projection["overwatch_cycles"] = [{"cycle_id": "cycle-a", "cycle_sequence": 1,
        "overwatcher_role_instance_id": request["role_instance_id"], "session_id": CHILD,
        "foreground_turn_id": "codex-subagent-spawn:call_old" if case == "old-cycle" else request["native_execution_id"],
        "cadence_seconds": 600, "completed_at": now,
        "next_cycle_at": (datetime.fromisoformat(now.replace("Z", "+00:00")) + timedelta(seconds=600)).isoformat()}]
    root = tmp_path / "adapter"
    root.mkdir()
    notices = tmp_path / "notices"
    notices.mkdir()
    placeholder = tmp_path / "placeholder.json"
    placeholder.write_text("{}")
    config = {"schema_version": "slk.temporal-standard-adapter/v2", "method_version": "4.5.0",
        "run_id": "run-a", "transport_command": [sys.executable], "query_command": [sys.executable],
        "state_config_path": str(placeholder), "admission_kind": "PRODUCT", "admission_path": str(placeholder),
        "attempt_root": str(tmp_path), "notification_attempt_root": str(notices), "supervisor_endpoint_path": str(placeholder),
        "role_host_binding": {"path": str(placeholder), "sha256": standard_adapter._sha256(placeholder)},
        "overwatcher_activity": {"endpoint_ref": "endpoint-a", "role_instance_id": "ow-a",
            "started_path": result["started_path"], "completed_path": str(placeholder), "failed_path": str(placeholder),
            "attestation_path": result["proof_path"], "attestation_sha256": result["proof_sha256"]}}
    (root / "run-a.json").write_text(json.dumps(config))
    standard_adapter.configure(root)
    monkeypatch.setattr(standard_adapter, "_query", lambda _config: projection)
    def run(_command, arguments, **_kwargs):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(arguments)
        return json.loads(output.getvalue())
    monkeypatch.setattr(standard_adapter, "_run_json", run)
    receipt = asyncio.run(standard_adapter.inspect_overwatcher({"run_id": "run-a",
        "overwatcher_role_instance_id": "ow-a", "endpoint_ref": "endpoint-a", "audit_cycle": 1}))
    assert receipt["status"] == expected
    evidence = notices / "run-a" / "overwatcher-audits" / (receipt["evidence_sha256"] + ".json")
    saved = json.loads(evidence.read_text())
    if case == "301-second-sample": assert saved["native"]["error"] == "NATIVE_ACTIVITY_STALE"
    if child_records is not None:
        assert saved["native"]["last_event"]["observed_at"] == now
        assert saved["cadence"]["elapsed_seconds"] == int(case.split("-")[1])
    assert SECRET not in evidence.read_text()


@pytest.mark.parametrize("case", ["active", "completed", "stale", "current-binding-drift"])
def test_450_startup_reuses_native_reader_without_first_cycle(simulated, tmp_path, monkeypatch, case):
    pytest.importorskip("temporalio")
    import asyncio
    import contextlib
    import io
    import sys
    from slk_temporal import standard_adapter
    from slk_transport import native_activity
    _, _, records, request, _, _, save, attest, _ = simulated
    attestation = attest()
    if case == "completed":
        records.extend(sample(stamp(), {"completed": SECRET}, "call_completed"))
        save()
    if case == "stale":
        monkeypatch.setattr(native_activity, "utc_now", lambda: stamp(301))
    projection = native_projection(request)
    projection["runtime_snapshot"]["runtime_revision"] = 9
    if case == "current-binding-drift":
        projection["roles"][1]["session_id"] = "/root/other"
    root = tmp_path / "startup-adapter"
    root.mkdir()
    placeholder = tmp_path / "startup-placeholder.json"
    placeholder.write_text("{}")
    config = {"schema_version": "slk.temporal-standard-adapter/v2", "method_version": "4.5.0",
        "run_id": "run-a", "transport_command": [sys.executable], "query_command": [sys.executable],
        "state_config_path": str(placeholder), "admission_kind": "PRODUCT", "admission_path": str(placeholder),
        "attempt_root": str(tmp_path), "notification_attempt_root": str(tmp_path), "supervisor_endpoint_path": str(placeholder),
        "role_host_binding": {"path": str(placeholder), "sha256": standard_adapter._sha256(placeholder)},
        "overwatcher_activity": {"endpoint_ref": "endpoint-a", "role_instance_id": "ow-a",
            "started_path": attestation["started_path"], "completed_path": str(placeholder), "failed_path": str(placeholder),
            "attestation_path": attestation["proof_path"], "attestation_sha256": attestation["proof_sha256"]}}
    (root / "run-a.json").write_text(json.dumps(config))
    standard_adapter.configure(root)
    monkeypatch.setattr(standard_adapter, "_query", lambda _config: projection)
    calls = []
    def run(_command, arguments, **_kwargs):
        calls.append(arguments[0])
        if arguments[0] == "preflight-new-run":
            return {"status": "READY", "run_id": "run-a"}
        assert arguments[0] == "inspect-native-activity", "startup has no cadence/sample/send requirement"
        assert "--completed" not in arguments and "--failed" not in arguments
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            main(arguments)
        return json.loads(output.getvalue())
    monkeypatch.setattr(standard_adapter, "_run_json", run)
    startup = {"run_id": "run-a", "method_version": "4.5.0", "runtime_revision": 9,
        "task_queue": "slk-local", "ack_timeout_seconds": 30, "startup_idempotency_key": "start-a",
        "roles": [{"role": role, "role_instance_id": identity, "endpoint_ref": "endpoint-" + identity}
                  for role, identity in (("SUPERVISOR", "supervisor-a"), ("WORKER", "worker-a"),
                                         ("CHECKER", "checker-a"), ("OVERWATCHER", "ow-a"))]}
    value = {"request": startup, "startup_fingerprint": "a" * 64}
    if case == "active":
        assert asyncio.run(standard_adapter.prepare_run(value))["status"] == "READY"
    else:
        with pytest.raises(ValueError, match="ACTIVE"):
            asyncio.run(standard_adapter.prepare_run(value))
    assert calls == ["preflight-new-run", "inspect-native-activity"]


def followup_records(records, request, *, target=CHILD, previous="codex-subagent-spawn:call_spawn"):
    """Synthetic parent tool sequence; an empty return is not a start ACK."""
    records.extend(sample(stamp(-3), {"completed": SECRET}, "call_pre"))
    records.extend([
        record("function_call", stamp(-2), namespace="collaboration", name="followup_task",
               call_id="call_followup", arguments=json.dumps({"target": target, "message": SECRET})),
        record("function_call_output", stamp(-1), call_id="call_followup", output=""),
        *sample(stamp(), call_id="call_post"),
    ])
    request.update(native_execution_id="codex-subagent-followup:call_followup", spawn_call_id="call_spawn",
                   previous_native_execution_id=previous, pre_activation_sample_call_id="call_pre")


@pytest.mark.parametrize("target", [CHILD, "ow"])
def test_followup_proves_a_new_execution_but_keeps_original_canonical_task(simulated, target):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    followup_records(records, request, target=target)
    result = attest()
    proof = json.loads((evidence / "subagent-overwatcher-proof.json").read_text())
    started = json.loads((evidence / "started.json").read_text())
    assert proof["canonical_task_id"] == "codex-subagent-spawn-call_spawn"
    assert started["message_id"] == "codex-subagent-followup-call_followup"
    assert started["native_request_sha256"] == proof["activation_call_sha256"]
    assert proof["pre_activation_sample_call_id"] == "call_pre"
    assert SECRET not in json.dumps(proof)
    assert inspect(result)["status"] == "ACTIVE"
    schema = json.loads((Path(__file__).parents[2] / "docs/contracts/slk-subagent-overwatcher.schema.json").read_text())
    validator = Draft202012Validator(schema)
    validator.validate(request)
    validator.validate(proof)


@pytest.mark.parametrize("fault", [
    "busy-pre", "missing-pre", "unknown-pre", "stale-pre", "future-pre", "wrong-target",
    "missing-activation-output", "wrong-activation-output", "duplicate-activation", "duplicate-pre",
    "post-before-output", "another-activation", "wrong-previous", "previous-not-latest",
])
def test_followup_requires_exact_completed_previous_execution_and_post_return_running(simulated, fault):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    followup_records(records, request)
    if fault == "busy-pre": records[6]["payload"]["output"] = json.dumps({"agents": [{"agent_name": CHILD, "agent_status": "running"}]})
    elif fault == "missing-pre": request["pre_activation_sample_call_id"] = "call_missing"
    elif fault == "unknown-pre": records[6]["payload"]["output"] = json.dumps({"agents": [{"agent_name": CHILD, "agent_status": "unknown"}]})
    elif fault == "stale-pre":
        records[5]["timestamp"] = records[6]["timestamp"] = stamp(-600)
    elif fault == "future-pre": records[6]["timestamp"] = stamp(100)
    elif fault == "wrong-target": records[7]["payload"]["arguments"] = json.dumps({"target": "/root/other", "message": SECRET})
    elif fault == "missing-activation-output": records.pop(8)
    elif fault == "wrong-activation-output": records[8]["payload"]["output"] = "{}"
    elif fault == "duplicate-activation": records.append(records[7])
    elif fault == "duplicate-pre": records.append(records[6])
    elif fault == "post-before-output": records[8], records[9] = records[9], records[8]
    elif fault == "another-activation": records.extend([
        record("function_call", stamp(), namespace="collaboration", name="followup_task", call_id="call_else", arguments=json.dumps({"target": CHILD, "message": SECRET})),
        record("function_call_output", stamp(), call_id="call_else", output=""), *sample(stamp(), call_id="call_after_else")])
    elif fault == "wrong-previous": request["previous_native_execution_id"] = "codex-subagent-spawn:call_wrong"
    elif fault == "previous-not-latest": records[5:5] = [
        record("function_call", stamp(-4), namespace="collaboration", name="followup_task", call_id="call_middle", arguments=json.dumps({"target": "ow", "message": SECRET})),
        record("function_call_output", stamp(-4), call_id="call_middle", output="")]
    with pytest.raises(reader.OverwatcherSubagentError):
        attest()


def test_old_execution_proof_cannot_borrow_running_from_a_later_activation(simulated):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    next_request = dict(request)
    followup_records(records, next_request)
    save()
    assert inspect(result)["status"] == "UNKNOWN"

@pytest.mark.parametrize("record_index", [5, 6, 7, 8])
def test_followup_frozen_activation_and_pre_sample_cannot_be_washed_by_new_sample(simulated, record_index):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    followup_records(records, request)
    result = attest()
    records[record_index]["timestamp"] = stamp(-1)
    records.extend(sample(stamp(), call_id="call_later"))
    save()
    assert inspect(result)["status"] == "UNKNOWN"


def test_followup_pre_sample_age_is_relative_to_activation_not_probe_time(simulated):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    followup_records(records, request)
    for item in records:
        item["timestamp"] = (datetime.fromisoformat(item["timestamp"].replace("Z", "+00:00")) - timedelta(hours=1)).isoformat()
    # Historical activation remains provable when a real fresh sample follows.
    records.extend(sample(stamp(), call_id="call_fresh"))
    result = attest()
    assert inspect(result)["status"] == "ACTIVE"


@pytest.mark.parametrize("tamper_previous", [False, True])
def test_followup_of_a_followup_freezes_only_exact_previous_activation(simulated, tamper_previous):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    followup_records(records, request)
    records.extend([
        *sample(stamp(), {"completed": SECRET}, "call_pre_second"),
        record("function_call", stamp(), namespace="collaboration", name="followup_task",
               call_id="call_second", arguments=json.dumps({"target": "ow", "message": SECRET})),
        record("function_call_output", stamp(), call_id="call_second", output=""),
        *sample(stamp(), call_id="call_post_second"),
    ])
    request.update(native_execution_id="codex-subagent-followup:call_second",
                   previous_native_execution_id="codex-subagent-followup:call_followup",
                   pre_activation_sample_call_id="call_pre_second")
    result = attest()
    proof = json.loads((evidence / "subagent-overwatcher-proof.json").read_text())
    assert proof["canonical_task_id"] == "codex-subagent-spawn-call_spawn"
    assert "previous_proof" not in proof
    if tamper_previous:
        records[7]["payload"]["arguments"] = json.dumps({"target": "ow", "message": "mutated old activation"})
        records.extend(sample(stamp(), call_id="call_after_tamper"))
        save()
    assert inspect(result)["status"] == ("UNKNOWN" if tamper_previous else "ACTIVE")


@pytest.mark.parametrize("old_record_order", [True, False])
def test_previous_followup_must_belong_to_original_spawn_incarnation(simulated, old_record_order):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    previous = [
        record("function_call", stamp(-20), namespace="collaboration", name="followup_task",
               call_id="call_old_followup", arguments=json.dumps({"target": CHILD, "message": SECRET})),
        record("function_call_output", stamp(-19), call_id="call_old_followup", output=""),
    ]
    if old_record_order:
        records[1:1] = [
            record("function_call", stamp(-30), namespace="collaboration", name="spawn_agent",
                   call_id="call_old_spawn", arguments=json.dumps({"task_name": "ow", "message": SECRET})),
            record("function_call_output", stamp(-29), call_id="call_old_spawn", output=json.dumps({"task_name": CHILD})),
            *previous,
        ]
    else:
        # Even if placed after spawn, timestamps cannot assign an old activation to it.
        records.extend(previous)
    followup_records(records, request, previous="codex-subagent-followup:call_old_followup")
    with pytest.raises(reader.OverwatcherSubagentError, match="original spawn"):
        attest()


def test_unrelated_followup_does_not_change_this_child_execution(simulated):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    records.extend([
        record("function_call", stamp(), namespace="collaboration", name="followup_task", call_id="call_other_activation",
               arguments=json.dumps({"target": "/root/other", "message": SECRET})),
        record("function_call_output", stamp(), call_id="call_other_activation", output=""),
    ])
    save()
    assert inspect(result)["status"] == "ACTIVE"


def test_nested_followup_uses_exact_parent_relative_child_without_depth_restriction(simulated):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    followup_records(records, request, target="ow")
    nested = "/root/supervisor/ow"
    request["native_address"]["agent_id"] = nested
    records[2]["payload"]["output"] = json.dumps({"task_name": nested})
    for item in records:
        if item["payload"].get("call_id") in {"call_list", "call_pre", "call_post"} and item["payload"]["type"] == "function_call_output":
            output = json.loads(item["payload"]["output"])
            output["agents"][0]["agent_name"] = nested
            item["payload"]["output"] = json.dumps(output)
    result = attest()
    assert inspect(result)["status"] == "ACTIVE"


def test_followup_return_without_new_post_query_never_proves_start(simulated):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    followup_records(records, request)
    del records[-2:]
    with pytest.raises(reader.OverwatcherSubagentError, match="post-activation query"):
        attest()


def test_new_target_query_recovers_unpinned_failure_within_current_followup(simulated):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    followup_records(records, request)
    result = attest()
    records.extend(sample(stamp(), call_id="call_bad_query"))
    records[-2]["payload"]["arguments"] = "bad-json"
    save()
    assert inspect(result)["status"] == "UNKNOWN"
    records.extend(sample(stamp(), call_id="call_new_query"))
    save()
    assert inspect(result)["status"] == "ACTIVE"


@pytest.mark.parametrize("followup", [False, True])
def test_successful_new_spawn_of_same_child_path_cannot_reuse_old_execution_proof(simulated, followup):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    if followup:
        followup_records(records, request)
    result = attest()
    records.extend([
        record("function_call", stamp(), namespace="collaboration", name="spawn_agent", call_id="call_replacement",
               arguments=json.dumps({"task_name": "ow", "message": SECRET})),
        record("function_call_output", stamp(), call_id="call_replacement", output=json.dumps({"task_name": CHILD})),
        *sample(stamp(), call_id="call_replacement_running"),
    ])
    save()
    assert inspect(result)["status"] == "UNKNOWN"

    request["native_execution_id"] = "codex-subagent-spawn:call_replacement"
    for field in ("spawn_call_id", "previous_native_execution_id", "pre_activation_sample_call_id"):
        request.pop(field, None)
    new_evidence = evidence.with_name("replacement-proof")
    new_result = reader.attest_subagent_overwatcher(request_path, request_sha256=save(), evidence_root=new_evidence)
    new_proof = json.loads((new_evidence / "subagent-overwatcher-proof.json").read_text())
    assert new_result["status"] == "ATTESTED"
    assert new_proof["canonical_task_id"] == "codex-subagent-spawn-call_replacement"


@pytest.mark.parametrize("returned", [json.dumps({"task_name": "/root/other"}), json.dumps({"error": "spawn failed"}), "", "not-json"])
def test_unrelated_or_failed_spawn_does_not_invent_a_child_replacement(simulated, returned):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    records.extend([
        record("function_call", stamp(), namespace="collaboration", name="spawn_agent", call_id="call_attempt",
               arguments=json.dumps({"task_name": "ow", "message": SECRET})),
        record("function_call_output", stamp(), call_id="call_attempt", output=returned),
        *sample(stamp(), call_id="call_same_execution"),
    ])
    save()
    assert inspect(result)["status"] == "ACTIVE"


@pytest.mark.parametrize("contract", ["slk-overwatch-cycle", "slk-overwatcher-status", "slk-overwatcher-turn-resume"])
def test_overwatch_contracts_allow_opaque_native_session_without_relaxing_other_ids(contract):
    schema = json.loads((Path(__file__).parents[2] / f"docs/contracts/{contract}.schema.json").read_text())
    property_validator = lambda field: Draft202012Validator({"$defs": schema["$defs"], **schema["properties"][field]})
    property_validator("session_id").validate("/root/supervisor/ow")
    assert list(property_validator("session_id").iter_errors(""))
    assert list(property_validator("run_id").iter_errors("/root/run"))
    property_validator("foreground_turn_id").validate("codex-subagent-followup:call_NativeA1")


@pytest.mark.parametrize("fault", [
    "wrong-parent", "wrong-child", "wrong-call", "wrong-namespace", "wrong-tool", "duplicate-call",
    "duplicate-output", "missing-spawn-output", "missing-list-output", "filter-omission", "absent-child",
    "duplicate-child", "unknown-status", "unknown-output", "spawn-name-mismatch", "outside-sessions",
    "duplicate-session-meta", "extra-request", "wrong-runtime", "not-running", "object-output", "null-filter",
])
def test_initial_attestation_rejects_unproved_native_identity_or_state(simulated, fault) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    if fault == "wrong-parent": records[0]["payload"]["id"] = "different-parent"
    elif fault == "wrong-child": request["native_address"]["agent_id"] = "/root/not_ow"
    elif fault == "wrong-call": request["native_execution_id"] = "codex-subagent-spawn:call_other"
    elif fault == "wrong-namespace": records[1]["payload"]["namespace"] = "model"
    elif fault == "wrong-tool": records[1]["payload"]["name"] = "followup_task"
    elif fault == "duplicate-call": records.append(records[1])
    elif fault == "duplicate-output": records.append(records[2])
    elif fault == "missing-spawn-output": records.pop(2)
    elif fault == "missing-list-output": records.pop()
    elif fault == "filter-omission": records[3]["payload"]["arguments"] = json.dumps({"path_prefix": "/root/other"})
    elif fault == "absent-child": records[4]["payload"]["output"] = json.dumps({"agents": []})
    elif fault == "duplicate-child": records[4]["payload"]["output"] = json.dumps({"agents": [{"agent_name": CHILD, "agent_status": "running"}] * 2})
    elif fault == "unknown-status": records[4]["payload"]["output"] = json.dumps({"agents": [{"agent_name": CHILD, "agent_status": {"running": "maybe"}}]})
    elif fault == "unknown-output": records[4]["payload"]["output"] = json.dumps({"tasks": []})
    elif fault == "spawn-name-mismatch": records[1]["payload"]["arguments"] = json.dumps({"task_name": "different", "message": SECRET})
    elif fault == "outside-sessions": request["native_source_path"] = str(request_path)
    elif fault == "duplicate-session-meta": records.append(records[0])
    elif fault == "extra-request": request["model"] = "unrequested"
    elif fault == "wrong-runtime": request["native_address"]["parent"]["agent_runtime"] = "another-runtime"
    elif fault == "not-running": records[4]["payload"]["output"] = json.dumps({"agents": [{"agent_name": CHILD, "agent_status": {"completed": SECRET}}]})
    elif fault == "object-output": records[4]["payload"]["output"] = {"agents": [{"agent_name": CHILD, "agent_status": "running"}]}
    elif fault == "null-filter": records[3]["payload"]["arguments"] = json.dumps({"path_prefix": None})
    with pytest.raises(reader.OverwatcherSubagentError):
        attest()
    assert not (evidence / "subagent-overwatcher-proof.json").exists()


@pytest.mark.parametrize("offset,error", [(-600, "NATIVE_ACTIVITY_STALE"), (600, "NATIVE_ACTIVITY_FROM_FUTURE")])
def test_rereading_never_refreshes_native_sample_time(simulated, offset, error) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    observed = stamp(-offset)
    actual = inspect(result, observed_at=observed)
    assert actual["status"] == "UNKNOWN"
    assert actual["error"] == error


def test_latest_real_sample_changes_state_without_leaking_completed_body(simulated) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    proof_before = (evidence / "subagent-overwatcher-proof.json").read_bytes()
    records.extend(sample(stamp(), {"completed": SECRET}, "call_list2"))
    save()
    actual = inspect(result)
    assert actual["status"] == "COMPLETED_WITHOUT_TERMINAL"
    assert SECRET not in json.dumps(actual)
    assert (evidence / "subagent-overwatcher-proof.json").read_bytes() == proof_before


@pytest.mark.parametrize("fault", ["spawn-record-drift", "sample-record-drift", "request-drift", "latest-missing-output", "latest-child-omission", "latest-duplicate-output", "proof-hash"])
def test_probe_rejects_frozen_drift_and_does_not_fall_back_to_older_good_sample(simulated, fault) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    if fault == "spawn-record-drift": records[1]["payload"]["arguments"] = json.dumps({"task_name": "ow", "message": "changed"})
    elif fault == "sample-record-drift": records[4]["timestamp"] = stamp()
    elif fault == "request-drift": request["endpoint_ref"] = "changed"
    elif fault == "proof-hash": result["proof_sha256"] = "0" * 64
    else:
        records.extend(sample(stamp(), call_id="call_list2"))
        if fault == "latest-missing-output": records.pop()
        elif fault == "latest-child-omission": records[-1]["payload"]["output"] = json.dumps({"agents": [{"agent_name": "/root/other", "agent_status": "running"}]})
        elif fault == "latest-duplicate-output": records.append(records[-1])
    save()
    if fault == "request-drift":
        copied = evidence / "subagent-overwatcher-request.json"
        copied.write_text(json.dumps(request))
    assert inspect(result)["status"] == "UNKNOWN"


@pytest.mark.parametrize("resample", [False, True])
def test_another_child_query_is_not_this_child_sample_or_a_permanent_block(simulated, resample) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    records.extend(sample(stamp(), call_id="call_other", arguments={"path_prefix": "/root/other"}))
    records[-1]["payload"]["output"] = json.dumps({"agents": [{"agent_name": "/root/other", "agent_status": "running"}]})
    if resample:
        records.extend(sample(stamp(), call_id="call_target_again", arguments={"path_prefix": CHILD}))
    save()
    actual = inspect(result)
    assert actual["status"] == "ACTIVE"
    expected_timestamp = records[-1 if resample else 4]["timestamp"]
    assert actual["last_event"]["observed_at"] == expected_timestamp


@pytest.mark.parametrize("fault", ["missing-output", "missing-child", "unsupported-status", "duplicate-query", "duplicate-output"])
def test_new_valid_target_sample_recovers_from_an_unpinned_old_query_failure(simulated, fault) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    records.extend(sample(stamp(), call_id="call_bad", arguments={"path_prefix": CHILD}))
    if fault == "missing-output": records.pop()
    elif fault == "missing-child": records[-1]["payload"]["output"] = json.dumps({"agents": []})
    elif fault == "unsupported-status": records[-1]["payload"]["output"] = json.dumps({"agents": [{"agent_name": CHILD, "agent_status": "unexpected"}]})
    elif fault == "duplicate-query": records.append(records[-2])
    elif fault == "duplicate-output": records.append(records[-1])
    save()
    assert inspect(result)["status"] == "UNKNOWN"
    records.extend(sample(stamp(), call_id="call_recovered", arguments={"path_prefix": CHILD}))
    save()
    assert inspect(result)["status"] == "ACTIVE"


@pytest.mark.parametrize("fault", ["bad-json", "null-filter", "extra-key", "object-output"])
def test_new_target_sample_recovers_unpinned_local_argument_or_encoding_failure(simulated, fault) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    records.extend(sample(stamp(), call_id="call_bad_encoding"))
    if fault == "bad-json": records[-2]["payload"]["arguments"] = "{broken-json}"
    elif fault == "null-filter": records[-2]["payload"]["arguments"] = json.dumps({"path_prefix": None})
    elif fault == "extra-key": records[-2]["payload"]["arguments"] = json.dumps({"path_prefix": CHILD, "unexpected": True})
    else: records[-1]["payload"]["output"] = {"agents": []}
    save()
    assert inspect(result)["status"] == "UNKNOWN"
    records.extend(sample(stamp(), call_id="call_recovered", arguments={"path_prefix": CHILD}))
    save()
    assert inspect(result)["status"] == "ACTIVE"


@pytest.mark.parametrize("frozen", ["spawn", "sample"])
@pytest.mark.parametrize("fault", ["bad-json", "null-filter", "extra-key", "object-output"])
def test_local_encoding_failures_in_frozen_records_cannot_be_washed_away(simulated, frozen, fault) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    index = 1 if frozen == "spawn" else 3
    if fault == "bad-json": records[index]["payload"]["arguments"] = "{broken-json}"
    elif fault == "null-filter": records[index]["payload"]["arguments"] = json.dumps({"path_prefix": None})
    elif fault == "extra-key": records[index]["payload"]["arguments"] = json.dumps({"path_prefix": CHILD, "unexpected": True})
    else: records[index + 1]["payload"]["output"] = {"agents": []}
    records.extend(sample(stamp(), call_id="call_recovered", arguments={"path_prefix": CHILD}))
    save()
    assert inspect(result)["status"] == "UNKNOWN"


@pytest.mark.parametrize("fault", ["spawn-duplicate", "pinned-sample-duplicate", "pinned-sample-missing", "pinned-sample-drift"])
def test_new_valid_target_sample_never_washes_away_frozen_record_integrity_failure(simulated, fault) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    if fault == "spawn-duplicate": records.append(records[2])
    elif fault == "pinned-sample-duplicate": records.append(records[4])
    elif fault == "pinned-sample-missing": records.pop(4)
    elif fault == "pinned-sample-drift": records[4]["timestamp"] = stamp()
    records.extend(sample(stamp(), call_id="call_new_valid", arguments={"path_prefix": CHILD}))
    save()
    assert inspect(result)["status"] == "UNKNOWN"


def test_initial_and_subsequent_samples_obey_existing_age_policy(simulated) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    records[3]["timestamp"] = records[4]["timestamp"] = stamp(-600)
    with pytest.raises(reader.OverwatcherSubagentError):
        attest()


@pytest.mark.parametrize("phase", ["initial", "probe"])
def test_output_future_cannot_be_hidden_by_a_current_query_timestamp(simulated, phase) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    if phase == "probe":
        result = attest()
        records.extend(sample(stamp(), call_id="call_list2"))
    records[-1]["timestamp"] = stamp(600)
    if phase == "initial":
        with pytest.raises(reader.OverwatcherSubagentError):
            attest()
    else:
        save()
        actual = inspect(result)
        assert actual["status"] == "UNKNOWN"
        assert actual["error"] == "NATIVE_ACTIVITY_FROM_FUTURE"


def test_native_sample_timestamp_is_unchanged_across_repeated_probe(simulated) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    started = json.loads((evidence / "started.json").read_text())
    first = reader.subagent_overwatcher_probe(evidence / "subagent-overwatcher-proof.json",
        proof_sha256=result["proof_sha256"], started_path=evidence / "started.json", start=started)
    second = reader.subagent_overwatcher_probe(evidence / "subagent-overwatcher-proof.json",
        proof_sha256=result["proof_sha256"], started_path=evidence / "started.json", start=started)
    assert first == second
    assert first["observed_at"] == records[3]["timestamp"]
    assert first["last_event"]["observed_at"] == records[4]["timestamp"]


def test_streaming_reader_does_not_retain_unrelated_tool_bodies(simulated, monkeypatch) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    unrelated = record("function_call", stamp(), namespace="functions", name="exec_command",
                       call_id="call_unrelated", arguments=json.dumps({"cmd": SECRET}))
    records[3:3] = [unrelated, record("function_call_output", stamp(), call_id="call_unrelated", output=SECRET)]
    parser = importlib.import_module("slk_overwatch_tools.native_records")
    original_object, original_timestamp = parser.native_object, parser.native_timestamp
    retained = []

    class TrackedRecord(dict):
        pass

    def tracking_object(value):
        parsed = original_object(value)
        if parsed.get("payload", {}).get("call_id") == "call_unrelated":
            parsed = TrackedRecord(parsed)
            retained.append(weakref.ref(parsed))
        return parsed

    def check_timestamp(value):
        assert retained and all(reference() is None for reference in retained), "unrelated tool body retained after source scan"
        return original_timestamp(value)

    monkeypatch.setattr(parser, "native_object", tracking_object)
    monkeypatch.setattr(parser, "native_timestamp", check_timestamp)
    assert attest()["status"] == "ATTESTED"


def test_unrelated_tool_body_filter_preserves_relevant_call_id_collision_checks(simulated) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    records.insert(1, record("function_call", stamp(), namespace="functions", name="exec_command",
                             call_id="call_spawn", arguments=json.dumps({"cmd": SECRET})))
    with pytest.raises(reader.OverwatcherSubagentError):
        attest()


def test_malformed_jsonl_structure_is_not_skipped_after_a_good_sample(simulated) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    with source.open("a", encoding="utf-8") as stream:
        stream.write("{malformed native record}\n")
    assert inspect(result)["status"] == "UNKNOWN"


@pytest.mark.parametrize("bad_record", [
    {},
    {"type": "response_item", "payload": None},
    record("function_call", stamp(), namespace="collaboration", name="list_agents", arguments="{}"),
    {"type": "", "payload": {}},
    {"type": "future_record", "payload": []},
    {"type": "response_item", "payload": {}},
    record("function_call", stamp(), call_id="call_broken", arguments="{}"),
    record("function_call", stamp(), call_id="call_broken", name="unrelated"),
    record("function_call_output", stamp(), call_id="call_broken"),
])
def test_structural_damage_never_silently_falls_back_to_old_running(simulated, bad_record) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    result = attest()
    records.append(bad_record)
    save()
    assert inspect(result)["status"] == "UNKNOWN"


def test_selected_list_call_id_must_match_native_contract_before_attestation(simulated) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    records[3]["payload"]["call_id"] = records[4]["payload"]["call_id"] = "not-a-native-call-id"
    with pytest.raises(reader.OverwatcherSubagentError):
        attest()
    assert not (evidence / "subagent-overwatcher-proof.json").exists()


@pytest.mark.parametrize("field", ["spawn_call_id", "sample_call_id"])
def test_closed_proof_rejects_invalid_native_call_ids(simulated, field) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    attest()
    proof_path = evidence / "subagent-overwatcher-proof.json"
    proof = json.loads(proof_path.read_text())
    proof[field] = "not-a-native-call-id"
    proof_path.write_text(json.dumps(proof), encoding="utf-8")
    with pytest.raises(reader.OverwatcherSubagentError):
        reader._proof(proof_path, hashlib.sha256(proof_path.read_bytes()).hexdigest(), evidence / "started.json")


def test_unknown_valid_records_and_legacy_unrelated_tool_identifiers_remain_compatible(simulated) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    records.extend([
        {"type": "future_record", "payload": {"opaque": SECRET}},
        record("future_response", stamp(), opaque=SECRET),
        record("function_call", stamp(), name="unrelated", call_id="legacy-tool-call-1", arguments="{}"),
        record("function_call_output", stamp(), call_id="legacy-tool-call-1", output=SECRET),
    ])
    assert attest()["status"] == "ATTESTED"


@pytest.mark.parametrize("position", [1, 3, 5])
def test_app_injected_message_receipt_without_call_id_is_not_an_ow_tool_pair(simulated, position):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    receipt = record("function_call_output", stamp(), id="app-injected-receipt",
                     namespace="codex_app", name="send_message_to_thread", output=SECRET,
                     internal_chat_message_metadata_passthrough={"opaque": SECRET})
    records.insert(position, receipt)
    result = attest()
    proof = json.loads((evidence / "subagent-overwatcher-proof.json").read_text())
    assert proof["spawn_call_id"] == "call_spawn"
    assert proof["sample_call_id"] == "call_list"
    # Selection hashes still bind exact original records, not a filtered copy.
    for call_id, kind, key in (("call_spawn", "function_call", "spawn_call_sha256"),
                               ("call_spawn", "function_call_output", "spawn_output_sha256"),
                               ("call_list", "function_call", "sample_call_sha256"),
                               ("call_list", "function_call_output", "sample_output_sha256")):
        raw = next(line for line in source.read_bytes().splitlines()
                   if (item := json.loads(line))["payload"].get("call_id") == call_id
                   and item["payload"]["type"] == kind)
        assert proof[key] == hashlib.sha256(raw).hexdigest()
    assert SECRET not in json.dumps(proof)
    assert inspect(result)["status"] == "ACTIVE"


@pytest.mark.parametrize("damage", ["namespace", "name", "kind", "id", "output", "call-id"])
def test_app_compatibility_never_skips_target_or_malformed_receipts(simulated, damage):
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    receipt = record("function_call_output", stamp(), id="app-injected-receipt",
                     namespace="codex_app", name="send_message_to_thread", output=SECRET)
    payload = receipt["payload"]
    if damage == "namespace": payload["namespace"] = "collaboration"
    elif damage == "name": payload["name"] = "list_agents"
    elif damage == "kind": payload["type"] = "function_call"
    elif damage == "id": payload["id"] = ""
    elif damage == "output": payload["output"] = None
    elif damage == "call-id": payload["call_id"] = "call_spawn"
    records.insert(1, receipt)
    with pytest.raises(reader.OverwatcherSubagentError):
        attest()
    assert not (evidence / "subagent-overwatcher-proof.json").exists()


def test_nested_child_locator_uses_parent_local_spawn_without_invented_ancestor_proof(simulated) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    nested = "/root/supervisor/ow"
    request["native_address"]["agent_id"] = nested
    records[2]["payload"]["output"] = json.dumps({"task_name": nested})
    records[4]["payload"]["output"] = json.dumps({"agents": [{"agent_name": nested, "agent_status": "running"}]})
    result = attest()
    assert inspect(result)["status"] == "ACTIVE"
    proof = json.loads((evidence / "subagent-overwatcher-proof.json").read_text())
    assert proof["native_address"]["agent_id"] == nested
    assert nested in proof["native_task_id"]


def test_request_proof_schema_and_cli(simulated, capsys) -> None:
    reader, source, records, request, request_path, evidence, save, attest, inspect = simulated
    digest = save()
    assert main(["attest-subagent-overwatcher", "--request", str(request_path), "--sha256", digest,
                 "--evidence-root", str(evidence)]) == 0
    result = json.loads(capsys.readouterr().out)
    schema_path = Path(__file__).parents[2] / "docs/contracts/slk-subagent-overwatcher.schema.json"
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(request)
    validator.validate(json.loads((evidence / "subagent-overwatcher-proof.json").read_text()))
    assert list(validator.iter_errors({**request, "unexpected": True}))
    assert main(["inspect-native-activity", "--started", str(evidence / "started.json"),
                 "--subagent-overwatcher-proof", result["proof_path"],
                 "--subagent-overwatcher-proof-sha256", result["proof_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ACTIVE"
    assert main(["inspect-native-activity", "--started", str(evidence / "started.json"),
                 "--subagent-overwatcher-proof", result["proof_path"]]) != 0
    capsys.readouterr()
    assert main(["inspect-native-activity", "--started", str(evidence / "started.json"),
                 "--subagent-overwatcher-proof", result["proof_path"],
                 "--subagent-overwatcher-proof-sha256", result["proof_sha256"],
                 "--desktop-overwatcher-attestation", result["proof_path"],
                 "--desktop-overwatcher-attestation-sha256", result["proof_sha256"]]) != 0
