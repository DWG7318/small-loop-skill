from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts import validate_repository


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_repository_validator_passes_for_the_current_collection() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_repository.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: SLK 4.4.3 skill collection" in result.stdout


def test_manifest_covers_the_collection_and_excludes_itself() -> None:
    manifest = json.loads(read("MANIFEST.json"))
    paths = {item["path"] for item in manifest["files"]}
    assert manifest["name"] == "Small Loop Skill Collection"
    assert manifest["version"] == "4.4.3"
    assert manifest["skill_count"] == len(validate_repository.EXPECTED_SKILLS)
    assert "MANIFEST.json" not in paths
    assert "skills/small-loop-skill/SKILL.md" in paths
    assert "skills/slk-close-run/SKILL.md" in paths
    assert "skills/slk-guard-resources/SKILL.md" in paths
    assert "skills/slk-record-run/assets/SLK-RUN.template.md" in paths


def test_426_public_runtime_contracts_are_closed_and_versioned() -> None:
    contracts = {
        "docs/contracts/slk-transport-task.schema.json": {
            "schema_version", "message_id", "run_id", "go_id", "cell_id",
            "endpoint", "envelope", "result_contract", "result_path",
        },
        "docs/contracts/slk-runtime-snapshot.schema.json": {
            "run_id", "runtime_revision", "plan_revision", "token_sequence",
            "token_holder_role_instance_id", "latest_event_id",
            "latest_message_id", "method_version", "overwatcher_binding_revision",
            "overwatcher_status", "committed_at",
        },
        "docs/contracts/slk-overwatch-cycle.schema.json": {
            "cycle_id", "run_id", "plan_revision", "role_instance_id",
            "session_id", "foreground_turn_id", "binding_revision",
            "runtime_revision", "native_liveness", "cycle_sequence",
            "cadence_seconds", "go_id", "cell_id", "attempt", "token_sequence",
            "token_holder_role_instance_id", "latest_event_id",
            "latest_message_id", "checklist", "anomaly_codes", "evidence_refs",
            "cost_metrics", "native_active_session_evidence_ref", "started_at",
            "completed_at", "next_cycle_at",
        },
        "docs/contracts/slk-worker-completion-inspection.schema.json": {
            "schema_version", "run_id", "go_id", "cell_id", "attempt", "source_message_id",
            "worker_role_instance_id", "observed_at", "cadence_seconds", "status",
                "grace_started_at", "anomaly_codes", "notification_already_sent",
                "missing_worker_events", "candidate", "worker_outcome", "blocker",
                "handoff_message_id",
        },
        "docs/contracts/slk-worker-continuation.schema.json": {
            "schema_version", "method_version", "run_id", "go_id", "cell_id", "attempt",
            "plan_revision", "runtime_revision", "source_message_id", "source_attempt_root",
            "continuation_result_path", "source_endpoint_sha256", "source_envelope_sha256",
            "source_runtime_projection_sha256", "source_runtime_snapshot", "recovery_mode",
            "worker_result_path", "worker_result_sha256", "source_terminal_sha256",
            "source_task_sha256", "source_started_sha256", "source_invalid_result_sha256",
            "source_candidate", "source_candidate_parent", "source_repository",
            "source_changed_paths", "supplement_result_contract",
            "worker_role_instance_id", "worker_instance_id",
            "worker_session_id", "checker_endpoint", "credential_path", "state_command",
            "transport_command", "token_sequence", "checker_token_already_committed", "occurred_at",
        },
        "docs/contracts/slk-ocrv-worker-recovery.schema.json": {
            "schema_version", "method_version", "recovery_invocation_id",
            "recovery_envelope_message_id", "run_id", "go_id", "cell_id",
            "checker_role_instance_id", "checker_endpoint_version", "checker_endpoint",
            "source_attempt_root", "runtime_projection_path", "plan_revision",
            "runtime_revision", "token_sequence", "worker_credential_path",
            "checker_credential_path", "state_command", "transport_command",
            "occurred_at", "result_path",
        },
        "docs/contracts/slk-ocrv-worker-recovery-result.schema.json": {
            "schema_version", "method_version", "status", "run_id", "cell_id",
            "source_message_id", "worker_session_id", "checker_role_instance_id",
            "checker_endpoint_version", "checker_authenticated", "authorized_recovery",
            "recovery_invocation_id", "request_sha256", "runtime_revision", "token_sequence",
            "checker_token_already_committed", "native_attempt_path", "d1_verdict",
            "d1_event_type", "native_result_path",
        },
        "docs/contracts/slk-pre-d0-blocked-recovery.schema.json": {
            "schema_version", "recovery_kind", "source_message_id",
            "candidate_repository", "candidate_commit", "tool_path", "tool_sha256",
            "state_config_path", "state_config_sha256", "d0_environment", "d0_command",
        },
        "docs/contracts/slk-ocrv-committed-terminal.schema.json": {
            "schema_version", "method_version", "recovery_invocation_id", "run_id",
            "go_id", "cell_id", "attempt", "plan_revision", "runtime_revision",
            "token_sequence", "worker_role_instance_id", "checker_role_instance_id",
            "checker_endpoint_version", "checker_endpoint", "runtime_projection_path",
            "runtime_projection_sha256", "candidate_repository", "candidate_commit",
            "candidate_parent", "candidate_message_id", "payload_sha256",
            "candidate_submitted_event_id", "transport_started_event_id",
            "commit_request_path", "commit_request_sha256", "native_attempt_path",
            "raw_review_path", "immutable_sha256", "recovery_terminal", "checker_credential_path",
            "state_command", "transport_command", "result_path",
        },
        "docs/contracts/slk-ocrv-incomplete-checker-resume.schema.json": {
            "schema_version", "method_version", "recovery_invocation_id",
            "run_id", "go_id", "cell_id", "attempt", "plan_revision",
            "runtime_revision", "token_sequence", "worker_role_instance_id",
            "checker_role_instance_id", "checker_endpoint_version", "checker_endpoint",
            "runtime_projection_path", "runtime_projection_sha256", "candidate_repository",
            "candidate_commit", "candidate_parent", "candidate_message_id", "payload_sha256",
            "candidate_submitted_event_id", "transport_started_event_id",
            "commit_request_path", "commit_request_sha256", "native_attempt_path",
            "checker_credential_path", "state_command", "transport_command",
            "immutable_sha256", "result_path", "background_path", "ocrv_session",
            "recovery_root",
        },
        "docs/contracts/slk-ocrv-terminal-budget-resume.schema.json": {
            "schema_version", "method_version", "recovery_invocation_id", "run_id",
            "go_id", "cell_id", "attempt", "plan_revision", "runtime_revision",
            "token_sequence", "worker_role_instance_id", "checker_role_instance_id",
            "checker_endpoint_version", "checker_endpoint", "runtime_projection_path",
            "runtime_projection_sha256", "candidate_repository", "candidate_commit",
            "candidate_parent", "candidate_message_id", "payload_sha256",
            "candidate_submitted_event_id", "transport_started_event_id",
            "commit_request_path", "commit_request_sha256", "native_attempt_path",
            "raw_review_path", "immutable_sha256", "checker_credential_path",
            "state_command", "transport_command", "result_path", "d1_started_event_id",
            "d1_incomplete_event_id", "ocrv_preflight_path", "ocrv_preflight_sha256",
            "background_path", "background_sha256", "native_activity_path",
            "native_activity_sha256", "session_record_path", "session_record_sha256",
                    "ocrv_session", "capacity_revision", "ocrv_transition",
                    "runtime_config_binding", "owner_authorization", "role_host_binding_path",
                    "role_host_binding_sha256", "recovery_root",
        },
        "docs/contracts/slk-ocrv-terminal-budget-resume-result.schema.json": {
            "schema_version", "method_version", "status", "run_id", "cell_id", "attempt",
            "candidate_message_id", "checker_role_instance_id", "checker_endpoint_version",
                "recovery_invocation_id", "request_sha256", "capacity_revision_sha256",
                    "ocrv_transition_sha256", "runtime_config_binding_sha256",
                "source_d1_incomplete_event_id", "parent_session_id", "child_session_id",
                    "d1_verdict", "d1_event_type", "corrected_d1_event_id", "suffix_mode",
                    "suffix_request_path", "suffix_result_path", "suffix_status",
            "native_attempt_path", "native_result_path",
        },
        "docs/contracts/slk-ocrv-terminal-budget-fresh-review.schema.json": {
            "schema_version", "strategy", "recovery_invocation_id", "source_request_path",
            "source_request_sha256", "rejection_native_attempt_path",
            "rejection_evidence_sha256", "source_rejection_sha256", "owner_authorization",
            "recovery_root", "result_path",
        },
        "docs/contracts/slk-ocrv-terminal-budget-fresh-review-result.schema.json": {
            "schema_version", "method_version", "status", "run_id", "cell_id", "attempt",
            "candidate_message_id", "checker_role_instance_id", "checker_endpoint_version",
            "recovery_invocation_id", "request_sha256", "capacity_revision_sha256",
            "source_rejection_sha256", "compatibility_authorization_sha256",
            "source_d1_incomplete_event_id", "parent_session_id", "child_session_id",
            "d1_verdict", "d1_event_type", "corrected_d1_event_id", "suffix_mode",
            "suffix_request_path", "suffix_result_path", "suffix_status",
            "native_attempt_path", "native_result_path",
        },
        "docs/contracts/slk-ocrv-committed-terminal-result.schema.json": {
            "schema_version", "method_version", "status", "run_id", "cell_id",
            "attempt", "candidate_message_id", "checker_role_instance_id",
            "checker_endpoint_version", "checker_authenticated",
            "authorized_existing_terminal", "recovery_invocation_id", "request_sha256",
            "runtime_revision", "token_sequence", "native_attempt_path", "d1_verdict",
            "d1_event_type", "native_result_path",
        },
        "docs/contracts/slk-checker-post-d1.schema.json": {
            "schema_version", "method_version", "post_d1_invocation_id", "run_id",
            "go_id", "cell_id", "attempt", "plan_revision", "runtime_revision",
            "token_sequence", "checker_role_instance_id", "d1_failure_event_id",
            "runtime_projection_path", "native_attempt_path", "supervisor_endpoint_path",
            "checker_credential_path", "state_command", "transport_command",
            "escalation_attempt_root", "rework_round", "cell_goal", "acceptance_criteria",
            "findings", "reproduction_steps", "expected_result", "evidence_refs", "occurred_at",
        },
        "docs/contracts/slk-checker-management.schema.json": {
            "schema_version", "method_version", "management_invocation_id", "run_id",
            "go_id", "cell_id", "attempt", "plan_revision", "runtime_revision",
            "token_sequence", "checker_role_instance_id", "d1_incomplete_event_id",
            "runtime_projection_path", "native_attempt_path", "supervisor_endpoint_path",
            "checker_credential_path", "state_command", "transport_command",
            "escalation_attempt_root", "reason_codes", "evidence_refs", "occurred_at",
        },
        "docs/contracts/slk-checker-completion.schema.json": {
            "schema_version", "method_version", "completion_invocation_id", "run_id",
            "go_id", "cell_id", "target_cell_id", "attempt", "plan_revision",
            "runtime_revision", "token_sequence", "checker_role_instance_id", "d1_event_id",
            "route", "runtime_projection_path", "target_endpoint_path",
            "checker_credential_path", "state_command", "transport_command",
            "handoff_attempt_root", "payload", "occurred_at",
        },
        "docs/contracts/slk-native-start.schema.json": {
            "schema_version", "status", "adapter", "run_id", "cell_id", "message_id",
            "request_sha256", "native_request_sha256", "observed_at", "process", "native_task",
        },
        "docs/contracts/slk-native-task-activity.schema.json": {
            "schema_version", "adapter", "run_id", "cell_id", "message_id",
            "native_task_id", "status", "sequence", "observed_at", "last_event", "waiting_on",
        },
        "docs/contracts/slk-native-execution-outcome.schema.json": {
            "schema_version", "adapter", "run_id", "cell_id", "message_id",
            "instance_id", "session_id", "status", "started_at", "ended_at", "duration_ms",
            "exit_code", "error_code", "stdout_sha256", "stderr_sha256",
        },
        "docs/contracts/slk-overwatcher-cadence-inspection.schema.json": {
            "schema_version", "run_id", "observed_at", "projected_active",
            "overwatcher_role_instance_id", "latest_cycle_id",
            "latest_cycle_completed_at", "cadence_seconds", "elapsed_seconds",
            "missed_intervals", "status", "anomaly_codes", "action",
        },
        "docs/contracts/slk-overwatcher-turn-resume.schema.json": {
            "event_id", "run_id", "role_instance_id", "session_id",
            "binding_revision", "expected_runtime_revision",
            "previous_foreground_turn_id", "foreground_turn_id",
            "last_anomaly_cycle_id", "last_native_status_id", "native_active_session_evidence",
            "reason", "occurred_at",
        },
        "docs/contracts/slk-overwatcher-credential-rotation.schema.json": {
            "rotation_id", "run_id", "expected_binding_revision",
            "expected_runtime_revision", "role_instance_id", "session_id",
            "foreground_turn_id", "expected_overwatcher_credential_id",
            "evidence", "reason", "occurred_at",
        },
        "docs/contracts/slk-overwatcher-status.schema.json": {
            "status_id", "run_id", "binding_revision", "role_instance_id",
            "session_id", "foreground_turn_id", "native_liveness", "evidence",
            "observed_at",
        },
    }
    for relative, required in contracts.items():
        schema = json.loads(read(relative))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["additionalProperties"] is False
        optional_partial = ({'partial_terminal', 'independent_fail'} if relative.endswith('slk-ocrv-committed-terminal.schema.json')
                            else {'partial_review'} if relative.endswith('slk-ocrv-incomplete-checker-resume.schema.json')
                            else {
                                'temporal', 'source_blocked_result_sha256', 'source_project_id',
                                'environment_adjustment_path', 'environment_adjustment_sha256',
                            } if relative.endswith('slk-worker-continuation.schema.json')
                            else {'environment_adjustment_path', 'environment_adjustment_sha256'}
                            if relative.endswith('slk-ocrv-worker-recovery.schema.json')
                            else {'native_status', 'native_identity', 'output_delivery'}
                            if relative.endswith('slk-worker-completion-inspection.schema.json')
                            else {'sample', 'error'} if relative.endswith('slk-native-task-activity.schema.json') else set())
        assert set(schema["properties"]) == required | optional_partial
        if relative.endswith("slk-overwatcher-turn-resume.schema.json"):
            assert set(schema["required"]) == required - {
                "last_anomaly_cycle_id",
                "last_native_status_id",
            }
        elif relative.endswith("slk-ocrv-committed-terminal.schema.json"):
            assert set(schema["required"]) == required - {"recovery_terminal"}
            partial = schema['properties']['partial_terminal']
            assert partial['additionalProperties'] is False
            assert set(partial['required']) == set(partial['properties']) == {
                'resume_request_path','resume_request_sha256','evidence_sha256'}
            independent = schema['properties']['independent_fail']
            assert independent['additionalProperties'] is False
            assert set(independent['required']) == set(independent['properties']) == {
                'schema_version','request','result','raw_review','session_record','role_host','scope_plan',
                'd1_started_event_id','d1_incomplete_event_id','owner_continuation','supervisor_confirmation'}
            assert independent['properties']['schema_version']['const'] == 'slk.ocrv-independent-fail/v1'
            assert schema['allOf'][0]['then']['properties']['method_version']['enum'] == ['4.4.2', '4.4.3']
        else:
            assert set(schema["required"]) == required


