from __future__ import annotations

import copy
import importlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from slk_transport import worker_completion
from slk_transport.contracts import canonical_json_sha256
from slk_transport.terminal_budget_fresh import (
    claim_fresh_review_source,
    prepare_fresh_review_request,
)
from slk_transport.terminal_budget_fresh_partial import (
    claim_fresh_partial_source,
    prepare_fresh_partial_request,
    validate_fresh_partial_child,
    validate_fresh_partial_request,
)

from test_committed_checker_terminal import sha256, write_json
from test_terminal_budget_fresh_review import nonresumable_predispatch_fixture
from test_terminal_budget_resume import built_transport_command


def consumed_fresh_partial_fixture(
    tmp_path: Path,
) -> tuple[dict[str, object], Path, dict[str, object], callable]:
    source, source_path, _projection, base_runner = nonresumable_predispatch_fixture(tmp_path)
    fresh_path = tmp_path / "prepared" / "fresh-review.json"
    prepare_fresh_review_request(
        source_path,
        authorization_id="owner-nonresumable-predispatch",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T11:30:00Z",
        output_path=fresh_path,
        run_command=base_runner,
    )
    fresh = json.loads(fresh_path.read_text(encoding="utf-8"))
    claim_fresh_review_source(fresh)
    root = Path(str(fresh["recovery_root"])).resolve()
    attempt = root / "native-attempt"
    attempt.mkdir(parents=True)
    (root / "fresh-consumed.json").write_text(
        json.dumps({
            "request_sha256": sha256(fresh_path),
            "source_request_sha256": fresh["source_request_sha256"],
            "source_rejection_sha256": fresh["source_rejection_sha256"],
            "authorization_sha256": canonical_json_sha256(fresh["owner_authorization"]),
        }, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_json(root / "session-show.json", {
        "summary": {"session_id": source["ocrv_session"]["session_id"]}, "items": None,
    })
    original = json.loads(
        (Path(str(source["native_attempt_path"])) / "ocrv-request.json").read_text(
            encoding="utf-8"
        )
    )
    original["capacity"].update(source["capacity_revision"]["new"])
    capacity_path = write_json(attempt / "ocrv-capacity-request.json", original)
    parent_raw = json.loads(Path(str(source["raw_review_path"])).read_text(encoding="utf-8"))
    manifest = copy.deepcopy(parent_raw["manifest"])
    child_session = "18cffc1f-5d7c-4442-b235-e86156403cf4"
    selected = manifest["coverage"]["selected"]
    manifest.update(run_id=child_session, terminal_state="partial", elapsed_ms=207962)
    manifest["execution"].update(
        ocr_version=source["ocrv_transition"]["target_version"],
        rule_config_sha256=source["ocrv_transition"]["target_rule_config_sha256"],
        runtime_config_sha256=source["runtime_config_binding"]["target_sha256"],
    )
    manifest["coverage"].update(
        completed=[selected[0]],
        reused=[],
        failed=[{
            **selected[1], "classification": "budget",
            "reason": "reached the aggregate token budget before finishing",
        }],
        waived=[],
    )
    finding = {
        "path": selected[0]["path"], "start_line": 1, "end_line": 1,
        "severity": "low", "category": "bug", "content": "Preserved low finding.",
        "existing_code": "example",
    }
    raw = {
        "status": "partial",
        "llm": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
        "message": "Review partially complete",
        "summary": {
            "files_reviewed": 2, "comments": 1, "total_tokens": 177912,
            "input_tokens": 168872, "output_tokens": 9040,
            "cache_read_tokens": 105344, "elapsed": "3m28s", "budget_exceeded": True,
        },
        "tool_calls": {
            "total": 14, "by_tool": {"file_read": 4}, "failure": 0,
            "failure_by_tool": {}, "failure_details": [],
        },
        "comments": [finding], "groups": [],
        "warnings": [{
            "file": selected[0]["path"],
            "message": "stopped group mid-review: used 177912 tokens exceeds budget 128000",
            "type": "token_budget_reached",
        }],
        "session_id": child_session, "manifest": manifest,
        "retry_report": {
            "schema_version": "ocr.llm-retry-report/v1", "total_requests": 1,
            "retried_requests": 0, "total_retries": 0, "recovered_requests": 0,
            "failed_requests": 0, "cancelled_requests": 1,
            "requests": [{
                "logical_request_id": "fixture", "provider": "dashscope-tokenplan",
                "model": "qwen3.8-max", "file_path": "fixture-group",
                "task_type": "memory_compression_task", "request_no": 1,
                "outcome": "cancelled", "attempts": [{
                    "attempt": 1, "outcome": "error", "error_class": "cancelled",
                    "failure_phase": "context", "duration_to_headers_ms": 1,
                }],
            }],
        },
    }
    raw_path = write_json(attempt / "ocrv-review.json", raw)
    invocation = "6d6a378d-bd65-4b05-a57c-795f9dfb07ff"
    result = {
        "schema_version": "slk.ocrv-d1-result/v1", "run_id": source["run_id"],
        "cell_id": source["cell_id"], "review_invocation_id": invocation,
        "verdict": "INCOMPLETE",
        "reason_codes": ["OCR_STATUS_NOT_COMPLETE", "OCR_COVERAGE_INCOMPLETE"],
        "findings": [finding],
        "review": {
            "status": "partial", "provider": "dashscope-tokenplan", "model": "qwen3.8-max",
            "session_id": child_session, "exit_code": 0,
        },
        "evidence": [], "request_sha256": sha256(capacity_path),
        "artifacts": {
            "background": source["background_path"], "raw_review": str(raw_path),
            "stdout": str(attempt / "ocrv.stdout.txt"),
            "stderr": str(attempt / "ocrv.stderr.txt"),
        },
    }
    result_path = write_json(attempt / "ocrv-result.json", result)
    (attempt / "ocrv.stdout.txt").write_bytes(b"")
    (attempt / "ocrv.stderr.txt").write_bytes(b"")
    start = {
        "schema_version": "slk.native-start/v2", "status": "STARTED",
        "adapter": "ocrv-checker", "run_id": source["run_id"], "cell_id": source["cell_id"],
        "message_id": source["candidate_message_id"], "request_sha256": source["payload_sha256"],
        "native_request_sha256": sha256(capacity_path), "observed_at": "2026-10-06T11:31:00Z",
        "process": {"pid": 999999, "creation_time": "win-filetime:1"},
        "native_task": {"kind": "ocrv-review", "id": invocation, "status": "RUNNING"},
    }
    write_json(attempt / "native-start.received.json", start)
    write_json(attempt / "started.json", start)
    write_json(attempt / "native-activity.json", {
        "schema_version": "slk.native-task-activity/v1", "adapter": "ocrv-checker",
        "run_id": source["run_id"], "cell_id": source["cell_id"],
        "message_id": source["candidate_message_id"], "native_task_id": invocation,
        "status": "COMPLETED", "sequence": 1, "observed_at": "2026-10-06T11:35:00Z",
        "last_event": {"kind": "OCRV_PROCESS_EXITED", "sequence": 1, "exit_code": 0},
        "waiting_on": None,
    })
    session_path = Path(str(source["session_record_path"])).resolve().parent / f"{child_session}.jsonl"
    session_path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in (
        {"type": "session_start", "sessionId": child_session},
        {"type": "session_end", "sessionId": child_session, "run_manifest": manifest},
    )) + "\n", encoding="utf-8")
    (attempt / "native-session.jsonl").write_bytes(session_path.read_bytes())
    write_json(attempt / "compatibility-lineage.json", {
        "schema_version": "slk.ocrv-terminal-budget-fresh-compatibility-lineage/v1",
        "strategy": fresh["strategy"], "source_request_path": fresh["source_request_path"],
        "source_request_sha256": fresh["source_request_sha256"],
        "source_rejection_sha256": fresh["source_rejection_sha256"],
        "compatibility_request_path": str(fresh_path.resolve()),
        "compatibility_request_sha256": sha256(fresh_path),
        "parent_session_id": source["ocrv_session"]["session_id"],
        "child_session_id": child_session, "review_invocation_id": invocation,
        "candidate_commit": source["candidate_commit"],
        "candidate_message_id": source["candidate_message_id"],
        "d1_started_event_id": source["d1_started_event_id"],
        "d1_incomplete_event_id": source["d1_incomplete_event_id"],
        "authorization_sha256": canonical_json_sha256(fresh["owner_authorization"]),
        "native_session_sha256": sha256(attempt / "native-session.jsonl"),
        "checkpoint_reuse": False,
    })
    write_json(attempt / "completed.json", {
        "schema_version": "slk.transport-result/v1", "message_id": source["candidate_message_id"],
        "run_id": source["run_id"], "adapter": "ocrv-checker", "status": "completed",
        "native_identity": {
            "run_id": source["run_id"], "cell_id": source["cell_id"],
            "review_invocation_id": invocation, "session_id": child_session,
            "provider": "dashscope-tokenplan", "model": "qwen3.8-max",
            "verdict": "INCOMPLETE", "exit_code": 0, "review_segment_count": 0,
        },
        "error_code": None,
        "evidence": ["started.json", "ocrv-capacity-request.json", "compatibility-lineage.json",
                     "native-session.jsonl", "ocrv-result.json"],
    })
    write_json(root / "result.json", {
        "schema_version": "slk.ocrv-terminal-budget-fresh-review-result/v1",
        "method_version": source["method_version"], "status": "CHECKER_D1_STILL_INCOMPLETE",
        "run_id": source["run_id"], "cell_id": source["cell_id"], "attempt": source["attempt"],
        "candidate_message_id": source["candidate_message_id"],
        "checker_role_instance_id": source["checker_role_instance_id"],
        "checker_endpoint_version": source["checker_endpoint_version"],
        "recovery_invocation_id": fresh["recovery_invocation_id"],
        "request_sha256": sha256(fresh_path),
        "capacity_revision_sha256": canonical_json_sha256(source["capacity_revision"]),
        "source_rejection_sha256": fresh["source_rejection_sha256"],
        "compatibility_authorization_sha256": canonical_json_sha256(fresh["owner_authorization"]),
        "source_d1_incomplete_event_id": source["d1_incomplete_event_id"],
        "parent_session_id": source["ocrv_session"]["session_id"],
        "child_session_id": child_session, "d1_verdict": "INCOMPLETE",
        "d1_event_type": "D1_INCOMPLETE", "corrected_d1_event_id": None,
        "suffix_mode": None, "suffix_request_path": None, "suffix_result_path": None,
        "suffix_status": "NOT_APPLICABLE", "native_attempt_path": str(attempt),
        "native_result_path": str(result_path),
    })
    summary = {
        "session_id": child_session, "file_path": str(session_path),
        "repo_dir": source["ocrv_session"]["repo_dir"], "git_branch": "fixture",
        "model": "qwen3.8-max", "review_mode": "commit",
        "diff_commit": source["candidate_commit"], "start_time": "2026-10-06T11:31:00Z",
        "end_time": "2026-10-06T11:35:00Z", "duration_ns": 207962000000,
        "selected_files": 2, "completed_files": 1, "failed_files": 1,
        "reused_files": 0, "waived_files": 0, "total_comments": 1,
        "llm_failures": 1, "aborted": False, "legacy": False, "run_manifest": manifest,
    }

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if "session" in command and "list" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps([summary]), "")
        if "session" in command and "show" in command and child_session in command:
            return subprocess.CompletedProcess(command, 0, json.dumps({
                "summary": summary,
                "items": [{"path": selected[0]["path"], "fingerprint": selected[0]["fingerprint"]}],
            }), "")
        return base_runner(command)

    return fresh, fresh_path, source, runner


