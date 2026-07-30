from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_defect_repair.py"


def d1_failure() -> dict:
    return {
        "receipt_id": "D1-001",
        "receipt_type": "D1",
        "verdict": "FAIL",
        "candidate_ref": {"sha256": "a" * 64},
        "defect_repair": {
            "status": "FAILURE_BOUND",
            "defect_lineage_id": "DL-001",
            "repair_round": 0,
            "candidate_kind": "ORIGINAL",
            "failed_candidate_ref": {"sha256": "a" * 64},
            "failure_fingerprint": "settings-reset-after-restart",
            "reproduction": {
                "status": "REPRODUCED",
                "steps_or_commands": ["pytest tests/test_settings.py::test_persists"],
                "observed_failure": "saved value reset to default",
                "evidence_refs": ["evidence/reproduction.txt"],
            },
            "rejected_fix_candidate_count": 0,
            "route": "CELL_REWORK",
            "ordinary_rework_allowed": True,
            "route_ref": "",
            "independent_reproduction_ref": "",
            "regression_review": {
                "mode": "PENDING",
                "decision": "PENDING",
                "evidence_refs": [],
            },
        },
    }


def d0_repair(*, regression_mode: str = "REQUIRED") -> dict:
    value = {
        "receipt_id": "D0-REPAIR-001",
        "receipt_type": "D0",
        "result": "READY_FOR_D1",
        "candidate_ref": {"sha256": "b" * 64},
        "defect_repair": {
            "status": "REPAIR_CANDIDATE",
            "defect_lineage_id": "DL-001",
            "repair_round": 1,
            "source_failure_receipt": "D1-001",
            "failed_candidate_ref": {"sha256": "a" * 64},
            "reproduction": {
                "status": "REPRODUCED",
                "evidence_refs": ["evidence/reproduction.txt"],
            },
            "root_cause": {
                "status": "CONFIRMED",
                "hypothesis": "the persistence adapter writes to a transient namespace",
                "evidence_refs": ["evidence/root-cause.txt"],
            },
            "minimal_experiment": {
                "variable": "storage namespace",
                "expected": "persistent namespace survives restart",
                "observed": "value survives restart only in persistent namespace",
                "evidence_refs": ["evidence/experiment.txt"],
            },
            "product_change_made": True,
            "change_scope": ["settings/persistence_adapter.py"],
            "regression": {
                "mode": regression_mode,
                "fail_before_ref": {
                    "candidate_ref": {"sha256": "a" * 64},
                    "evidence_ref": "evidence/fail-before.txt",
                },
                "pass_after_ref": {
                    "candidate_ref": {"sha256": "b" * 64},
                    "evidence_ref": "evidence/pass-after.txt",
                },
                "regression_refs": ["evidence/regression.txt"],
                "exemption": {"reason": "", "alternative_evidence_refs": []},
            },
        },
    }
    if regression_mode == "EXEMPT":
        regression = value["defect_repair"]["regression"]
        regression["fail_before_ref"] = {}
        regression["pass_after_ref"] = {}
        regression["regression_refs"] = []
        regression["exemption"] = {
            "reason": "failure depends on external hardware timing",
            "alternative_evidence_refs": ["evidence/hardware-probe.txt"],
        }
    return value


def d1_acceptance_for_exemption() -> dict:
    value = d1_failure()
    value["receipt_id"] = "D1-002"
    value["verdict"] = "PASS"
    value["candidate_ref"] = {"sha256": "b" * 64}
    repair = value["defect_repair"]
    repair.update(
        {
            "status": "REPAIR_ACCEPTED",
            "repair_round": 1,
            "candidate_kind": "REPAIR",
            "failed_candidate_ref": {},
            "failure_fingerprint": "settings-reset-after-restart",
            "rejected_fix_candidate_count": 0,
            "route": "NEXT",
            "ordinary_rework_allowed": False,
            "independent_reproduction_ref": "evidence/checker-hardware-probe.txt",
            "regression_review": {
                "mode": "EXEMPT",
                "decision": "APPROVED",
                "evidence_refs": ["evidence/checker-hardware-probe.txt"],
            },
        }
    )
    return value


