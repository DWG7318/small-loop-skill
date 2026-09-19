from __future__ import annotations

import sys
from pathlib import Path

from scripts.build_transport_zipapp import build_zipapp
from scripts.run_transport_drill import run_drill


TESTS = Path(__file__).parent


def fake_config(tmp_path: Path) -> dict[str, object]:
    return {
        "evidence_root": str(tmp_path / "evidence"),
        "workspace_root": str(tmp_path / "workspaces"),
        "codex_command": [sys.executable, str(TESTS / "fake_app_server.py"), "normal"],
        "ocrv_command": [sys.executable, str(TESTS / "fake_ocrv.py"), "normal"],
        "dsh_command": [sys.executable, str(TESTS / "fake_dsh.py"), "normal"],
        "timeout_seconds": 5,
    }


def test_drill_completes_four_legs_without_cross_run_data(tmp_path: Path) -> None:
    summary = run_drill(fake_config(tmp_path), live=False, run_ids=("RUN-A", "RUN-B"))

    assert summary["RUN-A"]["legs"] == ["S-C", "C-W", "W-C", "C-S"]
    assert summary["RUN-B"]["legs"] == ["S-C", "C-W", "W-C", "C-S"]
    assert summary["RUN-A"]["probe_nonce"] == "RUN-A-NONCE"
    assert summary["RUN-B"]["probe_nonce"] == "RUN-B-NONCE"
    assert summary["RUN-A"]["final_token_sequence"] == 4
    assert summary["RUN-B"]["final_token_sequence"] == 4
    assert summary["crossovers"] == []

    a = summary["RUN-A"]["native_identities"]
    b = summary["RUN-B"]["native_identities"]
    assert a["worker"]["instance_id"] != b["worker"]["instance_id"]
    assert a["worker"]["session_id"] != b["worker"]["session_id"]
    assert a["checker"]["session_id"] != b["checker"]["session_id"]
    assert a["supervisor"]["thread_id"] != b["supervisor"]["thread_id"]


def test_drill_proves_failed_boundary_retains_token_and_endpoint_rebound(tmp_path: Path) -> None:
    summary = run_drill(fake_config(tmp_path), live=False, run_ids=("RUN-A",))
    run = summary["RUN-A"]

    assert run["failed_delivery"]["rejected"] is True
    assert run["failed_delivery"]["token_before"] == run["failed_delivery"]["token_after"]
    assert run["endpoint_rebound"] == {
        "retired_version_rejected": True,
        "active_version": 2,
        "active_version_completed": True,
    }


def test_drill_rejects_live_mode_until_real_runtime_bootstrap_is_supplied(tmp_path: Path) -> None:
    config = fake_config(tmp_path)

    try:
        run_drill(config, live=True, run_ids=("RUN-A",))
    except ValueError as exc:
        assert str(exc) == "live drill requires explicit real runtime endpoints"
    else:
        raise AssertionError("live mode silently used fake endpoints")


def test_live_drill_first_leg_is_started_by_exact_supervisor_agent(tmp_path: Path) -> None:
    config = fake_config(tmp_path)
    config["codex_command"] = [sys.executable, str(TESTS / "fake_app_server.py"), "execute-command"]
    config["transport_artifact"] = str(build_zipapp(tmp_path / "slk-transport.pyz"))
    config["live_endpoints"] = True
    config["codex_model"] = "gpt-5.6-sol"
    config["codex_effort"] = "xhigh"

    summary = run_drill(config, live=True, run_ids=("RUN-A", "RUN-B"))

    assert summary["RUN-A"]["supervisor_started_first_send"] is True
    assert summary["RUN-B"]["supervisor_started_first_send"] is True
    assert summary["RUN-A"]["legs"] == ["S-C", "C-W", "W-C", "C-S"]
    assert summary["RUN-B"]["legs"] == ["S-C", "C-W", "W-C", "C-S"]
    assert summary["crossovers"] == []
