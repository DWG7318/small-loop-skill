from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import build_local_package as package_builder
from scripts.build_local_package import ARTIFACT_NAMES, PackageError, build_package as _build_package
from scripts.validate_repository import EXPECTED_SKILLS
from scripts.verify_local_install import VerificationError, _safe_relative, sha256, verify
from runtime_fixtures import prepared_runtimes


ROOT = Path(__file__).resolve().parents[2]


def fake_python(root: Path) -> Path:
    """Inventory fixture only; never claim that these bytes execute Python."""
    root.mkdir(exist_ok=True)
    for name in ("python.exe", "python314.dll", "python314.zip", "python314._pth"):
        (root / name).write_bytes(b"simulated Python inventory\n")
    return root


def build_package(repository: Path, artifacts: Path, output: Path) -> Path:
    return _build_package(
        repository, artifacts, output,
        python_runtime=fake_python(artifacts.parent / "fake-python"),
        **prepared_runtimes(artifacts.parent / "prepared"),
    )


def test_package_requires_an_explicit_prepared_python_runtime(tmp_path: Path) -> None:
    with pytest.raises(PackageError, match="Python runtime"):
        _build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package")


def test_prepared_python_inventory_accepts_regular_nested_files(tmp_path: Path) -> None:
    runtime = fake_python(tmp_path / "python")
    library = runtime / "Lib/site-packages"
    library.mkdir(parents=True)
    (library / "module.py").write_text("# ordinary prepared library\n", encoding="utf-8")
    (library / "module.pyc").write_bytes(b"development bytecode")
    cache = library / "__pycache__"
    cache.mkdir()
    (cache / "ignored.py").write_bytes(b"development cache")

    files = package_builder._runtime_files(runtime)

    assert [path.relative_to(runtime).as_posix() for path in files] == sorted([
        "python.exe", "python314.dll", "python314.zip", "python314._pth",
        "Lib/site-packages/module.py",
    ])


@pytest.mark.skipif(os.name != "nt", reason="actual Windows directory-junction regression")
@pytest.mark.parametrize("nested", (False, True), ids=("root-child", "nested-child"))
def test_prepared_python_rejects_junction_before_descendant_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nested: bool,
) -> None:
    import _winapi

    runtime = fake_python(tmp_path / "python")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_bytes(b"scratch-only outside-root bytes")
    parent = runtime / "Lib" if nested else runtime
    parent.mkdir(exist_ok=True)
    junction = parent / "linked-lib"
    _winapi.CreateJunction(str(outside), str(junction))
    assert not junction.is_symlink()
    original_is_file = Path.is_file
    original_scandir = os.scandir

    def guarded_is_file(path: Path, *args, **kwargs) -> bool:
        if junction in path.parents:
            raise AssertionError("outside-root descendant metadata was accessed")
        return original_is_file(path, *args, **kwargs)

    def guarded_scandir(path):
        directory = Path(path)
        if directory == junction or junction in directory.parents:
            raise AssertionError("outside-root directory was traversed")
        return original_scandir(path)

    monkeypatch.setattr(Path, "is_file", guarded_is_file)
    monkeypatch.setattr(os, "scandir", guarded_scandir)
    output = tmp_path / "package"
    with pytest.raises(PackageError, match="Python runtime.*(reparse|symbolic)"):
        _build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), output, python_runtime=runtime)
    assert not output.exists()


@pytest.mark.parametrize("missing", ("python.exe", "python314._pth", "python314.dll", "python314.zip"))
def test_package_rejects_incomplete_python_runtime(tmp_path: Path, missing: str) -> None:
    runtime = fake_python(tmp_path / "python")
    (runtime / missing).unlink()
    with pytest.raises(PackageError, match="Python runtime"):
        _build_package(
            ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package", python_runtime=runtime,
        )


@pytest.mark.parametrize("damage", ("missing", "corrupt", "unlisted", "extra"))
def test_python_runtime_inventory_is_required_and_hash_bound(tmp_path: Path, damage: str) -> None:
    package = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package")
    manifest_path = package / "install-manifest.json"
    relative = "tools/slk/runtime/python/python.exe"
    target = package / relative
    if damage == "missing":
        target.unlink()
    elif damage == "corrupt":
        target.write_bytes(b"changed runtime")
    elif damage == "unlisted":
        target.unlink()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"] = [entry for entry in manifest["files"] if entry["path"] != relative]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    else:
        (target.parent / "unexpected.dll").write_bytes(b"unlisted program")
    with pytest.raises(VerificationError):
        verify(package, package_mode=True)


def test_active_install_does_not_export_historical_auxiliary_instructions():
    from scripts.build_local_package import ROOT_DOCUMENTS, DOCUMENT_TREES
    assert "CHANGELOG.md" not in ROOT_DOCUMENTS
    assert "MIGRATION.md" not in ROOT_DOCUMENTS
    assert "docs/maintenance" not in DOCUMENT_TREES
    # Source audit/history stay immutable and available in Git, not current instructions.
    assert (ROOT / "CHANGELOG.md").is_file()
    assert (ROOT / "docs/maintenance/2026-09-28-slk-4.3.1-consistency-audit.md").is_file()


def fake_artifacts(root: Path) -> Path:
    """Simulated artifacts exercise packaging only, not executable/runtime readiness."""
    root.mkdir()
    for name in ARTIFACT_NAMES:
        (root / name).write_bytes(f"fake-{name}-4.4.5\n".encode())
    return root


