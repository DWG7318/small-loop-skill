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
        "schema_version": "slk.supervisor-admin/v1", "run_id": "RUN-A",
        "supervisor_role_instance_id": "RUN-A-supervisor-001", "expected_runtime_revision": 7,
        "sealed_credential_path": str(sealed), "state_command": ["slk-state"], "operation": operation,
        "operation_request_path": str(operation_request),
        "operation_request_sha256": hashlib.sha256(operation_request.read_bytes()).hexdigest(),
        "result_path": str(tmp_path / "admin-result.json"),
    })


def test_start_d2_admin_uses_original_bound_host_and_sealed_supervisor(tmp_path, monkeypatch):
    from test_role_host import current_d2_fixture
    host, source, _incoming, _result, _projection, seen = current_d2_fixture(tmp_path, monkeypatch)
    binding = write_json(tmp_path / "binding.json", host.binding)
    operation = write_json(tmp_path / "start-d2.json", {"run_id": "RUN-A",
        "role_instance_id": host.endpoint("supervisor")["role_instance_id"],
        "binding_path": str(binding), "binding_sha256": hashlib.sha256(binding.read_bytes()).hexdigest(),
        "source_attempt_path": str(source)})
    request = request_fixture(tmp_path, "start-d2")
    raw = json.loads(request.read_text())
    raw.update(sealed_credential_path=host.credential_path("supervisor"), state_command=host.state,
        operation_request_path=str(operation), operation_request_sha256=hashlib.sha256(operation.read_bytes()).hexdigest())
    write_json(request, raw)
    monkeypatch.setattr(admin.wc, "_default_load_current_projection", lambda *_a, **_k: _projection)
    digest = hashlib.sha256(request.read_bytes()).hexdigest()
    receipt = admin.execute_sealed_supervisor_admin(request, request_sha256=digest)
    assert receipt["operation"] == "start-d2"
    assert [e["event_type"] for e in seen] == ["D2_STARTED"]
    assert admin.execute_sealed_supervisor_admin(request, request_sha256=digest) == receipt
    from jsonschema import Draft202012Validator
    from slk_transport.cli import main
    contract = Path(__file__).resolve().parents[2] / "docs/contracts/slk-supervisor-admin.schema.json"
    validator = Draft202012Validator(json.loads(contract.read_text()))
    validator.validate(raw)
    validator.validate(receipt)
    assert main(["start-d2", "--request", str(request), "--sha256", digest]) == 0


def terminal_request_fixture(tmp_path: Path, operation: str) -> Path:
    operation_value = {
        "event_id": "close-checker-1",
        "run_id": "RUN-A",
        "role_instance_id": "RUN-A-checker-001",
        "role": "checker",
        "reason": "terminal Run member retirement",
        "occurred_at": "2026-10-06T00:00:02Z",
    }
    if operation == "close-run":
        operation_value = {
            "event_id": "run-closed-1",
            "run_id": "RUN-A",
            "go_id": None,
            "cell_id": None,
            "attempt": None,
            "plan_revision": 1,
            "role_instance_id": "RUN-A-supervisor-001",
            "event_type": "RUN_CLOSED",
            "details": {},
            "corrects_event_id": None,
            "occurred_at": "2026-10-06T00:00:01Z",
        }
    elif operation == "close-overwatcher":
        operation_value = {
            "event_id": "close-overwatcher-1",
            "run_id": "RUN-A",
            "archive_evidence_ref": "state/final-cycle.json",
            "final_cycle_id": "final-cycle-1",
            "runtime_revision": 7,
            "occurred_at": "2026-10-06T00:00:00Z",
        }
    operation_request = write_json(tmp_path / f"{operation}.json", operation_value)
    sealed = tmp_path / "supervisor.sealed"
    sealed.write_text("sealed-supervisor", encoding="ascii")
    request = {
        "schema_version": "slk.supervisor-admin/v1",
        "run_id": "RUN-A",
        "supervisor_role_instance_id": "RUN-A-supervisor-001",
        "expected_runtime_revision": 7,
        "sealed_credential_path": str(sealed),
        "state_command": ["slk-state"],
        "operation": operation,
        "operation_request_path": str(operation_request),
        "operation_request_sha256": hashlib.sha256(operation_request.read_bytes()).hexdigest(),
        "result_path": str(tmp_path / f"{operation}-result.json"),
    }
    if operation == "close-overwatcher":
        overwatcher = tmp_path / "overwatcher.sealed"
        overwatcher.write_text("sealed-overwatcher", encoding="ascii")
        request["sealed_overwatcher_credential_path"] = str(overwatcher)
    return write_json(tmp_path / f"{operation}-admin.json", request)


