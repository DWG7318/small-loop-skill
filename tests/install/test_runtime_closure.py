from __future__ import annotations

import json
import os
import base64
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_local_package import PackageError, build_package
from scripts.verify_local_install import VerificationError, sha256, verify
from test_build_local_package import ROOT, fake_artifacts, fake_python
from runtime_fixtures import prepared_runtimes, registration_fixture
from slk_transport.adapters.dsh import DshAdapter
from slk_transport.contracts import ENDPOINT_SCHEMA, Endpoint
from slk_transport.process import windows_no_window_kwargs
from slk_transport.subprocess_watch import finish, spawn

PS51 = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"


@pytest.fixture(scope="module")
def wrapper_fixture(tmp_path_factory) -> Path:
    node = os.environ.get("SLK_TEST_NODE_EXE") or shutil.which("node")
    if not node or not Path(node).is_file() or not PS51.is_file():
        pytest.skip("real Node and Windows PowerShell 5.1 required for argv fixture")
    root = tmp_path_factory.mktemp("wrapper 中文 空格")
    directory = root / "tools/slk/runtime/dsh"
    (directory / "node_modules/@deepseek-ai/dsh/lib").mkdir(parents=True)
    (directory.parent / "node").mkdir()
    shutil.copy2(node, directory.parent / "node/node.exe")
    shutil.copy2(ROOT / "integrations/dsh/dsh-slk.ps1", directory / "dsh-slk.ps1")
    scripts = directory.parent.parent / "scripts"
    scripts.mkdir()
    shutil.copy2(ROOT / "scripts/local_package_metadata.py", scripts / "local_package_metadata.py")
    public = directory.parent.parent / "bin"
    public.mkdir()
    shutil.copy2(ROOT / "scripts/dsh-slk.cmd", public / "dsh-slk.cmd")
    shutil.copy2(ROOT / "integrations/dsh/dsh-slk.cmd", directory / "dsh-slk.cmd")
    (directory / "node_modules/@deepseek-ai/dsh/lib/bin.js").write_text(
        "console.log(JSON.stringify({args:process.argv.slice(2),home:process.env.DSH_HOME,"
        "agents:process.env.DSH_AGENTS_HOME,trusted:process.env.SLK_DSH_CONTINUATION_TRUSTED}));"
        "process.exit(23);", encoding="utf-8")
    registration_fixture(root / "tools/slk/runtime")
    return root


def adapter_endpoint(root: Path, command: list[str], session: str | None = None) -> Endpoint:
    return Endpoint(ENDPOINT_SCHEMA, "RUN-A", "worker", "RUN-A-worker", "dsh", "dsh-worker",
                    "LOCAL-TEST-HOST", 1, "active", {
        "command": command, "instance_id": "RUN-A-worker", "session_id": session,
        "runtime_root": str(root), "cwd": str(root), "timeout_seconds": 5,
    })


@pytest.mark.parametrize("launcher", ("bin/dsh-slk.cmd", "runtime/dsh/dsh-slk.cmd"))
@pytest.mark.parametrize("session", (None, "session-00000000-0000-4000-8000-000000000000"))
@pytest.mark.parametrize("kind", ("multiline", "task-path"))
def test_packaged_adapter_task_argv_bypasses_cmd(
    wrapper_fixture: Path, launcher: str, session: str | None, kind: str,
) -> None:
    adapter = DshAdapter()
    instruction = ('quote "literal"\n第二行 空格 C:\\directory with spaces\\' if kind == "multiline" else
                   adapter.task_instruction(wrapper_fixture / "中文 %QUALITY_SENTINEL% ^目录" / "transport-task.json", "a" * 64))
    if kind == "task-path":
        assert "\n" not in instruction  # The normal adapter instruction is reachable without LF.
    endpoint = adapter_endpoint(wrapper_fixture, [str(wrapper_fixture / "tools/slk" / launcher)], session)
    command = adapter.command(endpoint, instruction)
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PROCESSOR_ARCHITECTURE"}}
    environment.update(DEEPSEEK_API_KEY="LOCAL-TEST-NOT-A-KEY", DSH_RUNTIME_ROOT=str(wrapper_fixture / "adapter mutable"),
                       DSH_AGENTS_HOME=str(wrapper_fixture / "adapter agents"),
                       PATH=str(Path(os.environ["SystemRoot"]) / "System32"), QUALITY_SENTINEL="EXPANDED_NOT_LITERAL")
    if session:
        environment["SLK_DSH_SESSION_ID"] = session
    completed = finish(spawn(command, cwd=str(wrapper_fixture), env=environment,
                             process_kwargs=windows_no_window_kwargs()), None)
    assert completed.returncode == 23, completed.stderr
    expected = ["--profile", "headless"] + (["--session-id", session] if session else []) + [instruction]
    assert json.loads(completed.stdout)["args"] == expected
    assert command[:8] == [str(PS51), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(wrapper_fixture / "tools/slk/runtime/dsh/dsh-slk.ps1")]


