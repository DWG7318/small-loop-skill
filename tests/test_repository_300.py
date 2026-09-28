from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import validate_repository


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_repository_validator_passes_for_the_current_collection() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_repository.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: SLK 4.3.1 skill collection" in result.stdout


def test_manifest_covers_the_collection_and_excludes_itself() -> None:
    manifest = json.loads(read("MANIFEST.json"))
    paths = {item["path"] for item in manifest["files"]}
    assert manifest["name"] == "Small Loop Skill Collection"
    assert manifest["version"] == "4.3.1"
    assert manifest["skill_count"] == 15
    assert "MANIFEST.json" not in paths
    assert "skills/small-loop-skill/SKILL.md" in paths
    assert "skills/slk-close-run/SKILL.md" in paths
    assert "skills/slk-guard-resources/SKILL.md" in paths
    assert "skills/slk-record-run/assets/SLK-RUN.template.md" in paths


def test_426_public_runtime_contracts_are_closed_and_versioned() -> None:
    contracts = {
        "docs/contracts/slk-transport-task.schema.json": {
            "schema_version", "message_id", "run_id", "go_id", "cell_id",
            "endpoint", "envelope", "result_contract", "result_path",
        },
        "docs/contracts/slk-runtime-snapshot.schema.json": {
            "run_id", "runtime_revision", "plan_revision", "token_sequence",
            "token_holder_role_instance_id", "latest_event_id",
            "latest_message_id", "method_version", "overwatcher_binding_revision",
            "overwatcher_status", "committed_at",
        },
        "docs/contracts/slk-overwatch-cycle.schema.json": {
            "cycle_id", "run_id", "plan_revision", "role_instance_id",
            "session_id", "foreground_turn_id", "binding_revision",
            "runtime_revision", "native_liveness", "cycle_sequence",
            "cadence_seconds", "go_id", "cell_id", "attempt", "token_sequence",
            "token_holder_role_instance_id", "latest_event_id",
            "latest_message_id", "checklist", "anomaly_codes", "evidence_refs",
            "cost_metrics", "native_active_session_evidence_ref", "started_at",
            "completed_at", "next_cycle_at",
        },
        "docs/contracts/slk-worker-completion-inspection.schema.json": {
            "schema_version", "run_id", "go_id", "cell_id", "attempt", "source_message_id",
            "worker_role_instance_id", "observed_at", "cadence_seconds", "status",
                "grace_started_at", "anomaly_codes", "notification_already_sent",
                "missing_worker_events", "candidate", "worker_outcome", "blocker",
                "handoff_message_id",
        },
        "docs/contracts/slk-worker-continuation.schema.json": {
            "schema_version", "method_version", "run_id", "go_id", "cell_id", "attempt",
            "plan_revision", "runtime_revision", "source_message_id", "source_attempt_root",
            "continuation_result_path", "source_endpoint_sha256", "source_envelope_sha256",
            "worker_result_sha256", "worker_role_instance_id", "worker_instance_id",
            "worker_session_id", "checker_endpoint", "credential_path", "state_command",
            "transport_command", "token_sequence", "occurred_at",
        },
        "docs/contracts/slk-ocrv-worker-recovery.schema.json": {
            "schema_version", "method_version", "recovery_invocation_id",
            "recovery_envelope_message_id", "run_id", "go_id", "cell_id",
            "checker_role_instance_id", "checker_endpoint_version", "checker_endpoint",
            "source_attempt_root", "runtime_projection_path", "plan_revision",
            "runtime_revision", "token_sequence", "worker_credential_path",
            "checker_credential_path", "state_command", "transport_command",
            "occurred_at", "result_path",
        },
        "docs/contracts/slk-ocrv-worker-recovery-result.schema.json": {
            "schema_version", "method_version", "status", "run_id", "cell_id",
            "source_message_id", "worker_session_id", "checker_role_instance_id",
            "checker_endpoint_version", "checker_authenticated", "authorized_recovery",
            "recovery_invocation_id", "request_sha256",
        },
        "docs/contracts/slk-overwatcher-cadence-inspection.schema.json": {
            "schema_version", "run_id", "observed_at", "projected_active",
            "overwatcher_role_instance_id", "latest_cycle_id",
            "latest_cycle_completed_at", "cadence_seconds", "elapsed_seconds",
            "missed_intervals", "status", "anomaly_codes", "action",
        },
        "docs/contracts/slk-overwatcher-turn-resume.schema.json": {
            "event_id", "run_id", "role_instance_id", "session_id",
            "binding_revision", "expected_runtime_revision",
            "previous_foreground_turn_id", "foreground_turn_id",
            "last_anomaly_cycle_id", "last_native_status_id", "native_active_session_evidence",
            "reason", "occurred_at",
        },
        "docs/contracts/slk-overwatcher-credential-rotation.schema.json": {
            "rotation_id", "run_id", "expected_binding_revision",
            "expected_runtime_revision", "role_instance_id", "session_id",
            "foreground_turn_id", "expected_overwatcher_credential_id",
            "evidence", "reason", "occurred_at",
        },
    }
    for relative, required in contracts.items():
        schema = json.loads(read(relative))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False
        assert set(schema["properties"]) == required
        if relative.endswith("slk-overwatcher-turn-resume.schema.json"):
            assert set(schema["required"]) == required - {
                "last_anomaly_cycle_id",
                "last_native_status_id",
            }
        else:
            assert set(schema["required"]) == required


