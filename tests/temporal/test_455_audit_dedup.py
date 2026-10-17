"""Keep observing, but do not create another repair for an unchanged proven cause."""
import asyncio
import copy
import json
import pytest

pytest.importorskip("temporalio")
from slk_temporal import workflows, standard_adapter
from slk_temporal.contracts import StartSlkRequest
from .test_contracts import start_value, runtime_guard_resolution_value
from .test_overwatcher_450_integration import native_config
from .test_standard_adapter import RUN_ID


def test_455_adapter_alarm_key_ignores_sample_time_not_changed_cause(tmp_path, monkeypatch):
    native_config(tmp_path, "4.5.5")
    monkeypatch.setattr(standard_adapter, "_query", lambda _: {"summary": {"run_id": RUN_ID}})
    sample = {"status": "COMPLETED_WITHOUT_TERMINAL", "error": None,
              "observed_at": "2026-10-18T00:00:00Z", "native_task_id": "child-1"}
    def command(_cmd, args, **_kw):
        if args[0] == "inspect-native-activity": return dict(sample)
        return {"status": "CONTINUITY_UNPROVEN"}
    monkeypatch.setattr(standard_adapter, "_run_json", command)
    request = {"run_id": RUN_ID, "overwatcher_role_instance_id": "ow-a",
               "endpoint_ref": "ow-endpoint-a", "audit_cycle": 1}
    first = asyncio.run(standard_adapter.inspect_overwatcher(request))
    sample["observed_at"] = "2026-10-18T00:20:00Z"
    second = asyncio.run(standard_adapter.inspect_overwatcher({**request, "audit_cycle": 2}))
    assert first["evidence_sha256"] != second["evidence_sha256"]
    assert first["alarm_key"] == second["alarm_key"]
    sample["native_task_id"] = "child-2"
    changed = asyncio.run(standard_adapter.inspect_overwatcher({**request, "audit_cycle": 3}))
    assert changed["alarm_key"] != first["alarm_key"]


@pytest.mark.parametrize("patched,expected", [(True, 1), (False, 3)])
def test_same_alarm_retains_one_obligation_but_all_three_audits(monkeypatch, patched, expected):
    instance = workflows.RunSlkWorkflow()
    instance._startup = StartSlkRequest.from_dict({**start_value(), "method_version": "4.5.5"})
    audits, notices = [], []
    async def activity(_name, value, **_kw):
        audits.append(value)
        return {"status": "EXITED", **value, "alarm_key": "c" * 64,
                "evidence_sha256": "a" * 64, "receipt_sha256": "b" * 64}
    async def closed_activity(name, value, **kwargs):
        result = await activity(name, value, **kwargs)
        result.pop("endpoint_ref")
        if not patched: result.pop("alarm_key")
        return result
    async def notify(value): notices.append(value); return True
    monkeypatch.setattr(workflows.workflow, "execute_activity", closed_activity)
    monkeypatch.setattr(workflows.workflow, "patched", lambda name: patched if name == "slk-4.5.5-audit-cause-dedup" else True)
    monkeypatch.setattr(instance, "_notify_supervisor", notify)
    for _ in range(3): asyncio.run(instance._inspect_overwatcher())
    assert len(audits) == 3
    assert len(notices) == expected
    assert instance._runtime_guard_blocker["event_id"] == notices[0]["event_id"]


