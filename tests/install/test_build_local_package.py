from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_local_package import ARTIFACT_NAMES, PackageError, build_package
from scripts.validate_repository import EXPECTED_SKILLS


ROOT = Path(__file__).resolve().parents[2]


def fake_artifacts(root: Path) -> Path:
    root.mkdir()
    for name in ARTIFACT_NAMES:
        (root / name).write_bytes(f"fake-{name}-4.2.6\n".encode())
    return root


def test_complete_package_has_exact_skills_artifacts_docs_and_hashes(tmp_path: Path) -> None:
    package = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package")
    manifest = json.loads((package / "install-manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "slk.install-manifest/v1"
    assert manifest["version"] == "4.2.6"
    assert manifest["skill_count"] == 15
    assert manifest["artifact_count"] == 5
    paths = {entry["path"] for entry in manifest["files"]}
    assert {f"skills/{name}/SKILL.md" for name in EXPECTED_SKILLS} <= paths
    assert {f"tools/slk/bin/{name}" for name in ARTIFACT_NAMES} <= paths
    assert {
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
        "tools/slk/share/small-loop-skill/docs/contracts/slk-overwatcher-cadence-inspection.schema.json",
        "tools/slk/share/small-loop-skill/integrations/ocrv/install.ps1",
        "tools/slk/share/small-loop-skill/integrations/ocrv/rollback.ps1",
        "tools/slk/share/small-loop-skill/integrations/ocrv/slk-checker.cmd",
        "tools/slk/share/small-loop-skill/integrations/ocrv/slk_checker_recovery.py",
        "tools/slk/share/small-loop-skill/schema/sqlite/0007.sql",
        "tools/slk/share/small-loop-skill/VERSION",
    } <= paths
    assert sorted(paths) == [entry["path"] for entry in manifest["files"]]
    assert all(len(entry["sha256"]) == 64 and entry["size"] >= 0 for entry in manifest["files"])


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
