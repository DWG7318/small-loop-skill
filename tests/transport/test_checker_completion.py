from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from slk_transport.contracts import canonical_json_sha256
from slk_transport.native_activity import make_native_start

from test_contracts import endpoint_value


RUN_ID = "RUN-A"
GO_ID = "GO-001"
CHECKER_ID = "ROLE-checker"
WORKER_ID = "ROLE-worker"
SUPERVISOR_ID = "ROLE-supervisor"
CANDIDATE_MESSAGE_ID = "11111111-1111-4111-8111-111111111111"


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def worker_endpoint(tmp_path: Path) -> dict[str, object]:
    value = endpoint_value(role="worker", version=2)
    value.update({"run_id": RUN_ID, "role_instance_id": WORKER_ID})
    value["address"] = {
        "command": ["D:/DSH/dsh-slk.cmd"],
        "instance_id": "RUN-A-worker",
        "session_id": "session-worker",
        "runtime_root": str(tmp_path / "dsh-runtime"),
        "cwd": str(tmp_path),
        "timeout_seconds": 30,
    }
    return value


def supervisor_endpoint(tmp_path: Path) -> dict[str, object]:
    value = endpoint_value(role="supervisor", version=1)
    value.update({"run_id": RUN_ID, "role_instance_id": SUPERVISOR_ID})
    value["address"] = {
        "command": ["codex", "app-server"],
        "thread_id": "thread-supervisor",
        "cwd": str(tmp_path),
        "startup_timeout_seconds": 1,
        "turn_timeout_seconds": 1,
    }
    return value


def fixture(tmp_path: Path, *, final: bool = False) -> tuple[dict[str, object], Path]:
    current_cell = "CELL-002" if final else "CELL-001"
    d1_event_id = f"d1-pass-{current_cell.lower()}"
    cells = [
        {
            "cell_id": "CELL-001",
            "ordinal": 1,
            "title": "First",
            "objective": "First objective",
            "state": "d1_passed",
            "attempt": 1,
            "outcome": "PASS",
        },
        {
            "cell_id": "CELL-002",
            "ordinal": 2,
            "title": "Second",
            "objective": "Second objective",
            "state": "d1_passed" if final else "planned",
            "attempt": 1 if final else 0,
            "outcome": "PASS" if final else None,
        },
    ]
    projection = {
        "summary": {
            "run_id": RUN_ID,
            "slk_version": "4.4.0",
            "current_plan_revision": 1,
        },
        "runtime_snapshot": {
            "method_version": "4.4.0",
            "plan_revision": 1,
            "runtime_revision": 25,
            "token_sequence": 4,
            "token_holder_role_instance_id": CHECKER_ID,
            "latest_event_id": d1_event_id,
            "latest_message_id": CANDIDATE_MESSAGE_ID,
        },
        "go_nodes": [
            {
                "go_id": GO_ID,
                "ordinal": 1,
                "title": "Serial run",
                "objective": "Finish both cells",
                "state": "active",
                "outcome": None,
                "cell_nodes": cells,
            }
        ],
        "events": [
            {
                "event_id": d1_event_id,
                "event_type": "D1_PASSED",
                "author_role_instance_id": CHECKER_ID,
                "go_id": GO_ID,
                "cell_id": current_cell,
                "attempt": 1,
                "details_json": json.dumps(
                    {"verdict": "PASS", "candidate_message_id": CANDIDATE_MESSAGE_ID},
                    sort_keys=True,
                ),
            }
        ],
    }
    projection_path = write_json(tmp_path / "runtime.json", projection)
    endpoint = supervisor_endpoint(tmp_path) if final else worker_endpoint(tmp_path)
    endpoint_path = write_json(tmp_path / "target-endpoint.json", endpoint)
    credential = tmp_path / "checker.dpapi"
    credential.write_text("00", encoding="ascii")
    attempt_root = tmp_path / "attempts"
    attempt_root.mkdir()
    payload = (
        {
            "d1_event_id": d1_event_id,
            "required_cell_ids": ["CELL-001", "CELL-002"],
            "accepted_cell_ids": ["CELL-001", "CELL-002"],
            "final_candidate_message_id": CANDIDATE_MESSAGE_ID,
            "d2_criteria": ["Verify the complete serial result."],
            "evidence_refs": [str(projection_path)],
        }
        if final
        else {
            "cell_id": "CELL-002",
            "cell_ordinal": 2,
            "required_cell_count": 2,
            "task": "Implement the second planned CELL.",
            "d1_criteria": ["The second objective is satisfied."],
            "root_record_path": str(projection_path),
        }
    )
    request = {
        "schema_version": "slk.checker-completion-request/v1",
        "method_version": "4.4.0",
        "completion_invocation_id": "checker-completion-001",
        "run_id": RUN_ID,
        "go_id": GO_ID,
        "cell_id": current_cell,
        "target_cell_id": current_cell if final else "CELL-002",
        "attempt": 1,
        "plan_revision": 1,
        "runtime_revision": 25,
        "token_sequence": 4,
        "checker_role_instance_id": CHECKER_ID,
        "d1_event_id": d1_event_id,
        "route": "D2_READY" if final else "NEXT_CELL",
        "runtime_projection_path": str(projection_path.resolve()),
        "target_endpoint_path": str(endpoint_path.resolve()),
        "checker_credential_path": str(credential.resolve()),
        "state_command": ["slk-state"],
        "transport_command": ["slk-transport"],
        "handoff_attempt_root": str(attempt_root.resolve()),
        "payload": payload,
        "occurred_at": "2026-10-04T00:00:00Z",
    }
    return request, write_json(tmp_path / "checker-completion.json", request)