def test_preparer_admits_exact_consumed_fresh_budget_partial(tmp_path: Path) -> None:
    fresh, fresh_path, source, runner = consumed_fresh_partial_fixture(tmp_path)
    output = tmp_path / "prepared" / "fresh-partial-256k.json"

    prepared = prepare_fresh_partial_request(
        fresh_path,
        max_tokens_budget=256000,
        authorization_id="owner-fresh-partial-256k",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T12:00:00Z",
        output_path=output,
        run_command=runner,
    )

    request = json.loads(output.read_text(encoding="utf-8"))
    validated = validate_fresh_partial_request(request)
    assert prepared["status"] == "CHECKER_TERMINAL_BUDGET_FRESH_PARTIAL_REQUEST_READY"
    assert request["fresh_request_sha256"] == sha256(fresh_path)
    assert request["capacity_revision"]["old"]["max_tokens_budget"] == 128000
    assert request["capacity_revision"]["observed"]["total_tokens"] == 177912
    assert request["capacity_revision"]["new"]["max_tokens_budget"] == 256000
    assert validated["source_request"]["candidate_commit"] == source["candidate_commit"]
    assert validated["source_request"]["ocrv_session"]["session_id"] == (
        "18cffc1f-5d7c-4442-b235-e86156403cf4"
    )
    coverage = validated["partial"]["raw"]["manifest"]["coverage"]
    assert validated["parent_completed_paths"] == {coverage["completed"][0]["path"]}
    assert validated["remaining_paths"] == {coverage["failed"][0]["path"]}


