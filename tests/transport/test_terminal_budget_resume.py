from __future__ import annotations

import copy
import importlib
import json
import os
import subprocess
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

import slk_transport.worker_completion as worker_completion
from slk_transport.contracts import canonical_json_sha256
from slk_transport.terminal_budget import (
    ocrv_runtime_config_sha256,
    prepare_terminal_budget_request,
    validate_resumed_child,
)
from slk_transport.worker_completion import CompletionError

from test_committed_checker_terminal import fixture as committed_fixture
from test_committed_checker_terminal import sha256, write_json


def budget_resume_fixture(tmp_path: Path) -> tuple[dict[str, object], Path]:
    base, _ = committed_fixture(tmp_path)
    attempt = Path(str(base["native_attempt_path"]))
    request_path = attempt / "ocrv-request.json"
    native_request = json.loads(request_path.read_text(encoding="utf-8"))
    native_request["capacity"].update(
        max_tokens=32000, max_tokens_budget=64000, timeout_minutes=15
    )
    write_json(request_path, native_request)

    started_path = attempt / "started.json"
    started = json.loads(started_path.read_text(encoding="utf-8"))
    started["native_request_sha256"] = sha256(request_path)
    write_json(started_path, started)

    commit_path = Path(str(base["commit_request_path"]))
    commit = json.loads(commit_path.read_text(encoding="utf-8"))
    commit["start_evidence"]["sha256"] = sha256(started_path)
    write_json(commit_path, commit)

    raw_path = Path(str(base["raw_review_path"]))
    selected = [
        {"item_id": "item-1", "path": "src/example.py", "fingerprint": "f" * 64},
        {"item_id": "item-2", "path": "src/other.py", "fingerprint": "e" * 64},
    ]
    failed = [
        {**item, "classification": "budget", "reason": "aggregate token budget reached"}
        for item in selected
    ]
    raw = {
        "status": "failed",
        "llm": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
        "summary": {
            "total_tokens": 93708,
            "input_tokens": 88854,
            "output_tokens": 4854,
            "cache_read_tokens": 48896,
            "budget_exceeded": True,
        },
        "tool_calls": {"total": 10, "failure": 0},
        "comments": None,
        "session_id": "ocrv-session-1",
        "manifest": {
            "schema_version": "ocr.run-manifest/v1",
            "run_id": "ocrv-session-1",
            "operation": "review",
            "terminal_state": "failed",
            "input": {
                "requested_head": base["candidate_commit"],
                "resolved_base": base["candidate_parent"],
                "resolved_head": base["candidate_commit"],
                "exact_range": f'{base["candidate_parent"]}..{base["candidate_commit"]}',
            },
            "execution": {
                "ocr_version": "v1.12.7",
                "provider": "dashscope-tokenplan",
                "model": "qwen3.8-max",
                "rule_config_sha256": "1" * 64,
                "runtime_config_sha256": "2" * 64,
            },
            "coverage": {
                "selected": selected,
                "completed": [],
                "reused": [],
                "failed": failed,
                "waived": [],
            },
        },
    }
    write_json(raw_path, raw)

    result_path = attempt / "ocrv-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result.update(
        verdict="INCOMPLETE",
        reason_codes=["OCR_EXIT_1", "OCR_STATUS_NOT_COMPLETE", "OCR_COVERAGE_INCOMPLETE"],
        findings=[],
        review={
            "status": "failed",
            "provider": "dashscope-tokenplan",
            "model": "qwen3.8-max",
            "session_id": "ocrv-session-1",
            "exit_code": 1,
        },
        request_sha256=sha256(request_path),
        artifacts={"raw_review": str(raw_path.resolve())},
    )
    write_json(result_path, result)

    terminal_path = attempt / "completed.json"
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["native_identity"].update(verdict="INCOMPLETE", exit_code=3)
    write_json(terminal_path, terminal)

    projection_path = Path(str(base["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    transport = next(
        event for event in projection["events"] if event["event_type"] == "TRANSPORT_STARTED"
    )
    transport_details = json.loads(transport["details_json"])
    transport_details["start_evidence_sha256"] = sha256(started_path)
    transport["details_json"] = json.dumps(transport_details, sort_keys=True)
    started_event_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    incomplete_event_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    projection["events"].extend(
        [
            {
                "event_id": started_event_id,
                "event_type": "D1_STARTED",
                "author_role_instance_id": base["checker_role_instance_id"],
                "go_id": base["go_id"],
                "cell_id": base["cell_id"],
                "attempt": base["attempt"],
                "details_json": json.dumps(
                    {
                        "candidate_message_id": base["candidate_message_id"],
                        "native_start_sha256": sha256(started_path),
                    },
                    sort_keys=True,
                ),
            },
            {
                "event_id": incomplete_event_id,
                "event_type": "D1_INCOMPLETE",
                "author_role_instance_id": base["checker_role_instance_id"],
                "go_id": base["go_id"],
                "cell_id": base["cell_id"],
                "attempt": base["attempt"],
                "details_json": json.dumps(
                    {
                        "candidate_message_id": base["candidate_message_id"],
                        "native_terminal_sha256": sha256(terminal_path),
                        "native_result_sha256": sha256(result_path),
                        "session_id": "ocrv-session-1",
                        "verdict": "INCOMPLETE",
                    },
                    sort_keys=True,
                ),
            },
        ]
    )
    projection["administrative_snapshot"]["latest_event_id"] = incomplete_event_id
    projection["runtime_snapshot"]["latest_event_id"] = incomplete_event_id
    projection.setdefault(
        "go_nodes",
        [
            {
                "go_id": base["go_id"],
                "ordinal": 1,
                "cell_nodes": [
                    {
                        "cell_id": base["cell_id"],
                        "ordinal": 1,
                        "objective": "Complete the bounded CELL.",
                        "state": "d1_incomplete",
                        "attempt": base["attempt"],
                        "outcome": None,
                    }
                ],
            }
        ],
    )
    write_json(projection_path, projection)

    preflight_path = write_json(
        attempt / "ocrv-preflight.json",
        {
            "schema_version": "slk.ocrv-d1-preflight/v1",
            "status": "READY",
            "request_sha256": sha256(request_path),
            "background": {"sha256": "c" * 64},
        },
    )
    background_path = tmp_path / "d1-background.md"
    background_path.write_text("closed D1 background\n", encoding="utf-8")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["artifacts"]["background"] = str(background_path.resolve())
    write_json(result_path, result)
    incomplete = next(
        event for event in projection["events"] if event["event_type"] == "D1_INCOMPLETE"
    )
    incomplete_details = json.loads(incomplete["details_json"])
    incomplete_details["native_result_sha256"] = sha256(result_path)
    incomplete["details_json"] = json.dumps(incomplete_details, sort_keys=True)
    write_json(projection_path, projection)
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    write_json(terminal_path, terminal)
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight["background"]["sha256"] = sha256(background_path)
    write_json(preflight_path, preflight)
    activity_path = write_json(
        attempt / "native-activity.json",
        {
            "schema_version": "slk.native-task-activity/v1",
            "adapter": "ocrv-checker",
            "run_id": base["run_id"],
            "cell_id": base["cell_id"],
            "message_id": base["candidate_message_id"],
            "native_task_id": "review-1",
            "status": "FAILED",
            "sequence": 11,
            "observed_at": "2026-10-06T07:15:06Z",
            "last_event": {"kind": "OCRV_PROCESS_EXITED", "sequence": 11, "exit_code": 1},
            "waiting_on": None,
        },
    )
    session_path = (
        tmp_path
        / ".opencodereview"
        / "sessions"
        / "D_fixture-repository"
        / "ocrv-session-1.jsonl"
    )
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        json.dumps(
            {
                "type": "session_end",
                "sessionId": "ocrv-session-1",
                "run_manifest": raw["manifest"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    revision = {
        "schema_version": "slk.ocrv-terminal-budget-capacity-revision/v1",
        "reason": "TERMINAL_TOKEN_BUDGET_EXHAUSTED",
        "old": {"max_tokens": 32000, "max_tokens_budget": 64000, "timeout_minutes": 15},
        "observed": {
            "total_tokens": 93708,
            "input_tokens": 88854,
            "output_tokens": 4854,
            "cache_read_tokens": 48896,
        },
        "new": {"max_tokens": 32000, "max_tokens_budget": 128000, "timeout_minutes": 15},
    }
    transition = {
        "schema_version": "slk.ocrv-version-transition/v1",
        "reason": "OWNER_REQUESTED_TOOL_UNIFICATION",
        "source_version": "v1.12.7",
        "target_version": "v1.12.12",
        "source_rule_config_sha256": "1" * 64,
        "target_rule_config_sha256": "3" * 64,
    }
    runtime_binding = {
        "schema_version": "slk.ocrv-runtime-config-binding/v1",
        "protocol": "openai",
        "model": "qwen3.8-max",
        "endpoint_host": "token-plan.cn-beijing.maas.aliyuncs.com",
        "language": "中文",
        "timeout": "0s",
        "concurrency": 1,
        "source_sha256": "2" * 64,
        "target_sha256": "4" * 64,
    }
    runtime_binding["source_sha256"] = ocrv_runtime_config_sha256(
        runtime_binding, revision["old"]["max_tokens_budget"]
    )
    runtime_binding["target_sha256"] = ocrv_runtime_config_sha256(
        runtime_binding, revision["new"]["max_tokens_budget"]
    )
    raw["manifest"]["execution"]["runtime_config_sha256"] = runtime_binding["source_sha256"]
    write_json(raw_path, raw)
    authorization = {
        "schema_version": "slk.owner-capacity-revision-authorization/v1",
        "authority": "OWNER",
        "decision": "APPROVED",
        "authorization_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        "source_thread_id": "019fac58-0ea6-76c1-a4d2-84d01d200f77",
        "capacity_revision_sha256": canonical_json_sha256(revision),
        "ocrv_transition_sha256": canonical_json_sha256(transition),
        "runtime_config_binding_sha256": canonical_json_sha256(runtime_binding),
        "occurred_at": "2026-10-06T08:00:00Z",
    }
    planned_cells = [
        cell
        for go in projection["go_nodes"]
        for cell in go["cell_nodes"]
        if cell.get("state") != "split"
    ]
    role_host_path = write_json(
        tmp_path / "role-host.json",
        {
            "schema_version": "slk.role-host/v2",
            "run_id": base["run_id"],
            "plan_revision": base["plan_revision"],
            "state_command": base["state_command"],
            "transport_command": base["transport_command"],
            "roles": {
                "supervisor": {"endpoint_path": str(attempt / "endpoint.json"), "endpoint_sha256": sha256(attempt / "endpoint.json"), "credential_path": str(tmp_path / "supervisor.dpapi")},
                "checker": {"endpoint_path": str(attempt / "endpoint.json"), "endpoint_sha256": sha256(attempt / "endpoint.json"), "credential_path": base["checker_credential_path"]},
                "worker": {"endpoint_path": str(attempt / "endpoint.json"), "endpoint_sha256": sha256(attempt / "endpoint.json"), "credential_path": str(tmp_path / "worker.dpapi")},
            },
            "cells": [
                {
                    "go_id": base["go_id"],
                    "cell_id": cell["cell_id"],
                    "payload": {
                        "cell_id": cell["cell_id"],
                        "cell_ordinal": index,
                        "required_cell_count": len(planned_cells),
                        "task": cell.get("objective") or "Complete the planned CELL.",
                        "d1_criteria": ["The bounded CELL is correct."],
                        "root_record_path": str(projection_path.resolve()),
                    },
                }
                for index, cell in enumerate(planned_cells, 1)
            ],
            "d2_criteria": ["All required CELLs pass."],
        },
    )
    recovery_root = attempt / "resume-terminal-budget-checker" / str(base["recovery_invocation_id"])
    request = {
        **{key: value for key, value in base.items() if key not in {
            "schema_version", "runtime_projection_sha256", "commit_request_sha256",
            "immutable_sha256", "result_path"
        }},
        "schema_version": "slk.ocrv-terminal-budget-resume-request/v1",
        "runtime_projection_sha256": sha256(projection_path),
        "commit_request_sha256": sha256(commit_path),
        "immutable_sha256": {
            "endpoint.json": sha256(attempt / "endpoint.json"),
            "envelope.json": sha256(attempt / "envelope.json"),
            "started.json": sha256(started_path),
            "ocrv-request.json": sha256(request_path),
            "completed.json": sha256(terminal_path),
            "ocrv-result.json": sha256(result_path),
            "raw_review": sha256(raw_path),
        },
        "d1_started_event_id": started_event_id,
        "d1_incomplete_event_id": incomplete_event_id,
        "ocrv_preflight_path": str(preflight_path.resolve()),
        "ocrv_preflight_sha256": sha256(preflight_path),
        "background_path": str(background_path.resolve()),
        "background_sha256": sha256(background_path),
        "native_activity_path": str(activity_path.resolve()),
        "native_activity_sha256": sha256(activity_path),
        "session_record_path": str(session_path.resolve()),
        "session_record_sha256": sha256(session_path),
        "ocrv_session": {
            "session_id": "ocrv-session-1",
            "repo_dir": str(Path(str(base["candidate_repository"])).resolve()).replace("\\", "/"),
            "diff_commit": base["candidate_commit"],
            "model": "qwen3.8-max",
            "review_mode": "commit",
            "start_time": "2026-10-06T07:13:22Z",
            "aborted": False,
            "selected_files": 2,
            "completed_files": 0,
        },
        "capacity_revision": revision,
        "ocrv_transition": transition,
        "runtime_config_binding": runtime_binding,
        "owner_authorization": authorization,
        "role_host_binding_path": str(role_host_path.resolve()),
        "role_host_binding_sha256": sha256(role_host_path),
        "recovery_root": str(recovery_root.resolve()),
        "result_path": str((recovery_root / "result.json").resolve()),
    }
    outer = write_json(tmp_path / "terminal-budget-resume.json", request)
    return request, outer


def preparation_fixture(
    tmp_path: Path,
) -> tuple[dict[str, object], Path, Path, Callable[[list[str]], subprocess.CompletedProcess[str]]]:
    expected, _ = budget_resume_fixture(tmp_path)
    run_root = tmp_path / "run"
    role_host_path = run_root / "prepared" / "role-host.json"
    role_host_path.parent.mkdir(parents=True)
    shutil.copy2(expected["role_host_binding_path"], role_host_path)
    evidence = run_root / "evidence"
    evidence.mkdir()
    shutil.copy2(expected["runtime_projection_path"], evidence / "projection.json")
    shutil.copy2(expected["commit_request_path"], evidence / "commit.json")

    endpoint = json.loads(
        (Path(str(expected["native_attempt_path"])) / "endpoint.json").read_text(
            encoding="utf-8"
        )
    )
    runtime_root = Path(endpoint["address"]["runtime_root"])
    (runtime_root / "slk").mkdir(parents=True)
    (runtime_root / "ocr-slk.ps1").write_text("# fixture\n", encoding="utf-8")
    first_rule = runtime_root / "slk" / "slk-d1-rule.json"
    second_rule = runtime_root / "slk" / "SLK-D1-REVIEW.md"
    first_rule.write_text("fixture rule\n", encoding="utf-8")
    second_rule.write_text("fixture review\n", encoding="utf-8")
    target_rule_hash = "3" * 64
    write_json(
        runtime_root / "slk-checker-capabilities.json",
        {
            "schema_version": "slk.ocrv-capabilities/v1",
            "method_version": "4.4.2",
            "required": ["terminal-budget-continuation"],
            "terminal_budget_resume_identity": {
                "ocrv_version": "v1.12.12",
                "provider": "dashscope-tokenplan",
                "model": "qwen3.8-max",
                "protocol": "openai",
                "endpoint_host": "token-plan.cn-beijing.maas.aliyuncs.com",
                "language": "中文",
                "timeout": "0s",
                "concurrency": 1,
                "rule_config_sha256": target_rule_hash,
                "managed_rule_files": {
                    "slk/slk-d1-rule.json": sha256(first_rule),
                    "slk/SLK-D1-REVIEW.md": sha256(second_rule),
                },
            },
            "optional": {},
            "prohibited": [],
        },
    )
    session_path = Path(str(expected["session_record_path"]))
    state_root = session_path.parents[2]
    write_json(
        state_root / "config.json",
        {
            "provider": "dashscope-tokenplan",
            "providers": {"dashscope-tokenplan": {"model": "qwen3.8-max"}},
            "language": "中文",
        },
    )
    session = expected["ocrv_session"]
    source_raw = json.loads(
        Path(str(expected["raw_review_path"])).read_text(encoding="utf-8")
    )
    selected_paths = [item["path"] for item in source_raw["manifest"]["coverage"]["selected"]]

    def run(command: list[str]) -> subprocess.CompletedProcess[str]:
        if "--version" in command:
            return subprocess.CompletedProcess(command, 0, "open-code-review v1.12.12\n", "")
        if "session" in command and "show" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"summary": {**session, "file_path": str(session_path)}}),
                "",
            )
        if "--preview" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "files": [
                            {"path": path, "will_review": True} for path in selected_paths
                        ],
                        "reviewable_count": len(selected_paths),
                        "excluded_count": 0,
                    }
                ),
                "",
            )
        raise AssertionError(command)

    return expected, role_host_path, evidence / "projection.json", run


