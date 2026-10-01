from __future__ import annotations

import json
import io
import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.build_transport_zipapp import build_zipapp
from scripts.run_transport_drill import run_drill
import slk_transport.cli as transport_cli

from test_contracts import endpoint_value, envelope_value, payload_hash
from test_worker_completion import completion_fixture, runtime_projection


TESTS = Path(__file__).parent


def write_json(path: Path, value: dict[str, object]) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def cli_delivery(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    runtime = tmp_path / "ocrv-runtime"
    runtime.mkdir()
    endpoint = endpoint_value(role="checker", version=2)
    endpoint["address"] = {
        "command": [sys.executable, str(TESTS / "fake_ocrv.py"), "normal"],
        "runtime_root": str(runtime),
        "timeout_seconds": 5,
    }
    worker = endpoint_value(role="worker", version=1)
    worker["agent_runtime"] = "dsh"
    worker["adapter"] = "dsh-worker"
    worker["address"] = {"command": ["D:/DSH/dsh-slk.cmd"]}
    payload = {
        "worker_endpoint": worker,
        "worker_payload": {"probe_nonce": "A-001", "task": "CLI probe"},
    }
    envelope = envelope_value()
    envelope["payload_type"] = "CELL_DISPATCH"
    envelope["payload"] = payload
    envelope["payload_sha256"] = payload_hash(payload)
    artifact = build_zipapp(tmp_path / "slk-transport.pyz")
    return (
        artifact,
        write_json(tmp_path / "endpoint.json", endpoint),
        write_json(tmp_path / "envelope.json", envelope),
        str(envelope["message_id"]),
    )


def run_cli(artifact: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(artifact), *arguments],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def test_nested_windows_send_retries_access_denied_without_breakaway(
    monkeypatch,
) -> None:
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    calls: list[int] = []

    class Process:
        pid = 436

    class AccessDenied(OSError):
        winerror = 5

    def popen(_command, **kwargs):
        calls.append(int(kwargs["creationflags"]))
        if len(calls) == 1:
            raise AccessDenied(5, "Access is denied")
        return Process()

    monkeypatch.setattr(transport_cli.subprocess, "Popen", popen)
    monkeypatch.setattr(
        transport_cli,
        "windows_no_window_kwargs",
        lambda *, detached: {
            "creationflags": no_window | breakaway,
            "startupinfo": object(),
        },
    )

    process = transport_cli._spawn_send_job(
        ["tool", "job"], stdout=io.BytesIO(), stderr=io.BytesIO()
    )

    assert process.pid == 436
    assert calls == [no_window | breakaway, no_window]


def test_nested_windows_send_does_not_retry_an_unrelated_start_failure(
    monkeypatch,
) -> None:
    breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
    calls = 0

    class MissingExecutable(OSError):
        winerror = 2

    def popen(_command, **_kwargs):
        nonlocal calls
        calls += 1
        raise MissingExecutable(2, "The system cannot find the file specified")

    monkeypatch.setattr(transport_cli.subprocess, "Popen", popen)
    monkeypatch.setattr(
        transport_cli,
        "windows_no_window_kwargs",
        lambda *, detached: {"creationflags": breakaway, "startupinfo": object()},
    )

    with pytest.raises(MissingExecutable):
        transport_cli._spawn_send_job(
            ["missing-tool"], stdout=io.BytesIO(), stderr=io.BytesIO()
        )

    assert calls == 1


def test_validate_and_job_execute_one_closed_delivery(tmp_path: Path) -> None:
    artifact, endpoint, envelope, message_id = cli_delivery(tmp_path)
    attempts = tmp_path / "attempts"

    validated = run_cli(
        artifact,
        "validate",
        "--endpoint",
        str(endpoint),
        "--envelope",
        str(envelope),
    )
    assert validated.returncode == 0
    assert json.loads(validated.stdout)["status"] == "valid"

    delivered = run_cli(
        artifact,
        "job",
        "--endpoint",
        str(endpoint),
        "--envelope",
        str(envelope),
        "--attempt-root",
        str(attempts),
    )
    assert delivered.returncode == 0
    assert json.loads(delivered.stdout)["status"] == "completed"
    assert (attempts / "RUN-A" / message_id / "started.json").is_file()
    assert (attempts / "RUN-A" / message_id / "completed.json").is_file()


def test_send_starts_one_detached_job_and_reports_native_start(tmp_path: Path) -> None:
    artifact, endpoint, envelope, message_id = cli_delivery(tmp_path)
    attempts = tmp_path / "attempts"

    sent = run_cli(
        artifact,
        "send",
        "--endpoint",
        str(endpoint),
        "--envelope",
        str(envelope),
        "--attempt-root",
        str(attempts),
        "--startup-timeout-seconds",
        "5",
    )

    assert sent.returncode == 0
    output = json.loads(sent.stdout)
    assert output["status"] in {"started", "completed"}
    assert output["message_id"] == message_id
    terminal = attempts / "RUN-A" / message_id / "completed.json"
    deadline = time.monotonic() + 5
    while not terminal.is_file() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert terminal.is_file()


def test_inspect_reports_existing_native_start_without_dispatch(tmp_path: Path) -> None:
    artifact, endpoint, envelope, _message_id = cli_delivery(tmp_path)
    attempts = tmp_path / "attempts"
    delivered = run_cli(
        artifact,
        "job",
        "--endpoint",
        str(endpoint),
        "--envelope",
        str(envelope),
        "--attempt-root",
        str(attempts),
    )
    assert delivered.returncode == 0

    inspected = run_cli(
        artifact,
        "inspect",
        "--endpoint",
        str(endpoint),
        "--envelope",
        str(envelope),
        "--attempt-root",
        str(attempts),
    )

    assert inspected.returncode == 0
    assert json.loads(inspected.stdout)["status"] == "ALREADY_STARTED"


def test_inspect_worker_completion_cli_returns_anomaly_without_mutating_source(tmp_path: Path) -> None:
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    completed_at = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc).timestamp()
    os.utime(attempt / "completed.json", (completed_at, completed_at))
    projection_path = write_json(
        tmp_path / "projection.json",
        runtime_projection(token_owner=str(endpoint["role_instance_id"])),
    )
    artifact = build_zipapp(tmp_path / "slk-transport.pyz")
    inspection_path = tmp_path / "worker-inspection.json"

    inspected = run_cli(
        artifact,
        "inspect-worker-completion",
        "--source-attempt",
        str(attempt),
        "--runtime-projection",
        str(projection_path),
        "--observed-at",
        "2026-09-23T00:04:00Z",
        "--cadence-seconds",
        "240",
        "--output",
        str(inspection_path),
    )

    assert inspected.returncode == 3
    output = json.loads(inspected.stdout)
    assert output["status"] == "WORKER_COMPLETION_HANDOFF_MISSING"
    assert output["notification_already_sent"] is False
    assert json.loads(inspection_path.read_text(encoding="utf-8")) == output
    assert not (attempt / "worker-continuation").exists()


