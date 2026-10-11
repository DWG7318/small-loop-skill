#!/usr/bin/env python3
"""Build transport plus the explicitly supplied OW helper; no installed imports."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import zipfile


PACKAGE_ROOT = Path(__file__).resolve().parent
MAIN = (
    "import os\nimport sys\n"
    "os.environ['PYTHONDONTWRITEBYTECODE'] = '1'\n"
    "sys.dont_write_bytecode = True\n"
    "from slk_transport.cli import main\n"
    "raise SystemExit(main())\n"
).encode("utf-8")


def _source_entries(root: Path, package: str, files: tuple[str, ...] | None = None) -> dict[str, bytes]:
    if not (root / "__init__.py").is_file():
        raise ValueError(f"explicit {package} source is missing: {root}")
    result = {}
    for source in sorted((root / name for name in files) if files is not None else root.rglob("*.py")):
        relative = source.relative_to(root)
        if any(part in {"__pycache__", "tests", "artifacts", "build", "dist", ".venv"}
               or part.endswith(".egg-info") for part in relative.parts):
            continue
        # Package subdirectories only, not repository/build helper directories.
        if any(not (root / Path(*relative.parts[:index]) / "__init__.py").is_file()
               for index in range(1, len(relative.parts))):
            continue
        result[f"{package}/{relative.as_posix()}"] = source.read_bytes()
    return result


def build_zipapp(output: Path | str, *, overwatch_tools: Path | str) -> Path:
    destination = Path(output).resolve()
    helper = Path(overwatch_tools).resolve()
    # Accept either an exported package prefix or a conventional source repo.
    if not (helper / "__init__.py").is_file():
        helper = helper / "src/slk_overwatch_tools"
    entries = {"__main__.py": MAIN}
    entries.update(_source_entries(PACKAGE_ROOT, "slk_transport"))
    specification = importlib.util.spec_from_file_location("slk_ow_build_inputs", helper / "build_wheel.py")
    if specification is None or specification.loader is None:
        raise ValueError(f"OW dependency build-input declaration is missing: {helper}")
    declaration = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(declaration)
    entries.update(_source_entries(helper, "slk_overwatch_tools", declaration.SOURCE_FILES))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    if temporary.exists():
        raise FileExistsError(f"another build or unfinished output exists: {temporary}")
    try:
        with zipfile.ZipFile(temporary, "x") as archive:
            for name in sorted(entries):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, entries[name])
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overwatch-tools", required=True, type=Path)
    arguments = parser.parse_args()
    print(build_zipapp(arguments.output, overwatch_tools=arguments.overwatch_tools))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
