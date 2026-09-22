#!/usr/bin/env python3
"""Verify an SLK package or installed Codex-home tree from its closed manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

try:
    from .build_local_package import ARTIFACT_NAMES, MANIFEST_SCHEMA
    from .validate_repository import EXPECTED_SKILLS, VERSION
except ImportError:  # direct script execution
    from build_local_package import ARTIFACT_NAMES, MANIFEST_SCHEMA
    from validate_repository import EXPECTED_SKILLS, VERSION


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
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise VerificationError(f"unsafe manifest path: {value!r}")
    return Path(*pure.parts)


def load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError("install manifest is unavailable or invalid") from exc
    if not isinstance(value, dict) or set(value) != {
        "schema_version", "version", "skill_count", "artifact_count", "files"
    }:
        raise VerificationError("install manifest must use the exact field set")
    if value["schema_version"] != MANIFEST_SCHEMA or value["version"] != VERSION:
        raise VerificationError("install manifest identity mismatch")
    if value["skill_count"] != len(EXPECTED_SKILLS) or value["artifact_count"] != len(ARTIFACT_NAMES):
        raise VerificationError("install manifest counts mismatch")
    if not isinstance(value["files"], list) or not value["files"]:
        raise VerificationError("install manifest files must be a non-empty array")
    return value


def verify(root: Path | str, *, package_mode: bool = False) -> dict[str, object]:
    base = Path(root).resolve()
    manifest_path = base / "install-manifest.json" if package_mode else base / "tools/slk/install-manifest.json"
    manifest = load_manifest(manifest_path)
    listed: dict[str, tuple[str, int]] = {}
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
        if target.is_symlink() or not target.is_file():
            raise VerificationError(f"managed file is missing or not regular: {key}")
        if target.stat().st_size != size or sha256(target) != digest:
            raise VerificationError(f"managed file hash mismatch: {key}")
        listed[key] = (digest, size)

    if [entry["path"] for entry in manifest["files"]] != sorted(listed):
        raise VerificationError("install manifest file order is not canonical")
    artifact_paths = {f"tools/slk/bin/{name}" for name in ARTIFACT_NAMES}
    if {path for path in listed if path.startswith("tools/slk/bin/")} != artifact_paths:
        raise VerificationError("installed artifact set is not exact")
    for name in EXPECTED_SKILLS:
        prefix = f"skills/{name}/"
        if f"{prefix}SKILL.md" not in listed:
            raise VerificationError(f"managed Skill is missing: {name}")
    if {path.split("/", 2)[1] for path in listed if path.startswith("skills/")} != set(EXPECTED_SKILLS):
        raise VerificationError("installed Skill set is not exact")

    if package_mode:
        actual = {
            path.relative_to(base).as_posix()
            for path in base.rglob("*")
            if path.is_file() and path != manifest_path
        }
        if actual != set(listed):
            raise VerificationError("package has missing or extra files")
    else:
        for prefix in [*(f"skills/{name}" for name in EXPECTED_SKILLS), "tools/slk/bin", "tools/slk/share/small-loop-skill"]:
            directory = base / Path(prefix)
            actual = {path.relative_to(base).as_posix() for path in directory.rglob("*") if path.is_file()}
            expected = {path for path in listed if path.startswith(prefix + "/")}
            if actual != expected:
                raise VerificationError(f"installed managed surface has missing or extra files: {prefix}")

    version_path = base / "tools/slk/share/small-loop-skill/VERSION"
    if version_path.read_text(encoding="utf-8").strip() != VERSION:
        raise VerificationError("installed VERSION mismatch")
    return {"status": "PASS", "version": VERSION, "file_count": len(listed)}


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
