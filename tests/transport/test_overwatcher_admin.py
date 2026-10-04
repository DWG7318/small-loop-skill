"""A saved Overwatcher credential is consumed only for OW-owned state writes."""

import hashlib
import json
from pathlib import Path

import pytest

from slk_transport import overwatcher_admin as admin


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def request_fixture(tmp_path: Path, operation: str = "record-overwatch-cycle") -> Path:
    operation_request = write_json(tmp_path / "operation.json", {
        "cycle_id": "cycle-1", "run_id": "RUN-A",
        "role_instance_id": "RUN-A-overwatcher-001",
    })
    sealed = tmp_path / "overwatcher.dpapi"
    sealed.write_text("sealed", encoding="ascii")
    return write_json(tmp_path / "admin.json", {
        "schema_version": "slk.overwatcher-admin/v1",
        "run_id": "RUN-A",
        "overwatcher_role_instance_id": "RUN-A-overwatcher-001",
        "expected_runtime_revision": 7,
        "sealed_credential_path": str(sealed),
        "state_command": ["slk-state"],
        "operation": operation,
        "operation_request_path": str(operation_request),
        "operation_request_sha256": hashlib.sha256(operation_request.read_bytes()).hexdigest(),
        "result_path": str(tmp_path / "admin-result.json"),
    })


def test_ow_consumer_authenticates_and_records_own_cycle_without_exposing_secret(tmp_path, monkeypatch):
    request = request_fixture(tmp_path)
    calls = []
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda path: "slk_" + "a" * 64)

    def run(command, arguments, credential=None, credential_scope="role"):
        calls.append((arguments, credential, credential_scope))
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "overwatcher",
                    "role_instance_id": "RUN-A-overwatcher-001", "runtime_revision": 7}
        return {"status": "overwatch_cycle_recorded", "run_id": "RUN-A", "cycle_id": "cycle-1"}

    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    result = admin.execute_sealed_overwatcher_admin(
        request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())

    assert [item[0][0] for item in calls] == ["authenticate-role", "record-overwatch-cycle"]
    assert [item[2] for item in calls] == ["role", "overwatcher"]
    assert result["status"] == "OVERWATCHER_ADMIN_COMPLETED"
    assert "slk_" not in json.dumps(result)
    assert "slk_" not in Path(json.loads(request.read_text())["result_path"]).read_text()


@pytest.mark.parametrize("damage", ["wrong-role", "wrong-runtime", "forbidden-operation", "changed-request"])
def test_ow_consumer_fails_closed_before_ow_state_write(tmp_path, monkeypatch, damage):
    operation = "close-overwatcher" if damage == "forbidden-operation" else "record-overwatch-cycle"
    request = request_fixture(tmp_path, operation)
    value = json.loads(request.read_text())
    if damage == "changed-request":
        Path(value["operation_request_path"]).write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda path: "slk_" + "b" * 64)

    def run(command, arguments, credential=None, credential_scope="role"):
        calls.append(arguments[0])
        return {"status": "authenticated", "run_id": "RUN-A",
                "role": "supervisor" if damage == "wrong-role" else "overwatcher",
                "role_instance_id": "RUN-A-overwatcher-001",
                "runtime_revision": 8 if damage == "wrong-runtime" else 7}

    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    with pytest.raises(ValueError):
        admin.execute_sealed_overwatcher_admin(
            request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert "record-overwatch-cycle" not in calls
