from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validate_role_eval import EvalError, load_pack, pack_sha256, validate_response
from scripts.build_transport_zipapp import build_zipapp


ROOT = Path(__file__).parents[2]
PACK = ROOT / "skills" / "small-loop-skill" / "assets" / "SLK-ROLE-EVAL.v1.json"


# Guidance ownership/reachability is tested in test_skill_collection_300.py.
# This module exercises the exact Eval asset and runtime validator behavior.

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
    assert pack["method_version"] == "4.5.5"
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


def test_standard_transport_artifact_exposes_role_eval_validator(tmp_path: Path) -> None:
    artifact = build_zipapp(tmp_path / "slk-transport.pyz")
    response = tmp_path / "response.json"
    response.write_text(json.dumps(valid_response()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(artifact),
            "validate-role-eval",
            "--pack",
            str(PACK),
            "--response",
            str(response),
            "--run-id",
            "RUN-A",
            "--project-id",
            "project-a",
            "--plan-revision",
            "3",
            "--role",
            "checker",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"status": "PASS", "role": "checker", "case_count": 8}


def test_supervisor_active_parent_rejects_exit_and_child_wake() -> None:
    response = valid_response("supervisor")
    answer = next(row for row in response["answers"] if row["case_id"] == "SUP-ACTIVE-PARENT")
    assert answer["choice"] == "KEEP_ACTIVE_WITH_BOUNDED_NATIVE_WAIT"
    answer["choice"] = "END_TURN_WAIT_FOR_CHILD_WAKE"
    with pytest.raises(EvalError):
        validate_response(PACK, response, expected_run_id="RUN-A", expected_project_id="project-a",
                          expected_plan_revision=3, expected_role="supervisor")


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
        "SUP-DSH-AWARE-CELL-SPLIT",
        "SUP-SECOND-D1-FAIL-SPLIT",
    } <= case_ids

    split = next(case for case in load_pack(PACK)["cases"]
                 if case["case_id"] == "SUP-DSH-AWARE-CELL-SPLIT")
    assert split["role"] == "supervisor"
    assert split["runtime_critical"] is False
    assert split["correct_choice"] == "PRESPLIT_FOR_DSH_WITH_ACCEPTANCE_PRESERVED"
    second_fail = next(case for case in load_pack(PACK)["cases"]
                       if case["case_id"] == "SUP-SECOND-D1-FAIL-SPLIT")
    assert second_fail["role"] == "supervisor"
    assert second_fail["runtime_critical"] is False
    assert second_fail["correct_choice"] == "REPLAN_AND_SPLIT_BEFORE_REDISPATCH"


def test_current_eval_distinguishes_original_read_action_normal_recovery_and_shared_pause():
    cases = {case["case_id"]: case for case in load_pack(PACK)["cases"]}
    expected = {
        "CHK-D1-INCOMPLETE": "ESCALATE_INCOMPLETE_TO_SUPERVISOR",
        "CHK-WHOLE-CANDIDATE": "CHECK_ALL_CELL_CRITERIA_ONCE",
        "CHK-GIT-EXTERNAL-ORIGINAL": "READ_HASH_BOUND_ORIGINAL_BEFORE_DECIDING",
        "CHK-FINAL-DECISION-ACTION": "DECIDE_AND_HANDOFF_AS_FINAL_ACTION",
        "SUP-NORMAL-NOT-RECOVERY": "VERIFY_ORIGINAL_NORMAL_LEG",
        "SUP-NO-INSPECTION-CELL": "KEEP_VERIFICATION_IN_D0_D1_D2",
        "OVW-SHARED-AUTHORIZED-PAUSE": "OBSERVE_PAUSED_A_AND_ACTIVE_B",
        "SUP-PAUSE-TIME-FACTS": "COUNT_THIRTY_WORK_MINUTES",
    }
    for identity, choice in expected.items():
        assert cases[identity]["correct_choice"] == choice
        assert choice in cases[identity]["choices"]


