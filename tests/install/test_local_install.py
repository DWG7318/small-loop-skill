from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.build_local_package import ARTIFACT_NAMES, build_package as _build_package
from scripts.validate_repository import EXPECTED_SKILLS
from scripts.tool_artifacts import begin_release_build, seal_release_build
from runtime_fixtures import prepared_runtimes
from scripts.local_package_metadata import INSTALL_SCRIPT_NAMES, LAUNCHER_NAMES, python_path_contents, read_version


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts" / "install_local.ps1"
VERIFY = ROOT / "scripts" / "verify_local_install.py"
RUNTIME_SCRIPTS = ("install_local.ps1", "verify_local_install.py", "local_package_metadata.py", "configure_ocrv.py")


def build_package(repository: Path, artifacts: Path, output: Path) -> Path:
    """Legacy-override tests use simulated runtime bytes, never default readiness."""
    runtime = artifacts.parent / "fake-python"
    runtime.mkdir(exist_ok=True)
    for name in ("python.exe", "python314.dll", "python314.zip", "python314._pth"):
        (runtime / name).write_bytes(b"simulated Python inventory\n")
    return _build_package(repository, artifacts, output, python_runtime=runtime,
                          **prepared_runtimes(artifacts.parent / "prepared", runnable_registration=True))


def fake_artifacts(root: Path) -> Path:
    """Simulated artifacts exercise installation only, not executable/runtime readiness."""
    root.mkdir()
    begin_release_build(ROOT, root, build={"commands": ["SIMULATED INVENTORY ONLY; no compiler executed"]})
    for name in ARTIFACT_NAMES:
        (root / name).write_bytes(f"new-{name}-4.4.5\n".encode())
    seal_release_build(ROOT, root)
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
    relative = Path("tools/slk/runtime/python/python.exe")
    target = codex_home / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"old simulated Python bytes\n")
    expected[relative.as_posix()] = target.read_bytes()
    relative = Path("tools/slk/share/small-loop-skill/VERSION")
    target = codex_home / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"4.2.2\n")
    expected[relative.as_posix()] = b"4.2.2\n"
    return expected


