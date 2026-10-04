from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from slk_transport.run_readiness import evaluate_run_readiness


REQUIRED_OPTIONS = ("Ponytail", "RTK", "Probe CLI")
REQUIRED_LEGS = (
    ("SETUP_TO_CHECKER", "supervisor", "checker"),
    ("CELL_TO_WORKER", "checker", "worker"),
    ("CANDIDATE_TO_CHECKER", "worker", "checker"),
    ("D1_FAIL_TO_SUPERVISOR", "checker", "supervisor"),
    ("REWORK_TO_WORKER", "supervisor", "worker"),
    ("D2_READY_TO_SUPERVISOR", "checker", "supervisor"),
    ("ANOMALY_TO_SUPERVISOR", "overwatcher", "supervisor"),
)


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def _request(tmp_path: Path) -> dict[str, object]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    endpoint = tmp_path / "endpoint.json"
    endpoint.write_text("{}\n", encoding="utf-8")
    skill = tmp_path / "SKILL.md"
    skill.write_text("# role\n", encoding="utf-8")
    capabilities = {}
    for runtime, events in (
        ("dsh", ["agent/status", "session/event"]),
        ("ocrv", ["review/progress", "task/status"]),
        ("lcas", ["session/status", "observation/cycle"]),
    ):
        capability = tmp_path / f"{runtime}-native-activity.json"
        capability.write_text(
            json.dumps(
                {
                    "schema_version": "slk.native-activity-capability/v1",
                    "method_version": "4.4.0",
                    "runtime": runtime,
                    "read_only_observation": True,
                    "model_call_required": False,
                    "native_events": events,
                }
            ),
            encoding="utf-8",
        )
        capabilities[runtime] = str(capability)
    roles = []
    for role, runtime, model in (
        ("supervisor", "codex", "gpt-5.6-sol"),
        ("worker", "dsh", "deepseek-v4-flash"),
        ("checker", "ocrv", "qwen3.8-max"),
        ("overwatcher", "lcas", "gpt-6-luna"),
    ):
        roles.append(
            {
                "role": role,
                "role_instance_id": f"RUN-READINESS-A-{role}",
                "expected_runtime": runtime,
                "actual_runtime": runtime,
                "expected_model": model,
                "actual_model": model,
                "adapter_command": [sys.executable, "--version"],
                "endpoint_path": str(endpoint),
                "workspace_root": str(workspace),
                "context_capacity": 100_000,
                "task_context_estimate": 10_000,
                "required_skills": [str(skill)],
                "required_tools": [sys.executable],
                "native_activity_capability": capabilities.get(runtime),
                "tool_update_status": "CURRENT",
            }
        )
    bi_receipt = write_json(
        tmp_path / "bi-open.json",
        {
            "schema_version": "slk.bi-open-readiness/v1",
            "method_version": "4.4.0",
            "run_id": "RUN-READINESS-A",
            "bi_version": "1.1.0",
            "device_id": "device-a",
            "visible": True,
            "evidence_sha256": "a" * 64,
        },
    )
    temporal_receipt = write_json(
        tmp_path / "temporal-ready.json",
        {
            "schema_version": "slk.temporal-readiness/v1",
            "method_version": "4.4.0",
            "run_id": "RUN-READINESS-A",
            "status": "READY",
            "service_mode": "SHARED_LOCAL",
            "workflow_templates": ["SLK.Start", "SLK.Run"],
            "evidence_sha256": "b" * 64,
        },
    )
    rehearsal = write_json(
        tmp_path / "communication-rehearsal.json",
        {
            "schema_version": "slk.communication-rehearsal/v1",
            "method_version": "4.4.0",
            "run_id": "RUN-READINESS-A",
            "status": "PASS",
            "legs": [
                {
                    "leg_id": leg_id,
                    "sender_role": sender,
                    "receiver_role": receiver,
                    "sent_receipt_sha256": "c" * 64,
                    "receiver_started_sha256": "d" * 64,
                    "response_receipt_sha256": "e" * 64,
                }
                for leg_id, sender, receiver in REQUIRED_LEGS
            ],
        },
    )
    return {
        "schema_version": "slk.run-readiness-request/v1",
        "run_id": "RUN-READINESS-A",
        "plan_revision": 1,
        "roles": roles,
        "bi_open_receipt": str(bi_receipt),
        "temporal_readiness_receipt": str(temporal_receipt),
        "communication_rehearsal": str(rehearsal),
        "optional_features": [
            {"name": name, "decision": "OFF", "owner_evidence_ref": f"owner:{name}"}
            for name in REQUIRED_OPTIONS
        ],
    }


def test_four_role_readiness_is_ready_only_when_every_fact_and_route_is_closed(
    tmp_path: Path,
) -> None:
    result = evaluate_run_readiness(_request(tmp_path))

    assert result["status"] == "READY"
    assert {item["role"] for item in result["roles"]} == {
        "supervisor",
        "worker",
        "checker",
        "overwatcher",
    }
    assert {item["status"] for item in result["roles"]} == {"READY"}
    assert result["optional_features"][0]["owner_evidence_ref"].startswith("owner:")


