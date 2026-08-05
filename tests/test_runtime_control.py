from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_runtime_control.py"

REQUIRED_SIMULATION_SCENARIOS = {
    "WAKE_LEVEL1_SUCCESS",
    "WAKE_LEVEL2_SUCCESS",
    "WAKE_ARCHIVE_HOST_REPAIR",
    "WAKE_THREAD_NOT_FOUND_NO_REPLACEMENT",
    "WAKE_LEVEL3_HEARTBEAT_UNIQUE_CLEANUP",
    "WAKE_LEVEL4_PENDING_PATROL",
    "WAKE_ACK_STOPS_ESCALATION",
    "WAKE_PROCESSING_EVIDENCE_STOPS_ESCALATION",
    "NON_WORKER_LADDER_REJECTED",
    "SUPERVISOR_WAIT_DETECTED",
    "VISIBLE_TASK_NOT_SUBAGENT",
    "SUBAGENT_EVIDENCE_REJECTED",
    "NORMAL_PAUSE_NOT_ALERTED",
    "DUPLICATE_PATROL_REJECTED",
    "TERMINAL_PATROL_CLOSED",
    "WORKER_MESSAGE_SCOPE_POSITION",
    "DELIVERY_DOES_NOT_INCREMENT_ACCEPTED",
    "D1_PASS_INCREMENTS_ONCE",
    "REWORK_DUPLICATE_DO_NOT_INCREMENT",
    "GO_CANDIDATE_NOT_D2",
    "CHECKER_MILESTONE_GO_BOUNDARY_ONLY",
    "SUPERVISOR_LAYERED_PROGRESS",
    "AMENDMENT_RECOMPUTES_DENOMINATOR",
    "NO_DUPLICATE_PROGRESS_NOISE",
    "WAKE_LEVELS_SHARE_PROGRESS_IDENTITY",
    "CAPACITY_EARLY_PASS_LATE_SPLIT",
    "LOW_RESOURCE_HEAVY_CELL_REJECTED",
    "UNKNOWN_CAPACITY_FAIL_CLOSED",
    "CAPACITY_GATE_REQUIRED_BEFORE_DISPATCH",
    "PRE_SPLIT_PRESERVES_GO_ACCEPTANCE",
    "WORKER_SELF_SPLIT_REJECTED",
    "POST_DISPATCH_SPLIT_SEVERE",
    "SIX_SEVEN_EIGHT_SPLITS_SEVERE",
    "ACTUAL_PEAK_TIGHTENS_CAPACITY",
    "LOGICAL_PARALLELISM_NOT_DEVICE_CONCURRENCY",
    "CAPACITY_SPLIT_RECOMPUTES_PROGRESS",
    "THREAD_CREATION_DISPATCH_NO_PIN",
    "METHOD_ROLES_PIN_DENIED",
    "PATROL_PIN_DENIED",
    "OWNER_PIN_NOT_ALERTED",
    "AGENT_PIN_ALERTED",
    "UNKNOWN_PIN_NO_AUTO_UNPIN",
    "PIN_THEN_UNPIN_RETAINS_VIOLATION",
    "EXTRA_SLK_ROLE_REJECTED",
    "OUTSIDE_LOOP_SUPERVISOR_WAIT_REJECTED",
    "SUPERVISOR_WAIT_LOOP_WAIT_ALL_REJECTED",
    "PROGRESS_TRIGGER_BOUND",
    "PATROL_COMPLETE_CHECKLIST",
    "RUN_RUNTIME_INDEX_COMPLETE",
    "PATROL_DIFFICULTY_INTERVAL_BOUND",
}

SLK_TECHNICAL_ROLES = [
    "SUPERVISOR_RESPONSIBILITY",
    "CHECKER_RESPONSIBILITY",
    "VERIFIER_RESPONSIBILITY",
    "WORKER",
]

PATROL_CHECK_KINDS = {
    "FORWARD_MOTION",
    "PENDING_WAKE",
    "SUBAGENT_EVIDENCE",
    "SUPERVISOR_WAIT",
    "PATROL_UNIQUENESS",
    "THREAD_PIN",
    "TERMINAL_CLOSURE",
}


def run_record(
    tmp_path: Path,
    packet: dict,
    *,
    optimized: bool = False,
) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "record.yaml"
    path.write_text(yaml.safe_dump(packet, sort_keys=False), encoding="utf-8")
    args = [sys.executable]
    if optimized:
        args.append("-O")
    args.extend([str(SCRIPT), str(path)])
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )


def assert_pass(tmp_path: Path, packet: dict) -> None:
    result = run_record(tmp_path, packet)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: SLK runtime control record" in result.stdout


def assert_reject(
    tmp_path: Path,
    packet: dict,
    code: str,
    *,
    optimized: bool = False,
) -> None:
    result = run_record(tmp_path, packet, optimized=optimized)
    assert result.returncode == 1, result.stdout + result.stderr
    assert code in result.stderr


def runtime_contract() -> dict:
    return {
        "schema_version": "2.5.0",
        "record_type": "RUN_RUNTIME_CONTRACT",
        "status": "READY",
        "run_id": "RUN-001",
        "workload_class": "MEDIUM",
        "baseline_ref": {"id": "SB-001", "version": 1, "sha256": "a" * 64},
        "formal_conversations": {
            "CONTROL": "thread-control",
            "WORKER": "thread-worker",
        },
        "patrol": {
            "conversation_id": "thread-patrol",
            "conversation_count": 1,
            "heartbeat_id": "SLK-PATROL-RUN-001",
            "heartbeat_count": 1,
            "model": "gpt-5.6-luna",
            "reasoning_effort": "xhigh",
            "interval_minutes": 15,
        },
        "checker_binding": {
            "thread_id": "thread-control",
            "host_id": "local",
        },
        "worker_capabilities": {
            "send_message_to_thread": "AVAILABLE",
            "read_thread": "AVAILABLE",
            "list_threads": "AVAILABLE",
            "unarchive_thread": "AVAILABLE",
            "bounded_ack_wait": "AVAILABLE",
            "temporary_heartbeat_upsert": "AVAILABLE",
            "temporary_heartbeat_delete": "AVAILABLE",
            "pending_wake_write": "AVAILABLE",
        },
        "supervisor_wait": {
            "positive_timeout_allowed": False,
            "loop_allowed": False,
            "wait_for_all_members_allowed": False,
            "snapshot_timeout_zero_allowed": True,
        },
        "required_sets": {
            "version": 1,
            "required_go_ids": ["GO-01", "GO-02"],
            "required_cells_by_go": {
                "GO-01": ["CELL-01.01", "CELL-01.02"],
                "GO-02": ["CELL-02.01"],
            },
        },
        "device_capacity_profile_ref": {"id": "DCP-RUN-001", "version": 1},
        "cumulative_engineering_load_ref": {"id": "CEL-RUN-001", "version": 1},
        "cell_capacity_policy": {
            "required_before_dispatch": True,
            "allowed_dispatch_outcome": "PASS",
            "worker_self_split_allowed": False,
        },
        "thread_pin_policy": {
            "technical_roles": SLK_TECHNICAL_ROLES,
            "technical_role_pin_allowed_by_default": False,
            "set_thread_pinned_true_capability": "DENIED",
            "owner_manual_allowed": True,
            "owner_explicit_item_authorization_allowed": True,
            "inferred_authorization_allowed": False,
            "patrol_pin_capability": "DENIED",
            "patrol_auto_unpin_allowed": False,
            "pin_lifecycle_independent": True,
            "unauthorized_history_persists_after_unpin": True,
        },
        "evidence_refs": ["evidence/runtime-readiness.txt"],
    }


def simulation() -> dict:
    return {
        "schema_version": "2.5.0",
        "record_type": "RUNTIME_SIMULATION",
        "status": "SIMULATION_PASS",
        "run_id": "RUN-001",
        "clock_source": "INJECTED",
        "scenarios": [
            {
                "scenario_id": scenario,
                "result": "PASS",
                "evidence_refs": [f"evidence/{scenario.lower()}.txt"],
            }
            for scenario in sorted(REQUIRED_SIMULATION_SCENARIOS)
        ],
    }


def ack() -> dict:
    return {
        "message": "WAKE_ACK RUN-001 GO-03 CELL-03.25 R01",
        "run_id": "RUN-001",
        "go_id": "GO-03",
        "cell_id": "CELL-03.25",
        "round_id": "R01",
    }


