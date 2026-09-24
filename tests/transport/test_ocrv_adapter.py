from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.ocrv import OcrvAdapter, _recovery_invocation_id
from slk_transport.contracts import Endpoint, Envelope, canonical_json_sha256
from slk_transport.evidence import AttemptStore

from test_contracts import endpoint_value, envelope_value
from test_worker_completion import completion_fixture


FAKE_OCRV = Path(__file__).with_name("fake_ocrv.py")
FAKE_RECOVERY_TRANSPORT = Path(__file__).with_name("fake_checker_recovery_transport.py")
RECOVERY_COMPANION = Path(__file__).parents[2] / "integrations" / "ocrv" / "slk_checker_recovery.py"


def checker_endpoint(tmp_path: Path, mode: str = "normal") -> Endpoint:
    runtime_root = tmp_path / "ocrv-runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    raw = endpoint_value(role="checker", version=2)
    raw["address"] = {
        "command": [sys.executable, str(FAKE_OCRV), mode],
        "runtime_root": str(runtime_root),
        "timeout_seconds": 5,
    }
    return Endpoint.from_dict(raw)


def candidate_envelope(tmp_path: Path) -> Envelope:
    repository = tmp_path / "repository"
    repository.mkdir(parents=True, exist_ok=True)
    payload = {
        "repository": str(repository),
        "candidate": {"kind": "workspace"},
        "cell_goal": "Verify the transport probe candidate.",
        "d1_criteria": ["The probe nonce remains bound to RUN-A."],
        "evidence_files": [],
    }
    raw = envelope_value(sender_role="worker", receiver_role="checker")
    raw["payload_type"] = "CANDIDATE_READY"
    raw["payload"] = payload
    raw["payload_sha256"] = canonical_json_sha256(payload)
    return Envelope.from_dict(raw)


def recovery_envelope(tmp_path: Path) -> Envelope:
    source_attempt, _worker, _checker = completion_fixture(tmp_path)
    projection = tmp_path / "runtime-projection.json"
    projection.write_text("{}", encoding="utf-8")
    worker_credential = tmp_path / "worker.dpapi"
    checker_credential = tmp_path / "checker.dpapi"
    worker_credential.write_text("00", encoding="ascii")
    checker_credential.write_text("00", encoding="ascii")
    payload = {
        "source_attempt_root": str(source_attempt),
        "runtime_projection_path": str(projection),
        "plan_revision": 1,
        "runtime_revision": 7,
        "token_sequence": 14,
        "worker_credential_path": str(worker_credential),
        "checker_credential_path": str(checker_credential),
        "state_command": ["slk-state"],
        "transport_command": [sys.executable, "slk-transport.pyz"],
        "occurred_at": "2026-09-23T00:00:00Z",
    }
    raw = envelope_value(sender_role="supervisor", receiver_role="checker", receiver_endpoint_version=2)
    raw["message_id"] = "22222222-2222-4222-8222-222222222222"
    raw["payload_type"] = "WORKER_COMPLETION_RECOVERY"
    raw["payload"] = payload
    raw["payload_sha256"] = canonical_json_sha256(payload)
    return Envelope.from_dict(raw)


def test_ocrv_candidate_review_records_run_cell_invocation_and_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = checker_endpoint(tmp_path)
    envelope = candidate_envelope(tmp_path)
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    monkeypatch.setenv("SLK_ROLE_CREDENTIAL", "slk_parent_secret")
    monkeypatch.setenv("SLK_OVERWATCHER_CREDENTIAL", "slk_parent_secret")

    result = OcrvAdapter().deliver(endpoint, envelope, attempt)

    assert result.status == "completed"
    assert result.native_identity["run_id"] == "RUN-A"
    assert result.native_identity["cell_id"] == "CELL-001"
    assert result.native_identity["review_invocation_id"]
    assert str(result.native_identity["session_id"]).startswith("ocrv-session-")
    assert result.native_identity["provider"] == "dashscope-tokenplan"
    assert result.native_identity["model"] == "qwen3.8-max"
    assert (attempt.root / "started.json").is_file()
    assert (attempt.root / "ocrv-result.json").is_file()


def test_ocrv_v1_request_matches_installed_closed_contract(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path)
    envelope = candidate_envelope(tmp_path)
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    result = OcrvAdapter().deliver(endpoint, envelope, attempt)

    request = json.loads((attempt.root / "ocrv-request.json").read_text(encoding="utf-8"))
    assert set(request) == {
        "schema_version",
        "run_id",
        "cell_id",
        "repository",
        "candidate",
        "cell_goal",
        "d1_criteria",
        "evidence_files",
    }
    started = json.loads((attempt.root / "started.json").read_text(encoding="utf-8"))
    assert "transport_invocation_id" in started
    assert "review_invocation_id" not in started
    assert result.native_identity["review_invocation_id"]


def test_registered_ocrv_checker_runs_one_closed_worker_completion_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = checker_endpoint(tmp_path, "recovery")
    envelope = recovery_envelope(tmp_path)
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    monkeypatch.setenv("SLK_ROLE_CREDENTIAL", "slk_parent_secret")
    monkeypatch.setenv("SLK_OVERWATCHER_CREDENTIAL", "slk_parent_secret")

    result = OcrvAdapter().deliver(endpoint, envelope, attempt)

    assert result.status == "completed"
    assert result.native_identity["checker_operation"] == "worker_completion_recovery"
    assert result.native_identity["checker_role_instance_id"] == endpoint.role_instance_id
    assert result.native_identity["checker_endpoint_version"] == endpoint.endpoint_version
    assert result.native_identity["checker_authenticated"] is True
    assert result.native_identity["authorized_recovery"] is True
    started = json.loads((attempt.root / "started.json").read_text(encoding="utf-8"))
    assert started["checker_role_instance_id"] == endpoint.role_instance_id
    assert started["authentication_status"] == "PENDING"
    assert started["authorized_recovery"] is False
    assert (attempt.root / "ocrv-recovery-request.json").is_file()
    assert (attempt.root / "ocrv-recovery-result.json").is_file()


