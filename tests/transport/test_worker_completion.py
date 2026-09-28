from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import slk_transport.worker_completion as worker_completion

from slk_transport.worker_completion import (
    CompletionError,
    _decode_dpapi_plaintext,
    build_continuation_request,
    execute_checker_recovery,
    inspect_worker_completion,
    resume_worker_continuation,
    run_worker_continuation,
    _stable_id,
)

from test_contracts import MESSAGE_ID, endpoint_value, envelope_value


FAKE_DSH = Path(__file__).with_name("fake_dsh.py")
VALID_CREDENTIAL = "slk_" + "a" * 64


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def commit_result(request: dict[str, object], *, status: str = "committed") -> dict[str, object]:
    return {
        "status": status,
        "runtime_revision": int(request["expected_runtime_revision"]) + 1,
        "token_sequence": request["token_sequence"],
        "message_id": request["message_id"],
    }


@pytest.mark.parametrize(
    "plaintext",
    [
        VALID_CREDENTIAL.encode("utf-8"),
        (VALID_CREDENTIAL + "\0").encode("utf-8"),
        (VALID_CREDENTIAL + "\0").encode("utf-16-le"),
        b"\xff\xfe" + (VALID_CREDENTIAL + "\0").encode("utf-16-le"),
    ],
)
def test_dpapi_plaintext_accepts_existing_utf8_and_powershell_utf16le(plaintext: bytes) -> None:
    assert _decode_dpapi_plaintext(plaintext) == VALID_CREDENTIAL


@pytest.mark.parametrize(
    "plaintext",
    [
        b"\xff\xfe\xfd",
        ("wrong_" + "a" * 64).encode("utf-8"),
        (VALID_CREDENTIAL + "\0\0").encode("utf-8"),
        (VALID_CREDENTIAL + "\0\0").encode("utf-16-le"),
    ],
)
def test_dpapi_plaintext_rejects_invalid_encoding_and_wrong_credential_shape(plaintext: bytes) -> None:
    with pytest.raises(CompletionError) as rejected:
        _decode_dpapi_plaintext(plaintext)
    assert rejected.value.error_code == "WORKER_CREDENTIAL_UNAVAILABLE"


def test_dpapi_plaintext_rejects_pseudo_utf8_with_embedded_nul() -> None:
    with pytest.raises(CompletionError, match="embedded NUL"):
        _decode_dpapi_plaintext(b"slk_" + b"a" * 8 + b"\0" + b"a" * 55)


def test_json_command_preserves_nonzero_valid_stdout_business_status() -> None:
    result = worker_completion._run_json_command(
        [sys.executable],
        ["-c", "import json,sys; print(json.dumps({'verdict':'INCOMPLETE'})); sys.exit(3)"],
        credential=None,
    )

    assert result["verdict"] == "INCOMPLETE"
    assert result["_slk_command"] == {
        "process_exit": 3,
        "json_parse": "PARSED_STDOUT",
        "business_status": "INCOMPLETE",
    }


def checker_recovery_request(tmp_path: Path) -> dict[str, object]:
    attempt, _worker, checker = completion_fixture(tmp_path)
    projection_path = write_json(tmp_path / "runtime-projection.json", runtime_projection())
    return {
        "schema_version": "slk.ocrv-worker-recovery-request/v1",
        "method_version": "4.3.1",
        "recovery_invocation_id": "recovery-invocation-1",
        "recovery_envelope_message_id": "22222222-2222-4222-8222-222222222222",
        "run_id": "RUN-A",
        "go_id": "GO-001",
        "cell_id": "CELL-001",
        "checker_role_instance_id": checker["role_instance_id"],
        "checker_endpoint_version": checker["endpoint_version"],
        "checker_endpoint": checker,
        "source_attempt_root": str(attempt),
        "runtime_projection_path": str(projection_path),
        "plan_revision": 1,
        "runtime_revision": 7,
        "token_sequence": 14,
        "worker_credential_path": str(tmp_path / "worker.dpapi"),
        "checker_credential_path": str(tmp_path / "checker.dpapi"),
        "state_command": ["slk-state"],
        "transport_command": ["python", "slk-transport.pyz"],
        "occurred_at": "2026-09-23T00:00:00Z",
        "result_path": str(tmp_path / "checker-recovery-result.json"),
    }


