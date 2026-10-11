from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from scripts import build_local_package, validate_repository


@pytest.fixture(params=["filesystem", "git-untracked", "git-tracked"])
def checkout(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[Path, str]:
    root = tmp_path / "checkout"
    root.mkdir()
    if request.param != "filesystem":
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    else:
        assert subprocess.run(
            ["git", "ls-files"], cwd=root, capture_output=True, check=False
        ).returncode != 0
    (root / "src").mkdir()
    (root / "src/real_source.py").write_text("VALUE = 1\n", encoding="utf-8")
    # Only metadata directories are excluded, not similarly named real files.
    (root / "release.egg-info").write_text("real file\n", encoding="utf-8")
    return root, request.param


def add_editable_metadata(root: Path, mode: str) -> None:
    for relative in ("src/slk_transport.egg-info", "integrations/tool/src/helper.egg-info"):
        directory = root / relative
        directory.mkdir(parents=True)
        for name in (
            "PKG-INFO", "SOURCES.txt", "dependency_links.txt", "entry_points.txt",
            "requires.txt", "top_level.txt",
        ):
            (directory / name).write_text("generated metadata\n", encoding="utf-8")
    if mode == "git-tracked":
        subprocess.run(["git", "add", "."], cwd=root, check=True)


def test_release_inventory_and_generator_ignore_editable_metadata(checkout) -> None:
    root, mode = checkout
    baseline = validate_repository.manifest_payload(root)
    add_editable_metadata(root, mode)

    assert {path.as_posix() for path in validate_repository.release_files(root)} == {
        "release.egg-info", "src/real_source.py",
    }
    assert validate_repository.manifest_payload(root) == baseline


def test_metadata_does_not_hide_real_source_hash_or_inventory_changes(checkout) -> None:
    root, mode = checkout
    validate_repository.write_manifest(root)
    add_editable_metadata(root, mode)

    listed = build_local_package._load_repository_manifest(root)
    source = root / "src/real_source.py"
    assert listed[source.relative_to(root).as_posix()] == hashlib.sha256(source.read_bytes()).hexdigest()

    (root / "src/new_source.py").write_text("NEW = True\n", encoding="utf-8")
    with pytest.raises(build_local_package.PackageError, match="inventory mismatch.*src/new_source.py"):
        build_local_package._load_repository_manifest(root)

    validate_repository.write_manifest(root)
    source.write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(build_local_package.PackageError, match="hash mismatch: src/real_source.py"):
        build_local_package._load_repository_manifest(root)
