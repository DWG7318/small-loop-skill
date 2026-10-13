"""The Worker MCP bridge exposes only the bound explicit Worker action."""

import importlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from slk_transport.worker_completion import CompletionError


@pytest.fixture
def mcp():
    assert importlib.util.find_spec("slk_transport.worker_mcp") is not None, "Worker MCP bridge is missing"
    return importlib.import_module("slk_transport.worker_mcp")


def test_worker_mcp_bridge_is_available():
    assert importlib.util.find_spec("slk_transport.worker_mcp") is not None, "Worker MCP bridge is missing"


def request(method, params=None, request_id=1):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def tool_call(arguments, name="slk_worker_action"):
    return request("tools/call", {"name": name, "arguments": arguments})


def test_startup_discovery_and_probe_never_load_or_record_an_action(mcp, monkeypatch):
    monkeypatch.delenv("SLK_NATIVE_ACTIVITY_PATH", raising=False)
    monkeypatch.setattr(mcp, "load_role_host", lambda *_: pytest.fail("startup read a host binding"))
    monkeypatch.setattr(mcp, "record", lambda *_: pytest.fail("startup recorded an action"))
    for method in ("initialize", "ping", "tools/list", "server/discover"):
        response = mcp.respond(request(method, {"protocolVersion": "2025-11-25"}))
        assert response["id"] == 1
    assert mcp.respond({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert mcp.respond({"jsonrpc": "2.0", "method": "tools/call", "params": {
        "name": "slk_worker_action", "arguments": {"event": "WORK_STARTED"},
    }}) is None


@pytest.mark.parametrize("version", ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07"])
def test_initialize_negotiates_installed_sdk_supported_legacy_versions(mcp, version):
    response = mcp.respond(request("initialize", {"protocolVersion": version}))
    assert response["result"]["protocolVersion"] == version
    assert response["result"]["capabilities"] == {"tools": {}}


def test_unknown_protocol_selects_latest_supported_and_discover_falls_back(mcp):
    assert mcp.respond(request("initialize", {"protocolVersion": "unknown"}))["result"]["protocolVersion"] == "2025-11-25"
    assert mcp.respond(request("server/discover"))["error"] == {"code": -32601, "message": "Method not found"}


def test_catalog_contains_one_closed_tool_and_optional_details(mcp):
    tools = mcp.respond(request("tools/list"))["result"]["tools"]
    assert len(tools) == 1
    assert tools[0]["name"] == "slk_worker_action"
    schema = tools[0]["inputSchema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["event"]
    assert set(schema["properties"]) == {"event", "details"}
    assert schema["properties"]["event"]["enum"] == ["WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED"]
    assert schema["properties"]["details"] == {"type": "object", "default": {}}


@pytest.mark.parametrize("event", ["WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED"])
def test_each_explicit_tool_call_invokes_action_exactly_once(mcp, event):
    seen = []
    details = {"candidate": {"head": "abc"}} if event == "CANDIDATE_SUBMITTED" else {"note": "original"}
    def action(actual_event, actual_details):
        seen.append((actual_event, actual_details))
        return {"status": "WORKER_ACTION_RECORDED", "event_type": actual_event}
    response = mcp.respond(tool_call({"event": event, "details": details}), action=action)
    assert seen == [(event, details)]
    assert json.loads(response["result"]["content"][0]["text"])["event_type"] == event
    assert not response["result"].get("isError")


def test_omitted_details_are_an_empty_object(mcp):
    seen = []
    mcp.respond(tool_call({"event": "WORK_STARTED"}), action=lambda *args: seen.append(args) or {})
    assert seen == [("WORK_STARTED", {})]


@pytest.mark.parametrize("arguments", [
    {}, [], None, "WORK_STARTED", {"event": []}, {"event": "PASS"}, {"event": 1},
    {"event": "WORK_STARTED", "details": []}, {"event": "WORK_STARTED", "details": None},
    *[{"event": "WORK_STARTED", field: "injected"} for field in (
        "source", "path", "credential", "run_id", "session_id", "action", "command",
    )],
])
def test_malformed_unknown_or_extra_tool_arguments_never_reach_action(mcp, arguments):
    response = mcp.respond(tool_call(arguments), action=lambda *_: pytest.fail("invalid action dispatched"))
    assert response["error"] == {"code": -32602, "message": "Invalid params"}


def test_unknown_tool_and_extra_call_params_never_reach_action(mcp):
    invalid = tool_call({"event": "WORK_STARTED"}, name="arbitrary_command")
    assert mcp.respond(invalid, action=lambda *_: pytest.fail("unknown tool dispatched"))["error"]["code"] == -32602
    invalid = tool_call({"event": "WORK_STARTED"})
    invalid["params"]["source"] = "injected"
    assert mcp.respond(invalid, action=lambda *_: pytest.fail("extra params dispatched"))["error"]["code"] == -32602


@pytest.mark.parametrize("message", [None, [], {"jsonrpc": "1.0", "id": 1, "method": "ping"},
    {"jsonrpc": "2.0", "id": True, "method": "ping"}, {"jsonrpc": "2.0", "id": [], "method": "ping"},
    {"jsonrpc": "2.0", "id": 1}, {"jsonrpc": "2.0", "id": 1, "method": []}])
def test_malformed_rpc_is_rejected_without_dispatch(mcp, message):
    assert mcp.respond(message, action=lambda *_: pytest.fail("malformed RPC dispatched"))["error"]["code"] == -32600


def test_non_object_params_are_rejected(mcp):
    message = request("ping")
    message["params"] = []
    assert mcp.respond(message)["error"]["code"] == -32602


def test_non_json_details_are_rejected_before_action(mcp):
    response = mcp.respond(tool_call({"event": "WORK_STARTED", "details": {"value": float("nan")}}),
        action=lambda *_: pytest.fail("non-JSON details dispatched"))
    assert response["error"]["code"] == -32602


def test_record_derives_exact_endpoint_and_source_from_bound_activity(mcp, tmp_path, monkeypatch):
    source = tmp_path / "exact-attempt"
    source.mkdir()
    endpoint = {"role": "worker", "bound": "exact"}
    (source / "endpoint.json").write_text(json.dumps(endpoint), encoding="utf-8")
    (source / "started.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_PATH", str(source / "native-activity.json"))
    seen = []
    class Host:
        def record_worker_action(self, actual_source, event, details, **options):
            assert options == {"wait_for_commit": False}
            seen.append((actual_source, event, details))
            return {"status": "WORKER_ACTION_RECORDED"}
    def load(actual_endpoint):
        assert actual_endpoint == endpoint
        return Host()
    monkeypatch.setattr(mcp, "load_role_host", load)
    monkeypatch.setattr(mcp, "require_live_action", lambda actual: seen.append(("live", actual)), raising=False)
    assert mcp.record("WORK_STARTED")["status"] == "WORKER_ACTION_RECORDED"
    assert seen == [("live", source), (source, "WORK_STARTED", {})]


@pytest.mark.parametrize("terminal", ["completed.json", "failed.json"])
def test_terminal_original_source_cannot_record_a_new_action(mcp, tmp_path, monkeypatch, terminal):
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_PATH", str(tmp_path / "native-activity.json"))
    (tmp_path / "endpoint.json").write_text("{}", encoding="utf-8")
    (tmp_path / terminal).write_text("{}", encoding="utf-8")
    seen = []
    class Host:
        def record_worker_action(self, *args):
            seen.append(args)
            return {}
    monkeypatch.setattr(mcp, "load_role_host", lambda *_: Host())
    with pytest.raises(ValueError, match="ended native invocation"):
        mcp.record("WORK_STARTED")
    assert seen == []


def test_fast_initial_mcp_is_retryable_until_exact_start_and_commit_without_shell(mcp, tmp_path, monkeypatch):
    from slk_transport import role_host, worker_completion as wc, native_activity as native
    from test_role_host import prepared_host, host_boundary
    from test_worker_completion import write_json
    host, source, envelope = prepared_host(tmp_path)
    (source / "completed.json").unlink()
    start = json.loads((source / "started.json").read_text())
    (source / "started.json").unlink()
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_PATH", str(source / "native-activity.json"))
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_CONTEXT", json.dumps({"adapter": "dsh-worker",
        "run_id": envelope.run_id, "cell_id": envelope.cell_id, "message_id": envelope.message_id}))
    monkeypatch.setattr(mcp, "load_role_host", lambda _: host)
    monkeypatch.setattr(native, "process_probe", lambda *_: {"exists": True, "identity_matches": True})
    observed = native.utc_now()
    write_json(source / "native-activity.json", {"schema_version": native.TASK_ACTIVITY_SCHEMA,
        "adapter": "dsh-worker", "run_id": envelope.run_id, "cell_id": envelope.cell_id,
        "message_id": envelope.message_id, "native_task_id": start["native_task"]["id"],
        "status": "RUNNING", "sequence": 1, "observed_at": observed,
        "sample": {"source": "DSH_LIVE_AGENT_REGISTRY", "native_task_id": start["native_task"]["id"],
                   "observed_at": observed},
        "last_event": {"kind": "DSH_AGENT_STATUS", "sequence": 1}, "waiting_on": None})
    projection = host_boundary(host, envelope)
    projection["events"] = [{"event_type": "TRANSPORT_STARTED", "cell_id": envelope.cell_id,
        "attempt": 1, "details": {"message_id": envelope.message_id}}]
    monkeypatch.setattr(host, "projection", lambda: projection)
    now = [0.0]
    monkeypatch.setattr(role_host.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(role_host.time, "sleep", lambda *_: pytest.fail("MCP must not wait or busy-loop"))
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("sandbox denies shell"))
    writes = []
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda _: "test-secret")
    monkeypatch.setattr(host, "_authenticate", lambda *_: {"status": "authenticated"})
    def state(arguments, **_kwargs):
        writes.append(json.loads(Path(arguments[-1]).read_text()))
        return {"status": "recorded"}
    monkeypatch.setattr(host, "_state_json", state)
    for phase in ("before-start", "before-commit", "delayed-commit"):
        if phase != "before-start":
            write_json(source / "started.json", start)
        now[0] += 60  # Well beyond the old fixed ten-second gate, without sleeping.
        pending = mcp.record("WORK_STARTED")
        assert pending["status"] == "WORKER_ACTION_PENDING" and pending["retryable"] is True
        assert pending["event_type"] == "WORK_STARTED" and pending["source_message_id"] == envelope.message_id
        assert writes == [] and not (source / "role-host" / "worker-work_started.json").exists()
    projection["runtime_snapshot"].update(token_holder_role_instance_id=envelope.receiver_role_instance_id,
        token_sequence=envelope.token_sequence, latest_message_id=envelope.message_id)
    result = mcp.record("WORK_STARTED")
    assert result["status"] == "WORKER_ACTION_RECORDED"
    assert len(writes) == 1 and writes[0]["event_type"] == "WORK_STARTED"
    assert writes[0]["occurred_at"] != start["observed_at"]