def test_exact_ocrv_checker_authenticates_before_resuming_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = checker_recovery_request(tmp_path)
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(request["checker_role_instance_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(request["checker_endpoint_version"]))
    calls: list[str] = []

    def authenticate(run_id: str, role_id: str, credential: Path, command: list[str]) -> dict[str, object]:
        calls.append("authenticate")
        assert run_id == "RUN-A"
        assert credential.name == "checker.dpapi"
        assert command == ["slk-state"]
        return {
            "status": "authenticated",
            "run_id": run_id,
            "role": "checker",
            "role_instance_id": role_id,
            "runtime_revision": 7,
        }

    def resume(continuation: dict[str, object]) -> dict[str, object]:
        calls.append("resume")
        assert continuation["method_version"] == "4.3.1"
        return {"status": "CHECKER_STARTED"}

    result = execute_checker_recovery(
        request,
        request_sha256="a" * 64,
        authenticate_checker=authenticate,
        resume_continuation=resume,
    )

    assert calls == ["authenticate", "resume"]
    assert result["status"] == "CHECKER_STARTED"
    assert result["checker_role_instance_id"] == request["checker_role_instance_id"]


def test_checker_recovery_rejects_supervisor_direct_call_and_wrong_checker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = checker_recovery_request(tmp_path)
    called = False

    def authenticate(*_args: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {}

    with pytest.raises(CompletionError) as no_native_checker:
        execute_checker_recovery(
            request,
            request_sha256="a" * 64,
            authenticate_checker=authenticate,
            resume_continuation=lambda _request: {},
        )
    assert no_native_checker.value.error_code == "CHECKER_RECOVERY_NATIVE_IDENTITY_UNPROVEN"
    assert called is False

    monkeypatch.setenv("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(request["checker_role_instance_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(request["checker_endpoint_version"]))
    with pytest.raises(CompletionError) as wrong_checker:
        execute_checker_recovery(
            request,
            request_sha256="a" * 64,
            authenticate_checker=lambda *_args: {
                "status": "authenticated",
                "role": "supervisor",
                "role_instance_id": "RUN-A-supervisor-001",
                "runtime_revision": 7,
            },
            resume_continuation=lambda _request: {},
        )
    assert wrong_checker.value.error_code == "CHECKER_RECOVERY_AUTHENTICATION_FAILED"


def completion_fixture(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, object]]:
    (tmp_path / "runtime").mkdir()
    (tmp_path / "repository").mkdir()
    (tmp_path / "ocrv").mkdir()
    endpoint = endpoint_value(role="worker", version=1)
    endpoint["agent_runtime"] = "dsh"
    endpoint["adapter"] = "dsh-worker"
    endpoint["address"] = {
        "command": ["D:/DSH/dsh-slk.cmd"],
        "instance_id": "RUN-A-worker",
        "session_id": "session-11111111-1111-4111-8111-111111111111",
        "runtime_root": str(tmp_path / "runtime"),
        "cwd": str(tmp_path / "repository"),
        "timeout_seconds": 30,
    }
    envelope = envelope_value(
        sender_role="checker",
        receiver_role="worker",
        receiver_endpoint_version=1,
    )
    envelope["payload"] = {
        "cell_goal": "finish one bounded change",
        "d1_criteria": ["focused test passes"],
    }
    from slk_transport.contracts import canonical_json_sha256

    envelope["payload_sha256"] = canonical_json_sha256(envelope["payload"])
    attempt = tmp_path / "attempts" / "RUN-A" / str(envelope["message_id"])
    write_json(attempt / "endpoint.json", endpoint)
    write_json(attempt / "envelope.json", envelope)
    write_json(
        attempt / "started.json",
        {
            "message_id": envelope["message_id"],
            "run_id": "RUN-A",
            "status": "started",
            "instance_id": "RUN-A-worker",
            "session_id": endpoint["address"]["session_id"],
            "task_sha256": "a" * 64,
        },
    )
    write_json(
        attempt / "worker-result.json",
        {
            "schema_version": "slk.worker-result/v1",
            "message_id": envelope["message_id"],
            "run_id": "RUN-A",
            "role_instance_id": endpoint["role_instance_id"],
            "status": "completed",
            "candidate": {"kind": "commit", "commit": "b" * 40},
            "next_payload": {
                "candidate_repository": str(tmp_path / "repository"),
                "cell_goal": "finish one bounded change",
                "candidate_baseline": "a" * 40,
                "changed_paths": ["src/example.py"],
                "d0": {"commands_and_outcomes": ["pytest: pass"], "not_run": []},
                "unproved": [],
            },
            "blocker": None,
        },
    )
    write_json(
        attempt / "completed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": envelope["message_id"],
            "run_id": "RUN-A",
            "adapter": "dsh-worker",
            "status": "completed",
            "native_identity": {
                "instance_id": "RUN-A-worker",
                "session_id": endpoint["address"]["session_id"],
                "exit_code": 0,
            },
            "error_code": None,
            "evidence": ["started.json", "worker-result.json"],
        },
    )
    checker = endpoint_value(role="checker", version=2)
    checker["address"] = {
        "command": ["D:/OCRV/slk-checker.cmd"],
        "runtime_root": str(tmp_path / "ocrv"),
        "timeout_seconds": 30,
    }
    return attempt, endpoint, checker


def runtime_projection(
    *,
    event_types: list[str] | None = None,
    token_owner: str = "ROLE-worker",
    attempt: int = 1,
) -> dict[str, object]:
    types = ["TRANSPORT_STARTED", *(item for item in event_types or [] if item != "TRANSPORT_STARTED")]
    events: list[dict[str, object]] = []
    for index, event_type in enumerate(types, start=1):
        event: dict[str, object] = {
            "event_id": f"event-{index}",
            "event_type": event_type,
            "cell_id": "CELL-001",
            "attempt": attempt,
        }
        if event_type == "TRANSPORT_STARTED":
            event["details_json"] = json.dumps({"message_id": MESSAGE_ID})
        events.append(event)
    return {
        "summary": {"run_id": "RUN-A", "slk_version": "4.3.1", "plan_revision": 1},
        "runtime_snapshot": {
            "method_version": "4.3.1",
            "plan_revision": 1,
            "runtime_revision": 7,
            "token_sequence": 14,
            "token_holder_role_instance_id": token_owner,
            "latest_message_id": MESSAGE_ID,
        },
        "events": events,
        "operational_observations": [],
    }


def current_worker_handoff_events() -> list[dict[str, object]]:
    candidate = {"kind": "commit", "commit": "b" * 40}
    handoff_message_id = _stable_id(MESSAGE_ID, "candidate-ready")
    return [
        {
            "event_id": "candidate-current",
            "event_type": "CANDIDATE_SUBMITTED",
            "cell_id": "CELL-001",
            "attempt": 1,
            "details_json": json.dumps(
                {
                    "candidate": candidate,
                    "source_message_id": MESSAGE_ID,
                    "handoff_message_id": handoff_message_id,
                }
            ),
        },
        {
            "event_id": "handoff-current",
            "event_type": "TRANSPORT_STARTED",
            "cell_id": "CELL-001",
            "attempt": 1,
            "details_json": json.dumps({"message_id": handoff_message_id}),
        },
    ]


def test_terminal_worker_without_handoff_alerts_after_one_complete_cadence(tmp_path: Path) -> None:
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    projection = runtime_projection(token_owner=str(endpoint["role_instance_id"]))
    completed_at = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc).timestamp()
    os.utime(attempt / "completed.json", (completed_at, completed_at))

    first = inspect_worker_completion(
        attempt,
        projection,
        observed_at="2026-09-23T00:00:00Z",
        cadence_seconds=240,
    )
    second = inspect_worker_completion(
        attempt,
        projection,
        observed_at="2026-09-23T00:04:00Z",
        cadence_seconds=240,
        previous_inspection=first,
    )

    assert first["status"] == "COMPLETION_GRACE"
    assert second["status"] == "WORKER_COMPLETION_HANDOFF_MISSING"
    assert second["anomaly_codes"] == [
        "WORKER_COMPLETION_HANDOFF_MISSING",
        "COMMUNICATION_RECOVERY_REQUIRED",
    ]


