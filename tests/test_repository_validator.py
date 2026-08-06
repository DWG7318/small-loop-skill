from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_repository_validator_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_repository.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: SLK repository" in result.stdout


def test_manifest_covers_validation_report_and_excludes_itself() -> None:
    manifest = json.loads((ROOT / "MANIFEST.json").read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["files"]}
    assert "VALIDATION-REPORT.md" in paths
    assert "MANIFEST.json" not in paths
    assert manifest["name"] == "Small Loop Skill"
    assert manifest["version"] == "2.5.1"


def test_license_is_complete_mit_text() -> None:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "The above copyright notice and this permission notice" in text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in text
    assert "IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE" in text


def test_ci_runs_on_windows_and_ubuntu() -> None:
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert "python scripts/validate_repository.py" in workflow
    assert "python scripts/validate_serial_plan.py examples/minimal-run/serial-plan.yaml" in workflow


def test_release_text_uses_stable_lf_hashes() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in attributes
    assert b"\r\n" not in (ROOT / "MANIFEST.json").read_bytes()