@pytest.mark.parametrize(
    "damage",
    ["candidate", "completed-count", "finding-path", "checkpoint", "already-consumed"],
)
def test_preparer_rejects_unproved_consumed_fresh_partial(
    tmp_path: Path, damage: str,
) -> None:
    fresh, fresh_path, _source, runner = consumed_fresh_partial_fixture(tmp_path)
    root = Path(str(fresh["recovery_root"]))
    raw_path = root / "native-attempt" / "ocrv-review.json"
    if damage in {"candidate", "completed-count", "finding-path"}:
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        if damage == "candidate":
            raw["manifest"]["input"]["resolved_head"] = "f" * 40
        elif damage == "completed-count":
            raw["manifest"]["coverage"]["completed"] = []
        else:
            raw["comments"][0]["path"] = "crates/codegen/lcas-mcp/src/servers.rs"
        write_json(raw_path, raw)
    elif damage == "checkpoint":
        original_runner = runner

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            completed = original_runner(command)
            if "session" in command and "show" in command:
                value = json.loads(completed.stdout)
                value["items"] = None
                return subprocess.CompletedProcess(command, 0, json.dumps(value), "")
            return completed
    else:
        marker = root / "fresh-partial-source-consumed.json"
        marker.write_text("{}\n", encoding="utf-8")

    with pytest.raises((ValueError, worker_completion.CompletionError)):
        prepare_fresh_partial_request(
            fresh_path,
            max_tokens_budget=256000,
            authorization_id="owner-fresh-partial-256k",
            source_thread_id="owner-thread",
            occurred_at="2026-10-06T12:00:00Z",
            output_path=tmp_path / "prepared" / "fresh-partial-256k.json",
            run_command=runner,
        )