@pytest.mark.parametrize("version", ["4.4.0", "4.4.1"])
def test_compatible_patch_requires_exact_request_and_run_version(tmp_path, version):
    from slk_transport.checker_completion import _validate_request, _validate_boundary, CheckerCompletionError
    request, _ = fixture(tmp_path)
    request["method_version"] = version
    path = Path(request["runtime_projection_path"])
    projection = json.loads(path.read_text())
    projection["summary"]["slk_version"] = version
    projection["runtime_snapshot"]["method_version"] = version
    write_json(path, projection)
    assert _validate_request(request)["method_version"] == version
    _validate_boundary(request)
    projection["runtime_snapshot"]["method_version"] = "4.4.1" if version == "4.4.0" else "4.4.0"
    write_json(path, projection)
    with pytest.raises(CheckerCompletionError, match="runtime"):
        _validate_boundary(request)


def successful_runner(request: dict[str, object], commands: list[str]):
    def run(_command: list[str], arguments: list[str], *, credential: str | None):
        operation = arguments[0]
        commands.append(operation)
        if operation == "authenticate-role":
            return {
                "status": "authenticated",
                "run_id": RUN_ID,
                "role": "checker",
                "role_instance_id": CHECKER_ID,
                "runtime_revision": 25,
            }
        if operation == "send":
            endpoint_path = Path(arguments[arguments.index("--endpoint") + 1])
            envelope_path = Path(arguments[arguments.index("--envelope") + 1])
            root = Path(arguments[arguments.index("--attempt-root") + 1])
            endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
            envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
            attempt = root / RUN_ID / envelope["message_id"]
            write_json(attempt / "endpoint.json", endpoint)
            write_json(attempt / "envelope.json", envelope)
            write_json(
                attempt / "started.json",
                make_native_start(
                    adapter=endpoint["adapter"],
                    run_id=RUN_ID,
                    cell_id=envelope["cell_id"],
                    message_id=envelope["message_id"],
                    request_sha256=envelope["payload_sha256"],
                    native_request_sha256=envelope["payload_sha256"],
                    native_task_kind="test-native-task",
                    native_task_id="native-1",
                    native_task_status="RUNNING",
                    pid=os.getpid(),
                ),
            )
            return {
                "status": "started",
                "run_id": RUN_ID,
                "message_id": envelope["message_id"],
                "adapter": endpoint["adapter"],
                "evidence": str(attempt / "started.json"),
            }
        assert operation == "commit-delivery-start"
        assert credential == "slk_" + "d" * 64
        commit = json.loads(Path(arguments[-1]).read_text(encoding="utf-8"))
        target = WORKER_ID if request["route"] == "NEXT_CELL" else SUPERVISOR_ID
        return {
            "status": "committed",
            "run_id": RUN_ID,
            "runtime_revision": 26,
            "token_sequence": 5,
            "token_owner_role_instance_id": target,
            "event_id": commit["event_id"],
            "message_id": commit["message_id"],
        }

    return run


