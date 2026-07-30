#!/usr/bin/env python3
"""Validate SLK causal defect-repair receipts."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml


def fail(code: str, detail: str) -> NoReturn:
    print(f"FAIL {code}: {detail}", file=sys.stderr)
    raise SystemExit(1)


def require_mapping(value: Any, code: str, detail: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(code, detail)
    return value


def require_text(value: Any, code: str, detail: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(code, detail)
    return value.strip()


def require_ref(value: Any, code: str, detail: str) -> Any:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, dict) and value:
        return value
    fail(code, detail)


def require_evidence(value: Any, code: str, detail: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        fail(code, detail)
    return value


def require_round(value: Any, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        fail("SLK_DEFECT_REPAIR_ROUND_INVALID", f"repair_round must be an integer >= {minimum}")
    return value


def validate_reproduction(value: Any, *, require_steps: bool) -> None:
    reproduction = require_mapping(
        value,
        "SLK_DEFECT_REPRODUCTION_REQUIRED",
        "defect.reproduction must be a mapping",
    )
    status = require_text(
        reproduction.get("status"),
        "SLK_DEFECT_REPRODUCTION_REQUIRED",
        "reproduction.status is required",
    )
    if status not in {"REPRODUCED", "NOT_REPRODUCIBLE"}:
        fail(
            "SLK_DEFECT_REPRODUCTION_REQUIRED",
            "reproduction.status must be REPRODUCED or NOT_REPRODUCIBLE",
        )
    require_evidence(
        reproduction.get("evidence_refs"),
        "SLK_DEFECT_REPRODUCTION_EVIDENCE_REQUIRED",
        "reproduction evidence_refs are required",
    )
    if status == "REPRODUCED" and require_steps:
        require_evidence(
            reproduction.get("steps_or_commands"),
            "SLK_DEFECT_REPRODUCTION_STEPS_REQUIRED",
            "stable reproduction steps_or_commands are required",
        )
        require_text(
            reproduction.get("observed_failure"),
            "SLK_DEFECT_REPRODUCTION_OBSERVATION_REQUIRED",
            "observed_failure is required",
        )


def validate_regression(
    value: Any,
    *,
    failed_candidate_ref: Any,
    current_candidate_ref: Any,
) -> None:
    regression = require_mapping(
        value,
        "SLK_DEFECT_REGRESSION_DECISION_REQUIRED",
        "defect.regression must be a mapping",
    )
    mode = require_text(
        regression.get("mode"),
        "SLK_DEFECT_REGRESSION_DECISION_REQUIRED",
        "regression.mode is required",
    )
    if mode == "REQUIRED":
        fail_before = regression.get("fail_before_ref")
        if not isinstance(fail_before, dict) or not fail_before.get("candidate_ref") or not fail_before.get("evidence_ref"):
            fail(
                "SLK_DEFECT_FAIL_BEFORE_REQUIRED",
                "REQUIRED regression needs candidate-bound fail-before evidence",
            )
        if fail_before["candidate_ref"] != failed_candidate_ref:
            fail(
                "SLK_DEFECT_FAIL_BEFORE_CANDIDATE_MISMATCH",
                "fail-before must bind the defect lineage failed Candidate",
            )
        pass_after = regression.get("pass_after_ref")
        if not isinstance(pass_after, dict) or not pass_after.get("candidate_ref") or not pass_after.get("evidence_ref"):
            fail(
                "SLK_DEFECT_PASS_AFTER_REQUIRED",
                "REQUIRED regression needs candidate-bound pass-after evidence",
            )
        if pass_after["candidate_ref"] != current_candidate_ref:
            fail(
                "SLK_DEFECT_PASS_AFTER_CANDIDATE_MISMATCH",
                "pass-after must bind the current D0 repair Candidate",
            )
        require_evidence(
            regression.get("regression_refs"),
            "SLK_DEFECT_REGRESSION_REQUIRED",
            "risk-scaled regression evidence is required",
        )
    elif mode == "EXEMPT":
        exemption = require_mapping(
            regression.get("exemption"),
            "SLK_DEFECT_EXEMPTION_REASON_REQUIRED",
            "EXEMPT regression needs an exemption mapping",
        )
        require_text(
            exemption.get("reason"),
            "SLK_DEFECT_EXEMPTION_REASON_REQUIRED",
            "EXEMPT regression needs an exemption_reason",
        )
        require_evidence(
            exemption.get("alternative_evidence_refs"),
            "SLK_DEFECT_EXEMPTION_EVIDENCE_REQUIRED",
            "EXEMPT regression needs alternative evidence",
        )
    else:
        fail(
            "SLK_DEFECT_REGRESSION_DECISION_REQUIRED",
            "regression.mode must be REQUIRED or EXEMPT",
        )


def validate_d0(receipt: dict[str, Any], defect: dict[str, Any]) -> None:
    if defect.get("status") != "REPAIR_CANDIDATE":
        fail("SLK_DEFECT_D0_STATUS_INVALID", "D0 defect.status must be REPAIR_CANDIDATE")
    require_text(
        defect.get("defect_lineage_id"),
        "SLK_DEFECT_LINEAGE_REQUIRED",
        "defect_lineage_id is required",
    )
    require_round(defect.get("repair_round"), minimum=1)
    require_text(
        defect.get("source_failure_receipt"),
        "SLK_DEFECT_SOURCE_FAILURE_REQUIRED",
        "source_failure_receipt is required",
    )
    current_candidate_ref = require_ref(
        receipt.get("candidate_ref"),
        "SLK_DEFECT_CURRENT_CANDIDATE_REQUIRED",
        "D0 candidate_ref is required",
    )
    failed_candidate_ref = require_ref(
        defect.get("failed_candidate_ref"),
        "SLK_DEFECT_FAILED_CANDIDATE_REQUIRED",
        "D0 defect lineage failed_candidate_ref is required",
    )
    validate_reproduction(defect.get("reproduction"), require_steps=False)

    root_cause = require_mapping(
        defect.get("root_cause"),
        "SLK_DEFECT_ROOT_CAUSE_REQUIRED",
        "root_cause must be a mapping",
    )
    hypothesis = root_cause.get("hypothesis")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        fail(
            "SLK_DEFECT_SINGLE_HYPOTHESIS",
            "exactly one scalar active root-cause hypothesis is required",
        )
    product_change_made = defect.get("product_change_made")
    if not isinstance(product_change_made, bool):
        fail(
            "SLK_DEFECT_PRODUCT_CHANGE_FLAG_REQUIRED",
            "product_change_made must be boolean",
        )
    if product_change_made and root_cause.get("status") != "CONFIRMED":
        fail(
            "SLK_DEFECT_ROOT_CAUSE_REQUIRED",
            "root cause must be CONFIRMED before a product change",
        )
    if root_cause.get("status") == "CONFIRMED":
        require_evidence(
            root_cause.get("evidence_refs"),
            "SLK_DEFECT_ROOT_CAUSE_EVIDENCE_REQUIRED",
            "confirmed root cause needs evidence",
        )

    experiment = require_mapping(
        defect.get("minimal_experiment"),
        "SLK_DEFECT_MINIMAL_EXPERIMENT_REQUIRED",
        "one minimal_experiment mapping is required",
    )
    for key in ("variable", "expected", "observed"):
        require_text(
            experiment.get(key),
            "SLK_DEFECT_MINIMAL_EXPERIMENT_REQUIRED",
            f"minimal_experiment.{key} is required",
        )
    require_evidence(
        experiment.get("evidence_refs"),
        "SLK_DEFECT_MINIMAL_EXPERIMENT_REQUIRED",
        "minimal_experiment evidence is required",
    )
    if product_change_made:
        require_evidence(
            defect.get("change_scope"),
            "SLK_DEFECT_CHANGE_SCOPE_REQUIRED",
            "change_scope is required when product_change_made is true",
        )
    validate_regression(
        defect.get("regression"),
        failed_candidate_ref=failed_candidate_ref,
        current_candidate_ref=current_candidate_ref,
    )


def validate_d1(receipt: dict[str, Any], defect: dict[str, Any]) -> None:
    require_text(
        defect.get("defect_lineage_id"),
        "SLK_DEFECT_LINEAGE_REQUIRED",
        "defect_lineage_id is required",
    )
    repair_round = require_round(defect.get("repair_round"))
    candidate_kind = defect.get("candidate_kind")
    if candidate_kind not in {"ORIGINAL", "REPAIR"}:
        fail(
            "SLK_DEFECT_CANDIDATE_KIND_INVALID",
            "candidate_kind must be ORIGINAL or REPAIR",
        )
    if candidate_kind == "REPAIR" and repair_round < 1:
        fail(
            "SLK_DEFECT_REPAIR_ROUND_INVALID",
            "a repair Candidate must use repair_round >= 1",
        )
    validate_reproduction(defect.get("reproduction"), require_steps=True)

    verdict = receipt.get("verdict")
    if verdict == "FAIL":
        if defect.get("status") != "FAILURE_BOUND":
            fail("SLK_DEFECT_D1_STATUS_INVALID", "failed D1 defect.status must be FAILURE_BOUND")
        current_candidate_ref = require_ref(
            receipt.get("candidate_ref"),
            "SLK_DEFECT_CURRENT_CANDIDATE_REQUIRED",
            "D1 candidate_ref is required",
        )
        failed_candidate_ref = require_ref(
            defect.get("failed_candidate_ref"),
            "SLK_DEFECT_FAILED_CANDIDATE_REQUIRED",
            "failed_candidate_ref is required",
        )
        if failed_candidate_ref != current_candidate_ref:
            fail(
                "SLK_DEFECT_FAILED_CANDIDATE_MISMATCH",
                "D1 failed_candidate_ref must equal the immutable Candidate under validation",
            )
        require_text(
            defect.get("failure_fingerprint"),
            "SLK_DEFECT_FAILURE_FINGERPRINT_REQUIRED",
            "failure_fingerprint is required",
        )
        rejected = defect.get("rejected_fix_candidate_count")
        if isinstance(rejected, bool) or not isinstance(rejected, int) or rejected < 0:
            fail(
                "SLK_DEFECT_REJECTED_COUNT_INVALID",
                "rejected_fix_candidate_count must be a non-negative integer",
            )
        if candidate_kind == "ORIGINAL" and (repair_round != 0 or rejected != 0):
            fail(
                "SLK_DEFECT_LINEAGE_COUNT_INVALID",
                "the original failed candidate starts repair_round and rejected count at zero",
            )
        if candidate_kind == "REPAIR" and rejected != repair_round:
            fail(
                "SLK_DEFECT_LINEAGE_COUNT_INVALID",
                "a Checker-rejected immutable repair Candidate increments the repair round once",
            )
        route = defect.get("route")
        ordinary_allowed = defect.get("ordinary_rework_allowed")
        if rejected >= 3:
            review_routes = {
                "ARCHITECTURE_REVIEW_REQUIRED",
                "METHOD_BOUNDARY_EXCEEDED",
                "CONTRACT_REVISION_REQUIRED",
            }
            if route not in review_routes or ordinary_allowed is not False:
                fail(
                    "SLK_DEFECT_ARCHITECTURE_GATE",
                    "the third rejected repair Candidate forbids a fourth ordinary rework",
                )
            require_ref(
                defect.get("route_ref"),
                "SLK_DEFECT_ROUTE_REF_REQUIRED",
                "the third-rejection route must bind a traceable Control reference",
            )
        elif route != "CELL_REWORK" or ordinary_allowed is not True:
            fail(
                "SLK_DEFECT_REWORK_ROUTE_INVALID",
                "before the third rejection the failed D1 route must be CELL_REWORK",
            )
    elif verdict == "PASS":
        if defect.get("status") != "REPAIR_ACCEPTED" or candidate_kind != "REPAIR":
            fail(
                "SLK_DEFECT_D1_STATUS_INVALID",
                "passing repair D1 must bind REPAIR_ACCEPTED to a repair Candidate",
            )
        if defect.get("route") != "NEXT":
            fail("SLK_DEFECT_PASS_ROUTE_INVALID", "passing D1 repair must route NEXT")
        require_text(
            defect.get("independent_reproduction_ref"),
            "SLK_DEFECT_INDEPENDENT_REPRODUCTION_REQUIRED",
            "Checker independent reproduction evidence is required",
        )
        review = require_mapping(
            defect.get("regression_review"),
            "SLK_DEFECT_REGRESSION_REVIEW_REQUIRED",
            "regression_review must be a mapping",
        )
        mode = review.get("mode")
        if mode not in {"REQUIRED", "EXEMPT"}:
            fail(
                "SLK_DEFECT_REGRESSION_REVIEW_REQUIRED",
                "regression_review.mode must be REQUIRED or EXEMPT",
            )
        if review.get("decision") != "APPROVED":
            code = (
                "SLK_DEFECT_EXEMPTION_REVIEW_REQUIRED"
                if mode == "EXEMPT"
                else "SLK_DEFECT_REGRESSION_REVIEW_REQUIRED"
            )
            fail(code, "Checker must approve regression evidence or exemption")
        require_evidence(
            review.get("evidence_refs"),
            "SLK_DEFECT_REGRESSION_REVIEW_REQUIRED",
            "Checker regression review evidence is required",
        )
    else:
        fail("SLK_DEFECT_D1_VERDICT_INVALID", "D1 verdict must be PASS or FAIL")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_defect_repair.py <D0-or-D1-receipt.yaml>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    try:
        receipt = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        fail("SLK_DEFECT_RECEIPT_UNREADABLE", str(exc))
    receipt = require_mapping(
        receipt,
        "SLK_DEFECT_RECEIPT_INVALID",
        "receipt must be a YAML mapping",
    )
    defect = require_mapping(
        receipt.get("defect_repair"),
        "SLK_DEFECT_BLOCK_REQUIRED",
        "receipt.defect_repair must be a mapping",
    )
    receipt_type = receipt.get("receipt_type")
    if receipt_type == "D0":
        validate_d0(receipt, defect)
    elif receipt_type == "D1":
        validate_d1(receipt, defect)
    else:
        fail("SLK_DEFECT_RECEIPT_TYPE_INVALID", "receipt_type must be D0 or D1")
    print("PASS: defect repair receipt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
