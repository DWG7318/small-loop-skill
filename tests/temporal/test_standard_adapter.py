from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

pytest.importorskip("temporalio")

from slk_temporal import standard_adapter


RUN_ID = "RUN-STANDARD-A"


def test_standard_adapter_keeps_the_temporal_venv_dependency_closed() -> None:
    source = Path(standard_adapter.__file__).read_text(encoding="utf-8")
    assert "from slk_transport" not in source
    assert "import slk_transport" not in source


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def config_root(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "standard-config"
    root.mkdir()
    attempts = tmp_path / "attempts"
    notices = tmp_path / "notices"
    attempts.mkdir()
    notices.mkdir()
    executable = Path(sys.executable).resolve()
    admission = write_json(tmp_path / "admission.json", {"run_id": RUN_ID})
    supervisor = write_json(tmp_path / "supervisor.json", {"run_id": RUN_ID})
    role_host = write_json(tmp_path / "role-host.json", {"run_id": RUN_ID})
    started = write_json(tmp_path / "ow" / "started.json", {"run_id": RUN_ID})
    state_config = write_json(tmp_path / "state-config.json", {"schema_version": "slk.config/v1"})
    config = {
        "schema_version": "slk.temporal-standard-adapter/v1",
        "method_version": "4.4.2",
        "run_id": RUN_ID,
        "transport_command": [str(executable), "-m", "slk_transport.cli"],
        "query_command": [str(executable), "-m", "slk_bi_query"],
        "state_config_path": str(state_config.resolve()),
        "admission_kind": "PRODUCT",
        "admission_path": str(admission.resolve()),
        "attempt_root": str(attempts.resolve()),
        "notification_attempt_root": str(notices.resolve()),
        "supervisor_endpoint_path": str(supervisor.resolve()),
        "role_host_binding": {
            "path": str(role_host.resolve()),
            "sha256": hashlib.sha256(role_host.read_bytes()).hexdigest(),
        },
        "overwatcher_activity": {
            "endpoint_ref": "ow-endpoint-a",
            "role_instance_id": "ow-a",
            "started_path": str(started.resolve()),
            "completed_path": None,
            "failed_path": None,
        },
    }
    write_json(root / f"{RUN_ID}.bootstrap.json", {
        "schema_version": "slk.temporal-standard-bootstrap/v1",
        "method_version": "4.4.2",
        "run_id": RUN_ID,
        "query_command": [str(executable), "-m", "slk_bi_query"],
        "state_config_path": str(state_config.resolve()),
    })
    write_json(root / f"{RUN_ID}.json", config)
    return root, config


def test_standard_bootstrap_needs_only_live_central_registry(tmp_path, monkeypatch):
    root, config = config_root(tmp_path)
    Path(config["role_host_binding"]["path"]).unlink()
    Path(config["overwatcher_activity"]["started_path"]).unlink()
    (root / f"{RUN_ID}.json").unlink()
    standard_adapter.configure(root)
    request = {
        "run_id": RUN_ID, "method_version": "4.4.2", "runtime_revision": 9,
        "task_queue": "slk-local", "ack_timeout_seconds": 30,
        "startup_idempotency_key": "start-a",
        "roles": [
            {"role": role, "role_instance_id": f"{role.lower()}-a", "endpoint_ref": f"{role.lower()}-endpoint"}
            for role in ("SUPERVISOR", "CHECKER", "WORKER", "OVERWATCHER")
        ],
    }
    monkeypatch.setattr(standard_adapter, "_run_json", lambda *_args, **_kwargs: {
        "summary": {"run_id": RUN_ID},
        "runtime_snapshot": {"runtime_revision": 9, "method_version": "4.4.2"},
        "roles": [{"role": row["role"].lower(), "role_instance_id": row["role_instance_id"], "lifecycle": "active"}
                  for row in request["roles"]],
    })

    receipt = standard_adapter.bootstrap_run(request)

    assert receipt["status"] == "BOOTSTRAP_READY"
    assert receipt["run_id"] == RUN_ID


def test_standard_adapter_bootstrap_and_final_configs_match_published_schemas(tmp_path):
    root, config = config_root(tmp_path)
    contracts = Path(__file__).resolve().parents[2] / "docs" / "contracts"
    bootstrap = json.loads((root / f"{RUN_ID}.bootstrap.json").read_text(encoding="utf-8"))
    Draft202012Validator(
        json.loads((contracts / "slk-temporal-standard-bootstrap.schema.json").read_text(encoding="utf-8"))
    ).validate(bootstrap)
    Draft202012Validator(
        json.loads((contracts / "slk-temporal-standard-adapter.schema.json").read_text(encoding="utf-8"))
    ).validate(config)


def test_standard_adapter_prepares_from_new_run_admission_and_live_revision(tmp_path, monkeypatch):
    root, config = config_root(tmp_path)
    standard_adapter.configure(root)
    request = {
        "run_id": RUN_ID, "method_version": "4.4.2", "runtime_revision": 9,
        "task_queue": "slk-local", "ack_timeout_seconds": 30,
        "startup_idempotency_key": "start-a",
        "roles": [
            {"role": role, "role_instance_id": f"{role.lower()}-a", "endpoint_ref": f"{role.lower()}-endpoint"}
            for role in ("SUPERVISOR", "CHECKER", "WORKER", "OVERWATCHER")
        ],
    }
    calls: list[list[str]] = []

    def run(command, arguments, **_kwargs):
        calls.append([*command, *arguments])
        if "preflight-new-run" in arguments:
            return {"status": "READY", "run_id": RUN_ID, "plan_revision": 1}
        return {"summary": {"run_id": RUN_ID}, "runtime_snapshot": {"runtime_revision": 9}}

    monkeypatch.setattr(standard_adapter, "_run_json", run)
    result = asyncio.run(standard_adapter.prepare_run({
        "request": request, "startup_fingerprint": "a" * 64,
    }))

    assert result["status"] == "READY"
    assert result["runtime_revision"] == 9
    assert Path(config["admission_path"]).resolve().as_posix() in " ".join(calls[0]).replace("\\", "/")


def test_standard_adapter_uses_only_the_explicit_isolated_conformance_entry(tmp_path, monkeypatch):
    root, config = config_root(tmp_path)
    config["admission_kind"] = "ISOLATED_CONFORMANCE_SAMPLE"
    write_json(root / f"{RUN_ID}.json", config)
    standard_adapter.configure(root)
    calls: list[list[str]] = []

    def run(command, arguments, **_kwargs):
        calls.append([*command, *arguments])
        if "preflight-conformance-sample" in arguments:
            return {"status": "READY", "run_id": RUN_ID, "plan_revision": 1}
        return {"summary": {"run_id": RUN_ID}, "runtime_snapshot": {"runtime_revision": 9}}

    monkeypatch.setattr(standard_adapter, "_run_json", run)
    result = asyncio.run(standard_adapter.prepare_run({
        "request": {
            "run_id": RUN_ID, "method_version": "4.4.2", "runtime_revision": 9,
            "task_queue": "slk-local", "ack_timeout_seconds": 30,
            "startup_idempotency_key": "start-a",
            "roles": [
                {"role": role, "role_instance_id": f"{role.lower()}-a", "endpoint_ref": f"{role.lower()}-endpoint"}
                for role in ("SUPERVISOR", "CHECKER", "WORKER", "OVERWATCHER")
            ],
        },
        "startup_fingerprint": "a" * 64,
    }))

    assert result["status"] == "READY"
    assert any("preflight-conformance-sample" in call for call in calls)
    assert not any("preflight-new-run" in call for call in calls)


def test_standard_adapter_rejects_unknown_admission_kind(tmp_path):
    root, config = config_root(tmp_path)
    config["admission_kind"] = "AUTO"
    write_json(root / f"{RUN_ID}.json", config)
    standard_adapter.configure(root)

    with pytest.raises(ValueError, match="admission kind"):
        standard_adapter._load_config(RUN_ID)


def test_standard_adapter_delivers_exact_staged_message_with_current_role_host(tmp_path, monkeypatch):
    root, config = config_root(tmp_path)
    standard_adapter.configure(root)
    message_id = "11111111-1111-4111-8111-111111111111"
    operation_id = "22222222-2222-4222-8222-222222222222"
    attempt = Path(config["attempt_root"]) / RUN_ID / message_id
    payload_sha256 = "b" * 64
    write_json(attempt / "endpoint.json", {"run_id": RUN_ID, "role_instance_id": "worker-a"})
    write_json(attempt / "envelope.json", {
        "run_id": RUN_ID, "cell_id": "CELL-001", "message_id": message_id,
        "sender_role_instance_id": "checker-a", "receiver_role_instance_id": "worker-a",
        "payload_sha256": payload_sha256,
    })
    write_json(attempt / "started.json", {
        "schema_version": "slk.native-start/v2", "status": "STARTED", "run_id": RUN_ID,
        "cell_id": "CELL-001", "message_id": message_id, "request_sha256": payload_sha256,
    })
    seen: dict[str, object] = {}

    def run(command, arguments, **kwargs):
        if command == config["query_command"]:
            return {"summary": {"run_id": RUN_ID, "state": "active"}}
        seen.update(command=command, arguments=arguments, environment=kwargs["environment"])
        return {"status": "started", "run_id": RUN_ID, "message_id": message_id}

    monkeypatch.setattr(standard_adapter, "_run_json", run)
    result = asyncio.run(standard_adapter.deliver_message({
        "operation_id": operation_id, "run_id": RUN_ID, "cell_id": "CELL-001", "attempt": 1,
        "message_id": message_id, "sender_role_instance_id": "checker-a",
        "receiver_role_instance_id": "worker-a", "payload_sha256": payload_sha256,
        "source_runtime_revision": 9,
    }))

    assert result["status"] == "DELIVERED"
    assert seen["environment"]["SLK_TRANSPORT_ROLE_HOST"] == config["role_host_binding"]["path"]
    assert seen["environment"]["SLK_TRANSPORT_ROLE_HOST_SHA256"] == config["role_host_binding"]["sha256"]


def test_standard_adapter_preserves_failed_send_as_activity_error(tmp_path, monkeypatch):
    root, config = config_root(tmp_path)
    standard_adapter.configure(root)
    message_id = "11111111-1111-4111-8111-111111111111"
    attempt = Path(config["attempt_root"]) / RUN_ID / message_id
    write_json(attempt / "endpoint.json", {"run_id": RUN_ID, "role_instance_id": "worker-a"})
    write_json(attempt / "envelope.json", {
        "run_id": RUN_ID, "cell_id": "CELL-001", "message_id": message_id,
        "sender_role_instance_id": "checker-a", "receiver_role_instance_id": "worker-a",
        "payload_sha256": "b" * 64,
    })
    monkeypatch.setattr(
        standard_adapter,
        "_run_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("standard adapter command failed")
        ),
    )
    with pytest.raises(RuntimeError, match="standard adapter command failed"):
        asyncio.run(standard_adapter.deliver_message({
            "operation_id": "22222222-2222-4222-8222-222222222222",
            "run_id": RUN_ID, "cell_id": "CELL-001", "attempt": 1,
            "message_id": message_id, "sender_role_instance_id": "checker-a",
            "receiver_role_instance_id": "worker-a", "payload_sha256": "b" * 64,
            "source_runtime_revision": 9,
        }))


