from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
from pathlib import Path

import pytest

from slk_transport.contracts import ContractError, canonical_json_sha256
from slk_transport.native_activity import make_native_start

from test_contracts import endpoint_value, envelope_value
from late_desktop import desktop_endpoint, write_late_desktop_start


@pytest.mark.parametrize('proof', ['valid', 'corrupt', 'wrong-root'])
def test_sealed_partial_failure_reads_original_identity_without_changing_aggregate(tmp_path, monkeypatch, proof):
    from slk_transport import checker_escalation as escalation, partial_review

    request, _ = fixture(tmp_path)
    native = Path(request['native_attempt_path'])
    source = tmp_path / 'original-delivery'
    source.mkdir()
    for name in ('endpoint.json', 'envelope.json'):
        (native / name).rename(source / name)
    committed = {'native_attempt_path': str(source)}
    write_json(native.parent / 'committed-terminal.json', committed)
    original = {p.name: p.read_bytes() for p in native.iterdir() if p.is_file()}

    # The full native proof is exercised by the existing partial-terminal tests;
    # isolate only its accepted/rejected outcome at this reader boundary.
    def validate(value, **kwargs):
        assert value == committed
        if proof == 'corrupt':
            raise ValueError('native proof hash mismatch')
        return {'activation': {'native_attempt_path': str(native if proof == 'valid' else source)}}

    monkeypatch.setattr(partial_review, 'validate_partial_terminal', validate)
    if proof == 'valid':
        result = escalation._validate_failure(request)
        assert result['candidate']['commit'] == CANDIDATE_COMMIT
    else:
        with pytest.raises(escalation.CheckerEscalationError):
            escalation._validate_failure(request)
    assert {p.name: p.read_bytes() for p in native.iterdir() if p.is_file()} == original


