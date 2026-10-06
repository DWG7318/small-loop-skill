from __future__ import annotations

import copy
import importlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from slk_transport import worker_completion
from slk_transport.contracts import canonical_json_sha256
from slk_transport.terminal_budget import (
    claim_terminal_budget_source,
    prepare_terminal_budget_request,
)
from slk_transport.terminal_budget_fresh import (
    _validate_nonresumable_session,
    claim_fresh_review_source,
    prepare_fresh_review_request,
    validate_fresh_review_request,
)

from test_committed_checker_terminal import sha256, write_json
from test_terminal_budget_resume import (
    _make_zero_token_predispatch_budget_stop,
    built_transport_command,
    preparation_fixture,
)


def rule_rejection_fixture(
    tmp_path: Path,
) -> tuple[
    dict[str, object],
    Path,
    Path,
    callable,
]:
    source, _role_host, projection_path, runner = preparation_fixture(tmp_path)
    source_path = write_json(tmp_path / "terminal-budget-source.json", source)
    claim_terminal_budget_source(source)
    rejection_root = Path(str(source["recovery_root"]))
    rejection_root.mkdir(parents=True)
    write_json(
        rejection_root / "resume-consumed.json",
        {
            "request_sha256": sha256(source_path),
            "source_d1_incomplete_event_id": source["d1_incomplete_event_id"],
            "capacity_revision_sha256": canonical_json_sha256(source["capacity_revision"]),
            "ocrv_transition_sha256": canonical_json_sha256(source["ocrv_transition"]),
        },
    )
    native = rejection_root / "native-attempt"
    native.mkdir()
    original = json.loads(
        (Path(str(source["native_attempt_path"])) / "ocrv-request.json").read_text(
            encoding="utf-8"
        )
    )
    original["capacity"].update(source["capacity_revision"]["new"])
    capacity_path = write_json(native / "ocrv-capacity-request.json", original)
    invocation = "538b3c0c-1362-4459-a458-8f04a6dc914f"
    write_json(
        native / "native-start.received.json",
        {
            "schema_version": "slk.native-start/v2",
            "status": "STARTED",
            "adapter": "ocrv-checker",
            "run_id": source["run_id"],
            "cell_id": source["cell_id"],
            "message_id": source["candidate_message_id"],
            "request_sha256": source["payload_sha256"],
            "native_request_sha256": sha256(capacity_path),
            "observed_at": "2026-10-06T11:13:38Z",
            "process": {"pid": 999999, "creation_time": "win-filetime:1"},
            "native_task": {"kind": "ocrv-review", "id": invocation, "status": "RUNNING"},
        },
    )
    result = write_json(
        native / "ocrv-result.json",
        {
            "schema_version": "slk.ocrv-d1-result/v1",
            "run_id": source["run_id"],
            "cell_id": source["cell_id"],
            "review_invocation_id": invocation,
            "verdict": "INCOMPLETE",
            "reason_codes": ["OCR_EXIT_1", "OCR_RESULT_MISSING_OR_INVALID"],
            "findings": [],
            "review": {
                "status": None,
                "provider": None,
                "model": None,
                "session_id": None,
                "exit_code": 1,
            },
            "evidence": [],
            "request_sha256": sha256(capacity_path),
            "artifacts": {
                "background": source["background_path"],
                "raw_review": str(native / "ocrv-review.json"),
                "stdout": str(native / "ocrv.stdout.txt"),
                "stderr": str(native / "ocrv.stderr.txt"),
            },
        },
    )
    (native / "ocrv.stdout.txt").write_bytes(b"")
    (native / "ocrv.stderr.txt").write_text(
        "Error: resume rejected: review rule identity changed — either a rule text layer "
        "(custom, project, global or system) or the include/exclude file filter differs from "
        f'session "{source["ocrv_session"]["session_id"]}"; start a new review instead of resuming\n',
        encoding="utf-8",
    )
    write_json(
        native / "native-activity.json",
        {
            "schema_version": "slk.native-task-activity/v1",
            "adapter": "ocrv-checker",
            "run_id": source["run_id"],
            "cell_id": source["cell_id"],
            "message_id": source["candidate_message_id"],
            "native_task_id": invocation,
            "status": "FAILED",
            "sequence": 1,
            "observed_at": "2026-10-06T11:13:39Z",
            "last_event": {
                "kind": "OCRV_PROCESS_EXITED",
                "sequence": 1,
                "exit_code": 1,
                "tail": [],
            },
            "waiting_on": None,
        },
    )
    assert result.is_file()
    return source, source_path, projection_path, runner


