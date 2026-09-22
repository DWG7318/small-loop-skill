from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from slk_transport.worker_completion import (
    CompletionError,
    build_continuation_request,
    inspect_worker_completion,
    resume_worker_continuation,
    run_worker_continuation,
)

from test_contracts import MESSAGE_ID, endpoint_value, envelope_value


FAKE_DSH = Path(__file__).with_name("fake_dsh.py")


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


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
        "summary": {"run_id": "RUN-A", "slk_version": "4.2.4", "plan_revision": 1},
        "runtime_snapshot": {
            "plan_revision": 1,
            "runtime_revision": 7,
            "token_sequence": 14,
            "token_holder_role_instance_id": token_owner,
            "latest_message_id": MESSAGE_ID,
        },
        "events": events,
        "operational_observations": [],
    }


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
    assert inspect_worker_completion(
        attempt,
        runtime_projection(event_types=["D1_INCOMPLETE"], token_owner="ROLE-checker"),
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

    def commit_start(value: dict[str, object]) -> str:
        commits.append(value)
        return "COMMITTED"

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
        commit_start=lambda _request: "IDEMPOTENT_REPLAY",
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
