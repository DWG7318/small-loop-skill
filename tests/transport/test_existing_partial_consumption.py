from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path

import pytest

from slk_transport.contracts import canonical_json_sha256
from slk_transport.native_activity import make_native_start
from test_committed_checker_terminal import sha256, write_json
from test_incomplete_checker_resume import dead_activity
from test_partial_checker_resume import later_partial_fixture


def _activity(path: Path, request: dict[str, object], task_id: str, *, failed: bool = False) -> None:
    write_json(path, {
        "schema_version": "slk.native-task-activity/v1",
        "adapter": "ocrv-checker",
        "run_id": request["run_id"],
        "cell_id": request["cell_id"],
        "message_id": request["candidate_message_id"],
        "native_task_id": task_id,
        "status": "FAILED" if failed else "COMPLETED",
        "sequence": 2,
        "observed_at": "2026-10-03T00:00:00Z",
        "last_event": {
            "kind": "OCRV_PROCESS_EXITED",
            "sequence": 2,
            "exit_code": 1 if failed else 0,
        },
        "waiting_on": None,
    })


def _start(path: Path, request: dict[str, object], request_path: Path, task_id: str) -> None:
    write_json(path, make_native_start(
        adapter="ocrv-checker",
        run_id=str(request["run_id"]),
        cell_id=str(request["cell_id"]),
        message_id=str(request["candidate_message_id"]),
        request_sha256=str(request["payload_sha256"]),
        native_request_sha256=sha256(request_path),
        native_task_kind="ocrv-review",
        native_task_id=task_id,
        native_task_status="RUNNING",
        pid=os.getpid(),
    ))


def _result(
    root: Path,
    request: dict[str, object],
    request_path: Path,
    *,
    task_id: str,
    raw: Path,
    verdict: str,
    reasons: list[str],
    session_id: str,
    status: str,
    findings: list[dict[str, object]],
) -> Path:
    for name in ("ocrv.stdout.txt", "ocrv.stderr.txt"):
        (root / name).write_text("", encoding="utf-8")
    return write_json(root / "result.json", {
        "schema_version": "slk.ocrv-d1-result/v1",
        "run_id": request["run_id"],
        "cell_id": request["cell_id"],
        "review_invocation_id": task_id,
        "verdict": verdict,
        "reason_codes": reasons,
        "findings": findings,
        "evidence": [],
        "request_sha256": sha256(request_path),
        "review": {
            "status": status,
            "provider": "dashscope-tokenplan",
            "model": "qwen3.8-max",
            "session_id": session_id,
            "exit_code": 0 if status != "failed" else 1,
        },
        "artifacts": {
            "raw_review": str(raw),
            "stdout": str(root / "ocrv.stdout.txt"),
            "stderr": str(root / "ocrv.stderr.txt"),
            "background": str(root / "d1-background.md"),
        },
    })


def _session(
    path: Path,
    manifest: dict[str, object],
    *,
    session_id: str,
    parent_id: str | None,
    rows: list[dict[str, object]] | None = None,
) -> None:
    lineage = [] if parent_id is None else [{
        "type": "resume_lineage",
        "schema_version": "ocr.resume-lineage/v1",
        "parent_run_id": parent_id,
        "run_id": session_id,
        "source_provider": "dashscope-tokenplan",
        "source_model": "qwen3.8-max",
        "target_provider": "dashscope-tokenplan",
        "target_model": "qwen3.8-max",
    }]
    all_rows = [*lineage, *(rows or []), {
        "type": "session_end", "sessionId": session_id, "run_manifest": manifest,
    }]
    path.write_text("\n".join(json.dumps(row) for row in all_rows) + "\n", encoding="utf-8")