def attempt(
    level: int,
    result: str,
    *,
    wait_seconds: int = 120,
    ack_value: dict | None = None,
) -> dict:
    actions = {
        1: "SEND_MESSAGE_TO_THREAD",
        2: "READ_LIST_RESOLVE_RESEND",
        3: "UPSERT_CHECKER_WAKE_HEARTBEAT",
        4: "WRITE_PENDING_WAKE",
    }
    value = {
        "level": level,
        "offset_seconds": (level - 1) * 120,
        "action": actions[level],
        "thread_id": "thread-control",
        "host_id": "local",
        "message": "GO-03 CELL 25/30 已交付，请检查",
        "wait_seconds": wait_seconds,
        "result": result,
        "evidence_refs": [f"evidence/wake-level-{level}.txt"],
    }
    if ack_value is not None:
        value["ack"] = ack_value
    if level == 2:
        value["resolution"] = {
            "thread_found": True,
            "registry_thread_id": "thread-control",
            "registry_host_id": "local",
            "was_archived": False,
            "unarchived": False,
            "host_repaired": False,
            "guessed_id": False,
            "replacement_created": False,
        }
    if level == 3:
        value["heartbeat"] = {
            "heartbeat_id": (
                "SLK-WAKE-RUN-001-GO-03-CELL-03.25-R01-thread-control"
            ),
            "heartbeat_count": 1,
        }
    if level == 4:
        value["pending_wake_ref"] = "pending/SLK-PENDING-WAKE-RUN-001-GO-03-CELL-03.25-R01.yaml"
    return value


def wake_trace(*, success_level: int = 1) -> dict:
    attempts = []
    for level in range(1, success_level):
        attempts.append(attempt(level, "NO_ACK"))
    attempts.append(
        attempt(
            success_level,
            "ACK",
            wait_seconds=5,
            ack_value=ack(),
        )
    )
    return {
        "schema_version": "2.5.0",
        "record_type": "WORKER_WAKE_TRACE",
        "status": "ACKNOWLEDGED",
        "run_id": "RUN-001",
        "go_id": "GO-03",
        "cell_id": "CELL-03.25",
        "cell_ordinal": 25,
        "required_cell_total": 30,
        "round_id": "R01",
        "sender_role": "WORKER",
        "receiver_responsibility": "CHECKER_RESPONSIBILITY",
        "checker_binding": {
            "thread_id": "thread-control",
            "host_id": "local",
        },
        "delivery_state": "DELIVERED",
        "message": "GO-03 CELL 25/30 已交付，请检查",
        "clock_source": "INJECTED",
        "attempts": attempts,
        "stopped": True,
        "temporary_heartbeat_state": (
            "DELETED" if success_level >= 3 else "NOT_CREATED"
        ),
        "pending_wake_ref": "",
        "evidence_refs": ["evidence/wake-trace.txt"],
    }


def failed_wake_trace() -> dict:
    value = wake_trace()
    value.update(
        {
            "status": "PENDING_WAKE_WRITTEN",
            "attempts": [
                attempt(1, "NO_ACK"),
                attempt(2, "THREAD_NOT_FOUND"),
                attempt(3, "NO_ACK"),
                attempt(4, "PENDING_WAKE_WRITTEN", wait_seconds=0),
            ],
            "temporary_heartbeat_state": "ACTIVE",
            "pending_wake_ref": (
                "pending/SLK-PENDING-WAKE-RUN-001-GO-03-CELL-03.25-R01.yaml"
            ),
        }
    )
    value["attempts"][1]["resolution"].update(
        {
            "thread_found": False,
            "registry_thread_id": "thread-control",
            "registry_host_id": "local",
        }
    )
    return value


def pending_wake() -> dict:
    return {
        "schema_version": "2.5.0",
        "record_type": "PENDING_WAKE",
        "status": "PATROL_OBSERVED",
        "pending_wake_id": "SLK-PENDING-WAKE-RUN-001-GO-03-CELL-03.25-R01",
        "run_id": "RUN-001",
        "go_id": "GO-03",
        "cell_id": "CELL-03.25",
        "cell_ordinal": 25,
        "required_cell_total": 30,
        "round_id": "R01",
        "worker_thread_id": "thread-worker",
        "checker_binding": {
            "thread_id": "thread-control",
            "host_id": "local",
        },
        "attempt_count": 3,
        "attempt_errors": ["NO_ACK", "THREAD_NOT_FOUND", "NO_ACK"],
        "created_at": "2026-08-04T00:06:00Z",
        "patrol": {
            "conversation_id": "thread-patrol",
            "conversation_count": 1,
            "heartbeat_id": "SLK-PATROL-RUN-001",
            "heartbeat_count": 1,
            "observed": True,
            "alert_code": "PENDING_WAKE_UNCONSUMED",
        },
        "checker_ack": {},
        "evidence_refs": ["evidence/pending-wake.txt"],
    }


def patrol_check(check_kind: str) -> dict:
    findings = {
        "FORWARD_MOTION": "LEGAL_FORWARD_MOTION",
        "PENDING_WAKE": "NO_PENDING_WAKE",
        "SUBAGENT_EVIDENCE": "NO_SUBAGENT_EVIDENCE",
        "SUPERVISOR_WAIT": "ZERO_SNAPSHOT_OR_NONE",
        "PATROL_UNIQUENESS": "UNIQUE_PATROL_AND_HEARTBEAT",
        "THREAD_PIN": "UNPINNED_OR_OWNER_PROVEN",
        "TERMINAL_CLOSURE": "RUN_NOT_TERMINAL",
    }
    return {
        "check_kind": check_kind,
        "finding": findings[check_kind],
        "result": "NORMAL",
        "alert_code": "",
        "timeout_ms": 0,
        "inside_loop": False,
        "looped": False,
        "wait_all": False,
        "legitimate_reason_ref": "",
        "evidence_refs": [f"evidence/patrol-{check_kind.lower()}.txt"],
    }


def patrol_item(packet: dict, check_kind: str) -> dict:
    return next(
        item for item in packet["checklist"] if item["check_kind"] == check_kind
    )


def patrol_receipt() -> dict:
    return {
        "schema_version": "2.5.0",
        "record_type": "RUN_PATROL_RECEIPT",
        "status": "OBSERVED",
        "run_id": "RUN-001",
        "patrol_cycle_id": "PATROL-RUN-001-CYCLE-001",
        "workload_class": "MEDIUM",
        "actor": "RUN_PATROL",
        "model": "gpt-5.6-luna",
        "reasoning_effort": "xhigh",
        "authority": "NONE",
        "conversation_id": "thread-patrol",
        "conversation_count": 1,
        "heartbeat_id": "SLK-PATROL-RUN-001",
        "heartbeat_count": 1,
        "interval_minutes": 15,
        "run_state": "RUNNING",
        "checklist": [patrol_check(kind) for kind in sorted(PATROL_CHECK_KINDS)],
        "actions": [],
        "engineering_progress_reported": False,
        "terminal_cleanup": {
            "loop_terminal_confirmed": False,
            "heartbeat_deleted": False,
            "conversation_archived": False,
        },
        "evidence_refs": ["evidence/patrol.txt"],
    }


def progress_event(
    sequence: int,
    event: str,
    actor: str,
    audience: str,
    message: str,
    *,
    cell_id: str = "CELL-01.01",
    cell_ordinal: int = 1,
    d1_receipts: list[dict] | None = None,
    d2_receipts: list[dict] | None = None,
    accepted: int = 0,
    verified: int = 0,
    milestone_id: str = "",
) -> dict:
    return {
        "sequence": sequence,
        "event_id": f"PE-{sequence:03d}",
        "trigger_event_id": f"PE-{sequence - 1:03d}" if sequence > 1 else "",
        "trigger_receipt_id": "",
        "trigger_verdict": "NONE",
        "event": event,
        "actor": actor,
        "audience": audience,
        "go_id": "GO-01",
        "go_ordinal": 1,
        "cell_id": cell_id,
        "cell_ordinal": cell_ordinal,
        "round_id": "R01",
        "required_set_version": 1,
        "required_cell_total": 2,
        "required_go_total": 2,
        "current_d1_pass_receipts": d1_receipts or [],
        "current_d2_pass_receipts": d2_receipts or [],
        "accepted_cell_count": accepted,
        "verified_go_count": verified,
        "d3_state": "PENDING",
        "owner_acceptance_state": "PENDING",
        "status": event,
        "message": message,
        "milestone_id": milestone_id,
        "recomputed": False,
        "evidence_refs": [f"evidence/progress-{sequence}.txt"],
    }


def bind_progress_events(packet: dict) -> None:
    for index, event in enumerate(packet["events"], start=1):
        event["sequence"] = index
        event["event_id"] = f"PE-{index:03d}"
        event["trigger_event_id"] = f"PE-{index - 1:03d}" if index > 1 else ""
        event["trigger_receipt_id"] = ""
        event["trigger_verdict"] = "NONE"
        if event["event"] in {"D1_ACCEPTED", "GO_CANDIDATE_READY"}:
            receipts = event["current_d1_pass_receipts"]
            if receipts:
                event["trigger_receipt_id"] = receipts[-1]["receipt_id"]
                event["trigger_verdict"] = "PASS"
        if event["event"] in {"D2_VERIFIED", "GLOBAL_PROGRESS"}:
            receipts = event["current_d2_pass_receipts"]
            if receipts:
                event["trigger_receipt_id"] = receipts[-1]["receipt_id"]
                event["trigger_verdict"] = "PASS"
        if event["event"] == "AMENDMENT":
            event["trigger_receipt_id"] = "AMENDMENT-001"
            event["trigger_verdict"] = "PASS"