def test_first_inspection_uses_old_terminal_evidence_instead_of_granting_fresh_grace(
    tmp_path: Path,
) -> None:
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    completed_at = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc).timestamp()
    os.utime(attempt / "completed.json", (completed_at, completed_at))

    result = inspect_worker_completion(
        attempt,
        runtime_projection(token_owner=str(endpoint["role_instance_id"])),
        observed_at="2026-09-23T00:04:00Z",
        cadence_seconds=240,
    )

    assert result["status"] == "WORKER_COMPLETION_HANDOFF_MISSING"
    assert result["grace_started_at"] == "2026-09-23T00:00:00Z"


def test_running_worker_and_existing_d1_do_not_raise_completion_handoff_alarm(tmp_path: Path) -> None:
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    (attempt / "completed.json").unlink()
    assert inspect_worker_completion(
        attempt,
        runtime_projection(token_owner=str(endpoint["role_instance_id"])),
        observed_at="2026-09-23T00:10:00Z",
        cadence_seconds=240,
    )["status"] == "IN_PROGRESS"

    write_json(attempt / "completed.json", {"status": "completed"})
    projection = runtime_projection(event_types=["D1_INCOMPLETE"], token_owner="ROLE-checker")
    projection["events"].extend(current_worker_handoff_events())
    assert inspect_worker_completion(
        attempt,
        projection,
        observed_at="2026-09-23T00:10:00Z",
        cadence_seconds=240,
    )["status"] == "HANDED_OFF_OR_D1"


def test_d1_from_an_older_attempt_does_not_hide_current_worker_handoff_stall(tmp_path: Path) -> None:
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    projection = runtime_projection(token_owner=str(endpoint["role_instance_id"]), attempt=2)
    projection["events"].append(
        {"event_id": "old-d1", "event_type": "D1_INCOMPLETE", "cell_id": "CELL-001", "attempt": 1}
    )
    first = inspect_worker_completion(
        attempt,
        projection,
        observed_at="2026-09-23T00:00:00Z",
        cadence_seconds=240,
    )
    result = inspect_worker_completion(
        attempt,
        projection,
        observed_at="2026-09-23T00:04:00Z",
        cadence_seconds=240,
        previous_inspection=first,
    )
    assert result["status"] == "WORKER_COMPLETION_HANDOFF_MISSING"
    assert result["attempt"] == 2


def test_d1_with_same_attempt_but_wrong_candidate_and_message_does_not_prove_handoff(
    tmp_path: Path,
) -> None:
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    projection = runtime_projection(event_types=[], token_owner="ROLE-checker")
    projection["events"].extend(
        [
            {
                "event_id": "candidate-other",
                "event_type": "CANDIDATE_SUBMITTED",
                "cell_id": "CELL-001",
                "attempt": 1,
                "details_json": json.dumps(
                    {
                        "candidate": {"kind": "commit", "commit": "c" * 40},
                        "source_message_id": "other-source-message",
                        "handoff_message_id": "other-handoff-message",
                    }
                ),
            },
            {
                "event_id": "d1-other",
                "event_type": "D1_PASSED",
                "cell_id": "CELL-001",
                "attempt": 1,
                "details_json": json.dumps(
                    {
                        "candidate": {"kind": "commit", "commit": "c" * 40},
                        "message_id": "other-handoff-message",
                    }
                ),
            },
        ]
    )

    result = inspect_worker_completion(
        attempt,
        projection,
        observed_at="2026-09-23T00:10:00Z",
        cadence_seconds=240,
        previous_inspection={
            "schema_version": "slk.worker-completion-inspection/v1",
            "run_id": "RUN-A",
            "source_message_id": MESSAGE_ID,
            "status": "COMPLETION_GRACE",
            "grace_started_at": "2026-09-23T00:00:00Z",
        },
    )

    assert result["status"] == "WORKER_COMPLETION_HANDOFF_MISSING"
    assert result["worker_role_instance_id"] == endpoint["role_instance_id"]
    assert result["candidate"] == {"kind": "commit", "commit": "b" * 40}
    assert result["handoff_message_id"] == _stable_id(MESSAGE_ID, "candidate-ready")