def run_packet(tmp_path: Path, packet: dict, *, optimized: bool = False) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "receipt.yaml"
    path.write_text(yaml.safe_dump(packet, sort_keys=False), encoding="utf-8")
    args = [sys.executable]
    if optimized:
        args.append("-O")
    args.extend([str(SCRIPT), str(path)])
    return subprocess.run(args, text=True, capture_output=True, encoding="utf-8", check=False)


def test_original_d1_failure_can_open_one_lineage(tmp_path: Path) -> None:
    result = run_packet(tmp_path, d1_failure())
    assert result.returncode == 0, result.stderr
    assert "PASS: defect repair receipt" in result.stdout


def test_d1_failure_rejects_failed_candidate_mismatch(tmp_path: Path) -> None:
    packet = d1_failure()
    packet["defect_repair"]["failed_candidate_ref"] = {"sha256": "c" * 64}
    result = run_packet(tmp_path, packet, optimized=True)
    assert result.returncode == 1
    assert "SLK_DEFECT_FAILED_CANDIDATE_MISMATCH" in result.stderr


def test_third_rejected_fix_requires_architecture_review(tmp_path: Path) -> None:
    packet = d1_failure()
    repair = packet["defect_repair"]
    repair.update(
        {
            "repair_round": 3,
            "candidate_kind": "REPAIR",
            "rejected_fix_candidate_count": 3,
            "route": "ARCHITECTURE_REVIEW_REQUIRED",
            "route_ref": "control/architecture-review-001",
            "ordinary_rework_allowed": False,
        }
    )
    result = run_packet(tmp_path, packet)
    assert result.returncode == 0, result.stderr


def test_third_rejected_fix_can_exit_method_boundary(tmp_path: Path) -> None:
    packet = d1_failure()
    repair = packet["defect_repair"]
    repair.update(
        {
            "repair_round": 3,
            "candidate_kind": "REPAIR",
            "rejected_fix_candidate_count": 3,
            "route": "METHOD_BOUNDARY_EXCEEDED",
            "route_ref": "control/method-boundary-001",
            "ordinary_rework_allowed": False,
        }
    )
    result = run_packet(tmp_path, packet)
    assert result.returncode == 0, result.stderr


def test_third_rejected_fix_can_require_versioned_contract_revision(tmp_path: Path) -> None:
    packet = d1_failure()
    repair = packet["defect_repair"]
    repair.update(
        {
            "repair_round": 3,
            "candidate_kind": "REPAIR",
            "rejected_fix_candidate_count": 3,
            "route": "CONTRACT_REVISION_REQUIRED",
            "route_ref": "control/contract-revision-001",
            "ordinary_rework_allowed": False,
        }
    )
    result = run_packet(tmp_path, packet)
    assert result.returncode == 0, result.stderr


def test_third_rejection_route_requires_traceable_reference(tmp_path: Path) -> None:
    packet = d1_failure()
    repair = packet["defect_repair"]
    repair.update(
        {
            "repair_round": 3,
            "candidate_kind": "REPAIR",
            "rejected_fix_candidate_count": 3,
            "route": "CONTRACT_REVISION_REQUIRED",
            "ordinary_rework_allowed": False,
        }
    )
    result = run_packet(tmp_path, packet)
    assert result.returncode == 1
    assert "SLK_DEFECT_ROUTE_REF_REQUIRED" in result.stderr


def test_fourth_ordinary_rework_is_blocked_even_under_python_optimized(tmp_path: Path) -> None:
    packet = d1_failure()
    repair = packet["defect_repair"]
    repair.update(
        {
            "repair_round": 3,
            "candidate_kind": "REPAIR",
            "rejected_fix_candidate_count": 3,
            "route": "CELL_REWORK",
            "ordinary_rework_allowed": True,
        }
    )
    result = run_packet(tmp_path, packet, optimized=True)
    assert result.returncode == 1
    assert "SLK_DEFECT_ARCHITECTURE_GATE" in result.stderr