def d1(receipt_id: str, cell_id: str) -> dict:
    digest = receipt_id.lower().replace("-", "").ljust(64, "a")[:64]
    return {
        "receipt_id": receipt_id,
        "cell_id": cell_id,
        "candidate_ref": {"sha256": digest},
        "verdict": "PASS",
        "invalidation_status": "CURRENT",
    }


def d2(receipt_id: str, go_id: str) -> dict:
    digest = receipt_id.lower().replace("-", "").ljust(64, "b")[:64]
    return {
        "receipt_id": receipt_id,
        "go_id": go_id,
        "candidate_ref": {"sha256": digest},
        "verdict": "PASS",
        "invalidation_status": "CURRENT",
    }


def progress_trace() -> dict:
    d1_one = d1("D1-001", "CELL-01.01")
    d1_two = d1("D1-002", "CELL-01.02")
    d2_one = d2("D2-001", "GO-01")
    packet = {
        "schema_version": "2.5.0",
        "record_type": "PROGRESS_TRACE",
        "status": "VALID",
        "run_id": "RUN-001",
        "history_immutable": True,
        "required_sets": [
            {
                "version": 1,
                "required_go_ids": ["GO-01", "GO-02"],
                "required_cells_by_go": {
                    "GO-01": ["CELL-01.01", "CELL-01.02"],
                    "GO-02": ["CELL-02.01"],
                },
            }
        ],
        "events": [
            progress_event(
                1,
                "DELIVERED",
                "WORKER",
                "CHECKER",
                "GO-01 CELL 1/2 已交付，请检查",
            ),
            progress_event(
                2,
                "WAKE_ACK",
                "CHECKER",
                "WORKER",
                "WAKE_ACK RUN-001 GO-01 CELL-01.01 R01",
            ),
            progress_event(
                3,
                "CHECKING",
                "CHECKER",
                "LOCAL",
                "收到 GO-01 CELL 1/2，开始检查",
            ),
            progress_event(
                4,
                "D1_ACCEPTED",
                "CHECKER",
                "LOCAL",
                "GO-01 CELL验收 1/2；下一状态=CELL-01.02",
                d1_receipts=[d1_one],
                accepted=1,
            ),
            progress_event(
                5,
                "D1_ACCEPTED",
                "CHECKER",
                "LOCAL",
                "GO-01 CELL验收 2/2；下一状态=GO_CANDIDATE_READY",
                cell_id="CELL-01.02",
                cell_ordinal=2,
                d1_receipts=[d1_one, d1_two],
                accepted=2,
            ),
            progress_event(
                6,
                "GO_CANDIDATE_READY",
                "CHECKER",
                "SUPERVISOR",
                "GO 1/2；本GO CELL 2/2已验收；当前状态=GO_CANDIDATE_READY",
                cell_id="",
                cell_ordinal=0,
                d1_receipts=[d1_one, d1_two],
                accepted=2,
                milestone_id="GO-01-CANDIDATE-V1",
            ),
            progress_event(
                7,
                "D2_VERIFIED",
                "VERIFIER",
                "SUPERVISOR",
                "D2 PASS GO-01",
                cell_id="",
                cell_ordinal=0,
                d1_receipts=[d1_one, d1_two],
                d2_receipts=[d2_one],
                accepted=2,
                verified=1,
            ),
            progress_event(
                8,
                "GLOBAL_PROGRESS",
                "SUPERVISOR",
                "OWNER",
                (
                    "RequiredSet v1；当前GO D1 CELL 2/2；"
                    "Required GO D2 1/2；D3=PENDING；Owner=PENDING"
                ),
                cell_id="",
                cell_ordinal=0,
                d1_receipts=[d1_one, d1_two],
                d2_receipts=[d2_one],
                accepted=2,
                verified=1,
            ),
        ],
        "evidence_refs": ["evidence/progress-trace.txt"],
    }
    bind_progress_events(packet)
    return packet


def progress_trace_with_run_milestones() -> dict:
    packet = progress_trace()
    latest = copy.deepcopy(packet["events"][-1])
    specs = [
        ("RUN_VERIFIED", "VERIFIER", "SUPERVISOR", "D3 PASS RUN-001"),
        (
            "GLOBAL_PROGRESS",
            "SUPERVISOR",
            "OWNER",
            "RequiredSet v1；D3=PASS；Owner=PENDING",
        ),
        ("OWNER_ACCEPTED", "OWNER", "SUPERVISOR", "OWNER_ACCEPTED RUN-001"),
        (
            "GLOBAL_PROGRESS",
            "SUPERVISOR",
            "OWNER",
            "RequiredSet v1；D3=PASS；Owner=OWNER_ACCEPTED",
        ),
    ]
    for event, actor, audience, message in specs:
        item = copy.deepcopy(latest)
        item.update(
            {
                "event": event,
                "actor": actor,
                "audience": audience,
                "status": event,
                "message": message,
                "d3_state": "PASS",
                "owner_acceptance_state": (
                    "OWNER_ACCEPTED"
                    if event == "OWNER_ACCEPTED" or "Owner=OWNER_ACCEPTED" in message
                    else "PENDING"
                ),
                "milestone_id": "",
            }
        )
        packet["events"].append(item)
    bind_progress_events(packet)
    for index, receipt_id in ((8, "D3-001"), (9, "D3-001"), (10, "OWNER-001"), (11, "OWNER-001")):
        packet["events"][index]["trigger_receipt_id"] = receipt_id
        packet["events"][index]["trigger_verdict"] = "PASS"
    return packet


def device_capacity_profile() -> dict:
    return {
        "schema_version": "2.5.0",
        "record_type": "DEVICE_CAPACITY_PROFILE",
        "status": "READY",
        "run_id": "RUN-001",
        "profile_id": "DCP-RUN-001",
        "version": 1,
        "captured_at": "2026-08-04T00:00:00Z",
        "cpu": {"model": "Test CPU", "logical_cores": 8},
        "memory": {"available_ram_mb": 16384},
        "gpu": {"applicable": False, "model": "N/A", "vram_mb": 0},
        "disk": {
            "free_mb": 102400,
            "read_mb_s": 500,
            "write_mb_s": 400,
        },
        "network": {
            "external_service_access": "LIMITED",
            "max_mbps": 100,
            "constraints": ["github.com may be unavailable"],
        },
        "process_limits": {
            "max_processes": 16,
            "allowed_ports": [3000, 8000],
            "safe_concurrency": 2,
        },
        "duration_budgets_seconds": {
            "single_command": 300,
            "full_test": 900,
            "build": 600,
            "cell_total": 3600,
        },
        "context_evidence_budgets": {
            "context_tokens": 120000,
            "evidence_mb": 1024,
        },
        "evidence_refs": ["evidence/device-capacity.txt"],
    }


def cumulative_engineering_load(*, version: int = 1, late: bool = False) -> dict:
    return {
        "schema_version": "2.5.0",
        "record_type": "CUMULATIVE_ENGINEERING_LOAD",
        "status": "CURRENT",
        "run_id": "RUN-001",
        "load_id": "CEL-RUN-001",
        "version": version,
        "device_capacity_profile_ref": {"id": "DCP-RUN-001", "version": 1},
        "baseline_ref": {"id": "SB-001", "version": version, "sha256": "b" * 64},
        "boundary_kind": "MEASURED_DEVIATION" if late else "RUN_FREEZE",
        "required_set_version": version,
        "measurements": {
            "accepted_cell_count": 18 if late else 0,
            "file_count": 600 if late else 80,
            "dependency_count": 45 if late else 12,
            "build_seconds": 420 if late else 60,
            "full_regression_seconds": 1800 if late else 240,
            "peak_ram_mb": 10000 if late else 3000,
            "peak_disk_mb": 16000 if late else 2000,
            "evidence_mb": 700 if late else 40,
            "hash_file_count": 900 if late else 100,
            "context_restore_seconds": 300 if late else 45,
            "external_tool_seconds": 90 if late else 0,
            "rollback_retry_seconds": 300 if late else 60,
            "coupling_score": 8 if late else 2,
        },
        "evidence_refs": [f"evidence/load-v{version}.txt"],
    }