def test_recorded_notification_does_not_clear_a_still_unresolved_completion_stall(tmp_path: Path) -> None:
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    projection = runtime_projection(token_owner=str(endpoint["role_instance_id"]))
    projection["operational_observations"] = [
        {
            "kind": "RECOVERY_ESCALATED",
            "details_json": json.dumps(
                {"message_id": json.loads((attempt / "envelope.json").read_text())["message_id"]}
            ),
        }
    ]
    previous = {
        "schema_version": "slk.worker-completion-inspection/v1",
        "status": "COMPLETION_GRACE",
        "grace_started_at": "2026-09-23T00:00:00Z",
        "run_id": "RUN-A",
        "source_message_id": json.loads((attempt / "envelope.json").read_text())["message_id"],
    }

    first_unresolved = inspect_worker_completion(
        attempt,
        projection,
        observed_at="2026-09-23T00:08:00Z",
        cadence_seconds=240,
        previous_inspection=previous,
    )
    second_unresolved = inspect_worker_completion(
        attempt,
        projection,
        observed_at="2026-09-23T00:12:00Z",
        cadence_seconds=240,
        previous_inspection=first_unresolved,
    )
    for result in (first_unresolved, second_unresolved):
        assert result["status"] == "WORKER_COMPLETION_HANDOFF_MISSING"
        assert result["notification_already_sent"] is True
        assert result["anomaly_codes"] == [
            "WORKER_COMPLETION_HANDOFF_MISSING",
            "COMMUNICATION_RECOVERY_REQUIRED",
        ]


def test_continuation_request_is_stable_resumes_exact_session_and_contains_no_secret(tmp_path: Path) -> None:
    attempt, _endpoint, checker = completion_fixture(tmp_path)
    projection = runtime_projection(attempt=2)
    first = build_continuation_request(
        attempt,
        checker,
        projection,
        plan_revision=1,
        runtime_revision=7,
        token_sequence=14,
        credential_path=tmp_path / "credentials" / "worker.dpapi",
        state_command=["D:/SLK/slk-state.exe"],
        transport_command=["python", "D:/SLK/slk-transport.pyz"],
        occurred_at="2026-09-23T00:00:00Z",
    )
    second = build_continuation_request(
        attempt,
        checker,
        projection,
        plan_revision=1,
        runtime_revision=7,
        token_sequence=14,
        credential_path=tmp_path / "credentials" / "worker.dpapi",
        state_command=["D:/SLK/slk-state.exe"],
        transport_command=["python", "D:/SLK/slk-transport.pyz"],
        occurred_at="2026-09-23T00:00:00Z",
    )

    assert first == second
    assert first["attempt"] == 2
    assert first["worker_session_id"] == "session-11111111-1111-4111-8111-111111111111"
    serialized = json.dumps(first)
    assert "SLK_ROLE_CREDENTIAL" not in serialized
    assert "slk_" not in serialized


@pytest.mark.parametrize("events", [[], [
    {
        "event_id": "ambiguous-attempt",
        "event_type": "TRANSPORT_STARTED",
        "cell_id": "CELL-001",
        "attempt": 2,
        "details_json": json.dumps({"message_id": MESSAGE_ID}),
    },
    {
        "event_id": "other-attempt",
        "event_type": "TRANSPORT_STARTED",
        "cell_id": "CELL-001",
        "attempt": 3,
        "details_json": json.dumps({"message_id": MESSAGE_ID}),
    },
]])
def test_continuation_fails_closed_when_source_attempt_is_missing_or_ambiguous(
    tmp_path: Path,
    events: list[dict[str, object]],
) -> None:
    attempt, _endpoint, checker = completion_fixture(tmp_path)
    projection = runtime_projection()
    projection["events"] = events

    with pytest.raises(CompletionError) as rejected:
        build_continuation_request(
            attempt,
            checker,
            projection,
            plan_revision=1,
            runtime_revision=7,
            token_sequence=14,
            credential_path=tmp_path / "worker.dpapi",
            state_command=["slk-state"],
            transport_command=["slk-transport"],
            occurred_at="2026-09-23T00:00:00Z",
        )

    assert rejected.value.error_code == "WORKER_COMPLETION_ATTEMPT_UNPROVEN"