def test_pending_initial_mcp_still_requires_exact_native_context(mcp, tmp_path, monkeypatch):
    from test_role_host import prepared_host
    host, source, _ = prepared_host(tmp_path)
    (source / "completed.json").unlink()
    (source / "started.json").unlink()
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_PATH", str(source / "native-activity.json"))
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_CONTEXT", "{}")
    monkeypatch.setattr(mcp, "load_role_host", lambda _: host)
    with pytest.raises(CompletionError, match="native invocation"):
        mcp.record("WORK_STARTED")


@pytest.mark.parametrize("binding", [None, "relative/native-activity.json", "", "wrong.json"])
def test_record_rejects_unbound_activity_before_loading_host(mcp, binding, monkeypatch):
    if binding is None:
        monkeypatch.delenv("SLK_NATIVE_ACTIVITY_PATH", raising=False)
    else:
        monkeypatch.setenv("SLK_NATIVE_ACTIVITY_PATH", binding)
    monkeypatch.setattr(mcp, "load_role_host", lambda *_: pytest.fail("unbound action loaded host"))
    with pytest.raises(CompletionError) as error:
        mcp.record("WORK_STARTED")
    assert error.value.error_code == "WORKER_ACTION_CALLER_UNPROVEN"


def test_record_rejects_absolute_wrong_activity_name(mcp, tmp_path, monkeypatch):
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_PATH", str(tmp_path / "wrong.json"))
    monkeypatch.setattr(mcp, "load_role_host", lambda *_: pytest.fail("wrong path loaded host"))
    with pytest.raises(CompletionError):
        mcp.record("WORK_STARTED")


