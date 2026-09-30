from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.run_425_sandbox_drill import run_sandbox_drill


def state_binary() -> Path:
    configured = os.environ.get("SLK_STATE_BIN")
    if configured:
        path = Path(configured)
    else:
        suffix = ".exe" if os.name == "nt" else ""
        path = Path(__file__).parents[2] / "target" / "debug" / f"slk-state{suffix}"
    if not path.is_file():
        pytest.skip("build slk-state or set SLK_STATE_BIN before the 4.3.5 sandbox drill")
    return path.resolve()


def test_426_sandbox_proves_runtime_consistency_without_product_paths(tmp_path: Path) -> None:
    output = tmp_path / "slk-4.3.5-sandbox"

    report = run_sandbox_drill(output, state_binary())

    assert report["schema_version"] == "slk.sandbox-drill-report/v1"
    assert report["method_version"] == "4.3.5"
    assert report["status"] == "PASS"
    assert report["proofs"] == {
        "active_writer_new_message_recovery": True,
        "atomic_delivery_start_revision": True,
        "direct_inactive_wake": True,
        "early_native_start_before_terminal": True,
        "exact_worker_event_replay": True,
        "final_cycle_close": True,
        "late_cadence_not_false_inactive": True,
        "no_bom_route": True,
        "no_model_upgrade": True,
        "overwatcher_worker_completion_guard": True,
        "one_overwatcher_binding": True,
        "one_overwatcher_foreground_turn": True,
        "same_worker_session_continuation": True,
        "authenticated_checker_recovery": True,
        "deterministic_recovery_invocation": True,
        "projected_active_not_cycle_proof": True,
        "public_direct_resume_removed": True,
    }
    assert report["counts"]["overwatcher_bindings"] == 1
    assert report["counts"]["overwatch_cycles"] == 3
    assert report["counts"]["transport_start_receipts"] == 1
    assert report["counts"]["worker_completion_guard_checks"] == 3
    assert report["counts"]["model_change_events"] == 0
    assert report["counts"]["bom_routes"] == 0

    output_root = output.resolve()
    for root in report["disposable_roots"]:
        assert Path(root).resolve().is_relative_to(output_root)
    assert "LCaS" not in json.dumps(report, ensure_ascii=False)
    assert (output / "report.json").is_file()
