"""A saved Overwatcher credential is consumed only for OW-owned state writes."""

import hashlib
import json
from datetime import timedelta
from pathlib import Path

import pytest

from slk_transport import overwatcher_admin as admin


def write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def request_fixture(tmp_path: Path, operation: str = "record-overwatch-cycle") -> Path:
    from test_worker_completion import completion_fixture, runtime_projection
    source, endpoint, _ = completion_fixture(tmp_path)
    envelope = json.loads((source / "envelope.json").read_text())
    envelope["token_sequence"] = 14
    write_json(source / "envelope.json", envelope)
    projection = runtime_projection(token_owner=endpoint["role_instance_id"])
    projection["runtime_snapshot"]["method_version"] = "4.4.2"
    projection["roles"] = [{"role": "worker", "role_instance_id": endpoint["role_instance_id"]}]
    projection["go_nodes"] = [{"go_id": "GO-001", "cell_nodes": [{"cell_id": "CELL-001", "attempt": 1}]}]
    projection["events"][0].update(go_id="GO-001", author_role_instance_id=envelope["sender_role_instance_id"])
    details = json.loads(projection["events"][0]["details_json"])
    details.update(start_evidence_sha256=hashlib.sha256((source / "started.json").read_bytes()).hexdigest(),
                   endpoint_sha256=hashlib.sha256((source / "endpoint.json").read_bytes()).hexdigest(),
                   envelope_sha256=hashlib.sha256((source / "envelope.json").read_bytes()).hexdigest())
    projection["events"][0]["details_json"] = json.dumps(details)
    write_json(tmp_path / "runtime.json", projection)
    from slk_transport.native_activity import collect_overwatch_scope
    query = collect_overwatch_scope(source / "started.json", run_id="RUN-A", state_command=["slk-state"])
    query_path = write_json(tmp_path / "scope-query.json", query)
    inspection = query["worker_completion"]
    inspection_path = write_json(tmp_path / "inspection.json", inspection)
    operation_request = write_json(tmp_path / "operation.json", {
        "cycle_id": "cycle-1", "run_id": "RUN-A", "role_instance_id": "RUN-A-overwatcher-001",
        "go_id": "GO-001", "cell_id": "CELL-001", "attempt": 1, "plan_revision": 1,
        "runtime_revision": 7, "token_sequence": 14, "token_holder_role_instance_id": endpoint["role_instance_id"],
        "latest_message_id": inspection["source_message_id"], "cadence_seconds": 600,
        "started_at": query["query_started_at"],
        "completed_at": query["query_completed_at"],
        "evidence_refs": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                          for p in (source / "started.json", inspection_path, query_path)],
    })
    sealed = tmp_path / "overwatcher.dpapi"
    sealed.write_text("sealed", encoding="ascii")
    return write_json(tmp_path / "admin.json", {
        "schema_version": "slk.overwatcher-admin/v1",
        "run_id": "RUN-A",
        "overwatcher_role_instance_id": "RUN-A-overwatcher-001",
        "expected_runtime_revision": 7,
        "sealed_credential_path": str(sealed),
        "state_command": ["slk-state"],
        "operation": operation,
        "operation_request_path": str(operation_request),
        "operation_request_sha256": hashlib.sha256(operation_request.read_bytes()).hexdigest(),
        "result_path": str(tmp_path / "admin-result.json"),
    })


@pytest.fixture(autouse=True)
def isolated_current_projection(tmp_path, monkeypatch):
    monkeypatch.setattr(admin.wc, "_default_load_current_projection",
                        lambda *_a, **_k: json.loads((tmp_path / "runtime.json").read_text()))


@pytest.mark.parametrize("damage", ["forged-status", "missing-start", "duplicate-inspection", "wrong-source",
                                    "old-clock", "instant-cycle", "future-cycle"])
