from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from slk_transport.cli import main
from slk_transport.native_activity import inspect_native_activity
from slk_transport.overwatcher_desktop import (
    OverwatcherDesktopError,
    attest_desktop_overwatcher,
    desktop_overwatcher_probe,
)
from slk_transport.run_readiness import _native_activity_capability


SERVER = Path(__file__).with_name("fake_overwatcher_desktop_mcp.py")
INPUT_TEXT = "<codex_delegation><input>observe the exact run</input></codex_delegation>"


def write_request(tmp_path: Path, method_version="4.4.2") -> tuple[Path, str]:
    request = {
        "schema_version": "slk.desktop-overwatcher-attestation-request/v1",
        "method_version": method_version,
        "attestation_id": "11111111-1111-4111-8111-111111111111",
        "run_id": "RUN-OW-A",
        "role_instance_id": "ow-a",
        "endpoint_ref": "ow-endpoint-a",
        "thread_id": "thread-ow",
        "host_id": "local",
        "cwd": str(tmp_path.resolve()),
        "turn_id": "turn-ow",
        "platform_input_item_id": "item-ow-input",
        "reader_thread_id": "thread-reader",
        "command": [sys.executable, str(SERVER.resolve())],
        "plugin_sha256": hashlib.sha256(SERVER.read_bytes()).hexdigest(),
        "timeout_seconds": 2,
    }
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_host(monkeypatch: pytest.MonkeyPatch, mode: str = "active") -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-reader")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "inherited-native-pipe")
    monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "Codex Desktop")
    monkeypatch.setenv("FAKE_OW_DESKTOP_MODE", mode)


@pytest.mark.parametrize("method_version", ["4.4.2", "4.4.3"])
def test_attests_existing_ow_turn_without_send_or_model_call(tmp_path: Path, monkeypatch, method_version) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path, method_version)
    evidence = tmp_path / "evidence"

    result = attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=evidence)

    started = json.loads((evidence / "started.json").read_text(encoding="utf-8"))
    attestation = json.loads((evidence / "desktop-overwatcher-attestation.json").read_text(encoding="utf-8"))
    calls = [json.loads(line) for line in (tmp_path / "ow-native-calls.jsonl").read_text().splitlines()]
    assert result["status"] == "ATTESTED"
    assert started["schema_version"] == "slk.native-start/v2"
    assert started["adapter"] == "codex-overwatcher"
    assert started["native_task"] == {
        "kind": "codex-desktop-turn",
        "id": "thread-ow:turn-ow:item-ow-input",
        "status": "RUNNING",
    }
    assert started["native_request_sha256"] == hashlib.sha256(INPUT_TEXT.encode()).hexdigest()
    assert attestation["role_instance_id"] == "ow-a"
    assert attestation["method_version"] == method_version
    assert attestation["endpoint_ref"] == "ow-endpoint-a"
    assert INPUT_TEXT not in (evidence / "desktop-overwatcher-attestation.json").read_text()
    assert {call["name"] for call in calls} == {"read_thread"}
    assert calls[0]["arguments"]["turnLimit"] == 1
    assert calls[0]["arguments"]["maxOutputCharsPerItem"] == 4096


def test_identical_attestation_retry_reuses_the_same_immutable_start(tmp_path: Path, monkeypatch) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path)
    evidence = tmp_path / "evidence"

    first = attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=evidence)
    second = attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=evidence)

    assert second == first


def test_each_native_inspection_refreshes_from_real_platform_after_file_snapshot_is_stale(
    tmp_path: Path, monkeypatch,
) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path)
    evidence = tmp_path / "evidence"
    result = attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=evidence)
    activity_path = evidence / "native-activity.json"
    stale = json.loads(activity_path.read_text(encoding="utf-8"))
    stale["observed_at"] = "2020-01-01T00:00:00Z"
    activity_path.write_text(json.dumps(stale), encoding="utf-8")

    observed = inspect_native_activity(
        evidence / "started.json",
        native_probe=lambda start: desktop_overwatcher_probe(
            evidence / "desktop-overwatcher-attestation.json",
            attestation_sha256=result["attestation_sha256"],
            started_path=evidence / "started.json",
            start=start,
        ),
    )

    calls = [json.loads(line) for line in (tmp_path / "ow-native-calls.jsonl").read_text().splitlines()]
    assert observed["status"] == "ACTIVE"
    assert observed["error"] is None
    assert len(calls) == 2
    assert {call["name"] for call in calls} == {"read_thread"}