def existing_partial_completion_fixture(tmp_path: Path):
    request, request_path, basis, second, _result_path, second_session = later_partial_fixture(tmp_path)
    recovery_root = Path(request["recovery_root"])
    attempt = recovery_root / "native-attempt"
    shutil.rmtree(attempt / "review-corrections")
    (recovery_root / "continue-consumed.json").unlink()
    first = attempt / "review-segments/segment-001"
    first_result = json.loads((first / "result.json").read_text())
    first_result.update(verdict="FAIL", reason_codes=["OCR_BLOCKING_FINDINGS_PRESENT"])
    write_json(first / "result.json", first_result)
    first_raw = json.loads((first / "ocrv-review.json").read_text())
    first_rows = [{
        "type": "review_item_done" if kind == "completed" else "review_item_reused",
        "sessionId": first_raw["session_id"], "filePath": item["path"],
        "fingerprint": item["fingerprint"], "comments": first_raw["comments"],
    } for kind in ("completed", "reused") for item in first_raw["manifest"]["coverage"][kind]]
    _session(Path(request["ocrv_session"]["session_record_path"]).parent
             / f"{first_raw['session_id']}.jsonl", first_raw["manifest"],
             session_id=first_raw["session_id"], parent_id=basis["manifest"]["run_id"],
             rows=first_rows)

    external = tmp_path / "completed-existing-evidence"
    session_dir = Path(request["ocrv_session"]["session_record_path"]).parent
    old_raw = json.loads((second / "ocrv-review.json").read_text())
    old_coverage = old_raw["manifest"]["coverage"]
    old_completed = copy.deepcopy(old_coverage["completed"])
    old_failed = copy.deepcopy(old_coverage["failed"])

    resumed = external / "segment-002-resume"
    resumed.mkdir(parents=True)
    resumed_manifest = copy.deepcopy(old_raw["manifest"])
    resumed_session_id = "segment-2-partial-child"
    resumed_manifest.update(run_id=resumed_session_id, terminal_state="partial")
    resumed_manifest["coverage"].update(
        completed=[], reused=old_completed, failed=old_failed, waived=[])
    resumed_raw = write_json(resumed / "ocrv-review.json", {
        "status": "partial", "session_id": resumed_session_id,
        "manifest": resumed_manifest, "comments": old_raw["comments"],
        "llm": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
        "tool_calls": {"failure": 0},
    })
    _result(resumed, request, second / "request.json", task_id="segment-2-resume-task",
            raw=resumed_raw, verdict="INCOMPLETE",
            reasons=["OCR_STATUS_NOT_COMPLETE", "OCR_COVERAGE_INCOMPLETE"],
            session_id=resumed_session_id, status="partial", findings=old_raw["comments"])
    _start(resumed / "started.json", request, second / "request.json", "segment-2-resume-task")
    _activity(resumed / "native-activity.json", request, "segment-2-resume-task")
    _session(session_dir / f"{resumed_session_id}.jsonl", resumed_manifest,
             session_id=resumed_session_id,
             parent_id=json.loads(second_session.read_text().splitlines()[-1])["sessionId"],
             rows=[{
                 "type": "review_item_reused", "sessionId": resumed_session_id,
                 "filePath": old_completed[0]["path"], "fingerprint": old_completed[0]["fingerprint"],
                 "comments": old_raw["comments"],
             }, {
                 "type": "review_item_failed", "sessionId": resumed_session_id,
                 "filePath": old_failed[0]["path"], "fingerprint": old_failed[0]["fingerprint"],
             }])

    narrowed = external / "segment-002-mod"
    narrowed.mkdir()
    narrowed_request = json.loads((second / "request.json").read_text())
    narrowed_request["cell_goal"] = "Only the still-uncovered frozen item."
    narrowed_request["review_scope"]["include_paths"] = [old_failed[0]["path"]]
    narrowed_request["review_scope"]["exclude_paths"] = [
        *json.loads((second / "request.json").read_text())["review_scope"]["exclude_paths"],
        old_completed[0]["path"],
    ]
    narrowed_request["review_scope"]["scope_sha256"] = canonical_json_sha256({
        key: value for key, value in narrowed_request["review_scope"].items()
        if key != "scope_sha256"
    })
    narrowed_request_path = write_json(narrowed / "request.json", narrowed_request)
    narrowed_session_id = "segment-2-narrowed-failed"
    narrowed_manifest = copy.deepcopy(resumed_manifest)
    narrowed_manifest.update(run_id=narrowed_session_id, terminal_state="failed")
    narrowed_manifest["coverage"].update(
        selected=[old_failed[0]], completed=[], reused=[], failed=old_failed, waived=[])
    narrowed_raw = write_json(narrowed / "ocrv-review.json", {
        "status": "failed", "session_id": narrowed_session_id,
        "manifest": narrowed_manifest, "comments": [],
        "llm": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
        "tool_calls": {"failure": 0},
    })
    _result(narrowed, request, narrowed_request_path, task_id="segment-2-narrowed-task",
            raw=narrowed_raw, verdict="INCOMPLETE",
            reasons=["OCR_EXIT_1", "OCR_STATUS_NOT_COMPLETE", "OCR_COVERAGE_INCOMPLETE"],
            session_id=narrowed_session_id, status="failed", findings=[])
    _start(narrowed / "started.json", request, narrowed_request_path, "segment-2-narrowed-task")
    _activity(narrowed / "native-activity.json", request, "segment-2-narrowed-task", failed=True)
    _session(session_dir / f"{narrowed_session_id}.jsonl", narrowed_manifest,
             session_id=narrowed_session_id, parent_id=None,
             rows=[{
                 "type": "review_item_failed", "sessionId": narrowed_session_id,
                 "filePath": old_failed[0]["path"], "fingerprint": old_failed[0]["fingerprint"],
             }])

    completed = external / "segment-002-mod-resume"
    completed.mkdir()
    completed_request = copy.deepcopy(narrowed_request)
    completed_request["capacity"]["max_tokens_budget"] = 800_000
    completed_request_path = write_json(completed / "request.json", completed_request)
    completed_session_id = "segment-2-narrowed-complete"
    completed_manifest = copy.deepcopy(narrowed_manifest)
    completed_manifest.update(run_id=completed_session_id, terminal_state="complete")
    completed_manifest["coverage"].update(
        selected=[old_failed[0]], completed=[old_failed[0]], reused=[], failed=[], waived=[])
    completed_findings = [{"severity": "low", "message": "preserved low observation"}]
    completed_raw = write_json(completed / "ocrv-review.json", {
        "status": "complete", "session_id": completed_session_id,
        "manifest": completed_manifest, "comments": completed_findings,
        "llm": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
        "tool_calls": {"failure": 0},
    })
    _result(completed, request, completed_request_path, task_id="segment-2-complete-task",
            raw=completed_raw, verdict="PASS", reasons=["OCR_COMPLETE_LOW_SEVERITY_OBSERVATIONS"],
            session_id=completed_session_id, status="complete", findings=completed_findings)
    _start(completed / "started.json", request, completed_request_path, "segment-2-complete-task")
    _activity(completed / "native-activity.json", request, "segment-2-complete-task")
    _session(session_dir / f"{completed_session_id}.jsonl", completed_manifest,
             session_id=completed_session_id, parent_id=narrowed_session_id,
             rows=[{
                 "type": "review_item_done", "sessionId": completed_session_id,
                 "filePath": old_failed[0]["path"], "fingerprint": old_failed[0]["fingerprint"],
                 "comments": completed_findings,
             }])

    third = external / "segment-003"
    third.mkdir()
    third_request = basis["segments"][2]
    third_scope = json.loads(third_request.read_text())["review_scope"]["include_paths"]
    third_selected = [
        {"item_id": f"item-{index}", "path": path, "fingerprint": str(index) * 64}
        for index, path in enumerate(third_scope, 1)
    ]
    third_session_id = "segment-3-complete"
    third_manifest = copy.deepcopy(basis["manifest"])
    third_manifest.update(run_id=third_session_id, terminal_state="complete")
    third_manifest["coverage"].update(
        selected=third_selected, completed=third_selected, reused=[], failed=[], waived=[])
    third_findings = [{"severity": "medium", "message": "third-segment defect"}]
    third_raw = write_json(third / "ocrv-review.json", {
        "status": "complete", "session_id": third_session_id,
        "manifest": third_manifest, "comments": third_findings,
        "llm": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
        "tool_calls": {"failure": 0},
    })
    _result(third, request, third_request, task_id="segment-3-task", raw=third_raw,
            verdict="FAIL", reasons=["OCR_BLOCKING_FINDINGS_PRESENT"],
            session_id=third_session_id, status="complete", findings=third_findings)
    _start(third / "started.json", request, third_request, "segment-3-task")
    _activity(third / "native-activity.json", request, "segment-3-task")
    _session(session_dir / f"{third_session_id}.jsonl", third_manifest,
             session_id=third_session_id, parent_id=None,
             rows=[{
                 "type": "review_item_done", "sessionId": third_session_id,
                 "filePath": item["path"], "fingerprint": item["fingerprint"], "comments": [],
             } for item in third_selected])
    return request, request_path, external


