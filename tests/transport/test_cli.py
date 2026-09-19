from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from scripts.build_transport_zipapp import build_zipapp
from scripts.run_transport_drill import run_drill

from test_contracts import endpoint_value, envelope_value, payload_hash


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
