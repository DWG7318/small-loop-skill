from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "small-loop-skill"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def contract() -> dict:
    return json.loads(read(ROOT / "contracts" / "slk-control-kernel.json"))


def test_version_identity_and_owner_choice() -> None:
    version = read(ROOT / "VERSION").strip()
    assert version == "2.6.0"
    assert "# Small Loop Skill (SLK)" in read(ROOT / "SKILL.md")
    assert "Current version: **2.6.0**" in read(ROOT / "README.md")
    assert "Serial Loop Kit" not in read(ROOT / "README.md")
    assert "Serial Loop Kit" not in read(ROOT / "README.zh-CN.md")
    assert "Small Loop Skill" in read(ROOT / "SPEC.md")


def test_two_formal_conversations_one_patrol_and_three_control_modes() -> None:
    value = contract()
    assert value["product_name"] == "Small Loop Skill"
    assert value["version"] == "2.6.0"
    assert value["formal_execution_conversations"] == ["CONTROL", "WORKER"]
    assert value["visible_safeguard_conversations"] == ["RUN_PATROL"]
    assert value["visible_conversations"] == ["CONTROL", "WORKER", "RUN_PATROL"]
    assert value["control_responsibilities"] == [
        "SUPERVISOR_RESPONSIBILITY",
        "CHECKER_RESPONSIBILITY",
        "VERIFIER_RESPONSIBILITY",
    ]
    assert value["worker_count"] == 1
    assert value["active_cell_count"] == 1
    assert value["separate_verification_conversation"] is False
    assert value["blind_context_independence_claimed"] is False
    assert "D4" not in value["verification_authority"]
    patrol = value["run_patrol"]
    assert patrol["formal_technical_role"] is False
    assert patrol["count_per_run"] == 1
    assert patrol["heartbeat_count_per_run"] == 1
    assert patrol["model_policy"] == "DEFAULT_TERRA_CLASS"
    assert patrol["reasoning_effort"] == "xhigh"
    assert patrol["workload_interval_minutes"] == {
        "LOW": 10,
        "MEDIUM": 15,
        "HIGH": 30,
    }


def test_worker_wake_wait_subagent_and_progress_authority() -> None:
    value = contract()
    wake = value["worker_wake"]
    assert wake["initiators"] == ["WORKER"]
    assert wake["receiver"] == "CHECKER_RESPONSIBILITY"
    assert wake["levels"] == [1, 2, 3, 4]
    assert wake["max_wait_seconds_per_level"] == 120
    wait = value["supervisor_wait"]
    assert wait["positive_timeout_allowed"] is False
    assert wait["loop_allowed"] is False
    assert wait["snapshot_timeout_zero_allowed"] is True
    definition = value["subagent_definition"]
    assert definition["visible_peer_task_is_subagent"] is False
    assert definition["subtask_terms_are_subagents"] is False
    assert set(definition["prohibited_evidence"]) == {
        "spawn_agent",
        "delegate_task",
        "HIDDEN_AGENT",
        "BACKGROUND_AGENT",
    }
    progress = value["progress"]
    assert progress["hard_rule_number"] == 5
    assert progress["cell_numerator_source"] == "CURRENT_VALID_D1_PASS"
    assert progress["go_numerator_source"] == "CURRENT_VALID_D2_PASS"
    assert progress["worker_delivery_increments_accepted"] is False
    assert progress["go_candidate_ready_equals_d2_verified"] is False
    capacity = value["cell_capacity"]
    assert capacity["hard_rule_number"] == 6
    assert capacity["planning_owner"] == "SUPERVISOR_RESPONSIBILITY"
    assert capacity["pre_dispatch_reviewer"] == "CHECKER_RESPONSIBILITY"
    assert capacity["allowed_gate_results"] == [
        "PASS",
        "SPLIT_REQUIRED",
        "CAPACITY_BLOCKED",
    ]
    assert capacity["dispatch_requires"] == "PASS"
    assert capacity["worker_self_split_allowed"] is False
    assert capacity["post_dispatch_severe_successor_minimum"] == 3
    pin = value["thread_pin"]
    assert pin["hard_rule_number"] == 7
    assert pin["technical_roles"] == [
        "SUPERVISOR_RESPONSIBILITY",
        "CHECKER_RESPONSIBILITY",
        "VERIFIER_RESPONSIBILITY",
        "WORKER",
    ]
    assert pin["technical_role_pin_allowed_by_default"] is False
    assert pin["owner_manual_or_exact_authorization_only"] is True
    assert pin["inferred_authorization_allowed"] is False
    assert pin["run_patrol_pin_or_unpin_allowed"] is False
    assert pin["unauthorized_history_persists_after_unpin"] is True
    assert pin["alerts"] == [
        "UNAUTHORIZED_THREAD_PIN",
        "PIN_PROVENANCE_UNKNOWN",
    ]
    model = value["model_selection"]
    assert model["default_reference_model"] == "gpt-5.6-terra"
    assert model["worker_low_risk_reference_model"] == "gpt-5.6-luna"
    assert model["high_difficulty_reference_model"] == "gpt-5.6-sol"
    assert model["reasoning_effort_default"] == "xhigh"
    assert model["ultra_requires_exact_owner_authorization"] is True
    assert model["gpt_5_5_or_lower_allowed"] is False
    assert model["patrol_policy"] == "DEFAULT_TERRA_CLASS"
    assert model["same_model_collapses_role_isolation"] is False