def test_cycle_requires_real_recollected_worker_facts_before_state_write(tmp_path, monkeypatch, damage):
    request = request_fixture(tmp_path)
    raw = json.loads(request.read_text())
    path = Path(raw["operation_request_path"])
    cycle = json.loads(path.read_text())
    inspection_path = tmp_path / "inspection.json"
    inspection = json.loads(inspection_path.read_text())
    if damage == "forged-status":
        inspection["status"] = "IN_PROGRESS"
    elif damage == "wrong-source":
        inspection["source_message_id"] = "wrong-message"
    elif damage == "missing-start":
        cycle["evidence_refs"] = cycle["evidence_refs"][1:]
    elif damage == "duplicate-inspection":
        copy = write_json(tmp_path / "second-inspection.json", inspection)
        cycle["evidence_refs"].append({"path": str(copy), "sha256": hashlib.sha256(copy.read_bytes()).hexdigest()})
    elif damage == "old-clock":
        inspection["observed_at"] = "2026-09-23T00:00:00Z"
    elif damage == "instant-cycle":
        cycle["completed_at"] = cycle["started_at"]
    else:
        cycle["completed_at"] = "2099-01-01T00:00:00Z"
    write_json(inspection_path, inspection)
    for ref in cycle["evidence_refs"]:
        ref["sha256"] = hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest()
    write_json(path, cycle)
    raw["operation_request_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(request, raw)
    calls = []
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _: "synthetic")
    def run(_command, args, **_kwargs):
        calls.append(args[0])
        if args[0] != "authenticate-role": pytest.fail("unproved cycle reached OW write")
        return {"status": "authenticated", "run_id": "RUN-A", "role": "overwatcher",
                "role_instance_id": "RUN-A-overwatcher-001", "runtime_revision": 7}
    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    with pytest.raises(ValueError, match="OVERWATCHER_CYCLE"):
        admin.execute_sealed_overwatcher_admin(request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert calls == ["authenticate-role"]
    assert not Path(raw["result_path"]).exists()


def test_ow_consumer_authenticates_and_records_own_cycle_without_exposing_secret(tmp_path, monkeypatch, capsys):
    request = request_fixture(tmp_path)
    from slk_transport.cli import main
    original_query = json.loads((tmp_path / "scope-query.json").read_text())
    assert main(["inspect-native-activity", "--started", original_query["native_start_path"],
                 "--run-id", "RUN-A", "--state-command", "slk-state"]) == 0
    query = json.loads(capsys.readouterr().out)
    assert query["query_started_at"] <= query["native_activity"]["observed_at"] <= query["query_completed_at"]
    assert query["runtime_projection_sha256"] == original_query["runtime_projection_sha256"]
    calls = []
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda path: "slk_" + "a" * 64)

    def run(command, arguments, credential=None, credential_scope="role"):
        calls.append((arguments, credential, credential_scope))
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "overwatcher",
                    "role_instance_id": "RUN-A-overwatcher-001", "runtime_revision": 7}
        return {"status": "overwatch_cycle_recorded", "run_id": "RUN-A", "cycle_id": "cycle-1"}

    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    result = admin.execute_sealed_overwatcher_admin(
        request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())

    assert [item[0][0] for item in calls] == ["authenticate-role", "record-overwatch-cycle"]
    assert [item[2] for item in calls] == ["role", "overwatcher"]
    assert result["status"] == "OVERWATCHER_ADMIN_COMPLETED"
    assert "slk_" not in json.dumps(result)
    assert "slk_" not in Path(json.loads(request.read_text())["result_path"]).read_text()


