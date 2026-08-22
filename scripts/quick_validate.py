from __future__ import annotations

import re
import sys
from pathlib import Path


def validate_skill(path: Path) -> list[str]:
    errors: list[str] = []
    skill_file = path / "SKILL.md"
    if not skill_file.is_file():
        return [f"missing {skill_file}"]
    try:
        text = skill_file.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [f"cannot read {skill_file}: {exc}"]
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        errors.append(f"{path.name}: frontmatter is not closed")
        return errors
    frontmatter = text[4:].split("\n---\n", 1)[0]
    name_match = re.search(r"^name:\s*([a-z0-9-]+)\s*$", frontmatter, re.MULTILINE)
    description_match = re.search(r"^description:\s*(.+)\s*$", frontmatter, re.MULTILINE)
    if not name_match or name_match.group(1) != path.name:
        errors.append(f"{path.name}: name does not match folder")
    if not description_match or not description_match.group(1).startswith("Use when "):
        errors.append(f"{path.name}: description does not start with Use when")
    return errors


def main(argv: list[str]) -> int:
    root = Path(argv[0]) if argv else Path("skills")
    paths = [root] if (root / "SKILL.md").is_file() else sorted(path for path in root.iterdir() if path.is_dir())
    errors = [error for path in paths for error in validate_skill(path)]
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {len(paths)} Skill directories are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