def test_441_temporal_handoff_schemas_are_closed_and_bind_the_standard_client() -> None:
    host = json.loads(read("docs/contracts/slk-role-host.schema.json"))
    continuation = json.loads(read("docs/contracts/slk-worker-continuation.schema.json"))
    delivery = json.loads(read("docs/contracts/slk-temporal-delivery.schema.json"))

    assert host["additionalProperties"] is continuation["additionalProperties"] is False
    assert host["properties"]["schema_version"]["enum"] == ["slk.role-host/v1", "slk.role-host/v2"]
    assert continuation["properties"]["schema_version"]["enum"] == [
        "slk.worker-continuation/v1", "slk.worker-continuation/v2",
        "slk.worker-continuation/v3"]
    for schema in (host, continuation):
        command = schema["$defs"]["temporal"]["properties"]["client_command"]
        assert command["prefixItems"][1:] == [
            {"const": "-m"}, {"const": "slk_temporal.delivery_client"}]
        assert schema["$defs"]["temporal"]["additionalProperties"] is False
    assert len(delivery["oneOf"]) == 5
    assert delivery["$defs"]["readiness"]["additionalProperties"] is False
    assert delivery["$defs"]["result"]["properties"]["status"]["enum"] == [
        "DELIVERY_REQUESTED", "DELIVERY_ACKNOWLEDGED", "RECOVERY_REQUIRED", "BLOCKED",
        "PRE_START_REJECTION_ABANDONED"]