def test_d0_d3_authority_is_non_interchangeable() -> None:
    authority = contract()["verification_authority"]
    assert authority == {
        "D0": ["WORKER"],
        "D1": ["CHECKER_RESPONSIBILITY"],
        "D2": ["VERIFIER_RESPONSIBILITY"],
        "D3": ["VERIFIER_RESPONSIBILITY"],
        "RUN_OWNER_ACCEPTANCE": ["OWNER"],
    }


def test_blank_receipts_are_fail_closed() -> None:
    expected = {
        "d0-worker-receipt.yaml": ("result", "PENDING"),
        "d1-checker-receipt.yaml": ("verdict", "PENDING"),
        "d2-go-verification-receipt.yaml": ("verdict", "PENDING"),
        "d3-run-verification-receipt.yaml": ("verdict", "PENDING"),
        "owner-acceptance-receipt.yaml": ("verdict", "PENDING"),
        "slk-run-receipt.yaml": ("status", "PENDING"),
    }
    for filename, (field, pending) in expected.items():
        root_value = yaml.safe_load(read(ROOT / "templates" / filename))
        package_value = yaml.safe_load(read(PACKAGE / "templates" / filename))
        assert root_value[field] == pending, filename
        assert package_value == root_value, filename
        assert "PASS" not in {root_value.get(field), root_value.get("owner_verdict")}
        assert root_value.get("owner_verdict") != "LOOP_OWNER_ACCEPTED"


def test_runtime_schema_templates_and_mirrors_are_closed_and_pending() -> None:
    schema = json.loads(read(ROOT / "contracts" / "slk-runtime-control.schema.json"))
    assert len(schema["oneOf"]) == 13
    assert {
        "run_runtime_contract",
        "device_capacity_profile",
        "cumulative_engineering_load",
        "cell_capacity_gate",
        "cell_capacity_event",
        "worker_wake_trace",
        "pending_wake",
        "run_patrol_receipt",
        "progress_trace",
        "runtime_simulation",
        "thread_pin_audit",
        "run_runtime_index",
        "model_binding_trace",
    } <= set(schema["$defs"])
    assert all(
        definition.get("additionalProperties") is False
        for definition in schema["$defs"].values()
        if definition.get("type") == "object"
    )
    names = {
        "run-runtime-contract.yaml",
        "device-capacity-profile.yaml",
        "cumulative-engineering-load.yaml",
        "cell-capacity-gate.yaml",
        "cell-capacity-event.yaml",
        "worker-wake-trace.yaml",
        "pending-wake.yaml",
        "run-patrol-receipt.yaml",
        "progress-trace.yaml",
        "runtime-simulation.yaml",
        "thread-pin-audit.yaml",
        "run-runtime-index.yaml",
        "model-binding-trace.yaml",
    }
    for name in names:
        root_path = ROOT / "templates" / name
        installed_path = PACKAGE / "templates" / name
        value = yaml.safe_load(read(root_path))
        assert value["status"] == "PENDING", name
        assert read(installed_path) == read(root_path), name


def test_default_prompt_contains_runtime_hard_brakes() -> None:
    prompt = yaml.safe_load(read(ROOT / "agents" / "openai.yaml"))["interface"][
        "default_prompt"
    ]
    for phrase in (
        "any positive wait_threads",
        "GO/CELL n/N",
        "gpt-5.6-terra+xhigh",
        "fine-grained/low-risk",
        "gpt-5.6-sol+xhigh",
        "gpt-5.5 and lower",
        "silent model switch",
        "CELL_CAPACITY_GATE",
        "patrol_cycle_id",
        "RUN_RUNTIME_INDEX",
        "set_thread_pinned(true)",
        "UNAUTHORIZED_THREAD_PIN",
        "PIN_PROVENANCE_UNKNOWN",
    ):
        assert phrase in prompt