def test_root_cause_and_single_experiment_allow_minimal_repair(tmp_path: Path) -> None:
    result = run_packet(tmp_path, d0_repair())
    assert result.returncode == 0, result.stderr


def test_product_change_without_confirmed_root_cause_is_rejected(tmp_path: Path) -> None:
    packet = d0_repair()
    packet["defect_repair"]["root_cause"]["status"] = "PENDING"
    result = run_packet(tmp_path, packet)
    assert result.returncode == 1
    assert "SLK_DEFECT_ROOT_CAUSE_REQUIRED" in result.stderr


def test_hypothesis_must_be_one_scalar_statement(tmp_path: Path) -> None:
    packet = d0_repair()
    packet["defect_repair"]["root_cause"]["hypothesis"] = ["namespace", "cache"]
    result = run_packet(tmp_path, packet)
    assert result.returncode == 1
    assert "SLK_DEFECT_SINGLE_HYPOTHESIS" in result.stderr


def test_required_regression_needs_fail_before_and_pass_after(tmp_path: Path) -> None:
    packet = d0_repair()
    packet["defect_repair"]["regression"]["fail_before_ref"] = {}
    result = run_packet(tmp_path, packet)
    assert result.returncode == 1
    assert "SLK_DEFECT_FAIL_BEFORE_REQUIRED" in result.stderr


def test_d0_regression_candidate_refs_bind_lineage_failure_and_current_repair(
    tmp_path: Path,
) -> None:
    fail_before_mismatch = d0_repair()
    fail_before_mismatch["defect_repair"]["regression"]["fail_before_ref"][
        "candidate_ref"
    ] = {"sha256": "c" * 64}
    result = run_packet(tmp_path, fail_before_mismatch, optimized=True)
    assert result.returncode == 1
    assert "SLK_DEFECT_FAIL_BEFORE_CANDIDATE_MISMATCH" in result.stderr

    pass_after_mismatch = d0_repair()
    pass_after_mismatch["defect_repair"]["regression"]["pass_after_ref"][
        "candidate_ref"
    ] = {"sha256": "c" * 64}
    result = run_packet(tmp_path, pass_after_mismatch, optimized=True)
    assert result.returncode == 1
    assert "SLK_DEFECT_PASS_AFTER_CANDIDATE_MISMATCH" in result.stderr


def test_exemption_needs_reason_and_alternative_evidence(tmp_path: Path) -> None:
    packet = d0_repair(regression_mode="EXEMPT")
    packet["defect_repair"]["regression"]["exemption"]["alternative_evidence_refs"] = []
    result = run_packet(tmp_path, packet)
    assert result.returncode == 1
    assert "SLK_DEFECT_EXEMPTION_EVIDENCE_REQUIRED" in result.stderr


def test_evidenced_non_reproduction_can_use_checker_reviewed_exemption(tmp_path: Path) -> None:
    packet = d0_repair(regression_mode="EXEMPT")
    packet["defect_repair"]["reproduction"] = {
        "status": "NOT_REPRODUCIBLE",
        "evidence_refs": ["evidence/non-reproduction-attempts.txt"],
    }
    result = run_packet(tmp_path, packet)
    assert result.returncode == 0, result.stderr


def test_checker_can_approve_proportional_exemption(tmp_path: Path) -> None:
    result = run_packet(tmp_path, d1_acceptance_for_exemption())
    assert result.returncode == 0, result.stderr


def test_checker_pass_cannot_leave_exemption_unreviewed(tmp_path: Path) -> None:
    packet = d1_acceptance_for_exemption()
    packet["defect_repair"]["regression_review"]["decision"] = "PENDING"
    result = run_packet(tmp_path, packet)
    assert result.returncode == 1
    assert "SLK_DEFECT_EXEMPTION_REVIEW_REQUIRED" in result.stderr


def test_d1_passing_repair_cannot_use_original_round_zero(tmp_path: Path) -> None:
    packet = d1_acceptance_for_exemption()
    packet["defect_repair"]["repair_round"] = 0
    result = run_packet(tmp_path, packet, optimized=True)
    assert result.returncode == 1
    assert "SLK_DEFECT_REPAIR_ROUND_INVALID" in result.stderr