@pytest.mark.parametrize(
    ("operation", "state_operation", "state_status", "uses_overwatcher"),
    [
        ("close-overwatcher", "close-overwatcher", "overwatcher_closed", True),
        ("close-run", "write", "recorded", False),
        ("close-role", "close-role", "closed", False),
    ],
)
def test_closed_admin_consumer_executes_only_exact_terminal_operations(
    tmp_path, monkeypatch, operation, state_operation, state_status, uses_overwatcher,
):
    request = terminal_request_fixture(tmp_path, operation)
    value = json.loads(request.read_text())
    supervisor_secret = "slk_" + "s" * 64
    overwatcher_secret = "slk_" + "o" * 64
    calls = []

    monkeypatch.setattr(
        admin.wc,
        "unprotect_dpapi_hex",
        lambda path: overwatcher_secret
        if Path(path) == Path(value.get("sealed_overwatcher_credential_path", "missing"))
        else supervisor_secret,
    )

    def run(command, arguments, credential=None, credential_scope="role"):
        calls.append((arguments[0], credential, credential_scope))
        if arguments[0] == "authenticate-role":
            return {
                "status": "authenticated",
                "run_id": "RUN-A",
                "role": "supervisor",
                "role_instance_id": "RUN-A-supervisor-001",
                "runtime_revision": 7,
            }
        return {"status": state_status, "run_id": "RUN-A"}

    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    result = admin.execute_sealed_supervisor_admin(
        request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())

    assert calls == [
        ("authenticate-role", supervisor_secret, "role"),
        (
            state_operation,
            overwatcher_secret if uses_overwatcher else supervisor_secret,
            "overwatcher" if uses_overwatcher else "role",
        ),
    ]
    assert result["operation"] == operation
    assert supervisor_secret not in json.dumps(result)
    assert overwatcher_secret not in json.dumps(result)


def test_close_run_admin_rejects_nonterminal_write_before_credential_access(tmp_path, monkeypatch):
    request = terminal_request_fixture(tmp_path, "close-run")
    value = json.loads(request.read_text())
    operation_path = Path(value["operation_request_path"])
    operation_value = json.loads(operation_path.read_text())
    operation_value["event_type"] = "D2_PASSED"
    operation_path.write_text(json.dumps(operation_value), encoding="utf-8")
    value["operation_request_sha256"] = hashlib.sha256(operation_path.read_bytes()).hexdigest()
    request.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(
        admin.wc, "unprotect_dpapi_hex",
        lambda _path: pytest.fail("invalid terminal operation must fail before credential access"),
    )

    with pytest.raises(ValueError, match="RUN_CLOSED"):
        admin.execute_sealed_supervisor_admin(
            request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())


def test_terminal_admin_preserves_safe_state_rejection_details(tmp_path, monkeypatch):
    request = terminal_request_fixture(tmp_path, "close-run")
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _path: "slk_" + "s" * 64)

    def run(command, arguments, credential=None):
        if arguments[0] == "authenticate-role":
            return {
                "status": "authenticated",
                "run_id": "RUN-A",
                "role": "supervisor",
                "role_instance_id": "RUN-A-supervisor-001",
                "runtime_revision": 7,
            }
        return {
            "error_code": "SLK_STATE_TERMINAL_ORDER_INVALID",
            "message": "final cycle is missing",
            "_slk_command": {
                "process_exit": 1,
                "json_parse": "PARSED_STDERR",
                "business_status": None,
            },
        }

    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    with pytest.raises(
        ValueError,
        match="SLK_STATE_TERMINAL_ORDER_INVALID: final cycle is missing",
    ):
        admin.execute_sealed_supervisor_admin(
            request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())


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


