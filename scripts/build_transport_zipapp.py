#!/usr/bin/env python3
"""Source-tree convenience entry for the independent transport builder."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = REPOSITORY_ROOT / "src/slk_transport"


def build_zipapp(output: Path | str) -> Path:
    specification = importlib.util.spec_from_file_location(
        "slk_transport_builder", PACKAGE_ROOT / "build_zipapp.py",
    )
    assert specification is not None and specification.loader is not None
    builder = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(builder)
    return builder.build_zipapp(output, overwatch_tools=REPOSITORY_ROOT / "src/slk_overwatch_tools")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(build_zipapp(args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
