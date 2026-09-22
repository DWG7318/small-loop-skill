from __future__ import annotations

from slk_transport.overwatcher_continuity import inspect_overwatcher_cadence


def projection(*, completed_at: str = "2026-09-23T00:00:00Z") -> dict[str, object]:
    return {
        "summary": {"run_id": "RUN-A"},
        "roles": [
            {
                "role": "overwatcher",
                "role_instance_id": "RUN-A-overwatcher-001",
                "lifecycle": "active",
            }
        ],
        "overwatch_cycles": [
            {
                "cycle_id": "cycle-54",
                "cycle_sequence": 54,
                "overwatcher_role_instance_id": "RUN-A-overwatcher-001",
                "cadence_seconds": 240,
                "completed_at": completed_at,
                "next_cycle_at": "2026-09-23T00:04:00Z",
            }
        ],
    }


def test_active_projection_does_not_hide_a_missed_overwatcher_cadence() -> None:
    late = inspect_overwatcher_cadence(projection(), observed_at="2026-09-23T00:06:00Z")
    unproven = inspect_overwatcher_cadence(projection(), observed_at="2026-09-23T00:12:00Z")

    assert late["projected_active"] is True
    assert late["status"] == "LATE"
    assert late["action"] == "WAKE_BOUND_OVERWATCHER"
    assert unproven["projected_active"] is True
    assert unproven["status"] == "CONTINUITY_UNPROVEN"
    assert unproven["action"] == "SUPERVISOR_RECOVERY_REVIEW"


def test_fresh_cycle_and_optional_absence_do_not_raise_false_alarm() -> None:
    current = inspect_overwatcher_cadence(projection(), observed_at="2026-09-23T00:04:00Z")
    absent_projection = {"summary": {"run_id": "RUN-A"}, "roles": [], "overwatch_cycles": []}
    absent = inspect_overwatcher_cadence(absent_projection, observed_at="2026-09-23T00:12:00Z")

    assert current["status"] == "CURRENT"
    assert current["anomaly_codes"] == []
    assert absent["status"] == "ABSENT"
    assert absent["action"] == "NONE"
