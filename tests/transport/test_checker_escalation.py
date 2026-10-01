from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
from pathlib import Path

import pytest

from slk_transport.contracts import canonical_json_sha256
from slk_transport.native_activity import make_native_start

from test_contracts import endpoint_value, envelope_value


RUN_ID = "RUN-A"
GO_ID = "GO-001"
CELL_ID = "CELL-001"
CHECKER_ID = "ROLE-checker"
SUPERVISOR_ID = "ROLE-supervisor"
FAILURE_EVENT_ID = "d1-failed-001"
CANDIDATE_COMMIT = "a" * 40
CANDIDATE_MESSAGE_ID = "11111111-1111-4111-8111-111111111111"
RECOVERY_MESSAGE_ID = "22222222-2222-4222-8222-222222222222"


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(tmp_path: Path) -> tuple[dict[str, object], Path]:
    native = tmp_path / "native-attempt"
    candidate_message_id = CANDIDATE_MESSAGE_ID
    candidate = {"kind": "commit", "commit": CANDIDATE_COMMIT}
    checker_endpoint = endpoint_value(role="checker", version=2)
    checker_endpoint["run_id"] = RUN_ID
    checker_endpoint["role_instance_id"] = CHECKER_ID
    checker_endpoint["address"] = {
        "command": ["D:/OCRV/slk-checker.cmd"],
        "runtime_root": str(tmp_path / "ocrv-runtime"),
        "timeout_seconds": 30,
    }
    envelope = envelope_value(
        sender_role="worker",
        receiver_role="checker",
        receiver_endpoint_version=2,
    )
    envelope.update(
        {
            "message_id": candidate_message_id,
            "run_id": RUN_ID,
            "go_id": GO_ID,
            "cell_id": CELL_ID,
            "sender_role_instance_id": "ROLE-worker",
            "receiver_role_instance_id": CHECKER_ID,
            "payload_type": "CANDIDATE_READY",
        }
    )
    envelope["payload"] = {
        "repository": str(tmp_path / "repository"),
        "candidate": candidate,
        "cell_goal": "Repair the current CELL.",
        "d1_criteria": ["The regression is corrected."],
        "evidence_files": [],
    }
    envelope["payload_sha256"] = canonical_json_sha256(envelope["payload"])
    write_json(native / "endpoint.json", checker_endpoint)
    write_json(native / "envelope.json", envelope)
    started = write_json(
        native / "started.json",
        make_native_start(
            adapter="ocrv-checker",
            run_id=RUN_ID,
            cell_id=CELL_ID,
            message_id=candidate_message_id,
            request_sha256=str(envelope["payload_sha256"]),
            native_request_sha256="b" * 64,
            native_task_kind="ocrv-review",
            native_task_id="review-1",
            native_task_status="RUNNING",
            pid=os.getpid(),
        ),
    )
    result = write_json(
        native / "ocrv-result.json",
        {
            "schema_version": "slk.ocrv-d1-result/v1",
            "run_id": RUN_ID,
            "cell_id": CELL_ID,
            "review_invocation_id": "review-1",
            "verdict": "FAIL",
            "reason_codes": ["OCR_FINDINGS_PRESENT"],
            "findings": [{"summary": "The candidate remains incorrect."}],
            "review": {
                "status": "complete",
                "provider": "dashscope-tokenplan",
                "model": "qwen3.8-max",
                "session_id": "review-session-1",
                "exit_code": 0,
            },
            "evidence": [],
            "request_sha256": "b" * 64,
            "artifacts": {},
        },
    )
    terminal = write_json(
        native / "completed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": candidate_message_id,
            "run_id": RUN_ID,
            "adapter": "ocrv-checker",
            "status": "completed",
            "native_identity": {
                "run_id": RUN_ID,
                "cell_id": CELL_ID,
                "review_invocation_id": "review-1",
                "session_id": "review-session-1",
                "provider": "dashscope-tokenplan",
                "model": "qwen3.8-max",
                "verdict": "FAIL",
                "exit_code": 2,
                "review_segment_count": 0,
            },
            "error_code": None,
            "evidence": ["started.json", "ocrv-result.json"],
        },
    )
    details = {
        "candidate_message_id": candidate_message_id,
        "verdict": "FAIL",
        "native_start_sha256": sha256(started),
        "native_terminal_path": str(terminal.resolve()),
        "native_terminal_sha256": sha256(terminal),
        "native_result_path": str(result.resolve()),
        "native_result_sha256": sha256(result),
        "native_aggregate_path": None,
        "native_aggregate_sha256": None,
        "review_invocation_id": "review-1",
        "session_id": "review-session-1",
        "reason_codes": ["OCR_FINDINGS_PRESENT"],
    }
    projection = write_json(
        tmp_path / "runtime.json",
        {
            "summary": {
                "run_id": RUN_ID,
                "slk_version": "4.3.6",
                "current_plan_revision": 1,
            },
            "runtime_snapshot": {
                "method_version": "4.3.6",
                "plan_revision": 1,
                "runtime_revision": 25,
                "token_sequence": 4,
                "token_holder_role_instance_id": CHECKER_ID,
                "latest_event_id": FAILURE_EVENT_ID,
                "latest_message_id": candidate_message_id,
            },
            "events": [
                {
                    "event_id": FAILURE_EVENT_ID,
                    "event_type": "D1_FAILED",
                    "author_role_instance_id": CHECKER_ID,
                    "go_id": GO_ID,
                    "cell_id": CELL_ID,
                    "attempt": 1,
                    "details_json": json.dumps(details, sort_keys=True),
                }
            ],
            "operational_observations": [],
        },
    )
    supervisor = endpoint_value(role="supervisor", version=1)
    supervisor.update({"run_id": RUN_ID, "role_instance_id": SUPERVISOR_ID})
    supervisor["address"] = {
        "command": ["codex", "app-server"],
        "thread_id": "thread-supervisor",
        "cwd": str(tmp_path),
        "startup_timeout_seconds": 1,
        "turn_timeout_seconds": 1,
    }
    supervisor_path = write_json(tmp_path / "supervisor-endpoint.json", supervisor)
    credential = tmp_path / "checker.dpapi"
    credential.write_text("00", encoding="ascii")
    attempt_root = tmp_path / "escalation-attempts"
    attempt_root.mkdir()
    request = {
        "schema_version": "slk.checker-post-d1-request/v1",
        "method_version": "4.3.6",
        "post_d1_invocation_id": "post-d1-001",
        "run_id": RUN_ID,
        "go_id": GO_ID,
        "cell_id": CELL_ID,
        "attempt": 1,
        "plan_revision": 1,
        "runtime_revision": 25,
        "token_sequence": 4,
        "checker_role_instance_id": CHECKER_ID,
        "d1_failure_event_id": FAILURE_EVENT_ID,
        "runtime_projection_path": str(projection.resolve()),
        "native_attempt_path": str(native.resolve()),
        "supervisor_endpoint_path": str(supervisor_path.resolve()),
        "checker_credential_path": str(credential.resolve()),
        "state_command": ["slk-state"],
        "transport_command": ["slk-transport"],
        "escalation_attempt_root": str(attempt_root.resolve()),
        "rework_round": 1,
        "cell_goal": "Repair the current CELL.",
        "acceptance_criteria": ["The regression is corrected."],
        "findings": ["The candidate remains incorrect."],
        "reproduction_steps": ["Run the focused regression."],
        "expected_result": "The focused regression passes.",
        "evidence_refs": [str(result.resolve())],
        "occurred_at": "2026-10-01T01:00:00Z",
    }
    request_path = write_json(tmp_path / "post-d1.json", request)
    return request, request_path


