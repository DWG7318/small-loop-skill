"""The sealed replacement consumer never repeats a committed OW transition."""

import hashlib
import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from slk_transport import supervisor_admin as admin
from test_supervisor_admin import write_json


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replacement_request(tmp_path):
    identity = {"role": "overwatcher", "role_instance_id": "RUN-A-overwatcher-002",
        "agent_runtime": "codex", "provider": "openai", "model": "gpt-6-luna",
        "reasoning": "high", "session_id": "ow-new"}
    operation = write_json(tmp_path / "replace.json", {
        "event_id": "replace-ow-1", "run_id": "RUN-A", "mode": "CONTINUITY_RECOVERY",
        "expected_binding_revision": 1, "expected_runtime_revision": 7,
        "replacement": identity, "endpoint": {"endpoint_version": 1,
            "transport_adapter": "codex-app-server", "host_identity": "host-a",
            "session_id": "ow-new", "native_address": {"agent_id": "ow-new"}},
        "cadence_seconds": 600, "foreground_turn_id": "turn-new",
        "native_active_session_evidence": {"path": "new-live.json", "sha256": "a" * 64},
        "authorization_evidence": {"path": "authorized.json", "sha256": "b" * 64},
        "final_cycle_id": None, "reason": "restore the interrupted watch",
        "occurred_at": "2026-10-14T00:00:00Z",
    })
    sealed = tmp_path / "supervisor.sealed"
    sealed.write_text("sealed-supervisor", encoding="ascii")
    return write_json(tmp_path / "admin.json", {
        "schema_version": "slk.supervisor-admin/v1", "run_id": "RUN-A",
        "supervisor_role_instance_id": "RUN-A-supervisor-001", "expected_runtime_revision": 7,
        "sealed_credential_path": str(sealed), "state_command": ["slk-state"],
        "operation": "replace-overwatcher", "operation_request_path": str(operation),
        "operation_request_sha256": digest(operation), "result_path": str(tmp_path / "result.json"),
        "issued_role": "overwatcher", "issued_role_instance_id": identity["role_instance_id"],
        "credential_destination_path": str(tmp_path / "overwatcher.sealed"),
    })


