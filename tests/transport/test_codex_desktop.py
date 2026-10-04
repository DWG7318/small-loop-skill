from dataclasses import asdict
import hashlib
import json
import sys
from pathlib import Path

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.codex import CodexAdapter
from slk_transport.contracts import Endpoint
from slk_transport.dispatcher import dispatch_once
from slk_transport.evidence import AttemptStore
from slk_transport.native_activity import inspect_native_activity, validate_native_task_activity
from slk_transport.adapters.codex_desktop import DesktopClient
from slk_transport.jsonrpc import JsonRpcProcess
from test_codex_adapter import codex_endpoint, supervisor_envelope

SERVER = Path(__file__).with_name("fake_desktop_mcp.py")


def prepared(tmp_path, monkeypatch, mode="normal"):
    raw = asdict(codex_endpoint(tmp_path))
    raw["address"]["command"] = [sys.executable, str(SERVER)]
    raw["address"]["startup_timeout_seconds"] = 1
    raw["address"]["desktop"] = {"caller_thread_id": "caller-exact", "model": "gpt-6.1-sol", "reasoning_effort": "xhigh", "plugin_sha256": hashlib.sha256(SERVER.read_bytes()).hexdigest()}
    monkeypatch.setenv("CODEX_THREAD_ID", "caller-exact")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "inherited-native-pipe")
    monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "Codex Desktop")
    monkeypatch.setenv("FAKE_DESKTOP_MODE", mode)
    return Endpoint.from_dict(raw)


def test_desktop_native_readback_starts_exact_same_thread_without_cli_takeover(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch)
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    result = CodexAdapter().deliver(endpoint, envelope, attempt)
    assert result.status == "completed"
    assert result.native_identity["thread_id"] == "thr_exact"
    assert result.native_identity["turn_id"] == "turn-new"
    assert result.native_identity["platform_item_id"] == "item-exact"
    start = json.loads((attempt.root / "started.json").read_text())
    assert start["native_task"]["kind"] == "codex-desktop-turn"
    calls = [json.loads(s) for s in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    sent = [c for c in calls if c["name"] == "send_message_to_thread"]
    assert len(sent) == 1
    assert sent[0]["arguments"]["model"] == "gpt-6.1-sol"
    assert sent[0]["arguments"]["thinking"] == "xhigh"
    assert sent[0]["_meta"]["codex_thread_id"] == "caller-exact"


def test_desktop_activity_is_bounded_exact_platform_evidence_not_host_pid(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch)
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    CodexAdapter().deliver(endpoint, envelope, attempt)
    path = attempt.root / "native-activity.json"
    value = json.loads(path.read_text())
    validate_native_task_activity(value, adapter=endpoint.adapter, run_id=envelope.run_id,
        cell_id=envelope.cell_id, message_id=envelope.message_id,
        native_task_id="thr_exact:turn-new:item-exact")
    assert value["status"] == "COMPLETED" and value["last_event"]["kind"] == "DESKTOP_TURN_OBSERVED"
    assert path.stat().st_size < 2048
    assert "prompt" not in path.read_text() and "caller-exact" not in path.read_text()
    observed = inspect_native_activity(attempt.root / "started.json")
    assert observed["status"] == "COMPLETED_WITHOUT_TERMINAL" and observed["error"] is None


def test_desktop_polling_does_not_retain_whole_repeated_thread_history(monkeypatch):
    client = object.__new__(DesktopClient)
    client.messages = []
    def receive(self, timeout):
        value = {"result": {"content": "large native result"}}
        self.messages.append(value)
        return value
    monkeypatch.setattr(JsonRpcProcess, "_receive", receive)
    for _ in range(1000): client._receive(1)
    assert len(client.messages) <= 1


@pytest.mark.parametrize("mode,code", [
    ("wrong-thread", "CODEX_THREAD_ID_MISMATCH"), ("wrong-host", "CODEX_THREAD_ID_MISMATCH"),
    ("unconfirmed", "CODEX_DESKTOP_READBACK_UNPROVED"),
    ("wrong-caller", "CODEX_DESKTOP_READBACK_UNPROVED"), ("wrong-payload", "CODEX_DESKTOP_READBACK_UNPROVED"),
    ("truncated", "CODEX_DESKTOP_READBACK_UNPROVED"), ("duplicate", "CODEX_DESKTOP_READBACK_AMBIGUOUS"),
    ("malformed-status", "CODEX_DESKTOP_PROTOCOL_INVALID"),
    ("malformed-item", "CODEX_DESKTOP_PROTOCOL_INVALID"),
    ("malformed-items", "CODEX_DESKTOP_PROTOCOL_INVALID"),
    ("failed-turn", "CODEX_TURN_FAILED"),
    ("old-item", "CODEX_DESKTOP_READBACK_UNPROVED"),
    ("ambiguous-active", "CODEX_ACTIVE_WRITER_UNRESOLVED"),
])
def test_desktop_does_not_turn_accepted_or_wrong_evidence_into_start(tmp_path, monkeypatch, mode, code):
    endpoint = prepared(tmp_path, monkeypatch, mode)
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    with pytest.raises(AdapterError) as error:
        CodexAdapter().deliver(endpoint, envelope, attempt)
    assert error.value.error_code == code
    assert not (attempt.root / "started.json").exists()


@pytest.mark.parametrize("key,value", [("CODEX_THREAD_ID", "someone-else"), ("CODEX_APP_TOOLS_PIPE_PATH", ""), ("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "cli")])
def test_desktop_host_context_must_be_inherited_and_exact(tmp_path, monkeypatch, key, value):
    endpoint = prepared(tmp_path, monkeypatch)
    monkeypatch.setenv(key, value)
    envelope = supervisor_envelope()
    with pytest.raises(AdapterError) as error:
        CodexAdapter().deliver(endpoint, envelope, AttemptStore(tmp_path / "attempts").create(envelope))
    assert error.value.error_code == "CODEX_DESKTOP_HOST_UNAVAILABLE"
    assert not (tmp_path / "native-calls.jsonl").exists()


def test_desktop_exact_retry_returns_immutable_result_without_second_message(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch)
    envelope = supervisor_envelope()
    args = (asdict(endpoint), asdict(envelope), tmp_path / "attempts")
    first = dispatch_once(*args, adapters={endpoint.adapter: CodexAdapter()})
    second = dispatch_once(*args, adapters={endpoint.adapter: CodexAdapter()})
    assert first == second and first.status == "completed"
    calls = [json.loads(s) for s in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert sum(c["name"] == "send_message_to_thread" for c in calls) == 1


def test_active_desktop_receives_new_item_on_same_native_turn_without_writer_takeover(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch, "active")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    result = CodexAdapter().deliver(endpoint, envelope, attempt)
    assert result.status == "completed" and result.native_identity["turn_id"] == "turn-old"
    calls = [json.loads(s) for s in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert {c["name"] for c in calls} == {"read_thread", "send_message_to_thread"}
    assert sum(c["name"] == "send_message_to_thread" for c in calls) == 1