def test_overwatcher_resume_has_exactly_one_basis_and_cycle_enum_excludes_incident_code() -> None:
    resume = json.loads(read("docs/contracts/slk-overwatcher-turn-resume.schema.json"))
    cycle = json.loads(read("docs/contracts/slk-overwatch-cycle.schema.json"))

    assert "last_anomaly_cycle_id" not in resume["required"]
    assert "last_native_status_id" not in resume["required"]
    assert len(resume["oneOf"]) == 2
    anomaly_codes = cycle["properties"]["anomaly_codes"]["items"]["enum"]
    assert "OVERWATCHER_ACTIVE_DEGRADED" in anomaly_codes
    assert "OVERWATCHER_CONTINUITY_VIOLATION" not in anomaly_codes


def test_overwatcher_contracts_preserve_legacy_cadence_and_allow_current_600_seconds() -> None:
    cycle = json.loads(read("docs/contracts/slk-overwatch-cycle.schema.json"))
    inspection = json.loads(
        read("docs/contracts/slk-overwatcher-cadence-inspection.schema.json")
    )

    assert cycle["properties"]["cadence_seconds"] == {
        "oneOf": [
            {"type": "integer", "minimum": 180, "maximum": 300},
            {"const": 600},
        ]
    }
    assert inspection["properties"]["cadence_seconds"] == {
        "oneOf": [
            {"type": "integer", "minimum": 180, "maximum": 300},
            {"const": 600},
            {"type": "null"},
        ]
    }