def test_fresh_inspection_accepts_live_turn_after_attested_input_rolls_out_of_latest_page(
    tmp_path: Path, monkeypatch,
) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path)
    evidence = tmp_path / "evidence"
    result = attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=evidence)
    monkeypatch.setenv("FAKE_OW_DESKTOP_MODE", "paged")

    observed = inspect_native_activity(
        evidence / "started.json",
        native_probe=lambda start: desktop_overwatcher_probe(
            evidence / "desktop-overwatcher-attestation.json",
            attestation_sha256=result["attestation_sha256"],
            started_path=evidence / "started.json",
            start=start,
        ),
    )

    assert observed["status"] == "ACTIVE"
    assert observed["error"] is None


@pytest.mark.parametrize(
    "mode",
    ["wrong-thread", "wrong-host", "wrong-cwd", "wrong-turn", "tampered-input"],
)
def test_fresh_inspection_rejects_live_identity_or_visible_input_drift(
    tmp_path: Path, monkeypatch, mode: str,
) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path)
    evidence = tmp_path / "evidence"
    result = attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=evidence)
    monkeypatch.setenv("FAKE_OW_DESKTOP_MODE", mode)

    observed = inspect_native_activity(
        evidence / "started.json",
        native_probe=lambda start: desktop_overwatcher_probe(
            evidence / "desktop-overwatcher-attestation.json",
            attestation_sha256=result["attestation_sha256"],
            started_path=evidence / "started.json",
            start=start,
        ),
    )

    assert observed["status"] == "UNKNOWN"
    assert observed["error"] == "NATIVE_QUERY_FAILED"


@pytest.mark.parametrize("reader", ["thread-reader", "thread-ow", "thread-temporal-host"])
def test_fresh_inspection_uses_the_current_trusted_desktop_reader_without_rebinding_target(
    tmp_path: Path, monkeypatch, reader: str,
) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path)
    evidence = tmp_path / "evidence"
    result = attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=evidence)
    monkeypatch.setenv("CODEX_THREAD_ID", reader)

    observed = inspect_native_activity(
        evidence / "started.json",
        native_probe=lambda start: desktop_overwatcher_probe(
            evidence / "desktop-overwatcher-attestation.json",
            attestation_sha256=result["attestation_sha256"],
            started_path=evidence / "started.json",
            start=start,
        ),
    )

    assert observed["status"] == "ACTIVE"
    assert observed["error"] is None


def test_fresh_inspection_rejects_a_caller_without_current_desktop_reader_identity(
    tmp_path: Path, monkeypatch,
) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path)
    evidence = tmp_path / "evidence"
    result = attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=evidence)
    monkeypatch.delenv("CODEX_THREAD_ID")

    observed = inspect_native_activity(
        evidence / "started.json",
        native_probe=lambda start: desktop_overwatcher_probe(
            evidence / "desktop-overwatcher-attestation.json",
            attestation_sha256=result["attestation_sha256"],
            started_path=evidence / "started.json",
            start=start,
        ),
    )

    assert observed["status"] == "UNKNOWN"
    assert observed["error"] == "NATIVE_QUERY_FAILED"


def test_initial_attestation_still_requires_the_frozen_attesting_reader(
    tmp_path: Path, monkeypatch,
) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path)
    monkeypatch.setenv("CODEX_THREAD_ID", "another-desktop-reader")

    with pytest.raises(OverwatcherDesktopError, match="reader capability"):
        attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=tmp_path / "evidence")


@pytest.mark.parametrize("mode", ["no-read", "tool-error", "idle-running"])
def test_live_inspection_fails_closed_when_desktop_cannot_prove_active_work(
    tmp_path: Path, monkeypatch, mode: str,
) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path)
    evidence = tmp_path / "evidence"
    result = attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=evidence)
    monkeypatch.setenv("FAKE_OW_DESKTOP_MODE", mode)

    observed = inspect_native_activity(
        evidence / "started.json",
        native_probe=lambda start: desktop_overwatcher_probe(
            evidence / "desktop-overwatcher-attestation.json",
            attestation_sha256=result["attestation_sha256"],
            started_path=evidence / "started.json",
            start=start,
        ),
    )

    assert observed["status"] == "UNKNOWN"
    assert observed["error"] == "NATIVE_QUERY_FAILED"


