"""Same-Session recovery must not replay an ended delivery or its old report."""
import importlib
import json
import os
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from slk_transport import native_activity as native, worker_completion as wc
from slk_transport.contracts import DeliveryResult, RESULT_SCHEMA
from test_role_host import prepared_host
from test_worker_completion import runtime_projection, write_json


def resume_module():
    from slk_transport import __path__
    assert any((Path(p) / "worker_resume.py").is_file() for p in __path__), "missing standard same-Session recovery"
    return importlib.import_module("slk_transport.worker_resume")


def setup(tmp_path, monkeypatch):
    host, source, envelope = prepared_host(tmp_path)
    projection = runtime_projection()
    projection["summary"]["state"] = "active"
    projection["runtime_snapshot"]["token_sequence"] = envelope.token_sequence
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setattr(host, "_boundary", lambda env: projection)
    monkeypatch.setattr(host, "inspect_recovery_authority", lambda role: {"status": "SUPERVISOR_RECOVERY_AUTHENTICATED"})
    module = resume_module()
    monkeypatch.setattr(module, "native_session_stopped", lambda endpoint: {"status": "NATIVE_SESSION_STOPPED"}, raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", host.endpoint("supervisor")["address"]["thread_id"])
    probe = native.process_probe
    monkeypatch.setattr(native, "process_probe", lambda pid, created: {"exists": False, "identity_matches": False}
                        if created == "fixture:1" else probe(pid, created))
    instructions = tmp_path / "continue.md"
    instructions.write_text("Continue the same task after the narrow permission repair.", encoding="utf-8")
    return host, source, envelope, projection, instructions


def invoke(module, host, source, instructions, adapter, invocation=None):
    return module.resume_worker_session(host, source, invocation_id=invocation or str(uuid.uuid4()),
        instructions_path=instructions, instructions_sha256=wc._sha256(instructions), adapter=adapter)


@pytest.mark.parametrize("candidate_source", ["original", "prior-resume"])
@pytest.mark.parametrize("handoff_fails", [False, True])
@pytest.mark.parametrize("native_status", ["completed", "failed"])
def test_submitted_candidate_recovery_only_replays_original_handoff(
    tmp_path, monkeypatch, candidate_source, handoff_fails, native_status,
):
    module = resume_module()
    host, source, envelope, projection, instructions = setup(tmp_path, monkeypatch)
    if native_status == "failed":
        terminal = wc._read_object(source / "completed.json", "terminal")
        write_json(source / "failed.json", {**terminal, "status": "failed", "error_code": "DSH_PROVIDER_EXITED"})
        (source / "completed.json").unlink()
    candidate = source
    if candidate_source == "prior-resume":
        candidate = source / "native-resumes" / str(uuid.uuid4())
        for name in ("endpoint.json", "envelope.json", "started.json", native_status + ".json"):
            write_json(candidate / name, wc._read_object(source / name, name))
        (candidate / "instructions.md").write_bytes(instructions.read_bytes())
        write_json(candidate / "native-resume.json", {"schema_version": "slk.worker-native-resume/v1",
            "invocation_id": candidate.name, "original_source": str(source),
            "original_source_sha256": host._source_sha256(source, "worker"), "binding_sha256": host.digest,
            "instructions_sha256": wc._sha256(instructions),
            "coordinator_process": {"pid": os.getpid(), "creation_time": native.process_creation_time(os.getpid())}})
    identity = module.source_identity(candidate, host, envelope)
    submitted = {"event_id": wc._stable_id(identity, "candidate_submitted"), "run_id": envelope.run_id,
        "go_id": envelope.go_id, "cell_id": envelope.cell_id, "attempt": 1, "plan_revision": 1,
        "event_type": "CANDIDATE_SUBMITTED", "role_instance_id": envelope.receiver_role_instance_id,
        "occurred_at": "2026-10-01T00:00:00Z", "corrects_event_id": None,
        "details": {"decision_source": "WORKER_EXPLICIT", "source_message_id": envelope.message_id,
            "native_start_sha256": wc._sha256(candidate / "started.json"),
            "native_task_id": host.endpoint("worker")["address"]["session_id"],
            "handoff_message_id": wc._stable_id(identity, "output-delivery"),
            "candidate": {"kind": "commit", "commit": "d" * 40}}}
    write_json(candidate / "role-host/worker-candidate_submitted.json", submitted)
    projection["events"].append({**submitted, "author_role_instance_id": submitted["role_instance_id"]})
    original = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _: "isolated-test-secret")
    monkeypatch.setattr(host, "_authenticate", lambda *_: {})
    sends, handoffs = [], []
    def send(_command, args, **kwargs):
        sends.append(wc._read_object(Path(args[args.index("--envelope") + 1]), "output"))
        return {"status": "started"}
    def handoff(_root, outgoing, *_args, **_kwargs):
        handoffs.append(outgoing)
        if handoff_fails:
            raise OSError("injected exact handoff failure")
        return {"status": "OWNED_HANDOFF_COMMITTED"}
    monkeypatch.setattr(wc, "_run_json_command", send)
    monkeypatch.setattr(host, "_send_owned", handoff)
    class Forbidden:
        def deliver(self, *args): pytest.fail("recorded candidate restarted engineering work")

    result = invoke(module, host, source, instructions, Forbidden())

    assert result["status"] == "CANDIDATE_HANDOFF_ONLY"
    assert result["invocation_id"] is None and Path(result["invocation_path"]) == candidate
    assert result["native_result"] == wc._read_object(candidate / (native_status + ".json"), "original terminal")
    assert len(sends) == len(handoffs) == 1
    assert sends[0]["message_id"] == submitted["details"]["handoff_message_id"]
    assert result["output_delivery"]["handoff"]["status"] == ("failed" if handoff_fails else "OWNED_HANDOFF_COMMITTED")
    assert all(path.read_bytes() == data for path, data in original.items())
    if candidate_source == "prior-resume":
        assert list((source / "native-resumes").iterdir()) == [candidate]
    else:
        assert not (source / "native-resumes").exists()


