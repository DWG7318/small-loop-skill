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
    assert manifest["version"] == "3.0.3"
    assert manifest["skill_count"] == 13
    assert "MANIFEST.json" not in paths
    assert "skills/small-loop-skill/SKILL.md" in paths
    assert "skills/slk-close-run/SKILL.md" in paths
    assert "skills/slk-record-run/assets/SLK-RUN.template.md" in paths


def test_readmes_explain_the_lightweight_collection_and_recovery_version() -> None:
    english = read("README.md")
    chinese = read("README.zh-CN.md")
    for text in (english, chinese):
        assert "3.0.3" in text
        assert "12" in text
        assert "skills/small-loop-skill/SKILL.md" in text
        assert "v2.6.0" in text
        assert "Control Conversation" not in text
    assert "select role models → size initial CELLs" in english
    assert "Supervisor creates Checker → Checker readiness" in english
    assert "Checker creates Worker" in english
    assert "选择角色模型 → 划分初始 CELL" in chinese
    assert "Supervisor 创建 Checker → Checker 职责确认" in chinese
    assert "Checker 创建 Worker" in chinese
    assert "not standalone methods" in english
    assert "不可脱离 SLK Run 单独使用" in chinese


def test_migration_and_changelog_state_the_major_boundary() -> None:
    migration = read("MIGRATION.md")
    changelog = read("CHANGELOG.md")
    assert "2.6.0" in migration and "3.0.0" in migration
    assert "Supervisor" in migration and "Checker" in migration and "Worker" in migration
    assert "## 3.0.3" in changelog and "## 3.0.2" in changelog and "## 3.0.1" in changelog and "## 3.0.0" in changelog
    assert "one complete CELL" in changelog


def test_current_design_uses_the_same_startup_d2_and_recovery_routes() -> None:
    design = read(
        "docs/superpowers/specs/2026-08-22-slk-lightweight-skill-collection-design.md"
    )
    assert design.index("plan-run: Run/GO/分层检查") < design.index(
        "select-models: 三角色能力"
    ) < design.index("plan-run: 初始 CELL")
    assert "D1 PASS 或 Supervisor 豁免" in design
    assert "全部计划 CELL 已 D1 PASS 或豁免" in design
    assert design.count("-.通讯异常.-> RC") == 1
    assert "Worker 交付候选后缺少当前 CELL 的接收证据" in design
    assert "Checker 理解确认" in design
    assert "复用已记录" in design


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