def test_release_file_discovery_follows_git_and_ignores_local_build_outputs(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("node_modules/\ndist/\n", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    (tmp_path / "new-doc.md").write_text("new\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dependency.js").write_text(
        "ignored\n", encoding="utf-8"
    )
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "bundle.js").write_text("ignored\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", "tracked.txt"], cwd=tmp_path, check=True
    )

    paths = {path.as_posix() for path in validate_repository.release_files(tmp_path)}

    assert paths == {".gitignore", "new-doc.md", "tracked.txt"}


def test_readmes_explain_the_lightweight_collection_and_recovery_version() -> None:
    english = read("README.md")
    chinese = read("README.zh-CN.md")
    for text in (english, chinese):
        assert "4.4.3" in text
        assert "17" in text
        assert "skills/small-loop-skill/SKILL.md" in text
        assert "v2.6.0" in text
        assert "Control Conversation" not in text
    assert "seven exact communication rehearsals" in english
    assert "BI 1.1.1" in english
    assert "七条准确通讯演练" in chinese
    assert "BI 1.1.1" in chinese
    assert "not standalone methods" in english
    assert "不是独立方法" in chinese
    for marker in ("RTK", "Probe CLI", "Ponytail"):
        assert marker in english and marker in chinese


def test_migration_and_changelog_state_the_major_boundary() -> None:
    migration = read("MIGRATION.md")
    changelog = read("CHANGELOG.md")
    assert "2.6.0" in migration and "3.0.0" in migration
    assert "Supervisor" in migration and "Checker" in migration and "Worker" in migration
    assert "## 4.4.2" in changelog and "## 4.4.1" in changelog and "## 4.3.4" in changelog and "## 4.3.3" in changelog and "## 4.3.2" in changelog and "## 4.3.1" in changelog and "## 4.3.0" in changelog and "## 4.2.11" in changelog and "## 4.2.10" in changelog and "## 4.2.9" in changelog and "## 4.2.8" in changelog and "## 4.2.7" in changelog and "## 4.2.6" in changelog and "## 4.2.5" in changelog and "## 4.2.4" in changelog and "## 4.2.2" in changelog and "## 4.2.1" in changelog and "## 4.2.0" in changelog and "## 4.1.1" in changelog and "## 4.1.0" in changelog and "## 4.0.0" in changelog and "## 3.0.8" in changelog and "## 3.0.7" in changelog and "## 3.0.6" in changelog and "## 3.0.5" in changelog and "## 3.0.4" in changelog and "## 3.0.3" in changelog and "## 3.0.2" in changelog and "## 3.0.1" in changelog and "## 3.0.0" in changelog
    assert "one complete CELL" in changelog
    assert "later CELLs" in changelog
    assert "inspection-only CELLs" in changelog
    assert "completed work" in changelog