def test_receipt_envelope_has_minimum_audit_fields() -> None:
    fields = set(contract()["receipt_envelope_required_fields"])
    assert {
        "receipt_id",
        "receipt_type",
        "contract_ref",
        "baseline_ref",
        "candidate_ref",
        "responsibility",
        "execution_context_ref",
        "issued_at",
        "evidence_refs",
        "consumed_receipts",
        "invalidation",
        "supersedes",
    } <= fields


def test_causal_defect_repair_is_native_and_bounded() -> None:
    value = contract()
    repair = value["defect_repair"]
    assert repair["stable_reproduction_or_documented_non_reproduction"] is True
    assert repair["root_cause_before_product_change"] is True
    assert repair["active_hypothesis_count"] == 1
    assert repair["minimal_experiment_count"] == 1
    assert repair["rejected_fix_candidate_threshold"] == 3
    assert repair["count_unit"] == "CHECKER_REJECTED_IMMUTABLE_REPAIR_CANDIDATE"
    assert repair["failed_hypotheses_count_as_fix_candidates"] is False
    assert repair["fourth_ordinary_rework_allowed"] is False
    assert repair["third_rejection_route_ref_required"] is True
    assert repair["d1_failed_candidate_equals_receipt_candidate"] is True
    assert repair["d0_failed_candidate_ref_required"] is True
    assert repair["d0_fail_before_equals_failed_candidate"] is True
    assert repair["d0_pass_after_equals_receipt_candidate"] is True
    assert repair["original_failure_round"] == 0
    assert repair["repair_candidate_minimum_round"] == 1
    assert repair["original_candidate_allowed_verdicts"] == ["FAIL"]
    assert repair["d1_pass_current_candidate_ref_required"] is True
    assert repair["d1_pass_lineage_failed_candidate_ref_required"] is True
    assert repair["repair_fail_rejected_count_offset"] == 0
    assert repair["repair_pass_rejected_count_offset"] == -1
    assert {
        "ARCHITECTURE_REVIEW_REQUIRED",
        "METHOD_BOUNDARY_EXCEEDED",
        "CONTRACT_REVISION_REQUIRED",
    } <= set(value["cell_routes"])


def test_bug_regression_first_is_proportional_not_universal_tdd() -> None:
    policy = contract()["bug_regression_first"]
    assert policy["scope"] == "DEFECT_REPAIR_ONLY"
    assert policy["required_when"] == ["STABLY_REPRODUCIBLE", "REASONABLY_AUTOMATABLE"]
    assert policy["required_evidence"] == ["FAIL_BEFORE", "PASS_AFTER", "RISK_SCALED_REGRESSION"]
    assert policy["exemption_requires_checker_approval"] is True
    assert policy["universal_tdd_required"] is False


def test_required_go_never_bypasses_d2() -> None:
    value = contract()
    assert value["required_go_completion"] == "D2_PASS"
    assert set(value["formal_resolution"]["allowed_results"]) == {
        "CANCELLED_BY_AUTHORITY",
        "REMOVED_FROM_SCOPE",
        "SUPERSEDED",
    }
    assert value["formal_resolution"]["requires_baseline_amendment"] is True
    assert value["formal_resolution"]["may_replace_required_go_d2"] is False
    spec = read(ROOT / "SPEC.md")
    assert "Every current Required GO must have D2 PASS before D3" in spec
    assert "formal resolution is not a substitute for D2" in spec


def test_lccoding_and_security_boundaries() -> None:
    value = contract()
    assert value["calabash_owner"] == "LCCODING"
    assert value["centralized_security_audit_owner"] == "LCCODING"
    assert value["run_contract_required"] is True
    brakes = set(value["security_hard_brakes"])
    assert {"CRITICAL_VULNERABILITY", "AUTHORIZATION_BYPASS", "CREDENTIAL_LEAK"} <= brakes
    assert value["known_high_risk_blocks_d3"] is True


def test_runtime_install_tree_is_mirrored() -> None:
    relative_paths = [
        Path("SKILL.md"),
        Path("contracts/slk-control-kernel.json"),
        Path("scripts/validate_serial_plan.py"),
        Path("scripts/validate_defect_repair.py"),
    ]
    relative_paths.extend(path.relative_to(ROOT) for path in sorted((ROOT / "templates").glob("*.yaml")))
    relative_paths.extend(path.relative_to(ROOT) for path in sorted((ROOT / "references").glob("*.md")))
    for relative in relative_paths:
        assert read(ROOT / relative) == read(PACKAGE / relative), relative


def test_normative_markdown_stays_bounded() -> None:
    paths = [ROOT / "SPEC.md", ROOT / "SKILL.md", PACKAGE / "SKILL.md"]
    paths.extend(sorted((ROOT / "references").glob("*.md")))
    for path in paths:
        assert len(read(path).splitlines()) <= 1000, path