def test_preparer_derives_the_closed_request_without_manual_ids_or_hashes(
    tmp_path: Path,
) -> None:
    expected, role_host_path, projection_path, runner = preparation_fixture(tmp_path)
    output = tmp_path / "prepared" / "terminal-budget-request.json"

    result = prepare_terminal_budget_request(
        expected["native_attempt_path"],
        role_host_path,
        max_tokens_budget=256000,
        authorization_id="owner-capacity-256k",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T08:00:00Z",
        output_path=output,
        run_command=runner,
        load_current_projection=lambda _run_id, _command: json.loads(
            projection_path.read_text(encoding="utf-8")
        ),
    )

    request = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "CHECKER_TERMINAL_BUDGET_REQUEST_READY"
    assert request["d1_started_event_id"] == expected["d1_started_event_id"]
    assert request["d1_incomplete_event_id"] == expected["d1_incomplete_event_id"]
    assert request["capacity_revision"]["new"] == {
        "max_tokens": 32000,
        "max_tokens_budget": 256000,
        "timeout_minutes": 15,
    }
    assert request["ocrv_session"] == expected["ocrv_session"]
    assert result["prepare_only_command"][-1] == "--prepare-only"


def test_preparer_rejects_preview_coverage_drift_before_writing_request(
    tmp_path: Path,
) -> None:
    expected, role_host_path, projection_path, runner = preparation_fixture(tmp_path)
    output = tmp_path / "prepared" / "terminal-budget-request.json"

    def drifted(command: list[str]) -> subprocess.CompletedProcess[str]:
        completed = runner(command)
        if "--preview" in command:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {
                        "files": [{"path": "src/other.py", "will_review": True}],
                        "reviewable_count": 1,
                        "excluded_count": 0,
                    }
                ),
                "",
            )
        return completed

    with pytest.raises(ValueError, match="coverage"):
        prepare_terminal_budget_request(
            expected["native_attempt_path"],
            role_host_path,
            max_tokens_budget=256000,
            authorization_id="owner-capacity-256k",
            source_thread_id="owner-thread",
            occurred_at="2026-10-06T08:00:00Z",
            output_path=output,
            run_command=drifted,
            load_current_projection=lambda _run_id, _command: json.loads(
                projection_path.read_text(encoding="utf-8")
            ),
        )

    assert not output.exists()


