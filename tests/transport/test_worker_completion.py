from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest
import slk_transport.worker_completion as worker_completion
import slk_transport.subprocess_watch as subprocess_watch

from slk_transport.adapters.dsh import DshAdapter
from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.contracts import Endpoint, Envelope, canonical_json_sha256
from slk_transport.dispatcher import dispatch_once
from slk_transport.task_file import canonical_task_bytes
from slk_transport.worker_completion import (
    CompletionError,
    _decode_dpapi_plaintext,
    inspect_worker_completion,
    _stable_id,
)
from slk_transport.native_activity import make_native_start

from test_contracts import MESSAGE_ID, endpoint_value, envelope_value


FAKE_DSH = Path(__file__).with_name("fake_dsh.py")
FAKE_OCRV = Path(__file__).with_name("fake_ocrv.py")
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


def actual_state_call(
    state_binary: Path,
    config_path: Path,
    arguments: list[object],
    *,
    credential: str | None = None,
) -> dict[str, object]:
    environment = os.environ.copy()
    environment["SLK_CONFIG_PATH"] = str(config_path)
    environment.pop("SLK_ROLE_CREDENTIAL", None)
    if credential is not None:
        environment["SLK_ROLE_CREDENTIAL"] = credential
    completed = subprocess.run(
        [str(state_binary), *map(str, arguments)],
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout or completed.stderr)
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