def test_missing_checker_capability_keeps_run_in_preparation(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["roles"][2]["required_tools"] = [str(tmp_path / "missing-ocrv")]

    result = evaluate_run_readiness(request)

    assert result["status"] == "REPAIR_NEEDED"
    checker = next(item for item in result["roles"] if item["role"] == "checker")
    assert checker["status"] == "REPAIR_NEEDED"
    assert "REQUIRED_TOOL_MISSING" in checker["reason_codes"]


def test_missing_overwatcher_or_failed_normal_route_rehearsal_blocks_start(tmp_path: Path) -> None:
    missing_role = _request(tmp_path)
    missing_role["roles"] = [row for row in missing_role["roles"] if row["role"] != "overwatcher"]
    with pytest.raises(ValueError, match="exactly one"):
        evaluate_run_readiness(missing_role)

    failed_route = _request(tmp_path)
    path = Path(failed_route["communication_rehearsal"])
    receipt = json.loads(path.read_text(encoding="utf-8"))
    receipt["legs"][2]["receiver_started_sha256"] = ""
    path.write_text(json.dumps(receipt), encoding="utf-8")
    result = evaluate_run_readiness(failed_route)
    assert result["status"] == "REPAIR_NEEDED"
    assert "COMMUNICATION_REHEARSAL_INVALID" in result["reason_codes"]


def test_tool_upgrade_need_and_missing_bi_or_temporal_proof_block_start(tmp_path: Path) -> None:
    update = _request(tmp_path)
    update["roles"][1]["tool_update_status"] = "UPDATE_REQUIRED"
    result = evaluate_run_readiness(update)
    assert result["status"] == "REPAIR_NEEDED"
    assert "TOOL_UPDATE_REQUIRED" in result["reason_codes"]

    missing = _request(tmp_path)
    Path(missing["bi_open_receipt"]).unlink()
    Path(missing["temporal_readiness_receipt"]).unlink()
    result = evaluate_run_readiness(missing)
    assert "BI_OPEN_RECEIPT_INVALID" in result["reason_codes"]
    assert "TEMPORAL_READINESS_INVALID" in result["reason_codes"]


def test_missing_or_wrong_native_activity_capability_blocks_worker_and_checker(
    tmp_path: Path,
) -> None:
    missing = _request(tmp_path)
    missing["roles"][1]["native_activity_capability"] = str(tmp_path / "missing.json")

    result = evaluate_run_readiness(missing)

    assert result["status"] == "REPAIR_NEEDED"
    worker = next(item for item in result["roles"] if item["role"] == "worker")
    assert "NATIVE_ACTIVITY_CAPABILITY_MISSING" in worker["reason_codes"]

    wrong = _request(tmp_path)
    checker_capability = Path(wrong["roles"][2]["native_activity_capability"])
    value = json.loads(checker_capability.read_text(encoding="utf-8"))
    value["runtime"] = "dsh"
    checker_capability.write_text(json.dumps(value), encoding="utf-8")

    result = evaluate_run_readiness(wrong)

    checker = next(item for item in result["roles"] if item["role"] == "checker")
    assert "NATIVE_ACTIVITY_CAPABILITY_INVALID" in checker["reason_codes"]


def test_role_context_smaller_than_task_is_incompatible(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["roles"][1]["task_context_estimate"] = 100_001

    result = evaluate_run_readiness(request)

    assert result["status"] == "INCOMPATIBLE"
    worker = next(item for item in result["roles"] if item["role"] == "worker")
    assert worker["reason_codes"] == ["TASK_EXCEEDS_CONTEXT_CAPACITY"]


def test_unconfirmed_or_missing_optional_feature_keeps_run_in_preparation(tmp_path: Path) -> None:
    unconfirmed = _request(tmp_path)
    unconfirmed["optional_features"][0] = {
        "name": "Ponytail",
        "decision": "UNCONFIRMED",
        "owner_evidence_ref": "",
    }
    result = evaluate_run_readiness(unconfirmed)
    assert result["status"] == "REPAIR_NEEDED"
    assert "OPTION_DECISION_REQUIRED" in result["reason_codes"]

    missing = _request(tmp_path)
    missing["optional_features"] = missing["optional_features"][:-1]
    result = evaluate_run_readiness(missing)
    assert result["status"] == "REPAIR_NEEDED"
    assert "REQUIRED_OPTION_MISSING" in result["reason_codes"]


def test_role_substitution_is_not_repairable_by_prompt(tmp_path: Path) -> None:
    request = copy.deepcopy(_request(tmp_path))
    request["roles"][2]["actual_runtime"] = "codex"

    result = evaluate_run_readiness(request)

    assert result["status"] == "INCOMPATIBLE"
    checker = next(item for item in result["roles"] if item["role"] == "checker")
    assert "RUNTIME_MISMATCH" in checker["reason_codes"]
    json.dumps(result)


def test_future_option_is_allowed_but_still_requires_owner_confirmation(tmp_path: Path) -> None:
    request = _request(tmp_path)
    request["optional_features"].append(
        {"name": "Future Tool", "decision": "UNCONFIRMED", "owner_evidence_ref": ""}
    )

    result = evaluate_run_readiness(request)

    assert result["status"] == "REPAIR_NEEDED"
    assert "OPTION_DECISION_REQUIRED" in result["reason_codes"]


@pytest.mark.parametrize("decision", ["ON", "OFF"])
def test_bom_is_forbidden_instead_of_owner_configurable(
    tmp_path: Path, decision: str
) -> None:
    request = _request(tmp_path)
    request["optional_features"].append(
        {"name": "BoM", "decision": decision, "owner_evidence_ref": "owner:legacy"}
    )

    result = evaluate_run_readiness(request)

    assert result["status"] == "REPAIR_NEEDED"
    assert "OPTION_FORBIDDEN" in result["reason_codes"]
    assert all(item["name"] != "BoM" for item in result["optional_features"])