@pytest.mark.parametrize("final", [False, True])
def test_checker_pass_completes_only_after_target_start_and_atomic_commit(
    tmp_path: Path, final: bool
) -> None:
    from slk_transport.checker_completion import execute_checker_completion

    request, request_path = fixture(tmp_path, final=final)
    commands: list[str] = []
    result = execute_checker_completion(
        request,
        request_sha256=digest(request_path),
        request_path=request_path,
        run_json_command=successful_runner(request, commands),
        unprotect_credential=lambda _path: "slk_" + "d" * 64,
    )

    assert result["status"] == "CHECKER_COMPLETION_COMMITTED"
    assert result["route"] == ("D2_READY" if final else "NEXT_CELL")
    assert result["token_owner_role_instance_id"] == (
        SUPERVISOR_ID if final else WORKER_ID
    )
    assert commands == ["authenticate-role", "send", "commit-delivery-start"]
    receipt = json.loads(Path(result["commit_request_path"]).with_suffix(".result.json").read_text())
    assert receipt["status"] == "committed" and receipt["message_id"] == result["message_id"]


def test_next_cell_must_be_the_exact_next_required_cell(tmp_path: Path) -> None:
    from slk_transport.checker_completion import CheckerCompletionError, execute_checker_completion

    request, request_path = fixture(tmp_path)
    request["target_cell_id"] = "CELL-003"
    request["payload"]["cell_id"] = "CELL-003"  # type: ignore[index]
    write_json(request_path, request)

    with pytest.raises(CheckerCompletionError, match="next required CELL"):
        execute_checker_completion(
            request,
            request_sha256=digest(request_path),
            request_path=request_path,
            run_json_command=lambda *_args, **_kwargs: pytest.fail("invalid route reached a command"),
            unprotect_credential=lambda _path: pytest.fail("invalid route reached credential"),
        )