def actual_worker_state(
    tmp_path: Path,
    *, credentials: dict | None = None, second_cell: bool = False,
) -> tuple[Path, Path, str, str, int]:
    suffix = ".exe" if os.name == "nt" else ""
    state_binary = Path(__file__).parents[2] / "target" / "debug" / f"slk-state{suffix}"
    if not state_binary.is_file():
        pytest.skip("build slk-state before the real revision integration test")
    config_path = tmp_path / "state-config" / "config.json"
    actual_state_call(
        state_binary,
        config_path,
        ["configure", "--data-root", tmp_path / "state-data"],
    )
    initialized = actual_state_call(
        state_binary,
        config_path,
        [
            "init-run",
            "--request",
            write_json(
                tmp_path / "init-run.json",
                {
                    "project": {
                        "project_id": "project-a",
                        "name": "Project A",
                        "repository_url": None,
                        "last_known_path": str(tmp_path),
                    },
                    "run_id": "RUN-A",
                    "goal": "prove Worker handoff revision closure",
                    "boundaries": {},
                    "go_nodes": [
                        {
                            "go_id": "GO-001",
                            "ordinal": 1,
                            "title": "GO",
                            "objective": "Objective",
                        }
                    ],
                    "cell_nodes": [
                        {
                            "go_id": "GO-001",
                            "cell_id": "CELL-001",
                            "ordinal": 1,
                            "title": "CELL",
                            "objective": "Objective",
                        },
                        *([{"go_id":"GO-001", "cell_id":"CELL-002", "ordinal":2,
                            "title":"second", "objective":"next bounded change"}] if second_cell else []),
                    ],
                    "supervisor": {
                        "role_instance_id": "RUN-A-supervisor-001",
                        "role": "supervisor",
                        "agent_runtime": "codex",
                        "provider": "openai",
                        "model": "gpt-6.1-sol",
                        "reasoning": "xhigh",
                        "session_id": "thread-a",
                    },
                    "supervisor_endpoint": {
                        "endpoint_version": 1,
                        "transport_adapter": "codex-app-server",
                        "host_identity": "host-a",
                        "session_id": "thread-a",
                        "native_address": {"thread_id": "thread-a"},
                    },
                    "occurred_at": "2026-09-23T00:00:00Z",
                },
            ),
        ],
    )
    supervisor_credential = str(initialized["supervisor_credential"])

    def role_request(role: str) -> dict[str, object]:
        role_instance_id = f"RUN-A-{role}-001"
        checker = role == "checker"
        return {
            "event_id": f"register-{role}",
            "run_id": "RUN-A",
            "identity": {
                "role_instance_id": role_instance_id,
                "role": role,
                "agent_runtime": "ocrv" if checker else "dsh",
                "provider": "dashscope-tokenplan" if checker else "deepseek",
                "model": "qwen3.8-max" if checker else "deepseek-v4-flash",
                "reasoning": "provider-default",
                "session_id": f"session-{role}",
            },
            "endpoint": {
                "endpoint_version": 1,
                "transport_adapter": "ocrv-checker" if checker else "dsh-worker",
                "host_identity": "host-a",
                "session_id": f"session-{role}",
                "native_address": {"session_id": f"session-{role}"},
            },
            "occurred_at": "2026-09-23T00:00:01Z",
        }

    checker = actual_state_call(
        state_binary,
        config_path,
        ["register-role", "--request", write_json(tmp_path / "register-checker.json", role_request("checker"))],
        credential=supervisor_credential,
    )
    checker_credential = str(checker["role_credential"])
    worker = actual_state_call(
        state_binary,
        config_path,
        ["register-role", "--request", write_json(tmp_path / "register-worker.json", role_request("worker"))],
        credential=checker_credential,
    )
    worker_credential = str(worker["role_credential"])
    if credentials is not None:
        credentials.update(supervisor=supervisor_credential, worker=worker_credential, checker=checker_credential)

    def commit_start(
        *,
        suffix_name: str,
        sender_role: str,
        sender_id: str,
        sender_credential: str,
        receiver_role: str,
        receiver_id: str,
        adapter: str,
        message_id: str,
        token_sequence: int,
        expected_runtime_revision: int,
    ) -> dict[str, object]:
        payload = {"stage": suffix_name}
        payload_sha = canonical_json_sha256(payload)
        evidence_root = tmp_path / f"start-{suffix_name}"
        endpoint_path = write_json(evidence_root / "endpoint.json", {"receiver": receiver_id})
        envelope_path = write_json(evidence_root / "envelope.json", payload)
        started_path = write_json(
            evidence_root / "started.json",
            make_native_start(
                adapter=adapter,
                run_id="RUN-A",
                cell_id="CELL-001",
                message_id=message_id,
                request_sha256=payload_sha,
                native_request_sha256="c" * 64,
                native_task_kind="ocrv-review" if receiver_role == "checker" else "dsh-session",
                native_task_id=f"native-{suffix_name}",
                native_task_status="RUNNING",
                pid=os.getpid(),
            ),
        )
        request = {
            "event_id": f"transport-started-{suffix_name}",
            "transport_receipt_id": f"transport-receipt-{suffix_name}",
            "run_id": "RUN-A",
            "go_id": "GO-001",
            "cell_id": "CELL-001",
            "attempt": 1,
            "plan_revision": 1,
            "expected_runtime_revision": expected_runtime_revision,
            "message_id": message_id,
            "token_sequence": token_sequence,
            "from_role_instance_id": sender_id,
            "to_role_instance_id": receiver_id,
            "endpoint_version": 1,
            "payload_type": "CELL_DISPATCH" if sender_role == "supervisor" else "WORKER_TASK",
            "payload_sha256": payload_sha,
            "start_evidence": {
                "evidence_id": f"native-start-{suffix_name}",
                "stored_path": str(started_path.resolve()),
                "sha256": hashlib.sha256(started_path.read_bytes()).hexdigest(),
                "message_id": message_id,
                "endpoint_sha256": hashlib.sha256(endpoint_path.read_bytes()).hexdigest(),
                "envelope_sha256": hashlib.sha256(envelope_path.read_bytes()).hexdigest(),
                "native_status": "STARTED",
            },
            "occurred_at": "2026-09-23T00:00:02Z",
        }
        return actual_state_call(
            state_binary,
            config_path,
            ["commit-delivery-start", "--request", write_json(tmp_path / f"commit-{suffix_name}.json", request)],
            credential=sender_credential,
        )

    supervisor_auth = actual_state_call(
        state_binary,
        config_path,
        ["authenticate-role", "--run-id", "RUN-A", "--role-instance-id", "RUN-A-supervisor-001"],
        credential=supervisor_credential,
    )
    checker_start = commit_start(
        suffix_name="checker",
        sender_role="supervisor",
        sender_id="RUN-A-supervisor-001",
        sender_credential=supervisor_credential,
        receiver_role="checker",
        receiver_id="RUN-A-checker-001",
        adapter="ocrv-checker",
        message_id=str(uuid.uuid4()),
        token_sequence=2,
        expected_runtime_revision=int(supervisor_auth["runtime_revision"]),
    )
    worker_start = commit_start(
        suffix_name="worker",
        sender_role="checker",
        sender_id="RUN-A-checker-001",
        sender_credential=checker_credential,
        receiver_role="worker",
        receiver_id="RUN-A-worker-001",
        adapter="dsh-worker",
        message_id=MESSAGE_ID,
        token_sequence=3,
        expected_runtime_revision=int(checker_start["runtime_revision"]),
    )
    return (
        state_binary,
        config_path,
        worker_credential,
        checker_credential,
        int(worker_start["runtime_revision"]),
    )


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