def test_pack_covers_preparation_goal_only_without_growing_runtime_subset() -> None:
    cases = {case["case_id"]: case for case in load_pack(PACK)["cases"]}
    for identity in ("SUP-PREP-GOAL-RESUME", "SUP-PREP-GOAL-ERROR", "SUP-PREP-GOAL-NATIVE",
                     "SUP-PREP-GOAL-CLOSE", "SUP-PREP-GOAL-SCOPE", "SUP-PREP-GOAL-UNAVAILABLE",
                     "SUP-PREP-GOAL-OWNER-STOP", "SUP-PREP-GOAL-CONFLICT"):
        assert cases[identity]["role"] == "supervisor"
        assert cases[identity]["runtime_critical"] is False


def test_450_preparation_can_end_before_first_cell_and_goal_is_optional() -> None:
    cases = {case["case_id"]: case for case in load_pack(PACK)["cases"]}
    expected = {
        "SUP-PREP-GOAL-NATIVE": "COMPLETE_PREPARATION_FROM_CURRENT_READINESS",
        "SUP-PREP-GOAL-CLOSE": "COMPLETE_OPTIONAL_PREPARATION_GOAL",
        "SUP-PREP-GOAL-UNAVAILABLE": "CONTINUE_PREPARATION_WITHOUT_GOAL",
    }
    for identity, choice in expected.items():
        assert cases[identity]["correct_choice"] == choice
        assert choice in cases[identity]["choices"]
        assert cases[identity]["runtime_critical"] is False
    native = cases["SUP-PREP-GOAL-NATIVE"]
    assert "首 CELL" in native["scenario"]
    assert "无首轮 cycle" in native["scenario"]
    assert "不以首 CELL" in native["rule"]


def test_450_current_readiness_does_not_require_historical_conformance() -> None:
    cases = {case["case_id"]: case for case in load_pack(PACK)["cases"]}
    fixed = cases["SUP-FIXED-RUNTIMES"]
    assert fixed["correct_choice"] == "REQUIRE_PREFLIGHT_READY"
    assert "当前" in fixed["rule"]
    assert "七条必要通讯腿都" not in fixed["rule"]
    assert "历史 conformance" in fixed["rule"]
    assert "可选" in fixed["rule"]
    normal = cases["SUP-NORMAL-NOT-RECOVERY"]
    assert normal["correct_choice"] == "VERIFY_ORIGINAL_NORMAL_LEG"
    assert "不作普通新 Run 开工前演练门槛" in normal["rule"]


def test_451_field_repairs_and_sealed_decisions_are_development_cases_not_new_preflight() -> None:
    cases = {case["case_id"]: case for case in load_pack(PACK)["cases"]}
    expected = {
        "SUP-ONSITE-MISSING-DELIVERY": "DELIVER_EXISTING_ORIGINAL_AS_SUPERVISOR",
        "CHK-REUSED-GROUPS-NO-D1": "MAKE_ONE_WHOLE_CELL_DECISION",
        "CHK-SAVED-D1-HANDOFF-FAILED": "KEEP_D1_RESUME_MISSING_HANDOFF",
        "WRK-CURRENT-CELL-SCOPE": "USE_CURRENT_CELL_REPLACING_OLD_SCOPE",
    }
    for identity, choice in expected.items():
        assert cases[identity]["correct_choice"] == choice
        assert choice in cases[identity]["choices"]
        assert cases[identity]["runtime_critical"] is False


