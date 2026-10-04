from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

import slk_transport.worker_completion as worker_completion
from slk_transport.worker_completion import CompletionError

from test_committed_checker_terminal import fixture as committed_fixture
from test_committed_checker_terminal import sha256, write_json

ROOT = Path(__file__).resolve().parents[2]


def dead_activity(*_args: object, **_kwargs: object) -> dict[str, object]:
    return {
        "schema_version": "slk.native-activity/v1",
        "status": "DEAD_WITHOUT_TERMINAL",
        "observed_at": "2026-10-02T08:00:00Z",
        "process": {"exists": False, "identity_matches": False},
        "native_task": {"kind": "ocrv-review", "id": "review-1", "status": "RUNNING"},
        "last_event": None,
        "waiting_on": None,
        "terminal_evidence": None,
        "error": None,
    }


def resume_fixture(tmp_path: Path) -> tuple[dict[str, object], Path]:
    base, _base_path = committed_fixture(tmp_path)
    attempt = Path(str(base["native_attempt_path"]))
    (attempt / "completed.json").unlink()
    (attempt / "ocrv-result.json").unlink()

    ocrv_request_path = attempt / "ocrv-request.json"
    ocrv_request = json.loads(ocrv_request_path.read_text(encoding="utf-8"))
    preflight = {
        "schema_version": "slk.ocrv-d1-preflight/v1",
        "status": "READY",
        "run_id": base["run_id"],
        "cell_id": base["cell_id"],
        "request_sha256": sha256(ocrv_request_path),
        "background": {
            "characters": 18,
            "bytes": 18,
            "evidence_bytes": 0,
            "sha256": "",
        },
        "preview": {
            "exit_code": 0,
            "selected_paths": ["src/example.py"],
            "inventory": [
                {
                    "path": "src/example.py",
                    "status": "modified",
                    "insertions": 1,
                    "deletions": 0,
                    "will_review": True,
                }
            ],
            "stdout_sha256": "0" * 64,
            "stderr_sha256": "1" * 64,
        },
        "scope": ocrv_request["review_scope"],
        "capabilities": {"available": ["ocrv-preview"], "selected": [], "invocations": []},
    }
    background = Path(str(base["checker_endpoint"]["address"]["runtime_root"])) / str(
        base["run_id"]
    ) / str(base["cell_id"]) / "review-1" / "d1-background.md"
    background.parent.mkdir(parents=True)
    background.write_text("original D1 input\n", encoding="utf-8")
    preflight["background"]["sha256"] = sha256(background)
    preflight_path = write_json(attempt / "ocrv-preflight.json", preflight)
    activity_path = write_json(
        attempt / "native-activity.json",
        {
            "schema_version": "slk.native-task-activity/v1",
            "adapter": "ocrv-checker",
            "run_id": base["run_id"],
            "cell_id": base["cell_id"],
            "message_id": base["candidate_message_id"],
            "native_task_id": "review-1",
            "status": "RUNNING",
            "sequence": 7,
            "observed_at": "2026-10-02T07:24:52Z",
            "last_event": {"kind": "OCRV_PROGRESS", "sequence": 7, "summary_sha256": "2" * 64},
            "waiting_on": "OCRV_REVIEW",
        },
    )
    session_record = tmp_path / "ocrv-sessions" / "ocrv-session-1.jsonl"
    session_record.parent.mkdir()
    session_start = {
        "cwd": str(Path(str(base["candidate_repository"])).resolve()).replace("\\", "/"),
        "diffCommit": base["candidate_commit"],
        "gitBranch": "feature/test",
        "model": "qwen3.8-max",
        "parentUuid": None,
        "reviewMode": "commit",
        "sessionId": "ocrv-session-1",
        "timestamp": "2026-10-02T07:21:32Z",
        "type": "session_start",
        "uuid": "77777777-7777-4777-8777-777777777777",
    }
    session_record.write_text(json.dumps(session_start) + "\n", encoding="utf-8")
    recovery_root = attempt / "resume-incomplete-checker" / str(base["recovery_invocation_id"])
    request = {
        key: base[key]
        for key in (
            "method_version",
            "recovery_invocation_id",
            "run_id",
            "go_id",
            "cell_id",
            "attempt",
            "plan_revision",
            "runtime_revision",
            "token_sequence",
            "worker_role_instance_id",
            "checker_role_instance_id",
            "checker_endpoint_version",
            "checker_endpoint",
            "runtime_projection_path",
            "runtime_projection_sha256",
            "candidate_repository",
            "candidate_commit",
            "candidate_parent",
            "candidate_message_id",
            "payload_sha256",
            "candidate_submitted_event_id",
            "transport_started_event_id",
            "commit_request_path",
            "commit_request_sha256",
            "native_attempt_path",
            "checker_credential_path",
            "state_command",
            "transport_command",
        )
    }
    request.update(
        {
            "schema_version": "slk.ocrv-incomplete-checker-resume-request/v1",
            "background_path": str(background.resolve()),
            "ocrv_session": {
                "session_id": "ocrv-session-1",
                "session_record_path": str(session_record.resolve()),
                "session_record_sha256": sha256(session_record),
                "repo_dir": str(Path(str(base["candidate_repository"])).resolve()).replace("\\", "/"),
                "diff_commit": base["candidate_commit"],
                "model": "qwen3.8-max",
                "review_mode": "commit",
                "start_time": "2026-10-02T07:21:32Z",
                "aborted": True,
                "selected_files": 0,
                "completed_files": 0,
            },
            "immutable_sha256": {
                "endpoint.json": sha256(attempt / "endpoint.json"),
                "envelope.json": sha256(attempt / "envelope.json"),
                "started.json": sha256(attempt / "started.json"),
                "ocrv-request.json": sha256(ocrv_request_path),
                "ocrv-preflight.json": sha256(preflight_path),
                "d1-background.md": sha256(background),
                "native-activity.json": sha256(activity_path),
                "session-record": sha256(session_record),
            },
            "recovery_root": str(recovery_root.resolve()),
            "result_path": str((recovery_root / "result.json").resolve()),
        }
    )
    request_path = write_json(tmp_path / "resume-request.json", request)
    return request, request_path


