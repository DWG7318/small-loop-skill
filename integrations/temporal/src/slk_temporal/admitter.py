"""Complete full new-Run admission for one already-created SLK workflow pair."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from temporalio.client import Client

from .delivery_client import _identity, _load_hashed
from .inspector import inspect_pair
from .workflows import RunSlkWorkflow


async def admit(identity: dict[str, str], identity_sha256: str) -> dict[str, Any]:
    await inspect_pair(**{
        field: value for field, value in identity.items() if field != "schema_version"
    })
    client = await Client.connect(identity["address"])
    handle = client.get_workflow_handle(
        identity["run_workflow_id"], run_id=identity["run_run_id"]
    )
    requested = await handle.execute_update(
        RunSlkWorkflow.request_admission,
        {"run_id": identity["run_id"],
         "startup_fingerprint": identity["startup_fingerprint"],
         "workflow_identity_sha256": identity_sha256},
    )

    async def wait_ready() -> dict[str, Any]:
        while True:
            status = await handle.query(RunSlkWorkflow.status)
            if status.get("phase") == "IDLE" and status.get("admitted") is True:
                return status
            if status.get("phase") == "ADMISSION_FAILED":
                raise RuntimeError(
                    f"full new-Run admission failed: {status.get('admission_failure')}"
                )
            await asyncio.sleep(0.1)

    snapshot = await asyncio.wait_for(wait_ready(), timeout=90)
    return {
        "schema_version": "slk.temporal-admission-result/v1",
        "status": "READY",
        "request_status": str(requested),
        "run_id": identity["run_id"],
        "startup_fingerprint": identity["startup_fingerprint"],
        "workflow_identity_sha256": identity_sha256,
        "admission_attempt": snapshot["admission_attempt"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--identity-sha256", required=True)
    args = parser.parse_args()
    identity_path = args.identity.resolve()
    value = _identity(_load_hashed(identity_path, args.identity_sha256, "identity"))
    result = asyncio.run(admit(value, args.identity_sha256))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