@pytest.mark.parametrize("endpoint", [None, "not-json", "[]"])
def test_missing_or_malformed_endpoint_cannot_record(mcp, tmp_path, monkeypatch, endpoint):
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_PATH", str(tmp_path / "native-activity.json"))
    if endpoint is not None:
        (tmp_path / "endpoint.json").write_text(endpoint, encoding="utf-8")
    monkeypatch.setattr(mcp, "load_role_host", lambda *_: pytest.fail("malformed endpoint loaded host"))
    with pytest.raises(CompletionError) as error:
        mcp.record("WORK_STARTED")
    assert error.value.error_code == "ROLE_HOST_BINDING_INVALID"


def test_missing_prepared_host_fails_closed(mcp, tmp_path, monkeypatch):
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_PATH", str(tmp_path / "native-activity.json"))
    (tmp_path / "endpoint.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mcp, "load_role_host", lambda *_: None)
    with pytest.raises(CompletionError) as error:
        mcp.record("WORK_STARTED")
    assert error.value.error_code == "ROLE_HOST_BINDING_INVALID"


@pytest.mark.parametrize("event,details", [("PASS", {}), ([], {}), ("WORK_STARTED", [])])
def test_direct_record_also_validates_action_before_reading_binding(mcp, monkeypatch, event, details):
    monkeypatch.setattr(mcp, "load_role_host", lambda *_: pytest.fail("invalid direct action loaded host"))
    with pytest.raises(ValueError):
        mcp.record(event, details)


def test_direct_record_rejects_non_json_details_before_reading_binding(mcp, tmp_path, monkeypatch):
    monkeypatch.setenv("SLK_NATIVE_ACTIVITY_PATH", str(tmp_path / "native-activity.json"))
    (tmp_path / "endpoint.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(mcp, "load_role_host", lambda *_: pytest.fail("non-JSON details loaded host"))
    with pytest.raises(ValueError):
        mcp.record("WORK_STARTED", {"value": object()})


@pytest.mark.parametrize("error", [
    CompletionError("WORKER_ACTION_CALLER_UNPROVEN", "secret-api-token-value"),
    CompletionError("secret-api-token-value", "secret-api-token-value"),
    OSError("secret-api-token-value"), RuntimeError("secret-api-token-value"),
])
def test_tool_errors_only_publish_safe_code_and_known_text(mcp, error):
    def action(*_):
        raise error
    response = mcp.respond(tool_call({"event": "WORK_STARTED"}), action=action)
    assert response["result"]["isError"] is True
    assert "secret" not in json.dumps(response).lower()
    if isinstance(error, CompletionError) and error.error_code == "WORKER_ACTION_CALLER_UNPROVEN":
        assert "WORKER_ACTION_CALLER_UNPROVEN" in response["result"]["content"][0]["text"]


@pytest.mark.parametrize("code", ["ROLE_HOST_TOKEN_UNCONFIRMED", "ROLE_HOST_PLAN_CHANGED"])
def test_unknown_symbolic_completion_code_is_retained_without_raw_message(mcp, code):
    def action(*_):
        raise CompletionError(code, "secret-api-token-value")

    response = mcp.respond(tool_call({"event": "WORK_STARTED"}), action=action)
    assert response["result"]["isError"] is True
    assert response["result"]["content"][0]["text"] == f"{code}: Worker action could not be recorded."
    assert "secret-api-token-value" not in json.dumps(response)


def test_main_replies_to_each_line_flushes_and_survives_bad_input(mcp, monkeypatch):
    class Output(io.StringIO):
        flushes = 0
        def flush(self):
            self.flushes += 1
    output = Output()
    messages = ["bad-json", "[]", json.dumps(request("ping")),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps(request("tools/list"))]
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(messages) + "\n"))
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(mcp, "record", lambda *_: pytest.fail("startup stream recorded an action"))
    assert mcp.main() == 0
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(responses) == 4
    assert responses[0]["error"] == {"code": -32700, "message": "Parse error"}
    assert responses[1]["error"]["code"] == -32600
    assert responses[2]["result"] == {}
    assert responses[3]["result"]["tools"][0]["name"] == "slk_worker_action"
    assert output.flushes == 4