def test_resume_worker_continuation_uses_exact_session_and_strips_parent_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt, endpoint, checker = completion_fixture(tmp_path)
    session_id = str(endpoint["address"]["session_id"])
    endpoint["address"]["command"] = [sys.executable, str(FAKE_DSH), "continuation"]
    endpoint["address"]["session_id"] = None
    endpoint["address"]["timeout_seconds"] = 5
    write_json(attempt / "endpoint.json", endpoint)
    session_root = (
        Path(str(endpoint["address"]["runtime_root"]))
        / "runs"
        / str(endpoint["address"]["instance_id"])
        / "home"
        / "storages"
        / "session_projcache"
        / "sessions"
    )
    session_root.mkdir(parents=True)
    (session_root / f"{session_id}.json").write_text("{}\n", encoding="utf-8")
    request = build_continuation_request(
        attempt,
        checker,
        runtime_projection(),
        plan_revision=1,
        runtime_revision=7,
        token_sequence=14,
        credential_path=tmp_path / "credentials" / "worker.dpapi",
        state_command=["slk-state"],
        transport_command=["slk-transport"],
        occurred_at="2026-09-23T00:00:00Z",
    )
    monkeypatch.setenv("SLK_ROLE_CREDENTIAL", "slk_must_not_escape")
    monkeypatch.setenv("SLK_OVERWATCHER_CREDENTIAL", "slk_must_not_escape")

    result = resume_worker_continuation(request)

    assert result["status"] == "CHECKER_STARTED"
    assert result["source_message_id"] == request["source_message_id"]
    started = json.loads((attempt / "worker-continuation" / "started.json").read_text(encoding="utf-8"))
    assert started["session_id"] == session_id


def test_worker_owned_continuation_records_d0_then_starts_checker_once(tmp_path: Path) -> None:
    attempt, endpoint, checker = completion_fixture(tmp_path)
    (attempt / "native.stdout.txt").write_text("x" * 100_000, encoding="utf-8")
    (attempt / "native.stderr.txt").write_text("warning tail", encoding="utf-8")
    request = build_continuation_request(
        attempt,
        checker,
        runtime_projection(),
        plan_revision=1,
        runtime_revision=7,
        token_sequence=14,
        credential_path=tmp_path / "credentials" / "worker.dpapi",
        state_command=["slk-state"],
        transport_command=["slk-transport"],
        occurred_at="2026-09-23T00:00:00Z",
    )
    events: list[dict[str, object]] = []
    sends: list[dict[str, object]] = []
    commits: list[dict[str, object]] = []

    def authenticate(run_id: str, role_instance_id: str) -> int:
        assert run_id == "RUN-A"
        assert role_instance_id == endpoint["role_instance_id"]
        return 10

    def write_event(event: dict[str, object]) -> str:
        events.append(event)
        return "RECORDED"

    def start_checker(endpoint_raw: dict[str, object], envelope_raw: dict[str, object]) -> dict[str, object]:
        sends.append(envelope_raw)
        endpoint_path = write_json(tmp_path / "checker-endpoint.json", endpoint_raw)
        envelope_path = write_json(tmp_path / "checker-envelope.json", envelope_raw)
        started_path = write_json(
            tmp_path / "checker-started.json",
            {
                "message_id": envelope_raw["message_id"],
                "run_id": envelope_raw["run_id"],
                "status": "started",
                "review_invocation_id": "review-1",
            },
        )
        return {
            "status": "started",
            "started_path": str(started_path),
            "endpoint_path": str(endpoint_path),
            "envelope_path": str(envelope_path),
        }

    def commit_start(value: dict[str, object]) -> dict[str, object]:
        commits.append(value)
        return {
            "status": "committed",
            "runtime_revision": 11,
            "token_sequence": value["token_sequence"],
            "message_id": value["message_id"],
        }

    result = run_worker_continuation(
        request,
        authenticate=authenticate,
        write_event=write_event,
        start_checker=start_checker,
        commit_start=commit_start,
    )

    assert result["status"] == "CHECKER_STARTED"
    assert [event["event_type"] for event in events] == [
        "WORK_STARTED",
        "D0_COMPLETED",
        "CANDIDATE_SUBMITTED",
    ]
    assert sends[0]["payload_type"] == "CANDIDATE_READY"
    assert commits[0]["from_role_instance_id"] == endpoint["role_instance_id"]
    assert result["runtime_revision"] == 11
    evidence_files = sends[0]["payload"]["evidence_files"]
    assert all(not str(path).endswith(("native.stdout.txt", "native.stderr.txt")) for path in evidence_files)
    index_path = next(Path(str(path)) for path in evidence_files if str(path).endswith("checker-evidence-index.json"))
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["schema_version"] == "slk.checker-evidence-index/v1"
    assert {entry["name"] for entry in index["entries"]} >= {"native.stdout.txt", "native.stderr.txt"}


def test_missing_worker_repository_uses_authenticated_endpoint_cwd(tmp_path: Path) -> None:
    attempt, _endpoint, checker = completion_fixture(tmp_path)
    worker_result = json.loads((attempt / "worker-result.json").read_text(encoding="utf-8"))
    worker_result["next_payload"].pop("candidate_repository")
    write_json(attempt / "worker-result.json", worker_result)
    request = build_continuation_request(
        attempt,
        checker,
        runtime_projection(),
        plan_revision=1,
        runtime_revision=7,
        token_sequence=14,
        credential_path=tmp_path / "worker.dpapi",
        state_command=["slk-state"],
        transport_command=["slk-transport"],
        occurred_at="2026-09-23T00:00:00Z",
    )
    sent: list[dict[str, object]] = []

    def start_checker(endpoint_raw: dict[str, object], envelope_raw: dict[str, object]) -> dict[str, object]:
        sent.append(envelope_raw)
        return {
            "status": "started",
            "started_path": str(write_json(tmp_path / "repo-fallback-started.json", {
                "message_id": envelope_raw["message_id"], "run_id": "RUN-A", "status": "started"
            })),
            "endpoint_path": str(write_json(tmp_path / "repo-fallback-endpoint.json", endpoint_raw)),
            "envelope_path": str(write_json(tmp_path / "repo-fallback-envelope.json", envelope_raw)),
        }

    result = run_worker_continuation(
        request,
        authenticate=lambda *_: 10,
        write_event=lambda _event: "RECORDED",
        start_checker=start_checker,
        commit_start=commit_result,
    )

    assert result["status"] == "CHECKER_STARTED"
    assert sent[0]["payload"]["repository"] == str((tmp_path / "repository").resolve())