@pytest.mark.parametrize("change", ("missing", "extra"))
def test_source_manifest_requires_exact_release_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    original_read_text = Path.read_text

    def altered_manifest(path: Path, *args, **kwargs) -> str:
        text = original_read_text(path, *args, **kwargs)
        if path == ROOT / "MANIFEST.json":
            manifest = json.loads(text)
            if change == "missing":
                omitted = "tests/install/test_bi_release.py"
                assert any(entry["path"] == omitted for entry in manifest["files"])
                manifest["files"] = [entry for entry in manifest["files"] if entry["path"] != omitted]
            else:
                manifest["files"].append({"path": "MANIFEST.json", "sha256": sha256(path)})
            return json.dumps(manifest)
        return text

    monkeypatch.setattr(Path, "read_text", altered_manifest)

    with pytest.raises(PackageError, match="repository manifest inventory mismatch"):
        build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package")


@pytest.mark.parametrize("unsafe", (
    "C:/outside.txt", "C:relative", "/outside.txt", "../outside.txt",
    "safe/../../outside.txt", "..\\outside.txt", "\\\\server\\share\\outside.txt",
))
def test_source_manifest_rejects_unsafe_paths_before_inventory_or_target_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unsafe: str,
) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    (repository / "MANIFEST.json").write_text(json.dumps({
        "version": package_builder.VERSION,
        "skill_count": len(EXPECTED_SKILLS),
        "files": [
            {"path": "safe.txt", "sha256": "0" * 64},
            {"path": unsafe, "sha256": "0" * 64},
        ],
    }), encoding="utf-8")

    def forbidden_inventory(root: Path) -> list[Path]:
        raise AssertionError("inventory target IO attempted before unsafe path rejection")

    def forbidden_is_file(path: Path, *args, **kwargs) -> bool:
        raise AssertionError(f"manifest target IO attempted before unsafe path rejection: {path}")

    monkeypatch.setattr(package_builder, "release_files", forbidden_inventory)
    monkeypatch.setattr(Path, "is_file", forbidden_is_file)

    with pytest.raises(PackageError, match="manifest path"):
        package_builder._load_repository_manifest(repository)


def test_package_delivers_only_authoritative_install_verification_scripts(tmp_path: Path) -> None:
    package = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package")
    manifest = json.loads((package / "install-manifest.json").read_text(encoding="utf-8"))
    scripts = {
        "install_local.ps1",
        "verify_local_install.py",
        "local_package_metadata.py",
        "configure_ocrv.py",
    }
    paths = {entry["path"] for entry in manifest["files"]}
    assert {path for path in paths if path.startswith("tools/slk/scripts/")} == {
        f"tools/slk/scripts/{name}" for name in scripts
    }
    for name in scripts:
        assert (package / "tools/slk/scripts" / name).read_bytes() == (ROOT / "scripts" / name).read_bytes()


def test_runtime_metadata_keeps_repository_managed_skill_identity() -> None:
    from scripts.local_package_metadata import EXPECTED_SKILLS as RUNTIME_SKILLS, read_version

    assert RUNTIME_SKILLS == EXPECTED_SKILLS
    assert read_version() == (ROOT / "VERSION").read_text(encoding="utf-8").strip()


@pytest.mark.parametrize("value", ("C:/outside.txt", "C:relative"))
def test_manifest_rejects_windows_drive_paths_before_any_file_access(value: str) -> None:
    with pytest.raises(VerificationError, match="unsafe manifest path"):
        _safe_relative(value)


@pytest.mark.parametrize("relative", (
    "tools/slk/scripts/unexpected.py",
    "tools/slk/bin/unexpected.exe",
    "skills/unexpected/SKILL.md",
))
def test_manifest_cannot_declare_extra_managed_script_artifact_or_skill(tmp_path: Path, relative: str) -> None:
    package = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package")
    target = package / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"unexpected managed file\n")
    manifest_path = package / "install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append({"path": relative, "size": target.stat().st_size, "sha256": sha256(target)})
    manifest["files"].sort(key=lambda entry: entry["path"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(VerificationError, match="set is not exact"):
        verify(package, package_mode=True)


def test_complete_package_has_exact_skills_artifacts_docs_and_hashes(tmp_path: Path) -> None:
    package = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package")
    manifest = json.loads((package / "install-manifest.json").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "slk.install-manifest/v1"
    assert manifest["version"] == package_builder.VERSION
    assert manifest["skill_count"] == len(EXPECTED_SKILLS)
    assert manifest["artifact_count"] == 5
    paths = {entry["path"] for entry in manifest["files"]}
    assert {f"skills/{name}/SKILL.md" for name in EXPECTED_SKILLS} <= paths
    assert {f"tools/slk/bin/{name}" for name in ARTIFACT_NAMES} <= paths
    assert "tools/slk/bin/slk-transport.cmd" in paths
    launcher = (package / "tools/slk/bin/slk-transport.cmd").read_text(encoding="utf-8")
    assert '"%~dp0..\\runtime\\python\\python.exe" "%~dp0slk-transport.pyz" %*' in launcher
    assert "if not exist" in launcher.lower()
    assert "tools/slk/runtime/python/python.exe" in paths
    python_path = (package / "tools/slk/runtime/python/python314._pth").read_text(encoding="utf-8")
    assert "../../scripts\n" in python_path
    assert "../../bin/slk-transport.pyz\n" in python_path
    assert "Lib/site-packages\n" in python_path
    assert "import site" not in python_path
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
        "tools/slk/share/small-loop-skill/docs/contracts/slk-checker-management.schema.json",
        "tools/slk/share/small-loop-skill/docs/contracts/slk-d1-management-return.schema.json",
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