def capacity_gate(*, outcome: str = "PASS", load_version: int = 1) -> dict:
    split_required = outcome == "SPLIT_REQUIRED"
    return {
        "schema_version": "2.5.0",
        "record_type": "CELL_CAPACITY_GATE",
        "status": "DECIDED",
        "run_id": "RUN-001",
        "go_id": "GO-01",
        "cell_id": "CELL-01.01",
        "round_id": "R01",
        "required_set_version": load_version,
        "phase": "PRE_DISPATCH",
        "device_capacity_profile_ref": {"id": "DCP-RUN-001", "version": 1},
        "cumulative_engineering_load_ref": {
            "id": "CEL-RUN-001",
            "version": load_version,
        },
        "go_outcome_sha256": "c" * 64,
        "acceptance_sha256": "d" * 64,
        "estimate": {
            "implementation_minutes": 20,
            "input_dependency_count": 3,
            "output_count": 2,
            "build_seconds": 60,
            "test_seconds": 180,
            "checker_seconds": 180,
            "regression_seconds": 240,
            "evidence_hash_cleanup_seconds": 90,
            "context_load_seconds": 60,
            "external_tool_seconds": 0,
            "rollback_retry_seconds": 120,
            "cumulative_coupling_score": 2,
            "peak_ram_mb": 6000,
            "peak_disk_mb": 8000,
            "requested_device_concurrency": 1,
        },
        "decision_inputs": {
            "available_ram_mb": 16384,
            "free_disk_mb": 102400,
            "safe_device_concurrency": 2,
            "cell_total_budget_seconds": 3600,
            "cumulative_full_regression_seconds": 1800 if load_version > 1 else 240,
            "cumulative_context_restore_seconds": 300 if load_version > 1 else 45,
            "cumulative_rollback_retry_seconds": 300 if load_version > 1 else 60,
            "cumulative_coupling_score": 8 if load_version > 1 else 2,
        },
        "logical_parallelism": 4,
        "decision": {
            "outcome": outcome,
            "dispatch_allowed": outcome == "PASS",
            "reason_codes": [
                "CUMULATIVE_TOTAL_EXCEEDS_CELL_BUDGET"
                if split_required
                else "WITHIN_CAPACITY"
            ],
        },
        "split_plan": {
            "successor_count": 2 if split_required else 0,
            "preserves_go_outcome_sha256": "c" * 64,
            "preserves_acceptance_sha256": "d" * 64,
            "creates_new_go": False,
            "creates_worker_or_subagent": False,
            "verification_weakened": False,
            "successor_cells": (
                [
                    {
                        "cell_id": "CELL-01.01A",
                        "depends_on": [],
                        "independently_deliverable": True,
                        "independently_d1_checkable": True,
                    },
                    {
                        "cell_id": "CELL-01.01B",
                        "depends_on": ["CELL-01.01A"],
                        "independently_deliverable": True,
                        "independently_d1_checkable": True,
                    },
                ]
                if split_required
                else []
            ),
        },
        "evidence_refs": ["evidence/cell-capacity-gate.txt"],
    }


def capacity_event(*, event: str = "CELL_SCOPE_EXCEEDED", successors: int = 0) -> dict:
    severe = event == "POST_DISPATCH_CELL_SPLIT" and successors >= 3
    return {
        "schema_version": "2.5.0",
        "record_type": "CELL_CAPACITY_EVENT",
        "status": "RECORDED",
        "run_id": "RUN-001",
        "go_id": "GO-01",
        "cell_id": "CELL-01.01",
        "round_id": "R01",
        "event": event,
        "actor": "WORKER" if event == "CELL_SCOPE_EXCEEDED" else "SUPERVISOR_RESPONSIBILITY",
        "worker_stopped": True,
        "worker_self_split": False,
        "returned_to": "CHECKER_RESPONSIBILITY",
        "checkpoint_ref": {"id": "CP-001", "sha256": "e" * 64},
        "successor_count": successors,
        "planning_defect": event == "POST_DISPATCH_CELL_SPLIT",
        "severity": "CELL_OVERSIZE_SEVERE" if severe else "NONE",
        "reevaluate_remaining_plan": severe,
        "reevaluate_device_budget": severe,
        "evidence_refs": ["evidence/capacity-event.txt"],
    }


def pin_audit(*, provenance: str = "NONE") -> dict:
    packet = {
        "schema_version": "2.5.0",
        "record_type": "THREAD_PIN_AUDIT",
        "status": "VALID",
        "run_id": "RUN-001",
        "task_thread_id": "thread-worker",
        "task_role": "WORKER",
        "lifecycle_state": "DISPATCHED",
        "pinned_state": False,
        "provenance": provenance,
        "owner_authorization_ref": "",
        "operations": [],
        "violation_history_retained": False,
        "pin_lifecycle_independent": True,
        "patrol": {
            "result": "NORMAL",
            "alert_code": "",
            "automatic_pin_attempted": False,
            "automatic_unpin_attempted": False,
            "owner_notified": False,
        },
        "evidence_refs": ["evidence/thread-pin-audit.txt"],
    }
    if provenance == "OWNER_MANUAL_UI":
        packet["pinned_state"] = True
        packet["operations"] = [
            {
                "sequence": 1,
                "action": "PIN",
                "actor": "OWNER",
                "tool": "CODEX_UI",
                "authorization_ref": "",
            }
        ]
    elif provenance == "OWNER_EXPLICIT_ITEM_AUTHORIZATION":
        packet["pinned_state"] = True
        packet["owner_authorization_ref"] = "owner-auth/PIN-thread-worker"
        packet["operations"] = [
            {
                "sequence": 1,
                "action": "PIN",
                "actor": "WORKER",
                "tool": "set_thread_pinned(true)",
                "authorization_ref": "owner-auth/PIN-thread-worker",
            }
        ]
    elif provenance == "AGENT_TOOL_CALL":
        packet["pinned_state"] = True
        packet["operations"] = [
            {
                "sequence": 1,
                "action": "PIN",
                "actor": "WORKER",
                "tool": "set_thread_pinned(true)",
                "authorization_ref": "",
            }
        ]
        packet["violation_history_retained"] = True
        packet["patrol"].update(
            {
                "result": "ALERT",
                "alert_code": "UNAUTHORIZED_THREAD_PIN",
                "owner_notified": True,
            }
        )
    elif provenance == "UNKNOWN":
        packet["pinned_state"] = True
        packet["patrol"].update(
            {
                "result": "ALERT",
                "alert_code": "PIN_PROVENANCE_UNKNOWN",
                "owner_notified": True,
            }
        )
    return packet


def test_runtime_contract_is_valid(tmp_path: Path) -> None:
    assert_pass(tmp_path, runtime_contract())


def test_runtime_contract_capabilities_fail_closed_under_optimized_python(
    tmp_path: Path,
) -> None:
    packet = runtime_contract()
    packet["worker_capabilities"]["read_thread"] = "PENDING"
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_CAPABILITY_UNAVAILABLE",
        optimized=True,
    )


def test_runtime_contract_rejects_duplicate_or_misbound_patrol(
    tmp_path: Path,
) -> None:
    packet = runtime_contract()
    packet["patrol"]["conversation_count"] = 2
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PATROL_UNIQUE")
    packet = runtime_contract()
    packet["patrol"]["model"] = "gpt-5.6-sol"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PATROL_MODEL")
    packet = runtime_contract()
    packet["patrol"]["interval_minutes"] = 20
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PATROL_DIFFICULTY_INTERVAL")


def test_runtime_contract_rejects_checker_or_supervisor_wait_drift(
    tmp_path: Path,
) -> None:
    packet = runtime_contract()
    packet["checker_binding"]["thread_id"] = "replacement-checker"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_CHECKER_BINDING")
    packet = runtime_contract()
    packet["supervisor_wait"]["positive_timeout_allowed"] = True
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_SUPERVISOR_WAIT_FORBIDDEN",
        optimized=True,
    )
    packet = runtime_contract()
    packet["supervisor_wait"]["wait_for_all_members_allowed"] = True
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_SUPERVISOR_WAIT_FORBIDDEN",
        optimized=True,
    )


def test_runtime_simulation_requires_every_unique_pass_scenario(
    tmp_path: Path,
) -> None:
    assert_pass(tmp_path, simulation())
    packet = simulation()
    packet["scenarios"].pop()
    assert_reject(tmp_path, packet, "SLK_RUNTIME_SIMULATION_INCOMPLETE")
    packet = simulation()
    packet["scenarios"].append(copy.deepcopy(packet["scenarios"][0]))
    assert_reject(tmp_path, packet, "SLK_RUNTIME_SIMULATION_DUPLICATE")
    packet = simulation()
    packet["scenarios"][0]["result"] = "PENDING"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_SIMULATION_NOT_PASS")


def test_wake_level_one_and_two_success(tmp_path: Path) -> None:
    assert_pass(tmp_path, wake_trace(success_level=1))
    assert_pass(tmp_path, wake_trace(success_level=2))


def test_wake_level_two_can_repair_archive_and_host_from_registry(
    tmp_path: Path,
) -> None:
    packet = wake_trace(success_level=2)
    packet["checker_binding"]["host_id"] = "stale-host"
    resolution = packet["attempts"][1]["resolution"]
    resolution.update(
        {
            "registry_host_id": "local",
            "was_archived": True,
            "unarchived": True,
            "host_repaired": True,
        }
    )
    packet["attempts"][1]["host_id"] = "local"
    assert_pass(tmp_path, packet)