def test_fresh_partial_source_is_one_shot(tmp_path: Path) -> None:
    _fresh, fresh_path, _source, runner = consumed_fresh_partial_fixture(tmp_path)
    output = tmp_path / "prepared" / "fresh-partial-256k.json"
    prepare_fresh_partial_request(
        fresh_path,
        max_tokens_budget=256000,
        authorization_id="owner-fresh-partial-256k",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T12:00:00Z",
        output_path=output,
        run_command=runner,
    )
    request = json.loads(output.read_text(encoding="utf-8"))
    claim_fresh_partial_source(request)
    with pytest.raises(worker_completion.CompletionError):
        claim_fresh_partial_source(request)


@pytest.mark.parametrize("damage", ["review-completed", "drop-finding", "wrong-remaining"])
def test_fresh_partial_child_rejects_coverage_or_finding_drift(
    tmp_path: Path, damage: str,
) -> None:
    _fresh, fresh_path, _source, runner = consumed_fresh_partial_fixture(tmp_path)
    output = tmp_path / "prepared" / "fresh-partial-256k.json"
    prepare_fresh_partial_request(
        fresh_path,
        max_tokens_budget=256000,
        authorization_id="owner-fresh-partial-256k",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T12:00:00Z",
        output_path=output,
        run_command=runner,
    )
    validated = validate_fresh_partial_request(
        json.loads(output.read_text(encoding="utf-8"))
    )
    parent = validated["partial"]["raw"]
    child = copy.deepcopy(parent)
    coverage = child["manifest"]["coverage"]
    completed, failed = coverage["completed"], coverage["failed"]
    coverage.update(completed=failed, reused=completed, failed=[], waived=[])
    if damage == "review-completed":
        coverage["completed"] = completed + failed
        coverage["reused"] = []
    elif damage == "drop-finding":
        child["comments"] = []
    else:
        coverage["completed"] = []
        coverage["failed"] = []

    with pytest.raises(ValueError, match="re-reviewed, lost, or changed"):
        validate_fresh_partial_child(parent, child)


