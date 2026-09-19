from __future__ import annotations

import json
import sys
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


def test_dsh_prompt_defines_the_closed_worker_result_without_d0_conclusions(tmp_path: Path) -> None:
    endpoint = worker_endpoint(tmp_path)
    envelope = worker_envelope()
    result_path = tmp_path / "worker-result.json"

    prompt = DshAdapter().command(endpoint, envelope, result_path)[-1]

    assert '"schema_version":"slk.worker-result/v1"' in prompt
    assert f'"message_id":"{envelope.message_id}"' in prompt
    assert '"candidate"' in prompt
    assert '"next_payload"' in prompt
    assert "D0 conclusion" not in prompt


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

    command = DshAdapter().command(endpoint, envelope, attempt.root / "worker-result.json")
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