def replacement_state(request, monkeypatch):
    raw = json.loads(request.read_text())
    operation = json.loads(Path(raw["operation_request_path"]).read_text())
    state = {"revision": 7, "replacements": 0, "rotations": 0, "calls": [],
        "secret": "slk_" + "b" * 64, "credential_id": "credential-first"}
    supervisor_secret = "slk_" + "a" * 64
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda p:
        supervisor_secret if Path(p) == Path(raw["sealed_credential_path"]) else state["secret"])

    def run(_command, arguments, *, credential, **_kwargs):
        command = arguments[0]
        state["calls"].append(command)
        if command == "authenticate-role":
            is_supervisor = arguments[-1] == raw["supervisor_role_instance_id"]
            assert credential == (supervisor_secret if is_supervisor else state["secret"])
            return {"status": "authenticated", "run_id": "RUN-A",
                "role": "supervisor" if is_supervisor else "overwatcher",
                "role_instance_id": arguments[-1], "runtime_revision": state["revision"]}
        assert credential == supervisor_secret
        if command == "replace-overwatcher":
            assert state["replacements"] == 0, "must not repeat the replacement"
            state["replacements"] += 1
            state["revision"] += 1
            return {"status": "overwatcher_replaced", "run_id": "RUN-A", "binding_revision": 2,
                "overwatcher_role_instance_id": raw["issued_role_instance_id"],
                "overwatcher_write_credential": state["secret"],
                "overwatcher_credential_id": state["credential_id"],
                "write_credential_delivery": "ONE_TIME_NON_REPLAYABLE"}
        assert command == "rotate-overwatcher-credential"
        rotation = json.loads(Path(arguments[-1]).read_text())
        assert rotation["expected_overwatcher_credential_id"] == state["credential_id"]
        assert rotation["role_instance_id"] == raw["issued_role_instance_id"]
        assert rotation["session_id"] == "ow-new"
        assert rotation["expected_runtime_revision"] == state["revision"]
        state["rotations"] += 1
        state["revision"] += 1
        state["secret"] = "slk_" + "c" * 64
        state["credential_id"] = "credential-rotated"
        return {"status": "overwatcher_credential_rotated", "run_id": "RUN-A",
            "binding_revision": 2, "runtime_revision": state["revision"],
            "overwatcher_role_instance_id": raw["issued_role_instance_id"],
            "overwatcher_write_credential": state["secret"],
            "overwatcher_credential_id": state["credential_id"],
            "write_credential_delivery": "ONE_TIME_NON_REPLAYABLE"}

    monkeypatch.setattr(admin.wc, "_run_json_command", run)

    def seal(secret, destination, **_kwargs):
        assert secret == state["secret"]
        Path(destination).write_bytes(b"sealed-new-ow")
        return {"status": "SEALED_ROLE_VERIFIED", "run_id": "RUN-A", "role": "overwatcher",
            "role_instance_id": raw["issued_role_instance_id"], "sealed_path": str(destination),
            "sealed_sha256": digest(destination), "runtime_revision": state["revision"]}

    monkeypatch.setattr(admin.wc, "seal_role_credential", seal)

    def projection(*_args):
        identity = operation["replacement"] if state["replacements"] else {
            **operation["replacement"], "role_instance_id": "RUN-A-overwatcher-001", "session_id": "ow-old"}
        return {"summary": {"run_id": "RUN-A", "closure_state": "open"},
            "runtime_snapshot": {"runtime_revision": state["revision"],
                "overwatcher_binding_revision": 2 if state["replacements"] else 1,
                "overwatcher_status": "ACTIVE"},
            "roles": [{**identity, "lifecycle": "active", "foreground_turn_id": "turn-new",
                "credential_id": state["credential_id"],
                "endpoints": [{**operation["endpoint"], "state": "active"}]}],
            "events": [{"event_id": operation["event_id"], "event_type": "OVERWATCHER_REPLACED",
                "author_role_instance_id": raw["supervisor_role_instance_id"],
                "details_json": json.dumps({"request_sha256": raw["operation_request_sha256"],
                    "overwatcher_role_instance_id": raw["issued_role_instance_id"], "binding_revision": 2})}]
                if state["replacements"] else [],
            "overwatcher_binding_transitions": [{"transition_id": operation["event_id"],
                "binding_revision": 2, "transition_type": "RECOVERY_REPLACEMENT", "cycle_id": None,
                "runtime_revision": 8, "evidence_ref": operation["native_active_session_evidence"]["path"],
                "occurred_at": operation["occurred_at"]}] if state["replacements"] else []}

    monkeypatch.setattr(admin.wc, "_default_load_current_projection", projection)
    return state


def execute(request):
    return admin.execute_sealed_supervisor_admin(request, request_sha256=digest(request))


def test_replacement_uses_existing_atomic_state_action_and_seals_once(tmp_path, monkeypatch):
    request = replacement_request(tmp_path)
    state = replacement_state(request, monkeypatch)
    result = execute(request)
    assert result["state_result"]["status"] == "overwatcher_replaced"
    assert result["issued_role_instance_id"] == "RUN-A-overwatcher-002"
    assert result["sealed_credential"]["status"] == "SEALED_ROLE_VERIFIED"
    assert state["calls"] == ["authenticate-role", "replace-overwatcher"]
    assert "slk_" not in json.dumps(result)
    assert "overwatcher_write_credential" not in json.dumps(result)
    assert execute(request) == result
    assert state["replacements"] == 1 and state["rotations"] == 0
    contract = Path(__file__).parents[2] / "docs/contracts/slk-supervisor-admin.schema.json"
    validator = Draft202012Validator(json.loads(contract.read_text()))
    validator.validate(json.loads(request.read_text()))
    validator.validate(result)


@pytest.mark.parametrize("damage", ["hash", "identity", "wrong-supervisor", "wrong-role", "stale"])
def test_replacement_rejects_wrong_authority_or_request_before_mutation(tmp_path, monkeypatch, damage):
    request = replacement_request(tmp_path)
    state = replacement_state(request, monkeypatch)
    raw = json.loads(request.read_text())
    if damage == "hash":
        Path(raw["operation_request_path"]).write_text("{}")
    elif damage == "identity":
        raw["issued_role_instance_id"] = "RUN-A-overwatcher-001"
        write_json(request, raw)
    elif damage == "stale":
        state["revision"] = 9
    else:
        original = admin.wc._run_json_command
        def run(*args, **kwargs):
            result = original(*args, **kwargs)
            result["role_instance_id" if damage == "wrong-supervisor" else "role"] = "wrong"
            return result
        monkeypatch.setattr(admin.wc, "_run_json_command", run)
    with pytest.raises(ValueError):
        execute(request)
    assert state["replacements"] == 0


