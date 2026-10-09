"""Closed communication-only recovery packet, validated outside and inside SDK replay."""

from datetime import datetime
from typing import Mapping

from .continuity import RunContinuity
from .contracts import IDENTIFIER, SHA256, StartSlkRequest


def validate_checkpoint(value: object) -> dict:
    fields = {"schema_version", "startup", "continuity", "delivery_started", "recovery_started",
              "status", "admission_requested", "admission_request_sha256"}
    if (not isinstance(value, Mapping) or set(value) != fields
        or value["schema_version"] != "slk.temporal-execution-checkpoint/v1"):
        raise ValueError("execution checkpoint is not closed")
    startup = StartSlkRequest.from_dict(value["startup"])
    continuity = RunContinuity.from_checkpoint(value["continuity"])
    pending = continuity.pending_delivery()
    if continuity.run_id != startup.run_id or continuity.is_terminal() or pending is None:
        raise ValueError("recovery requires the same nonterminal business Run and pending delivery")
    identities = {role.role_instance_id for role in startup.roles}
    seen = value["continuity"]["seen"]
    for delivery in seen:
        if not {delivery["sender_role_instance_id"], delivery["receiver_role_instance_id"]} <= identities:
            raise ValueError("checkpoint delivery changed frozen team")
    operations = {row["operation_id"] for row in seen}
    for field in ("delivery_started", "recovery_started"):
        rows = value[field]
        if (not isinstance(rows, list) or not all(isinstance(row, str) and row in operations for row in rows)
            or rows != sorted(set(rows))):
            raise ValueError("checkpoint activity identities changed")
    if (not set(value["recovery_started"]) <= set(value["delivery_started"])
        or pending.operation_id not in value["delivery_started"]):
        raise ValueError("recovery cannot silently skip an unattempted delivery")
    state = value["status"]
    summary = continuity.snapshot()
    extra = {"admitted", "admission_attempt", "admission_failure", "responsible_role_instance_id",
             "responsibility_operation_id", "member_residency_since", "member_residency_notice_sent",
             "overwatcher_audit_cycle", "next_overwatcher_audit_at", "runtime_guard_blocker",
             "notification_failure", "recovery_failure"}
    if (not isinstance(state, Mapping) or set(state) != set(summary) | extra
        or any(state[key] != val for key, val in summary.items()) or state["admitted"] is not True):
        raise ValueError("checkpoint summary or admission changed")
    for field in ("admission_attempt", "overwatcher_audit_cycle"):
        if type(state[field]) is not int or state[field] < 0:
            raise ValueError("checkpoint counter is invalid")
    if type(state["member_residency_notice_sent"]) is not bool or type(value["admission_requested"]) is not bool:
        raise ValueError("checkpoint flag is invalid")
    digest = value["admission_request_sha256"]
    if digest is not None and (not isinstance(digest, str) or not SHA256.fullmatch(digest)):
        raise ValueError("checkpoint admission hash is invalid")
    for field in ("member_residency_since", "next_overwatcher_audit_at"):
        raw = state[field]
        if raw is not None and (not isinstance(raw, str) or datetime.fromisoformat(raw).utcoffset() is None):
            raise ValueError("checkpoint timer must retain an aware timestamp")
    role, operation, since = (state[key] for key in (
        "responsible_role_instance_id", "responsibility_operation_id", "member_residency_since"))
    if (role is not None or operation is not None or since is not None) and (
        role not in identities or operation not in operations or since is None):
        raise ValueError("checkpoint member residency identity is incomplete")
    guard = state["runtime_guard_blocker"]
    if guard is not None and (not isinstance(guard, Mapping) or set(guard) != {
        "event_id", "kind", "run_id", "responsible_role_instance_id", "source_operation_id", "threshold_seconds"}
        or guard["run_id"] != startup.run_id or guard["responsible_role_instance_id"] not in identities
        or type(guard["threshold_seconds"]) is not int or guard["threshold_seconds"] < 0
        or not all(isinstance(guard[k], str) and IDENTIFIER.fullmatch(guard[k]) for k in (
            "event_id", "kind", "source_operation_id"))):
        raise ValueError("checkpoint guard is invalid")
    failure = state["notification_failure"]
    if failure is not None and (not isinstance(failure, Mapping) or set(failure) != {"event_id", "reason"}
        or not all(isinstance(row, str) and row for row in failure.values())):
        raise ValueError("checkpoint notification failure is invalid")
    recovery = state["recovery_failure"]
    if recovery is not None and (not isinstance(recovery, Mapping) or set(recovery) != {
        "reason", "type", "operation_id", "evidence"} or recovery["operation_id"] not in operations
        or not all(isinstance(recovery[k], str) and recovery[k] for k in ("reason", "type"))
        or recovery["evidence"] is not None and not isinstance(recovery["evidence"], Mapping)):
        raise ValueError("checkpoint recovery failure is invalid")
    if state["admission_failure"] is not None:
        raise ValueError("admitted checkpoint cannot retain admission failure")
    return dict(value)
