from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from slk_transport import checker_management as management
from slk_transport.native_activity import make_native_start
from test_checker_escalation import (
    CANDIDATE_MESSAGE_ID,
    CELL_ID,
    CHECKER_ID,
    GO_ID,
    RUN_ID,
    SUPERVISOR_ID,
    fixture as failure_fixture,
    sha256,
    write_json,
)


INCOMPLETE_EVENT_ID = "d1-incomplete-current"


def fixture(tmp_path: Path) -> tuple[dict[str, object], Path]:
    old, _ = failure_fixture(tmp_path)
    native = Path(str(old["native_attempt_path"]))
    result_path = native / "ocrv-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result.update(verdict="INCOMPLETE", reason_codes=["OCR_STATUS_NOT_COMPLETE"])
    write_json(result_path, result)
    terminal_path = native / "completed.json"
    terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
    terminal["native_identity"].update(verdict="INCOMPLETE", exit_code=3)
    write_json(terminal_path, terminal)
    projection_path = Path(str(old["runtime_projection_path"]))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    details = json.loads(projection["events"][0]["details_json"])
    details.update(
        verdict="INCOMPLETE",
        reason_codes=["OCR_STATUS_NOT_COMPLETE"],
        native_result_sha256=sha256(result_path),
        native_terminal_sha256=sha256(terminal_path),
    )
    projection["events"][0].update(
        event_id=INCOMPLETE_EVENT_ID,
        event_type="D1_INCOMPLETE",
        details_json=json.dumps(details, sort_keys=True),
    )
    projection["runtime_snapshot"]["latest_event_id"] = INCOMPLETE_EVENT_ID
    write_json(projection_path, projection)
    request = {
        "schema_version": management.REQUEST_SCHEMA,
        "method_version": old["method_version"],
        "management_invocation_id": "management-001",
        "run_id": RUN_ID,
        "go_id": GO_ID,
        "cell_id": CELL_ID,
        "attempt": 1,
        "plan_revision": 1,
        "runtime_revision": 25,
        "token_sequence": 4,
        "checker_role_instance_id": CHECKER_ID,
        "d1_incomplete_event_id": INCOMPLETE_EVENT_ID,
        "runtime_projection_path": old["runtime_projection_path"],
        "native_attempt_path": old["native_attempt_path"],
        "supervisor_endpoint_path": old["supervisor_endpoint_path"],
        "checker_credential_path": old["checker_credential_path"],
        "state_command": old["state_command"],
        "transport_command": old["transport_command"],
        "escalation_attempt_root": old["escalation_attempt_root"],
        "reason_codes": ["OCR_STATUS_NOT_COMPLETE"],
        "evidence_refs": [str(result_path.resolve()), str(terminal_path.resolve())],
        "occurred_at": old["occurred_at"],
    }
    path = write_json(tmp_path / "checker-management.json", request)
    return request, path


def test_current_incomplete_can_transfer_management_without_d1_fail_or_rework(
    tmp_path: Path,
) -> None:
    request, path = fixture(tmp_path)

    def run(_command, arguments, *, credential):
        operation = arguments[0]
        if operation == "authenticate-role":
            return {"status": "authenticated", "run_id": RUN_ID, "role": "checker",
                    "role_instance_id": CHECKER_ID, "runtime_revision": 25}
        prepared = management.materialize_management_escalation(request)
        message_id = prepared["envelope"]["message_id"]
        if operation == "send":
            native = Path(prepared["delivery_path"])
            write_json(native / "endpoint.json", prepared["endpoint"])
            write_json(native / "envelope.json", prepared["envelope"])
            write_json(native / "started.json", make_native_start(
                adapter="codex-app-server", run_id=RUN_ID, cell_id=CELL_ID,
                message_id=message_id, request_sha256=prepared["envelope"]["payload_sha256"],
                native_request_sha256="f" * 64, native_task_kind="codex-turn",
                native_task_id="turn-management", native_task_status="RUNNING", pid=os.getpid(),
            ))
            return {"status": "started", "run_id": RUN_ID, "message_id": message_id}
        assert operation == "commit-delivery-start"
        assert credential == "checker-secret"
        return {"status": "committed", "run_id": RUN_ID, "runtime_revision": 26,
                "token_sequence": 5, "token_owner_role_instance_id": SUPERVISOR_ID,
                "message_id": message_id}

    result = management.execute_checker_management(
        request, request_sha256=sha256(path), request_path=path,
        run_json_command=run, unprotect_credential=lambda _path: "checker-secret",
    )

    assert result["status"] == "CHECKER_INCOMPLETE_ESCALATION_COMMITTED"
    prepared = management.materialize_management_escalation(request)
    assert prepared["envelope"]["payload_type"] == "D1_INCOMPLETE_ESCALATION"
    assert "rework_round" not in prepared["envelope"]["payload"]
    assert "findings" not in prepared["envelope"]["payload"]
    schema = json.loads((Path(__file__).parents[2] / "docs/contracts/slk-checker-management.schema.json").read_text())
    Draft202012Validator(schema).validate(request)


@pytest.mark.parametrize("damage", ["stale-event", "changed-reason", "changed-result"])
def test_incomplete_management_fails_closed_on_drift(tmp_path: Path, damage: str) -> None:
    request, _ = fixture(tmp_path)
    if damage == "stale-event":
        projection_path = Path(str(request["runtime_projection_path"]))
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        projection["events"].append({**projection["events"][0], "event_id": "later",
                                     "event_type": "D1_PASSED"})
        write_json(projection_path, projection)
    elif damage == "changed-reason":
        request["reason_codes"] = ["OTHER"]
    else:
        result_path = Path(str(request["native_attempt_path"])) / "ocrv-result.json"
        value = json.loads(result_path.read_text(encoding="utf-8"))
        value["verdict"] = "PASS"
        write_json(result_path, value)

    with pytest.raises(management.CheckerEscalationError):
        management.materialize_management_escalation(request)
