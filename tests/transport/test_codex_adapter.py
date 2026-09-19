from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.codex import CodexAdapter
from slk_transport.contracts import Endpoint, Envelope
from slk_transport.evidence import AttemptStore

from test_contracts import endpoint_value, envelope_value


FAKE_SERVER = Path(__file__).with_name("fake_app_server.py")


def codex_endpoint(tmp_path: Path, mode: str = "normal") -> Endpoint:
    raw = endpoint_value(role="supervisor", version=1)
    raw["address"] = {
        "command": [sys.executable, str(FAKE_SERVER), mode],
        "thread_id": "thr_exact",
        "cwd": str(tmp_path),
        "startup_timeout_seconds": 1,
        "turn_timeout_seconds": 1,
    }
    return Endpoint.from_dict(raw)


def supervisor_envelope() -> Envelope:
    return Envelope.from_dict(
        envelope_value(
            sender_role="checker",
            receiver_role="supervisor",
            receiver_endpoint_version=1,
        )
    )


def test_codex_resumes_exact_thread_then_starts_turn(tmp_path: Path) -> None:
    endpoint = codex_endpoint(tmp_path)
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    result = CodexAdapter().deliver(endpoint, envelope, attempt)

    assert result.status == "completed"
    assert result.native_identity["thread_id"] == "thr_exact"
    assert result.native_identity["turn_id"] == "turn_exact"
    assert result.native_identity["turn_status"] == "completed"
    expected_turn = {"id": "turn_exact", "items": [], "status": "completed"}
    expected_hash = hashlib.sha256(
        json.dumps(expected_turn, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert result.native_identity["turn_sha256"] == expected_hash
    transcript = (attempt.root / "native.stdout.txt").read_text(encoding="utf-8").splitlines()
    client_methods = [
        json.loads(line[2:])["method"]
        for line in transcript
        if line.startswith("C ")
    ]
    assert client_methods == [
        "initialize",
        "initialized",
        "thread/resume",
        "thread/read",
        "turn/start",
    ]
    started = json.loads((attempt.root / "started.json").read_text(encoding="utf-8"))
    assert started["thread_id"] == "thr_exact"
    assert started["turn_id"] == "turn_exact"


@pytest.mark.parametrize(
    ("mode", "error_code"),
    [
        ("wrong-thread", "CODEX_THREAD_ID_MISMATCH"),
        ("active", "CODEX_THREAD_BUSY"),
        ("no-start", "CODEX_TURN_START_TIMEOUT"),
        ("failed-turn", "CODEX_TURN_FAILED"),
    ],
)
def test_codex_fails_closed_on_unproved_or_wrong_activation(
    tmp_path: Path,
    mode: str,
    error_code: str,
) -> None:
    endpoint = codex_endpoint(tmp_path, mode)
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    with pytest.raises(AdapterError) as error:
        CodexAdapter().deliver(endpoint, envelope, attempt)

    assert error.value.error_code == error_code


def test_codex_address_is_closed_and_never_accepts_a_title(tmp_path: Path) -> None:
    endpoint = codex_endpoint(tmp_path)
    invalid = Endpoint(
        **{
            **endpoint.__dict__,
            "address": {**endpoint.address, "conversation_title": "SLK Supervisor"},
        }
    )

    with pytest.raises(AdapterError) as error:
        CodexAdapter().validate_address(invalid)

    assert error.value.error_code == "CODEX_ADDRESS_INVALID"
