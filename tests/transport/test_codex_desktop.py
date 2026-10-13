from dataclasses import asdict, replace
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from slk_transport.adapters.base import AdapterError
from slk_transport.adapters.codex import CodexAdapter
from slk_transport.contracts import Endpoint, Envelope
from slk_transport.dispatcher import dispatch_once
from slk_transport.evidence import Attempt, AttemptStore
from slk_transport.native_activity import inspect_native_activity, validate_native_task_activity
from slk_transport.adapters.codex_desktop import DesktopClient, consume_desktop_readback, deliver_desktop, validate_late_desktop_start
from slk_transport.jsonrpc import JsonRpcProcess
from test_codex_adapter import codex_endpoint, supervisor_envelope

SERVER = Path(__file__).with_name("fake_desktop_mcp.py")


def prepared(tmp_path, monkeypatch, mode="normal"):
    raw = asdict(codex_endpoint(tmp_path))
    raw["address"]["command"] = [sys.executable, str(SERVER)]
    # Exercise native evidence, not one-second Python child startup under a
    # loaded Windows test/build host. This changes only the test RPC fixture.
    raw["address"]["startup_timeout_seconds"] = 10
    raw["address"]["desktop"] = {"caller_thread_id": "caller-exact", "model": "gpt-6.1-sol", "reasoning_effort": "xhigh", "plugin_sha256": hashlib.sha256(SERVER.read_bytes()).hexdigest()}
    monkeypatch.setenv("CODEX_THREAD_ID", "caller-exact")
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "inherited-native-pipe")
    monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "Codex Desktop")
    monkeypatch.setenv("FAKE_DESKTOP_MODE", mode)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    return Endpoint.from_dict(raw)


def current_desktop_plugin(tmp_path, monkeypatch, *, damage=None, revision="current"):
    """Configured bundled package fixture; never consult the user's installation."""
    home = tmp_path / "codex-home"
    marketplace = home / ("bundled-" + revision)
    plugin = marketplace / "plugins/codex-app-tools"
    (marketplace / ".agents/plugins").mkdir(parents=True)
    (plugin / ".codex-plugin").mkdir(parents=True)
    source = {"source": "local", "path": "./plugins/codex-app-tools"}
    if damage == "remote-source": source["source"] = "github"
    if damage == "escaped-package":
        outside = tmp_path / "untrusted-plugin"
        (outside / ".codex-plugin").mkdir(parents=True)
        (outside / ".codex-plugin/plugin.json").write_text(json.dumps({
            "name": "codex-app-tools", "mcpServers": "./.mcp.json"}), encoding="utf-8")
        (outside / "server.mjs").write_bytes(SERVER.read_bytes())
        source["path"] = "../../untrusted-plugin"
    entry = {"name": "codex-app-tools", "source": source}
    (marketplace / ".agents/plugins/marketplace.json").write_text(json.dumps({
        "name": "other-marketplace" if damage == "wrong-marketplace" else "openai-bundled",
        "plugins": [entry, entry] if damage == "duplicate-package" else [entry]}), encoding="utf-8")
    (plugin / ".codex-plugin/plugin.json").write_text(json.dumps({
        "name": "other-plugin" if damage == "wrong-package" else "codex-app-tools",
        "mcpServers": "elsewhere.json" if damage == "wrong-server-declaration" else "./.mcp.json"}), encoding="utf-8")
    server = plugin / "server.mjs"
    server.write_bytes(SERVER.read_bytes() + ("\n# " + revision + "\n").encode())
    if damage == "escaped-server":
        outside = tmp_path / "untrusted-server.mjs"
        server.rename(outside)
        try:
            server.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlink fixture unavailable: {exc}")
    configured = str(marketplace)
    if damage == "extended": configured = "\\\\?\\" + configured
    if damage == "relative-marketplace": configured = "relative-marketplace"
    (home / "config.toml").write_text('[marketplaces.openai-bundled]\nsource = '
        + json.dumps(configured) + '\n[plugins."codex-app-tools@openai-bundled"]\nenabled = '
        + ("false" if damage == "disabled" else "true") + '\n', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(home))
    return server