def test_terminal_budget_resume_enters_only_the_sealed_original_checker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, request_path = budget_resume_fixture(tmp_path)
    captured: dict[str, object] = {}

    def sealed(*args: object, **kwargs: object) -> dict[str, object]:
        captured["kwargs"] = kwargs
        return {
            "schema_version": "slk.ocrv-terminal-budget-resume-result/v1",
            "method_version": request["method_version"],
            "status": "CHECKER_D1_RECORDED",
            "run_id": request["run_id"],
            "cell_id": request["cell_id"],
            "attempt": request["attempt"],
            "candidate_message_id": request["candidate_message_id"],
            "checker_role_instance_id": request["checker_role_instance_id"],
            "checker_endpoint_version": request["checker_endpoint_version"],
            "recovery_invocation_id": request["recovery_invocation_id"],
            "request_sha256": sha256(request_path),
            "capacity_revision_sha256": canonical_json_sha256(request["capacity_revision"]),
            "ocrv_transition_sha256": canonical_json_sha256(request["ocrv_transition"]),
            "runtime_config_binding_sha256": canonical_json_sha256(request["runtime_config_binding"]),
            "source_d1_incomplete_event_id": request["d1_incomplete_event_id"],
            "parent_session_id": "ocrv-session-1",
            "child_session_id": "ocrv-session-child-1",
            "d1_verdict": "PASS",
            "d1_event_type": "D1_PASSED",
            "corrected_d1_event_id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
            "suffix_mode": "--slk-complete-d1",
            "suffix_request_path": str(Path(str(request["recovery_root"])) / "post-d1-request.json"),
            "suffix_result_path": str(Path(str(request["recovery_root"])) / "post-d1-result.json"),
            "suffix_status": "CHECKER_COMPLETION_COMMITTED",
            "native_attempt_path": str(Path(str(request["recovery_root"])) / "native-attempt"),
            "native_result_path": str(Path(str(request["recovery_root"])) / "native-attempt" / "ocrv-result.json"),
        }

    monkeypatch.setattr(worker_completion, "_run_sealed_checker_terminal", sealed)
    result = worker_completion.resume_terminal_budget_checker(
        request_path, request_sha256=sha256(request_path)
    )

    assert result["status"] == "CHECKER_D1_RECORDED"
    assert captured["kwargs"]["mode"] == "--slk-resume-terminal-budget"