def test_json_command_forces_child_utf8_and_parses_non_ascii_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert kwargs.get("text") is not True
        assert "encoding" not in kwargs
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment["PYTHONIOENCODING"] == "utf-8"
        assert environment["PYTHONUTF8"] == "1"
        return subprocess.CompletedProcess(
            command,
            2,
            stdout=json.dumps(
                {"status": "rejected", "error_code": "INPUT_INVALID", "message": "拒绝访问"},
                ensure_ascii=False,
            ).encode("utf-8"),
            stderr=b"",
        )

    monkeypatch.setattr(worker_completion.subprocess, "run", run)

    result = worker_completion._run_json_command(["tool"], ["send"], credential=None)

    assert result["message"] == "拒绝访问"
    assert result["_slk_command"]["process_exit"] == 2


@pytest.mark.parametrize(
    ("credential_scope", "expected_variable"),
    [("role", "SLK_ROLE_CREDENTIAL"), ("overwatcher", "SLK_OVERWATCHER_CREDENTIAL")],
)
def test_json_command_routes_one_credential_scope_without_cross_leak(
    monkeypatch: pytest.MonkeyPatch, credential_scope: str, expected_variable: str,
) -> None:
    monkeypatch.setenv("SLK_ROLE_CREDENTIAL", "parent-role")
    monkeypatch.setenv("SLK_OVERWATCHER_CREDENTIAL", "parent-overwatcher")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment[expected_variable] == VALID_CREDENTIAL
        other = ({"SLK_ROLE_CREDENTIAL", "SLK_OVERWATCHER_CREDENTIAL"} - {expected_variable}).pop()
        assert other not in environment
        return subprocess.CompletedProcess(command, 0, stdout=b'{"status":"ok"}', stderr=b"")

    monkeypatch.setattr(worker_completion.subprocess, "run", run)
    result = worker_completion._run_json_command(
        ["tool"], ["send"], credential=VALID_CREDENTIAL, credential_scope=credential_scope,
    )
    assert result["status"] == "ok"


def test_json_command_scopes_state_config_to_one_child_without_parent_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = tmp_path / "product-config.json"
    source = tmp_path / "source-config.json"
    product.write_text("{}", encoding="utf-8")
    source.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SLK_CONFIG_PATH", str(product.resolve()))
    command = [sys.executable, "-c",
        "import json,os; print(json.dumps({'config': os.environ.get('SLK_CONFIG_PATH')}))"]

    isolated = worker_completion._run_json_command(
        command, [], credential=None, state_config_path=str(source.resolve()),
    )
    inherited = worker_completion._run_json_command(command, [], credential=None)

    assert isolated["config"] == str(source.resolve())
    assert inherited["config"] == str(product.resolve())
    assert os.environ["SLK_CONFIG_PATH"] == str(product.resolve())


