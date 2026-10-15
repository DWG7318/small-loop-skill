"""Exercise the OW fragment with schema and member-evidence checks.

This does not authenticate an actual OW activation; the Rust integration test
separately exercises the central writer with isolated evidence fixtures.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from slk_transport import native_activity, overwatcher_admin as admin
from test_overwatcher_admin import request_fixture, write_json

ROOT = Path(__file__).resolve().parents[2]


def example():
    text = (ROOT / "skills/slk-overwatch-run/references/cycle-evidence.md").read_text(encoding="utf-8")
    match = re.search(r"```json\n(.*?)\n```", text, re.S)
    assert match, "OW needs a consumer-valid example, not a nonexistent verdict field"
    return json.loads(match[1])


def test_documented_member_unknown_passes_schema_and_member_evidence_check(tmp_path, monkeypatch):
    monkeypatch.setattr(admin.wc, "_default_load_current_projection",
                        lambda *_a, **_k: json.loads((tmp_path / "runtime.json").read_text()))
    request = request_fixture(tmp_path)
    cycle = json.loads(Path(json.loads(request.read_text())["operation_request_path"]).read_text())
    projection = json.loads((tmp_path / "runtime.json").read_text())
    projection["roles"][0]["role"] = "checker"
    write_json(tmp_path / "runtime.json", projection)
    query = native_activity.collect_overwatch_scope(None, run_id="RUN-A", state_command=["slk-state"])
    assert query["native_activity"]["status"] == "UNKNOWN"
    query_path = write_json(tmp_path / "scope-query.json", query)
    own_proof = write_json(tmp_path / "own-proof.json", {"fixture": "isolated own-activation evidence"})
    completed = datetime.fromisoformat(query["query_completed_at"].replace("Z", "+00:00"))
    cycle.update(example())
    cycle.update(session_id="exact-child", foreground_turn_id="exact-activation", binding_revision=1,
        cycle_sequence=1, latest_event_id="latest-event", cost_metrics=None,
        native_active_session_evidence_ref=str(own_proof),
        next_cycle_at=(completed + timedelta(seconds=600)).isoformat().replace("+00:00", "Z"),
        started_at=query["query_started_at"], completed_at=query["query_completed_at"],
        evidence_refs=[{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                       for path in (query_path, own_proof)])
    schema = json.loads((ROOT / "docs/contracts/slk-overwatch-cycle.schema.json").read_text())
    Draft202012Validator(schema).validate(cycle)
    assert cycle["native_liveness"] == "IN_PROGRESS"
    assert cycle["checklist"]["active_session"] == "CLEAR"
    assert cycle["checklist"]["stall_and_duplicates"] == "ANOMALY"
    assert cycle["anomaly_codes"] == ["ACTIVITY_UNPROVEN"]
    admin._verify_cycle(cycle, "RUN-A", ["slk-state"])
    cycle["checklist"]["stall_and_duplicates"] = "CLEAR"
    with pytest.raises(ValueError, match="unproven"):
        admin._verify_cycle(cycle, "RUN-A", ["slk-state"])