@pytest.mark.parametrize("damage", ["wrong-role", "wrong-runtime", "forbidden-operation", "changed-request"])
def test_ow_consumer_fails_closed_before_ow_state_write(tmp_path, monkeypatch, damage):
    operation = "close-overwatcher" if damage == "forbidden-operation" else "record-overwatch-cycle"
    request = request_fixture(tmp_path, operation)
    value = json.loads(request.read_text())
    if damage == "changed-request":
        Path(value["operation_request_path"]).write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda path: "slk_" + "b" * 64)

    def run(command, arguments, credential=None, credential_scope="role"):
        calls.append(arguments[0])
        return {"status": "authenticated", "run_id": "RUN-A",
                "role": "supervisor" if damage == "wrong-role" else "overwatcher",
                "role_instance_id": "RUN-A-overwatcher-001",
                "runtime_revision": 8 if damage == "wrong-runtime" else 7}

    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    with pytest.raises(ValueError):
        admin.execute_sealed_overwatcher_admin(
            request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert "record-overwatch-cycle" not in calls


def test_ow_consumer_preserves_safe_state_rejection_code_and_message(tmp_path, monkeypatch):
    request = request_fixture(tmp_path)
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda path: "slk_" + "c" * 64)

    def run(command, arguments, credential=None, credential_scope="role"):
        if arguments[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": "RUN-A", "role": "overwatcher",
                    "role_instance_id": "RUN-A-overwatcher-001", "runtime_revision": 7}
        return {"status": "error", "code": "SLK_STATE_COMMAND_FAILED",
                "message": "cycle runtime revision is stale",
                "_slk_command": {"process_exit": 1, "json_parse": "PARSED_STDERR",
                                 "business_status": "error"}}

    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    with pytest.raises(ValueError, match="SLK_STATE_COMMAND_FAILED: cycle runtime revision is stale"):
        admin.execute_sealed_overwatcher_admin(
            request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())


def test_authenticated_ow_stale_snapshot_is_not_bad_credential_and_never_replayed(tmp_path, monkeypatch):
    request = request_fixture(tmp_path)
    monkeypatch.setattr(admin.wc, "unprotect_dpapi_hex", lambda _: "synthetic")
    calls = []
    def run(_command, args, **_kwargs):
        calls.append(args[0])
        return {"status": "authenticated", "run_id": "RUN-A", "role": "overwatcher",
                "role_instance_id": "RUN-A-overwatcher-001", "runtime_revision": 8}
    monkeypatch.setattr(admin.wc, "_run_json_command", run)
    with pytest.raises(ValueError, match="OVERWATCHER_SNAPSHOT_STALE") as error:
        admin.execute_sealed_overwatcher_admin(request, request_sha256=hashlib.sha256(request.read_bytes()).hexdigest())
    assert "new observation" in str(error.value)
    assert calls == ["authenticate-role"]


def test_cycle_compares_engineering_attempt_with_current_cell_not_review_or_cycle(tmp_path):
    request = request_fixture(tmp_path)
    cycle = json.loads(Path(json.loads(request.read_text())["operation_request_path"]).read_text())
    path = tmp_path / "runtime.json"
    projection = json.loads(path.read_text())
    projection["go_nodes"][0]["cell_nodes"][0]["attempt"] = 2
    write_json(path, projection)
    with pytest.raises(ValueError, match="OVERWATCHER_CYCLE"):
        admin._verify_cycle(cycle, "RUN-A", ["slk-state"])
    cycle["attempt"] = 2
    projection["events"][0]["attempt"] = 2
    write_json(path, projection)
    from slk_transport.native_activity import collect_overwatch_scope
    query_path = tmp_path / "scope-query.json"
    query = collect_overwatch_scope(Path(json.loads(query_path.read_text())["native_start_path"]),
        run_id="RUN-A", state_command=["slk-state"])
    write_json(query_path, query)
    write_json(tmp_path / "inspection.json", query["worker_completion"])
    cycle.update(started_at=query["query_started_at"], completed_at=query["query_completed_at"])
    for ref in cycle["evidence_refs"]:
        ref["sha256"] = hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest()
    admin._verify_cycle(cycle, "RUN-A", ["slk-state"])


@pytest.mark.parametrize("role", ["checker", "supervisor"])
def test_old_nonworker_live_query_cannot_be_rewindowed(tmp_path, role):
    request = request_fixture(tmp_path)
    cycle = json.loads(Path(json.loads(request.read_text())["operation_request_path"]).read_text())
    projection = json.loads((tmp_path / "runtime.json").read_text())
    projection["roles"][0]["role"] = role
    write_json(tmp_path / "runtime.json", projection)
    old = write_json(tmp_path / "old-live-query.json", {
        "schema_version": "slk.overwatch-scope-inspection/v1", "run_id": "RUN-A",
        "query_started_at": "2026-09-23T00:00:00Z", "query_completed_at": "2026-09-23T00:00:01Z",
        "runtime_snapshot": projection["runtime_snapshot"],
        "runtime_projection_sha256": admin.wc.canonical_json_sha256(projection),
        "native_activity": {"status": "ACTIVE", "observed_at": "2026-09-23T00:00:01Z"},
        # Large legitimate state must not skip semantic JSON validation.
        "historical_report": "old report, not a current query" * 6000,
    })
    cycle["evidence_refs"].append({"path": str(old), "sha256": hashlib.sha256(old.read_bytes()).hexdigest()})
    cycle["evidence_refs"] = [ref for ref in cycle["evidence_refs"] if Path(ref["path"]).name != "scope-query.json"]
    with pytest.raises(ValueError, match="OVERWATCHER_CYCLE"):
        admin._verify_cycle(cycle, "RUN-A", ["slk-state"])


