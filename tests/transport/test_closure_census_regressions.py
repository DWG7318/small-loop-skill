"""Closure census reads actual attempt contracts and exact native identities."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

import pytest

from slk_transport import native_activity as native
from slk_transport import worker_completion as wc
from slk_transport.adapters import codex_desktop as desktop
from slk_transport.contracts import DeliveryResult
from test_codex_desktop import prepared as desktop_endpoint
from test_role_host import dispatch_incoming, prepared_host
from test_worker_completion import actual_state_call, write_json


def census_host(tmp_path, monkeypatch):
    host, source, incoming = prepared_host(tmp_path)
    projection = {"summary": {"run_id": incoming.run_id},
                  "runtime_snapshot": {"runtime_revision": 7}, "native_invocations": [],
                  "roles": [{"role": "overwatcher", "role_instance_id": "OW-A"}]}
    monkeypatch.setattr(host, "projection", lambda: projection)
    return host, source, incoming


def test_audit_only_directories_are_not_native_invocations(tmp_path, monkeypatch):
    host, _, _ = census_host(tmp_path, monkeypatch)
    root = tmp_path / "notifications"
    write_json(root / "RUN-A" / "overwatcher-audit-25" / "notification-request.json", {"audit": True})
    proof = host.inspect_run_quiescence("close", [root])
    assert proof["inspections"] == []
    assert proof["status"] == "QUIESCENT"


def test_ocrv_unproven_session_keeps_exact_probe_diagnostic_in_census(tmp_path, monkeypatch):
    host, _, original = census_host(tmp_path, monkeypatch)
    incoming = dispatch_incoming(host, original)
    root = tmp_path / "ocrv-unproven"
    source = root / incoming.run_id / incoming.message_id
    write_json(source / "endpoint.json", host.endpoint("checker"))
    write_json(source / "envelope.json", asdict(incoming))
    start = native.make_native_start(adapter="ocrv-checker", run_id=incoming.run_id, cell_id=incoming.cell_id,
        message_id=incoming.message_id, request_sha256=incoming.payload_sha256,
        native_request_sha256="b" * 64, native_task_kind="ocrv-invocation",
        native_task_id=str(uuid.uuid4()), native_task_status="RUNNING", pid=os.getpid())
    write_json(source / "started.json", start)
    diagnostic = native._file_native_probe(source / "started.json", start)
    assert diagnostic == {"status": "UNKNOWN", "error": "OCRV_NATIVE_SESSION_UNPROVEN",
                          "last_event": None, "waiting_on": None}
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    proof = host.inspect_run_quiescence("close", [root])
    assert proof["status"] == "NOT_QUIESCENT"
    row = proof["inspections"][0]
    assert row["status"] == "UNKNOWN"
    assert row["reason"] == diagnostic["error"]
    assert row["native_activity"] == diagnostic
    assert {path.name: path.read_bytes() for path in source.iterdir()} == before


def notification_source(tmp_path, monkeypatch):
    host, _, _ = census_host(tmp_path, monkeypatch)
    endpoint = desktop_endpoint(tmp_path, monkeypatch)
    host.endpoints["supervisor"] = asdict(endpoint)
    notice = {"schema_version": "slk.ow-notification/v1", "run_id": "RUN-A",
              "event_id": "00000000-0000-4000-8000-000000000025", "sender_role_instance_id": "OW-A",
              "receiver_role_instance_id": endpoint.role_instance_id, "message": "发现异常，请查验。"}
    root = tmp_path / "notifications"
    source = root / notice["run_id"] / notice["event_id"]
    write_json(source / "endpoint.json", asdict(endpoint))
    write_json(source / "notification.json", notice)
    return host, root, source, endpoint, notice


@pytest.mark.parametrize("accepted", [False, True])
def test_notification_without_start_is_staged_only_before_native_acceptance(tmp_path, monkeypatch, accepted):
    host, root, source, _, _ = notification_source(tmp_path, monkeypatch)
    if accepted:
        write_json(source / "desktop-send.json", {"threadId": "thr_exact"})
    proof = host.inspect_run_quiescence("close", [root])
    assert len(proof["inspections"]) == 1
    assert proof["inspections"][0]["status"] == ("UNKNOWN" if accepted else "STAGED_NOT_STARTED")


def test_historical_notification_does_not_require_sender_still_active(tmp_path, monkeypatch):
    host, root, _, _, _ = notification_source(tmp_path, monkeypatch)
    host.projection()["roles"] = []
    proof = host.inspect_run_quiescence("close", [root])
    assert proof["inspections"][0]["status"] == "STAGED_NOT_STARTED"


def desktop_start(source, endpoint, notice):
    start = native.make_native_start(adapter=endpoint.adapter, run_id=notice["run_id"],
        cell_id="PREPARATION", message_id=notice["event_id"], request_sha256=wc.canonical_json_sha256(notice),
        native_request_sha256="b" * 64, native_task_kind="codex-desktop-turn",
        native_task_id="thr_exact:turn-original:item-original", native_task_status="RUNNING", pid=os.getpid())
    write_json(source / "started.json", start)
    write_json(source / "desktop-readback.json", {"thread_id": "thr_exact", "turn_id": "turn-original",
        "platform_item_id": "item-original", "message_id": notice["event_id"],
        "caller_thread_id": "caller-exact", "turn_status": "inProgress",
        "platform_item": {"id": "item-original", "type": "functionCallOutput"}})
    write_json(source / "native-activity.json", activity(start, "RUNNING", "2020-01-01T00:00:00Z"))
    return start


def activity(start, status, observed_at=None):
    return {"schema_version": native.TASK_ACTIVITY_SCHEMA,
            **{key: start[key] for key in ("adapter", "run_id", "cell_id", "message_id")},
            "native_task_id": start["native_task"]["id"], "status": status, "sequence": 1,
            "observed_at": observed_at or native.utc_now(),
            "last_event": {"kind": "NATIVE_EVENT", "sequence": 1}, "waiting_on": None}


def coordinator_alias_fixture(tmp_path, monkeypatch, *, other_turn=False, bad_item=False):
    from test_role_host import supervisor_result_fixture
    host, coordinator, incoming, _, _ = supervisor_result_fixture(tmp_path)
    endpoint = desktop_endpoint(tmp_path, monkeypatch)
    host.endpoints["supervisor"] = asdict(endpoint)
    incoming = {**asdict(incoming), "receiver_role_instance_id": endpoint.role_instance_id,
                "receiver_endpoint_version": endpoint.endpoint_version}
    write_json(coordinator / "endpoint.json", asdict(endpoint))
    write_json(coordinator / "envelope.json", incoming)
    start = desktop_start(coordinator, endpoint, {"run_id": "RUN-A", "event_id": incoming["message_id"]})
    start.update(cell_id=incoming["cell_id"], request_sha256=incoming["payload_sha256"])
    write_json(coordinator / "started.json", start)
    root = tmp_path / "aliases"
    notice = {"schema_version": "slk.temporal-notification/v1", "run_id": "RUN-A",
        "event_id": str(uuid.uuid4()), "sender_role_instance_id": "temporal:RUN-A",
        "receiver_role_instance_id": endpoint.role_instance_id, "message": "发现异常，请查验。"}
    alias = root / "RUN-A" / notice["event_id"]
    write_json(alias / "endpoint.json", asdict(endpoint))
    write_json(alias / "notification.json", notice)
    alias_start = desktop_start(alias, endpoint, notice)
    proof = wc._read_object(alias / "desktop-readback.json", "alias")
    proof.update(platform_item_id="item-alias", platform_item={"id": "item-alias", "type": "functionCallOutput"})
    if other_turn: proof["turn_id"] = "older-live-turn"
    alias_start["native_task"]["id"] = f"thr_exact:{proof['turn_id']}:item-alias"
    write_json(alias / "desktop-readback.json", proof)
    write_json(alias / "started.json", alias_start)
    projection = {"runtime_snapshot": {"runtime_revision": 7}, "native_invocations": [
        {"message_id": value["message_id"], "role_instance_id": endpoint.role_instance_id,
         "start_evidence_path": str(path / "started.json"), "start_evidence_sha256": wc._sha256(path / "started.json")}
        for path, value in ((coordinator, start), (alias, alias_start))]}
    monkeypatch.setattr(host, "projection", lambda: projection)
    monkeypatch.setenv("CODEX_THREAD_ID", endpoint.address["thread_id"])
    monkeypatch.setattr(desktop.DesktopClient, "__init__", lambda *_: None)
    monkeypatch.setattr(desktop.DesktopClient, "request", lambda _s, _i, method, *_a:
        {"tools": [{"name": "read_thread"}]} if method == "tools/list" else {})
    monkeypatch.setattr(desktop.DesktopClient, "notify", lambda *_a: None)
    monkeypatch.setattr(desktop.DesktopClient, "close", lambda *_a: None)
    calls = []
    def read(_s, _id, _name, arguments, _caller, _timeout):
        calls.append(dict(arguments))
        return {"thread": {"id": endpoint.address["thread_id"], "hostId": endpoint.host_id,
                "cwd": endpoint.address["cwd"], "status": {"type": "active"}},
            "page": {"hasMore": False}, "turns": [{"id": turn, "status": "inProgress", "items": [
                {"id": "item-original", "type": "functionCallOutput"},
                {"id": "item-alias", "type": "changed" if bad_item else "functionCallOutput"}]}
                for turn in ("turn-original", "older-live-turn")]}
    monkeypatch.setattr(desktop.DesktopClient, "call", read)
    return host, [coordinator.parents[1], root], coordinator, alias, calls


@pytest.mark.parametrize("damage", [None, "other-turn", "bad-item"])
def test_census_counts_validated_same_turn_aliases_as_one_coordinator(tmp_path, monkeypatch, damage):
    host, roots, coordinator, alias, calls = coordinator_alias_fixture(tmp_path, monkeypatch,
        other_turn=damage == "other-turn", bad_item=damage == "bad-item")
    proof = host.inspect_run_quiescence("close", roots, coordinator / "started.json")
    assert len(proof["inspections"]) == 2
    assert {row["native_start_path"] for row in proof["inspections"]} == {
        str(path / "started.json") for path in (coordinator, alias)}
    assert proof["status"] == ("QUIESCENT" if damage is None else "NOT_QUIESCENT"), proof
    assert sum(row["status"] == "COORDINATING" for row in proof["inspections"]) == (2 if damage is None else 1)
    assert len(calls) == 1  # Raw page reused, each receipt/item still checked.
    host.inspect_run_quiescence("close-again", roots, coordinator / "started.json")
    assert len(calls) == 2  # No cache crosses an inspection boundary.


@pytest.mark.parametrize("damage", [None, "hash", "other-turn", "other-host"])
def test_coordinator_consumers_count_exact_receipts_not_claimed_labels(tmp_path, monkeypatch, damage):
    host, roots, coordinator, alias, _ = coordinator_alias_fixture(tmp_path, monkeypatch,
        other_turn=damage == "other-turn")
    proof = host.inspect_run_quiescence("close", roots, coordinator / "started.json")
    for row in proof["inspections"]:
        row["status"] = "COORDINATING"
        if damage == "hash": row["native_start_sha256"] = "0" * 64
    if damage == "other-host":
        endpoint = wc._read_object(alias / "endpoint.json", "alias")
        write_json(alias / "endpoint.json", {**endpoint, "host_id": "other-host"})
    if damage is None:
        paths = native.census_coordinator_sources(proof)
        assert paths[0] == coordinator / "started.json"  # Envelope call anchors notification aliases.
        assert set(paths) == {coordinator / "started.json", alias / "started.json"}
    else:
        with pytest.raises(ValueError):
            native.census_coordinator_sources(proof)


def test_desktop_census_cached_raw_page_retains_original_observation_time(tmp_path, monkeypatch):
    host, _, coordinator, alias, calls = coordinator_alias_fixture(tmp_path, monkeypatch)
    pages = {}
    monkeypatch.setattr(native, "utc_now", lambda: "2026-10-15T00:00:00Z")
    endpoint = wc._read_object(coordinator / "endpoint.json", "endpoint")
    first, _ = host._desktop_census_activity(coordinator, endpoint,
        native.validate_native_start(coordinator / "started.json"), pages)
    monkeypatch.setattr(native, "utc_now", lambda: "2026-10-15T00:10:00Z")
    second, _ = host._desktop_census_activity(alias, endpoint, native.validate_native_start(alias / "started.json"), pages)
    assert first["observed_at"] == second["observed_at"] == "2026-10-15T00:00:00Z"
    assert len(calls) == 1
    with pytest.raises(native.NativeActivityError, match="stale"):
        native.validate_native_task_activity(second, **{key: second[key] for key in (
            "adapter", "run_id", "cell_id", "message_id", "native_task_id")})


@pytest.mark.parametrize("damage", [None, "missing-ref", "hash", "run", "state", "newer-plan", "endpoint", "marker"])
def test_historical_resume_uses_only_explicit_frozen_host_authority(tmp_path, monkeypatch, damage):
    from slk_transport.role_host import RoleHost
    from test_worker_resume_observation import continuation
    old, source, incoming = prepared_host(tmp_path)
    binding = dict(old.binding)
    if damage == "run": binding["run_id"] = "RUN-OTHER"
    if damage == "state": binding["state_command"] = ["another-state-authority"]
    if damage == "newer-plan": binding["plan_revision"] = 5
    frozen = write_json(tmp_path / "explicit-frozen-host.json", binding)
    digest = wc._sha256(frozen)
    fresh = continuation(source, old.endpoint("worker"), asdict(incoming))
    marker = wc._read_object(fresh / "native-resume.json", "marker")
    marker["binding_sha256"] = "a" * 64 if damage == "marker" else digest
    write_json(fresh / "native-resume.json", marker)
    if damage == "endpoint":
        endpoint = wc._read_object(fresh / "endpoint.json", "endpoint")
        endpoint["address"]["session_id"] = "different-session"
        write_json(fresh / "endpoint.json", endpoint)
    current = RoleHost({**old.binding, "plan_revision": 4}, "b" * 64)
    monkeypatch.setattr(current, "projection", lambda: {"runtime_snapshot": {"runtime_revision": 8}})
    for path in (source, fresh):
        start = native.validate_native_start(path / "started.json")
        value = activity(start, "COMPLETED")
        value["sample"] = {"source": "DSH_LIVE_AGENT_REGISTRY", "native_task_id": value["native_task_id"],
                           "observed_at": value["observed_at"]}
        write_json(path / "native-activity.json", value)
    refs = [] if damage == "missing-ref" else [{"path": str(frozen), "sha256": "0" * 64 if damage == "hash" else digest}]
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    if damage in {"hash", "run", "state", "newer-plan"}:
        with pytest.raises(ValueError):
            current.inspect_run_quiescence("close", [source.parents[1]], historical_host_refs=refs)
    else:
        proof = current.inspect_run_quiescence("close", [source.parents[1]], historical_host_refs=refs)
        assert proof["status"] == ("QUIESCENT" if damage is None else "NOT_QUIESCENT"), proof
        if damage is None: assert proof["historical_host_refs"] == refs
    assert all(path.read_bytes() == data for path, data in before.items())


@pytest.mark.parametrize("damage", [None, "active", "coordinator", "changed-lineage", "wrong-reader", "changed-item"])
def test_census_reads_central_desktop_bridge_from_original_scope_without_writes(tmp_path, monkeypatch, damage):
    from test_desktop_current_turn import (unresolved_delivery, host_receipt, native_platform_record,
        desktop_environment, prepare_desktop_current_turn, complete_desktop_current_turn)
    from slk_transport.desktop_current_turn import resolve_delivery_start
    endpoint, envelope, attempts, original = unresolved_delivery(tmp_path)
    request = prepare_desktop_current_turn(attempts, endpoint, envelope)
    receipt = host_receipt(request)
    current = asdict(desktop_endpoint(tmp_path, monkeypatch))
    current.update(host_id=endpoint["host_id"], role_instance_id=endpoint["role_instance_id"])
    native_platform_record(tmp_path, monkeypatch, request, receipt)
    complete_desktop_current_turn(attempts, endpoint, envelope, receipt, environment=desktop_environment())
    packet, _ = resolve_delivery_start(original, endpoint, envelope)
    (tmp_path / "host").mkdir()
    host, _, _ = prepared_host(tmp_path / "host")
    if damage == "wrong-reader": current["address"]["thread_id"] = "another-thread"
    host.endpoints["supervisor"] = current
    monkeypatch.setattr(host, "projection", lambda: {"runtime_snapshot": {"runtime_revision": 9},
        "native_invocations": [{"message_id": envelope["message_id"], "role_instance_id": endpoint["role_instance_id"],
            "start_evidence_path": str(packet), "start_evidence_sha256": wc._sha256(packet)}]})
    monkeypatch.setattr(desktop.DesktopClient, "__init__", lambda *_: None)
    monkeypatch.setattr(desktop.DesktopClient, "request", lambda _s, _i, method, *_a:
        {"tools": [{"name": "read_thread"}]} if method == "tools/list" else {})
    monkeypatch.setattr(desktop.DesktopClient, "notify", lambda *_a: None)
    monkeypatch.setattr(desktop.DesktopClient, "close", lambda *_a: None)
    monkeypatch.setattr(desktop.DesktopClient, "call", lambda *_a: {
        "thread": {"id": endpoint["address"]["thread_id"], "hostId": endpoint["host_id"],
                   "cwd": endpoint["address"]["cwd"], "status": {"type": "active"}},
        "page": {"hasMore": False}, "turns": [{"id": receipt["after"]["turn_id"],
            "status": "inProgress" if damage in {"active", "coordinator"} else "completed", "items": [
                {"id": receipt["after"]["platform_item_id"], "type": "unrelated"}] if damage == "changed-item" else []}]})
    if damage == "changed-lineage":
        value = wc._read_object(packet.with_name("recovery.json"), "recovery")
        write_json(packet.with_name("recovery.json"), {**value, "recovery_of_message_id": "wrong"})
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    options = {}
    if damage == "coordinator":
        monkeypatch.setenv("CODEX_THREAD_ID", endpoint["address"]["thread_id"])
        options["coordinator_started_path"] = packet
    result = host.inspect_run_quiescence("close", [attempts], **options)
    assert len(result["inspections"]) == 1, result
    row = result["inspections"][0]
    assert row["native_start_path"] == str(packet)
    assert row["message_id"] == envelope["message_id"]
    assert row["status"] == ("STOPPED" if damage is None else "COORDINATING" if damage == "coordinator" else "UNKNOWN"), row
    assert result["status"] == ("QUIESCENT" if damage in {None, "coordinator"} else "NOT_QUIESCENT")
    if damage == "coordinator":
        assert native.census_coordinator_sources(result) == [packet]
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("damage", [None, "active", "missing-turn", "wrong-thread", "wrong-host", "wrong-item",
                                    "unknown", "no-capability", "retired-plugin", "disabled-plugin", "local-host-alias",
                                    "paginated", "cursor-loop", "duplicate-turn",
                                    pytest.param("retired-plugin-extended", marks=pytest.mark.skipif(os.name != "nt", reason="Windows native path"))])
def test_started_notification_reads_exact_desktop_turn_without_writing_evidence(tmp_path, monkeypatch, damage):
    host, root, source, endpoint, notice = notification_source(tmp_path, monkeypatch)
    desktop_start(source, endpoint, notice)
    if damage in {"retired-plugin", "disabled-plugin", "retired-plugin-extended"}:
        old_endpoint = asdict(endpoint)
        old_endpoint["address"]["command"][1] = str(tmp_path / "retired-plugin" / "server.mjs")
        write_json(source / "endpoint.json", old_endpoint)
        codex_home = tmp_path / "codex-home"
        marketplace = codex_home / "bundled-marketplace"
        plugin = marketplace / "plugins/codex-app-tools"
        write_json(marketplace / ".agents/plugins/marketplace.json", {"name": "openai-bundled", "plugins": [
            {"name": "codex-app-tools", "source": {"source": "local", "path": "./plugins/codex-app-tools"}}]})
        write_json(plugin / ".codex-plugin/plugin.json", {"name": "codex-app-tools", "version": "0.1.6", "mcpServers": "./.mcp.json"})
        (plugin / "server.mjs").write_text("// installed current reader fixture", encoding="utf-8")
        configured_marketplace = str(marketplace)
        if damage == "retired-plugin-extended":
            configured_marketplace = "\\\\?\\" + configured_marketplace
        (codex_home / "config.toml").write_text('[marketplaces.openai-bundled]\nsource = '
            + json.dumps(configured_marketplace) + '\n[plugins."codex-app-tools@openai-bundled"]\nenabled = '
            + ("false" if damage == "disabled-plugin" else "true") + '\n', encoding="utf-8")
        monkeypatch.setenv("CODEX_HOME", str(codex_home))
    if damage == "local-host-alias":
        write_json(source / "endpoint.json", {**asdict(endpoint), "host_id": "win-dwg"})
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    monkeypatch.setattr(desktop.DesktopClient, "request", lambda _s, _i, method, *_a:
        {"tools": [{"name": "read_thread"}]} if method == "tools/list" else {})
    monkeypatch.setattr(desktop.DesktopClient, "notify", lambda *_a: None)
    monkeypatch.setattr(desktop.DesktopClient, "close", lambda *_a: None)
    commands = []
    monkeypatch.setattr(desktop.DesktopClient, "__init__", lambda _s, command, _cwd: commands.append(command))
    calls = []
    def read(_self, _id, name, arguments, caller, _timeout):
        calls.append((name, arguments, caller))
        assert name == "read_thread"
        assert 1 <= arguments["turnLimit"] <= 10  # Actual Desktop tool schema.
        page = {"hasMore": False}
        turn_id = "wrong" if damage == "missing-turn" else "turn-original"
        if damage == "cursor-loop" or (damage == "paginated" and len(calls) == 1):
            turn_id, page = "another-turn", {"hasMore": True, "nextCursor": "original-opaque-cursor"}
        if damage == "paginated" and len(calls) == 2:
            assert arguments["cursor"] == "original-opaque-cursor"
        result = {"thread": {"id": "wrong" if damage == "wrong-thread" else endpoint.address["thread_id"],
                    "hostId": "foreign-host" if damage == "wrong-host" else endpoint.host_id,
                    "cwd": endpoint.address["cwd"], "status": {"type": "active"}},
                "page": page, "turns": [{"id": turn_id,
                    "status": "inProgress" if damage == "active" else "unknown" if damage == "unknown" else "completed",
                    "items": [{"id": "item-original", "type": "changed"}] if damage == "wrong-item" else []}]}
        if damage == "duplicate-turn":
            result["turns"].append(dict(result["turns"][0]))
        return result
    monkeypatch.setattr(desktop.DesktopClient, "call", read)
    if damage == "no-capability":
        monkeypatch.delenv("CODEX_APP_TOOLS_PIPE_PATH")
    proof = host.inspect_run_quiescence("close", [root])
    assert len(proof["inspections"]) == 1
    assert proof["inspections"][0]["status"] == ("STOPPED" if damage in {
        None, "retired-plugin", "retired-plugin-extended", "local-host-alias", "paginated"} else "UNKNOWN"), proof
    assert bool(calls) is (damage not in {"no-capability", "disabled-plugin"})
    assert {path.name: path.read_bytes() for path in source.iterdir()} == before
    if damage == "retired-plugin-extended":
        assert all(not path.startswith("\\\\?\\") for path in commands[0])
        reader = proof["inspections"][0]["native_reader"]
        assert reader["command"] == commands[0]
        assert reader["plugin_sha256"] == wc._sha256(Path(commands[0][1]))


@pytest.mark.parametrize("damage", [None, "alive", "wrong-terminal", "missing-route", "changed-route"])
def test_synchronous_checker_dispatch_uses_exact_process_not_activity_or_terminal_label(tmp_path, monkeypatch, damage):
    host, _, original = census_host(tmp_path, monkeypatch)
    incoming = dispatch_incoming(host, original)
    root = tmp_path / "dispatches"
    source = root / incoming.run_id / incoming.message_id
    write_json(source / "endpoint.json", host.endpoint("checker"))
    write_json(source / "envelope.json", asdict(incoming))
    start = native.make_native_start(adapter="ocrv-checker", run_id=incoming.run_id, cell_id=incoming.cell_id,
        message_id=incoming.message_id, request_sha256=incoming.payload_sha256,
        native_request_sha256=incoming.payload_sha256, native_task_kind="checker-dispatch",
        native_task_id="dispatch:" + incoming.message_id, native_task_status="RUNNING", pid=os.getpid())
    write_json(source / "started.json", start)
    terminal = DeliveryResult("slk.transport-result/v1", incoming.message_id, incoming.run_id, "ocrv-checker",
        "completed", {"checker_operation": "dispatch", "role_instance_id": incoming.receiver_role_instance_id},
        None, ("started.json", "checker-result.json")).to_dict()
    if damage == "wrong-terminal":
        terminal["message_id"] = "00000000-0000-4000-8000-000000000099"
    write_json(source / "completed.json", terminal)
    if damage != "missing-route":
        route = {"schema_version": "slk.checker-result/v1", "operation": "dispatch",
            "source_message_id": incoming.message_id, "next_endpoint": host.endpoint("worker"),
            "next_envelope": {**asdict(original), "token_sequence": incoming.token_sequence + 1}}
        if damage == "changed-route":
            route["source_message_id"] = "other-call"
        write_json(source / "checker-result.json", route)
    calls = []
    def probe(pid, creation_time):
        calls.append((pid, creation_time))
        return {"exists": damage == "alive", "identity_matches": damage == "alive"}
    monkeypatch.setattr(native, "process_probe", probe)
    proof = host.inspect_run_quiescence("close", [root])
    assert proof["inspections"][0]["status"] == ("STOPPED" if damage is None else "UNKNOWN"), proof
    if damage in {None, "alive"}:
        assert calls == [(start["process"]["pid"], start["process"]["creation_time"])]


@pytest.mark.parametrize("status", ["RUNNING", "COMPLETED"])
def test_old_dsh_sample_cannot_prove_current_stop(tmp_path, monkeypatch, status):
    host, source, _ = census_host(tmp_path, monkeypatch)
    start = native.validate_native_start(source / "started.json")
    value = activity(start, status, "2020-01-01T00:00:00Z")
    value["sample"] = {"source": "DSH_LIVE_AGENT_REGISTRY", "native_task_id": value["native_task_id"],
                       "observed_at": value["observed_at"]}
    write_json(source / "native-activity.json", value)
    proof = host.inspect_run_quiescence("close", [source.parents[1]])
    assert proof["status"] == "NOT_QUIESCENT"
    assert proof["inspections"][0]["status"] == "UNKNOWN"


def test_orphan_native_start_is_not_hidden_by_audit_filter(tmp_path, monkeypatch):
    host, _, _ = census_host(tmp_path, monkeypatch)
    root = tmp_path / "notifications"
    write_json(root / "RUN-A" / "orphan" / "started.json", {})
    proof = host.inspect_run_quiescence("close", [root])
    assert len(proof["inspections"]) == 1
    assert proof["inspections"][0]["status"] == "UNKNOWN"


def stale_dsh_source(tmp_path, monkeypatch, damage=None):
    from slk_transport import worker_session_stop
    host, source, _ = census_host(tmp_path, monkeypatch)
    start = native.validate_native_start(source / "started.json")
    endpoint = wc._read_object(source / "endpoint.json", "test endpoint")
    bundle = tmp_path / "tools" / "slk"
    launcher = bundle / "bin" / "dsh-slk.cmd"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    endpoint["address"]["command"] = [str(launcher)]
    endpoint["address"]["session_id"] = start["native_task"]["id"]
    write_json(source / "endpoint.json", endpoint)
    native_home = Path(endpoint["address"]["runtime_root"]) / "runs" / endpoint["address"]["instance_id"] / "home"
    corpus = native_home / "sessions" / "project" / start["native_task"]["id"] / "session.v4.jsonl.zstd"
    value = activity(start, "RUNNING", "2020-01-01T00:00:00Z")
    value["sample"] = {"source": "DSH_LIVE_AGENT_REGISTRY", "native_task_id": value["native_task_id"],
                       "observed_at": value["observed_at"]}
    write_json(source / "native-activity.json", value)
    native_host = {"id": "a" * 64, "pid": 24680, "process_created": "windows-filetime:01dd5b0d1a84c9c0",
        "native_home": str(native_home if damage != "other-home" else tmp_path / "other"),
        "observed_at": value["observed_at"], "coverage": "COMPLETE", "omitted": int(damage == "omitted"),
        "liveness": "ALIVE" if damage == "native-alive" else "UNKNOWN" if damage == "native-unknown" else "EXITED",
        "objects": [] if damage == "missing-session" else [{"session_id": start["native_task"]["id"],
            "source": str(corpus if damage != "wrong-source" else tmp_path / "wrong"),
            "event_source": "DSH_NATIVE_EMISSION", "status": "RUNNING"}]}
    snapshot = {"schema": "slk.native-probe/v1", "tool": "dsh", "version": "1.0.0", "coverage": "UNKNOWN",
                "hosts": {native_host["id"]: native_host}}
    # An unrelated native home never substitutes for, or blocks, this exact invocation.
    snapshot["hosts"]["b" * 64] = {**native_host, "id": "b" * 64, "native_home": str(tmp_path / "unrelated"), "liveness": "ALIVE"}
    queries = []
    def query(command, arguments, **_kwargs):
        queries.append((command, arguments))
        return snapshot
    monkeypatch.setattr(wc, "_run_json_command", query)
    monkeypatch.setattr(native, "process_probe", lambda *_a: {
        "exists": damage == "launcher-alive", "identity_matches": damage == "launcher-alive"})
    def durable(actual):
        assert actual == endpoint
        if damage == "open-turn":
            raise ValueError("native Turn is open")
        return {"status": "NATIVE_SESSION_STOPPED", "session_id": start["native_task"]["id"],
                "path": str(corpus), "sha256": "c" * 64, "last_seq": 5, "turn": 1,
                "turn_end_seq": 5, "turn_ended_at": native.utc_now()}
    monkeypatch.setattr(worker_session_stop, "native_session_stopped", durable)
    return host, source, start, queries


@pytest.mark.parametrize("damage", [None, "launcher-alive", "native-alive", "native-unknown", "missing-session",
                                    "wrong-source", "omitted", "open-turn", "other-home"])
def test_stale_dsh_joins_original_start_native_host_exit_and_durable_stop(tmp_path, monkeypatch, damage):
    host, source, start, queries = stale_dsh_source(tmp_path, monkeypatch, damage)
    before = (source / "native-activity.json").read_bytes()
    proof = host.inspect_run_quiescence("close", [source.parents[1]])
    row = proof["inspections"][0]
    assert row["status"] == ("STOPPED" if damage is None else "UNKNOWN"), proof
    assert (source / "native-activity.json").read_bytes() == before
    if damage is None:
        assert row["native_stop"]["native_probe"]["coverage"] == "UNKNOWN"
        assert queries[0][1] == ["--tool", "dsh", "--session", start["native_task"]["id"], "query"]


@pytest.mark.parametrize("damage", [None, "missing-core", "unknown-field", "active-writer", "nonobject-provenance"])
def test_generated_census_is_consumed_by_real_state_cli(tmp_path, monkeypatch, damage):
    """Exercise the shared Rust pause/closure consumer, never a live Run or DB."""
    suffix = ".exe" if os.name == "nt" else ""
    binary = Path(__file__).parents[2] / "target/debug" / f"slk-state{suffix}"
    query_binary = binary.with_name(f"slk-bi-query{suffix}")
    if not binary.is_file() or not query_binary.is_file():
        pytest.skip("build slk-state and slk-bi-query before the real census integration test")
    config = tmp_path / "state-config/config.json"
    actual_state_call(binary, config, ["configure", "--data-root", tmp_path / "state-data"])
    initialized = actual_state_call(binary, config, ["init-run", "--request", write_json(tmp_path / "init.json", {
        "project": {"project_id": "project-a", "name": "Project A", "repository_url": None,
                    "last_known_path": str(tmp_path)},
        "run_id": "RUN-A", "goal": "prove census producer-consumer compatibility", "boundaries": {},
        "go_nodes": [{"go_id": "GO-001", "ordinal": 1, "title": "GO", "objective": "Objective"}],
        "cell_nodes": [{"go_id": "GO-001", "cell_id": "CELL-001", "ordinal": 1,
                        "title": "CELL", "objective": "Objective"}],
        "supervisor": {"role_instance_id": "RUN-A-supervisor-001", "role": "supervisor",
            "agent_runtime": "codex", "provider": "openai", "model": "gpt-6.1-sol",
            "reasoning": "xhigh", "session_id": "thr_exact"},
        "supervisor_endpoint": {"endpoint_version": 1, "transport_adapter": "codex-app-server",
            "host_identity": "local", "session_id": "thr_exact", "native_address": {"thread_id": "thr_exact"}},
        "occurred_at": native.utc_now()} )])
    credential = initialized["supervisor_credential"]
    def projection():
        return actual_state_call(query_binary, config, ["run", "--run-id", "RUN-A"])
    def event(kind, proof_path=None):
        current = projection()["runtime_snapshot"]
        details = {"pause_id": "isolated-census", "expected_runtime_revision": current["runtime_revision"]}
        if proof_path is not None:
            details.update(quiescence_path=str(proof_path), quiescence_sha256=wc._sha256(proof_path))
        return write_json(tmp_path / f"{kind}.json", {"event_id": str(uuid.uuid4()), "run_id": "RUN-A",
            "role_instance_id": "RUN-A-supervisor-001", "go_id": None, "cell_id": None, "attempt": None,
            "plan_revision": current["plan_revision"], "event_type": kind, "details": details,
            "corrects_event_id": None, "occurred_at": datetime.now(timezone.utc).isoformat()})
    actual_state_call(binary, config, ["write", "--request", event("RUN_PAUSE_REQUESTED")], credential=credential)

    # Only external native process/read APIs are doubled; producer, BI projection,
    # authenticated state writer, hashing, and Rust proof validation are real.
    host, dsh_source, _, _ = stale_dsh_source(tmp_path, monkeypatch)
    desktop_root = tmp_path / "desktop"
    desktop_root.mkdir()
    _, notice_root, notice_source, endpoint, notice = notification_source(desktop_root, monkeypatch)
    desktop_start(notice_source, endpoint, notice)
    host.endpoints["supervisor"] = asdict(endpoint)
    monkeypatch.setattr(host, "projection", projection)
    monkeypatch.setattr(desktop.DesktopClient, "__init__", lambda *_a: None)
    monkeypatch.setattr(desktop.DesktopClient, "request", lambda _s, _i, method, *_a:
        {"tools": [{"name": "read_thread"}]} if method == "tools/list" else {})
    monkeypatch.setattr(desktop.DesktopClient, "notify", lambda *_a: None)
    monkeypatch.setattr(desktop.DesktopClient, "close", lambda *_a: None)
    monkeypatch.setattr(desktop.DesktopClient, "call", lambda *_a: {
        "thread": {"id": endpoint.address["thread_id"], "hostId": endpoint.host_id,
                   "cwd": endpoint.address["cwd"], "status": {"type": "idle"}},
        "page": {"hasMore": False}, "turns": [{"id": "turn-original", "status": "completed", "items": []}]})
    proof = host.inspect_run_quiescence("isolated-census", [dsh_source.parents[1], notice_root])
    assert proof["status"] == "QUIESCENT", proof
    assert len(proof["inspections"]) == 2
    assert all(row["status"] == "STOPPED" for row in proof["inspections"])
    assert any(isinstance(row.get("native_stop"), dict) for row in proof["inspections"])
    assert any(isinstance(row.get("native_reader"), dict) for row in proof["inspections"])
    row = proof["inspections"][0]
    if damage == "missing-core":
        row.pop("message_id")
    elif damage == "unknown-field":
        row["unregistered_provenance"] = {}
    elif damage == "active-writer":
        row["processes"] = [{"exists": True, "identity_matches": True}]
    elif damage == "nonobject-provenance":
        row["native_reader"] = "not an object"
    proof_path = write_json(tmp_path / "generated-census.json", proof)
    request = event("RUN_PAUSED", proof_path)
    before = projection()["runtime_snapshot"]["runtime_revision"]
    if damage is None:
        result = actual_state_call(binary, config, ["write", "--request", request], credential=credential)
        assert result["status"] == "recorded"
        assert projection()["runtime_snapshot"]["runtime_revision"] == before + 1
    else:
        with pytest.raises(AssertionError, match="quiescence"):
            actual_state_call(binary, config, ["write", "--request", request], credential=credential)
        assert projection()["runtime_snapshot"]["runtime_revision"] == before


@pytest.mark.parametrize("damage", [None, "missing-executor", "changed-index", "alive-executor"])
def test_ocrv_terminal_session_still_requires_original_executor_binding(tmp_path, monkeypatch, damage):
    from slk_transport import native_ocrv
    host, source, incoming = census_host(tmp_path, monkeypatch)
    endpoint = host.endpoint("checker")
    envelope = {**asdict(incoming), "sender_role": "worker", "sender_role_instance_id": host.endpoint("worker")["role_instance_id"],
        "receiver_role": "checker", "receiver_role_instance_id": endpoint["role_instance_id"],
        "receiver_endpoint_version": endpoint["endpoint_version"], "payload_type": "WORKER_REPORT"}
    write_json(source / "endpoint.json", endpoint)
    write_json(source / "envelope.json", envelope)
    start = native.make_native_start(adapter="ocrv-checker", run_id=incoming.run_id, cell_id=incoming.cell_id,
        message_id=incoming.message_id, request_sha256=incoming.payload_sha256, native_request_sha256="b" * 64,
        native_task_kind="ocrv-review", native_task_id="exact-review", native_task_status="RUNNING", pid=os.getpid())
    write_json(source / "started.json", start)
    receipt = write_json(source / "native-start.received.json", start)
    identity = {**{key: start[key] for key in ("run_id", "cell_id", "message_id", "native_request_sha256")},
                "native_task_id": start["native_task"]["id"]}
    index = write_json(source / "evidence-index.json", identity)
    if damage != "missing-executor":
        write_json(source / "ocrv-native-process.json", {"schema_version": "slk.ocrv-native-process/v1", **identity,
            "native_start_sha256": wc._sha256(receipt), "launcher_process": start["process"],
            "process": {"pid": 24680, "creation_time": "win-filetime:1"}, "index_path": str(index),
            "index_sha256": "0" * 64 if damage == "changed-index" else wc._sha256(index)})
    monkeypatch.setattr(native, "_file_native_probe", lambda *_a: activity(start, "COMPLETED"))
    monkeypatch.setattr(native, "process_probe", lambda pid, _created: {
        "exists": damage == "alive-executor" and pid == 24680, "identity_matches": damage == "alive-executor" and pid == 24680})
    monkeypatch.setattr(native_ocrv, "process_probe", native.process_probe)
    proof = host.inspect_run_quiescence("close", [source.parents[1]])
    assert proof["inspections"][0]["status"] == ("STOPPED" if damage is None else "UNKNOWN"), proof
