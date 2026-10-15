"""Closing one Run stops future checks, not the history of attempted notices."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("temporalio")
from slk_temporal import workflows
from .test_contracts import start_value, notification_value


PATCH = "slk-run-close-stops-runtime-checks"


def prepared(monkeypatch, run_id="RUN-A", *, legacy=False):
    run = workflows.RunSlkWorkflow()
    run._startup = workflows.StartSlkRequest.from_dict({**start_value(), "run_id": run_id})
    run._continuity = workflows.RunContinuity(run_id)
    run._admitted = True
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(workflows.workflow, "now", lambda: now)
    monkeypatch.setattr(workflows.workflow, "patched", lambda name: not (legacy and name == PATCH))
    run._next_overwatcher_audit_at = now
    run._member_residency_since = now - timedelta(minutes=30)
    run._responsibility_operation_id = "delivery-1"
    run._responsible_role_instance_id = "worker-a"
    return run


def pending_notice(run, event_id):
    notice = run._set_runtime_guard(event_id=event_id, kind="OVERWATCHER_ACTIVITY_ANOMALY",
                                    role_instance_id="overwatcher-a")
    run._pending_supervisor_notifications[event_id] = notice
    return notice


def audit_receipt(value, status):
    return {"status": status,
            **{key: value[key] for key in ("run_id", "overwatcher_role_instance_id", "audit_cycle")},
            "evidence_sha256": "a" * 64, "receipt_sha256": "b" * 64}


@pytest.mark.parametrize("outcome", ["CLEAR", "ANOMALY", "failure"])
def test_close_during_audit_stops_new_notices_retries_and_residency(monkeypatch, outcome):
    run = prepared(monkeypatch)
    old = pending_notice(run, "old-notice")
    before_deadline = run._next_overwatcher_audit_at
    activities = []

    async def activity(name, value, **_kwargs):
        activities.append((name, dict(value)))
        if name == "slk.inspect_overwatcher":
            assert run.close_run("Owner closed this exact Run") == "TERMINAL"
            if outcome == "failure":
                raise ValueError("original audit failed after the close update")
            return audit_receipt(value, outcome)
        return notification_value(value["event_id"], value["run_id"])

    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    asyncio.run(run._perform_runtime_checks())
    assert [name for name, _ in activities] == ["slk.inspect_overwatcher"]
    assert run._continuity.is_terminal()
    assert run._overwatcher_audit_cycle == 1  # The attempted audit remains real history.
    assert run._next_overwatcher_audit_at == before_deadline
    assert run._pending_supervisor_notifications == {"old-notice": old}
    assert run._runtime_guard_blocker == old
    assert run._latest_runtime_alarm_event_id == "old-notice"
    assert run._member_residency_notice_attempted is False


def test_closing_one_run_keeps_other_run_checks_and_existing_history(monkeypatch):
    run, other = prepared(monkeypatch), prepared(monkeypatch, "RUN-B")
    old = pending_notice(run, "old-notice")
    run.close_run("Owner closed only A")
    activities = []

    async def activity(name, value, **_kwargs):
        activities.append((name, dict(value)))
        if name == "slk.inspect_overwatcher":
            return audit_receipt(value, "ANOMALY")
        return notification_value(value["event_id"], value["run_id"])

    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    asyncio.run(run._perform_runtime_checks())
    asyncio.run(run._inspect_overwatcher())
    assert asyncio.run(run._notify_supervisor(old)) is False
    assert activities == []
    assert run._overwatcher_audit_cycle == 0
    assert run._pending_supervisor_notifications == {"old-notice": old}
    asyncio.run(other._perform_runtime_checks())
    assert [name for name, _ in activities] == ["slk.inspect_overwatcher", "slk.notify_supervisor", "slk.notify_supervisor"]
    assert all(value["run_id"] == "RUN-B" for _, value in activities)
    assert not other._continuity.is_terminal()
    assert other._member_residency_notice_sent is True


@pytest.mark.parametrize("delivered", [True, False])
def test_close_during_notice_keeps_real_result_without_starting_next_notice(monkeypatch, delivered):
    run = prepared(monkeypatch)
    first = pending_notice(run, "first-notice")
    second = pending_notice(run, "second-notice")
    activities = []

    async def activity(name, value, **_kwargs):
        activities.append((name, dict(value)))
        if name == "slk.inspect_overwatcher":
            return audit_receipt(value, "CLEAR")
        run.close_run("Owner closed during the already attempted notice")
        return notification_value(value["event_id"], value["run_id"]) if delivered else {}

    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    asyncio.run(run._perform_runtime_checks())
    assert [name for name, _ in activities] == ["slk.inspect_overwatcher", "slk.notify_supervisor"]
    assert activities[-1][1] == first
    expected = {"second-notice": second} if delivered else {"first-notice": first, "second-notice": second}
    assert run._pending_supervisor_notifications == expected
    assert (run._notification_failure is None) == delivered
    assert run._member_residency_notice_attempted is False


def test_old_history_keeps_post_close_commands_when_patch_is_absent(monkeypatch):
    run = prepared(monkeypatch, legacy=True)
    activities = []

    async def activity(name, value, **_kwargs):
        activities.append(name)
        if name == "slk.inspect_overwatcher":
            run.close_run("Historical close during audit")
            return audit_receipt(value, "ANOMALY")
        return notification_value(value["event_id"], value["run_id"])

    monkeypatch.setattr(workflows.workflow, "execute_activity", activity)
    asyncio.run(run._perform_runtime_checks())
    assert activities == ["slk.inspect_overwatcher", "slk.notify_supervisor", "slk.notify_supervisor"]