def test_new_cause_clear_and_supervisor_resolution_allow_new_report(monkeypatch):
    instance = workflows.RunSlkWorkflow()
    instance._startup = StartSlkRequest.from_dict({**start_value(), "method_version": "4.5.5"})
    response = {"status": "EXITED", "alarm_key": "c" * 64}
    notices = []
    async def activity(_name, value, **_kw):
        return {**response, **{k: value[k] for k in ("run_id", "overwatcher_role_instance_id", "audit_cycle")},
                "evidence_sha256": "a" * 64, "receipt_sha256": "b" * 64}
    async def notify(value): notices.append(value); return True
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _: True)
    monkeypatch.setattr(instance, "_notify_supervisor", notify)
    asyncio.run(instance._inspect_overwatcher())
    response["alarm_key"] = "d" * 64
    asyncio.run(instance._inspect_overwatcher())
    assert len(notices) == 2
    response["status"] = "CLEAR"
    asyncio.run(instance._inspect_overwatcher())
    response["status"] = "EXITED"
    asyncio.run(instance._inspect_overwatcher())
    assert len(notices) == 3
    # Resolve the original guard; a recurrence of that same proven source must report again.
    instance._runtime_guard_blocker = dict(notices[-1])
    instance.resolve_runtime_guard({**runtime_guard_resolution_value(),
                                   "blocker_event_id": notices[-1]["event_id"]})
    asyncio.run(instance._inspect_overwatcher())
    assert len(notices) == 4


@pytest.mark.parametrize("delivered", [False, True])
@pytest.mark.parametrize("status", ["ANOMALY", "EXITED"])
def test_resolving_older_cause_keeps_newer_exact_alarm_guarded(monkeypatch, delivered, status):
    from datetime import datetime, timezone
    from temporalio.exceptions import ApplicationError
    from slk_temporal.continuity import RunContinuity
    from slk_temporal.contracts import DeliveryRequest, NativeStartAck
    from .test_contracts import delivery_value, ack_value, notification_value

    instance = workflows.RunSlkWorkflow()
    instance._startup = StartSlkRequest.from_dict({**start_value(), "method_version": "4.5.5"})
    instance._continuity = RunContinuity("RUN-A")
    original = DeliveryRequest.from_dict(delivery_value())
    instance._continuity.request_delivery(original)
    instance._continuity.acknowledge(NativeStartAck.from_dict(ack_value()))
    instance._responsibility_operation_id = original.operation_id
    instance._admitted = True
    response = {"key": "a" * 64}
    notices = []
    async def activity(name, value, **_kwargs):
        if name == "slk.notify_supervisor":
            notices.append(dict(value))
            return notification_value(value["event_id"], value["run_id"]) if delivered else {}
        assert name == "slk.inspect_overwatcher"
        return {"status": status, "alarm_key": response["key"],
            **{key: value[key] for key in ("run_id", "overwatcher_role_instance_id", "audit_cycle")},
            "evidence_sha256": "e" * 64, "receipt_sha256": "f" * 64}
    now = datetime(2026, 10, 18, tzinfo=timezone.utc)
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _: True)
    monkeypatch.setattr(workflows.workflow, "now", lambda: now)
    asyncio.run(instance._inspect_overwatcher())
    first = dict(instance._runtime_guard_blocker)
    response["key"] = "b" * 64
    asyncio.run(instance._inspect_overwatcher())
    second = dict(notices[-1])
    assert instance._runtime_guard_blocker == first  # A is still the original obligation.
    instance.resolve_runtime_guard({**runtime_guard_resolution_value(), "blocker_event_id": first["event_id"]})
    assert instance._runtime_guard_blocker == second
    with pytest.raises(ApplicationError, match="runtime guard"):
        instance.request_delivery({**delivery_value(), "operation_id": "next-cell", "message_id": "next-message",
            "cell_id": "CELL-002"})
    instance._next_overwatcher_audit_at = now
    asyncio.run(instance._perform_runtime_checks())
    assert instance._runtime_guard_blocker == second
    assert instance._overwatcher_audit_cycle == 3
    # Dedup does not create C; an undelivered B retries with its original ID.
    assert notices == ([first, second] if delivered else [first, second, second])
    instance.resolve_runtime_guard({**runtime_guard_resolution_value(), "event_id": "resolve-b",
        "blocker_event_id": second["event_id"]})
    assert instance._runtime_guard_blocker is None
    assert instance._last_overwatcher_alarm is None


