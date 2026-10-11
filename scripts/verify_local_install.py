#!/usr/bin/env python3
"""Verify an SLK package or installed Codex-home tree from its closed manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

# Verification is read-only, including inside the exact managed script surface.
sys.dont_write_bytecode = True
# The Windows embed intentionally does not add a script's directory to sys.path.
# Resolve metadata beside this verifier, including for a trusted source invocation.
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    if __package__:
        from .local_package_metadata import (
            ARTIFACT_NAMES, EXPECTED_SKILLS, INSTALL_SCRIPT_NAMES, LAUNCHER_NAMES,
            MANIFEST_SCHEMA, PYTHON_RUNTIME_PATH, RUNTIME_PATHS, RUNTIME_REQUIRED_FILES, python_path_contents, read_version,
        )
    else:  # direct script execution
        from local_package_metadata import (
            ARTIFACT_NAMES, EXPECTED_SKILLS, INSTALL_SCRIPT_NAMES, LAUNCHER_NAMES,
            MANIFEST_SCHEMA, PYTHON_RUNTIME_PATH, RUNTIME_PATHS, RUNTIME_REQUIRED_FILES, python_path_contents, read_version,
        )
except ImportError as exc:
    if __name__ != "__main__":
        raise
    print(f"FAIL SLK_LOCAL_INSTALL: package metadata is unavailable: {exc}")
    raise SystemExit(2) from None


class VerificationError(RuntimeError):
    """Raised when any managed install byte or identity is inconsistent."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise VerificationError("manifest path must be a non-empty POSIX relative path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or PureWindowsPath(value).anchor or any(part in {"", ".", ".."} for part in pure.parts):
        raise VerificationError(f"unsafe manifest path: {value!r}")
    return Path(*pure.parts)


def load_manifest(path: Path) -> dict:
    try:
        version = read_version()
    except (OSError, UnicodeDecodeError) as exc:
        raise VerificationError("verifier VERSION is unavailable or invalid") from exc
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError("install manifest is unavailable or invalid") from exc
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "version", "skill_count", "artifact_count", "files"
    }:
        raise VerificationError("install manifest must use the exact field set")
    if value["schema_version"] != MANIFEST_SCHEMA or value["version"] != version:
        raise VerificationError("install manifest identity mismatch")
    if value["skill_count"] != len(EXPECTED_SKILLS) or value["artifact_count"] != len(ARTIFACT_NAMES):
        raise VerificationError("install manifest counts mismatch")
    if not isinstance(value["files"], list) or not value["files"]:
        raise VerificationError("install manifest files must be a non-empty array")
    return value


def _python_runtime_layout(names: set[str]) -> str:
    configurations = sorted(
        name for name in names
        if "/" not in name and name.startswith("python") and name.endswith("._pth")
    )
    if len(configurations) != 1:
        raise VerificationError("Python runtime requires one embedded python*._pth configuration")
    configuration = configurations[0]
    stem = configuration.removesuffix("._pth")
    required = {"python.exe", f"{stem}.dll", f"{stem}.zip", configuration}
    if not required <= names:
        raise VerificationError(f"Python runtime is incomplete: missing={sorted(required - names)}")
    return configuration


