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


def test_closed_admin_consumer_allows_versioned_cell_split_revise_plan(tmp_path, monkeypatch):
    request = request_fixture(tmp_path, "revise-plan")
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda path: "slk_" + "c" * 64)
    calls = []

    def run(command, arguments, credential=None):
        calls.append(arguments[0])
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "supervisor",
                    "role_instance_id": "RUN-A-supervisor-001", "runtime_revision": 7}
        return {"status": "revised", "run_id": "RUN-A", "revision": 2}

    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    result = admin.execute_sealed_supervisor_admin(
        request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert result["state_result"]["revision"] == 2
    assert calls == ["authenticate-role", "revise-plan"]


@pytest.mark.parametrize(
    ("operation", "role", "secret_field", "status"),
    [
        ("register-role", "checker", "role_credential", "registered"),
        ("bind-overwatcher", "overwatcher", "overwatcher_write_credential", "overwatcher_bound"),
    ],
)
def test_supervisor_admin_registers_and_seals_new_role_without_returning_plaintext(
    tmp_path, monkeypatch, operation, role, secret_field, status,
):
    role_instance_id = f"RUN-A-{role}-001"
    operation_request = write_json(tmp_path / "operation.json", {
        "run_id": "RUN-A", "identity": {"role": role, "role_instance_id": role_instance_id},
    })
    sealed_supervisor = tmp_path / "supervisor.sealed"
    sealed_supervisor.write_text("sealed", encoding="ascii")
    destination = tmp_path / f"{role}.sealed"
    request = write_json(tmp_path / "admin.json", {
        "schema_version": "slk.supervisor-admin/v1", "run_id": "RUN-A",
        "supervisor_role_instance_id": "RUN-A-supervisor-001",
        "expected_runtime_revision": 7, "sealed_credential_path": str(sealed_supervisor),
        "state_command": ["slk-state"], "operation": operation,
        "operation_request_path": str(operation_request),
        "operation_request_sha256": hashlib.sha256(operation_request.read_bytes()).hexdigest(),
        "result_path": str(tmp_path / "admin-result.json"), "issued_role": role,
        "issued_role_instance_id": role_instance_id,
        "credential_destination_path": str(destination),
    })
    secret = "slk_" + "d" * 64
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda path: "slk_" + "a" * 64)
    def seal(value, target, **_kwargs):
        if value != secret or Path(target) != destination:
            pytest.fail("wrong credential seal")
        Path(target).write_bytes(b"sealed-issued-role")
        return {
            "status": "SEALED_ROLE_VERIFIED", "run_id": "RUN-A", "role": role,
            "role_instance_id": role_instance_id, "sealed_path": str(target),
            "sealed_sha256": hashlib.sha256(Path(target).read_bytes()).hexdigest(),
            "runtime_revision": 8,
        }
    monkeypatch.setattr(admin.wc, "seal_role_credential", seal)

    def run(command, arguments, credential=None):
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "supervisor",
                    "role_instance_id": "RUN-A-supervisor-001", "runtime_revision": 7}
        result = {"status": status, "run_id": "RUN-A", secret_field: secret, "export": "run.md"}
        if role == "overwatcher":
            result["overwatcher_role_instance_id"] = role_instance_id
            result["overwatcher_credential_id"] = "credential-id"
        else:
            result["credential_id"] = "credential-id"
        return result

    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    result = admin.execute_sealed_supervisor_admin(
        request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())

    assert result["sealed_credential"]["status"] == "SEALED_ROLE_VERIFIED"
    assert secret not in json.dumps(result)
    assert secret_field not in json.dumps(result)

    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _path: pytest.fail(
        "matching replay must not consume Supervisor authority"))
    replay = admin.execute_sealed_supervisor_admin(
        request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert replay == result

    destination.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sealed credential"):
        admin.execute_sealed_supervisor_admin(
            request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())


def test_supervisor_admin_registers_worker_only_through_exact_sealed_checker_authority(
    tmp_path, monkeypatch,
):
    worker_id = "RUN-A-worker-001"
    checker_id = "RUN-A-checker-001"
    operation_request = write_json(tmp_path / "register-worker.json", {
        "run_id": "RUN-A",
        "identity": {"role": "worker", "role_instance_id": worker_id},
    })
    supervisor_sealed = tmp_path / "supervisor.sealed"
    checker_sealed = tmp_path / "checker.sealed"
    supervisor_sealed.write_text("supervisor-sealed", encoding="ascii")
    checker_sealed.write_text("checker-sealed", encoding="ascii")
    destination = tmp_path / "worker.sealed"
    request = write_json(tmp_path / "admin.json", {
        "schema_version": "slk.supervisor-admin/v1",
        "run_id": "RUN-A",
        "supervisor_role_instance_id": "RUN-A-supervisor-001",
        "expected_runtime_revision": 7,
        "sealed_credential_path": str(supervisor_sealed),
        "state_command": ["slk-state"],
        "operation": "register-role",
        "operation_request_path": str(operation_request),
        "operation_request_sha256": hashlib.sha256(operation_request.read_bytes()).hexdigest(),
        "result_path": str(tmp_path / "admin-result.json"),
        "issued_role": "worker",
        "issued_role_instance_id": worker_id,
        "credential_destination_path": str(destination),
        "checker_role_instance_id": checker_id,
        "sealed_checker_credential_path": str(checker_sealed),
    })
    supervisor_secret = "slk_" + "a" * 64
    checker_secret = "slk_" + "b" * 64
    worker_secret = "slk_" + "c" * 64

    monkeypatch.setattr(
        admin.wc,
        "unprotect_dpapi_hex",
        lambda path: checker_secret if Path(path) == checker_sealed else supervisor_secret,
    )
    calls = []

    def run(command, arguments, credential=None):
        calls.append((arguments[0], credential))
        if arguments[0] == "authenticate-role":
            target = arguments[-1]
            return {
                "status": "authenticated",
                "run_id": "RUN-A",
                "role": "checker" if target == checker_id else "supervisor",
                "role_instance_id": target,
                "runtime_revision": 7,
            }
        assert credential == checker_secret
        return {
            "status": "registered",
            "run_id": "RUN-A",
            "role_credential": worker_secret,
            "credential_id": "worker-credential-id",
        }

    monkeypatch.setattr(admin.wc, "_run_json_command", run)

    def seal(value, target, **kwargs):
        assert value == worker_secret
        assert kwargs["role"] == "worker"
        Path(target).write_bytes(b"sealed-worker")
        return {
            "status": "SEALED_ROLE_VERIFIED",
            "run_id": "RUN-A",
            "role": "worker",
            "role_instance_id": worker_id,
            "sealed_path": str(target),
            "sealed_sha256": hashlib.sha256(Path(target).read_bytes()).hexdigest(),
            "runtime_revision": 8,
        }

    monkeypatch.setattr(admin.wc, "seal_role_credential", seal)
    result = admin.execute_sealed_supervisor_admin(
        request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())

    assert calls == [
        ("authenticate-role", supervisor_secret),
        ("authenticate-role", checker_secret),
        ("register-role", checker_secret),
    ]
    assert result["issued_role"] == "worker"
    assert supervisor_secret not in json.dumps(result)
    assert checker_secret not in json.dumps(result)
    assert worker_secret not in json.dumps(result)


def test_worker_registration_without_checker_consumer_fields_fails_before_state_mutation(
    tmp_path, monkeypatch,
):
    role_instance_id = "RUN-A-worker-001"
    operation_request = write_json(tmp_path / "operation.json", {
        "run_id": "RUN-A", "identity": {"role": "worker", "role_instance_id": role_instance_id},
    })
    sealed = tmp_path / "supervisor.sealed"
    sealed.write_text("sealed", encoding="ascii")
    request = write_json(tmp_path / "admin.json", {
        "schema_version": "slk.supervisor-admin/v1", "run_id": "RUN-A",
        "supervisor_role_instance_id": "RUN-A-supervisor-001",
        "expected_runtime_revision": 7, "sealed_credential_path": str(sealed),
        "state_command": ["slk-state"], "operation": "register-role",
        "operation_request_path": str(operation_request),
        "operation_request_sha256": hashlib.sha256(operation_request.read_bytes()).hexdigest(),
        "result_path": str(tmp_path / "admin-result.json"), "issued_role": "worker",
        "issued_role_instance_id": role_instance_id,
        "credential_destination_path": str(tmp_path / "worker.sealed"),
    })
    monkeypatch.setattr(
        admin.wc, "unprotect_dpapi_hex", lambda _path: pytest.fail("must fail before credential access")
    )

    with pytest.raises(ValueError, match="closed"):
        admin.execute_sealed_supervisor_admin(
            request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())


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