def load_module():
    return importlib.import_module("slk_transport.checker_escalation")


def request_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_prepare_binds_failure_and_stops_at_desktop_bridge(tmp_path: Path) -> None:
    module = load_module()
    request, request_path = fixture(tmp_path)
    calls: list[tuple[list[str], list[str], str | None]] = []

    def run(command: list[str], arguments: list[str], *, credential: str | None):
        calls.append((command, arguments, credential))
        operation = arguments[0]
        if operation == "authenticate-role":
            return {
                "status": "authenticated",
                "run_id": RUN_ID,
                "role": "checker",
                "role_instance_id": CHECKER_ID,
                "runtime_revision": 25,
            }
        if operation == "send":
            return {"status": "failed", "error_code": "CODEX_ACTIVE_WRITER_UNRESOLVED"}
        if operation == "retry-exact":
            return {
                "status": "SUPERVISOR_DECISION_REQUIRED",
                "reason": "EXACT_RETRY_EXHAUSTED",
                "result": {"error_code": "CODEX_ACTIVE_WRITER_UNRESOLVED"},
            }
        assert operation == "prepare-desktop-current-turn"
        return {
            "schema_version": "slk.transport-desktop-current-turn-request/v1",
            "status": "PREPARED",
            "run_id": RUN_ID,
            "go_id": GO_ID,
            "cell_id": CELL_ID,
            "original_message_id": module.escalation_message_id(request),
            "recovery_message_id": "desktop-recovery-1",
            "target_thread_id": "thread-supervisor",
            "payload_type": "D1_FAILURE_ESCALATION",
            "payload_sha256": module.escalation_payload_sha256(request),
            "prompt": "exact desktop bridge prompt",
            "prompt_sha256": "c" * 64,
        }

    result = module.execute_checker_escalation(
        request,
        request_sha256=request_digest(request_path),
        request_path=request_path,
        run_json_command=run,
        unprotect_credential=lambda _path: "slk_" + "d" * 64,
    )

    assert result["status"] == "DESKTOP_BRIDGE_REQUIRED"
    assert result["d1_failure_event_id"] == FAILURE_EVENT_ID
    assert result["failed_candidate"]["commit"] == CANDIDATE_COMMIT
    assert result["desktop_request"]["target_thread_id"] == "thread-supervisor"
    assert [arguments[0] for _, arguments, _ in calls] == [
        "authenticate-role",
        "send",
        "retry-exact",
        "prepare-desktop-current-turn",
    ]
    assert calls[0][2] == "slk_" + "d" * 64
    assert all(credential is None for _, _, credential in calls[1:])


