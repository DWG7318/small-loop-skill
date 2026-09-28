from __future__ import annotations

import inspect
import sys
from types import ModuleType

import pytest

pytest.importorskip("temporalio")

from slk_temporal.activities import ACTIVITY_NAMES
from slk_temporal.worker import _activities
from slk_temporal.workflows import RunSlkWorkflow, StartSlkWorkflow


def test_two_named_templates_and_three_adapter_activities_are_exposed() -> None:
    assert StartSlkWorkflow.__temporal_workflow_definition.name == "SLK.Start"
    assert RunSlkWorkflow.__temporal_workflow_definition.name == "SLK.Run"
    assert ACTIVITY_NAMES == (
        "slk.prepare_run",
        "slk.deliver_message",
        "slk.request_recovery",
    )
    assert inspect.iscoroutinefunction(StartSlkWorkflow.run)
    assert inspect.iscoroutinefunction(RunSlkWorkflow.run)


def test_workflow_surface_has_only_communication_updates_and_queries() -> None:
    assert {"request_delivery", "native_started", "close_run", "status"}.issubset(
        set(dir(RunSlkWorkflow))
    )
    for forbidden in (
        "decide_d1",
        "decide_d2",
        "move_token",
        "select_model",
        "create_role",
        "write_bi",
    ):
        assert not hasattr(RunSlkWorkflow, forbidden)


def test_adapter_loader_exposes_three_single_argument_temporal_activities(monkeypatch) -> None:
    module = ModuleType("slk_test_adapter")

    async def prepare_run(value):
        return value

    async def deliver_message(value):
        return value

    async def request_recovery(value):
        return value

    module.prepare_run = prepare_run
    module.deliver_message = deliver_message
    module.request_recovery = request_recovery
    monkeypatch.setitem(sys.modules, module.__name__, module)

    loaded = _activities(module.__name__)

    assert tuple(item.__temporal_activity_definition.name for item in loaded) == ACTIVITY_NAMES
    assert all(len(inspect.signature(item).parameters) == 1 for item in loaded)