@pytest.mark.parametrize("case", ("legacy", "similar-name", "explicit-prefix", "relative"))
def test_adapter_preserves_unmatched_and_explicit_commands(tmp_path: Path, case: str) -> None:
    root = tmp_path / "tools/slk"
    (root / "bin").mkdir(parents=True)
    if case != "legacy":
        (root / "scripts").mkdir()
        (root / "scripts/local_package_metadata.py").write_text("layout fixture only", encoding="utf-8")
    command = [str(root / "bin/dsh-slk.cmd")]
    if case == "similar-name":
        command = [str(root / "bin/custom-dsh-slk.cmd")]
    elif case == "explicit-prefix":
        command.append("explicit-prefix")
    elif case == "relative":
        command = ["tools/slk/bin/dsh-slk.cmd"]
    assert DshAdapter().command(adapter_endpoint(tmp_path, command), "exact") == command + [
        "RUN-A-worker", "--profile", "headless", "exact"]


def wrapper_call(root: Path, args: list[str], *, session: str | None = None, default_data: bool = False,
                 legacy_node: str | None = None) -> subprocess.CompletedProcess:
    wrapper = root / "tools/slk/runtime/dsh/dsh-slk.ps1"
    values = [str(wrapper), "instance-a", *args]
    script = "& " + " ".join("'" + value.replace("'", "''") + "'" for value in values)
    script += "; exit $LASTEXITCODE"
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PROCESSOR_ARCHITECTURE"}}
    environment.update(DEEPSEEK_API_KEY="LOCAL-TEST-NOT-A-KEY", DSH_RUNTIME_ROOT=str(root / "mutable data"),
                       DSH_AGENTS_HOME=str(root / "explicit agents"))
    if legacy_node:
        environment["PATH"] = str(Path(legacy_node).parent) + os.pathsep + str(Path(os.environ["SystemRoot"]) / "System32")
    if default_data:
        environment.pop("DSH_RUNTIME_ROOT")
    if session:
        environment["SLK_DSH_SESSION_ID"] = session
    return subprocess.run([str(PS51), "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                          env=environment, cwd=root, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False, creationflags=subprocess.CREATE_NO_WINDOW)


def test_ps51_actual_node_receives_lossless_argv_and_exit_code(wrapper_fixture: Path) -> None:
    task = 'quote "literal"\n第二行 空格 C:\\directory with spaces\\'
    args = ["--profile", "headless", task]
    completed = wrapper_call(wrapper_fixture, args)
    assert completed.returncode == 23, completed.stderr
    facts = json.loads(completed.stdout)
    assert facts["args"] == args
    assert Path(facts["home"]).is_relative_to(wrapper_fixture / "mutable data")
    assert facts["agents"] == str(wrapper_fixture / "explicit agents")
    assert not (Path(facts["home"]) / "settings.yaml").exists()


def test_bundled_facade_maps_exact_resume_and_refuses_environment_mismatch(wrapper_fixture: Path) -> None:
    session = "session-00000000-0000-4000-8000-000000000000"
    completed = wrapper_call(wrapper_fixture, ["--profile", "headless", "--resume", session, "继续"], session=session)
    assert completed.returncode == 23, completed.stderr
    facts = json.loads(completed.stdout)
    assert facts["args"] == ["--profile", "headless", "--session-id", session, "继续"]
    assert "trusted" not in facts
    refused = wrapper_call(wrapper_fixture, ["--profile", "headless", "--resume", session, "must not run"], session="different")
    assert refused.returncode != 0 and not refused.stdout
    assert "does not match" in refused.stderr


def test_bundled_dsh_defaults_mutable_data_outside_replaced_roots(wrapper_fixture: Path) -> None:
    completed = wrapper_call(wrapper_fixture, ["--profile", "headless", "task"], default_data=True)
    assert completed.returncode == 23
    facts = json.loads(completed.stdout)
    assert Path(facts["home"]).is_relative_to(wrapper_fixture / "tools/slk/data/dsh")


@pytest.mark.parametrize("missing_part", ("node.exe", "node", "public-cli"))
def test_bundled_dsh_missing_product_has_no_legacy_fallback(wrapper_fixture: Path, missing_part: str) -> None:
    runtime = wrapper_fixture / "tools/slk/runtime"
    original = (runtime / "dsh/node_modules/@deepseek-ai/dsh/lib/bin.js" if missing_part == "public-cli"
                else runtime / "node" if missing_part == "node" else runtime / "node/node.exe")
    missing = original.with_name(original.name + ".absent")
    original.rename(missing)
    try:
        completed = wrapper_call(wrapper_fixture, ["--profile", "headless", "must not run"])
        assert completed.returncode != 0 and not completed.stdout
        diagnostic = "DSH public CLI is missing" if missing_part == "public-cli" else "Node runtime is missing"
        assert diagnostic in completed.stderr
    finally:
        missing.rename(original)


def test_legacy_dsh_with_public_cli_keeps_legacy_dispatch(tmp_path: Path) -> None:
    directory = tmp_path / "tools/slk/runtime/dsh"
    (directory / "node_modules/@deepseek-ai/dsh/lib").mkdir(parents=True)
    (directory / "node_modules/@deepseek-ai/dsh/lib/bin.js").write_text("unused legacy public CLI", encoding="utf-8")
    (directory / "node_modules/.bin").mkdir()
    (directory / "node_modules/.bin/dsh.cmd").write_text("@echo LEGACY_FALLBACK_REACHED\n@exit /b 29\n", encoding="utf-8")
    shutil.copy2(ROOT / "integrations/dsh/dsh-slk.ps1", directory / "dsh-slk.ps1")
    # Supply only the new probe contract to this deliberately legacy launcher.
    # A bundled Node would change its layout identity and defeat this regression.
    prepared = prepared_runtimes(tmp_path / "legacy-fixture", runnable_registration=True)
    shutil.copytree(prepared["native_probe_runtime"], directory.parent / "native-probe")
    shutil.copytree(prepared["dsh_runtime"] / "node_modules/@deepseek-ai/dsh-app-boot",
                    directory / "node_modules/@deepseek-ai/dsh-app-boot")
    shutil.copy2(prepared["dsh_runtime"] / "package.json", directory / "package.json")
    data = tmp_path / "mutable data/runs/instance-a/home"
    data.mkdir(parents=True)
    (data / "settings.yaml").write_text("existing scratch legacy settings", encoding="utf-8")
    completed = wrapper_call(tmp_path, ["--profile", "headless", "task"],
                             legacy_node=os.environ.get("SLK_TEST_NODE_EXE") or shutil.which("node"))
    assert completed.returncode == 29, completed.stderr
    assert completed.stdout.strip() == "LEGACY_FALLBACK_REACHED"


def test_isolated_checker_bridge_imports_sibling_without_site_path(tmp_path: Path) -> None:
    directory = tmp_path / "ocrv"
    directory.mkdir()
    for name in ("slk_checker_decision.py", "slk_checker_adapter.py"):
        shutil.copy2(ROOT / "integrations/ocrv" / name, directory / name)
    transport = tmp_path / "transport.pyz"
    transport.write_bytes(b"non-executed transport inventory; discovery does not call it")
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    completed = subprocess.run([sys.executable, "-I", "-B", str(directory / "slk_checker_decision.py"),
                                "--transport", str(transport)],
        input=json.dumps({"jsonrpc":"2.0", "id":1, "method":"tools/list"})+"\n", cwd=tmp_path,
        env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert completed.returncode == 0, completed.stderr
    tools = json.loads(completed.stdout)["result"]["tools"]
    assert {tool["name"] for tool in tools} == {"slk_checker_decide", "slk_read_evidence"}
    assert "CHECKER_NATIVE_PROCESS_UNCONFIRMED" in completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr


def test_prepared_dsh_never_packages_mutable_account_or_session_root(tmp_path: Path, monkeypatch) -> None:
    inputs = prepared_runtimes(tmp_path / "prepared")
    mutable = inputs['dsh_runtime'] / 'runs'
    mutable.mkdir()
    (mutable / 'account.json').write_bytes(b'scratch private sentinel, must not be copied')
    (inputs['dsh_runtime'] / 'README.md').write_bytes(b'legitimate unused source documentation')
    original = os.scandir

    def guarded(path):
        assert Path(path) != mutable and mutable not in Path(path).parents
        return original(path)

    monkeypatch.setattr(os, 'scandir', guarded)
    built = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package",
                          python_runtime=fake_python(tmp_path / "python"), **inputs)
    assert not (built / 'tools/slk/runtime/dsh/runs').exists()


def test_ocrv_native_selection_preserves_explicit_override_and_legacy(tmp_path: Path, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("closure_ocrv", ROOT / "integrations/ocrv/slk_checker_adapter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "__file__", str(tmp_path / "slk_checker_adapter.py"))
    monkeypatch.delenv("OCRV_SLK_COMMAND_JSON", raising=False)
    assert module._ocr_command()[-1] == str(tmp_path / "ocr-slk.ps1")
    program = tmp_path / "bin/opencodereview.exe"
    program.parent.mkdir()
    program.write_bytes(b"inventory only, never executed")
    assert module._ocr_command() == [str(program)]
    monkeypatch.setenv("OCRV_SLK_COMMAND_JSON", '["explicit.exe","exact argument"]')
    assert module._ocr_command() == ["explicit.exe", "exact argument"]


def package(tmp_path: Path) -> Path:
    return build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package",
                         python_runtime=fake_python(tmp_path / "python"),
                         **prepared_runtimes(tmp_path / "prepared"))


def test_complete_runtime_products_are_required(tmp_path: Path) -> None:
    with pytest.raises(PackageError, match="Node runtime"):
        build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package",
                      python_runtime=fake_python(tmp_path / "python"))


def test_runtime_inventory_and_relative_launchers(tmp_path: Path) -> None:
    built = package(tmp_path)
    assert verify(built, package_mode=True)["status"] == "PASS"
    manifest = json.loads((built / "install-manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "slk.install-manifest/v1"
    paths = {entry["path"] for entry in manifest["files"]}
    for runtime, program in (("node", "node.exe"), ("ocrv", "bin/opencodereview.exe"),
                             ("temporal", "temporal.exe")):
        assert f"tools/slk/runtime/{runtime}/{program}" in paths
        assert f"tools/slk/runtime/{runtime}/LICENSE" in paths
    assert "tools/slk/runtime/dsh/package-lock.json" in paths
    assert "tools/slk/runtime/dsh/dsh-slk.cmd" in paths
    assert not any(path.startswith("tools/slk/data/") for path in paths)
    for launcher in ("dsh-slk.cmd", "slk-checker.cmd", "slk-temporal.cmd",
                     "slk-temporal-worker.cmd", "slk-temporal-start.cmd", "slk-temporal-admit.cmd",
                     "slk-temporal-delivery.cmd", "slk-temporal-recover.cmd"):
        assert f"tools/slk/bin/{launcher}" in paths


@pytest.mark.parametrize("name", ("node", "dsh", "ocrv", "temporal", "git", "native-probe"))
def test_new_runtime_inventory_is_exact_and_hash_bound(tmp_path: Path, name: str) -> None:
    built = package(tmp_path)
    extra = built / "tools/slk/runtime" / name / "unexpected.dat"
    extra.write_bytes(b"unlisted")
    with pytest.raises(VerificationError, match="missing or extra"):
        verify(built, package_mode=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
@pytest.mark.parametrize("name", ("dsh",))
def test_new_runtime_rejects_junction_before_descendant_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str,
) -> None:
    import _winapi
    inputs = prepared_runtimes(tmp_path / "prepared")
    outside = tmp_path / "outside"
    outside.mkdir()
    parent = inputs[name + "_runtime"] / "node_modules" if name == "dsh" else inputs[name + "_runtime"]
    junction = parent / "external"
    _winapi.CreateJunction(str(outside), str(junction))
    original = os.scandir

    def guarded(path):
        assert Path(path) != junction and junction not in Path(path).parents
        return original(path)

    monkeypatch.setattr(os, "scandir", guarded)
    with pytest.raises(PackageError, match="reparse|symbolic"):
        build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package",
                      python_runtime=fake_python(tmp_path / "python"), **inputs)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
@pytest.mark.parametrize("name", ("node", "ocrv", "temporal"))
def test_native_product_ignores_unselected_junction_subtrees(tmp_path: Path, monkeypatch, name: str) -> None:
    import _winapi
    inputs = prepared_runtimes(tmp_path / "prepared")
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = inputs[name + "_runtime"] / "unused-developer-tree"
    _winapi.CreateJunction(str(outside), str(junction))
    original = os.scandir

    def guarded(path):
        assert Path(path) != junction and junction not in Path(path).parents
        return original(path)

    monkeypatch.setattr(os, "scandir", guarded)
    built = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package",
                          python_runtime=fake_python(tmp_path / "python"), **inputs)
    assert not (built / "tools/slk/runtime" / name / junction.name).exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_native_product_refuses_selected_junction_ancestor_before_file_io(tmp_path: Path, monkeypatch) -> None:
    import _winapi
    inputs = prepared_runtimes(tmp_path / "prepared")
    product = inputs["ocrv_runtime"]
    original_bin = product / "bin"
    outside = tmp_path / "selected-bin"
    original_bin.rename(outside)
    _winapi.CreateJunction(str(outside), str(original_bin))
    with pytest.raises(PackageError, match="reparse|symbolic"):
        build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "package",
                      python_runtime=fake_python(tmp_path / "python"), **inputs)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
def test_verifier_refuses_runtime_junction_before_hashing_external_file(tmp_path: Path, monkeypatch) -> None:
    import _winapi
    from scripts import verify_local_install as verifier
    built = package(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "external.dat"
    target.write_bytes(b"scratch-only external content")
    junction = built / "tools/slk/runtime/dsh/external"
    _winapi.CreateJunction(str(outside), str(junction))
    manifest_path = built / "install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative = "tools/slk/runtime/dsh/external/external.dat"
    manifest["files"].append({"path": relative, "size": target.stat().st_size, "sha256": sha256(target)})
    manifest["files"].sort(key=lambda entry: entry["path"])
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    original = verifier.sha256

    def guarded(path):
        assert junction not in path.parents, "external bytes were hashed"
        return original(path)

    monkeypatch.setattr(verifier, "sha256", guarded)
    with pytest.raises(VerificationError, match="reparse|symbolic"):
        verify(built, package_mode=True)