@pytest.mark.parametrize("failure", ["seal-before-write", "seal-after-write", "receipt"])
def test_replacement_resumes_committed_state_after_local_save_failure(tmp_path, monkeypatch, failure):
    request = replacement_request(tmp_path)
    state = replacement_state(request, monkeypatch)
    raw = json.loads(request.read_text())
    seal = admin.wc.seal_role_credential
    save = admin.wc._write_or_reuse_stable_request
    def failed_seal(*args, **kwargs):
        if failure == "seal-after-write":
            seal(*args, **kwargs)
        raise OSError("injected seal failure")
    def failed_save(path, value):
        if Path(path) == Path(raw["result_path"]):
            raise OSError("injected final receipt failure")
        return save(path, value)
    monkeypatch.setattr(admin.wc, "seal_role_credential", seal if failure == "receipt" else failed_seal)
    monkeypatch.setattr(admin.wc, "_write_or_reuse_stable_request", failed_save)
    with pytest.raises(OSError, match="injected"):
        execute(request)
    assert state["replacements"] == 1
    assert not Path(raw["result_path"]).exists()
    monkeypatch.setattr(admin.wc, "seal_role_credential", seal)
    monkeypatch.setattr(admin.wc, "_write_or_reuse_stable_request", save)
    result = execute(request)
    assert result["status"] == "SUPERVISOR_ADMIN_COMPLETED"
    assert state["replacements"] == 1
    assert state["rotations"] == (1 if failure == "seal-before-write" else 0)
    assert execute(request) == result
    for path in tmp_path.glob("*.json"):
        assert state["secret"] not in path.read_text()


def real_replacement_request(tmp_path, monkeypatch):
    from test_worker_completion import actual_state_call, actual_worker_state
    credentials = {}
    state, config, _worker, _checker, _revision = actual_worker_state(tmp_path, credentials=credentials)
    monkeypatch.setenv("SLK_CONFIG_PATH", str(config))
    request = replacement_request(tmp_path)
    raw = json.loads(request.read_text())
    raw["state_command"] = [str(state)]
    operation_path = Path(raw["operation_request_path"])
    operation = json.loads(operation_path.read_text())
    address = {"kind": "supervisor_subagent", "parent": {
        "agent_runtime": "codex", "host_identity": "host-a", "session_id": "thread-a"},
        "agent_id": "ow-new", "unicode": "观察员 / 🚀", "small_number": 1e-7}
    operation["endpoint"]["native_address"] = address
    live = write_json(tmp_path / "live.json", {"status": "in_progress"})
    authorization = write_json(tmp_path / "authorization.json", {"authorized": True})
    operation["native_active_session_evidence"] = {"path": str(live), "sha256": digest(live)}
    operation["authorization_evidence"] = {"path": str(authorization), "sha256": digest(authorization)}
    old_identity = {**operation["replacement"], "role_instance_id": "RUN-A-overwatcher-001", "session_id": "ow-old"}
    old_endpoint = {**operation["endpoint"], "session_id": "ow-old", "native_address": {**address, "agent_id": "ow-old"}}
    bind = write_json(tmp_path / "bind.json", {"event_id": "bind-ow-old", "run_id": "RUN-A",
        "identity": old_identity, "endpoint": old_endpoint, "observation_mode": "FOREGROUND_ACTIVE_TURN",
        "cadence_seconds": 600, "foreground_turn_id": "turn-old", "binding_revision": 1,
        "canonical_task_id": "ow-old", "native_active_session_evidence_ref": str(live),
        "reason": "isolated replacement fixture", "occurred_at": "2026-10-14T00:00:00Z"})
    issued = actual_state_call(state, config, ["bind-overwatcher", "--request", bind],
        credential=credentials["supervisor"])
    status = write_json(tmp_path / "status.json", {"status_id": "old-turn-ended", "run_id": "RUN-A",
        "binding_revision": 1, "role_instance_id": old_identity["role_instance_id"],
        "session_id": "ow-old", "foreground_turn_id": "turn-old", "native_liveness": "COMPLETED",
        "evidence": {"path": str(live), "sha256": digest(live)}, "observed_at": "2026-10-14T00:00:01Z"})
    recorded = admin.wc._run_json_command([str(state)], ["record-overwatcher-status", "--request", str(status)],
        credential=issued["overwatcher_write_credential"], credential_scope="overwatcher")
    assert recorded["_slk_command"]["process_exit"] == 0
    projection = admin.wc._default_load_current_projection("RUN-A", [str(state)])
    operation["expected_runtime_revision"] = projection["runtime_snapshot"]["runtime_revision"]
    operation["occurred_at"] = "2026-10-14T00:00:02Z"
    raw["expected_runtime_revision"] = operation["expected_runtime_revision"]
    write_json(operation_path, operation)
    raw["operation_request_sha256"] = digest(operation_path)
    sealed = Path(raw["sealed_credential_path"])
    sealed.unlink()  # Only the synthetic file made by replacement_request above.
    admin.wc.seal_role_credential(credentials["supervisor"], sealed,
        run_id="RUN-A", role="supervisor", role_instance_id=raw["supervisor_role_instance_id"],
        state_command=[str(state)])
    write_json(request, raw)
    return request, issued["overwatcher_write_credential"]