def test_d2_ready_rejects_any_required_cell_without_d1_pass(tmp_path: Path) -> None:
    from slk_transport.checker_completion import CheckerCompletionError, execute_checker_completion

    request, request_path = fixture(tmp_path, final=True)
    projection_path = Path(str(request["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    projection["go_nodes"][0]["cell_nodes"][0]["state"] = "rework_required"
    write_json(projection_path, projection)

    with pytest.raises(CheckerCompletionError, match="every required CELL"):
        execute_checker_completion(
            request,
            request_sha256=digest(request_path),
            request_path=request_path,
            run_json_command=lambda *_args, **_kwargs: pytest.fail("invalid D2 route reached a command"),
            unprotect_credential=lambda _path: pytest.fail("invalid D2 route reached credential"),
        )


def test_missing_native_start_never_commits_or_completes_checker(tmp_path: Path) -> None:
    from slk_transport.checker_completion import CheckerCompletionError, execute_checker_completion

    request, request_path = fixture(tmp_path)
    commands: list[str] = []

    def run(_command: list[str], arguments: list[str], *, credential: str | None):
        commands.append(arguments[0])
        if arguments[0] == "authenticate-role":
            return {
                "status": "authenticated",
                "run_id": RUN_ID,
                "role": "checker",
                "role_instance_id": CHECKER_ID,
                "runtime_revision": 25,
            }
        if arguments[0] == "send":
            return {"status": "started", "run_id": RUN_ID, "message_id": "missing"}
        pytest.fail("commit must not run without native start")

    with pytest.raises(CheckerCompletionError, match="start"):
        execute_checker_completion(
            request,
            request_sha256=digest(request_path),
            request_path=request_path,
            run_json_command=run,
            unprotect_credential=lambda _path: "slk_" + "d" * 64,
        )
    assert commands == ["authenticate-role", "send"]


def test_pass_completion_rejects_changed_or_nonpass_d1(tmp_path: Path) -> None:
    from slk_transport.checker_completion import CheckerCompletionError, execute_checker_completion

    request, request_path = fixture(tmp_path)
    projection_path = Path(str(request["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    projection["events"][0]["event_type"] = "D1_FAILED"
    write_json(projection_path, projection)

    with pytest.raises(CheckerCompletionError, match="D1 PASS"):
        execute_checker_completion(
            request,
            request_sha256=digest(request_path),
            request_path=request_path,
            run_json_command=lambda *_args, **_kwargs: pytest.fail("non-PASS reached a command"),
            unprotect_credential=lambda _path: pytest.fail("non-PASS reached credential"),
        )


def test_final_d2_ready_prepares_exact_desktop_bridge_after_active_writer(
    tmp_path: Path,
) -> None:
    from slk_transport.checker_completion import execute_checker_completion

    request, request_path = fixture(tmp_path, final=True)
    commands: list[str] = []

    def run(_command: list[str], arguments: list[str], *, credential: str | None):
        operation = arguments[0]
        commands.append(operation)
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
        envelope_path = Path(arguments[arguments.index("--envelope") + 1])
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        return {
            "schema_version": "slk.transport-desktop-current-turn-request/v1",
            "status": "PREPARED",
            "run_id": RUN_ID,
            "go_id": GO_ID,
            "cell_id": "CELL-002",
            "original_message_id": envelope["message_id"],
            "recovery_message_id": "desktop-d2-ready-1",
            "target_thread_id": "thread-supervisor",
            "payload_type": "D2_READY",
            "payload_sha256": envelope["payload_sha256"],
            "prompt": "exact D2 ready bridge prompt",
            "prompt_sha256": "c" * 64,
        }

    result = execute_checker_completion(
        request,
        request_sha256=digest(request_path),
        request_path=request_path,
        run_json_command=run,
        unprotect_credential=lambda _path: "slk_" + "d" * 64,
    )

    assert result["status"] == "DESKTOP_BRIDGE_REQUIRED"
    assert result["route"] == "D2_READY"
    assert result["desktop_request"]["target_thread_id"] == "thread-supervisor"
    assert commands == [
        "authenticate-role",
        "send",
        "retry-exact",
        "prepare-desktop-current-turn",
    ]


def test_final_d2_ready_commits_only_after_exact_desktop_bridge_start(
    tmp_path: Path,
) -> None:
    from slk_transport.checker_completion import (
        _materialize,
        _validate_boundary,
        _validate_request,
        execute_checker_completion,
    )

    request, request_path = fixture(tmp_path, final=True)
    prepared = _materialize(_validate_request(request), _validate_boundary(request))
    delivery = Path(str(request["handoff_attempt_root"])) / RUN_ID / prepared["envelope"]["message_id"]
    desktop_request_path = delivery / "recovery" / "desktop-current-turn" / "request.json"
    desktop_started_path = delivery / "recovery" / "desktop-current-turn" / "started.json"
    write_json(
        desktop_request_path,
        {
            "schema_version": "slk.transport-desktop-current-turn-request/v1",
            "status": "PREPARED",
            "run_id": RUN_ID,
            "go_id": GO_ID,
            "cell_id": "CELL-002",
            "original_message_id": prepared["envelope"]["message_id"],
            "recovery_message_id": "desktop-d2-ready-2",
            "target_thread_id": "thread-supervisor",
            "payload_type": "D2_READY",
            "payload_sha256": prepared["envelope"]["payload_sha256"],
            "prompt": "exact D2 ready bridge prompt",
            "prompt_sha256": "c" * 64,
        },
    )
    host_receipt = write_json(tmp_path / "host-receipt.json", {"schema_version": "host-receipt"})
    commands: list[str] = []

    def run(_command: list[str], arguments: list[str], *, credential: str | None):
        operation = arguments[0]
        commands.append(operation)
        if operation == "authenticate-role":
            return {
                "status": "authenticated",
                "run_id": RUN_ID,
                "role": "checker",
                "role_instance_id": CHECKER_ID,
                "runtime_revision": 25,
            }
        if operation == "complete-desktop-current-turn":
            write_json(
                desktop_started_path,
                make_native_start(
                    adapter="codex-app-server",
                    run_id=RUN_ID,
                    cell_id="CELL-002",
                    message_id="desktop-d2-ready-2",
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
                "recovery_message_id": "desktop-d2-ready-2",
                "run_id": RUN_ID,
                "payload_sha256": prepared["envelope"]["payload_sha256"],
                "endpoint_sha256": "d" * 64,
                "envelope_sha256": "e" * 64,
            }
        assert operation == "commit-delivery-start"
        assert credential == "slk_" + "d" * 64
        commit = json.loads(Path(arguments[-1]).read_text(encoding="utf-8"))
        assert commit["message_id"] == "desktop-d2-ready-2"
        return {
            "status": "committed",
            "run_id": RUN_ID,
            "runtime_revision": 26,
            "token_sequence": 5,
            "token_owner_role_instance_id": SUPERVISOR_ID,
            "message_id": "desktop-d2-ready-2",
        }

    result = execute_checker_completion(
        request,
        request_sha256=digest(request_path),
        request_path=request_path,
        host_receipt_path=host_receipt,
        run_json_command=run,
        unprotect_credential=lambda _path: "slk_" + "d" * 64,
    )

    assert result["status"] == "CHECKER_COMPLETION_COMMITTED"
    assert result["message_id"] == "desktop-d2-ready-2"
    assert commands == ["authenticate-role", "complete-desktop-current-turn", "commit-delivery-start"]
