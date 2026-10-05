from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import pytest

temporalio = pytest.importorskip("temporalio")

from temporalio import activity
from temporalio.client import Client, WorkflowUpdateFailedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from slk_temporal.workflows import RunSlkWorkflow, StartSlkWorkflow

from .test_contracts import (
    ack_value,
    delivery_value,
    overwatcher_exit_value,
    runtime_guard_resolution_value,
    start_value,
)


TEST_TASK_QUEUE = "slk441-isolated-" + uuid.uuid4().hex[:12]

CALLS: dict[str, list[dict[str, Any]]] = {
    "prepare": [],
    "deliver": [],
    "recover": [],
    "inspect_overwatcher": [],
    "notify_supervisor": [],
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


@activity.defn(name="slk.inspect_overwatcher")
async def inspect_overwatcher(value: dict[str, Any]) -> dict[str, Any]:
    CALLS["inspect_overwatcher"].append(value)
    return {
        "status": "CLEAR",
        "run_id": value["run_id"],
        "overwatcher_role_instance_id": value["overwatcher_role_instance_id"],
        "audit_cycle": value["audit_cycle"],
        "evidence_sha256": "f" * 64,
        "receipt_sha256": "a" * 64,
    }


@activity.defn(name="slk.notify_supervisor")
async def notify_supervisor(value: dict[str, Any]) -> dict[str, Any]:
    CALLS["notify_supervisor"].append(value)
    from .test_contracts import notification_value
    return notification_value(value["event_id"], value["run_id"])


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


def _unique_start(*, label: str) -> dict[str, Any]:
    value = start_value()
    run_id = f"RUN-{label}-{uuid.uuid4().hex[:8]}"
    value["run_id"] = run_id
    value["task_queue"] = TEST_TASK_QUEUE
    value["method_version"] = "4.4.2"
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
            task_queue=TEST_TASK_QUEUE,
            workflows=[StartSlkWorkflow, RunSlkWorkflow],
            activities=[prepare_run, deliver_message, request_recovery, inspect_overwatcher, notify_supervisor],
        ):
            parent = await env.client.start_workflow(
                StartSlkWorkflow.run,
                start,
                id=f"slk-start-{run_id}",
                task_queue=TEST_TASK_QUEUE,
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
async def test_ack_timeout_requests_exact_recovery_then_matching_ack_stops_it(
    tmp_path: Path,
) -> None:
    start = _unique_start(label="ACK-TIMEOUT")
    start["ack_timeout_seconds"] = 2
    delivery = delivery_value()
    delivery["run_id"] = start["run_id"]

    async with await _environment(tmp_path) as env:
        async with Worker(
            env.client,
            task_queue=TEST_TASK_QUEUE,
            workflows=[StartSlkWorkflow, RunSlkWorkflow],
            activities=[prepare_run, deliver_message, request_recovery, inspect_overwatcher, notify_supervisor],
        ):
            parent = await env.client.start_workflow(
                StartSlkWorkflow.run,
                start,
                id=f"slk-start-{start['run_id']}",
                task_queue=TEST_TASK_QUEUE,
            )
            child = env.client.get_workflow_handle(f"slk-run-{start['run_id']}")
            await _wait_for_phase(child, env, "IDLE")
            await child.execute_update(RunSlkWorkflow.request_delivery, delivery)
            await env.sleep(3)
            await _wait_for_phase(child, env, "RECOVERY_REQUIRED")
            assert len(CALLS["recover"]) == 1
            assert CALLS["recover"][0]["recovery_target_role_instance_id"] == "worker-a"

            ack = ack_value()
            ack["operation_id"] = delivery["operation_id"]
            await child.execute_update(RunSlkWorkflow.native_started, ack)
            await _wait_for_phase(child, env, "IDLE")
            await env.sleep(3)
            assert len(CALLS["recover"]) == 1
            await child.execute_update(RunSlkWorkflow.close_run, "RUN_CLOSED")
            assert (await parent.result())["phase"] == "TERMINAL"


@pytest.mark.asyncio
async def test_member_residency_over_thirty_minutes_notifies_supervisor_once(tmp_path: Path) -> None:
    start = _unique_start(label="MEMBER-TIMER")
    delivery = delivery_value()
    delivery["run_id"] = start["run_id"]
    async with await _environment(tmp_path) as env:
        async with Worker(
            env.client,
            task_queue=TEST_TASK_QUEUE,
            workflows=[StartSlkWorkflow, RunSlkWorkflow],
            activities=[prepare_run, deliver_message, request_recovery, inspect_overwatcher, notify_supervisor],
        ):
            parent = await env.client.start_workflow(
                StartSlkWorkflow.run, start, id=f"slk-start-{start['run_id']}", task_queue=TEST_TASK_QUEUE
            )
            child = env.client.get_workflow_handle(f"slk-run-{start['run_id']}")
            await _wait_for_phase(child, env, "IDLE")
            await child.execute_update(RunSlkWorkflow.request_delivery, delivery)
            ack = ack_value()
            ack["operation_id"] = delivery["operation_id"]
            await child.execute_update(RunSlkWorkflow.native_started, ack)
            await _wait_for_phase(child, env, "IDLE")
            await env.sleep(1801)
            assert [item["kind"] for item in CALLS["notify_supervisor"]].count("MEMBER_RESIDENCY_EXCEEDED") == 1
            notice = next(item for item in CALLS["notify_supervisor"] if item["kind"] == "MEMBER_RESIDENCY_EXCEEDED")
            assert notice["responsible_role_instance_id"] == "checker-a"
            await env.sleep(1801)
            assert [item["kind"] for item in CALLS["notify_supervisor"]].count("MEMBER_RESIDENCY_EXCEEDED") == 1
            await child.execute_update(RunSlkWorkflow.close_run, "RUN_CLOSED")
            await parent.result()


@pytest.mark.asyncio
async def test_temporal_independently_checks_overwatcher_every_twenty_minutes(tmp_path: Path) -> None:
    start = _unique_start(label="OW-AUDIT")
    async with await _environment(tmp_path) as env:
        async with Worker(
            env.client,
            task_queue=TEST_TASK_QUEUE,
            workflows=[StartSlkWorkflow, RunSlkWorkflow],
            activities=[prepare_run, deliver_message, request_recovery, inspect_overwatcher, notify_supervisor],
        ):
            parent = await env.client.start_workflow(
                StartSlkWorkflow.run, start, id=f"slk-start-{start['run_id']}", task_queue=TEST_TASK_QUEUE
            )
            child = env.client.get_workflow_handle(f"slk-run-{start['run_id']}")
            await _wait_for_phase(child, env, "IDLE")
            await env.sleep(1201)
            assert len(CALLS["inspect_overwatcher"]) == 1
            assert CALLS["inspect_overwatcher"][0]["overwatcher_role_instance_id"] == "overwatcher-a"
            await env.sleep(1201)
            assert len(CALLS["inspect_overwatcher"]) == 2
            await child.execute_update(RunSlkWorkflow.close_run, "RUN_CLOSED")
            await parent.result()


@pytest.mark.asyncio
async def test_overwatcher_exit_blocks_next_delivery_until_exact_supervisor_repair(
    tmp_path: Path,
) -> None:
    start = _unique_start(label="OW-EXIT")
    run_id = start["run_id"]
    exit_notice = overwatcher_exit_value()
    exit_notice["run_id"] = run_id
    resolution = runtime_guard_resolution_value()
    resolution["run_id"] = run_id
    delivery = delivery_value()
    delivery["run_id"] = run_id
    async with await _environment(tmp_path) as env:
        async with Worker(
            env.client,
            task_queue=TEST_TASK_QUEUE,
            workflows=[StartSlkWorkflow, RunSlkWorkflow],
            activities=[
                prepare_run,
                deliver_message,
                request_recovery,
                inspect_overwatcher,
                notify_supervisor,
            ],
        ):
            parent = await env.client.start_workflow(
                StartSlkWorkflow.run,
                start,
                id=f"slk-start-{run_id}",
                task_queue=TEST_TASK_QUEUE,
            )
            child = env.client.get_workflow_handle(f"slk-run-{run_id}")
            await _wait_for_phase(child, env, "IDLE")

            assert await child.execute_update(
                RunSlkWorkflow.overwatcher_exited, exit_notice
            ) == "SUPERVISOR_CONFIRMATION_REQUIRED"
            snapshot = await child.query(RunSlkWorkflow.status)
            assert snapshot["runtime_guard_blocker"]["event_id"] == "overwatcher-exit-a"
            assert CALLS["notify_supervisor"][-1]["kind"] == (
                "OVERWATCHER_EXIT_REQUIRES_SUPERVISOR_CONFIRMATION"
            )
            with pytest.raises(WorkflowUpdateFailedError) as rejected:
                await child.execute_update(RunSlkWorkflow.request_delivery, delivery)
            assert "runtime guard" in str(rejected.value.__cause__)
            assert (await child.query(RunSlkWorkflow.status))["runtime_guard_blocker"] is not None

            wrong_authority = dict(resolution)
            wrong_authority["supervisor_role_instance_id"] = "checker-a"
            with pytest.raises(WorkflowUpdateFailedError) as rejected:
                await child.execute_update(
                    RunSlkWorkflow.resolve_runtime_guard, wrong_authority
                )
            assert "frozen authority" in str(rejected.value.__cause__)
            assert await child.execute_update(
                RunSlkWorkflow.resolve_runtime_guard, resolution
            ) == "RUNTIME_GUARD_REPAIRED"
            assert await child.execute_update(
                RunSlkWorkflow.request_delivery, delivery
            ) == "DELIVERY_REQUESTED"
            ack = ack_value()
            ack["operation_id"] = delivery["operation_id"]
            await child.execute_update(RunSlkWorkflow.native_started, ack)
            await _wait_for_phase(child, env, "IDLE")
            await child.execute_update(RunSlkWorkflow.close_run, "RUN_CLOSED")
            await parent.result()