def test_450_one_direct_overwatcher_child_is_not_shared_across_supervisors() -> None:
    cases = {case["case_id"]: case for case in load_pack(PACK)["cases"]}
    shared = cases["SUP-SHARED-EXACT-WATCHER-SESSION"]
    assert shared["runtime_critical"] is True
    assert shared["correct_choice"] == "ALLOW_ONLY_SAME_SUPERVISOR_RUNS"
    assert "ALLOW_CROSS_SUPERVISOR_REUSE" in shared["choices"]
    assert "直属" in shared["rule"]
    assert "不跨 Supervisor" in shared["rule"]
    response = valid_response("supervisor")
    answer = next(item for item in response["answers"] if item["case_id"] == shared["case_id"])
    answer["choice"] = "ALLOW_CROSS_SUPERVISOR_REUSE"
    with pytest.raises(EvalError):
        validate_response(
            PACK, response, expected_run_id="RUN-A", expected_project_id="project-a",
            expected_plan_revision=3, expected_role="supervisor",
        )


def test_450_overwatcher_native_parent_report_is_not_engineering_handoff() -> None:
    cases = {case["case_id"]: case for case in load_pack(PACK)["cases"]}
    report = cases["OVW-ANOMALY-REPORT-AND-CONTINUE"]
    assert report["correct_choice"] == "KEEP_OBSERVING_WITHOUT_DUPLICATE_ALERT"
    assert "父子消息" in report["scenario"]
    assert "工程 ACK/TOKEN" in report["rule"]
    assert "已读" in report["rule"]
    unknown = cases["OVW-PROJECTED-ACTIVE-IS-UNKNOWN"]
    assert unknown["correct_choice"] == "REPORT_UNKNOWN_TO_SUPERVISOR"
    assert "UNKNOWN 不是退出" in unknown["rule"]
    assert "不必强制重启" in unknown["rule"]
    lifecycle = cases["OVW-DEDICATED-LIFECYCLE"]
    assert "所属 Supervisor" in lifecycle["rule"]
    assert "二次确认" in lifecycle["rule"]


def test_pack_covers_423_runtime_consistency_failures() -> None:
    pack = load_pack(PACK)
    case_ids = {case["case_id"] for case in pack["cases"]}
    assert {
        "SUP-ATOMIC-NATIVE-START",
        "SUP-ACTIVE-WRITER-NEW-MESSAGE",
        "SUP-NO-LEGACY-423-HANDOFF",
        "SUP-NO-AUTO-MODEL-UPGRADE",
        "SUP-NO-EXTRA-RECOVERY-ROLE",
        "WRK-GIT-WORKSPACE-PREFLIGHT",
        "OVW-ONE-WHOLE-RUN-BINDING",
        "OVW-PROJECTED-ACTIVE-IS-UNKNOWN",
        "OVW-HASHED-EVIDENCE",
        "OVW-NO-CELL-BOUNDARY-CLOSE",
        "OVW-ONE-RUNTIME-REVISION",
    } <= case_ids


def test_pack_covers_424_worker_completion_guard_failures() -> None:
    pack = load_pack(PACK)
    case_ids = {case["case_id"] for case in pack["cases"]}
    assert {
        "CHK-RECOVER-SAME-CANDIDATE",
        "WRK-TERMINAL-IS-NOT-D1-START",
        "OVW-WORKER-COMPLETION-GUARD",
    } <= case_ids


def test_pack_covers_426_real_cell03_recovery_failures() -> None:
    pack = load_pack(PACK)
    case_ids = {case["case_id"] for case in pack["cases"]}
    assert {
        "SUP-OVERWATCHER-GUARD-REPAIR",
        "CHK-TRANSPORT-FAIL-SAME-ATTEMPT",
        "WRK-CODE-DONE-IS-NOT-HANDOFF",
        "OVW-ANOMALY-REPORT-AND-CONTINUE",
    } <= case_ids


def test_pack_covers_4210_field_correction_failures() -> None:
    pack = load_pack(PACK)
    case_ids = {case["case_id"] for case in pack["cases"]}
    assert {
        "SUP-NO-DELAYED-SELF-WAKE",
        "CHK-LOW-ONLY-NOT-FAIL",
        "WRK-NO-RECOVERY-REPLAY",
        "OVW-SHARED-AUTHORIZED-PAUSE",
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
