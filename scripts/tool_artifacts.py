#!/usr/bin/env python3
"""Archive real tool outputs in their source subtree, or restore verified bytes.

Developer packaging only. Ordinary installation uses the already assembled release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import tempfile
import zipfile

try:
    from .local_package_metadata import ARTIFACT_NAMES
except ImportError:
    from local_package_metadata import ARTIFACT_NAMES


RELEASE_PROVENANCE = "BUILD-PROVENANCE.json"


class ArtifactError(ValueError):
    pass


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def relative_path(value: str) -> Path:
    path = PurePosixPath(value)
    if (not value or "\\" in value or path.is_absolute() or PureWindowsPath(value).anchor
            or any(part in {"..", "."} for part in path.parts) or path.as_posix() != value):
        raise ArtifactError(f"unsafe relative artifact path: {value!r}")
    return Path(*path.parts)


def source_hashes(prefix: Path, *, select=None, filesystem: bool = False) -> dict[str, str]:
    excluded = {
        "artifacts", ".git", ".codex", "target", "node_modules", "dist", "build",
        "__pycache__", ".pytest_cache", ".venv",
    }
    # Use the source inventory, not ignored developer caches or account data.
    # An independently exported prefix can also be built without a Git checkout.
    try:
        listed = None if filesystem else subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "."],
            cwd=prefix, capture_output=True, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except FileNotFoundError:
        listed = None
    result = {}
    if listed is not None and listed.returncode == 0:
        for raw in listed.stdout.split(b"\0"):
            if not raw:
                continue
            relative = relative_path(raw.decode("utf-8"))
            if any(part in excluded or part.endswith(".egg-info") for part in relative.parts):
                continue
            if select is not None and not select(relative):
                continue
            source = prefix / relative
            if select is not None and source.is_symlink():
                raise ArtifactError(f"build input is a symbolic link: {relative}")
            if source.is_file() and not source.is_symlink():
                result[relative.as_posix()] = digest(source)
        return dict(sorted(result.items()))
    for current, directories, files in os.walk(prefix):
        directories[:] = sorted(name for name in directories
                                if name not in excluded and not name.endswith(".egg-info"))
        for name in sorted(files):
            source = Path(current) / name
            if select is not None and not select(source.relative_to(prefix)):
                continue
            if select is not None and source.is_symlink():
                raise ArtifactError(f"build input is a symbolic link: {source.relative_to(prefix)}")
            if source.is_symlink() or source.suffix in {".pyc", ".pyo", ".tmp", ".log"}:
                continue
            result[source.relative_to(prefix).as_posix()] = digest(source)
    return dict(sorted(result.items()))


def _release_input(path: Path) -> bool:
    """Inputs consumed by the five-artifact build, not all release documents."""
    name = path.as_posix()
    if any(part in {"tests", "__tests__", "docs", "benches", "gen"} for part in path.parts):
        return False
    if any(marker in path.name for marker in (".test.", ".spec.")):
        return False
    if name in {"VERSION", "Cargo.toml", "Cargo.lock", "rust-toolchain", "rust-toolchain.toml",
                ".cargo/config", ".cargo/config.toml", "scripts/build_release_artifacts.ps1",
                "scripts/build_transport_zipapp.py", "scripts/tool_artifacts.py",
                "scripts/verify_bi_release.py", "scripts/local_package_metadata.py"}:
        return True
    if name.startswith("crates/"):
        return len(path.parts) > 2 and (path.parts[2] in {"src", "migrations"}
                                      or path.name in {"Cargo.toml", "Cargo.lock", "build.rs"})
    if name.startswith(("src/slk_transport/", "src/slk_overwatch_tools/")):
        return path.suffix == ".py"
    if name.startswith("apps/slk-bi/"):
        relative = path.parts[2:]
        return (relative[0] in {"src", "public", "src-tauri"}
                or (len(relative) == 1 and path.suffix in {".json", ".yaml", ".yml", ".ts", ".js", ".mjs", ".html"}))
    return False


def release_source_hashes(repository: Path) -> dict[str, str]:
    # These builders consume filesystem inputs even when Git ignores them.
    # Bound traversal to their own source roots; never hash unrelated caches.
    sources = {path.name: digest(path) for path in repository.iterdir()
               if path.is_file() and _release_input(Path(path.name))}
    for prefix in ("crates", "apps/slk-bi", "src/slk_transport", "src/slk_overwatch_tools", ".cargo", "scripts"):
        relative_root = Path(prefix)
        selected = source_hashes(repository / relative_root,
            select=lambda path: _release_input(relative_root / path), filesystem=True)
        sources.update({(relative_root / name).as_posix(): value for name, value in selected.items()})
    sources = dict(sorted(sources.items()))
    if not sources or "VERSION" not in sources or "Cargo.toml" not in sources:
        raise ArtifactError("release build inputs are incomplete")
    return sources


def _save_release_index(path: Path, value: dict, *, replace: bool = False) -> Path:
    if path.exists() and not replace:
        raise ArtifactError("release provenance already exists; use a fresh artifact directory")
    temporary = path.with_suffix(".json.tmp")
    created = False
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            created = True
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if created:
            temporary.unlink(missing_ok=True)
    return path


def begin_release_build(repository: Path, artifacts: Path, *, build: dict) -> Path:
    """Capture selected input bytes before invoking any compiler/builder."""
    if not isinstance(build, dict) or not build.get("commands"):
        raise ArtifactError("release build commands must be recorded")
    sources = release_source_hashes(repository)
    artifacts.mkdir(parents=True, exist_ok=True)
    if any(artifacts.iterdir()):
        raise ArtifactError("release artifact directory must be empty before build")
    return _save_release_index(artifacts / RELEASE_PROVENANCE, {
        "schema_version": "slk.release-build-inputs/v1", "source_sha256": sources,
        "product_version": (repository / "VERSION").read_text(encoding="utf-8").strip(),
        "build": {**build, "source_hash_mode": "sha256-raw-selected-build-inputs"},
    })


def _release_index(repository: Path, artifacts: Path, schema: str) -> dict:
    try:
        value = json.loads((artifacts / RELEASE_PROVENANCE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArtifactError("release build provenance is missing or invalid") from exc
    fields = {"schema_version", "source_sha256", "product_version", "build"}
    if schema == "slk.release-artifacts/v1":
        fields.add("payload")
    if (not isinstance(value, dict) or set(value) != fields or value.get("schema_version") != schema
        or not isinstance(value.get("build"), dict) or not value["build"].get("commands")):
        raise ArtifactError("release build provenance is not a sealed build batch")
    if (value["source_sha256"] != release_source_hashes(repository)
        or value["product_version"] != (repository / "VERSION").read_text(encoding="utf-8").strip()):
        raise ArtifactError("release build inputs changed since capture")
    return value


def _release_payload(artifacts: Path) -> list[dict]:
    if {path.name for path in artifacts.iterdir()} != set(ARTIFACT_NAMES) | {RELEASE_PROVENANCE}:
        raise ArtifactError("release artifact set must be the five outputs and provenance")
    result = []
    for name in sorted(ARTIFACT_NAMES):
        path = artifacts / name
        if not path.is_file() or path.is_symlink():
            raise ArtifactError("release payload must be regular files")
        result.append({"path": name, "size": path.stat().st_size, "sha256": digest(path)})
    return result


def seal_release_build(repository: Path, artifacts: Path) -> Path:
    """Confirm unchanged inputs, then bind the exact completed output batch."""
    value = _release_index(repository, artifacts, "slk.release-build-inputs/v1")
    payload = _release_payload(artifacts)
    if value["source_sha256"] != release_source_hashes(repository):
        raise ArtifactError("release build inputs changed while sealing")
    return _save_release_index(artifacts / RELEASE_PROVENANCE,
        {**value, "schema_version": "slk.release-artifacts/v1", "payload": payload}, replace=True)


def verify_release_build(repository: Path, artifacts: Path) -> dict:
    value = _release_index(repository, artifacts, "slk.release-artifacts/v1")
    if value["payload"] != _release_payload(artifacts):
        raise ArtifactError("release payload changed since build sealing")
    return value


def archive_module(prefix: Path, target: str, inputs: dict[str, Path], *, tool: str,
                   product_version: str, part_bytes: int = 64 * 1024 * 1024,
                   build: dict | None = None) -> Path:
    prefix = prefix.resolve()
    relative_path(target)
    payload = {}
    for name, source in inputs.items():
        relative_path(name)
        if source.is_symlink():
            raise ArtifactError(f"compiled payload is not a regular file: {source}")
        source = source.resolve()
        if not source.is_file() or source.is_symlink():
            raise ArtifactError(f"compiled payload is not a regular file: {source}")
        payload[name] = source
    if not payload or part_bytes < 1:
        raise ArtifactError("payload and archive part size must be nonempty/positive")
    destination = prefix / "artifacts" / target
    if destination.exists() and any(destination.iterdir()):
        raise ArtifactError(f"artifact directory must be absent or empty: {destination}")
    sources = source_hashes(prefix)
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="slk-tool-archive-") as temporary:
        archive_path = Path(temporary) / "payload.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, source in sorted(payload.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                info.create_system = 3
                with source.open("rb") as reader, archive.open(info, "w", force_zip64=True) as writer:
                    shutil.copyfileobj(reader, writer)
        parts = []
        split = archive_path.stat().st_size > part_bytes
        with archive_path.open("rb") as stream:
            index = 1
            while data := stream.read(part_bytes):
                name = f"payload.zip.part{index:03}" if split else "payload.zip"
                part = destination / name
                part.write_bytes(data)
                parts.append({"path": name, "size": len(data), "sha256": digest(part)})
                index += 1
        value = {
            "schema_version": "slk.tool-artifacts/v1", "tool": tool,
            "product_version": product_version, "target": target,
            "build": build or {"source_hash_mode": "sha256-raw"},
            "source_sha256": sources,
            "archive": {"sha256": digest(archive_path), "size": archive_path.stat().st_size, "parts": parts},
            "payload": [{"path": name, "size": source.stat().st_size, "sha256": digest(source)}
                        for name, source in sorted(payload.items())],
        }
        (destination / "ARTIFACTS.json").write_text(
            json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n",
        )
    return destination


def restore_module(artifacts: Path, destination: Path) -> Path:
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ArtifactError(f"restore destination must be absent or empty: {destination}")
    value = json.loads((artifacts / "ARTIFACTS.json").read_text(encoding="utf-8"))
    if value.get("schema_version") != "slk.tool-artifacts/v1":
        raise ArtifactError("unsupported tool artifact index")
    expected = {entry["path"]: entry for entry in value["payload"]}
    for name in expected:
        relative_path(name)
    if len(expected) != len(value["payload"]):
        raise ArtifactError("duplicate payload path")
    with tempfile.TemporaryDirectory(prefix="slk-tool-restore-") as temporary:
        archive_path = Path(temporary) / "payload.zip"
        with archive_path.open("xb") as output:
            for entry in value["archive"]["parts"]:
                part = artifacts / relative_path(entry["path"])
                if part.stat().st_size != entry["size"] or digest(part) != entry["sha256"]:
                    raise ArtifactError(f"corrupt archive part: {entry['path']}")
                with part.open("rb") as stream:
                    shutil.copyfileobj(stream, output)
        if (archive_path.stat().st_size != value["archive"]["size"]
                or digest(archive_path) != value["archive"]["sha256"]):
            raise ArtifactError("corrupt complete archive")
        with zipfile.ZipFile(archive_path) as archive:
            if sorted(archive.namelist()) != sorted(expected):
                raise ArtifactError("archive payload differs from its index")
            # Validate every decompressed byte before touching the destination.
            for name, entry in expected.items():
                content = archive.read(name)
                if len(content) != entry["size"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
                    raise ArtifactError(f"corrupt payload: {name}")
            for name in expected:
                output = destination / relative_path(name)
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(name) as stream, output.open("xb") as writer:
                    shutil.copyfileobj(stream, writer)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for operation in ("begin-release", "seal-release", "verify-release"):
        release = commands.add_parser(operation)
        release.add_argument("--repo", required=True, type=Path)
        release.add_argument("--artifacts", required=True, type=Path)
        if operation == "begin-release":
            release.add_argument("--build-command", action="append", required=True)
            release.add_argument("--toolchain", action="append", default=[])
    pack = commands.add_parser("archive")
    pack.add_argument("--prefix", required=True, type=Path)
    pack.add_argument("--tool", required=True)
    pack.add_argument("--product-version", required=True)
    pack.add_argument("--target", default="windows-x86_64")
    pack.add_argument("--build-info", type=Path, help="JSON with actual build command/toolchain provenance")
    pack.add_argument("--file", action="append", required=True, help="relative-payload-path=compiled-input-file")
    restore = commands.add_parser("restore")
    restore.add_argument("--artifacts", required=True, type=Path)
    restore.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.operation in {"begin-release", "seal-release", "verify-release"}:
        if args.operation == "begin-release":
            print(begin_release_build(args.repo, args.artifacts,
                build={"commands": args.build_command, "toolchains": args.toolchain}))
        elif args.operation == "seal-release":
            print(seal_release_build(args.repo, args.artifacts))
        else:
            verify_release_build(args.repo, args.artifacts)
            print("RELEASE_PROVENANCE_VERIFIED")
        return 0
    if args.operation == "archive":
        inputs = {}
        for item in args.file:
            name, source = item.split("=", 1)
            if name in inputs:
                raise ArtifactError(f"duplicate payload input: {name}")
            inputs[name] = Path(source)
        build = json.loads(args.build_info.read_text(encoding="utf-8")) if args.build_info else None
        print(archive_module(args.prefix, args.target, inputs, tool=args.tool, product_version=args.product_version, build=build))
    else:
        print(restore_module(args.artifacts, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
