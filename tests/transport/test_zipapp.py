from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.build_transport_zipapp import build_zipapp


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_transport_zipapp_is_reproducible_and_runnable(tmp_path: Path) -> None:
    first = build_zipapp(tmp_path / "a.pyz")
    second = build_zipapp(tmp_path / "b.pyz")

    assert sha256(first) == sha256(second)
    result = subprocess.run(
        [sys.executable, str(first), "--version"],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "slk-transport 4.4.2"


def test_transport_zipapp_contains_only_transport_source(tmp_path: Path) -> None:
    artifact = build_zipapp(tmp_path / "transport.pyz")

    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
    assert names == sorted(names)
    assert "__main__.py" in names
    assert "slk_transport/cli.py" in names
    assert all(
        name == "__main__.py" or name.startswith("slk_transport/")
        for name in names
    )
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
    assert not any("test" in name.lower() or "session" in name.lower() for name in names)


@pytest.mark.parametrize("exit_code", [0, 7])
def test_zipapp_entry_disables_external_bytecode_before_cli_import(
    tmp_path: Path, exit_code: int,
) -> None:
    artifact = build_zipapp(tmp_path / "transport.pyz")
    with zipfile.ZipFile(artifact) as archive:
        entry = archive.read("__main__.py")
    (tmp_path / "cache_probe.py").write_text("VALUE = 1\n", encoding="utf-8")
    probe = tmp_path / "entry-probe.pyz"
    with zipfile.ZipFile(probe, "w") as archive:
        archive.writestr("__main__.py", entry)
        archive.writestr("slk_transport/__init__.py", "")
        archive.writestr(
            "slk_transport/cli.py",
            f"import subprocess, sys\nsys.path.insert(0, {str(tmp_path)!r})\n"
            "import cache_probe\n"
            "def main():\n    print(sys.dont_write_bytecode)\n"
            "    child = subprocess.run([sys.executable, '-c', "
            "'import sys, cache_probe; print(sys.dont_write_bytecode)'], "
            "capture_output=True, text=True, check=True, "
            f"creationflags={subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0})\n"
            "    print(child.stdout.strip())\n"
            f"    return {exit_code}\n",
        )
    environment = os.environ.copy()
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    result = subprocess.run(
        [sys.executable, str(probe)], cwd=tmp_path, env=environment,
        capture_output=True, text=True, encoding="utf-8", check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert result.returncode == exit_code
    assert result.stdout.splitlines() == ["True", "True"]
    assert not (tmp_path / "__pycache__").exists()
