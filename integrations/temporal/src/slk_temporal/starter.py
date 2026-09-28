"""Start one deterministic SLK Temporal workflow pair against an existing service."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from .contracts import StartSlkRequest
from .workflows import StartSlkWorkflow


async def start(address: str, request_path: Path) -> dict[str, Any]:
    request = StartSlkRequest.from_dict(json.loads(request_path.read_text(encoding="utf-8")))
    client = await Client.connect(address)
    workflow_id = f"slk-start-{request.run_id}"
    handle = await client.start_workflow(
        StartSlkWorkflow.run,
        request.to_dict(),
        id=workflow_id,
        task_queue=request.task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    identity = await handle.query(StartSlkWorkflow.status)
    if identity.get("startup_fingerprint") != request.startup_fingerprint:
        raise RuntimeError("existing startup workflow has a different immutable request")
    return {
        "status": "STARTED_OR_ALREADY_RUNNING",
        "workflow_id": workflow_id,
        "run_workflow_id": f"slk-run-{request.run_id}",
        "startup_fingerprint": request.startup_fingerprint,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="localhost:7233")
    parser.add_argument("--request", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(start(args.address, args.request)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