def test_existing_partial_completion_prepare_only_accepts_without_model_launch(tmp_path, monkeypatch):
    from slk_transport import worker_completion as wc

    request, request_path, evidence_root = existing_partial_completion_fixture(tmp_path)
    monkeypatch.setattr(wc, "inspect_native_activity", dead_activity)
    monkeypatch.setattr(
        wc, "_default_load_current_projection",
        lambda *args: json.loads(Path(request["runtime_projection_path"]).read_text()),
    )
    monkeypatch.setattr(
        wc, "_run_sealed_checker_terminal",
        lambda *args, **kwargs: pytest.fail("prepare-only must not launch OCRV"),
    )

    result = wc.consume_existing_partial_checker(
        request_path,
        request_sha256=sha256(request_path),
        evidence_root=evidence_root,
        prepare_only=True,
    )

    assert result["status"] == "READY_TO_CONSUME_EXISTING_PARTIAL_EVIDENCE"
    assert result["candidate_message_id"] == request["candidate_message_id"]
    assert result["verdict"] == "FAIL"
    assert result["completed_segment_count"] == 3
    assert not (Path(request["recovery_root"]) / "consume-existing-partial").exists()


def test_cli_exposes_closed_existing_partial_prepare_only_command(tmp_path, monkeypatch, capsys):
    from slk_transport import cli

    request = tmp_path / "request.json"
    evidence = tmp_path / "evidence"
    request.write_text("{}", encoding="utf-8")
    evidence.mkdir()
    calls = []
    monkeypatch.setattr(
        cli, "consume_existing_partial_checker",
        lambda request_path, **kwargs: calls.append((request_path, kwargs))
        or {"status": "READY_TO_CONSUME_EXISTING_PARTIAL_EVIDENCE"},
    )

    assert cli.main([
        "consume-existing-partial", "--request", str(request), "--sha256", "a" * 64,
        "--evidence-root", str(evidence), "--prepare-only",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "READY_TO_CONSUME_EXISTING_PARTIAL_EVIDENCE"
    assert calls == [(request, {
        "request_sha256": "a" * 64, "evidence_root": evidence, "prepare_only": True,
    })]


def test_sealed_checker_consumes_existing_chain_once_without_model_call(tmp_path, monkeypatch, capsys):
    import importlib
    import subprocess
    from slk_transport import worker_completion as wc
    from slk_transport.partial_review import read, validate_partial_terminal

    request, request_path, evidence_root = existing_partial_completion_fixture(tmp_path)
    source_hashes = {str(path): sha256(path) for path in evidence_root.rglob("*") if path.is_file()}
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "integrations/ocrv"))
    recovery = importlib.import_module("slk_checker_recovery")
    monkeypatch.setattr(wc, "inspect_native_activity", dead_activity)
    for key, value in {
        "SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID": request["checker_role_instance_id"],
        "SLK_OCRV_RECOVERY_ENDPOINT_VERSION": str(request["checker_endpoint_version"]),
        "SLK_OCRV_RECOVERY_INVOCATION_ID": request["recovery_invocation_id"],
    }.items():
        monkeypatch.setenv(key, value)
    authentication = lambda *args: {
        "status": "authenticated", "role": "checker",
        "role_instance_id": request["checker_role_instance_id"],
        "runtime_revision": request["runtime_revision"],
    }
    monkeypatch.setattr(wc, "_default_checker_authenticate", authentication)
    monkeypatch.setattr(
        recovery.checker_adapter, "run",
        lambda *args, **kwargs: pytest.fail("existing terminal consumption must not call the model"),
    )
    writes = []
    monkeypatch.setattr(wc, "unprotect_dpapi_hex", lambda *args: "test-only")
    monkeypatch.setattr(
        wc, "_run_json_command",
        lambda command, args, **kwargs: writes.append(
            read(Path(args[args.index("--request") + 1])))
        or {"status": "recorded", "run_id": request["run_id"]},
    )

    def terminal_host(args, **kwargs):
        terminal_path = Path(args[args.index("--request") + 1])
        result = wc.execute_committed_checker_terminal(
            read(terminal_path), request_sha256=sha256(terminal_path),
            authenticate_checker=authentication,
        )
        return subprocess.CompletedProcess(args, 0, json.dumps(result).encode(), b"")

    monkeypatch.setattr(recovery.subprocess, "run", terminal_host)
    assert recovery._consume_existing_partial(
        request, request_path, request["transport_command"], evidence_root) == 0
    capsys.readouterr()

    formal_root = Path(request["recovery_root"]) / "consume-existing-partial"
    aggregate = read(formal_root / "native-attempt/ocrv-aggregate.json")
    assert aggregate["verdict"] == "FAIL"
    assert aggregate["completed_segment_count"] == 3
    assert aggregate["segments"][1]["verdict"] == "FAIL"
    composite_findings = read(
        formal_root / "native-attempt/review-segments/segment-002/result.json")["findings"]
    assert len(composite_findings) == 3
    assert len({canonical_json_sha256(item) for item in composite_findings}) == 3
    assert [item["event_type"] for item in writes] == ["D1_FAILED"]
    assert writes[0]["corrects_event_id"] == request["partial_review"]["d1_incomplete_event_id"]
    committed = read(formal_root / "committed-terminal.json")
    validate_partial_terminal(committed, recorded_d1=writes[0])
    assert source_hashes == {str(path): sha256(path) for path in evidence_root.rglob("*") if path.is_file()}
    with pytest.raises(ValueError, match="one-shot"):
        recovery._consume_existing_partial(
            request, request_path, request["transport_command"], evidence_root)


