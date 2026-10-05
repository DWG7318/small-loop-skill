from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any
import uuid

import pytest

pytest.importorskip("temporalio")

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from slk_temporal.contracts import StartSlkRequest
from slk_temporal.workflows import RunSlkWorkflow, StartSlkWorkflow
from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.contracts import Endpoint, Envelope, canonical_json_sha256
from slk_transport.dispatcher import dispatch_once
from slk_transport import worker_completion as wc

from .test_workflows import prepare_run, request_recovery, inspect_overwatcher, notify_supervisor


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


async def _idle(handle) -> dict[str, object]:
    for _ in range(100):
        try:
            snapshot = await handle.query(RunSlkWorkflow.status)
        except Exception:
            await asyncio.sleep(0.05)
            continue
        if snapshot["phase"] == "IDLE":
            return snapshot
        await asyncio.sleep(0.05)
    raise AssertionError("isolated SLK.Run did not reach IDLE")


async def _run_standard_client_drives_one_real_sdk_update_and_one_fake_ocrv_native_start(
    tmp_path: Path,
) -> None:
    address = os.environ.get("SLK_TEMPORAL_TEST_ADDRESS")
    if not address:
        pytest.skip("requires an existing shared Temporal address; never starts a test service")
    run_id = f"RUN-SLK441-BRIDGE-TEST-{uuid.uuid4().hex[:8]}"
    queue = f"slk441-bridge-test-{uuid.uuid4().hex[:10]}"
    message_id = str(uuid.uuid4())
    operation_id = wc._stable_id(message_id, "temporal-delivery")
    attempt_root = tmp_path / "attempts"
    attempt_root.mkdir()
    repository = tmp_path / "repository"
    repository.mkdir()
    runtime_root = tmp_path / "ocrv-runtime"
    runtime_root.mkdir()
    fake_ocrv = Path(__file__).parents[1] / "transport" / "fake_ocrv.py"
    endpoint = Endpoint.from_dict({
        "schema_version": "slk.transport-endpoint/v1", "run_id": run_id, "role": "checker",
        "role_instance_id": f"{run_id}-checker-001", "agent_runtime": "ocrv", "adapter": "ocrv-checker",
        "host_id": "local", "endpoint_version": 2, "state": "active",
        "address": {"command": [sys.executable, str(fake_ocrv), "normal"],
                    "runtime_root": str(runtime_root), "timeout_seconds": 5},
    })
    payload = {"repository": str(repository), "candidate": {"kind": "workspace"},
               "cell_goal": "Verify the isolated Temporal bridge.",
               "d1_criteria": ["The fake OCRV native receipt binds this isolated Run."],
               "evidence_files": []}
    envelope = Envelope.from_dict({
        "schema_version": "slk.transport-envelope/v1", "message_id": message_id, "token_sequence": 2,
        "run_id": run_id, "go_id": "GO-001", "cell_id": "CELL-001", "sender_role": "worker",
        "sender_role_instance_id": f"{run_id}-worker-001", "receiver_role": "checker",
        "receiver_role_instance_id": endpoint.role_instance_id, "receiver_endpoint_version": 2,
        "payload_type": "CANDIDATE_READY", "payload_sha256": canonical_json_sha256(payload), "payload": payload,
    })
    native_calls = 0

    @activity.defn(name="slk.deliver_message")
    async def deliver_message(value: dict[str, Any]) -> dict[str, str]:
        nonlocal native_calls
        assert value == {"operation_id": operation_id, "run_id": run_id, "cell_id": "CELL-001", "attempt": 1,
                         "message_id": message_id, "sender_role_instance_id": envelope.sender_role_instance_id,
                         "receiver_role_instance_id": envelope.receiver_role_instance_id,
                         "payload_sha256": envelope.payload_sha256, "source_runtime_revision": 7}
        native_calls += 1
        result = dispatch_once(asdict(endpoint), asdict(envelope), attempt_root,
                               adapters={"ocrv-checker": OcrvAdapter()})
        receipt = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return {"status": "DELIVERED", "operation_id": operation_id,
                "receipt_sha256": hashlib.sha256(receipt.encode()).hexdigest()}

    start = {"run_id": run_id, "method_version": "4.4.1", "runtime_revision": 7, "task_queue": queue,
             "ack_timeout_seconds": 120, "startup_idempotency_key": f"start-{run_id}-v7",
             "roles": [{"role": role.upper(), "role_instance_id": f"{run_id}-{role}-001",
                        "endpoint_ref": f"endpoint-{role}-v1"}
                       for role in ("supervisor", "checker", "worker", "overwatcher")]}
    client = await Client.connect(address)
    async with Worker(client, task_queue=queue, workflows=[StartSlkWorkflow, RunSlkWorkflow],
                      activities=[prepare_run, deliver_message, request_recovery,
                                  inspect_overwatcher, notify_supervisor]):
        parent = await client.start_workflow(StartSlkWorkflow.run, start, id=f"slk-start-{run_id}", task_queue=queue)
        child = client.get_workflow_handle(f"slk-run-{run_id}")
        await _idle(child)
        parent_description, child_description = await asyncio.gather(parent.describe(), child.describe())
        identity = {"schema_version": "slk.temporal-workflow-identity/v1", "run_id": run_id,
                    "address": address, "task_queue": queue, "start_workflow_id": parent_description.id,
                    "start_run_id": parent_description.run_id, "run_workflow_id": child_description.id,
                    "run_run_id": child_description.run_id,
                    "startup_fingerprint": StartSlkRequest.from_dict(start).startup_fingerprint}
        identity_path = _write(tmp_path / "identity.json", identity)
        binding = {"client_command": [sys.executable, "-m", "slk_temporal.delivery_client"],
                   "workflow_identity_path": str(identity_path),
                   "workflow_identity_sha256": hashlib.sha256(identity_path.read_bytes()).hexdigest(),
                   "attempt_root": str(attempt_root)}
        native = await asyncio.to_thread(wc.start_temporal_delivery, binding, tmp_path / "evidence",
                                         asdict(endpoint), asdict(envelope), attempt=1,
                                         source_runtime_revision=7)

        started = wc._read_object(native / "started.json", "isolated fake OCRV start")
        assert started["schema_version"] == "slk.native-start/v2"
        assert started["native_task"]["kind"] == "ocrv-review"
        assert native_calls == 1
        snapshot = await _idle(child)
        assert snapshot["last_completed_operation_id"] == operation_id
        assert await child.execute_update(RunSlkWorkflow.close_run, "ISOLATED_TEST_CLOSED") == "TERMINAL"
        assert (await parent.result())["phase"] == "TERMINAL"


def test_standard_client_drives_one_real_sdk_update_and_one_fake_ocrv_native_start(
    tmp_path: Path,
) -> None:
    asyncio.run(_run_standard_client_drives_one_real_sdk_update_and_one_fake_ocrv_native_start(tmp_path))
