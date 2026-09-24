from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "integrations" / "ocrv"


def powershell() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        pytest.skip("PowerShell is unavailable")
    return executable


def run_script(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [powershell(), "-NoProfile", "-NonInteractive", "-File", str(script), *arguments],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )


def test_ocrv_recovery_wrapper_preserves_the_existing_d1_entry() -> None:
    wrapper = (INTEGRATION / "slk-checker.cmd").read_text(encoding="utf-8")
    assert '"%~1"=="--slk-worker-recovery"' in wrapper
    assert "slk_checker_recovery.py" in wrapper
    assert "slk_checker_adapter.py" in wrapper


def test_ocrv_integration_installs_and_rolls_back_only_two_files(tmp_path: Path) -> None:
    ocrv = tmp_path / "ocrv"
    ocrv.mkdir()
    adapter = b"accepted-adapter\n"
    original_wrapper = b"@echo off\r\npython old.py %*\r\n"
    (ocrv / "slk_checker_adapter.py").write_bytes(adapter)
    (ocrv / "slk-checker.cmd").write_bytes(original_wrapper)

    installed = run_script(INTEGRATION / "install.ps1", "-OcrvRoot", str(ocrv))

    assert installed.returncode == 0, installed.stdout + installed.stderr
    receipt = json.loads(installed.stdout.strip())
    backup = Path(receipt["backup_root"])
    assert receipt["version"] == "4.2.9"
    assert (ocrv / "slk_checker_adapter.py").read_bytes() == adapter
    assert (ocrv / "slk-checker.cmd").read_bytes() == (INTEGRATION / "slk-checker.cmd").read_bytes()
    assert (ocrv / "slk_checker_recovery.py").read_bytes() == (
        INTEGRATION / "slk_checker_recovery.py"
    ).read_bytes()

    rolled_back = run_script(
        INTEGRATION / "rollback.ps1",
        "-OcrvRoot",
        str(ocrv),
        "-BackupRoot",
        str(backup),
    )

    assert rolled_back.returncode == 0, rolled_back.stdout + rolled_back.stderr
    assert (ocrv / "slk-checker.cmd").read_bytes() == original_wrapper
    assert not (ocrv / "slk_checker_recovery.py").exists()
    assert (ocrv / "slk_checker_adapter.py").read_bytes() == adapter