@pytest.mark.parametrize("extended", [False, pytest.param(True, marks=pytest.mark.skipif(os.name != "nt", reason="Windows path"))])
def test_retired_desktop_plugin_uses_enabled_current_package_without_rewriting_delivery(tmp_path, monkeypatch, extended):
    endpoint = prepared(tmp_path, monkeypatch)
    endpoint.address["command"][1] = str(tmp_path / "retired-plugin/server.mjs")
    original = asdict(endpoint)
    server = current_desktop_plugin(tmp_path, monkeypatch, damage="extended" if extended else None)
    envelope = supervisor_envelope()
    args = (original, asdict(envelope), tmp_path / "attempts")
    result = dispatch_once(*args, adapters={endpoint.adapter: CodexAdapter()})
    assert result.status == "completed", result
    root = tmp_path / "attempts" / envelope.run_id / envelope.message_id
    provenance = json.loads((root / "desktop-send.json").read_text())["native_runtime"]
    assert provenance["requested_command"] == original["address"]["command"]
    assert provenance["requested_plugin_sha256"] == original["address"]["desktop"]["plugin_sha256"]
    assert provenance["command"] == [sys.executable, str(server)]
    assert provenance["plugin_sha256"] == hashlib.sha256(server.read_bytes()).hexdigest()
    assert provenance["address_sha256"] == hashlib.sha256(json.dumps(original["address"], ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert json.loads((root / "endpoint.json").read_text()) == original == asdict(endpoint)
    assert dispatch_once(*args, adapters={endpoint.adapter: CodexAdapter()}) == result
    calls = [json.loads(line) for line in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert sum(call["name"] == "send_message_to_thread" for call in calls) == 1


@pytest.mark.parametrize("damage", ["disabled", "wrong-marketplace", "duplicate-package", "remote-source",
    "escaped-package", "wrong-package", "wrong-server-declaration", "relative-marketplace", "escaped-server"])
def test_retired_desktop_plugin_rejects_untrusted_current_source_before_native_calls(tmp_path, monkeypatch, damage):
    endpoint = prepared(tmp_path, monkeypatch)
    endpoint.address["command"][1] = str(tmp_path / "retired-plugin/server.mjs")
    current_desktop_plugin(tmp_path, monkeypatch, damage=damage)
    attempt = AttemptStore(tmp_path / "attempts").create(supervisor_envelope())
    with pytest.raises(AdapterError) as error:
        CodexAdapter().deliver(endpoint, supervisor_envelope(), attempt)
    assert error.value.error_code == "CODEX_DESKTOP_RUNTIME_UNAVAILABLE"
    assert not (tmp_path / "native-calls.jsonl").exists()


def test_present_changed_plugin_does_not_silently_select_current_package(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch)
    endpoint.address["desktop"]["plugin_sha256"] = "0" * 64
    current_desktop_plugin(tmp_path, monkeypatch)
    with pytest.raises(AdapterError) as error:
        CodexAdapter().deliver(endpoint, supervisor_envelope(), AttemptStore(tmp_path / "attempts").create(supervisor_envelope()))
    assert error.value.error_code == "CODEX_DESKTOP_PLUGIN_CHANGED"
    assert not (tmp_path / "native-calls.jsonl").exists()


def test_retired_plugin_and_node_preserve_original_node_rebind_contract(tmp_path, monkeypatch):
    from test_supervisor_notification import desktop_node_fixture
    raw, _notice, _projection, node = desktop_node_fixture(tmp_path, monkeypatch)
    Path(raw["address"]["command"][1]).unlink()
    server = current_desktop_plugin(tmp_path, monkeypatch)
    server.write_text("import {spawn} from 'node:child_process'; const p=spawn(" + json.dumps(sys.executable)
        + "," + json.dumps([str(SERVER)]) + ",{stdio:'inherit',windowsHide:true});"
        + "p.on('exit',code=>process.exit(code===null?1:code));", encoding="utf-8")
    envelope = supervisor_envelope()
    result = dispatch_once(raw, asdict(envelope), tmp_path / "attempts", adapters={"codex-app-server": CodexAdapter()})
    assert result.status == "completed", result
    root = tmp_path / "attempts" / envelope.run_id / envelope.message_id
    rebound = json.loads((root / "command-rebind.json").read_text())
    assert rebound["requested_command"] == raw["address"]["command"]
    assert rebound["plugin_sha256"] == raw["address"]["desktop"]["plugin_sha256"]
    assert rebound["resolved_command"] == [node, str(server)]
    actual = json.loads((root / "desktop-send.json").read_text())["native_runtime"]
    assert actual["command"] == rebound["resolved_command"]
    assert actual["plugin_sha256"] == hashlib.sha256(server.read_bytes()).hexdigest()


@pytest.mark.parametrize("retired_before_send", [False, True])
def test_retired_plugin_late_readback_records_actual_reader_without_second_send(tmp_path, monkeypatch, retired_before_send):
    endpoint = prepared(tmp_path, monkeypatch, "unconfirmed")
    old_server = tmp_path / "original-server.mjs"
    old_server.write_bytes(SERVER.read_bytes())
    endpoint.address["command"][1] = str(old_server)
    endpoint.address["startup_timeout_seconds"] = 1
    if retired_before_send:
        old_server.unlink()
        old_server = current_desktop_plugin(tmp_path, monkeypatch)
    envelope = supervisor_envelope()
    result = dispatch_once(asdict(endpoint), asdict(envelope), tmp_path / "attempts", adapters={endpoint.adapter: CodexAdapter()})
    assert result.error_code == "CODEX_DESKTOP_READBACK_UNPROVED", result
    attempt = Attempt(tmp_path / "attempts" / envelope.run_id / envelope.message_id)
    originals = {name: (attempt.root / name).read_bytes() for name in (
        "endpoint.json", "envelope.json", "failed.json", "desktop-send.json")}
    old_server.unlink()
    current = current_desktop_plugin(tmp_path, monkeypatch, revision="next")
    monkeypatch.setenv("FAKE_DESKTOP_MODE", "late-confirmed")
    completed = consume_desktop_readback(endpoint, envelope, attempt)
    assert completed.status == "completed"
    assert consume_desktop_readback(endpoint, envelope, attempt) == completed
    assert validate_late_desktop_start(endpoint, envelope, attempt).status == "completed"
    reader = json.loads((attempt.root / "desktop-readback.json").read_text())["native_reader"]
    assert reader["command"] == [sys.executable, str(current)]
    assert reader["plugin_sha256"] == hashlib.sha256(current.read_bytes()).hexdigest()
    assert all((attempt.root / name).read_bytes() == data for name, data in originals.items())
    calls = [json.loads(line) for line in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert sum(call["name"] == "send_message_to_thread" for call in calls) == 1


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


def test_proven_desktop_work_is_not_failed_by_transport_finish_clock(tmp_path, monkeypatch):
    from slk_transport.adapters import codex_desktop as desktop
    endpoint = prepared(tmp_path, monkeypatch, "active-running")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    clock = [0.0]
    original_call = desktop.DesktopClient.call
    after_start_reads = [0]
    def call(self, *args, **kwargs):
        result = original_call(self, *args, **kwargs)
        if (attempt.root / "started.json").is_file():
            clock[0] = 10_000.0
            after_start_reads[0] += 1
            if after_start_reads[0] >= 2:
                result["turns"][0]["status"] = "completed"
        return result
    monkeypatch.setattr(desktop.DesktopClient, "call", call)
    monkeypatch.setattr(desktop.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(desktop.time, "sleep", lambda _: None)
    result = desktop.deliver_desktop(endpoint, envelope, attempt, "exact bounded message")
    assert result.status == "completed" and after_start_reads[0] == 2
    assert not (attempt.root / "failed.json").exists()


@pytest.mark.parametrize("terminal", ["completed", "failed"])
def test_proven_delivery_uses_exact_turn_status_after_original_item_leaves_bounded_window(tmp_path, monkeypatch, terminal):
    from slk_transport.adapters import codex_desktop as desktop
    endpoint = prepared(tmp_path, monkeypatch, "active-running")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    original_call = desktop.DesktopClient.call
    reads = []
    def call(self, *args, **kwargs):
        result = original_call(self, *args, **kwargs)
        if (attempt.root / "started.json").is_file():
            reads.append(result)
            assert len(reads) == 1, "must not require the old item to reappear"
            result["turns"][0]["items"] = []
            result["turns"][0]["status"] = terminal
        return result
    monkeypatch.setattr(desktop.DesktopClient, "call", call)
    monkeypatch.setattr(desktop.time, "sleep", lambda _: None)
    if terminal == "failed":
        with pytest.raises(AdapterError, match="did not complete") as error:
            desktop.deliver_desktop(endpoint, envelope, attempt, "exact original handoff")
        assert error.value.error_code == "CODEX_TURN_FAILED"
    else:
        result = desktop.deliver_desktop(endpoint, envelope, attempt, "exact original handoff")
        assert result.status == "completed" and result.native_identity["turn_id"] == "turn-old"
        assert json.loads((attempt.root / "native-activity.json").read_text())["status"] == "COMPLETED"
    assert len(reads) == 1
    assert json.loads((attempt.root / "desktop-readback.json").read_text())["platform_item_id"] == "item-exact"


@pytest.mark.parametrize("damage", ["text", "truncated", "namespace", "type"])
def test_saved_delivery_proof_does_not_hide_a_contradictory_present_native_item(tmp_path, monkeypatch, damage):
    from slk_transport.adapters import codex_desktop as desktop
    endpoint = prepared(tmp_path, monkeypatch, "active-running")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    original_call = desktop.DesktopClient.call
    def call(self, *args, **kwargs):
        result = original_call(self, *args, **kwargs)
        if (attempt.root / "started.json").is_file():
            turn = result["turns"][0]
            turn["status"] = "completed"
            item = turn["items"][0]
            if damage == "text": item["output"]["text"] = "different original input"
            elif damage == "truncated": item["output"]["truncated"] = True
            else: item[damage] = "different-native-identity"
        return result
    monkeypatch.setattr(desktop.DesktopClient, "call", call)
    monkeypatch.setattr(desktop.time, "sleep", lambda _: None)
    with pytest.raises(AdapterError) as error:
        desktop.deliver_desktop(endpoint, envelope, attempt, "exact original handoff")
    assert error.value.error_code == "CODEX_DESKTOP_READBACK_DRIFT"
    assert json.loads((attempt.root / "desktop-readback.json").read_text())["platform_item_id"] == "item-exact"


def test_desktop_does_not_invent_a_16k_prompt_admission_limit(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch)
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)

    result = deliver_desktop(endpoint, envelope, attempt, "x" * 20_000)

    assert result.status == "completed"


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


@pytest.mark.parametrize("payload_type", ["D1_FAILURE_ESCALATION", "D1_INCOMPLETE_ESCALATION", "D2_READY"])
def test_checker_return_uses_inherited_executor_without_changing_registered_endpoint(tmp_path, monkeypatch, payload_type):
    from test_checker_escalation import fixture, load_module
    endpoint = prepared(tmp_path, monkeypatch)
    if payload_type == "D1_INCOMPLETE_ESCALATION":
        from test_checker_management import fixture as incomplete_fixture
        from slk_transport import checker_management
        request, _ = incomplete_fixture(tmp_path)
        raw = checker_management.materialize_management_escalation(request)["envelope"]
    elif payload_type == "D2_READY":
        from test_checker_completion import fixture as pass_fixture
        from slk_transport import checker_completion
        request, _ = pass_fixture(tmp_path, final=True)
        raw = checker_completion._materialize(request, checker_completion._validate_boundary(request))["envelope"]
    else:
        request, _ = fixture(tmp_path)
        raw = load_module().materialize_escalation(request)["envelope"]
    envelope = Envelope.from_dict(raw)
    endpoint = replace(endpoint, run_id=envelope.run_id, role_instance_id=envelope.receiver_role_instance_id,
                       endpoint_version=envelope.receiver_endpoint_version)
    monkeypatch.setenv("CODEX_THREAD_ID", "temporal-native-executor")
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    result = CodexAdapter().deliver(endpoint, envelope, attempt)
    assert result.status == "completed"
    assert endpoint.address["desktop"]["caller_thread_id"] == "caller-exact"
    proof = json.loads((attempt.root / "desktop-readback.json").read_text())
    assert proof["caller_thread_id"] == "temporal-native-executor"


@pytest.mark.parametrize("damage", ["run", "receiver", "version", "retired", "sender", "payload", "pipe", "origin"])
def test_checker_executor_exception_rejects_identity_scope_and_capability_drift(tmp_path, monkeypatch, damage):
    from test_checker_escalation import fixture, load_module
    endpoint = prepared(tmp_path, monkeypatch)
    request, _ = fixture(tmp_path)
    envelope = Envelope.from_dict(load_module().materialize_escalation(request)["envelope"])
    endpoint = replace(endpoint, run_id=envelope.run_id, role_instance_id=envelope.receiver_role_instance_id,
                       endpoint_version=envelope.receiver_endpoint_version)
    monkeypatch.setenv("CODEX_THREAD_ID", "temporal-native-executor")
    if damage == "run": endpoint = replace(endpoint, run_id="OTHER-RUN")
    elif damage == "receiver": endpoint = replace(endpoint, role_instance_id="OTHER-SUPERVISOR")
    elif damage == "version": endpoint = replace(endpoint, endpoint_version=endpoint.endpoint_version + 1)
    elif damage == "retired": endpoint = replace(endpoint, state="retired")
    elif damage == "sender": envelope = replace(envelope, sender_role="worker")
    elif damage == "payload": envelope = replace(envelope, payload_type="FREE_TEXT")
    elif damage == "pipe": monkeypatch.delenv("CODEX_APP_TOOLS_PIPE_PATH")
    elif damage == "origin": monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "cli")
    with pytest.raises(AdapterError) as error:
        CodexAdapter().deliver(endpoint, envelope, AttemptStore(tmp_path / "attempts").create(envelope))
    assert error.value.error_code == "CODEX_DESKTOP_HOST_UNAVAILABLE"
    assert not (tmp_path / "native-calls.jsonl").exists()


@pytest.mark.parametrize("mode,code", [("unknown-status", "CODEX_THREAD_STATE_UNKNOWN"),
                                      ("terminal-status", "CODEX_THREAD_TERMINAL")])
def test_desktop_preserves_native_status_and_does_not_call_unknown_terminal(tmp_path, monkeypatch, mode, code):
    endpoint = prepared(tmp_path, monkeypatch, mode)
    attempt = AttemptStore(tmp_path / "attempts").create(supervisor_envelope())
    with pytest.raises(AdapterError) as error:
        CodexAdapter().deliver(endpoint, supervisor_envelope(), attempt)
    assert error.value.error_code == code
    evidence = json.loads((attempt.root / "desktop-target-observation.json").read_text())
    assert evidence["thread_status"] == ("unknown" if mode == "unknown-status" else "failed")
    assert not (attempt.root / "desktop-send.json").exists()


def test_late_desktop_readback_consumes_original_send_without_resend(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch, "unconfirmed")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    adapter = CodexAdapter()
    prompt = adapter._prompt(envelope, attempt)
    with pytest.raises(AdapterError) as error:
        adapter.deliver(endpoint, envelope, attempt)
    assert error.value.error_code == "CODEX_DESKTOP_READBACK_UNPROVED"

    monkeypatch.setenv("FAKE_DESKTOP_MODE", "late-confirmed")
    result = consume_desktop_readback(endpoint, envelope, attempt)
    repeated = consume_desktop_readback(endpoint, envelope, attempt)

    assert result == repeated and result.status == "completed"
    assert result.native_identity["turn_id"] == "turn-new"
    calls = [json.loads(s) for s in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert sum(c["name"] == "send_message_to_thread" for c in calls) == 1


def test_rebound_desktop_node_keeps_immutable_failed_send_and_exact_late_readback(tmp_path, monkeypatch):
    from test_supervisor_notification import desktop_node_fixture
    raw, _notice, _projection, _node = desktop_node_fixture(tmp_path, monkeypatch)
    endpoint = Endpoint.from_dict(raw); envelope = supervisor_envelope()
    monkeypatch.setenv('FAKE_DESKTOP_MODE', 'unconfirmed')
    failed = dispatch_once(raw, asdict(envelope), tmp_path / 'attempts', adapters={endpoint.adapter: CodexAdapter()})
    assert failed.error_code == 'CODEX_DESKTOP_READBACK_UNPROVED' and 'command-rebind.json' in failed.evidence
    attempt = Attempt(tmp_path / 'attempts' / envelope.run_id / envelope.message_id)
    hashes = {name: hashlib.sha256((attempt.root / name).read_bytes()).hexdigest()
              for name in ('endpoint.json', 'envelope.json', 'failed.json', 'command-rebind.json', 'desktop-send.json')}
    monkeypatch.setenv('FAKE_DESKTOP_MODE', 'late-confirmed')
    assert consume_desktop_readback(endpoint, envelope, attempt).status == 'completed'
    assert validate_late_desktop_start(endpoint, envelope, attempt).status == 'completed'
    assert all(hashlib.sha256((attempt.root / name).read_bytes()).hexdigest() == digest for name, digest in hashes.items())
    calls = [json.loads(line) for line in (tmp_path / 'native-calls.jsonl').read_text().splitlines()]
    assert sum(call['name'] == 'send_message_to_thread' for call in calls) == 1


def test_saved_status_observation_remains_compatible_with_exact_late_start(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch, "unconfirmed")
    envelope = supervisor_envelope()
    result = dispatch_once(asdict(endpoint), asdict(envelope), tmp_path / "attempts", adapters={endpoint.adapter: CodexAdapter()})
    assert result.error_code == "CODEX_DESKTOP_READBACK_UNPROVED"
    attempt = Attempt(tmp_path / "attempts" / envelope.run_id / envelope.message_id)
    original = (attempt.root / "failed.json").read_bytes()
    monkeypatch.setenv("FAKE_DESKTOP_MODE", "late-confirmed")
    consume_desktop_readback(endpoint, envelope, attempt)
    assert validate_late_desktop_start(endpoint, envelope, attempt).status == "completed"
    assert (attempt.root / "failed.json").read_bytes() == original


def test_late_desktop_readback_rejects_ambiguous_native_match_without_resend(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch, "unconfirmed")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    adapter = CodexAdapter()
    prompt = adapter._prompt(envelope, attempt)
    with pytest.raises(AdapterError):
        adapter.deliver(endpoint, envelope, attempt)

    monkeypatch.setenv("FAKE_DESKTOP_MODE", "late-duplicate")
    prompt = json.loads((attempt.root / "desktop-prompt.json").read_text())["prompt"]
    with pytest.raises(AdapterError) as error:
        consume_desktop_readback(endpoint, envelope, attempt, prompt)

    assert error.value.error_code == "CODEX_DESKTOP_READBACK_AMBIGUOUS"
    calls = [json.loads(s) for s in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert sum(c["name"] == "send_message_to_thread" for c in calls) == 1


def test_late_desktop_readback_rejects_changed_anchor_before_native_query(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch, "unconfirmed")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    adapter = CodexAdapter()
    prompt = adapter._prompt(envelope, attempt)
    with pytest.raises(AdapterError):
        adapter.deliver(endpoint, envelope, attempt)
    prompt = json.loads((attempt.root / "desktop-prompt.json").read_text())["prompt"]
    anchor = json.loads((attempt.root / "desktop-readback-anchor.json").read_text())
    anchor["message_id"] = "another-message"
    (attempt.root / "desktop-readback-anchor.json").write_text(json.dumps(anchor), encoding="utf-8")

    with pytest.raises(AdapterError) as error:
        consume_desktop_readback(endpoint, envelope, attempt, prompt)

    assert error.value.error_code == "CODEX_DESKTOP_READBACK_DRIFT"


def test_active_desktop_receives_new_item_on_same_native_turn_without_writer_takeover(tmp_path, monkeypatch):
    endpoint = prepared(tmp_path, monkeypatch, "active")
    envelope = supervisor_envelope()
    attempt = AttemptStore(tmp_path / "attempts").create(envelope)
    result = CodexAdapter().deliver(endpoint, envelope, attempt)
    assert result.status == "completed" and result.native_identity["turn_id"] == "turn-old"
    calls = [json.loads(s) for s in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert {c["name"] for c in calls} == {"read_thread", "send_message_to_thread"}
    assert sum(c["name"] == "send_message_to_thread" for c in calls) == 1
