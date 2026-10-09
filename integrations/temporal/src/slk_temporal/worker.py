"""Run the optional SLK Temporal templates with explicit adapter activities."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import hashlib
import json
import os
from pathlib import Path
from collections.abc import Awaitable, Callable
from typing import Any

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from .workflows import RunSlkWorkflow, StartSlkWorkflow


Adapter = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _bind_activity(target: Adapter, attribute: str, activity_name: str) -> Adapter:
    async def invoke(value: dict[str, Any]) -> dict[str, Any]:
        try:
            return await target(value)
        except RuntimeError as error:
            if not isinstance(getattr(error, "evidence", None), dict):
                raise
            from temporalio.exceptions import ApplicationError
            raise ApplicationError(str(error), error.evidence,
                                   type="SLK_STANDARD_COMMAND_FAILED", non_retryable=True) from error

    invoke.__name__ = attribute
    return activity.defn(name=activity_name)(invoke)


def _activities(module_name: str) -> list[Adapter]:
    module = importlib.import_module(module_name)
    result: list[Adapter] = []
    for attribute, name in (
        ("prepare_run", "slk.prepare_run"),
        ("deliver_message", "slk.deliver_message"),
        ("request_recovery", "slk.request_recovery"),
        ("inspect_overwatcher", "slk.inspect_overwatcher"),
        ("notify_supervisor", "slk.notify_supervisor"),
    ):
        implementation: Any = getattr(module, attribute, None)
        if implementation is None or not inspect.iscoroutinefunction(implementation):
            raise RuntimeError(f"adapter module must define async {attribute}(value)")
        result.append(_bind_activity(implementation, attribute, name))
    return result


def _selected_adapter(*, adapter_module: str | None, standard_config_root: Any | None) -> str:
    if (adapter_module is None) == (standard_config_root is None):
        raise ValueError("exactly one adapter module or standard config root is required")
    if standard_config_root is not None:
        from . import standard_adapter

        standard_adapter.configure(standard_config_root)
        return "slk_temporal.standard_adapter"
    return str(adapter_module)


def binding_metadata(address: str, task_queue: str, adapter_module: str) -> dict:
    from . import workflows, standard_adapter
    def source(module):
        path = Path(inspect.getfile(module)).resolve()
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return {"schema_version": "slk.temporal-worker-binding/v1", "pid": os.getpid(),
            "address": address, "task_queue": task_queue,
            "adapter_source": source(importlib.import_module(adapter_module)),
            "workflow_source": source(workflows),
            "standard_config_root": str(standard_adapter._CONFIG_ROOT) if adapter_module == "slk_temporal.standard_adapter" else None}


async def run(address: str, task_queue: str, adapter_module: str, ready_file: Path | None = None) -> None:
    client = await Client.connect(address)
    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[StartSlkWorkflow, RunSlkWorkflow],
        activities=_activities(adapter_module),
    ):
        if ready_file is not None:
            from .starter import _write_identity
            _write_identity(ready_file, binding_metadata(address, task_queue, adapter_module))
        await asyncio.Future()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="localhost:7233")
    parser.add_argument("--task-queue", required=True)
    adapter = parser.add_mutually_exclusive_group(required=True)
    adapter.add_argument("--adapter-module")
    adapter.add_argument("--standard-config-root")
    parser.add_argument("--inspect-binding", action="store_true")
    parser.add_argument("--ready-file", type=Path)
    args = parser.parse_args()
    module = _selected_adapter(
        adapter_module=args.adapter_module,
        standard_config_root=args.standard_config_root,
    )
    if args.inspect_binding:
        print(json.dumps(binding_metadata(args.address, args.task_queue, module), sort_keys=True))
    else:
        asyncio.run(run(args.address, args.task_queue, module, args.ready_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