def test_stdio_rejects_nonstandard_json_constants_without_dispatch(mcp, monkeypatch):
    message = tool_call({"event": "WORK_STARTED", "details": {"value": float("nan")}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(message) + "\n"))
    output = io.StringIO()
    monkeypatch.setattr(sys, "stdout", output)
    monkeypatch.setattr(mcp, "record", lambda *_: pytest.fail("nonstandard JSON dispatched"))
    assert mcp.main() == 0
    assert json.loads(output.getvalue())["error"] == {"code": -32700, "message": "Parse error"}


def test_real_stdin_process_needs_no_binding_for_discovery(mcp, tmp_path):
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(root / "src")}
    env.pop("SLK_NATIVE_ACTIVITY_PATH", None)
    messages = [request("initialize", {"protocolVersion": "2025-11-25"}), request("tools/list", request_id=2)]
    process = subprocess.run([sys.executable, "-B", "-c", "from slk_transport.worker_mcp import main; raise SystemExit(main())"],
        input="".join(json.dumps(value) + "\n" for value in messages), env=env,
        capture_output=True, text=True, cwd=tmp_path, timeout=15)
    assert process.returncode == 0, process.stderr
    assert process.stderr == ""
    assert [json.loads(line)["id"] for line in process.stdout.splitlines()] == [1, 2]
    assert list(tmp_path.iterdir()) == []


