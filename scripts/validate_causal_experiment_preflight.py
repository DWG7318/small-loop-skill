#!/usr/bin/env python3
"""Validate the zero-credit SLK causal experiment preflight receipt."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


def fail(code: str, detail: str) -> None:
    print(f"FAIL {code}: {detail}", file=sys.stderr)
    raise SystemExit(1)


def mapping(value: Any, code: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail(code, "expected object")
    return value


def require(value: Any, code: str, name: str) -> Any:
    if value in (None, "", [], {}):
        fail(code, name)
    return value


def all_pass(rows: Any, code: str, name: str) -> None:
    if not isinstance(rows, list) or not rows:
        fail(code, name)
    for row in rows:
        if not isinstance(row, dict) or row.get("pass") is not True:
            fail(code, name)


def validate(receipt: dict[str, Any]) -> None:
    if receipt.get("schema_version") != "slk.causal-experiment-preflight.v1":
        fail("SLK_PREFLIGHT_SCHEMA", repr(receipt.get("schema_version")))
    if receipt.get("status") != "PASS_READY_FOR_CREDITED_EXPERIMENT":
        fail("SLK_PREFLIGHT_STATUS", repr(receipt.get("status")))
    require(receipt.get("candidate_ref"), "SLK_PREFLIGHT_CANDIDATE", "candidate_ref")
    contract = mapping(receipt.get("input_contract"), "SLK_PREFLIGHT_CONTRACT")
    pattern_text = require(contract.get("visible_id_pattern"), "SLK_PREFLIGHT_PATTERN", "visible_id_pattern")
    try:
        pattern = re.compile(pattern_text)
    except re.error as exc:
        fail("SLK_PREFLIGHT_PATTERN", str(exc))
    ids = contract.get("visible_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(value, str) or pattern.fullmatch(value) is None for value in ids):
        fail("SLK_PREFLIGHT_IDENTIFIER", "visible_ids must match visible_id_pattern")
    all_pass(contract.get("request_shape_checks"), "SLK_PREFLIGHT_REQUEST_SHAPE", "request_shape_checks")
    all_pass(contract.get("authority_seed_checks"), "SLK_PREFLIGHT_AUTHORITY_SEED", "authority_seed_checks")
    topology = mapping(contract.get("topology"), "SLK_PREFLIGHT_TOPOLOGY")
    if topology.get("planned_sqlite_authorities") != 1 or topology.get("planned_repository_authorities") != 1 or topology.get("table_reset_allowed") is not False:
        fail("SLK_PREFLIGHT_TOPOLOGY", "requires one SQLite, one repository and no reset")
    result = mapping(receipt.get("preflight_results"), "SLK_PREFLIGHT_RESULT")
    for name in ("visible_ids_match_pattern", "request_shape_valid", "authority_seeds_valid", "topology_valid"):
        if result.get(name) is not True:
            fail("SLK_PREFLIGHT_RESULT", name)
    if result.get("business_calls_attempted") != 0 or result.get("product_test_ui_writes") != 0:
        fail("SLK_PREFLIGHT_SIDE_EFFECT", "preflight must have zero business calls and writes")
    credit = mapping(receipt.get("credit"), "SLK_PREFLIGHT_CREDIT")
    if credit.get("credited_minimal_experiments_consumed") != 0 or credit.get("invalid_preflight_counts_as_experiment") is not False:
        fail("SLK_PREFLIGHT_CREDIT", "preflight cannot consume experiment credit")
    evidence = receipt.get("evidence_refs")
    if not isinstance(evidence, list) or not evidence:
        fail("SLK_PREFLIGHT_EVIDENCE", "evidence_refs")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: validate_causal_experiment_preflight.py <preflight.json>", file=sys.stderr)
        return 2
    try:
        receipt = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail("SLK_PREFLIGHT_READ", str(exc))
    validate(mapping(receipt, "SLK_PREFLIGHT_ROOT"))
    print("PASS: causal experiment preflight is deterministic, zero-credit and side-effect free.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