def test_thread_not_found_never_guesses_or_creates_replacement(
    tmp_path: Path,
) -> None:
    assert_pass(tmp_path, failed_wake_trace())
    packet = failed_wake_trace()
    packet["attempts"][1]["resolution"]["guessed_id"] = True
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_WAKE_GUESSED_ID",
        optimized=True,
    )
    packet = failed_wake_trace()
    packet["attempts"][1]["resolution"]["replacement_created"] = True
    assert_reject(tmp_path, packet, "SLK_RUNTIME_WAKE_REPLACEMENT_FORBIDDEN")


def test_level_three_heartbeat_is_unique_and_ack_deletes_it(
    tmp_path: Path,
) -> None:
    assert_pass(tmp_path, wake_trace(success_level=3))
    packet = wake_trace(success_level=3)
    packet["attempts"][2]["heartbeat"]["heartbeat_count"] = 2
    assert_reject(tmp_path, packet, "SLK_RUNTIME_WAKE_HEARTBEAT_NOT_UNIQUE")
    packet = wake_trace(success_level=3)
    packet["temporary_heartbeat_state"] = "ACTIVE"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_WAKE_HEARTBEAT_NOT_CLEAN")


def test_all_three_failures_write_pending_wake_for_unique_patrol(
    tmp_path: Path,
) -> None:
    assert_pass(tmp_path, failed_wake_trace())
    assert_pass(tmp_path, pending_wake())
    packet = failed_wake_trace()
    packet["pending_wake_ref"] = ""
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PENDING_WAKE_REQUIRED")


def test_matching_ack_stops_escalation(tmp_path: Path) -> None:
    packet = wake_trace(success_level=1)
    packet["attempts"].append(attempt(2, "NO_ACK"))
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_WAKE_AFTER_ACK",
        optimized=True,
    )


def test_mechanical_checker_processing_evidence_also_stops_escalation(
    tmp_path: Path,
) -> None:
    packet = wake_trace(success_level=2)
    packet["status"] = "PROCESSING_STARTED"
    packet["attempts"][1]["result"] = "PROCESSING_STARTED"
    packet["attempts"][1].pop("ack")
    packet["attempts"][1]["processing_started_ref"] = (
        "evidence/checker-processing-thread-control.txt"
    )
    assert_pass(tmp_path, packet)
    packet["attempts"][1]["processing_started_ref"] = ""
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_WAKE_PROCESSING_EVIDENCE",
        optimized=True,
    )


def test_wake_is_worker_only_and_checker_only(tmp_path: Path) -> None:
    packet = wake_trace()
    packet["sender_role"] = "SUPERVISOR_RESPONSIBILITY"
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_WAKE_WORKER_ONLY",
        optimized=True,
    )
    packet = wake_trace()
    packet["receiver_responsibility"] = "VERIFIER_RESPONSIBILITY"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_WAKE_CHECKER_ONLY")


def test_wake_message_scope_timing_and_identity_fail_closed(tmp_path: Path) -> None:
    packet = wake_trace()
    packet["message"] = "完成，请检验"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_WAKE_MESSAGE_INVALID")
    packet = wake_trace(success_level=2)
    packet["attempts"][1]["message"] = "GO-03 CELL 26/30 已交付，请检查"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_WAKE_IDENTITY_DRIFT")
    packet = wake_trace(success_level=2)
    packet["attempts"][0]["wait_seconds"] = 121
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_WAKE_WAIT_TOO_LONG",
        optimized=True,
    )
    packet = wake_trace(success_level=2)
    packet["attempts"][1]["offset_seconds"] = 121
    assert_reject(tmp_path, packet, "SLK_RUNTIME_WAKE_OFFSET_INVALID")


def test_blocked_and_execution_failure_keep_worker_scope(tmp_path: Path) -> None:
    for state in ("BLOCKED", "EXECUTION_FAILURE"):
        packet = wake_trace()
        packet["delivery_state"] = state
        packet["message"] = f"GO-03 CELL 25/30 {state}，请检查"
        packet["attempts"][0]["message"] = packet["message"]
        assert_pass(tmp_path, packet)


def test_patrol_normal_pause_and_visible_subtask_are_not_alerts(
    tmp_path: Path,
) -> None:
    for run_state in ("FORMALLY_PAUSED", "LEGAL_BLOCKED", "WAITING_EXTERNAL"):
        packet = patrol_receipt()
        packet["run_state"] = run_state
        forward = patrol_item(packet, "FORWARD_MOTION")
        forward.update(
            {
                "finding": "LEGITIMATE_PAUSE",
                "result": "NORMAL",
                "legitimate_reason_ref": "pause/PAUSE-001",
            }
        )
        assert_pass(tmp_path, packet)
        forward["result"] = "ALERT"
        forward["alert_code"] = "UNEXPLAINED_STALL"
        assert_reject(tmp_path, packet, "SLK_RUNTIME_PATROL_FALSE_POSITIVE")


def test_patrol_detects_subagent_and_supervisor_wait_evidence(
    tmp_path: Path,
) -> None:
    packet = patrol_receipt()
    subagent = patrol_item(packet, "SUBAGENT_EVIDENCE")
    subagent.update(
        {
            "finding": "PROHIBITED_SUBAGENT_EVIDENCE",
            "result": "ALERT",
            "alert_code": "SUBAGENT_MISUSE",
        }
    )
    packet["run_state"] = "FORMALLY_PAUSED"
    patrol_item(packet, "FORWARD_MOTION").update(
        {
            "finding": "LEGITIMATE_PAUSE",
            "legitimate_reason_ref": "pause/PAUSE-001",
        }
    )
    assert_pass(tmp_path, packet)
    packet = patrol_receipt()
    wait = patrol_item(packet, "SUPERVISOR_WAIT")
    wait.update(
        {
            "finding": "POSITIVE_WAIT",
            "timeout_ms": 120000,
            "inside_loop": True,
            "result": "ALERT",
            "alert_code": "SUPERVISOR_WAIT_FORBIDDEN",
        }
    )
    assert_pass(tmp_path, packet)
    wait["result"] = "NORMAL"
    wait["alert_code"] = ""
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PATROL_MISSED_ALERT",
        optimized=True,
    )


def test_patrol_detects_stall_pending_wake_and_duplicate_patrol(
    tmp_path: Path,
) -> None:
    cases = (
        ("FORWARD_MOTION", "UNEXPLAINED_STALL", "UNEXPLAINED_STALL"),
        ("PENDING_WAKE", "UNCONSUMED_PENDING_WAKE", "PENDING_WAKE_UNCONSUMED"),
        ("PATROL_UNIQUENESS", "DUPLICATE_PATROL", "DUPLICATE_PATROL"),
    )
    for check_kind, finding, alert in cases:
        packet = patrol_receipt()
        item = patrol_item(packet, check_kind)
        item.update(
            {
                "finding": finding,
                "result": "ALERT",
                "alert_code": alert,
            }
        )
        assert_pass(tmp_path, packet)
        item["result"] = "NORMAL"
        item["alert_code"] = ""
        assert_reject(tmp_path, packet, "SLK_RUNTIME_PATROL_MISSED_ALERT")


def test_patrol_cannot_gain_authority_or_report_progress(tmp_path: Path) -> None:
    packet = patrol_receipt()
    packet["authority"] = "CHECKER_RESPONSIBILITY"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PATROL_AUTHORITY")
    packet = patrol_receipt()
    packet["actions"] = ["create_thread"]
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PATROL_ACTION_FORBIDDEN",
        optimized=True,
    )
    packet = patrol_receipt()
    packet["engineering_progress_reported"] = True
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PATROL_PROGRESS_FORBIDDEN")


def test_patrol_terminal_sequence_deletes_heartbeat_and_archives(
    tmp_path: Path,
) -> None:
    packet = patrol_receipt()
    packet.update({"status": "PATROL_CLOSED", "run_state": "LOOP_TERMINAL"})
    terminal = patrol_item(packet, "TERMINAL_CLOSURE")
    terminal.update({"finding": "PATROL_CLOSED", "result": "NORMAL"})
    packet["terminal_cleanup"] = {
        "loop_terminal_confirmed": True,
        "heartbeat_deleted": True,
        "conversation_archived": True,
    }
    assert_pass(tmp_path, packet)
    packet["terminal_cleanup"]["conversation_archived"] = False
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PATROL_NOT_CLOSED")


def test_progress_trace_validates_layered_reporting(tmp_path: Path) -> None:
    assert_pass(tmp_path, progress_trace())