@pytest.mark.skipif(os.name != "nt", reason="real DPAPI is Windows-only")
@pytest.mark.parametrize("failure", ["response", "seal-before", "seal-after", "receipt", "rotation-response"])
def test_real_cli_replacement_recovers_without_replacing_again(tmp_path, monkeypatch, capsys, failure):
    request, old_secret = real_replacement_request(tmp_path, monkeypatch)
    raw = json.loads(request.read_text())
    command = admin.wc._run_json_command
    seal = admin.wc.seal_role_credential
    save = admin.wc._write_or_reuse_stable_request
    secrets = [old_secret]
    def fault_command(binary, arguments, **kwargs):
        result = command(binary, arguments, **kwargs)
        if "overwatcher_write_credential" in result:
            secrets.append(result["overwatcher_write_credential"])
        if arguments[0] == "replace-overwatcher" and failure in {"response", "rotation-response"}:
            assert result["status"] == "overwatcher_replaced"
            raise OSError("injected lost response")
        return result
    def fault_seal(*args, **kwargs):
        if failure == "seal-after":
            seal(*args, **kwargs)
        raise OSError("injected seal failure")
    def fault_save(path, value):
        if Path(path) == Path(raw["result_path"]):
            raise OSError("injected receipt failure")
        return save(path, value)
    monkeypatch.setattr(admin.wc, "_run_json_command", fault_command)
    if failure.startswith("seal-"):
        monkeypatch.setattr(admin.wc, "seal_role_credential", fault_seal)
    if failure == "receipt":
        monkeypatch.setattr(admin.wc, "_write_or_reuse_stable_request", fault_save)
    with pytest.raises(OSError, match="injected"):
        execute(request)
    monkeypatch.setattr(admin.wc, "_run_json_command", command)
    monkeypatch.setattr(admin.wc, "seal_role_credential", seal)
    monkeypatch.setattr(admin.wc, "_write_or_reuse_stable_request", save)
    if failure == "rotation-response":
        def lost_rotation(binary, arguments, **kwargs):
            result = command(binary, arguments, **kwargs)
            if arguments[0] == "rotate-overwatcher-credential":
                assert result["status"] == "overwatcher_credential_rotated"
                secrets.append(result["overwatcher_write_credential"])
                raise OSError("injected lost rotation response")
            return result
        monkeypatch.setattr(admin.wc, "_run_json_command", lost_rotation)
        with pytest.raises(OSError, match="lost rotation response"):
            execute(request)
        monkeypatch.setattr(admin.wc, "_run_json_command", command)
    result = execute(request)
    assert result["status"] == "SUPERVISOR_ADMIN_COMPLETED"
    assert execute(request) == result
    projection = admin.wc._default_load_current_projection("RUN-A", raw["state_command"])
    replacements = [e for e in projection["events"] if e["event_type"] == "OVERWATCHER_REPLACED"]
    assert len(replacements) == 1
    assert json.loads(replacements[0]["details_json"])["request_sha256"] == raw["operation_request_sha256"]
    assert projection["runtime_snapshot"]["overwatcher_binding_revision"] == 2
    old_auth = command(raw["state_command"], ["authenticate-role", "--run-id", "RUN-A",
        "--role-instance-id", "RUN-A-overwatcher-001"], credential=old_secret)
    assert old_auth["_slk_command"]["process_exit"] != 0
    secrets.append(admin.wc.unprotect_dpapi_hex(raw["credential_destination_path"]))
    captured = capsys.readouterr()
    for secret in secrets:
        assert secret not in captured.out + captured.err + json.dumps(result) + json.dumps(projection)
        for path in tmp_path.glob("*.json"):
            assert secret not in path.read_text()