def test_recorded_candidate_without_original_action_evidence_never_resumes_work(tmp_path, monkeypatch):
    module = resume_module()
    host, source, envelope, projection, instructions = setup(tmp_path, monkeypatch)
    projection["events"].append({"event_id": wc._stable_id(envelope.message_id, "candidate_submitted"),
        "event_type": "CANDIDATE_SUBMITTED", "go_id": envelope.go_id, "cell_id": envelope.cell_id,
        "author_role_instance_id": envelope.receiver_role_instance_id,
        "details": {"source_message_id": envelope.message_id}})
    class Forbidden:
        def deliver(self, *args): pytest.fail("missing candidate evidence restarted engineering work")
    with pytest.raises(ValueError, match="candidate.*evidence"):
        invoke(module, host, source, instructions, Forbidden())
    assert not (source / "native-resumes").exists()


@pytest.mark.parametrize("handoff,expected", [("OWNED_HANDOFF_COMMITTED", 0), ("failed", 3)])
def test_resume_cli_reports_saved_candidate_handoff_independent_of_provider_exit(tmp_path, monkeypatch, handoff, expected):
    from argparse import Namespace
    from slk_transport import cli
    module = resume_module()
    host, source, _envelope, _projection, instructions = setup(tmp_path, monkeypatch)
    binding = write_json(tmp_path / "bound-host.json", host.binding)
    monkeypatch.setattr(module, "resume_worker_session", lambda *_a, **_k: {
        "status": "CANDIDATE_HANDOFF_ONLY", "native_result": {"status": "failed", "error_code": "DSH_PROVIDER_EXITED"},
        "output_delivery": {"status": "OUTPUT_DELIVERED", "handoff": {"status": handoff}}})
    assert cli._resume_worker_session(Namespace(binding=binding, sha256=wc._sha256(binding),
        source_attempt=source, invocation_id=str(uuid.uuid4()), instructions=instructions,
        instructions_sha256=wc._sha256(instructions))) == expected