def test_delivery_checking_and_rework_do_not_increment_accepted(
    tmp_path: Path,
) -> None:
    packet = progress_trace()
    packet["events"][0]["accepted_cell_count"] = 1
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PROGRESS_COUNT_MISMATCH",
        optimized=True,
    )
    packet = progress_trace()
    rework = copy.deepcopy(packet["events"][3])
    rework.update(
        {
            "sequence": 5,
            "event": "REWORK",
            "status": "REWORK",
            "message": "GO-01 CELL验收仍为 1/2；CELL-01.01进入R02返工",
        }
    )
    packet["events"].insert(4, rework)
    bind_progress_events(packet)
    assert_pass(tmp_path, packet)
    packet = progress_trace()
    forged = d1("D1-099", "CELL-01.01")
    packet["events"][0]["current_d1_pass_receipts"] = [forged]
    packet["events"][0]["accepted_cell_count"] = 1
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PROGRESS_COUNT_MISMATCH",
        optimized=True,
    )


def test_checker_must_ack_before_starting_inspection(tmp_path: Path) -> None:
    packet = progress_trace()
    packet["events"].pop(1)
    bind_progress_events(packet)
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PROGRESS_LAYER_CONFUSION")


def test_d1_pass_increments_once_and_duplicate_receipt_does_not(
    tmp_path: Path,
) -> None:
    packet = progress_trace()
    duplicate = copy.deepcopy(packet["events"][3])
    duplicate.update(
        {
            "sequence": 5,
            "event": "D1_ACCEPTED",
            "status": "D1_ACCEPTED",
            "message": "GO-01 CELL验收 1/2；重复回执不增加",
        }
    )
    packet["events"].insert(4, duplicate)
    bind_progress_events(packet)
    assert_pass(tmp_path, packet)
    duplicate["accepted_cell_count"] = 2
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PROGRESS_COUNT_MISMATCH")


def test_go_candidate_ready_is_not_d2_verified(tmp_path: Path) -> None:
    packet = progress_trace()
    packet["events"][5]["verified_go_count"] = 1
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PROGRESS_LAYER_CONFUSION",
        optimized=True,
    )


def test_checker_reports_supervisor_only_at_go_boundary(tmp_path: Path) -> None:
    packet = progress_trace()
    packet["events"][3]["audience"] = "SUPERVISOR"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PROGRESS_NOISE")
    packet = progress_trace()
    packet["events"].append(copy.deepcopy(packet["events"][5]))
    bind_progress_events(packet)
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PROGRESS_NOISE")


def test_amendment_recomputes_denominators_without_rewriting_history(
    tmp_path: Path,
) -> None:
    packet = progress_trace()
    packet["required_sets"].append(
        {
            "version": 2,
            "required_go_ids": ["GO-01"],
            "required_cells_by_go": {"GO-01": ["CELL-01.01"]},
        }
    )
    amendment = progress_event(
        9,
        "AMENDMENT",
        "SUPERVISOR",
        "OWNER",
        "RequiredSet v2；当前GO D1 CELL 1/1；Required GO D2 1/1",
        d1_receipts=[d1("D1-001", "CELL-01.01")],
        d2_receipts=[d2("D2-001", "GO-01")],
        accepted=1,
        verified=1,
    )
    amendment.update(
        {
            "required_set_version": 2,
            "required_cell_total": 1,
            "required_go_total": 1,
            "recomputed": True,
        }
    )
    packet["events"].append(amendment)
    bind_progress_events(packet)
    assert_pass(tmp_path, packet)
    packet["events"][-1]["required_cell_total"] = 2
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PROGRESS_AMENDMENT_STALE")


def test_other_roles_and_generic_complete_cannot_emit_progress(
    tmp_path: Path,
) -> None:
    packet = progress_trace()
    packet["events"][7]["actor"] = "RUN_PATROL"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PROGRESS_ROLE_FORBIDDEN")
    packet = progress_trace()
    packet["events"][7]["message"] = "已完成"
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PROGRESS_LAYER_CONFUSION",
        optimized=True,
    )


def test_all_wake_levels_reuse_one_progress_identity(tmp_path: Path) -> None:
    packet = failed_wake_trace()
    packet["attempts"][2]["message"] = "GO-03 CELL 25/31 已交付，请检查"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_WAKE_IDENTITY_DRIFT")


def test_capacity_profiles_load_and_early_gate_are_valid(tmp_path: Path) -> None:
    assert_pass(tmp_path, device_capacity_profile())
    assert_pass(tmp_path, cumulative_engineering_load())
    assert_pass(tmp_path, capacity_gate())


def test_capacity_same_small_surface_splits_after_cumulative_growth(
    tmp_path: Path,
) -> None:
    early = capacity_gate()
    late = capacity_gate(outcome="SPLIT_REQUIRED", load_version=2)
    assert early["estimate"] == late["estimate"]
    assert_pass(tmp_path, early)
    assert_pass(tmp_path, cumulative_engineering_load(version=2, late=True))
    assert_pass(tmp_path, late)
    late["decision"] = {
        "outcome": "PASS",
        "dispatch_allowed": True,
        "reason_codes": ["WITHIN_CAPACITY"],
    }
    assert_reject(tmp_path, late, "SLK_RUNTIME_CAPACITY_SPLIT_REQUIRED")


def test_capacity_unknown_and_marketing_text_fail_closed(tmp_path: Path) -> None:
    packet = device_capacity_profile()
    packet["memory"]["available_ram_mb"] = "UNKNOWN"
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_CAPACITY_UNKNOWN",
        optimized=True,
    )
    packet = device_capacity_profile()
    packet["cpu"]["model"] = "高性能电脑"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_CAPACITY_UNKNOWN")


def test_capacity_low_ram_disk_or_concurrency_rejects_heavy_cell(
    tmp_path: Path,
) -> None:
    for field, value in (
        ("available_ram_mb", 5000),
        ("free_disk_mb", 7000),
        ("safe_device_concurrency", 0),
    ):
        packet = capacity_gate()
        packet["decision_inputs"][field] = value
        assert_reject(
            tmp_path,
            packet,
            "SLK_RUNTIME_CAPACITY_BLOCKED",
            optimized=field == "available_ram_mb",
        )


def test_capacity_gate_must_pass_before_dispatch(tmp_path: Path) -> None:
    packet = capacity_gate(outcome="SPLIT_REQUIRED", load_version=2)
    packet["decision"]["dispatch_allowed"] = True
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_CAPACITY_DISPATCH_FORBIDDEN",
        optimized=True,
    )
    packet = capacity_gate(outcome="CAPACITY_BLOCKED")
    packet["decision"]["dispatch_allowed"] = True
    assert_reject(tmp_path, packet, "SLK_RUNTIME_CAPACITY_DISPATCH_FORBIDDEN")


def test_capacity_presplit_preserves_go_acceptance_and_checkability(
    tmp_path: Path,
) -> None:
    packet = capacity_gate(outcome="SPLIT_REQUIRED", load_version=2)
    assert_pass(tmp_path, packet)
    packet["split_plan"]["preserves_acceptance_sha256"] = "f" * 64
    assert_reject(tmp_path, packet, "SLK_RUNTIME_CAPACITY_SPLIT_INVALID")
    packet = capacity_gate(outcome="SPLIT_REQUIRED", load_version=2)
    packet["split_plan"]["successor_cells"][1]["independently_d1_checkable"] = False
    assert_reject(tmp_path, packet, "SLK_RUNTIME_CAPACITY_SPLIT_INVALID")


def test_capacity_worker_scope_exceeded_stops_without_self_split(
    tmp_path: Path,
) -> None:
    packet = capacity_event()
    assert_pass(tmp_path, packet)
    packet["worker_self_split"] = True
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_CAPACITY_WORKER_SELF_SPLIT",
        optimized=True,
    )
    packet = capacity_event()
    packet["worker_stopped"] = False
    assert_reject(tmp_path, packet, "SLK_RUNTIME_CAPACITY_SCOPE_EXCEEDED")


def test_capacity_post_dispatch_three_or_more_is_always_severe(
    tmp_path: Path,
) -> None:
    for successors in (3, 6, 7, 8):
        assert_pass(
            tmp_path,
            capacity_event(
                event="POST_DISPATCH_CELL_SPLIT",
                successors=successors,
            ),
        )
    packet = capacity_event(event="POST_DISPATCH_CELL_SPLIT", successors=6)
    packet["severity"] = "NONE"
    packet["reevaluate_remaining_plan"] = False
    packet["reevaluate_device_budget"] = False
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_CAPACITY_OVERSIZE_SEVERE",
        optimized=True,
    )


def test_capacity_actual_peak_feedback_tightens_later_budget(
    tmp_path: Path,
) -> None:
    assert_pass(tmp_path, capacity_gate())
    later = capacity_gate()
    later["cumulative_engineering_load_ref"]["version"] = 2
    later["required_set_version"] = 2
    later["decision_inputs"]["available_ram_mb"] = 5500
    assert_reject(tmp_path, later, "SLK_RUNTIME_CAPACITY_BLOCKED")