def test_paused_central_boundary_defers_same_operation_without_native_send(tmp_path, monkeypatch):
    root, config = config_root(tmp_path)
    standard_adapter.configure(root)
    message = "11111111-1111-4111-8111-111111111111"
    attempt = Path(config["attempt_root"]) / RUN_ID / message
    write_json(attempt / "endpoint.json", {"run_id": RUN_ID, "role_instance_id": "worker-a", "role": "worker"})
    write_json(attempt / "envelope.json", {"run_id": RUN_ID, "cell_id": "CELL-001", "message_id": message,
        "sender_role_instance_id": "checker-a", "receiver_role_instance_id": "worker-a", "payload_sha256": "b" * 64})
    monkeypatch.setattr(standard_adapter, "_query", lambda _config: {"summary": {"run_id": RUN_ID, "state": "paused"}})
    monkeypatch.setattr(standard_adapter, "_run_json", lambda *_a, **_k: pytest.fail("paused operation physically started"))
    result = asyncio.run(standard_adapter.deliver_message({"operation_id": "original-op", "run_id": RUN_ID,
        "cell_id": "CELL-001", "attempt": 1, "message_id": message, "sender_role_instance_id": "checker-a",
        "receiver_role_instance_id": "worker-a", "payload_sha256": "b" * 64, "source_runtime_revision": 9}))
    assert result["status"] == "PAUSED" and result["operation_id"] == "original-op"
    assert not (attempt / "started.json").exists() and not (attempt / "failed.json").exists()


