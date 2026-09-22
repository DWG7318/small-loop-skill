from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from slk_transport.active_writer import recover_active_writer
from slk_transport.adapters.codex import CodexAdapter
from slk_transport.contracts import ContractError
from slk_transport.dispatcher import dispatch_once

from test_contracts import endpoint_value, envelope_value, payload_hash


FAKE_SERVER = Path(__file__).with_name("fake_app_server.py")


def delivery(tmp_path: Path) -> tuple[dict[str, object], dict[str, object]]:
    endpoint = endpoint_value(role="supervisor", version=1)
    endpoint["address"] = {
        "command": [sys.executable, str(FAKE_SERVER), "active"],
        "thread_id": "thr_exact",
        "cwd": str(tmp_path),
        "startup_timeout_seconds": 1,
        "turn_timeout_seconds": 1,
    }
    payload = {
        "d1_failure_event_id": "d1-failed-001",
        "failed_candidate_sha256": "a" * 64,
        "rework_round": 1,
        "cell_goal": "Repair the current CELL.",
        "acceptance_criteria": ["The failed behavior is corrected."],
        "findings": ["The candidate violates criterion one."],
        "reproduction_steps": ["Run the focused regression test."],
        "expected_result": "The focused regression test passes.",
        "evidence_refs": ["evidence/d1-failed-001.json"],
    }
    envelope = envelope_value(
        sender_role="checker", receiver_role="supervisor", receiver_endpoint_version=1
    )
    envelope["payload_type"] = "D1_FAILURE_ESCALATION"
    envelope["payload"] = payload
    envelope["payload_sha256"] = payload_hash(payload)
    return endpoint, envelope


def test_active_writer_recovery_uses_new_message_and_preserves_old_failure(tmp_path: Path) -> None:
    endpoint, envelope = delivery(tmp_path)
    attempts = tmp_path / "attempts"
    result = dispatch_once(
        endpoint, envelope, attempts, adapters={"codex-app-server": CodexAdapter()}
    )
    assert result.status == "failed"
    assert result.error_code == "CODEX_ACTIVE_WRITER"
    original = attempts / str(envelope["run_id"]) / str(envelope["message_id"])
    failed_before = (original / "failed.json").read_bytes()

    recovered = recover_active_writer(attempts, endpoint, envelope)

    assert recovered["status"] == "started"
    assert recovered["recovery_of_message_id"] == envelope["message_id"]
    assert recovered["recovery_message_id"] != envelope["message_id"]
    assert recovered["expected_turn_id"] == "turn_active"
    assert (original / "failed.json").read_bytes() == failed_before
    receipt = json.loads(
        (original / "recovery" / "active-writer" / "recovery.json").read_text(encoding="utf-8")
    )
    assert receipt == recovered
    transcript = (original / "recovery" / "active-writer" / "native.stdout.txt").read_text(
        encoding="utf-8"
    )
    assert '"method":"turn/steer"' in transcript
    assert f'"clientUserMessageId":"{recovered["recovery_message_id"]}"' in transcript


def test_active_writer_recovery_rejects_changed_identity_and_second_attempt(tmp_path: Path) -> None:
    endpoint, envelope = delivery(tmp_path)
    attempts = tmp_path / "attempts"
    dispatch_once(endpoint, envelope, attempts, adapters={"codex-app-server": CodexAdapter()})
    recover_active_writer(attempts, endpoint, envelope)

    with pytest.raises(ContractError, match="already exists"):
        recover_active_writer(attempts, endpoint, envelope)

    changed = json.loads(json.dumps(envelope))
    changed["payload"]["expected_result"] = "changed"
    changed["payload_sha256"] = payload_hash(changed["payload"])
    with pytest.raises(ContractError, match="identity"):
        recover_active_writer(attempts, endpoint, changed)