def test_real_installed_sdk_negotiates_and_lists_without_action(mcp, tmp_path):
    installed = Path("C:/Users/DWG/.codex/tools/slk/runtime")
    node = installed / "node/node.exe"
    client = installed / "dsh/node_modules/@modelcontextprotocol/client/dist/index.mjs"
    stdio = installed / "dsh/node_modules/@modelcontextprotocol/client/dist/stdio.mjs"
    if not all(path.is_file() for path in (node, client, stdio)):
        pytest.skip("installed native MCP SDK is unavailable")
    root = Path(__file__).resolve().parents[2]
    script = f"""
        import {{ Client }} from {json.dumps(client.as_uri())};
        import {{ StdioClientTransport }} from {json.dumps(stdio.as_uri())};
        const client = new Client({{name:'slk-worker-test',version:'1'}},{{capabilities:{{}}}});
        const transport = new StdioClientTransport({{
          command:{json.dumps(sys.executable)},
          args:['-B','-c','from slk_transport.worker_mcp import main; raise SystemExit(main())'],
          env:{{PYTHONPATH:{json.dumps(str(root / 'src'))}}}, cwd:{json.dumps(str(tmp_path))}
        }});
        try {{
          await client.connect(transport);
          const catalog = await client.listTools();
          console.log(JSON.stringify(catalog));
        }} finally {{ await client.close(); }}
    """
    env = {key: value for key, value in os.environ.items() if key != "SLK_NATIVE_ACTIVITY_PATH"}
    process = subprocess.run([str(node), "--input-type=module", "-e", script], env=env,
        capture_output=True, text=True, cwd=tmp_path, timeout=30)
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["tools"][0]["name"] == "slk_worker_action"
    assert list(tmp_path.iterdir()) == []


