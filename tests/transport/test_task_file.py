from __future__ import annotations

import json
from pathlib import Path

import pytest

from slk_transport.adapters.dsh import DshAdapter
from slk_transport.contracts import Endpoint, Envelope
from slk_transport.evidence import AttemptStore
from slk_transport.task_file import TaskFileError, verify_task_file

from test_contracts import endpoint_value, envelope_value


def _endpoint(tmp_path: Path) -> Endpoint:
    repository = tmp_path / "repository"
    runtime = tmp_path / "runtime"
    repository.mkdir()
    runtime.mkdir()
    raw = endpoint_value(role="worker", version=1)
    raw.update({"agent_runtime": "dsh", "adapter": "dsh-worker"})
    raw["address"] = {
        "command": ["fake-dsh"],
        "instance_id": "RUN-A-worker",
        "session_id": None,
        "runtime_root": str(runtime),
        "cwd": str(repository),
        "timeout_seconds": 5,
    }
    return Endpoint.from_dict(raw)


def test_worker_task_file_is_closed_hashed_and_copied_to_attempt(tmp_path: Path) -> None:
    endpoint = _endpoint(tmp_path)
    envelope = Envelope.from_dict(envelope_value(sender_role="checker", receiver_role="worker"))
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    drop = tmp_path / "drop"
    drop.mkdir()

    task_path, digest = DshAdapter().create_task_file(endpoint, envelope, attempt, drop)
    task = verify_task_file(task_path, digest)

    assert set(task) == {
        "schema_version", "message_id", "run_id", "go_id", "cell_id",
        "endpoint", "envelope", "result_contract", "result_path",
    }
    assert task["schema_version"] == "slk.transport-task/v1"
    assert task["result_contract"]["completed"]["next_payload"]["candidate_repository"] == str(
        Path(str(endpoint.address["cwd"])).resolve()
    )
    assert "incomplete" in task["result_contract"]["allowed_statuses"]
    assert task["result_contract"]["non_completed"]["candidate"] is None
    assert (attempt.root / "transport-task.json").read_bytes() == task_path.read_bytes()
    assert "envelope" not in DshAdapter().task_instruction(task_path, digest).lower()


def test_mutated_or_unknown_task_file_fails_closed(tmp_path: Path) -> None:
    endpoint = _endpoint(tmp_path)
    envelope = Envelope.from_dict(envelope_value(sender_role="checker", receiver_role="worker"))
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    drop = tmp_path / "drop"
    drop.mkdir()
    task_path, digest = DshAdapter().create_task_file(endpoint, envelope, attempt, drop)

    value = json.loads(task_path.read_text(encoding="utf-8"))
    value["unexpected"] = True
    task_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(TaskFileError):
        verify_task_file(task_path, digest)
