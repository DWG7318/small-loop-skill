from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, Iterable

import yaml


VERSION = "2.5.0"
WAKE_OFFSETS = {1: 0, 2: 120, 3: 240, 4: 360}
WAKE_ACTIONS = {
    1: "SEND_MESSAGE_TO_THREAD",
    2: "READ_LIST_RESOLVE_RESEND",
    3: "UPSERT_CHECKER_WAKE_HEARTBEAT",
    4: "WRITE_PENDING_WAKE",
}
REQUIRED_CAPABILITIES = {
    "send_message_to_thread",
    "read_thread",
    "list_threads",
    "unarchive_thread",
    "bounded_ack_wait",
    "temporary_heartbeat_upsert",
    "temporary_heartbeat_delete",
    "pending_wake_write",
}
REQUIRED_SCENARIOS = {
    "WAKE_LEVEL1_SUCCESS",
    "WAKE_LEVEL2_SUCCESS",
    "WAKE_ARCHIVE_HOST_REPAIR",
    "WAKE_THREAD_NOT_FOUND_NO_REPLACEMENT",
    "WAKE_LEVEL3_HEARTBEAT_UNIQUE_CLEANUP",
    "WAKE_LEVEL4_PENDING_PATROL",
    "WAKE_ACK_STOPS_ESCALATION",
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
}
METHOD_PIN_ROLES = {
    "SUPERVISOR_RESPONSIBILITY",
    "CHECKER_RESPONSIBILITY",
    "VERIFIER_RESPONSIBILITY",
    "WORKER",
    "RUN_PATROL",
    "ROUTER",
    "GRAPHER",
}
PROHIBITED_PATROL_ACTIONS = {
    "create_thread",
    "fork_thread",
    "spawn_agent",
    "delegate_task",
    "fix",
    "dispatch",
    "verify",
    "accept",
}
SUBAGENT_EVIDENCE = {
    "spawn_agent",
    "delegate_task",
    "HIDDEN_AGENT",
    "BACKGROUND_AGENT",
}
MARKETING_CAPACITY = {"高性能电脑", "资源充足", "POWERFUL", "HIGH_PERFORMANCE"}