def nonresumable_predispatch_fixture(
    tmp_path: Path,
) -> tuple[dict[str, object], Path, Path, callable]:
    expected, role_host_path, projection_path, base_runner = preparation_fixture(tmp_path)
    _make_zero_token_predispatch_budget_stop(expected)
    raw = json.loads(Path(str(expected["raw_review_path"])).read_text(encoding="utf-8"))
    session_path = Path(str(expected["session_record_path"])).resolve()
    summary = {
        **expected["ocrv_session"],
        "file_path": str(session_path),
        "end_time": "2026-10-06T07:15:05Z",
        "failed_files": 2,
        "reused_files": 0,
        "waived_files": 0,
        "total_comments": 0,
        "llm_failures": 0,
        "legacy": False,
        "run_manifest": raw["manifest"],
    }

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        if "session" in command and "list" in command:
            return subprocess.CompletedProcess(command, 0, json.dumps([summary]), "")
        if "session" in command and "show" in command:
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"summary": summary, "items": None}), ""
            )
        return base_runner(command)

    source_path = tmp_path / "prepared" / "terminal-budget-source.json"
    prepare_terminal_budget_request(
        expected["native_attempt_path"],
        role_host_path,
        max_tokens_budget=128000,
        authorization_id="owner-capacity-128k",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T08:00:00Z",
        output_path=source_path,
        run_command=runner,
        load_current_projection=lambda _run_id, _command: json.loads(
            projection_path.read_text(encoding="utf-8")
        ),
    )
    return json.loads(source_path.read_text(encoding="utf-8")), source_path, projection_path, runner


def test_zero_token_nonresumable_session_accepts_one_selected_file(tmp_path: Path) -> None:
    source, _source_path, _projection, _runner = nonresumable_predispatch_fixture(tmp_path)
    raw_path = Path(str(source["raw_review_path"]))
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    coverage = raw["manifest"]["coverage"]
    coverage["selected"] = coverage["selected"][:1]
    coverage["failed"] = coverage["failed"][:1]
    raw["summary"]["files_reviewed"] = 1
    write_json(raw_path, raw)
    source["ocrv_session"]["selected_files"] = 1
    session_path = Path(str(source["session_record_path"])).resolve()
    summary = {
        **source["ocrv_session"],
        "file_path": str(session_path),
        "end_time": "2026-10-06T07:15:05Z",
        "failed_files": 1,
        "reused_files": 0,
        "waived_files": 0,
        "total_comments": 0,
        "llm_failures": 0,
        "legacy": False,
        "run_manifest": raw["manifest"],
    }

    validated = _validate_nonresumable_session(
        source,
        [summary],
        {"summary": summary, "items": None},
    )

    assert validated["selected_files"] == 1
    assert validated["failed_files"] == 1


def test_preparer_selects_fresh_full_review_for_exact_zero_token_nonresumable_session(
    tmp_path: Path,
) -> None:
    source, source_path, _projection, runner = nonresumable_predispatch_fixture(tmp_path)
    output = tmp_path / "prepared" / "fresh-review.json"

    prepared = prepare_fresh_review_request(
        source_path,
        authorization_id="owner-nonresumable-predispatch",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T11:30:00Z",
        output_path=output,
        run_command=runner,
    )

    request = json.loads(output.read_text(encoding="utf-8"))
    assert prepared["status"] == "CHECKER_TERMINAL_BUDGET_FRESH_REQUEST_READY"
    assert prepared["source_basis"] == "ZERO_TOKEN_PREDISPATCH_NON_RESUMABLE"
    assert request["source_request_path"] == str(source_path.resolve())
    assert request["strategy"] == "FRESH_FULL_REVIEW_NO_CHECKPOINT_REUSE"
    assert set(request["rejection_evidence_sha256"]) == {
        "session-list.json", "session-show.json", "non-resumable.json",
    }
    assert not (
        Path(str(source["native_attempt_path"]))
        / "resume-terminal-budget-checker"
        / "source-consumed.json"
    ).exists()
    validated = validate_fresh_review_request(request)
    assert validated["source_basis"] == "ZERO_TOKEN_PREDISPATCH_NON_RESUMABLE"
    retried = prepare_fresh_review_request(
        source_path,
        authorization_id="owner-nonresumable-predispatch",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T11:30:00Z",
        output_path=output,
        run_command=runner,
    )
    assert retried == prepared


