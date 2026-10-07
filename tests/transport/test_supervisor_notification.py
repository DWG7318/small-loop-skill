"""Operational notices need real native wake evidence, without an engineering TOKEN."""
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

import pytest

from slk_transport import supervisor_notification as notification
from slk_transport.native_activity import make_native_start
from slk_transport.process import windows_no_window_kwargs
from slk_transport.adapters.base import AdapterError
from slk_temporal.contracts import (
    RoleBinding, StartSlkRequest, notification_native_id, validate_supervisor_notification,
)
from test_codex_desktop import prepared


def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    endpoint = asdict(prepared(tmp_path, monkeypatch))
    notice = {"schema_version": "slk.temporal-notification/v1", "run_id": endpoint["run_id"],
        "event_id": "951f288a-7195-4c8d-969b-8f87675d75ef", "sender_role_instance_id": "temporal:" + endpoint["run_id"],
        "receiver_role_instance_id": endpoint["role_instance_id"], "message": "发现异常，请查验。精确 Run 的 OW 原生进程已退出，需要 Supervisor 确认。"}
    projection = {"summary": {"run_id": endpoint["run_id"]}, "roles": [{"role": "supervisor", "lifecycle": "active",
        "role_instance_id": endpoint["role_instance_id"], "session_id": endpoint["address"]["thread_id"],
        "model": "gpt-6.1-sol", "reasoning": "xhigh"}]}
    return endpoint, notice, projection


def test_native_notification_is_idempotent_and_never_commits_token(tmp_path, monkeypatch):
    endpoint, notice, projection = fixture(tmp_path, monkeypatch)
    result = notification.notify_registered_supervisor(notice, endpoint, projection, tmp_path / "notices")
    assert result["status"] == "NOTIFIED" and result["native_start"]["message_id"] == notice["event_id"]
    assert result["supervisor_role_instance_id"] == endpoint["role_instance_id"]
    assert notification.notify_registered_supervisor(notice, endpoint, projection, tmp_path / "notices") == result
    calls = [json.loads(line) for line in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert sum(c["name"] == "send_message_to_thread" for c in calls) == 1
    assert all(c["name"] in {"read_thread", "send_message_to_thread"} for c in calls)


def test_operational_notice_does_not_wait_for_supervisor_turn_to_finish(tmp_path, monkeypatch):
    endpoint, notice, projection = fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DESKTOP_MODE", "active-running")
    result = notification.notify_registered_supervisor(notice, endpoint, projection, tmp_path / "notices")
    assert result["status"] == "NOTIFIED" and result["native_start"]["native_task"]["status"] == "RUNNING"
    assert not (tmp_path / "notices" / notice["run_id"] / notice["event_id"] / "completed.json").exists()


@pytest.mark.parametrize("damage", ["wrong-supervisor", "ow-model", "accepted-only", "unknown-prior"])
def test_notice_cannot_claim_wake_from_accepted_or_wrong_identity(tmp_path, monkeypatch, damage):
    endpoint, notice, projection = fixture(tmp_path, monkeypatch)
    if damage == "wrong-supervisor": notice["receiver_role_instance_id"] = "other-supervisor"
    if damage == "ow-model": endpoint["address"]["desktop"]["model"] = "gpt-6-luna"
    if damage == "accepted-only": monkeypatch.setenv("FAKE_DESKTOP_MODE", "unconfirmed")
    if damage == "unknown-prior":
        prior = tmp_path / "notices" / endpoint["run_id"] / notice["event_id"]
        prior.mkdir(parents=True)
        (prior / "desktop-send.json").write_text("{}")
    with pytest.raises((ValueError, AdapterError)):
        notification.notify_registered_supervisor(notice, endpoint, projection, tmp_path / "notices")
    if damage != "accepted-only": assert not (tmp_path / "native-calls.jsonl").exists()


def test_independent_exit_evidence_does_not_need_ow_final_message(tmp_path):
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(.3)"], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, **windows_no_window_kwargs())
    try:
        start = make_native_start(adapter="ow-native-host", run_id="RUN-A", cell_id="OBSERVATION",
            message_id="ed7b0d9c-43b8-4d9b-aeac-1190956e67b6", request_sha256="a" * 64, native_request_sha256="b" * 64,
            native_task_kind="ow-session", native_task_id="exact-ow-session", native_task_status="RUNNING", pid=process.pid)
        path = tmp_path / "started.json"
        path.write_text(json.dumps(start))
        process.wait(timeout=5)
        result = notification.observe_overwatcher_exit(path, run_id="RUN-A", role_instance_id="OW-A",
            native_task_id="exact-ow-session", requested_by_role_instance_id="owning-host")
        assert result["run_id"] == "RUN-A" and result["overwatcher_role_instance_id"] == "OW-A"
        assert len(result["evidence_sha256"]) == 64
        assert notification.observe_overwatcher_exit(path, run_id="RUN-A", role_instance_id="OW-A",
            native_task_id="exact-ow-session", requested_by_role_instance_id="owning-host") == result
        with pytest.raises(ValueError):
            notification.observe_overwatcher_exit(path, run_id="OTHER-RUN", role_instance_id="OW-A",
                native_task_id="exact-ow-session", requested_by_role_instance_id="owning-host")
    finally:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)