def prepare_script():
    script = Path(__file__).resolve().parents[2] / "integrations/dsh/prepare-worker-mcp.ps1"
    assert script.is_file(), "packaged Worker MCP preparation is required"
    return script


def run_prepare(home, transport, powershell_name=None):
    import shutil
    powershell = (shutil.which(powershell_name) if powershell_name else
        shutil.which("pwsh.exe") or shutil.which("powershell.exe"))
    python = Path("C:/Users/DWG/.codex/tools/slk/runtime/python/python.exe")
    if powershell is None or not python.is_file():
        pytest.skip("bundled native Windows runtime is unavailable")
    return subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
        "-File", str(prepare_script()), "-HomePath", str(home), "-PythonPath", str(python),
        "-TransportPath", str(transport)], capture_output=True, text=True, timeout=20)


def test_prepare_script_preserves_original_bytes_and_is_exactly_idempotent(tmp_path):
    home = tmp_path / "native home"
    home.mkdir()
    original = (b"\xef\xbb\xbf# private-setting-do-not-print\r\n- insert:\r\n"
        b"    - id: slk-native-probe\r\n      name: './plugins/slk-native-probe/activity.mjs'\r\n")
    patch = home / "cordis.patch.yml"
    patch.write_bytes(original)
    settings = home / "settings.yaml"
    settings.write_bytes(b"private unchanged settings\r\n")
    profiles = home / "profiles/headless"
    profiles.mkdir(parents=True)
    (profiles / "cordis.yml").write_bytes(b"do not rewrite root\r\n")
    transport = tmp_path / "transport 'quoted & path'.pyz"
    transport.write_bytes(b"test package is never executed")
    process = run_prepare(home, transport)
    assert process.returncode == 0, process.stderr
    assert "private-setting-do-not-print" not in process.stdout + process.stderr
    updated = patch.read_bytes()
    assert updated.startswith(original)
    assert updated.count(b"id: slk-worker-action-mcp") == 1
    assert b"cwd: !!js process.cwd()" in updated
    assert b"failOnStartupError: true" in updated
    assert b"enabled: false" in updated
    backups = list(home.glob(".slk-worker-mcp-backup-*.yml"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    before = {path.relative_to(home): path.read_bytes() for path in home.rglob("*") if path.is_file()}
    again = run_prepare(home, transport)
    assert again.returncode == 0, again.stderr
    assert "UNCHANGED" in again.stdout
    assert {path.relative_to(home): path.read_bytes() for path in home.rglob("*") if path.is_file()} == before
    changed_transport = tmp_path / "different.pyz"
    changed_transport.write_bytes(b"different package")
    rejected = run_prepare(home, changed_transport)
    assert rejected.returncode != 0
    assert {path.relative_to(home): path.read_bytes() for path in home.rglob("*") if path.is_file()} == before


def test_prepare_script_supports_windows_powershell_5(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    patch = home / "cordis.patch.yml"
    original = b"- insert:\n    - id: existing\n      name: original\n"
    patch.write_bytes(original)
    transport = tmp_path / "transport 'quoted'.pyz"
    transport.write_bytes(b"never executed")
    process = run_prepare(home, transport, "powershell.exe")
    assert process.returncode == 0, process.stderr
    assert patch.read_bytes().startswith(original)


@pytest.mark.parametrize("original", [
    b"settings: private-setting-do-not-print\n", b"[]\n", b"- insert: [\n",
    b"- insert:\n    - id: slk-worker-action-mcp\n      name: different\n",
])
def test_prepare_script_rejects_invalid_nonappendable_or_conflicting_patch_without_changes(tmp_path, original):
    home = tmp_path / "home"
    home.mkdir()
    patch = home / "cordis.patch.yml"
    patch.write_bytes(original)
    transport = tmp_path / "transport.pyz"
    transport.write_bytes(b"test package is never executed")
    process = run_prepare(home, transport)
    assert process.returncode != 0
    assert "private-setting-do-not-print" not in process.stdout + process.stderr
    assert patch.read_bytes() == original
    assert sorted(path.name for path in home.iterdir()) == ["cordis.patch.yml"]