@pytest.mark.parametrize(
    "mutation",
    [
        "non-budget", "unsupported-ocrv", "insufficient-capacity", "missing-authorization",
        "wrong-d1", "forged-source-rule", "forged-runtime-target", "stale-role-host",
        "wrong-session-repository",
    ],
)
def test_terminal_budget_resume_fails_closed_before_model_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str
) -> None:
    request, request_path = budget_resume_fixture(tmp_path)
    if mutation == "non-budget":
        raw_path = Path(str(request["raw_review_path"]))
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        raw["manifest"]["coverage"]["failed"][0]["classification"] = "provider"
        write_json(raw_path, raw)
        request["immutable_sha256"]["raw_review"] = sha256(raw_path)
    elif mutation == "unsupported-ocrv":
        raw_path = Path(str(request["raw_review_path"]))
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        raw["manifest"]["execution"]["ocr_version"] = "v1.12.6"
        write_json(raw_path, raw)
        request["immutable_sha256"]["raw_review"] = sha256(raw_path)
    elif mutation == "insufficient-capacity":
        request["capacity_revision"]["new"]["max_tokens_budget"] = 90000
        request["owner_authorization"]["capacity_revision_sha256"] = canonical_json_sha256(
            request["capacity_revision"]
        )
    elif mutation == "missing-authorization":
        del request["owner_authorization"]
    elif mutation == "forged-source-rule":
        request["ocrv_transition"]["source_rule_config_sha256"] = "9" * 64
        request["owner_authorization"]["ocrv_transition_sha256"] = canonical_json_sha256(
            request["ocrv_transition"]
        )
    elif mutation == "forged-runtime-target":
        request["runtime_config_binding"]["target_sha256"] = "9" * 64
        request["owner_authorization"]["runtime_config_binding_sha256"] = canonical_json_sha256(
            request["runtime_config_binding"]
        )
    elif mutation == "stale-role-host":
        request["role_host_binding_sha256"] = "9" * 64
    elif mutation == "wrong-session-repository":
        request["ocrv_session"]["repo_dir"] = str(tmp_path / "other-repository")
    else:
        request["d1_incomplete_event_id"] = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    write_json(request_path, request)
    monkeypatch.setattr(
        worker_completion,
        "_run_sealed_checker_terminal",
        lambda *_args, **_kwargs: pytest.fail("invalid request must not start the Checker"),
    )

    with pytest.raises(CompletionError):
        worker_completion.resume_terminal_budget_checker(
            request_path, request_sha256=sha256(request_path)
        )