@pytest.mark.parametrize("stale_sample", ["query", "worker-completion"])
def test_wide_cycle_cannot_refresh_old_worker_samples(tmp_path, monkeypatch, stale_sample):
    request = request_fixture(tmp_path)
    cycle = json.loads(Path(json.loads(request.read_text())["operation_request_path"]).read_text())
    query_path = tmp_path / "scope-query.json"
    query = json.loads(query_path.read_text())
    now = query["query_completed_at"]
    old = (admin.wc._timestamp(query["query_started_at"]) - timedelta(days=17)).isoformat()
    cycle.update(started_at=old, completed_at=now)
    monkeypatch.setattr(admin, "utc_now", lambda: now)
    if stale_sample == "query":
        query.update(query_started_at=old, query_completed_at=old)
        query["native_activity"]["observed_at"] = old
        write_json(query_path, query)
    inspection_path = tmp_path / "inspection.json"
    inspection = json.loads(inspection_path.read_text())
    inspection["observed_at"] = old
    write_json(inspection_path, inspection)
    for ref in cycle["evidence_refs"]:
        ref["sha256"] = hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="cadence"):
        admin._verify_cycle(cycle, "RUN-A", ["slk-state"])


@pytest.mark.parametrize("role", ["checker", "supervisor"])
def test_nonworker_real_requery_accepts_historical_report_but_binds_original_start_and_scope(tmp_path, monkeypatch, role):
    import os
    from slk_transport.native_activity import collect_overwatch_scope, make_native_start
    from test_contracts import endpoint_value, envelope_value
    request = request_fixture(tmp_path)
    cycle = json.loads(Path(json.loads(request.read_text())["operation_request_path"]).read_text())
    old = json.loads((tmp_path / "scope-query.json").read_text())
    source = Path(old["native_start_path"]).parent
    endpoint = endpoint_value(role=role)
    envelope = envelope_value(sender_role="worker" if role == "checker" else "checker", receiver_role=role)
    envelope["token_sequence"] = 14
    write_json(source / "endpoint.json", endpoint)
    write_json(source / "envelope.json", envelope)
    write_json(source / "started.json", make_native_start(adapter=endpoint["adapter"], run_id="RUN-A",
        cell_id="CELL-001", message_id=envelope["message_id"], request_sha256=envelope["payload_sha256"],
        native_request_sha256="b" * 64, native_task_kind="ocrv-review" if role == "checker" else "codex-turn",
        native_task_id=f"original-{role}:turn", native_task_status="RUNNING", pid=os.getpid()))
    terminal = json.loads((source / "completed.json").read_text())
    write_json(source / "completed.json", {**terminal, "adapter": endpoint["adapter"]})
    projection = json.loads((tmp_path / "runtime.json").read_text())
    projection["roles"] = [{"role": role, "role_instance_id": endpoint["role_instance_id"]}]
    projection["runtime_snapshot"]["token_holder_role_instance_id"] = endpoint["role_instance_id"]
    projection["events"][0]["author_role_instance_id"] = envelope["sender_role_instance_id"]
    projection["events"][0]["details_json"] = json.dumps({"message_id": envelope["message_id"],
        **{key: hashlib.sha256((source / filename).read_bytes()).hexdigest() for key, filename in (
            ("start_evidence_sha256", "started.json"), ("endpoint_sha256", "endpoint.json"), ("envelope_sha256", "envelope.json"))}})
    write_json(tmp_path / "runtime.json", projection)
    query = collect_overwatch_scope(source / "started.json", run_id="RUN-A", state_command=["slk-state"])
    query_path = write_json(tmp_path / "scope-query.json", query)
    historical = write_json(tmp_path / "historical-report.json", {"reported_at": "2020-01-01T00:00:00Z", "report": "original"})
    cycle.update(token_holder_role_instance_id=endpoint["role_instance_id"],
        started_at=query["query_started_at"], completed_at=query["query_completed_at"],
        evidence_refs=[{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                       for p in (source / "started.json", query_path, historical)])
    if role == "supervisor": cycle.update(go_id=None, cell_id=None, attempt=None)
    admin._verify_cycle(cycle, "RUN-A", ["slk-state"])
    original_inspector = admin.inspect_native_activity
    with monkeypatch.context() as patch:
        now = query["query_completed_at"]
        old = (admin.wc._timestamp(query["query_started_at"]) - timedelta(days=17)).isoformat()
        stale = {**query, "query_started_at": old, "query_completed_at": old,
                 "native_activity": {**query["native_activity"], "observed_at": old}}
        write_json(query_path, stale)
        wide_cycle = {**cycle, "started_at": old, "completed_at": now,
                      "evidence_refs": [{**ref, "sha256": hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest()}
                                        for ref in cycle["evidence_refs"]]}
        patch.setattr(admin, "utc_now", lambda: now)
        with pytest.raises(ValueError, match="cadence"):
            admin._verify_cycle(wide_cycle, "RUN-A", ["slk-state"])
    write_json(query_path, query)
    monkeypatch.setattr(admin, "inspect_native_activity", lambda *_a, **_k: {
        **query["native_activity"], "last_event": {"kind": "tool-completed", "sequence": 2}})
    admin._verify_cycle(cycle, "RUN-A", ["slk-state"])
    monkeypatch.setattr(admin, "inspect_native_activity", lambda *_a, **_k: {
        **query["native_activity"], "status": "DEAD_WITHOUT_TERMINAL", "process": {"exists": False, "identity_matches": False}})
    with pytest.raises(ValueError, match="native sample is stale"):
        admin._verify_cycle(cycle, "RUN-A", ["slk-state"])
    monkeypatch.setattr(admin, "inspect_native_activity", lambda *_a, **_k: query["native_activity"])
    for field, wrong in (("source_message_id", "wrong-message"), ("run_id", "wrong-run"), ("runtime_projection_sha256", "0" * 64)):
        write_json(query_path, {**query, field: wrong})
        cycle["evidence_refs"][1]["sha256"] = hashlib.sha256(query_path.read_bytes()).hexdigest()
        with pytest.raises(ValueError, match="OVERWATCHER_CYCLE"):
            admin._verify_cycle(cycle, "RUN-A", ["slk-state"])
    if role == "checker":
        monkeypatch.setattr(admin, "inspect_native_activity", original_inspector)
        (source / "completed.json").unlink()
        started = json.loads((source / "started.json").read_text())
        started["process"] = {"pid": 2147483647, "creation_time": "win-filetime:1"}
        write_json(source / "started.json", started)
        proof = json.loads(projection["events"][0]["details_json"])
        proof["start_evidence_sha256"] = hashlib.sha256((source / "started.json").read_bytes()).hexdigest()
        projection["events"][0]["details_json"] = json.dumps(proof)
        write_json(tmp_path / "runtime.json", projection)
        query = collect_overwatch_scope(source / "started.json", run_id="RUN-A", state_command=["slk-state"])
        assert query["native_activity"]["status"] == "DEAD_WITHOUT_TERMINAL"
        query["native_activity"].update(status="ACTIVE", process={"exists": True, "identity_matches": True})
        write_json(query_path, query)
        cycle.update(started_at=query["query_started_at"], completed_at=query["query_completed_at"])
        for ref in cycle["evidence_refs"]:
            ref["sha256"] = hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest()
        with pytest.raises(ValueError, match="native sample is stale"):
            admin._verify_cycle(cycle, "RUN-A", ["slk-state"])


@pytest.mark.parametrize("unavailable", ["no-message", "native-source", "central-query"])
def test_real_unknown_query_is_recordable_without_inventing_native_proof(tmp_path, monkeypatch, unavailable):
    from slk_transport.native_activity import collect_overwatch_scope
    request = request_fixture(tmp_path)
    cycle = json.loads(Path(json.loads(request.read_text())["operation_request_path"]).read_text())
    projection = json.loads((tmp_path / "runtime.json").read_text())
    projection["roles"][0]["role"] = "supervisor"
    if unavailable == "no-message":
        projection["runtime_snapshot"]["latest_message_id"] = None
        cycle.update(go_id=None, cell_id=None, attempt=None, latest_message_id=None)
    write_json(tmp_path / "runtime.json", projection)
    with monkeypatch.context() as patch:
        if unavailable == "central-query":
            patch.setattr(admin.wc, "_default_load_current_projection", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("query offline")))
        query = collect_overwatch_scope(None, run_id="RUN-A", state_command=["slk-state"])
    query_path = write_json(tmp_path / "scope-query.json", query)
    cycle.update(started_at=query["query_started_at"], completed_at=query["query_completed_at"],
        checklist={"active_session": "CLEAR", "bi_projection": "ANOMALY"}, anomaly_codes=["ACTIVITY_UNPROVEN"],
        evidence_refs=[{"path": str(query_path), "sha256": hashlib.sha256(query_path.read_bytes()).hexdigest()}])
    assert query["native_activity"]["status"] == "UNKNOWN"
    assert query["native_activity"]["error"]
    admin._verify_cycle(cycle, "RUN-A", ["slk-state"])
    if unavailable == "central-query":
        with monkeypatch.context() as patch:
            patch.setattr(admin.wc, "_default_load_current_projection", lambda *_a, **_k: (_ for _ in ()).throw(ValueError("query offline")))
            admin._verify_cycle(cycle, "RUN-A", ["slk-state"])
    cycle["checklist"]["bi_projection"] = "CLEAR"
    with pytest.raises(ValueError, match="unproven"):
        admin._verify_cycle(cycle, "RUN-A", ["slk-state"])