def test_checker_recovery_invocation_is_stable_for_exact_message_retry(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path, "recovery")
    envelope = recovery_envelope(tmp_path)
    first = _recovery_invocation_id(envelope.message_id)
    second = _recovery_invocation_id(envelope.message_id)
    request = OcrvAdapter()._recovery_request(endpoint, envelope, first, tmp_path / "result.json")

    assert first == second
    assert request["recovery_invocation_id"] == first


def test_ocrv_recovery_companion_strips_parent_credentials_and_keeps_native_identity(
    tmp_path: Path,
) -> None:
    result_path = tmp_path / "result.json"
    request = {
        "schema_version": "slk.ocrv-worker-recovery-request/v1",
        "result_path": str(result_path),
        "transport_command": [sys.executable, str(FAKE_RECOVERY_TRANSPORT)],
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    environment = os.environ.copy()
    environment["SLK_ROLE_CREDENTIAL"] = "slk_parent_secret"
    environment["SLK_OVERWATCHER_CREDENTIAL"] = "slk_parent_secret"
    environment["SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID"] = "RUN-A-checker-001"
    environment["SLK_OCRV_RECOVERY_INVOCATION_ID"] = "recovery-1"
    environment["SLK_OCRV_RECOVERY_ENDPOINT_VERSION"] = "2"

    completed = subprocess.run(
        [
            sys.executable,
            str(RECOVERY_COMPANION),
            "--slk-worker-recovery",
            "--request",
            str(request_path),
            "--output",
            str(result_path),
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(result_path.read_text(encoding="utf-8"))["status"] == "CHECKER_STARTED"


def test_ocrv_records_spawn_start_before_terminal_result(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path, "delayed-terminal")
    envelope = candidate_envelope(tmp_path)
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    outcome: list[object] = []

    thread = threading.Thread(
        target=lambda: outcome.append(OcrvAdapter().deliver(endpoint, envelope, attempt)),
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 2
    while not (attempt.root / "started.json").is_file() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert (attempt.root / "started.json").is_file()
    assert thread.is_alive()
    assert not (attempt.root / "ocrv-result.json").exists()
    thread.join(5)
    assert outcome and outcome[0].status == "completed"


def test_ocrv_fails_closed_when_session_identity_is_missing(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path, "missing-session")
    envelope = candidate_envelope(tmp_path)
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    with pytest.raises(AdapterError) as error:
        OcrvAdapter().deliver(endpoint, envelope, attempt)

    assert error.value.error_code == "OCRV_RESULT_INVALID"
    assert (attempt.root / "started.json").exists()


def test_ocrv_preserves_a_valid_incomplete_review_without_calling_it_pass(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path, "incomplete")
    envelope = candidate_envelope(tmp_path)
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    result = OcrvAdapter().deliver(endpoint, envelope, attempt)

    assert result.status == "completed"
    assert result.native_identity["verdict"] == "INCOMPLETE"
    assert result.native_identity["exit_code"] == 3
    assert (attempt.root / "started.json").is_file()


def test_checker_dispatch_creates_exact_worker_delivery_without_running_d1(tmp_path: Path) -> None:
    checker = checker_endpoint(tmp_path)
    worker_raw = endpoint_value(role="worker", version=1)
    worker_raw["agent_runtime"] = "dsh"
    worker_raw["adapter"] = "dsh-worker"
    worker_raw["address"] = {"command": ["D:/DSH/dsh-slk.cmd"]}
    worker = Endpoint.from_dict(worker_raw)
    payload = {
        "worker_endpoint": worker_raw,
        "worker_payload": {"probe_nonce": "A-001", "task": "No project change probe."},
    }
    raw = envelope_value()
    raw["payload_type"] = "CELL_DISPATCH"
    raw["payload"] = payload
    raw["payload_sha256"] = canonical_json_sha256(payload)
    envelope = Envelope.from_dict(raw)
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    result = OcrvAdapter().deliver(checker, envelope, attempt)

    assert result.native_identity["checker_operation"] == "dispatch"
    checker_result = json.loads((attempt.root / "checker-result.json").read_text(encoding="utf-8"))
    next_envelope = checker_result["next_envelope"]
    assert checker_result["next_endpoint"]["role_instance_id"] == "RUN-A-worker-001"
    assert next_envelope["sender_role"] == "checker"
    assert next_envelope["receiver_role"] == "worker"
    assert next_envelope["token_sequence"] == 2
    assert next_envelope["run_id"] == "RUN-A"
    assert next_envelope["go_id"] == "GO-001"
    assert next_envelope["cell_id"] == "CELL-001"


def test_ocrv_address_is_closed(tmp_path: Path) -> None:
    endpoint = checker_endpoint(tmp_path)
    invalid = Endpoint(
        **{
            **endpoint.__dict__,
            "address": {**endpoint.address, "conversation_title": "Checker"},
        }
    )

    with pytest.raises(AdapterError) as error:
        OcrvAdapter().validate_address(invalid)

    assert error.value.error_code == "OCRV_ADDRESS_INVALID"