@pytest.mark.parametrize(
    "damage",
    ["checkpoint", "completed", "llm-call", "manifest-drift", "source-consumed"],
)
def test_preparer_rejects_unproved_zero_token_nonresumable_session(
    tmp_path: Path, damage: str,
) -> None:
    source, source_path, _projection, runner = nonresumable_predispatch_fixture(tmp_path)
    original_runner = runner

    def damaged_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        completed = original_runner(command)
        if "session" not in command or ("list" not in command and "show" not in command):
            return completed
        value = json.loads(completed.stdout)
        if "list" in command:
            rows = value
            if damage == "completed":
                rows[0]["completed_files"] = 1
            elif damage == "llm-call":
                rows[0]["llm_failures"] = 1
            elif damage == "manifest-drift":
                rows[0]["run_manifest"]["input"]["resolved_head"] = "f" * 40
        else:
            if damage == "checkpoint":
                value["items"] = [{"type": "review_item", "path": "src/example.py"}]
            elif damage == "completed":
                value["summary"]["completed_files"] = 1
            elif damage == "llm-call":
                value["summary"]["llm_failures"] = 1
            elif damage == "manifest-drift":
                value["summary"]["run_manifest"]["input"]["resolved_head"] = "f" * 40
        return subprocess.CompletedProcess(command, 0, json.dumps(value), "")

    if damage == "source-consumed":
        claim_terminal_budget_source(source)

    with pytest.raises((ValueError, worker_completion.CompletionError)):
        prepare_fresh_review_request(
            source_path,
            authorization_id="owner-nonresumable-predispatch",
            source_thread_id="owner-thread",
            occurred_at="2026-10-06T11:30:00Z",
            output_path=tmp_path / "prepared" / "fresh-review.json",
            run_command=damaged_runner,
        )


def test_preparer_admits_only_the_consumed_real_rule_identity_rejection(
    tmp_path: Path,
) -> None:
    source, source_path, _projection, runner = rule_rejection_fixture(tmp_path)
    output = tmp_path / "prepared" / "fresh-review.json"

    prepared = prepare_fresh_review_request(
        source_path,
        authorization_id="owner-rule-compatibility",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T11:30:00Z",
        output_path=output,
        run_command=runner,
        process_probe=lambda _pid, _created: {"exists": False, "identity_matches": False},
    )

    request = json.loads(output.read_text(encoding="utf-8"))
    assert prepared["status"] == "CHECKER_TERMINAL_BUDGET_FRESH_REQUEST_READY"
    assert prepared["candidate_commit"] == source["candidate_commit"]
    assert prepared["parent_session_id"] == source["ocrv_session"]["session_id"]
    assert request["source_request_path"] == str(source_path.resolve())
    assert request["strategy"] == "FRESH_FULL_REVIEW_NO_CHECKPOINT_REUSE"
    assert prepared["prepare_only_command"][-1] == "--prepare-only"
    validate_fresh_review_request(request)


@pytest.mark.parametrize(
    ("authorization_id", "source_thread_id", "occurred_at"),
    [
        ("owner authorization", "owner-thread", "2026-10-06T11:30:00Z"),
        ("owner-rule-compatibility", "owner/thread", "2026-10-06T11:30:00Z"),
        ("owner-rule-compatibility", "owner-thread", "2026-10-06"),
    ],
)
def test_preparer_rejects_noncanonical_owner_authorization(
    tmp_path: Path, authorization_id: str, source_thread_id: str, occurred_at: str
) -> None:
    _source, source_path, _projection, runner = rule_rejection_fixture(tmp_path)

    with pytest.raises(ValueError, match="authorization"):
        prepare_fresh_review_request(
            source_path,
            authorization_id=authorization_id,
            source_thread_id=source_thread_id,
            occurred_at=occurred_at,
            output_path=tmp_path / "prepared" / "fresh-review.json",
            run_command=runner,
            process_probe=lambda _pid, _created: {"exists": False, "identity_matches": False},
        )