def test_resume_schema_identity_matches_runtime_and_valid_request(tmp_path: Path) -> None:
    schema = json.loads(
        (ROOT / "docs/contracts/slk-ocrv-incomplete-checker-resume.schema.json").read_text(
            encoding="utf-8"
        )
    )
    request, _request_path = resume_fixture(tmp_path)

    assert schema["properties"]["schema_version"]["const"] == worker_completion.INCOMPLETE_RESUME_SCHEMA
    assert request["schema_version"] == worker_completion.INCOMPLETE_RESUME_SCHEMA


def test_outer_resume_validates_closed_incomplete_review_then_enters_sealed_checker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, request_path = resume_fixture(tmp_path)
    monkeypatch.setattr(worker_completion, "inspect_native_activity", dead_activity)
    captured: dict[str, object] = {}

    def sealed(*args: object, **kwargs: object) -> dict[str, object]:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {
            "schema_version": "slk.ocrv-committed-terminal-result/v1",
            "method_version": "4.4.0",
            "status": "CHECKER_D1_RECORDED",
            "run_id": request["run_id"],
            "cell_id": request["cell_id"],
            "attempt": request["attempt"],
            "candidate_message_id": request["candidate_message_id"],
            "checker_role_instance_id": request["checker_role_instance_id"],
            "checker_endpoint_version": request["checker_endpoint_version"],
            "checker_authenticated": True,
            "authorized_existing_terminal": True,
            "recovery_invocation_id": request["recovery_invocation_id"],
            "request_sha256": sha256(request_path),
            "runtime_revision": request["runtime_revision"],
            "token_sequence": request["token_sequence"],
            "native_attempt_path": str(Path(str(request["recovery_root"])) / "native-attempt"),
            "d1_verdict": "PASS",
            "d1_event_type": "D1_PASSED",
            "native_result_path": str(Path(str(request["recovery_root"])) / "native-attempt" / "ocrv-result.json"),
        }

    monkeypatch.setattr(worker_completion, "_run_sealed_checker_terminal", sealed)
    result = worker_completion.resume_incomplete_checker(
        request_path, request_sha256=sha256(request_path)
    )

    assert result["d1_verdict"] == "PASS"
    assert captured["kwargs"]["mode"] == "--slk-resume-incomplete-checker"


@pytest.mark.parametrize(
    "mutation",
    ["terminal", "session-candidate", "process-alive", "wrong-token"],
)
def test_resume_rejects_terminal_mismatch_or_live_process_before_host_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    request, request_path = resume_fixture(tmp_path)
    activity = dead_activity
    if mutation == "terminal":
        write_json(Path(str(request["native_attempt_path"])) / "completed.json", {"status": "completed"})
    elif mutation == "session-candidate":
        request["ocrv_session"]["diff_commit"] = "c" * 40
        write_json(request_path, request)
    elif mutation == "process-alive":
        activity = lambda *_a, **_k: {**dead_activity(), "status": "ACTIVE"}
    elif mutation == "wrong-token":
        request["token_sequence"] = int(request["token_sequence"]) + 1
        write_json(request_path, request)
    monkeypatch.setattr(worker_completion, "inspect_native_activity", activity)
    monkeypatch.setattr(
        worker_completion,
        "_run_sealed_checker_terminal",
        lambda *_args, **_kwargs: pytest.fail("invalid recovery must not enter Checker host"),
    )

    with pytest.raises(CompletionError):
        worker_completion.resume_incomplete_checker(
            request_path, request_sha256=sha256(request_path)
        )


def test_second_resume_is_rejected_by_the_consumed_recovery_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, request_path = resume_fixture(tmp_path)
    monkeypatch.setattr(worker_completion, "inspect_native_activity", dead_activity)
    consumed = Path(str(request["recovery_root"])) / "resume-consumed.json"
    write_json(consumed, {"request_sha256": sha256(request_path)})

    with pytest.raises(CompletionError, match="already consumed"):
        worker_completion.resume_incomplete_checker(
            request_path, request_sha256=sha256(request_path)
        )


def test_sealed_terminal_nonzero_preserves_the_native_stderr_reason(tmp_path, monkeypatch) -> None:
    request, request_path = resume_fixture(tmp_path)
    endpoint = worker_completion.Endpoint.from_dict(request['checker_endpoint'])
    monkeypatch.setattr(worker_completion.subprocess, 'run', lambda *a, **k:
        subprocess.CompletedProcess(a, 5, b'', b'bounded continuation remains incomplete'))

    with pytest.raises(CompletionError, match='bounded continuation remains incomplete'):
        worker_completion._run_sealed_checker_terminal(
            request_path, request, endpoint, request_sha256=sha256(request_path),
            mode='--slk-resume-incomplete-checker', result_schema='unused', error_code='TEST_FAILED')
