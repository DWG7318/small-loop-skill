"""A saved Supervisor credential may execute only closed administrative operations."""

import hashlib
import json
from pathlib import Path

import pytest

from slk_transport import supervisor_admin as admin


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def request_fixture(tmp_path: Path, operation: str = "revise-role-model") -> Path:
    operation_request = write_json(tmp_path / "operation.json", {
        "event_id": "model-revision-1", "run_id": "RUN-A",
        "role_instance_id": "RUN-A-supervisor-001",
    })
    sealed = tmp_path / "supervisor.sealed"
    sealed.write_text("sealed", encoding="ascii")
    return write_json(tmp_path / "admin.json", {
        "schema_version": "slk.supervisor-admin/v1",
        "run_id": "RUN-A",
        "supervisor_role_instance_id": "RUN-A-supervisor-001",
        "expected_runtime_revision": 7,
        "sealed_credential_path": str(sealed),
        "state_command": ["slk-state"],
        "operation": operation,
        "operation_request_path": str(operation_request),
        "operation_request_sha256": hashlib.sha256(operation_request.read_bytes()).hexdigest(),
        "result_path": str(tmp_path / "admin-result.json"),
    })


def test_closed_admin_consumer_authenticates_then_executes_without_exposing_secret(tmp_path, monkeypatch):
    request = request_fixture(tmp_path)
    calls = []
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda path: "slk_" + "a" * 64)
    def run(command, arguments, credential=None):
        calls.append((arguments, credential))
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "supervisor",
                    "role_instance_id": "RUN-A-supervisor-001", "runtime_revision": 7}
        return {"status": "model_revised", "run_id": "RUN-A", "runtime_revision": 8}
    monkeypatch.setattr(admin.wc, "_run_json_command", run)

    result = admin.execute_sealed_supervisor_admin(
        request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())

    assert [item[0][0] for item in calls] == ["authenticate-role", "revise-role-model"]
    assert result["status"] == "SUPERVISOR_ADMIN_COMPLETED"
    assert result["operation"] == "revise-role-model"
    assert "slk_" not in json.dumps(result)
    assert "slk_" not in Path(json.loads(request.read_text())["result_path"]).read_text()


def test_closed_admin_consumer_allows_authenticated_endpoint_rebind(tmp_path, monkeypatch):
    request = request_fixture(tmp_path, "rebind-session")
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda path: "slk_" + "c" * 64)

    def run(command, arguments, credential=None):
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "supervisor",
                    "role_instance_id": "RUN-A-supervisor-001", "runtime_revision": 7}
        return {"status": "rebound", "run_id": "RUN-A", "endpoint_version": 2}

    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    result = admin.execute_sealed_supervisor_admin(
        request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert result["operation"] == "rebind-session"


@pytest.mark.parametrize("damage", ["unknown-operation", "wrong-runtime", "changed-request"])
def test_admin_consumer_fails_closed_before_mutation(tmp_path, monkeypatch, damage):
    request = request_fixture(tmp_path, "replace-role" if damage == "unknown-operation" else "revise-role-model")
    value = json.loads(request.read_text())
    if damage == "changed-request":
        Path(value["operation_request_path"]).write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda path: "slk_" + "b" * 64)
    def run(command, arguments, credential=None):
        calls.append(arguments[0])
        return {"status": "authenticated", "run_id": "RUN-A", "role": "supervisor",
                "role_instance_id": "RUN-A-supervisor-001",
                "runtime_revision": 8 if damage == "wrong-runtime" else 7}
    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    with pytest.raises(ValueError):
        admin.execute_sealed_supervisor_admin(
            request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert "revise-role-model" not in calls
