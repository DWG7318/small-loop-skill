import json
import os
from pathlib import Path
import subprocess

import pytest


def state_binary() -> Path:
    configured = os.environ.get("SLK_STATE_BIN")
    if configured:
        path = Path(configured)
    else:
        suffix = ".exe" if os.name == "nt" else ""
        path = Path(__file__).parents[2] / "target" / "debug" / f"slk-state{suffix}"
    if not path.is_file():
        pytest.skip("build slk-state or set SLK_STATE_BIN before CLI contract tests")
    return path


def invoke(arguments, environment, check=True):
    completed = subprocess.run(
        [str(state_binary()), *map(str, arguments)],
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return completed


def configured_environment(tmp_path):
    environment = os.environ.copy()
    environment["SLK_CONFIG_PATH"] = str(tmp_path / "config" / "config.json")
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    return environment


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def init_request():
    return {
        "project": {
            "project_id": "project-a",
            "name": "Project A",
            "repository_url": None,
            "last_known_path": "D:/ProjectA",
        },
        "run_id": "run-a",
        "goal": "Goal",
        "boundaries": {},
        "go_nodes": [
            {
                "go_id": "GO-001",
                "ordinal": 1,
                "title": "GO",
                "objective": "Objective",
            }
        ],
        "cell_nodes": [
            {
                "go_id": "GO-001",
                "cell_id": "CELL-001",
                "ordinal": 1,
                "title": "CELL",
                "objective": "Objective",
            }
        ],
        "supervisor": {
            "role_instance_id": "supervisor-a",
            "role": "supervisor",
            "agent_runtime": "codex",
            "provider": "openai",
            "model": "sol",
            "reasoning": "xhigh",
            "session_id": "thread-a",
        },
        "supervisor_endpoint": {
            "endpoint_version": 1,
            "transport_adapter": "codex-app-server",
            "host_identity": "host-a",
            "session_id": "thread-a",
            "native_address": {"thread_id": "thread-a"},
        },
        "occurred_at": "2026-09-20T00:00:00Z",
    }


def supervisor_event():
    return {
        "event_id": "d2-started",
        "run_id": "run-a",
        "go_id": None,
        "cell_id": None,
        "attempt": None,
        "plan_revision": 1,
        "role_instance_id": "supervisor-a",
        "event_type": "D2_STARTED",
        "details": {},
        "occurred_at": "2026-09-20T00:00:01Z",
    }


def test_writer_configures_initializes_and_applies_one_role_event(tmp_path):
    environment = configured_environment(tmp_path)
    data_root = tmp_path / "state"
    configured = invoke(["configure", "--data-root", data_root], environment)
    assert json.loads(configured.stdout)["status"] == "configured"

    request_path = write_json(tmp_path / "init.json", init_request())
    initialized = json.loads(
        invoke(["init-run", "--request", request_path], environment).stdout
    )
    credential = initialized["supervisor_credential"]
    assert credential.startswith("slk_")

    event_path = write_json(tmp_path / "event.json", supervisor_event())
    role_environment = environment.copy()
    role_environment["SLK_ROLE_CREDENTIAL"] = credential
    result = json.loads(
        invoke(["write", "--request", event_path], role_environment).stdout
    )
    assert result["status"] == "recorded"


def test_writer_has_no_owner_or_anonymous_write_mode(tmp_path):
    environment = configured_environment(tmp_path)
    data_root = tmp_path / "state"
    invoke(["configure", "--data-root", data_root], environment)
    request_path = write_json(tmp_path / "init.json", init_request())
    invoke(["init-run", "--request", request_path], environment)
    event_path = write_json(tmp_path / "event.json", supervisor_event())

    result = invoke(["write", "--request", event_path], environment, check=False)
    assert result.returncode != 0
    error = json.loads(result.stderr)
    assert error["code"] == "SLK_ROLE_CREDENTIAL_REQUIRED"
    assert "SLK_ROLE_CREDENTIAL" in error["message"]