@pytest.mark.parametrize("mode", ["wrong-thread", "wrong-item", "completed"])
def test_initial_attestation_fails_closed_on_identity_or_liveness_drift(
    tmp_path: Path, monkeypatch, mode: str,
) -> None:
    prepare_host(monkeypatch, mode)
    request, digest = write_request(tmp_path)

    with pytest.raises(OverwatcherDesktopError):
        attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=tmp_path / "evidence")

    assert not (tmp_path / "evidence" / "started.json").exists()


def test_tampered_attestation_cannot_refresh_activity(tmp_path: Path, monkeypatch) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path)
    evidence = tmp_path / "evidence"
    result = attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=evidence)
    attestation_path = evidence / "desktop-overwatcher-attestation.json"
    attestation = json.loads(attestation_path.read_text(encoding="utf-8"))
    attestation["turn_id"] = "another-turn"
    attestation_path.write_text(json.dumps(attestation), encoding="utf-8")

    observed = inspect_native_activity(
        evidence / "started.json",
        native_probe=lambda start: desktop_overwatcher_probe(
            attestation_path,
            attestation_sha256=result["attestation_sha256"],
            started_path=evidence / "started.json",
            start=start,
        ),
    )

    assert observed["status"] == "UNKNOWN"
    assert observed["error"] == "NATIVE_QUERY_FAILED"


def test_tampered_native_start_cannot_refresh_activity(tmp_path: Path, monkeypatch) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path)
    evidence = tmp_path / "evidence"
    result = attest_desktop_overwatcher(request, request_sha256=digest, evidence_root=evidence)
    started_path = evidence / "started.json"
    started = json.loads(started_path.read_text(encoding="utf-8"))
    started["observed_at"] = "2020-01-01T00:00:00Z"
    started_path.write_text(json.dumps(started), encoding="utf-8")

    observed = inspect_native_activity(
        started_path,
        native_probe=lambda start: desktop_overwatcher_probe(
            evidence / "desktop-overwatcher-attestation.json",
            attestation_sha256=result["attestation_sha256"],
            started_path=started_path,
            start=start,
        ),
    )

    assert observed["status"] == "UNKNOWN"
    assert observed["error"] == "NATIVE_QUERY_FAILED"


def test_cli_attestation_and_fresh_inspection_use_closed_contracts(tmp_path: Path, monkeypatch, capsys) -> None:
    prepare_host(monkeypatch)
    request, digest = write_request(tmp_path)
    evidence = tmp_path / "evidence"

    assert main([
        "attest-desktop-overwatcher", "--request", str(request), "--sha256", digest,
        "--evidence-root", str(evidence),
    ]) == 0
    attested = json.loads(capsys.readouterr().out)
    assert main([
        "inspect-native-activity", "--started", str(evidence / "started.json"),
        "--desktop-overwatcher-attestation", attested["attestation_path"],
        "--desktop-overwatcher-attestation-sha256", attested["attestation_sha256"],
    ]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["status"] == "ACTIVE"

    contracts = Path(__file__).resolve().parents[2] / "docs" / "contracts"
    Draft202012Validator(json.loads(
        (contracts / "slk-desktop-overwatcher-attestation-request.schema.json").read_text(encoding="utf-8")
    )).validate(json.loads(request.read_text(encoding="utf-8")))
    Draft202012Validator(json.loads(
        (contracts / "slk-desktop-overwatcher-attestation.schema.json").read_text(encoding="utf-8")
    )).validate(json.loads(Path(attested["attestation_path"]).read_text(encoding="utf-8")))


def test_installed_codex_ow_capability_is_closed_and_read_only() -> None:
    root = Path(__file__).resolve().parents[2]
    capability = root / "integrations" / "temporal" / "slk-overwatcher-capabilities.json"

    assert _native_activity_capability(str(capability), "codex") is None
    value = json.loads(capability.read_text(encoding="utf-8"))
    assert value["read_only_observation"] is True
    assert value["model_call_required"] is False
    assert value["native_events"] == ["thread/status", "turn/status", "platform-input/item"]