def test_standard_adapter_inspects_ow_and_notifies_with_fresh_projection(tmp_path, monkeypatch):
    root, _config = config_root(tmp_path)
    standard_adapter.configure(root)
    calls: list[tuple[list[str], list[str]]] = []

    def run(command, arguments, **_kwargs):
        calls.append((command, arguments))
        if "inspect-native-activity" in arguments:
            return {"status": "ACTIVE", "run_id": RUN_ID}
        if "inspect-overwatcher-cadence" in arguments:
            return current_cadence()
        if arguments and arguments[0] == "run":
            return {"summary": {"run_id": RUN_ID}, "runtime_snapshot": {"runtime_revision": 9}}
        return {"status": "NOTIFIED", "event_id": "event-a",
                "supervisor_role_instance_id": "supervisor-a", "native_start": {},
                "receipt_sha256": "c" * 64}

    monkeypatch.setattr(standard_adapter, "_run_json", run)
    inspected = asyncio.run(standard_adapter.inspect_overwatcher({
        "run_id": RUN_ID, "overwatcher_role_instance_id": "ow-a",
        "endpoint_ref": "ow-endpoint-a", "audit_cycle": 2,
    }))
    notified = asyncio.run(standard_adapter.notify_supervisor({
        "event_id": "event-a", "kind": "MEMBER_RESIDENCY_EXCEEDED", "run_id": RUN_ID,
        "responsible_role_instance_id": "worker-a", "source_operation_id": "operation-a",
        "threshold_seconds": 1800,
    }))

    assert inspected["status"] == "CLEAR" and inspected["audit_cycle"] == 2
    assert notified["status"] == "NOTIFIED"
    assert any(arguments and arguments[0] == "run" for _command, arguments in calls)
    assert any("notify-supervisor" in arguments for _command, arguments in calls)