def test_436_readiness_and_ocrv_preflight_contracts_are_closed() -> None:
    readiness = json.loads(read("docs/contracts/slk-run-readiness.schema.json"))
    ocrv = json.loads(read("docs/contracts/slk-ocrv-d1-preflight.schema.json"))
    for schema in (readiness, ocrv):
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert len(schema["oneOf"]) == (9 if schema is readiness else 2)
    for name in ("request", "result"):
        assert readiness["$defs"][name]["additionalProperties"] is False
    option_name = readiness["$defs"]["option"]["properties"]["name"]
    assert option_name["enum"] == ["Ponytail", "RTK", "Probe CLI"]
    assert readiness["$defs"]["request"]["properties"]["optional_features"]["minItems"] == 3
    assert readiness["$defs"]["request"]["properties"]["roles"]["minItems"] == 4
    for receipt in ("bi_open_receipt", "temporal_readiness_receipt", "communication_rehearsal"):
        assert receipt in readiness["$defs"]["request"]["required"]
    for name in ("request", "preflight"):
        assert ocrv["$defs"][name]["additionalProperties"] is False


def test_441_saved_authority_and_reload_contracts_are_closed() -> None:
    for relative in (
        "docs/contracts/slk-supervisor-admin.schema.json",
        "docs/contracts/slk-overwatcher-admin.schema.json",
        "docs/contracts/slk-supervisor-model-revision.schema.json",
        "docs/contracts/slk-temporal-worker-reload.schema.json",
    ):
        schema = json.loads(read(relative))
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    supervisor = json.loads(read("docs/contracts/slk-supervisor-admin.schema.json"))
    overwatcher = json.loads(read("docs/contracts/slk-overwatcher-admin.schema.json"))
    assert set(supervisor["$defs"]["request"]["properties"]["operation"]["enum"]) == {
        "start-d2", "pause-run", "resume-run", "adopt-method-contract", "revise-role-model", "resume-overwatcher-turn", "rebind-session",
        "revise-plan", "close-run", "close-role",
    }
    assert supervisor["$defs"]["overwatcherCloseRequest"]["properties"]["operation"] == {
        "const": "close-overwatcher",
    }
    assert "sealed_overwatcher_credential_path" in supervisor["$defs"]["overwatcherCloseRequest"]["required"]
    assert set(supervisor["$defs"]["provisionRequest"]["properties"]["operation"]["enum"]) == {
        "register-role", "bind-overwatcher",
    }
    assert supervisor["$defs"]["workerProvisionRequest"]["properties"]["issued_role"] == {
        "const": "worker",
    }
    assert {
        "checker_role_instance_id", "sealed_checker_credential_path",
    }.issubset(supervisor["$defs"]["workerProvisionRequest"]["required"])
    assert overwatcher["oneOf"][0]["properties"]["operation"]["enum"] == [
        "record-overwatch-cycle", "record-overwatcher-status"
    ]


