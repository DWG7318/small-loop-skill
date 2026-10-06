from __future__ import annotations

import inspect
import sys
from types import ModuleType

import pytest

pytest.importorskip("temporalio")

from slk_temporal.activities import ACTIVITY_NAMES
from slk_temporal.worker import _activities, _selected_adapter
from slk_temporal.workflows import RunSlkWorkflow, StartSlkWorkflow


def test_two_named_templates_and_five_adapter_activities_are_exposed() -> None:
    assert StartSlkWorkflow.__temporal_workflow_definition.name == "SLK.Start"
    assert RunSlkWorkflow.__temporal_workflow_definition.name == "SLK.Run"
    assert ACTIVITY_NAMES == (
        "slk.prepare_run",
        "slk.deliver_message",
        "slk.request_recovery",
        "slk.inspect_overwatcher",
        "slk.notify_supervisor",
    )
    assert inspect.iscoroutinefunction(StartSlkWorkflow.run)
    assert inspect.iscoroutinefunction(RunSlkWorkflow.run)


def test_workflow_surface_has_only_communication_updates_and_queries() -> None:
    assert {
        "request_delivery",
        "request_admission",
        "native_started",
        "overwatcher_exited",
        "resolve_runtime_guard",
        "close_run",
        "status",
    }.issubset(
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


def test_adapter_loader_exposes_five_single_argument_temporal_activities(monkeypatch) -> None:
    module = ModuleType("slk_test_adapter")

    async def prepare_run(value):
        return value

    async def deliver_message(value):
        return value

    async def request_recovery(value):
        return value

    async def inspect_overwatcher(value):
        return value

    async def notify_supervisor(value):
        return value

    module.prepare_run = prepare_run
    module.deliver_message = deliver_message
    module.request_recovery = request_recovery
    module.inspect_overwatcher = inspect_overwatcher
    module.notify_supervisor = notify_supervisor
    monkeypatch.setitem(sys.modules, module.__name__, module)

    loaded = _activities(module.__name__)

    assert tuple(item.__temporal_activity_definition.name for item in loaded) == ACTIVITY_NAMES
    assert all(len(inspect.signature(item).parameters) == 1 for item in loaded)


def test_worker_selects_built_in_standard_adapter_without_caller_module(tmp_path) -> None:
    selected = _selected_adapter(adapter_module=None, standard_config_root=tmp_path)
    assert selected == "slk_temporal.standard_adapter"


def test_worker_rejects_two_adapter_sources(tmp_path) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        _selected_adapter(adapter_module="custom", standard_config_root=tmp_path)
