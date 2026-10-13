"""Explicit Supervisor abandonment is sealed management, not engineering success."""

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from slk_transport import supervisor_admin as admin
from test_supervisor_admin import terminal_request_fixture, write_json


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_sealed_abandon_authenticates_supervisor_and_writes_only_abandoned(tmp_path, monkeypatch):
    request = terminal_request_fixture(tmp_path, "abandon-run")
    raw = json.loads(request.read_text())
    calls = []
    secret = "slk_" + "s" * 64
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _path: secret)

    def state(_command, arguments, *, credential):
        assert credential == secret
        calls.append(arguments[0])
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "supervisor",
                    "role_instance_id": raw["supervisor_role_instance_id"], "runtime_revision": 7}
        assert arguments == ["write", "--request", raw["operation_request_path"]]
        assert json.loads(Path(arguments[2]).read_text())["event_type"] == "RUN_ABANDONED"
        return {"status": "recorded", "run_id": "RUN-A"}

    monkeypatch.setattr(admin.wc, "_run_json_command", state)
    result = admin.execute_sealed_supervisor_admin(request, request_sha256=digest(request))
    assert calls == ["authenticate-role", "write"]
    assert result["operation"] == "abandon-run"
    assert secret not in json.dumps(result)
    assert admin.execute_sealed_supervisor_admin(request, request_sha256=digest(request)) == result
    assert calls == ["authenticate-role", "write"]
    contract = Path(__file__).resolve().parents[2] / "docs/contracts/slk-supervisor-admin.schema.json"
    validator = Draft202012Validator(json.loads(contract.read_text()))
    validator.validate(raw)
    validator.validate(result)


@pytest.mark.parametrize("event_type", ["RUN_CLOSED", "D2_PASSED", "WORK_STARTED"])
def test_abandon_rejects_other_events_before_unsealing(tmp_path, monkeypatch, event_type):
    request = terminal_request_fixture(tmp_path, "abandon-run")
    raw = json.loads(request.read_text())
    operation = Path(raw["operation_request_path"])
    value = json.loads(operation.read_text())
    value["event_type"] = event_type
    write_json(operation, value)
    raw["operation_request_sha256"] = digest(operation)
    write_json(request, raw)
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _path: pytest.fail("must not unseal"))
    with pytest.raises(ValueError, match="RUN_ABANDONED"):
        admin.execute_sealed_supervisor_admin(request, request_sha256=digest(request))


@pytest.mark.parametrize("damage", [None, "author", "event-type", "time", "details", "absent"])
def test_abandon_retry_after_state_write_requires_its_exact_original_event(tmp_path, monkeypatch, damage):
    request = terminal_request_fixture(tmp_path, "abandon-run")
    raw = json.loads(request.read_text())
    operation = json.loads(Path(raw["operation_request_path"]).read_text())
    recorded = {**operation, "author_role_instance_id": operation["role_instance_id"],
                "details_json": json.dumps(operation["details"])}
    # Actual BI projection serializes details; it does not also expose request details.
    recorded.pop("details")
    if damage == "author": recorded["author_role_instance_id"] = "different-supervisor"
    if damage == "event-type": recorded["event_type"] = "RUN_CLOSED"
    if damage == "time": recorded["occurred_at"] = "2026-10-06T00:00:02Z"
    if damage == "details": recorded["details_json"] = '{"reason":"changed"}'
    events = [] if damage == "absent" else [recorded]
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _path: "sealed-consumer-secret")
    monkeypatch.setattr(admin.wc, "_default_load_current_projection", lambda *_a: {"events": events})
    writes = []

    def state(_command, arguments, **_kwargs):
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "supervisor",
                    "role_instance_id": raw["supervisor_role_instance_id"], "runtime_revision": 8}
        writes.append(arguments)
        return {"status": "recorded", "run_id": "RUN-A"}

    monkeypatch.setattr(admin.wc, "_run_json_command", state)
    if damage is not None:
        with pytest.raises(ValueError, match="stale"):
            admin.execute_sealed_supervisor_admin(request, request_sha256=digest(request))
        assert not writes
        assert not Path(raw["result_path"]).exists()
    else:
        receipt = admin.execute_sealed_supervisor_admin(request, request_sha256=digest(request))
        assert receipt["status"] == "SUPERVISOR_ADMIN_COMPLETED"
        assert writes == [["write", "--request", raw["operation_request_path"]]]
