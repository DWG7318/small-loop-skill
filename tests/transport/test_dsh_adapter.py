from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.dsh import DshAdapter
from slk_transport.contracts import Endpoint, Envelope
from slk_transport.evidence import AttemptStore

from test_contracts import endpoint_value, envelope_value


FAKE_DSH = Path(__file__).with_name("fake_dsh.py")


def worker_endpoint(
    tmp_path: Path,
    *,
    mode: str = "normal",
    session_id: str | None = None,
    run_id: str = "RUN-A",
) -> Endpoint:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    repository = tmp_path / "repository"
    repository.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    raw = endpoint_value(role="worker", run_id=run_id, version=1)
    raw["agent_runtime"] = "dsh"
    raw["adapter"] = "dsh-worker"
    raw["address"] = {
        "command": [sys.executable, str(FAKE_DSH), mode],
        "instance_id": f"{run_id}-worker",
        "session_id": session_id,
        "runtime_root": str(runtime_root),
        "cwd": str(repository),
        "timeout_seconds": 5,
    }
    return Endpoint.from_dict(raw)


def worker_envelope(run_id: str = "RUN-A") -> Envelope:
    return Envelope.from_dict(
        envelope_value(
            run_id=run_id,
            sender_role="checker",
            receiver_role="worker",
            receiver_endpoint_version=1,
        )
    )


def test_dsh_first_turn_uses_run_scoped_instance_and_records_session(tmp_path: Path) -> None:
    endpoint = worker_endpoint(tmp_path)
    envelope = worker_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    result = DshAdapter().deliver(endpoint, envelope, attempt)

    assert result.status == "completed"
    assert result.native_identity["instance_id"] == "RUN-A-worker"
    assert str(result.native_identity["session_id"]).startswith("session-")
    assert (attempt.root / "worker-result.json").is_file()
    assert (attempt.root / "started.json").is_file()
    native = json.loads((attempt.root / "native.stdout.txt").read_text(encoding="utf-8"))
    assert Path(native["result_path"]).is_relative_to(Path(str(endpoint.address["cwd"])))
    assert not (Path(str(endpoint.address["cwd"])) / ".slk-transport").exists()


def test_dsh_records_native_start_before_terminal_result(tmp_path: Path) -> None:
    endpoint = worker_endpoint(tmp_path, mode="delayed-terminal")
    envelope = worker_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    outcome: list[object] = []

    thread = threading.Thread(
        target=lambda: outcome.append(DshAdapter().deliver(endpoint, envelope, attempt)),
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 2
    while not (attempt.root / "started.json").is_file() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert (attempt.root / "started.json").is_file()
    assert thread.is_alive()
    assert not (attempt.root / "worker-result.json").exists()
    thread.join(5)
    assert outcome and outcome[0].status == "completed"


def test_dsh_command_uses_only_a_short_hashed_task_reference(tmp_path: Path) -> None:
    endpoint = worker_endpoint(tmp_path)
    envelope = worker_envelope()
    instruction = DshAdapter().task_instruction(tmp_path / "task.json", "a" * 64)
    assert json.dumps(str((tmp_path / "task.json").resolve())) in instruction
    assert "a" * 64 in instruction
    assert envelope.message_id not in instruction
    assert len(instruction) < 600


def test_dsh_resume_uses_only_the_recorded_session(tmp_path: Path) -> None:
    session_id = "session-11111111-1111-4111-8111-111111111111"
    endpoint = worker_endpoint(tmp_path, session_id=session_id)
    session_root = (
        Path(str(endpoint.address["runtime_root"]))
        / "runs"
        / str(endpoint.address["instance_id"])
        / "home"
        / "storages"
        / "session_projcache"
        / "sessions"
    )
    session_root.mkdir(parents=True, exist_ok=True)
    (session_root / f"{session_id}.json").write_text("{}\n", encoding="utf-8")
    envelope = worker_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    command = DshAdapter().command(endpoint, "task")
    assert command[-3:-1] == ["--resume", session_id]

    result = DshAdapter().deliver(endpoint, envelope, attempt)
    assert result.native_identity["session_id"] == session_id
    assert len(list(session_root.glob("session-*.json"))) == 1


@pytest.mark.parametrize(
    ("mode", "error_code"),
    [
        ("missing-result", "DSH_RESULT_MISSING"),
        ("multiple-sessions", "DSH_SESSION_AMBIGUOUS"),
    ],
)
def test_dsh_fails_closed_without_one_result_and_one_session(
    tmp_path: Path,
    mode: str,
    error_code: str,
) -> None:
    endpoint = worker_endpoint(tmp_path, mode=mode)
    envelope = worker_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    with pytest.raises(AdapterError) as error:
        DshAdapter().deliver(endpoint, envelope, attempt)

    assert error.value.error_code == error_code


def test_dsh_rejects_instance_reuse_across_runs(tmp_path: Path) -> None:
    endpoint = worker_endpoint(tmp_path, run_id="RUN-B")
    invalid = Endpoint(
        **{
            **endpoint.__dict__,
            "address": {**endpoint.address, "instance_id": "RUN-A-worker"},
        }
    )

    with pytest.raises(AdapterError) as error:
        DshAdapter().validate_address(invalid)

    assert error.value.error_code == "DSH_ADDRESS_INVALID"


@pytest.mark.parametrize(
    ("role", "adapter"),
    [("supervisor", "codex-app-server"), ("checker", "ocrv-checker")],
)
def test_dsh_adapter_rejects_non_worker_roles(
    tmp_path: Path, role: str, adapter: str
) -> None:
    endpoint = worker_endpoint(tmp_path)
    invalid = Endpoint(
        **{
            **endpoint.__dict__,
            "role": role,
            "adapter": adapter,
        }
    )

    with pytest.raises(AdapterError) as error:
        DshAdapter().validate_address(invalid)

    assert error.value.error_code == "DSH_ADDRESS_INVALID"