def run_installer(
    package: Path,
    codex_home: Path,
    *,
    corrupt: str | None = None,
    entry: Path = INSTALLER,
    cwd: Path = ROOT,
    ocrv_user_home: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell 7 is unavailable")
    command = [
        pwsh, "-NoProfile", "-NonInteractive", "-File", str(entry),
        "-PackageRoot", str(package), "-CodexHome", str(codex_home),
        "-PythonExecutable", sys.executable,
        "-DshUserHome", str(codex_home.parent / (codex_home.name + "-dsh-home")),
    ]
    environment = os.environ.copy()
    if ocrv_user_home is not None:
        command.extend(["-OcrvUserHome", str(ocrv_user_home)])
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONDONTWRITEBYTECODE", None)
    if corrupt:
        command.extend(["-TestCorruptStagedRelativePath", corrupt])
        environment["SLK_INSTALL_TEST_MODE"] = "1"
    return subprocess.run(
        command,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def unpack_simulated_package(tmp_path: Path) -> Path:
    """Deliver a real archive of a package containing explicitly simulated binaries."""
    built = build_package(ROOT, fake_artifacts(tmp_path / "artifacts"), tmp_path / "built")
    archive = shutil.make_archive(str(tmp_path / "delivery"), "zip", built)
    package = tmp_path / "unpacked"
    shutil.unpack_archive(archive, package)
    # ZIP extraction drops POSIX execution bits needed by the real Node fixture.
    node = Path("tools/slk/runtime/node/node.exe")
    shutil.copymode(built / node, package / node)
    shutil.rmtree(built)
    return package


def run_delivered_verifier(root: Path, *, package_mode: bool = False) -> subprocess.CompletedProcess[str]:
    arguments = [
        sys.executable, "-E", "-s", str(root / "tools/slk/scripts/verify_local_install.py"),
        "--root", str(root),
    ]
    if package_mode:
        arguments.append("--package-mode")
    # -E ignores PYTHONPATH/PYTHONHOME; neither the script directory nor cwd is the repository.
    return subprocess.run(
        arguments, cwd=root.parent, text=True, encoding="utf-8", capture_output=True, check=False,
    )


def test_simulated_unpacked_package_verifier_runs_without_source_repository(tmp_path: Path) -> None:
    package = unpack_simulated_package(tmp_path)

    completed = run_delivered_verifier(package, package_mode=True)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS SLK_LOCAL_INSTALL " + read_version() in completed.stdout
    assert {path.name for path in (package / "tools/slk/scripts").iterdir()} == set(RUNTIME_SCRIPTS)


@pytest.mark.parametrize("missing", (
    "tools/slk/share/small-loop-skill/VERSION",
    "tools/slk/scripts/local_package_metadata.py",
))
def test_simulated_delivered_verifier_reports_missing_dependencies(tmp_path: Path, missing: str) -> None:
    package = unpack_simulated_package(tmp_path)
    (package / missing).unlink()

    completed = run_delivered_verifier(package, package_mode=True)

    assert completed.returncode == 2, completed.stdout + completed.stderr
    assert "FAIL SLK_LOCAL_INSTALL" in completed.stdout
    assert "PASS SLK_LOCAL_INSTALL" not in completed.stdout + completed.stderr


def test_simulated_packaged_entry_installs_repeatedly_and_installed_verifier_is_standalone(tmp_path: Path) -> None:
    package = unpack_simulated_package(tmp_path)
    codex_home = tmp_path / "isolated-codex-home"
    retained = {
        "config.toml": b"unrelated user configuration\n",
        "skills/unrelated/SKILL.md": b"unrelated user Skill\n",
        "docs/custom/owner.md": b"unrelated user docs\n",
        "tools/slk/config/owner.json": b'{"preserve":true}\n',
        "tools/slk/data/owner.db": b"simulated user data, never a real runtime database\n",
    }
    for relative, data in retained.items():
        target = codex_home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    entry = package / "tools/slk/scripts/install_local.ps1"

    for _ in range(2):
        result = run_installer(package, codex_home, entry=entry, cwd=tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        for relative, data in retained.items():
            assert (codex_home / relative).read_bytes() == data

    # Installed verification cannot fall back to the unpacked package or source tree.
    shutil.rmtree(package)
    completed = run_delivered_verifier(codex_home)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PASS SLK_LOCAL_INSTALL " + read_version() in completed.stdout
    assert {path.name for path in (codex_home / "tools/slk/scripts").iterdir()} == set(RUNTIME_SCRIPTS)


@pytest.mark.parametrize("script", RUNTIME_SCRIPTS)
@pytest.mark.parametrize("damage", ("missing", "corrupt", "unlisted"))
@pytest.mark.parametrize("installed", (False, True), ids=("package", "installed"))
def test_simulated_tree_rejects_missing_corrupt_or_unlisted_install_scripts(
    tmp_path: Path, script: str, damage: str, installed: bool,
) -> None:
    package = unpack_simulated_package(tmp_path)
    root = package
    manifest_path = package / "install-manifest.json"
    if installed:
        root = tmp_path / "isolated-codex-home"
        result = run_installer(
            package, root, entry=package / "tools/slk/scripts/install_local.ps1", cwd=tmp_path,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        manifest_path = root / "tools/slk/install-manifest.json"
    relative = f"tools/slk/scripts/{script}"
    target = root / relative
    if damage == "corrupt":
        target.write_bytes(target.read_bytes() + b"\n# corrupted script bytes\n")
    else:
        target.unlink()
        if damage == "unlisted":
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"] = [entry for entry in manifest["files"] if entry["path"] != relative]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    # A trusted verifier must reject even a missing verifier/helper in the target tree.
    arguments = [sys.executable, str(VERIFY), "--root", str(root)]
    if not installed:
        arguments.append("--package-mode")
    completed = subprocess.run(
        arguments,
        cwd=ROOT, text=True, encoding="utf-8", capture_output=True, check=False,
    )
    assert completed.returncode != 0, completed.stdout + completed.stderr
    assert "FAIL SLK_LOCAL_INSTALL" in completed.stdout


def test_trusted_source_entry_rejects_package_verifier_that_only_claims_pass(tmp_path: Path) -> None:
    package = unpack_simulated_package(tmp_path)
    untrusted_verifier = package / "tools/slk/scripts/verify_local_install.py"
    untrusted_verifier.write_text('print("PASS SLK_LOCAL_INSTALL fake, unverified claim")\n', encoding="utf-8")
    codex_home = tmp_path / "isolated-codex-home"
    previous = seed_old_install(codex_home)

    result = run_installer(package, codex_home, cwd=tmp_path)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "managed file hash mismatch: tools/slk/scripts/verify_local_install.py" in result.stderr
    for relative, data in previous.items():
        assert (codex_home / relative).read_bytes() == data
    reports = list((codex_home / ".tmp").glob("slk-install-failed-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["status"] == "UNCHANGED"
    assert report["active_tree_verified"] is True


def test_simulated_packaged_entry_rolls_back_scripts_with_previous_install(tmp_path: Path) -> None:
    package = unpack_simulated_package(tmp_path)
    codex_home = tmp_path / "isolated-codex-home"
    entry = package / "tools/slk/scripts/install_local.ps1"
    first = run_installer(package, codex_home, entry=entry, cwd=tmp_path)
    assert first.returncode == 0, first.stdout + first.stderr
    manifest = json.loads((codex_home / "tools/slk/install-manifest.json").read_text(encoding="utf-8"))
    expected = {entry["path"]: (codex_home / entry["path"]).read_bytes() for entry in manifest["files"]}

    failed = run_installer(
        package, codex_home, entry=entry, cwd=tmp_path,
        corrupt="tools/slk/scripts/verify_local_install.py",
    )

    assert failed.returncode != 0, failed.stdout + failed.stderr
    for relative, data in expected.items():
        assert (codex_home / relative).read_bytes() == data
    reports = list((codex_home / ".tmp").glob("slk-install-failed-*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    assert report["status"] == "ROLLED_BACK"
    assert report["active_tree_verified"] is True
    assert run_delivered_verifier(codex_home).returncode == 0


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
    assert "PASS SLK_LOCAL_INSTALL " + read_version() in completed.stdout
    assert (codex_home / "tools/slk/share/small-loop-skill/VERSION").read_text(encoding="utf-8").strip() == read_version()
    assert (codex_home / "docs/state/SLK-STATE.md").read_bytes() == (
        codex_home / "tools/slk/share/small-loop-skill/docs/state/SLK-STATE.md"
    ).read_bytes()
    launcher = codex_home / "tools/slk/bin/slk-transport.cmd"
    assert launcher.is_file()
    assert '"%~dp0..\\runtime\\python\\python.exe" "%~dp0slk-transport.pyz" %*' in launcher.read_text(encoding="utf-8")


def test_native_configuration_is_explicit_opt_in(tmp_path):
    package = unpack_simulated_package(tmp_path)
    codex = tmp_path / "codex"
    user = tmp_path / "native user"
    target = user / ".opencodereview/config.json"
    target.parent.mkdir(parents=True)
    original = b'{"telemetry":false,"empty":[],"mcp_servers":{"other":{"args":[]}}}'
    target.write_bytes(original)
    assert run_installer(package, codex).returncode == 0
    assert target.read_bytes() == original
    installed = run_installer(package, codex, ocrv_user_home=user)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    value = json.loads(target.read_bytes())
    assert value["telemetry"] is False and value["empty"] == []
    assert value["mcp_servers"]["other"] == {"args": []}
    assert value["mcp_servers"]["slk_checker_decision"]["command"] == str(codex / "tools/slk/runtime/python/python.exe")
    before = target.stat().st_mtime_ns
    again = run_installer(package, codex, ocrv_user_home=user)
    assert again.returncode == 0, again.stdout + again.stderr
    assert target.stat().st_mtime_ns == before


def test_invalid_opt_in_configuration_rolls_back_existing_code(tmp_path):
    package = unpack_simulated_package(tmp_path)
    codex = tmp_path / "codex"
    previous = seed_old_install(codex)
    user = tmp_path / "native user"
    config = user / ".opencodereview/config.json"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"invalid JSON original")
    failed = run_installer(package, codex, ocrv_user_home=user)
    assert failed.returncode != 0
    assert config.read_bytes() == b"invalid JSON original"
    for relative, data in previous.items():
        assert (codex / relative).read_bytes() == data
    report = json.loads(next((codex / ".tmp").glob("slk-install-failed-*.json")).read_text(encoding="utf-8"))
    assert report["status"] == "ROLLED_BACK" and report["active_tree_verified"]


@pytest.mark.parametrize("phase", ("backup", "install"))
def test_partial_root_move_failure_preserves_all_previous_roots(tmp_path, phase):
    """Run the installer's actual mutation/catch tail, without a fake package gate."""
    powershell = shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell required")
    harness = tmp_path / "partial-move.ps1"
    script = r'''
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$codexRoot = Join-Path $PSScriptRoot 'codex'
$package = Join-Path $PSScriptRoot 'unused-package'
$stage = Join-Path $codexRoot '.tmp/stage'
$backupRoot = Join-Path $codexRoot 'tools/slk/backups/fixture'
$failureReport = Join-Path $codexRoot '.tmp/failure.json'
$managedRoots = @('skills/first', 'tools/slk/scripts', 'tools/slk/runtime/python')
foreach ($relative in $managedRoots) {
    foreach ($tree in @($codexRoot, $stage)) {
        $directory = Join-Path $tree $relative
        [void][IO.Directory]::CreateDirectory($directory)
        [IO.File]::WriteAllText((Join-Path $directory 'sentinel.txt'), $(if ($tree -eq $codexRoot) {'OLD:'} else {'NEW:'}) + $relative)
    }
}
[void][IO.Directory]::CreateDirectory($backupRoot)
$configState = $null; $configStateJson = ''; $selectedOcrvHome = ''
$probeState = $null; $probeStateJson = ''
$probeRegistrationAttempted = $false
$targetVersion = 'fixture'; $mutated = $false
$backedUpRoots = [System.Collections.Generic.List[string]]::new()
$installedRoots = [System.Collections.Generic.List[string]]::new()
$text = [IO.File]::ReadAllText('__INSTALLER__')
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw 'source parse failed' }
foreach ($name in @('Get-FullPath', 'Get-Sha256', 'Assert-Within', 'Get-ManagedState')) {
    $definition = $ast.Find({ param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$oldState = Get-ManagedState $codexRoot $managedRoots
$global:injected = $false
$global:failureTarget = Join-Path $(if ('__PHASE__' -eq 'backup') {$codexRoot} else {$stage}) 'tools/slk/scripts'
function Move-Item {
    [CmdletBinding()]
    param([string]$LiteralPath, [string]$Destination)
    if (-not $global:injected -and $LiteralPath -eq $global:failureTarget) {
        $global:injected = $true
        throw 'FIXTURE second root Move failed before moving'
    }
    Microsoft.PowerShell.Management\Move-Item @PSBoundParameters
}
$start = $text.IndexOf('    $mutated = $true', [StringComparison]::Ordinal)
if ($start -lt 0) { throw 'source mutation boundary not found' }
. ([scriptblock]::Create("try {`n" + $text.Substring($start)))
'''
    harness.write_text(script.replace("__INSTALLER__", str(INSTALLER).replace("'", "''")).replace("__PHASE__", phase), encoding="utf-8")
    completed = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-File", str(harness)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    for relative in ("skills/first", "tools/slk/scripts", "tools/slk/runtime/python"):
        sentinel = tmp_path / "codex" / relative / "sentinel.txt"
        assert sentinel.is_file(), f"old unmoved root lost: {relative}; {completed.stderr}"
        assert sentinel.read_text() == "OLD:" + relative
    report = json.loads((tmp_path / "codex/.tmp/failure.json").read_text(encoding="utf-8-sig"))
    assert report["status"] == "ROLLED_BACK" and report["active_tree_verified"] is True


def _encoding_package(tmp_path):
    """Closed tiny inventory, no repository MANIFEST/build or real-runtime copy."""
    package = tmp_path / "package 中文 %ENC_LITERAL% ^tiny"
    package.mkdir()
    def write(relative, data):
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for name in EXPECTED_SKILLS:
        write(f"skills/{name}/SKILL.md", b"encoding-only inventory fixture\n")
    for name in (*ARTIFACT_NAMES, *LAUNCHER_NAMES):
        write(f"tools/slk/bin/{name}", b"inventory fixture, not executed\n")
    for name in INSTALL_SCRIPT_NAMES:
        write(f"tools/slk/scripts/{name}", (ROOT / "scripts" / name).read_bytes())
    for name in ("python.exe", "python314.dll", "python314.zip"):
        write(f"tools/slk/runtime/python/{name}", b"inventory fixture, explicit test Python override\n")
    write("tools/slk/runtime/python/python314._pth", python_path_contents("python314.zip").encode())
    for name, product in prepared_runtimes(tmp_path / "tiny-prepared", runnable_registration=True).items():
        for file in product.rglob("*"):
            if file.is_file():
                write(f"tools/slk/runtime/{name.removesuffix('_runtime').replace('_', '-')}/{file.relative_to(product).as_posix()}", file.read_bytes())
    write("tools/slk/runtime/ocrv/slk_checker_decision.py", b"inventory fixture, not executed\n")
    write("tools/slk/share/small-loop-skill/VERSION", (read_version() + "\n").encode())
    write("docs/state/encoding-fixture.md", b"not a release package\n")
    entries = [{"path": file.relative_to(package).as_posix(), "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
                "size": file.stat().st_size} for file in sorted(package.rglob("*")) if file.is_file()]
    entries.sort(key=lambda entry: entry["path"])
    (package / "install-manifest.json").write_text(json.dumps({"schema_version": "slk.install-manifest/v1",
        "version": read_version(), "skill_count": len(EXPECTED_SKILLS), "artifact_count": len(ARTIFACT_NAMES),
        "files": entries}), encoding="utf-8")
    return package


def _ps51():
    path = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if os.name != "nt" or not path.is_file():
        pytest.skip("Windows PowerShell5.1 required")
    return path


def _ps51_module_path(mode):
    native = str(_ps51().parent / "Modules")
    if mode == "native":
        return native
    pwsh = shutil.which("pwsh")
    if not pwsh or not (Path(pwsh).parent / "Modules/Microsoft.PowerShell.Utility/Microsoft.PowerShell.Utility.psd1").is_file():
        pytest.skip("PowerShell7 modules required for the actual mixed-module regression")
    return str(Path(pwsh).parent / "Modules") + os.pathsep + native


def test_ps51_mixed_module_path_hashes_managed_files_without_module_autoload(tmp_path):
    root = tmp_path / "state 中文 %ENC_LITERAL% ^home"
    files = {"direct.bin": b"\x00binary\xff\n", "nested/empty.bin": b"",
             "nested/中文 %ENC_LITERAL% ^bytes.bin": bytes(range(256)) * 4097}
    for relative, data in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    before = {relative: (root / relative).stat().st_mtime_ns for relative in files}
    harness = tmp_path / "mixed modules.ps1"
    script = r'''
$beforeModulePath = $env:PSModulePath
$text = [IO.File]::ReadAllText('__INSTALLER__')
$start = $text.IndexOf('$ErrorActionPreference =', [StringComparison]::Ordinal)
$end = $text.IndexOf('$package = Get-FullPath $PackageRoot', [StringComparison]::Ordinal)
. ([scriptblock]::Create($text.Substring($start, $end - $start)))
$hashCommandAvailable = $false
try { $hashCommandAvailable = $null -ne (Get-Command Get-FileHash -ErrorAction Stop) } catch { }
$state = Get-ManagedState '__ROOT__' @('direct.bin', 'nested')
[ordered]@{state=($state | ConvertFrom-Json); module_path=$env:PSModulePath; before_module_path=$beforeModulePath; hash_command_available=$hashCommandAvailable} | ConvertTo-Json -Compress
'''
    harness.write_text(script.replace("__INSTALLER__", str(INSTALLER).replace("'", "''"))
        .replace("__ROOT__", str(root).replace("'", "''")), encoding="utf-8-sig")
    environment = os.environ.copy()
    environment["PSModulePath"] = _ps51_module_path("mixed")
    environment["ENC_LITERAL"] = "WRONG_EXPANSION"
    completed = subprocess.run([str(_ps51()), "-NoProfile", "-NonInteractive", "-File", str(harness)],
        env=environment, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    # PS5.1 startup itself may add the shared WindowsPowerShell Modules directory.
    # Require the incompatible PS7 prefix to remain and the installer not to sanitize it.
    assert result["module_path"] == result["before_module_path"]
    assert result["module_path"].split(os.pathsep)[0] == environment["PSModulePath"].split(os.pathsep)[0]
    assert str(_ps51().parent / "Modules") in result["module_path"].split(os.pathsep)
    assert result["hash_command_available"] is False
    assert {name.replace("\\", "/"): value for name, value in result["state"].items()} == {
        relative: hashlib.sha256(data).hexdigest() for relative, data in files.items()}
    assert completed.stderr == b""
    assert all((root / relative).read_bytes() == data and (root / relative).stat().st_mtime_ns == before[relative]
               for relative, data in files.items())


@pytest.mark.parametrize("opt_in", (False, True))
@pytest.mark.parametrize("module_path", ("native", "mixed"), ids=("native_modules", "mixed_module_path"))
def test_ps51_headless_install_receipt_is_strict_utf8_and_reachable(tmp_path, opt_in, module_path):
    package = _encoding_package(tmp_path)
    codex = tmp_path / "installed 中文 %ENC_LITERAL% ^home"
    if module_path == "mixed":
        seed_old_install(codex)  # Real upgrade hashes both existing files and directory contents.
    environment = os.environ.copy()
    environment["PSModulePath"] = _ps51_module_path(module_path)
    environment["ENC_LITERAL"] = "WRONG_EXPANSION"
    command = [str(_ps51()), "-NoProfile", "-NonInteractive", "-File", str(INSTALLER),
        "-PackageRoot", str(package), "-CodexHome", str(codex), "-PythonExecutable", sys.executable,
        "-DshUserHome", str(tmp_path / "DSH 中文 %ENC_LITERAL% ^home")]
    user = tmp_path / "native 中文 %ENC_LITERAL% ^user"
    config = user / ".opencodereview/config.json"
    config.parent.mkdir(parents=True)
    original = b'{"keep_false":false,"keep_empty":[],"mcp_servers":{"slk_checker_decision":{"future":[]}}}'
    config.write_bytes(original)
    if opt_in:
        command.extend(["-OcrvUserHome", str(user)])
    completed = subprocess.run(command,
        env=environment, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.returncode == 0, completed.stderr
    receipt = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    backup = Path(receipt["backup_root"])
    assert backup.parent == codex / "tools/slk/backups"
    assert backup.is_dir() and "%ENC_LITERAL%" in str(backup) and "^home" in str(backup)
    assert receipt["status"] == "INSTALLED"
    assert receipt["dsh_probe"]["load_state"] == "PENDING_RELOAD"
    assert Path(receipt["dsh_probe"]["home"]) == tmp_path / "DSH 中文 %ENC_LITERAL% ^home"
    assert (Path(receipt["dsh_probe"]["home"]) / "cordis.patch.yml").is_file()
    assert completed.stderr.decode("utf-8", errors="strict") == ""
    if opt_in:
        merged = json.loads(config.read_bytes())
        assert merged["keep_false"] is False and merged["keep_empty"] == []
        assert merged["mcp_servers"]["slk_checker_decision"]["future"] == []
        assert merged["mcp_servers"]["slk_checker_decision"]["command"] == str(codex / "tools/slk/runtime/python/python.exe")
        assert (backup / "ocrv-config.original.json").read_bytes() == original
    else:
        assert config.read_bytes() == original


@pytest.mark.parametrize("module_path", ("native", "mixed"), ids=("native_modules", "mixed_module_path"))
def test_ps51_headless_config_failure_keeps_utf8_error_and_rolls_back(tmp_path, module_path):
    package = _encoding_package(tmp_path)
    codex = tmp_path / "previous 中文 %ENC_LITERAL% ^home"
    previous = seed_old_install(codex)
    user = tmp_path / "native 中文 %ENC_LITERAL% ^user"
    config = user / ".opencodereview/config.json"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"invalid JSON original")
    environment = os.environ.copy()
    environment["PSModulePath"] = _ps51_module_path(module_path)
    completed = subprocess.run([str(_ps51()), "-NoProfile", "-NonInteractive", "-File", str(INSTALLER),
        "-PackageRoot", str(package), "-CodexHome", str(codex), "-PythonExecutable", sys.executable,
        "-DshUserHome", str(tmp_path / "DSH 中文 %ENC_LITERAL% ^home"),
        "-OcrvUserHome", str(user)], env=environment, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.returncode == 1
    assert completed.stdout.decode("utf-8", errors="strict") == ""
    assert str(codex / ".tmp") in completed.stderr.decode("utf-8", errors="strict")
    assert config.read_bytes() == b"invalid JSON original"
    for relative, data in previous.items():
        assert (codex / relative).read_bytes() == data
    report = json.loads(next((codex / ".tmp").glob("slk-install-failed-*.json")).read_text(encoding="utf-8-sig"))
    assert report["status"] == "ROLLED_BACK" and report["active_tree_verified"] is True


@pytest.mark.parametrize("interpreter", ("explicit", "isolated"))
@pytest.mark.parametrize("exit_code", (0, 7))
def test_ps51_hidden_python_utf8_streams_and_exact_argv(tmp_path, interpreter, exit_code):
    python = sys.executable
    if interpreter == "isolated":
        runtime = os.environ.get("SLK_TEST_PYTHON_RUNTIME")
        if not runtime or not (Path(runtime) / "python.exe").is_file():
            pytest.skip("set SLK_TEST_PYTHON_RUNTIME to the prepared isolated Windows embed")
        python = str(Path(runtime) / "python.exe")
    # Extract the real preamble/helper, rather than mirroring their implementation.
    harness = tmp_path / "helper 中文 %ENC_LITERAL% ^probe.ps1"
    argument = '中文 %ENC_LITERAL% ^path "quoted"\nline with trailing\\'
    program = ("import json,sys;print(json.dumps({'argv':sys.argv[1:],'isolated':sys.flags.isolated,"
               "'utf8_mode':sys.flags.utf8_mode,'encoding':sys.stdout.encoding},ensure_ascii=False));"
               "sys.stderr.write('子进程错误中文');sys.exit(" + str(exit_code) + ")")
    def literal(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = r'''
$PythonExecutable = __PYTHON__
$text = [IO.File]::ReadAllText(__INSTALLER__)
$start = $text.IndexOf('$ErrorActionPreference =', [StringComparison]::Ordinal)
$end = $text.IndexOf('function Get-FullPath', [StringComparison]::Ordinal)
. ([scriptblock]::Create($text.Substring($start, $end - $start)))
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$parseErrors)
foreach ($name in @('ConvertTo-NativeArgument', 'Invoke-HiddenPython')) {
    $definition = $ast.Find({param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name
    }, $true)
    . ([scriptblock]::Create($definition.Extent.Text))
}
try {
    $value = Invoke-HiddenPython $PSScriptRoot @('-c', __PROGRAM__, __ARGUMENT__)
    [ordered]@{value=$value; error=$null} | ConvertTo-Json -Compress
} catch {
    [ordered]@{value=$null; error=$_.Exception.Message} | ConvertTo-Json -Compress
}
[Console]::Error.WriteLine(__ARGUMENT__)
'''
    script = script.replace("__PYTHON__", literal(python)).replace("__INSTALLER__", literal(INSTALLER))
    script = script.replace("__PROGRAM__", literal(program)).replace("__ARGUMENT__", literal(argument))
    harness.write_text(script, encoding="utf-8-sig", newline="\n")  # Keep the argv fixture's LF, with PS5.1 BOM input.
    environment = os.environ.copy()
    environment["PSModulePath"] = str(_ps51().parent / "Modules")
    environment.update(ENC_LITERAL="WRONG_EXPANSION", PYTHONIOENCODING="ascii")
    completed = subprocess.run([str(_ps51()), "-NoProfile", "-NonInteractive", "-File", str(harness)],
        env=environment, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout.decode("utf-8", errors="strict"))
    assert completed.stderr.decode("utf-8", errors="strict") == argument + "\r\n"
    if exit_code:
        assert "子进程错误中文" in result["error"] and "中文 %ENC_LITERAL% ^path" in result["error"]
    else:
        child = json.loads(result["value"])
        assert child["argv"] == [argument] and child["utf8_mode"] == 1 and child["encoding"] == "utf-8"
        assert child["isolated"] == (1 if interpreter == "isolated" else 0)