def _plain_metadata(base: Path, relative: Path, checked: set[Path]):
    target = base
    metadata = None
    for part in relative.parts:
        target /= part
        if target in checked:
            continue
        try:
            metadata = target.lstat()
        except OSError as exc:
            raise VerificationError(f"managed file is missing: {relative.as_posix()}") from exc
        if stat.S_ISLNK(metadata.st_mode) or (
            getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise VerificationError(f"managed path contains a reparse point or symbolic link: {target}")
        if stat.S_ISDIR(metadata.st_mode):
            checked.add(target)
    return metadata


def _inventory(base: Path, directory: Path) -> set[str]:
    actual = set()
    pending = [directory]
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                metadata = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(metadata.st_mode) or (
                    getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise VerificationError(f"managed path contains a reparse point or symbolic link: {entry.path}")
                if stat.S_ISDIR(metadata.st_mode):
                    pending.append(Path(entry.path))
                elif stat.S_ISREG(metadata.st_mode):
                    actual.add(Path(entry.path).relative_to(base).as_posix())
    return actual


def verify(root: Path | str, *, package_mode: bool = False) -> dict[str, object]:
    base = Path(root).resolve()
    manifest_path = base / "install-manifest.json" if package_mode else base / "tools/slk/install-manifest.json"
    manifest = load_manifest(manifest_path)
    listed: dict[str, tuple[str, int]] = {}
    checked: set[Path] = set()
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256", "size"}:
            raise VerificationError("install manifest file entry must be closed")
        relative = _safe_relative(entry["path"])
        key = relative.as_posix()
        digest, size = entry["sha256"], entry["size"]
        if key in listed or not isinstance(digest, str) or len(digest) != 64:
            raise VerificationError("duplicate or malformed manifest file entry")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise VerificationError("manifest size must be a non-negative integer")
        target = base / relative
        metadata = _plain_metadata(base, relative, checked)
        if metadata is None or not stat.S_ISREG(metadata.st_mode):
            raise VerificationError(f"managed file is missing or not regular: {key}")
        if metadata.st_size != size or sha256(target) != digest:
            raise VerificationError(f"managed file hash mismatch: {key}")
        listed[key] = (digest, size)

    if [entry["path"] for entry in manifest["files"]] != sorted(listed):
        raise VerificationError("install manifest file order is not canonical")
    artifact_paths = {
        f"tools/slk/bin/{name}" for name in (*ARTIFACT_NAMES, *LAUNCHER_NAMES)
    }
    if {path for path in listed if path.startswith("tools/slk/bin/")} != artifact_paths:
        raise VerificationError("installed artifact set is not exact")
    script_paths = {f"tools/slk/scripts/{name}" for name in INSTALL_SCRIPT_NAMES}
    if {path for path in listed if path.startswith("tools/slk/scripts/")} != script_paths:
        raise VerificationError("installed install-script set is not exact")
    runtime_prefix = PYTHON_RUNTIME_PATH + "/"
    runtime_names = {path.removeprefix(runtime_prefix) for path in listed if path.startswith(runtime_prefix)}
    configuration = _python_runtime_layout(runtime_names)
    expected_path = python_path_contents(configuration.removesuffix("._pth") + ".zip")
    if (base / PYTHON_RUNTIME_PATH / configuration).read_text(encoding="utf-8") != expected_path:
        raise VerificationError("Python runtime import paths are not isolated and package-relative")
    for name, required in RUNTIME_REQUIRED_FILES.items():
        prefix = f"tools/slk/runtime/{name}/"
        names = {path.removeprefix(prefix) for path in listed if path.startswith(prefix)}
        if not required <= names:
            raise VerificationError(f"{name} runtime is incomplete: missing={sorted(required - names)}")
    runtime_roots = {path.split("/", 4)[3] for path in listed if path.startswith("tools/slk/runtime/")}
    if runtime_roots != {"python", *RUNTIME_REQUIRED_FILES}:
        raise VerificationError("installed runtime set is not exact")
    for name in EXPECTED_SKILLS:
        prefix = f"skills/{name}/"
        if f"{prefix}SKILL.md" not in listed:
            raise VerificationError(f"managed Skill is missing: {name}")
    if {path.split("/", 2)[1] for path in listed if path.startswith("skills/")} != set(EXPECTED_SKILLS):
        raise VerificationError("installed Skill set is not exact")
    if not any(path.startswith("docs/state/") for path in listed):
        raise VerificationError("installed Skill-linked docs are missing")

    if package_mode:
        actual = _inventory(base, base) - {manifest_path.relative_to(base).as_posix()}
        if actual != set(listed):
            raise VerificationError("package has missing or extra files")
    else:
        for prefix in [
            *(f"skills/{name}" for name in EXPECTED_SKILLS), "tools/slk/bin",
            "tools/slk/scripts", "tools/slk/share/small-loop-skill", *RUNTIME_PATHS,
        ]:
            directory = base / Path(prefix)
            actual = _inventory(base, directory)
            expected = {path for path in listed if path.startswith(prefix + "/")}
            if actual != expected:
                raise VerificationError(f"installed managed surface has missing or extra files: {prefix}")

    version_path = base / "tools/slk/share/small-loop-skill/VERSION"
    if version_path.read_text(encoding="utf-8").strip() != manifest["version"]:
        raise VerificationError("installed VERSION mismatch")
    return {"status": "PASS", "version": manifest["version"], "file_count": len(listed)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--package-mode", action="store_true")
    args = parser.parse_args()
    try:
        result = verify(args.root, package_mode=args.package_mode)
    except VerificationError as exc:
        print(f"FAIL SLK_LOCAL_INSTALL: {exc}")
        return 2
    print(f"PASS SLK_LOCAL_INSTALL {result['version']} files={result['file_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
