"""Same-Session native resume through the real, isolated state and RoleHost."""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from dataclasses import asdict
from pathlib import Path

import pytest

from slk_transport import native_activity as native, worker_completion as wc
from slk_transport import worker_resume as worker_resume_module
from slk_transport.contracts import DeliveryResult, Envelope, RESULT_SCHEMA
from slk_transport.dispatcher import dispatch_once
from slk_transport.role_host import RoleHost
from slk_transport.worker_resume import invocation_environment, resume_worker_session
from test_role_host import prepared_host
from test_worker_completion import actual_worker_state, write_json


def test_same_session_resume_commits_fresh_candidate_once_against_real_state(tmp_path, monkeypatch):
    credentials = {}
    binary, config, _worker, _checker, revision = actual_worker_state(
        tmp_path, credentials=credentials,
    )
    prepared, source, incoming = prepared_host(tmp_path)
    # Match the real registered endpoint versions and native Sessions, not a
    # projection or authentication stub. Only the external launch is faked.
    for role in ("supervisor", "checker", "worker"):
        endpoint = {**prepared.endpoint(role), "endpoint_version": 1}
        if role == "supervisor":
            endpoint["address"] = {"thread_id": "thread-a"}
        elif role == "worker":
            endpoint["address"] = {**endpoint["address"], "session_id": "session-worker"}
        path = Path(prepared.binding["roles"][role]["endpoint_path"])
        write_json(path, endpoint)
        prepared.binding["roles"][role]["endpoint_sha256"] = wc._sha256(path)
    host = RoleHost({**prepared.binding, "state_command": [str(binary)],
        "transport_command": ["isolated-native-receiver"]}, prepared.digest,
        state_config_path=str(config))
    write_json(source / "endpoint.json", host.endpoint("worker"))
    incoming = Envelope.from_dict({**asdict(incoming), "payload_type": "WORKER_TASK"})
    write_json(source / "envelope.json", asdict(incoming))
    session = host.endpoint("worker")["address"]["session_id"]
    # Give the ended original an actual OS process identity. No liveness or
    # state-boundary checks are monkeypatched for either native invocation.
    with subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"],
                          stdin=subprocess.PIPE) as process:
        old_start = native.make_native_start(adapter="dsh-worker", run_id=incoming.run_id,
            cell_id=incoming.cell_id, message_id=incoming.message_id,
            request_sha256=incoming.payload_sha256, native_request_sha256="b" * 64,
            native_task_kind="dsh-session", native_task_id=session,
            native_task_status="RUNNING", pid=process.pid)
        write_json(source / "started.json", old_start)
        process.communicate(timeout=10)
    assert native.process_probe(**old_start["process"]) == {"exists": False, "identity_matches": False}
    terminal = wc._read_object(source / "completed.json", "original terminal")
    terminal["native_identity"]["session_id"] = session
    write_json(source / "completed.json", terminal)
    old_report = b"Blocked before D0: native tool permission unavailable.\r\nOriginal bytes: \xff\r\n"
    (source / "worker-result.json").write_bytes(old_report)
    (source / "native.stdout.txt").write_bytes(b"Original ended native stdout.\r\n")
    write_json(source / "role-host" / "output.json", {
        "source_message_id": incoming.message_id, "source_role": "worker",
        "files": [{"path": str(source / "worker-result.json"),
                   "bytes": len(old_report), "sha256": wc._sha256(source / "worker-result.json")}],
    })
    original_files = {path.relative_to(source): path.read_bytes()
                      for path in source.rglob("*") if path.is_file()}
    before = host.projection()
    assert before["runtime_snapshot"]["runtime_revision"] == revision
    assert before["runtime_snapshot"]["token_sequence"] == incoming.token_sequence == 3
    assert before["runtime_snapshot"]["token_holder_role_instance_id"] == incoming.receiver_role_instance_id
    assert before["runtime_snapshot"]["latest_message_id"] == incoming.message_id
    assert wc._source_attempt(before, incoming) == 1
    monkeypatch.setenv("CODEX_THREAD_ID", host.endpoint("supervisor")["address"]["thread_id"])
    secret_map = {Path(host.credential_path(role)): secret for role, secret in credentials.items()}
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda path: secret_map[Path(path)])
    # This test has a fake native DSH Session, not a bundled v4 Session log.
    # Stub only that external read-only proof; state and OS process checks stay real.
    def native_stopped(endpoint):
        assert asdict(endpoint) == host.endpoint("worker")
        return {"status": "NATIVE_SESSION_STOPPED", "session_id": session,
            "path": str(source / "native.stdout.txt"), "sha256": wc._sha256(source / "native.stdout.txt"),
            "last_seq": 2, "turn": 1, "turn_end_seq": 2, "turn_ended_at": old_start["observed_at"]}
    monkeypatch.setattr(worker_resume_module, "native_session_stopped", native_stopped)

    candidate = {"kind": "commit", "commit": "d" * 40}
    fresh_report = b"Original Worker finished D0 and submitted the fresh candidate.\r\nNot JSON.\xff\r\n"
    launched = []
    received = []

    class NativeWorker:
        def deliver(self, endpoint, envelope, attempt):
            launched.append(attempt.root)
            assert envelope == incoming and endpoint.address["session_id"] == session
            assert attempt.root.parent == source / "native-resumes"
            assert Path(os.environ["SLK_NATIVE_ACTIVITY_PATH"]) == attempt.root / "native-activity.json"
            attempt.write_json_once("started.json", native.make_native_start(
                adapter=endpoint.adapter, run_id=envelope.run_id, cell_id=envelope.cell_id,
                message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
                native_request_sha256="c" * 64, native_task_kind="dsh-session",
                native_task_id=session, native_task_status="RUNNING", pid=os.getpid()))
            attempt.write_json_once("native-activity.json", {
                "schema_version": native.TASK_ACTIVITY_SCHEMA, "adapter": endpoint.adapter,
                "run_id": envelope.run_id, "cell_id": envelope.cell_id,
                "message_id": envelope.message_id, "native_task_id": session,
                "status": "RUNNING", "sequence": 1, "observed_at": native.utc_now(),
                "last_event": {"kind": "tool_call", "sequence": 1}, "waiting_on": None,
            })
            for event, details in (("WORK_STARTED", {}),
                ("D0_COMPLETED", {"d0": "focused test passed in the original Worker"}),
                ("CANDIDATE_SUBMITTED", {"candidate": candidate})):
                if event == "CANDIDATE_SUBMITTED":
                    attempt.write_bytes_once("worker-result.json", fresh_report)
                assert host.record_worker_action(attempt.root, event, details)["status"] == "WORKER_ACTION_RECORDED"
            return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id,
                endpoint.adapter, "completed", {"session_id": session, "exit_code": 0},
                None, ("started.json", "worker-result.json"))

    class NativeChecker:
        def validate_address(self, endpoint):
            assert endpoint.role == "checker"

        def deliver(self, endpoint, envelope, attempt):
            received.append((envelope, attempt.root))
            attempt.write_json_once("started.json", native.make_native_start(
                adapter=endpoint.adapter, run_id=envelope.run_id, cell_id=envelope.cell_id,
                message_id=envelope.message_id, request_sha256=envelope.payload_sha256,
                native_request_sha256="e" * 64, native_task_kind="ocrv-review",
                native_task_id="original-checker:" + envelope.message_id,
                native_task_status="RUNNING", pid=os.getpid()))
            return DeliveryResult(RESULT_SCHEMA, envelope.message_id, envelope.run_id,
                endpoint.adapter, "completed", {}, None, ("started.json",))

    real_command = wc._run_json_command

    def command(executable, arguments, **kwargs):
        if executable != host.transport:
            return real_command(executable, arguments, **kwargs)
        assert arguments[0] == "send" and kwargs["credential"] is None
        endpoint = wc._read_object(Path(arguments[arguments.index("--endpoint") + 1]), "receiver endpoint")
        envelope = wc._read_object(Path(arguments[arguments.index("--envelope") + 1]), "receiver envelope")
        return dispatch_once(endpoint, envelope,
            arguments[arguments.index("--attempt-root") + 1],
            adapters={"ocrv-checker": NativeChecker()}).to_dict()

    monkeypatch.setattr(wc, "_run_json_command", command)
    instructions = tmp_path / "supervisor-continue.md"
    instructions.write_text("Continue the original task and Session after the narrow permission repair.", encoding="utf-8")
    identity = str(uuid.uuid4())
    invocation_keys = ("SLK_NATIVE_ACTIVITY_PATH", "SLK_NATIVE_ACTIVITY_CONTEXT", "SLK_WORKER_NATIVE_RESUME_SHA256")
    prior_environment = {key: os.environ.get(key) for key in invocation_keys}
    result = resume_worker_session(host, source, invocation_id=identity,
        instructions_path=instructions, instructions_sha256=wc._sha256(instructions),
        adapter=NativeWorker())

    fresh = Path(result["invocation_path"])
    assert result["status"] == "completed"
    assert result["output_delivery"]["status"] == "OUTPUT_DELIVERED"
    handoff = result["output_delivery"]["handoff"]
    assert handoff["status"] == "OWNED_HANDOFF_COMMITTED", handoff
    assert launched == [fresh] and len(received) == 1
    assert fresh == source / "native-resumes" / identity
    assert wc._read_object(fresh / "envelope.json", "fresh source") == asdict(incoming)
    assert (fresh / "completed.json").is_file()
    assert {key: os.environ.get(key) for key in invocation_keys} == prior_environment
    assert (fresh / "worker-result.json").read_bytes() == fresh_report
    assert all((source / name).read_bytes() == data for name, data in original_files.items())
    assert (source / "worker-result.json").read_bytes() == old_report

    outgoing, checker_source = received[0]
    invocation_identity = wc._stable_id(incoming.message_id, "native-resume:" + identity)
    assert outgoing.message_id == wc._stable_id(invocation_identity, "output-delivery")
    assert outgoing.message_id != wc._stable_id(incoming.message_id, "output-delivery")
    assert outgoing.payload_type == "CANDIDATE_READY" and outgoing.token_sequence == 4
    assert outgoing.payload["candidate"] == candidate
    assert outgoing.payload["source_message_id"] == incoming.message_id
    assert all(Path(item["path"]).parent == fresh for item in outgoing.payload["files"])
    assert any(Path(item["path"]).name == "worker-result.json" and item["sha256"] == wc._sha256(fresh / "worker-result.json")
               for item in outgoing.payload["files"])
    commit = wc._read_object(Path(handoff["commit_path"]), "real start commit")
    assert commit["attempt"] == 1 and commit["cell_id"] == incoming.cell_id
    assert Path(commit["start_evidence"]["stored_path"]) == checker_source / "started.json"
    after = host.projection()
    assert after["runtime_snapshot"]["runtime_revision"] == revision + 4
    assert after["runtime_snapshot"]["token_sequence"] == 4
    assert after["runtime_snapshot"]["token_holder_role_instance_id"] == host.endpoint("checker")["role_instance_id"]
    assert after["runtime_snapshot"]["latest_message_id"] == outgoing.message_id
    assert len(after["token_history"]) == len(before["token_history"]) + 1
    new_events = [event for event in after["events"]
                  if event["event_id"] not in {prior["event_id"] for prior in before["events"]}]
    actions = [event for event in new_events if event["event_type"] in
               {"WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED"}]
    assert [event["event_type"] for event in actions] == ["WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED"]
    assert all(event["attempt"] == 1 and event["cell_id"] == incoming.cell_id
               and event["author_role_instance_id"] == incoming.receiver_role_instance_id for event in actions)
    for event in actions:
        details = wc._event_details(event)
        assert details["decision_source"] == "WORKER_EXPLICIT"
        assert details["source_message_id"] == incoming.message_id
        assert details["native_task_id"] == session
        assert details["native_start_sha256"] == wc._sha256(fresh / "started.json")
        assert details["native_start_sha256"] != wc._sha256(source / "started.json")
    assert wc._event_details(actions[-1])["candidate"] == candidate
    assert wc._event_details(actions[-1])["handoff_message_id"] == outgoing.message_id
    assert len([event for event in new_events if event["event_type"] == "TRANSPORT_STARTED"]) == 1
    assert not any(event["event_type"] in {"D1_FAIL", "D1_FAILED", "REWORK_REQUESTED"} for event in after["events"])

    replay = host.complete(fresh)
    assert replay["handoff"]["status"] == "OWNED_HANDOFF_ALREADY_COMMITTED"
    assert len(received) == 1 and host.projection() == after
    with invocation_environment({"SLK_WORKER_NATIVE_RESUME_SHA256": wc._sha256(fresh / "native-resume.json")}):
        with pytest.raises(ValueError, match="ended native invocation"):
            host.record_worker_action(fresh, "WORK_STARTED", {})
    assert host.projection() == after
    assert all((source / name).read_bytes() == data for name, data in original_files.items())
