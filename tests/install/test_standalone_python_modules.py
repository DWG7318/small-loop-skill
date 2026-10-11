"""Behavior checks for the source prefixes exported as independent tool repos."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[2]


def hidden_run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment["PYTHONPATH"] = str(cwd / "not-a-source-checkout")
    return subprocess.run(
        command, cwd=cwd, env=environment, capture_output=True, text=True,
        encoding="utf-8", check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def test_transport_prefix_declares_its_own_package_and_license() -> None:
    prefix = ROOT / "src/slk_transport"
    metadata = tomllib.loads((prefix / "pyproject.toml").read_text(encoding="utf-8"))
    assert metadata["project"]["name"] == "slk-transport"
    assert metadata["project"]["version"] == (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert metadata["project"]["scripts"]["slk-transport"] == "slk_transport.cli:main"
    assert (prefix / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()


def test_independent_transport_zipapp_contains_explicit_ow_dependency(tmp_path: Path) -> None:
    transport = tmp_path / "transport-source"
    helper = tmp_path / "ow-source"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "artifacts", "*.egg-info")
    shutil.copytree(ROOT / "src/slk_transport", transport, ignore=ignore)
    shutil.copytree(ROOT / "src/slk_overwatch_tools", helper, ignore=ignore)
    first, second = tmp_path / "a.pyz", tmp_path / "b.pyz"
    for output in (first, second):
        built = hidden_run([
            sys.executable, str(transport / "build_zipapp.py"),
            "--overwatch-tools", str(helper), "--output", str(output),
        ], tmp_path)
        assert built.returncode == 0, built.stdout + built.stderr
    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        names = archive.namelist()
    assert "slk_transport/cli.py" in names
    assert "slk_overwatch_tools/__init__.py" in names
    assert not any("artifacts/" in name or "/tests/" in name or "__pycache__" in name for name in names)
    # The copied source is no longer present when the artifact is invoked.
    shutil.rmtree(transport)
    shutil.rmtree(helper)
    result = hidden_run([sys.executable, "-I", str(first), "--version"], tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "slk-transport " + (ROOT / "VERSION").read_text(encoding="utf-8").strip()


def test_transport_builder_requires_explicit_dependency(tmp_path: Path) -> None:
    result = hidden_run([
        sys.executable, str(ROOT / "src/slk_transport/build_zipapp.py"),
        "--overwatch-tools", str(tmp_path / "missing-helper"),
        "--output", str(tmp_path / "not-produced.pyz"),
    ], tmp_path)
    assert result.returncode != 0
    assert not (tmp_path / "not-produced.pyz").exists()

