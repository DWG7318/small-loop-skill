from __future__ import annotations

from slk_transport.overwatcher_continuity import inspect_overwatcher_cadence
import pytest
import json
from pathlib import Path
from jsonschema import Draft202012Validator


def test_missing_current_overwatcher_alarm_matches_published_schema():
    result = inspect_overwatcher_cadence(
        {"summary": {"run_id": "RUN-A", "slk_version": "4.4.3"},
            "roles": [], "overwatch_cycles": []}, observed_at="2026-10-10T11:00:00Z")
    schema = Path(__file__).resolve().parents[2] / "docs/contracts/slk-overwatcher-cadence-inspection.schema.json"
    Draft202012Validator(json.loads(schema.read_text())).validate(result)
    assert result["anomaly_codes"] == ["OVERWATCHER_MISSING"]
    assert result["action"] == "SUPERVISOR_RECOVERY_REVIEW"


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


def test_current_method_accepts_ten_minute_cadence_and_requires_ow():
    value = projection()
    value["summary"]["slk_version"] = "4.4.0"
    value["overwatch_cycles"][0].update(cadence_seconds=600, next_cycle_at="2026-09-23T00:10:00Z")
    assert inspect_overwatcher_cadence(value, observed_at="2026-09-23T00:10:00Z")["status"] == "CURRENT"
    value["roles"] = []
    assert inspect_overwatcher_cadence(value, observed_at="2026-09-23T00:10:00Z")["action"] == "SUPERVISOR_RECOVERY_REVIEW"


def test_current_method_rejects_old_cadence():
    value = projection()
    value["summary"]["slk_version"] = "4.4.0"
    with pytest.raises(ValueError):
        inspect_overwatcher_cadence(value, observed_at="2026-09-23T00:04:00Z")


def test_443_shared_session_keeps_each_runs_cadence_separate():
    a, b = projection(), projection()
    for value, run in ((a, "RUN-A"), (b, "RUN-B")):
        value["summary"].update(run_id=run, slk_version="4.4.3")
        value["roles"][0].update(role_instance_id=run + "-ow", session_id="shared-session")
        value["overwatch_cycles"][0].update(overwatcher_role_instance_id=run + "-ow",
            cadence_seconds=600, next_cycle_at="2026-09-23T00:10:00Z")
    b["overwatch_cycles"][0].update(completed_at="2026-09-23T00:20:00Z", next_cycle_at="2026-09-23T00:30:00Z")
    assert inspect_overwatcher_cadence(a, observed_at="2026-09-23T00:25:00Z")["status"] == "CONTINUITY_UNPROVEN"
    assert inspect_overwatcher_cadence(b, observed_at="2026-09-23T00:25:00Z")["status"] == "CURRENT"
    a["roles"][0]["lifecycle"] = "closed"
    assert inspect_overwatcher_cadence(b, observed_at="2026-09-23T00:25:00Z")["status"] == "CURRENT"
