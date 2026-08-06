from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable, Iterable

import yaml


VERSION = "2.6.0"
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
    "MODEL_TERRA_DEFAULT_ACCEPTED",
    "MODEL_LUNA_FINE_GRAINED_LOW_RISK_ACCEPTED",
    "MODEL_SOL_HIGH_DIFFICULTY_ACCEPTED",
    "MODEL_EQUIVALENT_SUBSTITUTE_ACCEPTED",
    "MODEL_GPT55_OR_LOWER_REJECTED",
    "MODEL_ULTRA_WITHOUT_OWNER_REJECTED",
    "MODEL_UNJUSTIFIED_DOWNGRADE_REJECTED",
    "MODEL_SILENT_SWITCH_REJECTED",
    "MODEL_ROLE_ISOLATION_PRESERVED",
    "MODEL_PATROL_DEFAULT_TERRA",
    "MODEL_KNOWN_REFERENCE_CLASS_SPOOF_REJECTED",
    "MODEL_SECOND_ROLE_INSTANCE_REJECTED",
    "MODEL_SHARED_ROLE_INSTANCE_REJECTED",
}
SLK_TECHNICAL_ROLES = {
    "SUPERVISOR_RESPONSIBILITY",
    "CHECKER_RESPONSIBILITY",
    "VERIFIER_RESPONSIBILITY",
    "WORKER",
}
PIN_SUBJECT_ROLES = SLK_TECHNICAL_ROLES | {"RUN_PATROL"}
MODEL_ROLES = SLK_TECHNICAL_ROLES | {"RUN_PATROL"}
REFERENCE_CLASSES = {
    "gpt-5.6-terra": "TERRA_CLASS",
    "gpt-5.6-luna": "LUNA_CLASS",
    "gpt-5.6-sol": "SOL_CLASS",
}
KNOWN_GPT_FAMILY = re.compile(
    r"^(gpt-5\.6-(terra|luna|sol))(?=$|[-._])"
)
HIGH_DIFFICULTY_WORK = {
    "HIGH_DIFFICULTY_CORRECTION",
    "ROOT_CAUSE_DIAGNOSIS",
    "COMPLEX_REWORK",
}
MODEL_SELECTION_REASONS = {
    "STANDARD_TECHNICAL": "DEFAULT_TECHNICAL_ROLE",
    "NON_TECHNICAL_PATROL": "DEFAULT_NON_TECHNICAL_PATROL",
    "FINE_GRAINED_LOW_RISK": "FINE_GRAINED_LOW_RISK_CELL",
    "HIGH_DIFFICULTY_CORRECTION": "HIGH_DIFFICULTY_CORRECTION",
    "ROOT_CAUSE_DIAGNOSIS": "ROOT_CAUSE_DIAGNOSIS",
    "COMPLEX_REWORK": "COMPLEX_REWORK",
}
WORKLOAD_INTERVALS = {"LOW": 10, "MEDIUM": 15, "HIGH": 30}
PATROL_REQUIRED_CHECKS = {
    "FORWARD_MOTION",
    "PENDING_WAKE",
    "SUBAGENT_EVIDENCE",
    "SUPERVISOR_WAIT",
    "PATROL_UNIQUENESS",
    "THREAD_PIN",
    "TERMINAL_CLOSURE",
}
PATROL_FINDINGS = {
    "FORWARD_MOTION": {
        "LEGAL_FORWARD_MOTION": ("NORMAL", ""),
        "LEGITIMATE_PAUSE": ("NORMAL", ""),
        "UNEXPLAINED_STALL": ("ALERT", "UNEXPLAINED_STALL"),
    },
    "PENDING_WAKE": {
        "NO_PENDING_WAKE": ("NORMAL", ""),
        "UNCONSUMED_PENDING_WAKE": ("ALERT", "PENDING_WAKE_UNCONSUMED"),
    },
    "SUBAGENT_EVIDENCE": {
        "NO_SUBAGENT_EVIDENCE": ("NORMAL", ""),
        "PROHIBITED_SUBAGENT_EVIDENCE": ("ALERT", "SUBAGENT_MISUSE"),
    },
    "SUPERVISOR_WAIT": {
        "ZERO_SNAPSHOT_OR_NONE": ("NORMAL", ""),
        "POSITIVE_WAIT": ("ALERT", "SUPERVISOR_WAIT_FORBIDDEN"),
        "LOOPED_WAIT": ("ALERT", "SUPERVISOR_WAIT_FORBIDDEN"),
        "WAIT_ALL": ("ALERT", "SUPERVISOR_WAIT_FORBIDDEN"),
    },
    "PATROL_UNIQUENESS": {
        "UNIQUE_PATROL_AND_HEARTBEAT": ("NORMAL", ""),
        "DUPLICATE_PATROL": ("ALERT", "DUPLICATE_PATROL"),
        "DUPLICATE_HEARTBEAT": ("ALERT", "DUPLICATE_PATROL"),
    },
    "THREAD_PIN": {
        "UNPINNED_OR_OWNER_PROVEN": ("NORMAL", ""),
        "UNAUTHORIZED_THREAD_PIN": ("ALERT", "UNAUTHORIZED_THREAD_PIN"),
        "PIN_PROVENANCE_UNKNOWN": ("ALERT", "PIN_PROVENANCE_UNKNOWN"),
    },
    "TERMINAL_CLOSURE": {
        "RUN_NOT_TERMINAL": ("NORMAL", ""),
        "PATROL_CLOSED": ("NORMAL", ""),
        "TERMINAL_CLOSURE_MISSING": ("ALERT", "PATROL_NOT_CLOSED"),
    },
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


def validate_model_floor(model: object) -> str:
    value = text(model, "SLK_RUNTIME_MODEL_BINDING_INVALID", "actual_model")
    if value != value.strip():
        fail(
            "SLK_RUNTIME_MODEL_EQUIVALENCE_INVALID",
            "model identity cannot contain leading or trailing whitespace",
        )
    lowered = value.lower()
    if lowered.startswith("gpt-"):
        if value != lowered:
            fail(
                "SLK_RUNTIME_MODEL_EQUIVALENCE_INVALID",
                "GPT model identity must use its canonical lowercase identifier",
            )
        match = re.fullmatch(
            r"gpt-(\d+)(?:\.(\d+))?(?:-[a-z0-9][a-z0-9._-]*)?",
            lowered,
        )
        if match is None:
            fail("SLK_RUNTIME_MODEL_FLOOR", "unparseable GPT model claim")
        major = int(match.group(1))
        minor = int(match.group(2) or 0)
        if major < 5 or (major == 5 and minor <= 5):
            fail("SLK_RUNTIME_MODEL_FLOOR", "GPT 5.5 and lower are forbidden")
        return lowered
    return value


def classify_known_gpt_family(model: str) -> tuple[str, str] | None:
    match = KNOWN_GPT_FAMILY.match(model)
    if match is None:
        return None
    reference_model = match.group(1)
    return reference_model, REFERENCE_CLASSES[reference_model]


def model_scope_key(binding: dict) -> tuple[str, str, str, str, str, str]:
    return (
        str(binding.get("role")),
        str(binding.get("role_instance_id")),
        str(binding.get("scope_kind")),
        str(binding.get("go_id")),
        str(binding.get("cell_id")),
        str(binding.get("round_id")),
    )


def validate_model_binding(binding: object, *, run_id: str) -> dict:
    item = mapping(binding, "SLK_RUNTIME_MODEL_BINDING_INVALID", "model binding")
    expected_fields = {
        "sequence",
        "binding_id",
        "binding_version",
        "status",
        "role",
        "role_instance_id",
        "scope_kind",
        "go_id",
        "cell_id",
        "round_id",
        "selection_level",
        "work_class",
        "selection_reason",
        "selection_evidence_refs",
        "reference_model",
        "actual_model",
        "capability_class",
        "capability_equivalence",
        "reasoning_effort",
        "owner_ultra_authorization_ref",
        "cell_contract_ref",
        "cell_granularity",
        "risk_level",
        "contract_luna_allowed",
        "readiness_gate",
        "isolation_gate",
        "verification_gate",
        "model_switch",
        "supersedes_binding_id",
        "switch_reason",
        "switch_evidence_refs",
        "evidence_refs",
    }
    if set(item) != expected_fields:
        fail("SLK_RUNTIME_MODEL_BINDING_INVALID", "model binding fields are closed")
    integer(item.get("sequence"), "SLK_RUNTIME_MODEL_BINDING_INVALID", "sequence", minimum=1)
    text(item.get("binding_id"), "SLK_RUNTIME_MODEL_BINDING_INVALID", "binding_id")
    integer(
        item.get("binding_version"),
        "SLK_RUNTIME_MODEL_BINDING_INVALID",
        "binding_version",
        minimum=1,
    )
    if item.get("status") not in {"CURRENT", "SUPERSEDED"}:
        fail("SLK_RUNTIME_MODEL_BINDING_INVALID", "binding status must be CURRENT or SUPERSEDED")
    role = item.get("role")
    if role not in MODEL_ROLES:
        fail("SLK_RUNTIME_MODEL_ROLE_ISOLATION", "model binding role is outside SLK")
    text(item.get("role_instance_id"), "SLK_RUNTIME_MODEL_ROLE_ISOLATION", "role_instance_id")

    scope_kind = item.get("scope_kind")
    if scope_kind not in {"RUN", "GO", "CELL", "ROUND"}:
        fail("SLK_RUNTIME_MODEL_BINDING_SCOPE", "invalid model binding scope")
    for name in ("go_id", "cell_id", "round_id"):
        if not isinstance(item.get(name), str):
            fail("SLK_RUNTIME_MODEL_BINDING_SCOPE", f"{name} must be text")
    go_id, cell_id, round_id = item["go_id"], item["cell_id"], item["round_id"]
    scope_valid = {
        "RUN": not go_id and not cell_id and not round_id,
        "GO": bool(go_id) and not cell_id and not round_id,
        "CELL": bool(go_id and cell_id) and not round_id,
        "ROUND": bool(go_id and cell_id and round_id),
    }[scope_kind]
    if not scope_valid:
        fail("SLK_RUNTIME_MODEL_BINDING_SCOPE", "scope identifiers do not match scope_kind")

    reference_model = item.get("reference_model")
    capability_class = item.get("capability_class")
    if REFERENCE_CLASSES.get(reference_model) != capability_class:
        fail("SLK_RUNTIME_MODEL_EQUIVALENCE_INVALID", "reference model and capability class differ")
    actual_model = validate_model_floor(item.get("actual_model"))
    equivalence = mapping(
        item.get("capability_equivalence"),
        "SLK_RUNTIME_MODEL_EQUIVALENCE_INVALID",
        "capability_equivalence",
    )
    if set(equivalence) != {"status", "evidence_refs"}:
        fail("SLK_RUNTIME_MODEL_EQUIVALENCE_INVALID", "equivalence fields are closed")
    evidence(
        equivalence.get("evidence_refs"),
        "SLK_RUNTIME_MODEL_EQUIVALENCE_INVALID",
    )
    known_family = classify_known_gpt_family(actual_model)
    if known_family is not None:
        known_reference_model, known_actual_class = known_family
        expected_equivalence = (
            "EXACT_REFERENCE"
            if actual_model == known_reference_model
            else "PROVEN_EQUIVALENT"
        )
        if (
            reference_model != known_reference_model
            or capability_class != known_actual_class
            or equivalence.get("status") != expected_equivalence
        ):
            fail(
                "SLK_RUNTIME_MODEL_EQUIVALENCE_INVALID",
                "known GPT family requires its canonical reference and real class",
            )
    elif equivalence.get("status") != "PROVEN_EQUIVALENT":
        fail("SLK_RUNTIME_MODEL_EQUIVALENCE_INVALID", "model equivalence is not proven")

    effort = item.get("reasoning_effort")
    owner_ultra_ref = item.get("owner_ultra_authorization_ref")
    if effort not in {"xhigh", "ultra"} or not isinstance(owner_ultra_ref, str):
        fail("SLK_RUNTIME_MODEL_BINDING_INVALID", "reasoning effort must be xhigh or Owner-authorized ultra")
    if effort == "ultra":
        owner_role = str(role).replace("_RESPONSIBILITY", "")
        expected_ultra_ref = f"owner-auth/{run_id}/{owner_role}/ULTRA"
        if owner_ultra_ref != expected_ultra_ref:
            fail("SLK_RUNTIME_MODEL_ULTRA_FORBIDDEN", "ultra requires exact Owner authorization")
    elif owner_ultra_ref:
        fail("SLK_RUNTIME_MODEL_ULTRA_FORBIDDEN", "unused ultra authorization is forbidden")

    selection_level = item.get("selection_level")
    work_class = item.get("work_class")
    if item.get("selection_reason") != MODEL_SELECTION_REASONS.get(work_class):
        fail("SLK_RUNTIME_MODEL_SELECTION_INVALID", "selection reason does not match work class")
    evidence(
        item.get("selection_evidence_refs"),
        "SLK_RUNTIME_MODEL_SELECTION_INVALID",
    )
    cell_ref = mapping(
        item.get("cell_contract_ref"),
        "SLK_RUNTIME_MODEL_SELECTION_INVALID",
        "cell_contract_ref",
    )
    if scope_kind in {"CELL", "ROUND"}:
        ref(cell_ref, "SLK_RUNTIME_MODEL_SELECTION_INVALID", "cell_contract_ref", hashed=True)
    elif cell_ref:
        fail("SLK_RUNTIME_MODEL_SELECTION_INVALID", "non-CELL scope cannot claim a CELL contract")
    if item.get("cell_granularity") not in {"NOT_APPLICABLE", "FINE_GRAINED", "COARSE"}:
        fail("SLK_RUNTIME_MODEL_SELECTION_INVALID", "invalid CELL granularity")
    if item.get("risk_level") not in {"NOT_APPLICABLE", "LOW", "MEDIUM", "HIGH"}:
        fail("SLK_RUNTIME_MODEL_SELECTION_INVALID", "invalid risk level")
    boolean(
        item.get("contract_luna_allowed"),
        "SLK_RUNTIME_MODEL_SELECTION_INVALID",
        "contract_luna_allowed",
    )

    if selection_level == "DEFAULT":
        expected_work = "NON_TECHNICAL_PATROL" if role == "RUN_PATROL" else "STANDARD_TECHNICAL"
        valid_selection = (
            reference_model == "gpt-5.6-terra"
            and capability_class == "TERRA_CLASS"
            and work_class == expected_work
            and item.get("contract_luna_allowed") is False
        )
    elif selection_level == "CELL_LOW_RISK_EXCEPTION":
        valid_selection = (
            role == "WORKER"
            and scope_kind in {"CELL", "ROUND"}
            and reference_model == "gpt-5.6-luna"
            and capability_class == "LUNA_CLASS"
            and work_class == "FINE_GRAINED_LOW_RISK"
            and item.get("cell_granularity") == "FINE_GRAINED"
            and item.get("risk_level") == "LOW"
            and item.get("contract_luna_allowed") is True
        )
    elif selection_level == "HIGH_DIFFICULTY_ESCALATION":
        valid_selection = (
            role in SLK_TECHNICAL_ROLES
            and scope_kind in {"GO", "CELL", "ROUND"}
            and reference_model == "gpt-5.6-sol"
            and capability_class == "SOL_CLASS"
            and work_class in HIGH_DIFFICULTY_WORK
            and item.get("contract_luna_allowed") is False
        )
    else:
        valid_selection = False
    if not valid_selection:
        fail("SLK_RUNTIME_MODEL_SELECTION_INVALID", "model selection level is not authorized for this role/work")

    for name in ("readiness_gate", "isolation_gate", "verification_gate"):
        if item.get(name) != "PASS":
            fail("SLK_RUNTIME_MODEL_REVALIDATION_REQUIRED", f"{name} must PASS")
    boolean(item.get("model_switch"), "SLK_RUNTIME_MODEL_BINDING_INVALID", "model_switch")
    for name in ("supersedes_binding_id", "switch_reason"):
        if not isinstance(item.get(name), str):
            fail("SLK_RUNTIME_MODEL_BINDING_INVALID", f"{name} must be text")
    switch_evidence = sequence(
        item.get("switch_evidence_refs"),
        "SLK_RUNTIME_MODEL_BINDING_INVALID",
        "switch_evidence_refs",
    )
    if any(not isinstance(value, str) or not value for value in switch_evidence):
        fail("SLK_RUNTIME_MODEL_BINDING_INVALID", "switch evidence must be immutable refs")
    evidence(item.get("evidence_refs"), "SLK_RUNTIME_MODEL_BINDING_INVALID")
    return item


def validate_model_binding_trace(packet: dict) -> None:
    expected_fields = {
        "schema_version",
        "record_type",
        "status",
        "run_id",
        "trace_id",
        "version",
        "trace_sha256",
        "history_immutable",
        "bindings",
        "evidence_refs",
    }
    if set(packet) != expected_fields:
        fail("SLK_RUNTIME_MODEL_BINDING_INVALID", "model trace fields are closed")
    if packet.get("status") != "READY" or packet.get("history_immutable") is not True:
        fail("SLK_RUNTIME_MODEL_REVALIDATION_REQUIRED", "model trace must be READY and immutable")
    run_id = text(packet.get("run_id"), "SLK_RUNTIME_MODEL_BINDING_INVALID", "run_id")
    text(packet.get("trace_id"), "SLK_RUNTIME_MODEL_BINDING_INVALID", "trace_id")
    integer(packet.get("version"), "SLK_RUNTIME_MODEL_BINDING_INVALID", "version", minimum=1)
    sha256(packet.get("trace_sha256"), "SLK_RUNTIME_MODEL_BINDING_INVALID", "trace_sha256")
    raw_bindings = sequence(
        packet.get("bindings"),
        "SLK_RUNTIME_MODEL_BINDING_INVALID",
        "bindings",
    )
    if not raw_bindings:
        fail("SLK_RUNTIME_MODEL_BINDING_INVALID", "model trace requires bindings")
    bindings = [validate_model_binding(value, run_id=run_id) for value in raw_bindings]
    if [item["sequence"] for item in bindings] != list(range(1, len(bindings) + 1)):
        fail("SLK_RUNTIME_MODEL_BINDING_INVALID", "binding sequence must be contiguous")
    binding_ids = [item["binding_id"] for item in bindings]
    if len(binding_ids) != len(set(binding_ids)):
        fail("SLK_RUNTIME_MODEL_ROLE_ISOLATION", "binding IDs cannot be shared across roles")

    role_instances: dict[str, set[str]] = {}
    instance_roles: dict[str, set[str]] = {}
    for item in bindings:
        role_instances.setdefault(item["role"], set()).add(item["role_instance_id"])
        instance_roles.setdefault(item["role_instance_id"], set()).add(item["role"])
    if any(len(instance_ids) != 1 for instance_ids in role_instances.values()):
        fail(
            "SLK_RUNTIME_MODEL_ROLE_ISOLATION",
            "each SLK role must retain one stable role instance within the Run",
        )
    if any(len(roles) != 1 for roles in instance_roles.values()):
        fail(
            "SLK_RUNTIME_MODEL_ROLE_ISOLATION",
            "a role instance cannot be shared across SLK roles",
        )

    groups: dict[tuple[str, str, str, str, str, str], list[dict]] = {}
    for item in bindings:
        groups.setdefault(model_scope_key(item), []).append(item)
    for values in groups.values():
        values.sort(key=lambda value: value["binding_version"])
        if [item["binding_version"] for item in values] != list(range(1, len(values) + 1)):
            fail("SLK_RUNTIME_SILENT_MODEL_SWITCH", "binding versions must be contiguous")
        first = values[0]
        if (
            first["model_switch"] is not False
            or first["supersedes_binding_id"]
            or first["switch_reason"]
            or first["switch_evidence_refs"]
        ):
            fail("SLK_RUNTIME_SILENT_MODEL_SWITCH", "initial binding cannot claim a switch")
        for previous, current in zip(values, values[1:]):
            changed = (
                previous["actual_model"] != current["actual_model"]
                or previous["reasoning_effort"] != current["reasoning_effort"]
            )
            if (
                not changed
                or current["model_switch"] is not True
                or current["supersedes_binding_id"] != previous["binding_id"]
                or not current["switch_reason"]
                or not current["switch_evidence_refs"]
            ):
                fail("SLK_RUNTIME_SILENT_MODEL_SWITCH", "model change requires a new evidenced binding")
        if any(item["status"] != "SUPERSEDED" for item in values[:-1]):
            fail("SLK_RUNTIME_SILENT_MODEL_SWITCH", "prior binding must be superseded")
        if values[-1]["status"] != "CURRENT":
            fail("SLK_RUNTIME_MODEL_REVALIDATION_REQUIRED", "each role/scope needs one current binding")

    current_roles = {
        item["role"]
        for item in bindings
        if item["status"] == "CURRENT"
    }
    if current_roles != MODEL_ROLES:
        fail("SLK_RUNTIME_MODEL_ROLE_ISOLATION", "every SLK role needs a separate current binding")
    evidence(packet.get("evidence_refs"), "SLK_RUNTIME_MODEL_BINDING_INVALID")


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
    patrol_model = validate_model_floor(patrol.get("model"))
    if patrol_model in {"gpt-5.6-luna", "gpt-5.6-sol"}:
        fail("SLK_RUNTIME_MODEL_SELECTION_INVALID", "Patrol uses Terra class only")
    text(
        patrol.get("model_binding_id"),
        "SLK_RUNTIME_MODEL_BINDING_INVALID",
        "patrol.model_binding_id",
    )
    patrol_effort = patrol.get("reasoning_effort")
    patrol_ultra_ref = patrol.get("owner_ultra_authorization_ref")
    if patrol_effort not in {"xhigh", "ultra"} or not isinstance(patrol_ultra_ref, str):
        fail("SLK_RUNTIME_MODEL_BINDING_INVALID", "Patrol effort requires a current binding")
    expected_patrol_ultra_ref = f"owner-auth/{run_id}/RUN_PATROL/ULTRA"
    if patrol_effort == "ultra" and patrol_ultra_ref != expected_patrol_ultra_ref:
        fail("SLK_RUNTIME_MODEL_ULTRA_FORBIDDEN", "Patrol ultra requires exact Owner authorization")
    if patrol_effort == "xhigh" and patrol_ultra_ref:
        fail("SLK_RUNTIME_MODEL_ULTRA_FORBIDDEN", "unused Patrol ultra authorization is forbidden")
    workload_class = packet.get("workload_class")
    if workload_class not in WORKLOAD_INTERVALS:
        fail("SLK_RUNTIME_PATROL_DIFFICULTY_INTERVAL", "workload_class must be LOW, MEDIUM, or HIGH")
    if patrol.get("interval_minutes") != WORKLOAD_INTERVALS[workload_class]:
        fail("SLK_RUNTIME_PATROL_DIFFICULTY_INTERVAL", "Patrol interval must match frozen workload_class")
    text(patrol.get("conversation_id"), "SLK_RUNTIME_PATROL_UNIQUE", "patrol.conversation_id")
    expected_heartbeat = f"SLK-PATROL-{run_id}"
    if patrol.get("heartbeat_id") != expected_heartbeat:
        fail("SLK_RUNTIME_PATROL_UNIQUE", "Patrol heartbeat must be deterministic")

    trace_ref = ref(
        packet.get("model_binding_trace_ref"),
        "SLK_RUNTIME_MODEL_BINDING_INVALID",
        "model_binding_trace_ref",
        hashed=True,
    )
    if set(trace_ref) != {"id", "version", "sha256"}:
        fail("SLK_RUNTIME_MODEL_BINDING_INVALID", "model trace ref must be versioned and hashed")

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
        or wait.get("wait_for_all_members_allowed") is not False
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
    if set(pin.get("technical_roles", [])) != SLK_TECHNICAL_ROLES:
        fail("SLK_RUNTIME_PIN_ROLE_INVALID", "SLK technical roles are Control responsibilities plus Worker")
    if (
        pin.get("technical_role_pin_allowed_by_default") is not False
        or pin.get("set_thread_pinned_true_capability") != "DENIED"
        or pin.get("owner_manual_allowed") is not True
        or pin.get("owner_explicit_item_authorization_allowed") is not True
        or pin.get("inferred_authorization_allowed") is not False
        or pin.get("patrol_pin_capability") != "DENIED"
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
        elif item.get("result") == "PROCESSING_STARTED":
            text(
                item.get("processing_started_ref"),
                "SLK_RUNTIME_WAKE_PROCESSING_EVIDENCE",
                "processing_started_ref",
            )
            ack_seen = True

    if ack_seen:
        expected_status = (
            "ACKNOWLEDGED"
            if attempts[-1].get("result") == "ACK"
            else "PROCESSING_STARTED"
        )
        if packet.get("status") != expected_status or packet.get("stopped") is not True:
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
    patrol_model = validate_model_floor(packet.get("model"))
    if patrol_model in {"gpt-5.6-luna", "gpt-5.6-sol"}:
        fail("SLK_RUNTIME_MODEL_SELECTION_INVALID", "Patrol uses Terra class only")
    text(
        packet.get("model_binding_id"),
        "SLK_RUNTIME_MODEL_BINDING_INVALID",
        "model_binding_id",
    )
    patrol_effort = packet.get("reasoning_effort")
    patrol_ultra_ref = packet.get("owner_ultra_authorization_ref")
    if patrol_effort not in {"xhigh", "ultra"} or not isinstance(patrol_ultra_ref, str):
        fail("SLK_RUNTIME_MODEL_BINDING_INVALID", "Patrol effort requires a current binding")
    expected_patrol_ultra_ref = f"owner-auth/{packet.get('run_id')}/RUN_PATROL/ULTRA"
    if patrol_effort == "ultra" and patrol_ultra_ref != expected_patrol_ultra_ref:
        fail("SLK_RUNTIME_MODEL_ULTRA_FORBIDDEN", "Patrol ultra requires exact Owner authorization")
    if patrol_effort == "xhigh" and patrol_ultra_ref:
        fail("SLK_RUNTIME_MODEL_ULTRA_FORBIDDEN", "unused Patrol ultra authorization is forbidden")
    if (
        packet.get("conversation_count") != 1
        or packet.get("heartbeat_count") != 1
    ):
        fail("SLK_RUNTIME_PATROL_UNIQUE", "Patrol and heartbeat are unique per Run")
    workload_class = packet.get("workload_class")
    if workload_class not in WORKLOAD_INTERVALS:
        fail("SLK_RUNTIME_PATROL_DIFFICULTY_INTERVAL", "Patrol workload_class is required")
    if packet.get("interval_minutes") != WORKLOAD_INTERVALS[workload_class]:
        fail("SLK_RUNTIME_PATROL_DIFFICULTY_INTERVAL", "Patrol interval must match workload_class")
    cycle_id = text(
        packet.get("patrol_cycle_id"),
        "SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE",
        "patrol_cycle_id",
    )
    if not cycle_id.startswith(f"PATROL-{packet.get('run_id')}-CYCLE-"):
        fail("SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "patrol_cycle_id must bind the Run")
    actions = sequence(packet.get("actions"), "SLK_RUNTIME_PATROL_ACTION_FORBIDDEN", "actions")
    if actions:
        fail("SLK_RUNTIME_PATROL_ACTION_FORBIDDEN", "Patrol may only observe and alert")
    if packet.get("engineering_progress_reported") is not False:
        fail("SLK_RUNTIME_PATROL_PROGRESS_FORBIDDEN", "Patrol cannot report engineering progress")

    checklist = sequence(
        packet.get("checklist"),
        "SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE",
        "checklist",
    )
    kinds = [item.get("check_kind") for item in checklist if isinstance(item, dict)]
    if len(kinds) != len(set(kinds)):
        fail("SLK_RUNTIME_PATROL_CHECKLIST_DUPLICATE", "each check_kind appears once per cycle")
    if set(kinds) != PATROL_REQUIRED_CHECKS:
        fail("SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "every patrol cycle requires the fixed checklist")
    expected_fields = {
        "check_kind",
        "finding",
        "result",
        "alert_code",
        "timeout_ms",
        "inside_loop",
        "looped",
        "wait_all",
        "legitimate_reason_ref",
        "evidence_refs",
    }
    by_kind: dict[str, dict] = {}
    for raw in checklist:
        item = mapping(raw, "SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "patrol check")
        if set(item) != expected_fields:
            fail("SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "free text cannot replace checklist fields")
        kind = item["check_kind"]
        finding = item.get("finding")
        if finding not in PATROL_FINDINGS[kind]:
            fail("SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", f"invalid {kind} finding")
        expected_result, expected_alert = PATROL_FINDINGS[kind][finding]
        if item.get("result") != expected_result or item.get("alert_code") != expected_alert:
            code = (
                "SLK_RUNTIME_PATROL_FALSE_POSITIVE"
                if expected_result == "NORMAL" and item.get("result") == "ALERT"
                else "SLK_RUNTIME_PATROL_MISSED_ALERT"
            )
            fail(code, f"{kind}/{finding} requires {expected_result}/{expected_alert}")
        integer(item.get("timeout_ms"), "SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "timeout_ms")
        for name in ("inside_loop", "looped", "wait_all"):
            boolean(item.get(name), "SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", name)
        if not isinstance(item.get("legitimate_reason_ref"), str):
            fail("SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "legitimate_reason_ref must be text")
        evidence(item.get("evidence_refs"), "SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE")
        by_kind[kind] = item

    wait = by_kind["SUPERVISOR_WAIT"]
    wait_fault = wait["timeout_ms"] > 0 or wait["looped"] or wait["wait_all"]
    if wait_fault and wait["result"] != "ALERT":
        fail("SLK_RUNTIME_PATROL_MISSED_ALERT", "any positive, looped, or wait-all Supervisor wait alerts")
    if wait["finding"] == "POSITIVE_WAIT" and wait["timeout_ms"] <= 0:
        fail("SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "POSITIVE_WAIT requires timeout_ms > 0")
    if wait["finding"] == "LOOPED_WAIT" and wait["looped"] is not True:
        fail("SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "LOOPED_WAIT requires looped=true")
    if wait["finding"] == "WAIT_ALL" and wait["wait_all"] is not True:
        fail("SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "WAIT_ALL requires wait_all=true")
    if not wait_fault and wait["finding"] != "ZERO_SNAPSHOT_OR_NONE":
        fail("SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "zero snapshot/absence is the only normal wait state")

    forward = by_kind["FORWARD_MOTION"]
    legitimate_state = packet.get("run_state") in {
        "FORMALLY_PAUSED",
        "LEGAL_BLOCKED",
        "WAITING_EXTERNAL",
    }
    if legitimate_state:
        if forward["finding"] != "LEGITIMATE_PAUSE" or not forward["legitimate_reason_ref"]:
            fail("SLK_RUNTIME_PATROL_FALSE_POSITIVE", "legal pause/block/external wait needs reason evidence")
    elif forward["finding"] == "LEGITIMATE_PAUSE":
        fail("SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "LEGITIMATE_PAUSE requires a legal Run state")
    cleanup = mapping(
        packet.get("terminal_cleanup"),
        "SLK_RUNTIME_PATROL_NOT_CLOSED",
        "terminal_cleanup",
    )
    terminal = by_kind["TERMINAL_CLOSURE"]
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
        if terminal["finding"] != "PATROL_CLOSED":
            fail("SLK_RUNTIME_PATROL_NOT_CLOSED", "closed Patrol cycle must record PATROL_CLOSED")
    elif terminal["finding"] != "RUN_NOT_TERMINAL":
        fail("SLK_RUNTIME_PATROL_CHECKLIST_INCOMPLETE", "non-terminal Run must record RUN_NOT_TERMINAL")
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
        candidate = mapping(
            value.get("candidate_ref"),
            "SLK_RUNTIME_PROGRESS_COUNT_MISMATCH",
            "receipt.candidate_ref",
        )
        sha256(
            candidate.get("sha256"),
            "SLK_RUNTIME_PROGRESS_COUNT_MISMATCH",
            "receipt.candidate_ref.sha256",
        )
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
    acknowledged: set[tuple[str, str, str]] = set()
    last_accepted: dict[int, set[str]] = {}
    last_verified: dict[int, set[str]] = {}
    seen_events: dict[str, dict] = {}
    material_trigger_ids: list[str] = []
    supervisor_progress_by_trigger: dict[str, int] = {}
    candidate_ready_by_go: dict[tuple[int, str], str] = {}
    candidate_trigger_by_go: dict[tuple[int, str], tuple[str, str]] = {}
    initial_required_set_version = min(required_sets)
    amended_versions: set[int] = set()
    for expected_sequence, raw in enumerate(events, start=1):
        event = mapping(raw, "SLK_RUNTIME_PROGRESS_COUNT_MISMATCH", "event")
        if event.get("sequence") != expected_sequence:
            fail("SLK_RUNTIME_PROGRESS_COUNT_MISMATCH", "event sequence must be contiguous")
        event_id = text(
            event.get("event_id"),
            "SLK_RUNTIME_PROGRESS_TRIGGER_INVALID",
            "event_id",
        )
        if event_id in seen_events:
            fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "event_id must be unique")
        trigger_id = event.get("trigger_event_id")
        if expected_sequence == 1:
            if trigger_id != "":
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "first progress event has no trigger")
            trigger_event = None
        else:
            if not isinstance(trigger_id, str) or trigger_id not in seen_events:
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "trigger_event_id must name an earlier event")
            trigger_event = seen_events[trigger_id]
        trigger_receipt_id = event.get("trigger_receipt_id")
        trigger_verdict = event.get("trigger_verdict")
        if not isinstance(trigger_receipt_id, str) or trigger_verdict not in {"NONE", "PASS", "FAIL", "BLOCKED"}:
            fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "trigger receipt/verdict binding is invalid")
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
        event_kind = event.get("event")
        if version != initial_required_set_version and version not in amended_versions:
            if event_kind != "AMENDMENT":
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "Required-set version must begin with its amendment progress")
            if trigger_event is None or trigger_event.get("required_set_version") >= version:
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "amendment must follow an earlier Required-set version")
            amended_versions.add(version)
        elif event_kind == "AMENDMENT":
            fail("SLK_RUNTIME_PROGRESS_MILESTONE_DUPLICATE", "Required-set amendment progress must be unique")
        prior_accepted = last_accepted.get(version, set())
        prior_verified = last_verified.get(version, set())
        new_accepted = accepted - prior_accepted
        new_verified = verified - prior_verified
        if event_kind not in {"D1_ACCEPTED", "AMENDMENT"} and new_accepted:
            fail("SLK_RUNTIME_PROGRESS_COUNT_MISMATCH", "delivery/check/rework cannot add D1 acceptance")
        if event_kind == "D1_ACCEPTED" and (
            len(new_accepted) > 1
            or (new_accepted and event.get("cell_id") not in new_accepted)
        ):
            fail("SLK_RUNTIME_PROGRESS_COUNT_MISMATCH", "one D1 decision can accept only its CELL")
        if event_kind == "GO_CANDIDATE_READY" and new_verified:
            fail("SLK_RUNTIME_PROGRESS_LAYER_CONFUSION", "candidate-ready is not a new D2 verdict")
        if (
            event_kind == "GO_CANDIDATE_READY"
            and event.get("verified_go_count") != len(verified)
        ):
            fail("SLK_RUNTIME_PROGRESS_LAYER_CONFUSION", "candidate-ready cannot claim a D2 count")
        if event_kind not in {"D2_VERIFIED", "AMENDMENT"} and new_verified:
            fail("SLK_RUNTIME_PROGRESS_LAYER_CONFUSION", "only a D2 verdict adds GO verification")
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
        audience = event.get("audience")
        if actor == "RUN_PATROL":
            fail("SLK_RUNTIME_PROGRESS_ROLE_FORBIDDEN", "Patrol cannot emit engineering progress")
        if actor == "VERIFIER" and event_kind not in {"D2_VERIFIED", "RUN_VERIFIED"}:
            fail("SLK_RUNTIME_PROGRESS_ROLE_FORBIDDEN", "Verifier emits formal verdicts only")
        if actor == "OWNER" and event_kind != "OWNER_ACCEPTED":
            fail("SLK_RUNTIME_PROGRESS_ROLE_FORBIDDEN", "Owner emits Owner Acceptance only")
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

        d1_ids = {
            item.get("receipt_id") for item in event.get("current_d1_pass_receipts", [])
        }
        d1_receipt_members = {
            item.get("receipt_id"): item.get("cell_id")
            for item in event.get("current_d1_pass_receipts", [])
        }
        d2_ids = {
            item.get("receipt_id") for item in event.get("current_d2_pass_receipts", [])
        }
        if event_kind in {"D1_ACCEPTED", "GO_CANDIDATE_READY"}:
            if trigger_receipt_id not in d1_ids or trigger_verdict != "PASS":
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "D1/GO boundary requires current D1 PASS binding")
            if event_kind == "D1_ACCEPTED" and new_accepted:
                if d1_receipt_members.get(trigger_receipt_id) != event.get("cell_id"):
                    fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "D1 event must bind its newly accepted CELL receipt")
                if accepted == required_cells:
                    candidate_trigger_by_go[(version, str(go_id))] = (
                        event_id,
                        trigger_receipt_id,
                    )
            if event_kind == "GO_CANDIDATE_READY":
                key = (version, str(go_id))
                if actor != "CHECKER" or audience != "SUPERVISOR":
                    fail("SLK_RUNTIME_PROGRESS_ROLE_FORBIDDEN", "GO candidate is Checker-to-Supervisor only")
                if key in candidate_ready_by_go:
                    fail("SLK_RUNTIME_PROGRESS_MILESTONE_DUPLICATE", "GO candidate milestone must be unique")
                if candidate_trigger_by_go.get(key) != (trigger_id, trigger_receipt_id):
                    fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "GO candidate must follow the D1 event that completed its Required CELL set")
                candidate_ready_by_go[key] = event_id
        elif event_kind == "D2_VERIFIED":
            if trigger_receipt_id not in d2_ids or trigger_verdict != "PASS":
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "D2 event requires current D2 PASS binding")
            ready_id = candidate_ready_by_go.get((version, str(go_id)))
            if not ready_id or trigger_id != ready_id:
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "D2 must follow the bound GO_CANDIDATE_READY")
            material_trigger_ids.append(event_id)
        elif event_kind in {"RUN_VERIFIED", "OWNER_ACCEPTED"}:
            if not trigger_receipt_id or trigger_verdict != "PASS":
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "Run/Owner milestone requires formal PASS receipt")
            material_trigger_ids.append(event_id)
        elif event_kind == "GLOBAL_PROGRESS":
            if actor != "SUPERVISOR" or audience != "OWNER" or trigger_event is None:
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "GLOBAL_PROGRESS is Supervisor-to-Owner")
            if trigger_event.get("event") not in {"D2_VERIFIED", "RUN_VERIFIED", "OWNER_ACCEPTED"}:
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "GLOBAL_PROGRESS trigger is not a material verdict")
            if (
                trigger_receipt_id != trigger_event.get("trigger_receipt_id")
                or trigger_verdict != trigger_event.get("trigger_verdict")
            ):
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "GLOBAL_PROGRESS must bind the exact verdict receipt")
            supervisor_progress_by_trigger[trigger_id] = (
                supervisor_progress_by_trigger.get(trigger_id, 0) + 1
            )
        elif event_kind == "AMENDMENT":
            if actor != "SUPERVISOR" or audience != "OWNER" or not trigger_receipt_id:
                fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "amendment progress binds its versioned receipt")
        elif trigger_receipt_id or trigger_verdict != "NONE":
            fail("SLK_RUNTIME_PROGRESS_TRIGGER_INVALID", "non-verdict event cannot claim a verdict receipt")

        scope = (str(go_id), str(event.get("cell_id")), str(event.get("round_id")))
        if event_kind == "WAKE_ACK":
            if actor != "CHECKER":
                fail("SLK_RUNTIME_PROGRESS_LAYER_CONFUSION", "Checker owns WAKE_ACK")
            acknowledged.add(scope)
        if event_kind == "CHECKING" and scope not in acknowledged:
            fail("SLK_RUNTIME_PROGRESS_LAYER_CONFUSION", "Checker must ACK before checking")
        if event_kind == "AMENDMENT":
            if event.get("recomputed") is not True or version != max(required_sets):
                fail("SLK_RUNTIME_PROGRESS_AMENDMENT_STALE", "amendment must use latest version and recompute")
        last_accepted[version] = accepted
        last_verified[version] = verified
        seen_events[event_id] = event
    for trigger_id in material_trigger_ids:
        count = supervisor_progress_by_trigger.get(trigger_id, 0)
        if count == 0:
            fail("SLK_RUNTIME_PROGRESS_MILESTONE_MISSING", "material verdict lacks Supervisor progress")
        if count != 1:
            fail("SLK_RUNTIME_PROGRESS_MILESTONE_DUPLICATE", "material verdict has duplicate Supervisor progress")
    missing_amendments = set(required_sets) - {initial_required_set_version} - amended_versions
    if missing_amendments:
        fail("SLK_RUNTIME_PROGRESS_MILESTONE_MISSING", "Required-set amendment progress is missing")
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
    integer(packet.get("version"), "SLK_RUNTIME_LOAD_STALE", "version", minimum=1)
    ref(packet.get("device_capacity_profile_ref"), "SLK_RUNTIME_LOAD_STALE", "device profile")
    ref(packet.get("baseline_ref"), "SLK_RUNTIME_LOAD_STALE", "baseline", hashed=True)
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
    text(packet.get("round_id"), "SLK_RUNTIME_CAPACITY_UNKNOWN", "round_id")
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
    if packet.get("task_role") not in PIN_SUBJECT_ROLES:
        fail("SLK_RUNTIME_PIN_ROLE_INVALID", "task_role is neither an SLK technical role nor Run Patrol")
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


