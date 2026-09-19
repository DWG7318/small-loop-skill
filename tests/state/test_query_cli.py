import json
import os
from pathlib import Path
import subprocess

import pytest

from test_state_cli import configured_environment, init_request, invoke as invoke_state, write_json


def query_binary() -> Path:
    configured = os.environ.get("SLK_QUERY_BIN")
    if configured:
        path = Path(configured)
    else:
        suffix = ".exe" if os.name == "nt" else ""
        path = Path(__file__).parents[2] / "target" / "debug" / f"slk-bi-query{suffix}"
    if not path.is_file():
        pytest.skip("build slk-bi-query or set SLK_QUERY_BIN before CLI contract tests")
    return path


def invoke_query(arguments, environment, check=True):
    completed = subprocess.run(
        [str(query_binary()), *map(str, arguments)],
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise AssertionError(completed.stderr)
    return completed


def seed(tmp_path):
    environment = configured_environment(tmp_path)
    invoke_state(["configure", "--data-root", tmp_path / "state"], environment)
    request = write_json(tmp_path / "init.json", init_request())
    invoke_state(["init-run", "--request", request], environment)
    return environment


def test_query_works_while_no_bi_process_exists(tmp_path):
    environment = seed(tmp_path)
    result = json.loads(
        invoke_query(["run", "--run-id", "run-a"], environment).stdout
    )
    assert result["schema_version"] == "slk.bi.run/v1"
    assert result["run_id"] == "run-a"
    assert result["summary"]["run_id"] == "run-a"


def test_configure_creates_an_empty_readable_state(tmp_path):
    environment = configured_environment(tmp_path)
    invoke_state(["configure", "--data-root", tmp_path / "state"], environment)

    result = json.loads(invoke_query(["projects"], environment).stdout)

    assert result == {"schema_version": "slk.bi.projects/v1", "projects": []}


def test_query_surface_has_no_mutation_or_secret_path(tmp_path):
    environment = configured_environment(tmp_path)
    help_text = invoke_query(["--help"], environment).stdout.lower()
    for forbidden in ("write", "dispatch", "approve", "credential", "exempt"):
        assert forbidden not in help_text
