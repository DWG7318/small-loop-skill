from __future__ import annotations

import hashlib
import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

import slk_transport.worker_completion as worker_completion
from slk_transport.contracts import canonical_json_sha256
from slk_transport.native_activity import make_native_start
from slk_transport.worker_completion import CompletionError

from test_contracts import endpoint_value, envelope_value


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path: Path) -> tuple[dict[str, object], Path]:
    run_id = "RUN-A"
    go_id = "GO-001"
    cell_id = "CELL-001"
    attempt = 10
    candidate_commit = "b" * 40
    candidate_parent = "a" * 40
    message_id = "11111111-1111-4111-8111-111111111111"
    candidate_event_id = "22222222-2222-4222-8222-222222222222"
    transport_event_id = "33333333-3333-4333-8333-333333333333"
    receipt_id = "44444444-4444-4444-8444-444444444444"
    worker_id = "RUN-A-worker-001"
    checker_id = "RUN-A-checker-001"
    overwatcher_id = "RUN-A-overwatcher-001"
    repository = tmp_path / "repository"
    repository.mkdir()
    runtime_root = tmp_path / "ocrv-runtime"
    runtime_root.mkdir()
    checker = endpoint_value(role="checker", version=2)
    checker["role_instance_id"] = checker_id
    checker["address"] = {
        "command": ["D:/OCRV/slk-checker.cmd"],
        "runtime_root": str(runtime_root),
        "timeout_seconds": 30,
    }
    payload = {
        "repository": str(repository.resolve()),
        "candidate": {"kind": "commit", "commit": candidate_commit},
        "cell_goal": "judge the preserved candidate",
        "d1_criteria": ["the existing review is complete"],
        "evidence_files": [],
    }
    envelope = envelope_value(sender_role="worker", receiver_role="checker")
    envelope.update(
        {
            "run_id": run_id,
            "go_id": go_id,
            "cell_id": cell_id,
            "message_id": message_id,
            "sender_role_instance_id": worker_id,
            "receiver_role_instance_id": checker_id,
            "receiver_endpoint_version": 2,
            "token_sequence": 31,
            "payload_type": "CANDIDATE_READY",
            "payload": payload,
            "payload_sha256": canonical_json_sha256(payload),
        }
    )
    native_attempt = tmp_path / "attempts" / run_id / message_id
    endpoint_path = write_json(native_attempt / "endpoint.json", checker)
    envelope_path = write_json(native_attempt / "envelope.json", envelope)
    ocrv_request = {
        "schema_version": "slk.ocrv-d1-request/v2",
        "run_id": run_id,
        "cell_id": cell_id,
        "repository": str(repository.resolve()),
        "candidate": {"kind": "commit", "commit": candidate_commit},
        "cell_goal": payload["cell_goal"],
        "d1_criteria": payload["d1_criteria"],
        "evidence_files": [],
        "review_scope": {
            "include_paths": ["src/example.py"],
            "exclude_paths": [],
            "criterion_ids": ["D1-001"],
            "scope_sha256": canonical_json_sha256(
                {
                    "include_paths": ["src/example.py"],
                    "exclude_paths": [],
                    "criterion_ids": ["D1-001"],
                }
            ),
        },
        "capacity": {
            "max_background_characters": 8000,
            "max_background_bytes": 12000,
            "max_changed_lines": 800,
            "max_segment_paths": 2,
            "max_tokens": 200000,
            "max_tokens_budget": 500000,
            "timeout_minutes": 15,
        },
    }
    ocrv_request_path = write_json(native_attempt / "ocrv-request.json", ocrv_request)
    started_path = write_json(
        native_attempt / "started.json",
        make_native_start(
            adapter="ocrv-checker",
            run_id=run_id,
            cell_id=cell_id,
            message_id=message_id,
            request_sha256=envelope["payload_sha256"],
            native_request_sha256=sha256(ocrv_request_path),
            native_task_kind="ocrv-review",
            native_task_id="review-1",
            native_task_status="RUNNING",
            pid=os.getpid(),
        ),
    )
    raw_review = {
        "status": "complete",
        "session_id": "ocrv-session-1",
        "manifest": {
            "schema_version": "ocr.run-manifest/v1",
            "run_id": "ocrv-session-1",
            "operation": "review",
            "terminal_state": "complete",
            "input": {
                "requested_head": candidate_commit,
                "resolved_base": candidate_parent,
                "resolved_head": candidate_commit,
                "exact_range": f"{candidate_parent}..{candidate_commit}",
            },
            "execution": {"provider": "dashscope-tokenplan", "model": "qwen3.8-max"},
            "coverage": {
                "selected": [{"item_id": "item-1", "path": "src/example.py", "fingerprint": "f" * 64}],
                "completed": [{"item_id": "item-1", "path": "src/example.py", "fingerprint": "f" * 64}],
                "reused": [],
                "failed": [],
                "waived": [],
            },
        },
    }
    raw_review_path = write_json(tmp_path / "native" / "review-1" / "ocrv-review.json", raw_review)
    result = {
        "schema_version": "slk.ocrv-d1-result/v1",
        "run_id": run_id,
        "cell_id": cell_id,
        "review_invocation_id": "review-1",
        "verdict": "FAIL",
        "reason_codes": ["OCR_BLOCKING_FINDINGS_PRESENT"],
        "findings": [{"severity": "medium", "content": "preserved finding"}],
        "review": {
            "status": "complete",
            "provider": "dashscope-tokenplan",
            "model": "qwen3.8-max",
            "session_id": "ocrv-session-1",
            "exit_code": 0,
        },
        "evidence": [],
        "request_sha256": sha256(ocrv_request_path),
        "artifacts": {"raw_review": str(raw_review_path.resolve())},
    }
    result_path = write_json(native_attempt / "ocrv-result.json", result)
    terminal_path = write_json(
        native_attempt / "completed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": message_id,
            "run_id": run_id,
            "adapter": "ocrv-checker",
            "status": "completed",
            "native_identity": {
                "run_id": run_id,
                "cell_id": cell_id,
                "review_invocation_id": "review-1",
                "session_id": "ocrv-session-1",
                "provider": "dashscope-tokenplan",
                "model": "qwen3.8-max",
                "verdict": "FAIL",
                "exit_code": 2,
                "review_segment_count": 0,
            },
            "error_code": None,
            "evidence": ["started.json", "ocrv-request.json", "ocrv-result.json"],
        },
    )
    commit_request = {
        "event_id": transport_event_id,
        "transport_receipt_id": receipt_id,
        "run_id": run_id,
        "go_id": go_id,
        "cell_id": cell_id,
        "attempt": attempt,
        "plan_revision": 2,
        "expected_runtime_revision": 152,
        "message_id": message_id,
        "token_sequence": 31,
        "from_role_instance_id": worker_id,
        "to_role_instance_id": checker_id,
        "endpoint_version": 2,
        "payload_type": "CANDIDATE_READY",
        "payload_sha256": envelope["payload_sha256"],
        "start_evidence": {
            "evidence_id": "55555555-5555-4555-8555-555555555555",
            "stored_path": str(started_path.resolve()),
            "sha256": sha256(started_path),
            "message_id": message_id,
            "endpoint_sha256": sha256(endpoint_path),
            "envelope_sha256": sha256(envelope_path),
            "native_status": "STARTED",
        },
        "occurred_at": "2026-10-01T23:09:41Z",
    }
    commit_path = write_json(tmp_path / "commit-delivery-start.json", commit_request)
    candidate_details = {
        "candidate": {"kind": "commit", "commit": candidate_commit},
        "checker_endpoint_version": 2,
        "handoff_message_id": message_id,
        "source_message_id": "source-message-1",
    }
    transport_details = {
        "endpoint_sha256": sha256(endpoint_path),
        "envelope_sha256": sha256(envelope_path),
        "message_id": message_id,
        "start_evidence_id": commit_request["start_evidence"]["evidence_id"],
        "start_evidence_sha256": sha256(started_path),
        "transport_receipt_id": receipt_id,
    }
    projection = {
        "schema_version": "slk.bi.run/v1",
        "run_id": run_id,
        "summary": {
            "run_id": run_id,
            "slk_version": "4.4.0",
            "current_plan_revision": 2,
            "state": "active",
            "closure_state": "open",
        },
        "administrative_snapshot": {
            "run_id": run_id,
            "state": "active",
            "closure_state": "open",
            "latest_event_id": transport_event_id,
        },
        "runtime_snapshot": {
            "run_id": run_id,
            "method_version": "4.4.0",
            "plan_revision": 2,
            "runtime_revision": 155,
            "token_sequence": 31,
            "token_holder_role_instance_id": checker_id,
            "latest_event_id": transport_event_id,
            "latest_message_id": message_id,
            "overwatcher_binding_revision": 1,
            "overwatcher_status": "ACTIVE",
            "committed_at": "2026-10-01T23:09:41Z",
        },
        "roles": [
            {
                "role": "worker",
                "role_instance_id": worker_id,
                "agent_runtime": "dsh",
                "lifecycle": "active",
                "endpoints": [],
            },
            {
                "role": "checker",
                "role_instance_id": checker_id,
                "agent_runtime": "ocrv",
                "lifecycle": "active",
                "endpoints": [
                    {
                        "endpoint_version": 2,
                        "transport_adapter": "ocrv-checker",
                        "state": "active",
                        "retired_at": None,
                    }
                ],
            },
            {
                "role": "overwatcher",
                "role_instance_id": overwatcher_id,
                "agent_runtime": "codex",
                "lifecycle": "active",
                "session_id": "overwatcher-session-1",
                "endpoints": [],
            },
        ],
        "events": [
            {
                "event_id": candidate_event_id,
                "event_type": "CANDIDATE_SUBMITTED",
                "author_role_instance_id": worker_id,
                "go_id": go_id,
                "cell_id": cell_id,
                "attempt": attempt,
                "details_json": json.dumps(candidate_details, sort_keys=True),
            },
            {
                "event_id": transport_event_id,
                "event_type": "TRANSPORT_STARTED",
                "author_role_instance_id": worker_id,
                "go_id": go_id,
                "cell_id": cell_id,
                "attempt": attempt,
                "details_json": json.dumps(transport_details, sort_keys=True),
            },
            {
                "event_id": "later-overwatch-cycle",
                "event_type": "OVERWATCH_CYCLE_RECORDED",
                "author_role_instance_id": "RUN-A-overwatcher-001",
                "go_id": go_id,
                "cell_id": cell_id,
                "attempt": attempt,
                "details_json": "{}",
            },
        ],
        "token_history": [
            {
                "event_type": "TOKEN_HANDED_OFF",
                "from_role_instance_id": worker_id,
                "to_role_instance_id": checker_id,
                "go_id": go_id,
                "cell_id": cell_id,
                "message_id": message_id,
                "token_sequence": 31,
            }
        ],
        "overwatch_cycles": [],
        "overwatcher_native_status_receipts": [],
        "overwatcher_incident_transitions": [],
        "overwatcher_binding_transitions": [],
        "operational_observations": [
            {
                "observation_id": "overwatcher-existing-observation",
                "overwatcher_role_instance_id": overwatcher_id,
                "go_id": go_id,
                "cell_id": cell_id,
                "attempt": attempt,
                "plan_revision": 2,
                "kind": "ACTIVITY_UNPROVEN",
                "related_event_id": transport_event_id,
                "message_id": message_id,
                "evidence_refs_json": "[]",
                "details_json": '"existing observation"',
                "occurred_at": "2026-10-01T23:13:41Z",
            }
        ],
    }
    projection_path = write_json(tmp_path / "runtime-projection.json", projection)
    checker_credential_path = tmp_path / "checker.dpapi"
    checker_credential_path.write_text("sealed", encoding="ascii")
    state_command_path = tmp_path / "slk-state.exe"
    transport_command_path = tmp_path / "slk-transport.pyz"
    state_command_path.write_bytes(b"state")
    transport_command_path.write_bytes(b"transport")
    request = {
        "schema_version": "slk.ocrv-committed-terminal-request/v1",
        "method_version": "4.4.0",
        "recovery_invocation_id": "66666666-6666-4666-8666-666666666666",
        "run_id": run_id,
        "go_id": go_id,
        "cell_id": cell_id,
        "attempt": attempt,
        "plan_revision": 2,
        "runtime_revision": 155,
        "token_sequence": 31,
        "worker_role_instance_id": worker_id,
        "checker_role_instance_id": checker_id,
        "checker_endpoint_version": 2,
        "checker_endpoint": checker,
        "runtime_projection_path": str(projection_path.resolve()),
        "runtime_projection_sha256": sha256(projection_path),
        "candidate_repository": str(repository.resolve()),
        "candidate_commit": candidate_commit,
        "candidate_parent": candidate_parent,
        "candidate_message_id": message_id,
        "payload_sha256": envelope["payload_sha256"],
        "candidate_submitted_event_id": candidate_event_id,
        "transport_started_event_id": transport_event_id,
        "commit_request_path": str(commit_path.resolve()),
        "commit_request_sha256": sha256(commit_path),
        "native_attempt_path": str(native_attempt.resolve()),
        "raw_review_path": str(raw_review_path.resolve()),
        "immutable_sha256": {
            "endpoint.json": sha256(endpoint_path),
            "envelope.json": sha256(envelope_path),
            "started.json": sha256(started_path),
            "ocrv-request.json": sha256(ocrv_request_path),
            "completed.json": sha256(terminal_path),
            "ocrv-result.json": sha256(result_path),
            "raw_review": sha256(raw_review_path),
        },
        "checker_credential_path": str(checker_credential_path),
        "state_command": [str(state_command_path.resolve())],
        "transport_command": [os.fspath(Path(os.sys.executable).resolve()), str(transport_command_path.resolve())],
        "result_path": str(tmp_path / "committed-terminal-result.json"),
    }
    request_path = write_json(tmp_path / "request.json", request)
    return request, request_path


