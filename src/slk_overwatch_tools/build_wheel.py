"""Build the pure-Python OW wheel reproducibly, without third-party build tools."""
from __future__ import annotations

import argparse
import ast
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent
PACKAGE = "slk_overwatch_tools"
SOURCE_FILES = ("__init__.py", "cadence.py", "native_records.py")
VERSION = next(ast.literal_eval(node.value) for node in ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8")).body
               if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "__version__"
                                                      for target in node.targets))


def get_requires_for_build_wheel(config_settings=None):
    return []


def _info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    return info


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None) -> str:
    """PEP 517 build entry; the resulting wheel has no runtime dependencies."""
    directory = Path(wheel_directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{PACKAGE}-{VERSION}-py3-none-any.whl"
    dist_info = f"{PACKAGE}-{VERSION}.dist-info"
    metadata = ("Metadata-Version: 2.4\nName: slk-overwatch-tools\n"
                f"Version: {VERSION}\nSummary: Deterministic read-only Overwatcher helpers\n"
                "Requires-Python: >=3.10\nLicense-Expression: MIT\n"
                "License-File: LICENSE\nDescription-Content-Type: text/markdown\n\n")
    entries = {f"{PACKAGE}/{relative}": (ROOT / relative).read_bytes() for relative in SOURCE_FILES}
    entries.update({f"{dist_info}/METADATA": (metadata + (ROOT / "README.md").read_text(encoding="utf-8")).encode(),
                    f"{dist_info}/WHEEL": b"Wheel-Version: 1.0\nGenerator: slk-overwatch-tools\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
                    f"{dist_info}/licenses/LICENSE": (ROOT / "LICENSE").read_bytes()})
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for relative, content in sorted(entries.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        writer.writerow((relative, "sha256=" + digest, len(content)))
    writer.writerow((f"{dist_info}/RECORD", "", ""))
    entries[f"{dist_info}/RECORD"] = record.getvalue().encode()
    destination = directory / name
    temporary = destination.with_name(name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            for relative, content in sorted(entries.items()):
                archive.writestr(_info(relative), content)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return name


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts")
    args = parser.parse_args(argv)
    name = build_wheel(args.output)
    inputs = (*SOURCE_FILES, "build_wheel.py", "pyproject.toml", "LICENSE", "README.md")
    manifest = {"schema_version": "slk.tool-build-inputs/v1", "product": "slk-overwatch-tools", "version": VERSION,
                "source_sha256": {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() for relative in inputs},
                "artifact": name, "artifact_sha256": hashlib.sha256((args.output / name).read_bytes()).hexdigest()}
    (args.output / "BUILD_INPUTS.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(args.output / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