def test_overwatcher_resume_has_exactly_one_basis_and_cycle_enum_excludes_incident_code() -> None:
    resume = json.loads(read("docs/contracts/slk-overwatcher-turn-resume.schema.json"))
    cycle = json.loads(read("docs/contracts/slk-overwatch-cycle.schema.json"))

    assert "last_anomaly_cycle_id" not in resume["required"]
    assert "last_native_status_id" not in resume["required"]
    assert len(resume["oneOf"]) == 2
    anomaly_codes = cycle["properties"]["anomaly_codes"]["items"]["enum"]
    assert "OVERWATCHER_ACTIVE_DEGRADED" in anomaly_codes
    assert "OVERWATCHER_CONTINUITY_VIOLATION" not in anomaly_codes


def test_release_file_discovery_follows_git_and_ignores_local_build_outputs(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("node_modules/\ndist/\n", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    (tmp_path / "new-doc.md").write_text("new\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dependency.js").write_text(
        "ignored\n", encoding="utf-8"
    )
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.js").write_text("ignored\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", "tracked.txt"], cwd=tmp_path, check=True
    )

    paths = {path.as_posix() for path in validate_repository.release_files(tmp_path)}

    assert paths == {".gitignore", "new-doc.md", "tracked.txt"}


def test_readmes_explain_the_lightweight_collection_and_recovery_version() -> None:
    english = read("README.md")
    chinese = read("README.zh-CN.md")
    for text in (english, chinese):
        assert "4.3.1" in text
        assert "14" in text
        assert "skills/small-loop-skill/SKILL.md" in text
        assert "v2.6.0" in text
        assert "Control Conversation" not in text
    assert "verify fixed role bindings → size initial CELLs" in english
    assert "Supervisor creates Checker → Checker role Eval" in english
    assert "Checker creates Worker" in english
    assert "核对固定角色绑定 → 划分初始 CELL" in chinese
    assert "Supervisor 创建 Checker → Checker 角色 Eval" in chinese
    assert "Checker 创建 Worker" in chinese
    assert "not standalone methods" in english
    assert "不可脱离 SLK Run 单独使用" in chinese
    for marker in ("RTK", "Probe CLI", "Ponytail"):
        assert marker in english and marker in chinese


def test_migration_and_changelog_state_the_major_boundary() -> None:
    migration = read("MIGRATION.md")
    changelog = read("CHANGELOG.md")
    assert "2.6.0" in migration and "3.0.0" in migration
    assert "Supervisor" in migration and "Checker" in migration and "Worker" in migration
    assert "## 4.3.1" in changelog and "## 4.3.0" in changelog and "## 4.2.11" in changelog and "## 4.2.10" in changelog and "## 4.2.9" in changelog and "## 4.2.8" in changelog and "## 4.2.7" in changelog and "## 4.2.6" in changelog and "## 4.2.5" in changelog and "## 4.2.4" in changelog and "## 4.2.2" in changelog and "## 4.2.1" in changelog and "## 4.2.0" in changelog and "## 4.1.1" in changelog and "## 4.1.0" in changelog and "## 4.0.0" in changelog and "## 3.0.8" in changelog and "## 3.0.7" in changelog and "## 3.0.6" in changelog and "## 3.0.5" in changelog and "## 3.0.4" in changelog and "## 3.0.3" in changelog and "## 3.0.2" in changelog and "## 3.0.1" in changelog and "## 3.0.0" in changelog
    assert "one complete CELL" in changelog
    assert "later CELLs" in changelog
    assert "inspection-only CELLs" in changelog
    assert "completed work" in changelog


def test_431_consistency_audit_is_complete_and_packaged() -> None:
    audit = (ROOT / "docs/maintenance/2026-09-28-slk-4.3.1-consistency-audit.md").read_text(
        encoding="utf-8"
    )
    for skill in validate_repository.EXPECTED_SKILLS:
        assert f"`{skill}`" in audit
    for marker in (
        "Skill / contract / producer / consumer matrix",
        "Authority and outcome matrix",
        "Writes, capacity and continuity",
        "Migration, package, BI and Temporal-off",
        "Same-class findings and corrections",
        "context compaction",
    ):
        assert marker in audit
    assert "docs/maintenance" in (ROOT / "scripts/build_local_package.py").read_text(
        encoding="utf-8"
    )


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