@pytest.mark.parametrize(
    "proof", ["valid", "valid-pre-record-revision", "corrupt-receipt", "wrong-root"]
)
def test_sealed_fresh_failure_reads_hash_bound_original_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, proof: str
) -> None:
    from slk_transport import checker_escalation as escalation, worker_completion

    request, _ = fixture(tmp_path)
    native = Path(str(request["native_attempt_path"]))
    projection_path = Path(str(request["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    projection["events"][0]["corrects_event_id"] = "d1-incomplete-001"
    projection["events"].insert(
        0,
        {
            "event_id": "d1-incomplete-001",
            "event_type": "D1_INCOMPLETE",
            "author_role_instance_id": CHECKER_ID,
            "go_id": GO_ID,
            "cell_id": CELL_ID,
            "attempt": 1,
            "details_json": json.dumps(
                {"candidate_message_id": CANDIDATE_MESSAGE_ID, "verdict": "INCOMPLETE"},
                sort_keys=True,
            ),
        },
    )
    write_json(projection_path, projection)
    source = tmp_path / "original-delivery"
    source.mkdir()
    for name in ("endpoint.json", "envelope.json"):
        (native / name).rename(source / name)
    recovery_native = native if proof != "wrong-root" else source
    committed = {
        "native_attempt_path": str(source),
        "candidate_message_id": CANDIDATE_MESSAGE_ID,
        "checker_endpoint_version": 2,
        "recovery_invocation_id": "fresh-review-001",
        "runtime_revision": request["runtime_revision"] - 2,
        "token_sequence": request["token_sequence"],
        "recovery_terminal": {
            "compatibility_request_path": str(tmp_path / "fresh-request.json"),
            "native_attempt_path": str(recovery_native),
        },
    }
    committed_path = write_json(native.parent / "committed-terminal.json", committed)
    receipt = {
        "schema_version": "slk.ocrv-committed-terminal-result/v1",
        "status": "CHECKER_D1_RECORDED",
        "method_version": request["method_version"],
        "run_id": request["run_id"],
        "cell_id": request["cell_id"],
        "attempt": request["attempt"],
        "candidate_message_id": CANDIDATE_MESSAGE_ID,
        "checker_role_instance_id": request["checker_role_instance_id"],
        "checker_endpoint_version": 2,
        "recovery_invocation_id": "fresh-review-001",
        "request_sha256": sha256(committed_path),
        "runtime_revision": request["runtime_revision"] - (
            2 if proof == "valid-pre-record-revision" else 1
        ),
        "token_sequence": request["token_sequence"],
        "d1_verdict": "FAIL",
        "d1_event_type": "D1_FAILED",
        "authorized_existing_terminal": True,
        "checker_authenticated": True,
        "native_attempt_path": str(native),
        "native_result_path": str(native / "ocrv-result.json"),
    }
    if proof == "corrupt-receipt":
        receipt["request_sha256"] = "0" * 64
    write_json(native.parent / "committed-terminal-result.json", receipt)

    def validate(value, **_kwargs):
        assert value == committed
        return {"checker": object(), "frozen_projection": {}}

    monkeypatch.setattr(worker_completion, "_validate_committed_terminal_request", validate)
    if proof in {"valid", "valid-pre-record-revision"}:
        assert escalation._validate_failure(request)["candidate"]["commit"] == CANDIDATE_COMMIT
    else:
        with pytest.raises(escalation.CheckerEscalationError, match="lineage"):
            escalation._validate_failure(request)


def test_sealed_terminal_budget_failure_reads_hash_bound_original_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from slk_transport import checker_escalation as escalation, worker_completion

    request, _ = fixture(tmp_path)
    native = Path(str(request["native_attempt_path"]))
    source = tmp_path / "original-delivery"
    source.mkdir()
    for name in ("endpoint.json", "envelope.json"):
        (native / name).rename(source / name)
    committed = {
        "native_attempt_path": str(source),
        "candidate_message_id": CANDIDATE_MESSAGE_ID,
        "checker_endpoint_version": 2,
        "recovery_invocation_id": "terminal-budget-001",
        "runtime_revision": request["runtime_revision"] - 2,
        "token_sequence": request["token_sequence"],
        "recovery_terminal": {
            "source_request_path": str(tmp_path / "budget-request.json"),
            "native_attempt_path": str(native),
        },
    }
    committed_path = write_json(native.parent / "committed-terminal.json", committed)
    write_json(
        native.parent / "committed-terminal-result.json",
        {
            "schema_version": "slk.ocrv-committed-terminal-result/v1",
            "status": "CHECKER_D1_RECORDED",
            "method_version": request["method_version"],
            "run_id": request["run_id"],
            "cell_id": request["cell_id"],
            "attempt": request["attempt"],
            "candidate_message_id": CANDIDATE_MESSAGE_ID,
            "checker_role_instance_id": request["checker_role_instance_id"],
            "checker_endpoint_version": 2,
            "recovery_invocation_id": "terminal-budget-001",
            "request_sha256": sha256(committed_path),
            "runtime_revision": request["runtime_revision"] - 1,
            "token_sequence": request["token_sequence"],
            "d1_verdict": "FAIL",
            "d1_event_type": "D1_FAILED",
            "authorized_existing_terminal": True,
            "checker_authenticated": True,
            "native_attempt_path": str(native),
            "native_result_path": str(native / "ocrv-result.json"),
        },
    )

    def validate(value, **_kwargs):
        assert value == committed
        return {"checker": object(), "frozen_projection": {}}

    monkeypatch.setattr(worker_completion, "_validate_committed_terminal_request", validate)
    assert escalation._validate_failure(request)["candidate"]["commit"] == CANDIDATE_COMMIT


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
                "slk_version": "4.4.0",
                "current_plan_revision": 1,
            },
            "runtime_snapshot": {
                "method_version": "4.4.0",
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
        "method_version": "4.4.0",
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


def management_return_fixture(
    tmp_path: Path,
) -> tuple[object, dict[str, object], Path, str]:
    module = load_module()
    request, request_path = fixture(tmp_path)
    native = Path(str(request["native_attempt_path"]))
    return_message_id = "77777777-7777-4777-8777-777777777777"
    source_incomplete_event_id = "d1-incomplete-before-management"
    envelope_path = native / "envelope.json"
    original = json.loads(envelope_path.read_text(encoding="utf-8"))
    management_payload = {
        "source_d1_incomplete_event_id": source_incomplete_event_id,
        "candidate_message_id": CANDIDATE_MESSAGE_ID,
        "candidate_payload": original["payload"],
        "candidate_payload_sha256": original["payload_sha256"],
        "management_action": "ADJUST_CAPACITY",
        "management_summary": "Return to the normal unlimited D1 profile.",
        "management_evidence_refs": [str((native / "ocrv-result.json").resolve())],
        "review_policy": {
            "profile": "NORMAL_D1_DEFAULT",
            "aggregate_budget": "NATIVE_UNLIMITED",
            "review_timeout": "NATIVE_UNLIMITED",
            "tool_rounds": "TEMPLATE_DEFAULT",
        },
    }
    returned = {
        **original,
        "message_id": return_message_id,
        "token_sequence": int(original["token_sequence"]) + 2,
        "sender_role": "supervisor",
        "sender_role_instance_id": SUPERVISOR_ID,
        "payload_type": "D1_MANAGEMENT_RETURN",
        "payload": management_payload,
        "payload_sha256": canonical_json_sha256(management_payload),
    }
    write_json(envelope_path, returned)
    started_path = write_json(
        native / "started.json",
        make_native_start(
            adapter="ocrv-checker",
            run_id=RUN_ID,
            cell_id=CELL_ID,
            message_id=return_message_id,
            request_sha256=returned["payload_sha256"],
            native_request_sha256="b" * 64,
            native_task_kind="ocrv-review",
            native_task_id="review-1",
            native_task_status="RUNNING",
            pid=os.getpid(),
        ),
    )
    terminal_path = native / "completed.json"
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["message_id"] = return_message_id
    write_json(terminal_path, terminal)
    projection_path = Path(str(request["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    current = projection["events"][0]
    current["corrects_event_id"] = source_incomplete_event_id
    details = json.loads(current["details_json"])
    details.update(
        native_message_id=return_message_id,
        native_start_sha256=sha256(started_path),
        native_terminal_sha256=sha256(terminal_path),
    )
    current["details_json"] = json.dumps(details, sort_keys=True)
    projection["events"].insert(0, {
        "event_id": "candidate-transport-started",
        "event_type": "TRANSPORT_STARTED",
        "author_role_instance_id": "ROLE-worker",
        "go_id": GO_ID,
        "cell_id": CELL_ID,
        "attempt": 2,
        "corrects_event_id": None,
        "details_json": json.dumps({
            "message_id": CANDIDATE_MESSAGE_ID,
            "endpoint_sha256": "a" * 64,
            "envelope_sha256": original["payload_sha256"],
            "start_evidence_sha256": "b" * 64,
        }, sort_keys=True),
    })
    projection["events"].insert(1, {
        "event_id": source_incomplete_event_id,
        "event_type": "D1_INCOMPLETE",
        "author_role_instance_id": CHECKER_ID,
        "go_id": GO_ID,
        "cell_id": CELL_ID,
        "attempt": 2,
        "corrects_event_id": None,
        "details_json": json.dumps({
            "candidate_message_id": CANDIDATE_MESSAGE_ID,
            "verdict": "INCOMPLETE",
        }, sort_keys=True),
    })
    projection["events"].insert(2, {
        "event_id": "management-transport-started",
        "event_type": "TRANSPORT_STARTED",
        "author_role_instance_id": SUPERVISOR_ID,
        "go_id": GO_ID,
        "cell_id": CELL_ID,
        "attempt": 1,
        "corrects_event_id": None,
        "details_json": json.dumps({
            "message_id": return_message_id,
            "endpoint_sha256": "c" * 64,
            "envelope_sha256": returned["payload_sha256"],
            "start_evidence_sha256": "d" * 64,
        }, sort_keys=True),
    })
    projection["runtime_snapshot"]["latest_message_id"] = return_message_id
    write_json(projection_path, projection)
    return module, request, request_path, source_incomplete_event_id


def test_management_return_failure_preserves_original_candidate_and_cross_attempt_lineage(
    tmp_path: Path,
) -> None:
    module, request, _request_path, source_incomplete_event_id = management_return_fixture(
        tmp_path
    )

    validated = module._validate_failure(request)

    assert validated["candidate"]["commit"] == CANDIDATE_COMMIT
    assert validated["event"]["corrects_event_id"] == source_incomplete_event_id


def test_management_return_cross_attempt_failure_completes_checker_escalation(
    tmp_path: Path,
) -> None:
    module, request, request_path, _source_event_id = management_return_fixture(tmp_path)
    operations: list[str] = []

    def run(_command, args, *, credential):
        operation = args[0]
        operations.append(operation)
        if operation == "authenticate-role":
            return {
                "status": "authenticated",
                "run_id": RUN_ID,
                "role": "checker",
                "role_instance_id": CHECKER_ID,
                "runtime_revision": request["runtime_revision"],
            }
        prepared = module.materialize_escalation(request)
        message_id = prepared["envelope"]["message_id"]
        if operation == "send":
            delivery = Path(prepared["delivery_path"])
            write_json(delivery / "endpoint.json", prepared["endpoint"])
            write_json(delivery / "envelope.json", prepared["envelope"])
            write_json(
                delivery / "started.json",
                make_native_start(
                    adapter="codex-app-server",
                    run_id=RUN_ID,
                    cell_id=CELL_ID,
                    message_id=message_id,
                    request_sha256=prepared["envelope"]["payload_sha256"],
                    native_request_sha256="f" * 64,
                    native_task_kind="codex-turn",
                    native_task_id="turn-management-fail",
                    native_task_status="RUNNING",
                    pid=os.getpid(),
                ),
            )
            return {"status": "started", "run_id": RUN_ID, "message_id": message_id}
        assert operation == "commit-delivery-start"
        return {
            "status": "committed",
            "run_id": RUN_ID,
            "runtime_revision": int(request["runtime_revision"]) + 1,
            "token_sequence": int(request["token_sequence"]) + 1,
            "token_owner_role_instance_id": SUPERVISOR_ID,
            "message_id": message_id,
        }

    result = module.execute_checker_escalation(
        request,
        request_sha256=sha256(request_path),
        request_path=request_path,
        run_json_command=run,
        unprotect_credential=lambda _: "synthetic",
    )

    assert result["status"] == "CHECKER_ESCALATION_COMMITTED"
    assert operations == ["authenticate-role", "send", "commit-delivery-start"]


@pytest.mark.parametrize(
    "tamper",
    [
        "source-attempt",
        "management-attempt",
        "source-cell",
        "source-role",
        "source-candidate",
        "candidate-payload-hash",
        "later-cross-attempt-terminal",
    ],
)
def test_management_return_cross_attempt_lineage_rejects_mismatched_identity(
    tmp_path: Path, tamper: str,
) -> None:
    module, request, _request_path, source_event_id = management_return_fixture(tmp_path)
    projection_path = Path(str(request["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    source = next(item for item in projection["events"] if item["event_id"] == source_event_id)
    if tamper == "source-attempt":
        source["attempt"] = 3
    elif tamper == "management-attempt":
        next(
            item for item in projection["events"]
            if item["event_id"] == "management-transport-started"
        )["attempt"] = 2
    elif tamper == "source-cell":
        source["cell_id"] = "CELL-other"
    elif tamper == "source-role":
        source["author_role_instance_id"] = "ROLE-other-checker"
    elif tamper == "source-candidate":
        source_details = json.loads(source["details_json"])
        source_details["candidate_message_id"] = "wrong-candidate-message"
        source["details_json"] = json.dumps(source_details, sort_keys=True)
    elif tamper == "candidate-payload-hash":
        envelope_path = Path(str(request["native_attempt_path"])) / "envelope.json"
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        envelope["payload"]["candidate_payload_sha256"] = "0" * 64
        envelope["payload_sha256"] = canonical_json_sha256(envelope["payload"])
        write_json(envelope_path, envelope)
    else:
        projection["events"].append({
            "event_id": "later-d1-terminal",
            "event_type": "D1_PASSED",
            "author_role_instance_id": CHECKER_ID,
            "go_id": GO_ID,
            "cell_id": CELL_ID,
            "attempt": 3,
            "corrects_event_id": None,
            "details_json": json.dumps({
                "candidate_message_id": "later-candidate-message",
                "verdict": "PASS",
            }, sort_keys=True),
        })
    write_json(projection_path, projection)

    with pytest.raises((module.CheckerEscalationError, ContractError)):
        module._validate_failure(request)


@pytest.mark.parametrize("version", ["4.4.0", "4.4.1", "4.4.2"])
def test_patch_failure_requires_exact_request_and_run_version(tmp_path, version):
    module = load_module()
    request, _ = fixture(tmp_path)
    request["method_version"] = version
    path = Path(request["runtime_projection_path"])
    projection = json.loads(path.read_text())
    projection["summary"]["slk_version"] = version
    projection["runtime_snapshot"]["method_version"] = version
    write_json(path, projection)
    assert module._validate_request(request)["method_version"] == version
    module._validate_failure(request)
    projection["summary"]["slk_version"] = "4.4.2" if version == "4.4.0" else "4.4.0"
    write_json(path, projection)
    with pytest.raises(module.CheckerEscalationError, match="runtime"):
        module._validate_failure(request)


@pytest.mark.parametrize("start_proof", [True, False])
def test_ordinary_supervisor_start_does_not_require_desktop_repair(tmp_path, start_proof):
    module = load_module()
    request, path = fixture(tmp_path)
    operations = []

    def run(_command, args, *, credential):
        operation = args[0]
        operations.append(operation)
        if operation == "authenticate-role":
            return {"status": "authenticated", "run_id": RUN_ID, "role": "checker",
                    "role_instance_id": CHECKER_ID, "runtime_revision": request["runtime_revision"]}
        prepared = module.materialize_escalation(request)
        message = prepared["envelope"]["message_id"]
        if operation == "send":
            native = Path(prepared["delivery_path"])
            write_json(native / "endpoint.json", prepared["endpoint"])
            write_json(native / "envelope.json", prepared["envelope"])
            if start_proof:
                write_json(native / "started.json", make_native_start(
                    adapter="codex-app-server", run_id=RUN_ID, cell_id=CELL_ID, message_id=message,
                    request_sha256=prepared["envelope"]["payload_sha256"], native_request_sha256="f" * 64,
                    native_task_kind="codex-turn", native_task_id="turn-normal", native_task_status="RUNNING",
                    pid=os.getpid(),
                ))
            return {"status": "started", "run_id": RUN_ID, "message_id": message}
        assert operation == "commit-delivery-start"
        assert credential is not None
        return {"status": "committed", "run_id": RUN_ID, "runtime_revision": request["runtime_revision"] + 1,
                "token_sequence": request["token_sequence"] + 1, "token_owner_role_instance_id": SUPERVISOR_ID,
                "message_id": message}

    if not start_proof:
        with pytest.raises(module.CheckerEscalationError):
            module.execute_checker_escalation(request, request_sha256=sha256(path), request_path=path,
                                              run_json_command=run, unprotect_credential=lambda _: "synthetic")
        assert "commit-delivery-start" not in operations
    else:
        result = module.execute_checker_escalation(request, request_sha256=sha256(path), request_path=path,
                                                  run_json_command=run, unprotect_credential=lambda _: "synthetic")
        assert result["status"] == "CHECKER_ESCALATION_COMMITTED"
        receipt = json.loads(Path(result["commit_request_path"]).with_suffix(".result.json").read_text())
        assert receipt["status"] == "committed" and receipt["run_id"] == RUN_ID
        assert result["recovery_message_id"] is None
        assert operations == ["authenticate-role", "send", "commit-delivery-start"]


@pytest.mark.parametrize("tamper", [None, "failure", "readback", "started"])
def test_late_desktop_start_commits_without_resending_or_rewriting_failure(
    tmp_path: Path, tamper: str | None,
) -> None:
    module = load_module()
    request, path = fixture(tmp_path)
    endpoint_path = Path(str(request["supervisor_endpoint_path"]))
    endpoint = json.loads(endpoint_path.read_text(encoding="utf-8"))
    desktop_endpoint(endpoint, tmp_path)
    write_json(endpoint_path, endpoint)
    prepared = module.materialize_escalation(request)
    attempt = Path(prepared["delivery_path"])
    failed_bytes = write_late_desktop_start(attempt, prepared["endpoint"], prepared["envelope"])
    if tamper == "failure":
        failure = json.loads((attempt / "failed.json").read_text(encoding="utf-8"))
        failure["error_code"] = "CODEX_RPC_TIMEOUT"
        write_json(attempt / "failed.json", failure)
        failed_bytes = (attempt / "failed.json").read_bytes()
    elif tamper == "readback":
        proof = json.loads((attempt / "desktop-readback.json").read_text(encoding="utf-8"))
        proof["message_id"] = "wrong-message"
        write_json(attempt / "desktop-readback.json", proof)
    elif tamper == "started":
        started = json.loads((attempt / "started.json").read_text(encoding="utf-8"))
        started["request_sha256"] = "0" * 64
        write_json(attempt / "started.json", started)
    operations: list[str] = []

    def run(_command, arguments, *, credential):
        operation = arguments[0]
        operations.append(operation)
        if operation == "authenticate-role":
            return {"status": "authenticated", "run_id": RUN_ID, "role": "checker",
                    "role_instance_id": CHECKER_ID, "runtime_revision": request["runtime_revision"]}
        if operation == "send":
            pytest.fail("a verified late Desktop start must never resend")
        assert operation == "commit-delivery-start" and credential == "synthetic"
        commit = json.loads(Path(arguments[-1]).read_text(encoding="utf-8"))
        return {"status": "committed", "run_id": RUN_ID,
                "runtime_revision": request["runtime_revision"] + 1,
                "token_sequence": request["token_sequence"] + 1,
                "token_owner_role_instance_id": SUPERVISOR_ID,
                "message_id": commit["message_id"]}

    if tamper is None:
        result = module.execute_checker_escalation(
            request, request_sha256=sha256(path), request_path=path,
            run_json_command=run, unprotect_credential=lambda _: "synthetic",
        )
        assert result["status"] == "CHECKER_ESCALATION_COMMITTED"
        assert operations == ["authenticate-role", "commit-delivery-start"]
    else:
        with pytest.raises(module.CheckerEscalationError, match="late Desktop"):
            module.execute_checker_escalation(
                request, request_sha256=sha256(path), request_path=path,
                run_json_command=run, unprotect_credential=lambda _: "synthetic",
            )
        assert operations == ["authenticate-role"]
    assert (attempt / "failed.json").read_bytes() == failed_bytes
    assert not (attempt / "completed.json").exists()


def request_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("damage", [None, "authentication", "missing-start", "changed-endpoint", "prior-send"])
def test_pre_send_host_failure_uses_exact_retry_and_authenticated_checker_commit(tmp_path, damage):
    module = load_module()
    request, path = fixture(tmp_path)
    endpoint_path = Path(request["supervisor_endpoint_path"])
    endpoint = json.loads(endpoint_path.read_text())
    desktop_endpoint(endpoint, tmp_path)
    write_json(endpoint_path, endpoint)
    prepared = module.materialize_escalation(request)
    native = Path(prepared["delivery_path"])
    write_json(native / "endpoint.json", prepared["endpoint"])
    write_json(native / "envelope.json", prepared["envelope"])
    write_json(native / "accepted.json", {"status": "accepted", "run_id": RUN_ID,
                                         "message_id": prepared["envelope"]["message_id"]})
    write_json(native / "failed.json", {
        "schema_version": "slk.transport-result/v1", "status": "failed", "adapter": "codex-app-server",
        "run_id": RUN_ID, "message_id": prepared["envelope"]["message_id"], "native_identity": {},
        "error_code": "CODEX_DESKTOP_HOST_UNAVAILABLE", "evidence": ["accepted.json", "endpoint.json", "envelope.json"],
    })
    failed_bytes = (native / "failed.json").read_bytes()
    if damage == "prior-send":
        write_json(native / "desktop-send.json", {"result": {"threadId": "thread-supervisor"}})
    calls = []
    def run(_command, args, *, credential):
        calls.append(args[0])
        if args[0] == "authenticate-role":
            return {"status": "authenticated", "run_id": RUN_ID, "role": "worker" if damage == "authentication" else "checker",
                    "role_instance_id": CHECKER_ID, "runtime_revision": request["runtime_revision"]}
        if args[0] == "send":
            retry_root = Path(args[args.index("--attempt-root") + 1])
            assert retry_root == native / "recovery" / "exact-1"
            retry = retry_root / RUN_ID / prepared["envelope"]["message_id"]
            write_json(retry / "endpoint.json", {} if damage == "changed-endpoint" else prepared["endpoint"])
            write_json(retry / "envelope.json", prepared["envelope"])
            if damage != "missing-start":
                write_json(retry / "started.json", make_native_start(
                    adapter="codex-app-server", run_id=RUN_ID, cell_id=CELL_ID,
                    message_id=prepared["envelope"]["message_id"], request_sha256=prepared["envelope"]["payload_sha256"],
                    native_request_sha256="f" * 64, native_task_kind="codex-desktop-turn",
                    native_task_id="thread-supervisor:turn-a:item-a", native_task_status="RUNNING", pid=os.getpid(),
                ))
            return {"status": "started", "run_id": RUN_ID, "message_id": prepared["envelope"]["message_id"]}
        assert args[0] == "commit-delivery-start" and credential == "synthetic"
        return {"status": "committed", "run_id": RUN_ID, "runtime_revision": request["runtime_revision"] + 1,
                "token_sequence": request["token_sequence"] + 1, "token_owner_role_instance_id": SUPERVISOR_ID,
                "message_id": prepared["envelope"]["message_id"]}
    if damage is not None:
        with pytest.raises(module.CheckerEscalationError):
            module.execute_checker_escalation(request, request_sha256=sha256(path), request_path=path,
                                             run_json_command=run, unprotect_credential=lambda _: "synthetic")
        assert "commit-delivery-start" not in calls
    else:
        result = module.execute_checker_escalation(request, request_sha256=sha256(path), request_path=path,
                                                  run_json_command=run, unprotect_credential=lambda _: "synthetic")
        assert result["status"] == "CHECKER_ESCALATION_COMMITTED"
        assert calls == ["authenticate-role", "send", "commit-delivery-start"]
    assert (native / "failed.json").read_bytes() == failed_bytes


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


def test_prepare_routes_matching_metadata_timeouts_to_desktop_validation(
    tmp_path: Path,
) -> None:
    module = load_module()
    request, request_path = fixture(tmp_path)
    calls: list[str] = []

    def run(_command: list[str], arguments: list[str], *, credential: str | None):
        operation = arguments[0]
        calls.append(operation)
        if operation == "authenticate-role":
            return {
                "status": "authenticated",
                "run_id": RUN_ID,
                "role": "checker",
                "role_instance_id": CHECKER_ID,
                "runtime_revision": 25,
            }
        if operation == "send":
            return {"status": "failed", "error_code": "CODEX_RPC_TIMEOUT"}
        if operation == "retry-exact":
            return {
                "status": "SUPERVISOR_DECISION_REQUIRED",
                "reason": "EXACT_RETRY_EXHAUSTED",
                "result": {"error_code": "CODEX_RPC_TIMEOUT"},
            }
        assert operation == "prepare-desktop-current-turn"
        return {
            "schema_version": "slk.transport-desktop-current-turn-request/v1",
            "status": "PREPARED",
            "run_id": RUN_ID,
            "go_id": GO_ID,
            "cell_id": CELL_ID,
            "original_message_id": module.escalation_message_id(request),
            "recovery_message_id": "desktop-recovery-timeout",
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
    assert calls == [
        "authenticate-role",
        "send",
        "retry-exact",
        "prepare-desktop-current-turn",
    ]


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


def test_fresh_runtime_request_reuses_the_same_escalation_identity_and_bytes(
    tmp_path: Path,
) -> None:
    module = load_module()
    request, _request_path = fixture(tmp_path)
    first = module.materialize_escalation(request)
    first_endpoint = Path(first["endpoint_path"]).read_bytes()
    first_envelope = Path(first["envelope_path"]).read_bytes()

    projection_path = Path(str(request["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    projection["events"].append(
        {
            "event_id": "overwatcher-turn-resumed-current",
            "event_type": "OVERWATCHER_TURN_RESUMED",
            "author_role_instance_id": SUPERVISOR_ID,
            "details_json": "{}",
        }
    )
    projection["runtime_snapshot"]["runtime_revision"] = 26
    projection["runtime_snapshot"]["latest_event_id"] = "overwatcher-turn-resumed-current"
    refreshed_projection = write_json(tmp_path / "runtime-current.json", projection)
    refreshed = dict(request)
    refreshed["runtime_revision"] = 26
    refreshed["runtime_projection_path"] = str(refreshed_projection.resolve())
    refreshed["occurred_at"] = "2026-10-01T02:00:00Z"

    second = module.materialize_escalation(refreshed)

    assert second["envelope"]["message_id"] == first["envelope"]["message_id"]
    assert second["envelope"]["payload_sha256"] == first["envelope"]["payload_sha256"]
    assert second["delivery_path"] == first["delivery_path"]
    assert Path(second["endpoint_path"]).read_bytes() == first_endpoint
    assert Path(second["envelope_path"]).read_bytes() == first_envelope


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