def test_outer_consumer_validates_chain_then_starts_only_the_sealed_checker_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, request_path = fixture(tmp_path)
    request_sha256 = sha256(request_path)
    monkeypatch.setenv("SLK_ROLE_CREDENTIAL", "must-not-leak")
    monkeypatch.setenv("SLK_OVERWATCHER_CREDENTIAL", "must-not-leak")
    captured: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        value = {
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
            "request_sha256": request_sha256,
            "runtime_revision": request["runtime_revision"],
            "token_sequence": request["token_sequence"],
            "native_attempt_path": request["native_attempt_path"],
            "d1_verdict": "FAIL",
            "d1_event_type": "D1_FAILED",
            "native_result_path": str(Path(str(request["native_attempt_path"])) / "ocrv-result.json"),
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(value).encode(), b"")

    monkeypatch.setattr(worker_completion.subprocess, "run", run)
    result = worker_completion.consume_committed_checker_terminal(
        request_path, request_sha256=request_sha256
    )

    assert result["d1_verdict"] == "FAIL"
    assert "--slk-committed-terminal" in captured["command"]
    assert "--slk-worker-recovery" not in captured["command"]
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert "SLK_ROLE_CREDENTIAL" not in environment
    assert "SLK_OVERWATCHER_CREDENTIAL" not in environment


