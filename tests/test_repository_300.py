from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_repository_validator_passes_for_the_300_collection() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_repository.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: SLK 3.0 skill collection" in result.stdout


def test_manifest_covers_the_collection_and_excludes_itself() -> None:
    manifest = json.loads(read("MANIFEST.json"))
    paths = {item["path"] for item in manifest["files"]}
    assert manifest["name"] == "Small Loop Skill Collection"
    assert manifest["version"] == "3.0.0"
    assert manifest["skill_count"] == 13
    assert "MANIFEST.json" not in paths
    assert "skills/small-loop-skill/SKILL.md" in paths
    assert "skills/slk-close-run/SKILL.md" in paths
    assert "skills/slk-record-run/assets/SLK-RUN.template.md" in paths


def test_readmes_explain_the_lightweight_collection_and_recovery_version() -> None:
    english = read("README.md")
    chinese = read("README.zh-CN.md")
    for text in (english, chinese):
        assert "3.0.0" in text
        assert "12" in text
        assert "skills/small-loop-skill/SKILL.md" in text
        assert "v2.6.0" in text
        assert "Control Conversation" not in text


def test_migration_and_changelog_state_the_major_boundary() -> None:
    migration = read("MIGRATION.md")
    changelog = read("CHANGELOG.md")
    assert "2.6.0" in migration and "3.0.0" in migration
    assert "Supervisor" in migration and "Checker" in migration and "Worker" in migration
    assert "## 3.0.0" in changelog


def test_ci_validates_repository_tests_and_each_skill_on_windows_and_ubuntu() -> None:
    workflow = read(".github/workflows/validate.yml")
    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert "python scripts/validate_repository.py" in workflow
    assert "python -m pytest -q" in workflow
    assert "quick_validate.py" in workflow
    assert "validate_serial_plan.py" not in workflow


def test_license_and_lf_policy_remain_available() -> None:
    license_text = read("LICENSE")
    assert "The above copyright notice and this permission notice" in license_text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text
    assert "* text=auto eol=lf" in read(".gitattributes")
    for path in (ROOT / "skills").rglob("*"):
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), path