class ValidationError(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def fail(code: str, detail: str) -> None:
    raise ValidationError(code, detail)


def mapping(value: object, code: str, name: str) -> dict:
    if not isinstance(value, dict):
        fail(code, f"{name} must be an object")
    return value


def sequence(value: object, code: str, name: str) -> list:
    if not isinstance(value, list):
        fail(code, f"{name} must be a list")
    return value


def text(value: object, code: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(code, f"{name} must be non-empty text")
    return value


def number(value: object, code: str, name: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum:
        fail(code, f"{name} must be numeric and >= {minimum}")
    return float(value)


def integer(value: object, code: str, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        fail(code, f"{name} must be an integer and >= {minimum}")
    return value


def boolean(value: object, code: str, name: str) -> bool:
    if not isinstance(value, bool):
        fail(code, f"{name} must be boolean")
    return value


def evidence(value: object, code: str = "SLK_RUNTIME_EVIDENCE_REQUIRED") -> None:
    values = sequence(value, code, "evidence_refs")
    if not values or any(not isinstance(item, str) or not item.strip() for item in values):
        fail(code, "evidence_refs must contain non-empty immutable references")


def sha256(value: object, code: str, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        fail(code, f"{name} must be a lowercase sha256")
    return value


def ref(value: object, code: str, name: str, *, hashed: bool = False) -> dict:
    item = mapping(value, code, name)
    text(item.get("id"), code, f"{name}.id")
    if "version" in item:
        integer(item.get("version"), code, f"{name}.version", minimum=1)
    if hashed:
        sha256(item.get("sha256"), code, f"{name}.sha256")
    return item


def validate_common(packet: dict) -> None:
    if packet.get("schema_version") != VERSION:
        fail("SLK_RUNTIME_SCHEMA_VERSION", f"expected {VERSION}")
    text(packet.get("record_type"), "SLK_RUNTIME_RECORD_TYPE", "record_type")


def validate_run_runtime_contract(packet: dict) -> None:
    if packet.get("status") != "READY":
        fail("SLK_RUNTIME_NOT_READY", "runtime contract must be READY")
    run_id = text(packet.get("run_id"), "SLK_RUNTIME_RUN_ID", "run_id")
    ref(packet.get("baseline_ref"), "SLK_RUNTIME_BASELINE_REF", "baseline_ref", hashed=True)
    formal = mapping(
        packet.get("formal_conversations"),
        "SLK_RUNTIME_FORMAL_TOPOLOGY",
        "formal_conversations",
    )
    if set(formal) != {"CONTROL", "WORKER"}:
        fail("SLK_RUNTIME_FORMAL_TOPOLOGY", "formal topology is exactly Control + Worker")
    control = text(formal.get("CONTROL"), "SLK_RUNTIME_FORMAL_TOPOLOGY", "CONTROL")
    text(formal.get("WORKER"), "SLK_RUNTIME_FORMAL_TOPOLOGY", "WORKER")

    patrol = mapping(packet.get("patrol"), "SLK_RUNTIME_PATROL_UNIQUE", "patrol")
    if patrol.get("conversation_count") != 1 or patrol.get("heartbeat_count") != 1:
        fail("SLK_RUNTIME_PATROL_UNIQUE", "exactly one Patrol and heartbeat are required")
    if patrol.get("model") != "gpt-5.6-luna" or patrol.get("reasoning_effort") != "xhigh":
        fail("SLK_RUNTIME_PATROL_MODEL", "Patrol requires gpt-5.6-luna + xhigh")
    if patrol.get("interval_minutes") not in {10, 15, 30}:
        fail("SLK_RUNTIME_PATROL_INTERVAL", "Patrol interval must be 10, 15, or 30")
    text(patrol.get("conversation_id"), "SLK_RUNTIME_PATROL_UNIQUE", "patrol.conversation_id")
    expected_heartbeat = f"SLK-PATROL-{run_id}"
    if patrol.get("heartbeat_id") != expected_heartbeat:
        fail("SLK_RUNTIME_PATROL_UNIQUE", "Patrol heartbeat must be deterministic")

    binding = mapping(
        packet.get("checker_binding"),
        "SLK_RUNTIME_CHECKER_BINDING",
        "checker_binding",
    )
    if binding.get("thread_id") != control:
        fail("SLK_RUNTIME_CHECKER_BINDING", "Checker is Control in CHECKER_RESPONSIBILITY")
    text(binding.get("host_id"), "SLK_RUNTIME_CHECKER_BINDING", "checker_binding.host_id")

    capabilities = mapping(
        packet.get("worker_capabilities"),
        "SLK_RUNTIME_CAPABILITY_UNAVAILABLE",
        "worker_capabilities",
    )
    if set(capabilities) != REQUIRED_CAPABILITIES or any(
        capabilities.get(name) != "AVAILABLE" for name in REQUIRED_CAPABILITIES
    ):
        fail("SLK_RUNTIME_CAPABILITY_UNAVAILABLE", "all Worker wake capabilities must be AVAILABLE")

    wait = mapping(
        packet.get("supervisor_wait"),
        "SLK_RUNTIME_SUPERVISOR_WAIT_FORBIDDEN",
        "supervisor_wait",
    )
    if (
        wait.get("positive_timeout_allowed") is not False
        or wait.get("loop_allowed") is not False
        or wait.get("snapshot_timeout_zero_allowed") is not True
    ):
        fail("SLK_RUNTIME_SUPERVISOR_WAIT_FORBIDDEN", "Supervisor may only take zero-time snapshots")

    required = mapping(packet.get("required_sets"), "SLK_RUNTIME_REQUIRED_SET", "required_sets")
    integer(required.get("version"), "SLK_RUNTIME_REQUIRED_SET", "required_sets.version", minimum=1)
    gos = sequence(required.get("required_go_ids"), "SLK_RUNTIME_REQUIRED_SET", "required_go_ids")
    cells = mapping(
        required.get("required_cells_by_go"),
        "SLK_RUNTIME_REQUIRED_SET",
        "required_cells_by_go",
    )
    if not gos or len(gos) != len(set(gos)) or set(cells) != set(gos):
        fail("SLK_RUNTIME_REQUIRED_SET", "Required GO/CELL set must be complete and unique")
    if any(not isinstance(values, list) or not values for values in cells.values()):
        fail("SLK_RUNTIME_REQUIRED_SET", "every Required GO needs at least one CELL")

    ref(
        packet.get("device_capacity_profile_ref"),
        "SLK_RUNTIME_CAPACITY_UNKNOWN",
        "device_capacity_profile_ref",
    )
    ref(
        packet.get("cumulative_engineering_load_ref"),
        "SLK_RUNTIME_CAPACITY_UNKNOWN",
        "cumulative_engineering_load_ref",
    )
    policy = mapping(
        packet.get("cell_capacity_policy"),
        "SLK_RUNTIME_CAPACITY_DISPATCH_FORBIDDEN",
        "cell_capacity_policy",
    )
    if (
        policy.get("required_before_dispatch") is not True
        or policy.get("allowed_dispatch_outcome") != "PASS"
        or policy.get("worker_self_split_allowed") is not False
    ):
        fail("SLK_RUNTIME_CAPACITY_DISPATCH_FORBIDDEN", "capacity PASS is required before dispatch")
    pin = mapping(
        packet.get("thread_pin_policy"),
        "SLK_RUNTIME_PIN_CAPABILITY_FORBIDDEN",
        "thread_pin_policy",
    )
    if set(pin.get("method_roles", [])) != METHOD_PIN_ROLES:
        fail("SLK_RUNTIME_PIN_CAPABILITY_FORBIDDEN", "every method role must be Pin-denied")
    if (
        pin.get("default_method_pin_allowed") is not False
        or pin.get("set_thread_pinned_true_capability") != "DENIED"
        or pin.get("owner_manual_allowed") is not True
        or pin.get("owner_explicit_item_authorization_allowed") is not True
        or pin.get("inferred_authorization_allowed") is not False
        or pin.get("patrol_auto_unpin_allowed") is not False
        or pin.get("pin_lifecycle_independent") is not True
        or pin.get("unauthorized_history_persists_after_unpin") is not True
    ):
        fail("SLK_RUNTIME_PIN_CAPABILITY_FORBIDDEN", "method Pin capability is default-deny")
    evidence(packet.get("evidence_refs"))


def validate_simulation(packet: dict) -> None:
    if packet.get("status") != "SIMULATION_PASS" or packet.get("clock_source") != "INJECTED":
        fail("SLK_RUNTIME_SIMULATION_NOT_PASS", "simulation and injected clock must pass")
    scenarios = sequence(
        packet.get("scenarios"),
        "SLK_RUNTIME_SIMULATION_INCOMPLETE",
        "scenarios",
    )
    ids = [item.get("scenario_id") for item in scenarios if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        fail("SLK_RUNTIME_SIMULATION_DUPLICATE", "scenario IDs must be unique")
    if set(ids) != REQUIRED_SCENARIOS:
        fail("SLK_RUNTIME_SIMULATION_INCOMPLETE", "required scenario set is incomplete")
    for item in scenarios:
        if item.get("result") != "PASS":
            fail("SLK_RUNTIME_SIMULATION_NOT_PASS", "every scenario must PASS")
        evidence(item.get("evidence_refs"), "SLK_RUNTIME_SIMULATION_NOT_PASS")


def expected_wake_message(packet: dict) -> str:
    state = packet.get("delivery_state")
    tail = "已交付" if state == "DELIVERED" else state
    return (
        f"{packet.get('go_id')} CELL {packet.get('cell_ordinal')}/"
        f"{packet.get('required_cell_total')} {tail}，请检查"
    )


def validate_ack(packet: dict, ack_value: object) -> None:
    item = mapping(ack_value, "SLK_RUNTIME_WAKE_ACK_SCOPE", "ack")
    for name in ("run_id", "go_id", "cell_id", "round_id"):
        if item.get(name) != packet.get(name):
            fail("SLK_RUNTIME_WAKE_ACK_SCOPE", f"ACK {name} drift")
    expected = (
        f"WAKE_ACK {packet['run_id']} {packet['go_id']} "
        f"{packet['cell_id']} {packet['round_id']}"
    )
    if item.get("message") != expected:
        fail("SLK_RUNTIME_WAKE_ACK_SCOPE", "ACK message scope drift")


def validate_worker_wake(packet: dict) -> None:
    if packet.get("sender_role") != "WORKER":
        fail("SLK_RUNTIME_WAKE_WORKER_ONLY", "only Worker may initiate the ladder")
    if packet.get("receiver_responsibility") != "CHECKER_RESPONSIBILITY":
        fail("SLK_RUNTIME_WAKE_CHECKER_ONLY", "receiver must be the original Checker")
    if packet.get("delivery_state") not in {"DELIVERED", "BLOCKED", "EXECUTION_FAILURE"}:
        fail("SLK_RUNTIME_WAKE_MESSAGE_INVALID", "invalid delivery state")
    ordinal = integer(packet.get("cell_ordinal"), "SLK_RUNTIME_WAKE_MESSAGE_INVALID", "cell_ordinal", minimum=1)
    total = integer(
        packet.get("required_cell_total"),
        "SLK_RUNTIME_WAKE_MESSAGE_INVALID",
        "required_cell_total",
        minimum=1,
    )
    if ordinal > total or packet.get("message") != expected_wake_message(packet):
        fail("SLK_RUNTIME_WAKE_MESSAGE_INVALID", "message must carry GO/CELL n/N and state")
    if packet.get("clock_source") != "INJECTED":
        fail("SLK_RUNTIME_WAKE_WAIT_TOO_LONG", "wake timing must use an injected clock")
    binding = mapping(packet.get("checker_binding"), "SLK_RUNTIME_CHECKER_BINDING", "checker_binding")
    text(binding.get("thread_id"), "SLK_RUNTIME_CHECKER_BINDING", "checker thread")
    text(binding.get("host_id"), "SLK_RUNTIME_CHECKER_BINDING", "checker host")

    attempts = sequence(packet.get("attempts"), "SLK_RUNTIME_WAKE_LEVEL_ORDER", "attempts")
    if not attempts or len(attempts) > 4:
        fail("SLK_RUNTIME_WAKE_LEVEL_ORDER", "wake ladder requires one through four attempts")
    ack_seen = False
    for index, raw in enumerate(attempts, start=1):
        item = mapping(raw, "SLK_RUNTIME_WAKE_LEVEL_ORDER", f"attempt {index}")
        if ack_seen:
            fail("SLK_RUNTIME_WAKE_AFTER_ACK", "ladder must stop after ACK")
        if item.get("level") != index or item.get("action") != WAKE_ACTIONS[index]:
            fail("SLK_RUNTIME_WAKE_LEVEL_ORDER", "wake levels/actions must be ordered")
        if item.get("offset_seconds") != WAKE_OFFSETS[index]:
            fail("SLK_RUNTIME_WAKE_OFFSET_INVALID", f"level {index} offset is fixed")
        wait_seconds = integer(
            item.get("wait_seconds"),
            "SLK_RUNTIME_WAKE_WAIT_TOO_LONG",
            "wait_seconds",
        )
        if wait_seconds > 120:
            fail("SLK_RUNTIME_WAKE_WAIT_TOO_LONG", "each wait is at most 120 seconds")
        if item.get("thread_id") != binding.get("thread_id") and index != 2:
            fail("SLK_RUNTIME_WAKE_IDENTITY_DRIFT", "Checker thread identity drift")
        if item.get("message") != packet.get("message"):
            fail("SLK_RUNTIME_WAKE_IDENTITY_DRIFT", "all levels reuse one progress identity")
        evidence(item.get("evidence_refs"))
        if index == 2:
            resolution = mapping(
                item.get("resolution"),
                "SLK_RUNTIME_WAKE_RESOLUTION_INVALID",
                "resolution",
            )
            if resolution.get("guessed_id") is True:
                fail("SLK_RUNTIME_WAKE_GUESSED_ID", "thread IDs may not be guessed")
            if resolution.get("replacement_created") is True:
                fail("SLK_RUNTIME_WAKE_REPLACEMENT_FORBIDDEN", "replacement Checker is forbidden")
            if resolution.get("registry_thread_id") != binding.get("thread_id"):
                fail("SLK_RUNTIME_WAKE_IDENTITY_DRIFT", "registry must resolve the frozen Checker")
            if resolution.get("thread_found") is True:
                if item.get("host_id") != resolution.get("registry_host_id"):
                    fail("SLK_RUNTIME_WAKE_IDENTITY_DRIFT", "resolved host must use the frozen registry")
                if resolution.get("was_archived") is True and resolution.get("unarchived") is not True:
                    fail("SLK_RUNTIME_WAKE_RESOLUTION_INVALID", "archived Checker must be unarchived")
        if index == 3:
            heartbeat = mapping(
                item.get("heartbeat"),
                "SLK_RUNTIME_WAKE_HEARTBEAT_NOT_UNIQUE",
                "heartbeat",
            )
            if heartbeat.get("heartbeat_count") != 1:
                fail("SLK_RUNTIME_WAKE_HEARTBEAT_NOT_UNIQUE", "temporary heartbeat must be unique")
            expected_id = (
                f"SLK-WAKE-{packet['run_id']}-{packet['go_id']}-"
                f"{packet['cell_id']}-{packet['round_id']}-{binding['thread_id']}"
            )
            if heartbeat.get("heartbeat_id") != expected_id:
                fail("SLK_RUNTIME_WAKE_HEARTBEAT_NOT_UNIQUE", "heartbeat ID must be deterministic")
        if item.get("result") == "ACK":
            validate_ack(packet, item.get("ack"))
            ack_seen = True

    if ack_seen:
        if packet.get("status") != "ACKNOWLEDGED" or packet.get("stopped") is not True:
            fail("SLK_RUNTIME_WAKE_AFTER_ACK", "matching ACK must stop the ladder")
        if len(attempts) >= 3 and packet.get("temporary_heartbeat_state") != "DELETED":
            fail("SLK_RUNTIME_WAKE_HEARTBEAT_NOT_CLEAN", "ACK must delete temporary heartbeat")
        if packet.get("pending_wake_ref"):
            fail("SLK_RUNTIME_WAKE_AFTER_ACK", "ACK must consume pending wake")
    else:
        if len(attempts) != 4 or attempts[-1].get("result") != "PENDING_WAKE_WRITTEN":
            fail("SLK_RUNTIME_PENDING_WAKE_REQUIRED", "four failed levels require PENDING_WAKE")
        if not packet.get("pending_wake_ref"):
            fail("SLK_RUNTIME_PENDING_WAKE_REQUIRED", "PENDING_WAKE reference is required")


def validate_pending_wake(packet: dict) -> None:
    if packet.get("status") not in {"PENDING", "PATROL_OBSERVED", "ACKNOWLEDGED", "CONSUMED"}:
        fail("SLK_RUNTIME_PENDING_WAKE_INVALID", "invalid pending wake status")
    text(packet.get("pending_wake_id"), "SLK_RUNTIME_PENDING_WAKE_INVALID", "pending_wake_id")
    if packet.get("attempt_count") != 3:
        fail("SLK_RUNTIME_PENDING_WAKE_INVALID", "PENDING_WAKE records the three failed ACK waits")
    errors = sequence(packet.get("attempt_errors"), "SLK_RUNTIME_PENDING_WAKE_INVALID", "attempt_errors")
    if len(errors) != 3:
        fail("SLK_RUNTIME_PENDING_WAKE_INVALID", "three attempt errors are required")
    patrol = mapping(packet.get("patrol"), "SLK_RUNTIME_PATROL_UNIQUE", "patrol")
    if patrol.get("conversation_count") != 1 or patrol.get("heartbeat_count") != 1:
        fail("SLK_RUNTIME_PATROL_UNIQUE", "only the unique Patrol may consume pending wake")
    if packet.get("status") == "PATROL_OBSERVED" and (
        patrol.get("observed") is not True
        or patrol.get("alert_code") != "PENDING_WAKE_UNCONSUMED"
    ):
        fail("SLK_RUNTIME_PENDING_WAKE_INVALID", "Patrol observation must be explicit")
    evidence(packet.get("evidence_refs"))


def validate_patrol(packet: dict) -> None:
    if packet.get("actor") != "RUN_PATROL" or packet.get("authority") != "NONE":
        fail("SLK_RUNTIME_PATROL_AUTHORITY", "Patrol has no technical authority")
    if packet.get("model") != "gpt-5.6-luna" or packet.get("reasoning_effort") != "xhigh":
        fail("SLK_RUNTIME_PATROL_MODEL", "Patrol requires gpt-5.6-luna + xhigh")
    if (
        packet.get("conversation_count") != 1
        or packet.get("heartbeat_count") != 1
    ):
        fail("SLK_RUNTIME_PATROL_UNIQUE", "Patrol and heartbeat are unique per Run")
    if packet.get("interval_minutes") not in {10, 15, 30}:
        fail("SLK_RUNTIME_PATROL_INTERVAL", "invalid Patrol interval")
    actions = sequence(packet.get("actions"), "SLK_RUNTIME_PATROL_ACTION_FORBIDDEN", "actions")
    if actions:
        fail("SLK_RUNTIME_PATROL_ACTION_FORBIDDEN", "Patrol may only observe and alert")
    if packet.get("engineering_progress_reported") is not False:
        fail("SLK_RUNTIME_PATROL_PROGRESS_FORBIDDEN", "Patrol cannot report engineering progress")

    observation = mapping(packet.get("observation"), "SLK_RUNTIME_PATROL_OBSERVATION", "observation")
    kind = observation.get("kind")
    evidence_kind = observation.get("evidence_kind")
    result = observation.get("result")
    alert = observation.get("alert_code")
    source = str(observation.get("source_text", ""))
    false_positive = (
        evidence_kind == "VISIBLE_PEER_TASK"
        or "子任务" in source
        or packet.get("run_state") in {"FORMALLY_PAUSED", "LEGAL_BLOCKED", "WAITING_EXTERNAL"}
    )
    if false_positive and (result != "NORMAL" or alert):
        fail("SLK_RUNTIME_PATROL_FALSE_POSITIVE", "visible tasks and legitimate pauses are not subagents/stalls")
    if kind == "SUBAGENT_EVIDENCE":
        if evidence_kind not in SUBAGENT_EVIDENCE:
            fail("SLK_RUNTIME_PATROL_FALSE_POSITIVE", "only explicit agent evidence is prohibited")
        if result != "ALERT" or alert != "SUBAGENT_MISUSE":
            fail("SLK_RUNTIME_PATROL_MISSED_ALERT", "subagent evidence requires fixed alert")
    if kind == "SUPERVISOR_WAIT":
        timeout_ms = integer(
            observation.get("timeout_ms"),
            "SLK_RUNTIME_PATROL_OBSERVATION",
            "timeout_ms",
        )
        if timeout_ms > 0 and observation.get("inside_loop") is True:
            if result != "ALERT" or alert != "SUPERVISOR_WAIT_FORBIDDEN":
                fail("SLK_RUNTIME_PATROL_MISSED_ALERT", "positive Supervisor wait requires alert")
    cleanup = mapping(
        packet.get("terminal_cleanup"),
        "SLK_RUNTIME_PATROL_NOT_CLOSED",
        "terminal_cleanup",
    )
    if packet.get("run_state") == "LOOP_TERMINAL" or packet.get("status") == "PATROL_CLOSED":
        if packet.get("status") != "PATROL_CLOSED" or not all(
            cleanup.get(name) is True
            for name in (
                "loop_terminal_confirmed",
                "heartbeat_deleted",
                "conversation_archived",
            )
        ):
            fail("SLK_RUNTIME_PATROL_NOT_CLOSED", "terminal order must delete heartbeat then archive")
    evidence(packet.get("evidence_refs"))


def current_receipt_set(
    receipts: object,
    *,
    id_field: str,
    member_field: str,
    required: set[str],
) -> set[str]:
    values = sequence(receipts, "SLK_RUNTIME_PROGRESS_COUNT_MISMATCH", "receipts")
    receipt_ids: list[str] = []
    members: set[str] = set()
    for item in values:
        value = mapping(item, "SLK_RUNTIME_PROGRESS_COUNT_MISMATCH", "receipt")
        receipt_ids.append(str(value.get(id_field)))
        if (
            value.get("verdict") == "PASS"
            and value.get("invalidation_status") == "CURRENT"
            and value.get(member_field) in required
        ):
            members.add(value[member_field])
    if len(receipt_ids) != len(set(receipt_ids)):
        fail("SLK_RUNTIME_PROGRESS_DUPLICATE_RECEIPT", "duplicate active receipt ID")
    return members


def validate_progress(packet: dict) -> None:
    if packet.get("history_immutable") is not True:
        fail("SLK_RUNTIME_PROGRESS_AMENDMENT_STALE", "progress history must be immutable")
    raw_sets = sequence(packet.get("required_sets"), "SLK_RUNTIME_REQUIRED_SET", "required_sets")
    required_sets: dict[int, dict] = {}
    for raw in raw_sets:
        item = mapping(raw, "SLK_RUNTIME_REQUIRED_SET", "required set")
        version = integer(item.get("version"), "SLK_RUNTIME_REQUIRED_SET", "version", minimum=1)
        if version in required_sets:
            fail("SLK_RUNTIME_REQUIRED_SET", "Required-set versions must be unique")
        required_sets[version] = item
    events = sequence(packet.get("events"), "SLK_RUNTIME_PROGRESS_COUNT_MISMATCH", "events")
    milestones: set[str] = set()
    for expected_sequence, raw in enumerate(events, start=1):
        event = mapping(raw, "SLK_RUNTIME_PROGRESS_COUNT_MISMATCH", "event")
        if event.get("sequence") != expected_sequence:
            fail("SLK_RUNTIME_PROGRESS_COUNT_MISMATCH", "event sequence must be contiguous")
        version = event.get("required_set_version")
        if version not in required_sets:
            fail("SLK_RUNTIME_PROGRESS_AMENDMENT_STALE", "event references unknown Required set")
        required = required_sets[version]
        go_id = event.get("go_id")
        required_gos = set(required.get("required_go_ids", []))
        cells_by_go = mapping(
            required.get("required_cells_by_go"),
            "SLK_RUNTIME_REQUIRED_SET",
            "required_cells_by_go",
        )
        required_cells = set(cells_by_go.get(go_id, []))
        accepted = current_receipt_set(
            event.get("current_d1_pass_receipts"),
            id_field="receipt_id",
            member_field="cell_id",
            required=required_cells,
        )
        verified = current_receipt_set(
            event.get("current_d2_pass_receipts"),
            id_field="receipt_id",
            member_field="go_id",
            required=required_gos,
        )
        if event.get("event") == "GO_CANDIDATE_READY" and event.get("verified_go_count") != 0:
            fail("SLK_RUNTIME_PROGRESS_LAYER_CONFUSION", "candidate-ready is not D2 verified")
        if (
            event.get("accepted_cell_count") != len(accepted)
            or event.get("verified_go_count") != len(verified)
        ):
            fail("SLK_RUNTIME_PROGRESS_COUNT_MISMATCH", "declared progress must equal current receipts")
        if event.get("required_cell_total") != len(required_cells):
            fail("SLK_RUNTIME_PROGRESS_AMENDMENT_STALE", "CELL denominator is stale")
        if event.get("required_go_total") != len(required_gos):
            fail("SLK_RUNTIME_PROGRESS_AMENDMENT_STALE", "GO denominator is stale")
        message = str(event.get("message", ""))
        if not message.strip():
            fail("SLK_RUNTIME_PROGRESS_LAYER_CONFUSION", "progress message is required")
        if message.strip() == "已完成":
            fail("SLK_RUNTIME_PROGRESS_LAYER_CONFUSION", "generic completion hides the authority layer")
        actor = event.get("actor")
        event_kind = event.get("event")
        audience = event.get("audience")
        if actor == "RUN_PATROL":
            fail("SLK_RUNTIME_PROGRESS_ROLE_FORBIDDEN", "Patrol cannot emit engineering progress")
        if actor == "VERIFIER" and event_kind != "D2_VERIFIED":
            fail("SLK_RUNTIME_PROGRESS_ROLE_FORBIDDEN", "Verifier emits formal verdicts only")
        if actor == "WORKER":
            if event_kind not in {"DELIVERED", "BLOCKED", "EXECUTION_FAILURE"} or audience != "CHECKER":
                fail("SLK_RUNTIME_PROGRESS_ROLE_FORBIDDEN", "Worker only reports scoped delivery to Checker")
            expected = (
                f"{go_id} CELL {event.get('cell_ordinal')}/"
                f"{event.get('required_cell_total')}"
            )
            if expected not in message:
                fail("SLK_RUNTIME_PROGRESS_LAYER_CONFUSION", "Worker message must contain GO/CELL n/N")
        if actor == "CHECKER" and audience == "SUPERVISOR":
            if event_kind != "GO_CANDIDATE_READY" or len(accepted) != len(required_cells):
                fail("SLK_RUNTIME_PROGRESS_NOISE", "Checker reports Supervisor only at GO boundary")
            milestone = text(
                event.get("milestone_id"),
                "SLK_RUNTIME_PROGRESS_NOISE",
                "milestone_id",
            )
            if milestone in milestones:
                fail("SLK_RUNTIME_PROGRESS_NOISE", "duplicate GO milestone")
            milestones.add(milestone)
        elif event.get("milestone_id"):
            fail("SLK_RUNTIME_PROGRESS_NOISE", "milestone IDs belong only to GO boundary reports")
        if event_kind == "AMENDMENT":
            if event.get("recomputed") is not True or version != max(required_sets):
                fail("SLK_RUNTIME_PROGRESS_AMENDMENT_STALE", "amendment must use latest version and recompute")
    evidence(packet.get("evidence_refs"))


def validate_device_capacity(packet: dict) -> None:
    if packet.get("status") != "READY":
        fail("SLK_RUNTIME_CAPACITY_UNKNOWN", "device profile must be READY")
    text(packet.get("profile_id"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "profile_id")
    integer(packet.get("version"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "version", minimum=1)
    text(packet.get("captured_at"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "captured_at")
    cpu = mapping(packet.get("cpu"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "cpu")
    model = text(cpu.get("model"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "cpu.model")
    if model.strip().upper() in MARKETING_CAPACITY or model.strip() in MARKETING_CAPACITY:
        fail("SLK_RUNTIME_CAPACITY_UNKNOWN", "marketing descriptions are not capacity facts")
    integer(cpu.get("logical_cores"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "logical_cores", minimum=1)
    memory = mapping(packet.get("memory"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "memory")
    number(memory.get("available_ram_mb"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "available_ram_mb", minimum=1)
    gpu = mapping(packet.get("gpu"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "gpu")
    applicable = boolean(gpu.get("applicable"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "gpu.applicable")
    gpu_model = text(gpu.get("model"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "gpu.model")
    vram = number(gpu.get("vram_mb"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "gpu.vram_mb")
    if applicable and (gpu_model == "N/A" or vram <= 0):
        fail("SLK_RUNTIME_CAPACITY_UNKNOWN", "applicable GPU requires model and VRAM")
    if not applicable and (gpu_model != "N/A" or vram != 0):
        fail("SLK_RUNTIME_CAPACITY_UNKNOWN", "non-applicable GPU must be explicit N/A")
    disk = mapping(packet.get("disk"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "disk")
    for name in ("free_mb", "read_mb_s", "write_mb_s"):
        number(disk.get(name), "SLK_RUNTIME_CAPACITY_UNKNOWN", f"disk.{name}", minimum=1)
    network = mapping(packet.get("network"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "network")
    if network.get("external_service_access") not in {"AVAILABLE", "LIMITED", "UNAVAILABLE"}:
        fail("SLK_RUNTIME_CAPACITY_UNKNOWN", "network access must be enumerated")
    number(network.get("max_mbps"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "network.max_mbps")
    sequence(network.get("constraints"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "network.constraints")
    limits = mapping(packet.get("process_limits"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "process_limits")
    integer(limits.get("max_processes"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "max_processes", minimum=1)
    integer(limits.get("safe_concurrency"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "safe_concurrency", minimum=1)
    sequence(limits.get("allowed_ports"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "allowed_ports")
    durations = mapping(
        packet.get("duration_budgets_seconds"),
        "SLK_RUNTIME_CAPACITY_UNKNOWN",
        "duration_budgets_seconds",
    )
    for name in ("single_command", "full_test", "build", "cell_total"):
        number(durations.get(name), "SLK_RUNTIME_CAPACITY_UNKNOWN", name, minimum=1)
    budgets = mapping(
        packet.get("context_evidence_budgets"),
        "SLK_RUNTIME_CAPACITY_UNKNOWN",
        "context_evidence_budgets",
    )
    number(budgets.get("context_tokens"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "context_tokens", minimum=1)
    number(budgets.get("evidence_mb"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "evidence_mb", minimum=1)
    evidence(packet.get("evidence_refs"))


def validate_cumulative_load(packet: dict) -> None:
    if packet.get("status") != "CURRENT":
        fail("SLK_RUNTIME_LOAD_STALE", "cumulative load must be CURRENT")
    text(packet.get("load_id"), "SLK_RUNTIME_LOAD_STALE", "load_id")
    version = integer(packet.get("version"), "SLK_RUNTIME_LOAD_STALE", "version", minimum=1)
    ref(packet.get("device_capacity_profile_ref"), "SLK_RUNTIME_LOAD_STALE", "device profile")
    baseline = ref(packet.get("baseline_ref"), "SLK_RUNTIME_LOAD_STALE", "baseline", hashed=True)
    if baseline.get("version") != version:
        fail("SLK_RUNTIME_LOAD_STALE", "load version must bind accepted baseline version")
    if packet.get("boundary_kind") not in {
        "RUN_FREEZE",
        "GO_BOUNDARY",
        "REQUIRED_SET_AMENDMENT",
        "MEASURED_DEVIATION",
    }:
        fail("SLK_RUNTIME_LOAD_STALE", "load must identify a re-estimation boundary")
    integer(packet.get("required_set_version"), "SLK_RUNTIME_LOAD_STALE", "required_set_version", minimum=1)
    measurements = mapping(packet.get("measurements"), "SLK_RUNTIME_LOAD_STALE", "measurements")
    required = {
        "accepted_cell_count",
        "file_count",
        "dependency_count",
        "build_seconds",
        "full_regression_seconds",
        "peak_ram_mb",
        "peak_disk_mb",
        "evidence_mb",
        "hash_file_count",
        "context_restore_seconds",
        "external_tool_seconds",
        "rollback_retry_seconds",
        "coupling_score",
    }
    if set(measurements) != required:
        fail("SLK_RUNTIME_LOAD_STALE", "cumulative load measurements are incomplete")
    for name in required:
        number(measurements.get(name), "SLK_RUNTIME_LOAD_STALE", name)
    evidence(packet.get("evidence_refs"))


def validate_capacity_gate(packet: dict) -> None:
    if packet.get("status") != "DECIDED" or packet.get("phase") != "PRE_DISPATCH":
        fail("SLK_RUNTIME_CAPACITY_DISPATCH_FORBIDDEN", "capacity gate is pre-dispatch")
    ref(packet.get("device_capacity_profile_ref"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "device profile")
    ref(packet.get("cumulative_engineering_load_ref"), "SLK_RUNTIME_LOAD_STALE", "load")
    sha256(packet.get("go_outcome_sha256"), "SLK_RUNTIME_CAPACITY_SPLIT_INVALID", "go outcome")
    sha256(packet.get("acceptance_sha256"), "SLK_RUNTIME_CAPACITY_SPLIT_INVALID", "acceptance")
    estimate = mapping(packet.get("estimate"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "estimate")
    estimate_fields = {
        "implementation_minutes",
        "input_dependency_count",
        "output_count",
        "build_seconds",
        "test_seconds",
        "checker_seconds",
        "regression_seconds",
        "evidence_hash_cleanup_seconds",
        "context_load_seconds",
        "external_tool_seconds",
        "rollback_retry_seconds",
        "cumulative_coupling_score",
        "peak_ram_mb",
        "peak_disk_mb",
        "requested_device_concurrency",
    }
    if set(estimate) != estimate_fields:
        fail("SLK_RUNTIME_CAPACITY_UNKNOWN", "CELL total-cost estimate is incomplete")
    for name in estimate_fields:
        number(estimate.get(name), "SLK_RUNTIME_CAPACITY_UNKNOWN", name)
    integer(packet.get("logical_parallelism"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "logical_parallelism", minimum=1)
    inputs = mapping(packet.get("decision_inputs"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "decision_inputs")
    input_fields = {
        "available_ram_mb",
        "free_disk_mb",
        "safe_device_concurrency",
        "cell_total_budget_seconds",
        "cumulative_full_regression_seconds",
        "cumulative_context_restore_seconds",
        "cumulative_rollback_retry_seconds",
        "cumulative_coupling_score",
    }
    if set(inputs) != input_fields:
        fail("SLK_RUNTIME_CAPACITY_UNKNOWN", "capacity/load decision inputs are incomplete")
    for name in input_fields:
        number(inputs.get(name), "SLK_RUNTIME_CAPACITY_UNKNOWN", name)
    decision = mapping(packet.get("decision"), "SLK_RUNTIME_CAPACITY_OUTCOME_INVALID", "decision")
    outcome = decision.get("outcome")
    if outcome not in {"PASS", "SPLIT_REQUIRED", "CAPACITY_BLOCKED"}:
        fail("SLK_RUNTIME_CAPACITY_OUTCOME_INVALID", "invalid capacity outcome")
    dispatch = decision.get("dispatch_allowed")
    if dispatch is not (outcome == "PASS"):
        fail("SLK_RUNTIME_CAPACITY_DISPATCH_FORBIDDEN", "only PASS permits dispatch")
    evidence(packet.get("evidence_refs"))

    blocked = (
        estimate["peak_ram_mb"] > inputs["available_ram_mb"]
        or estimate["peak_disk_mb"] > inputs["free_disk_mb"]
        or estimate["requested_device_concurrency"] > inputs["safe_device_concurrency"]
        or inputs["safe_device_concurrency"] < 1
    )
    time_names = (
        "build_seconds",
        "test_seconds",
        "checker_seconds",
        "regression_seconds",
        "evidence_hash_cleanup_seconds",
        "context_load_seconds",
        "external_tool_seconds",
        "rollback_retry_seconds",
    )
    total_seconds = estimate["implementation_minutes"] * 60 + sum(
        estimate[name] for name in time_names
    )
    total_seconds += (
        inputs["cumulative_full_regression_seconds"]
        + inputs["cumulative_context_restore_seconds"]
        + inputs["cumulative_rollback_retry_seconds"]
    )
    split_required = total_seconds > inputs["cell_total_budget_seconds"]
    if blocked and outcome != "CAPACITY_BLOCKED":
        fail("SLK_RUNTIME_CAPACITY_BLOCKED", "resource or device concurrency limit is exceeded")
    if not blocked and split_required and outcome != "SPLIT_REQUIRED":
        fail("SLK_RUNTIME_CAPACITY_SPLIT_REQUIRED", "total engineering cost exceeds CELL budget")
    if not blocked and not split_required and outcome != "PASS":
        fail("SLK_RUNTIME_CAPACITY_OUTCOME_INVALID", "decision does not match measured capacity")

    split = mapping(packet.get("split_plan"), "SLK_RUNTIME_CAPACITY_SPLIT_INVALID", "split_plan")
    successors = sequence(
        split.get("successor_cells"),
        "SLK_RUNTIME_CAPACITY_SPLIT_INVALID",
        "successor_cells",
    )
    if outcome == "SPLIT_REQUIRED":
        if split.get("successor_count") != len(successors) or len(successors) < 2:
            fail("SLK_RUNTIME_CAPACITY_SPLIT_INVALID", "split requires at least two successor CELLs")
        if (
            split.get("preserves_go_outcome_sha256") != packet.get("go_outcome_sha256")
            or split.get("preserves_acceptance_sha256") != packet.get("acceptance_sha256")
            or split.get("creates_new_go") is not False
            or split.get("creates_worker_or_subagent") is not False
            or split.get("verification_weakened") is not False
        ):
            fail("SLK_RUNTIME_CAPACITY_SPLIT_INVALID", "split must preserve GO outcome and acceptance")
        ids = {item.get("cell_id") for item in successors if isinstance(item, dict)}
        if len(ids) != len(successors) or any(
            item.get("independently_deliverable") is not True
            or item.get("independently_d1_checkable") is not True
            or not isinstance(item.get("depends_on"), list)
            or any(dep not in ids for dep in item.get("depends_on", []))
            for item in successors
        ):
            fail("SLK_RUNTIME_CAPACITY_SPLIT_INVALID", "successors must be independent and dependencies explicit")
    elif split.get("successor_count") != 0 or successors:
        fail("SLK_RUNTIME_CAPACITY_SPLIT_INVALID", "non-split gate cannot define successors")


def validate_capacity_event(packet: dict) -> None:
    event_kind = packet.get("event")
    if event_kind not in {"CELL_SCOPE_EXCEEDED", "POST_DISPATCH_CELL_SPLIT"}:
        fail("SLK_RUNTIME_CAPACITY_EVENT_INVALID", "invalid capacity event")
    if packet.get("worker_self_split") is not False:
        fail("SLK_RUNTIME_CAPACITY_WORKER_SELF_SPLIT", "Worker may never split its own CELL")
    if packet.get("worker_stopped") is not True:
        fail("SLK_RUNTIME_CAPACITY_SCOPE_EXCEEDED", "execution deviation must stop")
    ref(packet.get("checkpoint_ref"), "SLK_RUNTIME_CAPACITY_SCOPE_EXCEEDED", "checkpoint", hashed=True)
    evidence(packet.get("evidence_refs"))
    successors = integer(packet.get("successor_count"), "SLK_RUNTIME_CAPACITY_EVENT_INVALID", "successor_count")
    if event_kind == "CELL_SCOPE_EXCEEDED":
        if (
            packet.get("actor") != "WORKER"
            or packet.get("returned_to") != "CHECKER_RESPONSIBILITY"
            or successors != 0
            or packet.get("planning_defect") is not False
        ):
            fail("SLK_RUNTIME_CAPACITY_SCOPE_EXCEEDED", "Worker must stop/checkpoint/return without splitting")
    else:
        if packet.get("planning_defect") is not True or successors < 2:
            fail("SLK_RUNTIME_CAPACITY_EVENT_INVALID", "post-dispatch split is a planning defect")
        severe = successors >= 3
        if severe and (
            packet.get("severity") != "CELL_OVERSIZE_SEVERE"
            or packet.get("reevaluate_remaining_plan") is not True
            or packet.get("reevaluate_device_budget") is not True
        ):
            fail("SLK_RUNTIME_CAPACITY_OVERSIZE_SEVERE", "3+ successors require severe re-evaluation")
        if not severe and packet.get("severity") != "NONE":
            fail("SLK_RUNTIME_CAPACITY_EVENT_INVALID", "two successors are not severe")


def validate_thread_pin_audit(packet: dict) -> None:
    if packet.get("status") != "VALID":
        fail("SLK_RUNTIME_PIN_AUDIT_INVALID", "Pin audit must be VALID")
    text(packet.get("run_id"), "SLK_RUNTIME_PIN_AUDIT_INVALID", "run_id")
    text(packet.get("task_thread_id"), "SLK_RUNTIME_PIN_AUDIT_INVALID", "task_thread_id")
    if packet.get("task_role") not in METHOD_PIN_ROLES:
        fail("SLK_RUNTIME_PIN_AUDIT_INVALID", "task_role is not a method role")
    if packet.get("lifecycle_state") not in {
        "CREATED",
        "DISPATCHED",
        "ACTIVE",
        "WAITING_RECEIPT",
        "BLOCKED",
        "REWORK",
        "VERIFYING",
        "MILESTONE",
        "IMPORTANT",
        "ARCHIVED",
        "UNARCHIVED",
        "TERMINAL",
    }:
        fail("SLK_RUNTIME_PIN_AUDIT_INVALID", "lifecycle does not confer Pin authority")
    pinned = boolean(packet.get("pinned_state"), "SLK_RUNTIME_PIN_AUDIT_INVALID", "pinned_state")
    if packet.get("pin_lifecycle_independent") is not True:
        fail("SLK_RUNTIME_PIN_CAPABILITY_FORBIDDEN", "Pin and lifecycle are independent")
    patrol = mapping(packet.get("patrol"), "SLK_RUNTIME_PIN_AUDIT_INVALID", "patrol")
    if (
        patrol.get("automatic_pin_attempted") is not False
        or patrol.get("automatic_unpin_attempted") is not False
    ):
        fail("SLK_RUNTIME_PIN_AUTO_ACTION_FORBIDDEN", "Patrol cannot Pin or Unpin")
    operations = sequence(packet.get("operations"), "SLK_RUNTIME_PIN_AUDIT_INVALID", "operations")
    last_state: bool | None = None
    unauthorized_pin = False
    for expected, raw in enumerate(operations, start=1):
        item = mapping(raw, "SLK_RUNTIME_PIN_AUDIT_INVALID", "operation")
        if item.get("sequence") != expected or item.get("action") not in {"PIN", "UNPIN"}:
            fail("SLK_RUNTIME_PIN_AUDIT_INVALID", "Pin operations must be ordered")
        text(item.get("actor"), "SLK_RUNTIME_PIN_AUDIT_INVALID", "operation.actor")
        text(item.get("tool"), "SLK_RUNTIME_PIN_AUDIT_INVALID", "operation.tool")
        if not isinstance(item.get("authorization_ref"), str):
            fail("SLK_RUNTIME_PIN_AUDIT_INVALID", "authorization_ref must be text")
        last_state = item.get("action") == "PIN"
        if item.get("action") == "PIN" and item.get("actor") != "OWNER":
            if not item.get("authorization_ref"):
                unauthorized_pin = True
    if last_state is not None and pinned is not last_state:
        fail("SLK_RUNTIME_PIN_AUDIT_INVALID", "pinned_state must match the operation history")

    provenance = packet.get("provenance")
    owner_ref = packet.get("owner_authorization_ref")
    if not isinstance(owner_ref, str):
        fail("SLK_RUNTIME_PIN_AUDIT_INVALID", "owner_authorization_ref must be text")
    if provenance == "NONE":
        if pinned or operations or owner_ref:
            fail("SLK_RUNTIME_PIN_UNAUTHORIZED", "lifecycle state cannot infer Pin authority")
        if patrol.get("result") != "NORMAL" or patrol.get("alert_code"):
            fail("SLK_RUNTIME_PIN_AUDIT_INVALID", "un-pinned task is normal")
    elif provenance == "OWNER_MANUAL_UI":
        if (
            not pinned
            or len(operations) != 1
            or operations[0].get("actor") != "OWNER"
            or operations[0].get("tool") != "CODEX_UI"
            or owner_ref
            or patrol.get("result") != "NORMAL"
            or patrol.get("alert_code")
        ):
            fail("SLK_RUNTIME_PIN_UNAUTHORIZED", "Owner manual UI provenance is malformed")
    elif provenance == "OWNER_EXPLICIT_ITEM_AUTHORIZATION":
        if (
            not owner_ref
            or not operations
            or any(item.get("authorization_ref") != owner_ref for item in operations if item.get("action") == "PIN")
            or patrol.get("result") != "NORMAL"
            or patrol.get("alert_code")
        ):
            fail("SLK_RUNTIME_PIN_UNAUTHORIZED", "Owner authorization must bind this exact task")
    elif provenance == "AGENT_TOOL_CALL":
        if (
            not any(item.get("action") == "PIN" for item in operations)
            or not unauthorized_pin
            or packet.get("violation_history_retained") is not True
            or patrol.get("result") != "ALERT"
            or patrol.get("alert_code") != "UNAUTHORIZED_THREAD_PIN"
            or patrol.get("owner_notified") is not True
        ):
            code = (
                "SLK_RUNTIME_PIN_HISTORY_REQUIRED"
                if packet.get("violation_history_retained") is not True
                else "SLK_RUNTIME_PIN_UNAUTHORIZED"
            )
            fail(code, "unauthorized Pin remains a fixed alert after any Unpin")
    elif provenance == "UNKNOWN":
        if (
            not pinned
            or patrol.get("result") != "ALERT"
            or patrol.get("alert_code") != "PIN_PROVENANCE_UNKNOWN"
            or patrol.get("owner_notified") is not True
        ):
            fail("SLK_RUNTIME_PIN_PROVENANCE_UNKNOWN", "unknown provenance must alert Owner")
    else:
        fail("SLK_RUNTIME_PIN_PROVENANCE_UNKNOWN", "Pin provenance is not proven")
    evidence(packet.get("evidence_refs"))


VALIDATORS: dict[str, Callable[[dict], None]] = {
    "RUN_RUNTIME_CONTRACT": validate_run_runtime_contract,
    "DEVICE_CAPACITY_PROFILE": validate_device_capacity,
    "CUMULATIVE_ENGINEERING_LOAD": validate_cumulative_load,
    "CELL_CAPACITY_GATE": validate_capacity_gate,
    "CELL_CAPACITY_EVENT": validate_capacity_event,
    "WORKER_WAKE_TRACE": validate_worker_wake,
    "PENDING_WAKE": validate_pending_wake,
    "RUN_PATROL_RECEIPT": validate_patrol,
    "PROGRESS_TRACE": validate_progress,
    "RUNTIME_SIMULATION": validate_simulation,
    "THREAD_PIN_AUDIT": validate_thread_pin_audit,
}


def validate(packet: object) -> None:
    value = mapping(packet, "SLK_RUNTIME_ROOT", "record")
    validate_common(value)
    validator = VALIDATORS.get(value.get("record_type"))
    if validator is None:
        fail("SLK_RUNTIME_RECORD_TYPE", "unsupported record_type")
    validator(value)


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    if len(args) != 1:
        print("FAIL SLK_RUNTIME_USAGE: expected one YAML record path", file=sys.stderr)
        return 2
    path = Path(args[0])
    try:
        packet = yaml.safe_load(path.read_text(encoding="utf-8"))
        validate(packet)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        print(f"FAIL SLK_RUNTIME_INPUT: {exc}", file=sys.stderr)
        return 1
    except ValidationError as exc:
        print(f"FAIL {exc.code}: {exc.detail}", file=sys.stderr)
        return 1
    print("PASS: SLK runtime control record")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
