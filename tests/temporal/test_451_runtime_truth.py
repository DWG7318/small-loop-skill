"""4.5.1 truth-preserving regressions; clocks and native calls are simulated."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from slk_temporal import workflows, standard_adapter
from slk_temporal.contracts import StartSlkRequest, RuntimeGuardResolution
from slk_temporal.continuity import RunContinuity
from .test_contracts import start_value, runtime_guard_resolution_value
from .test_overwatcher_450_integration import native_config
from .test_standard_adapter import RUN_ID, current_cadence, config_root


def member(monkeypatch):
    run = workflows.RunSlkWorkflow()
    run._startup = StartSlkRequest.from_dict(start_value())
    run._continuity = RunContinuity(run._startup.run_id)
    clock = [datetime(2026, 10, 13, tzinfo=timezone.utc)]
    monkeypatch.setattr(workflows.workflow, "now", lambda: clock[0])
    monkeypatch.setattr(workflows.workflow, "patched", lambda _: True)
    run._member_residency_since = clock[0] - timedelta(minutes=30)
    run._responsibility_operation_id = "delivery-1"
    run._responsible_role_instance_id = "worker-a"
    run._next_overwatcher_audit_at = clock[0] + timedelta(minutes=10)
    return run, clock


def test_failed_member_notice_is_not_sent_and_does_not_leave_expired_timer(monkeypatch):
    run, clock = member(monkeypatch)
    notices = []
    async def notify(value):
        notices.append(value)
        return False
    monkeypatch.setattr(run, "_notify_supervisor", notify)
    asyncio.run(run._perform_runtime_checks())
    assert run._member_residency_notice_sent is False
    assert run.status()["member_residency_notice_attempted"] is True
    assert run._runtime_check_timeout() == 600
    asyncio.run(run._perform_runtime_checks())
    assert len(notices) == 1


def test_legacy_replay_keeps_recorded_notice_result(monkeypatch):
    run, _clock = member(monkeypatch)
    monkeypatch.setattr(workflows.workflow, "patched", lambda name: name != "slk-4.5.1-notification-truth")
    async def notify(_value): return False
    monkeypatch.setattr(run, "_notify_supervisor", notify)
    asyncio.run(run._perform_runtime_checks())
    assert run._member_residency_notice_sent is True


def test_pending_notice_retries_same_identity_only_at_existing_audit(monkeypatch):
    from .test_contracts import notification_value
    run, clock = member(monkeypatch)
    calls = []
    async def activity(name, value, **_kwargs):
        assert name == "slk.notify_supervisor"
        calls.append(dict(value))
        return {} if len(calls) == 1 else notification_value(value["event_id"], value["run_id"])
    async def inspect(): pass
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(run, "_inspect_overwatcher", inspect)
    asyncio.run(run._perform_runtime_checks())
    assert run._member_residency_notice_sent is False
    assert len(run.status()["pending_supervisor_notifications"]) == 1
    asyncio.run(run._perform_runtime_checks())
    assert len(calls) == 1
    clock[0] += timedelta(minutes=10)
    asyncio.run(run._perform_runtime_checks())
    assert calls == [calls[0], calls[0]]
    assert run._member_residency_notice_sent is True
    assert run.status()["pending_supervisor_notifications"] == {}
    assert run._runtime_check_timeout() == 1200


def test_checkpoint_roundtrip_retains_failed_notice_attempt_and_exact_pending_identity(monkeypatch):
    from .test_recovery_client import packet as checkpoint
    from slk_temporal.checkpoint import validate_checkpoint
    packet = checkpoint()
    packet["status"].update(member_residency_notice_attempted=True,
        pending_supervisor_notifications={}, latest_runtime_alarm_event_id="alarm-77")
    assert validate_checkpoint(packet)["status"] == packet["status"]


def test_recovery_accepts_new_truth_fields_but_never_drops_earlier_pending_notice():
    import copy
    from .test_recovery_client import packet
    from slk_temporal.recovery_client import verify_restored_checkpoint
    source = packet()
    target = copy.deepcopy(source)
    target["status"].update(member_residency_notice_attempted=False, pending_supervisor_notifications={})
    verify_restored_checkpoint(source, target, initial=True)
    source = copy.deepcopy(target)
    source["status"]["pending_supervisor_notifications"] = {"alarm-77": {"event_id": "alarm-77",
        "kind": "OVERWATCHER_ACTIVITY_ANOMALY", "run_id": "RUN-A", "responsible_role_instance_id": "overwatcher-a",
        "source_operation_id": "runtime-guard-alarm-77", "threshold_seconds": 0}}
    with pytest.raises(ValueError): verify_restored_checkpoint(source, target, initial=True)


def test_exact_guard_resolution_retires_only_original_not_newer_same_ow_alarm(monkeypatch):
    run, _clock = member(monkeypatch)
    first = run._set_runtime_guard(event_id="alarm-77", kind="OVERWATCHER_ACTIVITY_ANOMALY", role_instance_id="ow-a")
    later = run._set_runtime_guard(event_id="alarm-78", kind="OVERWATCHER_ACTIVITY_ANOMALY", role_instance_id="ow-a")
    run._pending_supervisor_notifications = {"alarm-77": first, "alarm-78": later}
    run._notification_failure = {"event_id": "alarm-77", "reason": "SUPERVISOR_NOTIFICATION_UNPROVED"}
    run.resolve_runtime_guard({**runtime_guard_resolution_value(), "blocker_event_id": "alarm-77"})
    assert run._pending_supervisor_notifications == {"alarm-78": later}
    assert run._notification_failure["event_id"] == "alarm-77"


def test_retry_of_old_failed_notice_does_not_rename_latest_alarm(monkeypatch):
    run, _clock = member(monkeypatch)
    first = run._set_runtime_guard(event_id="alarm-77", kind="OVERWATCHER_ACTIVITY_ANOMALY", role_instance_id="ow-a")
    async def activity(*_args, **_kwargs): return {}
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    asyncio.run(run._notify_supervisor(first))
    run._set_runtime_guard(event_id="alarm-78", kind="OVERWATCHER_ACTIVITY_ANOMALY", role_instance_id="ow-a")
    asyncio.run(run._notify_supervisor(first))
    assert run.status()["latest_runtime_alarm_event_id"] == "alarm-78"
    assert run.status()["runtime_guard_blocker"]["event_id"] == "alarm-77"


def test_new_alarm_during_old_notice_retry_keeps_latest_identity(monkeypatch):
    run, _clock = member(monkeypatch)
    first = run._set_runtime_guard(event_id="alarm-77", kind="OVERWATCHER_ACTIVITY_ANOMALY", role_instance_id="ow-a")
    run._pending_supervisor_notifications = {"alarm-77": first}
    async def activity(*_args, **_kwargs):
        run._set_runtime_guard(event_id="alarm-78", kind="OVERWATCHER_ACTIVITY_ANOMALY", role_instance_id="ow-a")
        return {}
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    assert asyncio.run(run._notify_supervisor(first)) is False
    assert run.status()["latest_runtime_alarm_event_id"] == "alarm-78"
    assert run.status()["runtime_guard_blocker"]["event_id"] == "alarm-77"


def test_exact_resolution_during_notification_activity_is_not_undone_by_late_failure(monkeypatch):
    run, _clock = member(monkeypatch)
    notice = run._set_runtime_guard(event_id="alarm-77", kind="OVERWATCHER_ACTIVITY_ANOMALY", role_instance_id="ow-a")
    async def activity(*_args, **_kwargs):
        run.resolve_runtime_guard({**runtime_guard_resolution_value(), "blocker_event_id": "alarm-77"})
        return {}
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    assert asyncio.run(run._notify_supervisor(notice)) is False
    assert run._runtime_guard_blocker is None
    assert run._pending_supervisor_notifications == {}
    assert run._notification_failure["event_id"] == "alarm-77"


def test_exact_resolution_during_audit_skips_already_captured_retry(monkeypatch):
    run, clock = member(monkeypatch)
    notice = run._set_runtime_guard(event_id="alarm-77", kind="OVERWATCHER_ACTIVITY_ANOMALY", role_instance_id="ow-a")
    run._pending_supervisor_notifications = {"alarm-77": notice}
    run._next_overwatcher_audit_at = clock[0]
    run._member_residency_notice_sent = True
    async def inspect():
        run.resolve_runtime_guard({**runtime_guard_resolution_value(), "blocker_event_id": "alarm-77"})
    async def notify(_notice): pytest.fail("resolved notice was retried")
    monkeypatch.setattr(run, "_inspect_overwatcher", inspect)
    monkeypatch.setattr(run, "_notify_supervisor", notify)
    asyncio.run(run._perform_runtime_checks())


@pytest.mark.parametrize("age,expected", [(661, "LATE"), (1200, "LATE"), (2904, "ANOMALY")])
def test_native_active_late_cycle_is_not_dead(tmp_path, monkeypatch, age, expected):
    native_config(tmp_path)
    monkeypatch.setattr(standard_adapter, "_query", lambda _: {"summary": {"run_id": RUN_ID}})
    monkeypatch.setattr(standard_adapter, "_run_json", lambda _command, args, **_kw:
        {**current_cadence(), "status": "LATE", "elapsed_seconds": age}
        if args[0] == "inspect-overwatcher-cadence" else {"status": "ACTIVE", "error": None})
    result = asyncio.run(standard_adapter.inspect_overwatcher({"run_id": RUN_ID,
        "overwatcher_role_instance_id": "ow-a", "endpoint_ref": "ow-endpoint-a", "audit_cycle": 1}))
    assert result["status"] == expected


@pytest.mark.parametrize("method_version", ["4.5.1", "4.5.2"])
def test_451_configuration_and_startup_use_native_subagent_semantics(tmp_path, method_version):
    import json
    from pathlib import Path
    from .test_standard_adapter import write_json
    root, config = native_config(tmp_path)
    config["method_version"] = method_version
    proof = Path(config["overwatcher_activity"]["attestation_path"])
    write_json(proof, {**json.loads(proof.read_text()), "method_version": method_version})
    config["overwatcher_activity"]["attestation_sha256"] = standard_adapter._sha256(proof)
    write_json(root / f"{RUN_ID}.json", config)
    assert standard_adapter._load_config(RUN_ID)["method_version"] == method_version
    assert StartSlkRequest.from_dict({**start_value(), "method_version": method_version}).method_version == method_version


def test_generic_guard_recovery_keeps_exact_earliest_identity(monkeypatch):
    run, _clock = member(monkeypatch)
    first = run._set_runtime_guard(event_id="alarm-77", kind="RECOVERY_ACTIVITY_FAILED", role_instance_id="worker-a")
    latest = run._set_runtime_guard(event_id="alarm-78", kind="OVERWATCHER_ACTIVITY_ANOMALY", role_instance_id="ow-a")
    assert run.status()["runtime_guard_blocker"] == first
    assert run.status()["latest_runtime_alarm_event_id"] == latest["event_id"]
    packet = {**runtime_guard_resolution_value(), "resolution": "EXACT_RUNTIME_RECOVERY_VERIFIED", "blocker_event_id": "alarm-78"}
    assert RuntimeGuardResolution.from_dict(packet).resolution == "EXACT_RUNTIME_RECOVERY_VERIFIED"
    with pytest.raises(Exception, match="blocker"):
        run.resolve_runtime_guard(packet)
    packet["blocker_event_id"] = "alarm-77"
    assert run.resolve_runtime_guard(packet) == "RUNTIME_GUARD_REPAIRED"


def test_notification_retry_preserves_original_projection_and_checks_current_target(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    root, config = config_root(tmp_path)
    standard_adapter.configure(root)
    projection = {"summary": {"run_id": RUN_ID}, "runtime_snapshot": {"runtime_revision": 9}, "roles": []}
    monkeypatch.setattr(standard_adapter, "_query", lambda _: dict(projection))
    requests = []
    def command(_command, args, **_kw):
        request = json.loads(Path(args[args.index("--request") + 1]).read_text())
        requests.append(request)
        return {"status": "NOTIFIED"}
    monkeypatch.setattr(standard_adapter, "_run_json", command)
    value = {"event_id": "retry-event", "kind": "MEMBER_RESIDENCY_EXCEEDED", "run_id": RUN_ID,
        "responsible_role_instance_id": "worker-a", "source_operation_id": "operation-a", "threshold_seconds": 1800}
    asyncio.run(standard_adapter.notify_supervisor(value))
    original = Path(requests[0]["runtime_projection_path"]).read_bytes()
    projection["runtime_snapshot"] = {"runtime_revision": 10}
    asyncio.run(standard_adapter.notify_supervisor(value))
    assert Path(requests[0]["runtime_projection_path"]).read_bytes() == original
    assert requests[0] == requests[1]
