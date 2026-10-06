"""Start one deterministic SLK Temporal workflow pair against an existing service."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from .contracts import StartSlkRequest
from .workflows import StartSlkWorkflow


async def start(
    address: str, request_path: Path, standard_config_root: Path | None = None,
) -> dict[str, Any]:
    request = StartSlkRequest.from_dict(json.loads(request_path.read_text(encoding="utf-8")))
    client = await Client.connect(address)
    if standard_config_root is not None:
        from . import standard_adapter

        standard_adapter.configure(standard_config_root)
        standard_adapter.bootstrap_run(request.to_dict())
    workflow_id = f"slk-start-{request.run_id}"
    handle = await client.start_workflow(
        StartSlkWorkflow.run,
        request.to_dict(),
        id=workflow_id,
        task_queue=request.task_queue,
        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
    )
    async def pair_identity() -> dict[str, Any]:
        while True:
            status = await handle.query(StartSlkWorkflow.status)
            if status.get("phase") in {"PAIR_CREATED", "RUNNING"}:
                child = client.get_workflow_handle(f"slk-run-{request.run_id}")
                parent_description, child_description = await asyncio.gather(
                    handle.describe(), child.describe()
                )
                return {
                    "schema_version": "slk.temporal-workflow-identity/v1",
                    "run_id": request.run_id,
                    "address": address,
                    "task_queue": request.task_queue,
                    "start_workflow_id": parent_description.id,
                    "start_run_id": parent_description.run_id,
                    "run_workflow_id": child_description.id,
                    "run_run_id": child_description.run_id,
                    "startup_fingerprint": request.startup_fingerprint,
                }
            await asyncio.sleep(0.1)

    identity = await asyncio.wait_for(pair_identity(), timeout=30)
    if identity.get("startup_fingerprint") != request.startup_fingerprint:
        raise RuntimeError("existing startup workflow has a different immutable request")
    return identity


def _write_identity(path: Path, value: dict[str, Any]) -> None:
    encoded = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if not path.is_absolute():
        raise ValueError("workflow identity output must be absolute")
    if path.exists() and path.read_bytes() != encoded:
        raise ValueError("workflow identity output already contains different bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="localhost:7233")
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--standard-config-root", type=Path)
    parser.add_argument("--identity-out", required=True, type=Path)
    args = parser.parse_args()
    identity = asyncio.run(start(
        args.address, args.request.resolve(),
        args.standard_config_root.resolve() if args.standard_config_root else None,
    ))
    output = args.identity_out.resolve()
    _write_identity(output, identity)
    print(json.dumps({"status": "PAIR_CREATED", "identity_path": str(output),
                      "identity_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                      **identity}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
