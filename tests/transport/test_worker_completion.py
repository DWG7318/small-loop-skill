from __future__ import annotations

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

from slk_transport.adapters.dsh import DshAdapter
from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.contracts import Endpoint, Envelope, canonical_json_sha256
from slk_transport.dispatcher import dispatch_once
from slk_transport.task_file import canonical_task_bytes
from slk_transport.worker_completion import (
    CompletionError,
    _activate_staged_checker,
    _decode_dpapi_plaintext,
    build_continuation_request,
    execute_checker_recovery,
    inspect_worker_completion,
    resume_worker_continuation,
    run_worker_continuation,
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
                        }
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


def checker_recovery_request(tmp_path: Path) -> dict[str, object]:
    attempt, _worker, checker = completion_fixture(tmp_path)
    projection_path = write_json(tmp_path / "runtime-projection.json", runtime_projection())
    return {
        "schema_version": "slk.ocrv-worker-recovery-request/v1",
        "method_version": "4.4.0",
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
        assert continuation["method_version"] == "4.4.0"
        return {
            "status": "CHECKER_DELIVERY_READY",
            "source_message_id": continuation["source_message_id"],
            "candidate_message_id": "candidate-message-1",
            "runtime_revision": 10,
            "endpoint_path": str(tmp_path / "checker-endpoint.json"),
            "envelope_path": str(tmp_path / "candidate-envelope.json"),
            "attempt_root": str(tmp_path / "checker-attempts"),
        }

    def activate(outcome: dict[str, object], continuation: dict[str, object]) -> dict[str, object]:
        calls.append("activate")
        assert outcome["status"] == "CHECKER_DELIVERY_READY"
        assert continuation["method_version"] == "4.4.0"
        return {
            "status": "CHECKER_STARTED",
            "runtime_revision": 11,
            "candidate_message_id": outcome["candidate_message_id"],
            "token_sequence": 15,
            "checker_token_already_committed": False,
            "native_attempt_path": str(tmp_path / "checker-attempts" / "RUN-A" / "candidate-message-1"),
        }

    def record(
        activation: dict[str, object],
        continuation: dict[str, object],
        credential: Path,
        timeout: float,
    ) -> dict[str, object]:
        calls.append("record")
        assert activation["status"] == "CHECKER_STARTED"
        assert continuation["method_version"] == "4.4.0"
        assert credential.name == "checker.dpapi"
        assert timeout == 30
        return {
            "status": "CHECKER_D1_RECORDED",
            "d1_verdict": "PASS",
            "d1_event_type": "D1_PASSED",
            "native_result_path": str(tmp_path / "ocrv-result.json"),
        }

    result = execute_checker_recovery(
        request,
        request_sha256="a" * 64,
        authenticate_checker=authenticate,
        resume_continuation=resume,
        activate_checker=activate,
        record_checker_d1=record,
    )

    assert calls == ["authenticate", "resume", "activate", "record"]
    assert result["status"] == "CHECKER_D1_RECORDED"
    assert result["checker_role_instance_id"] == request["checker_role_instance_id"]


def test_original_checker_path_consumes_commit_only_activation_without_restarting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = checker_recovery_request(tmp_path)
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(request["checker_role_instance_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(request["checker_endpoint_version"]))
    calls: list[str] = []

    def load_activation(continuation: dict[str, object], revision: int) -> dict[str, object]:
        calls.append("load-commit-only")
        assert revision == 14
        return {
            "status": "CHECKER_STARTED",
            "runtime_revision": 14,
            "token_sequence": 15,
            "candidate_message_id": _stable_id(str(continuation["source_message_id"]), "candidate-ready"),
            "checker_token_already_committed": False,
            "native_attempt_path": str(tmp_path / "existing-ocrv-attempt"),
        }

    result = execute_checker_recovery(
        request,
        request_sha256="e" * 64,
        authenticate_checker=lambda *_args: {
            "status": "authenticated",
            "role": "checker",
            "role_instance_id": request["checker_role_instance_id"],
            "runtime_revision": 14,
        },
        resume_continuation=lambda _request: pytest.fail("Worker must not restart"),
        activate_checker=lambda *_args: pytest.fail("OCRV must not restart"),
        load_committed_activation=load_activation,
        record_checker_d1=lambda *_args: calls.append("record-d1")
        or {
            "status": "CHECKER_D1_RECORDED",
            "d1_verdict": "FAIL",
            "d1_event_type": "D1_FAILED",
            "native_result_path": str(tmp_path / "existing-ocrv-attempt" / "ocrv-result.json"),
        },
    )

    assert calls == ["load-commit-only", "record-d1"]
    assert result["d1_verdict"] == "FAIL"
    assert result["runtime_revision"] == 14


def test_standard_terminal_consumer_restores_original_checker_host_without_starting_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = checker_recovery_request(tmp_path)
    request_path = write_json(tmp_path / "original-checker-recovery.json", request)
    request_sha256 = hashlib.sha256(request_path.read_bytes()).hexdigest()
    recovery_root = tmp_path / "commit-only-root"
    write_json(
        recovery_root / "commit-only-recovery" / "result.json",
        {"runtime_revision": 14},
    )
    monkeypatch.setattr(worker_completion, "build_continuation_request", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(worker_completion, "_continuation_root", lambda _continuation: recovery_root)
    monkeypatch.setattr(
        worker_completion,
        "_load_commit_only_checker_activation",
        lambda _continuation, revision: {"runtime_revision": revision},
    )
    monkeypatch.setenv("SLK_ROLE_CREDENTIAL", "must-not-leak")
    monkeypatch.setenv("SLK_OVERWATCHER_CREDENTIAL", "must-not-leak")
    monkeypatch.setenv("SLK_NATIVE_START_RECEIPT", "must-not-publish")
    monkeypatch.setenv("SLK_NATIVE_START_CONTEXT", "must-not-publish")
    captured: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["command"] = command
        captured["cwd"] = kwargs["cwd"]
        captured["environment"] = kwargs["env"]
        value = {
            "schema_version": "slk.ocrv-worker-recovery-result/v1",
            "status": "CHECKER_D1_RECORDED",
            "run_id": request["run_id"],
            "checker_role_instance_id": request["checker_role_instance_id"],
            "request_sha256": request_sha256,
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(value).encode(), b"")

    monkeypatch.setattr(worker_completion.subprocess, "run", run)

    result = worker_completion.consume_staged_checker_terminal(
        request_path,
        request_sha256=request_sha256,
    )

    assert result["status"] == "CHECKER_D1_RECORDED"
    assert "--slk-existing-terminal" in captured["command"]
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment["SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID"] == request["checker_role_instance_id"]
    assert environment["SLK_OCRV_RECOVERY_INVOCATION_ID"] == request["recovery_invocation_id"]
    assert "SLK_ROLE_CREDENTIAL" not in environment
    assert "SLK_OVERWATCHER_CREDENTIAL" not in environment
    assert "SLK_NATIVE_START_RECEIPT" not in environment
    assert "SLK_NATIVE_START_CONTEXT" not in environment


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


def test_checker_token_recovery_reuses_staged_candidate_without_resuming_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = checker_recovery_request(tmp_path)
    source_message_id = MESSAGE_ID
    candidate_message_id = _stable_id(source_message_id, "candidate-ready")
    projection_path = Path(str(request["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    projection["runtime_snapshot"]["token_holder_role_instance_id"] = request["checker_role_instance_id"]
    projection["runtime_snapshot"]["latest_message_id"] = candidate_message_id
    write_json(projection_path, projection)
    attempt_root = (
        Path(str(request["source_attempt_root"]))
        / "worker-continuation"
        / "checker-attempts"
    )
    candidate_attempt = attempt_root / "RUN-A" / candidate_message_id
    write_json(candidate_attempt / "endpoint.json", request["checker_endpoint"])
    write_json(candidate_attempt / "envelope.json", {"message_id": candidate_message_id})
    write_json(candidate_attempt / "started.json", {"status": "started"})
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(request["checker_role_instance_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(request["checker_endpoint_version"]))
    activated_outcomes: list[dict[str, object]] = []

    result = execute_checker_recovery(
        request,
        request_sha256="d" * 64,
        authenticate_checker=lambda run_id, role_id, _path, _command: {
            "status": "authenticated",
            "run_id": run_id,
            "role": "checker",
            "role_instance_id": role_id,
            "runtime_revision": 7,
        },
        resume_continuation=lambda _continuation: pytest.fail(
            "existing candidate and Checker TOKEN must not resume or redo Worker"
        ),
        activate_checker=lambda outcome, _continuation: (
            activated_outcomes.append(dict(outcome))
            or {
                "status": "CHECKER_STARTED",
                "runtime_revision": 7,
                "candidate_message_id": candidate_message_id,
                "token_sequence": 14,
                "checker_token_already_committed": True,
                "native_attempt_path": str(candidate_attempt),
            }
        ),
        record_checker_d1=lambda _activation, _continuation, _credential, _timeout: {
            "status": "CHECKER_D1_RECORDED",
            "d1_verdict": "PASS",
            "d1_event_type": "D1_PASSED",
            "native_result_path": str(candidate_attempt / "ocrv-result.json"),
        },
    )

    assert result["status"] == "CHECKER_D1_RECORDED"
    assert result["checker_token_already_committed"] is True
    assert activated_outcomes[0]["checker_token_already_committed"] is True
    assert activated_outcomes[0]["attempt_root"] == str(attempt_root.resolve())


@pytest.mark.parametrize(
    "mutation",
    [None, "task-hash", "session", "extra-start-field", "missing-candidate-event", "worker-token"],
)
def test_checker_token_legacy_434_start_requires_the_entire_exact_completed_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str | None,
) -> None:
    request = checker_recovery_request(tmp_path)
    source_attempt = Path(str(request["source_attempt_root"]))
    endpoint = Endpoint.from_dict(json.loads((source_attempt / "endpoint.json").read_text(encoding="utf-8")))
    envelope = Envelope.from_dict(json.loads((source_attempt / "envelope.json").read_text(encoding="utf-8")))
    task_path = source_attempt / "transport-task.json"
    task_bytes = canonical_task_bytes(
        {
            "schema_version": "slk.transport-task/v1",
            "message_id": envelope.message_id,
            "run_id": envelope.run_id,
            "go_id": envelope.go_id,
            "cell_id": envelope.cell_id,
            "endpoint": asdict(endpoint),
            "envelope": asdict(envelope),
            "result_contract": DshAdapter().legacy_result_contract(endpoint, envelope),
            "result_path": str(
                (
                    Path(str(endpoint.address["cwd"]))
                    / ".slk-transport"
                    / envelope.message_id
                    / "worker-result.json"
                ).resolve()
            ),
        }
    )
    task_path.write_bytes(task_bytes)
    worker_session_id = str(endpoint.address["session_id"])
    write_json(
        source_attempt / "started.json",
        {
            "instance_id": endpoint.address["instance_id"],
            "message_id": envelope.message_id,
            "run_id": envelope.run_id,
            "session_id": worker_session_id,
            "status": "started",
            "task_sha256": hashlib.sha256(task_bytes).hexdigest(),
        },
    )
    write_json(
        source_attempt / "completed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": envelope.message_id,
            "run_id": envelope.run_id,
            "adapter": "dsh-worker",
            "status": "completed",
            "native_identity": {
                "instance_id": endpoint.address["instance_id"],
                "session_id": worker_session_id,
                "exit_code": 0,
                "worker_outcome": "completed",
                "blocker_cause": None,
            },
            "error_code": None,
            "evidence": [
                "started.json",
                "worker-result.json",
                "native.stdout.txt",
                "native.stderr.txt",
            ],
        },
    )
    projection_path = Path(str(request["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    candidate_message_id = _stable_id(envelope.message_id, "candidate-ready")
    projection["runtime_snapshot"]["token_holder_role_instance_id"] = request[
        "checker_role_instance_id"
    ]
    projection["runtime_snapshot"]["latest_message_id"] = candidate_message_id
    projection["events"].extend(current_worker_handoff_events())
    write_json(projection_path, projection)
    attempt_root = source_attempt / "worker-continuation" / "checker-attempts"
    candidate_attempt = attempt_root / envelope.run_id / candidate_message_id
    write_json(candidate_attempt / "endpoint.json", request["checker_endpoint"])
    write_json(candidate_attempt / "envelope.json", {"message_id": candidate_message_id})
    write_json(candidate_attempt / "started.json", {"status": "started"})
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", str(request["checker_role_instance_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_INVOCATION_ID", str(request["recovery_invocation_id"]))
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(request["checker_endpoint_version"]))

    if mutation is not None:
        if mutation in {"task-hash", "session", "extra-start-field"}:
            legacy_start = json.loads((source_attempt / "started.json").read_text(encoding="utf-8"))
            if mutation == "task-hash":
                legacy_start["task_sha256"] = "0" * 64
            elif mutation == "session":
                legacy_start["session_id"] = "session-22222222-2222-4222-8222-222222222222"
            else:
                legacy_start["native_task"] = {"id": worker_session_id}
            write_json(source_attempt / "started.json", legacy_start)
        elif mutation == "missing-candidate-event":
            projection["events"] = [
                item for item in projection["events"] if item["event_type"] != "CANDIDATE_SUBMITTED"
            ]
            write_json(projection_path, projection)
        else:
            projection["runtime_snapshot"]["token_holder_role_instance_id"] = endpoint.role_instance_id
            projection["runtime_snapshot"]["latest_message_id"] = envelope.message_id
            write_json(projection_path, projection)

    def recover() -> dict[str, object]:
        return execute_checker_recovery(
            request,
            request_sha256="e" * 64,
            authenticate_checker=lambda run_id, role_id, _path, _command: {
                "status": "authenticated",
                "run_id": run_id,
                "role": "checker",
                "role_instance_id": role_id,
                "runtime_revision": 7,
            },
            resume_continuation=lambda _continuation: pytest.fail(
                "legacy completed Worker evidence must not restart or replay Worker"
            ),
            activate_checker=lambda outcome, _continuation: {
                "status": "CHECKER_STARTED",
                "runtime_revision": 7,
                "candidate_message_id": outcome["candidate_message_id"],
                "token_sequence": 14,
                "checker_token_already_committed": True,
                "native_attempt_path": str(candidate_attempt),
            },
            record_checker_d1=lambda _activation, _continuation, _credential, _timeout: {
                "status": "CHECKER_D1_RECORDED",
                "d1_verdict": "PASS",
                "d1_event_type": "D1_PASSED",
                "native_result_path": str(candidate_attempt / "ocrv-result.json"),
            },
        )

    if mutation is not None:
        with pytest.raises(CompletionError) as rejected:
            recover()
        assert rejected.value.error_code == "WORKER_CONTINUATION_NOT_READY"
        return

    result = recover()

    assert result["status"] == "CHECKER_D1_RECORDED"
    assert result["worker_session_id"] == worker_session_id
    assert result["checker_token_already_committed"] is True


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
    assert result["worker_outcome"] == outcome
    assert result["blocker"] == {
        "phase": "native_execution",
        "cause": error_code,
        "summary": "the exact DSH runtime did not produce a Worker engineering result",
        "evidence": ["native-execution.json", "failed.json"],
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

    assert result["status"] == "WORKER_INCOMPLETE"
    assert result["worker_outcome"] == "incomplete"
    assert result["blocker"]["cause"] == "NATIVE_TURN_ORPHANED"
    assert result["candidate"] is None


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


@pytest.mark.parametrize("version", ["4.4.0", "4.4.1"])
def test_patch_continuation_preserves_run_version(tmp_path, version):
    from slk_transport.worker_completion import build_continuation_request, _validate_continuation_request
    attempt, _endpoint, checker = completion_fixture(tmp_path)
    projection = runtime_projection(attempt=2)
    projection["summary"]["slk_version"] = version
    projection["runtime_snapshot"]["method_version"] = version
    value = build_continuation_request(attempt, checker, projection, plan_revision=1,
        runtime_revision=7, token_sequence=14, credential_path=tmp_path / "worker.dpapi",
        state_command=["state"], transport_command=["transport"], occurred_at="2026-10-05T00:00:00Z")
    assert value["method_version"] == version
    _validate_continuation_request(value)
    value["source_runtime_snapshot"]["method_version"] = "4.4.1" if version == "4.4.0" else "4.4.0"
    with pytest.raises(CompletionError):
        _validate_continuation_request(value)


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
    instructions: list[str] = []
    original_command = DshAdapter.command

    def capture_command(self: DshAdapter, exact_endpoint: Endpoint, instruction: str) -> list[str]:
        instructions.append(instruction)
        return original_command(self, exact_endpoint, instruction)

    monkeypatch.setattr(DshAdapter, "command", capture_command)
    monkeypatch.setenv("SLK_ROLE_CREDENTIAL", "slk_must_not_escape")
    monkeypatch.setenv("SLK_OVERWATCHER_CREDENTIAL", "slk_must_not_escape")

    result = resume_worker_continuation(request)

    assert result["status"] == "CHECKER_DELIVERY_READY"
    assert result["source_message_id"] == request["source_message_id"]
    assert len(instructions) == 1
    assert "\r" not in instructions[0] and "\n" not in instructions[0]
    started = json.loads((attempt / "worker-continuation" / "started.json").read_text(encoding="utf-8"))
    assert started["session_id"] == session_id


def test_resume_worker_continuation_rejects_second_same_session_execution(tmp_path: Path) -> None:
    attempt, _endpoint, checker = completion_fixture(tmp_path)
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
    continuation_root = worker_completion._continuation_root(request)
    continuation_root.mkdir(parents=True)
    (continuation_root / "request.json").write_bytes(worker_completion.continuation_request_bytes(request))
    write_json(
        continuation_root / "started.json",
        {
            "schema_version": "slk.worker-continuation-start/v1",
            "run_id": request["run_id"],
            "source_message_id": request["source_message_id"],
            "instance_id": request["worker_instance_id"],
            "session_id": request["worker_session_id"],
            "request_sha256": "0" * 64,
            "status": "started",
        },
    )

    with pytest.raises(CompletionError) as rejected:
        resume_worker_continuation(request)

    assert rejected.value.error_code == "WORKER_CONTINUATION_ALREADY_ATTEMPTED"


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


def test_invalid_worker_payload_is_rejected_before_any_engineering_fact(tmp_path: Path) -> None:
    attempt, endpoint, checker, candidate, _baseline = invalid_result_contract_fixture(tmp_path)
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
            "candidate": {"kind": "commit", "commit": candidate},
            "next_payload": {
                "attempt": 1,
                "candidate_repository": str(endpoint["address"]["cwd"]),
                "cell_id": "CELL-001",
                "changed_paths": ["example.txt"],
                "suffix_blocker": None,
                "unproved": [],
            },
        },
    )
    events: list[dict[str, object]] = []

    with pytest.raises(CompletionError) as rejected:
        run_worker_continuation(
            request,
            authenticate=lambda *_args: 7,
            write_event=lambda event: events.append(event) or "RECORDED",
            start_checker=lambda *_args: pytest.fail("invalid result must not reach Checker"),
            commit_start=lambda *_args: pytest.fail("invalid result must not move TOKEN"),
        )

    assert rejected.value.error_code == "WORKER_COMPLETION_EVIDENCE_INVALID"
    assert events == []


def test_dsh_worker_only_stages_checker_delivery_and_never_hosts_ocrv(tmp_path: Path) -> None:
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
    staged: list[dict[str, object]] = []

    def stage_checker(
        endpoint_raw: dict[str, object], envelope_raw: dict[str, object]
    ) -> dict[str, object]:
        staged.append(envelope_raw)
        endpoint_path = write_json(tmp_path / "staged-endpoint.json", endpoint_raw)
        envelope_path = write_json(tmp_path / "staged-envelope.json", envelope_raw)
        return {
            "status": "delivery_ready",
            "endpoint_path": str(endpoint_path),
            "envelope_path": str(envelope_path),
            "attempt_root": str(tmp_path / "checker-attempts"),
        }

    result = run_worker_continuation(
        request,
        authenticate=lambda *_: 10,
        write_event=lambda _event: "RECORDED",
        start_checker=stage_checker,
        commit_start=lambda _request: pytest.fail(
            "DSH must not commit a start before the external OCRV host proves it"
        ),
        defer_checker_start=True,
    )

    assert result["status"] == "CHECKER_DELIVERY_READY"
    assert result["runtime_revision"] == 10
    assert staged[0]["payload_type"] == "CANDIDATE_READY"


def test_worker_stages_fresh_revision_after_three_state_events(tmp_path: Path) -> None:
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
    revisions = iter((10, 13))
    authentication_calls: list[tuple[str, str]] = []

    def authenticate(run_id: str, role_instance_id: str) -> int:
        authentication_calls.append((run_id, role_instance_id))
        return next(revisions)

    result = run_worker_continuation(
        request,
        authenticate=authenticate,
        write_event=lambda _event: "RECORDED",
        start_checker=lambda endpoint, envelope: {
            "status": "delivery_ready",
            "endpoint_path": str(write_json(tmp_path / "staged-endpoint.json", endpoint)),
            "envelope_path": str(write_json(tmp_path / "staged-envelope.json", envelope)),
            "attempt_root": str(tmp_path / "checker-attempts"),
        },
        commit_start=lambda _request: pytest.fail("DSH must not commit Checker start"),
        defer_checker_start=True,
    )

    assert authentication_calls == [
        ("RUN-A", "RUN-A-worker-001"),
        ("RUN-A", "RUN-A-worker-001"),
    ]
    assert result["runtime_revision"] == 13


def test_external_recovery_host_starts_ocrv_then_commits_exact_native_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    def stage_checker(
        endpoint_raw: dict[str, object], envelope_raw: dict[str, object]
    ) -> dict[str, object]:
        return {
            "status": "delivery_ready",
            "endpoint_path": str(write_json(tmp_path / "staged-endpoint.json", endpoint_raw)),
            "envelope_path": str(write_json(tmp_path / "staged-envelope.json", envelope_raw)),
            "attempt_root": str(tmp_path / "checker-attempts"),
        }

    outcome = run_worker_continuation(
        request,
        authenticate=lambda *_: 10,
        write_event=lambda _event: "RECORDED",
        start_checker=stage_checker,
        commit_start=lambda _request: pytest.fail("DSH must not commit Checker start"),
        defer_checker_start=True,
    )
    commands: list[tuple[list[str], list[str], str | None]] = []

    def run_command(
        command: list[str], arguments: list[str], *, credential: str | None
    ) -> dict[str, object]:
        commands.append((command, arguments, credential))
        if arguments[0] == "send":
            endpoint_raw = json.loads(Path(str(outcome["endpoint_path"])).read_text(encoding="utf-8"))
            envelope_raw = json.loads(Path(str(outcome["envelope_path"])).read_text(encoding="utf-8"))
            delivery = (
                Path(str(outcome["attempt_root"]))
                / str(envelope_raw["run_id"])
                / str(envelope_raw["message_id"])
            )
            write_json(delivery / "endpoint.json", endpoint_raw)
            write_json(delivery / "envelope.json", envelope_raw)
            write_json(
                delivery / "started.json",
                make_native_start(
                    adapter=str(endpoint_raw["adapter"]),
                    run_id=str(envelope_raw["run_id"]),
                    cell_id=str(envelope_raw["cell_id"]),
                    message_id=str(envelope_raw["message_id"]),
                    request_sha256=str(envelope_raw["payload_sha256"]),
                    native_request_sha256="b" * 64,
                    native_task_kind="ocrv-review",
                    native_task_id="review-1",
                    native_task_status="RUNNING",
                    pid=os.getpid(),
                ),
            )
            return {
                "status": "started",
                "run_id": envelope_raw["run_id"],
                "message_id": envelope_raw["message_id"],
                "_slk_command": {"process_exit": 0},
            }
        commit_request = json.loads(Path(arguments[-1]).read_text(encoding="utf-8"))
        return {
            "status": "committed",
            "runtime_revision": int(commit_request["expected_runtime_revision"]) + 1,
            "token_sequence": commit_request["token_sequence"],
            "message_id": commit_request["message_id"],
            "_slk_command": {"process_exit": 0},
        }

    monkeypatch.setattr(worker_completion, "_run_json_command", run_command)
    monkeypatch.setattr(worker_completion, "unprotect_dpapi_hex", lambda _path: VALID_CREDENTIAL)

    activated = _activate_staged_checker(outcome, request)

    assert activated["status"] == "CHECKER_STARTED"
    assert [arguments[0] for _, arguments, _ in commands] == ["send", "commit-delivery-start"]
    assert commands[0][2] is None
    assert commands[1][2] == VALID_CREDENTIAL
    commit_path = Path(commands[1][1][-1])
    saved_commit = json.loads(commit_path.with_suffix(".result.json").read_text())
    assert saved_commit["status"] == "committed"
    assert saved_commit["message_id"] == activated["candidate_message_id"]
    assert VALID_CREDENTIAL not in str(saved_commit)


def test_commit_only_recovery_reuses_existing_start_and_changes_only_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt, _endpoint, checker = completion_fixture(tmp_path)
    continuation = build_continuation_request(
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

    def stage_checker(
        endpoint_raw: dict[str, object], envelope_raw: dict[str, object]
    ) -> dict[str, object]:
        root = attempt / "worker-continuation"
        return {
            "status": "delivery_ready",
            "endpoint_path": str(write_json(root / "checker-endpoint.json", endpoint_raw)),
            "envelope_path": str(write_json(root / "candidate-envelope.json", envelope_raw)),
            "attempt_root": str(root / "checker-attempts"),
        }

    outcome = run_worker_continuation(
        continuation,
        authenticate=lambda *_: 10,
        write_event=lambda _event: "RECORDED",
        start_checker=stage_checker,
        commit_start=lambda _request: pytest.fail("DSH must not commit Checker start"),
        defer_checker_start=True,
    )
    write_json(Path(str(continuation["continuation_result_path"])), outcome)
    endpoint_raw = json.loads(Path(str(outcome["endpoint_path"])).read_text(encoding="utf-8"))
    envelope_raw = json.loads(Path(str(outcome["envelope_path"])).read_text(encoding="utf-8"))
    native_attempt = (
        Path(str(outcome["attempt_root"]))
        / str(envelope_raw["run_id"])
        / str(envelope_raw["message_id"])
    )
    write_json(native_attempt / "endpoint.json", endpoint_raw)
    write_json(native_attempt / "envelope.json", envelope_raw)
    write_json(
        native_attempt / "started.json",
        make_native_start(
            adapter=str(endpoint_raw["adapter"]),
            run_id=str(envelope_raw["run_id"]),
            cell_id=str(envelope_raw["cell_id"]),
            message_id=str(envelope_raw["message_id"]),
            request_sha256=str(envelope_raw["payload_sha256"]),
            native_request_sha256="b" * 64,
            native_task_kind="ocrv-review",
            native_task_id="review-1",
            native_task_status="RUNNING",
            pid=os.getpid(),
        ),
    )
    monkeypatch.setattr(worker_completion, "unprotect_dpapi_hex", lambda _path: VALID_CREDENTIAL)
    monkeypatch.setattr(
        worker_completion,
        "_run_json_command",
        lambda _command, arguments, credential: {
            "status": "rejected",
            "error_code": "WORKER_RUNTIME_REVISION_INVALID",
            "_slk_command": {"process_exit": 2},
        },
    )
    with pytest.raises(CompletionError):
        _activate_staged_checker(outcome, continuation)
    failed_request_path = next(
        (attempt / "worker-continuation").glob("commit-delivery-start-*.json")
    )
    failed_bytes = failed_request_path.read_bytes()
    failed_request = json.loads(failed_bytes)
    commands: list[str] = []

    def recover_command(
        _command: list[str], arguments: list[str], *, credential: str | None
    ) -> dict[str, object]:
        commands.append(arguments[0])
        assert credential == VALID_CREDENTIAL
        if arguments[0] == "authenticate-role":
            return {
                "status": "authenticated",
                "role": "worker",
                "role_instance_id": continuation["worker_role_instance_id"],
                "runtime_revision": 13,
                "_slk_command": {"process_exit": 0},
            }
        recovery_request = json.loads(Path(arguments[-1]).read_text(encoding="utf-8"))
        assert recovery_request == {**failed_request, "expected_runtime_revision": 13}
        return {
            "status": "committed",
            "runtime_revision": 14,
            "token_sequence": recovery_request["token_sequence"],
            "message_id": recovery_request["message_id"],
            "_slk_command": {"process_exit": 0},
        }

    monkeypatch.setattr(worker_completion, "_run_json_command", recover_command)

    recovered = worker_completion.recover_staged_checker_commit(
        continuation,
        outcome,
        failed_request_path=failed_request_path,
    )

    assert commands == ["authenticate-role", "commit-delivery-start"]
    assert failed_request_path.read_bytes() == failed_bytes
    assert recovered["status"] == "CHECKER_START_COMMITTED"
    assert recovered["runtime_revision"] == 14
    assert Path(str(recovered["recovery_request_path"])).parent.name == "commit-only-recovery"
    assert Path(str(recovered["result_path"])).is_file()
    activation = worker_completion._load_commit_only_checker_activation(continuation, 14)
    assert activation["status"] == "CHECKER_STARTED"
    assert activation["native_attempt_path"] == str(native_attempt.resolve())


@pytest.mark.parametrize("competing_write", [False, True])
def test_real_state_revision_closes_handoff_and_rejects_post_stage_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    competing_write: bool,
) -> None:
    state_binary, config_path, worker_credential, _checker_credential, initial_revision = (
        actual_worker_state(tmp_path)
    )
    monkeypatch.setenv("SLK_CONFIG_PATH", str(config_path))
    monkeypatch.setattr(worker_completion, "unprotect_dpapi_hex", lambda _path: worker_credential)
    completion_root = tmp_path / "completion"
    completion_root.mkdir()
    attempt, _worker_endpoint, checker = completion_fixture(completion_root)
    checker["endpoint_version"] = 1
    envelope_path = attempt / "envelope.json"
    source_envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    source_envelope["token_sequence"] = 3
    write_json(envelope_path, source_envelope)
    projection = runtime_projection(token_owner="RUN-A-worker-001")
    projection["runtime_snapshot"].update(
        runtime_revision=initial_revision,
        token_sequence=3,
    )
    continuation = build_continuation_request(
        attempt,
        checker,
        projection,
        plan_revision=1,
        runtime_revision=initial_revision,
        token_sequence=3,
        credential_path=tmp_path / "worker.dpapi",
        state_command=[str(state_binary)],
        transport_command=["slk-transport"],
        occurred_at="2026-09-23T00:00:03Z",
    )
    event_root = tmp_path / "worker-events"

    def state_request(command: str, value: dict[str, object]) -> dict[str, object]:
        return actual_state_call(
            state_binary,
            config_path,
            [command, "--request", write_json(event_root / f"{value['event_id']}.json", value)],
            credential=worker_credential,
        )

    def authenticate(run_id: str, role_instance_id: str) -> int:
        value = actual_state_call(
            state_binary,
            config_path,
            ["authenticate-role", "--run-id", run_id, "--role-instance-id", role_instance_id],
            credential=worker_credential,
        )
        return int(value["runtime_revision"])

    def stage_checker(
        endpoint_raw: dict[str, object], envelope_raw: dict[str, object]
    ) -> dict[str, object]:
        root = attempt / "worker-continuation"
        return {
            "status": "delivery_ready",
            "endpoint_path": str(write_json(root / "checker-endpoint.json", endpoint_raw)),
            "envelope_path": str(write_json(root / "candidate-envelope.json", envelope_raw)),
            "attempt_root": str(root / "checker-attempts"),
        }

    outcome = run_worker_continuation(
        continuation,
        authenticate=authenticate,
        write_event=lambda event: str(state_request("write", event)["status"]),
        start_checker=stage_checker,
        commit_start=lambda _request: pytest.fail("DSH must not commit Checker start"),
        defer_checker_start=True,
    )
    assert outcome["runtime_revision"] == initial_revision + 3
    assert authenticate("RUN-A", "RUN-A-worker-001") == initial_revision + 3
    endpoint_raw = json.loads(Path(str(outcome["endpoint_path"])).read_text(encoding="utf-8"))
    envelope_raw = json.loads(Path(str(outcome["envelope_path"])).read_text(encoding="utf-8"))
    native_attempt = (
        Path(str(outcome["attempt_root"]))
        / str(envelope_raw["run_id"])
        / str(envelope_raw["message_id"])
    )
    write_json(native_attempt / "endpoint.json", endpoint_raw)
    write_json(native_attempt / "envelope.json", envelope_raw)
    write_json(
        native_attempt / "started.json",
        make_native_start(
            adapter="ocrv-checker",
            run_id="RUN-A",
            cell_id="CELL-001",
            message_id=str(envelope_raw["message_id"]),
            request_sha256=str(envelope_raw["payload_sha256"]),
            native_request_sha256="d" * 64,
            native_task_kind="ocrv-review",
            native_task_id="integration-review",
            native_task_status="RUNNING",
            pid=os.getpid(),
        ),
    )
    if competing_write:
        state_request(
            "write",
            {
                "event_id": "post-stage-competing-write",
                "run_id": "RUN-A",
                "go_id": "GO-001",
                "cell_id": "CELL-001",
                "attempt": 1,
                "plan_revision": 1,
                "role_instance_id": "RUN-A-worker-001",
                "event_type": "WORK_STARTED",
                "details": {"reason": "race probe"},
                "corrects_event_id": None,
                "occurred_at": "2026-09-23T00:00:04Z",
            },
        )
        with pytest.raises(CompletionError) as rejected:
            _activate_staged_checker(outcome, continuation)
        assert rejected.value.error_code == "WORKER_RUNTIME_REVISION_INVALID"
        assert authenticate("RUN-A", "RUN-A-worker-001") == initial_revision + 4
        return

    activated = _activate_staged_checker(outcome, continuation)
    assert activated["status"] == "CHECKER_STARTED"
    assert activated["runtime_revision"] == initial_revision + 4
    assert activated["token_sequence"] == 4


def test_false_legacy_start_with_token_at_checker_recovers_same_candidate_without_recommit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "SLK-RUN-LCAS-RC08-WINDOWS-IDENTITY-ROOT-R2"
    source_message_id = "d1d118c5-abb7-4ef9-b0bc-7e5321da73bb"
    candidate_message_id = "5fe6847d-11bb-5111-8b32-389ea73f0879"
    checker = endpoint_value(role="checker", version=1)
    checker["run_id"] = run_id
    checker["role_instance_id"] = "SLK-RC08-WINDOWS-IDENTITY-CHECKER-R2-01"
    checker["address"] = {
        "command": ["D:/OCRV/slk-checker.cmd"],
        "runtime_root": str(tmp_path / "ocrv"),
        "timeout_seconds": 30,
    }
    (tmp_path / "ocrv").mkdir()
    payload = {
        "repository": str(tmp_path),
        "candidate": {"kind": "commit", "commit": "a3f8f5911bc8dee77ed00333f633ce1a9ba9af68"},
        "cell_goal": "preserve the existing candidate",
        "d1_criteria": ["review the same candidate"],
        "evidence_files": [str(tmp_path / "evidence.json")],
    }
    envelope = envelope_value(
        sender_role="worker",
        receiver_role="checker",
        receiver_endpoint_version=1,
    )
    envelope.update(
        {
            "message_id": candidate_message_id,
            "token_sequence": 4,
            "run_id": run_id,
            "go_id": "LEGACY-GROUP-01",
            "cell_id": "CELL01",
            "sender_role_instance_id": "SLK-RC08-WINDOWS-IDENTITY-WORKER-R2-01",
            "receiver_role_instance_id": checker["role_instance_id"],
            "payload_type": "CANDIDATE_READY",
            "payload": payload,
            "payload_sha256": worker_completion.canonical_json_sha256(payload),
        }
    )
    staged_endpoint = write_json(tmp_path / "staged-endpoint.json", checker)
    staged_envelope = write_json(tmp_path / "staged-envelope.json", envelope)
    original_root = tmp_path / "checker-attempts"
    original_attempt = original_root / run_id / candidate_message_id
    write_json(original_attempt / "endpoint.json", checker)
    write_json(original_attempt / "envelope.json", envelope)
    legacy_bytes = b'{"message_id":"5fe6847d-11bb-5111-8b32-389ea73f0879","status":"started"}\n'
    (original_attempt / "started.json").write_bytes(legacy_bytes)
    outcome = {
        "status": "CHECKER_DELIVERY_READY",
        "run_id": run_id,
        "source_message_id": source_message_id,
        "candidate_message_id": candidate_message_id,
        "runtime_revision": 16,
        "checker_token_already_committed": True,
        "endpoint_path": str(staged_endpoint),
        "envelope_path": str(staged_envelope),
        "attempt_root": str(original_root),
    }
    continuation = {
        "method_version": "4.4.0",
        "run_id": run_id,
        "go_id": "LEGACY-GROUP-01",
        "cell_id": "CELL01",
        "attempt": 1,
        "plan_revision": 1,
        "runtime_revision": 16,
        "source_message_id": source_message_id,
        "source_attempt_root": str(tmp_path / source_message_id),
        "worker_role_instance_id": "SLK-RC08-WINDOWS-IDENTITY-WORKER-R2-01",
        "checker_endpoint": checker,
        "credential_path": str(tmp_path / "worker.dpapi"),
        "state_command": ["slk-state"],
        "transport_command": ["slk-transport"],
        "token_sequence": 4,
        "checker_token_already_committed": True,
        "occurred_at": "2026-10-01T04:48:00+08:00",
    }
    commands: list[list[str]] = []

    def run_command(
        _command: list[str], arguments: list[str], *, credential: str | None
    ) -> dict[str, object]:
        assert credential is None
        commands.append(arguments)
        recovery_root = Path(arguments[arguments.index("--attempt-root") + 1])
        assert recovery_root != original_root
        attempt = recovery_root / run_id / candidate_message_id
        write_json(attempt / "endpoint.json", checker)
        write_json(attempt / "envelope.json", envelope)
        write_json(
            attempt / "started.json",
            make_native_start(
                adapter="ocrv-checker",
                run_id=run_id,
                cell_id="CELL01",
                message_id=candidate_message_id,
                request_sha256=str(envelope["payload_sha256"]),
                native_request_sha256="c" * 64,
                native_task_kind="ocrv-review",
                native_task_id="review-recovery-1",
                native_task_status="RUNNING",
                    pid=os.getpid(),
            ),
        )
        return {
            "status": "started",
            "run_id": run_id,
            "message_id": candidate_message_id,
            "_slk_command": {"process_exit": 0},
        }

    monkeypatch.setattr(worker_completion, "_run_json_command", run_command)
    monkeypatch.setattr(
        worker_completion,
        "unprotect_dpapi_hex",
        lambda _path: pytest.fail("TOKEN is already at Checker; Worker credential must not be used"),
    )

    activated = _activate_staged_checker(outcome, continuation)

    assert activated["status"] == "CHECKER_STARTED"
    assert activated["runtime_revision"] == 16
    assert activated["token_sequence"] == 4
    assert activated["checker_token_already_committed"] is True
    assert len(commands) == 1
    assert (original_attempt / "started.json").read_bytes() == legacy_bytes


@pytest.mark.parametrize(
    (
        "verdict",
        "review_exit_code",
        "terminal_exit_code",
        "terminal_session_id",
        "expected_event_type",
    ),
    [
        ("PASS", 0, 0, "ocrv-session-1", "D1_PASSED"),
        ("FAIL", 0, 2, "ocrv-session-1", "D1_FAILED"),
        ("INCOMPLETE", 7, 3, "ocrv-session-1", "D1_INCOMPLETE"),
        ("FAIL", 0, 0, "ocrv-session-1", None),
        ("FAIL", 0, 2, "forged-session", None),
    ],
)
def test_native_ocrv_result_is_recorded_only_with_bound_terminal_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    verdict: str,
    review_exit_code: int,
    terminal_exit_code: int,
    terminal_session_id: str,
    expected_event_type: str | None,
) -> None:
    native_attempt = tmp_path / "native-attempt"
    write_json(
        native_attempt / "started.json",
        make_native_start(
            adapter="ocrv-checker",
            run_id="RUN-A",
            cell_id="CELL-001",
            message_id="candidate-message-1",
            request_sha256="a" * 64,
            native_request_sha256="b" * 64,
            native_task_kind="ocrv-review",
            native_task_id="review-1",
            native_task_status="RUNNING",
            pid=os.getpid(),
        ),
    )
    write_json(
        native_attempt / "ocrv-result.json",
        {
            "schema_version": "slk.ocrv-d1-result/v1",
            "run_id": "RUN-A",
            "cell_id": "CELL-001",
            "review_invocation_id": "review-1",
            "verdict": verdict,
            "reason_codes": [
                {
                    "PASS": "OCR_COMPLETE_ZERO_FINDINGS",
                    "FAIL": "OCR_FINDINGS_PRESENT",
                    "INCOMPLETE": "OCRV_REVIEW_INCOMPLETE",
                }[verdict]
            ],
            "findings": [],
            "review": {
                "status": "complete",
                "provider": "dashscope-tokenplan",
                "model": "qwen3.8-max",
                "session_id": "ocrv-session-1",
                "exit_code": review_exit_code,
            },
            "evidence": [],
            "request_sha256": "b" * 64,
            "artifacts": {},
        },
    )
    write_json(
        native_attempt / "completed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": "candidate-message-1",
            "run_id": "RUN-A",
            "adapter": "ocrv-checker",
            "status": "completed",
            "native_identity": {
                "run_id": "RUN-A",
                "cell_id": "CELL-001",
                "review_invocation_id": "review-1",
                "session_id": terminal_session_id,
                "provider": "dashscope-tokenplan",
                "model": "qwen3.8-max",
                "verdict": verdict,
                "exit_code": terminal_exit_code,
                "review_segment_count": 0,
            },
            "error_code": None,
            "evidence": ["started.json", "ocrv-result.json"],
        },
    )
    writes: list[tuple[dict[str, object], str | None]] = []

    def run_command(
        _command: list[str], arguments: list[str], *, credential: str | None
    ) -> dict[str, object]:
        request = json.loads(Path(arguments[-1]).read_text(encoding="utf-8"))
        writes.append((request, credential))
        return {"status": "recorded", "run_id": "RUN-A", "export": "runtime.json"}

    monkeypatch.setattr(worker_completion, "_run_json_command", run_command)
    monkeypatch.setattr(worker_completion, "unprotect_dpapi_hex", lambda _path: "slk_" + "c" * 64)
    continuation = {
        "run_id": "RUN-A",
        "go_id": "GO-001",
        "cell_id": "CELL-001",
        "attempt": 1,
        "plan_revision": 1,
        "source_message_id": MESSAGE_ID,
        "checker_endpoint": endpoint_value(role="checker", version=2),
        "state_command": ["slk-state"],
        "occurred_at": "2026-10-01T00:00:00Z",
    }
    activation = {
        "status": "CHECKER_STARTED",
        "candidate_message_id": "candidate-message-1",
        "native_attempt_path": str(native_attempt),
    }

    if expected_event_type is None:
        with pytest.raises(worker_completion.CompletionError, match="OCRV D1 terminal"):
            worker_completion._record_checker_d1(
                activation,
                continuation,
                checker_credential_path=tmp_path / "checker.dpapi",
                timeout_seconds=1,
            )
        assert [request["event_type"] for request, _ in writes] == ["D1_STARTED"]
    else:
        result = worker_completion._record_checker_d1(
            activation,
            continuation,
            checker_credential_path=tmp_path / "checker.dpapi",
            timeout_seconds=1,
        )

        assert result["status"] == "CHECKER_D1_RECORDED"
        assert result["d1_verdict"] == verdict
        assert [request["event_type"] for request, _ in writes] == ["D1_STARTED", expected_event_type]
        assert {credential for _, credential in writes} == {"slk_" + "c" * 64}
        assert writes[1][0]["details"]["native_result_sha256"] == hashlib.sha256(
            (native_attempt / "ocrv-result.json").read_bytes()
        ).hexdigest()


def test_checker_d1_rejects_terminal_with_wrong_message_or_native_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native_attempt = tmp_path / "native-attempt"
    write_json(
        native_attempt / "started.json",
        make_native_start(
            adapter="ocrv-checker",
            run_id="RUN-A",
            cell_id="CELL-001",
            message_id="candidate-message-1",
            request_sha256="a" * 64,
            native_request_sha256="b" * 64,
            native_task_kind="ocrv-review",
            native_task_id="review-1",
            native_task_status="RUNNING",
            pid=os.getpid(),
        ),
    )
    write_json(
        native_attempt / "ocrv-result.json",
        {
            "schema_version": "slk.ocrv-d1-result/v1",
            "run_id": "RUN-A",
            "cell_id": "CELL-001",
            "review_invocation_id": "review-1",
            "verdict": "PASS",
            "reason_codes": ["OCR_COMPLETE_ZERO_FINDINGS"],
            "findings": [],
            "review": {
                "status": "complete",
                "provider": "dashscope-tokenplan",
                "model": "qwen3.8-max",
                "session_id": "ocrv-session-1",
                "exit_code": 0,
            },
            "evidence": [],
            "request_sha256": "b" * 64,
            "artifacts": {},
        },
    )
    write_json(
        native_attempt / "completed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": "different-candidate-message",
            "run_id": "RUN-A",
            "adapter": "ocrv-checker",
            "status": "completed",
            "native_identity": {
                "review_invocation_id": "different-review",
                "verdict": "PASS",
            },
            "error_code": None,
            "evidence": ["started.json", "ocrv-result.json"],
        },
    )
    monkeypatch.setattr(worker_completion, "unprotect_dpapi_hex", lambda _path: "slk_" + "c" * 64)
    monkeypatch.setattr(
        worker_completion,
        "_run_json_command",
        lambda *_args, **_kwargs: {"status": "recorded", "run_id": "RUN-A"},
    )
    continuation = {
        "run_id": "RUN-A",
        "go_id": "GO-001",
        "cell_id": "CELL-001",
        "attempt": 1,
        "plan_revision": 1,
        "source_message_id": MESSAGE_ID,
        "checker_endpoint": endpoint_value(role="checker", version=2),
        "state_command": ["slk-state"],
        "occurred_at": "2026-10-01T00:00:00Z",
    }
    activation = {
        "status": "CHECKER_STARTED",
        "candidate_message_id": "candidate-message-1",
        "native_attempt_path": str(native_attempt),
    }

    with pytest.raises(worker_completion.CompletionError, match="OCRV D1 terminal"):
        worker_completion._record_checker_d1(
            activation,
            continuation,
            checker_credential_path=tmp_path / "checker.dpapi",
            timeout_seconds=1,
        )


def test_actual_ocrv_adapter_terminal_is_bound_into_checker_d1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "ocrv-runtime"
    runtime_root.mkdir()
    checker_raw = endpoint_value(role="checker", version=2)
    checker_raw["address"] = {
        "command": [sys.executable, str(FAKE_OCRV), "normal"],
        "runtime_root": str(runtime_root),
        "timeout_seconds": 5,
    }
    checker = Endpoint.from_dict(checker_raw)
    repository = tmp_path / "repository"
    repository.mkdir()
    payload = {
        "repository": str(repository),
        "candidate": {"kind": "workspace"},
        "cell_goal": "Verify the actual Checker result binding.",
        "d1_criteria": ["The actual adapter result remains bound."],
        "evidence_files": [],
    }
    envelope_raw = envelope_value(sender_role="worker", receiver_role="checker")
    envelope_raw["payload_type"] = "CANDIDATE_READY"
    envelope_raw["payload"] = payload
    envelope_raw["payload_sha256"] = canonical_json_sha256(payload)
    envelope = Envelope.from_dict(envelope_raw)
    result = dispatch_once(
        asdict(checker),
        asdict(envelope),
        tmp_path / "attempts",
        adapters={"ocrv-checker": OcrvAdapter()},
    )
    assert result.status == "completed"
    native_attempt = tmp_path / "attempts" / envelope.run_id / envelope.message_id
    writes: list[dict[str, object]] = []

    def run_command(
        _command: list[str], arguments: list[str], *, credential: str | None
    ) -> dict[str, object]:
        assert credential == "slk_" + "c" * 64
        writes.append(json.loads(Path(arguments[-1]).read_text(encoding="utf-8")))
        return {"status": "recorded", "run_id": envelope.run_id}

    monkeypatch.setattr(worker_completion, "_run_json_command", run_command)
    monkeypatch.setattr(worker_completion, "unprotect_dpapi_hex", lambda _path: "slk_" + "c" * 64)
    continuation = {
        "run_id": envelope.run_id,
        "go_id": envelope.go_id,
        "cell_id": envelope.cell_id,
        "attempt": 1,
        "plan_revision": 1,
        "source_message_id": MESSAGE_ID,
        "checker_endpoint": asdict(checker),
        "state_command": ["slk-state"],
        "occurred_at": "2026-10-01T00:00:00Z",
    }
    recorded = worker_completion._record_checker_d1(
        {
            "status": "CHECKER_STARTED",
            "candidate_message_id": envelope.message_id,
            "native_attempt_path": str(native_attempt),
        },
        continuation,
        checker_credential_path=tmp_path / "checker.dpapi",
        timeout_seconds=1,
    )

    assert recorded["d1_verdict"] == "PASS"
    assert [item["event_type"] for item in writes] == ["D1_STARTED", "D1_PASSED"]
    assert writes[1]["details"]["native_result_sha256"] == hashlib.sha256(
        (native_attempt / "ocrv-result.json").read_bytes()
    ).hexdigest()


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
        "investigation_mode": "STANDARD",
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
    started = json.loads((attempt / "started.json").read_text(encoding="utf-8"))
    started["request_sha256"] = source["payload_sha256"]
    write_json(attempt / "started.json", started)
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


def test_next_cell_candidate_keeps_frozen_task_not_worker_self_report(tmp_path: Path) -> None:
    attempt, endpoint, checker = completion_fixture(tmp_path)
    source = json.loads((attempt / "envelope.json").read_text())
    source["payload"] = {"cell_id": "CELL-001", "cell_ordinal": 1, "required_cell_count": 1,
        "task": "Exact frozen NEXT_CELL task", "d1_criteria": ["focused test passes"],
        "root_record_path": str(attempt / "endpoint.json")}
    source["payload_sha256"] = canonical_json_sha256(source["payload"])
    write_json(attempt / "envelope.json", source)
    started = json.loads((attempt / "started.json").read_text())
    started["request_sha256"] = source["payload_sha256"]
    write_json(attempt / "started.json", started)
    request = build_continuation_request(attempt, checker, runtime_projection(), plan_revision=1,
        runtime_revision=7, token_sequence=14, credential_path=tmp_path / "worker.dpapi",
        state_command=["state"], transport_command=["transport"], occurred_at="2026-10-05T00:00:00Z")
    sent = []
    def capture(endpoint, envelope):
        sent.append(envelope)
        raise RuntimeError("capture-only")
    with pytest.raises(RuntimeError, match="capture-only"):
        run_worker_continuation(request, authenticate=lambda *a: 10, write_event=lambda e: "RECORDED",
                               start_checker=capture, commit_start=commit_result)
    assert sent[0]["payload"]["cell_goal"] == source["payload"]["task"]


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


def invalid_result_contract_fixture(
    tmp_path: Path,
) -> tuple[Path, dict[str, object], dict[str, object], str, str]:
    attempt, worker, checker = completion_fixture(tmp_path)
    repository = Path(str(worker["address"]["cwd"]))

    def git(*arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repository,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=True,
        )
        return completed.stdout.strip()

    git("init")
    git("config", "user.name", "SLK Test")
    git("config", "user.email", "slk-test@example.invalid")
    (repository / "example.txt").write_text("baseline\n", encoding="utf-8")
    git("add", "example.txt")
    git("commit", "-m", "baseline")
    baseline = git("rev-parse", "HEAD")
    (repository / "example.txt").write_text("candidate\n", encoding="utf-8")
    git("add", "example.txt")
    git("commit", "-m", "candidate")
    candidate = git("rev-parse", "HEAD")

    envelope = json.loads((attempt / "envelope.json").read_text(encoding="utf-8"))
    endpoint = Endpoint.from_dict(worker)
    legacy_contract = {
        "schema_version": "slk.worker-result-contract/v1",
        "identity": {
            "schema_version": "slk.worker-result/v1",
            "message_id": envelope["message_id"],
            "run_id": envelope["run_id"],
            "role_instance_id": envelope["receiver_role_instance_id"],
        },
        "allowed_statuses": [
            "completed", "incomplete", "blocked", "execution_failure", "timed_out",
        ],
        "completed": {
            "candidate": {"kind": "commit", "commit": "REPLACE_WITH_EXACT_COMMIT"},
            "next_payload": {"candidate_repository": str(repository.resolve())},
            "blocker": None,
        },
        "non_completed": {
            "candidate": None,
            "next_payload": None,
            "blocker_fields": ["phase", "cause", "summary", "evidence"],
        },
    }
    task = {
        "schema_version": "slk.transport-task/v1",
        "message_id": envelope["message_id"],
        "run_id": envelope["run_id"],
        "go_id": envelope["go_id"],
        "cell_id": envelope["cell_id"],
        "endpoint": worker,
        "envelope": envelope,
        "result_contract": legacy_contract,
        "result_path": str(
            (repository / ".slk-transport" / str(envelope["message_id"]) / "worker-result.json").resolve()
        ),
    }
    task_bytes = canonical_task_bytes(task)
    (attempt / "transport-task.json").write_bytes(task_bytes)
    started = json.loads((attempt / "started.json").read_text(encoding="utf-8"))
    started["native_request_sha256"] = hashlib.sha256(task_bytes).hexdigest()
    write_json(attempt / "started.json", started)
    (attempt / "completed.json").unlink()
    (attempt / "worker-result.json").unlink()
    invalid = {
        "schema_version": "slk.worker-result-contract/v1",
        "identity": legacy_contract["identity"],
        "status": "completed",
        "completed": {
            "candidate": {"kind": "commit", "commit": candidate},
            "next_payload": {"candidate_repository": str(repository.resolve())},
            "blocker": None,
            "evidence": {
                "candidate_commit": candidate,
                "candidate_parent": baseline,
                "changed_paths": ["example.txt"],
            },
        },
    }
    (attempt / "worker-result.invalid.txt").write_text(
        json.dumps(invalid, sort_keys=True), encoding="utf-8"
    )
    write_json(
        attempt / "failed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": envelope["message_id"],
            "run_id": envelope["run_id"],
            "adapter": "dsh-worker",
            "status": "failed",
            "native_identity": {},
            "error_code": "DSH_RESULT_INVALID",
            "evidence": [
                "started.json", "transport-task.json", "worker-result.invalid.txt",
            ],
        },
    )
    return attempt, worker, checker, candidate, baseline


def write_valid_invalid_result_supplement(
    attempt: Path,
    worker: dict[str, object],
    request: dict[str, object],
    candidate: str,
    baseline: str,
) -> Path:
    next_payload = {
        "attempt": request["attempt"],
        "candidate_repository": str(Path(str(worker["address"]["cwd"])).resolve()),
        "cell_id": request["cell_id"],
        "changed_paths": ["example.txt"],
        "d0": {
            "baseline_commit": baseline,
            "branch": "test-branch",
            "candidate_commit": candidate,
            "changed_paths": ["example.txt"],
            "evidence_files": [str((attempt / "worker-result.invalid.txt").resolve())],
            "focused_command": "pytest focused",
            "frozen_command": "pytest full",
            "frozen_command_result": {"status": "passed"},
            "green": {"status": "passed"},
            "red": {"status": "failed-before"},
            "unproved": [],
        },
        "suffix_blocker": None,
        "unproved": [],
    }
    return write_json(
        Path(str(request["worker_result_path"])),
        {
            "schema_version": "slk.worker-result/v1",
            "message_id": MESSAGE_ID,
            "run_id": "RUN-A",
            "role_instance_id": worker["role_instance_id"],
            "status": "completed",
            "candidate": {"kind": "commit", "commit": candidate},
            "next_payload": next_payload,
        },
    )


def test_checker_recovery_builds_one_invalid_result_contract_supplement(tmp_path: Path) -> None:
    attempt, worker, checker, candidate, baseline = invalid_result_contract_fixture(tmp_path)

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

    assert request["recovery_mode"] == "INVALID_RESULT_CONTRACT"
    assert request["worker_result_path"] == str(
        (attempt / "invalid-result-supplement" / "recovered-worker-result.json").resolve()
    )
    assert request["source_candidate"] == {"kind": "commit", "commit": candidate}
    assert request["source_candidate_parent"] == baseline
    assert request["source_repository"] == str(Path(str(worker["address"]["cwd"])).resolve())
    assert request["source_changed_paths"] == ["example.txt"]
    assert request["source_invalid_result_sha256"] == worker_completion._sha256(
        attempt / "worker-result.invalid.txt"
    )
    assert request["source_task_sha256"] == worker_completion._sha256(attempt / "transport-task.json")
    assert request["source_started_sha256"] == worker_completion._sha256(attempt / "started.json")
    assert request["supplement_result_contract"] == worker_completion.INVALID_SUPPLEMENT_RESULT_CONTRACT
    assert "slk_" not in json.dumps(request)


def test_invalid_result_contract_supplement_validates_before_worker_events(tmp_path: Path) -> None:
    attempt, worker, checker, candidate, baseline = invalid_result_contract_fixture(tmp_path)
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
    write_valid_invalid_result_supplement(attempt, worker, request, candidate, baseline)
    events: list[dict[str, object]] = []
    staged: list[dict[str, object]] = []

    def start_checker(endpoint_raw: dict[str, object], envelope_raw: dict[str, object]) -> dict[str, object]:
        staged.append(envelope_raw)
        root = attempt / "invalid-result-supplement"
        return {
            "status": "delivery_ready",
            "endpoint_path": str(write_json(root / "checker-endpoint.json", endpoint_raw)),
            "envelope_path": str(write_json(root / "candidate-envelope.json", envelope_raw)),
            "attempt_root": str(root / "checker-attempts"),
        }

    result = run_worker_continuation(
        request,
        authenticate=lambda *_args: 7,
        write_event=lambda event: events.append(event) or "RECORDED",
        start_checker=start_checker,
        commit_start=lambda *_args: pytest.fail("DSH must only stage Checker"),
        defer_checker_start=True,
    )

    assert result["status"] == "CHECKER_DELIVERY_READY"
    assert [event["event_type"] for event in events] == [
        "WORK_STARTED",
        "D0_COMPLETED",
        "CANDIDATE_SUBMITTED",
    ]
    assert staged[0]["payload"]["candidate"] == {"kind": "commit", "commit": candidate}


@pytest.mark.parametrize(
    "field,mutated",
    [
        ("source_terminal_sha256", "0" * 64),
        ("source_task_sha256", "0" * 64),
        ("source_started_sha256", "0" * 64),
        ("source_invalid_result_sha256", "0" * 64),
        ("source_candidate", {"kind": "commit", "commit": "0" * 40}),
        ("source_candidate_parent", "0" * 40),
        ("token_sequence", 15),
        ("runtime_revision", 8),
    ],
)
def test_invalid_result_contract_supplement_rejects_frozen_source_drift(
    tmp_path: Path,
    field: str,
    mutated: object,
) -> None:
    attempt, worker, checker, candidate, baseline = invalid_result_contract_fixture(tmp_path)
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
    write_valid_invalid_result_supplement(attempt, worker, request, candidate, baseline)
    request[field] = mutated
    events: list[dict[str, object]] = []

    with pytest.raises(CompletionError):
        run_worker_continuation(
            request,
            authenticate=lambda *_args: 7,
            write_event=lambda event: events.append(event) or "RECORDED",
            start_checker=lambda *_args: pytest.fail("drift must not reach Checker"),
            commit_start=lambda *_args: pytest.fail("drift must not move TOKEN"),
        )

    assert events == []


def test_invalid_result_contract_supplement_is_one_shot(tmp_path: Path) -> None:
    attempt, _worker, checker, _candidate, _baseline = invalid_result_contract_fixture(tmp_path)
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
    (attempt / "invalid-result-supplement").mkdir()

    with pytest.raises(CompletionError) as rejected:
        resume_worker_continuation(request)

    assert rejected.value.error_code == "WORKER_INVALID_RESULT_SUPPLEMENT_ALREADY_ATTEMPTED"


def test_invalid_result_contract_resume_instruction_is_one_physical_line_and_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt, _worker, checker, _candidate, _baseline = invalid_result_contract_fixture(tmp_path)
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
    instructions: list[str] = []

    def capture(_self: DshAdapter, _endpoint: Endpoint, instruction: str) -> list[str]:
        instructions.append(instruction)
        raise CompletionError("TEST_COMMAND_CAPTURED", "stop before model start")

    monkeypatch.setattr(DshAdapter, "command", capture)

    with pytest.raises(CompletionError) as stopped:
        resume_worker_continuation(request)

    assert stopped.value.error_code == "TEST_COMMAND_CAPTURED"
    assert len(instructions) == 1
    assert "\r" not in instructions[0] and "\n" not in instructions[0]
    assert "supplement_result_contract" in instructions[0]
    assert json.dumps(str(attempt / "invalid-result-supplement" / "request.json")) in instructions[0]


@pytest.mark.parametrize("mutation", ["session", "commit"])
def test_invalid_result_contract_supplement_rejects_session_or_commit_drift_before_resume(
    tmp_path: Path,
    mutation: str,
) -> None:
    attempt, worker, checker, _candidate, _baseline = invalid_result_contract_fixture(tmp_path)
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
    if mutation == "session":
        request["worker_session_id"] = "session-22222222-2222-4222-8222-222222222222"
    else:
        repository = Path(str(worker["address"]["cwd"]))
        (repository / "example.txt").write_text("third commit\n", encoding="utf-8")
        subprocess.run(["git", "add", "example.txt"], cwd=repository, check=True)
        subprocess.run(
            ["git", "-c", "user.name=SLK Test", "-c", "user.email=slk-test@example.invalid", "commit", "-m", "drift"],
            cwd=repository,
            check=True,
            capture_output=True,
        )

    with pytest.raises(CompletionError):
        resume_worker_continuation(request)

    assert not (attempt / "invalid-result-supplement").exists()


@pytest.mark.parametrize("event_type", ["WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED"])
def test_invalid_result_contract_supplement_rejects_existing_worker_facts(
    tmp_path: Path,
    event_type: str,
) -> None:
    attempt, _worker, checker, _candidate, _baseline = invalid_result_contract_fixture(tmp_path)
    projection = runtime_projection(event_types=[event_type])

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

    assert rejected.value.error_code == "WORKER_CONTINUATION_NOT_READY"


def test_invalid_result_contract_rejects_candidate_repository_drift(tmp_path: Path) -> None:
    attempt, worker, checker, _candidate, _baseline = invalid_result_contract_fixture(tmp_path)
    repository = Path(str(worker["address"]["cwd"]))
    (repository / "unexpected.txt").write_text("drift\n", encoding="utf-8")

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
                "candidate_baseline": "a" * 40,
                "changed_paths": ["src/example.py"],
                "d0": {"commands_and_outcomes": ["pytest: pass"], "not_run": []},
                "unproved": [],
            },
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


def test_missing_result_recovery_rejects_completed_blocker_field_before_events(
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
    recovered = {
        "schema_version": "slk.worker-result/v1",
        "message_id": MESSAGE_ID,
        "run_id": "RUN-A",
        "role_instance_id": endpoint["role_instance_id"],
        "status": "completed",
        "candidate": {"kind": "commit", "commit": "c" * 40},
        "next_payload": {
            "candidate_repository": str(tmp_path / "repository"),
            "candidate_baseline": "a" * 40,
            "changed_paths": ["src/example.py"],
            "d0": {"commands_and_outcomes": ["pytest: pass"], "not_run": []},
            "unproved": [],
        },
        "blocker": None,
    }
    write_json(Path(str(request["worker_result_path"])), recovered)
    events: list[dict[str, object]] = []

    with pytest.raises(CompletionError) as rejected:
        run_worker_continuation(
            request,
            authenticate=lambda *_args: 7,
            write_event=lambda event: events.append(event) or "RECORDED",
            start_checker=lambda *_args: pytest.fail("invalid result must not reach Checker"),
            commit_start=lambda *_args: pytest.fail("invalid result must not move TOKEN"),
        )

    assert rejected.value.error_code == "WORKER_COMPLETION_EVIDENCE_INVALID"
    assert events == []


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