def test_retry_reuses_original_immutable_request_bytes_when_only_time_changes(tmp_path: Path) -> None:
    path = tmp_path / "write-event.json"
    first = {"event_id": "stable-event", "event_type": "WORK_STARTED", "occurred_at": "2026-09-23T00:00:00Z"}
    retry = {**first, "occurred_at": "2026-09-23T00:05:00Z"}

    first_path = worker_completion._write_or_reuse_stable_request(path, first)
    original = first_path.read_bytes()
    retry_path = worker_completion._write_or_reuse_stable_request(path, retry)

    assert retry_path.read_bytes() == original
    assert json.loads(original)["occurred_at"] == "2026-09-23T00:00:00Z"


def test_rework_acceptance_criteria_become_checker_d1_criteria(tmp_path: Path) -> None:
    attempt, endpoint, checker = completion_fixture(tmp_path)
    source = json.loads((attempt / "envelope.json").read_text(encoding="utf-8"))
    source["sender_role"] = "supervisor"
    source["sender_role_instance_id"] = "RUN-A-supervisor-001"
    source["payload_type"] = "D1_REWORK_DIRECTIVE"
    source["payload"] = {
        "d1_failure_event_id": "d1-failed-001",
        "failed_candidate_sha256": "a" * 64,
        "rework_round": 1,
        "cell_goal": "remove the invalid comparison",
        "acceptance_criteria": [
            "compare only the valid GUI identity surface",
            "keep the localized footer text",
        ],
        "findings": ["the localized footer is not the GUI package identity"],
        "evidence_refs": ["evidence/d1-failed-001.json"],
        "root_cause_hypothesis": "the implementation compared unrelated identity surfaces",
        "minimal_experiment": "run the focused GUI identity regression",
        "minimal_repair_scope": "remove only the invalid footer comparison",
        "regression_target": "the focused regression fails before and passes after",
    }
    from slk_transport.contracts import canonical_json_sha256

    source["payload_sha256"] = canonical_json_sha256(source["payload"])
    write_json(attempt / "envelope.json", source)
    request = build_continuation_request(
        attempt,
        checker,
        runtime_projection(),
        plan_revision=1,
        runtime_revision=7,
        token_sequence=14,
        credential_path=tmp_path / "worker.dpapi",
        state_command=["slk-state"],
        transport_command=["slk-transport"],
        occurred_at="2026-09-23T00:00:00Z",
    )
    sent: list[dict[str, object]] = []

    def start_checker(endpoint_raw: dict[str, object], envelope_raw: dict[str, object]) -> dict[str, object]:
        sent.append(envelope_raw)
        return {
            "status": "started",
            "started_path": str(
                write_json(
                    tmp_path / "rework-checker-started.json",
                    {
                        "message_id": envelope_raw["message_id"],
                        "run_id": envelope_raw["run_id"],
                        "status": "started",
                    },
                )
            ),
            "endpoint_path": str(write_json(tmp_path / "rework-checker-endpoint.json", endpoint_raw)),
            "envelope_path": str(write_json(tmp_path / "rework-checker-envelope.json", envelope_raw)),
        }

    result = run_worker_continuation(
        request,
        authenticate=lambda run_id, role_id: 10,
        write_event=lambda event: "RECORDED",
        start_checker=start_checker,
        commit_start=commit_result,
    )

    assert result["status"] == "CHECKER_STARTED"
    assert sent[0]["payload"]["d1_criteria"] == source["payload"]["acceptance_criteria"]
    assert sent[0]["payload"]["cell_goal"] == source["payload"]["cell_goal"]


def test_continuation_exact_replay_does_not_send_checker_twice(tmp_path: Path) -> None:
    attempt, _endpoint, checker = completion_fixture(tmp_path)
    request = build_continuation_request(
        attempt,
        checker,
        runtime_projection(),
        plan_revision=1,
        runtime_revision=7,
        token_sequence=14,
        credential_path=tmp_path / "worker.dpapi",
        state_command=["slk-state"],
        transport_command=["slk-transport"],
        occurred_at="2026-09-23T00:00:00Z",
    )
    sends = 0

    def start_checker(endpoint_raw: dict[str, object], envelope_raw: dict[str, object]) -> dict[str, object]:
        nonlocal sends
        sends += 1
        return {
            "status": "already_started",
            "started_path": str(
                write_json(
                    tmp_path / "started.json",
                    {"message_id": envelope_raw["message_id"], "run_id": "RUN-A", "status": "started"},
                )
            ),
            "endpoint_path": str(write_json(tmp_path / "endpoint.json", endpoint_raw)),
            "envelope_path": str(write_json(tmp_path / "candidate-envelope.json", envelope_raw)),
        }

    result = run_worker_continuation(
        request,
        authenticate=lambda *_: 10,
        write_event=lambda _event: "IDEMPOTENT_REPLAY",
        start_checker=start_checker,
        commit_start=lambda request: commit_result(request, status="idempotent_replay"),
    )

    assert result["status"] == "CHECKER_STARTED"
    assert sends == 1