def test_temporal_activity_receipt_binds_outer_event_and_exact_native_notice(tmp_path, monkeypatch):
    endpoint, notice, projection = fixture(tmp_path, monkeypatch)
    value = {"event_id": "RUN-A-ow-exit", "kind": "OVERWATCHER_EXIT_REQUIRES_SUPERVISOR_CONFIRMATION",
        "run_id": endpoint["run_id"], "responsible_role_instance_id": "OW-A", "source_operation_id": "guard-a", "threshold_seconds": 0}
    result = notification.notify_temporal_supervisor(value, endpoint, projection, tmp_path / "notices")
    assert result["event_id"] == value["event_id"]
    assert result["native_start"]["message_id"] == notification_native_id(value["run_id"], value["event_id"])
    validate_supervisor_notification(
        result, run_id=value["run_id"], event_id=value["event_id"],
        supervisor_role_instance_id=endpoint["role_instance_id"],
    )
    assert result["receipt_sha256"] == notification.canonical_json_sha256({k: v for k, v in result.items() if k != "receipt_sha256"})


def test_real_temporal_runtime_events_reach_native_start_validator_and_replay(tmp_path, monkeypatch):
    pytest.importorskip("temporalio")
    import asyncio
    from datetime import datetime, timedelta, timezone
    from slk_temporal import workflows

    endpoint, _notice, projection = fixture(tmp_path, monkeypatch)
    startup = StartSlkRequest(
        run_id=endpoint["run_id"], method_version="4.4.2", runtime_revision=11,
        task_queue="slk-test", ack_timeout_seconds=120,
        startup_idempotency_key="start-run-a-v11",
        roles=(
            RoleBinding("SUPERVISOR", endpoint["role_instance_id"], "supervisor-endpoint"),
            RoleBinding("CHECKER", "checker-a", "checker-endpoint"),
            RoleBinding("WORKER", "worker-a", "worker-endpoint"),
            RoleBinding("OVERWATCHER", "OW-A", "overwatcher-endpoint"),
        ),
    )
    notices = []

    async def collect(value):
        notices.append(value)
        return True

    member = workflows.RunSlkWorkflow()
    member._startup = startup
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    member._member_residency_since = now - workflows.MEMBER_RESIDENCY_LIMIT
    member._responsibility_operation_id = "delivery-1"
    member._responsible_role_instance_id = "checker-a"
    member._next_overwatcher_audit_at = now + timedelta(hours=1)
    monkeypatch.setattr(workflows.workflow, "now", lambda: now)
    monkeypatch.setattr(member, "_notify_supervisor", collect)
    asyncio.run(member._perform_runtime_checks())

    audit = workflows.RunSlkWorkflow()
    audit._startup = startup

    async def inspect(_name, value, **_kwargs):
        return {
            "status": "ANOMALY", "run_id": value["run_id"],
            "overwatcher_role_instance_id": value["overwatcher_role_instance_id"],
            "audit_cycle": value["audit_cycle"], "evidence_sha256": "a" * 64,
            "receipt_sha256": "b" * 64,
        }

    monkeypatch.setattr(workflows.workflow, "execute_activity", inspect)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _name: True)
    monkeypatch.setattr(audit, "_notify_supervisor", collect)
    asyncio.run(audit._inspect_overwatcher())

    assert [value["event_id"] for value in notices] == [
        "RUN-A-member-residency-delivery-1", "RUN-A-overwatcher-audit-1",
    ]
    for value in notices:
        result = notification.notify_temporal_supervisor(
            value, endpoint, projection, tmp_path / "notices")
        assert result["event_id"] == value["event_id"]
        assert result["native_start"]["message_id"] == notification_native_id(
            value["run_id"], value["event_id"])
        validate_supervisor_notification(
            result, run_id=value["run_id"], event_id=value["event_id"],
            supervisor_role_instance_id=endpoint["role_instance_id"],
        )
        assert notification.notify_temporal_supervisor(
            value, endpoint, projection, tmp_path / "notices") == result
    calls = [json.loads(line) for line in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert sum(call["name"] == "send_message_to_thread" for call in calls) == 2


def test_native_ow_notice_keeps_semantic_sender_but_uses_current_trusted_desktop_executor(tmp_path, monkeypatch):
    endpoint, notice, projection = fixture(tmp_path, monkeypatch)
    notice.update(schema_version="slk.ow-notification/v1", sender_role_instance_id="OW-A")
    projection["roles"].append({"role": "overwatcher", "lifecycle": "active", "role_instance_id": "OW-A",
        "agent_runtime": "codex", "session_id": "registered-native-ow"})
    registered_caller = endpoint["address"]["desktop"]["caller_thread_id"]
    monkeypatch.setenv("CODEX_THREAD_ID", "trusted-root-executor")

    result = notification.notify_registered_supervisor(notice, endpoint, projection, tmp_path / "notices")

    assert result["status"] == "NOTIFIED"
    root = tmp_path / "notices" / notice["run_id"] / notice["event_id"]
    assert notification.wc._read_object(root / "notification.json", "notice")["sender_role_instance_id"] == "OW-A"
    assert notification.wc._read_object(root / "endpoint.json", "endpoint")["address"]["desktop"]["caller_thread_id"] == registered_caller
    calls = [json.loads(line) for line in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert all(call["_meta"]["codex_thread_id"] == "trusted-root-executor" for call in calls)


def test_native_ow_notice_still_rejects_unregistered_semantic_sender(tmp_path, monkeypatch):
    endpoint, notice, projection = fixture(tmp_path, monkeypatch)
    notice.update(schema_version="slk.ow-notification/v1", sender_role_instance_id="OW-A")
    monkeypatch.setenv("CODEX_THREAD_ID", "trusted-root-executor")
    with pytest.raises(ValueError, match="sender is not registered"):
        notification.notify_registered_supervisor(notice, endpoint, projection, tmp_path / "notices")
    assert not (tmp_path / "native-calls.jsonl").exists()


def test_missing_trusted_notice_executor_does_not_poison_an_unsent_retry(tmp_path, monkeypatch):
    endpoint, notice, projection = fixture(tmp_path, monkeypatch)
    monkeypatch.delenv("CODEX_APP_TOOLS_PIPE_PATH")
    root = tmp_path / "notices" / notice["run_id"] / notice["event_id"]

    with pytest.raises(AdapterError, match="executor capability"):
        notification.notify_registered_supervisor(notice, endpoint, projection, tmp_path / "notices")

    assert not root.exists()
    monkeypatch.setenv("CODEX_APP_TOOLS_PIPE_PATH", "inherited-native-pipe")
    assert notification.notify_registered_supervisor(
        notice, endpoint, projection, tmp_path / "notices"
    )["status"] == "NOTIFIED"


def test_exact_notice_only_pre_send_rejection_resumes_once(tmp_path, monkeypatch):
    endpoint, notice, projection = fixture(tmp_path, monkeypatch)
    root = tmp_path / "notices" / notice["run_id"] / notice["event_id"]
    root.mkdir(parents=True)
    (root / "notification.json").write_text(json.dumps(notice), encoding="utf-8")
    (root / "endpoint.json").write_text(json.dumps(endpoint), encoding="utf-8")
    original = {p.name: p.read_bytes() for p in root.iterdir()}
    result = notification.notify_registered_supervisor(notice, endpoint, projection, tmp_path / "notices")
    assert result["status"] == "NOTIFIED"
    assert {n: (root / n).read_bytes() for n in original} == original
    assert notification.notify_registered_supervisor(notice, endpoint, projection, tmp_path / "notices") == result
    calls = [json.loads(s) for s in (tmp_path / "native-calls.jsonl").read_text().splitlines()]
    assert sum(c["name"] == "send_message_to_thread" for c in calls) == 1


def test_notice_status_retry_retains_first_observation_without_second_send(tmp_path, monkeypatch):
    endpoint, notice, projection = fixture(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_DESKTOP_MODE", "unknown-status")
    with pytest.raises(AdapterError) as error:
        notification.notify_registered_supervisor(notice, endpoint, projection, tmp_path / "notices")
    assert error.value.error_code == "CODEX_THREAD_STATE_UNKNOWN"
    root = tmp_path / "notices" / notice["run_id"] / notice["event_id"]
    original = (root / "desktop-target-observation.json").read_bytes()
    monkeypatch.setenv("FAKE_DESKTOP_MODE", "normal")
    result = notification.notify_registered_supervisor(notice, endpoint, projection, tmp_path / "notices")
    assert result["status"] == "NOTIFIED"
    assert (root / "desktop-target-observation.json").read_bytes() == original
    assert notification.wc._read_object(root / "desktop-target-observation-latest.json", "latest")["thread_status"] == "idle"
