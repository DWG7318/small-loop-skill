"""A saved Overwatcher credential is consumed only for OW-owned state writes."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from slk_transport import overwatcher_admin as admin


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def request_fixture(tmp_path: Path, operation: str = "record-overwatch-cycle") -> Path:
    from test_worker_completion import completion_fixture, runtime_projection
    source, endpoint, _ = completion_fixture(tmp_path)
    projection = runtime_projection(token_owner=endpoint["role_instance_id"])
    projection["runtime_snapshot"]["method_version"] = "4.4.2"
    projection["roles"] = [{"role": "worker", "role_instance_id": endpoint["role_instance_id"]}]
    details = json.loads(projection["events"][0]["details_json"])
    details.update(start_evidence_sha256=hashlib.sha256((source / "started.json").read_bytes()).hexdigest(),
                   endpoint_sha256=hashlib.sha256((source / "endpoint.json").read_bytes()).hexdigest(),
                   envelope_sha256=hashlib.sha256((source / "envelope.json").read_bytes()).hexdigest())
    projection["events"][0]["details_json"] = json.dumps(details)
    write_json(tmp_path / "runtime.json", projection)
    now = datetime.now(timezone.utc)
    inspection = admin.wc.inspect_worker_completion(source, projection, observed_at=now.isoformat(), cadence_seconds=600)
    inspection_path = write_json(tmp_path / "inspection.json", inspection)
    operation_request = write_json(tmp_path / "operation.json", {
        "cycle_id": "cycle-1", "run_id": "RUN-A", "role_instance_id": "RUN-A-overwatcher-001",
        "go_id": "GO-001", "cell_id": "CELL-001", "attempt": 1,
        "runtime_revision": 7, "token_sequence": 14, "token_holder_role_instance_id": endpoint["role_instance_id"],
        "latest_message_id": inspection["source_message_id"], "cadence_seconds": 600,
        "started_at": (now - timedelta(seconds=1)).isoformat(),
        "completed_at": (now + timedelta(milliseconds=1)).isoformat(),
        "evidence_refs": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                          for p in (source / "started.json", inspection_path)],
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


@pytest.fixture(autouse=True)
def isolated_current_projection(tmp_path, monkeypatch):
    monkeypatch.setattr(admin.wc, "_default_load_current_projection",
                        lambda *_a, **_k: json.loads((tmp_path / "runtime.json").read_text()))


@pytest.mark.parametrize("damage", ["forged-status", "missing-start", "duplicate-inspection", "wrong-source",
                                    "old-clock", "instant-cycle", "future-cycle"])
def test_cycle_requires_real_recollected_worker_facts_before_state_write(tmp_path, monkeypatch, damage):
    request = request_fixture(tmp_path)
    raw = json.loads(request.read_text())
    path = Path(raw["operation_request_path"])
    cycle = json.loads(path.read_text())
    inspection_path = tmp_path / "inspection.json"
    inspection = json.loads(inspection_path.read_text())
    if damage == "forged-status":
        inspection["status"] = "IN_PROGRESS"
    elif damage == "wrong-source":
        inspection["source_message_id"] = "wrong-message"
    elif damage == "missing-start":
        cycle["evidence_refs"] = cycle["evidence_refs"][1:]
    elif damage == "duplicate-inspection":
        copy = write_json(tmp_path / "second-inspection.json", inspection)
        cycle["evidence_refs"].append({"path": str(copy), "sha256": hashlib.sha256(copy.read_bytes()).hexdigest()})
    elif damage == "old-clock":
        inspection["observed_at"] = "2026-09-23T00:00:00Z"
    elif damage == "instant-cycle":
        cycle["completed_at"] = cycle["started_at"]
    else:
        cycle["completed_at"] = "2099-01-01T00:00:00Z"
    write_json(inspection_path, inspection)
    for ref in cycle["evidence_refs"]:
        ref["sha256"] = hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest()
    write_json(path, cycle)
    raw["operation_request_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(request, raw)
    calls = []
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _: "synthetic")
    def run(_command, args, **_kwargs):
        calls.append(args[0])
        if args[0] != "authenticate-role": pytest.fail("unproved cycle reached OW write")
        return {"status": "authenticated", "run_id": "RUN-A", "role": "overwatcher",
                "role_instance_id": "RUN-A-overwatcher-001", "runtime_revision": 7}
    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    with pytest.raises(ValueError, match="OVERWATCHER_CYCLE"):
        admin.execute_sealed_overwatcher_admin(request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert calls == ["authenticate-role"]
    assert not Path(raw["result_path"]).exists()


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


def test_ow_consumer_preserves_safe_state_rejection_code_and_message(tmp_path, monkeypatch):
    request = request_fixture(tmp_path)
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda path: "slk_" + "c" * 64)

    def run(command, arguments, credential=None, credential_scope="role"):
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "overwatcher",
                    "role_instance_id": "RUN-A-overwatcher-001", "runtime_revision": 7}
        return {"status": "error", "code": "SLK_STATE_COMMAND_FAILED",
                "message": "cycle runtime revision is stale",
                "_slk_command": {"process_exit": 1, "json_parse": "PARSED_STDERR",
                                 "business_status": "error"}}

    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    with pytest.raises(ValueError, match="SLK_STATE_COMMAND_FAILED: cycle runtime revision is stale"):
        admin.execute_sealed_overwatcher_admin(
            request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())


def test_authenticated_ow_stale_snapshot_is_not_bad_credential_and_never_replayed(tmp_path, monkeypatch):
    request = request_fixture(tmp_path)
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _: "synthetic")
    calls = []
    def run(_command, args, **_kwargs):
        calls.append(args[0])
        return {"status": "authenticated", "run_id": "RUN-A", "role": "overwatcher",
                "role_instance_id": "RUN-A-overwatcher-001", "runtime_revision": 8}
    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    with pytest.raises(ValueError, match="OVERWATCHER_SNAPSHOT_STALE") as error:
        admin.execute_sealed_overwatcher_admin(request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert "new observation" in str(error.value)
    assert calls == ["authenticate-role"]