def test_scope_collector_queries_central_exact_delivery_before_touching_native(tmp_path, monkeypatch):
    import slk_transport.native_activity as native
    request_fixture(tmp_path)
    query = json.loads((tmp_path / "scope-query.json").read_text())
    start = Path(query["native_start_path"])
    endpoint = json.loads(start.with_name("endpoint.json").read_text())
    endpoint["role_instance_id"] = "different-worker"
    write_json(start.with_name("endpoint.json"), endpoint)
    monkeypatch.setattr(native, "inspect_native_activity", lambda *_a, **_k: pytest.fail("unbound native source must not be queried"))
    actual = native.collect_overwatch_scope(start, run_id="RUN-A", state_command=["slk-state"])
    assert actual["native_activity"]["status"] == "UNKNOWN"
    assert actual["native_start_sha256"] is None


@pytest.mark.parametrize("role", ["worker", "checker", "supervisor"])
@pytest.mark.parametrize("damage", [None, "event-go", "event-cell", "event-attempt", "event-author",
    "missing-go", "missing-attempt", "duplicate-cell", "current-attempt", "plan", "role", "missing-role",
    "event-correction", "snapshot-run", "token-sequence"])
def test_scope_collector_checks_current_central_scope_before_any_roles_native_query(tmp_path, monkeypatch, role, damage):
    import os
    import slk_transport.native_activity as native
    from test_contracts import endpoint_value, envelope_value
    request_fixture(tmp_path)
    source = Path(json.loads((tmp_path / "scope-query.json").read_text())["native_start_path"]).parent
    endpoint = endpoint_value(role=role)
    envelope = envelope_value(sender_role="worker" if role == "checker" else "checker", receiver_role=role)
    envelope["token_sequence"] = 14
    if role == "supervisor": envelope["payload_type"] = "D2_READY"
    write_json(source / "endpoint.json", endpoint)
    write_json(source / "envelope.json", envelope)
    write_json(source / "started.json", native.make_native_start(adapter=endpoint["adapter"], run_id="RUN-A",
        cell_id=envelope["cell_id"], message_id=envelope["message_id"], request_sha256=envelope["payload_sha256"],
        native_request_sha256="b" * 64, native_task_kind="role-invocation", native_task_id="exact-task",
        native_task_status="RUNNING", pid=os.getpid()))
    terminal = json.loads((source / "completed.json").read_text())
    write_json(source / "completed.json", {**terminal, "adapter": endpoint["adapter"]})
    projection = json.loads((tmp_path / "runtime.json").read_text())
    projection["roles"] = [{"role": role, "role_instance_id": endpoint["role_instance_id"],
                            "lifecycle": "active", "current_go_id": None, "current_cell_id": None}]
    projection["runtime_snapshot"]["token_holder_role_instance_id"] = endpoint["role_instance_id"]
    event = projection["events"][0]
    event.update(go_id=envelope["go_id"], author_role_instance_id=envelope["sender_role_instance_id"])
    event["details_json"] = json.dumps({"message_id": envelope["message_id"],
        **{key: hashlib.sha256((source / filename).read_bytes()).hexdigest() for key, filename in (
            ("start_evidence_sha256", "started.json"), ("endpoint_sha256", "endpoint.json"), ("envelope_sha256", "envelope.json"))}})
    if damage == "event-go": event["go_id"] = "wrong-go"
    if damage == "event-cell": event["cell_id"] = "wrong-cell"
    if damage == "event-attempt": event["attempt"] = 99
    if damage == "event-author": event["author_role_instance_id"] = "different-sender"
    if damage == "missing-go": event.pop("go_id")
    if damage == "missing-attempt": event.pop("attempt")
    if damage == "duplicate-cell": projection["go_nodes"][0]["cell_nodes"] *= 2
    if damage == "current-attempt": projection["go_nodes"][0]["cell_nodes"][0]["attempt"] = 2
    if damage == "plan": projection["summary"]["current_plan_revision"] = 2
    if damage == "role": projection["roles"][0]["role"] = "different-role"
    if damage == "missing-role": projection["roles"] = []
    if damage == "event-correction": event["corrects_event_id"] = "different-event"
    if damage == "snapshot-run": projection["runtime_snapshot"]["run_id"] = "different-run"
    if damage == "token-sequence": projection["runtime_snapshot"]["token_sequence"] += 1
    write_json(tmp_path / "runtime.json", projection)
    calls = []
    original = native.inspect_native_activity
    def inspect(*args, **kwargs):
        assert damage is None, "mismatched central scope reached the native inspector"
        calls.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(native, "inspect_native_activity", inspect)
    actual = native.collect_overwatch_scope(source / "started.json", run_id="RUN-A", state_command=["slk-state"])
    assert len(calls) == (1 if damage is None else 0)
    assert actual["native_activity"]["status"] == ("COMPLETED" if damage is None else "UNKNOWN")
    if damage is not None:
        assert actual["native_start_sha256"] is None and actual["worker_completion"] is None


def test_initial_supervisor_without_current_cell_or_message_does_not_invent_a_native_task(tmp_path, monkeypatch):
    import slk_transport.native_activity as native
    request_fixture(tmp_path)
    projection = json.loads((tmp_path / "runtime.json").read_text())
    projection["runtime_snapshot"].update(token_holder_role_instance_id="RUN-A-supervisor-001", latest_message_id=None)
    projection["roles"] = [{"role": "supervisor", "role_instance_id": "RUN-A-supervisor-001",
                            "current_go_id": None, "current_cell_id": None}]
    projection["go_nodes"] = []
    projection["events"] = []
    write_json(tmp_path / "runtime.json", projection)
    monkeypatch.setattr(native, "inspect_native_activity", lambda *_a, **_k: pytest.fail("initial TOKEN has no native task"))
    actual = native.collect_overwatch_scope(None, run_id="RUN-A", state_command=["slk-state"])
    assert actual["query_error"] is None
    assert actual["native_activity"]["error"] == "NO_NATIVE_TASK_FOR_CURRENT_TOKEN"
    assert actual["worker_completion"] is None and actual["native_start_sha256"] is None