@pytest.mark.parametrize(
    "mutation",
    ["wrong-diagnostic", "model-present", "raw-review", "child-session", "live-process"],
)
def test_preparer_rejects_any_unproved_pre_llm_rule_rejection(
    tmp_path: Path, mutation: str
) -> None:
    source, source_path, _projection, runner = rule_rejection_fixture(tmp_path)
    native = Path(str(source["recovery_root"])) / "native-attempt"
    if mutation == "wrong-diagnostic":
        (native / "ocrv.stderr.txt").write_text("Error: provider failed\n", encoding="utf-8")
    elif mutation == "model-present":
        result = json.loads((native / "ocrv-result.json").read_text(encoding="utf-8"))
        result["review"]["model"] = "qwen3.8-max"
        write_json(native / "ocrv-result.json", result)
    elif mutation == "raw-review":
        write_json(native / "ocrv-review.json", {"status": "failed"})
    elif mutation == "child-session":
        result = json.loads((native / "ocrv-result.json").read_text(encoding="utf-8"))
        result["review"]["session_id"] = "child-session"
        write_json(native / "ocrv-result.json", result)

    with pytest.raises((ValueError, worker_completion.CompletionError)):
        prepare_fresh_review_request(
            source_path,
            authorization_id="owner-rule-compatibility",
            source_thread_id="owner-thread",
            occurred_at="2026-10-06T11:30:00Z",
            output_path=tmp_path / "prepared" / "fresh-review.json",
            run_command=runner,
            process_probe=(
                (lambda _pid, _created: {"exists": True, "identity_matches": True})
                if mutation == "live-process"
                else (lambda _pid, _created: {"exists": False, "identity_matches": False})
            ),
        )


def test_fresh_compatibility_source_is_atomic_and_authorization_bound(tmp_path: Path) -> None:
    _source, source_path, _projection, runner = rule_rejection_fixture(tmp_path)
    output = tmp_path / "prepared" / "fresh-review.json"
    prepare_fresh_review_request(
        source_path,
        authorization_id="owner-rule-compatibility",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T11:30:00Z",
        output_path=output,
        run_command=runner,
        process_probe=lambda _pid, _created: {"exists": False, "identity_matches": False},
    )
    request = json.loads(output.read_text(encoding="utf-8"))
    marker = claim_fresh_review_source(request)

    changed = copy.deepcopy(request)
    changed["owner_authorization"]["authorization_id"] = "different-owner-authorization"
    with pytest.raises(worker_completion.CompletionError):
        validate_fresh_review_request(changed)
    with pytest.raises(worker_completion.CompletionError):
        claim_fresh_review_source(request)
    assert marker.is_file()


def test_concurrent_fresh_compatibility_claims_have_one_winner(tmp_path: Path) -> None:
    _source, source_path, _projection, runner = rule_rejection_fixture(tmp_path)
    output = tmp_path / "prepared" / "fresh-review.json"
    prepare_fresh_review_request(
        source_path,
        authorization_id="owner-rule-compatibility",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T11:30:00Z",
        output_path=output,
        run_command=runner,
        process_probe=lambda _pid, _created: {"exists": False, "identity_matches": False},
    )
    request = json.loads(output.read_text(encoding="utf-8"))

    def claim() -> str:
        try:
            claim_fresh_review_source(request)
            return "CLAIMED"
        except worker_completion.CompletionError as exc:
            return exc.error_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _index: claim(), range(2)))

    assert sorted(results) == ["CHECKER_TERMINAL_BUDGET_FRESH_ALREADY_CONSUMED", "CLAIMED"]


