from __future__ import annotations

import hashlib
import asyncio
import json
from pathlib import Path

import pytest

pytest.importorskip("temporalio")

from slk_temporal import delivery_client


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def identity() -> dict[str, str]:
    return {
        "schema_version": "slk.temporal-workflow-identity/v1",
        "run_id": "RUN-A",
        "address": "127.0.0.1:7233",
        "task_queue": "slk-test",
        "start_workflow_id": "slk-start-RUN-A",
        "start_run_id": "11111111-1111-4111-8111-111111111111",
        "run_workflow_id": "slk-run-RUN-A",
        "run_run_id": "22222222-2222-4222-8222-222222222222",
        "startup_fingerprint": "a" * 64,
    }


def delivery() -> dict[str, object]:
    return {
        "operation_id": "33333333-3333-4333-8333-333333333333",
        "run_id": "RUN-A",
        "cell_id": "CELL-001",
        "attempt": 1,
        "message_id": "44444444-4444-4444-8444-444444444444",
        "sender_role_instance_id": "worker-a",
        "receiver_role_instance_id": "checker-a",
        "payload_sha256": "b" * 64,
        "source_runtime_revision": 7,
    }


def test_cli_rejects_changed_identity_and_request_hashes_before_network(tmp_path: Path, monkeypatch) -> None:
    identity_path = write_json(tmp_path / "identity.json", identity())
    request_path = write_json(tmp_path / "request.json", delivery())
    monkeypatch.setattr(delivery_client, "submit", lambda **_kwargs: pytest.fail("network must not be reached"))

    with pytest.raises(ValueError, match="identity SHA-256"):
        delivery_client.run_update(
            operation="request-delivery", identity_path=identity_path, identity_sha256="0" * 64,
            request_path=request_path, request_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest())
    with pytest.raises(ValueError, match="request SHA-256"):
        delivery_client.run_update(
            operation="request-delivery", identity_path=identity_path,
            identity_sha256=hashlib.sha256(identity_path.read_bytes()).hexdigest(),
            request_path=request_path, request_sha256="0" * 64)


def test_client_result_must_bind_the_exact_existing_run_and_operation(tmp_path: Path, monkeypatch) -> None:
    identity_path = write_json(tmp_path / "identity.json", identity())
    request_path = write_json(tmp_path / "request.json", delivery())
    monkeypatch.setattr(delivery_client, "submit", lambda **_kwargs: {
        "schema_version": "slk.temporal-delivery-update-result/v1",
        "status": "DELIVERY_REQUESTED", "operation": "request_delivery",
        "run_id": "OTHER", "operation_id": delivery()["operation_id"],
        "message_id": delivery()["message_id"],
    })

    with pytest.raises(ValueError, match="result identity"):
        delivery_client.run_update(
            operation="request-delivery", identity_path=identity_path,
            identity_sha256=hashlib.sha256(identity_path.read_bytes()).hexdigest(),
            request_path=request_path, request_sha256=hashlib.sha256(request_path.read_bytes()).hexdigest())


def test_sdk_update_has_one_bounded_rpc_deadline(monkeypatch) -> None:
    async def never_returns(**_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(delivery_client, "RPC_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(delivery_client, "_submit_once", never_returns)

    with pytest.raises(TimeoutError):
        asyncio.run(delivery_client._submit(
            operation="request-delivery", identity=identity(), request=delivery()))
