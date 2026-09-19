#!/usr/bin/env python3
"""Build the dependency-free SLK transport artifact reproducibly."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPOSITORY_ROOT / "src" / "slk_transport"
MAIN = (
    "from slk_transport.cli import main\n"
    "raise SystemExit(main())\n"
).encode("utf-8")


def _info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_zipapp(output: Path | str) -> Path:
    destination = Path(output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    entries: dict[str, bytes] = {"__main__.py": MAIN}
    for path in PACKAGE_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(PACKAGE_ROOT).as_posix()
        entries[f"slk_transport/{relative}"] = path.read_bytes()
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for name in sorted(entries):
                archive.writestr(_info(name), entries[name])
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(build_zipapp(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
