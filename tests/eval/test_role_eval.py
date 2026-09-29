from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.validate_role_eval import EvalError, load_pack, pack_sha256, validate_response


ROOT = Path(__file__).parents[2]
PACK = ROOT / "skills" / "small-loop-skill" / "assets" / "SLK-ROLE-EVAL.v1.json"


def valid_response(role: str = "checker") -> dict[str, object]:
    pack = load_pack(PACK)
    cases = [case for case in pack["cases"] if case["role"] == role and case["runtime_critical"]]
    return {
        "schema_version": "slk.role-eval-response/v1",
        "run_id": "RUN-A",
        "project_id": "project-a",
        "plan_revision": 3,
        "role": role,
        "case_pack_sha256": pack_sha256(PACK),
        "answers": [
            {"case_id": case["case_id"], "choice": case["correct_choice"]}
            for case in cases
        ],
    }


def test_pack_is_closed_comprehensive_and_runtime_subset_is_bounded() -> None:
    pack = load_pack(PACK)
    assert pack["schema_version"] == "slk.role-eval-pack/v1"
    assert pack["method_version"] == "4.3.2"
    assert len(pack["cases"]) >= 36
    for role in ("supervisor", "checker", "worker", "overwatcher"):
        role_cases = [case for case in pack["cases"] if case["role"] == role]
        assert len(role_cases) >= 9
        assert sum(case["runtime_critical"] for case in role_cases) == 8


@pytest.mark.parametrize("role", ["supervisor", "checker", "worker", "overwatcher"])
def test_each_role_passes_only_its_eight_exact_runtime_cases(role: str) -> None:
    result = validate_response(
        PACK,
        valid_response(role),
        expected_run_id="RUN-A",
        expected_project_id="project-a",
        expected_plan_revision=3,
        expected_role=role,
    )
    assert result == {"status": "PASS", "role": role, "case_count": 8}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["answers"].pop(),
        lambda value: value["answers"].append(
            {"case_id": "EXTRA", "choice": "ALLOW"}
        ),
        lambda value: value["answers"].append(copy.deepcopy(value["answers"][0])),
        lambda value: value.update(role="worker"),
        lambda value: value["answers"][0].update(choice="WRONG"),
        lambda value: value.update(schema_version="slk.role-eval-response/v2"),
        lambda value: value.update(case_pack_sha256="0" * 64),
        lambda value: value["answers"][0].update(
            case_id=str(value["answers"][0]["case_id"]).lower()
        ),
        lambda value: value["answers"][0].update(
            case_id=f" {value['answers'][0]['case_id']}"
        ),
        lambda value: value.update(plan_revision=2),
        lambda value: value.update(answers=[], claim="I understand SLK"),
    ],
)
def test_response_mutations_fail_closed(mutate) -> None:
    response = valid_response()
    mutate(response)
    with pytest.raises(EvalError):
        validate_response(
            PACK,
            response,
            expected_run_id="RUN-A",
            expected_project_id="project-a",
            expected_plan_revision=3,
            expected_role="checker",
        )


def test_unknown_fields_and_identity_whitespace_fail_closed() -> None:
    response = valid_response()
    response["extra"] = True
    with pytest.raises(EvalError):
        validate_response(
            PACK,
            response,
            expected_run_id="RUN-A",
            expected_project_id="project-a",
            expected_plan_revision=3,
            expected_role="checker",
        )

    response = valid_response()
    response["project_id"] = "project-a "
    with pytest.raises(EvalError):
        validate_response(
            PACK,
            response,
            expected_run_id="RUN-A",
            expected_project_id="project-a",
            expected_plan_revision=3,
            expected_role="checker",
        )


def test_pack_bytes_are_stable_json_and_do_not_embed_project_paths() -> None:
    pack = load_pack(PACK)
    encoded = json.dumps(pack, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert "D:/" not in encoded
    assert "C:/" not in encoded


def test_pack_covers_fixed_topology_incomplete_and_supervisor_rework() -> None:
    pack = load_pack(PACK)
    case_ids = {case["case_id"] for case in pack["cases"]}
    assert {
        "SUP-FIXED-RUNTIMES",
        "CHK-D1-INCOMPLETE",
        "SUP-D1-FAIL-DIRECTIVE",
        "OVW-FOREGROUND-ACTIVE",
        "OVW-NO-SCHEDULER-SUBSTITUTE",
        "SUP-IDENTITY-NO-SQL",
        "SUP-ADOPT-EXPLICITLY",
        "SUP-ADMIN-HISTORY-IMMUTABLE",
        "OVW-ADOPTION-GATE",
    } <= case_ids


def test_pack_covers_423_runtime_consistency_failures() -> None:
    pack = load_pack(PACK)
    case_ids = {case["case_id"] for case in pack["cases"]}
    assert {
        "SUP-ATOMIC-NATIVE-START",
        "SUP-ACTIVE-WRITER-NEW-MESSAGE",
        "SUP-NO-LEGACY-423-HANDOFF",
        "SUP-NO-AUTO-MODEL-UPGRADE",
        "SUP-NO-BOM-RUNTIME",
        "WRK-GIT-WORKSPACE-PREFLIGHT",
        "OVW-ONE-WHOLE-RUN-BINDING",
        "OVW-LATE-IS-NOT-INACTIVE",
        "OVW-HASHED-EVIDENCE",
        "OVW-NO-CELL-BOUNDARY-CLOSE",
        "OVW-ONE-RUNTIME-REVISION",
    } <= case_ids


def test_pack_covers_424_worker_completion_guard_failures() -> None:
    pack = load_pack(PACK)
    case_ids = {case["case_id"] for case in pack["cases"]}
    assert {
        "CHK-RESUME-SAME-WORKER",
        "WRK-TERMINAL-IS-NOT-HANDOFF",
        "OVW-WORKER-COMPLETION-GUARD",
    } <= case_ids


def test_pack_covers_426_real_cell03_recovery_failures() -> None:
    pack = load_pack(PACK)
    case_ids = {case["case_id"] for case in pack["cases"]}
    assert {
        "SUP-RESUME-SAME-OVERWATCHER-SESSION",
        "CHK-TRANSPORT-FAIL-SAME-ATTEMPT",
        "WRK-CODE-DONE-IS-NOT-HANDOFF",
        "OVW-ANOMALY-REPORT-THEN-PAUSE",
    } <= case_ids


def test_pack_covers_4210_field_correction_failures() -> None:
    pack = load_pack(PACK)
    case_ids = {case["case_id"] for case in pack["cases"]}
    assert {
        "SUP-NO-DELAYED-SELF-WAKE",
        "CHK-LOW-ONLY-NOT-FAIL",
        "WRK-RESUMED-NATIVE-IDENTITY",
        "OVW-THREE-LEGAL-EXITS",
    } <= case_ids


@pytest.mark.parametrize(
    ("case_id", "wrong_choice"),
    [
        ("OVW-FOREGROUND-ACTIVE", "END_TURN_UNTIL_WOKEN"),
        ("OVW-NO-SCHEDULER-SUBSTITUTE", "CREATE_HEARTBEAT_OR_SCHEDULED_TASK"),
    ],
)
def test_overwatcher_passive_or_scheduled_substitutes_fail_closed(
    case_id: str, wrong_choice: str
) -> None:
    response = valid_response("overwatcher")
    answer = next(item for item in response["answers"] if item["case_id"] == case_id)
    answer["choice"] = wrong_choice
    with pytest.raises(EvalError):
        validate_response(
            PACK,
            response,
            expected_run_id="RUN-A",
            expected_project_id="project-a",
            expected_plan_revision=3,
            expected_role="overwatcher",
        )
