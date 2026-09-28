from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import pytest

temporalio = pytest.importorskip("temporalio")

from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from slk_temporal.workflows import RunSlkWorkflow, StartSlkWorkflow

from .test_contracts import ack_value, delivery_value, start_value


CALLS: dict[str, list[dict[str, Any]]] = {
    "prepare": [],
    "deliver": [],
    "recover": [],
}


@activity.defn(name="slk.prepare_run")
async def prepare_run(value: dict[str, Any]) -> dict[str, Any]:
    CALLS["prepare"].append(value)
    request = value["request"]
    return {
        "status": "READY",
        "run_id": request["run_id"],
        "runtime_revision": request["runtime_revision"],
        "startup_fingerprint": value["startup_fingerprint"],
        "receipt_sha256": "c" * 64,
    }


@activity.defn(name="slk.deliver_message")
async def deliver_message(value: dict[str, Any]) -> dict[str, Any]:
    CALLS["deliver"].append(value)
    return {
        "status": "DELIVERED",
        "operation_id": value["operation_id"],
        "receipt_sha256": "d" * 64,
    }


@activity.defn(name="slk.request_recovery")
async def request_recovery(value: dict[str, Any]) -> dict[str, Any]:
    CALLS["recover"].append(value)
    return {
        "status": "RECOVERY_REQUESTED",
        "operation_id": value["delivery"]["operation_id"],
        "receipt_sha256": "e" * 64,
    }


@pytest.fixture(autouse=True)
def clear_calls() -> None:
    for values in CALLS.values():
        values.clear()


async def _wait_for_phase(handle, env: WorkflowEnvironment, phase: str) -> dict[str, Any]:
    for _ in range(20):
        try:
            snapshot = await handle.query(RunSlkWorkflow.status)
        except Exception:
            await env.sleep(0.1)
            continue
        if snapshot["phase"] == phase:
            return snapshot
        await env.sleep(0.1)
    raise AssertionError(f"workflow did not reach {phase}")


async def _environment(tmp_path: Path) -> WorkflowEnvironment:
    address = os.environ.get("SLK_TEMPORAL_TEST_ADDRESS")
    if address:
        return WorkflowEnvironment.from_client(await Client.connect(address))
    destination = tmp_path / "temporal-test-server"
    destination.mkdir()
    return await WorkflowEnvironment.start_time_skipping(download_dest_dir=str(destination))


def _unique_start(*, label: str, overwatcher: bool = True) -> dict[str, Any]:
    value = start_value(overwatcher=overwatcher)
    run_id = f"RUN-{label}-{uuid.uuid4().hex[:8]}"
    value["run_id"] = run_id
    value["startup_idempotency_key"] = f"start-{run_id}-v7"
    return value


@pytest.mark.asyncio
async def test_start_template_starts_one_run_and_ack_closes_delivery(tmp_path: Path) -> None:
    start = _unique_start(label="ACK")
    run_id = start["run_id"]
    delivery = delivery_value()
    delivery["run_id"] = run_id
    async with await _environment(tmp_path) as env:
        async with Worker(
            env.client,
            task_queue="slk-local",
            workflows=[StartSlkWorkflow, RunSlkWorkflow],
            activities=[prepare_run, deliver_message, request_recovery],
        ):
            parent = await env.client.start_workflow(
                StartSlkWorkflow.run,
                start,
                id=f"slk-start-{run_id}",
                task_queue="slk-local",
            )
            child = env.client.get_workflow_handle(f"slk-run-{run_id}")
            await _wait_for_phase(child, env, "IDLE")

            assert await child.execute_update(
                RunSlkWorkflow.request_delivery, delivery
            ) == "DELIVERY_REQUESTED"
            await _wait_for_phase(child, env, "DELIVERY_REQUESTED")
            assert await child.execute_update(
                RunSlkWorkflow.native_started, ack_value()
            ) == "DELIVERY_ACKNOWLEDGED"
            snapshot = await _wait_for_phase(child, env, "IDLE")
            assert snapshot["last_completed_operation_id"] == delivery["operation_id"]
            assert await child.execute_update(RunSlkWorkflow.close_run, "RUN_CLOSED") == "TERMINAL"

            result = await parent.result()
            assert result["phase"] == "TERMINAL"
            assert len(CALLS["prepare"]) == 1
            assert len(CALLS["deliver"]) == 1
            assert CALLS["recover"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("with_overwatcher,expected_target", [(True, "overwatcher-a"), (False, "SENDER")])
async def test_ack_timeout_requests_exact_recovery_then_matching_ack_stops_it(
    tmp_path: Path, with_overwatcher: bool, expected_target: str
) -> None:
    start = _unique_start(label="OW" if with_overwatcher else "NOOW", overwatcher=with_overwatcher)
    start["ack_timeout_seconds"] = 2
    delivery = delivery_value()
    delivery["run_id"] = start["run_id"]

    async with await _environment(tmp_path) as env:
        async with Worker(
            env.client,
            task_queue="slk-local",
            workflows=[StartSlkWorkflow, RunSlkWorkflow],
            activities=[prepare_run, deliver_message, request_recovery],
        ):
            parent = await env.client.start_workflow(
                StartSlkWorkflow.run,
                start,
                id=f"slk-start-{start['run_id']}",
                task_queue="slk-local",
            )
            child = env.client.get_workflow_handle(f"slk-run-{start['run_id']}")
            await _wait_for_phase(child, env, "IDLE")
            await child.execute_update(RunSlkWorkflow.request_delivery, delivery)
            await env.sleep(3)
            await _wait_for_phase(child, env, "RECOVERY_REQUIRED")
            assert len(CALLS["recover"]) == 1
            assert CALLS["recover"][0]["recovery_target_role_instance_id"] == expected_target

            ack = ack_value()
            ack["operation_id"] = delivery["operation_id"]
            await child.execute_update(RunSlkWorkflow.native_started, ack)
            await _wait_for_phase(child, env, "IDLE")
            await env.sleep(3)
            assert len(CALLS["recover"]) == 1
            await child.execute_update(RunSlkWorkflow.close_run, "RUN_CLOSED")
            assert (await parent.result())["phase"] == "TERMINAL"
