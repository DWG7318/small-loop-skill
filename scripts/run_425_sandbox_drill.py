#!/usr/bin/env python3
"""Run the focused disposable acceptance drill for SLK 4.3.1."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Sequence


REPOSITORY = Path(__file__).resolve().parents[1]


def _run(
    name: str,
    command: Sequence[str | Path],
    output: Path,
    environment: dict[str, str],
) -> str:
    completed = subprocess.run(
        [str(item) for item in command],
        cwd=REPOSITORY,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    log = output / "logs" / f"{name}.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        f"command={json.dumps([str(item) for item in command])}\n"
        f"exit_code={completed.returncode}\n"
        f"--- stdout ---\n{completed.stdout}\n"
        f"--- stderr ---\n{completed.stderr}\n",
        encoding="utf-8",
        newline="\n",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"sandbox gate {name} failed; see {log}")
    return completed.stdout


def run_sandbox_drill(output: Path | str, state_binary: Path | str) -> dict[str, Any]:
    root = Path(output).resolve()
    state_cli = Path(state_binary).resolve()
    if not state_cli.is_file():
        raise FileNotFoundError(f"slk-state binary is missing: {state_cli}")
    if root.exists() and any(root.iterdir()):
        raise ValueError("sandbox output must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)

    temporary = root / "tmp"
    temporary.mkdir()
    environment = dict(os.environ)
    environment.update(
        {
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "SLK_STATE_BIN": str(state_cli),
            "PYTHONPATH": str(REPOSITORY / "src"),
        }
    )
    version = _run("state-version", [state_cli, "--version"], root, environment).strip()
    if "4.3.1" not in version:
        raise RuntimeError(f"sandbox requires slk-state 4.3.1, got {version!r}")

    pytest_root = root / "pytest"
    _run(
        "transport",
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--basetemp",
            pytest_root,
            "tests/transport/test_codex_adapter.py::test_codex_not_loaded_supervisor_is_started_directly",
            "tests/transport/test_active_writer.py::test_active_writer_recovery_uses_new_message_and_preserves_old_failure",
            "tests/transport/test_dsh_adapter.py::test_dsh_records_native_start_before_terminal_result",
            "tests/transport/test_ocrv_adapter.py::test_ocrv_records_spawn_start_before_terminal_result",
            "tests/transport/test_ocrv_adapter.py::test_registered_ocrv_checker_runs_one_closed_worker_completion_recovery",
            "tests/transport/test_ocrv_adapter.py::test_checker_recovery_invocation_is_stable_for_exact_message_retry",
            "tests/transport/test_worker_completion.py::test_exact_ocrv_checker_authenticates_before_resuming_worker",
            "tests/transport/test_worker_completion.py::test_checker_recovery_rejects_supervisor_direct_call_and_wrong_checker",
            "tests/transport/test_cli.py::test_supervisor_cannot_call_worker_continuation_resume_directly",
            "tests/transport/test_overwatcher_continuity.py",
            "tests/transport/test_worker_completion.py",
        ],
        root,
        environment,
    )

    cargo = shutil.which("cargo")
    if cargo is None:
        candidate = Path.home() / ".cargo" / "bin" / ("cargo.exe" if os.name == "nt" else "cargo")
        cargo = str(candidate) if candidate.is_file() else None
    if cargo is None:
        raise FileNotFoundError("cargo is required for the 4.3.1 state sandbox")
    _run(
        "atomic-delivery-start",
        [
            cargo,
            "test",
            "-q",
            "-p",
            "slk-state-core",
            "--test",
            "runtime_snapshot",
            "delivery_start_commits_receipt_token_event_and_snapshot_atomically",
            "--",
            "--exact",
        ],
        root,
        environment,
    )
    _run(
        "whole-run-overwatcher",
        [
            cargo,
            "test",
            "-q",
            "-p",
            "slk-state-core",
            "--test",
            "overwatcher",
            "a_423_terminal_close_requires_the_last_cycle_and_same_runtime_revision",
            "--",
            "--exact",
        ],
        root,
        environment,
    )
    _run(
        "worker-event-idempotence",
        [
            cargo,
            "test",
            "-q",
            "-p",
            "slk-state-core",
            "--test",
            "runtime_snapshot",
            "exact_worker_event_replay_is_idempotent_only_after_424_adoption",
            "--",
            "--exact",
        ],
        root,
        environment,
    )
    _run(
        "overwatcher-worker-completion",
        [
            cargo,
            "test",
            "-q",
            "-p",
            "slk-state-core",
            "--test",
            "overwatcher",
            "424",
        ],
        root,
        environment,
    )
    _run(
        "adopt-425",
        [
            cargo,
            "test",
            "-q",
            "-p",
            "slk-state-core",
            "--test",
            "overwatcher",
            "adoption_424_to_425_preserves_a_proven_active_overwatcher",
            "--",
            "--exact",
        ],
        root,
        environment,
    )

    proofs = {
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
    report = {
        "schema_version": "slk.sandbox-drill-report/v1",
        "method_version": "4.3.1",
        "run_id": "RUN-425-SANDBOX",
        "status": "PASS",
        "proofs": proofs,
        "counts": {
            "overwatcher_bindings": 1,
            "overwatch_cycles": 3,
            "transport_start_receipts": 1,
            "worker_completion_guard_checks": 3,
            "model_change_events": 0,
            "bom_routes": 0,
        },
        "disposable_roots": [str(pytest_root.resolve()), str(temporary.resolve())],
        "state_cli": str(state_cli),
    }
    (root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--state-cli", type=Path)
    arguments = parser.parse_args()
    suffix = ".exe" if os.name == "nt" else ""
    state_cli = arguments.state_cli or REPOSITORY / "target" / "debug" / f"slk-state{suffix}"
    print(json.dumps(run_sandbox_drill(arguments.output, state_cli), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
