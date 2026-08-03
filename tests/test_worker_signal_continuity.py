from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_worker_signal_stream.py"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def dispatch() -> dict:
    return {
        "run_id": "RUN-001",
        "dispatch_id": "DISPATCH-001",
        "worker_conversation_id": "WORKER-001",
        "go_id": "GO-01",
        "cell_id": "CELL-01.01",
        "round_id": "R01",
        "task_ref": {"sha256": "d" * 64},
        "created_at": "2026-08-03T10:00:00Z",
    }


def event(sequence: int, event_type: str, signal_id: str, signal_hash: str) -> dict:
    value = {
        **{key: value for key, value in dispatch().items() if key not in {"task_ref", "created_at"}},
        "sequence": sequence,
        "event_type": event_type,
        "signal_id": signal_id,
        "signal_sha256": signal_hash,
        "issued_at": f"2026-08-03T10:00:0{sequence}Z",
    }
    if event_type == "ACK":
        value["delivery_status"] = "RECEIVED"
    return value


def stream() -> dict:
    final = event(3, "FINAL", "SIGNAL-003", HASH_C)
    final.update(
        {
            "candidate_state": "IMMUTABLE_CANDIDATE",
            "candidate_ref": {"sha256": "e" * 64},
        }
    )
    return {
        "schema_version": "2.5",
        "dispatch": dispatch(),
        "delivery": {"status": "DELIVERED", "redispatch_count": 0},
        "control_state": "COMPLETED_UNREAD",
        "events": [
            event(1, "ACK", "SIGNAL-001", HASH_A),
            event(2, "PROGRESS", "SIGNAL-002", HASH_B),
            final,
        ],
        "ingestion": {"status": "PENDING"},
    }


def run_packet(tmp_path: Path, value: dict, *, optimized: bool = False) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "signals.yaml"
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command.extend([str(SCRIPT), str(path)])
    return subprocess.run(command, text=True, capture_output=True, check=False)


def test_completed_unread_is_valid(tmp_path: Path) -> None:
    result = run_packet(tmp_path, stream())
    assert result.returncode == 0, result.stderr


def test_atomic_final_ingestion_is_valid(tmp_path: Path) -> None:
    value = stream()
    value["control_state"] = "FINAL_INGESTED"
    value["ingestion"] = {
        "status": "INGESTED",
        "terminal_signal_id": "SIGNAL-003",
        "terminal_signal_sha256": HASH_C,
        "ingested_at": "2026-08-03T10:01:00Z",
        "resulting_route": "D1_VALIDATION",
        "state_sync_receipt_ref": {"sha256": "f" * 64},
    }
    result = run_packet(tmp_path, value, optimized=True)
    assert result.returncode == 0, result.stderr


def test_blocked_unread_is_valid(tmp_path: Path) -> None:
    value = stream()
    blocked = event(2, "BLOCKED", "SIGNAL-002", HASH_B)
    blocked["required_route"] = "PLAN_DEFECT"
    value["events"] = [event(1, "ACK", "SIGNAL-001", HASH_A), blocked]
    value["control_state"] = "BLOCKED_UNREAD"
    result = run_packet(tmp_path, value)
    assert result.returncode == 0, result.stderr


def test_missing_ack_fails_closed(tmp_path: Path) -> None:
    value = stream()
    value["events"] = value["events"][1:]
    for index, item in enumerate(value["events"], start=1):
        item["sequence"] = index
    result = run_packet(tmp_path, value, optimized=True)
    assert result.returncode == 1
    assert "SLK_SIGNAL_ACK_REQUIRED" in result.stderr


def test_event_after_terminal_fails_closed(tmp_path: Path) -> None:
    value = stream()
    value["events"].append(event(4, "PROGRESS", "SIGNAL-004", "d" * 64))
    result = run_packet(tmp_path, value)
    assert result.returncode == 1
    assert "SLK_SIGNAL_AFTER_TERMINAL" in result.stderr


def test_completed_unread_cannot_claim_ingested(tmp_path: Path) -> None:
    value = stream()
    value["ingestion"] = {"status": "INGESTED"}
    result = run_packet(tmp_path, value)
    assert result.returncode == 1
    assert "SLK_SIGNAL_UNREAD_INGESTION" in result.stderr


def test_ingestion_must_bind_terminal_identity(tmp_path: Path) -> None:
    value = stream()
    value["control_state"] = "FINAL_INGESTED"
    value["ingestion"] = {
        "status": "INGESTED",
        "terminal_signal_id": "WRONG",
        "terminal_signal_sha256": HASH_C,
        "ingested_at": "2026-08-03T10:01:00Z",
        "resulting_route": "D1_VALIDATION",
        "state_sync_receipt_ref": {"sha256": "f" * 64},
    }
    result = run_packet(tmp_path, value, optimized=True)
    assert result.returncode == 1
    assert "SLK_SIGNAL_INGESTION_ID" in result.stderr


def test_binding_drift_fails_closed(tmp_path: Path) -> None:
    value = stream()
    value["events"][1]["worker_conversation_id"] = "SECOND-WORKER"
    result = run_packet(tmp_path, value)
    assert result.returncode == 1
    assert "SLK_SIGNAL_BINDING_MISMATCH" in result.stderr


def test_redispatch_requires_proven_non_delivery(tmp_path: Path) -> None:
    value = stream()
    value["delivery"] = {
        "status": "DELIVERED",
        "redispatch_count": 1,
        "prior_delivery_status": "UNKNOWN",
        "redispatch_authority_ref": {"sha256": "f" * 64},
    }
    result = run_packet(tmp_path, value, optimized=True)
    assert result.returncode == 1
    assert "SLK_SIGNAL_DUPLICATE_DISPATCH" in result.stderr


def test_redispatch_with_proven_non_delivery_is_valid(tmp_path: Path) -> None:
    value = stream()
    value["delivery"] = {
        "status": "DELIVERED",
        "redispatch_count": 1,
        "prior_delivery_status": "TASK_NOT_DELIVERED_PROVEN",
        "redispatch_authority_ref": {"sha256": "f" * 64},
    }
    result = run_packet(tmp_path, value)
    assert result.returncode == 0, result.stderr


def test_duplicate_signal_identity_fails_closed(tmp_path: Path) -> None:
    value = stream()
    value["events"][1]["signal_id"] = "SIGNAL-001"
    result = run_packet(tmp_path, value)
    assert result.returncode == 1
    assert "SLK_SIGNAL_DUPLICATE_EVENT" in result.stderr


def test_no_candidate_final_requires_route(tmp_path: Path) -> None:
    value = stream()
    final = copy.deepcopy(value["events"][-1])
    final["candidate_state"] = "NO_CANDIDATE"
    final["candidate_ref"] = {}
    value["events"][-1] = final
    result = run_packet(tmp_path, value)
    assert result.returncode == 1
    assert "SLK_SIGNAL_NO_CANDIDATE_ROUTE" in result.stderr