def test_wrong_worker_credential_fails_before_any_write_or_delivery(tmp_path: Path) -> None:
    attempt, _endpoint, checker = completion_fixture(tmp_path)
    request = build_continuation_request(
        attempt,
        checker,
        runtime_projection(),
        plan_revision=1,
        runtime_revision=7,
        token_sequence=14,
        credential_path=tmp_path / "worker.dpapi",
        state_command=["slk-state"],
        transport_command=["slk-transport"],
        occurred_at="2026-09-23T00:00:00Z",
    )
    touched = False

    def authenticate(*_args: str) -> None:
        raise CompletionError("WORKER_CREDENTIAL_MISMATCH", "wrong active Worker")

    def touch(*_args: object, **_kwargs: object) -> str:
        nonlocal touched
        touched = True
        return "unexpected"

    with pytest.raises(CompletionError, match="wrong active Worker"):
        run_worker_continuation(
            request,
            authenticate=authenticate,
            write_event=touch,
            start_checker=touch,
            commit_start=touch,
        )
    assert touched is False


def test_terminal_text_without_exact_started_evidence_cannot_advance_token(tmp_path: Path) -> None:
    attempt, _endpoint, checker = completion_fixture(tmp_path)
    request = build_continuation_request(
        attempt,
        checker,
        runtime_projection(),
        plan_revision=1,
        runtime_revision=7,
        token_sequence=14,
        credential_path=tmp_path / "worker.dpapi",
        state_command=["slk-state"],
        transport_command=["slk-transport"],
        occurred_at="2026-09-23T00:00:00Z",
    )
    committed = False

    def commit(_request: dict[str, object]) -> str:
        nonlocal committed
        committed = True
        return "unexpected"

    with pytest.raises(CompletionError, match="native start"):
        run_worker_continuation(
            request,
            authenticate=lambda *_: 10,
            write_event=lambda _event: "RECORDED",
            start_checker=lambda *_: {"status": "completed"},
            commit_start=commit,
        )
    assert committed is False


def test_inspector_reports_structured_incomplete_worker_result(tmp_path: Path) -> None:
    attempt, _endpoint, _checker = completion_fixture(tmp_path)
    (attempt / "completed.json").unlink()
    result = json.loads((attempt / "worker-result.json").read_text(encoding="utf-8"))
    result.update(
        {
            "status": "incomplete",
            "candidate": None,
            "next_payload": None,
            "blocker": {
                "phase": "git_commit",
                "cause": "GIT_COMMON_DIR_UNWRITABLE",
                "summary": "the exact sandbox cannot create index.lock",
                "evidence": ["native.stderr.txt"],
            },
        }
    )
    write_json(attempt / "worker-result.json", result)
    write_json(
        attempt / "failed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": MESSAGE_ID,
            "run_id": "RUN-A",
            "adapter": "dsh-worker",
            "status": "failed",
            "native_identity": {"worker_outcome": "incomplete"},
            "error_code": "DSH_WORKER_INCOMPLETE",
            "evidence": ["started.json", "worker-result.json"],
        },
    )

    inspection = inspect_worker_completion(
        attempt,
        runtime_projection(),
        observed_at="2026-09-23T00:04:00Z",
        cadence_seconds=240,
    )

    assert inspection["status"] == "WORKER_INCOMPLETE"
    assert inspection["worker_outcome"] == "incomplete"
    assert inspection["blocker"]["cause"] == "GIT_COMMON_DIR_UNWRITABLE"


def legacy_missing_result_fixture(
    tmp_path: Path,
) -> tuple[Path, dict[str, object], dict[str, object]]:
    attempt, worker, checker = completion_fixture(tmp_path)
    (attempt / "completed.json").unlink()
    (attempt / "worker-result.json").unlink()
    write_json(
        attempt / "failed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": MESSAGE_ID,
            "run_id": "RUN-A",
            "adapter": "dsh-worker",
            "status": "failed",
            "native_identity": {},
            "error_code": "DSH_RESULT_MISSING",
            "evidence": ["started.json", "native.stdout.txt", "native.stderr.txt"],
        },
    )
    (attempt / "native.stdout.txt").write_text(
        "Worker reports that implementation and checks completed but the result contract was not written.\n",
        encoding="utf-8",
    )
    (attempt / "native.stderr.txt").write_text("", encoding="utf-8")
    return attempt, worker, checker


def test_inspector_reports_legacy_missing_result_as_recoverable_incomplete(
    tmp_path: Path,
) -> None:
    attempt, _worker, _checker = legacy_missing_result_fixture(tmp_path)

    inspection = inspect_worker_completion(
        attempt,
        runtime_projection(),
        observed_at="2026-09-23T00:04:00Z",
        cadence_seconds=240,
    )

    assert inspection["status"] == "WORKER_INCOMPLETE"
    assert inspection["worker_outcome"] == "incomplete"
    assert inspection["blocker"] == {
        "phase": "result_contract",
        "cause": "RESULT_CONTRACT_MISSING",
        "summary": "the exact started DSH Worker terminated without its closed result contract",
        "evidence": ["failed.json", "native.stdout.txt", "native.stderr.txt"],
    }