@pytest.mark.parametrize(
    "mutation",
    ["same-session", "forged-parent", "version-drift", "stale-rule", "stale-runtime"],
)
def test_terminal_budget_child_lineage_rejects_identity_spoof(
    tmp_path: Path, mutation: str
) -> None:
    request, _ = budget_resume_fixture(tmp_path)
    parent = json.loads(Path(str(request["raw_review_path"])).read_text(encoding="utf-8"))
    child = copy.deepcopy(parent)
    child["session_id"] = "ocrv-session-child-1"
    child["manifest"]["run_id"] = "ocrv-session-child-1"
    child["manifest"]["parent_run_id"] = "ocrv-session-1"
    lineage = {
        "schema_version": "ocr.resume-lineage/v1",
        "parent_run_id": "ocrv-session-1",
        "run_id": "ocrv-session-child-1",
        "source_provider": "dashscope-tokenplan",
        "source_model": "qwen3.8-max",
        "target_provider": "dashscope-tokenplan",
        "target_model": "qwen3.8-max",
    }
    if mutation == "same-session":
        child["session_id"] = "ocrv-session-1"
        child["manifest"]["run_id"] = "ocrv-session-1"
        child["manifest"]["parent_run_id"] = "ocrv-session-1"
        lineage["run_id"] = "ocrv-session-1"
    else:
        if mutation == "forged-parent":
            lineage["parent_run_id"] = "unrelated-session"
        elif mutation == "version-drift":
            child["manifest"]["execution"]["ocr_version"] = "v1.12.8"
        elif mutation == "stale-rule":
            child["manifest"]["execution"]["rule_config_sha256"] = "1" * 64
        else:
            child["manifest"]["execution"]["runtime_config_sha256"] = "2" * 64
    with pytest.raises(ValueError):
        validate_resumed_child(
            parent,
            child,
            lineage,
            target_ocrv_version="v1.12.12",
            target_rule_config_sha256="3" * 64,
            target_runtime_config_sha256=request["runtime_config_binding"]["target_sha256"],
        )


