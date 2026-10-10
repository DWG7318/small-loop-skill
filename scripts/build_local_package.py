#!/usr/bin/env python3
"""Build one deterministic, hash-bound local SLK installation package."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

try:
    from .validate_repository import EXPECTED_SKILLS, VERSION
    from .verify_bi_release import BiReleaseError, verify_bi_release
except ImportError:  # direct script execution
    from validate_repository import EXPECTED_SKILLS, VERSION
    from verify_bi_release import BiReleaseError, verify_bi_release


ARTIFACT_NAMES = (
    "slk-bi-desktop.exe",
    "slk-bi-query.exe",
    "slk-cargo.exe",
    "slk-state.exe",
    "slk-transport.pyz",
)
LAUNCHER_NAMES = ("slk-transport.cmd",)
ROOT_DOCUMENTS = (
    "VERSION",
    "README.md",
    "README.zh-CN.md",
    "LICENSE",
    "MANIFEST.json",
    "VALIDATION-REPORT.md",
)
DOCUMENT_TREES = (
    "docs/state",
    "docs/transport",
    "docs/runtime",
    "docs/contracts",
    "integrations/dsh",
    "integrations/ocrv",
    "integrations/temporal",
)
SQLITE_SCHEMA_ROOT = "crates/slk-state-core/migrations"
MANIFEST_SCHEMA = "slk.install-manifest/v1"


class PackageError(RuntimeError):
    """Raised before an incomplete or ambiguous package can be emitted."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files(root: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        ),
        key=lambda p: p.as_posix(),
    )