def _audited_recovery(monkeypatch, *, delivered=True, newer=False):
    from datetime import datetime, timezone
    from .test_contracts import notification_value
    from .test_recovery_client import packet

    instance = workflows.RunSlkWorkflow()
    source = packet("4.5.5")
    instance._startup = StartSlkRequest.from_dict(source["startup"])
    instance._restore_checkpoint(source)
    response = {"key": "a" * 64, "delivered": delivered}
    audits, notices = [], []
    async def activity(name, value, **_kwargs):
        if name == "slk.notify_supervisor":
            notices.append(dict(value))
            return notification_value(value["event_id"], value["run_id"]) if response["delivered"] else {}
        assert name == "slk.inspect_overwatcher"
        audits.append(dict(value))
        return {"status": "EXITED", "alarm_key": response["key"],
            **{key: value[key] for key in ("run_id", "overwatcher_role_instance_id", "audit_cycle")},
            "evidence_sha256": "e" * 64, "receipt_sha256": "f" * 64}
    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    monkeypatch.setattr(workflows.workflow, "patched", lambda _: True)
    monkeypatch.setattr(workflows.workflow, "now", lambda: datetime(2026, 10, 18, tzinfo=timezone.utc))
    asyncio.run(instance._inspect_overwatcher())
    if newer:
        response["key"] = "b" * 64
        asyncio.run(instance._inspect_overwatcher())
    return instance, audits, notices, response


@pytest.mark.parametrize("delivered", [False, True])
@pytest.mark.parametrize("newer", [False, True])
def test_checkpoint_restores_original_cause_and_exact_notification_retry(monkeypatch, delivered, newer):
    from slk_temporal.checkpoint import validate_checkpoint
    from slk_temporal.recovery_client import verify_restored_checkpoint

    instance, audits, notices, response = _audited_recovery(monkeypatch, delivered=delivered, newer=newer)
    original = copy.deepcopy(notices)
    source = json.loads(json.dumps(instance.recovery_checkpoint()))
    assert source["status"]["last_overwatcher_alarm"] == {
        "alarm_key": response["key"], "blocker": original[-1]}
    validate_checkpoint(source)
    restored = workflows.RunSlkWorkflow()
    restored._startup = instance._startup
    restored._restore_checkpoint(source)
    verify_restored_checkpoint(source, restored.recovery_checkpoint(), initial=True)
    # A fresh observation still occurs, but only unfinished original IDs retry.
    restored._next_overwatcher_audit_at = workflows.workflow.now()
    asyncio.run(restored._perform_runtime_checks())
    assert len(audits) == len(original) + 1
    assert notices == (original if delivered else original + original)
    assert restored._runtime_guard_blocker == original[0]
    restored.resolve_runtime_guard({**runtime_guard_resolution_value(), "blocker_event_id": original[0]["event_id"]})
    if newer:
        assert restored._runtime_guard_blocker == original[-1]
        restored.resolve_runtime_guard({**runtime_guard_resolution_value(), "event_id": "resolve-b",
            "blocker_event_id": original[-1]["event_id"]})
    assert restored._runtime_guard_blocker is None
    assert "last_overwatcher_alarm" not in restored.recovery_checkpoint()["status"]


def test_legacy_checkpoint_missing_cause_is_valid_and_reobserved(monkeypatch):
    from slk_temporal.checkpoint import validate_checkpoint
    from slk_temporal.recovery_client import verify_restored_checkpoint

    instance, audits, notices, _ = _audited_recovery(monkeypatch)
    source = instance.recovery_checkpoint()
    source["status"].pop("last_overwatcher_alarm", None)
    validate_checkpoint(source)
    restored = workflows.RunSlkWorkflow()
    restored._startup = instance._startup
    restored._restore_checkpoint(source)
    assert restored._last_overwatcher_alarm is None
    verify_restored_checkpoint(source, restored.recovery_checkpoint(), initial=True)
    asyncio.run(restored._inspect_overwatcher())
    assert len(audits) == 2
    assert len(notices) == 2
    assert restored._runtime_guard_blocker == notices[0]


