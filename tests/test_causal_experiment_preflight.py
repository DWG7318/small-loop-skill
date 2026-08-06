from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_causal_experiment_preflight.py"


def receipt() -> dict:
    return {
        "schema_version": "slk.causal-experiment-preflight.v1",
        "status": "PASS_READY_FOR_CREDITED_EXPERIMENT",
        "candidate_ref": "sha256:example",
        "input_contract": {
            "visible_id_pattern": "^[A-Z0-9]{4}$",
            "visible_ids": ["A001", "S001"],
            "request_shape_checks": [{"name": "exact envelope", "pass": True}],
            "authority_seed_checks": [{"name": "one exact seed", "pass": True}],
            "topology": {
                "planned_sqlite_authorities": 1,
                "planned_repository_authorities": 1,
                "table_reset_allowed": False,
            },
        },
        "preflight_results": {
            "visible_ids_match_pattern": True,
            "request_shape_valid": True,
            "authority_seeds_valid": True,
            "topology_valid": True,
            "business_calls_attempted": 0,
            "product_test_ui_writes": 0,
        },
        "credit": {
            "credited_minimal_experiments_consumed": 0,
            "invalid_preflight_counts_as_experiment": False,
        },
        "evidence_refs": ["preflight.json"],
    }


def run(tmp_path: Path, value: dict) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "preflight.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_valid_preflight_is_zero_credit_and_side_effect_free(tmp_path: Path) -> None:
    result = run(tmp_path, receipt())
    assert result.returncode == 0
    assert "PASS: causal experiment preflight" in result.stdout


def test_invalid_identifier_and_business_call_fail_closed(tmp_path: Path) -> None:
    value = receipt()
    value["input_contract"]["visible_ids"] = ["TOO-LONG"]
    result = run(tmp_path, value)
    assert result.returncode == 1
    assert "SLK_PREFLIGHT_IDENTIFIER" in result.stderr

    value = receipt()
    value["preflight_results"]["business_calls_attempted"] = 1
    result = run(tmp_path, value)
    assert result.returncode == 1
    assert "SLK_PREFLIGHT_SIDE_EFFECT" in result.stderr