def test_431_consistency_audit_is_complete_and_packaged() -> None:
    audit = (ROOT / "docs/maintenance/2026-09-28-slk-4.3.1-consistency-audit.md").read_text(
        encoding="utf-8"
    )
    for skill in validate_repository.EXPECTED_SKILLS:
        if skill in {"slk-manage-temporal", "slk-pause-run"}:
            continue
        assert f"`{skill}`" in audit
    for marker in (
        "Skill / contract / producer / consumer matrix",
        "Authority and outcome matrix",
        "Writes, capacity and continuity",
        "Migration, package, BI and Temporal-off",
        "Same-class findings and corrections",
        "context compaction",
    ):
        assert marker in audit
    assert "docs/maintenance" not in (ROOT / "scripts/build_local_package.py").read_text(
        encoding="utf-8"
    )


def test_current_design_uses_the_same_startup_d2_and_recovery_routes() -> None:
    design = read(
        "docs/superpowers/specs/2026-08-22-slk-lightweight-skill-collection-design.md"
    )
    assert design.index("plan-run: Run/GO/分层检查") < design.index(
        "select-models: 三角色能力"
    ) < design.index("plan-run: 初始 CELL")
    assert "D1 PASS 或 Supervisor 豁免" in design
    assert "全部计划 CELL 已 D1 PASS 或豁免" in design
    assert design.count("-.通讯异常.-> RC") == 1
    assert "Worker 交付候选后缺少当前 CELL 的接收证据" in design
    assert "Checker 理解确认" in design
    assert "复用已记录" in design


def test_ci_validates_repository_tests_and_each_skill_on_windows_and_ubuntu() -> None:
    workflow = read(".github/workflows/validate.yml")
    assert "ubuntu-latest" in workflow
    assert "windows-latest" in workflow
    assert "python scripts/validate_repository.py" in workflow
    assert "python -m pytest -q" in workflow
    assert "quick_validate.py" in workflow
    assert "validate_serial_plan.py" not in workflow


def test_native_activity_documentation_uses_the_real_closed_cli_flags() -> None:
    transport = read("docs/transport/SLK-TRANSPORT.md")
    assert "--completed COMPLETED.json" in transport
    assert "--failed FAILED.json" in transport
    assert "--terminal COMPLETED.json" not in transport
    assert "python path\\to\\slk-transport.pyz" not in transport


def test_license_and_lf_policy_remain_available() -> None:
    license_text = read("LICENSE")
    assert "The above copyright notice and this permission notice" in license_text
    assert 'THE SOFTWARE IS PROVIDED "AS IS"' in license_text
    assert "* text=auto eol=lf" in read(".gitattributes")
    for path in (ROOT / "skills").rglob("*"):
        if path.is_file():
            assert b"\r\n" not in path.read_bytes(), path