def test_recovery_preserves_originals_and_automatically_hands_off_fresh_candidate(tmp_path, monkeypatch):
    module = resume_module()
    host, source, envelope, projection, instructions = setup(tmp_path, monkeypatch)
    write_json(source / "role-host/output.json", {"old": "blocked report"})
    old = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    sent = []
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda path: "isolated-test-secret")
    monkeypatch.setattr(host, "_authenticate", lambda *args: {"runtime_revision": 7})
    def state(args, **kwargs):
        request = wc._read_object(Path(args[args.index("--request") + 1]), "action")
        projection["events"].append({**request, "author_role_instance_id": request["role_instance_id"],
            "details_json": json.dumps(request["details"])})
        return {"status": "recorded"}
    monkeypatch.setattr(host, "_state_json", state)
    def command(_cmd, args, **kwargs):
        sent.append(wc._read_object(Path(args[args.index("--envelope") + 1]), "new handoff"))
        return {"status": "started"}
    monkeypatch.setattr(wc, "_run_json_command", command)
    monkeypatch.setattr(host, "_send_owned", lambda *args, **kwargs: {"status": "OWNED_HANDOFF_COMMITTED"})

    class Native:
        def deliver(self, endpoint, incoming, attempt):
            assert incoming == envelope and endpoint.address["session_id"] == host.endpoint("worker")["address"]["session_id"]
            assert attempt.root != source
            start = native.make_native_start(adapter=endpoint.adapter, run_id=incoming.run_id, cell_id=incoming.cell_id,
                message_id=incoming.message_id, request_sha256=incoming.payload_sha256, native_request_sha256="c" * 64,
                native_task_kind="dsh-session", native_task_id=endpoint.address["session_id"], native_task_status="RUNNING", pid=os.getpid())
            attempt.write_json_once("started.json", start)
            attempt.write_json_once("native-activity.json", {"schema_version": native.TASK_ACTIVITY_SCHEMA,
                "adapter": endpoint.adapter, "run_id": incoming.run_id, "cell_id": incoming.cell_id,
                "message_id": incoming.message_id, "native_task_id": endpoint.address["session_id"],
                "status": "RUNNING", "sequence": 1, "observed_at": native.utc_now(),
                "last_event": {"kind": "tool_call", "sequence": 1}, "waiting_on": None})
            assert Path(os.environ["SLK_NATIVE_ACTIVITY_PATH"]) == attempt.root / "native-activity.json"
            for event, details in [("WORK_STARTED", {}), ("D0_COMPLETED", {"d0": "real fixture result"}),
                                   ("CANDIDATE_SUBMITTED", {"candidate": {"kind": "commit", "commit": "d" * 40}})]:
                host.record_worker_action(attempt.root, event, details)
            attempt.write_text_once("worker-result.json", "Fresh original Worker output, not old blocked output.")
            return DeliveryResult(RESULT_SCHEMA, incoming.message_id, incoming.run_id, endpoint.adapter, "completed", {}, None, ("started.json",))

    result = invoke(module, host, source, instructions, Native())
    fresh = Path(result["invocation_path"])
    assert result["output_delivery"]["handoff"]["status"] == "OWNED_HANDOFF_COMMITTED"
    assert fresh.parent == source / "native-resumes" and (fresh / "completed.json").is_file()
    assert all((source / name).read_bytes() == data for name, data in old.items())
    assert len(sent) == 1 and sent[0]["message_id"] != wc._stable_id(envelope.message_id, "output-delivery")
    assert sent[0]["payload"]["candidate"]["commit"] == "d" * 40
    assert sent[0]["payload"]["source_message_id"] == envelope.message_id
    assert all(str(fresh) in item["path"] for item in sent[0]["payload"]["files"])
    assert all(e["attempt"] == 1 for e in projection["events"] if e["event_type"] != "TRANSPORT_STARTED")
    assert "SLK_NATIVE_ACTIVITY_PATH" not in os.environ
    with pytest.raises(ValueError):
        host.record_worker_action(fresh, "WORK_STARTED", {})


@pytest.mark.parametrize("damage", ["live-original", "wrong-session", "wrong-supervisor", "changed-instructions", "unsafe-id", "terminal-run"])
def test_recovery_rejects_unproved_scope_before_native_launch(tmp_path, monkeypatch, damage):
    module = resume_module()
    host, source, envelope, projection, instructions = setup(tmp_path, monkeypatch)
    digest = wc._sha256(instructions)
    identity = str(uuid.uuid4())
    if damage == "live-original":
        monkeypatch.setattr(native, "process_probe", lambda *args: {"exists": True, "identity_matches": True})
    if damage == "wrong-session":
        start = wc._read_object(source / "started.json", "source")
        start["native_task"]["id"] = "session-other"
        write_json(source / "started.json", start)
    if damage == "wrong-supervisor": monkeypatch.setenv("CODEX_THREAD_ID", "other-thread")
    if damage == "changed-instructions": instructions.write_text("changed", encoding="utf-8")
    if damage == "unsafe-id": identity = "../other"
    if damage == "terminal-run": projection["summary"]["state"] = "closed"
    class Forbidden:
        def deliver(self, *args): pytest.fail("invalid recovery launched a native Worker")
    with pytest.raises(ValueError):
        module.resume_worker_session(host, source, invocation_id=identity, instructions_path=instructions,
                                     instructions_sha256=digest, adapter=Forbidden())