def test_standard_adapter_rejects_changed_role_host_hash(tmp_path):
    root, config = config_root(tmp_path)
    Path(config["role_host_binding"]["path"]).write_text("changed", encoding="utf-8")
    standard_adapter.configure(root)
    with pytest.raises(ValueError, match="role host"):
        standard_adapter._load_config(RUN_ID)


@pytest.mark.parametrize("cadence_status", ["LATE", "CONTINUITY_UNPROVEN", "CURRENT"])
def test_ow_native_active_is_not_a_substitute_for_real_cycle_cadence(tmp_path, monkeypatch, cadence_status):
    root, _config = config_root(tmp_path)
    standard_adapter.configure(root)
    calls = []
    def run(_command, arguments, **_kwargs):
        calls.append(arguments)
        if arguments[0] == "inspect-native-activity":
            return {"status": "ACTIVE", "run_id": RUN_ID}
        if arguments[0] == "inspect-overwatcher-cadence":
            return {**current_cadence(), "status": cadence_status}
        return {"summary": {"run_id": RUN_ID}, "runtime_snapshot": {"runtime_revision": 9}}
    monkeypatch.setattr(standard_adapter, "_run_json", run)
    result = asyncio.run(standard_adapter.inspect_overwatcher({
        "run_id": RUN_ID, "overwatcher_role_instance_id": "ow-a", "endpoint_ref": "ow-endpoint-a", "audit_cycle": 2,
    }))
    assert result["status"] == ("CLEAR" if cadence_status == "CURRENT" else "ANOMALY")
    assert any(args[0] == "inspect-overwatcher-cadence" for args in calls)


def current_cadence():
    return {"schema_version": "slk.overwatcher-cadence-inspection/v1", "status": "CURRENT",
            "run_id": RUN_ID, "overwatcher_role_instance_id": "ow-a", "latest_cycle_id": "cycle-real",
            "cadence_seconds": 600, "elapsed_seconds": 60}


@pytest.mark.parametrize("damage", ["no-cycle", "no-schema", "negative-age", "overdue", "old-cadence"])
def test_current_ow_label_without_real_fresh_cycle_cannot_clear_audit(tmp_path, monkeypatch, damage):
    root, _ = config_root(tmp_path)
    standard_adapter.configure(root)
    cadence = current_cadence()
    if damage == "no-cycle": cadence["latest_cycle_id"] = None
    if damage == "no-schema": cadence.pop("schema_version")
    if damage == "negative-age": cadence["elapsed_seconds"] = -1
    if damage == "overdue": cadence["elapsed_seconds"] = 601
    if damage == "old-cadence": cadence["cadence_seconds"] = 240
    def run(_command, args, **_kwargs):
        return cadence if args[0] == "inspect-overwatcher-cadence" else {"status": "ACTIVE"}
    monkeypatch.setattr(standard_adapter, "_run_json", run)
    result = asyncio.run(standard_adapter.inspect_overwatcher({"run_id": RUN_ID,
        "overwatcher_role_instance_id": "ow-a", "endpoint_ref": "ow-endpoint-a", "audit_cycle": 1}))
    assert result["status"] == "ANOMALY"