def test_checker_host_authenticates_current_revision_and_reuses_existing_d1_recorder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, request_path = fixture(tmp_path)
    request_sha256 = sha256(request_path)
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(request["checker_role_instance_id"])
    )
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"])
    )
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(request["checker_endpoint_version"])
    )
    calls: list[str] = []

    result = worker_completion.execute_committed_checker_terminal(
        request,
        request_sha256=request_sha256,
        authenticate_checker=lambda *_args: calls.append("authenticate")
        or {
            "status": "authenticated",
            "role": "checker",
            "role_instance_id": request["checker_role_instance_id"],
            "runtime_revision": 155,
        },
        record_checker_d1=lambda activation, continuation, credential, timeout: calls.append(
            "record"
        )
        or {
            "status": "CHECKER_D1_RECORDED",
            "d1_verdict": "FAIL",
            "d1_event_type": "D1_FAILED",
            "native_result_path": str(Path(str(request["native_attempt_path"])) / "ocrv-result.json"),
        },
    )

    assert calls == ["authenticate", "record"]
    assert result["d1_verdict"] == "FAIL"
    assert result["runtime_revision"] == 155


def test_recovered_terminal_reuses_the_existing_committed_validator_and_d1_recorder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, request_path = fixture(tmp_path)
    source = Path(str(request["native_attempt_path"]))
    recovery = source / "resume-incomplete-checker" / str(request["recovery_invocation_id"]) / "native-attempt"
    recovery.mkdir(parents=True)
    for source_name, target_name in (
        ("started.json", "started.json"), ("completed.json", "completed.json"),
        ("ocrv-result.json", "ocrv-result.json"), ("ocrv-request.json", "ocrv-resume-request.json"),
    ):
        (recovery / target_name).write_bytes((source / source_name).read_bytes())
    terminal = json.loads((recovery / "completed.json").read_text(encoding="utf-8"))
    terminal["evidence"] = ["started.json", "ocrv-resume-request.json", "ocrv-result.json"]
    terminal["native_identity"]["review_invocation_id"] = "review-fresh"
    terminal["native_identity"]["session_id"] = "ocrv-session-fresh"
    write_json(recovery / "completed.json", terminal)
    started = json.loads((recovery / "started.json").read_text(encoding="utf-8"))
    started["native_task"]["id"] = "review-fresh"
    write_json(recovery / "started.json", started)
    recovered_result = json.loads((recovery / "ocrv-result.json").read_text(encoding="utf-8"))
    recovered_result["review_invocation_id"] = "review-fresh"
    recovered_result["review"]["session_id"] = "ocrv-session-fresh"
    write_json(recovery / "ocrv-result.json", recovered_result)
    raw = Path(str(request["raw_review_path"]))
    raw_review = json.loads(raw.read_text(encoding="utf-8"))
    raw_review["session_id"] = "ocrv-session-fresh"
    raw_review["manifest"]["run_id"] = "ocrv-session-fresh"
    write_json(raw, raw_review)
    request["immutable_sha256"] = {
        name: sha256(source / name) for name in (
            "endpoint.json", "envelope.json", "started.json", "ocrv-request.json",
        )
    }
    request["recovery_terminal"] = {
        "native_attempt_path": str(recovery), "started_sha256": sha256(recovery / "started.json"),
        "completed_sha256": sha256(recovery / "completed.json"),
        "ocrv_result_sha256": sha256(recovery / "ocrv-result.json"),
        "resume_request_sha256": sha256(recovery / "ocrv-resume-request.json"),
        "raw_review_sha256": sha256(raw),
    }
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(request["checker_role_instance_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(request["checker_endpoint_version"]))
    result = worker_completion.execute_committed_checker_terminal(
        request, request_sha256=sha256(request_path),
        authenticate_checker=lambda *_args: {"status": "authenticated", "role": "checker",
            "role_instance_id": request["checker_role_instance_id"], "runtime_revision": request["runtime_revision"]},
        record_checker_d1=lambda activation, *_args: {"status": "CHECKER_D1_RECORDED",
            "d1_verdict": "FAIL", "d1_event_type": "D1_FAILED",
            "native_result_path": str(Path(str(activation["native_attempt_path"])) / "ocrv-result.json")},
    )

    assert Path(str(result["native_attempt_path"])) == recovery
    assert terminal["native_identity"]["review_invocation_id"] == "review-fresh"
    assert terminal["native_identity"]["session_id"] == "ocrv-session-fresh"


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        (
            "missing-start",
            lambda request: (Path(str(request["native_attempt_path"])) / "started.json").unlink(),
        ),
        (
            "wrong-candidate",
            lambda request: request.__setitem__("candidate_commit", "c" * 40),
        ),
        (
            "mixed-revision",
            lambda request: request.__setitem__("runtime_revision", 156),
        ),
        (
            "wrong-checker",
            lambda request: request.__setitem__("checker_role_instance_id", "RUN-A-checker-other"),
        ),
        (
            "commit-drift",
            lambda request: Path(str(request["commit_request_path"])).write_text("{}", encoding="utf-8"),
        ),
        (
            "command-drift",
            lambda request: request.__setitem__("state_command", ["malicious.exe"]),
        ),
        (
            "missing-coverage",
            lambda request: _remove_review_coverage(Path(str(request["raw_review_path"]))),
        ),
        (
            "already-advanced",
            lambda request: _append_d1_event(Path(str(request["runtime_projection_path"]))),
        ),
        ("non-checker-token", lambda request: _move_token_to_worker(request)),
    ],
)
def test_closed_chain_rejects_missing_tampered_advanced_or_mixed_evidence_before_host_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    mutate: object,
) -> None:
    request, request_path = fixture(tmp_path)
    mutate(request)  # type: ignore[operator]
    write_json(request_path, request)
    monkeypatch.setattr(
        worker_completion.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail(f"{name} must fail before Checker host start"),
    )

    with pytest.raises(CompletionError):
        worker_completion.consume_committed_checker_terminal(
            request_path, request_sha256=sha256(request_path)
        )


