from __future__ import annotations

import sys
from pathlib import Path

import pytest

from scripts.run_transport_drill import run_drill
from slk_transport.drill_verify import DrillVerificationError, verify_drill


TESTS = Path(__file__).parent


def config(tmp_path: Path) -> dict[str, object]:
    return {
        "evidence_root": str(tmp_path / "evidence"),
        "workspace_root": str(tmp_path / "workspaces"),
        "codex_command": [sys.executable, str(TESTS / "fake_app_server.py"), "normal"],
        "ocrv_command": [sys.executable, str(TESTS / "fake_ocrv.py"), "normal"],
        "dsh_command": [sys.executable, str(TESTS / "fake_dsh.py"), "normal"],
        "timeout_seconds": 5,
    }


def test_verify_drill_proves_four_exact_legs_and_unique_native_identities(tmp_path: Path) -> None:
    values = config(tmp_path)
    run_drill(values, live=False, run_ids=("RUN-A", "RUN-B"))

    result = verify_drill(Path(str(values["evidence_root"])))

    assert result["status"] == "TRANSPORT_DRILL_PASS"
    assert result["run_ids"] == ["RUN-A", "RUN-B"]
    assert result["runs"]["RUN-A"]["token_sequences"] == [1, 2, 3, 4]
    assert result["runs"]["RUN-B"]["legs"] == ["S-C", "C-W", "W-C", "C-S"]


def test_verify_drill_rejects_missing_native_start_evidence(tmp_path: Path) -> None:
    values = config(tmp_path)
    run_drill(values, live=False, run_ids=("RUN-A", "RUN-B"))
    evidence = Path(str(values["evidence_root"]))
    started = next((evidence / "RUN-A").glob("*/started.json"))
    started.unlink()

    with pytest.raises(DrillVerificationError, match="started"):
        verify_drill(evidence)
