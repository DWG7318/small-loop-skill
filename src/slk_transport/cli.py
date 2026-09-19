"""Command-line entry point for the SLK transport artifact."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


VERSION = "4.0.0"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="slk-transport")
    parser.add_argument("--version", action="version", version=f"slk-transport {VERSION}")
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
