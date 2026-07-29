from __future__ import annotations

import subprocess
import sys
import hashlib
import copy
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_serial_plan.py"
VALID_PLAN = {
    "run_id": "RUN-TEST",
    "serial_baseline": {
        "baseline_id": "SB-001",
        "version": 1,
        "sha256": "a" * 64,
    },
    "current_go_id": "GO-001",
    "active_go_id": None,
    "gos": [
        {
            "go_id": "GO-001",
            "ordinal": 1,
            "go_contract_ref": "contracts/go-001.yaml",
            "go_contract_version": 1,
            "go_contract_hash": "b" * 64,
            "lifecycle_state": "READY",
            "required": True,
            "d2_receipt": None,
            "formal_resolution": None,
        }
    ],
}

GO_CONTRACT = {
    "go_id": "GO-001",
    "version": 1,
    "intent": "Persist settings",
    "scope": ["settings"],
    "claim": "Settings persist",
    "acceptance": ["Reload preserves value"],
    "counter_evidence": ["Value resets"],
    "evidence_required": ["integration test"],
    "readiness_conditions": ["database available"],
    "security_impact": [],
}


def run_plan(
    tmp_path: Path,
    plan: object,
    *,
    optimized: bool = False,
    write_contracts: bool = True,
    preserve_hashes: bool = False,
    contract_override: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    plan = copy.deepcopy(plan)
    if write_contracts and isinstance(plan, dict):
        for go in plan.get("gos", []):
            if not isinstance(go, dict) or not isinstance(go.get("go_contract_ref"), str):
                continue
            contract = copy.deepcopy(contract_override or GO_CONTRACT)
            contract["go_id"] = go.get("go_id", contract["go_id"])
            target = tmp_path / go["go_contract_ref"]
            target.parent.mkdir(parents=True, exist_ok=True)
            content = yaml.safe_dump(contract, sort_keys=False)
            target.write_text(content, encoding="utf-8")
            if "go_contract_hash" in go and not preserve_hashes:
                go["go_contract_hash"] = hashlib.sha256(target.read_bytes()).hexdigest()
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(plan, sort_keys=False), encoding="utf-8")
    args = [sys.executable]
    if optimized:
        args.append("-O")
    args.extend([str(SCRIPT), str(path)])
    return subprocess.run(args, text=True, capture_output=True, encoding="utf-8", check=False)


def test_valid_serial_plan_passes(tmp_path: Path) -> None:
    result = run_plan(tmp_path, VALID_PLAN)
    assert result.returncode == 0, result.stderr
    assert "PASS: serial plan" in result.stdout


def test_empty_plan_fails_closed(tmp_path: Path) -> None:
    plan = {**VALID_PLAN, "gos": [], "current_go_id": None}
    result = run_plan(tmp_path, plan)
    assert result.returncode == 1
    assert "SLK_PLAN_EMPTY" in result.stderr


def test_missing_contract_binding_is_rejected(tmp_path: Path) -> None:
    plan = yaml.safe_load(yaml.safe_dump(VALID_PLAN))
    del plan["gos"][0]["go_contract_hash"]
    result = run_plan(tmp_path, plan)
    assert result.returncode == 1
    assert "SLK_PLAN_GO_FIELD_MISSING" in result.stderr


def test_bad_ordinal_fails_even_with_python_optimized(tmp_path: Path) -> None:
    plan = yaml.safe_load(yaml.safe_dump(VALID_PLAN))
    plan["gos"][0]["ordinal"] = 2
    result = run_plan(tmp_path, plan, optimized=True)
    assert result.returncode == 1
    assert "SLK_PLAN_ORDINAL_SEQUENCE" in result.stderr


def test_active_pointer_must_match_current_and_implementing_state(tmp_path: Path) -> None:
    plan = yaml.safe_load(yaml.safe_dump(VALID_PLAN))
    plan["active_go_id"] = "GO-001"
    result = run_plan(tmp_path, plan)
    assert result.returncode == 1
    assert "SLK_PLAN_ACTIVE_STATE" in result.stderr


def test_successor_requires_predecessor_d2_pass(tmp_path: Path) -> None:
    plan = yaml.safe_load(yaml.safe_dump(VALID_PLAN))
    plan["gos"].append(
        {
            **plan["gos"][0],
            "go_id": "GO-002",
            "ordinal": 2,
            "go_contract_ref": "contracts/go-002.yaml",
            "go_contract_hash": "c" * 64,
        }
    )
    plan["current_go_id"] = "GO-002"
    result = run_plan(tmp_path, plan)
    assert result.returncode == 1
    assert "SLK_PLAN_PREDECESSOR_D2_REQUIRED" in result.stderr


def test_required_go_cannot_use_formal_resolution(tmp_path: Path) -> None:
    plan = yaml.safe_load(yaml.safe_dump(VALID_PLAN))
    plan["gos"][0]["formal_resolution"] = {
        "result": "REMOVED_FROM_SCOPE",
        "baseline_amendment_ref": "BA-001",
    }
    result = run_plan(tmp_path, plan)
    assert result.returncode == 1
    assert "SLK_PLAN_REQUIRED_GO_RESOLUTION" in result.stderr


def test_missing_go_contract_file_is_rejected(tmp_path: Path) -> None:
    result = run_plan(tmp_path, VALID_PLAN, write_contracts=False)
    assert result.returncode == 1
    assert "SLK_PLAN_GO_CONTRACT_MISSING" in result.stderr


def test_go_contract_hash_must_match_file(tmp_path: Path) -> None:
    result = run_plan(tmp_path, VALID_PLAN, preserve_hashes=True)
    assert result.returncode == 1
    assert "SLK_PLAN_GO_CONTRACT_HASH_MISMATCH" in result.stderr


def test_go_contract_required_fields_are_enforced(tmp_path: Path) -> None:
    incomplete = {**GO_CONTRACT}
    del incomplete["acceptance"]
    result = run_plan(tmp_path, VALID_PLAN, contract_override=incomplete)
    assert result.returncode == 1
    assert "SLK_PLAN_GO_CONTRACT_FIELD_MISSING" in result.stderr