def test_checker_recovery_builds_missing_result_continuation(tmp_path: Path) -> None:
    attempt, _worker, checker = legacy_missing_result_fixture(tmp_path)

    request = build_continuation_request(
        attempt,
        checker,
        runtime_projection(),
        plan_revision=1,
        runtime_revision=7,
        token_sequence=14,
        credential_path=tmp_path / "worker.dpapi",
        state_command=["slk-state"],
        transport_command=["slk-transport"],
        occurred_at="2026-09-23T00:00:00Z",
    )

    assert request["recovery_mode"] == "MISSING_RESULT"
    assert request["worker_result_sha256"] is None
    assert request["worker_result_path"] == str(
        (attempt / "worker-continuation" / "recovered-worker-result.json").resolve()
    )
    assert request["source_terminal_sha256"] == worker_completion._sha256(
        attempt / "failed.json"
    )


def test_checker_recovery_rejects_other_terminal_failure_without_result(
    tmp_path: Path,
) -> None:
    attempt, _worker, checker = legacy_missing_result_fixture(tmp_path)
    failed = json.loads((attempt / "failed.json").read_text(encoding="utf-8"))
    failed["error_code"] = "DSH_PROCESS_FAILED"
    write_json(attempt / "failed.json", failed)

    with pytest.raises(CompletionError) as rejected:
        build_continuation_request(
            attempt,
            checker,
            runtime_projection(),
            plan_revision=1,
            runtime_revision=7,
            token_sequence=14,
            credential_path=tmp_path / "worker.dpapi",
            state_command=["slk-state"],
            transport_command=["slk-transport"],
            occurred_at="2026-09-23T00:00:00Z",
        )

    assert rejected.value.error_code == "WORKER_CONTINUATION_NOT_READY"


def test_worker_owned_missing_result_continuation_uses_recovered_result(
    tmp_path: Path,
) -> None:
    attempt, endpoint, checker = legacy_missing_result_fixture(tmp_path)
    request = build_continuation_request(
        attempt,
        checker,
        runtime_projection(),
        plan_revision=1,
        runtime_revision=7,
        token_sequence=14,
        credential_path=tmp_path / "worker.dpapi",
        state_command=["slk-state"],
        transport_command=["slk-transport"],
        occurred_at="2026-09-23T00:00:00Z",
    )
    write_json(
        Path(str(request["worker_result_path"])),
        {
            "schema_version": "slk.worker-result/v1",
            "message_id": MESSAGE_ID,
            "run_id": "RUN-A",
            "role_instance_id": endpoint["role_instance_id"],
            "status": "completed",
            "candidate": {"kind": "commit", "commit": "c" * 40},
            "next_payload": {
                "candidate_repository": str(tmp_path / "repository"),
                "cell_goal": "finish one bounded change",
                "candidate_baseline": "a" * 40,
                "changed_paths": ["src/example.py"],
                "d0": {"commands_and_outcomes": ["pytest: pass"], "not_run": []},
                "unproved": [],
            },
            "blocker": None,
        },
    )
    sent: list[dict[str, object]] = []

    def start_checker(
        endpoint_raw: dict[str, object], envelope_raw: dict[str, object]
    ) -> dict[str, object]:
        sent.append(envelope_raw)
        return {
            "status": "started",
            "started_path": str(
                write_json(
                    tmp_path / "missing-result-checker-started.json",
                    {
                        "message_id": envelope_raw["message_id"],
                        "run_id": "RUN-A",
                        "status": "started",
                    },
                )
            ),
            "endpoint_path": str(
                write_json(tmp_path / "missing-result-checker-endpoint.json", endpoint_raw)
            ),
            "envelope_path": str(
                write_json(tmp_path / "missing-result-checker-envelope.json", envelope_raw)
            ),
        }

    result = run_worker_continuation(
        request,
        authenticate=lambda *_: 10,
        write_event=lambda _event: "RECORDED",
        start_checker=start_checker,
        commit_start=commit_result,
    )

    assert result["status"] == "CHECKER_STARTED"
    assert sent[0]["payload"]["candidate"] == {
        "kind": "commit",
        "commit": "c" * 40,
    }
    assert str(request["worker_result_path"]) in sent[0]["payload"]["evidence_files"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"message_id": "22222222-2222-4222-8222-222222222222"}),
        lambda value: value.update({"unexpected": True}),
        lambda value: value["blocker"].update({"unexpected": True}),
    ],
)
def test_inspector_rejects_mismatched_or_open_ended_noncompleted_worker_result(
    tmp_path: Path, mutate
) -> None:
    attempt, _endpoint, _checker = completion_fixture(tmp_path)
    (attempt / "completed.json").unlink()
    result = json.loads((attempt / "worker-result.json").read_text(encoding="utf-8"))
    result.update(
        {
            "status": "incomplete",
            "candidate": None,
            "next_payload": None,
            "blocker": {
                "phase": "git_commit",
                "cause": "GIT_COMMON_DIR_UNWRITABLE",
                "summary": "blocked",
                "evidence": ["native.stderr.txt"],
            },
        }
    )
    mutate(result)
    write_json(attempt / "worker-result.json", result)
    write_json(
        attempt / "failed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": MESSAGE_ID,
            "run_id": "RUN-A",
            "adapter": "dsh-worker",
            "status": "failed",
            "native_identity": {"worker_outcome": "incomplete"},
            "error_code": "DSH_WORKER_INCOMPLETE",
            "evidence": ["started.json", "worker-result.json"],
        },
    )

    with pytest.raises(CompletionError, match="non-completed Worker result"):
        inspect_worker_completion(
            attempt,
            runtime_projection(),
            observed_at="2026-09-23T00:04:00Z",
            cadence_seconds=240,
        )