@pytest.mark.parametrize("mutation", ["run", "cell", "attempt", "candidate", "model", "rules"])
def test_fresh_request_cannot_rebind_consumed_source_identity(
    tmp_path: Path, mutation: str,
) -> None:
    _source, source_path, _projection, runner = rule_rejection_fixture(tmp_path)
    output = tmp_path / "prepared" / "fresh-review.json"
    prepare_fresh_review_request(
        source_path,
        authorization_id="owner-rule-compatibility",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T11:30:00Z",
        output_path=output,
        run_command=runner,
        process_probe=lambda _pid, _created: {"exists": False, "identity_matches": False},
    )
    request = json.loads(output.read_text(encoding="utf-8"))
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if mutation in {"run", "cell"}:
        source[mutation + "_id"] = "OTHER-" + mutation.upper()
    elif mutation == "attempt":
        source["attempt"] += 1
    elif mutation == "candidate":
        source["candidate_commit"] = "f" * 40
    elif mutation == "model":
        source["runtime_config_binding"]["model"] = "other-model"
    else:
        source["ocrv_transition"]["target_rule_config_sha256"] = "f" * 64
    write_json(source_path, source)
    request["source_request_sha256"] = sha256(source_path)
    request["owner_authorization"]["source_request_sha256"] = request["source_request_sha256"]

    with pytest.raises(worker_completion.CompletionError):
        validate_fresh_review_request(request)


