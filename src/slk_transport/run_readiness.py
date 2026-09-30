"""Closed, deterministic Run-start readiness evaluation for SLK roles."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping


REQUEST_FIELDS = frozenset(
    {"schema_version", "run_id", "plan_revision", "roles", "optional_features"}
)
ROLE_FIELDS = frozenset(
    {
        "role",
        "expected_runtime",
        "actual_runtime",
        "expected_model",
        "actual_model",
        "adapter_command",
        "endpoint_path",
        "workspace_root",
        "context_capacity",
        "task_context_estimate",
        "required_skills",
        "required_tools",
    }
)
OPTION_FIELDS = frozenset({"name", "decision", "owner_evidence_ref"})
REQUIRED_ROLES = ("supervisor", "worker", "checker")
REQUIRED_OPTIONS = ("Ponytail", "Temporal", "Overwatcher", "RTK", "Probe CLI")
FORBIDDEN_OPTION_NAMES = frozenset({"bom"})


def _closed(value: Mapping[str, Any], fields: frozenset[str], label: str) -> None:
    if set(value) != fields:
        raise ValueError(f"{label} must use the exact field set")


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _string_array(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValueError(f"{label} must be a non-empty string array")
    return [item.strip() for item in value]


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _tool_exists(value: str) -> bool:
    candidate = Path(value)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate.is_file()
    return shutil.which(value) is not None


def _workspace_writable(path: Path) -> bool:
    if not path.is_absolute() or not path.is_dir():
        return False
    try:
        descriptor, probe = tempfile.mkstemp(prefix=".slk-readiness-", dir=path)
        os.close(descriptor)
        Path(probe).unlink()
    except OSError:
        return False
    return True


def _role_result(raw: Mapping[str, Any]) -> dict[str, Any]:
    _closed(raw, ROLE_FIELDS, "role")
    role = _nonempty(raw["role"], "role")
    expected_runtime = _nonempty(raw["expected_runtime"], "expected_runtime")
    actual_runtime = _nonempty(raw["actual_runtime"], "actual_runtime")
    expected_model = _nonempty(raw["expected_model"], "expected_model")
    actual_model = _nonempty(raw["actual_model"], "actual_model")
    command = _string_array(raw["adapter_command"], "adapter_command")
    endpoint = Path(_nonempty(raw["endpoint_path"], "endpoint_path"))
    workspace = Path(_nonempty(raw["workspace_root"], "workspace_root"))
    capacity = _positive_int(raw["context_capacity"], "context_capacity")
    estimate = _positive_int(raw["task_context_estimate"], "task_context_estimate")
    skills = _string_array(raw["required_skills"], "required_skills")
    tools = _string_array(raw["required_tools"], "required_tools")

    incompatible: list[str] = []
    repair: list[str] = []
    if actual_runtime != expected_runtime:
        incompatible.append("RUNTIME_MISMATCH")
    if actual_model != expected_model:
        incompatible.append("MODEL_MISMATCH")
    if estimate > capacity:
        incompatible.append("TASK_EXCEEDS_CONTEXT_CAPACITY")
    if not _tool_exists(command[0]):
        repair.append("ADAPTER_COMMAND_MISSING")
    if not endpoint.is_absolute() or not endpoint.is_file():
        repair.append("ENDPOINT_MISSING")
    if not _workspace_writable(workspace):
        repair.append("WORKSPACE_NOT_WRITABLE")
    if any(not Path(item).is_absolute() or not Path(item).is_file() for item in skills):
        repair.append("REQUIRED_SKILL_MISSING")
    if any(not _tool_exists(item) for item in tools):
        repair.append("REQUIRED_TOOL_MISSING")
    reasons = incompatible or repair
    status = "INCOMPATIBLE" if incompatible else "REPAIR_NEEDED" if repair else "READY"
    return {
        "role": role,
        "status": status,
        "reason_codes": reasons,
        "repair": [f"Restore {role} readiness for {code}." for code in repair],
    }


def evaluate_run_readiness(request: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one closed three-role Run request without inferring missing facts."""

    if not isinstance(request, Mapping):
        raise ValueError("request must be an object")
    _closed(request, REQUEST_FIELDS, "request")
    if request["schema_version"] != "slk.run-readiness-request/v1":
        raise ValueError("run readiness schema mismatch")
    run_id = _nonempty(request["run_id"], "run_id")
    revision = _positive_int(request["plan_revision"], "plan_revision")
    raw_roles = request["roles"]
    if not isinstance(raw_roles, list):
        raise ValueError("roles must be an array")
    roles = [_role_result(item) for item in raw_roles if isinstance(item, Mapping)]
    role_names = [item["role"] for item in roles]
    if len(roles) != len(raw_roles) or sorted(role_names) != sorted(REQUIRED_ROLES):
        raise ValueError("roles must contain exactly one supervisor, worker, and checker")

    raw_options = request["optional_features"]
    if not isinstance(raw_options, list):
        raise ValueError("optional_features must be an array")
    options_by_name: dict[str, dict[str, Any]] = {}
    forbidden_option_declared = False
    for raw in raw_options:
        if not isinstance(raw, Mapping):
            raise ValueError("optional feature must be an object")
        _closed(raw, OPTION_FIELDS, "optional feature")
        name = _nonempty(raw["name"], "optional feature name")
        if name in options_by_name:
            raise ValueError("optional feature names must be unique")
        decision = raw["decision"]
        if decision not in {"ON", "OFF", "UNCONFIRMED"}:
            raise ValueError("optional feature decision is invalid")
        evidence = raw["owner_evidence_ref"]
        if not isinstance(evidence, str):
            raise ValueError("owner_evidence_ref must be a string")
        if name.casefold() in FORBIDDEN_OPTION_NAMES:
            forbidden_option_declared = True
            continue
        options_by_name[name] = {
            "name": name,
            "decision": decision,
            "owner_evidence_ref": evidence,
        }

    reason_codes: list[str] = []
    for role in roles:
        for code in role["reason_codes"]:
            if code not in reason_codes:
                reason_codes.append(code)
    if forbidden_option_declared:
        reason_codes.append("OPTION_FORBIDDEN")
    missing = [name for name in REQUIRED_OPTIONS if name not in options_by_name]
    if missing:
        reason_codes.append("REQUIRED_OPTION_MISSING")
    for option in options_by_name.values():
        if option["decision"] == "UNCONFIRMED" or not option["owner_evidence_ref"].strip():
            if "OPTION_DECISION_REQUIRED" not in reason_codes:
                reason_codes.append("OPTION_DECISION_REQUIRED")
    status = (
        "INCOMPATIBLE"
        if any(item["status"] == "INCOMPATIBLE" for item in roles)
        else "REPAIR_NEEDED"
        if reason_codes
        else "READY"
    )
    canonical = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "slk.run-readiness-result/v1",
        "run_id": run_id,
        "plan_revision": revision,
        "status": status,
        "reason_codes": reason_codes,
        "repairs": [f"Resolve {code}." for code in reason_codes if code != "TASK_EXCEEDS_CONTEXT_CAPACITY"],
        "roles": roles,
        "optional_features": list(options_by_name.values()),
        "request_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }
