from __future__ import annotations

import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

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
    assert result.stdout.strip() == "slk-transport 4.1.0"


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
