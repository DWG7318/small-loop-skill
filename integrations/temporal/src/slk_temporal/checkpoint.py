"""Closed communication-only recovery packet, validated outside and inside SDK replay."""

from datetime import datetime
from typing import Mapping

from .continuity import RunContinuity
from .contracts import IDENTIFIER, SHA256, StartSlkRequest


def validate_checkpoint(value: object) -> dict:
    fields = {"schema_version", "startup", "continuity", "delivery_started", "recovery_started",
              "status", "admission_requested", "admission_request_sha256"}
    if (not isinstance(value, Mapping) or set(value) != fields
        or value["schema_version"] not in {"slk.temporal-execution-checkpoint/v1", "slk.temporal-execution-checkpoint/v2"}):
        raise ValueError("execution checkpoint is not closed")
    startup = StartSlkRequest.from_dict(value["startup"])
    continuity = RunContinuity.from_checkpoint(value["continuity"])
    pending = continuity.pending_delivery()
    v2 = value["schema_version"] == "slk.temporal-execution-checkpoint/v2"
    if continuity.run_id != startup.run_id or continuity.is_terminal() or (pending is None and not v2):
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
        or (pending is not None and pending.operation_id not in value["delivery_started"] and not v2)):
        raise ValueError("recovery cannot silently skip an unattempted delivery")
    state = value["status"]
    summary = continuity.snapshot()
    extra = {"admitted", "admission_attempt", "admission_failure", "responsible_role_instance_id",
             "responsibility_operation_id", "member_residency_since", "member_residency_notice_sent",
             "overwatcher_audit_cycle", "next_overwatcher_audit_at", "runtime_guard_blocker",
             "notification_failure", "recovery_failure"}
    if v2:
        extra.add("run_pause")
        pause = state.get("run_pause") if isinstance(state, Mapping) else None
        if (not isinstance(pause, Mapping) or set(pause) != {"phase", "pause_id", "paused_at", "events", "deferred_operation_id", "delivery_generation"}
            or pause["phase"] not in {"REQUESTED", "PAUSED", "RESUMED"}
            or not isinstance(pause["events"], Mapping) or not pause["events"]
            or not isinstance(pause["pause_id"], str) or not IDENTIFIER.fullmatch(pause["pause_id"])):
            raise ValueError("checkpoint pause lifecycle is invalid")
        if (type(pause["delivery_generation"]) is not int or pause["delivery_generation"] < 0
            or pause["deferred_operation_id"] is not None and (pending is None or pause["deferred_operation_id"] not in {
                pending.operation_id, "RETRY:" + pending.operation_id})):
            raise ValueError("checkpoint deferred pause operation is invalid")
        for event_id, event in pause["events"].items():
            event_fields = {"run_id", "supervisor_role_instance_id", "pause_id", "event_id", "phase"}
            if isinstance(event, Mapping) and "confirmed_at" in event: event_fields.add("confirmed_at")
            if (not isinstance(event, Mapping) or set(event) != event_fields
                or event["event_id"] != event_id or event["run_id"] != startup.run_id
                or event["supervisor_role_instance_id"] != startup.supervisor.role_instance_id
                or event["phase"] not in {"REQUESTED", "PAUSED", "RESUMED"}
                or not IDENTIFIER.fullmatch(str(event["pause_id"])) or not IDENTIFIER.fullmatch(str(event_id))
                or "confirmed_at" in event and (event["phase"] != "PAUSED"
                    or datetime.fromisoformat(event["confirmed_at"]).utcoffset() is None)):
                raise ValueError("checkpoint pause event changed frozen authority")
        # JSON object key order is not a lifecycle sequence. Reconstruct each
        # unique pause by its phases and require this packet's current phase.
        groups = {}
        for event in pause["events"].values():
            phases = groups.setdefault(event["pause_id"], set())
            if event["phase"] in phases: raise ValueError("checkpoint repeats a lifecycle phase")
            phases.add(event["phase"])
        expected = {"REQUESTED": {"REQUESTED"}, "PAUSED": {"REQUESTED", "PAUSED"},
                    "RESUMED": {"REQUESTED", "PAUSED", "RESUMED"}}
        if groups[pause["pause_id"]] != expected[pause["phase"]] or any(
            phases != expected["RESUMED"] for identity, phases in groups.items() if identity != pause["pause_id"]):
            raise ValueError("checkpoint pause transition is incomplete")
        if pause["phase"] in {"PAUSED", "RESUMED"}:
            if not isinstance(pause["paused_at"], str) or datetime.fromisoformat(pause["paused_at"]).utcoffset() is None:
                raise ValueError("checkpoint pause timestamp is invalid")
        if (pause["phase"] == "PAUSED" and pending is not None and pending.operation_id in value["delivery_started"]
            and pause["deferred_operation_id"] != pending.operation_id):
            raise ValueError("confirmed pause cannot retain unresolved delivery")
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
