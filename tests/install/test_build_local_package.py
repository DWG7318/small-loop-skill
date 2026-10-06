from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_local_package import ARTIFACT_NAMES, PackageError, build_package
from scripts.validate_repository import EXPECTED_SKILLS
from scripts.verify_local_install import VerificationError, verify


ROOT = Path(__file__).resolve().parents[2]


def test_active_install_does_not_export_historical_auxiliary_instructions():
    from scripts.build_local_package import ROOT_DOCUMENTS, DOCUMENT_TREES
    assert "CHANGELOG.md" not in ROOT_DOCUMENTS
    assert "MIGRATION.md" not in ROOT_DOCUMENTS
    assert "docs/maintenance" not in DOCUMENT_TREES
    # Source audit/history stay immutable and available in Git, not current instructions.
    assert (ROOT / "CHANGELOG.md").is_file()
    assert (ROOT / "docs/maintenance/2026-09-28-slk-4.3.1-consistency-audit.md").is_file()


def fake_artifacts(root: Path) -> Path:
    root.mkdir()
    for name in ARTIFACT_NAMES:
        (root / name).write_bytes(f"fake-{name}-4.4.2\n".encode())
    return root


def test_complete_package_has_exact_skills_artifacts_docs_and_hashes(tmp_path: Path) -> None:
    package = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package")
    manifest = json.loads((package / "install-manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "slk.install-manifest/v1"
    assert manifest["version"] == "4.4.2"
    assert manifest["skill_count"] == 16
    assert manifest["artifact_count"] == 5
    paths = {entry["path"] for entry in manifest["files"]}
    assert {f"skills/{name}/SKILL.md" for name in EXPECTED_SKILLS} <= paths
    assert {f"tools/slk/bin/{name}" for name in ARTIFACT_NAMES} <= paths
    assert "tools/slk/bin/slk-transport.cmd" in paths
    launcher = (package / "tools/slk/bin/slk-transport.cmd").read_text(encoding="utf-8")
    assert 'python "%~dp0slk-transport.pyz" %*' in launcher
    assert {
        "docs/state/SLK-STATE.md",
        "docs/transport/SLK-TRANSPORT.md",
        "docs/runtime/SLK-TEMPORAL.md",
        "tools/slk/share/small-loop-skill/docs/state/SLK-STATE.md",
        "tools/slk/share/small-loop-skill/docs/state/SLK-BI.md",
        "tools/slk/share/small-loop-skill/docs/transport/SLK-TRANSPORT.md",
        "tools/slk/share/small-loop-skill/docs/runtime/SLK-WINDOWS-RUNTIME.md",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-transport-task.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-runtime-snapshot.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-overwatch-cycle.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-worker-completion-inspection.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-worker-continuation.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-ocrv-worker-recovery.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-ocrv-worker-recovery-result.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-ocrv-incomplete-checker-resume.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-ocrv-terminal-budget-resume.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-ocrv-terminal-budget-resume-result.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-ocrv-terminal-budget-fresh-review.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-ocrv-terminal-budget-fresh-review-result.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-checker-post-d1.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-checker-completion.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-native-execution-outcome.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-overwatcher-cadence-inspection.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-overwatcher-credential-rotation.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-overwatcher-status.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-desktop-overwatcher-attestation-request.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-desktop-overwatcher-attestation.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-temporal-delivery.schema.json",
        "tools/slk/share/small-loop-skill/docs/runtime/SLK-4.4.2-MIGRATION.md",
        "tools/slk/share/small-loop-skill/integrations/ocrv/install.ps1",
        "tools/slk/share/small-loop-skill/integrations/ocrv/rollback.ps1",
        "tools/slk/share/small-loop-skill/integrations/ocrv/slk-checker.cmd",
        "tools/slk/share/small-loop-skill/integrations/ocrv/slk_checker_recovery.py",
        "tools/slk/share/small-loop-skill/integrations/ocrv/slk_checker_post_d1.py",
        "tools/slk/share/small-loop-skill/integrations/temporal/README.md",
        "tools/slk/share/small-loop-skill/integrations/temporal/slk-overwatcher-capabilities.json",
        "tools/slk/share/small-loop-skill/integrations/temporal/pyproject.toml",
        "tools/slk/share/small-loop-skill/integrations/temporal/src/slk_temporal/contracts.py",
        "tools/slk/share/small-loop-skill/integrations/temporal/src/slk_temporal/delivery_client.py",
        "tools/slk/share/small-loop-skill/integrations/temporal/src/slk_temporal/workflows.py",
        "tools/slk/share/small-loop-skill/schema/sqlite/0007.sql",
        "tools/slk/share/small-loop-skill/schema/sqlite/0008.sql",
        "tools/slk/share/small-loop-skill/schema/sqlite/0009.sql",
        "tools/slk/share/small-loop-skill/VERSION",
    } <= paths
    assert (package / "docs/state/SLK-STATE.md").read_bytes() == (
        package / "tools/slk/share/small-loop-skill/docs/state/SLK-STATE.md"
    ).read_bytes()
    assert sorted(paths) == [entry["path"] for entry in manifest["files"]]
    assert all(len(entry["sha256"]) == 64 and entry["size"] >= 0 for entry in manifest["files"])


def test_temporal_tree_is_closed_and_hash_bound_in_package(tmp_path: Path) -> None:
    package = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package")
    assert verify(package, package_mode=True)["status"] == "PASS"

    target = package / "tools/slk/share/small-loop-skill/integrations/temporal/README.md"
    original = target.read_bytes()
    target.write_bytes(original + b"tampered")
    with pytest.raises(VerificationError, match="hash mismatch"):
        verify(package, package_mode=True)
    target.write_bytes(original)

    extra = package / "tools/slk/share/small-loop-skill/integrations/temporal/extra.py"
    extra.write_text("unexpected", encoding="utf-8")
    with pytest.raises(VerificationError, match="missing or extra"):
        verify(package, package_mode=True)


def test_artifact_set_is_exact_and_output_must_be_empty(tmp_path: Path) -> None:
    artifacts = fake_artifacts(tmp_path / "artifacts")
    (artifacts / "unexpected.exe").write_bytes(b"extra")
    with pytest.raises(PackageError, match="artifact set"):
        build_package(ROOT, artifacts, tmp_path / "package")

    (artifacts / "unexpected.exe").unlink()
    output = tmp_path / "occupied"
    output.mkdir()
    (output / "old.txt").write_text("old", encoding="utf-8")
    with pytest.raises(PackageError, match="output directory"):
        build_package(ROOT, artifacts, output)


def test_package_rejects_a_bi_artifact_that_still_uses_vite_dev_assets(tmp_path: Path) -> None:
    artifacts = fake_artifacts(tmp_path / "artifacts")
    (artifacts / "slk-bi-desktop.exe").write_bytes(
        b"MZ release-looking bytes http://localhost:1430/src/main.tsx @vite/client"
    )

    with pytest.raises(PackageError, match="development asset markers"):
        build_package(ROOT, artifacts, tmp_path / "package")
