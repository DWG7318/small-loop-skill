#!/usr/bin/env python3
"""Build one deterministic, hash-bound local SLK installation package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
from pathlib import Path

try:
    from .local_package_metadata import (
        ARTIFACT_NAMES, EXPECTED_SKILLS, INSTALL_SCRIPT_NAMES, LAUNCHER_NAMES,
        MANIFEST_SCHEMA, PYTHON_RUNTIME_PATH, RUNTIME_REQUIRED_FILES, python_path_contents, read_version,
    )
    from .validate_repository import release_files
    from .verify_bi_release import BiReleaseError, verify_bi_release
    from .tool_artifacts import ArtifactError, RELEASE_PROVENANCE, verify_release_build
    from .verify_local_install import VerificationError, _plain_metadata, _python_runtime_layout, _safe_relative
except ImportError:  # direct script execution
    from local_package_metadata import (
        ARTIFACT_NAMES, EXPECTED_SKILLS, INSTALL_SCRIPT_NAMES, LAUNCHER_NAMES,
        MANIFEST_SCHEMA, PYTHON_RUNTIME_PATH, RUNTIME_REQUIRED_FILES, python_path_contents, read_version,
    )
    from validate_repository import release_files
    from verify_bi_release import BiReleaseError, verify_bi_release
    from tool_artifacts import ArtifactError, RELEASE_PROVENANCE, verify_release_build
    from verify_local_install import VerificationError, _plain_metadata, _python_runtime_layout, _safe_relative


VERSION = read_version()
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


def _document_files(root: Path) -> list[Path]:
    """Deliver runtime guidance/source only, not a second developer artifact tree."""
    files: list[Path] = []
    excluded = {"artifacts", "upstream", "tests", "build", "dist", "target", "node_modules",
                "__pycache__", ".git", ".codex", ".pytest_cache", ".venv"}
    for directory, children, names in os.walk(root):
        children[:] = [name for name in children if name not in excluded and not name.endswith(".egg-info")]
        files.extend(Path(directory) / name for name in names if Path(name).suffix not in {".pyc", ".pyo"})
    return sorted(files, key=lambda path: path.as_posix())


def _runtime_files(root: Path, label: str = "Python") -> list[Path]:
    files: list[Path] = []
    pending = [root]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode) or (
                    getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise PackageError(f"{label} runtime contains a reparse point or symbolic link: {entry.path}")
                path = Path(entry.path)
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(metadata.st_mode) and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
                    files.append(path)
    return sorted(files, key=lambda path: path.as_posix())


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
        try:
            _safe_relative(relative)
        except VerificationError as exc:
            raise PackageError(str(exc)) from exc
        result[relative] = digest
    actual = {relative.as_posix() for relative in release_files(repository)}
    if set(result) != actual:
        raise PackageError(
            f"repository manifest inventory mismatch: missing={sorted(actual - set(result))}; "
            f"extra={sorted(set(result) - actual)}"
        )
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
        files = _document_files(source_root)
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


def build_package(
    repository: Path | str, artifacts: Path | str, output: Path | str,
    *, python_runtime: Path | str | None = None,
    node_runtime: Path | str | None = None, dsh_runtime: Path | str | None = None,
    ocrv_runtime: Path | str | None = None, temporal_runtime: Path | str | None = None,
    git_runtime: Path | str | None = None, native_probe_runtime: Path | str | None = None,
) -> Path:
    repo = Path(repository).resolve()
    artifact_root = Path(artifacts).resolve()
    destination = Path(output).resolve()
    if not repo.is_dir() or not artifact_root.is_dir():
        raise PackageError("repository and artifact roots must be existing directories")
    if destination == repo or repo in destination.parents or destination == artifact_root:
        raise PackageError("output directory must be separate from repository and artifacts")
    if destination.exists() and any(destination.iterdir()):
        raise PackageError("output directory must be absent or empty")
    if python_runtime is None:
        raise PackageError("Python runtime is required; supply a prepared embedded runtime directory")
    runtime = Path(python_runtime).resolve()
    if not runtime.is_dir():
        raise PackageError("Python runtime must be an existing prepared directory")
    if destination == runtime or runtime in destination.parents:
        raise PackageError("output directory must be separate from the Python runtime")
    runtime_files = _runtime_files(runtime)
    try:
        configuration = _python_runtime_layout({path.relative_to(runtime).as_posix() for path in runtime_files})
    except VerificationError as exc:
        raise PackageError(str(exc)) from exc

    products: list[tuple[Path, Path]] = []
    for name, prepared in (("node", node_runtime), ("dsh", dsh_runtime),
                           ("ocrv", ocrv_runtime), ("temporal", temporal_runtime), ("git", git_runtime),
                           ("native-probe", native_probe_runtime)):
        label = {"node": "Node", "dsh": "DSH", "ocrv": "OCRV", "temporal": "Temporal", "git": "Git",
                 "native-probe": "Native probe"}[name]
        if prepared is None:
            raise PackageError(f"{label} runtime is required; supply a prepared offline directory")
        product = Path(prepared).resolve()
        if not product.is_dir():
            raise PackageError(f"{label} runtime must be an existing prepared directory")
        if destination == product or product in destination.parents:
            raise PackageError(f"output directory must be separate from the {label} runtime")
        if name == "dsh":
            # Select only the locked production product, not a runtime's homes,
            # Sessions or config. Unused upstream source files need no new gate.
            files = []
            for relative in ("node_modules", "package.json", "package-lock.json", "LICENSE", "NOTICE"):
                path = product / relative
                try:
                    metadata = path.lstat()
                except FileNotFoundError:
                    continue
                if stat.S_ISLNK(metadata.st_mode) or (
                    getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise PackageError(f"DSH runtime contains a reparse point or symbolic link: {path}")
                if stat.S_ISDIR(metadata.st_mode):
                    files.extend(_runtime_files(path, label))
                elif stat.S_ISREG(metadata.st_mode):
                    files.append(path)
        elif name == "git":
            # MinGit is one complete official distribution, including DLLs,
            # helpers and upstream notices; a lone git.exe is not a runtime.
            files = _runtime_files(product, label)
        else:
            # Only the native executable and notices are delivered. Unselected
            # developer subtrees are not dependencies and need no traversal.
            files = []
            checked: set[Path] = set()
            for relative in sorted(RUNTIME_REQUIRED_FILES[name]):
                try:
                    metadata = _plain_metadata(product, Path(relative), checked)
                except VerificationError as exc:
                    raise PackageError(f"{label} runtime is incomplete: {exc}") from exc
                if not stat.S_ISREG(metadata.st_mode):
                    raise PackageError(f"{label} runtime requires a regular file: {relative}")
                files.append(product / relative)
        names = {path.relative_to(product).as_posix() for path in files}
        required = RUNTIME_REQUIRED_FILES[name]
        if not required <= names:
            raise PackageError(f"{label} runtime is incomplete: missing={sorted(required - names)}")
        products.extend((source, Path("tools/slk/runtime") / name / source.relative_to(product))
                        for source in files)

    actual_artifacts = {path.name for path in artifact_root.iterdir() if path.is_file()}
    if (actual_artifacts - {RELEASE_PROVENANCE} != set(ARTIFACT_NAMES)
        or any(path.is_dir() for path in artifact_root.iterdir())):
        raise PackageError("artifact set must contain exactly the five managed files and build provenance")
    try:
        verify_bi_release(artifact_root / "slk-bi-desktop.exe", require_pe=False)
    except BiReleaseError as exc:
        raise PackageError(str(exc)) from exc
    try:
        provenance = verify_release_build(repo, artifact_root)
    except ArtifactError as exc:
        raise PackageError(str(exc)) from exc
    listed = _load_repository_manifest(repo)
    mappings = _repository_sources(repo, listed)
    mappings.extend((artifact_root / name, Path("tools/slk/bin") / name) for name in ARTIFACT_NAMES)
    mappings.append((artifact_root / RELEASE_PROVENANCE,
                     Path("tools/slk/share/small-loop-skill") / RELEASE_PROVENANCE))
    mappings.extend((source, Path(PYTHON_RUNTIME_PATH) / source.relative_to(runtime)) for source in runtime_files)
    mappings.extend(products)
    for integration, names in {
        "dsh": ("dsh-slk.ps1", "dsh-slk.cmd", "prepare-worker-mcp.ps1", "slk-native-activity.patch.yml",
                "slk_native_activity.mjs", "slk-worker-capabilities.json"),
        "ocrv": ("slk_checker_adapter.py", "slk_checker_decision.py", "slk-checker.cmd",
                 "slk_checker_post_d1.py", "slk_checker_recovery.py", "slk-checker-capabilities.json",
                 "slk-native-activity-capabilities.json", "OCRV-SLK-CONFIGURATION.md"),
    }.items():
        for name in names:
            source = repo / "integrations" / integration / name
            if listed.get(source.relative_to(repo).as_posix()) != sha256(source):
                raise PackageError(f"integration is not the current repository manifest entry: {name}")
            mappings.append((source, Path("tools/slk/runtime") / integration / name))
    for name in LAUNCHER_NAMES:
        source = repository / "scripts" / name
        relative = source.relative_to(repository).as_posix()
        if listed.get(relative) != sha256(source):
            raise PackageError(f"launcher is not the current repository manifest entry: {relative}")
        mappings.append((source, Path("tools/slk/bin") / name))
    for name in INSTALL_SCRIPT_NAMES:
        source = repo / "scripts" / name
        relative = source.relative_to(repo).as_posix()
        if listed.get(relative) != sha256(source):
            raise PackageError(f"install script is not the current repository manifest entry: {relative}")
        mappings.append((source, Path("tools/slk/scripts") / name))

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
        try:
            if verify_release_build(repo, artifact_root) != provenance:
                raise ArtifactError("release provenance changed during packaging")
            for item in provenance["payload"]:
                copied = destination / "tools/slk/bin" / item["path"]
                if copied.stat().st_size != item["size"] or sha256(copied) != item["sha256"]:
                    raise ArtifactError("copied release payload changed from sealed build")
        except ArtifactError as exc:
            raise PackageError(str(exc)) from exc
        (destination / PYTHON_RUNTIME_PATH / configuration).write_text(
            python_path_contents(configuration.removesuffix("._pth") + ".zip"),
            encoding="utf-8", newline="\n",
        )
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
    parser.add_argument("--python-runtime", required=True, type=Path, help="prepared offline Windows Python embed directory")
    for name in RUNTIME_REQUIRED_FILES:
        parser.add_argument(f"--{name}-runtime", required=True, type=Path, help=f"prepared offline {name} directory")
    args = parser.parse_args()
    try:
        package = build_package(args.repo, args.artifacts, args.output, python_runtime=args.python_runtime,
                                **{name.replace("-", "_") + "_runtime": getattr(args, name.replace("-", "_") + "_runtime")
                                   for name in RUNTIME_REQUIRED_FILES})
    except PackageError as exc:
        print(f"FAIL SLK_LOCAL_PACKAGE: {exc}")
        return 2
    print(package)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