def test_standard_adapter_v2_binds_live_ow_attestation_and_passes_it_to_each_audit(
    tmp_path, monkeypatch,
):
    root, config = config_root(tmp_path)
    started = Path(config["overwatcher_activity"]["started_path"])
    started.write_text(json.dumps({"native": "start"}), encoding="utf-8")
    attestation = write_json(tmp_path / "ow" / "desktop-overwatcher-attestation.json", {
        "schema_version": "slk.desktop-overwatcher-attestation/v1",
        "method_version": "4.4.2",
        "attestation_id": "11111111-1111-4111-8111-111111111111",
        "run_id": RUN_ID,
        "role_instance_id": "ow-a",
        "endpoint_ref": "ow-endpoint-a",
        "thread_id": "thread-ow",
        "host_id": "local",
        "cwd": str(tmp_path.resolve()),
        "turn_id": "turn-ow",
        "platform_input_item_id": "item-ow-input",
        "platform_input_sha256": "a" * 64,
        "request_sha256": "b" * 64,
        "plugin_sha256": "c" * 64,
        "observed_at": "2026-10-06T00:00:00Z",
        "thread_status": "active",
        "turn_status": "inProgress",
        "native_task_id": "thread-ow:turn-ow:item-ow-input",
        "started_sha256": hashlib.sha256(started.read_bytes()).hexdigest(),
    })
    config["schema_version"] = "slk.temporal-standard-adapter/v2"
    config["overwatcher_activity"].update({
        "attestation_path": str(attestation.resolve()),
        "attestation_sha256": hashlib.sha256(attestation.read_bytes()).hexdigest(),
    })
    contracts = Path(__file__).resolve().parents[2] / "docs" / "contracts"
    Draft202012Validator(json.loads(
        (contracts / "slk-temporal-standard-adapter.schema.json").read_text(encoding="utf-8")
    )).validate(config)
    write_json(root / f"{RUN_ID}.json", config)
    standard_adapter.configure(root)
    calls = []

    def run(command, arguments, **_kwargs):
        calls.append(arguments)
        if "inspect-overwatcher-cadence" in arguments:
            return current_cadence()
        return {"status": "ACTIVE"}

    monkeypatch.setattr(standard_adapter, "_run_json", run)
    result = asyncio.run(standard_adapter.inspect_overwatcher({
        "run_id": RUN_ID,
        "overwatcher_role_instance_id": "ow-a",
        "endpoint_ref": "ow-endpoint-a",
        "audit_cycle": 1,
    }))

    assert result["status"] == "CLEAR"
    assert calls[0] == [
        "inspect-native-activity",
        "--started", str(started.resolve()),
        "--desktop-overwatcher-attestation", str(attestation.resolve()),
        "--desktop-overwatcher-attestation-sha256", hashlib.sha256(attestation.read_bytes()).hexdigest(),
    ]
    assert any(args[0] == "inspect-overwatcher-cadence" for args in calls)


def test_standard_adapter_v2_rejects_ow_attestation_for_another_binding(tmp_path):
    root, config = config_root(tmp_path)
    started = Path(config["overwatcher_activity"]["started_path"])
    attestation = write_json(tmp_path / "ow" / "desktop-overwatcher-attestation.json", {
        "schema_version": "slk.desktop-overwatcher-attestation/v1",
        "method_version": "4.4.2",
        "attestation_id": "11111111-1111-4111-8111-111111111111",
        "run_id": RUN_ID,
        "role_instance_id": "some-other-ow",
        "endpoint_ref": "ow-endpoint-a",
        "thread_id": "thread-ow",
        "host_id": "local",
        "cwd": str(tmp_path.resolve()),
        "turn_id": "turn-ow",
        "platform_input_item_id": "item-ow-input",
        "platform_input_sha256": "a" * 64,
        "request_sha256": "b" * 64,
        "plugin_sha256": "c" * 64,
        "observed_at": "2026-10-06T00:00:00Z",
        "thread_status": "active",
        "turn_status": "inProgress",
        "native_task_id": "thread-ow:turn-ow:item-ow-input",
        "started_sha256": hashlib.sha256(started.read_bytes()).hexdigest(),
    })
    config["schema_version"] = "slk.temporal-standard-adapter/v2"
    config["overwatcher_activity"].update({
        "attestation_path": str(attestation.resolve()),
        "attestation_sha256": hashlib.sha256(attestation.read_bytes()).hexdigest(),
    })
    write_json(root / f"{RUN_ID}.json", config)
    standard_adapter.configure(root)

    with pytest.raises(ValueError, match="Overwatcher attestation"):
        standard_adapter._load_config(RUN_ID)
