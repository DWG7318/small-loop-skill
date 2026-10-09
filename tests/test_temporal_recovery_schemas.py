"""Closed maintenance and recovery schemas preserve their distinct assurances."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]


def validator(name):
    schema = json.loads((ROOT / "docs/contracts" / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())


def recovery_request():
    proof = {"path": "D:/isolated/immutable.json", "sha256": "a" * 64}
    return {"schema_version": "slk.temporal-execution-recovery/v1", "run_id": "RUN-A",
        **{key: proof for key in ("source_identity", "checkpoint", "source_host", "source_config", "central_projection")},
        "histories": {key: proof for key in ("start", "run")},
        "source_executions": {key: {"status": "FAILED", "close_time": "2026-10-09T00:00:00Z"} for key in ("start", "run")},
        "decision": {"supervisor_role_instance_id": "supervisor-a", "reason": "same-scope repair", "evidence_ref": "sealed-Supervisor"},
        "evidence_root": "D:/isolated/versioned"}


def test_recovery_schema_accepts_existing_supervisor_authority_without_new_owner_gate():
    validator("slk-temporal-execution-recovery.schema.json").validate(recovery_request())


@pytest.mark.parametrize("damage", ["unknown", "healthy-source", "blank-reason", "missing-history", "bad-hash"])
def test_recovery_schema_rejects_unclosed_or_unproved_inputs(damage):
    value = copy.deepcopy(recovery_request())
    if damage == "unknown": value["invented"] = True
    if damage == "healthy-source": value["source_executions"]["run"]["status"] = "RUNNING"
    if damage == "blank-reason": value["decision"]["reason"] = " "
    if damage == "missing-history": del value["histories"]["start"]
    if damage == "bad-hash": value["checkpoint"]["sha256"] = "wrong"
    with pytest.raises(jsonschema.ValidationError):
        validator("slk-temporal-execution-recovery.schema.json").validate(value)


def test_maintenance_schema_requires_explicit_purpose_not_normal_readiness(tmp_path):
    from tests.transport.test_temporal_reload import reload_request
    value = json.loads(reload_request(tmp_path).read_text())
    check = validator("slk-temporal-worker-reload.schema.json")
    check.validate(value)
    value["schema_version"] = "slk.temporal-worker-reload/v2"
    with pytest.raises(jsonschema.ValidationError): check.validate(value)
    value["purpose"] = "CLOSED_EXECUTION_MAINTENANCE"
    check.validate(value)
    value["purpose"] = "READY"
    with pytest.raises(jsonschema.ValidationError): check.validate(value)
