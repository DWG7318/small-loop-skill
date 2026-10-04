"""Read-only cadence inspection; legacy evidence does not redefine current readiness."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


class OverwatcherContinuityError(ValueError):
    pass


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise OverwatcherContinuityError("Overwatcher cadence timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OverwatcherContinuityError("Overwatcher cadence timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise OverwatcherContinuityError("Overwatcher cadence timestamp requires a timezone")
    return parsed


def inspect_overwatcher_cadence(
    projection: Mapping[str, Any],
    *,
    observed_at: str,
) -> dict[str, Any]:
    """Classify cycle freshness without treating an active projection as live execution."""

    summary = projection.get("summary")
    roles = projection.get("roles")
    cycles = projection.get("overwatch_cycles")
    if not isinstance(summary, Mapping) or not isinstance(roles, list) or not isinstance(cycles, list):
        raise OverwatcherContinuityError("Run projection is incomplete")
    run_id = summary.get("run_id")
    active = [
        item
        for item in roles
        if isinstance(item, Mapping)
        and item.get("role") == "overwatcher"
        and item.get("lifecycle") == "active"
    ]
    if len(active) > 1:
        raise OverwatcherContinuityError("Run projection has multiple active Overwatchers")
    base = {
        "schema_version": "slk.overwatcher-cadence-inspection/v1",
        "run_id": run_id,
        "observed_at": observed_at,
        "projected_active": bool(active),
        "overwatcher_role_instance_id": active[0].get("role_instance_id") if active else None,
        "latest_cycle_id": None,
        "latest_cycle_completed_at": None,
        "cadence_seconds": None,
        "elapsed_seconds": None,
        "missed_intervals": 0,
        "anomaly_codes": [],
        "action": "NONE",
    }
    now = _time(observed_at)
    current_method = summary.get("slk_version") in {"4.4.0", "4.4.1"}
    if not active:
        if current_method:
            return {**base, "status": "CONTINUITY_UNPROVEN", "anomaly_codes": ["OVERWATCHER_MISSING"],
                    "action": "SUPERVISOR_RECOVERY_REVIEW"}
        return {**base, "status": "ABSENT"}
    matching = [
        item
        for item in cycles
        if isinstance(item, Mapping)
        and item.get("overwatcher_role_instance_id") == active[0].get("role_instance_id")
    ]
    if not matching:
        return {
            **base,
            "status": "CONTINUITY_UNPROVEN",
            "anomaly_codes": ["OVERWATCHER_CONTINUITY_UNPROVEN"],
            "action": "SUPERVISOR_RECOVERY_REVIEW",
        }
    latest = max(matching, key=lambda item: int(item.get("cycle_sequence", 0)))
    cadence = latest.get("cadence_seconds")
    if isinstance(cadence, bool) or not isinstance(cadence, int) or (
        cadence != 600 if current_method else not 180 <= cadence <= 300
    ):
        raise OverwatcherContinuityError("Overwatcher cadence is invalid")
    completed = _time(latest.get("completed_at"))
    next_cycle = _time(latest.get("next_cycle_at"))
    if int((next_cycle - completed).total_seconds()) != cadence:
        raise OverwatcherContinuityError("Overwatcher next-cycle boundary is invalid")
    elapsed = int((now - completed).total_seconds())
    if elapsed < 0:
        raise OverwatcherContinuityError("Observed time precedes the latest Overwatcher cycle")
    current = {
        **base,
        "latest_cycle_id": latest.get("cycle_id"),
        "latest_cycle_completed_at": latest.get("completed_at"),
        "cadence_seconds": cadence,
        "elapsed_seconds": elapsed,
        "missed_intervals": elapsed // cadence,
    }
    if elapsed <= cadence:
        return {**current, "status": "CURRENT"}
    if elapsed <= cadence * 2:
        return {
            **current,
            "status": "LATE",
            "anomaly_codes": ["OVERWATCHER_CADENCE_LATE"],
            "action": "WAKE_BOUND_OVERWATCHER",
        }
    return {
        **current,
        "status": "CONTINUITY_UNPROVEN",
        "anomaly_codes": ["OVERWATCHER_CADENCE_LATE", "OVERWATCHER_CONTINUITY_UNPROVEN"],
        "action": "SUPERVISOR_RECOVERY_REVIEW",
    }