def test_projection_forwards_exact_state_config_to_the_query_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "slk-state.exe"
    query = tmp_path / "slk-bi-query.exe"
    config = tmp_path / "source-config.json"
    state.write_bytes(b"")
    query.write_bytes(b"")
    config.write_text("{}", encoding="utf-8")
    captured = {}

    def run(command, arguments, *, credential, state_config_path=None, **_kwargs):
        captured.update(command=command, arguments=arguments,
                        state_config_path=state_config_path)
        return {"run_id": "RUN-SOURCE", "_slk_command": {"process_exit": 0}}

    monkeypatch.setattr(worker_completion, "_run_json_command", run)
    result = worker_completion._default_load_current_projection(
        "RUN-SOURCE", [str(state)], state_config_path=str(config.resolve()),
    )

    assert result == {"run_id": "RUN-SOURCE"}
    assert captured["command"] == [str(query.resolve())]
    assert captured["state_config_path"] == str(config.resolve())


def test_json_command_rejects_non_utf8_without_secondary_decode_or_none_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker_completion.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["tool"],
            2,
            stdout=None,
            stderr='{"status":"rejected","message":"拒绝访问"}'.encode("gbk"),
        ),
    )

    with pytest.raises(CompletionError) as rejected:
        worker_completion._run_json_command(["tool"], ["send"], credential=None)

    assert rejected.value.error_code == "WORKER_CONTINUATION_COMMAND_ENCODING_INVALID"
    assert "stderr is not UTF-8" in str(rejected.value)


def test_json_command_empty_binary_output_has_one_closed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker_completion.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["tool"], 2, stdout=None, stderr=None
        ),
    )

    with pytest.raises(CompletionError) as rejected:
        worker_completion._run_json_command(["tool"], ["send"], credential=None)

    assert rejected.value.error_code == "WORKER_CONTINUATION_COMMAND_FAILED"
    assert "no parseable JSON" in str(rejected.value)


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
            "schema_version": "slk.native-start/v2",
            "status": "STARTED",
            "adapter": "dsh-worker",
            "run_id": "RUN-A",
            "cell_id": "CELL-001",
            "message_id": envelope["message_id"],
            "request_sha256": envelope["payload_sha256"],
            "native_request_sha256": "b" * 64,
            "observed_at": "2026-09-23T00:00:00Z",
            "process": {"pid": 1, "creation_time": "fixture:1"},
            "native_task": {
                "kind": "dsh-session",
                "id": endpoint["address"]["session_id"],
                "status": "RUNNING",
            },
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
    token_owner: str = "RUN-A-worker-001",
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
        "summary": {"run_id": "RUN-A", "slk_version": "4.4.0", "plan_revision": 1},
        "runtime_snapshot": {
            "method_version": "4.4.0",
            "plan_revision": 1,
            "runtime_revision": 7,
            "token_sequence": 14,
            "token_holder_role_instance_id": token_owner,
            "latest_message_id": MESSAGE_ID,
        },
        "events": events,
        "operational_observations": [],
    }


@pytest.mark.parametrize(
    ("outcome", "error_code", "exit_code", "expected_status"),
    [
        ("execution_failure", "DSH_EXIT_NONZERO", 42, "WORKER_EXECUTION_FAILURE"),
        ("timed_out", "DSH_TIMEOUT", None, "WORKER_TIMED_OUT"),
    ],
)
def test_worker_inspection_preserves_native_runtime_failure_without_worker_claim(
    tmp_path: Path,
    outcome: str,
    error_code: str,
    exit_code: int | None,
    expected_status: str,
) -> None:
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    (attempt / "completed.json").unlink()
    (attempt / "worker-result.json").unlink()
    receipt = write_json(
        attempt / "native-execution.json",
        {
            "schema_version": "slk.native-execution-outcome/v1",
            "adapter": "dsh-worker",
            "run_id": "RUN-A",
            "cell_id": "CELL-001",
            "message_id": MESSAGE_ID,
            "instance_id": endpoint["address"]["instance_id"],
            "session_id": endpoint["address"]["session_id"],
            "status": outcome,
            "started_at": "2026-09-23T00:00:00Z",
            "ended_at": "2026-09-23T00:00:05Z",
            "duration_ms": 5000,
            "exit_code": exit_code,
            "error_code": error_code,
            "stdout_sha256": "a" * 64,
            "stderr_sha256": "b" * 64,
        },
    )
    write_json(
        attempt / "failed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": MESSAGE_ID,
            "run_id": "RUN-A",
            "adapter": "dsh-worker",
            "status": "failed",
            "native_identity": {
                "instance_id": endpoint["address"]["instance_id"],
                "session_id": endpoint["address"]["session_id"],
                "exit_code": exit_code,
                "runtime_outcome": outcome,
                "duration_ms": 5000,
                "error_code": error_code,
                "execution_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            },
            "error_code": error_code,
            "evidence": ["started.json", "native-execution.json"],
        },
    )

    result = inspect_worker_completion(
        attempt,
        runtime_projection(),
        observed_at="2026-09-23T00:00:06Z",
        cadence_seconds=60,
    )

    assert result["status"] == expected_status
    assert result["worker_outcome"] is None
    assert result["native_status"] == "failed"
    assert result["native_identity"]["exit_code"] == exit_code
    assert result["blocker"]["cause"] == error_code
    assert result["blocker"]["evidence"] == [str(attempt / "failed.json")]


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