@pytest.mark.parametrize("operation", ["pause-run", "resume-run"])
def test_lifecycle_admin_uses_bound_host_and_does_not_save_pending_result(tmp_path, monkeypatch, operation):
    from test_role_host import prepared_host
    from slk_transport.role_host import RoleHost
    host, source, _ = prepared_host(tmp_path)
    binding = write_json(tmp_path / "binding.json", host.binding)
    request = request_fixture(tmp_path, operation)
    raw = json.loads(request.read_text())
    raw["state_command"] = host.state
    raw["sealed_credential_path"] = host.credential_path("supervisor")
    op = write_json(Path(raw["operation_request_path"]), {"run_id": "RUN-A", "role_instance_id": "RUN-A-supervisor-001",
        "binding_path": str(binding), "binding_sha256": hashlib.sha256(binding.read_bytes()).hexdigest()})
    raw["operation_request_sha256"] = hashlib.sha256(op.read_bytes()).hexdigest()
    request.write_text(json.dumps(raw))
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _path: "slk_" + "a" * 64)
    monkeypatch.setattr(admin.wc, "_run_json_command", lambda *_a, **_k: {"status": "authenticated", "run_id": "RUN-A",
        "role": "supervisor", "role_instance_id": "RUN-A-supervisor-001", "runtime_revision": 7})
    monkeypatch.setattr(RoleHost, "run_lifecycle", lambda _self, *args, **kwargs: {"run_id": "RUN-A", "status": "pause_requested" if operation == "pause-run" else "resumed"})
    result = admin.execute_sealed_supervisor_admin(request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert result["status"] == ("SUPERVISOR_ADMIN_PENDING" if operation == "pause-run" else "SUPERVISOR_ADMIN_COMPLETED")
    assert Path(raw["result_path"]).exists() == (operation != "pause-run")


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


def test_close_pair_suffix_retries_only_its_own_recorded_close_and_caches_final_success(tmp_path, monkeypatch):
    from slk_transport import role_host
    request = terminal_request_fixture(tmp_path, "close-run")
    raw = json.loads(request.read_text())
    operation_path = Path(raw["operation_request_path"])
    operation = json.loads(operation_path.read_text())
    binding = write_json(tmp_path / "close-host.json", {"run_id": "RUN-A", "temporal": {"original": True}})
    operation["details"] = {"close_binding_path": str(binding), "close_binding_sha256": hashlib.sha256(binding.read_bytes()).hexdigest()}
    write_json(operation_path, operation)
    raw["operation_request_sha256"] = hashlib.sha256(operation_path.read_bytes()).hexdigest()
    write_json(request, raw)
    revision, events, suffix_calls = [7], [], []
    class Host:
        lifecycle_retry_matches = staticmethod(lambda *_a: False)
        def __init__(self, value, _digest):
            self.binding, self.state = value, raw["state_command"]
        def endpoint(self, _role): return {"role_instance_id": raw["supervisor_role_instance_id"]}
        def credential_path(self, _role): return raw["sealed_credential_path"]
        def close_run_pair(self, _event, _root):
            suffix_calls.append(_event)
            if len(suffix_calls) == 1: raise ValueError("pair RPC unavailable")
    monkeypatch.setattr(role_host, "RoleHost", Host)
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda *_a: "secret")
    monkeypatch.setattr(admin.wc, "_default_load_current_projection", lambda *_a: {"events": events})
    def state(_command, arguments, **_k):
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "supervisor",
                "role_instance_id": raw["supervisor_role_instance_id"], "runtime_revision": revision[0]}
        assert arguments[0] == "write"
        if not events:
            events.append({**operation, "author_role_instance_id": operation["role_instance_id"], "details_json": json.dumps(operation["details"])})
            revision[0] += 1
        return {"status": "recorded", "run_id": "RUN-A"}
    monkeypatch.setattr(admin.wc, "_run_json_command", state)
    digest = hashlib.sha256(request.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="RPC"):
        admin.execute_sealed_supervisor_admin(request, request_sha256=digest)
    assert len(events) == 1 and not Path(raw["result_path"]).exists()
    events[0]["author_role_instance_id"] = "different-supervisor"
    with pytest.raises(ValueError, match="stale"):
        admin.execute_sealed_supervisor_admin(request, request_sha256=digest)
    assert len(suffix_calls) == 1
    events[0]["author_role_instance_id"] = operation["role_instance_id"]
    receipt = admin.execute_sealed_supervisor_admin(request, request_sha256=digest)
    assert admin.execute_sealed_supervisor_admin(request, request_sha256=digest) == receipt
    assert len(events) == 1 and len(suffix_calls) == 2
