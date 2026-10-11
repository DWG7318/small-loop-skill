"""Small packaged-layout fixtures for child Git/home/Checker ingress."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.process import windows_no_window_kwargs
from scripts.build_local_package import PackageError, build_package
from scripts.local_package_metadata import RUNTIME_REQUIRED_FILES, RUNTIME_PATHS
from runtime_fixtures import prepared_runtimes
from test_build_local_package import fake_artifacts, fake_python
from test_runtime_closure import wrapper_fixture, adapter_endpoint
from slk_transport.adapters.dsh import DshAdapter

ROOT = Path(__file__).resolve().parents[2]


def ocrv_module(root, monkeypatch):
    spec = importlib.util.spec_from_file_location("p1_ocrv", ROOT / "integrations/ocrv/slk_checker_adapter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "__file__", str(root / "runtime/ocrv/slk_checker_adapter.py"))
    monkeypatch.delenv("OCRV_SLK_COMMAND_JSON", raising=False)
    return module


def layout(tmp_path):
    slk = tmp_path / "tools/slk"
    for name in ("scripts/local_package_metadata.py", "runtime/ocrv/bin/opencodereview.exe", "runtime/git/cmd/git.exe"):
        path = slk / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"inventory fixture")
    return slk


def test_native_home_and_mutable_output_use_selected_child_environment(tmp_path, monkeypatch):
    slk = layout(tmp_path)
    module = ocrv_module(slk, monkeypatch)
    user = tmp_path / "actual-user"
    monkeypatch.setenv("USERPROFILE", str(user))
    monkeypatch.setenv("HOME", str(tmp_path / "not-user"))
    monkeypatch.setenv("OCRV_RUNTIME_ROOT", str(tmp_path / "legacy"))
    monkeypatch.delenv("OCRV_SLK_RUNTIME_ROOT", raising=False)
    environment = module._child_environment()
    repository = tmp_path / "repo"
    sessions = module._session_directory(repository, environment)
    assert sessions.is_relative_to(user / ".opencodereview/sessions")
    assert not sessions.is_relative_to(tmp_path / "legacy")
    _, output = module._artifact_root({"run_id": "R", "cell_id": "C"})
    assert output.is_relative_to(slk / "data/ocrv")
    explicit = tmp_path / "explicit-output"
    monkeypatch.setenv("OCRV_SLK_RUNTIME_ROOT", str(explicit))
    assert module._artifact_root({"run_id": "R", "cell_id": "C"})[1].is_relative_to(explicit)
    monkeypatch.setenv("OCRV_SLK_COMMAND_JSON", '["custom-wrapper","unchanged"]')
    assert module._session_directory(repository, environment).is_relative_to(tmp_path / "legacy/home")
    assert module._ocr_command() == ["custom-wrapper", "unchanged"]


@pytest.mark.parametrize("host_available", (False, True))
def test_git_fallback_only_changes_native_child_path(tmp_path, monkeypatch, host_available):
    slk = layout(tmp_path)
    module = ocrv_module(slk, monkeypatch)
    monkeypatch.setenv("PATH", "EXACT-HOST-PATH")
    monkeypatch.setattr(module.shutil, "which", lambda *a, **kw: "host-git.exe" if host_available else None)
    environment = module._child_environment()
    assert os.environ["PATH"] == "EXACT-HOST-PATH"
    assert environment["PATH"] == ("EXACT-HOST-PATH" if host_available else str(slk / "runtime/git/cmd") + os.pathsep + "EXACT-HOST-PATH")


@pytest.mark.skipif(os.name != "nt", reason="Windows packaged CMD ingress conversion")
@pytest.mark.parametrize("launcher", ("bin/slk-checker.cmd", "runtime/ocrv/slk-checker.cmd"))
def test_packaged_checker_automatic_ingress_is_direct_and_lossless(tmp_path, launcher):
    slk = layout(tmp_path / "中文 %P1_EXPANSION% ^space")
    python = slk / "runtime/python/python.exe"
    python.parent.mkdir(parents=True)
    shutil.copy2(sys.executable, python)
    # Use a real Python rather than copying DLLs: the command selection is tested
    # below and its selected script is then executed by this test interpreter.
    adapter = slk / "runtime/ocrv/slk_checker_adapter.py"
    adapter.write_text("import json,sys;print(json.dumps(sys.argv[1:]))", encoding="utf-8")
    endpoint = SimpleNamespace(address={"command": [str(slk / launcher)]})
    command = OcrvAdapter.command(endpoint)
    assert command == [str(python), "-B", str(adapter)]
    arguments = ["--request", str(tmp_path / '中文 %P1_EXPANSION% ^path' / 'request.json'), "--output", 'quote "literal"\n尾\\']
    environment = os.environ.copy()
    environment["P1_EXPANSION"] = "WRONG_EXPANSION"
    completed = subprocess.run([sys.executable, *command[1:], *arguments], env=environment,
        capture_output=True, text=True, encoding="utf-8", **windows_no_window_kwargs())
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == arguments


@pytest.mark.parametrize("kind", ("legacy", "similar", "prefix", "relative"))
def test_checker_command_keeps_legacy_and_explicit_overrides(tmp_path, kind):
    slk = layout(tmp_path)
    command = [str(slk / "bin/slk-checker.cmd")]
    if kind == "legacy":
        (slk / "scripts/local_package_metadata.py").unlink()
    elif kind == "similar":
        command = [str(slk / "bin/custom-slk-checker.cmd")]
    elif kind == "prefix":
        command.append("explicit")
    else:
        command = ["tools/slk/bin/slk-checker.cmd"]
    assert OcrvAdapter.command(SimpleNamespace(address={"command": command})) == command


def test_git_is_a_complete_required_static_runtime():
    assert "tools/slk/runtime/git" in RUNTIME_PATHS
    assert {"cmd/git.exe", "ucrt64/bin/git.exe", "usr/bin/sh.exe", "LICENSE.txt"} <= RUNTIME_REQUIRED_FILES["git"]


def test_git_missing_member_is_rejected_before_repository_manifest(tmp_path):
    inputs = prepared_runtimes(tmp_path / "prepared")
    inputs["git_runtime"] = tmp_path / "incomplete-git"
    inputs["git_runtime"].mkdir()
    (inputs["git_runtime"] / "LICENSE.txt").write_text("fixture")
    with pytest.raises(PackageError, match="Git runtime is incomplete"):
        build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "output",
                      python_runtime=fake_python(tmp_path / "python"), **inputs)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_git_no_follow_before_descendant_io(tmp_path, monkeypatch):
    import _winapi
    inputs = prepared_runtimes(tmp_path / "prepared")
    product = tmp_path / "git"
    product.mkdir()
    inputs["git_runtime"] = product
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = product / "external"
    _winapi.CreateJunction(str(outside), str(junction))
    original = os.scandir
    def guarded(path):
        assert Path(path) != junction and junction not in Path(path).parents
        return original(path)
    monkeypatch.setattr(os, "scandir", guarded)
    with pytest.raises(PackageError, match="reparse|symbolic"):
        build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "output",
                      python_runtime=fake_python(tmp_path / "python"), **inputs)


@pytest.mark.parametrize("host_available", (False, True))
def test_dsh_git_path_is_child_only_and_host_first(wrapper_fixture, tmp_path, host_available):
    slk = wrapper_fixture / "tools/slk"
    cli = slk / "runtime/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js"
    previous = cli.read_bytes()
    git = slk / "runtime/git/cmd/git.exe"
    git.parent.mkdir(parents=True, exist_ok=True)
    git.write_bytes(b"fixture selection only, not executed")
    host_git = shutil.which("git")
    if host_available and not host_git:
        pytest.skip("host Git required for host-first case")
    system32 = str(Path(os.environ["SystemRoot"]) / "System32")
    original_path = str(Path(host_git).parent) + os.pathsep + system32 if host_available else system32
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PROCESSOR_ARCHITECTURE"}}
    environment.update(PATH=original_path, DEEPSEEK_API_KEY="LOCAL-FIXTURE-NOT-A-KEY",
                       DSH_RUNTIME_ROOT=str(tmp_path / "data"), DSH_AGENTS_HOME=str(tmp_path / "agents"))
    command = DshAdapter().command(adapter_endpoint(wrapper_fixture, [str(slk / "bin/dsh-slk.cmd")]), "fixture")
    parent_path = os.environ.get("PATH")
    try:
        cli.write_text("console.log(JSON.stringify({path:process.env.PATH}));", encoding="utf-8")
        result = subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8",
                                **windows_no_window_kwargs())
        assert result.returncode == 0, result.stderr
        expected = original_path if host_available else str(git.parent) + os.pathsep + original_path
        assert json.loads(result.stdout)["path"] == expected
        assert os.environ.get("PATH") == parent_path
    finally:
        cli.write_bytes(previous)
