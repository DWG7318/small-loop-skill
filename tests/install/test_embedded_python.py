"""Opt-in real Windows embed checks; other SLK binaries remain packaging fixtures."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.build_local_package import ARTIFACT_NAMES, build_package
from scripts.build_transport_zipapp import build_zipapp
from scripts.tool_artifacts import begin_release_build, seal_release_build
from runtime_fixtures import prepared_runtimes


ROOT = Path(__file__).resolve().parents[2]
PS51 = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


@pytest.fixture
def embedded_package(tmp_path: Path) -> Path:
    source = os.environ.get("SLK_TEST_PYTHON_RUNTIME")
    if not source or not Path(source).is_dir():
        pytest.skip("set SLK_TEST_PYTHON_RUNTIME to an offline prepared Windows embed directory")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    begin_release_build(ROOT, artifacts, build={"commands": [
        "SIMULATED native artifacts + real transport zipapp; no native compiler executed",
    ]})
    for name in ARTIFACT_NAMES:
        (artifacts / name).write_bytes(b"simulated non-executed SLK native artifact\n")
    build_zipapp(artifacts / "slk-transport.pyz")
    seal_release_build(ROOT, artifacts)
    return build_package(ROOT, artifacts, tmp_path / "中文 空格 package", python_runtime=Path(source),
                         **prepared_runtimes(tmp_path / "prepared", runnable_registration=True))


def clean_environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment["PATH"] = str(Path(environment.get("SystemRoot", "C:/Windows")) / "System32")
    environment["PYTHONPATH"] = str(tmp_path / "poisoned source checkout")
    environment["PYTHONHOME"] = str(tmp_path / "nonexistent global Python")
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    environment["DSH_HOME"] = str(tmp_path / "isolated native DSH home")
    # Do not load PowerShell 7 modules into the independently tested PS 5.1 host.
    for key in list(environment):
        if key.upper() == "PSMODULEPATH":
            environment.pop(key)
    return environment


def run(command: list[str], tmp_path: Path, *, corrupt: bool = False) -> subprocess.CompletedProcess[str]:
    environment = clean_environment(tmp_path)
    if corrupt:
        environment["SLK_INSTALL_TEST_MODE"] = "1"
    return subprocess.run(
        command, cwd=tmp_path, env=environment, text=True, encoding="utf-8", errors="replace",
        capture_output=True, check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def test_embedded_subprocess_helper_requests_headless_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def record_run(command, **kwargs):
        calls.append(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", record_run)
    run(["not-executed"], tmp_path)
    assert calls[0]["creationflags"] == (subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def verify(root: Path, tmp_path: Path, *, package: bool = False) -> subprocess.CompletedProcess[str]:
    command = [
        str(root / "tools/slk/runtime/python/python.exe"),
        str(root / "tools/slk/scripts/verify_local_install.py"), "--root", str(root),
    ]
    if package:
        command.append("--package-mode")
    return run(command, tmp_path)


def test_real_embed_package_runs_isolated_verifier_and_transport_help(
    embedded_package: Path, tmp_path: Path,
) -> None:
    completed = verify(embedded_package, tmp_path, package=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    python = embedded_package / "tools/slk/runtime/python/python.exe"
    isolated = run([str(python), "-B", "-c", (
        "import sys,json,ssl,sqlite3,ctypes,slk_transport,local_package_metadata; "
        "print(json.dumps({'isolated':sys.flags.isolated,'executable':sys.executable,"
        "'paths':sys.path,'site_loaded':'site' in sys.modules,"
        "'metadata':local_package_metadata.__file__,'version':slk_transport.__version__}))"
    )], tmp_path)
    assert isolated.returncode == 0, isolated.stdout + isolated.stderr
    identity = json.loads(isolated.stdout)
    assert identity["isolated"] == 1
    assert identity["executable"] == str(python)
    assert identity["site_loaded"] is False
    assert identity["version"] == (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert identity["metadata"] == str(embedded_package / "tools/slk/scripts/local_package_metadata.py")
    assert all(Path(path).is_relative_to(embedded_package) for path in identity["paths"])
    launcher = embedded_package / "tools/slk/bin/slk-transport.cmd"
    help_result = run([os.environ.get("COMSPEC", "C:/Windows/System32/cmd.exe"), "/d", "/c", str(launcher), "--help"], tmp_path)
    assert help_result.returncode == 0, help_result.stdout + help_result.stderr
    assert "attest-subagent-overwatcher" in help_result.stdout
    native_help = run([
        os.environ.get("COMSPEC", "C:/Windows/System32/cmd.exe"), "/d", "/c", str(launcher),
        "attest-subagent-overwatcher", "--help",
    ], tmp_path)
    assert native_help.returncode == 0, native_help.stdout + native_help.stderr
    assert "--evidence-root" in native_help.stdout
    assert verify(embedded_package, tmp_path, package=True).returncode == 0
    shutil.move(python, python.with_suffix(".absent"))
    missing = run([os.environ.get("COMSPEC", "C:/Windows/System32/cmd.exe"), "/d", "/c", str(launcher), "--help"], tmp_path)
    assert missing.returncode != 0
    assert "Python runtime is missing" in missing.stdout + missing.stderr


def test_default_installer_reports_missing_embed_without_system_python_fallback(
    embedded_package: Path, tmp_path: Path,
) -> None:
    shell = shutil.which("pwsh")
    if not shell:
        pytest.skip("PowerShell 7 is unavailable")
    (embedded_package / "tools/slk/runtime/python/python.exe").unlink()
    completed = run([
        shell, "-NoProfile", "-NonInteractive", "-File",
        str(embedded_package / "tools/slk/scripts/install_local.ps1"),
        "-PackageRoot", str(embedded_package), "-CodexHome", str(tmp_path / "missing runtime home"),
        "-DshUserHome", str(tmp_path / "isolated DSH home"),
    ], tmp_path)
    assert completed.returncode != 0
    assert "Python runtime is missing" in completed.stdout + completed.stderr


@pytest.mark.parametrize("shell", (str(PS51), shutil.which("pwsh")), ids=("powershell51", "pwsh7"))
def test_real_embed_default_install_repeat_rollback_and_relocate(
    embedded_package: Path, tmp_path: Path, shell: str | None,
) -> None:
    if not shell or not Path(shell).is_file():
        pytest.skip("requested PowerShell executable is unavailable")
    home = tmp_path / "中文 空格 isolated home"
    retained = {
        "config.toml": b"unrelated owner config\n",
        "tools/slk/config/owner.json": b'{"retain":true}\n',
        "tools/slk/data/owner.db": b"simulated owner bytes\n",
        "skills/unrelated/SKILL.md": b"unrelated owner skill\n",
    }
    for relative, data in retained.items():
        target = home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    command = [
        shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
        str(embedded_package / "tools/slk/scripts/install_local.ps1"),
        "-PackageRoot", str(embedded_package), "-CodexHome", str(home) + "\\",
        "-DshUserHome", str(tmp_path / "isolated DSH home"),
    ]
    for _ in range(2):
        result = run(command, tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert '"status":"INSTALLED"' in result.stdout
    extra = home / "tools/slk/runtime/python/unlisted.dll"
    extra.write_bytes(b"unlisted runtime program")
    drifted = verify(home, tmp_path)
    assert drifted.returncode != 0
    assert "missing or extra files" in drifted.stdout
    extra.unlink()
    manifest = json.loads((home / "tools/slk/install-manifest.json").read_text(encoding="utf-8"))
    before = {entry["path"]: (home / entry["path"]).read_bytes() for entry in manifest["files"]}
    failed = run(command + ["-TestCorruptStagedRelativePath", "tools/slk/runtime/python/python314._pth"], tmp_path, corrupt=True)
    assert failed.returncode != 0, failed.stdout + failed.stderr
    report = json.loads(next((home / ".tmp").glob("slk-install-failed-*.json")).read_text(encoding="utf-8-sig"))
    assert report["status"] == "ROLLED_BACK"
    assert report["active_tree_verified"] is True
    assert all((home / relative).read_bytes() == data for relative, data in before.items())
    assert all((home / relative).read_bytes() == data for relative, data in retained.items())
    shutil.rmtree(embedded_package)
    moved = tmp_path / "迁移 后 installed"
    shutil.move(home, moved)
    completed = verify(moved, tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS SLK_LOCAL_INSTALL " + (ROOT / "VERSION").read_text(encoding="utf-8").strip() in completed.stdout