@pytest.mark.parametrize("final_verdict", ["PASS", "FAIL", "INCOMPLETE"])
def test_sealed_budget_host_records_truthful_child_session_and_one_d1_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, final_verdict: str
) -> None:
    request, request_path = budget_resume_fixture(tmp_path)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "integrations" / "ocrv"))
    recovery = importlib.import_module("slk_checker_recovery")
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(request["checker_role_instance_id"])
    )
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(request["checker_endpoint_version"])
    )
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"])
    )
    monkeypatch.setattr(
        worker_completion,
        "_default_checker_authenticate",
        lambda *_args, **_kwargs: {
            "status": "authenticated",
            "role": "checker",
            "role_instance_id": request["checker_role_instance_id"],
            "runtime_revision": request["runtime_revision"],
        },
    )
    monkeypatch.setattr(
        recovery,
        "_session_resume_mode",
        lambda _request, session: (
            "RESUME_SESSION",
            {
                "summary": {
                    "session_id": session["session_id"],
                    "run_manifest": {"terminal_state": "failed"},
                },
                "items": [{"path": "src/example.py"}],
            },
        ),
    )
    monkeypatch.setattr(recovery, "_ocrv_version", lambda: "v1.12.12")

    def run_adapter(
        capacity_path: Path,
        output_path: Path,
        *,
        invocation_override: str,
        background_override: Path,
        resume_session: str,
        result_request_path: Path,
    ) -> int:
        assert invocation_override != resume_session
        assert resume_session == "ocrv-session-1"
        revised = json.loads(capacity_path.read_text(encoding="utf-8"))
        assert revised["capacity"]["max_tokens_budget"] == 128000
        assert revised["capacity"]["max_tokens"] == 32000
        assert background_override == Path(str(request["background_path"])).resolve()
        source_raw = json.loads(Path(str(request["raw_review_path"])).read_text(encoding="utf-8"))
        manifest = copy.deepcopy(source_raw["manifest"])
        manifest["run_id"] = "ocrv-session-child-1"
        manifest["parent_run_id"] = "ocrv-session-1"
        manifest["execution"]["ocr_version"] = "v1.12.12"
        manifest["execution"]["rule_config_sha256"] = request["ocrv_transition"]["target_rule_config_sha256"]
        manifest["execution"]["runtime_config_sha256"] = request["runtime_config_binding"]["target_sha256"]
        manifest["terminal_state"] = "failed" if final_verdict == "INCOMPLETE" else "complete"
        selected = manifest["coverage"]["selected"]
        if final_verdict != "INCOMPLETE":
            manifest["coverage"].update(completed=selected, reused=[], failed=[], waived=[])
        finding = {
            "path": "src/example.py",
            "line": 1,
            "severity": "high",
            "category": "correctness",
            "title": "Candidate defect",
            "description": "The candidate remains incorrect.",
            "suggestion": "Repair the bounded defect.",
        }
        raw = {
            "status": "failed" if final_verdict == "INCOMPLETE" else "complete",
            "llm": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
            "summary": {"budget_exceeded": False},
            "tool_calls": {"failure": 0},
            "comments": [finding] if final_verdict == "FAIL" else [] if final_verdict == "PASS" else None,
            "session_id": "ocrv-session-child-1",
            "manifest": manifest,
        }
        raw_path = output_path.parent / "ocrv-review.json"
        write_json(raw_path, raw)
        result = {
            "schema_version": "slk.ocrv-d1-result/v1",
            "run_id": request["run_id"],
            "cell_id": request["cell_id"],
            "review_invocation_id": invocation_override,
            "verdict": final_verdict,
            "reason_codes": (
                ["OCR_COMPLETE_ZERO_FINDINGS"] if final_verdict == "PASS"
                else ["OCR_COMPLETE_BLOCKING_FINDINGS"] if final_verdict == "FAIL"
                else ["OCR_COVERAGE_INCOMPLETE"]
            ),
            "findings": [finding] if final_verdict == "FAIL" else [],
            "review": {
                "status": "failed" if final_verdict == "INCOMPLETE" else "complete",
                "provider": "dashscope-tokenplan",
                "model": "qwen3.8-max",
                "session_id": "ocrv-session-child-1",
                "exit_code": {"PASS": 0, "FAIL": 2, "INCOMPLETE": 1}[final_verdict],
            },
            "evidence": [],
            "request_sha256": sha256(result_request_path),
            "artifacts": {"raw_review": str(raw_path.resolve())},
        }
        write_json(output_path, result)
        context = json.loads(os.environ["SLK_NATIVE_START_CONTEXT"])
        write_json(
            Path(os.environ["SLK_NATIVE_START_RECEIPT"]),
            {
                "schema_version": "slk.native-start/v2",
                "status": "STARTED",
                "adapter": "ocrv-checker",
                "run_id": request["run_id"],
                "cell_id": request["cell_id"],
                "message_id": request["candidate_message_id"],
                "request_sha256": request["payload_sha256"],
                "native_request_sha256": context["native_request_sha256"],
                "observed_at": "2026-10-06T08:01:00Z",
                "process": {"pid": os.getpid(), "creation_time": "test"},
                "native_task": {
                    "kind": "ocrv-review",
                    "id": invocation_override,
                    "status": "RUNNING",
                },
            },
        )
        child_session_path = Path(str(request["session_record_path"])).resolve().parent / "ocrv-session-child-1.jsonl"
        child_session_path.write_text(
            "\n".join(
                json.dumps(value, sort_keys=True)
                for value in (
                    {
                        "type": "resume_lineage",
                        "schema_version": "ocr.resume-lineage/v1",
                        "parent_run_id": "ocrv-session-1",
                        "run_id": "ocrv-session-child-1",
                        "source_provider": "dashscope-tokenplan",
                        "source_model": "qwen3.8-max",
                        "target_provider": "dashscope-tokenplan",
                        "target_model": "qwen3.8-max",
                    },
                    {
                        "type": "session_end",
                        "sessionId": "ocrv-session-child-1",
                        "run_manifest": manifest,
                    },
                )
            )
            + "\n",
            encoding="utf-8",
        )
        return {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}[final_verdict]

    monkeypatch.setattr(recovery.checker_adapter, "run", run_adapter)
    monkeypatch.setattr(
        recovery,
        "_run_ocrv_json",
        lambda arguments: {
            "summary": {
                "session_id": arguments[-1],
                "file_path": str(
                    Path(str(request["session_record_path"])).resolve().parent
                    / (arguments[-1] + ".jsonl")
                ),
                "run_manifest": json.loads(
                    (Path(str(request["recovery_root"])) / "native-attempt" / "ocrv-review.json").read_text(
                        encoding="utf-8"
                    )
                )["manifest"],
            },
            "items": [],
        },
    )

    def current_projection(*_args: object, **_kwargs: object) -> dict[str, object]:
        projection = json.loads(Path(str(request["runtime_projection_path"])).read_text(encoding="utf-8"))
        projection["runtime_snapshot"]["runtime_revision"] += 1
        projection["administrative_snapshot"]["latest_event_id"] = worker_completion._stable_id(
            request["candidate_message_id"],
            "d1-budget-" + request["recovery_invocation_id"],
        )
        projection["runtime_snapshot"]["latest_event_id"] = projection["administrative_snapshot"]["latest_event_id"]
        if final_verdict != "INCOMPLETE":
            projection["events"].append(
                {
                    "event_id": projection["runtime_snapshot"]["latest_event_id"],
                    "event_type": "D1_PASSED" if final_verdict == "PASS" else "D1_FAILED",
                    "author_role_instance_id": request["checker_role_instance_id"],
                    "go_id": request["go_id"],
                    "cell_id": request["cell_id"],
                    "attempt": request["attempt"],
                    "corrects_event_id": request["d1_incomplete_event_id"],
                    "details_json": json.dumps(
                        {
                            "candidate_message_id": request["candidate_message_id"],
                            "verdict": final_verdict,
                        },
                        sort_keys=True,
                    ),
                    "occurred_at": "2026-10-06T08:02:00Z",
                }
            )
        return projection

    monkeypatch.setattr(worker_completion, "_default_load_current_projection", current_projection)

    def record(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if final_verdict == "INCOMPLETE":
            pytest.fail("a still-incomplete continuation must not write another central D1 event")
        if "--slk-complete-d1" in command or "--slk-post-d1" in command:
            output = Path(command[command.index("--output") + 1])
            value = {
                "status": (
                    "CHECKER_COMPLETION_COMMITTED"
                    if "--slk-complete-d1" in command
                    else "CHECKER_ESCALATION_COMMITTED"
                )
            }
            write_json(output, value)
            return subprocess.CompletedProcess(command, 0, json.dumps(value).encode(), b"")
        committed_path = Path(command[command.index("--request") + 1])
        committed = json.loads(committed_path.read_text(encoding="utf-8"))
        correction = committed["recovery_terminal"]["d1_correction"]
        assert correction["d1_incomplete_event_id"] == request["d1_incomplete_event_id"]
        value = {
            "request_sha256": sha256(committed_path),
            "d1_verdict": final_verdict,
            "d1_event_type": "D1_PASSED" if final_verdict == "PASS" else "D1_FAILED",
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(value).encode(), b"")

    monkeypatch.setattr(recovery.subprocess, "run", record)
    result_code = recovery._resume_terminal_budget(
        request,
        request_path,
        [os.fspath(Path(os.sys.executable).resolve()), os.fspath(Path(worker_completion.__file__).parent.parent)],
    )

    assert result_code == 0
    result = json.loads(Path(str(request["result_path"])).read_text(encoding="utf-8"))
    assert result["status"] == (
        "CHECKER_D1_STILL_INCOMPLETE"
        if final_verdict == "INCOMPLETE"
        else "CHECKER_D1_RECORDED"
    )
    assert result["d1_verdict"] == final_verdict
    assert result["parent_session_id"] == "ocrv-session-1"
    assert result["child_session_id"] == "ocrv-session-child-1"
    if final_verdict == "PASS":
        assert result["suffix_mode"] == "--slk-complete-d1"
        assert result["suffix_status"] == "CHECKER_COMPLETION_COMMITTED"
    elif final_verdict == "FAIL":
        assert result["suffix_mode"] == "--slk-post-d1"
        assert result["suffix_status"] == "CHECKER_ESCALATION_COMMITTED"
    else:
        assert result["suffix_mode"] is None
        assert result["suffix_status"] == "NOT_APPLICABLE"
    assert (Path(str(request["recovery_root"])) / "resume-consumed.json").is_file()
