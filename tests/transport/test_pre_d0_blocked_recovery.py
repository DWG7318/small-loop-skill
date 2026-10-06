"""Closed recovery for an exact Worker blocked before D0."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest

import slk_transport.worker_completion as wc
from slk_transport.contracts import Envelope
from slk_transport.adapters.dsh import DshAdapter
from slk_transport.adapters.ocrv import OcrvAdapter
from slk_transport.contracts import Endpoint
from slk_transport.task_file import canonical_task_bytes
from test_worker_completion import completion_fixture, runtime_projection, write_json


def git(repository: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repository), *arguments], text=True, encoding="utf-8"
    ).strip()


def fixture(tmp_path: Path) -> dict[str, object]:
    attempt, worker, checker = completion_fixture(tmp_path)
    repository = Path(str(worker["address"]["cwd"]))
    git(repository, "init", "-q")
    (repository / "example.py").write_text("value = 0\n", encoding="utf-8")
    git(repository, "add", ".")
    git(repository, "-c", "user.name=SLK test", "-c", "user.email=slk@example.invalid",
        "commit", "-qm", "baseline")
    (repository / "example.py").write_text("value = 1\n", encoding="utf-8")
    git(repository, "add", ".")
    git(repository, "-c", "user.name=SLK test", "-c", "user.email=slk@example.invalid",
        "commit", "-qm", "candidate")
    candidate = git(repository, "rev-parse", "HEAD")

    (attempt / "completed.json").unlink()
    source = json.loads((attempt / "envelope.json").read_text(encoding="utf-8"))
    result = {
        "schema_version": "slk.worker-result/v1",
        "message_id": source["message_id"],
        "run_id": source["run_id"],
        "role_instance_id": worker["role_instance_id"],
        "status": "blocked",
        "candidate": None,
        "next_payload": None,
        "blocker": {
            "phase": "D0",
            "cause": "ENVIRONMENT_SLK_CARGO_TARGET_UNC_PREFIX_BREAKS_MSVC_INCLUDE",
            "summary": "verbatim Cargo target paths are not accepted by this MSVC include parser",
            "evidence": ["plain spelling passed the isolated compiler probe"],
        },
    }
    write_json(attempt / "worker-result.json", result)
    write_json(
        attempt / "failed.json",
        {
            "schema_version": "slk.transport-result/v1",
            "message_id": source["message_id"],
            "run_id": source["run_id"],
            "adapter": "dsh-worker",
            "status": "failed",
            "native_identity": {
                "instance_id": worker["address"]["instance_id"],
                "session_id": worker["address"]["session_id"],
                "exit_code": 0,
                "worker_outcome": "blocked",
                "blocker_cause": result["blocker"]["cause"],
            },
            "error_code": "DSH_WORKER_BLOCKED",
            "evidence": ["started.json", "worker-result.json", "native.stdout.txt", "native.stderr.txt"],
        },
    )
    endpoint = Endpoint.from_dict(worker)
    envelope = Envelope.from_dict(source)
    task = {
        "schema_version": "slk.transport-task/v1",
        "message_id": envelope.message_id,
        "run_id": envelope.run_id,
        "go_id": envelope.go_id,
        "cell_id": envelope.cell_id,
        "endpoint": asdict(endpoint),
        "envelope": asdict(envelope),
        "result_contract": DshAdapter().result_contract(endpoint, envelope),
        "result_path": str(
            (
                repository / ".slk-transport" / envelope.message_id / "worker-result.json"
            ).resolve()
        ),
    }
    task_bytes = canonical_task_bytes(task)
    (attempt / "transport-task.json").write_bytes(task_bytes)
    started = json.loads((attempt / "started.json").read_text(encoding="utf-8"))
    started["native_request_sha256"] = hashlib.sha256(task_bytes).hexdigest()
    write_json(attempt / "started.json", started)
    (attempt / "native.stdout.txt").write_text("", encoding="utf-8")
    (attempt / "native.stderr.txt").write_text("C1083\n", encoding="utf-8")

    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "slk.db").write_bytes(b"")
    state_config = write_json(
        tmp_path / "state-config.json",
        {"schema_version": "slk.config/v1", "data_root": str(data_root.resolve())},
    )
    cargo_program = tmp_path / "cargo.exe"
    cargo_program.write_bytes(b"cargo")
    protoc = tmp_path / "protoc.exe"
    protoc.write_bytes(b"protoc")
    tool = tmp_path / "slk-cargo.exe"
    tool.write_bytes(b"fixed-slk-cargo")
    environment = {
        "schema_version": "slk.pre-d0-blocked-recovery/v1",
        "recovery_kind": "WINDOWS_CARGO_TARGET_PLAIN_PATH",
        "source_message_id": source["message_id"],
        "candidate_repository": str(repository.resolve()),
        "candidate_commit": candidate,
        "tool_path": str(tool.resolve()),
        "tool_sha256": hashlib.sha256(tool.read_bytes()).hexdigest(),
        "state_config_path": str(state_config.resolve()),
        "state_config_sha256": hashlib.sha256(state_config.read_bytes()).hexdigest(),
        "d0_environment": {
            "PROTOC": str(protoc.resolve()),
            "PROTOC_SHA256": hashlib.sha256(protoc.read_bytes()).hexdigest(),
        },
        "d0_command": [
            str(tool.resolve()), "run", "--data-root", str(data_root.resolve()),
            "--project-id", "project-a", "--run-id", source["run_id"],
            "--go-id", source["go_id"], "--cell-id", source["cell_id"],
            "--attempt", "1", "--cargo-program", str(cargo_program.resolve()),
            "--", "test", "-p", "example", "--lib",
        ],
    }
    environment_path = write_json(tmp_path / "pre-d0-environment.json", environment)
    projection = runtime_projection()
    projection["summary"]["project_id"] = "project-a"
    projection["administrative_snapshot"] = {"project_id": "project-a"}
    projection_path = write_json(tmp_path / "runtime-projection.json", projection)
    worker_credential = tmp_path / "worker.dpapi"
    checker_credential = tmp_path / "checker.dpapi"
    worker_credential.write_text("sealed-worker", encoding="ascii")
    checker_credential.write_text("sealed-checker", encoding="ascii")
    return {
        "attempt": attempt,
        "worker": worker,
        "checker": checker,
        "candidate": candidate,
        "environment_path": environment_path,
        "environment_sha256": hashlib.sha256(environment_path.read_bytes()).hexdigest(),
        "data_root": data_root,
        "state_config": state_config,
        "protoc": protoc,
        "projection_path": projection_path,
        "worker_credential": worker_credential,
        "checker_credential": checker_credential,
        "output": tmp_path / "pre-d0-recovery-envelope.json",
    }


def prepare(case: dict[str, object]) -> dict[str, object]:
    operation = getattr(wc, "prepare_pre_d0_blocked_recovery_envelope", None)
    assert callable(operation), "PRE_D0_BLOCKED_RECOVERY prepare entry is missing"
    checker = case["checker"]
    assert isinstance(checker, dict)
    return operation(
        case["attempt"], checker, case["projection_path"],
        supervisor_role_instance_id="RUN-A-supervisor-001",
        plan_revision=1, runtime_revision=7, token_sequence=14,
        worker_credential_path=case["worker_credential"],
        checker_credential_path=case["checker_credential"],
        state_command=["slk-state"], transport_command=["python", "slk-transport.pyz"],
        environment_adjustment_path=case["environment_path"],
        environment_adjustment_sha256=case["environment_sha256"],
        occurred_at="2026-10-06T05:30:00Z", output_path=case["output"],
    )


def continuation(case: dict[str, object]) -> dict[str, object]:
    checker = case["checker"]
    assert isinstance(checker, dict)
    return wc.build_continuation_request(
        case["attempt"], checker,
        json.loads(Path(str(case["projection_path"])).read_text(encoding="utf-8")),
        plan_revision=1, runtime_revision=7, token_sequence=14,
        credential_path=case["worker_credential"],
        state_command=["slk-state"], transport_command=["python", "slk-transport.pyz"],
        occurred_at="2026-10-06T05:30:00Z",
        environment_adjustment_path=case["environment_path"],
        environment_adjustment_sha256=str(case["environment_sha256"]),
    )


def write_recovered_result(case: dict[str, object], request: dict[str, object]) -> Path:
    repository = Path(str(case["worker"]["address"]["cwd"]))
    candidate = str(case["candidate"])
    baseline = git(repository, "rev-parse", "HEAD^")
    path = Path(str(request["worker_result_path"]))
    return write_json(
        path,
        {
            "schema_version": "slk.worker-result/v1",
            "message_id": request["source_message_id"],
            "run_id": request["run_id"],
            "role_instance_id": request["worker_role_instance_id"],
            "status": "completed",
            "candidate": {"kind": "commit", "commit": candidate},
            "next_payload": {
                "attempt": 1,
                "candidate_repository": str(repository.resolve()),
                "cell_id": "CELL-001",
                "changed_paths": ["example.py"],
                "d0": {
                    "baseline_commit": baseline,
                    "branch": git(repository, "branch", "--show-current"),
                    "candidate_commit": candidate,
                    "changed_paths": ["example.py"],
                    "evidence_files": [str(case["environment_path"])],
                    "focused_command": "slk-cargo run -- test -p example --lib",
                    "frozen_command": json.dumps(
                        json.loads(
                            Path(str(case["environment_path"])).read_text(encoding="utf-8")
                        )["d0_command"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    "frozen_command_result": {"exit_code": 0},
                    "green": {"status": "PASS"},
                    "red": {"status": "PRESERVED"},
                    "unproved": [],
                },
                "suffix_blocker": None,
                "unproved": [],
            },
        },
    )


def test_prepare_pre_d0_blocked_recovery_binds_exact_source_environment_and_candidate(tmp_path: Path) -> None:
    case = fixture(tmp_path)

    receipt = prepare(case)

    assert receipt["status"] == "PRE_D0_BLOCKED_RECOVERY_READY"
    assert receipt["recovery_mode"] == "PRE_D0_BLOCKED_RECOVERY"
    assert receipt["candidate"] == {"kind": "commit", "commit": case["candidate"]}
    envelope = Envelope.from_dict(json.loads(Path(str(case["output"])).read_text(encoding="utf-8")))
    assert envelope.payload_type == "PRE_D0_BLOCKED_RECOVERY"
    assert envelope.payload["environment_adjustment_sha256"] == case["environment_sha256"]
    assert envelope.payload["source_attempt_root"] == str(Path(str(case["attempt"])).resolve())


def test_pre_d0_recovery_runs_only_original_worker_suffix_and_preserves_source(tmp_path: Path) -> None:
    case = fixture(tmp_path)
    request = continuation(case)
    attempt = Path(str(case["attempt"]))
    repository = Path(str(case["worker"]["address"]["cwd"]))
    original = {
        name: (attempt / name).read_bytes()
        for name in ("worker-result.json", "failed.json", "started.json", "transport-task.json")
    }
    original_head = git(repository, "rev-parse", "HEAD")
    write_recovered_result(case, request)
    events: list[dict[str, object]] = []
    staged: list[dict[str, object]] = []

    def start_checker(endpoint: dict[str, object], envelope: dict[str, object]) -> dict[str, object]:
        staged.append(envelope)
        root = attempt / "pre-d0-blocked-recovery"
        return {
            "status": "delivery_ready",
            "endpoint_path": str(write_json(root / "checker-endpoint.json", endpoint)),
            "envelope_path": str(write_json(root / "candidate-envelope.json", envelope)),
            "attempt_root": str(root / "checker-attempts"),
        }

    result = wc.run_worker_continuation(
        request,
        authenticate=lambda *_args: 7,
        write_event=lambda event: events.append(event) or "RECORDED",
        start_checker=start_checker,
        commit_start=lambda *_args: pytest.fail("Worker recovery may only stage original Checker"),
        defer_checker_start=True,
    )

    assert result["status"] == "CHECKER_DELIVERY_READY"
    assert [event["event_type"] for event in events] == [
        "WORK_STARTED", "D0_COMPLETED", "CANDIDATE_SUBMITTED",
    ]
    assert staged[0]["receiver_role_instance_id"] == case["checker"]["role_instance_id"]
    assert staged[0]["payload"]["candidate"] == {"kind": "commit", "commit": original_head}
    assert git(repository, "rev-parse", "HEAD") == original_head
    for name, data in original.items():
        assert (attempt / name).read_bytes() == data


@pytest.mark.parametrize("mutation", ["command", "exit", "green"])
def test_pre_d0_recovery_rejects_unproved_d0_before_events(
    tmp_path: Path, mutation: str,
) -> None:
    case = fixture(tmp_path)
    request = continuation(case)
    result_path = write_recovered_result(case, request)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    d0 = result["next_payload"]["d0"]
    if mutation == "command":
        d0["frozen_command"] = "cargo test"
    elif mutation == "exit":
        d0["frozen_command_result"]["exit_code"] = 1
    else:
        d0["green"]["status"] = "UNKNOWN"
    write_json(result_path, result)
    events: list[dict[str, object]] = []

    with pytest.raises(wc.CompletionError) as rejected:
        wc.run_worker_continuation(
            request,
            authenticate=lambda *_args: 7,
            write_event=lambda event: events.append(event) or "RECORDED",
            start_checker=lambda *_args: pytest.fail("unproved D0 must not reach Checker"),
            commit_start=lambda *_args: pytest.fail("unproved D0 must not move TOKEN"),
        )

    assert rejected.value.error_code == "WORKER_COMPLETION_EVIDENCE_INVALID"
    assert events == []


def test_pre_d0_recovery_is_one_shot_before_any_model_start(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = fixture(tmp_path)
    request = continuation(case)
    root = Path(str(case["attempt"])) / "pre-d0-blocked-recovery"
    root.mkdir()
    write_json(root / "started.json", {"status": "active_native_writer"})
    monkeypatch.setattr(
        DshAdapter,
        "command",
        lambda *_args: pytest.fail("existing recovery evidence must block before model start"),
    )

    with pytest.raises(wc.CompletionError) as rejected:
        wc.resume_worker_continuation(request)

    assert rejected.value.error_code == "WORKER_PRE_D0_RECOVERY_ALREADY_ATTEMPTED"


def test_pre_d0_resume_instruction_is_single_line_and_reuses_original_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = fixture(tmp_path)
    request = continuation(case)
    captured: list[tuple[str, str]] = []

    def capture(_self: DshAdapter, endpoint: Endpoint, instruction: str) -> list[str]:
        captured.append((str(endpoint.address["session_id"]), instruction))
        raise wc.CompletionError("TEST_COMMAND_CAPTURED", "stop before model start")

    monkeypatch.setattr(DshAdapter, "command", capture)
    with pytest.raises(wc.CompletionError) as stopped:
        wc.resume_worker_continuation(request)
    assert stopped.value.error_code == "TEST_COMMAND_CAPTURED"
    assert captured[0][0] == case["worker"]["address"]["session_id"]
    assert "\r" not in captured[0][1] and "\n" not in captured[0][1]
    assert "environment_adjustment.d0_command" in captured[0][1]


def test_pre_d0_resume_inherits_only_hash_bound_protoc_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = fixture(tmp_path)
    request = continuation(case)
    captured: dict[str, str] = {}

    monkeypatch.setattr(DshAdapter, "command", lambda *_args: ["dsh", "resume"])

    def capture_spawn(
        _command: list[str], *, cwd: str, env: dict[str, str], process_kwargs: dict[str, object],
    ) -> object:
        del cwd, process_kwargs
        captured.update(env)
        raise RuntimeError("captured before native start")

    monkeypatch.setattr("slk_transport.subprocess_watch.spawn", capture_spawn)
    with pytest.raises(RuntimeError, match="captured before native start"):
        wc.resume_worker_continuation(request)

    assert captured["PROTOC"] == str(Path(str(case["protoc"])).resolve())
    assert "PROTOC_SHA256" not in captured


def test_pre_d0_recovery_rejects_changed_protoc_bytes(tmp_path: Path) -> None:
    case = fixture(tmp_path)
    Path(str(case["protoc"])).write_bytes(b"replaced-protoc")

    with pytest.raises(wc.CompletionError) as rejected:
        prepare(case)

    assert rejected.value.error_code == "WORKER_PRE_D0_RECOVERY_NOT_READY"


@pytest.mark.skipif(os.name != "nt", reason="Windows verbatim-path identity contract")
def test_pre_d0_recovery_preserves_state_config_data_root_spelling(tmp_path: Path) -> None:
    case = fixture(tmp_path)
    state_config = Path(str(case["state_config"]))
    environment_path = Path(str(case["environment_path"]))
    data_root = Path(str(case["data_root"])).resolve()
    verbatim_data_root = rf"\\?\{data_root}"
    write_json(
        state_config,
        {"schema_version": "slk.config/v1", "data_root": verbatim_data_root},
    )
    environment = json.loads(environment_path.read_text(encoding="utf-8"))
    environment["state_config_sha256"] = hashlib.sha256(state_config.read_bytes()).hexdigest()
    index = environment["d0_command"].index("--data-root")
    environment["d0_command"][index + 1] = verbatim_data_root
    write_json(environment_path, environment)
    case["environment_sha256"] = hashlib.sha256(environment_path.read_bytes()).hexdigest()

    assert prepare(case)["status"] == "PRE_D0_BLOCKED_RECOVERY_READY"

    environment["d0_command"][index + 1] = str(data_root)
    write_json(environment_path, environment)
    case["environment_sha256"] = hashlib.sha256(environment_path.read_bytes()).hexdigest()
    with pytest.raises(wc.CompletionError) as rejected:
        prepare(case)
    assert rejected.value.error_code == "WORKER_PRE_D0_RECOVERY_NOT_READY"


def test_pre_d0_payload_reaches_checker_with_environment_binding(tmp_path: Path) -> None:
    case = fixture(tmp_path)
    prepare(case)
    envelope = Envelope.from_dict(json.loads(Path(str(case["output"])).read_text(encoding="utf-8")))
    checker = Endpoint.from_dict(case["checker"])
    request = OcrvAdapter()._recovery_request(
        checker, envelope, "recovery-invocation", tmp_path / "result.json",
    )
    assert request["environment_adjustment_path"] == str(Path(str(case["environment_path"])).resolve())
    assert request["environment_adjustment_sha256"] == case["environment_sha256"]


def checker_request(case: dict[str, object], tmp_path: Path) -> tuple[dict[str, object], Endpoint]:
    prepare(case)
    envelope = Envelope.from_dict(json.loads(Path(str(case["output"])).read_text(encoding="utf-8")))
    checker = Endpoint.from_dict(case["checker"])
    return (
        OcrvAdapter()._recovery_request(
            checker, envelope, "recovery-invocation", tmp_path / "checker-result.json",
        ),
        checker,
    )


def test_pre_d0_checker_authenticates_before_worker_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = fixture(tmp_path)
    request, checker = checker_request(case, tmp_path)
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", checker.role_instance_id)
    monkeypatch.setenv("SLK_OCRV_RECOVERY_INVOCATION_ID", "recovery-invocation")
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(checker.endpoint_version))
    resumed: list[bool] = []

    with pytest.raises(wc.CompletionError) as rejected:
        wc.execute_checker_recovery(
            request,
            request_sha256="a" * 64,
            authenticate_checker=lambda *_args: {
                "status": "rejected", "role": "checker",
                "role_instance_id": checker.role_instance_id, "runtime_revision": 7,
            },
            resume_continuation=lambda _request: resumed.append(True) or {},
        )

    assert rejected.value.error_code == "CHECKER_RECOVERY_AUTHENTICATION_FAILED"
    assert resumed == []


def test_pre_d0_original_checker_drives_normal_d1_after_successful_worker_suffix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = fixture(tmp_path)
    request, checker = checker_request(case, tmp_path)
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ROLE_INSTANCE_ID", checker.role_instance_id)
    monkeypatch.setenv("SLK_OCRV_RECOVERY_INVOCATION_ID", "recovery-invocation")
    monkeypatch.setenv("SLK_OCRV_RECOVERY_ENDPOINT_VERSION", str(checker.endpoint_version))
    order: list[str] = []

    def authenticate(*_args: object) -> dict[str, object]:
        order.append("authenticate-checker")
        return {
            "status": "authenticated", "role": "checker",
            "role_instance_id": checker.role_instance_id, "runtime_revision": 7,
        }

    def resume(value: dict[str, object]) -> dict[str, object]:
        order.append("resume-worker")
        assert value["recovery_mode"] == "PRE_D0_BLOCKED_RECOVERY"
        return {"status": "CHECKER_DELIVERY_READY", "candidate_message_id": "candidate-message"}

    def activate(_outcome: dict[str, object], _continuation: dict[str, object]) -> dict[str, object]:
        order.append("start-checker")
        return {
            "status": "CHECKER_STARTED", "candidate_message_id": "candidate-message",
            "runtime_revision": 8, "token_sequence": 15,
            "checker_token_already_committed": False,
            "native_attempt_path": str((tmp_path / "checker-attempt").resolve()),
        }

    def record(*_args: object) -> dict[str, object]:
        order.append("record-d1")
        return {
            "status": "CHECKER_D1_RECORDED", "d1_verdict": "PASS",
            "d1_event_type": "D1_PASSED",
            "native_result_path": str((tmp_path / "ocrv-result.json").resolve()),
        }

    result = wc.execute_checker_recovery(
        request,
        request_sha256="a" * 64,
        authenticate_checker=authenticate,
        resume_continuation=resume,
        activate_checker=activate,
        record_checker_d1=record,
    )

    assert order == ["authenticate-checker", "resume-worker", "start-checker", "record-d1"]
    assert result["status"] == "CHECKER_D1_RECORDED"
    assert result["d1_verdict"] == "PASS"


@pytest.mark.parametrize(
    "mutation",
    ["wrong_status", "wrong_phase", "candidate_claimed", "wrong_token_owner", "d0_exists",
     "wrong_session", "wrong_environment_message", "wrong_project", "wrong_data_root",
     "wrong_tool_hash", "missing_protoc", "wrong_protoc", "environment_hash", "candidate_changed"],
)
def test_prepare_pre_d0_blocked_recovery_fails_closed_on_source_drift(
    tmp_path: Path, mutation: str,
) -> None:
    case = fixture(tmp_path)
    attempt = Path(str(case["attempt"]))
    if mutation in {"wrong_status", "wrong_phase", "candidate_claimed"}:
        result = json.loads((attempt / "worker-result.json").read_text(encoding="utf-8"))
        if mutation == "wrong_status":
            result["status"] = "incomplete"
        elif mutation == "wrong_phase":
            result["blocker"]["phase"] = "implementation"
        else:
            result["candidate"] = {"kind": "commit", "commit": str(case["candidate"])}
        write_json(attempt / "worker-result.json", result)
    elif mutation == "wrong_token_owner":
        projection = json.loads(Path(str(case["projection_path"])).read_text(encoding="utf-8"))
        projection["runtime_snapshot"]["token_holder_role_instance_id"] = "RUN-A-checker-001"
        write_json(Path(str(case["projection_path"])), projection)
    elif mutation == "d0_exists":
        projection = json.loads(Path(str(case["projection_path"])).read_text(encoding="utf-8"))
        projection["events"].append({"event_id": "d0", "event_type": "D0_COMPLETED",
                                     "cell_id": "CELL-001", "attempt": 1})
        write_json(Path(str(case["projection_path"])), projection)
    elif mutation == "wrong_session":
        endpoint = json.loads((attempt / "endpoint.json").read_text(encoding="utf-8"))
        endpoint["address"]["session_id"] = "session-22222222-2222-4222-8222-222222222222"
        write_json(attempt / "endpoint.json", endpoint)
    elif mutation in {
        "wrong_environment_message", "wrong_project", "wrong_data_root", "wrong_tool_hash",
        "missing_protoc", "wrong_protoc",
    }:
        environment = json.loads(Path(str(case["environment_path"])).read_text(encoding="utf-8"))
        if mutation == "wrong_environment_message":
            environment["source_message_id"] = "22222222-2222-4222-8222-222222222222"
        elif mutation == "wrong_project":
            index = environment["d0_command"].index("--project-id")
            environment["d0_command"][index + 1] = "other-project"
        elif mutation == "wrong_data_root":
            other = tmp_path / "other-data"
            other.mkdir()
            (other / "slk.db").write_bytes(b"")
            index = environment["d0_command"].index("--data-root")
            environment["d0_command"][index + 1] = str(other.resolve())
        elif mutation == "missing_protoc":
            environment["d0_environment"] = {}
        elif mutation == "wrong_protoc":
            environment["d0_environment"]["PROTOC"] = str((tmp_path / "missing-protoc.exe").resolve())
        else:
            environment["tool_sha256"] = "0" * 64
        write_json(Path(str(case["environment_path"])), environment)
        case["environment_sha256"] = hashlib.sha256(Path(str(case["environment_path"])).read_bytes()).hexdigest()
    elif mutation == "environment_hash":
        case["environment_sha256"] = "f" * 64
    else:
        repository = Path(str(case["worker"]["address"]["cwd"]))
        (repository / "example.py").write_text("value = 2\n", encoding="utf-8")

    with pytest.raises(wc.CompletionError) as rejected:
        prepare(case)
    assert rejected.value.error_code == "WORKER_PRE_D0_RECOVERY_NOT_READY"
