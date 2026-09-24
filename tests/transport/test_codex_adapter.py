from __future__ import annotations

import json
import hashlib
import shutil
import sys
from pathlib import Path

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.codex import CodexAdapter, wait_for_exact_thread_idle
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


def test_codex_reads_exact_idle_thread_then_starts_turn(tmp_path: Path) -> None:
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
        ("active", "CODEX_ACTIVE_WRITER"),
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


def test_codex_not_loaded_supervisor_is_started_directly(tmp_path: Path) -> None:
    endpoint = codex_endpoint(tmp_path, "not-loaded")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    result = CodexAdapter().deliver(endpoint, envelope, attempt)

    assert result.status == "completed"
    assert result.native_identity["turn_id"] == "turn_exact"


def test_active_writer_records_exact_turn_without_starting_or_waiting(tmp_path: Path) -> None:
    endpoint = codex_endpoint(tmp_path, "active")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    with pytest.raises(AdapterError, match="turn_active") as error:
        CodexAdapter().deliver(endpoint, envelope, attempt)

    assert error.value.error_code == "CODEX_ACTIVE_WRITER"
    evidence = json.loads((attempt.root / "active-writer.json").read_text(encoding="utf-8"))
    assert evidence["active_turn_id"] == "turn_active"
    transcript = (attempt.root / "native.stdout.txt").read_text(encoding="utf-8")
    assert '"method":"turn/start"' not in transcript


def test_active_writer_is_read_before_resume_can_conflict(tmp_path: Path) -> None:
    endpoint = codex_endpoint(tmp_path, "active-resume-conflict")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    with pytest.raises(AdapterError) as error:
        CodexAdapter().deliver(endpoint, envelope, attempt)

    assert error.value.error_code == "CODEX_ACTIVE_WRITER"
    assert (attempt.root / "active-writer.json").is_file()
    transcript = (attempt.root / "native.stdout.txt").read_text(encoding="utf-8")
    assert '"method":"thread/read"' in transcript
    assert '"method":"thread/resume"' not in transcript


def test_stale_codex_executable_is_rebound_without_changing_endpoint_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = codex_endpoint(tmp_path)
    stale = Endpoint(
        **{
            **endpoint.__dict__,
            "address": {
                **endpoint.address,
                "command": [str(tmp_path / "old-build" / "codex.exe"), str(FAKE_SERVER), "normal"],
            },
        }
    )
    monkeypatch.setattr(shutil, "which", lambda _name: sys.executable)
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    result = CodexAdapter().deliver(stale, envelope, attempt)

    assert result.status == "completed"
    evidence = json.loads((attempt.root / "command-rebind.json").read_text(encoding="utf-8"))
    assert evidence["requested_executable"].endswith("codex.exe")
    assert evidence["resolved_executable"] == sys.executable
    assert evidence["thread_id"] == stale.address["thread_id"]


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


@pytest.mark.parametrize("role", ["checker", "worker"])
def test_codex_adapter_rejects_non_supervisor_roles(tmp_path: Path, role: str) -> None:
    endpoint = codex_endpoint(tmp_path)
    invalid = Endpoint(**{**endpoint.__dict__, "role": role})

    with pytest.raises(AdapterError) as error:
        CodexAdapter().validate_address(invalid)

    assert error.value.error_code == "CODEX_ADDRESS_INVALID"


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def test_bounded_activation_accepts_busy_then_idle_without_real_sleep() -> None:
    clock = FakeClock()
    states = iter(["active", "active", "idle"])

    result = wait_for_exact_thread_idle(
        lambda: {"thread": {"id": "thr_exact", "status": {"type": next(states)}}},
        "thr_exact",
        timeout=1,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        poll_interval=0.1,
    )

    assert result["status"]["type"] == "idle"
    assert clock.value == pytest.approx(0.2)


def test_bounded_activation_rejects_permanent_busy_at_deadline() -> None:
    clock = FakeClock()
    with pytest.raises(AdapterError) as error:
        wait_for_exact_thread_idle(
            lambda: {"thread": {"id": "thr_exact", "status": {"type": "active"}}},
            "thr_exact",
            timeout=0.2,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
            poll_interval=0.1,
        )
    assert error.value.error_code == "CODEX_THREAD_BUSY"
    assert clock.value == pytest.approx(0.2)


@pytest.mark.parametrize(
    ("thread", "error_code"),
    [
        ({"id": "wrong", "status": {"type": "idle"}}, "CODEX_THREAD_ID_MISMATCH"),
        ({"id": "thr_exact", "status": {"type": "failed"}}, "CODEX_THREAD_TERMINAL"),
    ],
)
def test_bounded_activation_rejects_wrong_target_and_terminal_state(
    thread: dict[str, object], error_code: str
) -> None:
    clock = FakeClock()
    with pytest.raises(AdapterError) as error:
        wait_for_exact_thread_idle(
            lambda: {"thread": thread},
            "thr_exact",
            timeout=1,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
    assert error.value.error_code == error_code
