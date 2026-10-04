from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / "skills"
VERSION = "4.4.0"
COLLECTION_NAME = "Small Loop Skill Collection"
EXPECTED_SKILLS = (
    "small-loop-skill",
    "slk-plan-run",
    "slk-guard-resources",
    "slk-select-models",
    "slk-grill-supervisor",
    "slk-manage-team",
    "slk-overwatch-run",
    "slk-manage-temporal",
    "slk-dispatch-cell",
    "slk-execute-cell",
    "slk-check-cell",
    "slk-record-run",
    "slk-rework-cell",
    "slk-adjust-run",
    "slk-recover-communication",
    "slk-close-run",
)
EXCLUDED_DIRS = {
    ".git",
    ".codex",
    ".worktrees",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "node_modules",
    "target",
}
EXCLUDED_FILES = {"MANIFEST.json"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_files(root: Path) -> list[Path]:
    git_files = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if git_files.returncode == 0:
        values = [
            Path(raw.decode("utf-8"))
            for raw in git_files.stdout.split(b"\0")
            if raw
        ]
        return sorted(
            (
                relative
                for relative in values
                if relative.as_posix() not in EXCLUDED_FILES
                and (root / relative).is_file()
            ),
            key=lambda item: item.as_posix(),
        )

    values: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if (
            relative.as_posix() in EXCLUDED_FILES
            or path.name in {".DS_Store", "Thumbs.db"}
            or path.suffix in {".log", ".pyc", ".tmp", ".tsbuildinfo"}
        ):
            continue
        values.append(relative)
    return sorted(values, key=lambda item: item.as_posix())


def manifest_payload(root: Path) -> dict:
    return {
        "name": COLLECTION_NAME,
        "version": VERSION,
        "skill_count": len(EXPECTED_SKILLS),
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
        data = path.read_bytes()
        if b"\r\n" in data:
            errors.append(f"SLK_REPO_LF: {path.relative_to(ROOT).as_posix()}")
        return data.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"SLK_REPO_UTF8: {path}: {exc}")
        return ""


def frontmatter_name(text: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    match = re.search(r"^name:\s*([a-z0-9-]+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


def validate(root: Path) -> list[str]:
    errors: list[str] = []
    required = (
        "VERSION",
        "README.md",
        "README.zh-CN.md",
        "MIGRATION.md",
        "CHANGELOG.md",
        "LICENSE",
        "MANIFEST.json",
        "VALIDATION-REPORT.md",
        ".github/workflows/validate.yml",
        "docs/contracts/slk-transport-task.schema.json",
        "docs/contracts/slk-runtime-snapshot.schema.json",
        "docs/contracts/slk-overwatch-cycle.schema.json",
        "docs/contracts/slk-overwatcher-turn-resume.schema.json",
        "docs/contracts/slk-overwatcher-credential-rotation.schema.json",
        "docs/contracts/slk-ocrv-worker-recovery.schema.json",
        "docs/contracts/slk-ocrv-worker-recovery-result.schema.json",
        "docs/contracts/slk-checker-post-d1.schema.json",
        "docs/contracts/slk-checker-completion.schema.json",
        "docs/contracts/slk-native-execution-outcome.schema.json",
        "docs/contracts/slk-overwatcher-cadence-inspection.schema.json",
        "docs/contracts/slk-desktop-current-turn-recovery.schema.json",
        "docs/contracts/slk-run-readiness.schema.json",
        "docs/contracts/slk-ocrv-d1-preflight.schema.json",
        "docs/maintenance/2026-09-28-slk-4.3.1-consistency-audit.md",
        "docs/superpowers/specs/2026-09-28-slk-4.3.1-field-corrections-design.md",
        "docs/superpowers/specs/2026-09-29-slk-4.3.2-desktop-current-turn-recovery-design.md",
        "docs/superpowers/specs/2026-09-30-slk-4.3.3-ocrv-preflight-design.md",
        "docs/superpowers/plans/2026-09-30-slk-4.3.3-ocrv-preflight.md",
        "integrations/ocrv/install.ps1",
        "integrations/ocrv/rollback.ps1",
        "integrations/ocrv/slk-checker.cmd",
        "integrations/ocrv/slk_checker_recovery.py",
        "integrations/ocrv/slk_checker_post_d1.py",
        "integrations/ocrv/slk_checker_adapter.py",
        "integrations/ocrv/slk-checker-capabilities.json",
        "scripts/build_release_artifacts.ps1",
        "scripts/build_local_package.py",
        "scripts/slk-transport.cmd",
        "scripts/install_local.ps1",
        "scripts/verify_bi_release.py",
        "scripts/verify_local_install.py",
    )
    for relative in required:
        check((root / relative).is_file(), "SLK_REPO_REQUIRED_FILE", relative, errors)

    if errors:
        return errors

    version = utf8_text(root / "VERSION", errors).strip()
    check(version == VERSION, "SLK_REPO_VERSION", repr(version), errors)

    actual_skills = tuple(sorted(path.name for path in SKILLS_ROOT.iterdir() if path.is_dir()))
    check(actual_skills == tuple(sorted(EXPECTED_SKILLS)), "SLK_REPO_SKILL_SET", repr(actual_skills), errors)
    for name in EXPECTED_SKILLS:
        path = SKILLS_ROOT / name / "SKILL.md"
        check(path.is_file(), "SLK_REPO_SKILL_FILE", name, errors)
        if path.is_file():
            text = utf8_text(path, errors)
            check(frontmatter_name(text) == name, "SLK_REPO_SKILL_NAME", name, errors)
            check("description: Use when " in text, "SLK_REPO_SKILL_DESCRIPTION", name, errors)

    audit = utf8_text(
        root / "docs/maintenance/2026-09-28-slk-4.3.1-consistency-audit.md",
        errors,
    )
    for marker in (
        "Skill / contract / producer / consumer matrix",
        "Authority and outcome matrix",
        "Writes, capacity and continuity",
        "Migration, package, BI and Temporal-off",
        "Same-class findings and corrections",
        "context compaction",
    ):
        check(marker in audit, "SLK_REPO_AUDIT_MATRIX", marker, errors)
    for name in EXPECTED_SKILLS:
        if name == "slk-manage-temporal":
            continue
        check(f"`{name}`" in audit, "SLK_REPO_AUDIT_SKILL", name, errors)

    main = utf8_text(SKILLS_ROOT / "small-loop-skill" / "SKILL.md", errors)
    for name in EXPECTED_SKILLS[1:]:
        check(main.count(f"`${name}`") == 1, "SLK_REPO_ROUTE", name, errors)

    try:
        manifest = json.loads(utf8_text(root / "MANIFEST.json", errors))
    except json.JSONDecodeError as exc:
        errors.append(f"SLK_REPO_MANIFEST_JSON: {exc}")
        return errors

    check(manifest.get("name") == COLLECTION_NAME, "SLK_REPO_MANIFEST_NAME", repr(manifest.get("name")), errors)
    check(manifest.get("version") == VERSION, "SLK_REPO_MANIFEST_VERSION", repr(manifest.get("version")), errors)
    check(manifest.get("skill_count") == len(EXPECTED_SKILLS), "SLK_REPO_MANIFEST_SKILLS", repr(manifest.get("skill_count")), errors)
    listed = {
        item.get("path"): item.get("sha256")
        for item in manifest.get("files", [])
        if isinstance(item, dict)
    }
    actual = {path.as_posix() for path in release_files(root)}
    check(set(listed) == actual, "SLK_REPO_MANIFEST_SET", f"missing={sorted(actual-set(listed))}; extra={sorted(set(listed)-actual)}", errors)
    for relative, expected in listed.items():
        path = root / relative
        if path.is_file():
            check(sha256(path) == expected, "SLK_REPO_MANIFEST_HASH", relative, errors)
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
    print("PASS: SLK 4.4.0 skill collection structure, identity, and Manifest are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