@pytest.mark.parametrize("mutation", ["missing-third", "candidate", "fingerprint"])
def test_existing_partial_completion_rejects_incomplete_or_drifted_evidence(tmp_path, monkeypatch, mutation):
    from slk_transport import worker_completion as wc

    request, request_path, evidence_root = existing_partial_completion_fixture(tmp_path)
    if mutation == "missing-third":
        (evidence_root / "segment-003/result.json").unlink()
    elif mutation == "candidate":
        raw_path = evidence_root / "segment-002-mod-resume/ocrv-review.json"
        raw = json.loads(raw_path.read_text())
        raw["manifest"]["input"]["resolved_head"] = "f" * 40
        write_json(raw_path, raw)
    else:
        raw_path = evidence_root / "segment-002-mod-resume/ocrv-review.json"
        raw = json.loads(raw_path.read_text())
        raw["manifest"]["coverage"]["completed"][0]["fingerprint"] = "e" * 64
        write_json(raw_path, raw)
    monkeypatch.setattr(wc, "inspect_native_activity", dead_activity)
    monkeypatch.setattr(
        wc, "_run_sealed_checker_terminal",
        lambda *args, **kwargs: pytest.fail("invalid evidence must not launch OCRV"),
    )

    with pytest.raises(wc.CompletionError):
        wc.consume_existing_partial_checker(
            request_path,
            request_sha256=sha256(request_path),
            evidence_root=evidence_root,
            prepare_only=True,
        )
