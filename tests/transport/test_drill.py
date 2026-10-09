from __future__ import annotations

import sys
import json
from dataclasses import replace
from pathlib import Path

import pytest

from scripts.build_transport_zipapp import build_zipapp
from scripts.run_transport_drill import run_drill
from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.codex import CodexAdapter
from slk_transport.adapters.codex_desktop import MATERIAL_PREFIX, _material_prompt, _prepare_prompt
from slk_transport.evidence import AttemptStore
from slk_transport.jsonrpc import JsonRpcProcess
from test_codex_adapter import codex_endpoint, supervisor_envelope


TESTS = Path(__file__).parent


def fake_config(tmp_path: Path) -> dict[str, object]:
    return {
        "evidence_root": str(tmp_path / "evidence"),
        "workspace_root": str(tmp_path / "workspaces"),
        "codex_command": [sys.executable, str(TESTS / "fake_app_server.py"), "normal"],
        "ocrv_command": [sys.executable, str(TESTS / "fake_ocrv.py"), "normal"],
        "dsh_command": [sys.executable, str(TESTS / "fake_dsh.py"), "normal"],
        "timeout_seconds": 5,
    }


def test_drill_completes_four_legs_without_cross_run_data(tmp_path: Path) -> None:
    summary = run_drill(fake_config(tmp_path), live=False, run_ids=("RUN-A", "RUN-B"))

    assert summary["RUN-A"]["legs"] == ["S-C", "C-W", "W-C", "C-S"]
    assert summary["RUN-B"]["legs"] == ["S-C", "C-W", "W-C", "C-S"]
    assert summary["RUN-A"]["probe_nonce"] == "RUN-A-NONCE"
    assert summary["RUN-B"]["probe_nonce"] == "RUN-B-NONCE"
    assert summary["RUN-A"]["final_token_sequence"] == 4
    assert summary["RUN-B"]["final_token_sequence"] == 4
    assert summary["crossovers"] == []

    a = summary["RUN-A"]["native_identities"]
    b = summary["RUN-B"]["native_identities"]
    assert a["worker"]["instance_id"] != b["worker"]["instance_id"]
    assert a["worker"]["session_id"] != b["worker"]["session_id"]
    assert a["checker"]["review_invocation_id"] != b["checker"]["review_invocation_id"]
    assert a["supervisor"]["thread_id"] != b["supervisor"]["thread_id"]


def test_drill_proves_failed_boundary_retains_token_and_endpoint_rebound(tmp_path: Path) -> None:
    summary = run_drill(fake_config(tmp_path), live=False, run_ids=("RUN-A",))
    run = summary["RUN-A"]

    assert run["failed_delivery"]["rejected"] is True
    assert run["failed_delivery"]["token_before"] == run["failed_delivery"]["token_after"]
    assert run["endpoint_rebound"] == {
        "retired_version_rejected": True,
        "active_version": 2,
        "active_version_completed": True,
    }


def test_drill_rejects_live_mode_until_real_runtime_bootstrap_is_supplied(tmp_path: Path) -> None:
    config = fake_config(tmp_path)

    try:
        run_drill(config, live=True, run_ids=("RUN-A",))
    except ValueError as exc:
        assert str(exc) == "live drill requires explicit real runtime endpoints"
    else:
        raise AssertionError("live mode silently used fake endpoints")


def test_live_drill_first_leg_is_started_by_exact_supervisor_agent(tmp_path: Path) -> None:
    config = fake_config(tmp_path)
    config["codex_command"] = [sys.executable, str(TESTS / "fake_app_server.py"), "execute-command"]
    config["transport_artifact"] = str(build_zipapp(tmp_path / "slk-transport.pyz"))
    config["live_endpoints"] = True
    config["codex_model"] = "gpt-6.1-sol"
    config["codex_effort"] = "xhigh"

    summary = run_drill(config, live=True, run_ids=("RUN-A", "RUN-B"))

    assert summary["RUN-A"]["supervisor_started_first_send"] is True
    assert summary["RUN-B"]["supervisor_started_first_send"] is True
    assert summary["RUN-A"]["legs"] == ["S-C", "C-W", "W-C", "C-S"]
    assert summary["RUN-B"]["legs"] == ["S-C", "C-W", "W-C", "C-S"]
    assert summary["crossovers"] == []


def test_fake_native_receiver_reads_material_before_executing_the_preserved_task(tmp_path, monkeypatch):
    endpoint = codex_endpoint(tmp_path, "execute-command")
    # Fixture startup safety only; this is not an engineering-turn wait or production policy.
    endpoint = replace(endpoint, address={**endpoint.address, "startup_timeout_seconds": 5})
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    marker = tmp_path / "receiver-read-original.txt"
    command = [sys.executable, "-c",
        f"from pathlib import Path; Path({str(marker)!r}).write_text('original task executed', encoding='utf-8')"]
    adapter = CodexAdapter()
    task = adapter._prompt(envelope, attempt) + (
        f"\n<slk-supervisor-command>{json.dumps(command)}</slk-supervisor-command>")
    monkeypatch.setattr(adapter, "_prompt", lambda *_: task)

    assert adapter.deliver(endpoint, envelope, attempt).status == "completed"

    assert marker.is_file()
    assert marker.read_text(encoding="utf-8") == "original task executed"
    assert json.loads((attempt.root / "desktop-material.json").read_bytes())["prompt"] == task


@pytest.mark.parametrize("damage", ["missing", "changed-bytes", "wrong-run", "wrong-role", "wrong-message"])
def test_fake_native_receiver_rejects_invalid_material_before_native_start(tmp_path, damage):
    endpoint = codex_endpoint(tmp_path, "execute-command")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    reference_prompt = _prepare_prompt(CodexAdapter()._prompt(envelope, attempt), envelope, attempt)
    material = attempt.root / "desktop-material.json"
    message_id = envelope.message_id
    if damage == "missing":
        material.unlink()
    elif damage == "changed-bytes":
        material.write_bytes(material.read_bytes() + b"\n")
    elif damage == "wrong-run":
        reference = json.loads(reference_prompt[len(MATERIAL_PREFIX):])
        reference["run_id"] = "OTHER-RUN"
        reference_prompt = MATERIAL_PREFIX + json.dumps(reference, ensure_ascii=False, sort_keys=True)
    elif damage == "wrong-role":
        value = json.loads(material.read_bytes())
        value["envelope"]["receiver_role"] = "worker"
        material.write_text(json.dumps(value), encoding="utf-8")
        reference_prompt = _material_prompt(material, material.read_bytes(), envelope)
    else:
        message_id = "different-message"
    client = JsonRpcProcess(endpoint.address["command"], tmp_path)
    try:
        client.request(1, "initialize", {"clientInfo": {"name": "material-reader-test"}}, 5)
        client.notify("initialized", {})

        with pytest.raises(AdapterError, match="material") as rejected:
            client.request(2, "turn/start", {"threadId": "thr_exact",
                "input": [{"type": "text", "text": reference_prompt}],
                "clientUserMessageId": message_id, "cwd": str(tmp_path)}, 5)

        assert rejected.value.error_code == "CODEX_RPC_ERROR"
        assert str(material.resolve()) in str(rejected.value).replace("\\\\", "\\")
        assert not any(item.get("method") == "turn/started" for item in client.messages)
    finally:
        client.close()
