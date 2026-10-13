"""Overwatch observes native continuations without replacing central proof."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from slk_transport import native_activity as native, overwatcher_admin as admin, worker_completion as wc
from slk_transport.role_host import RoleHost
from test_worker_completion import completion_fixture, runtime_projection, write_json


def original_scope(tmp_path, monkeypatch):
    source, endpoint, _checker = completion_fixture(tmp_path)
    envelope = wc._read_object(source / "envelope.json", "original envelope")
    envelope["token_sequence"] = 14
    write_json(source / "envelope.json", envelope)
    projection = runtime_projection(token_owner=endpoint["role_instance_id"])
    projection["roles"] = [{"role": "worker", "role_instance_id": endpoint["role_instance_id"]}]
    projection["go_nodes"] = [{"go_id": envelope["go_id"], "cell_nodes": [
        {"cell_id": envelope["cell_id"], "attempt": 1}]}]
    event = projection["events"][0]
    event.update(go_id=envelope["go_id"], author_role_instance_id=envelope["sender_role_instance_id"])
    event["details_json"] = json.dumps({"message_id": envelope["message_id"],
        "start_evidence_sha256": wc._sha256(source / "started.json"),
        "endpoint_sha256": wc._sha256(source / "endpoint.json"),
        "envelope_sha256": wc._sha256(source / "envelope.json")})
    monkeypatch.setattr(wc, "_default_load_current_projection", lambda *_args, **_kwargs: projection)
    return source, endpoint, envelope, projection


def continuation(source, endpoint, envelope, *, identity=None, observed_at=None, terminal=False, pending=False):
    root = source / "native-resumes" / (identity or str(uuid.uuid4()))
    root.mkdir(parents=True)
    write_json(root / "endpoint.json", endpoint)
    write_json(root / "envelope.json", envelope)
    (root / "instructions.md").write_text("Continue the original bounded task and Session.", encoding="utf-8")
    write_json(root / "native-resume.json", {
        "schema_version": "slk.worker-native-resume/v1", "invocation_id": root.name,
        "original_source": str(source.resolve()),
        "original_source_sha256": RoleHost._source_sha256(source, "worker"),
        "binding_sha256": "a" * 64, "instructions_sha256": wc._sha256(root / "instructions.md"),
        "coordinator_process": {"pid": os.getpid(), "creation_time": native.process_creation_time(os.getpid())},
    })
    if not pending:
        write_json(root / "started.json", native.make_native_start(
            adapter=endpoint["adapter"], run_id=envelope["run_id"], cell_id=envelope["cell_id"],
            message_id=envelope["message_id"], request_sha256=envelope["payload_sha256"],
            native_request_sha256="c" * 64, native_task_kind="dsh-session",
            native_task_id=endpoint["address"]["session_id"], native_task_status="RUNNING",
            pid=os.getpid(), observed_at=observed_at))
        sampled_at = native.utc_now()
        write_json(root / "native-activity.json", {
            "schema_version": native.TASK_ACTIVITY_SCHEMA, "adapter": endpoint["adapter"],
            "run_id": envelope["run_id"], "cell_id": envelope["cell_id"],
            "message_id": envelope["message_id"], "native_task_id": endpoint["address"]["session_id"],
            "status": "RUNNING", "sequence": 2, "observed_at": sampled_at,
            "sample": {"source": "DSH_LIVE_AGENT_REGISTRY",
                "native_task_id": endpoint["address"]["session_id"], "observed_at": sampled_at},
            "last_event": {"kind": "tool_call", "sequence": 2}, "waiting_on": None,
        })
    if terminal:
        write_json(root / "completed.json", wc._read_object(source / "completed.json", "original terminal"))
    return root


def collect(source):
    return native.collect_overwatch_scope(source / "started.json", run_id="RUN-A", state_command=["slk-state"])


def cycle_for(tmp_path, source, projection, query):
    query_path = write_json(tmp_path / "query.json", query)
    paths = [source / "started.json", query_path]
    if query["worker_completion"] is not None:
        paths.append(write_json(tmp_path / "inspection.json", query["worker_completion"]))
    unknown = query["native_activity"]["status"] == "UNKNOWN"
    return {**projection["runtime_snapshot"], "go_id": "GO-001", "cell_id": "CELL-001", "attempt": 1,
        "started_at": query["query_started_at"], "completed_at": query["query_completed_at"],
        "cadence_seconds": 600,
        "checklist": {"active_session": "ANOMALY" if unknown else "CLEAR"},
        "anomaly_codes": ["ACTIVITY_UNPROVEN"] if unknown else [],
        "evidence_refs": [{"path": str(path), "sha256": wc._sha256(path)} for path in paths]}


def test_scope_uses_latest_validated_native_start_not_uuid_order_or_old_terminal(tmp_path, monkeypatch):
    source, endpoint, envelope, _projection = original_scope(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    continuation(source, endpoint, envelope, identity="ffffffff-ffff-4fff-bfff-ffffffffffff",
        observed_at=(now - timedelta(minutes=2)).isoformat(), terminal=True)
    fresh = continuation(source, endpoint, envelope, identity="00000000-0000-4000-8000-000000000001",
        observed_at=(now - timedelta(minutes=1)).isoformat())
    original_bytes = {path: path.read_bytes() for path in source.rglob("*") if path.is_file()}
    result = collect(source)
    assert result["native_activity"]["status"] == "ACTIVE", result["native_activity"]
    assert result["worker_completion"]["status"] == "IN_PROGRESS"
    assert result["native_start_path"] == str((source / "started.json").resolve())
    assert result["native_start_sha256"] == wc._sha256(source / "started.json")
    assert result["native_resume"] == {"invocation_id": fresh.name,
        "native_start_path": str(fresh / "started.json"), "native_start_sha256": wc._sha256(fresh / "started.json")}
    assert all(path.read_bytes() == data for path, data in original_bytes.items())


def test_pending_accepted_invocation_is_unknown_not_old_completed(tmp_path, monkeypatch):
    source, endpoint, envelope, _projection = original_scope(tmp_path, monkeypatch)
    fresh = continuation(source, endpoint, envelope, pending=True)
    result = collect(source)
    assert result["native_activity"]["status"] == "UNKNOWN"
    assert result["native_activity"]["error"] == "NATIVE_RESUME_START_PENDING"
    assert result["worker_completion"]["status"] == "UNKNOWN"
    assert result["native_resume"] == {"invocation_id": fresh.name,
        "native_start_path": str(fresh / "started.json"), "native_start_sha256": None}
    assert result["native_start_sha256"] == wc._sha256(source / "started.json")


@pytest.mark.parametrize("damage", ["extra-marker-key", "wrong-original", "original-hash", "binding-shape",
    "instructions", "endpoint", "envelope", "session", "message", "request", "bad-time", "naive-time",
    "older-than-original", "terminal-conflict", "noncanonical-id", "coordinator-shape"])
def test_untrustworthy_resume_never_falls_back_to_old_completion(tmp_path, monkeypatch, damage):
    source, endpoint, envelope, _projection = original_scope(tmp_path, monkeypatch)
    fresh = continuation(source, endpoint, envelope)
    marker = wc._read_object(fresh / "native-resume.json", "marker")
    if damage == "extra-marker-key": marker["unregistered"] = True
    if damage == "wrong-original": marker["original_source"] = str(tmp_path / "another-source")
    if damage == "original-hash": marker["original_source_sha256"] = "b" * 64
    if damage == "binding-shape": marker["binding_sha256"] = "not-a-digest"
    if damage == "coordinator-shape": marker["coordinator_process"]["pid"] = True
    write_json(fresh / "native-resume.json", marker)
    if damage == "instructions": (fresh / "instructions.md").write_text("changed", encoding="utf-8")
    if damage == "endpoint":
        write_json(fresh / "endpoint.json", {**endpoint, "role_instance_id": "different-worker"})
    if damage == "envelope": write_json(fresh / "envelope.json", {**envelope, "token_sequence": 15})
    start = wc._read_object(fresh / "started.json", "start")
    if damage == "session": start["native_task"]["id"] = "another-session"
    if damage == "message": start["message_id"] = str(uuid.uuid4())
    if damage == "request": start["request_sha256"] = "b" * 64
    if damage == "bad-time": start["observed_at"] = "not-a-time"
    if damage == "naive-time": start["observed_at"] = "2026-10-10T00:00:00"
    if damage == "older-than-original": start["observed_at"] = "2020-01-01T00:00:00Z"
    write_json(fresh / "started.json", start)
    if damage == "terminal-conflict":
        terminal = wc._read_object(source / "completed.json", "terminal")
        write_json(fresh / "completed.json", terminal)
        write_json(fresh / "failed.json", {**terminal, "status": "failed", "error_code": "DSH_EXIT_NONZERO"})
    if damage == "noncanonical-id": fresh.rename(fresh.with_name(fresh.name.upper()))
    result = collect(source)
    assert result["native_activity"]["status"] == "UNKNOWN"
    assert "NATIVE_RESUME_QUERY_UNAVAILABLE" in result["native_activity"]["error"]
    assert result["native_start_sha256"] == wc._sha256(source / "started.json")
    assert result["worker_completion"] is None


def test_two_live_native_activations_are_ambiguous(tmp_path, monkeypatch):
    source, endpoint, envelope, _projection = original_scope(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    continuation(source, endpoint, envelope, observed_at=(now - timedelta(minutes=1)).isoformat())
    continuation(source, endpoint, envelope)
    result = collect(source)
    assert result["native_activity"]["status"] == "UNKNOWN"
    assert "ambiguous" in result["native_activity"]["error"]
    assert result["native_start_sha256"] == wc._sha256(source / "started.json")


def test_equal_start_times_cannot_be_ordered_by_uuid(tmp_path, monkeypatch):
    source, endpoint, envelope, _projection = original_scope(tmp_path, monkeypatch)
    observed_at = native.utc_now()
    continuation(source, endpoint, envelope, observed_at=observed_at, terminal=True)
    continuation(source, endpoint, envelope, observed_at=observed_at, terminal=True)
    result = collect(source)
    assert result["native_activity"]["status"] == "UNKNOWN"
    assert "ambiguous" in result["native_activity"]["error"]


def test_resume_scan_is_bounded_to_direct_entries(tmp_path, monkeypatch):
    source, _endpoint, _envelope, _projection = original_scope(tmp_path, monkeypatch)
    from slk_transport.worker_resume_observation import MAX_NATIVE_RESUMES
    for _index in range(MAX_NATIVE_RESUMES + 1):
        (source / "native-resumes" / str(uuid.uuid4())).mkdir(parents=True)
    result = collect(source)
    assert result["native_activity"]["status"] == "UNKNOWN"
    assert "bounded direct entries" in result["native_activity"]["error"]


def test_changed_selected_start_does_not_discard_intact_original_central_proof(tmp_path, monkeypatch):
    source, endpoint, envelope, _projection = original_scope(tmp_path, monkeypatch)
    fresh = continuation(source, endpoint, envelope)
    inspector = native.inspect_native_activity
    def changing_inspector(path, **kwargs):
        result = inspector(path, **kwargs)
        assert path == fresh / "started.json"
        start = wc._read_object(path, "fresh start")
        write_json(path, {**start, "native_request_sha256": "d" * 64})
        return result
    monkeypatch.setattr(native, "inspect_native_activity", changing_inspector)
    result = collect(source)
    assert result["native_activity"]["status"] == "UNKNOWN"
    assert "changed during query" in result["native_activity"]["error"]
    assert result["native_start_path"] == str((source / "started.json").resolve())
    assert result["native_start_sha256"] == wc._sha256(source / "started.json")


@pytest.mark.parametrize("name", ["instructions.md", "native-resume.json", "started.json", "native-activity.json"])
def test_resume_symlink_evidence_is_refused_before_reading(tmp_path, monkeypatch, name):
    source, endpoint, envelope, _projection = original_scope(tmp_path, monkeypatch)
    fresh = continuation(source, endpoint, envelope)
    path = fresh / name
    outside = tmp_path / ("outside-" + name)
    path.rename(outside)
    try:
        path.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"OS does not permit test symlinks: {exc}")
    result = collect(source)
    assert result["native_activity"]["status"] == "UNKNOWN"
    assert "symlinks" in result["native_activity"]["error"]
    assert result["native_start_sha256"] == wc._sha256(source / "started.json")


@pytest.mark.parametrize("pending", [False, True])
def test_cycle_verifier_recollects_same_selected_resume(tmp_path, monkeypatch, pending):
    source, endpoint, envelope, projection = original_scope(tmp_path, monkeypatch)
    continuation(source, endpoint, envelope, pending=pending)
    query = collect(source)
    assert query["native_activity"]["status"] == ("UNKNOWN" if pending else "ACTIVE")
    cycle = cycle_for(tmp_path, source, projection, query)
    admin._verify_cycle(cycle, "RUN-A", ["slk-state"])
    forged = {**query, "native_resume": {**query["native_resume"], "invocation_id": str(uuid.uuid4())}}
    query_path = write_json(tmp_path / "query.json", forged)
    cycle["evidence_refs"][1]["sha256"] = wc._sha256(query_path)
    with pytest.raises(ValueError, match="resume"):
        admin._verify_cycle(cycle, "RUN-A", ["slk-state"])