def _remove_review_coverage(path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    value["manifest"]["coverage"]["completed"] = []
    write_json(path, value)


def _append_d1_event(path: Path) -> None:
    value = json.loads(path.read_text(encoding="utf-8"))
    value["events"].append(
        {
            "event_id": "later-d1",
            "event_type": "D1_FAILED",
            "author_role_instance_id": "RUN-A-checker-001",
            "go_id": "GO-001",
            "cell_id": "CELL-001",
            "attempt": 10,
            "details_json": "{}",
        }
    )
    value["administrative_snapshot"]["latest_event_id"] = "later-d1"
    write_json(path, value)


def _move_token_to_worker(request: dict[str, object]) -> None:
    path = Path(str(request["runtime_projection_path"]))
    value = json.loads(path.read_text(encoding="utf-8"))
    value["runtime_snapshot"]["token_holder_role_instance_id"] = request["worker_role_instance_id"]
    write_json(path, value)
    request["runtime_projection_sha256"] = sha256(path)


def test_duplicate_consume_is_rejected_when_checker_revision_has_advanced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, request_path = fixture(tmp_path)
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(request["checker_role_instance_id"])
    )
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"])
    )
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(request["checker_endpoint_version"])
    )

    with pytest.raises(CompletionError) as rejected:
        worker_completion.execute_committed_checker_terminal(
            request,
            request_sha256=sha256(request_path),
            authenticate_checker=lambda *_args: {
                "status": "authenticated",
                "role": "checker",
                "role_instance_id": request["checker_role_instance_id"],
                "runtime_revision": 157,
            },
            record_checker_d1=lambda *_args: pytest.fail("duplicate must not record D1"),
        )

    assert rejected.value.error_code == "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED"