def test_fresh_partial_prepare_only_and_sealed_route_keep_exact_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh, fresh_path, source, runner = consumed_fresh_partial_fixture(tmp_path)
    request_path = tmp_path / "prepared" / "fresh-partial-256k.json"
    prepare_fresh_partial_request(
        fresh_path,
        max_tokens_budget=256000,
        authorization_id="owner-fresh-partial-256k",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T12:00:00Z",
        output_path=request_path,
        run_command=runner,
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    validated = validate_fresh_partial_request(request)
    projection = json.loads(
        Path(str(source["runtime_projection_path"])).read_text(encoding="utf-8")
    )
    monkeypatch.setattr(
        worker_completion, "_default_load_current_projection", lambda *_args: projection
    )
    digest = sha256(request_path)
    preflight = worker_completion.resume_terminal_budget_fresh_partial(
        request_path, request_sha256=digest, prepare_only=True
    )
    assert preflight["status"] == "READY_FOR_SEALED_CHECKER_FRESH_PARTIAL_RESUME"
    assert preflight["completed_paths"] == sorted(validated["parent_completed_paths"])
    assert preflight["remaining_paths"] == sorted(validated["remaining_paths"])

    captured: dict[str, object] = {}

    def sealed(*_args: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "schema_version": "slk.ocrv-terminal-budget-fresh-partial-result/v1",
            "method_version": source["method_version"], "status": "CHECKER_D1_STILL_INCOMPLETE",
            "run_id": source["run_id"], "cell_id": source["cell_id"],
            "attempt": source["attempt"], "candidate_message_id": source["candidate_message_id"],
            "checker_role_instance_id": source["checker_role_instance_id"],
            "checker_endpoint_version": source["checker_endpoint_version"],
            "recovery_invocation_id": request["recovery_invocation_id"],
            "request_sha256": digest,
            "capacity_revision_sha256": canonical_json_sha256(request["capacity_revision"]),
            "ocrv_transition_sha256": canonical_json_sha256(request["ocrv_transition"]),
            "runtime_config_binding_sha256": canonical_json_sha256(
                request["runtime_config_binding"]
            ),
            "source_d1_incomplete_event_id": source["d1_incomplete_event_id"],
            "parent_session_id": request["parent_session_id"],
            "child_session_id": "fresh-partial-child", "d1_verdict": "INCOMPLETE",
            "d1_event_type": "D1_INCOMPLETE", "corrected_d1_event_id": None,
            "suffix_mode": None, "suffix_request_path": None,
            "suffix_result_path": None, "suffix_status": "NOT_APPLICABLE",
            "native_attempt_path": str(Path(request["recovery_root"]) / "native-attempt"),
            "native_result_path": str(
                Path(request["recovery_root"]) / "native-attempt" / "ocrv-result.json"
            ),
        }

    monkeypatch.setattr(worker_completion, "_run_sealed_checker_terminal", sealed)
    result = worker_completion.resume_terminal_budget_fresh_partial(
        request_path, request_sha256=digest
    )
    assert result["status"] == "CHECKER_D1_STILL_INCOMPLETE"
    assert captured["mode"] == "--slk-resume-terminal-budget-fresh-partial"


def test_fresh_partial_host_resumes_only_remaining_and_commits_same_d1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh, fresh_path, source, runner = consumed_fresh_partial_fixture(tmp_path)
    request_path = tmp_path / "prepared" / "fresh-partial-256k.json"
    prepare_fresh_partial_request(
        fresh_path,
        max_tokens_budget=256000,
        authorization_id="owner-fresh-partial-256k",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T12:00:00Z",
        output_path=request_path,
        run_command=runner,
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    validated = validate_fresh_partial_request(request)
    command = built_transport_command(tmp_path)
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "integrations" / "ocrv")
    )
    recovery = importlib.import_module("slk_checker_recovery")
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(source["checker_role_instance_id"])
    )
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(source["checker_endpoint_version"])
    )
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"])
    )
    monkeypatch.setattr(
        worker_completion,
        "_default_checker_authenticate",
        lambda *_args, **_kwargs: {
            "status": "authenticated", "role": "checker",
            "role_instance_id": source["checker_role_instance_id"],
            "runtime_revision": source["runtime_revision"],
        },
    )
    parent_detail = {
        "summary": validated["session_summary"],
        "items": [{"path": path} for path in validated["parent_completed_paths"]],
    }
    monkeypatch.setattr(
        recovery, "_session_resume_mode", lambda *_args: ("RESUME_SESSION", parent_detail)
    )
    monkeypatch.setattr(recovery, "_ocrv_version", lambda: "v1.12.12")
    import slk_transport.terminal_budget_fresh_partial as partial_module

    monkeypatch.setattr(partial_module, "verify_managed_target", lambda *_args: None)
    child_session = "fresh-partial-child"

    def run_adapter(
        capacity_path: Path, output_path: Path, *, invocation_override: str,
        background_override: Path, resume_session: str | None, result_request_path: Path,
    ) -> int:
        assert resume_session == request["parent_session_id"]
        assert background_override == Path(str(source["background_path"])).resolve()
        revised = json.loads(capacity_path.read_text(encoding="utf-8"))
        assert revised["capacity"]["max_tokens_budget"] == 256000
        parent = validated["partial"]["raw"]
        manifest = copy.deepcopy(parent["manifest"])
        manifest.update(
            run_id=child_session, parent_run_id=request["parent_session_id"],
            terminal_state="complete",
        )
        manifest["execution"].update(
            ocr_version=request["ocrv_transition"]["target_version"],
            rule_config_sha256=request["ocrv_transition"]["target_rule_config_sha256"],
            runtime_config_sha256=request["runtime_config_binding"]["target_sha256"],
        )
        selected = list(manifest["coverage"]["selected"])
        parent_completed = [
            item for item in selected if item["path"] in validated["parent_completed_paths"]
        ]
        remaining = [
            item for item in selected if item["path"] in validated["remaining_paths"]
        ]
        manifest["coverage"].update(
            completed=remaining, reused=parent_completed, failed=[], waived=[]
        )
        raw_path = output_path.parent / "ocrv-review.json"
        findings = copy.deepcopy(parent["comments"])
        write_json(raw_path, {
            "status": "complete",
            "llm": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
            "summary": {"budget_exceeded": False}, "tool_calls": {"failure": 0},
            "comments": findings, "session_id": child_session, "manifest": manifest,
        })
        write_json(output_path, {
            "schema_version": "slk.ocrv-d1-result/v1", "run_id": source["run_id"],
            "cell_id": source["cell_id"], "review_invocation_id": invocation_override,
            "verdict": "FAIL", "reason_codes": ["OCR_COMPLETE_BLOCKING_FINDINGS"],
            "findings": findings,
            "review": {
                "status": "complete", "provider": "dashscope-tokenplan",
                "model": "qwen3.8-max", "session_id": child_session, "exit_code": 2,
            },
            "evidence": [], "request_sha256": sha256(result_request_path),
            "artifacts": {"raw_review": str(raw_path.resolve())},
        })
        context = json.loads(os.environ["SLK_NATIVE_START_CONTEXT"])
        write_json(Path(os.environ["SLK_NATIVE_START_RECEIPT"]), {
            "schema_version": "slk.native-start/v2", "status": "STARTED",
            "adapter": "ocrv-checker", "run_id": source["run_id"],
            "cell_id": source["cell_id"], "message_id": source["candidate_message_id"],
            "request_sha256": source["payload_sha256"],
            "native_request_sha256": context["native_request_sha256"],
            "observed_at": "2026-10-06T12:01:00Z",
            "process": {"pid": os.getpid(), "creation_time": "test"},
            "native_task": {"kind": "ocrv-review", "id": invocation_override, "status": "RUNNING"},
        })
        child = Path(str(source["session_record_path"])).resolve().parent / f"{child_session}.jsonl"
        lineage = {
            "type": "resume_lineage", "schema_version": "ocr.resume-lineage/v1",
            "parent_run_id": request["parent_session_id"], "run_id": child_session,
            "source_provider": "dashscope-tokenplan", "source_model": "qwen3.8-max",
            "target_provider": "dashscope-tokenplan", "target_model": "qwen3.8-max",
        }
        child.write_text("\n".join(json.dumps(row, sort_keys=True) for row in (
            {"type": "session_start", "sessionId": child_session}, lineage,
            {"type": "session_end", "sessionId": child_session, "run_manifest": manifest},
        )) + "\n", encoding="utf-8")
        return 2

    monkeypatch.setattr(recovery.checker_adapter, "run", run_adapter)

    def show_child(arguments: list[str]) -> object:
        assert arguments[-1] == child_session
        child = Path(str(source["session_record_path"])).resolve().parent / f"{child_session}.jsonl"
        raw = json.loads(
            (Path(str(request["recovery_root"])) / "native-attempt" / "ocrv-review.json")
            .read_text(encoding="utf-8")
        )
        return {
            "summary": {
                "session_id": child_session, "file_path": str(child),
                "run_manifest": raw["manifest"],
            },
            "items": [],
        }

    monkeypatch.setattr(recovery, "_run_ocrv_json", show_child)

    def current_projection(*_args: object, **_kwargs: object) -> dict[str, object]:
        projection = json.loads(
            Path(str(source["runtime_projection_path"])).read_text(encoding="utf-8")
        )
        projection["runtime_snapshot"]["runtime_revision"] += 1
        event_id = worker_completion._stable_id(
            source["candidate_message_id"], "d1-budget-" + request["recovery_invocation_id"]
        )
        projection["administrative_snapshot"]["latest_event_id"] = event_id
        projection["runtime_snapshot"]["latest_event_id"] = event_id
        projection["events"].append({
            "event_id": event_id, "event_type": "D1_FAILED",
            "author_role_instance_id": source["checker_role_instance_id"],
            "go_id": source["go_id"], "cell_id": source["cell_id"],
            "attempt": source["attempt"], "corrects_event_id": source["d1_incomplete_event_id"],
            "details_json": json.dumps({
                "candidate_message_id": source["candidate_message_id"], "verdict": "FAIL",
            }, sort_keys=True),
            "occurred_at": "2026-10-06T12:02:00Z",
        })
        return projection

    monkeypatch.setattr(worker_completion, "_default_load_current_projection", current_projection)

    def record(command_line: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if "--slk-post-d1" in command_line:
            output = Path(command_line[command_line.index("--output") + 1])
            value = {"status": "CHECKER_ESCALATION_COMMITTED"}
            write_json(output, value)
            return subprocess.CompletedProcess(command_line, 0, json.dumps(value).encode(), b"")
        committed_path = Path(command_line[command_line.index("--request") + 1])
        value = {
            "request_sha256": sha256(committed_path), "d1_verdict": "FAIL",
            "d1_event_type": "D1_FAILED",
        }
        return subprocess.CompletedProcess(command_line, 0, json.dumps(value).encode(), b"")

    monkeypatch.setattr(recovery.subprocess, "run", record)
    assert recovery._fresh_terminal_budget_partial(request, request_path, command) == 0
    result = json.loads(Path(str(request["result_path"])).read_text(encoding="utf-8"))
    assert result["status"] == "CHECKER_D1_RECORDED"
    assert result["d1_verdict"] == "FAIL"
    assert result["parent_session_id"] == request["parent_session_id"]
    child_raw = json.loads(
        (Path(str(request["recovery_root"])) / "native-attempt" / "ocrv-review.json")
        .read_text(encoding="utf-8")
    )
    assert {
        item["path"] for item in child_raw["manifest"]["coverage"]["reused"]
    } == validated["parent_completed_paths"]
    assert {
        item["path"] for item in child_raw["manifest"]["coverage"]["completed"]
    } == validated["remaining_paths"]


def test_ocrv_launcher_exposes_fresh_partial_route() -> None:
    launcher = (
        Path(__file__).resolve().parents[2] / "integrations" / "ocrv" / "slk-checker.cmd"
    ).read_text(encoding="utf-8")
    assert "--slk-resume-terminal-budget-fresh-partial" in launcher