def test_repeat_invocation_never_restarts_worker(tmp_path, monkeypatch):
    module = resume_module()
    host, source, envelope, projection, instructions = setup(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(host, "complete", lambda path: {"status": "OUTPUT_DELIVERED"})
    class Native:
        def deliver(self, endpoint, incoming, attempt):
            seen.append(attempt.root)
            return DeliveryResult(RESULT_SCHEMA, incoming.message_id, incoming.run_id, endpoint.adapter, "failed", {}, "DSH_START_UNPROVED", ())
    identity = str(uuid.uuid4())
    invoke(module, host, source, instructions, Native(), identity)
    with pytest.raises(ValueError): invoke(module, host, source, instructions, Native(), identity)
    assert len(seen) == 1


def test_real_dsh_adapter_uses_unique_result_drop_without_touching_old_blocked_drop(tmp_path, monkeypatch):
    from slk_transport.adapters.dsh import DshAdapter
    from slk_transport.evidence import Attempt
    from slk_transport import role_host
    from test_dsh_adapter import worker_endpoint, worker_envelope
    session = "session-11111111-1111-4111-8111-111111111111"
    endpoint = worker_endpoint(tmp_path, session_id=session)
    envelope = worker_envelope()
    original = tmp_path / "attempts" / envelope.run_id / envelope.message_id
    write_json(original / "endpoint.json", asdict(endpoint))
    write_json(original / "envelope.json", asdict(envelope))
    root = original / "native-resumes" / str(uuid.uuid4())
    write_json(root / "endpoint.json", asdict(endpoint))
    write_json(root / "envelope.json", asdict(envelope))
    (root / "instructions.md").write_text("Continue original", encoding="utf-8")
    class Bound:
        digest = "a" * 64
        transport = ["transport"]
        _source_sha256 = staticmethod(role_host.RoleHost._source_sha256)
        def endpoint(self, _role): return asdict(endpoint)
    host = Bound()
    write_json(root / "native-resume.json", {"schema_version": "slk.worker-native-resume/v1", "invocation_id": root.name,
        "original_source": str(original), "original_source_sha256": host._source_sha256(original, "worker"),
        "binding_sha256": host.digest, "instructions_sha256": wc._sha256(root / "instructions.md"),
        "coordinator_process": {"pid": os.getpid(), "creation_time": native.process_creation_time(os.getpid())}})
    monkeypatch.setattr(role_host, "load_role_host", lambda *args: host)
    monkeypatch.setenv("SLK_TRANSPORT_ROLE_HOST", str(tmp_path / "bound-host.json"))
    sessions = DshAdapter()._session_root(endpoint)
    write_json(sessions / (session + ".json"), {})
    old_drop = Path(endpoint.address["cwd"]) / ".slk-transport" / envelope.message_id
    write_json(old_drop / "worker-result.json", {"old": "blocked"})
    write_json(old_drop / "transport-task.json", {"old": "descriptor"})
    old_bytes = {p.name: p.read_bytes() for p in old_drop.iterdir()}
    result = DshAdapter().deliver(endpoint, envelope, Attempt(root))
    assert result.status == "completed"
    observed = json.loads((root / "native.stdout.txt").read_text(encoding="utf-8"))
    assert Path(observed["result_path"]).parent != old_drop
    assert Path(observed["result_path"]).parent.parent == old_drop.parent
    assert all((old_drop / name).read_bytes() == data for name, data in old_bytes.items())
    assert (root / "worker-result.json").is_file()


def test_quiescence_census_does_not_miss_pending_native_resume(tmp_path, monkeypatch):
    module = resume_module()
    host, source, envelope, projection, instructions = setup(tmp_path, monkeypatch)
    observed = native.utc_now()
    write_json(source / "native-activity.json", {"schema_version": native.TASK_ACTIVITY_SCHEMA,
        "adapter": "dsh-worker", "run_id": envelope.run_id, "cell_id": envelope.cell_id,
        "message_id": envelope.message_id, "native_task_id": host.endpoint("worker")["address"]["session_id"],
        "status": "COMPLETED", "sequence": 1, "observed_at": observed,
        "sample": {"source": "DSH_LIVE_AGENT_REGISTRY", "native_task_id": host.endpoint("worker")["address"]["session_id"], "observed_at": observed},
        "last_event": {"kind": "DSH_AGENT_STATUS", "sequence": 1}, "waiting_on": None})
    monkeypatch.setattr(host, "complete", lambda *args: {"status": "OUTPUT_DELIVERED"})
    class NotStarted:
        def deliver(self, endpoint, incoming, attempt):
            return DeliveryResult(RESULT_SCHEMA, incoming.message_id, incoming.run_id, endpoint.adapter, "failed", {}, "DSH_START_UNPROVED", ())
    result = invoke(module, host, source, instructions, NotStarted())
    proof = host.inspect_run_quiescence("isolated-pause", [source.parents[1]])
    assert proof["status"] == "NOT_QUIESCENT"
    assert any(Path(row["native_start_path"]).parent == Path(result["invocation_path"]) for row in proof["inspections"])


def test_dead_launcher_does_not_override_open_native_session(tmp_path, monkeypatch):
    module = resume_module()
    host, source, envelope, projection, instructions = setup(tmp_path, monkeypatch)
    def open_turn(_endpoint):
        raise ValueError("native Turn remains open")
    monkeypatch.setattr(module, "native_session_stopped", open_turn, raising=False)
    class Forbidden:
        def deliver(self, *args): pytest.fail("dead launcher hid a still-running native Turn")
    with pytest.raises(ValueError, match="native Turn"):
        invoke(module, host, source, instructions, Forbidden())
