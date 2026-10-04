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
    assert '"%~1"=="--slk-continue-consumed-partial"' in wrapper
    assert '"%~1"=="--slk-resume-consumed-partial"' in wrapper
    assert '"%~1"=="--slk-refine-consumed-partial"' in wrapper
    assert '"%~1"=="--slk-consume-existing-partial"' in wrapper
    assert "slk_checker_recovery.py" in wrapper
    assert "slk_checker_adapter.py" in wrapper


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
    assert receipt["version"] == "4.4.0"
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
    assert set(receipt["installed_sha256"]) == {
        "slk_checker_adapter.py",
        "slk-checker.cmd",
        "slk_checker_post_d1.py",
        "slk_checker_recovery.py",
        "slk-checker-capabilities.json",
        "slk-native-activity-capabilities.json",
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