def _set_committed_terminal_identity(
    monkeypatch: pytest.MonkeyPatch, request: dict[str, object]
) -> None:
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(request["checker_role_instance_id"])
    )
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"])
    )
    monkeypatch.setenv(
        "SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(request["checker_endpoint_version"])
    )


def _current_projection_after_overwatcher_pause(request: dict[str, object]) -> dict[str, object]:
    frozen = json.loads(
        Path(str(request["runtime_projection_path"])).read_text(encoding="utf-8")
    )
    status_id = "overwatcher-native-paused-after-terminal"
    overwatcher_id = "RUN-A-overwatcher-001"
    frozen["runtime_snapshot"].update(
        {
            "runtime_revision": int(request["runtime_revision"]) + 1,
            "latest_event_id": status_id,
            "overwatcher_status": "VIOLATION",
            "committed_at": "2026-10-01T23:11:41Z",
        }
    )
    frozen["overwatcher_native_status_receipts"].append(
        {
            "status_id": status_id,
            "binding_revision": 1,
            "role_instance_id": overwatcher_id,
            "session_id": "overwatcher-session-1",
            "foreground_turn_id": "overwatcher-turn-2",
            "native_liveness": "COMPLETED",
            "evidence_path": "D:/evidence/overwatcher-paused.json",
            "evidence_sha256": "d" * 64,
            "observed_at": "2026-10-01T23:11:41Z",
        }
    )
    frozen["overwatcher_incident_transitions"].append(
        {
            "transition_id": f"incident-open-{status_id}",
            "incident_id": f"continuity-RUN-A-1-{status_id}",
            "binding_revision": 1,
            "incident_code": "OVERWATCHER_CONTINUITY_VIOLATION",
            "state": "OPEN",
            "evidence_path": "D:/evidence/overwatcher-paused.json",
            "evidence_sha256": "d" * 64,
            "occurred_at": "2026-10-01T23:11:41Z",
        }
    )
    frozen["operational_observations"].insert(
        0,
        {
            "observation_id": "overwatcher-correction-after-terminal",
            "overwatcher_role_instance_id": overwatcher_id,
            "go_id": request["go_id"],
            "cell_id": request["cell_id"],
            "attempt": request["attempt"],
            "plan_revision": request["plan_revision"],
            "kind": "RECORD_CONFLICT",
            "related_event_id": request["transport_started_event_id"],
            "message_id": request["candidate_message_id"],
            "evidence_refs_json": "[]",
            "details_json": '"correction only"',
            "occurred_at": "2026-10-01T23:12:41Z",
        },
    )
    return frozen


