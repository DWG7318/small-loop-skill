from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {".git", ".codex", "__pycache__", ".pytest_cache"}
EXCLUDED_FILES = {"MANIFEST.json"}
VERSION = "2.5.0"
MIRRORED = [
    Path("agents/openai.yaml"),
    Path("SKILL.md"),
    Path("SPEC.md"),
    Path("contracts/slk-control-kernel.json"),
    Path("scripts/validate_defect_repair.py"),
    Path("scripts/validate_serial_plan.py"),
    Path("scripts/validate_worker_signal_stream.py"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_files(root: Path) -> list[Path]:
    values: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if relative.as_posix() in EXCLUDED_FILES or path.suffix == ".pyc":
            continue
        values.append(relative)
    return sorted(values, key=lambda item: item.as_posix())


def manifest_payload(root: Path) -> dict:
    return {
        "name": "Small Loop Skill",
        "version": VERSION,
        "excludes": sorted(EXCLUDED_FILES),
        "files": [
            {"path": relative.as_posix(), "sha256": sha256(root / relative)}
            for relative in release_files(root)
        ],
    }


def write_manifest(root: Path) -> None:
    text = json.dumps(manifest_payload(root), ensure_ascii=False, indent=2) + "\n"
    (root / "MANIFEST.json").write_bytes(text.encode("utf-8"))


def check(condition: bool, code: str, detail: str, errors: list[str]) -> None:
    if not condition:
        errors.append(f"{code}: {detail}")


def utf8_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"SLK_REPO_UTF8: {path}: {exc}")
        return ""


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    required = [
        "VERSION",
        "README.md",
        "README.zh-CN.md",
        "SPEC.md",
        "SKILL.md",
        "MIGRATION.md",
        "LICENSE",
        "MANIFEST.json",
        "VALIDATION-REPORT.md",
        "contracts/slk-control-kernel.json",
        "scripts/validate_defect_repair.py",
        "scripts/validate_serial_plan.py",
        "scripts/validate_worker_signal_stream.py",
        "small-loop-skill/SKILL.md",
        "small-loop-skill/agents/openai.yaml",
    ]
    for relative in required:
        check((root / relative).is_file(), "SLK_REPO_REQUIRED_FILE", relative, errors)
    if errors:
        return errors

    version = utf8_text(root / "VERSION", errors).strip()
    check(version == VERSION, "SLK_REPO_VERSION", f"VERSION is {version!r}", errors)
    readme = utf8_text(root / "README.md", errors)
    skill = utf8_text(root / "SKILL.md", errors)
    spec = utf8_text(root / "SPEC.md", errors)
    check(f"Current version: **{VERSION}**" in readme, "SLK_REPO_README_VERSION", "README version drift", errors)
    check(
        f"Current specification version: `{VERSION}`." in skill,
        "SLK_REPO_SKILL_VERSION",
        "SKILL body version drift",
        errors,
    )
    check("Small Loop Skill" in skill and "Small Loop Skill" in spec, "SLK_REPO_IDENTITY", "canonical identity missing", errors)
    check("Serial Loop Kit" not in readme and "Serial Loop Kit" not in skill and "Serial Loop Kit" not in spec, "SLK_REPO_IDENTITY", "unapproved canonical rename", errors)

    try:
        contract = json.loads(utf8_text(root / "contracts/slk-control-kernel.json", errors))
        check(contract.get("version") == VERSION, "SLK_REPO_CONTRACT_VERSION", "control contract version drift", errors)
        check(contract.get("visible_conversations") == ["CONTROL", "WORKER"], "SLK_REPO_TOPOLOGY", "visible conversation drift", errors)
    except json.JSONDecodeError as exc:
        errors.append(f"SLK_REPO_CONTRACT_JSON: {exc}")

    mirror_paths = list(MIRRORED)
    mirror_paths.extend(path.relative_to(root) for path in sorted((root / "templates").glob("*.yaml")))
    mirror_paths.extend(path.relative_to(root) for path in sorted((root / "references").glob("*.md")))
    for relative in mirror_paths:
        source = root / relative
        installed = root / "small-loop-skill" / relative
        check(installed.is_file(), "SLK_REPO_MIRROR_MISSING", installed.as_posix(), errors)
        if installed.is_file():
            check(source.read_bytes() == installed.read_bytes(), "SLK_REPO_MIRROR_DRIFT", relative.as_posix(), errors)

    try:
        manifest = json.loads(utf8_text(root / "MANIFEST.json", errors))
    except json.JSONDecodeError as exc:
        errors.append(f"SLK_REPO_MANIFEST_JSON: {exc}")
        return errors
    check(manifest.get("name") == "Small Loop Skill", "SLK_REPO_MANIFEST_NAME", "Manifest name drift", errors)
    check(manifest.get("version") == VERSION, "SLK_REPO_MANIFEST_VERSION", "Manifest version drift", errors)
    listed = {item.get("path"): item.get("sha256") for item in manifest.get("files", []) if isinstance(item, dict)}
    actual = {path.as_posix() for path in release_files(root)}
    check(set(listed) == actual, "SLK_REPO_MANIFEST_SET", f"missing={sorted(actual-set(listed))}; extra={sorted(set(listed)-actual)}", errors)
    for relative, expected in listed.items():
        path = root / relative
        if path.is_file():
            check(sha256(path) == expected, "SLK_REPO_MANIFEST_HASH", relative, errors)
    check("VALIDATION-REPORT.md" in listed, "SLK_REPO_MANIFEST_REPORT", "Validation Report must be protected", errors)
    return errors


def main(argv: Iterable[str]) -> int:
    args = list(argv)
    if args == ["--write-manifest"]:
        write_manifest(ROOT)
        print("WROTE: MANIFEST.json")
        return 0
    if args:
        print("FAIL SLK_REPO_USAGE: optional argument is --write-manifest", file=sys.stderr)
        return 2
    errors = validate(ROOT)
    if errors:
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        return 1
    print("PASS: SLK repository structure, identity, mirrors, and Manifest are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
