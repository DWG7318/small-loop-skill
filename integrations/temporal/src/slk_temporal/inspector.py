"""Read one existing SLK Temporal workflow pair without starting a workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from temporalio.client import Client

from .workflows import StartSlkWorkflow


async def inspect_pair(*, address: str, run_id: str, task_queue: str,
                       start_workflow_id: str, start_run_id: str,
                       run_workflow_id: str, run_run_id: str,
                       startup_fingerprint: str) -> dict[str, Any]:
    client = await Client.connect(address)
    start = client.get_workflow_handle(start_workflow_id, run_id=start_run_id)
    run = client.get_workflow_handle(run_workflow_id, run_id=run_run_id)
    start_description, run_description = await asyncio.gather(start.describe(), run.describe())
    start_status = await start.query(StartSlkWorkflow.status)
    if (start_description.run_id != start_run_id or run_description.run_id != run_run_id
        or start_description.task_queue != task_queue or run_description.task_queue != task_queue
        or start_status.get("run_id") != run_id
        or start_status.get("child_workflow_id") != run_workflow_id
        or start_status.get("startup_fingerprint") != startup_fingerprint):
        raise RuntimeError("live Temporal workflow identity changed")
    return {"schema_version": "slk.temporal-workflow-identity/v1", "run_id": run_id,
            "address": address, "task_queue": task_queue,
            "start_workflow_id": start_workflow_id, "start_run_id": start_run_id,
            "run_workflow_id": run_workflow_id, "run_run_id": run_run_id,
            "startup_fingerprint": startup_fingerprint}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-queue", required=True)
    parser.add_argument("--start-workflow-id", required=True)
    parser.add_argument("--start-run-id", required=True)
    parser.add_argument("--run-workflow-id", required=True)
    parser.add_argument("--run-run-id", required=True)
    parser.add_argument("--startup-fingerprint", required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(inspect_pair(**vars(args))), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