def test_sealed_fresh_review_route_keeps_the_original_checker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _source, source_path, _projection, runner = rule_rejection_fixture(tmp_path)
    request_path = tmp_path / "prepared" / "fresh-review.json"
    prepare_fresh_review_request(
        source_path,
        authorization_id="owner-rule-compatibility",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T11:30:00Z",
        output_path=request_path,
        run_command=runner,
        process_probe=lambda _pid, _created: {"exists": False, "identity_matches": False},
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    source = json.loads(source_path.read_text(encoding="utf-8"))
    captured: dict[str, object] = {}

    def sealed(*_args: object, **kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "schema_version": "slk.ocrv-terminal-budget-fresh-review-result/v1",
            "method_version": "4.4.2",
            "status": "CHECKER_D1_STILL_INCOMPLETE",
            "run_id": source["run_id"],
            "cell_id": source["cell_id"],
            "attempt": source["attempt"],
            "candidate_message_id": source["candidate_message_id"],
            "checker_role_instance_id": source["checker_role_instance_id"],
            "checker_endpoint_version": source["checker_endpoint_version"],
            "recovery_invocation_id": request["recovery_invocation_id"],
            "request_sha256": sha256(request_path),
            "capacity_revision_sha256": canonical_json_sha256(source["capacity_revision"]),
            "source_rejection_sha256": request["source_rejection_sha256"],
            "compatibility_authorization_sha256": canonical_json_sha256(
                request["owner_authorization"]
            ),
            "source_d1_incomplete_event_id": source["d1_incomplete_event_id"],
            "parent_session_id": source["ocrv_session"]["session_id"],
            "child_session_id": "fresh-child-session",
            "d1_verdict": "INCOMPLETE",
            "d1_event_type": "D1_INCOMPLETE",
            "corrected_d1_event_id": None,
            "suffix_mode": None,
            "suffix_request_path": None,
            "suffix_result_path": None,
            "suffix_status": "NOT_APPLICABLE",
            "native_attempt_path": str(Path(request["recovery_root"]) / "native-attempt"),
            "native_result_path": str(Path(request["recovery_root"]) / "native-attempt" / "ocrv-result.json"),
        }

    monkeypatch.setattr(worker_completion, "_run_sealed_checker_terminal", sealed)
    result = worker_completion.resume_terminal_budget_fresh_review(
        request_path, request_sha256=sha256(request_path), prepare_only=False
    )

    assert result["status"] == "CHECKER_D1_STILL_INCOMPLETE"
    assert captured["mode"] == "--slk-fresh-terminal-budget-review"


@pytest.mark.parametrize("source_kind", ["rule-rejection", "zero-token-nonresumable"])
@pytest.mark.parametrize("verdict", ["PASS", "FAIL", "INCOMPLETE"])
def test_fresh_host_runs_full_review_without_resume_and_preserves_d1_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verdict: str, source_kind: str,
) -> None:
    source, source_path, _projection, runner = (
        rule_rejection_fixture(tmp_path)
        if source_kind == "rule-rejection"
        else nonresumable_predispatch_fixture(tmp_path)
    )
    request_path = tmp_path / "prepared" / "fresh-review.json"
    prepare_fresh_review_request(
        source_path,
        authorization_id="owner-rule-compatibility",
        source_thread_id="owner-thread",
        occurred_at="2026-10-06T11:30:00Z",
        output_path=request_path,
        run_command=runner,
        process_probe=lambda _pid, _created: {"exists": False, "identity_matches": False},
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    command = built_transport_command(tmp_path)
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "integrations" / "ocrv"))
    recovery = importlib.import_module("slk_checker_recovery")
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(source["checker_role_instance_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(source["checker_endpoint_version"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"]))
    monkeypatch.setattr(
        worker_completion,
        "_default_checker_authenticate",
        lambda *_args, **_kwargs: {
            "status": "authenticated", "role": "checker",
            "role_instance_id": source["checker_role_instance_id"],
            "runtime_revision": source["runtime_revision"],
        },
    )
    monkeypatch.setattr(
        recovery,
        "_session_resume_mode",
        lambda _source, session: (
            "RESUME_SESSION" if source_kind == "rule-rejection" else "FRESH_REVIEW",
            {"summary": {"session_id": session["session_id"]}, "items": []},
        ),
    )
    monkeypatch.setattr(recovery, "_ocrv_version", lambda: "v1.12.12")
    import slk_transport.terminal_budget_fresh as fresh_module

    monkeypatch.setattr(fresh_module, "verify_managed_target", lambda _source: None)

    def run_adapter(
        capacity_path: Path, output_path: Path, *, invocation_override: str,
        background_override: Path, resume_session: str | None, result_request_path: Path,
    ) -> int:
        assert resume_session is None
        assert background_override == Path(str(source["background_path"])).resolve()
        revised = json.loads(capacity_path.read_text(encoding="utf-8"))
        assert all(
            revised["capacity"][name] == value
            for name, value in source["capacity_revision"]["new"].items()
        )
        parent = json.loads(Path(str(source["raw_review_path"])).read_text(encoding="utf-8"))
        manifest = copy.deepcopy(parent["manifest"])
        manifest.update(run_id="fresh-child", parent_run_id=None)
        manifest["execution"].update(
            ocr_version="v1.12.12",
            rule_config_sha256=source["ocrv_transition"]["target_rule_config_sha256"],
            runtime_config_sha256=source["runtime_config_binding"]["target_sha256"],
        )
        manifest["terminal_state"] = "failed" if verdict == "INCOMPLETE" else "complete"
        selected = manifest["coverage"]["selected"]
        if verdict != "INCOMPLETE":
            manifest["coverage"].update(completed=selected, reused=[], failed=[], waived=[])
        finding = {
            "path": "src/example.py", "line": 1, "severity": "high",
            "category": "correctness", "title": "Candidate defect",
            "description": "The candidate remains incorrect.",
            "suggestion": "Repair the bounded defect.",
        }
        raw_path = output_path.parent / "ocrv-review.json"
        write_json(raw_path, {
            "status": "failed" if verdict == "INCOMPLETE" else "complete",
            "llm": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
            "summary": {"budget_exceeded": False}, "tool_calls": {"failure": 0},
            "comments": [finding] if verdict == "FAIL" else [] if verdict == "PASS" else None,
            "session_id": "fresh-child", "manifest": manifest,
        })
        write_json(output_path, {
            "schema_version": "slk.ocrv-d1-result/v1", "run_id": source["run_id"],
            "cell_id": source["cell_id"], "review_invocation_id": invocation_override,
            "verdict": verdict,
            "reason_codes": [
                "OCR_COMPLETE_ZERO_FINDINGS" if verdict == "PASS"
                else "OCR_COMPLETE_BLOCKING_FINDINGS" if verdict == "FAIL"
                else "OCR_COVERAGE_INCOMPLETE"
            ],
            "findings": [finding] if verdict == "FAIL" else [],
            "review": {
                "status": "failed" if verdict == "INCOMPLETE" else "complete",
                "provider": "dashscope-tokenplan", "model": "qwen3.8-max",
                "session_id": "fresh-child", "exit_code": {"PASS": 0, "FAIL": 2, "INCOMPLETE": 1}[verdict],
            },
            "evidence": [], "request_sha256": sha256(result_request_path),
            "artifacts": {"raw_review": str(raw_path.resolve())},
        })
        context = json.loads(os.environ["SLK_NATIVE_START_CONTEXT"])
        write_json(Path(os.environ["SLK_NATIVE_START_RECEIPT"]), {
            "schema_version": "slk.native-start/v2", "status": "STARTED",
            "adapter": "ocrv-checker", "run_id": source["run_id"], "cell_id": source["cell_id"],
            "message_id": source["candidate_message_id"], "request_sha256": source["payload_sha256"],
            "native_request_sha256": context["native_request_sha256"],
            "observed_at": "2026-10-06T11:31:00Z",
            "process": {"pid": os.getpid(), "creation_time": "test"},
            "native_task": {"kind": "ocrv-review", "id": invocation_override, "status": "RUNNING"},
        })
        child = Path(str(source["session_record_path"])).resolve().parent / "fresh-child.jsonl"
        child.write_text("\n".join(json.dumps(row, sort_keys=True) for row in (
            {"type": "session_start", "sessionId": "fresh-child"},
            {"type": "session_end", "sessionId": "fresh-child", "run_manifest": manifest},
        )) + "\n", encoding="utf-8")
        return {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}[verdict]

    monkeypatch.setattr(recovery.checker_adapter, "run", run_adapter)
    monkeypatch.setattr(
        recovery,
        "_run_ocrv_json",
        lambda arguments: {
            "summary": {
                "session_id": arguments[-1],
                "file_path": str(Path(str(source["session_record_path"])).resolve().parent / "fresh-child.jsonl"),
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
        projection = json.loads(Path(str(source["runtime_projection_path"])).read_text(encoding="utf-8"))
        projection["runtime_snapshot"]["runtime_revision"] += 1
        event_id = worker_completion._stable_id(
            source["candidate_message_id"], "d1-budget-" + request["recovery_invocation_id"]
        )
        projection["administrative_snapshot"]["latest_event_id"] = event_id
        projection["runtime_snapshot"]["latest_event_id"] = event_id
        if verdict != "INCOMPLETE":
            projection["events"].append({
                "event_id": event_id, "event_type": "D1_PASSED" if verdict == "PASS" else "D1_FAILED",
                "author_role_instance_id": source["checker_role_instance_id"], "go_id": source["go_id"],
                "cell_id": source["cell_id"], "attempt": source["attempt"],
                "corrects_event_id": source["d1_incomplete_event_id"],
                "details_json": json.dumps({
                    "candidate_message_id": source["candidate_message_id"], "verdict": verdict,
                }, sort_keys=True),
                "occurred_at": "2026-10-06T11:32:00Z",
            })
        return projection

    monkeypatch.setattr(worker_completion, "_default_load_current_projection", current_projection)

    def record(command_line: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if "--slk-complete-d1" in command_line or "--slk-post-d1" in command_line:
            output = Path(command_line[command_line.index("--output") + 1])
            value = {"status": "CHECKER_COMPLETION_COMMITTED" if verdict == "PASS" else "CHECKER_ESCALATION_COMMITTED"}
            write_json(output, value)
            return subprocess.CompletedProcess(command_line, 0, json.dumps(value).encode(), b"")
        committed_path = Path(command_line[command_line.index("--request") + 1])
        value = {
            "request_sha256": sha256(committed_path), "d1_verdict": verdict,
            "d1_event_type": "D1_PASSED" if verdict == "PASS" else "D1_FAILED",
        }
        return subprocess.CompletedProcess(command_line, 0, json.dumps(value).encode(), b"")

    monkeypatch.setattr(recovery.subprocess, "run", record)
    assert recovery._fresh_terminal_budget_review(request, request_path, command) == 0
    result = json.loads(Path(str(request["result_path"])).read_text(encoding="utf-8"))
    assert result["d1_verdict"] == verdict
    assert result["status"] == (
        "CHECKER_D1_STILL_INCOMPLETE" if verdict == "INCOMPLETE" else "CHECKER_D1_RECORDED"
    )
    assert result["parent_session_id"] == source["ocrv_session"]["session_id"]
    assert (Path(str(request["recovery_root"])) / "fresh-consumed.json").is_file()
    lineage = json.loads(
        (Path(str(request["recovery_root"])) / "native-attempt" / "compatibility-lineage.json").read_text(
            encoding="utf-8"
        )
    )
    assert lineage["checkpoint_reuse"] is False
    assert lineage["source_rejection_sha256"] == request["source_rejection_sha256"]
    session_text = (
        Path(str(request["recovery_root"])) / "native-attempt" / "native-session.jsonl"
    ).read_text(encoding="utf-8")
    assert '"type": "resume_lineage"' not in session_text
