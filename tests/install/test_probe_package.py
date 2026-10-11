"""Probe package/installer contracts, distinct from native host activation proof."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

import pytest

from scripts import build_local_package as builder
from scripts.local_package_metadata import ARTIFACT_NAMES, RUNTIME_PATHS, RUNTIME_REQUIRED_FILES


PROBE_FILES = {
    "artifacts/windows-amd64/slk-native-probe.exe",
    "dsh/register.mjs", "dsh/activity.mjs", "dsh/probe.mjs", "LICENSE",
}


def test_probe_is_seventh_runtime_not_sixth_public_artifact():
    assert "native-probe" in RUNTIME_REQUIRED_FILES
    assert RUNTIME_REQUIRED_FILES["native-probe"] == PROBE_FILES
    assert "tools/slk/runtime/native-probe" in RUNTIME_PATHS
    assert len(RUNTIME_PATHS) == 7
    assert len(ARTIFACT_NAMES) == 5
    assert not any("probe" in name for name in ARTIFACT_NAMES)


def test_document_files_do_not_include_developer_artifacts_or_tests(tmp_path: Path):
    root = tmp_path / "integration"
    for relative in ("README.md", "src/runtime.py", "artifacts/windows/payload.zip", "upstream/large-source.zip",
                     "tests/test_runtime.py", "build/debug.exe", "__pycache__/cache.pyc"):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"inventory only")
    assert {path.relative_to(root).as_posix() for path in builder._document_files(root)} == {
        "README.md", "src/runtime.py",
    }


def test_document_filter_does_not_traverse_excluded_artifacts(tmp_path: Path, monkeypatch):
    root = tmp_path / "integration"
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    (root / "README.md").write_text("user runtime guidance", encoding="utf-8")
    original = builder.os.scandir

    def guarded(path):
        assert Path(path) != artifacts and artifacts not in Path(path).parents
        return original(path)

    monkeypatch.setattr(builder.os, "scandir", guarded)
    assert [path.name for path in builder._document_files(root)] == ["README.md"]


@pytest.mark.parametrize("conflict", (False, True))
def test_installer_probe_rollback_preserves_owner_configuration(tmp_path: Path, conflict: bool):
    from test_local_install import _encoding_package, _ps51, INSTALLER, seed_old_install

    package = _encoding_package(tmp_path)
    codex = tmp_path / "old codex 中文 %LITERAL% ^home"
    previous = seed_old_install(codex)
    dsh_home = tmp_path / "DSH 中文 %LITERAL% ^home"
    dsh_home.mkdir()
    patch = dsh_home / "cordis.patch.yml"
    original_patch = b"# exact owner comment\n[]\n"
    patch.write_bytes(original_patch)
    plugin = dsh_home / "plugins/slk-native-probe"
    plugin.mkdir(parents=True)
    originals = {name: ("old-owner-" + name).encode() for name in ("activity.mjs", "probe.mjs", "slk-native-probe.exe")}
    for name, data in originals.items():
        (plugin / name).write_bytes(data)
    user = tmp_path / "OCRV isolated user"
    config = user / ".opencodereview/config.json"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"invalid JSON original")
    if conflict:
        # This explicitly trusted fixture helper injects an intervening owner
        # edit after successful native registration, then a downstream failure.
        helper = package / "tools/slk/scripts/configure_ocrv.py"
        helper.write_text("from pathlib import Path\nimport sys\np=Path(" + repr(str(patch)) +
                          ")\np.write_bytes(p.read_bytes()+b'# owner concurrent edit\\n')\n"
                          "raise SystemExit(7)\n", encoding="utf-8")
        manifest_path = package / "install-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            if entry["path"] == "tools/slk/scripts/configure_ocrv.py":
                entry.update(sha256=hashlib.sha256(helper.read_bytes()).hexdigest(), size=helper.stat().st_size)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    environment = os.environ.copy()
    environment["PSModulePath"] = str(_ps51().parent / "Modules")
    completed = subprocess.run([str(_ps51()), "-NoProfile", "-NonInteractive", "-File", str(INSTALLER),
        "-PackageRoot", str(package), "-CodexHome", str(codex), "-PythonExecutable", sys.executable,
        "-DshUserHome", str(dsh_home), "-OcrvUserHome", str(user)], env=environment,
        capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert config.read_bytes() == b"invalid JSON original"
    for relative, data in previous.items():
        assert (codex / relative).read_bytes() == data
    report = json.loads(next((codex / ".tmp").glob("slk-install-failed-*.json")).read_text(encoding="utf-8-sig"))
    if conflict:
        assert report["status"] == "ROLLBACK_FAILED" and report["active_tree_verified"] is False
        assert patch.read_bytes().endswith(b"# owner concurrent edit\n")
        # Keep the whole registration, including its still-referenced plugin.
        assert all((plugin / name).read_bytes() != data for name, data in originals.items())
    else:
        assert report["status"] == "ROLLED_BACK" and report["active_tree_verified"] is True
        assert patch.read_bytes() == original_patch
        assert all((plugin / name).read_bytes() == data for name, data in originals.items())


@pytest.mark.parametrize("state", ("UNCHANGED", "ROLLED_BACK", "ROLLBACK_FAILED", "UNPARSEABLE"))
def test_installer_keeps_registration_failure_state_truthful(tmp_path: Path, state: str):
    from test_local_install import _encoding_package, _ps51, INSTALLER, seed_old_install

    package = _encoding_package(tmp_path)
    codex = tmp_path / "isolated codex"
    previous = seed_old_install(codex)
    dsh_home = tmp_path / "isolated DSH"
    dsh_home.mkdir()
    patch = dsh_home / "cordis.patch.yml"
    patch.write_bytes(b"owner edit retained\n")
    # A registered helper's structured failure is the only authority for its
    # own transaction result. This contract fixture does not claim native work.
    script = package / "tools/slk/runtime/native-probe/dsh/register.mjs"
    failure = {"error": "SLK_NATIVE_PROBE_REGISTRATION_FAILED", "rollback_state": state, "cause": "Error"}
    if state == "ROLLBACK_FAILED":
        failure["conflicts"] = [str(patch)]
    payload = "not a structured receipt" if state == "UNPARSEABLE" else json.dumps(failure)
    script.write_text("console.error(" + json.dumps(payload) + ");process.exitCode=1;", encoding="utf-8")
    manifest_path = package / "install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == "tools/slk/runtime/native-probe/dsh/register.mjs":
            entry.update(sha256=hashlib.sha256(script.read_bytes()).hexdigest(), size=script.stat().st_size)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    environment = os.environ.copy()
    environment["PSModulePath"] = str(_ps51().parent / "Modules")
    completed = subprocess.run([str(_ps51()), "-NoProfile", "-NonInteractive", "-File", str(INSTALLER),
        "-PackageRoot", str(package), "-CodexHome", str(codex), "-PythonExecutable", sys.executable,
        "-DshUserHome", str(dsh_home)], env=environment, capture_output=True,
        creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.returncode == 1
    assert patch.read_bytes() == b"owner edit retained\n"
    assert all((codex / relative).read_bytes() == data for relative, data in previous.items())
    report = json.loads(next((codex / ".tmp").glob("slk-install-failed-*.json")).read_text(encoding="utf-8-sig"))
    verified = state in {"UNCHANGED", "ROLLED_BACK"}
    assert report["status"] == ("ROLLED_BACK" if verified else "ROLLBACK_FAILED")
    assert report["active_tree_verified"] is verified


@pytest.mark.parametrize("override", ("relative 中文 %LITERAL% ^home", "~/tilde 中文 %LITERAL% ^home", " \t "))
def test_installer_default_home_uses_real_native_resolver(tmp_path: Path, override: str):
    from test_local_install import _encoding_package, _ps51, INSTALLER
    import shutil

    native = os.environ.get("SLK_DSH_NATIVE_PACKAGE_ROOT")
    if not native:
        pytest.skip("set SLK_DSH_NATIVE_PACKAGE_ROOT for the real product home-resolver check")
    package = _encoding_package(tmp_path)
    source = Path(native) / "node_modules/@deepseek-ai/dsh-home-paths"
    shutil.copytree(source, package / "tools/slk/runtime/dsh/node_modules/@deepseek-ai/dsh-home-paths")
    manifest_path = package / "install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = [{"path": path.relative_to(package).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size} for path in sorted(package.rglob("*")) if path.is_file() and path != manifest_path]
    manifest["files"].sort(key=lambda entry: entry["path"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    environment = os.environ.copy()
    environment["PSModulePath"] = str(_ps51().parent / "Modules")
    profile = tmp_path / "native profile 中文 %LITERAL% ^home"
    environment.update(DSH_HOME=override, USERPROFILE=str(profile), HOME=str(profile),
        APPDATA=str(profile / "AppData/Roaming"), LOCALAPPDATA=str(profile / "AppData/Local"))
    expected = subprocess.run([str(package / "tools/slk/runtime/node/node.exe"), "--input-type=module", "-e",
        "import {createRequire} from 'node:module';import {pathToFileURL} from 'node:url';const r=createRequire(process.argv[1]);const {resolveDshHome}=await import(pathToFileURL(r.resolve('@deepseek-ai/dsh-home-paths')).href);console.log(resolveDshHome());",
        str(package / "tools/slk/runtime/dsh/package.json")], cwd=tmp_path, env=environment,
        capture_output=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
    assert expected.returncode == 0, expected.stderr
    expected_home = Path(expected.stdout.strip())
    assert expected_home.is_relative_to(tmp_path)
    expected_home.mkdir(parents=True)
    patch = expected_home / "cordis.patch.yml"
    original = b"# exact owner bytes\n[]\n"
    patch.write_bytes(original)
    result = subprocess.run([str(_ps51()), "-NoProfile", "-NonInteractive", "-File", str(INSTALLER),
        "-PackageRoot", str(package), "-CodexHome", str(tmp_path / "isolated codex"), "-PythonExecutable", sys.executable],
        cwd=tmp_path, env=environment, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout.decode("utf-8"))
    assert receipt["status"] == "INSTALLED" and receipt["dsh_probe"]["load_state"] == "PENDING_RELOAD"
    assert Path(receipt["dsh_probe"]["home"]) == expected_home
    # Native YAML must replace an empty [] with the new list; owner comments
    # remain intact and the receipt restores the complete original bytes.
    assert patch.read_bytes().startswith(b"# exact owner bytes\n")
    recovery = subprocess.run([str(package / "tools/slk/runtime/node/node.exe"),
        str(package / "tools/slk/runtime/native-probe/dsh/register.mjs"), "rollback", receipt["dsh_probe"]["receipt"]],
        cwd=tmp_path, env=environment, capture_output=True, encoding="utf-8",
        creationflags=subprocess.CREATE_NO_WINDOW)
    assert recovery.returncode == 0, recovery.stderr
    assert json.loads(recovery.stdout)["conflicts"] == []
    assert patch.read_bytes() == original
