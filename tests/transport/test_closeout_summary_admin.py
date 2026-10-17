"""The existing sealed Supervisor consumer can record a summary, not decide D2."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from slk_transport import supervisor_admin as admin
from test_supervisor_admin import request_fixture, write_json


def fixture(tmp_path):
    path = request_fixture(tmp_path, "record-closeout-summary")
    request = json.loads(path.read_text())
    operation = Path(request["operation_request_path"])
    write_json(operation, {
        "run_id": "RUN-A", "original_id": "summary-1",
        "body": "成果已交付。现场补交原证据，未重做 D2。",
        "recorded_at": "2026-10-18T00:00:00Z",
        "device_signature": {"computer_name": "PC-A", "ip_address": None,
                             "os_version": "Windows 11"},
    })
    request["operation_request_sha256"] = hashlib.sha256(operation.read_bytes()).hexdigest()
    write_json(path, request)
    return path, request


def test_summary_uses_exact_sealed_supervisor_and_reuses_receipt(tmp_path, monkeypatch):
    path, request = fixture(tmp_path)
    calls = []
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _: "test-only-secret")

    def command(_command, args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "supervisor",
                    "role_instance_id": "RUN-A-supervisor-001", "runtime_revision": 7}
        assert args == ["record-closeout-summary", "--request", request["operation_request_path"]]
        return {"status": "summary_recorded", "run_id": "RUN-A", "original_id": "summary-1"}

    monkeypatch.setattr(admin.wc, "_run_json_command", command)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = admin.execute_sealed_supervisor_admin(path, request_sha256=digest)
    assert result["status"] == "SUPERVISOR_ADMIN_COMPLETED"
    assert len(calls) == 2
    assert all(k["credential"] == "test-only-secret" for _, k in calls)
    assert all(k.get("credential_scope", "role") == "role" for _, k in calls)
    assert "test-only-secret" not in json.dumps(result)
    assert admin.execute_sealed_supervisor_admin(path, request_sha256=digest) == result
    assert len(calls) == 2
    schema = Path(__file__).resolve().parents[2] / "docs/contracts/slk-supervisor-admin.schema.json"
    validator = Draft202012Validator(json.loads(schema.read_text()))
    validator.validate(request)
    validator.validate(result)


@pytest.mark.parametrize("role,revision", [("worker", 7), ("checker", 7), ("overwatcher", 7), ("supervisor", 6)])
def test_summary_rejects_wrong_authority_or_revision(tmp_path, monkeypatch, role, revision):
    path, _ = fixture(tmp_path)
    calls = []
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _: "test-only-secret")
    def command(_command, args, **_kwargs):
        calls.append(args[0])
        return {"status": "authenticated", "run_id": "RUN-A", "role": role,
                "role_instance_id": "RUN-A-supervisor-001", "runtime_revision": revision}
    monkeypatch.setattr(admin.wc, "_run_json_command", command)
    with pytest.raises(ValueError, match="authenticate the exact current Supervisor"):
        admin.execute_sealed_supervisor_admin(path, request_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    assert calls == ["authenticate-role"]


def test_summary_cannot_change_run_at_sealed_boundary(tmp_path, monkeypatch):
    path, request = fixture(tmp_path)
    operation = Path(request["operation_request_path"])
    value = json.loads(operation.read_text())
    value["run_id"] = "RUN-B"
    write_json(operation, value)
    request["operation_request_sha256"] = hashlib.sha256(operation.read_bytes()).hexdigest()
    write_json(path, request)
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _: pytest.fail("must reject before unseal"))
    with pytest.raises(ValueError, match="changed Run identity"):
        admin.execute_sealed_supervisor_admin(path, request_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def test_sealed_summary_consumer_reaches_real_cli_and_projection(tmp_path, monkeypatch):
    from test_worker_completion import actual_state_call
    from slk_transport.native_activity import utc_now
    root = Path(__file__).resolve().parents[2]
    binary = root / "target/debug" / ("slk-state.exe" if os.name == "nt" else "slk-state")
    query = binary.with_name("slk-bi-query.exe" if os.name == "nt" else "slk-bi-query")
    if not binary.is_file() or not query.is_file():
        pytest.skip("build real state/query binaries for integration")
    config = tmp_path / "config.json"
    actual_state_call(binary, config, ["configure", "--data-root", tmp_path / "data"])
    request = {"project": {"project_id": "P", "name": "Isolated", "repository_url": None,
                           "last_known_path": str(tmp_path)},
               "run_id": "RUN-A", "goal": "summary test", "boundaries": {},
               "go_nodes": [{"go_id": "GO-1", "ordinal": 1, "title": "G", "objective": "G"}],
               "cell_nodes": [{"go_id": "GO-1", "cell_id": "C-1", "ordinal": 1, "title": "C", "objective": "C"}],
               "supervisor": {"role_instance_id": "RUN-A-supervisor-001", "role": "supervisor",
                   "agent_runtime": "codex", "provider": "openai", "model": "gpt-6.1-sol",
                   "reasoning": "high", "session_id": "parent"},
               "supervisor_endpoint": {"endpoint_version": 1, "transport_adapter": "codex-app-server",
                   "host_identity": "local", "session_id": "parent", "native_address": {"thread_id": "parent"}},
               "occurred_at": utc_now()}
    init_path = write_json(tmp_path / "init.json", request)
    initialized = actual_state_call(binary, config, ["init-run", "--request", init_path])
    before = actual_state_call(query, config, ["run", "--run-id", "RUN-A"])
    path, sealed_request = fixture(tmp_path)
    sealed_request.update(state_command=[str(binary)],
                          expected_runtime_revision=before["runtime_snapshot"]["runtime_revision"])
    write_json(path, sealed_request)
    monkeypatch.setenv("SLK_CONFIG_PATH", str(config))
    # Only OS secret retrieval is substituted; authenticated subprocesses and DB are real.
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _: initialized["supervisor_credential"])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = admin.execute_sealed_supervisor_admin(path, request_sha256=digest)
    assert result["state_result"]["status"] == "summary_recorded"
    after = actual_state_call(query, config, ["run", "--run-id", "RUN-A"])
    assert after["closeout_summary"] == result["state_result"]["closeout_summary"]
    assert after["closeout_summary"]["authored_by"] == "RUN-A-supervisor-001"
    assert after["runtime_snapshot"] == before["runtime_snapshot"]
    assert after["events"] == before["events"]
    assert initialized["supervisor_credential"] not in json.dumps(result)
    assert admin.execute_sealed_supervisor_admin(path, request_sha256=digest) == result
