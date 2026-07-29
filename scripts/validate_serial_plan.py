from __future__ import annotations

import re
import sys
import hashlib
from pathlib import Path
from typing import Any

import yaml


HASH = re.compile(r"^[0-9a-fA-F]{64}$")
GO_STATES = {
    "FROZEN",
    "READY",
    "IMPLEMENTING",
    "D1_PENDING",
    "D2_PENDING",
    "VERIFIED",
    "BLOCKED",
    "CANCELLED",
    "SUPERSEDED",
}
RESOLUTIONS = {"CANCELLED_BY_AUTHORITY", "REMOVED_FROM_SCOPE", "SUPERSEDED"}
GO_FIELDS = {
    "go_id",
    "ordinal",
    "go_contract_ref",
    "go_contract_version",
    "go_contract_hash",
    "lifecycle_state",
    "required",
    "d2_receipt",
    "formal_resolution",
}
GO_CONTRACT_FIELDS = {
    "go_id",
    "version",
    "intent",
    "scope",
    "claim",
    "acceptance",
    "counter_evidence",
    "evidence_required",
    "readiness_conditions",
    "security_impact",
}


class PlanError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def fail(code: str, detail: str) -> None:
    raise PlanError(code, detail)


def validate_serial_plan(plan: Any, base_dir: Path) -> None:
    if not isinstance(plan, dict):
        fail("SLK_PLAN_ROOT_TYPE", "plan root must be a mapping")
    if not isinstance(plan.get("run_id"), str) or not plan["run_id"].strip():
        fail("SLK_PLAN_RUN_ID", "run_id must be a non-empty string")

    baseline = plan.get("serial_baseline")
    if not isinstance(baseline, dict):
        fail("SLK_PLAN_BASELINE", "serial_baseline must be a mapping")
    if not isinstance(baseline.get("baseline_id"), str) or not baseline["baseline_id"]:
        fail("SLK_PLAN_BASELINE", "baseline_id is required")
    if not isinstance(baseline.get("version"), int) or baseline["version"] < 1:
        fail("SLK_PLAN_BASELINE", "baseline version must be a positive integer")
    if not isinstance(baseline.get("sha256"), str) or not HASH.fullmatch(baseline["sha256"]):
        fail("SLK_PLAN_BASELINE_HASH", "baseline sha256 must contain 64 hex characters")

    gos = plan.get("gos")
    if not isinstance(gos, list):
        fail("SLK_PLAN_GOS_TYPE", "gos must be a list")
    if not gos:
        fail("SLK_PLAN_EMPTY", "a Serial Plan requires at least one GO")

    ids: list[str] = []
    ordinals: list[int] = []
    for index, go in enumerate(gos):
        if not isinstance(go, dict):
            fail("SLK_PLAN_GO_TYPE", f"GO at index {index} must be a mapping")
        missing = sorted(GO_FIELDS - set(go))
        if missing:
            fail("SLK_PLAN_GO_FIELD_MISSING", f"GO at index {index} is missing {missing}")
        if not isinstance(go["go_id"], str) or not go["go_id"].strip():
            fail("SLK_PLAN_GO_ID", f"GO at index {index} has an invalid go_id")
        if not isinstance(go["ordinal"], int):
            fail("SLK_PLAN_ORDINAL_TYPE", f"{go['go_id']} ordinal must be an integer")
        if not isinstance(go["go_contract_ref"], str) or not go["go_contract_ref"].strip():
            fail("SLK_PLAN_GO_CONTRACT_REF", f"{go['go_id']} requires go_contract_ref")
        if not isinstance(go["go_contract_version"], int) or go["go_contract_version"] < 1:
            fail("SLK_PLAN_GO_CONTRACT_VERSION", f"{go['go_id']} requires a positive contract version")
        if not isinstance(go["go_contract_hash"], str) or not HASH.fullmatch(go["go_contract_hash"]):
            fail("SLK_PLAN_GO_CONTRACT_HASH", f"{go['go_id']} requires a 64-character SHA-256")
        contract_path = (base_dir / go["go_contract_ref"]).resolve()
        try:
            contract_path.relative_to(base_dir.resolve())
        except ValueError:
            fail("SLK_PLAN_GO_CONTRACT_PATH", f"{go['go_id']} contract must stay inside the plan directory")
        if not contract_path.is_file():
            fail("SLK_PLAN_GO_CONTRACT_MISSING", f"{go['go_id']} contract does not exist: {go['go_contract_ref']}")
        actual_hash = hashlib.sha256(contract_path.read_bytes()).hexdigest()
        if actual_hash != go["go_contract_hash"].lower():
            fail("SLK_PLAN_GO_CONTRACT_HASH_MISMATCH", f"{go['go_id']} contract hash does not match")
        try:
            go_contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            fail("SLK_PLAN_GO_CONTRACT_READ", f"{go['go_id']} contract cannot be read: {exc}")
        if not isinstance(go_contract, dict):
            fail("SLK_PLAN_GO_CONTRACT_TYPE", f"{go['go_id']} contract must be a mapping")
        contract_missing = sorted(GO_CONTRACT_FIELDS - set(go_contract))
        if contract_missing:
            fail("SLK_PLAN_GO_CONTRACT_FIELD_MISSING", f"{go['go_id']} contract is missing {contract_missing}")
        if go_contract["go_id"] != go["go_id"] or go_contract["version"] != go["go_contract_version"]:
            fail("SLK_PLAN_GO_CONTRACT_IDENTITY", f"{go['go_id']} contract identity/version mismatch")
        if go["lifecycle_state"] not in GO_STATES:
            fail("SLK_PLAN_GO_STATE", f"{go['go_id']} has an invalid lifecycle_state")
        if not isinstance(go["required"], bool):
            fail("SLK_PLAN_REQUIRED_TYPE", f"{go['go_id']} required must be boolean")
        resolution = go["formal_resolution"]
        if go["required"] and resolution is not None:
            fail("SLK_PLAN_REQUIRED_GO_RESOLUTION", f"{go['go_id']} remains Required and cannot use resolution")
        if resolution is not None:
            if not isinstance(resolution, dict) or resolution.get("result") not in RESOLUTIONS:
                fail("SLK_PLAN_RESOLUTION_RESULT", f"{go['go_id']} has an invalid resolution")
            if not isinstance(resolution.get("baseline_amendment_ref"), str) or not resolution["baseline_amendment_ref"]:
                fail("SLK_PLAN_RESOLUTION_AMENDMENT", f"{go['go_id']} resolution requires baseline_amendment_ref")
        ids.append(go["go_id"])
        ordinals.append(go["ordinal"])

    if len(ids) != len(set(ids)):
        fail("SLK_PLAN_DUPLICATE_GO_ID", "go_id values must be unique")
    if ordinals != list(range(1, len(gos) + 1)):
        fail("SLK_PLAN_ORDINAL_SEQUENCE", "ordinals must be exactly 1..N in list order")

    current = plan.get("current_go_id")
    active = plan.get("active_go_id")
    if current is not None and current not in ids:
        fail("SLK_PLAN_CURRENT_POINTER", "current_go_id must identify a GO or be null")
    if active is not None and active not in ids:
        fail("SLK_PLAN_ACTIVE_POINTER", "active_go_id must identify a GO or be null")
    if active is not None and active != current:
        fail("SLK_PLAN_ACTIVE_CURRENT_MISMATCH", "active_go_id must equal current_go_id")
    if active is not None:
        active_go = gos[ids.index(active)]
        if active_go["lifecycle_state"] != "IMPLEMENTING":
            fail("SLK_PLAN_ACTIVE_STATE", "the Active GO must be IMPLEMENTING")

    if current is not None:
        current_index = ids.index(current)
        for predecessor in gos[:current_index]:
            if not predecessor["required"]:
                continue
            receipt = predecessor["d2_receipt"]
            if predecessor["lifecycle_state"] != "VERIFIED" or not isinstance(receipt, dict) or receipt.get("verdict") != "PASS":
                fail(
                    "SLK_PLAN_PREDECESSOR_D2_REQUIRED",
                    f"{predecessor['go_id']} requires VERIFIED lifecycle and D2 PASS before {current}",
                )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("FAIL SLK_PLAN_USAGE: expected one serial-plan path", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        plan = yaml.safe_load(path.read_text(encoding="utf-8"))
        validate_serial_plan(plan, path.parent)
    except PlanError as exc:
        print(f"FAIL {exc.code}: {exc.detail}", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        print(f"FAIL SLK_PLAN_READ: {exc}", file=sys.stderr)
        return 1
    print("PASS: serial plan")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