def test_replacement_recovers_when_committed_response_was_lost(tmp_path, monkeypatch):
    request = replacement_request(tmp_path)
    state = replacement_state(request, monkeypatch)
    original = admin.wc._run_json_command
    def lose_response(command, arguments, **kwargs):
        value = original(command, arguments, **kwargs)
        if arguments[0] == "replace-overwatcher":
            raise OSError("committed response lost")
        return value
    monkeypatch.setattr(admin.wc, "_run_json_command", lose_response)
    with pytest.raises(OSError, match="response lost"):
        execute(request)
    monkeypatch.setattr(admin.wc, "_run_json_command", original)
    assert execute(request)["status"] == "SUPERVISOR_ADMIN_COMPLETED"
    assert state["replacements"] == 1 and state["rotations"] == 1


@pytest.mark.parametrize("damage", ["request", "actor", "superseded", "credential-id", "old-sealed"])
def test_replacement_retry_requires_exact_central_fact_and_current_new_binding(tmp_path, monkeypatch, damage):
    request = replacement_request(tmp_path)
    state = replacement_state(request, monkeypatch)
    state.update(replacements=1, revision=8)
    raw = json.loads(request.read_text())
    projection = admin.wc._default_load_current_projection
    def damaged(*args):
        value = projection(*args)
        if damage == "request":
            details = json.loads(value["events"][0]["details_json"])
            details["request_sha256"] = "f" * 64
            value["events"][0]["details_json"] = json.dumps(details)
        elif damage == "actor":
            value["events"][0]["author_role_instance_id"] = "previous-supervisor"
        elif damage == "superseded":
            value["roles"][0]["role_instance_id"] = "RUN-A-overwatcher-003"
        elif damage == "credential-id":
            value["roles"][0].pop("credential_id")
        return value
    monkeypatch.setattr(admin.wc, "_default_load_current_projection", damaged)
    if damage == "old-sealed":
        Path(raw["credential_destination_path"]).write_text("old sealed credential")
        original = admin.wc._run_json_command
        def old_identity(command, arguments, **kwargs):
            value = original(command, arguments, **kwargs)
            if arguments[-1] == raw["issued_role_instance_id"]:
                value["role_instance_id"] = "RUN-A-overwatcher-001"
            return value
        monkeypatch.setattr(admin.wc, "_run_json_command", old_identity)
    with pytest.raises(ValueError):
        execute(request)
    assert state["rotations"] == 0
    assert not Path(raw["result_path"]).exists()


def test_replacement_retry_can_refresh_a_rotation_request_after_an_unrelated_revision(tmp_path, monkeypatch):
    request = replacement_request(tmp_path)
    state = replacement_state(request, monkeypatch)
    state.update(replacements=1, revision=8)
    original = admin.wc._run_json_command
    def unavailable(command, arguments, **kwargs):
        if arguments[0] == "rotate-overwatcher-credential":
            raise OSError("rotation never started")
        return original(command, arguments, **kwargs)
    monkeypatch.setattr(admin.wc, "_run_json_command", unavailable)
    with pytest.raises(OSError, match="never started"):
        execute(request)
    state["revision"] += 1
    monkeypatch.setattr(admin.wc, "_run_json_command", original)
    assert execute(request)["status"] == "SUPERVISOR_ADMIN_COMPLETED"
    assert state["replacements"] == 1 and state["rotations"] == 1


def test_replacement_schema_requires_overwatcher_issuance(tmp_path):
    request = json.loads(replacement_request(tmp_path).read_text())
    request["issued_role"] = "checker"
    contract = Path(__file__).parents[2] / "docs/contracts/slk-supervisor-admin.schema.json"
    validator = Draft202012Validator(json.loads(contract.read_text()))
    assert not validator.is_valid(request)