def _two_revision_overwatcher_resume_and_status(
    request: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    frozen = json.loads(
        Path(str(request["runtime_projection_path"])).read_text(encoding="utf-8")
    )
    watcher = next(row for row in frozen["roles"] if row["role"] == "overwatcher")
    supervisor = {
        "role": "supervisor", "role_instance_id": "RUN-A-supervisor-001",
        "agent_runtime": "codex", "lifecycle": "active", "session_id": "supervisor-session-1",
        "endpoints": [],
    }
    frozen["roles"].append(supervisor)
    old_status_id = "overwatcher-paused-old"
    old_time = "2026-10-02T17:20:00Z"
    old_evidence = {"path": "D:/evidence/old-paused.json", "sha256": "a" * 64}
    frozen["runtime_snapshot"].update(
        {"latest_event_id": old_status_id, "overwatcher_status": "VIOLATION", "committed_at": old_time}
    )
    frozen["administrative_snapshot"]["event_count"] = len(frozen["events"])
    frozen["overwatcher_native_status_receipts"].append(
        {"status_id": old_status_id, "binding_revision": 1,
         "role_instance_id": watcher["role_instance_id"], "session_id": watcher["session_id"],
         "foreground_turn_id": "ow-turn-old", "native_liveness": "COMPLETED",
         "evidence_path": old_evidence["path"], "evidence_sha256": old_evidence["sha256"],
         "observed_at": old_time}
    )
    old_incident_id = f"continuity-{request['run_id']}-1-{old_status_id}"
    frozen["overwatcher_incident_transitions"].append(
        {"transition_id": f"incident-open-{old_status_id}", "incident_id": old_incident_id,
         "binding_revision": 1, "incident_code": "OVERWATCHER_CONTINUITY_VIOLATION",
         "state": "OPEN", "evidence_path": old_evidence["path"],
         "evidence_sha256": old_evidence["sha256"], "occurred_at": old_time}
    )
    current = copy.deepcopy(frozen)
    resume_id = "resume-overwatcher-after-maintenance"
    resume_time = "2026-10-02T17:29:50Z"
    status_id = "overwatcher-completed-new"
    status_time = "2026-10-02T17:30:12Z"
    resume_evidence = {"path": "D:/evidence/native-active.json", "sha256": "b" * 64}
    status_evidence = {"path": "D:/evidence/completed.json", "sha256": "c" * 64}
    current["events"].append(
        {"event_id": resume_id, "event_type": "OVERWATCHER_TURN_RESUMED",
         "author_role_instance_id": supervisor["role_instance_id"], "go_id": None, "cell_id": None,
         "attempt": None, "corrects_event_id": None, "occurred_at": resume_time,
         "details_json": json.dumps({"binding_revision": 1, "foreground_turn_id": "ow-turn-new",
             "last_anomaly_cycle_id": None, "last_native_status_id": old_status_id,
             "native_active_session_evidence": resume_evidence,
             "previous_foreground_turn_id": "ow-turn-old", "reason": "resume exact OW",
             "resume_basis": "NATIVE_STATUS", "role_instance_id": watcher["role_instance_id"],
             "session_id": watcher["session_id"]}, sort_keys=True)}
    )
    current["administrative_snapshot"].update(
        {"event_count": frozen["administrative_snapshot"]["event_count"] + 1,
         "latest_event_id": resume_id}
    )
    current["runtime_snapshot"].update(
        {"runtime_revision": int(frozen["runtime_snapshot"]["runtime_revision"]) + 2,
         "latest_event_id": status_id, "overwatcher_status": "VIOLATION", "committed_at": status_time}
    )
    current["overwatcher_native_status_receipts"].append(
        {"status_id": status_id, "binding_revision": 1,
         "role_instance_id": watcher["role_instance_id"], "session_id": watcher["session_id"],
         "foreground_turn_id": "ow-turn-new", "native_liveness": "COMPLETED",
         "evidence_path": status_evidence["path"], "evidence_sha256": status_evidence["sha256"],
         "observed_at": status_time}
    )
    current["overwatcher_incident_transitions"].extend([
        {"transition_id": f"incident-resolved-{resume_id}", "incident_id": old_incident_id,
         "binding_revision": 1, "incident_code": "OVERWATCHER_CONTINUITY_VIOLATION",
         "state": "RESOLVED", "evidence_path": resume_evidence["path"],
         "evidence_sha256": resume_evidence["sha256"], "occurred_at": resume_time},
        {"transition_id": f"incident-open-{status_id}",
         "incident_id": f"continuity-{request['run_id']}-1-{status_id}",
         "binding_revision": 1, "incident_code": "OVERWATCHER_CONTINUITY_VIOLATION",
         "state": "OPEN", "evidence_path": status_evidence["path"],
         "evidence_sha256": status_evidence["sha256"], "occurred_at": status_time},
    ])
    for ordinal in (1, 2):
        current["operational_observations"].append(
            {"observation_id": f"ow-recovery-{ordinal}",
             "overwatcher_role_instance_id": watcher["role_instance_id"], "go_id": request["go_id"],
             "cell_id": request["cell_id"], "attempt": request["attempt"],
             "plan_revision": request["plan_revision"], "kind": "RECOVERY_ESCALATED",
             "related_event_id": resume_id if ordinal == 1 else status_id,
             "message_id": request["candidate_message_id"], "evidence_refs_json": "[]",
             "details_json": f'"observation {ordinal}"', "occurred_at": status_time}
        )
    return frozen, current


def _append_overwatcher_resume_cycle_status(
    request: dict[str, object], current: dict[str, object]
) -> dict[str, object]:
    advanced = copy.deepcopy(current)
    watcher = next(row for row in advanced["roles"] if row["role"] == "overwatcher")
    supervisor = next(row for row in advanced["roles"] if row["role"] == "supervisor")
    prior_status = advanced["overwatcher_native_status_receipts"][-1]
    resume_id = "resume-overwatcher-after-paid-review"
    resume_time = "2026-10-02T18:00:00Z"
    status_id = "overwatcher-completed-after-paid-review"
    status_time = "2026-10-02T18:05:00Z"
    resume_evidence = {"path": "D:/evidence/native-active-2.json", "sha256": "e" * 64}
    status_evidence = {"path": "D:/evidence/completed-2.json", "sha256": "f" * 64}
    previous_revision = advanced["runtime_snapshot"]["runtime_revision"]
    advanced["events"].append(
        {"event_id": resume_id, "event_type": "OVERWATCHER_TURN_RESUMED",
         "author_role_instance_id": supervisor["role_instance_id"], "go_id": None,
         "cell_id": None, "attempt": None, "corrects_event_id": None,
         "occurred_at": resume_time,
         "details_json": json.dumps({"binding_revision": 1,
             "foreground_turn_id": "ow-turn-after-paid-review",
             "last_anomaly_cycle_id": None, "last_native_status_id": prior_status["status_id"],
             "native_active_session_evidence": resume_evidence,
             "previous_foreground_turn_id": prior_status["foreground_turn_id"],
             "reason": "resume the same Overwatcher during the paid review",
             "resume_basis": "NATIVE_STATUS", "role_instance_id": watcher["role_instance_id"],
             "session_id": watcher["session_id"]}, sort_keys=True)}
    )
    advanced["administrative_snapshot"].update(
        {"event_count": advanced["administrative_snapshot"]["event_count"] + 1,
         "latest_event_id": resume_id}
    )
    advanced["overwatcher_incident_transitions"].append(
        {"transition_id": f"incident-resolved-{resume_id}",
         "incident_id": f"continuity-{request['run_id']}-1-{prior_status['status_id']}",
         "binding_revision": 1, "incident_code": "OVERWATCHER_CONTINUITY_VIOLATION",
         "state": "RESOLVED", "evidence_path": resume_evidence["path"],
         "evidence_sha256": resume_evidence["sha256"], "occurred_at": resume_time}
    )
    advanced["overwatch_cycles"].append(
        {"cycle_id": "cycle-after-paid-review", "overwatcher_role_instance_id": watcher["role_instance_id"],
         "session_id": watcher["session_id"], "foreground_turn_id": "ow-turn-after-paid-review",
         "cycle_sequence": 1, "cadence_seconds": 240, "plan_revision": request["plan_revision"],
         "go_id": request["go_id"], "cell_id": request["cell_id"], "attempt": request["attempt"],
         "token_sequence": request["token_sequence"],
         "token_holder_role_instance_id": request["checker_role_instance_id"],
         "latest_event_id": resume_id, "latest_message_id": request["candidate_message_id"],
         "checklist_json": "[]", "anomaly_codes_json": "[]",
         "evidence_refs_json": json.dumps([resume_evidence], sort_keys=True),
         "native_active_session_evidence_ref": resume_evidence["path"],
         "started_at": "2026-10-02T18:00:01Z", "completed_at": "2026-10-02T18:00:02Z",
         "next_cycle_at": "2026-10-02T18:04:02Z", "binding_revision": 1,
         "runtime_revision": previous_revision + 1, "native_liveness": "IN_PROGRESS",
         "cadence_health": "ON_TIME", "cost_metrics_json": None}
    )
    advanced["overwatcher_native_status_receipts"].append(
        {"status_id": status_id, "binding_revision": 1,
         "role_instance_id": watcher["role_instance_id"], "session_id": watcher["session_id"],
         "foreground_turn_id": "ow-turn-after-paid-review", "native_liveness": "COMPLETED",
         "evidence_path": status_evidence["path"], "evidence_sha256": status_evidence["sha256"],
         "observed_at": status_time}
    )
    advanced["overwatcher_incident_transitions"].append(
        {"transition_id": f"incident-open-{status_id}",
         "incident_id": f"continuity-{request['run_id']}-1-{status_id}",
         "binding_revision": 1, "incident_code": "OVERWATCHER_CONTINUITY_VIOLATION",
         "state": "OPEN", "evidence_path": status_evidence["path"],
         "evidence_sha256": status_evidence["sha256"], "occurred_at": status_time}
    )
    advanced["runtime_snapshot"].update(
        {"runtime_revision": previous_revision + 2, "latest_event_id": status_id,
         "overwatcher_status": "VIOLATION", "committed_at": status_time}
    )
    return advanced


def test_rebind_accepts_exact_two_revision_supervisor_resume_then_overwatcher_status(tmp_path: Path) -> None:
    request, _ = fixture(tmp_path)
    frozen, current = _two_revision_overwatcher_resume_and_status(request)
    assert worker_completion._rebind_overwatcher_only_committed_boundary(
        request, frozen, current, int(request["runtime_revision"]) + 2
    ) == int(request["runtime_revision"]) + 2


def test_rebind_accepts_repeated_authenticated_overwatcher_resume_cycle_status(
    tmp_path: Path,
) -> None:
    request, _ = fixture(tmp_path)
    frozen, current = _two_revision_overwatcher_resume_and_status(request)
    current = _append_overwatcher_resume_cycle_status(request, current)

    assert worker_completion._rebind_overwatcher_only_committed_boundary(
        request, frozen, current, int(request["runtime_revision"]) + 4
    ) == int(request["runtime_revision"]) + 4


def test_committed_terminal_rebinds_from_original_boundary_after_repeated_ow_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, request_path = fixture(tmp_path)
    frozen, current = _two_revision_overwatcher_resume_and_status(request)
    current = _append_overwatcher_resume_cycle_status(request, current)
    projection_path = write_json(Path(str(request["runtime_projection_path"])), frozen)
    request["runtime_projection_sha256"] = sha256(projection_path)
    write_json(request_path, request)
    _set_committed_terminal_identity(monkeypatch, request)
    captured: dict[str, object] = {}

    result = worker_completion.execute_committed_checker_terminal(
        request,
        request_sha256=sha256(request_path),
        authenticate_checker=lambda *_args: {
            "status": "authenticated", "role": "checker",
            "role_instance_id": request["checker_role_instance_id"],
            "runtime_revision": int(request["runtime_revision"]) + 4,
        },
        load_current_projection=lambda *_args: current,
        record_checker_d1=lambda activation, *_args: captured.update(activation) or {
            "status": "CHECKER_D1_RECORDED", "d1_verdict": "FAIL",
            "d1_event_type": "D1_FAILED",
            "native_result_path": str(Path(str(request["native_attempt_path"])) / "ocrv-result.json"),
        },
    )

    assert captured["runtime_revision"] == int(request["runtime_revision"]) + 4
    assert result["runtime_revision"] == int(request["runtime_revision"]) + 4


@pytest.mark.parametrize(
    "drift", ["revision", "token", "role", "candidate", "business-event", "plan", "incident"]
)
def test_two_revision_overwatcher_rebind_rejects_engineering_or_identity_drift(
    tmp_path: Path, drift: str
) -> None:
    request, _ = fixture(tmp_path)
    frozen, current = _two_revision_overwatcher_resume_and_status(request)
    authenticated = int(request["runtime_revision"]) + 2
    if drift == "revision": authenticated += 1
    elif drift == "token": current["runtime_snapshot"]["token_sequence"] += 1
    elif drift == "role": current["roles"][0]["lifecycle"] = "exited"
    elif drift == "candidate": current["events"][0]["details_json"] = "{}"
    elif drift == "business-event": current["events"].append(
        {"event_id": "business", "event_type": "D1_FAILED", "author_role_instance_id": request["checker_role_instance_id"]}
    )
    elif drift == "plan": current["summary"]["current_plan_revision"] = 3
    else: current["overwatcher_incident_transitions"][-1]["transition_id"] = "unrelated-incident"
    with pytest.raises(CompletionError):
        worker_completion._rebind_overwatcher_only_committed_boundary(
            request, frozen, current, authenticated
        )


def test_checker_host_rebinds_one_authenticated_overwatcher_only_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, request_path = fixture(tmp_path)
    _set_committed_terminal_identity(monkeypatch, request)
    current = _current_projection_after_overwatcher_pause(request)
    captured: dict[str, object] = {}

    result = worker_completion.execute_committed_checker_terminal(
        request,
        request_sha256=sha256(request_path),
        authenticate_checker=lambda *_args: {
            "status": "authenticated",
            "role": "checker",
            "role_instance_id": request["checker_role_instance_id"],
            "runtime_revision": 156,
        },
        load_current_projection=lambda *_args: current,
        record_checker_d1=lambda activation, *_args: captured.update(activation)
        or {
            "status": "CHECKER_D1_RECORDED",
            "d1_verdict": "FAIL",
            "d1_event_type": "D1_FAILED",
            "native_result_path": str(
                Path(str(request["native_attempt_path"])) / "ocrv-result.json"
            ),
        },
    )

    assert captured["runtime_revision"] == 156
    assert result["runtime_revision"] == 156


@pytest.mark.parametrize(
    ("name", "mutate"),
    [
        (
            "d1",
            lambda current, request: current["events"].append(
                {
                    "event_id": "later-d1",
                    "event_type": "D1_FAILED",
                    "author_role_instance_id": request["checker_role_instance_id"],
                    "go_id": request["go_id"],
                    "cell_id": request["cell_id"],
                    "attempt": request["attempt"],
                    "details_json": "{}",
                }
            ),
        ),
        (
            "token",
            lambda current, request: current["runtime_snapshot"].update(
                {"token_sequence": int(request["token_sequence"]) + 1}
            ),
        ),
        (
            "business-event",
            lambda current, request: current["events"].append(
                {
                    "event_id": "later-business-event",
                    "event_type": "WORK_PROGRESS",
                    "author_role_instance_id": request["worker_role_instance_id"],
                    "go_id": request["go_id"],
                    "cell_id": request["cell_id"],
                    "attempt": request["attempt"],
                    "details_json": "{}",
                }
            ),
        ),
        (
            "unknown-drift",
            lambda current, _request: current["runtime_snapshot"].update(
                {"latest_event_id": "unknown-runtime-event"}
            ),
        ),
        (
            "plan",
            lambda current, _request: current["summary"].update(
                {"current_plan_revision": 3}
            ),
        ),
        (
            "role",
            lambda current, _request: current["roles"][0].update(
                {"lifecycle": "exited"}
            ),
        ),
        (
            "message",
            lambda current, _request: current["runtime_snapshot"].update(
                {"latest_message_id": "different-message"}
            ),
        ),
        (
            "candidate",
            lambda current, _request: current["events"][0].update(
                {"details_json": "{}"}
            ),
        ),
    ],
)
def test_checker_host_rejects_non_overwatcher_or_authority_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    mutate: object,
) -> None:
    request, request_path = fixture(tmp_path)
    _set_committed_terminal_identity(monkeypatch, request)
    current = _current_projection_after_overwatcher_pause(request)
    mutate(current, request)  # type: ignore[operator]

    with pytest.raises(CompletionError) as rejected:
        worker_completion.execute_committed_checker_terminal(
            request,
            request_sha256=sha256(request_path),
            authenticate_checker=lambda *_args: {
                "status": "authenticated",
                "role": "checker",
                "role_instance_id": request["checker_role_instance_id"],
                "runtime_revision": 156,
            },
            load_current_projection=lambda *_args: current,
            record_checker_d1=lambda *_args: pytest.fail(f"{name} drift must not record D1"),
        )

    assert rejected.value.error_code == "CHECKER_COMMITTED_TERMINAL_ALREADY_ADVANCED"