def test_capacity_logical_parallelism_is_not_device_concurrency(
    tmp_path: Path,
) -> None:
    packet = capacity_gate()
    packet["logical_parallelism"] = 8
    packet["estimate"]["requested_device_concurrency"] = 1
    assert_pass(tmp_path, packet)
    packet["estimate"]["requested_device_concurrency"] = 3
    assert_reject(tmp_path, packet, "SLK_RUNTIME_CAPACITY_BLOCKED")


def test_capacity_split_recomputes_progress_denominator_without_acceptance(
    tmp_path: Path,
) -> None:
    packet = progress_trace()
    packet["required_sets"].append(
        {
            "version": 2,
            "required_go_ids": ["GO-01", "GO-02"],
            "required_cells_by_go": {
                "GO-01": ["CELL-01.01", "CELL-01.02A", "CELL-01.02B"],
                "GO-02": ["CELL-02.01"],
            },
            "amendment_reason": "CAPACITY_SPLIT",
            "supersedes_cell_id": "CELL-01.02",
        }
    )
    amendment = progress_event(
        9,
        "AMENDMENT",
        "SUPERVISOR",
        "OWNER",
        "RequiredSet v2；容量拆分；当前GO D1 CELL 1/3；Required GO D2 0/2",
        d1_receipts=[d1("D1-001", "CELL-01.01")],
        accepted=1,
        verified=0,
    )
    amendment.update(
        {
            "required_set_version": 2,
            "required_cell_total": 3,
            "required_go_total": 2,
            "recomputed": True,
        }
    )
    packet["events"].append(amendment)
    bind_progress_events(packet)
    assert_pass(tmp_path, packet)
    packet["events"][-1]["accepted_cell_count"] = 2
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PROGRESS_COUNT_MISMATCH",
        optimized=True,
    )


def test_pin_creation_dispatch_and_lifecycle_never_infer_authority(
    tmp_path: Path,
) -> None:
    for state in (
        "CREATED",
        "DISPATCHED",
        "ACTIVE",
        "WAITING_RECEIPT",
        "BLOCKED",
        "REWORK",
        "VERIFYING",
        "MILESTONE",
        "IMPORTANT",
    ):
        packet = pin_audit()
        packet["lifecycle_state"] = state
        assert_pass(tmp_path, packet)


def test_pin_all_slk_technical_roles_and_patrol_are_default_denied(
    tmp_path: Path,
) -> None:
    packet = runtime_contract()
    assert_pass(tmp_path, packet)
    assert packet["thread_pin_policy"]["technical_roles"] == SLK_TECHNICAL_ROLES
    assert packet["thread_pin_policy"]["patrol_pin_capability"] == "DENIED"
    packet["thread_pin_policy"]["technical_role_pin_allowed_by_default"] = True
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PIN_CAPABILITY_FORBIDDEN",
        optimized=True,
    )


def test_pin_patrol_cannot_pin_or_unpin(tmp_path: Path) -> None:
    audit = pin_audit()
    audit["task_role"] = "RUN_PATROL"
    assert_pass(tmp_path, audit)
    for action in ("set_thread_pinned(true)", "set_thread_pinned(false)"):
        packet = patrol_receipt()
        packet["actions"] = [action]
        assert_reject(
            tmp_path,
            packet,
            "SLK_RUNTIME_PATROL_ACTION_FORBIDDEN",
            optimized=action.endswith("true)"),
        )


def test_pin_owner_manual_and_exact_authorization_are_not_alerted(
    tmp_path: Path,
) -> None:
    assert_pass(tmp_path, pin_audit(provenance="OWNER_MANUAL_UI"))
    assert_pass(
        tmp_path,
        pin_audit(provenance="OWNER_EXPLICIT_ITEM_AUTHORIZATION"),
    )
    packet = pin_audit(provenance="OWNER_EXPLICIT_ITEM_AUTHORIZATION")
    packet["owner_authorization_ref"] = "owner-auth/PIN-another-task"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PIN_UNAUTHORIZED")


def test_pin_agent_call_stably_alerts(tmp_path: Path) -> None:
    assert_pass(tmp_path, pin_audit(provenance="AGENT_TOOL_CALL"))
    packet = pin_audit(provenance="AGENT_TOOL_CALL")
    packet["patrol"]["result"] = "NORMAL"
    packet["patrol"]["alert_code"] = ""
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PIN_UNAUTHORIZED",
        optimized=True,
    )


def test_pin_unknown_provenance_alerts_without_automatic_unpin(
    tmp_path: Path,
) -> None:
    assert_pass(tmp_path, pin_audit(provenance="UNKNOWN"))
    packet = pin_audit(provenance="UNKNOWN")
    packet["patrol"]["automatic_unpin_attempted"] = True
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PIN_AUTO_ACTION_FORBIDDEN",
        optimized=True,
    )
    packet = pin_audit(provenance="UNKNOWN")
    packet["patrol"]["alert_code"] = ""
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PIN_PROVENANCE_UNKNOWN")


def test_pin_then_unpin_retains_unauthorized_violation(tmp_path: Path) -> None:
    packet = pin_audit(provenance="AGENT_TOOL_CALL")
    packet["operations"].append(
        {
            "sequence": 2,
            "action": "UNPIN",
            "actor": "WORKER",
            "tool": "set_thread_pinned(false)",
            "authorization_ref": "",
        }
    )
    packet["pinned_state"] = False
    assert_pass(tmp_path, packet)
    packet["violation_history_retained"] = False
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PIN_HISTORY_REQUIRED",
        optimized=True,
    )


def index_wake_trace() -> dict:
    packet = wake_trace()
    packet.update(
        {
            "go_id": "GO-01",
            "cell_id": "CELL-01.01",
            "cell_ordinal": 1,
            "required_cell_total": 2,
            "message": "GO-01 CELL 1/2 已交付，请检查",
        }
    )
    first = packet["attempts"][0]
    first["message"] = packet["message"]
    first["ack"] = {
        "message": "WAKE_ACK RUN-001 GO-01 CELL-01.01 R01",
        "run_id": "RUN-001",
        "go_id": "GO-01",
        "cell_id": "CELL-01.01",
        "round_id": "R01",
    }
    return packet


def runtime_index() -> dict:
    progress = progress_trace()
    progress["events"] = progress["events"][:3]
    return {
        "schema_version": "2.5.0",
        "record_type": "RUN_RUNTIME_INDEX",
        "status": "COMPLETE",
        "run_id": "RUN-001",
        "index_version": 1,
        "runtime_contract": runtime_contract(),
        "dispatches": [
            {
                "dispatch_id": "DISPATCH-001",
                "run_id": "RUN-001",
                "go_id": "GO-01",
                "cell_id": "CELL-01.01",
                "cell_ordinal": 1,
                "required_cell_total": 2,
                "round_id": "R01",
                "required_set_version": 1,
            }
        ],
        "capacity_gates": [capacity_gate()],
        "wake_traces": [index_wake_trace()],
        "progress_trace": progress,
        "patrol_receipts": [patrol_receipt()],
        "evidence_refs": ["evidence/run-runtime-index.txt"],
    }


def test_redo_slk_pin_roles_exclude_glk_roles_and_reject_extras(
    tmp_path: Path,
) -> None:
    packet = runtime_contract()
    packet["thread_pin_policy"] = {
        "technical_roles": [
            "SUPERVISOR_RESPONSIBILITY",
            "CHECKER_RESPONSIBILITY",
            "VERIFIER_RESPONSIBILITY",
            "WORKER",
        ],
        "technical_role_pin_allowed_by_default": False,
        "set_thread_pinned_true_capability": "DENIED",
        "owner_manual_allowed": True,
        "owner_explicit_item_authorization_allowed": True,
        "inferred_authorization_allowed": False,
        "patrol_pin_capability": "DENIED",
        "patrol_auto_unpin_allowed": False,
        "pin_lifecycle_independent": True,
        "unauthorized_history_persists_after_unpin": True,
    }
    assert_pass(tmp_path, packet)
    packet["thread_pin_policy"]["technical_roles"].append("EXTRA_ROLE")
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PIN_ROLE_INVALID",
        optimized=True,
    )
    audit = pin_audit()
    audit["task_role"] = "NON_SLK_ROLE"
    assert_reject(
        tmp_path,
        audit,
        "SLK_RUNTIME_PIN_ROLE_INVALID",
        optimized=True,
    )


