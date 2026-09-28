"""Run the optional SLK Temporal templates with explicit adapter activities."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from .workflows import RunSlkWorkflow, StartSlkWorkflow


Adapter = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _bind_activity(target: Adapter, attribute: str, activity_name: str) -> Adapter:
    async def invoke(value: dict[str, Any]) -> dict[str, Any]:
        return await target(value)

    invoke.__name__ = attribute
    return activity.defn(name=activity_name)(invoke)


def _activities(module_name: str) -> list[Adapter]:
    module = importlib.import_module(module_name)
    result: list[Adapter] = []
    for attribute, name in (
        ("prepare_run", "slk.prepare_run"),
        ("deliver_message", "slk.deliver_message"),
        ("request_recovery", "slk.request_recovery"),
    ):
        implementation: Any = getattr(module, attribute, None)
        if implementation is None or not inspect.iscoroutinefunction(implementation):
            raise RuntimeError(f"adapter module must define async {attribute}(value)")
        result.append(_bind_activity(implementation, attribute, name))
    return result


async def run(address: str, task_queue: str, adapter_module: str) -> None:
    client = await Client.connect(address)
    async with Worker(
        client,
        task_queue=task_queue,
        workflows=[StartSlkWorkflow, RunSlkWorkflow],
        activities=_activities(adapter_module),
    ):
        await asyncio.Future()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="localhost:7233")
    parser.add_argument("--task-queue", required=True)
    parser.add_argument("--adapter-module", required=True)
    args = parser.parse_args()
    asyncio.run(run(args.address, args.task_queue, args.adapter_module))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