def dispatch_scope(value: dict) -> tuple[str, str, str, str]:
    return (
        str(value.get("run_id")),
        str(value.get("go_id")),
        str(value.get("cell_id")),
        str(value.get("round_id")),
    )


def model_binding_covers_dispatch(binding: dict, dispatch: dict) -> bool:
    if binding.get("role") != "WORKER" or binding.get("status") != "CURRENT":
        return False
    scope_kind = binding.get("scope_kind")
    if scope_kind == "RUN":
        return True
    if binding.get("go_id") != dispatch.get("go_id"):
        return False
    if scope_kind == "GO":
        return True
    if binding.get("cell_id") != dispatch.get("cell_id"):
        return False
    if scope_kind == "CELL":
        return True
    return scope_kind == "ROUND" and binding.get("round_id") == dispatch.get("round_id")


def validate_runtime_index(packet: dict) -> None:
    if packet.get("status") != "COMPLETE":
        fail("SLK_RUNTIME_INDEX_MISSING", "Run runtime index must be COMPLETE")
    run_id = text(packet.get("run_id"), "SLK_RUNTIME_INDEX_SCOPE", "run_id")
    integer(packet.get("index_version"), "SLK_RUNTIME_INDEX_STALE", "index_version", minimum=1)
    contract = mapping(
        packet.get("runtime_contract"),
        "SLK_RUNTIME_INDEX_MISSING",
        "runtime_contract",
    )
    if not contract:
        fail("SLK_RUNTIME_INDEX_MISSING", "runtime_contract is required")
    validate(contract)
    if contract.get("record_type") != "RUN_RUNTIME_CONTRACT" or contract.get("run_id") != run_id:
        fail("SLK_RUNTIME_INDEX_SCOPE", "runtime contract must bind the indexed Run")

    model_trace = mapping(
        packet.get("model_binding_trace"),
        "SLK_RUNTIME_INDEX_MISSING",
        "model_binding_trace",
    )
    if not model_trace:
        fail("SLK_RUNTIME_INDEX_MISSING", "current model binding trace is required")
    validate(model_trace)
    if model_trace.get("record_type") != "MODEL_BINDING_TRACE" or model_trace.get("run_id") != run_id:
        fail("SLK_RUNTIME_MODEL_BINDING_SCOPE", "model trace must bind the indexed Run")
    trace_ref = contract.get("model_binding_trace_ref", {})
    if (
        trace_ref.get("id") != model_trace.get("trace_id")
        or trace_ref.get("version") != model_trace.get("version")
        or trace_ref.get("sha256") != model_trace.get("trace_sha256")
    ):
        fail("SLK_RUNTIME_MODEL_BINDING_SCOPE", "runtime contract references a different model trace")
    current_model_bindings = {
        item["binding_id"]: item
        for item in model_trace.get("bindings", [])
        if item.get("status") == "CURRENT"
    }

    dispatches = sequence(packet.get("dispatches"), "SLK_RUNTIME_INDEX_MISSING", "dispatches")
    if not dispatches:
        fail("SLK_RUNTIME_INDEX_MISSING", "at least one formal dispatch is required")
    expected_dispatch_fields = {
        "dispatch_id",
        "run_id",
        "go_id",
        "cell_id",
        "cell_ordinal",
        "required_cell_total",
        "round_id",
        "required_set_version",
        "model_binding_id",
    }
    scopes: list[tuple[str, str, str, str]] = []
    dispatch_by_scope: dict[tuple[str, str, str, str], dict] = {}
    required = contract["required_sets"]
    for raw in dispatches:
        item = mapping(raw, "SLK_RUNTIME_INDEX_SCOPE", "dispatch")
        if set(item) != expected_dispatch_fields:
            fail("SLK_RUNTIME_INDEX_SCOPE", "dispatch fields are closed")
        text(item.get("dispatch_id"), "SLK_RUNTIME_INDEX_SCOPE", "dispatch_id")
        model_binding_id = text(
            item.get("model_binding_id"),
            "SLK_RUNTIME_MODEL_BINDING_SCOPE",
            "dispatch.model_binding_id",
        )
        model_binding = current_model_bindings.get(model_binding_id)
        if model_binding is None or not model_binding_covers_dispatch(model_binding, item):
            fail("SLK_RUNTIME_MODEL_BINDING_SCOPE", "dispatch model binding is not current Worker scope")
        scope = dispatch_scope(item)
        scopes.append(scope)
        if item.get("run_id") != run_id:
            fail("SLK_RUNTIME_INDEX_SCOPE", "dispatch Run scope mismatch")
        if item.get("required_set_version") != required.get("version"):
            fail("SLK_RUNTIME_INDEX_STALE", "dispatch Required-set version is stale")
        cells = required.get("required_cells_by_go", {}).get(item.get("go_id"), [])
        if item.get("cell_id") not in cells:
            fail("SLK_RUNTIME_INDEX_SCOPE", "dispatch CELL is outside current Required set")
        if (
            item.get("required_cell_total") != len(cells)
            or item.get("cell_ordinal") != cells.index(item.get("cell_id")) + 1
        ):
            fail("SLK_RUNTIME_INDEX_SCOPE", "dispatch ordinal/denominator mismatch")
        dispatch_by_scope[scope] = item
    if len(scopes) != len(set(scopes)) or len({item["dispatch_id"] for item in dispatches}) != len(dispatches):
        fail("SLK_RUNTIME_INDEX_DUPLICATE", "dispatch scopes and IDs must be unique")
    expected_scopes = set(scopes)

    gates = sequence(packet.get("capacity_gates"), "SLK_RUNTIME_INDEX_MISSING", "capacity_gates")
    if not gates:
        fail("SLK_RUNTIME_INDEX_MISSING", "every dispatch requires a capacity gate")
    gate_scopes: list[tuple[str, str, str, str]] = []
    for raw in gates:
        gate = mapping(raw, "SLK_RUNTIME_INDEX_SCOPE", "capacity gate")
        validate(gate)
        if gate.get("record_type") != "CELL_CAPACITY_GATE":
            fail("SLK_RUNTIME_INDEX_SCOPE", "capacity_gates may contain only CELL_CAPACITY_GATE")
        scope = dispatch_scope(gate)
        if scope not in expected_scopes:
            gate_scopes.append(scope)
            continue
        dispatch = dispatch_by_scope[scope]
        if (
            gate.get("required_set_version") != dispatch["required_set_version"]
            or gate.get("decision", {}).get("outcome") != "PASS"
            or gate.get("decision", {}).get("dispatch_allowed") is not True
        ):
            fail("SLK_RUNTIME_INDEX_STALE", "dispatch requires current capacity PASS")
        gate_scopes.append(scope)
    if len(gate_scopes) != len(set(gate_scopes)):
        fail("SLK_RUNTIME_INDEX_DUPLICATE", "capacity gates must be unique per dispatch")
    if len(gate_scopes) > len(expected_scopes):
        fail("SLK_RUNTIME_INDEX_EXTRA", "unindexed capacity gate")
    if set(gate_scopes) != expected_scopes:
        code = "SLK_RUNTIME_INDEX_MISSING" if len(gate_scopes) < len(expected_scopes) else "SLK_RUNTIME_INDEX_SCOPE"
        fail(code, "capacity gate scope set differs from dispatch set")

    wakes = sequence(packet.get("wake_traces"), "SLK_RUNTIME_INDEX_MISSING", "wake_traces")
    if not wakes:
        fail("SLK_RUNTIME_INDEX_MISSING", "every dispatch requires a wake trace")
    wake_scopes: list[tuple[str, str, str, str]] = []
    wake_values: list[dict] = []
    for raw in wakes:
        wake = mapping(raw, "SLK_RUNTIME_INDEX_SCOPE", "wake trace")
        if wake.get("record_type") != "WORKER_WAKE_TRACE":
            fail("SLK_RUNTIME_INDEX_SCOPE", "wake_traces may contain only WORKER_WAKE_TRACE")
        wake_values.append(wake)
        scope = dispatch_scope(wake)
        wake_scopes.append(scope)
        if scope in dispatch_by_scope:
            dispatch = dispatch_by_scope[scope]
            if (
                wake.get("cell_ordinal") != dispatch["cell_ordinal"]
                or wake.get("required_cell_total") != dispatch["required_cell_total"]
            ):
                fail("SLK_RUNTIME_INDEX_SCOPE", "wake position differs from dispatch")
    if len(wake_scopes) != len(set(wake_scopes)):
        fail("SLK_RUNTIME_INDEX_DUPLICATE", "wake traces must be unique per dispatch")
    if len(wake_scopes) > len(expected_scopes):
        fail("SLK_RUNTIME_INDEX_EXTRA", "unindexed wake trace")
    if set(wake_scopes) != expected_scopes:
        code = "SLK_RUNTIME_INDEX_MISSING" if len(wake_scopes) < len(expected_scopes) else "SLK_RUNTIME_INDEX_SCOPE"
        fail(code, "wake trace scope set differs from dispatch set")
    for wake in wake_values:
        validate(wake)

    progress = mapping(packet.get("progress_trace"), "SLK_RUNTIME_INDEX_MISSING", "progress_trace")
    if not progress:
        fail("SLK_RUNTIME_INDEX_MISSING", "indexed progress trace is required")
    validate(progress)
    if progress.get("record_type") != "PROGRESS_TRACE" or progress.get("run_id") != run_id:
        fail("SLK_RUNTIME_INDEX_SCOPE", "progress trace must bind the indexed Run")
    delivery_scopes = [
        dispatch_scope({**event, "run_id": run_id})
        for event in progress.get("events", [])
        if event.get("event") == "DELIVERED"
    ]
    if len(delivery_scopes) != len(set(delivery_scopes)):
        fail("SLK_RUNTIME_INDEX_DUPLICATE", "delivery progress must be unique per dispatch")
    if len(delivery_scopes) > len(expected_scopes):
        fail("SLK_RUNTIME_INDEX_EXTRA", "unindexed Worker delivery progress")
    if set(delivery_scopes) != expected_scopes:
        fail("SLK_RUNTIME_INDEX_MISSING", "every dispatch requires matching Worker delivery progress")

    patrols = sequence(packet.get("patrol_receipts"), "SLK_RUNTIME_INDEX_MISSING", "patrol_receipts")
    if len(patrols) != 1:
        code = "SLK_RUNTIME_INDEX_MISSING" if not patrols else "SLK_RUNTIME_INDEX_DUPLICATE"
        fail(code, "index requires exactly one current Patrol cycle")
    patrol = mapping(patrols[0], "SLK_RUNTIME_INDEX_SCOPE", "patrol receipt")
    validate(patrol)
    if patrol.get("record_type") != "RUN_PATROL_RECEIPT" or patrol.get("run_id") != run_id:
        fail("SLK_RUNTIME_INDEX_SCOPE", "Patrol receipt must bind the indexed Run")
    if patrol.get("workload_class") != contract.get("workload_class"):
        fail("SLK_RUNTIME_INDEX_STALE", "Patrol workload class differs from runtime contract")
    patrol_binding_id = patrol.get("model_binding_id")
    patrol_binding = current_model_bindings.get(patrol_binding_id)
    if (
        patrol_binding is None
        or patrol_binding.get("role") != "RUN_PATROL"
        or patrol_binding.get("actual_model") != patrol.get("model")
        or patrol_binding.get("reasoning_effort") != patrol.get("reasoning_effort")
        or patrol_binding.get("owner_ultra_authorization_ref")
        != patrol.get("owner_ultra_authorization_ref")
        or contract.get("patrol", {}).get("model_binding_id") != patrol_binding_id
        or contract.get("patrol", {}).get("model") != patrol.get("model")
        or contract.get("patrol", {}).get("reasoning_effort") != patrol.get("reasoning_effort")
        or contract.get("patrol", {}).get("owner_ultra_authorization_ref")
        != patrol.get("owner_ultra_authorization_ref")
    ):
        fail("SLK_RUNTIME_MODEL_BINDING_SCOPE", "Patrol record is not bound to the current model trace")
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
    "RUN_RUNTIME_INDEX": validate_runtime_index,
    "MODEL_BINDING_TRACE": validate_model_binding_trace,
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