def test_redo_supervisor_positive_wait_is_alerted_even_outside_loop(
    tmp_path: Path,
) -> None:
    packet = patrol_receipt()
    wait = patrol_item(packet, "SUPERVISOR_WAIT")
    wait.update(
        {
            "finding": "POSITIVE_WAIT",
            "timeout_ms": 120000,
            "inside_loop": False,
            "result": "NORMAL",
            "alert_code": "",
        }
    )
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PATROL_MISSED_ALERT",
        optimized=True,
    )
    zero = patrol_receipt()
    assert_pass(tmp_path, zero)
    for field, finding in (("looped", "LOOPED_WAIT"), ("wait_all", "WAIT_ALL")):
        packet = patrol_receipt()
        wait = patrol_item(packet, "SUPERVISOR_WAIT")
        wait.update(
            {
                "finding": finding,
                field: True,
                "result": "ALERT",
                "alert_code": "SUPERVISOR_WAIT_FORBIDDEN",
            }
        )
        assert_pass(tmp_path, packet)
        wait["result"] = "NORMAL"
        wait["alert_code"] = ""
        assert_reject(tmp_path, packet, "SLK_RUNTIME_PATROL_MISSED_ALERT")


def test_redo_d2_requires_exactly_one_bound_supervisor_progress(
    tmp_path: Path,
) -> None:
    missing = progress_trace()
    missing["events"].pop()
    assert_reject(
        tmp_path,
        missing,
        "SLK_RUNTIME_PROGRESS_MILESTONE_MISSING",
        optimized=True,
    )
    duplicate = progress_trace()
    extra = copy.deepcopy(duplicate["events"][-1])
    extra["sequence"] = 9
    extra["event_id"] = "PE-009"
    duplicate["events"].append(extra)
    assert_reject(tmp_path, duplicate, "SLK_RUNTIME_PROGRESS_MILESTONE_DUPLICATE")
    wrong = progress_trace()
    wrong["events"][-1]["trigger_event_id"] = "PE-006"
    assert_reject(tmp_path, wrong, "SLK_RUNTIME_PROGRESS_TRIGGER_INVALID")


def test_redo_go_candidate_requires_final_d1_trigger_and_is_unique(
    tmp_path: Path,
) -> None:
    wrong_trigger = progress_trace()
    wrong_trigger["events"][5]["trigger_event_id"] = "PE-004"
    assert_reject(
        tmp_path,
        wrong_trigger,
        "SLK_RUNTIME_PROGRESS_TRIGGER_INVALID",
        optimized=True,
    )

    duplicate = progress_trace()
    extra = copy.deepcopy(duplicate["events"][5])
    extra["milestone_id"] = "GO-01-CANDIDATE-V1-DUPLICATE"
    duplicate["events"].insert(6, extra)
    bind_progress_events(duplicate)
    duplicate["events"][6]["trigger_event_id"] = "PE-005"
    duplicate["events"][7]["trigger_event_id"] = "PE-007"
    duplicate["events"][8]["trigger_event_id"] = "PE-008"
    assert_reject(
        tmp_path,
        duplicate,
        "SLK_RUNTIME_PROGRESS_MILESTONE_DUPLICATE",
    )


def test_redo_required_set_amendment_progress_is_unique_and_ordered(
    tmp_path: Path,
) -> None:
    required_v2 = {
        "version": 2,
        "required_go_ids": ["GO-01"],
        "required_cells_by_go": {"GO-01": ["CELL-01.01"]},
    }
    missing = progress_trace()
    missing["required_sets"].append(copy.deepcopy(required_v2))
    assert_reject(
        tmp_path,
        missing,
        "SLK_RUNTIME_PROGRESS_MILESTONE_MISSING",
        optimized=True,
    )

    packet = progress_trace()
    packet["required_sets"].append(copy.deepcopy(required_v2))
    amendment = progress_event(
        9,
        "AMENDMENT",
        "SUPERVISOR",
        "OWNER",
        "RequiredSet v2；当前GO D1 CELL 1/1；Required GO D2 1/1",
        d1_receipts=[d1("D1-001", "CELL-01.01")],
        d2_receipts=[d2("D2-001", "GO-01")],
        accepted=1,
        verified=1,
    )
    amendment.update(
        {
            "required_set_version": 2,
            "required_cell_total": 1,
            "required_go_total": 1,
            "recomputed": True,
        }
    )
    packet["events"].append(amendment)
    bind_progress_events(packet)
    assert_pass(tmp_path, packet)

    duplicate = copy.deepcopy(packet)
    duplicate["events"].append(copy.deepcopy(duplicate["events"][-1]))
    bind_progress_events(duplicate)
    assert_reject(
        tmp_path,
        duplicate,
        "SLK_RUNTIME_PROGRESS_MILESTONE_DUPLICATE",
    )

    wrong_order = copy.deepcopy(packet)
    premature = progress_event(
        9,
        "DELIVERED",
        "WORKER",
        "CHECKER",
        "GO-01 CELL 1/1 已交付，请检查",
        accepted=0,
        verified=0,
    )
    premature.update(
        {
            "required_set_version": 2,
            "required_cell_total": 1,
            "required_go_total": 1,
        }
    )
    wrong_order["events"].insert(-1, premature)
    bind_progress_events(wrong_order)
    assert_reject(
        tmp_path,
        wrong_order,
        "SLK_RUNTIME_PROGRESS_TRIGGER_INVALID",
    )


def test_redo_run_and_owner_milestones_require_bound_supervisor_progress(
    tmp_path: Path,
) -> None:
    assert_pass(tmp_path, progress_trace_with_run_milestones())
    packet = progress_trace_with_run_milestones()
    packet["events"] = packet["events"][:9]
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PROGRESS_MILESTONE_MISSING",
        optimized=True,
    )
    packet = progress_trace_with_run_milestones()
    packet["events"].pop()
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PROGRESS_MILESTONE_MISSING")


def test_redo_patrol_cycle_requires_complete_unique_checklist(
    tmp_path: Path,
) -> None:
    packet = patrol_receipt()
    packet["checklist"] = []
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE",
        optimized=True,
    )
    packet = patrol_receipt()
    packet["checklist"].append(copy.deepcopy(packet["checklist"][0]))
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PATROL_CHECKLIST_DUPLICATE")
    packet = patrol_receipt()
    packet["checklist"][0]["check_kind"] = "FREE_TEXT_CHECK"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE")


def test_redo_runtime_index_requires_every_dispatch_artifact(
    tmp_path: Path,
) -> None:
    assert_pass(tmp_path, runtime_index())
    for field in ("wake_traces", "patrol_receipts"):
        packet = runtime_index()
        packet[field] = []
        assert_reject(
            tmp_path,
            packet,
            "SLK_RUNTIME_INDEX_MISSING",
            optimized=field == "wake_traces",
        )
    packet = runtime_index()
    packet["progress_trace"] = {}
    assert_reject(tmp_path, packet, "SLK_RUNTIME_INDEX_MISSING")
    packet = runtime_index()
    packet["wake_traces"][0]["cell_id"] = "CELL-OTHER"
    assert_reject(tmp_path, packet, "SLK_RUNTIME_INDEX_SCOPE")
    packet = runtime_index()
    packet["capacity_gates"].append(copy.deepcopy(packet["capacity_gates"][0]))
    assert_reject(tmp_path, packet, "SLK_RUNTIME_INDEX_DUPLICATE")
    packet = runtime_index()
    extra = copy.deepcopy(packet["wake_traces"][0])
    extra["cell_id"] = "CELL-EXTRA"
    packet["wake_traces"].append(extra)
    assert_reject(tmp_path, packet, "SLK_RUNTIME_INDEX_EXTRA")
    packet = runtime_index()
    packet["progress_trace"]["events"] = packet["progress_trace"]["events"][1:]
    bind_progress_events(packet["progress_trace"])
    assert_reject(tmp_path, packet, "SLK_RUNTIME_INDEX_MISSING")
    packet = runtime_index()
    packet["runtime_contract"]["schema_version"] = "2.4.0"
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_SCHEMA_VERSION",
        optimized=True,
    )


def test_redo_runtime_index_capacity_gate_binds_dispatch_round(
    tmp_path: Path,
) -> None:
    packet = runtime_index()
    packet["dispatches"][0]["round_id"] = "R02"
    packet["wake_traces"][0]["round_id"] = "R02"
    packet["wake_traces"][0]["attempts"][0]["ack"]["round_id"] = "R02"
    packet["wake_traces"][0]["attempts"][0]["ack"]["message"] = (
        "WAKE_ACK RUN-001 GO-01 CELL-01.01 R02"
    )
    for event in packet["progress_trace"]["events"]:
        event["round_id"] = "R02"
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_INDEX_SCOPE",
        optimized=True,
    )


def test_redo_patrol_interval_is_bound_to_frozen_workload_class(
    tmp_path: Path,
) -> None:
    for workload_class, interval in (("LOW", 10), ("MEDIUM", 15), ("HIGH", 30)):
        packet = runtime_contract()
        packet["workload_class"] = workload_class
        packet["patrol"]["interval_minutes"] = interval
        assert_pass(tmp_path, packet)
    packet = runtime_contract()
    packet["workload_class"] = "LOW"
    packet["patrol"]["interval_minutes"] = 30
    assert_reject(
        tmp_path,
        packet,
        "SLK_RUNTIME_PATROL_DIFFICULTY_INTERVAL",
        optimized=True,
    )