def test_restored_dedup_does_not_hide_a_new_observed_cause(monkeypatch):
    instance, audits, notices, response = _audited_recovery(monkeypatch)
    restored = workflows.RunSlkWorkflow()
    restored._startup = instance._startup
    restored._restore_checkpoint(instance.recovery_checkpoint())
    response["key"] = "b" * 64
    asyncio.run(restored._inspect_overwatcher())
    assert len(audits) == len(notices) == 2
    assert notices[0]["event_id"] != notices[1]["event_id"]
    restored.resolve_runtime_guard({**runtime_guard_resolution_value(), "blocker_event_id": notices[0]["event_id"]})
    assert restored._runtime_guard_blocker == notices[1]


@pytest.mark.parametrize("damage", ["extra", "hash", "version", "blocker-extra", "run", "role", "kind",
    "source", "threshold", "event", "future-event", "pending-conflict", "guard-conflict"])
def test_checkpoint_cause_is_closed_and_bound_to_original_obligation(monkeypatch, damage):
    from slk_temporal.checkpoint import validate_checkpoint

    instance, _, notices, response = _audited_recovery(monkeypatch, delivered=False)
    source = copy.deepcopy(instance.recovery_checkpoint())
    alarm = source["status"].setdefault("last_overwatcher_alarm", {
        "alarm_key": response["key"], "blocker": dict(notices[0])})
    blocker = alarm["blocker"]
    if damage == "extra": alarm["unexpected"] = True
    if damage == "hash": alarm["alarm_key"] = "A" * 64
    if damage == "version": source["startup"]["method_version"] = "4.5.4"
    if damage == "blocker-extra": blocker["unexpected"] = True
    if damage == "run": blocker["run_id"] = "OTHER"
    if damage == "role": blocker["responsible_role_instance_id"] = "supervisor-a"
    if damage == "kind": blocker["kind"] = "MEMBER_RESIDENCY_EXCEEDED"
    if damage == "source": blocker["source_operation_id"] = "other"
    if damage == "threshold": blocker["threshold_seconds"] = True
    if damage in {"event", "future-event"}:
        blocker["event_id"] = "invented" if damage == "event" else "RUN-A-overwatcher-audit-2"
        blocker["source_operation_id"] = "runtime-guard-" + blocker["event_id"]
    if damage == "pending-conflict": source["status"]["pending_supervisor_notifications"][blocker["event_id"]]["kind"] = "OTHER"
    if damage == "guard-conflict": source["status"]["runtime_guard_blocker"]["kind"] = "OTHER"
    with pytest.raises(ValueError): validate_checkpoint(source)


@pytest.mark.parametrize("damage", ["dropped", "changed"])
def test_recovery_verifier_rejects_valid_but_changed_cause(monkeypatch, damage):
    from slk_temporal.recovery_client import verify_restored_checkpoint

    instance, _, _, _ = _audited_recovery(monkeypatch)
    source = instance.recovery_checkpoint()
    target = copy.deepcopy(source)
    if damage == "dropped": target["status"].pop("last_overwatcher_alarm", None)
    else: target["status"].setdefault("last_overwatcher_alarm", {})["alarm_key"] = "b" * 64
    with pytest.raises(ValueError): verify_restored_checkpoint(source, target, initial=True)


@pytest.mark.parametrize("field,value", [("run_id", "OTHER"), ("supervisor_role_instance_id", "checker-a"),
    ("blocker_event_id", "other-event")])
def test_restored_cause_does_not_expand_resolution_authority(monkeypatch, field, value):
    from temporalio.exceptions import ApplicationError

    instance, _, notices, _ = _audited_recovery(monkeypatch)
    restored = workflows.RunSlkWorkflow()
    restored._startup = instance._startup
    restored._restore_checkpoint(instance.recovery_checkpoint())
    with pytest.raises(ApplicationError, match="authority or blocker"):
        restored.resolve_runtime_guard({**runtime_guard_resolution_value(),
            "blocker_event_id": notices[0]["event_id"], field: value})
    assert restored._runtime_guard_blocker == notices[0]