def _copy(source: Path, destination: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise PackageError(f"managed source is not a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _load_repository_manifest(repository: Path) -> dict[str, str]:
    path = repository / "MANIFEST.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackageError("repository MANIFEST.json is unavailable or invalid") from exc
    if value.get("version") != VERSION or value.get("skill_count") != len(EXPECTED_SKILLS):
        raise PackageError("repository manifest identity does not match this builder")
    entries = value.get("files")
    if not isinstance(entries, list):
        raise PackageError("repository manifest files must be an array")
    result: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise PackageError("repository manifest entry is not closed")
        relative, digest = entry["path"], entry["sha256"]
        if not isinstance(relative, str) or not isinstance(digest, str) or relative in result:
            raise PackageError("repository manifest entry is invalid or duplicate")
        result[relative] = digest
    for relative, digest in result.items():
        source = repository / Path(relative)
        if not source.is_file() or sha256(source) != digest:
            raise PackageError(f"repository manifest hash mismatch: {relative}")
    return result


def _repository_sources(repository: Path, listed: dict[str, str]) -> list[tuple[Path, Path]]:
    skills_root = repository / "skills"
    actual_skills = {path.name for path in skills_root.iterdir() if path.is_dir()}
    if actual_skills != set(EXPECTED_SKILLS):
        raise PackageError(f"repository skill set does not match the {len(EXPECTED_SKILLS)} managed Skills")

    mappings: list[tuple[Path, Path]] = []
    for name in EXPECTED_SKILLS:
        source_root = skills_root / name
        skill_files = _files(source_root)
        if not skill_files or not (source_root / "SKILL.md").is_file():
            raise PackageError(f"managed Skill is incomplete: {name}")
        for source in skill_files:
            relative = source.relative_to(repository).as_posix()
            if listed.get(relative) != sha256(source):
                raise PackageError(f"Skill file is not the current repository manifest entry: {relative}")
            mappings.append((source, Path("skills") / source.relative_to(skills_root)))

    share = Path("tools/slk/share/small-loop-skill")
    for relative in ROOT_DOCUMENTS:
        source = repository / relative
        if relative != "MANIFEST.json" and listed.get(relative) != sha256(source):
            raise PackageError(f"document is not the current repository manifest entry: {relative}")
        if relative == "MANIFEST.json" and not source.is_file():
            raise PackageError("repository MANIFEST.json is missing")
        mappings.append((source, share / relative))

    for tree in DOCUMENT_TREES:
        source_root = repository / tree
        files = _files(source_root)
        if not files:
            raise PackageError(f"required document tree is empty: {tree}")
        for source in files:
            relative = source.relative_to(repository).as_posix()
            if listed.get(relative) != sha256(source):
                raise PackageError(f"document is not the current repository manifest entry: {relative}")
            mappings.append((source, share / source.relative_to(repository)))
            if tree.startswith("docs/"):
                # Installed Skills resolve ../../docs against CodexHome, not the share mirror.
                mappings.append((source, source.relative_to(repository)))

    migrations = _files(repository / SQLITE_SCHEMA_ROOT)
    if [path.name for path in migrations] != [f"{index:04}.sql" for index in range(1, 10)]:
        raise PackageError("SQLite schema identity must contain migrations 0001.sql through 0009.sql")
    for source in migrations:
        relative = source.relative_to(repository).as_posix()
        if listed.get(relative) != sha256(source):
            raise PackageError(f"migration is not the current repository manifest entry: {relative}")
        mappings.append((source, share / "schema/sqlite" / source.name))
    return mappings


def build_package(repository: Path | str, artifacts: Path | str, output: Path | str) -> Path:
    repo = Path(repository).resolve()
    artifact_root = Path(artifacts).resolve()
    destination = Path(output).resolve()
    if not repo.is_dir() or not artifact_root.is_dir():
        raise PackageError("repository and artifact roots must be existing directories")
    if destination == repo or repo in destination.parents or destination == artifact_root:
        raise PackageError("output directory must be separate from repository and artifacts")
    if destination.exists() and any(destination.iterdir()):
        raise PackageError("output directory must be absent or empty")

    actual_artifacts = {path.name for path in artifact_root.iterdir() if path.is_file()}
    if actual_artifacts != set(ARTIFACT_NAMES) or any(path.is_dir() for path in artifact_root.iterdir()):
        raise PackageError("artifact set must contain exactly the five managed files")
    try:
        verify_bi_release(artifact_root / "slk-bi-desktop.exe", require_pe=False)
    except BiReleaseError as exc:
        raise PackageError(str(exc)) from exc
    listed = _load_repository_manifest(repo)
    mappings = _repository_sources(repo, listed)
    mappings.extend((artifact_root / name, Path("tools/slk/bin") / name) for name in ARTIFACT_NAMES)
    for name in LAUNCHER_NAMES:
        source = repository / "scripts" / name
        relative = source.relative_to(repository).as_posix()
        if listed.get(relative) != sha256(source):
            raise PackageError(f"launcher is not the current repository manifest entry: {relative}")
        mappings.append((source, Path("tools/slk/bin") / name))

    seen: set[str] = set()
    for _, relative in mappings:
        normalized = relative.as_posix()
        if normalized in seen:
            raise PackageError(f"duplicate package destination: {normalized}")
        seen.add(normalized)

    destination.mkdir(parents=True, exist_ok=True)
    try:
        for source, relative in mappings:
            _copy(source, destination / relative)
        entries = [
            {
                "path": relative.as_posix(),
                "sha256": sha256(destination / relative),
                "size": (destination / relative).stat().st_size,
            }
            for _, relative in sorted(mappings, key=lambda item: item[1].as_posix())
        ]
        manifest = {
            "schema_version": MANIFEST_SCHEMA,
            "version": VERSION,
            "skill_count": len(EXPECTED_SKILLS),
            "artifact_count": len(ARTIFACT_NAMES),
            "files": entries,
        }
        data = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        (destination / "install-manifest.json").write_bytes(data)
        return destination
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        package = build_package(args.repo, args.artifacts, args.output)
    except PackageError as exc:
        print(f"FAIL SLK_LOCAL_PACKAGE: {exc}")
        return 2
    print(package)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