def test_supervisor_cannot_call_worker_continuation_resume_directly(tmp_path: Path) -> None:
    artifact = build_zipapp(tmp_path / "slk-transport.pyz")

    rejected = run_cli(artifact, "resume-worker-continuation")

    assert rejected.returncode == 2
    assert "invalid choice" in rejected.stderr


def test_checker_post_d1_cli_is_exposed_and_fails_closed_on_an_open_request(tmp_path: Path) -> None:
    artifact = build_zipapp(tmp_path / "slk-transport.pyz")
    request = write_json(tmp_path / "post-d1.json", {})

    rejected = run_cli(
        artifact,
        "checker-escalate-d1",
        "--request",
        str(request),
        "--sha256",
        hashlib.sha256(request.read_bytes()).hexdigest(),
    )

    assert rejected.returncode == 2
    result = json.loads(rejected.stdout)
    assert result["status"] == "rejected"
    assert result["error_code"] == "CHECKER_ESCALATION_REQUEST_INVALID"


def test_retry_exact_uses_persisted_identity_and_stops_after_one_attempt(
    tmp_path: Path,
) -> None:
    artifact, endpoint_path, envelope_path, message_id = cli_delivery(tmp_path)
    attempts = tmp_path / "attempts"
    endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    attempt = attempts / "RUN-A" / message_id
    attempt.mkdir(parents=True)
    write_json(attempt / "endpoint.json", endpoint)
    write_json(attempt / "envelope.json", envelope)
    write_json(
        attempt / "failed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": message_id,
            "run_id": "RUN-A",
            "adapter": "ocrv-checker",
            "status": "failed",
            "native_identity": {},
            "error_code": "DELIVERY_UNCONFIRMED",
            "evidence": [],
        },
    )

    retried = run_cli(
        artifact,
        "retry-exact",
        "--endpoint",
        str(endpoint_path),
        "--envelope",
        str(envelope_path),
        "--attempt-root",
        str(attempts),
    )

    assert retried.returncode == 0
    assert json.loads(retried.stdout)["status"] == "RETRY_COMPLETED"
    assert (
        attempt
        / "recovery"
        / "exact-1"
        / "RUN-A"
        / message_id
        / "started.json"
    ).is_file()


def test_validate_rejects_unknown_address_field_before_attempt_creation(tmp_path: Path) -> None:
    artifact, endpoint_path, envelope, _ = cli_delivery(tmp_path)
    endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
    endpoint["address"]["conversation_title"] = "Checker"
    endpoint_path.write_text(json.dumps(endpoint), encoding="utf-8")

    result = run_cli(
        artifact,
        "validate",
        "--endpoint",
        str(endpoint_path),
        "--envelope",
        str(envelope),
    )

    assert result.returncode != 0
    output = json.loads(result.stdout)
    assert output["status"] == "rejected"
    assert output["error_code"] == "OCRV_ADDRESS_INVALID"


def test_drill_verify_cli_independently_accepts_two_complete_runs(tmp_path: Path) -> None:
    values = {
        "evidence_root": str(tmp_path / "evidence"),
        "workspace_root": str(tmp_path / "workspaces"),
        "codex_command": [sys.executable, str(TESTS / "fake_app_server.py"), "normal"],
        "ocrv_command": [sys.executable, str(TESTS / "fake_ocrv.py"), "normal"],
        "dsh_command": [sys.executable, str(TESTS / "fake_dsh.py"), "normal"],
        "timeout_seconds": 5,
    }
    run_drill(values, live=False, run_ids=("RUN-A", "RUN-B"))
    artifact = build_zipapp(tmp_path / "slk-transport.pyz")

    result = run_cli(
        artifact,
        "drill-verify",
        "--evidence-root",
        str(values["evidence_root"]),
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "TRANSPORT_DRILL_PASS"