def test_explicit_host_handoff_failure_is_not_hidden_by_completion_grace(tmp_path: Path) -> None:
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    failure = attempt / "role-host" / "failure-ROLE_HOST_START_INVALID.json"
    write_json(failure, {
        "status": "HOST_HANDOFF_FAILED",
        "run_id": "RUN-A",
        "source_message_id": MESSAGE_ID,
        "error_code": "ROLE_HOST_START_INVALID",
    })

    result = inspect_worker_completion(
        attempt,
        runtime_projection(token_owner=str(endpoint["role_instance_id"])),
        observed_at="2026-09-23T00:00:01Z",
        cadence_seconds=240,
    )

    assert result["status"] == "WORKER_COMPLETION_HANDOFF_MISSING"
    assert result["grace_started_at"] is None
    assert result["blocker"]["cause"] == "ROLE_HOST_START_INVALID"
    assert result["blocker"]["evidence"] == [str(failure.resolve())]


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
        native_inspector=lambda *_args, **_kwargs: {"status": "ACTIVE"},
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


def test_dead_worker_native_turn_is_not_reported_as_in_progress(tmp_path: Path) -> None:
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    (attempt / "completed.json").unlink()
    (attempt / "worker-result.json").unlink()

    result = inspect_worker_completion(
        attempt,
        runtime_projection(token_owner=str(endpoint["role_instance_id"])),
        observed_at="2026-09-23T00:10:00Z",
        cadence_seconds=240,
        native_inspector=lambda *_args, **_kwargs: {"status": "DEAD_WITHOUT_TERMINAL"},
    )

    assert result["status"] == "NATIVE_TURN_ORPHANED"
    assert result["worker_outcome"] is None
    assert result["blocker"]["cause"] == "NATIVE_TURN_ORPHANED"
    assert result["candidate"] is None


@pytest.mark.parametrize("error", ["NATIVE_ACTIVITY_STALE", "NATIVE_ACTIVITY_MISSING", "NATIVE_ACTIVITY_FROM_FUTURE", "PROCESS_PROBE_FAILED"])
def test_unprovable_native_observation_is_unknown_not_worker_incomplete(tmp_path: Path, error: str) -> None:
    import jsonschema
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    (attempt / "completed.json").unlink()
    (attempt / "worker-result.json").unlink()
    result = inspect_worker_completion(
        attempt, runtime_projection(token_owner=str(endpoint["role_instance_id"])),
        observed_at="2026-09-23T00:10:00Z", cadence_seconds=600,
        native_inspector=lambda *_args, **_kwargs: {"status": "UNKNOWN", "error": error},
    )
    assert result["status"] == "UNKNOWN" and result["worker_outcome"] is None
    assert result["blocker"]["cause"] == error
    schema = json.loads((Path(__file__).resolve().parents[2] / "docs/contracts/slk-worker-completion-inspection.schema.json").read_text())
    jsonschema.validate(result, schema)