def test_complete_commits_only_the_proven_desktop_start(tmp_path: Path) -> None:
    module = load_module()
    request, request_path = fixture(tmp_path)
    prepared = module.materialize_escalation(request)
    desktop_request = {
        "schema_version": "slk.transport-desktop-current-turn-request/v1",
        "status": "PREPARED",
        "run_id": RUN_ID,
        "go_id": GO_ID,
        "cell_id": CELL_ID,
        "original_message_id": prepared["envelope"]["message_id"],
        "recovery_message_id": RECOVERY_MESSAGE_ID,
        "target_thread_id": "thread-supervisor",
        "payload_type": "D1_FAILURE_ESCALATION",
        "payload_sha256": prepared["envelope"]["payload_sha256"],
        "prompt": "exact desktop bridge prompt",
        "prompt_sha256": "c" * 64,
    }
    write_json(Path(prepared["desktop_request_path"]), desktop_request)
    host_receipt = write_json(tmp_path / "host-receipt.json", {"schema_version": "host-receipt"})
    committed_request: dict[str, object] = {}

    def run(command: list[str], arguments: list[str], *, credential: str | None):
        operation = arguments[0]
        if operation == "authenticate-role":
            return {
                "status": "authenticated",
                "run_id": RUN_ID,
                "role": "checker",
                "role_instance_id": CHECKER_ID,
                "runtime_revision": 25,
            }
        if operation == "complete-desktop-current-turn":
            started_path = Path(prepared["desktop_started_path"])
            write_json(
                started_path,
                make_native_start(
                    adapter="codex-app-server",
                    run_id=RUN_ID,
                    cell_id=CELL_ID,
                    message_id=RECOVERY_MESSAGE_ID,
                    request_sha256=str(prepared["envelope"]["payload_sha256"]),
                    native_request_sha256="c" * 64,
                    native_task_kind="codex-desktop-turn",
                    native_task_id="thread-supervisor:turn-1:item-1",
                    native_task_status="RUNNING",
                    pid=os.getpid(),
                ),
            )
            return {
                "status": "started",
                "recovery_of_message_id": prepared["envelope"]["message_id"],
                "recovery_message_id": RECOVERY_MESSAGE_ID,
                "run_id": RUN_ID,
                "thread_id": "thread-supervisor",
                "payload_sha256": prepared["envelope"]["payload_sha256"],
                "endpoint_sha256": "d" * 64,
                "envelope_sha256": "e" * 64,
            }
        assert operation == "commit-delivery-start"
        committed_request.update(json.loads(Path(arguments[-1]).read_text(encoding="utf-8")))
        assert credential == "slk_" + "d" * 64
        return {
            "status": "committed",
            "run_id": RUN_ID,
            "runtime_revision": 26,
            "token_sequence": 5,
            "token_owner_role_instance_id": SUPERVISOR_ID,
            "event_id": committed_request["event_id"],
            "message_id": RECOVERY_MESSAGE_ID,
        }

    result = module.execute_checker_escalation(
        request,
        request_sha256=request_digest(request_path),
        request_path=request_path,
        host_receipt_path=host_receipt,
        run_json_command=run,
        unprotect_credential=lambda _path: "slk_" + "d" * 64,
    )

    assert result["status"] == "CHECKER_ESCALATION_COMMITTED"
    assert result["runtime_revision"] == 26
    assert result["token_sequence"] == 5
    assert committed_request["expected_runtime_revision"] == 25
    assert committed_request["token_sequence"] == 5
    assert committed_request["message_id"] == RECOVERY_MESSAGE_ID
    assert committed_request["payload_type"] == "D1_FAILURE_ESCALATION"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda request, projection: projection["events"][0].update(event_type="D1_PASSED"),
        lambda request, projection: projection["events"][0].update(attempt=2),
        lambda request, projection: projection["runtime_snapshot"].update(
            token_holder_role_instance_id="ROLE-worker"
        ),
        lambda request, projection: projection["runtime_snapshot"].update(runtime_revision=24),
        lambda request, projection: request.update(d1_failure_event_id="different-event"),
    ],
)
def test_prepare_rejects_changed_failure_runtime_or_authority(tmp_path: Path, mutation) -> None:
    module = load_module()
    request, request_path = fixture(tmp_path)
    projection_path = Path(str(request["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    mutation(request, projection)
    write_json(projection_path, projection)
    write_json(request_path, request)

    with pytest.raises(module.CheckerEscalationError):
        module.execute_checker_escalation(
            request,
            request_sha256=request_digest(request_path),
            request_path=request_path,
            run_json_command=lambda *_args, **_kwargs: pytest.fail("invalid evidence reached a command"),
            unprotect_credential=lambda _path: pytest.fail("invalid evidence reached the credential"),
        )


def test_path_escape_invocation_id_is_rejected_before_credential_or_files(tmp_path: Path) -> None:
    module = load_module()
    request, request_path = fixture(tmp_path)
    request["post_d1_invocation_id"] = "../escape"
    write_json(request_path, request)

    with pytest.raises(module.CheckerEscalationError, match="identifier"):
        module.execute_checker_escalation(
            request,
            request_sha256=request_digest(request_path),
            request_path=request_path,
            run_json_command=lambda *_args, **_kwargs: pytest.fail("invalid ID reached a command"),
            unprotect_credential=lambda _path: pytest.fail("invalid ID reached the credential"),
        )

    assert not (tmp_path / "escape").exists()


def test_later_overwatcher_resume_keeps_the_same_current_d1_failure_eligible(
    tmp_path: Path,
) -> None:
    module = load_module()
    request, request_path = fixture(tmp_path)
    projection_path = Path(str(request["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    projection["events"].append(
        {
            "event_id": "overwatcher-turn-resumed",
            "event_type": "OVERWATCHER_TURN_RESUMED",
            "author_role_instance_id": SUPERVISOR_ID,
            "details_json": "{}",
        }
    )
    projection["runtime_snapshot"]["runtime_revision"] = 26
    projection["runtime_snapshot"]["latest_event_id"] = "overwatcher-turn-resumed"
    request["runtime_revision"] = 26
    write_json(projection_path, projection)
    write_json(request_path, request)

    prepared = module.materialize_escalation(request)

    assert prepared["envelope"]["payload"]["d1_failure_event_id"] == FAILURE_EVENT_ID


@pytest.mark.parametrize("later_type", ["D1_PASSED", "D1_INCOMPLETE"])
def test_later_same_scope_d1_terminal_supersedes_the_bound_failure(
    tmp_path: Path, later_type: str
) -> None:
    module = load_module()
    request, request_path = fixture(tmp_path)
    projection_path = Path(str(request["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    projection["events"].append(
        {
            "event_id": f"later-{later_type.lower()}",
            "event_type": later_type,
            "author_role_instance_id": CHECKER_ID,
            "go_id": GO_ID,
            "cell_id": CELL_ID,
            "attempt": 1,
            "details_json": json.dumps({"verdict": later_type.removeprefix("D1_")}),
        }
    )
    projection["runtime_snapshot"]["runtime_revision"] = 26
    projection["runtime_snapshot"]["latest_event_id"] = f"later-{later_type.lower()}"
    request["runtime_revision"] = 26
    write_json(projection_path, projection)
    write_json(request_path, request)

    with pytest.raises(module.CheckerEscalationError, match="current terminal"):
        module.execute_checker_escalation(
            request,
            request_sha256=request_digest(request_path),
            request_path=request_path,
            run_json_command=lambda *_args, **_kwargs: pytest.fail("superseded D1 reached a command"),
            unprotect_credential=lambda _path: pytest.fail("superseded D1 reached the credential"),
        )


def test_complete_rejects_missing_native_start_without_commit(tmp_path: Path) -> None:
    module = load_module()
    request, request_path = fixture(tmp_path)
    prepared = module.materialize_escalation(request)
    write_json(
        Path(prepared["desktop_request_path"]),
        {
            "schema_version": "slk.transport-desktop-current-turn-request/v1",
            "status": "PREPARED",
            "recovery_message_id": RECOVERY_MESSAGE_ID,
            "prompt_sha256": "c" * 64,
        },
    )
    host_receipt = write_json(tmp_path / "host-receipt.json", {"schema_version": "host-receipt"})

    def run(_command: list[str], arguments: list[str], *, credential: str | None):
        if arguments[0] == "authenticate-role":
            return {
                "status": "authenticated",
                "run_id": RUN_ID,
                "role": "checker",
                "role_instance_id": CHECKER_ID,
                "runtime_revision": 25,
            }
        if arguments[0] == "complete-desktop-current-turn":
            return {
                "status": "started",
                "recovery_of_message_id": prepared["envelope"]["message_id"],
                "recovery_message_id": RECOVERY_MESSAGE_ID,
                "run_id": RUN_ID,
                "payload_sha256": prepared["envelope"]["payload_sha256"],
                "endpoint_sha256": "d" * 64,
                "envelope_sha256": "e" * 64,
            }
        pytest.fail("commit must not run without native start evidence")

    with pytest.raises(module.CheckerEscalationError, match="start"):
        module.execute_checker_escalation(
            request,
            request_sha256=request_digest(request_path),
            request_path=request_path,
            host_receipt_path=host_receipt,
            run_json_command=run,
            unprotect_credential=lambda _path: "slk_" + "d" * 64,
        )
