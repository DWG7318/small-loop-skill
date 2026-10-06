from __future__ import annotations

import errno
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "integrations" / "ocrv"


def _load_adapter():
    specification = importlib.util.spec_from_file_location(
        "slk_test_ocrv_adapter", INTEGRATION / "slk_checker_adapter.py"
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _load_recovery():
    specification = importlib.util.spec_from_file_location(
        "slk_test_ocrv_recovery", INTEGRATION / "slk_checker_recovery.py"
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.path.insert(0, str(INTEGRATION))
    try:
        specification.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_compact_evidence_discloses_path_omission_and_keeps_source(tmp_path: Path) -> None:
    module = _load_adapter()
    evidence = tmp_path / "worker-result.json"
    paths = [f"src/file-{index:04d}.py" for index in range(1005)]
    evidence.write_text(
        json.dumps({"next_payload": {"changed_paths": paths}}), encoding="utf-8"
    )

    compact = module._compact_evidence(evidence)

    assert compact["summary"]["changed_paths"] == paths[:1000]
    assert compact["summary"]["changed_paths_summary"] == {
        "total": 1005,
        "shown": 1000,
        "omitted": 5,
        "source": str(evidence.resolve()),
    }


def test_normalized_findings_exclude_provider_thinking_but_keep_evidence() -> None:
    module = _load_adapter()
    findings = module._normalized_findings({
        "comments": [{
            "severity": "HIGH",
            "message": "criterion violated",
            "path": "src/a.py",
            "line": 7,
            "evidence_refs": ["review.json"],
            "thinking": "duplicated hidden chain " * 1000,
            "reasoning": "more duplicated analysis",
        }]
    })

    assert findings == [{
        "severity": "HIGH",
        "message": "criterion violated",
        "path": "src/a.py",
        "line": 7,
        "evidence_refs": ["review.json"],
    }]


def powershell() -> str:
    executable = shutil.which("pwsh") or shutil.which("powershell")
    if not executable:
        pytest.skip("PowerShell is unavailable")
    return executable


def run_script(script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [powershell(), "-NoProfile", "-NonInteractive", "-File", str(script), *arguments],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )


def test_ocrv_recovery_wrapper_preserves_the_existing_d1_entry() -> None:
    wrapper = (INTEGRATION / "slk-checker.cmd").read_text(encoding="utf-8")
    assert '"%~1"=="--slk-post-d1"' in wrapper
    assert '"%~1"=="--slk-complete-d1"' in wrapper
    assert "slk_checker_post_d1.py" in wrapper
    assert '"%~1"=="--slk-worker-recovery"' in wrapper
    assert '"%~1"=="--slk-existing-terminal"' in wrapper
    assert '"%~1"=="--slk-committed-terminal"' in wrapper
    assert '"%~1"=="--slk-resume-incomplete-checker"' in wrapper
    assert '"%~1"=="--slk-resume-terminal-budget"' in wrapper
    assert '"%~1"=="--slk-fresh-terminal-budget-review"' in wrapper
    assert '"%~1"=="--slk-continue-consumed-partial"' in wrapper
    assert '"%~1"=="--slk-resume-consumed-partial"' in wrapper
    assert '"%~1"=="--slk-refine-consumed-partial"' in wrapper
    assert '"%~1"=="--slk-consume-existing-partial"' in wrapper
    assert "slk_checker_recovery.py" in wrapper
    assert "slk_checker_adapter.py" in wrapper


def test_terminal_budget_resolves_the_canonical_launcher_to_a_real_zipapp(
    tmp_path: Path,
) -> None:
    module = _load_recovery()
    runtime = tmp_path / "bin"
    runtime.mkdir()
    zipapp = runtime / "slk-transport.pyz"
    built = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_transport_zipapp.py"),
            "--output",
            str(zipapp),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    launcher = runtime / "slk-transport.cmd"
    launcher.write_text(
        '@echo off\npython "%~dp0slk-transport.pyz" %*\nexit /b %ERRORLEVEL%\n',
        encoding="utf-8",
    )

    assert module._transport_runtime_path([str(launcher)]) == zipapp.resolve()

    if os.name == "nt":
        launched = subprocess.run(
            [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", str(launcher), "--help"],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert launched.returncode == 0, launched.stdout + launched.stderr
        assert "resume-terminal-budget-checker" in launched.stdout


def test_fresh_review_resolves_transport_only_from_its_hash_bound_source(tmp_path: Path) -> None:
    module = _load_recovery()
    source = tmp_path / "source.json"
    source.write_text(json.dumps({"transport_command": ["managed-transport"]}), encoding="utf-8")
    request = {
        "source_request_path": str(source.resolve()),
        "source_request_sha256": module._sha256(source),
    }

    assert module._request_transport_command(request, fresh=True) == ["managed-transport"]
    request["source_request_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source request"):
        module._request_transport_command(request, fresh=True)


def test_checker_capability_freezes_the_managed_terminal_budget_target() -> None:
    capability = json.loads(
        (INTEGRATION / "slk-checker-capabilities.json").read_text(encoding="utf-8")
    )
    identity = capability["terminal_budget_resume_identity"]

    assert identity["ocrv_version"] == "v1.12.12"
    assert identity["provider"] == "dashscope-tokenplan"
    assert identity["model"] == "qwen3.8-max"
    assert identity["rule_config_sha256"] == (
        "03406157658b5549e2088b45059ea9cc7528c38eeb30f268b3decb6538737640"
    )
    assert identity["managed_rule_files"] == {
        "slk/slk-d1-rule.json": (
            "fb7ab06a64579a185a683a120c39e13ee82625aa29354b0df837462fcd4e166b"
        ),
        "slk/SLK-D1-REVIEW.md": (
            "0ffdba9cf7c5934f4966f35e08a6000b7c630ce33a5d7d1e2626d4f13ed65693"
        ),
    }


def test_ocrv_atomic_replace_retries_busy_and_cleans_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    target = tmp_path / "native-activity.json"
    adapter._write_json_atomic(target, {"sequence": 1})
    real_replace = os.replace
    attempts = 0

    def replace(source, destination):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError(errno.EBUSY, "busy once")
        real_replace(source, destination)

    monkeypatch.setattr(adapter.os, "replace", replace)
    monkeypatch.setattr(adapter.time, "sleep", lambda _seconds: None)

    adapter._write_json_atomic(target, {"sequence": 2})

    assert attempts == 2
    assert json.loads(target.read_text(encoding="utf-8")) == {"sequence": 2}
    assert list(tmp_path.glob("native-activity.json.*.tmp")) == []


def test_ocrv_atomic_replace_exhaustion_keeps_previous_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    target = tmp_path / "native-activity.json"
    adapter._write_json_atomic(target, {"sequence": 1})
    attempts = 0

    def replace(_source, _destination):
        nonlocal attempts
        attempts += 1
        raise OSError(errno.EPERM, "still busy")

    monkeypatch.setattr(adapter.os, "replace", replace)
    monkeypatch.setattr(adapter.time, "sleep", lambda _seconds: None)

    with pytest.raises(OSError) as failure:
        adapter._write_json_atomic(target, {"sequence": 2})

    assert failure.value.errno == errno.EPERM
    assert attempts == 3
    assert json.loads(target.read_text(encoding="utf-8")) == {"sequence": 1}
    assert list(tmp_path.glob("native-activity.json.*.tmp")) == []


def test_post_d1_wrapper_is_headless_strips_credentials_and_writes_exact_phase_result(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "fake_transport.py"
    fake.write_text(
        """import json, os, sys
assert sys.argv[1] == 'checker-escalate-d1'
assert 'SLK_ROLE_CREDENTIAL' not in os.environ
assert 'SLK_OVERWATCHER_CREDENTIAL' not in os.environ
print(json.dumps({'schema_version':'slk.checker-post-d1-result/v1','status':'DESKTOP_BRIDGE_REQUIRED'}))
""",
        encoding="utf-8",
    )
    attempt_root = tmp_path / "attempts"
    attempt_root.mkdir()
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "slk.checker-post-d1-request/v1",
                "post_d1_invocation_id": "suffix-1",
                "escalation_attempt_root": str(attempt_root),
                "transport_command": [sys.executable, str(fake)],
            }
        ),
        encoding="utf-8",
    )
    output = attempt_root / ".checker-post-d1" / "suffix-1" / "prepared-result.json"
    environment = os.environ.copy()
    environment["SLK_ROLE_CREDENTIAL"] = "must-not-leak"
    environment["SLK_OVERWATCHER_CREDENTIAL"] = "must-not-leak"

    completed = subprocess.run(
        [
            sys.executable,
            str(INTEGRATION / "slk_checker_post_d1.py"),
            "--slk-post-d1",
            "--request",
            str(request),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "DESKTOP_BRIDGE_REQUIRED"


def test_complete_d1_wrapper_is_headless_strips_credentials_and_writes_exact_result(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "fake_transport.py"
    fake.write_text(
        """import json, os, sys
assert sys.argv[1] == 'checker-complete-d1'
assert '--host-receipt' in sys.argv
assert 'SLK_ROLE_CREDENTIAL' not in os.environ
assert 'SLK_OVERWATCHER_CREDENTIAL' not in os.environ
print(json.dumps({'schema_version':'slk.checker-completion-result/v1','status':'CHECKER_COMPLETION_COMMITTED'}))
""",
        encoding="utf-8",
    )
    attempt_root = tmp_path / "attempts"
    attempt_root.mkdir()
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "slk.checker-completion-request/v1",
                "completion_invocation_id": "completion-1",
                "handoff_attempt_root": str(attempt_root),
                "transport_command": [sys.executable, str(fake)],
            }
        ),
        encoding="utf-8",
    )
    output = attempt_root / ".checker-completion" / "completion-1" / "committed-result.json"
    host_receipt = tmp_path / "host-receipt.json"
    host_receipt.write_text("{}", encoding="utf-8")
    environment = os.environ.copy()
    environment["SLK_ROLE_CREDENTIAL"] = "must-not-leak"
    environment["SLK_OVERWATCHER_CREDENTIAL"] = "must-not-leak"

    completed = subprocess.run(
        [
            sys.executable,
            str(INTEGRATION / "slk_checker_post_d1.py"),
            "--slk-complete-d1",
            "--request",
            str(request),
            "--output",
            str(output),
            "--host-receipt",
            str(host_receipt),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "CHECKER_COMPLETION_COMMITTED"


def test_complete_d1_wrapper_preserves_desktop_bridge_as_pending_suffix(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "fake_transport.py"
    fake.write_text(
        """import json, sys
assert sys.argv[1] == 'checker-complete-d1'
assert '--host-receipt' not in sys.argv
print(json.dumps({'schema_version':'slk.checker-completion-result/v1','status':'DESKTOP_BRIDGE_REQUIRED'}))
""",
        encoding="utf-8",
    )
    attempt_root = tmp_path / "attempts"
    attempt_root.mkdir()
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "slk.checker-completion-request/v1",
                "completion_invocation_id": "completion-bridge-1",
                "handoff_attempt_root": str(attempt_root),
                "transport_command": [sys.executable, str(fake)],
            }
        ),
        encoding="utf-8",
    )
    output = attempt_root / ".checker-completion" / "completion-bridge-1" / "result.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(INTEGRATION / "slk_checker_post_d1.py"),
            "--slk-complete-d1",
            "--request",
            str(request),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "DESKTOP_BRIDGE_REQUIRED"


def test_existing_terminal_wrapper_reuses_checker_command_without_publishing_new_start(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "fake_transport.py"
    fake.write_text(
        """import json, os, sys
assert sys.argv[1] == 'checker-recover-worker'
assert os.environ['SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID'] == 'checker-a'
assert os.environ['SLK_OCRV_RECOVERY_INVOCATION_ID'] == 'recovery-a'
assert os.environ['SLK_OCRV_RECOVERY_ENDPOINT_VERSION'] == '2'
assert 'SLK_ROLE_CREDENTIAL' not in os.environ
assert 'SLK_NATIVE_START_RECEIPT' not in os.environ
assert 'SLK_NATIVE_START_CONTEXT' not in os.environ
print(json.dumps({'schema_version':'slk.ocrv-worker-recovery-result/v1','status':'CHECKER_D1_RECORDED'}))
""",
        encoding="utf-8",
    )
    output = tmp_path / "checker-result.json"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
            "schema_version": "slk.ocrv-worker-recovery-request/v1",
            "recovery_invocation_id": "recovery-a",
            "result_path": str(output),
            "transport_command": [sys.executable, str(fake)],
            }
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID"] = "checker-a"
    environment["SLK_OCRV_RECOVERY_INVOCATION_ID"] = "recovery-a"
    environment["SLK_OCRV_RECOVERY_ENDPOINT_VERSION"] = "2"
    environment["SLK_ROLE_CREDENTIAL"] = "must-not-leak"
    start_receipt = tmp_path / "must-not-exist.json"
    environment["SLK_NATIVE_START_RECEIPT"] = str(start_receipt)
    environment["SLK_NATIVE_START_CONTEXT"] = "{}"

    completed = subprocess.run(
        [
            sys.executable,
            str(INTEGRATION / "slk_checker_recovery.py"),
            "--slk-existing-terminal",
            "--request",
            str(request),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["status"] == "CHECKER_D1_RECORDED"
    assert not start_receipt.exists()


def test_committed_terminal_wrapper_uses_the_dedicated_internal_consumer(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "fake_transport.py"
    fake.write_text(
        """import json, os, sys
assert sys.argv[1] == 'checker-record-committed-terminal'
assert 'SLK_ROLE_CREDENTIAL' not in os.environ
assert 'SLK_NATIVE_START_RECEIPT' not in os.environ
assert 'SLK_NATIVE_START_CONTEXT' not in os.environ
print(json.dumps({'schema_version':'slk.ocrv-committed-terminal-result/v1','status':'CHECKER_D1_RECORDED'}))
""",
        encoding="utf-8",
    )
    output = tmp_path / "checker-result.json"
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "schema_version": "slk.ocrv-committed-terminal-request/v1",
                "result_path": str(output),
                "transport_command": [sys.executable, str(fake)],
            }
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID"] = "checker-a"
    environment["SLK_OCRV_RECOVERY_INVOCATION_ID"] = "recovery-a"
    environment["SLK_OCRV_RECOVERY_ENDPOINT_VERSION"] = "2"

    completed = subprocess.run(
        [
            sys.executable,
            str(INTEGRATION / "slk_checker_recovery.py"),
            "--slk-committed-terminal",
            "--request",
            str(request),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["status"] == "CHECKER_D1_RECORDED"


def test_ocrv_integration_installs_hashes_and_rolls_back_all_managed_files(tmp_path: Path) -> None:
    ocrv = tmp_path / "ocrv"
    ocrv.mkdir()
    adapter = b"accepted-adapter\n"
    original_wrapper = b"@echo off\r\npython old.py %*\r\n"
    original_capabilities = b'{"old":true}\n'
    (ocrv / "slk_checker_adapter.py").write_bytes(adapter)
    (ocrv / "slk-checker.cmd").write_bytes(original_wrapper)
    (ocrv / "slk-checker-capabilities.json").write_bytes(original_capabilities)

    installed = run_script(INTEGRATION / "install.ps1", "-OcrvRoot", str(ocrv))

    assert installed.returncode == 0, installed.stdout + installed.stderr
    receipt = json.loads(installed.stdout.strip())
    backup = Path(receipt["backup_root"])
    assert receipt["version"] == "4.4.2"
    assert (ocrv / "slk_checker_adapter.py").read_bytes() == (
        INTEGRATION / "slk_checker_adapter.py"
    ).read_bytes()
    assert (ocrv / "slk-checker.cmd").read_bytes() == (INTEGRATION / "slk-checker.cmd").read_bytes()
    assert (ocrv / "slk_checker_recovery.py").read_bytes() == (
        INTEGRATION / "slk_checker_recovery.py"
    ).read_bytes()
    assert (ocrv / "slk_checker_post_d1.py").read_bytes() == (
        INTEGRATION / "slk_checker_post_d1.py"
    ).read_bytes()
    assert (ocrv / "slk-checker-capabilities.json").read_bytes() == (
        INTEGRATION / "slk-checker-capabilities.json"
    ).read_bytes()
    assert (ocrv / "slk-native-activity-capabilities.json").read_bytes() == (
        INTEGRATION / "slk-native-activity-capabilities.json"
    ).read_bytes()
    assert (ocrv / "OCRV-SLK-CONFIGURATION.md").read_bytes() == (
        INTEGRATION / "OCRV-SLK-CONFIGURATION.md"
    ).read_bytes()
    assert set(receipt["installed_sha256"]) == {
        "slk_checker_adapter.py",
        "slk-checker.cmd",
        "slk_checker_post_d1.py",
        "slk_checker_recovery.py",
        "slk-checker-capabilities.json",
        "slk-native-activity-capabilities.json",
        "OCRV-SLK-CONFIGURATION.md",
    }

    rolled_back = run_script(
        INTEGRATION / "rollback.ps1",
        "-OcrvRoot",
        str(ocrv),
        "-BackupRoot",
        str(backup),
    )

    assert rolled_back.returncode == 0, rolled_back.stdout + rolled_back.stderr
    assert (ocrv / "slk-checker.cmd").read_bytes() == original_wrapper
    assert not (ocrv / "slk_checker_post_d1.py").exists()
    assert not (ocrv / "slk_checker_recovery.py").exists()
    assert (ocrv / "slk_checker_adapter.py").read_bytes() == adapter
    assert (ocrv / "slk-checker-capabilities.json").read_bytes() == original_capabilities
    assert not (ocrv / "slk-native-activity-capabilities.json").exists()
    assert not (ocrv / "OCRV-SLK-CONFIGURATION.md").exists()
