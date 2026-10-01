from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_local_package import ARTIFACT_NAMES, build_package
from scripts.validate_repository import EXPECTED_SKILLS


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install_local.ps1"
VERIFY = ROOT / "scripts" / "verify_local_install.py"


def fake_artifacts(root: Path) -> Path:
    root.mkdir()
    for name in ARTIFACT_NAMES:
        (root / name).write_bytes(f"new-{name}-4.3.6\n".encode())
    return root


def seed_old_install(codex_home: Path) -> dict[str, bytes]:
    expected: dict[str, bytes] = {}
    for name in EXPECTED_SKILLS:
        relative = Path("skills") / name / "SKILL.md"
        data = f"old-{name}-4.2.2\n".encode()
        target = codex_home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        expected[relative.as_posix()] = data
    for name in (*ARTIFACT_NAMES, "slk-transport.cmd"):
        relative = Path("tools/slk/bin") / name
        data = f"old-{name}-4.2.2\n".encode()
        target = codex_home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        expected[relative.as_posix()] = data
    relative = Path("tools/slk/share/small-loop-skill/VERSION")
    target = codex_home / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"4.2.2\n")
    expected[relative.as_posix()] = b"4.2.2\n"
    return expected


def run_installer(package: Path, codex_home: Path, *, corrupt: str | None = None) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell 7 is unavailable")
    command = [
        pwsh, "-NoProfile", "-NonInteractive", "-File", str(INSTALLER),
        "-PackageRoot", str(package), "-CodexHome", str(codex_home),
        "-PythonExecutable", sys.executable,
    ]
    environment = os.environ.copy()
    if corrupt:
        command.extend(["-TestCorruptStagedRelativePath", corrupt])
        environment["SLK_INSTALL_TEST_MODE"] = "1"
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=environment,
    )


def test_staged_corruption_rolls_back_entire_previous_install(tmp_path: Path) -> None:
    package = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package")
    codex_home = tmp_path / "codex-home"
    expected = seed_old_install(codex_home)

    result = run_installer(
        package,
        codex_home,
        corrupt="tools/slk/bin/slk-state.exe",
    )

    assert result.returncode != 0, result.stdout + result.stderr
    for relative, data in expected.items():
        assert (codex_home / relative).read_bytes() == data
    assert not (codex_home / "tools/slk/install-manifest.json").exists()
    reports = list((codex_home / ".tmp").glob("slk-install-failed-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["status"] == "ROLLED_BACK"
    assert report["active_tree_verified"] is True


def test_successful_install_matches_package_manifest(tmp_path: Path) -> None:
    package = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package")
    codex_home = tmp_path / "codex-home"
    seed_old_install(codex_home)

    result = run_installer(package, codex_home)

    assert result.returncode == 0, result.stdout + result.stderr
    completed = subprocess.run(
        [sys.executable, str(VERIFY), "--root", str(codex_home)],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS SLK_LOCAL_INSTALL 4.3.6" in completed.stdout
    assert (codex_home / "tools/slk/share/small-loop-skill/VERSION").read_text(encoding="utf-8").strip() == "4.3.6"
    launcher = codex_home / "tools/slk/bin/slk-transport.cmd"
    assert launcher.is_file()
    assert 'python "%~dp0slk-transport.pyz" %*' in launcher.read_text(encoding="utf-8")