@pytest.mark.parametrize("exception", [PermissionError("native evidence access denied"), ValueError("malformed native evidence")])
def test_native_observation_exception_does_not_create_engineering_result(tmp_path: Path, exception: Exception) -> None:
    attempt, endpoint, _checker = completion_fixture(tmp_path)
    (attempt / "completed.json").unlink()
    (attempt / "worker-result.json").unlink()
    def unavailable(*_args, **_kwargs):
        raise exception
    result = inspect_worker_completion(
        attempt, runtime_projection(token_owner=str(endpoint["role_instance_id"])),
        observed_at="2026-09-23T00:10:00Z", cadence_seconds=600, native_inspector=unavailable,
    )
    assert result["status"] == "UNKNOWN" and result["worker_outcome"] is None
    assert str(exception) in result["blocker"]["cause"]


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


def test_authoritative_token_resolver_preserves_only_the_exact_initial_supervisor_boundary():
    projection = {"run_id": "RUN-A",
        "summary": {"run_id": "RUN-A", "slk_version": "4.4.2", "current_plan_revision": 1},
        "runtime_snapshot": {"run_id": "RUN-A", "method_version": "4.4.2", "plan_revision": 1,
            "runtime_revision": 1, "token_sequence": 1,
            "token_holder_role_instance_id": "RUN-A-supervisor", "latest_message_id": None},
        "roles": [{"role": "supervisor", "role_instance_id": "RUN-A-supervisor", "lifecycle": "active"}],
        "token_history": [{"event_type": "TOKEN_CREATED", "token_sequence": 1,
            "to_role_instance_id": "RUN-A-supervisor", "from_role_instance_id": None,
            "message_id": None, "go_id": None, "cell_id": None}], "events": []}

    boundary = worker_completion.resolve_authoritative_token_boundary(
        projection, run_id="RUN-A", plan_revision=1)
    assert boundary == {"message_id": None, "token_sequence": 1,
        "holder_role_instance_id": "RUN-A-supervisor", "source": "TOKEN_CREATED",
        "go_id": None, "cell_id": None}

    for mutation in ("wrong-holder", "created-message", "hidden-handoff"):
        changed = copy.deepcopy(projection)
        if mutation == "wrong-holder":
            changed["token_history"][0]["to_role_instance_id"] = "RUN-A-worker"
        elif mutation == "created-message":
            changed["token_history"][0]["message_id"] = "not-an-initial-boundary"
        else:
            changed["token_history"].append({"event_type": "TOKEN_HANDED_OFF", "token_sequence": 2,
                "to_role_instance_id": "RUN-A-checker", "from_role_instance_id": "RUN-A-supervisor",
                "message_id": "handoff", "go_id": "GO-001", "cell_id": "CELL-001"})
        with pytest.raises(CompletionError) as rejected:
            worker_completion.resolve_authoritative_token_boundary(changed, run_id="RUN-A", plan_revision=1)
        assert rejected.value.error_code == "AUTHORITATIVE_TOKEN_BOUNDARY_INVALID"


def test_authoritative_token_resolver_rejects_non_null_snapshot_that_conflicts_with_newer_history():
    projection = {"run_id": "RUN-A",
        "summary": {"run_id": "RUN-A", "slk_version": "4.4.2", "current_plan_revision": 1},
        "runtime_snapshot": {"run_id": "RUN-A", "method_version": "4.4.2", "plan_revision": 1,
            "runtime_revision": 4, "token_sequence": 2,
            "token_holder_role_instance_id": "RUN-A-checker", "latest_message_id": "message-2"},
        "token_history": [
            {"event_type": "TOKEN_HANDED_OFF", "token_sequence": 2, "message_id": "message-2",
             "to_role_instance_id": "RUN-A-checker"},
            {"event_type": "TOKEN_HANDED_OFF", "token_sequence": 3, "message_id": "message-3",
             "to_role_instance_id": "RUN-A-worker"}], "events": []}
    with pytest.raises(CompletionError) as rejected:
        worker_completion.resolve_authoritative_token_boundary(projection, run_id="RUN-A", plan_revision=1)
    assert rejected.value.error_code == "AUTHORITATIVE_TOKEN_BOUNDARY_INVALID"