@pytest.mark.skipif(os.name != "nt", reason="real DPAPI is Windows-only")
@pytest.mark.parametrize("damage", ["same-name-request", "old-identity", "superseded-new-role"])
def test_real_replacement_refuses_changed_or_superseded_identity(tmp_path, monkeypatch, damage):
    request, old_secret = real_replacement_request(tmp_path, monkeypatch)
    raw = json.loads(request.read_text())
    operation_path = Path(raw["operation_request_path"])
    operation = json.loads(operation_path.read_text())
    if damage == "old-identity":
        operation["replacement"].update(role_instance_id="RUN-A-overwatcher-001", session_id="ow-old")
        operation["endpoint"]["session_id"] = "ow-old"
        operation["endpoint"]["native_address"]["agent_id"] = "ow-old"
        raw["issued_role_instance_id"] = "RUN-A-overwatcher-001"
    else:
        supervisor = admin.wc.unprotect_dpapi_hex(raw["sealed_credential_path"])
        replaced = admin.wc._run_json_command(raw["state_command"],
            ["replace-overwatcher", "--request", str(operation_path)], credential=supervisor)
        assert replaced["status"] == "overwatcher_replaced"
        if damage == "same-name-request":
            operation["reason"] = "a different request cannot claim the same replacement"
        else:
            status = write_json(tmp_path / "new-status.json", {"status_id": "new-turn-ended",
                "run_id": "RUN-A", "binding_revision": 2, "role_instance_id": raw["issued_role_instance_id"],
                "session_id": "ow-new", "foreground_turn_id": "turn-new", "native_liveness": "COMPLETED",
                "evidence": operation["native_active_session_evidence"], "observed_at": "2026-10-14T00:00:03Z"})
            ended = admin.wc._run_json_command(raw["state_command"],
                ["record-overwatcher-status", "--request", str(status)],
                credential=replaced["overwatcher_write_credential"], credential_scope="overwatcher")
            assert ended["_slk_command"]["process_exit"] == 0
            projection = admin.wc._default_load_current_projection("RUN-A", raw["state_command"])
            successor = json.loads(json.dumps(operation))
            successor.update(event_id="replace-again", expected_binding_revision=2,
                expected_runtime_revision=projection["runtime_snapshot"]["runtime_revision"])
            successor["replacement"].update(role_instance_id="RUN-A-overwatcher-003", session_id="ow-third")
            successor["endpoint"]["session_id"] = "ow-third"
            successor["endpoint"]["native_address"]["agent_id"] = "ow-third"
            successor_path = write_json(tmp_path / "successor.json", successor)
            latest = admin.wc._run_json_command(raw["state_command"],
                ["replace-overwatcher", "--request", str(successor_path)], credential=supervisor)
            assert latest["status"] == "overwatcher_replaced"
        supervisor = ""
    write_json(operation_path, operation)
    raw["operation_request_sha256"] = digest(operation_path)
    write_json(request, raw)
    before = admin.wc._default_load_current_projection("RUN-A", raw["state_command"])
    with pytest.raises(ValueError):
        execute(request)
    after = admin.wc._default_load_current_projection("RUN-A", raw["state_command"])
    assert before == after
    assert not Path(raw["result_path"]).exists()


@pytest.mark.skipif(os.name != "nt", reason="real DPAPI is Windows-only")
def test_partial_seal_is_preserved_and_recovers_only_to_a_new_explicit_destination(tmp_path, monkeypatch):
    request, _old_secret = real_replacement_request(tmp_path, monkeypatch)
    raw = json.loads(request.read_text())
    original_seal = admin.wc.seal_role_credential
    def partial_seal(_secret, destination, **_kwargs):
        Path(destination).write_bytes(b"partial-not-a-dpapi-blob")
        raise OSError("injected partial seal")
    monkeypatch.setattr(admin.wc, "seal_role_credential", partial_seal)
    with pytest.raises(OSError, match="partial seal"):
        execute(request)
    monkeypatch.setattr(admin.wc, "seal_role_credential", original_seal)
    old_destination = Path(raw["credential_destination_path"])
    before = admin.wc._default_load_current_projection("RUN-A", raw["state_command"])
    with pytest.raises(admin.wc.CompletionError):
        execute(request)
    assert not Path(raw["result_path"]).exists()
    assert admin.wc._default_load_current_projection("RUN-A", raw["state_command"]) == before
    raw["credential_destination_path"] = str(tmp_path / "overwatcher-recovered.sealed")
    write_json(request, raw)
    assert execute(request)["status"] == "SUPERVISOR_ADMIN_COMPLETED"
    assert old_destination.read_bytes() == b"partial-not-a-dpapi-blob"
    projection = admin.wc._default_load_current_projection("RUN-A", raw["state_command"])
    assert len([e for e in projection["events"] if e["event_type"] == "OVERWATCHER_REPLACED"]) == 1
