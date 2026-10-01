from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "integrations" / "dsh"


def _powershell() -> str:
    value = shutil.which("pwsh") or shutil.which("powershell")
    if not value:
        pytest.skip("PowerShell unavailable")
    return value


def _run(script: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_powershell(), "-NoProfile", "-NonInteractive", "-File", str(script), *args],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )


def test_dsh_activity_plugin_uses_native_status_and_session_events() -> None:
    source = (INTEGRATION / "slk_native_activity.mjs").read_text(encoding="utf-8")
    wrapper = (INTEGRATION / "dsh-slk.ps1").read_text(encoding="utf-8")

    assert 'ctx.on("agent/status"' in source
    assert 'ctx.on("session/event"' in source
    assert "SLK_NATIVE_ACTIVITY_CONTEXT" in source
    assert "--patch" in wrapper
    assert "Start-Process" not in wrapper


def test_installed_dsh_can_compose_the_activity_patch_without_a_model_call() -> None:
    dsh = Path(r"D:\DSH\node_modules\.bin\dsh.cmd")
    if not dsh.is_file():
        pytest.skip("local DSH is unavailable")

    completed = subprocess.run(
        [
            str(dsh),
            "--profile",
            "headless",
            "--patch",
            str(INTEGRATION / "slk-native-activity.patch.yml"),
            "--dump-config",
        ],
        cwd=Path(r"D:\DSH"),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "slk-native-activity" in completed.stdout


def test_installed_dsh_event_signatures_match_the_activity_plugin() -> None:
    cordis = Path(r"D:\DSH\node_modules\@deepseek-ai\dsh-tool-cordis\lib\index.js")
    if not cordis.is_file():
        pytest.skip("local DSH Cordis package is unavailable")

    installed = cordis.read_text(encoding="utf-8")
    plugin = (INTEGRATION / "slk_native_activity.mjs").read_text(encoding="utf-8")

    assert "payload: { agent: Agent; status: AgentStatus }" in installed
    assert "session: Session, event: SessionEvent" in installed
    assert 'ctx.on("agent/status", ({ agent, status: next }) =>' in plugin
    assert 'ctx.on("session/event", (session, event) =>' in plugin
    assert "agent.session.id" in plugin


def test_dsh_activity_plugin_atomically_publishes_on_the_real_node_runtime(
    tmp_path: Path,
) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable")
    target = tmp_path / "native-activity.json"
    environment = os.environ.copy()
    environment["SLK_ACTIVITY_PLUGIN_URI"] = (INTEGRATION / "slk_native_activity.mjs").as_uri()
    environment["SLK_NATIVE_ACTIVITY_PATH"] = str(target)
    environment["SLK_NATIVE_ACTIVITY_CONTEXT"] = json.dumps(
        {
            "adapter": "dsh-worker",
            "run_id": "RUN-NATIVE-ATOMIC",
            "cell_id": "CELL-001",
            "message_id": "message-native-atomic",
        }
    )
    script = """
import { existsSync, readdirSync } from "node:fs";
const { apply } = await import(process.env.SLK_ACTIVITY_PLUGIN_URI);
const callbacks = new Map();
apply({ on: (name, callback) => callbacks.set(name, callback) });
callbacks.get("agent/status")({ agent: { session: { id: "session-native-atomic" } }, status: "running" });
const target = process.env.SLK_NATIVE_ACTIVITY_PATH;
const prefix = target.split(/[\\/]/).pop() + ".";
const temporary = readdirSync(new URL(".", `file:///${target.replaceAll("\\\\", "/")}`))
  .filter((name) => name.startsWith(prefix) && name.endsWith(".tmp"));
console.log(JSON.stringify({ target: existsSync(target), temporary }));
"""

    completed = subprocess.run(
        [node, "--input-type=module", "-e", script],
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
    result = json.loads(completed.stdout)
    assert result == {"target": True, "temporary": []}
    activity = json.loads(target.read_text(encoding="utf-8"))
    assert activity["native_task_id"] == "session-native-atomic"
    assert activity["sequence"] == 1


def test_dsh_integration_installs_and_rolls_back_managed_files(tmp_path: Path) -> None:
    dsh = tmp_path / "dsh"
    dsh.mkdir()
    original = b"# original wrapper\n"
    (dsh / "dsh-slk.ps1").write_bytes(original)

    installed = _run(INTEGRATION / "install.ps1", "-DshRoot", str(dsh))

    assert installed.returncode == 0, installed.stdout + installed.stderr
    receipt = json.loads(installed.stdout.strip())
    assert receipt["version"] == "4.3.6"
    for name in (
        "dsh-slk.ps1",
        "slk-native-activity.patch.yml",
        "slk_native_activity.mjs",
        "slk-worker-capabilities.json",
    ):
        assert (dsh / name).read_bytes() == (INTEGRATION / name).read_bytes()

    rolled_back = _run(
        INTEGRATION / "rollback.ps1",
        "-DshRoot",
        str(dsh),
        "-BackupRoot",
        receipt["backup_root"],
    )
    assert rolled_back.returncode == 0, rolled_back.stdout + rolled_back.stderr
    assert (dsh / "dsh-slk.ps1").read_bytes() == original
    assert not (dsh / "slk_native_activity.mjs").exists()
